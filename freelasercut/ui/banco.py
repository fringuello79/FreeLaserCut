# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Interfaccia «Banco»: il piano al centro, i comandi dove servono.

Riusa tutti i comandi, i pannelli e la logica della finestra classica e cambia solo la disposizione:
- barra superiore sottile: progetto, ricerca di tutti i comandi (Ctrl+F), stato della macchina, Officina, impostazioni;
- strati a sinistra come «ricette» nell'ordine di lavoro, modificabili sul posto;
- a destra le proprietà della selezione e il percorso «dal disegno al pezzo», con avvio a pressione prolungata;
- isola degli strumenti in basso; barra contestuale accanto alla selezione; menu radiale col tasto destro;
- cabina durante il lavoro (Pausa e Stop grandi, tempo rimanente, regolazioni dal vivo);
- Officina (laser, movimento, camera, macchina, console, tabella strati): cassetto a destra con un monitor,
  finestra sul secondo monitor quando c'è.
La finestra classica resta disponibile: l'interfaccia si sceglie al primo avvio e in Impostazioni → Interfaccia.
"""
import os
import time
import unicodedata

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider, QSpinBox, QStyledItemDelegate,
    QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from freelasercut.i18n import tr  # noqa: E402
from .. import units

from . import style
from ..theme import css, tc
from .canvas import RULER
from .panels_machine import OVERRIDE_TIP
from .editor import TOOL_LAYER

OFF_W = 520  # larghezza dell'Officina a cassetto
MODES = ("banco", "classica")
ORANGE = "#FF7A2E"

BANCO_QSS = css(f"""
QToolBar#bcTopBar {{ background: #0A0E17; border: none; border-bottom: 1px solid #1A2234; padding: 0; spacing: 0; }}
QFrame#bcTop {{ background: #0A0E17; }}
QFrame#bcCard, QFrame#bcIsland, QFrame#bcCtx, QFrame#bcOfficina {{
    background: #121826; border: 1px solid #263048; border-radius: 14px; }}
QFrame#bcIsland {{ border-radius: 18px; }}
QFrame#bcCardOn {{ background: #161E30; border: 1px solid {ORANGE}; border-radius: 14px; }}
QFrame#bcCockpitTop {{ background: #3A1D08; border: 1px solid {ORANGE}; border-radius: 16px; }}
QLabel#bcSection {{ color: #94A0B8; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#bcMuted {{ color: #94A0B8; }}
QLabel#bcTitle {{ font-weight: 700; }}
QLabel#bcBig {{ font-size: 30pt; font-weight: 700; }}
QLabel#bcTag {{ color: #C9D3E6; border: 1px solid #2E3A56; border-radius: 6px; padding: 1px 6px; font-size: 7.5pt; font-weight: 700; }}
QToolButton#bcTool {{ min-width: 40px; min-height: 40px; max-width: 40px; max-height: 40px; border-radius: 11px;
    background: transparent; border: none; padding: 0; }}
QToolButton#bcTool:hover {{ background: #1E2638; }}
QToolButton#bcTool:checked {{ background: {ORANGE}; }}
QToolButton#bcTool:disabled {{ background: transparent; }}
QPushButton#bcChip, QToolButton#bcChip {{ background: #172034; border: 1px solid #2A3550; border-radius: 9px;
    padding: 4px 10px; color: #DDE5F3; font-weight: 600; min-height: 22px; }}
QPushButton#bcChip:hover, QToolButton#bcChip:hover {{ border-color: #4FB4FF; }}
QPushButton#bcChip:disabled, QToolButton#bcChip:disabled {{ color: #55627E; border-color: #1A253C; }}
QToolButton#bcChip::menu-indicator {{ image: none; width: 0; }}
QPushButton#bcSearch {{ background: #111827; border: 1px solid #263048; border-radius: 10px; color: #94A0B8;
    text-align: left; padding: 6px 12px; min-height: 22px; }}
QPushButton#bcSearch:hover {{ border-color: #4FB4FF; color: #C9D3E6; }}
QPushButton#bcPill {{ border-radius: 15px; padding: 5px 12px; font-weight: 600; text-align: left; }}
QPushButton#bcSupport {{ background: #FFFFFF; color: #0E1734; border: 1px solid #FFFFFF; border-radius: 9px;
    padding: 5px 12px; font-weight: 700; }}
QPushButton#bcSupport:hover {{ background: #FFF3EA; border-color: #FF9A4D; }}
QPushButton#bcStart {{ background: {ORANGE}; color: #1A0E05; border: none; border-radius: 14px; font-size: 11pt;
    font-weight: 800; min-height: 52px; }}
QPushButton#bcStart:disabled {{ background: #2A2018; color: #7A6A5A; }}
QPushButton#bcPause {{ background: #FFB347; color: #1A0E05; border: none; border-radius: 16px; font-size: 13pt;
    font-weight: 800; min-height: 60px; min-width: 200px; }}
QPushButton#bcStop {{ background: #E5484D; color: #FFFFFF; border: none; border-radius: 16px; font-size: 13pt;
    font-weight: 800; min-height: 60px; min-width: 200px; }}
QPushButton#bcStep {{ background: #172034; border: 1px solid #2A3550; border-radius: 12px; font-size: 14pt;
    min-width: 44px; min-height: 44px; max-width: 44px; }}
QFrame#bcLayerHead {{ background: transparent; border: none; }}
QFrame#bcLayerHead:focus {{ border: 1px dotted #4FB4FF; border-radius: 6px; }}
QListWidget#bcPalList {{ background: transparent; border: none; outline: none; }}
QListWidget#bcPalList::item {{ border-radius: 8px; padding: 0; }}
QListWidget#bcPalList::item:selected {{ background: #22304D; }}
QLineEdit#bcPalEdit, QLineEdit#bcPalEdit:focus, QLineEdit#bcPalEdit:hover {{ background: transparent; color: #E8EDF7;
    border: none; border-bottom: 1px solid #263048; font-size: 13pt; padding: 8px 6px; selection-background-color: #2E7CF6; }}
QFrame#bcPalette {{ background: #121826; border: 1px solid #2E3A56; border-radius: 16px; }}
""")


# ============================================================ scelta dell'interfaccia
def settings():
    from ..settings_store import app_settings

    return app_settings()


def ui_mode(qs=None):
    """Interfaccia da usare: variabile FLC_UI, poi la scelta salvata, altrimenti Banco."""
    env = os.environ.get("FLC_UI")
    if env in MODES:
        return env
    v = (qs or settings()).value("ui_mode")
    return v if v in MODES else "banco"


def needs_choice(qs=None):
    return os.environ.get("FLC_UI") not in MODES and (qs or settings()).value("ui_mode") not in MODES


def save_mode(mode, qs=None):
    qs = qs or settings()
    qs.setValue("ui_mode", mode)
    qs.sync()


class ChoiceDialog(QDialog):
    """Primo avvio: Banco o Classica (si cambia poi da Impostazioni → Interfaccia)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Scegli l'interfaccia"))
        self.setMinimumWidth(640)
        self.choice = "banco"
        v = QVBoxLayout(self)
        v.setSpacing(14)
        head = QLabel(tr("<b style='font-size:14pt'>Come preferisci lavorare?</b><br>"
                         "Le due interfacce hanno gli stessi comandi: cambia solo la disposizione."))
        head.setWordWrap(True)
        v.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.b_banco = self._card(tr("Banco"), tr("consigliata"),
                                  tr("Il piano di lavoro a tutto schermo. Strati a sinistra, percorso guidato «dal "
                                     "disegno al pezzo» a destra, strumenti in un'isola in basso, ricerca di tutti i "
                                     "comandi con Ctrl+F, menu radiale col tasto destro. Con un secondo monitor, "
                                     "laser e camera vanno da soli sull'altro schermo."))
        self.b_classic = self._card(tr("Classica"), tr("menu e pannelli"),
                                    tr("Barra dei menu, barre di strumenti e pannelli laterali come nei programmi "
                                       "di incisione tradizionali. Comoda se arrivi da altri software."))
        self.b_banco._fn = lambda: self._pick("banco")
        self.b_classic._fn = lambda: self._pick("classica")
        # doppio clic su una scheda: la sceglie e parte subito, come «Inizia»
        self.b_banco._dbl = lambda: self._start("banco")
        self.b_classic._dbl = lambda: self._start("classica")
        self.setStyleSheet(css("QFrame#bcChoice { border-radius: 14px; border: 1px solid #2A3550; background: #121826; }"
                           "QFrame#bcChoice:focus { border-color: #4FB4FF; }"
                           "QFrame#bcChoice[on=\"true\"] { border: 2px solid " + ORANGE + "; background: #1A1410; }"))
        row.addWidget(self.b_banco, 1)
        row.addWidget(self.b_classic, 1)
        v.addLayout(row)
        # il laser: solo alla prima installazione (chi aggiorna ha già il suo profilo)
        self.machine = None
        qs = settings()
        if not qs.value("profile_path", ""):
            from .. import machines

            mr = QHBoxLayout()
            ml = QLabel(tr("<b>Il tuo laser</b>"))
            mr.addWidget(ml)
            self.machine = QComboBox()
            self.machine.addItems(machines.catalog_names())
            self.machine.setToolTip(tr("Area di lavoro e velocità di targa. Quando colleghi la macchina, FreeLaserCut "
                                       "rilegge i valori veri dalla scheda (Laser → Riconosci la macchina)."))
            mr.addWidget(self.machine, 1)
            v.addLayout(mr)
        note = QLabel(tr("Puoi cambiarla in qualsiasi momento da <b>Impostazioni → Interfaccia</b> "
                         "(nel Banco: pulsante ⚙ in alto a destra)."))
        note.setWordWrap(True)
        note.setObjectName("muted")
        v.addWidget(note)
        hint = QLabel(tr("Doppio clic su una scheda per iniziare subito."))
        hint.setObjectName("muted")
        ok = QPushButton(tr("Inizia"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.setMinimumHeight(38)
        ok.setMinimumWidth(220)
        f = ok.font()
        f.setBold(True)
        ok.setFont(f)
        ok.clicked.connect(self.accept)
        self.ok = ok
        h = QHBoxLayout()
        h.addWidget(hint)
        h.addStretch(1)
        h.addWidget(ok)
        v.addLayout(h)
        self._pick("banco")

    def _card(self, title, tag, text):
        b = _ClickFrame(None)
        b.setObjectName("bcChoice")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(170)
        lay = QVBoxLayout(b)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        t = QLabel(f"<b style='font-size:12pt'>{title}</b> &nbsp;<span style='color:#94A0B8'>{tag}</span>")
        d = QLabel(text)
        d.setWordWrap(True)
        for w in (t, d):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        lay.addStretch(1)
        return b

    def _pick(self, mode):
        self.choice = mode
        for b, m in ((self.b_banco, "banco"), (self.b_classic, "classica")):
            b.setProperty("on", m == mode)
            b.style().unpolish(b)
            b.style().polish(b)
        if hasattr(self, "ok"):
            self.ok.setText(tr("Inizia con {0}  ▶", tr("Banco") if mode == "banco" else tr("Classica")))

    def _start(self, mode):
        self._pick(mode)
        self.accept()

    def _save_machine(self):
        if self.machine is not None:
            from .dialogs_machine import use_preset

            use_preset(settings(), self.machine.currentText())

    def accept(self):
        save_mode(self.choice)
        self._save_machine()
        super().accept()

    def reject(self):  # chiusa con la X: vale la scelta evidenziata
        save_mode(self.choice)
        self._save_machine()
        super().reject()


# ============================================================ piccoli componenti
def _norm(s):
    s = unicodedata.normalize("NFKD", s.replace("&", "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _clean(text):
    return text.replace("&&", "\x00").replace("&", "").replace("\x00", "&").replace("…", "").strip()


def _label(text, name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _chip(text, fn=None, tip=None):
    b = QPushButton(text)
    b.setObjectName("bcChip")
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    if fn is not None:
        b.clicked.connect(fn)
    return b


def _act_button(act, name="bcTool", icon_size=20, text_beside=False):
    b = QToolButton()
    b.setObjectName(name)
    b.setDefaultAction(act)
    b.setIconSize(QSize(icon_size, icon_size))
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if text_beside else Qt.ToolButtonIconOnly)
    b.setCursor(Qt.PointingHandCursor)
    b.setAutoRaise(True)
    return b


def _menu_button(text, actions, tip=None):
    b = QToolButton()
    b.setObjectName("bcChip")
    b.setText(text + " ▾")
    b.setPopupMode(QToolButton.InstantPopup)
    b.setCursor(Qt.PointingHandCursor)
    m = QMenu(b)
    for a in actions:
        if a is None:
            m.addSeparator()
        else:
            m.addAction(a)
    b.setMenu(m)
    if tip:
        b.setToolTip(tip)
    return b


def _sep(vertical=True):
    f = QFrame()
    f.setFixedSize(1, 28) if vertical else f.setFixedHeight(1)
    f.setStyleSheet(css("background: #2A3550;"))
    return f


def _hms(sec):
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class HoldButton(QPushButton):
    """Pulsante che agisce solo dopo una pressione prolungata: evita gli avvii per sbaglio."""
    held = Signal()

    def __init__(self, text, ms=900, parent=None):
        super().__init__(text, parent)
        self._ms = ms
        self._p = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def _begin(self):
        if self.isEnabled():
            self._p = 0.0
            self._timer.start()

    def _end(self):
        self._timer.stop()
        self._p = 0.0
        self.update()

    def _tick(self):
        self._p += 30.0 / self._ms
        self.update()
        if self._p >= 1.0:
            self._end()
            self.held.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._begin()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._end()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not e.isAutoRepeat():
            self._begin()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not e.isAutoRepeat():
            self._end()
            return
        super().keyReleaseEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._p > 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 90))
            r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
            r.setWidth(r.width() * min(self._p, 1.0))
            p.drawRoundedRect(r, 12, 12)
            p.end()


# ============================================================ ricerca di tutti i comandi
class _PalDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        super().paint(p, option, index)
        path = index.data(Qt.UserRole + 1) or ""
        key = index.data(Qt.UserRole + 2) or ""
        r = option.rect.adjusted(12, 0, -12, 0)
        p.save()
        p.setPen(QColor(tc("#94A0B8")))
        p.setFont(style.ui_font(8))
        if key:
            p.setFont(style.mono_font(8))
            p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, key)
            r.setRight(r.right() - 130)
            p.setFont(style.ui_font(8))
        p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, path)
        p.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), 34)


class CommandPalette(QFrame):
    """Tutti i comandi del programma, trovati scrivendo (Ctrl+F). Nessun comando resta nascosto nei menu."""

    def __init__(self, win):
        super().__init__(win, Qt.Popup | Qt.FramelessWindowHint)
        self.win = win
        self.setObjectName("bcPalette")
        self.resize(700, 480)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("bcPalEdit")
        self.edit.setPlaceholderText(tr("Cosa vuoi fare? Scrivi una parola: offset, testo, contorno, homing…"))
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        v.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("bcPalList")
        self.list.setItemDelegate(_PalDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        v.addWidget(self.list, 1)
        self.hint = _label(tr("Invio: esegue · ↑↓: scorre · Esc: chiude"), "bcMuted")
        v.addWidget(self.hint)
        self.entries = []

    # -- elenco di tutti i comandi, preso dai menu (anche nascosti) e dagli strumenti
    def collect(self):
        out, seen = [], set()

        def walk(menu, path):
            for a in menu.actions():
                if a.isSeparator():
                    continue
                if a.menu() is not None:
                    walk(a.menu(), path + [_clean(a.text())])
                    continue
                if id(a) in seen or not _clean(a.text()) or not a.isVisible():
                    continue  # 0.17.16: le funzioni nascoste (es. in prova, non sbloccate) non si cercano
                seen.add(id(a))
                out.append((a, " › ".join(path)))

        for a in self.win.menuBar().actions():
            if a.menu() is not None:
                walk(a.menu(), [_clean(a.text())])
        extra = getattr(self.win.banco, "extra_actions", []) if self.win.banco else []
        for a, path in extra:
            if id(a) not in seen:
                seen.add(id(a))
                out.append((a, path))
        self.entries = out

    def open(self):
        self.collect()
        g = self.win.geometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 70)
        self.edit.clear()
        self._filter("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def _filter(self, text):
        words = _norm(text).split()
        rows = []
        for a, path in self.entries:
            name = _norm(a.text())
            hay = name + " " + _norm(path)
            if words and not all(w in hay for w in words):
                continue
            score = 0
            if words:
                score -= 3 if name.startswith(words[0]) else 0
                score -= 2 if any(t.startswith(words[0]) for t in name.split()) else 0
                score -= 1 if words[0] in name else 0
            rows.append((score, a, path))
        rows.sort(key=lambda r: r[0])
        self.list.clear()
        for _score, a, path in rows[:80]:
            it = QListWidgetItem(a.icon(), _clean(a.text()) + ("  ✓" if a.isCheckable() and a.isChecked() else ""))
            it.setData(Qt.UserRole, a)
            it.setData(Qt.UserRole + 1, path if a.isEnabled() else tr("{0} · non disponibile ora", path))
            it.setData(Qt.UserRole + 2, a.shortcut().toString(QKeySequence.NativeText))
            if not a.isEnabled():
                it.setForeground(QColor(tc("#55627E")))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, it):
        a = it.data(Qt.UserRole) if it is not None else None
        if a is None or not a.isEnabled():
            return
        self.hide()
        QTimer.singleShot(0, a.trigger)

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(r, self.list.count() - 1)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._run(self.list.currentItem())
                return True
            if k == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, e)


# ============================================================ menu radiale (tasto destro)
class RadialMenu(QWidget):
    """Otto azioni in cerchio intorno al cursore: si raggiungono con un gesto breve, senza leggere una lista."""
    R = 104
    SIZE = 300

    def __init__(self, parent, title, items):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.title = title
        import math

        c = self.SIZE / 2
        self.buttons = []
        for i, (label, act) in enumerate(items[:8]):
            a = -math.pi / 2 + i * 2 * math.pi / min(len(items), 8)
            b = QToolButton(self)
            b.setObjectName("bcRad")
            b.setIcon(act.icon())
            b.setIconSize(QSize(20, 20))
            b.setText(label)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(80, 80)
            b.setEnabled(act.isEnabled())
            b.setToolTip(_clean(act.text()))
            b.setStyleSheet(css("QToolButton { background: #141B2B; border: 1px solid #2E3A56; border-radius: 40px; "
                            "color: #E8EDF7; font-size: 7.5pt; font-weight: 600; } "
                            "QToolButton:hover { background: " + ORANGE + "; color: #1A0E05; border-color: " + ORANGE + "; } "
                            "QToolButton:disabled { color: #55627E; }"))
            b.move(int(c + self.R * math.cos(a) - 40), int(c + self.R * math.sin(a) - 40))
            b.clicked.connect(lambda _=False, act=act: self._go(act))
            self.buttons.append(b)

    def _go(self, act):
        self.close()
        QTimer.singleShot(0, act.trigger)

    def popup_at(self, global_pt):
        self.move(global_pt - QPoint(self.SIZE // 2, self.SIZE // 2))
        self.show()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        p.setPen(QPen(QColor(tc("#2E3A56")), 1))
        p.setBrush(QColor(10, 14, 23, 225))
        p.drawEllipse(c, 148, 148)
        p.setBrush(QColor(tc("#0D1320")))
        p.drawEllipse(c, 46, 46)
        p.setPen(QColor(tc("#C9D3E6")))
        p.setFont(style.ui_font(8, QFont.Weight.Bold))
        p.drawText(QRectF(c.x() - 44, c.y() - 20, 88, 40), Qt.AlignCenter | Qt.TextWordWrap, self.title)
        p.end()


# ============================================================ strati come «ricette»
class _ClickFrame(QFrame):
    """Riquadro che si comporta come un pulsante (clic o Invio/spazio) ma calcola l'altezza dal contenuto."""

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.setFocusPolicy(Qt.StrongFocus)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            QTimer.singleShot(0, self._fn)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            QTimer.singleShot(0, self._fn)
            return
        super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        fn = getattr(self, "_dbl", None)
        if fn is not None and e.button() == Qt.LeftButton:
            QTimer.singleShot(0, fn)
            return
        super().mouseDoubleClickEvent(e)


class LayerRail(QWidget):
    def __init__(self, win):
        super().__init__(win.canvas)
        self.win, self.ed = win, win.editor
        self.open_index = None
        self.compact = win.qs.value("banco_rail_compact", "false") in (True, "true")
        self._pending = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.title = _label(tr("STRATI · IN ORDINE DI LAVORO"), "bcSection")
        head.addWidget(self.title, 1)
        self.b_compact = QToolButton()
        self.b_compact.setObjectName("bcChip")
        self.b_compact.setCursor(Qt.PointingHandCursor)
        self.b_compact.clicked.connect(self.toggle_compact)
        head.addWidget(self.b_compact)
        v.addLayout(head)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.inner = QWidget()
        self.box = QVBoxLayout(self.inner)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)
        self.area.setWidget(self.inner)
        v.addWidget(self.area, 1)
        self.foot = QWidget()
        fl = QVBoxLayout(self.foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        fl.addWidget(_chip(tr("Libreria materiali…"), win.material_library,
                           tr("Applica i valori di un materiale agli strati")))
        fl.addWidget(_chip(tr("Tabella completa degli strati"), lambda: win.banco.officina_show("layers")))
        v.addWidget(self.foot)
        self.ed.changed.connect(self.schedule)
        self.ed.selection_changed.connect(self.schedule)
        self.rebuild()

    def schedule(self):
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.rebuild)

    def toggle_compact(self):
        self.compact = not self.compact
        self.win.qs.setValue("banco_rail_compact", self.compact)
        self.rebuild()
        self.win.banco.relayout()

    def width_hint(self):
        return 64 if self.compact else 300

    def desired_height(self):
        """Solo l'altezza che serve: sotto le schede il piano resta cliccabile."""
        w = self.width_hint()

        def hfw(widget):
            lay = widget.layout()
            if lay is not None and lay.hasHeightForWidth():
                return lay.heightForWidth(w)
            return widget.sizeHint().height()

        h = max(self.title.sizeHint().height(), self.b_compact.sizeHint().height()) + 8 + hfw(self.inner) + 6
        if not self.compact:
            h += hfw(self.foot) + 8
        return h + 4

    def rebuild(self):
        self._pending = False
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.title.setVisible(not self.compact)
        self.foot.setVisible(not self.compact)
        self.b_compact.setText("»" if self.compact else "«")
        self.b_compact.setToolTip(tr("Allarga gli strati") if self.compact else tr("Riduci gli strati a una colonna di colori"))
        layers = [cs for cs in self.ed.doc.used_layers() if cs.index != TOOL_LAYER]
        if not layers and not self.compact:
            hint = _label(tr("Ancora nessuno strato. Disegna o importa qualcosa: ogni colore diventa uno strato, "
                             "con velocità, potenza e passate."), "bcMuted", True)
            card = QFrame()
            card.setObjectName("bcCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.addWidget(hint)
            self.box.addWidget(card)
        for cs in layers:
            self.box.addWidget(self._compact_card(cs) if self.compact else self._card(cs))
        self.box.addStretch(1)
        banco = getattr(self.win, "banco", None)
        if banco is not None:
            QTimer.singleShot(0, banco.relayout)

    def _compact_card(self, cs):
        b = QPushButton()
        b.setFixedSize(56, 52)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(f"{cs.label()} · {units.fmt(cs.speed)} · {cs.power_max:g}% · {cs.passes}×")
        b.setStyleSheet(css("QPushButton { background: #121826; border: 1px solid #263048; border-radius: 14px; } "
                        "QPushButton:hover { border-color: #4FB4FF; }"))
        sw = QLabel(b)
        sw.setGeometry(15, 13, 26, 26)
        sw.setStyleSheet(css(f"background: {cs.color}; border-radius: 8px;" + ("" if cs.output else "border: 2px dashed #94A0B8;")))
        sw.setAttribute(Qt.WA_TransparentForMouseEvents)

        def open_full():
            self.open_index = cs.index
            self.toggle_compact()
        b.clicked.connect(open_full)
        return b

    def _card(self, cs):
        from ..core.document import MODE_LABELS

        is_open = self.open_index == cs.index
        card = QFrame()
        card.setObjectName("bcCardOn" if is_open else "bcCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(8)
        head = _ClickFrame(lambda: self._toggle_open(cs.index))
        head.setObjectName("bcLayerHead")
        head.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        bar = QLabel()
        bar.setFixedSize(10, 34)
        bar.setStyleSheet(f"background: {cs.color}; border-radius: 5px;")
        txt = QVBoxLayout()
        txt.setSpacing(0)
        name = _label(cs.label(), "bcTitle")
        summ = _label(tr("{0} · {1:g}% · {2}×", units.fmt(cs.speed), cs.power_max, cs.passes)
                      + (tr(" · aria") if cs.air else "") + ("" if cs.output else tr(" · non inciso")), "bcMuted")
        txt.addWidget(name)
        txt.addWidget(summ)
        tag = _label(MODE_LABELS.get(cs.mode, cs.mode).upper(), "bcTag")
        for w in (bar, name, summ, tag):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(bar)
        hl.addLayout(txt, 1)
        hl.addWidget(tag)
        v.addWidget(head)
        if is_open:
            v.addWidget(self._editor(cs))
        return card

    def _toggle_open(self, idx):
        self.open_index = None if self.open_index == idx else idx
        self.rebuild()

    def _apply(self, idx, vals, label):
        def later():
            cs = self.ed.doc.layers.get(idx)
            if cs is None:
                return
            todo = {k: v for k, v in vals.items() if getattr(cs, k) != v}
            if not todo:
                return

            def do():
                for k, v in todo.items():
                    setattr(cs, k, v)
            self.ed.run(label, do)
        QTimer.singleShot(0, later)

    def _editor(self, cs):
        from ..core.document import MODE_LABELS

        w = QWidget()
        g = QVBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        mode = QComboBox()
        for k, lab in MODE_LABELS.items():
            mode.addItem(lab, k)
        mode.setCurrentIndex(max(0, mode.findData(cs.mode)))
        mode.activated.connect(lambda _i: self._apply(cs.index, {"mode": mode.currentData()}, tr("Modalità livello")))
        g.addWidget(mode)

        def slider_row(label, lo, hi, val, step, suffix, key, undo_label):
            box = QVBoxLayout()
            box.setSpacing(2)
            top = QHBoxLayout()
            top.addWidget(_label(label, "bcMuted"), 1)
            sp = units.SpeedIntSpin() if key == "speed" else QSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setValue(int(round(val)))
            sp.setSuffix(suffix)
            sp.setKeyboardTracking(False)
            sp.setFixedWidth(118)
            top.addWidget(sp)
            box.addLayout(top)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setSingleStep(step)
            sl.setValue(int(round(val)))
            sl.valueChanged.connect(lambda x: (sp.blockSignals(True), sp.setValue(x), sp.blockSignals(False)))
            sl.sliderReleased.connect(lambda: self._apply(cs.index, {key: float(sl.value())}, undo_label))
            sp.valueChanged.connect(lambda x: (sl.blockSignals(True), sl.setValue(x), sl.blockSignals(False),
                                               self._apply(cs.index, {key: float(x)}, undo_label)))
            box.addWidget(sl)
            return box

        g.addLayout(slider_row(tr("Velocità"), 10, 36000, cs.speed, 60 if units.per_s() else 100, units.suffix(), "speed",
                               tr("Velocità livello")))
        g.addLayout(slider_row(tr("Potenza"), 0, 100, cs.power_max, 1, " %", "power_max", tr("Potenza livello")))
        row = QHBoxLayout()
        row.addWidget(_label(tr("Passate"), "bcMuted"))
        ps = QSpinBox()
        ps.setRange(1, 99)
        ps.setValue(cs.passes)
        ps.setKeyboardTracking(False)
        ps.valueChanged.connect(lambda x: self._apply(cs.index, {"passes": int(x)}, tr("Passate livello")))
        row.addWidget(ps)
        row.addStretch(1)
        g.addLayout(row)
        checks = QHBoxLayout()
        out = QCheckBox(tr("Incidi"))
        out.setChecked(cs.output)
        out.toggled.connect(lambda x: self._apply(cs.index, {"output": bool(x)}, tr("Incidi livello")))
        air = QCheckBox(tr("Aria"))
        air.setChecked(cs.air)
        air.toggled.connect(lambda x: self._apply(cs.index, {"air": bool(x)}, tr("Aria livello")))
        checks.addWidget(out)
        checks.addWidget(air)
        checks.addStretch(1)
        g.addLayout(checks)
        btns = QHBoxLayout()
        btns.addWidget(_chip(tr("Tutte le impostazioni…"), lambda: self._full(cs.index)))
        btns.addWidget(_chip(tr("Seleziona"), lambda: self._select(cs.index), tr("Seleziona le forme di questo strato")))
        g.addLayout(btns)
        return w

    def _full(self, idx):
        from .panels_design import CutSettingsDialog

        cs = self.ed.doc.layers.get(idx)
        if cs is None:
            return
        dlg = CutSettingsDialog(cs, self.win.profile, self.win)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.values()

            def do():
                for k, v in vals.items():
                    setattr(cs, k, v)
            self.ed.run(tr("Impostazioni di taglio"), do)

    def _select(self, idx):
        shapes = [s for s in self.ed.doc.shapes if any(leaf.layer == idx for leaf, _ in s.leaves())]
        self.ed.select(shapes)


# ============================================================ percorso «dal disegno al pezzo»
class JobFlow(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("bcCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(10)
        v.addWidget(_label(tr("DAL DISEGNO AL PEZZO"), "bcSection"))
        self.steps = []
        for n in range(4):
            row = QHBoxLayout()
            row.setSpacing(10)
            dot = QLabel(str(n + 1))
            dot.setFixedSize(24, 24)
            dot.setAlignment(Qt.AlignCenter)
            col = QVBoxLayout()
            col.setSpacing(1)
            t = _label("", "bcTitle")
            d = _label("", "bcMuted", True)
            col.addWidget(t)
            col.addWidget(d)
            row.addWidget(dot, 0, Qt.AlignTop)
            row.addLayout(col, 1)
            v.addLayout(row)
            self.steps.append((dot, t, d))
            if n == 1:
                r2 = QHBoxLayout()
                r2.addWidget(_chip(tr("Materiali…"), win.material_library))
                r2.addWidget(_chip(tr("Test materiale…"), win.material_test))
                v.addLayout(r2)
            if n == 2:
                r3 = QHBoxLayout()
                r3.addWidget(_chip(tr("Anteprima"), win.preview_job, tr("Simula il percorso del laser e calcola il tempo")))
                self.b_verify = _chip(tr("Verifica"), win.verify_job, tr("La scheda controlla tutto il G-code prima di partire"))
                r3.addWidget(self.b_verify)
                v.addLayout(r3)
            if n == 3:
                r4 = QHBoxLayout()
                self.b_frame = _chip(tr("Contorno"), lambda: win.frame_job("box"), tr("La testa percorre il bordo del lavoro"))
                r4.addWidget(self.b_frame)
                r4.addWidget(_chip(tr("Camera"), lambda: win.banco.officina_show("camera")))
                r4.addWidget(_chip(tr("Origine"), lambda: win.banco.officina_show("laser"),
                                   tr("Da dove parte il lavoro: piano, posizione attuale, origine utente")))
                v.addLayout(r4)
        safety = QFrame()
        safety.setStyleSheet(css("QFrame { background: #0D1320; border-radius: 12px; }"))
        sl = QVBoxLayout(safety)
        sl.setContentsMargins(10, 8, 10, 8)
        self.c_glasses = QCheckBox(tr("Occhiali protettivi indossati"))
        self.c_air = QCheckBox(tr("Aria e aspirazione accese"))
        for c in (self.c_glasses, self.c_air):
            c.toggled.connect(self.refresh)
            sl.addWidget(c)
        sl.addWidget(_chip(tr("Guardia fiamme…"), win.fire_guard_dialog,
                           tr("La camera sorveglia il lavoro e lo ferma se vede una fiamma (spenta di partenza)")))
        sl.addWidget(_chip(tr("Controllo dal telefono…"), win.phone_dialog,
                           tr("Pausa, stop, avanzamento e camera dal telefono sulla rete di casa")))
        v.addWidget(safety)
        self.b_start = HoldButton(tr("Tieni premuto per incidere"))
        self.b_start.setObjectName("bcStart")
        self.b_start.setCursor(Qt.PointingHandCursor)
        self.b_start.held.connect(self._start)
        self.b_start.clicked.connect(self._click_start)
        v.addWidget(self.b_start)
        self.note = _label("", "bcMuted", True)
        self.note.setAlignment(Qt.AlignCenter)
        v.addWidget(self.note)
        win.editor.changed.connect(self.refresh)
        win.ctl.connection_changed.connect(lambda *_: self.refresh())
        win.ctl.job_finished.connect(lambda *_: self.refresh())
        self._timer = QTimer(self)  # tempo stimato dopo un'anteprima, stato della macchina
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1500)
        self.refresh()

    def _click_start(self):
        if not self.win.ctl.connected:
            self.win.toggle_connection()

    def _start(self):
        if self.win.ctl.connected and self.c_glasses.isChecked() and self.c_air.isChecked():
            self.win.start_job()

    def _set(self, n, state, title, text):
        dot, t, d = self.steps[n]
        colors = {"ok": ("#3DD68C", "✓"), "todo": ("#FFB37A", str(n + 1)), "warn": ("#E5484D", "!")}
        col, sym = colors[state]
        dot.setText(sym)
        dot.setStyleSheet(f"background: {col}; color: #0B0B0B; border-radius: 12px; font-weight: 800;")  # testo scuro sul pallino colorato, in entrambi i temi
        t.setText(title)
        d.setText(text)

    def refresh(self, *_):
        win = self.win
        doc = win.editor.doc
        shapes = [s for s in doc.shapes if not s.hidden]
        layers = [cs for cs in doc.used_layers() if cs.index != TOOL_LAYER]
        out = [cs for cs in layers if cs.output]
        if not shapes:
            self._set(0, "todo", tr("Disegno"), tr("Ancora vuoto: disegna, scrivi o importa (Ctrl+I)"))
        else:
            b = doc.bounds()
            inside = b.isNull() or (b.left() >= -0.01 and b.top() >= -0.01 and b.right() <= win.profile.bed_x + 0.01
                                    and b.bottom() <= win.profile.bed_y + 0.01)
            self._set(0, "ok" if inside else "warn", tr("Disegno"),
                      (tr("{0} oggetti su {1} strati", len(shapes), len(layers)) if len(layers) != 1
                       else tr("{0} oggetti su 1 strato", len(shapes)) if len(shapes) != 1 else tr("1 oggetto su 1 strato"))
                      + ("" if inside else tr(" · qualcosa esce dal piano")))
        if not out:
            self._set(1, "todo", tr("Strati e materiale"), tr("Nessuno strato da incidere"))
        else:
            self._set(1, "ok", tr("Strati e materiale"), (tr("{0} strati da incidere · valori dalla libreria o a mano", len(out)) if len(out) != 1
                       else tr("1 strato da incidere · valori dalla libreria o a mano")))
        job = win.job
        if job is not None and job.lines:
            self._set(2, "ok", tr("Controllo"), tr("Lavoro pronto · tempo stimato {0}", _hms(job.seconds)))
        else:
            self._set(2, "todo", tr("Controllo"), tr("Guarda l'anteprima: calcola percorso e tempo"))
        rot = win.rotary_settings() if hasattr(win, "rotary_settings") else None
        rot_txt = tr(" · rotativo attivo") if rot else ""
        if win.ctl.connected:
            self._set(3, "todo", tr("Posiziona sul materiale"), tr("Fai il contorno o guarda la foto del piano") + rot_txt)
        else:
            self._set(3, "warn", tr("Posiziona sul materiale"), tr("Laser non connesso") + rot_txt)
        connected = win.ctl.connected
        self.b_verify.setEnabled(connected)
        self.b_frame.setEnabled(connected)
        ready = connected and bool(out) and not win.ctl.job_active
        safe = self.c_glasses.isChecked() and self.c_air.isChecked()
        if not connected:
            self.b_start.setText(tr("Collega il laser"))
            self.b_start.setEnabled(True)
            self.note.setText(tr("Clic per connettere la macchina sull'ultima porta usata"))
        else:
            self.b_start.setText(tr("Tieni premuto per incidere"))
            self.b_start.setEnabled(ready and safe)
            self.note.setText(tr("Spunta le due voci di sicurezza per abilitare l'avvio") if not safe else
                              (tr("Tieni premuto un secondo: si apre la conferma finale") if ready else ""))


# ============================================================ barra contestuale accanto alla selezione
class ContextBar(QFrame):
    def __init__(self, win):
        super().__init__(win.canvas)
        self.win = win
        self.setObjectName("bcCtx")
        a = win.acts
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(4)
        win.removeToolBar(win.numeric)
        win.numeric.setParent(self)
        win.numeric.setStyleSheet("QToolBar { background: transparent; border: none; }")
        win.numeric.show()
        v.addWidget(win.numeric)
        row = QHBoxLayout()
        row.setSpacing(4)
        for k in ("duplicate", "group", "ungroup", "weld"):
            row.addWidget(_act_button(a[k], "bcTool", 18))
        row.addWidget(_sep())
        row.addWidget(_menu_button(tr("Allinea"), [a["align_left"], a["align_hcenter"], a["align_right"], None, a["align_top"],
                                                   a["align_vcenter"], a["align_bottom"], None, a["align_center"], None,
                                                   a["dist_h"], a["dist_v"], a["dist_hc"], a["dist_vc"], None,
                                                   a["same_w"], a["same_h"], None, a["distance"]]))
        row.addWidget(_menu_button(tr("Combina"), [a["union"], a["difference"], a["intersection"], a["xor"]]))
        row.addWidget(_menu_button(tr("Serie"), [a["grid_array"], a["circ_array"], a["along_path"]]))
        row.addWidget(_act_button(a["nest"], "bcTool", 18))
        row.addWidget(_act_button(a["offset"], "bcTool", 18))
        row.addWidget(_act_button(a["to_path"], "bcTool", 18))
        row.addWidget(_menu_button(tr("Altro"), [a["flip_h"], a["flip_v"], a["rot_cw"], a["rot_ccw"], None, a["front"], a["back"],
                                                 None, a["break"], a["join"], a["close_paths"], a["reverse"], a["duplicates"],
                                                 None, a["lock"], a["unlock"], None, a["fit_sel"]]))
        row.addStretch(1)
        row.addWidget(_act_button(a["delete"], "bcTool", 18))
        v.addLayout(row)
        self.hide()

    def place(self, canvas, rail_w, right_w):
        ed = self.win.editor
        if not ed.selection or self.win.banco.dragging or self.win.banco.locked():
            self.hide()
            return
        r = ed.selection_bounds()
        cv = canvas
        pts = [cv.to_view(QPointF(x, y)) for x in (r.left(), r.right()) for y in (r.top(), r.bottom())]
        off = cv.viewport().pos()
        left = min(p.x() for p in pts) + off.x()
        right = max(p.x() for p in pts) + off.x()
        top = min(p.y() for p in pts) + off.y()
        bottom = max(p.y() for p in pts) + off.y()
        self.adjustSize()
        w, h = self.sizeHint().width(), self.sizeHint().height()
        self.resize(w, h)
        x = int((left + right) / 2 - w / 2)
        y = int(bottom + 16)
        if y + h > cv.height() - 96:
            y = int(top - h - 16)
        y = max(8, min(y, cv.height() - h - 96))
        lo = RULER + 10 + rail_w + 12  # a destra degli strati
        hi = cv.width() - right_w - 14 - 12 - w  # a sinistra della colonna destra
        if hi >= lo:
            x = max(lo, min(x, hi))
        else:  # schermo stretto: meglio sopra lo spazio degli strati che sopra il percorso del lavoro
            x = max(RULER + 8, hi)
        self.move(x, y)
        self.show()
        self.raise_()


# ============================================================ cabina durante il lavoro
class Cockpit:
    def __init__(self, win):
        self.win = win
        cv = win.canvas
        self.top = QFrame(cv)
        self.top.setObjectName("bcCockpitTop")
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(16, 8, 16, 8)
        self.state = _label(tr("INCISIONE IN CORSO"))
        self.state.setStyleSheet(css("color: #FFD3B3; font-weight: 800; letter-spacing: 1px;"))
        self.detail = _label("")
        self.detail.setStyleSheet(css("color: #FFE8D6;"))
        tl.addWidget(self.state)
        tl.addSpacing(14)
        tl.addWidget(self.detail)
        self.side = QFrame(cv)
        self.side.setObjectName("bcCard")
        sv = QVBoxLayout(self.side)
        sv.setContentsMargins(16, 14, 16, 16)
        sv.setSpacing(10)
        sv.addWidget(_label(tr("TEMPO RIMANENTE"), "bcSection"))
        self.left = _label("—", "bcBig")
        self.left.setFont(style.mono_font(28))
        sv.addWidget(self.left)
        self.eta = _label("", "bcMuted")
        sv.addWidget(self.eta)
        self.lines = _label("", "bcMuted")
        self.lines.setFont(style.mono_font(8.5))
        sv.addWidget(self.lines)
        sv.addSpacing(6)
        sv.addWidget(_label(tr("REGOLA SENZA FERMARTI"), "bcSection"))
        self.ov = {}
        for kind, label in (("feed", tr("Velocità")), ("power", tr("Potenza"))):
            r = QHBoxLayout()
            r.addWidget(_label(label, "bcTitle"), 1)
            minus = QPushButton("−")
            minus.setObjectName("bcStep")
            minus.setToolTip(tr("Riduci del 10%"))
            plus = QPushButton("+")
            plus.setObjectName("bcStep")
            plus.setToolTip(tr("Aumenta del 10%") + "\n" + OVERRIDE_TIP[kind]())
            val = _label("100%")
            val.setFont(style.mono_font(11))
            val.setFixedWidth(60)
            val.setAlignment(Qt.AlignCenter)
            minus.clicked.connect(lambda _=False, k=kind: self._ov(k, -10))
            plus.clicked.connect(lambda _=False, k=kind: self._ov(k, +10))
            r.addWidget(minus)
            r.addWidget(val)
            r.addWidget(plus)
            sv.addLayout(r)
            self.ov[kind] = val
        self.b_air = QPushButton(tr("Aria"))
        self.b_air.setObjectName("bcChip")
        self.b_air.setCheckable(True)
        self.b_air.setMinimumHeight(40)
        self.b_air.clicked.connect(lambda: win.laser.b_air.toggle())
        win.laser.b_air.toggled.connect(self._air_state)
        sv.addWidget(self.b_air)
        self.bottom = QFrame(cv)
        self.bottom.setObjectName("bcIsland")
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(12)
        self.b_pause = QPushButton(tr("Pausa"))
        self.b_pause.setObjectName("bcPause")
        self.b_pause.setIcon(style.icon("pause", "#1A0E05"))
        self.b_pause.setIconSize(QSize(22, 22))
        self.b_pause.clicked.connect(lambda: win.laser.b_pause.toggle())
        win.laser.b_pause.toggled.connect(self._pause_state)
        self.b_stop = QPushButton(tr("Stop"))
        self.b_stop.setObjectName("bcStop")
        self.b_stop.setIcon(style.icon("stop", "#FFFFFF"))
        self.b_stop.setIconSize(QSize(20, 20))
        self.b_stop.clicked.connect(win.ctl.stop_job)
        bl.addWidget(self.b_pause)
        bl.addWidget(self.b_stop)
        self.widgets = (self.top, self.side, self.bottom)
        for w in self.widgets:
            w.hide()
        self._t0 = 0.0
        self._air_state(win.laser.b_air.isChecked())

    def _air_state(self, on):
        self.b_air.setChecked(bool(on))
        self.b_air.setText(tr("Aria accesa") if on else tr("Aria spenta"))

    def _pause_state(self, paused):
        self.b_pause.setText(tr("Riprendi") if paused else tr("Pausa"))
        self.b_pause.setIcon(style.icon("play" if paused else "pause", "#1A0E05"))
        self.state.setText(tr("IN PAUSA") if paused else tr("INCISIONE IN CORSO"))

    def _ov(self, kind, delta):
        lp = self.win.laser
        sl = lp.ov_speed if kind == "feed" else lp.ov_power
        val = max(10, min(200, sl.value() + delta))
        sl.setValue(val)
        lp._override(kind, val)  # come il cursore: sopra il 100% dice se la scheda può salire (0.17.2)
        self.ov[kind].setText(f"{val}%")

    def enter(self):
        self._t0 = time.time()
        lp = self.win.laser
        self.ov["feed"].setText(f"{lp.ov_speed.value()}%")
        self.ov["power"].setText(f"{lp.ov_power.value()}%")
        self._pause_state(lp.b_pause.isChecked())
        for w in self.widgets:
            w.show()
            w.raise_()

    def leave(self):
        for w in self.widgets:
            w.hide()

    def progress(self, done, total):
        pct = 100.0 * done / max(total, 1)
        doc = self.win.editor.doc
        i = doc.plate_index(getattr(self.win, "_job_plate", None))
        where = doc.plate_name(i) + " · " if i is not None and len(doc.plates) > 1 else ""  # quale piano di lavoro
        self.detail.setText(where + tr("{0:.0f}% · riga {1} di {2}", pct, done, total))
        self._place_top(self.win.canvas)
        if done:
            el = time.time() - self._t0
            rest = el / done * (total - done)
            self.left.setText(_hms(rest))
            self.eta.setText(tr("finisce verso le {0}", time.strftime("%H:%M", time.localtime(time.time() + rest))))
        self.lines.setText(tr("trascorso {0}", _hms(time.time() - self._t0)))

    def _place_top(self, cv):
        """La scritta «Incisione in corso» in alto al centro, ma mai sopra le linguette dei piani di lavoro."""
        self.top.adjustSize()
        x, y = (cv.width() - self.top.width()) // 2, RULER + 10
        bar = getattr(self.win, "plate_bar", None)
        if bar is not None and bar.isVisible():
            g = bar.geometry().translated(cv.viewport().pos())
            if g.right() + 12 > x and g.top() < y + self.top.height() and g.bottom() > y:
                x = g.right() + 12
                right = cv.width() - getattr(cv, "fit_insets", (0, 0, 0, 0))[2]
                if x + self.top.width() > right:  # tante linguette: la scritta va sotto, senza coprire i pannelli
                    x, y = (cv.width() - self.top.width()) // 2, g.bottom() + 8
        self.top.move(x, y)

    def place(self, cv, editing=False, above=None):
        """editing: si sta preparando un altro piano di lavoro; la scheda dei tempi si nasconde (lascia il posto
        alle proprietà) e Pausa/Stop salgono sopra la barra degli strumenti."""
        self._place_top(cv)
        self.side.setFixedWidth(300)
        self.side.adjustSize()
        self.side.move(cv.width() - 316, 70)
        self.side.setVisible(not editing)
        self.bottom.adjustSize()
        y = cv.height() - self.bottom.height() - 18
        if editing and above is not None:
            y = above - self.bottom.height() - 10
        self.bottom.move((cv.width() - self.bottom.width()) // 2, y)
        for w in (self.top, self.bottom):
            w.raise_()


# ============================================================ Officina (laser, camera, console…)
class Officina(QFrame):
    TABS = (("laser", "Laser", "laser"), ("move", "Movimento", "move"), ("camera", "Camera", "camera"),
            ("machine", "Macchina", "machine"), ("console", "Console", "console"), ("layers", "Strati (tabella)", "layers"))

    def __init__(self, win):
        super().__init__(win.canvas)
        self.win = win
        self.setObjectName("bcOfficina")
        self.window_mode = False
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = _label(tr("OFFICINA · laser, camera e macchina"), "bcSection")
        head.addWidget(self.title, 1)
        self.b_close = QToolButton()
        self.b_close.setObjectName("bcChip")
        self.b_close.setText("✕")
        self.b_close.setToolTip(tr("Chiudi l'Officina (resta tutto attivo)"))
        self.b_close.clicked.connect(self.hide_drawer)
        head.addWidget(self.b_close)
        v.addLayout(head)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.index = {}
        for key, title, icon in self.TABS:
            d = win.docks[key]
            w = d.widget()
            d.setWidget(QWidget())
            w.setParent(None)
            self.index[key] = self.tabs.addTab(w, style.icon(icon), tr(title))
        v.addWidget(self.tabs, 1)
        self.hide()

    def show_tab(self, key):
        if key in self.index:
            self.tabs.setCurrentIndex(self.index[key])
        self.show()
        self.raise_()
        if self.window_mode:
            self.activateWindow()
        else:
            self.win.banco.relayout()

    def hide_drawer(self):
        if self.window_mode:
            return
        self.hide()
        self.win.banco.relayout()

    def to_window(self, screen):
        self.window_mode = True
        self.hide()
        self.setParent(self.win, Qt.Window)
        self.setWindowTitle(tr("FreeLaserCut — Officina"))
        self.b_close.hide()
        self.title.setText(tr("OFFICINA · secondo monitor"))
        self.setStyleSheet(css("QFrame#bcOfficina { border-radius: 0; border: none; background: #0A0E17; }"))
        self.show()
        h = self.windowHandle()
        if h is not None:
            h.setScreen(screen)
        self.setGeometry(screen.availableGeometry())
        self.showMaximized()

    def to_drawer(self):
        if not self.window_mode:
            return
        self.window_mode = False
        self.hide()
        self.setParent(self.win.canvas, Qt.Widget)
        self.setStyleSheet("")
        self.b_close.show()
        self.title.setText(tr("OFFICINA · laser, camera e macchina"))
        self.hide()
        self.win.banco.relayout()

    def closeEvent(self, e):
        if self.window_mode:  # chiusa a mano sul secondo monitor: torna come cassetto
            e.ignore()
            self.win.banco.officina_screen = None
            QTimer.singleShot(0, self.to_drawer)
            return
        super().closeEvent(e)


# ============================================================ l'interfaccia Banco
class Banco(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.dragging = False
        self.cockpit_on = False
        self.officina_screen = None
        self._rpress = None
        cv = win.canvas
        win.setStyleSheet(win.styleSheet() + BANCO_QSS)
        # --- via la disposizione classica (i comandi restano tutti, anche le scorciatoie)
        # con la barra dei menu e le barre nascoste Qt non attiverebbe più le loro scorciatoie:
        # le azioni vengono agganciate anche alla finestra, così Ctrl+S, Ctrl+K, R, E… restano tutte vive
        keep = list(win.actions())

        def hook(menu):
            for a in menu.actions():
                if a.menu() is not None:
                    hook(a.menu())
                elif not a.isSeparator() and a not in keep:
                    keep.append(a)
                    win.addAction(a)

        for a in win.menuBar().actions():
            if a.menu() is not None:
                hook(a.menu())
        for tb in win.findChildren(QToolBar):
            if tb.parent() is win and tb is not win.numeric:
                for a in tb.actions():
                    if not a.isSeparator() and a not in keep and a.shortcut().toString():
                        keep.append(a)
                        win.addAction(a)
        win.menuBar().hide()
        for tb in win.findChildren(QToolBar):
            if tb.parent() is win and tb is not win.numeric:
                tb.hide()
        # --- pannelli: proprietà nella colonna destra, il resto nell'Officina
        self.props_card = QFrame()
        self.props_card.setObjectName("bcCard")
        pl = QVBoxLayout(self.props_card)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(4)
        self.props_title = _label(tr("PROPRIETÀ"), "bcSection")
        pl.addWidget(self.props_title)
        win.docks["props"].setWidget(QWidget())
        win.props.setParent(None)
        win.props.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        pl.addWidget(win.props, 1)
        win.props.show()
        self.officina = Officina(win)
        for d in win.docks.values():
            win.removeDockWidget(d)
            d.hide()
        win.show_panel = self._show_panel
        win.reset_layout = self.reset_layout
        # --- comandi in più del Banco
        self.act_palette = QAction(style.icon("zoom_in"), tr("Cerca un comando…"), win)
        self.act_palette.setShortcuts([QKeySequence("Ctrl+F"), QKeySequence("F3")])
        self.act_palette.triggered.connect(self.open_palette)
        win.addAction(self.act_palette)
        self.act_officina = QAction(style.icon("machine"), tr("Apri / chiudi l'Officina"), win)
        self.act_officina.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self.act_officina.triggered.connect(self.toggle_officina)
        win.addAction(self.act_officina)
        self.extra_actions = [(self.act_officina, tr("Banco"))]
        # --- barra superiore
        self._build_top()
        # --- sovrapposizioni sul piano
        self.rail = LayerRail(win)
        self.right = QWidget(cv)
        rv = QVBoxLayout(self.right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        rv.addWidget(self.props_card, 1)
        self.flow = JobFlow(win)
        rv.addWidget(self.flow, 0)
        self._build_island()
        self.ctx = ContextBar(win)
        self.cockpit = Cockpit(win)
        self.palette = CommandPalette(win)
        # --- collegamenti
        self._closing = False
        cv.installEventFilter(self)
        cv.viewport().installEventFilter(self)
        ed = win.editor
        ed.selection_changed.connect(self._sel_changed)
        ed.changed.connect(self._place_ctx_later)
        cv.zoom_changed.connect(lambda *_: self._place_ctx_later())
        cv.horizontalScrollBar().valueChanged.connect(lambda *_: self._place_ctx_later())
        cv.verticalScrollBar().valueChanged.connect(lambda *_: self._place_ctx_later())
        cv.tool_changed.connect(self._tool_changed)
        win.ctl.job_progress.connect(self._job_progress)
        win.ctl.job_finished.connect(self._job_finished)
        ed.plates_changed.connect(self._plate_changed)
        win.ctl.status_changed.connect(self._status)
        win.ctl.connection_changed.connect(lambda ok, msg: self._status(None))
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda *_: QTimer.singleShot(400, self.check_screens))
        app.screenRemoved.connect(lambda *_: QTimer.singleShot(400, self.check_screens))
        self._status(None)
        QTimer.singleShot(0, self.relayout)
        QTimer.singleShot(600, self.check_screens)

    # ---------------------------------------------------------- barra superiore
    def _build_top(self):
        win = self.win
        tb = QToolBar(tr("Banco"))
        tb.setObjectName("bcTopBar")
        tb.setMovable(False)
        tb.setFloatable(False)
        top = QFrame()
        top.setObjectName("bcTop")
        h = QHBoxLayout(top)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(style.ASSETS, "logo.svg")).pixmap(26, 26))
        h.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.proj = _label("", "bcTitle")
        self.proj_sub = _label("", "bcMuted")
        self.proj_sub.setFont(style.ui_font(7.5))
        col.addWidget(self.proj)
        col.addWidget(self.proj_sub)
        left = QWidget()
        left.setLayout(col)
        left.setMinimumWidth(220)
        h.addWidget(left)
        h.addStretch(1)
        self.search = QPushButton(tr("Cosa vuoi fare? Cerca tra tutti i comandi…") + "      Ctrl+F")
        self.search.setObjectName("bcSearch")
        self.search.setIcon(style.icon("zoom_in", tc("#94A0B8")))
        self.search.setCursor(Qt.PointingHandCursor)
        self.search.setMinimumWidth(420)
        self.search.setMaximumWidth(560)
        self.search.clicked.connect(self.open_palette)
        h.addWidget(self.search, 2)
        h.addStretch(1)
        self.pill = QPushButton()
        self.pill.setObjectName("bcPill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip(tr("Clic: connetti / disconnetti il laser"))
        self.pill.clicked.connect(lambda: win.toggle_connection())
        h.addWidget(self.pill)
        self.b_off = QPushButton(tr("Officina"))
        self.b_off.setObjectName("bcChip")
        self.b_off.setIcon(style.icon("machine"))
        self.b_off.setToolTip(tr("Laser, movimento, camera, macchina e console (Ctrl+Shift+W)"))
        self.b_off.clicked.connect(self.toggle_officina)
        h.addWidget(self.b_off)
        gear = QToolButton()
        gear.setObjectName("bcChip")
        gear.setIcon(style.icon("settings"))
        gear.setToolTip(tr("Impostazioni: interfaccia, lingua, vista"))
        gear.setPopupMode(QToolButton.InstantPopup)
        gear.setMenu(win.m_settings)
        h.addWidget(gear)
        self.gear = gear
        help_b = QToolButton()
        help_b.setObjectName("bcChip")
        help_b.setDefaultAction(win.acts["help_mode"])
        help_b.setProperty("help_toggle", True)
        h.addWidget(help_b)
        sup = QPushButton(tr("Sostieni"))
        sup.setObjectName("bcSupport")
        sup.setIcon(style.icon("heart", color="#E5484D", active="#E5484D"))
        sup.setIconSize(QSize(13, 13))
        sup.setCursor(Qt.PointingHandCursor)
        sup.setToolTip(tr("Sostieni FreeLaserCut: contributo volontario allo sviluppo"))
        sup.clicked.connect(win.show_support)
        h.addWidget(sup)
        self.support = sup
        tb.addWidget(top)
        win.addToolBar(Qt.TopToolBarArea, tb)
        self.topbar = tb
        win.editor.history_changed.connect(self._update_project)
        win.editor.changed.connect(self._update_project)
        self._update_project()

    def _update_project(self, *_):
        d = self.win.editor.doc
        name = os.path.basename(d.path) if d.path else d.name
        self.proj.setText(name)
        self.proj_sub.setText(tr("modifiche non salvate") if self.win.editor.dirty else
                              (tr("salvato") if d.path else tr("nuovo progetto")))

    def _status(self, st):
        from .main_window import STATE_IT

        ctl = self.win.ctl
        if not ctl.connected:
            self.pill.setText(tr("○  Laser non connesso"))
            self.pill.setStyleSheet(css("QPushButton#bcPill { background: #161B26; border: 1px solid #2A3550; color: #C9D3E6; }"))
            return
        st = st or getattr(ctl, "last_status", None) or {}
        state = st.get("state", "Idle") if isinstance(st, dict) else "Idle"
        pos = st.get("MPos") if isinstance(st, dict) else None
        name = getattr(self.win.profile, "name", "")
        txt = f"●  {name} · {STATE_IT.get(state, state)}"
        if pos:
            try:
                bx, by = self.win.profile.to_bed(pos[0], pos[1])
                txt += f"   X {bx:.1f}  Y {by:.1f}"
            except Exception:  # noqa: BLE001
                pass
        self.pill.setText(txt)
        col = {"Alarm": ("#3A1418", "#E5484D", "#FFD9DA"), "Run": ("#3A1D08", ORANGE, "#FFD3B3"),
               "Hold": ("#3A2A0A", "#F5A524", "#FFE8B8")}.get(state, ("#0F2A1E", "#1D5A3C", "#BFF2D6"))
        col = tuple(tc(x) for x in col)
        self.pill.setStyleSheet(f"QPushButton#bcPill {{ background: {col[0]}; border: 1px solid {col[1]}; color: {col[2]}; }}")

    # ---------------------------------------------------------- isola degli strumenti
    def _build_island(self):
        win = self.win
        f = QFrame(win.canvas)
        f.setObjectName("bcIsland")
        h = QHBoxLayout(f)
        h.setContentsMargins(8, 7, 8, 7)
        h.setSpacing(3)
        for k in ("undo", "redo"):
            h.addWidget(_act_button(win.acts[k]))
        h.addWidget(_sep())
        for name in ("select", "nodes", "trim", "line", "rect", "ellipse", "polygon", "star", "special", "text"):
            h.addWidget(_act_button(win.tool_actions[name]))
        h.addWidget(_sep())
        for k in ("import", "photo", "trace", "exact_shape", "code", "text_path", "puzzle", "sculpt", "variables"):
            h.addWidget(_act_button(win.acts[k]))
        h.addWidget(_sep())
        for name in ("measure", "position"):
            h.addWidget(_act_button(win.tool_actions[name]))
        h.addWidget(_sep())
        self.tool_label = _label("", "bcMuted")
        self.tool_label.setMinimumWidth(150)
        self.tool_label.setAlignment(Qt.AlignCenter)
        h.addWidget(self.tool_label)
        self.island = f
        g = QFrame(win.canvas)  # vista, in basso a destra
        g.setObjectName("bcIsland")
        gh = QHBoxLayout(g)
        gh.setContentsMargins(6, 6, 6, 6)
        gh.setSpacing(3)
        for k in ("zoom_out", "fit", "zoom_in"):
            gh.addWidget(_act_button(win.acts[k], "bcTool", 18))
        self.view_box = g
        self.hint = _label(tr("Tasto destro sul piano: menu radiale · Ctrl+F: tutti i comandi"), "bcMuted")
        self.hint.setParent(win.canvas)
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hint.setFont(style.ui_font(7.5))
        self._update_tool_label()

    def current_tool(self):
        cv = self.win.canvas
        return next((k for k, v in cv.tools.items() if v is cv.tool), "select")

    def _update_tool_label(self):
        act = self.win.tool_actions.get(self.current_tool())
        self.tool_label.setText(_clean(act.text()).split(":")[0] if act else "")

    def _tool_changed(self, name):
        self._update_tool_label()
        QTimer.singleShot(0, self.relayout)

    # ---------------------------------------------------------- disposizione
    def relayout(self):
        cv = self.win.canvas
        W, H = cv.width(), cv.height()
        top_pad = RULER + 10  # i pannelli non coprono i righelli
        rail_w = self.rail.width_hint()
        self.rail.setGeometry(RULER + 10, top_pad + 4, rail_w, min(self.rail.desired_height(), max(160, H - top_pad - 20 - 110)))
        right_w = 300
        drawer = self.officina.isVisible() and not self.officina.window_mode
        if drawer:
            self.officina.setGeometry(W - OFF_W - 14, top_pad, OFF_W, H - top_pad - 96)
            self.officina.raise_()
        props_on = self._props_visible()
        self.props_card.setVisible(props_on)
        full_h = H - top_pad - 96
        lay = self.flow.layout()
        flow_h = lay.heightForWidth(right_w) if lay is not None and lay.hasHeightForWidth() else self.flow.sizeHint().height()
        flow_h = min(flow_h, full_h)
        self.flow.setFixedHeight(flow_h)  # il percorso del lavoro non si schiaccia mai
        right_h = flow_h
        if props_on:  # le proprietà prendono solo lo spazio che serve (al massimo quello che resta)
            host = self.win.props.widget()
            hl = host.layout() if host is not None else None
            inner = (hl.heightForWidth(right_w - 16) if hl is not None and hl.hasHeightForWidth()
                     else host.sizeHint().height() if host is not None else 200)
            need = 8 + self.props_title.sizeHint().height() + 4 + inner + 8
            props_h = max(90, min(need + 4, full_h - flow_h - 10))
            self.props_card.setFixedHeight(props_h)
            right_h = props_h + 10 + flow_h
        self.right.setGeometry(W - right_w - 14, top_pad, right_w, right_h)
        locked = self.locked()
        self.right.setVisible(not drawer and not locked)
        self.island.adjustSize()
        self.island.move((W - self.island.width()) // 2, H - self.island.height() - 16)
        self.view_box.adjustSize()
        self.view_box.move(W - self.view_box.width() - 14, H - self.view_box.height() - 16)
        self.hint.adjustSize()
        self.hint.move((W - self.hint.width()) // 2, self.island.y() - self.hint.height() - 6)
        for w in (self.island, self.view_box):
            w.setVisible(not locked)
            w.raise_()
        self.hint.setVisible(not self.cockpit_on and W > 900)
        self.rail.setVisible(not locked)
        cv.fit_insets = (rail_w + 24, 0, (OFF_W if drawer else right_w) + 24, 110)
        if getattr(self.win, "plate_bar", None) is not None:
            QTimer.singleShot(0, self.win.plate_bar, self.win.plate_bar.place)  # linguette dei piani fuori dai pannelli
        if not getattr(cv, "_user_zoomed", False):
            cv.fit_bed()
        if self.cockpit_on:
            self.cockpit.place(cv, editing=not locked, above=self.island.y())
        self._place_ctx()

    def locked(self):
        """Durante l'incisione il piano in lavoro non si tocca col mouse (cabina di comando). Su un altro piano di
        lavoro invece si disegna: restano in vista solo l'avanzamento in alto e Pausa/Stop."""
        if not self.cockpit_on:
            return False
        uid = getattr(self.win, "_job_plate", None)
        return uid is None or self.win.editor.doc.plate.uid == uid

    def _plate_changed(self):
        if self.cockpit_on:
            self.relayout()

    def _props_visible(self):
        return bool(self.win.editor.selection) or self.current_tool() in ("rect", "ellipse", "polygon", "star", "special", "text")

    def _place_ctx_later(self, *_):
        QTimer.singleShot(0, self._place_ctx)

    def _place_ctx(self):
        drawer = self.officina.isVisible() and not self.officina.window_mode
        self.ctx.place(self.win.canvas, self.rail.width_hint(), OFF_W if drawer else 300)

    def _sel_changed(self):
        QTimer.singleShot(0, self.relayout)  # le proprietà cambiano altezza con la selezione
        self._place_ctx_later()

    # ---------------------------------------------------------- eventi sul piano: tasto destro, trascinamenti
    def eventFilter(self, obj, e):
        if self._closing:
            return False
        try:
            cv = self.win.canvas
            vp = cv.viewport()
        except RuntimeError:  # finestra già distrutta (uscita dal programma)
            self._closing = True
            return False
        t = e.type()
        if obj is cv and t == QEvent.Resize:
            QTimer.singleShot(0, self.relayout)
        elif obj is vp:
            if t == QEvent.MouseButtonPress:
                if self.locked() and e.button() == Qt.LeftButton:
                    return True  # durante il lavoro il piano non si modifica col mouse
                if e.button() == Qt.LeftButton:
                    self.dragging = True
                    self.ctx.hide()
                if e.button() == Qt.RightButton:
                    self._rpress = e.position()
            elif t == QEvent.MouseButtonRelease:
                if e.button() == Qt.LeftButton and self.dragging:
                    self.dragging = False
                    self._place_ctx_later()
                if e.button() == Qt.RightButton and not self.locked():
                    p0 = self._rpress
                    if p0 is not None and self.current_tool() in ("select", "nodes") \
                            and (e.position() - p0).manhattanLength() < 6:
                        self.open_radial(e.position(), e.globalPosition().toPoint())
                        return True
        return False

    def radial_items(self, view_pt=None):
        win, ed, cv = self.win, self.win.editor, self.win.canvas
        a = win.acts
        if view_pt is not None:
            hit = cv.hit_shape(cv.to_bed(view_pt))
            if hit is not None and hit not in ed.selection:
                ed.select([hit])
        if ed.selection:
            n = len(ed.selection)
            title = tr("{0} oggetti", n) if n > 1 else tr("Selezione")
            items = [(tr("Duplica"), a["duplicate"]),
                     (tr("Raggruppa"), a["group"]) if n > 1 else (tr("Separa"), a["ungroup"]),
                     (tr("Offset"), a["offset"]), (tr("Serie"), a["grid_array"]), (tr("In tracciato"), a["to_path"]),
                     (tr("Rifletti"), a["flip_h"]), (tr("Elimina"), a["delete"]), (tr("Inquadra"), a["fit_sel"])]
        else:
            title = tr("Piano")
            items = [(tr("Incolla"), a["paste"]), (tr("Tutto"), a["select_all"]), (tr("Forme"), win.tool_actions["special"]),
                     (tr("Testo"), win.tool_actions["text"]), (tr("Importa"), a["import"]), (tr("Annulla {0}", "").strip(), a["undo"]),
                     (tr("Ottimizza"), a["nest"]), (tr("Adatta"), a["fit"])]
        return title, items

    def open_radial(self, view_pt, global_pt):
        title, items = self.radial_items(view_pt)
        m = RadialMenu(self.win, title, items)
        m.popup_at(global_pt)
        self.radial = m
        return m

    # ---------------------------------------------------------- comandi
    def open_palette(self):
        self.palette.open()

    def toggle_officina(self):
        if self.officina.window_mode:
            self.officina.show()
            self.officina.raise_()
            self.officina.activateWindow()
            return
        if self.officina.isVisible():
            self.officina.hide_drawer()
        else:
            self.officina.show_tab(self.officina_current())

    def officina_current(self):
        for k, i in self.officina.index.items():
            if i == self.officina.tabs.currentIndex():
                return k
        return "laser"

    def officina_show(self, key):
        self.officina.show_tab(key)

    def _show_panel(self, dock):
        for key, d in self.win.docks.items():
            if d is dock:
                if key == "props":
                    self.relayout()
                else:
                    self.officina_show(key)
                return

    def reset_layout(self):
        self.win.canvas._user_zoomed = False
        if self.officina.isVisible() and not self.officina.window_mode:
            self.officina.hide_drawer()
        self.relayout()

    # ---------------------------------------------------------- secondo monitor
    def check_screens(self):
        win = self.win
        if win.qs.value("officina_second_screen", "true") not in (True, "true"):
            if self.officina.window_mode:
                self.officina.to_drawer()
            return
        mine = win.screen() or QGuiApplication.primaryScreen()
        others = [s for s in QGuiApplication.screens() if mine is None or s.name() != mine.name()]
        if others and not self.officina.window_mode:
            self.officina_screen = others[0]
            self.officina.to_window(others[0])
            self.relayout()
        elif not others and self.officina.window_mode:
            self.officina.to_drawer()

    def shutdown(self):
        """Alla chiusura del programma: l'Officina sul secondo monitor si chiude con la finestra principale."""
        self._closing = True
        try:
            self.win.canvas.removeEventFilter(self)
            self.win.canvas.viewport().removeEventFilter(self)
        except RuntimeError:
            pass
        if self.officina.window_mode:
            self.officina.window_mode = False
            self.officina.hide()
        self.palette.hide()

    # ---------------------------------------------------------- cabina
    def _job_progress(self, done, total):
        if self.win.ctl.job_active and not self.cockpit_on:
            self.cockpit_on = True
            self.ctx.hide()
            self.cockpit.enter()
            self.relayout()
        if self.cockpit_on:
            self.cockpit.progress(done, total)

    def _job_finished(self, ok, msg):
        if self.cockpit_on:
            self.cockpit_on = False
            self.cockpit.leave()
            self.relayout()
