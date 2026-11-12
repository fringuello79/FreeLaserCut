# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Nesting manuale (0.18.16): i pezzi dentro un'area disegnata sul piano, punto per punto.

Per sfruttare un avanzo di forma qualsiasi (un trapezio di legno rimasto): si clicca sul piano lungo il bordo del
pezzo di materiale fino a chiudere il contorno, e il nesting usa esattamente quell'area.
Regole:
- clic = un punto; clic su un punto già messo = lo toglie (per rimetterlo meglio); clic sul primo punto (con almeno
  3 punti), Invio o «Chiudi l'area» = fine; Backspace toglie l'ultimo; Esc annulla;
- con la spunta «Porta il laser…» a ogni punto messo la testa ci va con il laser acceso al minimo (la Lucciola, con il
  suo limite di potenza e i suoi avvisi): si vede sul materiale se il punto è dentro o fuori dal pezzo;
- l'area chiusa diventa una forma sul livello T1 (mai incisa) e si apre «Ottimizza lo spazio» con quell'area;
- se i pezzi non entrano tutti non si sposta niente: «Disegna una nuova area» oppure «Annulla».
0.18.17 (correzioni chieste da Ale):
- si dispongono SOLO i pezzi selezionati prima di scegliere il nesting manuale (una foto di riferimento sotto, non
  selezionata, non si tocca); senza selezione il comando non parte e dice di selezionare i pezzi;
- le altre forme sul piano non contano, nemmeno se stanno sotto l'area o a cavallo del tracciato: i pezzi vanno
  nell'area disegnata e basta;
- finito il nesting il contorno dell'area sparisce (il comando ha finito il suo ciclo); resta sul livello T1 solo
  con la spunta «Lascia sul piano l'area disegnata…» di «Ottimizza lo spazio»;
- tutto il comando (area, pezzi sistemati, area tolta) è un solo passo di Ctrl+Z.
0.19.0 (chiesto da Ale): una finestra sola, stretta e di lato, al posto delle due che si coprivano:
- passo 1 «Area» e passo 2 «Disponi i pezzi» nella stessa finestra; fatto il passo 1 resta una riga («Area: N punti ·
  X cm² · Ridisegna»);
- poche scritte a vista: il resto dietro «Vedi istruzioni» e, al passo 2, dietro «Altre opzioni»;
- «l'area non basta» è un messaggio nella stessa finestra, con «Ridisegna l'area» e «Cambia le opzioni»;
- la spunta del laser pensa anche all'homing: lo propone con un avviso da confermare, lo fa e poi accende il laser;
  se il laser non è collegato lo dice e offre «Collega il laser» (la porta usata l'ultima volta);
- finché la finestra è aperta la vista si ingrandisce e si sposta, ma i disegni non si toccano (ViewOnly).
"""
import math
import os

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollBar, QVBoxLayout, QWidget,
)

from ..core.document import ImageShape, PathShape
from ..theme import C
from .editor import TOOL_LAYER
from .tools import Tool, _mods, _pen
from freelasercut.i18n import tr  # noqa: E402

HIT_PX = 9  # un clic entro tanti punti dello schermo da un punto già messo lo prende
POINT_FEED = 3000  # mm/min con cui la testa va sul punto
HOMING_WAIT_S = 90.0  # quanto aspetto, al massimo, l'homing chiesto dalla spunta del laser


def polygon_area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0


def self_crossing(pts):
    """Il contorno si incrocia da solo? (un'area a «otto» non è un pezzo di materiale)"""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue  # lati vicini: si toccano nel punto in comune
            c, d = pts[j], pts[(j + 1) % n]
            if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
                return True
    return False


def choose_mode(parent):
    """Prima scelta di «Ottimizza lo spazio»: -> "auto", "manual" oppure None (annullato)."""
    if os.environ.get("FLC_NO_DIALOGS"):
        return "auto"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(tr("Ottimizza lo spazio (nesting)"))
    box.setTextFormat(Qt.RichText)
    box.setText(tr("<b>Dove vanno sistemati i pezzi?</b><br><br>"
                   "<b>Nesting automatico</b>: sul piano di lavoro, su un rettangolo su misura o sulla forma del "
                   "materiale già disegnata.<br><br>"
                   "<b>Nesting manuale</b>: disegni tu l'area sul piano, punto per punto, per esempio lungo il bordo di "
                   "un avanzo di forma irregolare. Ci andranno dentro solo i pezzi che hai selezionato prima; le altre "
                   "forme sul piano non vengono toccate."))
    auto = box.addButton(tr("Nesting automatico"), QMessageBox.AcceptRole)
    manual = box.addButton(tr("Nesting manuale"), QMessageBox.ActionRole)
    box.addButton(tr("Annulla"), QMessageBox.RejectRole)
    box.setDefaultButton(auto)
    box.exec()
    hit = box.clickedButton()
    return "auto" if hit is auto else "manual" if hit is manual else None


def selected_parts(editor):
    """I pezzi del nesting manuale: solo quelli selezionati in questo momento (0.18.17), senza le forme del livello
    T1 e senza quelle bloccate o nascoste."""
    return [s for s in editor.selection if s.layer != TOOL_LAYER and not s.locked and not s.hidden]


def need_selection(main):
    """Nesting manuale senza niente di selezionato: non parte, e dice che cosa fare."""
    text = tr("Nesting manuale: seleziona prima i pezzi da sistemare, poi scegli di nuovo il comando.")
    main.statusBar().showMessage(text, 10000)
    if os.environ.get("FLC_NO_DIALOGS"):
        return
    box = QMessageBox(main)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(tr("Nesting manuale"))
    box.setTextFormat(Qt.RichText)
    box.setText(tr("<b>Seleziona prima i pezzi da sistemare.</b><br><br>"
                   "Il nesting manuale dispone nell'area che disegni solo i pezzi selezionati: tutto il resto (per "
                   "esempio una foto di riferimento) resta dov'è.<br><br>"
                   "Seleziona i pezzi e scegli di nuovo <i>Disponi → Ottimizza lo spazio</i>."))
    box.exec()


def collapse_history(ed, first, label, sel_before=None):
    """Riunisce in un solo passo di Ctrl+Z tutto quello che è successo dal passo `first` (l'area aggiunta) in poi:
    area, pezzi sistemati, area tolta. Se alla fine non è cambiato niente, non resta nessun passo.
    -> True se la cronologia è stata riunita."""
    stack = ed.undo_stack
    i = next((k for k, e in enumerate(stack) if e is first), None)
    if i is None:
        return False
    last = stack[-1]
    before, after = first[1], last[3]
    del stack[i:]
    if after != before:
        stack.append((label, before, first[2] if sel_before is None else list(sel_before), after,
                      [s.id for s in ed.selection]))
    ed.history_changed.emit()
    return True


class NestAreaTool(Tool):
    """Lo strumento che disegna l'area: solo tratti dritti, un punto per clic."""

    name = "nest_area"
    label = tr("Area del nesting")

    def __init__(self, cv, panel):
        super().__init__(cv)
        self.panel = panel
        self.pts = []  # [(x, y)] in mm, coordinate del piano
        self.cursor_pt = None
        self.ending = False

    def deactivate(self):
        if not self.ending:  # scelto un altro strumento a metà: è un annullamento
            self.panel.cancel(from_tool=True)

    def hit(self, view_pt):
        """Indice del punto già messo sotto il clic, o None."""
        for i, (x, y) in enumerate(self.pts):
            v = self.cv.to_view(QPointF(x, y))
            if math.hypot(v.x() - view_pt.x(), v.y() - view_pt.y()) <= HIT_PX:
                return i
        return None

    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        _, _, alt = _mods(e)
        i = self.hit(e.position())
        if i is not None:
            if i == 0 and len(self.pts) >= 3:
                self.panel.finish()  # clic sul primo punto: l'area si chiude
            else:
                self.panel.remove_point(i)  # clic su un punto messo: lo tolgo, per rimetterlo meglio
            return
        q = p if alt else self.cv.snap(p)
        self.panel.add_point(q.x(), q.y())

    def move(self, e, p):
        _, _, alt = _mods(e)
        self.cursor_pt = p if alt else self.cv.snap(p)
        if self.pts:
            a = self.pts[-1]
            dx, dy = self.cursor_pt.x() - a[0], self.cursor_pt.y() - a[1]
            self.cv.status.emit(tr("Area del nesting  L {0:.1f} mm  ·  clic: punto  ·  clic su un punto: lo toglie  ·  "
                                   "clic sul primo punto o Invio: chiude", math.hypot(dx, dy)))

    def double_click(self, e, p):
        pass  # il secondo clic del doppio clic cade sul punto appena messo e lo toglie: resta com'era

    def wants_key(self, e):
        return e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete)

    def key(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self.panel.finish()
            return True
        if k == Qt.Key_Escape:
            self.panel.cancel()
            return True
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            if self.pts:
                self.panel.remove_point(len(self.pts) - 1)
            return True
        return False

    def draw(self, p, tf):
        if not self.pts:
            return
        view = [tf.map(QPointF(x, y)) for x, y in self.pts]
        if len(view) >= 3:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(60, 160, 255, 38))
            p.drawPolygon(QPolygonF(view))
        path = QPainterPath()
        path.moveTo(view[0])
        for v in view[1:]:
            path.lineTo(v)
        p.setPen(_pen(C["accent_hi"], 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if self.cursor_pt is not None:
            c = tf.map(self.cursor_pt)
            p.setPen(_pen(C["accent_hi"], 1.0, Qt.DashLine))
            p.drawLine(view[-1], c)
            if len(view) >= 2:
                p.drawLine(c, view[0])
        for i, v in enumerate(view):
            p.setBrush(QColor(C["success"] if i == 0 else "#FFFFFF"))
            p.setPen(_pen(C["accent_lo"], 1))
            r = 5.0 if i == 0 else 4.0
            p.drawRect(QRectF(v.x() - r, v.y() - r, 2 * r, 2 * r))


VIEW_ACTS = ("zoom_in", "zoom_out", "fit", "fit_sel", "home", "unlock_m", "pause", "stop")
BANCO_SIDE = ("officina", "pill", "b_off")
MACHINE_SIDE = ("laser", "move", "machine", "console", "camera", "port_combo", "btn_refresh", "btn_wifi", "btn_connect")


class ViewOnly(QObject):
    """Finché la finestra del nesting manuale è aperta il progetto si guarda ma non si tocca (0.19.0): la vista si
    ingrandisce e si sposta, il laser si comanda (collegamento, homing, spostamenti), ma menu, strumenti, livelli e
    scorciatoie che cambiano i disegni non rispondono. È quello che faceva la finestra di prima, che però bloccava
    anche la vista e copriva il piano."""

    BLOCK = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress, QEvent.Type.Shortcut,
             QEvent.Type.ContextMenu, QEvent.Type.DragEnter, QEvent.Type.Drop)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.main = panel, panel.main
        self.on = False
        self.blocked = 0

    def start(self):
        if not self.on:
            QApplication.instance().installEventFilter(self)
            self.on = True

    def stop(self):
        if self.on:
            QApplication.instance().removeEventFilter(self)
            self.on = False

    def eventFilter(self, obj, ev):
        try:
            if ev.type() in self.BLOCK and self.stops(obj, ev):
                self.blocked += 1
                if ev.type() != QEvent.Type.DragEnter:
                    self.main.statusBar().showMessage(tr("Nesting manuale aperto: finisci o annulla dalla sua finestra. "
                                                         "Intanto puoi ingrandire e spostare la vista."), 6000)
                    self.panel.raise_()
                return True
        except Exception:  # un filtro che inciampa non deve bloccare il programma
            return False
        return False

    def stops(self, obj, ev):
        main = self.main
        if not isinstance(obj, QWidget) or obj.window() is not main:
            return False  # la finestra del nesting, i suoi avvisi, le tendine: tutto libero
        t = ev.type()
        if t == QEvent.Type.Shortcut:
            free = [k for name in VIEW_ACTS if name in main.acts for k in main.acts[name].shortcuts()]
            return ev.key() not in free
        cv = main.canvas
        if obj is cv or obj is cv.viewport():
            return self.canvas_stops(cv, ev)
        free = [getattr(main, name, None) for name in MACHINE_SIDE]
        banco = getattr(main, "banco", None)  # interfaccia Banco: l'Officina (i pannelli della macchina) e i comandi
        if banco is not None:  # del lavoro stanno sopra la tela
            free += [getattr(banco, name, None) for name in BANCO_SIDE]
            free += [getattr(getattr(banco, "cockpit", None), name, None) for name in ("top", "side", "bottom")]
        w = obj
        while w is not None and w is not main:
            if w in free:
                return False
            if w is cv:  # sopra la tela ci sono anche linguette, strumenti e livelli (Banco): liberi solo gli scorrimenti
                return not isinstance(obj, QScrollBar)
            w = w.parentWidget()
        return True

    def canvas_stops(self, cv, ev):
        t = ev.type()
        drawing = self.panel.step == 1  # passo 1: i clic mettono i punti dell'area
        if t == QEvent.Type.KeyPress:
            return not (ev.key() == Qt.Key_Space or (drawing and cv.tool.wants_key(ev)))
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            return not (drawing or ev.button() == Qt.MiddleButton or cv._space)
        return True


class _Link(QLabel):
    """Una scritta cliccabile («Vedi istruzioni», «Ridisegna»)."""

    def __init__(self, text, slot):
        super().__init__()
        self.setTextFormat(Qt.RichText)
        self.setCursor(Qt.PointingHandCursor)
        self.linkActivated.connect(lambda *_: slot())
        self.set(text)

    def set(self, text):
        self.plain = text
        self.setText(f"<a href='#' style='color:{C['accent_hi']}'>{text}</a>")


class NestAreaPanel(QDialog):
    """La finestra del nesting manuale, una sola e di lato (0.19.0): passo 1 si disegna l'area, passo 2 si scelgono
    le opzioni e si dispongono i pezzi. Le istruzioni lunghe stanno dietro «Vedi istruzioni»."""

    done = Signal(object)  # fine del comando: il passo 2 (NestDialog) se ci si è arrivati, altrimenti None

    def __init__(self, main, parts=None):
        super().__init__(main)
        self.main, self.ed, self.cv, self.ctl = main, main.editor, main.canvas, main.ctl
        self.parts = list(parts or [])  # i pezzi selezionati prima di cominciare: si dispongono solo quelli
        self.shape = None
        self.dlg = None  # il passo 2, dentro questa finestra
        self.step = 1
        self._closed = False  # il disegno dell'area è finito (chiusa o annullata)
        self._over = False  # il comando è finito: la finestra si chiude
        self._homing = False
        self.laser_note = ""
        self.setWindowTitle(tr("Nesting manuale"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setFixedWidth(380)
        v = QVBoxLayout(self)
        self.head1 = QLabel()
        v.addWidget(self.head1)
        # ---------------------------------------------------------------- passo 1: l'area
        self.p1 = QWidget()
        v1 = QVBoxLayout(self.p1)
        v1.setContentsMargins(0, 0, 0, 0)
        how = QLabel(tr("Clicca sul piano lungo il bordo del materiale, un punto dopo l'altro, fino a tornare al "
                        "primo (quello verde)."))
        how.setWordWrap(True)
        v1.addWidget(how)
        self.help_link = _Link(tr("Vedi istruzioni"), self.toggle_help)
        v1.addWidget(self.help_link)
        self.help = QLabel(tr("• Un clic su un punto già messo lo <b>toglie</b>: poi lo rimetti dove serve.<br>"
                              "• Per finire: clic sul primo punto, tasto Invio, oppure «Chiudi l'area».<br>"
                              "• Backspace toglie l'ultimo punto, Esc annulla.<br>"
                              "• Con la rotella ingrandisci, con il tasto centrale (o Spazio) sposti la vista.<br>"
                              "• Con la spunta del laser, a ogni punto la testa ci va con il laser acceso al minimo: "
                              "vedi sul materiale se il punto è dentro o fuori dal pezzo."))
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.RichText)
        self.help.setObjectName("muted")
        self.help.hide()
        v1.addWidget(self.help)
        self.laser = QCheckBox(tr("Porta il laser, acceso al minimo, su ogni punto"))
        self.laser.setToolTip(tr("A ogni punto la testa ci va con il laser acceso alla potenza della Lucciola. Se serve "
                                 "l'homing lo faccio io, dopo il tuo OK. Occhiali protettivi indossati."))
        self.laser.toggled.connect(self._laser_toggled)
        v1.addWidget(self.laser)
        self.b_connect = QPushButton(tr("Collega il laser"))
        self.b_connect.clicked.connect(lambda: self.connect_laser())
        self.b_connect.hide()
        v1.addWidget(self.b_connect)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        v1.addWidget(self.info)
        row = QHBoxLayout()
        self.b_cancel = QPushButton(tr("Annulla"))
        self.b_cancel.clicked.connect(lambda: self.cancel())
        self.b_done = QPushButton(tr("Chiudi l'area"))
        self.b_done.setObjectName("primary")
        self.b_done.clicked.connect(lambda: self.finish())
        row.addStretch(1)
        row.addWidget(self.b_cancel)
        row.addWidget(self.b_done)
        v1.addLayout(row)
        v.addWidget(self.p1)
        # il passo 1 a cose fatte: una riga sola, con «Ridisegna»
        self.sum1 = QWidget()
        hs = QHBoxLayout(self.sum1)
        hs.setContentsMargins(0, 0, 0, 0)
        self.sum_text = QLabel()
        self.sum_text.setObjectName("muted")
        self.redraw_link = _Link(tr("Ridisegna"), self.redraw)
        hs.addWidget(self.sum_text)
        hs.addStretch(1)
        hs.addWidget(self.redraw_link)
        self.sum1.hide()
        v.addWidget(self.sum1)
        # ---------------------------------------------------------------- passo 2: opzioni e «Disponi»
        self.head2 = QLabel()
        v.addWidget(self.head2)
        self.p2 = QWidget()
        self.v2 = QVBoxLayout(self.p2)
        self.v2.setContentsMargins(0, 0, 0, 0)
        self.p2.hide()
        v.addWidget(self.p2)
        self.tool = NestAreaTool(self.cv, self)
        self.view_only = ViewOnly(self)
        self._home_timer = QTimer(self)
        self._home_timer.setSingleShot(True)
        self._home_timer.timeout.connect(lambda: self._homing_end(tr("L'homing non è finito in tempo.")))
        self.ctl.homed_changed.connect(self._homed)
        self.ctl.alarm_raised.connect(self._alarm)
        self._heads()
        self._refresh()

    def _heads(self):
        one, two = tr("1 · Area"), tr("2 · Disponi i pezzi")
        if self.step == 1:
            self.head1.setText(f"<b>{one}</b>")
            self.head2.setText(f"<span style='color:{C['muted']}'>{two}</span>")
        else:
            self.head1.setText(f"<span style='color:{C['muted']}'>{one}</span>")
            self.head2.setText(f"<b>{two}</b>")

    def _fit(self):
        """La finestra prende l'altezza del suo contenuto (un pezzo è stato aperto o chiuso)."""
        if self._over:
            return
        for wd in self.findChildren(QWidget):  # un riquadro interno appena aperto o chiuso: la sua misura va ricalcolata
            if wd.layout() is not None:
                wd.layout().invalidate()
                wd.updateGeometry()
        lay = self.layout()
        lay.invalidate()
        lay.activate()
        # le scritte vanno a capo: l'altezza giusta è quella che serve alla larghezza (fissa) della finestra
        h = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        self.setFixedHeight(max(60, h))

    def toggle_help(self):
        on = self.help.isHidden()
        self.help.setVisible(on)
        self.help_link.set(tr("Nascondi istruzioni") if on else tr("Vedi istruzioni"))
        self._fit()

    # ------------------------------------------------------------------ avvio e fine
    def _take_canvas(self):
        cv = self.cv
        cv.tool.deactivate()
        cv.tool = self.tool  # non passa da set_tool: non è uno strumento della barra
        self.tool.activate()
        cv.viewport().setCursor(self.tool.cursor())
        cv.viewport().update()

    def start(self):
        self._take_canvas()
        self.view_only.start()
        self.show()
        self._fit()
        self._place()
        return self

    def _place(self):
        try:  # in alto a destra della finestra, fuori dal centro del piano
            g = self.main.geometry()
            self.move(g.right() - self.width() - 40, g.top() + 110)
        except RuntimeError:
            pass

    def _laser_off(self):
        self._homing = False
        self._home_timer.stop()
        if self.laser.isChecked():
            self.main.laser.glow_stop()
            self._set_check(False)
        self.laser.setEnabled(True)
        self.laser_note = ""

    def _leave_tool(self):
        self.tool.ending = True
        if self.cv.tool is self.tool:
            self.cv.set_tool("select")
        self._laser_off()

    def _finish_command(self, dlg, close=True):
        """Il comando è finito (in qualsiasi modo): si avvisa una volta sola e la finestra si chiude."""
        if self._over:
            return
        self._over = True
        self.view_only.stop()
        self.done.emit(dlg)
        if close:
            self.close()

    def cancel(self, from_tool=False):
        if self._closed:
            return
        self._closed = True
        self.tool.ending = True
        if not from_tool:
            self._leave_tool()
        else:
            self._laser_off()
        self.main.statusBar().showMessage(tr("Nesting manuale annullato"), 5000)
        self._finish_command(None)

    def closeEvent(self, ev):
        if not self._over:  # chiusa con la X
            if self.step == 1:  # a metà del disegno: è un annullamento
                self._closed = True
                self._leave_tool()
                self._finish_command(None, close=False)
            else:  # al passo 2: come «Annulla» prima di disporre, come «Fatto» dopo
                dlg = self.dlg
                self._over = True
                self.view_only.stop()
                if dlg is not None and not dlg._ended:
                    dlg.done(0)
                self.done.emit(dlg)
        super().closeEvent(ev)

    def finish(self):
        """Chiude l'area: forma sul livello T1, selezionata insieme ai pezzi, e si passa al passo 2 nella stessa
        finestra. False (con il motivo) se non si può."""
        if self._closed:
            return False
        pts = list(self.tool.pts)
        if len(pts) < 3:
            return self._say(tr("Servono almeno 3 punti per chiudere un'area."), True)
        if polygon_area(pts) < 1.0:
            return self._say(tr("L'area è troppo piccola (meno di 1 mm²): i punti sono quasi in fila."), True)
        if self_crossing(pts):
            return self._say(tr("Il contorno si incrocia da solo: togli un punto (cliccandoci sopra) e rimettilo "
                                "seguendo il bordo del pezzo in ordine."), True)
        path = QPainterPath()
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        shape = PathShape(path, layer=TOOL_LAYER)
        alive = set(self.ed.doc.shapes)
        parts = [s for s in self.parts if s in alive]
        self._closed = True
        self._leave_tool()
        # le impostazioni del livello T1 nascono alla prima forma che ci finisce: le faccio nascere prima, così se poi
        # si annulla il progetto torna identico e nella cronologia non resta un passo che non fa niente
        self.ed.doc.layer(TOOL_LAYER)
        self.ed.add([shape], tr("Area del nesting"), select=False)
        self.ed.select([shape] + parts)
        self.parts = parts
        self.shape = shape
        self._arrange(shape, len(pts), polygon_area(pts))
        return True

    # ------------------------------------------------------------------ passo 2
    def _arrange(self, shape, n, area):
        from .dialogs_nest import NestDialog

        dlg = NestDialog(self.main, manual=shape, host=self)
        self.dlg = self.main._nest_manual_dlg = dlg
        self.step = 2
        self.p1.hide()
        self.sum_text.setText(tr("Area: {0} punti · {1:.1f} cm²", n, area / 100.0))
        self.redraw_link.show()
        self.sum1.show()
        self.v2.addWidget(dlg)
        self.p2.show()
        dlg.show()
        dlg.changed.connect(self._dlg_changed)
        dlg.finished.connect(self._dlg_finished)
        self._heads()
        self._fit()
        dlg.b_run.setFocus()

    def _dlg_changed(self):
        if self.dlg is not None and self.dlg.placed:
            self.redraw_link.hide()  # i pezzi sono a posto: un'altra area è un altro comando
        self._fit()

    def redraw(self):
        """«Ridisegna»: l'area non va bene, se ne disegna un'altra con gli stessi pezzi (stessa finestra)."""
        if self.dlg is not None and self.step == 2:
            self.dlg.redraw()

    def _dlg_finished(self, *_):
        dlg = self.dlg
        if dlg is None or self._over:
            return
        if not dlg.again:
            return self._finish_command(dlg)
        # si ridisegna: di nuovo il passo 1, con i pezzi di prima
        alive = set(self.ed.doc.shapes)
        self.parts = [s for s in dlg.parts if s in alive]
        self.v2.removeWidget(dlg)
        dlg.setParent(None)
        dlg.deleteLater()
        self.dlg = None
        if not self.parts:
            return self._finish_command(None)
        self.shape = None
        self.step = 1
        self._closed = False
        self.tool = NestAreaTool(self.cv, self)
        self.p2.hide()
        self.sum1.hide()
        self.p1.show()
        self._heads()
        self._take_canvas()
        self._refresh(tr("Disegna la nuova area."))
        self._fit()

    # ------------------------------------------------------------------ punti
    def add_point(self, x, y):
        self.tool.pts.append((float(x), float(y)))
        if self.laser.isChecked() and not self._homing:
            self.laser_note = self.point_laser(x, y)
        self._refresh()

    def remove_point(self, i):
        if 0 <= i < len(self.tool.pts):
            del self.tool.pts[i]
            if not self._homing:
                self.laser_note = ""
            self._refresh(tr("Punto tolto: clicca dove lo vuoi rimettere."))

    def _say(self, text, bad=False):
        self._refresh(("⚠ " if bad else "") + text)
        return not bad

    def _refresh(self, note=""):
        n = len(self.tool.pts)
        text = tr("Punti messi: {0}.", n)
        if n >= 3:
            text += " " + tr("Area: {0:.0f} mm².", polygon_area(self.tool.pts))
        for extra in (self.laser_note, note):
            if extra:
                text += "<br>" + extra
        self.info.setText(text)
        self.b_done.setEnabled(n >= 3)
        self.cv.viewport().update()
        if self.isVisible():
            self._fit()

    # ------------------------------------------------------------------ laser sul punto
    def laser_ready(self):
        """None se il laser può andare sui punti, altrimenti il motivo."""
        c = self.ctl
        if not c.connected:
            return tr("Il laser non è collegato.")
        if c.job_active or c.checking:
            return tr("C'è un lavoro in corso.")
        if self.main.profile.homing and not c.homed:
            return tr("Fai prima l'homing: serve perché la testa vada nel punto giusto del piano.")
        if c.last_status.get("state") not in ("Idle", "Run", "Jog"):
            return tr("La macchina non è pronta (stato: {0}).", c.last_status.get("state", "?"))
        return None

    def _set_check(self, on):
        self.laser.blockSignals(True)
        self.laser.setChecked(on)
        self.laser.blockSignals(False)

    def ask_homing(self):
        """La spunta del laser senza homing fatto: lo propongo io (0.19.0). -> True = OK, faccio l'homing."""
        if os.environ.get("FLC_NO_DIALOGS"):
            return False
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr("Serve l'homing"))
        box.setTextFormat(Qt.RichText)
        box.setText(tr("<b>Per portare il laser sui punti serve l'homing.</b><br><br>"
                       "La testa va ai finecorsa: <b>tieni libero il piano</b>. Poi il laser si accende al minimo: "
                       "<b>occhiali protettivi indossati</b>.<br><br>Premi OK per fare l'homing adesso."))
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Ok)
        return box.exec() == QMessageBox.Ok

    def _laser_toggled(self, on):
        self.b_connect.hide()
        if not on:
            self._homing = False
            self._home_timer.stop()
            self.main.laser.glow_stop()
            self.laser_note = ""
            self._refresh()
            return
        c = self.ctl
        if not c.connected:
            self._set_check(False)
            self.b_connect.show()
            self._refresh("⚠ " + tr("Il laser non è collegato."))
            return
        if self.main.profile.homing and not c.homed and not (c.job_active or c.checking):
            if not self.ask_homing():
                self._set_check(False)
                self._refresh("⚠ " + tr("Senza homing la testa non sa dov'è: la spunta resta spenta."))
                return
            self._homing = True
            self.laser.setEnabled(False)
            self.laser_note = tr("Homing in corso: la testa va ai finecorsa…")
            self._refresh()
            self._home_timer.start(int(HOMING_WAIT_S * 1000))
            c.home()
            return
        self._glow_on_now()

    def _glow_on_now(self):
        why = self.laser_ready()
        if why is None and not self.main.laser._glow_on and not self.main.laser.glow_start_on():
            why = tr("Il laser al minimo non è stato acceso.")
        if why:
            self._set_check(False)
            self.laser_note = ""
            self._refresh("⚠ " + why)
            return
        self.laser_note = tr("Laser acceso al minimo: a ogni punto la testa ci va. Occhiali indossati.")
        self._refresh()

    def _homed(self, ok, *_):
        if self._homing and ok:
            self._homing = False
            self._home_timer.stop()
            self.laser.setEnabled(True)
            self._glow_on_now()

    def _alarm(self, code, *_):
        if self._homing:
            self._homing_end(tr("Homing non riuscito (allarme {0}): controlla la macchina e riprova.", code))

    def _homing_end(self, why):
        if not self._homing:
            return
        self._homing = False
        self._home_timer.stop()
        self.laser.setEnabled(True)
        self._set_check(False)
        self.laser_note = ""
        self._refresh("⚠ " + why)

    def connect_laser(self):
        """«Collega il laser»: alla porta usata l'ultima volta, come fa il programma all'avvio."""
        m = self.main
        last = m.qs.value("port", "")
        i = m.port_combo.findData(last) if last else -1
        if i < 0:
            return self._say(tr("Non trovo la porta usata l'ultima volta: collega il laser dalla finestra principale "
                                "(pulsante Connetti), poi rimetti la spunta."), True)
        m.port_combo.setCurrentIndex(i)
        m.toggle_connection(quiet=True)
        if not self.ctl.connected:
            return self._say(tr("Il laser non risponde su {0}: controlla che sia acceso.", last), True)
        self.b_connect.hide()
        return self._say(tr("Laser collegato: ora rimetti la spunta."))

    def point_laser(self, x, y):
        """Manda la testa sul punto (laser già acceso al minimo). -> testo da mostrare."""
        lp = self.main.laser
        if not lp._glow_on:  # spenta nel frattempo (5 minuti fermi, allarme…): la spunta non vale più
            self._set_check(False)
            return "⚠ " + tr("Il laser al minimo si è spento: rimetti la spunta per riaccenderlo.")
        why = self.laser_ready()
        if why:
            return "⚠ " + why
        prof = self.main.profile
        if not (0.0 <= x <= prof.bed_x and 0.0 <= y <= prof.bed_y):
            return "⚠ " + tr("Questo punto è fuori dall'area di lavoro: la testa non ci va.")
        mx, my = prof.to_machine(x, y)
        self.ctl.send_line(f"G53 G1 X{mx:.3f} Y{my:.3f} F{POINT_FEED}")
        return tr("La testa va sul punto X {0:.1f}  Y {1:.1f}.", x, y)


def area_shapes(doc):
    return [s for s in doc.shapes if s.layer == TOOL_LAYER and not isinstance(s, ImageShape)]
