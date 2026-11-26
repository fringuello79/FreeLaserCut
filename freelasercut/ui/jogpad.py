# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Comandi di movimento della testa (0.19.5), uguali nella scheda Movimento e in Stampa e taglia.

- Frecce: croce 3 × 3 con 8 frecce (passo scelto nella fila sotto, «Continuo» = finché tieni premuto) e al centro
  Puntino (tieni premuto) e Lucciola (resta accesa): sono gli stessi comandi della scheda Laser (stessa potenza,
  stessi avvisi, stesso spegnimento automatico).
- Joystick: manopola da trascinare, direzione libera e velocità proporzionale alla distanza dal centro fino alla
  «Velocità jog»; al rilascio la testa si ferma. Sulla scheda è il «jog a bassa latenza» di GRBL: pezzetti corti
  ($J=G91) mandati di continuo, al massimo MAX_Q in attesa, e al rilascio l'arresto del jog (0x85).
"""
import math
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

STEPS = (0.1, 1, 10, 50, 100)
TAG = "joy"


def rotary_sign(ctl):
    """0.23.3: -1 se il rotativo è al posto della Y con «Inverti il senso di rotazione»: un comando in su fa scendere la
    Y della macchina (ctl.jog), così il pezzo gira nel verso del disegno. 1 altrimenti."""
    return -1.0 if getattr(ctl, "rotary_y", False) and getattr(ctl, "rotary_sign", 1.0) < 0 else 1.0


# ======================================================================= joystick: la logica (senza finestra)
class JoyJog(QObject):
    """Movimento continuo dal joystick. set_vector(ux, uy): vettore nel cerchio unitario (y verso l'alto del piano,
    lunghezza 0…1).

    0.21.1 (leone2805 su GitHub e Ale: «il cambio di direzione non è immediato, anche qualche secondo»): GRBL risponde
    «ok» a un jog appena lo mette nella sua coda dei movimenti, non quando l'ha percorso. Fino alla 0.21.0 ogni 25 ms
    partiva un pezzetto da 60 ms se c'erano meno di 2 righe senza «ok»: quasi sempre, quindi ogni secondo arrivavano
    circa 2,4 secondi di movimento e la coda della scheda si riempiva (fino a 7 s di ritardo con i 127 posti del Falcon
    A1). Ora i pezzetti partono al ritmo del tempo vero: davanti alla testa resta solo il movimento di `lead()` secondi
    (un decimo di secondo, di più solo se l'accelerazione della macchina lo chiede per arrivare alla velocità), e in più
    si controlla dove è davvero la testa: se il movimento mandato è troppo avanti rispetto a lei, si aspetta."""
    DEAD = 0.08  # zona morta al centro
    SEG_T = 0.05  # durata di un pezzetto (s)
    MAX_Q = 2  # pezzetti al massimo senza «ok» della scheda
    TICK_MS = 20
    MARGIN = 0.5  # mm dal bordo dell'area
    LEAD_MIN = 0.10  # s di movimento al massimo davanti alla testa (di solito)
    LEAD_MAX = 0.40  # s: tetto anche per le macchine con accelerazione molto bassa
    LEAD_K40 = 0.20  # s, 0.23.3: anticipo minimo sulla K40 (vedi lead)
    POS_SLACK = 0.30  # s: ritardo della posizione letta (lo stato arriva ogni 0,2 s) per il controllo sulla testa
    SETTLE = 0.35  # s dopo la fine prevista: la posizione letta è quella vera e si riparte da lì

    def __init__(self, ctl, get_profile, get_head, get_feed, parent=None, clock=None):
        super().__init__(parent)
        self.ctl, self.get_profile, self.get_head, self.get_feed = ctl, get_profile, get_head, get_feed
        self.clock = clock or time.monotonic
        self.active = False
        self.vec = (0.0, 0.0)
        self.pos = None  # posizione pianificata sul piano (testa + pezzetti già mandati)
        self.sent = 0  # pezzetti mandati da quando è attivo
        self.plan_end = 0.0  # quando la scheda avrà finito i pezzetti mandati (stima, orologio self.clock)
        self.stop_reason = ""
        self._t = QTimer(self)
        self._t.setInterval(self.TICK_MS)
        self._t.timeout.connect(self.tick)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)

    def _app_state(self, st):
        if st != Qt.ApplicationActive:
            self.stop(tr("FreeLaserCut non è più in primo piano"))

    def can_move(self):
        c = self.ctl
        return (bool(c.connected) and not c.job_active and not getattr(c, "checking", False)
                and c.last_status.get("state") not in ("Alarm", "Door", "Hold", "Sleep"))

    def start(self):
        if not self.can_move():
            self.stop_reason = tr("Macchina non pronta: collegala, sbloccala o aspetta la fine del lavoro")
            return False
        head = self.get_head()
        if head is None:
            self.stop_reason = tr("Posizione della testa non ancora nota")
            return False
        self.pos = (float(head.x()), float(head.y()))
        self.active = True
        self.sent = 0
        self.plan_end = self.clock()
        self.stop_reason = ""
        self._t.start()
        return True

    def set_vector(self, ux, uy):
        m = math.hypot(ux, uy)
        if m > 1.0:
            ux, uy = ux / m, uy / m
        self.vec = (float(ux), float(uy))

    def magnitude(self):
        return math.hypot(*self.vec)

    def speed(self):
        """Velocità chiesta (mm/min) per il vettore attuale: 0 nella zona morta."""
        m = self.magnitude()
        if m <= self.DEAD:
            return 0.0
        return (m - self.DEAD) / (1.0 - self.DEAD) * float(self.get_feed())

    def angle(self):
        return (math.degrees(math.atan2(self.vec[1], self.vec[0])) + 360.0) % 360.0

    def accel(self):
        """Accelerazione della macchina (mm/s²): la più bassa dei due assi, dal profilo ($120/$121)."""
        prof = self.get_profile()
        vals = []
        for k in ("accel_x", "accel_y"):
            try:
                v = float(getattr(prof, k, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0 and math.isfinite(v):
                vals.append(v)
        return min(vals) if vals else 500.0

    def lead(self, v=None):
        """Secondi di movimento da tenere davanti alla testa alla velocità v (mm/min). La scheda deve poter frenare
        entro il movimento che ha in coda: per arrivare a v servono almeno v²/(2a) mm, cioè v/(2a) secondi."""
        v = self.speed() if v is None else v
        need = 1.2 * (v / 60.0) / (2.0 * self.accel()) + self.SEG_T  # + un pezzetto: si manda a metà pezzetto
        # 0.23.3: sulla K40 i pezzetti diventano un movimento continuo nel ponte; un po' più di anticipo evita che la
        # scheda resti senza comandi fra un pezzetto e l'altro (al rilascio il ponte butta quelli non ancora mandati)
        lo = self.LEAD_K40 if getattr(self.ctl, "port", None) == "K40" else self.LEAD_MIN
        return min(self.LEAD_MAX, max(lo, need))

    def _head(self):
        h = self.get_head()
        return None if h is None else (float(h.x()), float(h.y()))

    def tick(self):
        if not self.active:
            return
        if not self.can_move():
            self.stop(tr("Joystick fermato: la macchina non è più pronta"))
            return
        now = self.clock()
        idle_q = self.ctl.queued(TAG) == 0
        if idle_q and now > self.plan_end + self.SETTLE:
            head = self._head()  # tutto finito da un po': si riparte dalla posizione vera, non da quella stimata
            if head is not None:
                self.pos = head
        v = self.speed()
        if v <= 0 or self.ctl.queued(TAG) >= self.MAX_Q:
            return
        lead = self.lead(v)
        if self.plan_end - now > lead - self.SEG_T / 2:
            return  # davanti alla testa c'è già abbastanza movimento
        head = self._head()
        if head is not None and self.pos is not None:
            behind = math.dist(head, self.pos)  # quanto il movimento mandato è avanti rispetto alla testa vera
            if behind > v / 60.0 * (lead + self.POS_SLACK) + 1.0:
                return
        m = self.magnitude()
        seg = self.SEG_T
        d = v / 60.0 * seg
        # 0.23.3: rotativo con il senso invertito: la testa (asse del rotativo) va al contrario del comando; si conta
        # dove va davvero, per i bordi e per il controllo sulla posizione letta
        s = rotary_sign(self.ctl)
        dx, dy = self.vec[0] / m * d, self.vec[1] / m * d * s
        x0, y0, x1, y1 = reach_box(self.ctl, self.get_profile())
        x, y = self.pos
        nx, ny = self._limit(x, dx, x0, x1), self._limit(y, dy, y0, y1)
        ddx, ddy = nx - x, ny - y
        dist = math.hypot(ddx, ddy)
        if dist < 0.005:
            return  # al bordo: fermo finché non cambi direzione
        self.ctl.jog(ddx, ddy * s, v, tag=TAG)
        self.pos = (nx, ny)
        self.plan_end = max(self.plan_end, now) + dist / (v / 60.0)
        self.sent += 1

    def _limit(self, p, d, lo, hi=None):
        """Nuova coordinata su un asse fra lo e hi (con un solo numero: da 0 a quella misura): si ferma a MARGIN dal
        bordo verso cui si va, e non si muove mai nel verso opposto a quello chiesto (con la testa già oltre il
        margine resta dov'è)."""
        if hi is None:
            lo, hi = 0.0, lo
        if hi - lo <= 2 * self.MARGIN or d == 0:
            return p + d if hi - lo <= 2 * self.MARGIN else p
        if d > 0:
            return min(p + d, max(p, hi - self.MARGIN))
        return max(p + d, min(p, lo + self.MARGIN))

    def stop(self, reason=""):
        was = self.active
        self.active = False
        self._t.stop()
        self.vec = (0.0, 0.0)
        if reason:
            self.stop_reason = reason
        if was and self.ctl.connected:
            self.ctl.jog_cancel(tag=TAG)
        return was


# ======================================================================= joystick: il disegno
class JoystickPad(QWidget):
    """Cerchio con anello graduato e manopola. Tieni premuto e trascina; al rilascio la manopola torna al centro."""
    SIZE = 180

    def __init__(self, joy, on_change=None, parent=None):
        super().__init__(parent)
        self.joy = joy
        self.on_change = on_change
        self.knob = QPointF(0, 0)  # in unità del raggio utile, y verso l'alto
        self.pressed = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(tr("Joystick: tieni premuto e trascina. La testa va nella direzione della manopola, più "
                           "veloce più la allontani dal centro (fino alla «Velocità jog»); al rilascio si ferma. "
                           "Si ferma anche con Esc, se il mouse esce dalla finestra o se cambi programma."))

    def _geo(self):
        c = QPointF(self.width() / 2, self.height() / 2)
        r_out = min(self.width(), self.height()) / 2 - 6
        return c, r_out, r_out * 0.71  # centro, bordo, raggio utile della manopola

    def _set_from(self, pos):
        c, _, r = self._geo()
        x, y = (pos.x() - c.x()) / r, -(pos.y() - c.y()) / r
        m = math.hypot(x, y)
        if m > 1:
            x, y = x / m, y / m
        self.knob = QPointF(x, y)
        self.joy.set_vector(x, y)
        self.update()
        if self.on_change:
            self.on_change()

    def _release(self, reason=""):
        if not self.pressed and not self.joy.active:
            return
        self.pressed = False
        self.knob = QPointF(0, 0)
        self.joy.stop(reason)
        self.setCursor(Qt.OpenHandCursor)
        self.update()
        if self.on_change:
            self.on_change()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.isEnabled():
            return
        self.setFocus()
        self.pressed = True
        self.setCursor(Qt.ClosedHandCursor)
        self._set_from(e.position())
        if not self.joy.start():
            self.pressed = False
            self.knob = QPointF(0, 0)
            self.joy.set_vector(0, 0)
            self.update()
            if self.on_change:
                self.on_change()

    def mouseMoveEvent(self, e):
        if self.pressed:
            self._set_from(e.position())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._release()

    def focusOutEvent(self, e):
        self._release(tr("Joystick fermato"))
        super().focusOutEvent(e)

    def hideEvent(self, e):
        self._release()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._release(tr("Joystick fermato con Esc"))
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if not self.isEnabled():
            self._release()

    def paintEvent(self, _e):
        c, ro, r = self._geo()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        en = self.isEnabled()
        line = QColor(C["border"])
        p.setPen(QPen(line, 1))
        p.setBrush(QColor(C["panel2"]))
        p.drawEllipse(c, ro, ro)
        for a in range(0, 360, 15):  # anello graduato: tacche ogni 15°, più lunghe ogni 45°
            L = 9 if a % 45 == 0 else 4
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            p.setPen(QPen(QColor(C["muted"]), 1.2 if a % 45 == 0 else 1))
            p.drawLine(QPointF(c.x() + ca * ro, c.y() + sa * ro), QPointF(c.x() + ca * (ro - L), c.y() + sa * (ro - L)))
        p.setBrush(Qt.NoBrush)
        dash = QPen(line, 1, Qt.DashLine)
        p.setPen(dash)
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.56, r * 0.56)
        p.setPen(QPen(line, 1))
        p.drawEllipse(c, r * self.joy.DEAD + 3, r * self.joy.DEAD + 3)
        p.setPen(QColor(C["muted"]))
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        for txt, x, y in (("Y+", c.x(), c.y() - ro + 20), ("Y−", c.x(), c.y() + ro - 12), ("X−", c.x() - ro + 18, c.y() + 4),
                          ("X+", c.x() + ro - 18, c.y() + 4)):
            p.drawText(QRectF(x - 14, y - 8, 28, 14), Qt.AlignCenter, txt)
        k = QPointF(c.x() + self.knob.x() * r, c.y() - self.knob.y() * r)
        if self.pressed:
            p.setPen(QPen(QColor(C["accent_hi"]), 2.5))
            p.drawLine(c, k)
        p.setPen(QPen(QColor(C["accent_hi"] if self.pressed else C["border"]), 1.5))
        p.setBrush(QColor(C["panel"]) if en else QColor(C["panel2"]))
        p.drawEllipse(k, 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["accent_hi"] if self.pressed else C["muted"]))
        p.drawEllipse(k, 5, 5)
        p.end()


# ======================================================================= il componente completo
def reach_box(ctl, prof):
    """0.21.2 (rapporto 3802): dove la testa può andare davvero, nel piano come si vede (x0, y0, x1, y1): il piano
    del profilo, ristretto alla corsa che la scheda accetta quando ha i limiti software accesi. Prima si guardava solo
    il piano del profilo: con un profilo di 600 mm e una scheda da 450 «Continuo» chiedeva X599,5 e la scheda
    rispondeva error:15 a ogni clic, senza che comparisse niente."""
    get = getattr(ctl, "soft_limits", None)
    lim = get() if callable(get) and getattr(ctl, "connected", False) else None
    try:
        return prof.reach_box(lim, getattr(ctl, "negative_space", None))
    except (AttributeError, TypeError, ValueError):
        return (0.0, 0.0, float(getattr(prof, "bed_x", 0) or 0), float(getattr(prof, "bed_y", 0) or 0))


class JogPad(QWidget):
    """Frecce o joystick, Puntino e Lucciola, passi e «Continuo». get_feed() = velocità del jog (mm/min)."""
    # senza margine interno: nei mezzi pulsanti stretti (25 px) il margine del tema schiaccerebbe l'icona
    _BTN_CSS = "QToolButton { padding: 0px; }"
    _GLOW_ON_CSS = "QToolButton { padding: 0px; background:#FFD43B; border:1px solid #B8860B; border-radius:6px; }"
    travel_fix_requested = Signal(float, float)  # 0.21.2: «Usa le misure della macchina» (corsa X, corsa Y)

    def __init__(self, ctl, settings, get_profile, get_head, get_feed, parent=None):
        super().__init__(parent)
        self.ctl, self.qs = ctl, settings
        self.get_profile, self.get_head, self.get_feed = get_profile, get_head, get_feed
        self.laser = None
        self._cont = False
        self._jog_sent = -1e9  # 0.21.2: quando la croce ha mandato l'ultimo spostamento (per l'error:15)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        # Puntino e Lucciola (si spostano fra le due pagine)
        self.b_dot = QToolButton()
        self.b_dot.setIcon(style.icon("dot", "#FF6B6B", 20))
        self.b_dot.setToolTip(tr("Puntino: tieni premuto per accendere il laser alla potenza del puntino (scheda Laser)"))
        self.b_dot.pressed.connect(lambda: self._dot(True))
        self.b_dot.released.connect(lambda: self._dot(False))
        self.b_glow = QToolButton()
        self.b_glow.setCheckable(True)
        self.b_glow.setIcon(style.icon("glow", "#FFD43B", 20, active="#3A2A00"))
        self.b_glow.clicked.connect(self._glow_clicked)
        self._glow_tip()
        # pagina 1: frecce
        self.stack = QStackedWidget()
        self.page_arrows = QWidget()
        grid = QGridLayout(self.page_arrows)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)
        arrows = [("arrow_ul", -1, 1), ("arrow_up", 0, 1), ("arrow_ur", 1, 1), ("arrow_left", -1, 0), None,
                  ("arrow_right", 1, 0), ("arrow_dl", -1, -1), ("arrow_down", 0, -1), ("arrow_dr", 1, -1)]
        self.jog_buttons = []
        for i, a in enumerate(arrows):
            r, c = divmod(i, 3)
            if a is None:
                self.center = QWidget()
                self.center.setFixedSize(52, 44)
                self.center_l = QHBoxLayout(self.center)
                self.center_l.setContentsMargins(0, 0, 0, 0)
                self.center_l.setSpacing(2)
                grid.addWidget(self.center, r, c)
                continue
            name, dx, dy = a
            b = QToolButton()
            b.setFixedSize(52, 44)
            b.setIcon(style.icon(name, size=22))
            b.setIconSize(b.size() * 0.45)
            b.pressed.connect(lambda dx=dx, dy=dy: self.jog_press(dx, dy))
            b.released.connect(self.jog_release)
            grid.addWidget(b, r, c)
            self.jog_buttons.append(b)
        self.stack.addWidget(self.page_arrows)
        # pagina 2: joystick
        self.page_joy = QWidget()
        jl = QVBoxLayout(self.page_joy)
        jl.setContentsMargins(0, 0, 0, 0)
        jl.setSpacing(4)
        self.joy = JoyJog(ctl, get_profile, get_head, get_feed, self)
        self.pad = JoystickPad(self.joy, self._readout)
        jl.addWidget(self.pad, 0, Qt.AlignHCenter)
        self.joy_row = QHBoxLayout()
        self.joy_row.setSpacing(6)
        self.joy_row.addStretch(1)
        self.joy_row.addStretch(1)
        jl.addLayout(self.joy_row)
        self.stack.addWidget(self.page_joy)
        v.addWidget(self.stack, 0, Qt.AlignLeft)
        # interruttore Frecce | Joystick e lettura
        mode = QHBoxLayout()
        mode.setSpacing(0)
        self.b_arrows = QToolButton()
        self.b_arrows.setText(tr("Frecce"))
        self.b_arrows.setIcon(style.icon("move", size=16))
        self.b_joy = QToolButton()
        self.b_joy.setText(tr("Joystick"))
        self.b_joy.setIcon(style.icon("joystick", size=16))
        self.mode_group = QButtonGroup(self)
        for b in (self.b_arrows, self.b_joy):
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setMinimumHeight(26)
            self.mode_group.addButton(b)
            mode.addWidget(b)
        self.b_arrows.setToolTip(tr("Frecce: la testa si sposta del passo scelto (o finché tieni premuto, con «Continuo»)"))
        self.b_joy.setToolTip(tr("Joystick: movimento continuo in qualsiasi direzione, finché tieni premuto"))
        self.readout = QLabel("")
        self.readout.setObjectName("muted")
        mode.addSpacing(10)
        mode.addWidget(self.readout, 1)
        v.addLayout(mode)
        # 0.21.2: la scheda ha rifiutato lo spostamento e si può correggere il profilo (rapporto 3802)
        self.refusal = QWidget()
        rv = QVBoxLayout(self.refusal)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(3)
        self.refusal_lab = QLabel("")
        self.refusal_lab.setWordWrap(True)
        rv.addWidget(self.refusal_lab)
        self.b_fix = QPushButton(tr("Usa le misure della macchina"))
        self.b_fix.setToolTip(tr("Il piano del profilo prende la corsa letta dalla scheda ($130/$131)"))
        self.b_fix.clicked.connect(self._use_board_travel)
        rv.addWidget(self.b_fix, 0, Qt.AlignLeft)
        self.refusal.setVisible(False)
        v.addWidget(self.refusal)
        ctl.error_raised.connect(self._board_error)
        # passi e Continuo
        self.steps_w = QWidget()
        sv = QVBoxLayout(self.steps_w)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(3)
        sv.addWidget(QLabel(tr("Passo (mm)")))
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.steps = []
        try:
            saved = float(self.qs.value("jog_step", 10))
        except (TypeError, ValueError):
            saved = 10.0
        for s in STEPS:
            b = QToolButton()
            b.setText(f"{s:g}")
            b.setCheckable(True)
            b.setChecked(abs(s - saved) < 1e-9)
            b.setMinimumWidth(40)
            b.clicked.connect(lambda _=False, s=s, b=b: self._step(s, b))
            seg.addWidget(b)
            self.steps.append((s, b))
        if not any(b.isChecked() for _, b in self.steps):
            self.steps[2][1].setChecked(True)
        self.cont = QCheckBox(tr("Continuo"))
        self.cont.setToolTip(tr("Tieni premuta una freccia: la testa si muove finché non la rilasci"))
        self.cont.setChecked(self.qs.value("jog_cont", "false") == "true")
        self.cont.toggled.connect(lambda x: self.qs.setValue("jog_cont", "true" if x else "false"))
        seg.addWidget(self.cont)
        seg.addStretch(1)
        sv.addLayout(seg)
        v.addWidget(self.steps_w)
        joy_mode = self.qs.value("jog_mode", "arrows") == "joystick"
        (self.b_joy if joy_mode else self.b_arrows).setChecked(True)
        self.mode_group.buttonClicked.connect(lambda b: self.set_mode("joystick" if b is self.b_joy else "arrows"))
        self.set_mode("joystick" if joy_mode else "arrows", save=False)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(250)
        self._sync_timer.timeout.connect(self._sync)
        self._sync_timer.start()
        self.set_connected(False)

    # ---- modalità
    def mode(self):
        return "joystick" if self.stack.currentWidget() is self.page_joy else "arrows"

    def set_mode(self, m, save=True):
        joy = m == "joystick"
        self.joy.stop()
        for b in (self.b_dot, self.b_glow):
            b.setParent(None)
        if joy:
            for b in (self.b_dot, self.b_glow):
                b.setFixedSize(44, 30)
            self.joy_row.insertWidget(1, self.b_dot)
            self.joy_row.insertWidget(2, self.b_glow)
            self.stack.setCurrentWidget(self.page_joy)
        else:
            for b in (self.b_dot, self.b_glow):
                b.setFixedSize(25, 44)
            self.center_l.addWidget(self.b_dot)
            self.center_l.addWidget(self.b_glow)
            self.stack.setCurrentWidget(self.page_arrows)
        for b in (self.b_dot, self.b_glow):
            b.setIconSize(QSize(18, 18))
            b.show()
        self.b_dot.setStyleSheet(self._BTN_CSS)
        self._sync()
        self.steps_w.setVisible(not joy)
        (self.b_joy if joy else self.b_arrows).setChecked(True)
        if save:
            self.qs.setValue("jog_mode", "joystick" if joy else "arrows")
        self._readout()

    def _readout(self):
        if self.mode() != "joystick":
            self.readout.setText("")
            return
        if self.pad.pressed and self.joy.active:
            v = self.joy.speed()
            self.readout.setText(tr("Zona morta") if v <= 0 else tr("{0:.0f} mm/min · {1:.0f}°", v, self.joy.angle()))
        else:
            self.readout.setText(self.joy.stop_reason or tr("Fermo"))

    # ---- frecce
    def step(self):
        for s, b in self.steps:
            if b.isChecked():
                return s
        return 10.0

    def _step(self, s, btn):
        for _, b in self.steps:
            b.setChecked(b is btn)
        self.qs.setValue("jog_step", s)

    def set_step(self, s):
        for st, b in self.steps:
            if abs(st - s) < 1e-9:
                self._step(st, b)
                return True
        return False

    def jog_press(self, dx, dy):
        if not self.ctl.connected:
            return
        if self.cont.isChecked():
            # con i soft limits GRBL rifiuta un jog oltre l'area: punto esattamente al bordo del piano
            dy = dy * rotary_sign(self.ctl)  # 0.23.3: rotativo invertito: il bordo verso cui va davvero la testa
            prof = self.get_profile()
            head = self.get_head()
            if head is None:
                self._arrow_note(tr("Posizione della testa non ancora nota: aspetta un attimo o fai l'homing"))
                return
            margin = 0.5
            hx, hy = float(head.x()), float(head.y())
            x0, y0, bx, by = reach_box(self.ctl, prof)  # 0.21.2: anche la corsa della scheda, non solo il profilo
            # 0.21.1 (Giuseppe su GitHub, Discussion #5: «se imposto continuo il tasto di sinistra non funziona»): un asse
            # già sul bordo verso cui si va non blocca più tutta la freccia (in diagonale va avanti l'altro asse), e se
            # non si può andare da nessuna parte lo dice invece di non fare niente in silenzio
            ux = float(dx) if (dx < 0 and hx > x0 + margin) or (dx > 0 and hx < bx - margin) else 0.0
            uy = float(dy) if (dy < 0 and hy > y0 + margin) or (dy > 0 and hy < by - margin) else 0.0
            L = math.hypot(ux, uy)
            t = float("inf")
            if L > 0:
                ux, uy = ux / L, uy / L
                for p, u, lo, hi in ((hx, ux, x0, bx), (hy, uy, y0, by)):
                    if u > 0:
                        t = min(t, (hi - margin - p) / u)
                    elif u < 0:
                        t = min(t, (p - lo - margin) / -u)
            if L == 0 or t <= 0 or t == float("inf"):
                self._arrow_note(self._edge_text(dx, dy))
                return
            self._arrow_note("")
            mx, my = prof.to_machine(hx + ux * t, hy + uy * t)
            self._cont = True
            self._jog_sent = time.monotonic()
            self.ctl.goto_machine(mx, my, self.get_feed())
        else:
            self._arrow_note("")
            self._cont = False
            s = self.step()
            self._jog_sent = time.monotonic()
            self.ctl.jog(dx * s, dy * s, self.get_feed())

    # ---- 0.21.2: la scheda rifiuta lo spostamento (rapporto 3802): mai più un clic che non fa niente in silenzio
    def _board_error(self, code, _text, line):
        # solo la croce che ha appena mandato lo spostamento (la scheda Movimento o quella di Stampa e taglia)
        recent = time.monotonic() - self._jog_sent <= 3.0 or self.joy.active
        if not str(line).startswith("$J=") or not recent:
            return
        lim = self.ctl.soft_limits()
        small = self.get_profile().board_smaller(lim) if lim else None
        if code == 15 and small:
            tx, ty = self.get_profile().travel()
            self._arrow_note(tr("La scheda rifiuta il movimento: il piano del profilo ({0:g} × {1:g} mm) è più grande "
                                "della corsa della macchina ({2:g} × {3:g} mm).", tx, ty, small[0], small[1]),
                             fix=True)
        elif code == 15:
            self._arrow_note(tr("La scheda rifiuta il movimento: la testa uscirebbe dall'area di lavoro."))
        else:
            self._arrow_note(tr("La scheda rifiuta il movimento (errore {0}): la testa non si è mossa.", code))

    @staticmethod
    def _edge_text(dx, dy):
        sides = []
        if dx < 0:
            sides.append(tr("sinistro"))
        elif dx > 0:
            sides.append(tr("destro"))
        if dy > 0:
            sides.append(tr("in alto"))
        elif dy < 0:
            sides.append(tr("in basso"))
        return tr("Già al bordo {0}: con «Continuo» non va più in là", " / ".join(sides))

    def _arrow_note(self, text, fix=False):
        """0.21.1: un messaggio breve sotto le frecce (sparisce da solo dopo qualche secondo). 0.21.2: con fix=True
        anche il pulsante «Usa le misure della macchina», e il messaggio resta finché non lo usi o non muovi."""
        if fix or not text:
            self.refusal_lab.setText(text if fix else "")
            self.refusal.setVisible(bool(fix and text))
            if fix:
                return
        if self.mode() == "joystick":
            return
        self.readout.setText(text)
        self.readout.setToolTip(text)
        if text and not fix:
            QTimer.singleShot(5000, self._clear_note_later(text))

    def _clear_note_later(self, text):
        def clear():
            if self.readout.text() == text:
                self.readout.setText("")
        return clear

    def _use_board_travel(self):
        """0.21.2: il piano del profilo prende le misure della corsa della scheda ($130/$131)."""
        lim = self.ctl.soft_limits()
        if lim:
            self.travel_fix_requested.emit(float(lim[0]), float(lim[1]))
        self._arrow_note("")

    def jog_release(self):
        if self._cont:
            self.ctl.jog_cancel()
            self._cont = False

    # ---- Puntino e Lucciola: gli stessi della scheda Laser
    def attach_laser(self, laser):
        self.laser = laser
        # 0.21.2: un metodo, non una lambda: quando la croce sparisce (finestra Stampa e taglia chiusa) Qt stacca da
        # solo il collegamento. Con la lambda restava attaccato e ogni clic sulla Lucciola dava «already deleted»
        laser.b_glow.toggled.connect(self._glow_toggled)
        self._sync()

    def _glow_toggled(self, _on):
        self._sync()

    def _dot(self, on):
        if self.laser is not None:
            self.laser.fire_changed(on)

    def _glow_clicked(self, on):
        if self.laser is None:
            self.b_glow.setChecked(False)
            return
        if on:
            self.laser.glow_start_on()
        else:
            self.laser.glow_stop()
        self._sync()

    def _glow_tip(self, left=None):
        base = tr("Lucciola: clic per accendere il laser al minimo e lasciarlo acceso (potenza e avvisi nella scheda "
                  "Laser); clic di nuovo per spegnerlo")
        if left is not None:
            s = int(left + 0.999)
            base = tr("LASER ACCESO · {0}:{1:02d}", s // 60, s % 60) + "\n" + base
        self.b_glow.setToolTip(base)

    def glow_on(self):
        return bool(self.laser is not None and self.laser._glow_on)

    def _sync(self):
        lz = self.laser
        if lz is None:
            self.b_glow.setStyleSheet(self._BTN_CSS)
            return
        on = lz._glow_on
        if self.b_glow.isChecked() != on:
            self.b_glow.setChecked(on)
        self.b_glow.setStyleSheet(self._GLOW_ON_CSS if on else self._BTN_CSS)
        self._glow_tip(lz.glow_seconds_left() if on else None)
        self.b_dot.setEnabled(lz.b_fire.isEnabled())
        self.b_glow.setEnabled(lz.b_glow.isEnabled() or on)
        if self.mode() == "joystick" and not self.pad.pressed:
            self._readout()

    def set_connected(self, ok):
        for w in self.jog_buttons + [self.pad]:
            w.setEnabled(ok)
        if not ok:
            self.joy.stop()
        if self.laser is None:
            self.b_dot.setEnabled(ok)
            self.b_glow.setEnabled(ok)
        self._sync()
