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
        self.touched = False  # l'utente ha scelto un angolo (non solo lasciato quello proposto, né «Non lo so»)
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

    def choose(self, c):
        """Angolo scelto dall'utente (clic)."""
        self.touched = True
        if c == self.corner:
            self.changed.emit(c)
        self.set_corner(c)

    def mousePressEvent(self, e):
        pos = e.position()
        best = min(self._points().items(), key=lambda kv: (kv[1] - pos).manhattanLength())
        self.choose(best[0])

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
        self.tested = [bool(p.tested_x or p.axes_tested), bool(p.tested_y or p.axes_tested)]
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
        # profilo che non viene dal catalogo (riconosciuto dalla scheda, rinominato…): resta il primo della lista e
        # resta quello scelto, così Avanti non lo sostituisce con il primo modello del catalogo
        self.keep_label = None if cur else tr("Il profilo attuale: {0}", p.name)
        if self.keep_label:
            self.model.insertItem(0, self.keep_label)
            self.model.setCurrentIndex(0)
        else:
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
        if not hasattr(self, "tested"):
            return
        p = self.main.profile
        if self._same_model():  # la macchina di adesso: quello che si sa già dei suoi assi
            self.tested = [bool(p.tested_x or p.axes_tested), bool(p.tested_y or p.axes_tested)]
            self.inv = [p.invert_x, p.invert_y]
        else:  # un'altra macchina: niente di quella attuale vale per lei
            self.tested = [False, False]
            self.inv = [False, False]

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
        self._unknown = False
        self.picker.changed.connect(self._corner_changed)
        h.addWidget(self.picker)
        h.addStretch(1)
        v.addLayout(h)
        r = QHBoxLayout()
        self.corner_lab = QLabel(tr("Lo 0 è {0}.", corner_name(self.picker.corner)))
        r.addWidget(self.corner_lab, 1)
        b = QPushButton(tr("Non lo so"))
        b.setToolTip(tr("Lascia davanti a sinistra, come la maggior parte dei laser: lo confermi con la prova delle frecce"))
        b.clicked.connect(self._dont_know)
        r.addWidget(b)
        v.addLayout(r)
        self.stack.addWidget(w)

    def _corner_changed(self, c):
        if self.picker.touched:
            self._unknown = False
        self.corner_lab.setText(tr("Lo 0 è {0}.", corner_name(c)))

    def _dont_know(self):
        """«Non lo so»: propongo davanti a sinistra ma non lo do per vero (il verso degli assi resta com'è finché non
        lo provi con le frecce)."""
        self.picker.touched = False
        self.picker.set_corner("fl")
        self._unknown = True
        self.corner_lab.setText(tr("Lo 0 non è indicato: lo scoprirai con la prova delle frecce."))

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
        self.b_home = QPushButton(tr("Homing"))
        self.b_home.setToolTip(tr("La macchina è bloccata (allarme): con l'homing si sblocca e trova lo 0"))
        self.b_home.clicked.connect(lambda: self.main.ctl.home())
        self.b_home.setVisible(False)
        v.addWidget(self.b_home)
        self.arrows_lab = _text("")
        v.addWidget(self.arrows_lab)
        self._last_axis = None
        # spostamento rifiutato dalla scheda (fuori area, macchina bloccata): non vale come prova, e lo dico
        self.main.ctl.error_raised.connect(self._jog_refused)
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
        # 0.18.17: solo se la scheda collegata ha il Wi-Fi (ESP32)
        self.wifi_hint = _text(tr("Vuoi usarlo senza cavo? Dopo, apri <i>Impostazioni → Collegamento Wi-Fi del laser…</i>"))
        from .. import wifi_setup

        ctl = self.main.ctl
        self.wifi_hint.setVisible(bool(ctl.connected and wifi_setup.esp32_hints(ctl.board_info, ctl.board_settings)))
        v.addWidget(self.wifi_hint)
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
        for axis in (0, 1):
            if not self.tested[axis]:
                self.inv[axis] = self._base_axes()[axis]
        ok = self._can_jog()
        self.arrows_box.setVisible(ok)
        self.b_home.setVisible(ok and self._alarm())
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

    def _alarm(self):
        return self.main.ctl.last_status.get("state") == "Alarm"

    def jog(self, key):
        if not self._can_jog():
            self.arrows_lab.setText(tr("Il laser non è pronto: collegalo e riprova."))
            return
        if self._alarm():
            self.b_home.setVisible(True)
            self.arrows_lab.setText(tr("La macchina è bloccata (allarme) e non si muove: premi <b>Homing</b> (o "
                                       "sbloccala dal pannello Laser), poi riprova le frecce."))
            return
        dx, dy = {"up": (0, STEP_MM), "down": (0, -STEP_MM), "left": (-STEP_MM, 0), "right": (STEP_MM, 0)}[key]
        base = self._base_axes()  # gli assi non ancora provati seguono il profilo (anche dopo un homing fatto da qui)
        for a in (0, 1):
            if not self.tested[a]:
                self.inv[a] = base[a]
        self._apply_sign()
        self._last_axis = 0 if dx else 1
        self._tested_before = self.tested[self._last_axis]
        self.main.ctl.jog(dx, dy, JOG_FEED)
        self.tested[self._last_axis] = True
        self.arrows_lab.setText(tr("È andata dove indica la freccia? Se sì, prova anche l'altro asse; se no, premi "
                                   "«correggi»."))

    def _jog_refused(self, code, _text, line):
        if self.stack.currentIndex() != 2 or not str(line).startswith("$J=") or self._last_axis is None:
            return
        self.tested[self._last_axis] = getattr(self, "_tested_before", False)  # non si è mosso: non è una prova
        if code == 15:
            self.arrows_lab.setText(tr("La macchina ha rifiutato lo spostamento: la testa uscirebbe dall'area di lavoro. "
                                       "Non è un verso sbagliato: usa la freccia opposta, che la allontana dal bordo."))
        else:
            self.arrows_lab.setText(tr("La macchina ha rifiutato lo spostamento (errore {0}): la testa non si è mossa. "
                                       "Controlla che sia pronta e riprova.", code))

    def fix(self, axis):
        self.inv[axis] = not self.inv[axis]
        self.tested[axis] = True
        self._apply_sign()
        self.arrows_lab.setText(tr("Corretto: ora {0} va nel verso giusto. Riprova la freccia per controllare.",
                                   tr("sinistra–destra") if axis == 0 else tr("fondo–davanti")))

    def _same_model(self):
        p = self.main.profile
        return self.model.currentText() in (p.model, p.name, self.keep_label)

    def _base_axes(self):
        """Verso degli assi non provati: dall'angolo, se l'hai scelto; altrimenti resta com'era."""
        same = self._same_model()
        if self.picker.touched:
            neg = self.main.profile.negative_space if same else None
            return list(MachineProfile.corner_inversion(self.picker.corner, neg))
        if not same:
            return [False, False]
        # il profilo di adesso, letto ora: se nel frattempo l'homing ha ricalcolato gli assi, vale quello
        return [self.main.profile.invert_x, self.main.profile.invert_y]

    def _final_axes(self):
        base = self._base_axes()
        return [self.inv[a] if self.tested[a] else base[a] for a in (0, 1)]

    def _fill_summary(self):
        ix, iy = self._final_axes()
        q = MachineProfile(invert_x=ix, invert_y=iy,
                           negative_space=self.main.profile.negative_space if self._same_model() else None)
        corner = q.corner_now()  # dagli assi come saranno (provati o dall'angolo scelto)
        tested = tr("provati con le frecce") if all(self.tested) else tr("da provare con le frecce quando colleghi il laser")
        self.summary.setText(tr("<b>Macchina:</b> {0}<br><b>Lo 0 è</b> {1}.<br><b>Assi:</b> X {2}, Y {3} ({4}).",
                                self.main.profile.name if self._same_model() else self.model.currentText(), corner_name(corner),
                                tr("invertito") if ix else tr("normale"), tr("invertito") if iy else tr("normale"),
                                tested))

    def help_level_choice(self):
        return next((lv for lv, b in self.levels.items() if b.isChecked()), "normale")

    # ------------------------------------------------------------------ fine
    def _disconnect(self):
        try:
            self.main.ctl.error_raised.disconnect(self._jog_refused)
        except (RuntimeError, TypeError):
            pass

    def reject(self):
        self._disconnect()
        self.main.ctl.axis_sign = self._sign_before
        super().reject()

    def accept(self):
        self._disconnect()
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
        p.tested_x, p.tested_y = bool(self.tested[0]), bool(self.tested[1])
        p.axes_tested = all(self.tested)
        if self.picker.touched:
            p.origin_corner = self.picker.corner  # serve per gli assi non provati, quando l'homing dirà di più
        elif self._unknown:
            p.origin_corner = ""
        try:
            p.save()
        except OSError:
            pass
        main._sync_axes()
        main.qs.setValue("setup_wizard_done", True)
        main.set_help_level(self.help_level_choice(), quiet=True)
        main.statusBar().showMessage(tr("Configurazione salvata: {0}, lo 0 è {1}", p.name, corner_name(p.corner_now())),
                                     8000)
        if main.job is not None and not getattr(main, "_job_is_external", False):
            main.build_job()
