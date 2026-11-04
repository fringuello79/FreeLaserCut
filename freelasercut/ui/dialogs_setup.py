# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Impostazioni → Configurazione guidata della macchina (anche al primo avvio).

Poche domande: il modello, l'angolo in cui sta lo 0 della macchina e, se il laser è collegato, la prova delle
frecce. Da lì FreeLaserCut ricava il verso degli assi, così testa e lavoro compaiono nel punto giusto del piano.
Alla fine: nomi sotto i comandi oppure modalità esperto. Si può rifare quando si vuole."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QRadioButton, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import machines
from ..profile import MachineProfile
from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

CORNERS = {"bl": tr("dietro a sinistra"), "br": tr("dietro a destra"), "fl": tr("davanti a sinistra"),
           "fr": tr("davanti a destra")}
STEP_MM = 10.0
JOG_FEED = 1500


def corner_name(corner):
    return CORNERS.get(corner or "fl", CORNERS["fl"])


class CornerPicker(QWidget):
    """Il piano visto dall'alto, con i quattro angoli da cliccare. In alto il fondo della macchina."""

    changed = Signal(str)
    W, H = 320, 220

    def __init__(self, corner="fl", parent=None):
        super().__init__(parent)
        self.corner = corner if corner in CORNERS else "fl"
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)

    def _bed(self):
        return QRectF(40, 26, self.W - 80, self.H - 56)

    def _points(self):
        r = self._bed()
        return {"bl": r.topLeft(), "br": r.topRight(), "fl": r.bottomLeft(), "fr": r.bottomRight()}

    def set_corner(self, c):
        if c in CORNERS and c != self.corner:
            self.corner = c
            self.update()
            self.changed.emit(c)

    def mousePressEvent(self, e):
        pos = e.position()
        best = min(self._points().items(), key=lambda kv: (kv[1] - pos).manhattanLength())
        self.set_corner(best[0])

    def paint_corner(self, p, pt, on):
        col = QColor(C["accent"]) if on else QColor(C["muted"])
        p.setPen(QPen(col, 2))
        p.setBrush(col if on else Qt.NoBrush)
        p.drawEllipse(pt, 11 if on else 8, 11 if on else 8)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._bed()
        pal = self.palette()
        p.setPen(QPen(QColor(C["muted"]), 1.5))
        p.setBrush(pal.color(QPalette.Base))
        p.drawRoundedRect(r, 6, 6)
        p.setFont(style.ui_font(8))
        p.setPen(pal.color(QPalette.WindowText))
        p.drawText(QRectF(0, 2, self.W, 20), Qt.AlignCenter, tr("DIETRO (fondo della macchina)"))
        p.drawText(QRectF(0, self.H - 24, self.W, 20), Qt.AlignCenter, tr("DAVANTI (verso di te)"))
        for c, pt in self._points().items():
            self.paint_corner(p, pt, c == self.corner)
        # piccola testa nell'angolo scelto
        pt = self._points()[self.corner]
        p.setPen(QPen(QColor(C["accent_hi"]), 2))
        p.setBrush(Qt.NoBrush)
        inward = QPointF(18 if "l" in self.corner[1:] else -18, 18 if self.corner[0] == "b" else -18)
        p.drawText(QRectF(pt.x() + inward.x() - 40, pt.y() + inward.y() - 8, 80, 16), Qt.AlignCenter, "0,0")
        p.end()


def _title(text):
    lab = QLabel(f"<b>{text}</b>")
    lab.setStyleSheet("font-size: 13pt;")
    return lab


def _text(html):
    lab = QLabel(html)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.RichText)
    return lab


class SetupWizard(QDialog):
    """main: MainWindow. first=True al primo avvio (il pulsante per uscire diventa «Più tardi»)."""

    def __init__(self, main, first=False):
        super().__init__(main)
        self.main, self.first = main, first
        self.setWindowTitle(tr("Configurazione guidata della macchina"))
        self.setMinimumWidth(560)
        p = main.profile
        self.tested = [False, False]
        self.inv = [p.invert_x, p.invert_y]
        self._sign_before = tuple(getattr(main.ctl, "axis_sign", (1.0, 1.0)))
        v = QVBoxLayout(self)
        self.step_lab = QLabel()
        self.step_lab.setObjectName("muted")
        v.addWidget(self.step_lab)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self._page_model(p)
        self._page_corner(p)
        self._page_arrows()
        self._page_end()
        row = QHBoxLayout()
        self.b_skip = QPushButton(tr("Più tardi") if first else tr("Annulla"))
        self.b_skip.clicked.connect(self.reject)
        row.addWidget(self.b_skip)
        row.addStretch(1)
        self.b_back = QPushButton(tr("Indietro"))
        self.b_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        row.addWidget(self.b_back)
        self.b_next = QPushButton(tr("Avanti"))
        self.b_next.setObjectName("primary")
        self.b_next.setDefault(True)
        self.b_next.clicked.connect(self._next)
        row.addWidget(self.b_next)
        v.addLayout(row)
        self.go(0)

    # ------------------------------------------------------------------ pagine
    def _page_model(self, p):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title(tr("Quale laser hai?")))
        v.addWidget(_text(tr("Scegli il modello: FreeLaserCut prende area di lavoro e velocità di targa. Se il tuo non c'è, "
                             "scegli l'ultima voce: i valori veri si leggono dalla scheda quando la colleghi.")))
        self.model = QComboBox()
        names = machines.catalog_names()
        self.model.addItems(names)
        cur = p.model if p.model in names else (p.name if p.name in names else None)
        if cur:
            self.model.setCurrentText(cur)
        self.model.currentTextChanged.connect(self._model_changed)
        v.addWidget(self.model)
        self.model_note = _text("")
        self.model_note.setObjectName("muted")
        v.addWidget(self.model_note)
        v.addStretch(1)
        self.stack.addWidget(w)
        self._model_changed(self.model.currentText())

    def _model_changed(self, name):
        self.model_note.setText(machines.NOTES.get(name, ""))

    def _page_corner(self, p):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title(tr("Dov'è lo 0 della tua macchina?")))
        v.addWidget(_text(tr("Clicca l'angolo del piano in cui va la testa con l'<b>homing</b>. Se la macchina non ha "
                             "l'homing, è l'angolo da cui parte: lì va messa la testa prima di accenderla.<br>"
                             "Quasi tutti i laser a diodo hanno lo 0 <b>davanti a sinistra</b>; molte schede MKS DLC32 "
                             "<b>dietro a sinistra</b>.")))
        h = QHBoxLayout()
        h.addStretch(1)
        self.picker = CornerPicker(p.corner_now())
        self.picker.changed.connect(lambda c: self.corner_lab.setText(tr("Lo 0 è {0}.", corner_name(c))))
        h.addWidget(self.picker)
        h.addStretch(1)
        v.addLayout(h)
        r = QHBoxLayout()
        self.corner_lab = QLabel(tr("Lo 0 è {0}.", corner_name(self.picker.corner)))
        r.addWidget(self.corner_lab, 1)
        b = QPushButton(tr("Non lo so"))
        b.setToolTip(tr("Lascia davanti a sinistra, come la maggior parte dei laser: lo confermi con la prova delle frecce"))
        b.clicked.connect(lambda: self.picker.set_corner("fl"))
        r.addWidget(b)
        v.addLayout(r)
        self.stack.addWidget(w)

    def _page_arrows(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title(tr("Prova delle frecce")))
        self.arrows_intro = _text("")
        v.addWidget(self.arrows_intro)
        self.arrows_box = QWidget()
        g = QGridLayout(self.arrows_box)
        self.b_arrow = {}
        for key, text, row, col in (("up", tr("↑ verso il fondo"), 0, 1), ("left", tr("← sinistra"), 1, 0),
                                    ("right", tr("destra →"), 1, 2), ("down", tr("↓ verso di te"), 2, 1)):
            b = QPushButton(text)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, k=key: self.jog(k))
            g.addWidget(b, row, col)
            self.b_arrow[key] = b
        self.fix_x = QPushButton(tr("Sinistra–destra al contrario: correggi"))
        self.fix_x.clicked.connect(lambda: self.fix(0))
        self.fix_y = QPushButton(tr("Fondo–davanti al contrario: correggi"))
        self.fix_y.clicked.connect(lambda: self.fix(1))
        g.addWidget(self.fix_x, 3, 0, 1, 3)
        g.addWidget(self.fix_y, 4, 0, 1, 3)
        v.addWidget(self.arrows_box)
        self.arrows_lab = _text("")
        v.addWidget(self.arrows_lab)
        v.addStretch(1)
        self.stack.addWidget(w)

    def _page_end(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title(tr("Ultima cosa: quanto aiuto vuoi sullo schermo?")))
        self.summary = _text("")
        v.addWidget(self.summary)
        self.levels = {}
        grp = QButtonGroup(self)
        for lv, text in (("principiante", tr("<b>Principiante</b>: nomi sotto i comandi e accanto ai segni del piano, "
                                             "spiegazioni e suggerimenti")),
                         ("normale", tr("<b>Normale</b>: solo icone; spiegazioni passando sui segni e suggerimenti")),
                         ("esperto", tr("<b>Esperto</b>: niente nomi, spiegazioni né suggerimenti (gli avvisi di "
                                        "sicurezza restano sempre)"))):
            b = QRadioButton()
            row = QHBoxLayout()
            row.addWidget(b)
            lab = _text(text)
            lab.mousePressEvent = lambda _e, bb=b: bb.setChecked(True)
            row.addWidget(lab, 1)
            grp.addButton(b)
            v.addLayout(row)
            self.levels[lv] = b
        self.levels[self.main.help_level()].setChecked(True)
        v.addWidget(_text(tr("Puoi cambiare tutto quando vuoi: <i>Impostazioni → Configurazione guidata della macchina</i> "
                             "e <i>Impostazioni → Livello di aiuto</i>.")))
        v.addStretch(1)
        self.stack.addWidget(w)

    # ------------------------------------------------------------------ navigazione
    def _can_jog(self):
        ctl = self.main.ctl
        return bool(ctl.connected) and not (ctl.job_active or ctl.checking)

    def go(self, i):
        i = max(0, min(self.stack.count() - 1, i))
        if i == 2:
            self._enter_arrows()
        if i == 3:
            self._fill_summary()
        self.stack.setCurrentIndex(i)
        self.step_lab.setText(tr("Passo {0} di {1}", i + 1, self.stack.count()))
        self.b_back.setEnabled(i > 0)
        self.b_next.setText(tr("Fine") if i == self.stack.count() - 1 else tr("Avanti"))

    def _next(self):
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.accept()
        else:
            self.go(self.stack.currentIndex() + 1)

    def _enter_arrows(self):
        neg = self.main.profile.negative_space if self._same_model() else None
        for axis in (0, 1):
            if not self.tested[axis]:
                self.inv[axis] = MachineProfile.corner_inversion(self.picker.corner, neg)[axis]
        ok = self._can_jog()
        self.arrows_box.setVisible(ok)
        if ok:
            self._apply_sign()
            self.arrows_intro.setText(tr(
                "Premi le frecce: la testa si sposta di {0:g} mm a laser spento. Deve andare dove indica la freccia "
                "(↑ = verso il fondo della macchina). Se va al contrario, premi «correggi» per quell'asse e riprova.<br>"
                "Se la testa è vicina a un bordo, usa la freccia che la allontana.", STEP_MM))
            self.arrows_lab.setText("")
        else:
            self.arrows_intro.setText(tr(
                "Il laser non è collegato: la prova la fai dopo. Quando lo colleghi, apri <i>Impostazioni → "
                "Configurazione guidata della macchina</i> e premi le frecce: se una va al contrario, la correggi lì. "
                "Intanto FreeLaserCut usa l'angolo che hai scelto."))
            self.arrows_lab.setText("")

    def _apply_sign(self):
        self.main.ctl.axis_sign = (-1.0 if self.inv[0] else 1.0, -1.0 if self.inv[1] else 1.0)

    def jog(self, key):
        if not self._can_jog():
            self.arrows_lab.setText(tr("Il laser non è pronto: collegalo e riprova."))
            return
        dx, dy = {"up": (0, STEP_MM), "down": (0, -STEP_MM), "left": (-STEP_MM, 0), "right": (STEP_MM, 0)}[key]
        self._apply_sign()
        self.main.ctl.jog(dx, dy, JOG_FEED)
        self.tested[0 if dx else 1] = True
        self.arrows_lab.setText(tr("È andata dove indica la freccia? Se sì, prova anche l'altro asse; se no, premi "
                                   "«correggi»."))

    def fix(self, axis):
        self.inv[axis] = not self.inv[axis]
        self.tested[axis] = True
        self._apply_sign()
        self.arrows_lab.setText(tr("Corretto: ora {0} va nel verso giusto. Riprova la freccia per controllare.",
                                   tr("sinistra–destra") if axis == 0 else tr("fondo–davanti")))

    def _same_model(self):
        p = self.main.profile
        return self.model.currentText() in (p.model, p.name)

    def _final_axes(self):
        neg = self.main.profile.negative_space if self._same_model() else None
        base = list(MachineProfile.corner_inversion(self.picker.corner, neg))
        return [self.inv[a] if self.tested[a] else base[a] for a in (0, 1)]

    def _fill_summary(self):
        ix, iy = self._final_axes()
        corner = self.picker.corner
        if any(self.tested):  # le frecce hanno l'ultima parola: l'angolo si ricava dagli assi provati
            q = MachineProfile(invert_x=ix, invert_y=iy,
                               negative_space=self.main.profile.negative_space if self._same_model() else None)
            corner = q.corner_now()
        tested = tr("provati con le frecce") if all(self.tested) else tr("da provare con le frecce quando colleghi il laser")
        self.summary.setText(tr("<b>Macchina:</b> {0}<br><b>Lo 0 è</b> {1}.<br><b>Assi:</b> X {2}, Y {3} ({4}).",
                                self.model.currentText(), corner_name(corner),
                                tr("invertito") if ix else tr("normale"), tr("invertito") if iy else tr("normale"),
                                tested))

    def help_level_choice(self):
        return next((lv for lv, b in self.levels.items() if b.isChecked()), "normale")

    # ------------------------------------------------------------------ fine
    def reject(self):
        self.main.ctl.axis_sign = self._sign_before
        super().reject()

    def accept(self):
        self.apply()
        super().accept()

    def apply(self):
        from .dialogs_machine import use_preset

        main = self.main
        ix, iy = self._final_axes()
        if not self._same_model():
            p = use_preset(main.qs, self.model.currentText())
            if p is not None:
                main.set_active_profile(p)
        p = main.profile
        p.invert_x, p.invert_y = bool(ix), bool(iy)
        p.axes_tested = all(self.tested)
        if any(self.tested):  # le frecce hanno l'ultima parola: l'angolo si ricava dagli assi provati
            p.origin_corner = ""
        p.origin_corner = p.corner_now() if any(self.tested) else self.picker.corner
        try:
            p.save()
        except OSError:
            pass
        main._sync_axes()
        main.qs.setValue("setup_wizard_done", True)
        main.set_help_level(self.help_level_choice(), quiet=True)
        main.statusBar().showMessage(tr("Configurazione salvata: {0}, lo 0 è {1}", p.name, corner_name(p.origin_corner)),
                                     8000)
        if main.job is not None and not getattr(main, "_job_is_external", False):
            main.build_job()
