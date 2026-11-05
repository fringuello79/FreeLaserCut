# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Pannelli di progettazione: barra numerica, tavolozza livelli, livelli/impostazioni di taglio, proprietà forma."""
import math

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QStyledItemDelegate, QTabWidget,
    QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import ops, text as textmod
from ..core import shapes_lib
from ..core.document import (
    DITHER_LABELS, DITHERS, IMAGE_STARTS, LAYER_COLORS, MODE_LABELS, MODES, EllipseShape, GroupShape, ImageShape, PathShape,
    CodeShape, PolygonShape, RectShape, SpecialShape, TextPathShape, TextShape,
)
from freelasercut.i18n import tr  # noqa: E402
from .. import units


def shape_icon(key, size=34, color=None):
    """Icona di una forma della galleria, disegnata dalla forma vera."""
    from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap

    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    asp = shapes_lib.natural_aspect(key)
    w, h = (1.0, 1.0 / asp) if asp >= 1 else (asp, 1.0)
    path = shapes_lib.make(key, w, h, shapes_lib.default_param(key))
    m = size * 0.1
    k = (size * 2 - 2 * m)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size - w * k / 2, size + h * k / 2)
    p.scale(k, -k)
    col = QColor(color or C["text"])
    pen = QPen(col, 0)
    pen.setCosmetic(True)
    pen.setWidthF(2.4)
    p.setPen(pen)
    fill = QColor(col)
    fill.setAlpha(45 if key not in shapes_lib.OPEN_SHAPES else 0)
    p.setBrush(fill)
    p.drawPath(path)
    p.end()
    return QIcon(pm)
from ..theme import C, css
from . import style
from .canvas import TOOL_LAYER_COLOR
from .editor import TOOL_LAYER
from .widgets import AnchorPicker, NumField, Swatch, hline, row, section


# ======================================================================= barra numerica
class NumericBar(QToolBar):
    """Posizione, misure e rotazione della selezione, più i comandi rapidi sulla selezione.

    Campi bassi (18 px) con l'unità scritta dentro (mm), lucchetto piccolo, a destra il livello
    della selezione e "centra sul piano"."""

    FIELD_H = 18

    def __init__(self, editor, canvas):
        super().__init__(tr("Posizione e dimensioni"))
        self.setObjectName("numeric")
        self.setMovable(False)
        self.setIconSize(QSize(14, 14))
        self.ed = editor
        self.cv = canvas
        self.anchor = AnchorPicker(4, cell=5, gap=2)
        self.anchor.setToolTip(tr("Punto di riferimento per posizione, scala e rotazione"))
        self.anchor.setProperty("help_key", "num:anchor")
        self.anchor.changed.connect(lambda _: self.refresh())
        self.addWidget(self.anchor)
        self.fx = self._field("X", suffix=" mm", help_key="num:x")
        self.fy = self._field("Y", suffix=" mm", help_key="num:y")
        self.addSeparator()
        self.fw = self._field("L", suffix=" mm", minimum=0.001, help_key="num:w")
        self.lock = QToolButton()
        self.lock.setObjectName("minilock")
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setFixedSize(18, 18)
        self.lock.setIconSize(QSize(12, 12))
        self.lock.setProperty("help_key", "num:lock")
        self.lock.toggled.connect(self._lock_icon)
        self._lock_icon(True)
        self.addWidget(self.lock)
        self.fh = self._field("A", suffix=" mm", minimum=0.001, help_key="num:h")
        self.addSeparator()
        self.fr = self._field("↻", decimals=2, suffix="°", step=1.0, width=58, help_key="num:rot")
        self.addSeparator()
        # ---- comandi rapidi sulla selezione (spazio libero a destra)
        lab = QLabel(tr("Livello"))
        lab.setObjectName("numlabel")
        self.addWidget(lab)
        self.layer_combo = QComboBox()
        self.layer_combo.setObjectName("numcombo")
        self.layer_combo.setFixedHeight(self.FIELD_H + 2)
        self.layer_combo.setMinimumWidth(118)
        self.layer_combo.setToolTip(tr("Livello della selezione: scegline un altro per spostarla (o per i nuovi disegni)"))
        self.layer_combo.setProperty("help_key", "num:layer")
        self.layer_combo.activated.connect(self._layer_picked)
        self.addWidget(self.layer_combo)
        self.btn_center = QToolButton()
        self.btn_center.setIcon(style.icon("move"))
        self.btn_center.setToolTip(tr("Centra la selezione sul piano di lavoro"))
        self.btn_center.setProperty("help_key", "num:center")
        self.btn_center.clicked.connect(self._center_on_bed)
        self.addWidget(self.btn_center)
        self.addSeparator()
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.info.setStyleSheet(f"color:{C['muted']}; padding-left:6px;")
        self.addWidget(self.info)
        self.fx.committed.connect(lambda v: self._move("x", v))
        self.fy.committed.connect(lambda v: self._move("y", v))
        self.fw.committed.connect(lambda v: self._size("w", v))
        self.fh.committed.connect(lambda v: self._size("h", v))
        self.fr.committed.connect(self._rotate)
        editor.selection_changed.connect(self.refresh)
        editor.changed.connect(self.refresh)
        editor.live.connect(self.refresh)
        self._layer_names = None
        self.refresh()

    def _lock_icon(self, on):
        self.lock.setIcon(style.icon("lock" if on else "unlock", C["accent_hi"] if on else C["muted"], 14,
                                     active=C["accent_hi"]))
        self.lock.setToolTip(tr("Proporzioni bloccate: larghezza e altezza cambiano insieme (clic per sbloccare)") if on
                             else tr("Proporzioni libere: larghezza e altezza indipendenti (clic per bloccare)"))

    def _field(self, label, decimals=2, suffix="", step=1.0, width=76, minimum=None, help_key=None):
        lab = QLabel(label)
        lab.setObjectName("numlabel")
        self.addWidget(lab)
        f = NumField(0.0, decimals, step, suffix, width, minimum)
        f.setObjectName("numbar")
        f.setFixedHeight(self.FIELD_H)
        if help_key:
            f.setProperty("help_key", help_key)
            lab.setProperty("help_key", help_key)
        self.addWidget(f)
        return f

    def _anchor_pt(self, b):
        from ..core import geom

        return geom.rect_anchor(b, self.anchor.value)

    def _fill_layers(self):
        """Voci del menu Livello: nome del livello se l'hai dato, altrimenti C00…C29, più T1."""
        layers = self.ed.doc.layers
        names = tuple((i, layers[i].name if i in layers else "") for i in range(len(LAYER_COLORS)))
        if names == self._layer_names:
            return
        self._layer_names = names
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for i, name in names:
            self.layer_combo.addItem(_swatch(LAYER_COLORS[i]), f"C{i:02d}  {name}" if name else f"C{i:02d}", i)
        self.layer_combo.addItem(_swatch(TOOL_LAYER_COLOR), tr("T1  strumenti (mai inciso)"), TOOL_LAYER)
        self.layer_combo.blockSignals(False)

    def _sync_layer(self):
        self._fill_layers()
        sel_layers = {s.layer for s in self.ed.selection}
        cur = next(iter(sel_layers)) if len(sel_layers) == 1 else (None if sel_layers else self.ed.current_layer)
        self.layer_combo.blockSignals(True)
        idx = self.layer_combo.findData(cur) if cur is not None else -1
        self.layer_combo.setCurrentIndex(idx)  # -1 = livelli diversi nella selezione
        self.layer_combo.blockSignals(False)

    def _layer_picked(self, i):
        idx = self.layer_combo.itemData(i)
        if idx is not None:
            self.ed.set_layer(idx)

    def _center_on_bed(self):
        from PySide6.QtCore import QRectF

        self.ed.move_to(4, QRectF(0, 0, self.cv.bed_x, self.cv.bed_y))

    def refresh(self):
        sel = self.ed.selection
        on = bool(sel)
        for f in (self.fx, self.fy, self.fw, self.fh, self.fr):
            f.setEnabled(on and bool(self.ed.editable()))
        self.btn_center.setEnabled(on and bool(self.ed.editable()))
        self._sync_layer()
        if not on:
            for f in (self.fx, self.fy, self.fw, self.fh, self.fr):
                f.setValue(0.0)
            self.info.setText(tr("Nessuna selezione"))
            return
        b = self.ed.selection_bounds()
        a = self._anchor_pt(b)
        self.fx.setValue(a.x())
        self.fy.setValue(a.y())
        self.fw.setValue(b.width())
        self.fh.setValue(b.height())
        if len(sel) == 1 and not isinstance(sel[0], GroupShape):
            t = sel[0].tf
            self.fr.setValue(math.degrees(math.atan2(t.m12(), t.m11())))
        else:
            self.fr.setValue(0.0)
        kinds = {s.describe() for s in sel}
        self.info.setText(tr("{0} oggetti", len(sel)) if len(sel) > 1 else next(iter(kinds)))

    def _move(self, axis, v):
        b = self.ed.selection_bounds()
        a = self._anchor_pt(b)
        d = v - (a.x() if axis == "x" else a.y())
        self.ed.transform(QTransform.fromTranslate(d, 0) if axis == "x" else QTransform.fromTranslate(0, d), tr("Sposta"))

    def _size(self, axis, v):
        b = self.ed.selection_bounds()
        a = self._anchor_pt(b)
        w0, h0 = max(b.width(), 1e-9), max(b.height(), 1e-9)
        if axis == "w":
            sx = v / w0
            sy = sx if self.lock.isChecked() else 1.0
        else:
            sy = v / h0
            sx = sy if self.lock.isChecked() else 1.0
        self.ed.transform(ops.about(QTransform.fromScale(sx, sy), a.x(), a.y()), tr("Ridimensiona"))

    def _rotate(self, v):
        sel = self.ed.selection
        cur = 0.0
        if len(sel) == 1 and not isinstance(sel[0], GroupShape):
            t = sel[0].tf
            cur = math.degrees(math.atan2(t.m12(), t.m11()))
        b = self.ed.selection_bounds()
        a = self._anchor_pt(b)
        r = QTransform()
        r.rotate(v - cur)
        self.ed.transform(ops.about(r, a.x(), a.y()), tr("Ruota"))


def _swatch(color, size=12):
    """Quadratino colorato per menu e liste dei livelli."""
    from PySide6.QtGui import QIcon, QPainter, QPixmap

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, 3, 3)
    p.end()
    return QIcon(pm)


# ======================================================================= tavolozza
class PaletteBar(QToolBar):
    def __init__(self, editor):
        super().__init__(tr("Livelli (colori)"))
        self.setObjectName("palette")
        self.setMovable(False)
        self.ed = editor
        lab = QLabel(tr("Livello"))
        lab.setObjectName("numlabel")
        self.addWidget(lab)
        self.swatches = []
        for i, col in enumerate(LAYER_COLORS):
            sw = Swatch(col, f"{i:02d}", tr("Livello {0:02d} — clic: assegna alla selezione (o ai nuovi disegni)", i))
            sw.clicked.connect(lambda _=False, i=i: self.pick(i))
            self.addWidget(sw)
            self.swatches.append(sw)
        self.addSeparator()
        t1 = Swatch(TOOL_LAYER_COLOR, "T1", tr("Livello strumenti T1: guide e contorni che non vengono mai incisi"))
        t1.clicked.connect(lambda: self.pick(TOOL_LAYER))
        self.addWidget(t1)
        self.swatches.append(t1)
        editor.changed.connect(self.refresh)
        editor.selection_changed.connect(self.refresh)
        self.refresh()

    def pick(self, i):
        self.ed.set_layer(i)
        self.refresh()

    def refresh(self):
        used = {leaf.layer for s in self.ed.doc.shapes for leaf, _ in s.leaves()}
        sel_layers = {s.layer for s in self.ed.selection}
        cur = next(iter(sel_layers)) if len(sel_layers) == 1 else (None if sel_layers else self.ed.current_layer)
        for i, sw in enumerate(self.swatches):
            idx = TOOL_LAYER if i == len(LAYER_COLORS) else i
            sw.used = idx in used
            sw.current = idx == cur
            sw.update()


# ======================================================================= livelli
def _spin(lo, hi, val, dec=1, step=1.0, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


class CutSettingsDialog(QDialog):
    """Tutte le impostazioni di un livello, organizzate per modalità."""

    def __init__(self, cs, profile, parent=None):
        super().__init__(parent)
        self.cs = cs
        self.setWindowTitle(tr("Impostazioni di taglio — {0}", cs.label()))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        head = QHBoxLayout()
        sw = Swatch(cs.color)
        sw.setFixedSize(30, 26)
        head.addWidget(sw)
        from PySide6.QtWidgets import QLineEdit

        self.name = QLineEdit(cs.name)
        self.name.setPlaceholderText(tr("Nome del livello (es. Taglio 3 mm)"))
        head.addWidget(self.name, 1)
        v.addLayout(head)
        f = QFormLayout()
        self.mode = QComboBox()
        for m in MODES:
            self.mode.addItem(MODE_LABELS[m], m)
        self.mode.setCurrentIndex(MODES.index(cs.mode))
        f.addRow(tr("Modalità"), self.mode)
        max_rate = min(profile.max_rate_x, profile.max_rate_y) if profile else 36000
        self.speed = units.SpeedSpin(1, max_rate, cs.speed, 100)
        self.speed_s = QLabel()
        self.speed_s.setObjectName("muted")
        self.speed.valueChanged.connect(lambda x: self.speed_s.setText("= " + units.other(x)))
        self.speed.valueChanged.emit(self.speed.value())
        f.addRow(tr("Velocità"), row(self.speed, self.speed_s))
        self.pmax = _spin(0, 100, cs.power_max, 1, 1, " %")
        self.pmin = _spin(0, 100, cs.power_min, 1, 1, " %")
        f.addRow(tr("Potenza massima"), self.pmax)
        f.addRow(tr("Potenza minima"), self.pmin)
        self.passes = QSpinBox()
        self.passes.setRange(1, 100)
        self.passes.setValue(cs.passes)
        f.addRow(tr("Passate"), self.passes)
        self.air = QCheckBox(tr("Air assist acceso per questo livello"))
        self.air.setChecked(cs.air)
        f.addRow("", self.air)
        self.const = QCheckBox(tr("Potenza costante (M3) invece che dinamica (M4)"))
        self.const.setChecked(getattr(cs, "constant_power", False))
        self.const.setToolTip(tr("Dinamica M4 (consigliata): la potenza segue la velocità reale, angoli e partenze non bruciano di più."))
        f.addRow("", self.const)
        self.output = QCheckBox(tr("Incidi questo livello (uscita attiva)"))
        self.output.setChecked(cs.output)
        f.addRow("", self.output)
        v.addLayout(f)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        # linea
        lt = QWidget()
        lf = QFormLayout(lt)
        self.kerf = _spin(-5, 5, cs.kerf, 3, 0.01, " mm")
        self.kerf.setToolTip(tr("Larghezza del taglio: i contorni esterni si allargano, i fori si stringono, i pezzi escono a misura."))
        lf.addRow(tr("Compensazione kerf"), self.kerf)
        self.tabs_on = QCheckBox(tr("Ponticelli (il pezzo resta attaccato al foglio)"))
        self.tabs_on.setChecked(cs.tabs)
        lf.addRow("", self.tabs_on)
        self.tab_size = _spin(0.1, 10, cs.tab_size, 2, 0.1, " mm")
        self.tab_count = QSpinBox()
        self.tab_count.setRange(1, 50)
        self.tab_count.setValue(cs.tab_count)
        lf.addRow(tr("Larghezza ponticello"), self.tab_size)
        lf.addRow(tr("Ponticelli per forma"), self.tab_count)
        self.tabs.addTab(lt, tr("Linea"))
        # riempimento
        ft = QWidget()
        ff = QFormLayout(ft)
        self.interval = _spin(0.01, 5, cs.interval, 3, 0.01, " mm")
        self.lpi = QLabel()
        self.lpi.setObjectName("muted")
        self.interval.valueChanged.connect(lambda x: self.lpi.setText(tr("= {0:.0f} righe/pollice", 25.4 / max(x, 1e-6))))
        self.interval.valueChanged.emit(self.interval.value())
        ff.addRow(tr("Interlinea"), row(self.interval, self.lpi))
        self.angle = _spin(-180, 180, cs.angle, 1, 15, " °")
        ff.addRow(tr("Angolo di scansione"), self.angle)
        self.cross = QCheckBox(tr("Tratteggio incrociato (seconda passata a +90°)"))
        self.cross.setChecked(cs.crosshatch)
        ff.addRow("", self.cross)
        self.bidir = QCheckBox(tr("Bidirezionale (incide andando e tornando)"))
        self.bidir.setChecked(cs.bidirectional)
        ff.addRow("", self.bidir)
        self.overscan = _spin(0, 30, cs.overscan, 1, 0.5, " mm")
        self.overscan.setToolTip(tr("Corsa extra a laser spento ai lati: la testa è già a velocità quando inizia a bruciare. "
                                 "FreeLaserCut la limita sempre ai bordi del piano."))
        ff.addRow(tr("Overscan"), self.overscan)
        self.grouping = QComboBox()
        for k, lab in (("auto", tr("Automatico: FreeLaserCut sceglie il più veloce")), ("together", tr("Tutte le forme insieme")),
                       ("each", tr("Forma per forma"))):
            self.grouping.addItem(lab, k)
        gi = self.grouping.findData(cs.fill_grouping)
        self.grouping.setCurrentIndex(max(gi, 0))
        ff.addRow(tr("Raggruppamento"), self.grouping)
        self.tabs.addTab(ft, tr("Riempimento"))
        # immagine
        it = QWidget()
        iff = QFormLayout(it)
        self.dpi = _spin(25, 1000, cs.dpi, 0, 10, " dpi")
        self.dpi_mm = QLabel()
        self.dpi_mm.setObjectName("muted")
        self.dpi.valueChanged.connect(lambda x: self.dpi_mm.setText(tr("= {0:.3f} mm fra le righe", 25.4 / max(x, 1))))
        self.dpi.valueChanged.emit(self.dpi.value())
        iff.addRow(tr("Risoluzione"), row(self.dpi, self.dpi_mm))
        self.dither = QComboBox()
        for d in DITHERS:
            self.dither.addItem(DITHER_LABELS[d], d)
        self.dither.setCurrentIndex(DITHERS.index(cs.dither))
        iff.addRow(tr("Metodo"), self.dither)
        self.negative = QCheckBox(tr("Negativo (inverte chiari e scuri)"))
        self.negative.setChecked(cs.negative)
        iff.addRow("", self.negative)
        self.dotc = _spin(0, 1, cs.dot_correction, 3, 0.01, " mm")
        self.dotc.setToolTip(tr("Accorcia ogni punto acceso: compensa lo spot del laser (circa metà della sua larghezza)."))
        iff.addRow(tr("Correzione punto"), self.dotc)
        self.hcell = _spin(0.2, 10, cs.halftone_cell, 2, 0.1, " mm")
        self.hcell.setToolTip(tr("Solo con il metodo «Mezzetinte (retino)»: la foto diventa punti tondi, come nelle foto "
                                 "dei giornali. La cella è la distanza fra un punto e l'altro: più grande = punti grossi e "
                                 "ben visibili, più piccola = immagine più fine. Sul legno di solito 0,5–1 mm."))
        self.hangle = _spin(0, 90, cs.halftone_angle, 0, 5, " °")
        self.hangle.setToolTip(tr("Solo con il metodo «Mezzetinte (retino)»: inclinazione della griglia dei punti. "
                                  "45° è il classico e si nota meno a occhio. Non cambia il movimento della testa."))
        self.hcell_name = QLabel(tr("Retino: cella"))
        self.hangle_name = QLabel(tr("Retino: angolo"))
        for lab_, w_ in ((self.hcell_name, self.hcell), (self.hangle_name, self.hangle)):
            lab_.setToolTip(w_.toolTip())
            iff.addRow(lab_, w_)
        self.dither.currentIndexChanged.connect(self._dither_changed)
        self._dither_changed()
        self.istart = QComboBox()
        for k, lab in IMAGE_STARTS.items():
            self.istart.addItem(lab, k)
        self.istart.setCurrentIndex(max(0, self.istart.findData(cs.image_start)))
        self.istart.setToolTip(tr("Da dove comincia l'incisione della foto e in che verso vanno le righe. I punti incisi "
                                  "sono gli stessi, cambia solo il percorso della testa. Di solito le righe orizzontali "
                                  "sono più veloci: lungo X si muove solo la testa, lungo Y tutto il portale. La "
                                  "correzione della scansione avanti e indietro, misurata lungo X, vale per le righe "
                                  "orizzontali."))
        iff.addRow(tr("Partenza della foto"), self.istart)
        self.bidir_i = QCheckBox(tr("Bidirezionale"))
        self.bidir_i.setChecked(cs.bidirectional)
        iff.addRow("", self.bidir_i)
        self.overscan_i = _spin(0, 30, cs.overscan, 1, 0.5, " mm")
        iff.addRow(tr("Overscan"), self.overscan_i)
        self.tabs.addTab(it, tr("Immagine"))
        self.mode.currentIndexChanged.connect(self._mode_tab)
        self._mode_tab()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Applica"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _dither_changed(self, *_):
        """Cella e angolo del retino servono solo alle mezzetinte: con gli altri metodi restano grigi."""
        on = self.dither.currentData() == "halftone"
        for w_ in (self.hcell, self.hangle, self.hcell_name, self.hangle_name):
            w_.setEnabled(on)

    def _mode_tab(self):
        m = self.mode.currentData()
        idx = {"line": 0, "fill": 1, "offset_fill": 1, "image": 2}[m]
        for i in range(3):
            self.tabs.setTabEnabled(i, i == idx or (m == "offset_fill" and i == 1))
        self.tabs.setCurrentIndex(idx)

    def values(self):
        m = self.mode.currentData()
        img = m == "image"
        return dict(name=self.name.text().strip(), mode=m, speed=self.speed.value(), power_max=self.pmax.value(),
                    power_min=self.pmin.value(), passes=self.passes.value(), air=self.air.isChecked(),
                    output=self.output.isChecked(), constant_power=self.const.isChecked(), kerf=self.kerf.value(),
                    tabs=self.tabs_on.isChecked(), tab_size=self.tab_size.value(), tab_count=self.tab_count.value(),
                    interval=self.interval.value(), angle=self.angle.value(), crosshatch=self.cross.isChecked(),
                    bidirectional=(self.bidir_i if img else self.bidir).isChecked(),
                    overscan=(self.overscan_i if img else self.overscan).value(),
                    fill_grouping=self.grouping.currentData(), dpi=self.dpi.value(), dither=self.dither.currentData(),
                    negative=self.negative.isChecked(), dot_correction=self.dotc.value(),
                    halftone_cell=self.hcell.value(), halftone_angle=self.hangle.value(),
                    image_start=self.istart.currentData() or "top")


# colonne della tabella livelli
L_NAME, L_MODE, L_SPEED, L_POWER, L_PASSES, L_OUT, L_SHOW, L_AIR = range(8)
LAYER_COLS = (
    (tr("Livello"), tr("Nome del livello: doppio clic per rinominarlo (vuoto = C00…C29)")),
    (tr("Modalità"), tr("Linea, Riempimento, Riempimento offset o Immagine: doppio clic per cambiarla")),
    (units.speed_unit(), tr("Velocità: doppio clic per modificarla (unità in Impostazioni → Unità di misura)")),
    (tr("Pot. %"), tr("Potenza massima in percentuale: doppio clic per modificarla")),
    ("×", tr("Numero di passate: doppio clic per modificarlo")),
    (tr("Inc."), tr("Incidi: se tolto, il livello resta nel disegno ma non viene inciso")),
    (tr("Vis."), tr("Visibile sulla tela (non cambia cosa viene inciso)")),
    (tr("Aria"), tr("Air assist acceso durante questo livello")),
)
_CHECK_ATTR = {L_OUT: "output", L_SHOW: "show", L_AIR: "air"}
_EDIT_ATTR = {L_NAME: "name", L_MODE: "mode", L_SPEED: "speed", L_POWER: "power_max", L_PASSES: "passes"}


class _LayerDelegate(QStyledItemDelegate):
    """Modifica in linea dei livelli: nome, modalità, velocità, potenza e passate direttamente nella tabella.

    Il valore NON viene scritto nel modello della tabella: va all'editor (annullabile) e la tabella si ricostruisce
    da sola, a evento concluso (vedi LayersPanel._apply)."""

    def __init__(self, panel):
        super().__init__(panel.tree)
        self.panel = panel

    def createEditor(self, parent, option, index):
        col = index.column()
        cs = self.panel._cs_at(index)
        if cs is None or col not in _EDIT_ATTR:
            return None
        if col == L_NAME:
            from PySide6.QtWidgets import QLineEdit

            w = QLineEdit(parent)
            w.setPlaceholderText(f"C{cs.index:02d}")
        elif col == L_MODE:
            w = QComboBox(parent)
            for m in MODES:
                w.addItem(MODE_LABELS[m], m)
            # la scelta si applica subito, senza dover premere Invio
            w.activated.connect(lambda _=0, w=w: (self.commitData.emit(w),
                                                  self.closeEditor.emit(w, QStyledItemDelegate.NoHint)))
        elif col == L_SPEED:
            p = self.panel.get_profile()
            hi = min(p.max_rate_x, p.max_rate_y) if p else 36000
            w = units.SpeedSpin(1, max(hi, 1), cs.speed, 100, show_suffix=False)
        elif col == L_POWER:
            w = _spin(0, 100, cs.power_max, 1, 1, "")
        else:
            w = QSpinBox(parent)
            w.setRange(1, 100)
        w.setParent(parent)
        w.setAutoFillBackground(True)
        return w

    def setEditorData(self, w, index):
        cs = self.panel._cs_at(index)
        if cs is None:
            return
        col = index.column()
        if col == L_NAME:
            w.setText(cs.name)
            w.selectAll()
        elif col == L_MODE:
            w.setCurrentIndex(max(w.findData(cs.mode), 0))
            from PySide6.QtCore import QTimer as _T

            _T.singleShot(0, w.showPopup)
        elif col == L_SPEED:
            w.setValue(cs.speed)
        elif col == L_POWER:
            w.setValue(cs.power_max)
        else:
            w.setValue(cs.passes)

    def setModelData(self, w, model, index):
        cs = self.panel._cs_at(index)
        if cs is None:
            return
        col = index.column()
        if col == L_NAME:
            val = w.text().strip()
        elif col == L_MODE:
            val = w.currentData()
        elif col in (L_SPEED, L_POWER):
            w.interpretText()
            val = float(w.value())
        else:
            w.interpretText()
            val = int(w.value())
        self.panel._apply(cs.index, {_EDIT_ATTR[col]: val})

    def updateEditorGeometry(self, w, option, index):
        r = option.rect
        if isinstance(w, QComboBox):
            r = r.adjusted(0, 0, 40, 0)  # le voci della modalità sono lunghe
        w.setGeometry(r)


class LayersPanel(QWidget):
    material_requested = Signal()

    def __init__(self, editor, get_profile):
        super().__init__()
        self.ed = editor
        self.get_profile = get_profile
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(5)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([c[0] for c in LAYER_COLS])
        hi = self.tree.headerItem()
        for i, (_, tip) in enumerate(LAYER_COLS):
            hi.setToolTip(i, tip)
        self.tree.setProperty("help_key", "layers:table")
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                                  | QAbstractItemView.EditKeyPressed)
        self.tree.setItemDelegate(_LayerDelegate(self))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 8):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._load_quick())
        v.addWidget(self.tree, 1)
        hint = QLabel(tr("Doppio clic su una cella per modificarla · tasto destro per altre opzioni"))
        hint.setObjectName("muted")
        hint.setStyleSheet(f"color:{C['muted']}; font-size:7.5pt;")
        v.addWidget(hint)
        bar = QHBoxLayout()
        for icon, tip, fn, key in (("chevron_up", tr("Sposta su (prima nell'ordine di lavoro)"), lambda: self.move(-1), "layers:up"),
                                   ("chevron_down", tr("Sposta giù"), lambda: self.move(1), "layers:down"),
                                   ("select_all", tr("Seleziona le forme di questo livello"), self.select_shapes, "layers:select"),
                                   ("settings", tr("Tutte le impostazioni…"), self.edit, "layers:settings")):
            b = QToolButton()
            b.setIcon(style.icon(icon))
            b.setToolTip(tip)
            b.setProperty("help_key", key)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.mat_btn = QPushButton(style.icon("library"), tr("Materiale…"))
        self.mat_btn.setToolTip(tr("Applica al livello i valori di un materiale (tabella Longer B1 40W + le tue voci)  Ctrl+M"))
        self.mat_btn.setProperty("help_key", "materials")
        self.mat_btn.clicked.connect(self.material_requested.emit)
        bar.addWidget(self.mat_btn)
        self.sort_btn = QPushButton(tr("Tagli per ultimi"))
        self.sort_btn.setToolTip(tr("Ordina: prima incisioni e riempimenti, per ultime le linee di taglio "
                                 "(così i pezzi non cadono prima di essere incisi)"))
        self.sort_btn.setProperty("help_key", "layers:sort")
        self.sort_btn.clicked.connect(self.sort_cuts_last)
        bar.addWidget(self.sort_btn)
        v.addLayout(bar)
        v.addWidget(section(tr("Impostazioni rapide")))
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)
        self.q_mode = QComboBox()
        for m in MODES:
            self.q_mode.addItem(MODE_LABELS[m], m)
        self.q_speed = units.SpeedSpin(1, 36000, 1000, 100)
        self.q_pmax = _spin(0, 100, 20, 1, 1, " %")
        self.q_pmin = _spin(0, 100, 0, 1, 1, " %")
        self.q_passes = QSpinBox()
        self.q_passes.setRange(1, 100)
        self.q_interval = _spin(0.01, 5, 0.1, 3, 0.01, " mm")
        for r_, (lab, w, key) in enumerate(((tr("Modalità"), self.q_mode, "cs:mode"), (tr("Velocità"), self.q_speed, "cs:speed"),
                                            (tr("Potenza max"), self.q_pmax, "cs:power_max"),
                                            (tr("Potenza min"), self.q_pmin, "cs:power_min"),
                                            (tr("Passate"), self.q_passes, "cs:passes"),
                                            (tr("Interlinea"), self.q_interval, "cs:interval"))):
            l = QLabel(lab)
            l.setObjectName("muted")
            l.setProperty("help_key", key)
            w.setProperty("help_key", key)
            g.addWidget(l, r_ // 2, (r_ % 2) * 2)
            g.addWidget(w, r_ // 2, (r_ % 2) * 2 + 1)
        v.addLayout(g)
        for w in (self.q_mode,):
            w.currentIndexChanged.connect(self._quick_changed)
        for w in (self.q_speed, self.q_pmax, self.q_pmin, self.q_interval):
            w.valueChanged.connect(self._quick_changed)
        self.q_passes.valueChanged.connect(self._quick_changed)
        self._loading = False
        editor.changed.connect(self.refresh)
        self.refresh()

    def _current_cs(self):
        it = self.tree.currentItem()
        if it is None:
            return None
        return self.ed.doc.layers.get(it.data(0, Qt.UserRole))

    def _cs_at(self, index):
        it = self.tree.topLevelItem(index.row()) if index.isValid() else None  # tabella piatta: riga = livello
        if it is None:
            return None
        return self.ed.doc.layers.get(it.data(0, Qt.UserRole))

    def refresh(self):
        cur = self._current_cs()
        cur_idx = cur.index if cur else None
        self._loading = True
        self.tree.blockSignals(True)
        self.tree.clear()
        layers = [cs for cs in self.ed.doc.used_layers() if cs.index != TOOL_LAYER]
        mono = style.mono_font(9)
        for cs in layers:
            it = QTreeWidgetItem()
            it.setData(0, Qt.UserRole, cs.index)
            it.setText(L_NAME, cs.label())
            it.setIcon(L_NAME, self._swatch_icon(cs.color))
            it.setText(L_MODE, MODE_LABELS[cs.mode])
            it.setText(L_SPEED, units.fmt(cs.speed, unit=False))
            it.setToolTip(L_SPEED, tr("{0:g} mm/min = {1:.1f} mm/s", cs.speed, cs.speed / 60))
            it.setText(L_POWER, f"{cs.power_max:g}")
            it.setText(L_PASSES, f"{cs.passes}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            for col, attr in _CHECK_ATTR.items():
                it.setCheckState(col, Qt.Checked if getattr(cs, attr) else Qt.Unchecked)
            for col in (L_SPEED, L_POWER, L_PASSES):
                it.setFont(col, mono)
                it.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
            if not cs.output:
                for col in range(len(LAYER_COLS)):
                    it.setForeground(col, QColor(C["muted"]))
            self.tree.addTopLevelItem(it)
            if cs.index == cur_idx:
                self.tree.setCurrentItem(it)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.blockSignals(False)
        self._loading = False
        self._load_quick()

    def _swatch_icon(self, color):
        return _swatch(color, 14)

    def _item_changed(self, it, col):
        """Spunte Inc./Vis./Aria.

        Il segnale arriva da DENTRO QTreeWidgetItem.setData: se qui ricostruissimo subito la tabella
        (editor.changed → refresh → tree.clear) l'elemento verrebbe distrutto mentre Qt lo sta ancora usando,
        e il programma si chiuderebbe (era il crash togliendo e rimettendo la spunta "Inc.").
        Per questo la modifica si applica un istante dopo, a evento concluso."""
        if self._loading or col not in _CHECK_ATTR:
            return
        self._apply(it.data(0, Qt.UserRole), {_CHECK_ATTR[col]: it.checkState(col) == Qt.Checked})

    def _apply(self, layer_index, vals):
        """Applica valori a un livello come azione annullabile, sempre fuori dall'evento della tabella."""
        def later():
            cs = self.ed.doc.layers.get(layer_index)
            if cs is None:
                return
            todo = {k: v for k, v in vals.items() if getattr(cs, k) != v}
            if not todo:
                self.refresh()  # es. spunta rimessa com'era: riallinea la tabella
                return

            def do():
                for k, v in todo.items():
                    setattr(cs, k, v)
            label = {"name": tr("Rinomina livello"), "mode": tr("Modalità livello"), "output": tr("Incidi livello"),
                     "show": tr("Mostra livello"), "air": tr("Aria livello")}.get(next(iter(todo)), "Impostazioni livello")
            self.ed.run(label, do)
        QTimer.singleShot(0, later)

    def _context_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        it = self.tree.itemAt(pos)
        if it is None:
            return
        self.tree.setCurrentItem(it)
        cs = self._current_cs()
        m = QMenu(self)
        m.addAction(style.icon("settings"), tr("Tutte le impostazioni…"), self.edit)
        m.addAction(tr("Rinomina"), lambda: self.tree.editItem(it, L_NAME))
        mm = m.addMenu(tr("Modalità"))
        for mode in MODES:
            a = mm.addAction(MODE_LABELS[mode], lambda mode=mode: self._apply(cs.index, {"mode": mode}))
            a.setCheckable(True)
            a.setChecked(cs.mode == mode)
        m.addSeparator()
        m.addAction(tr("Incidi") if not cs.output else tr("Non incidere"),
                    lambda: self._apply(cs.index, {"output": not cs.output}))
        m.addAction(tr("Mostra") if not cs.show else tr("Nascondi"), lambda: self._apply(cs.index, {"show": not cs.show}))
        m.addAction(tr("Incidi solo questo livello"), lambda: self._solo(cs.index))
        m.addSeparator()
        m.addAction(style.icon("select_all"), tr("Seleziona le forme del livello"), self.select_shapes)
        m.addAction(style.icon("library"), tr("Applica un materiale…"), self.material_requested.emit)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _solo(self, layer_index):
        layers = [cs for cs in self.ed.doc.used_layers() if cs.index != TOOL_LAYER]

        def later():
            def do():
                for c in layers:
                    c.output = c.index == layer_index
            self.ed.run(tr("Incidi solo un livello"), do)
        QTimer.singleShot(0, later)

    def _load_quick(self):
        cs = self._current_cs()
        self._loading = True
        for w in (self.q_mode, self.q_speed, self.q_pmax, self.q_pmin, self.q_passes, self.q_interval):
            w.setEnabled(cs is not None)
        if cs is not None:
            self.q_mode.setCurrentIndex(MODES.index(cs.mode))
            self.q_speed.setValue(cs.speed)
            self.q_pmax.setValue(cs.power_max)
            self.q_pmin.setValue(cs.power_min)
            self.q_passes.setValue(cs.passes)
            self.q_interval.setValue(cs.dpi and 25.4 / cs.dpi if cs.mode == "image" else cs.interval)
        self._loading = False

    def _quick_changed(self, *_):
        if self._loading:
            return
        cs = self._current_cs()
        if cs is None:
            return
        vals = dict(mode=self.q_mode.currentData(), speed=self.q_speed.value(), power_max=self.q_pmax.value(),
                    power_min=self.q_pmin.value(), passes=self.q_passes.value())
        iv = self.q_interval.value()
        if vals["mode"] == "image":
            vals["dpi"] = 25.4 / max(iv, 1e-3)
        else:
            vals["interval"] = iv
        self._apply(cs.index, vals)

    def edit(self):
        cs = self._current_cs()
        if cs is None:
            return
        dlg = CutSettingsDialog(cs, self.get_profile(), self)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.values()

            def do():
                for k, v in vals.items():
                    setattr(cs, k, v)
            self.ed.run(tr("Impostazioni di taglio"), do)

    def move(self, d):
        layers = [cs for cs in self.ed.doc.used_layers() if cs.index != TOOL_LAYER]
        cs = self._current_cs()
        if cs is None or cs not in layers:
            return
        i = layers.index(cs)
        j = i + d
        if not 0 <= j < len(layers):
            return
        layers[i], layers[j] = layers[j], layers[i]

        def do():
            for k, c in enumerate(layers):
                c.priority = k
        self.ed.run(tr("Ordine livelli"), do)

    def sort_cuts_last(self):
        layers = [cs for cs in self.ed.doc.used_layers() if cs.index != TOOL_LAYER]
        weight = {"image": 0, "fill": 1, "offset_fill": 2, "line": 3}

        def key(c):
            # a parità di modalità: prima i più leggeri (meno energia per mm)
            return (weight[c.mode], c.power_max * c.passes / max(c.speed, 1))

        ordered = sorted(layers, key=key)

        def do():
            for k, c in enumerate(ordered):
                c.priority = k
        self.ed.run(tr("Tagli per ultimi"), do)

    def select_shapes(self):
        cs = self._current_cs()
        if cs is not None:
            self.ed.select_layer(cs.index)


# ======================================================================= proprietà
class PropertiesPanel(QScrollArea):
    trace_requested = Signal()
    photo_requested = Signal()
    variables_requested = Signal()

    def __init__(self, editor, canvas):
        super().__init__()
        self.ed = editor
        self.cv = canvas
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.setWidget(self.host)
        self.lay = QVBoxLayout(self.host)
        self.lay.setContentsMargins(6, 4, 6, 6)
        self.lay.setSpacing(5)
        self.shape = None
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(600)
        self._typing.timeout.connect(self.ed.commit)
        self.text_edit = None
        editor.selection_changed.connect(self.rebuild)
        editor.changed.connect(self._external_change)
        canvas.tool_changed.connect(lambda _: self.rebuild())
        self.rebuild()

    def _external_change(self):
        # dopo annulla/ripeti la forma mostrata potrebbe essere stata ricreata
        if self._typing.isActive():
            return
        if self.shape is not None and self.shape not in self.ed.doc.shapes:
            self.rebuild()

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.text_edit = None

    def rebuild(self):
        if self._typing.isActive():
            self._typing.stop()
            self.ed.commit()
        self._clear()
        sel = self.ed.selection
        self.shape = sel[0] if len(sel) == 1 else None
        s = self.shape
        if s is None:
            self._tool_options(len(sel))
        elif isinstance(s, TextShape):
            self._text(s)
        elif isinstance(s, RectShape):
            self._rect(s)
        elif isinstance(s, EllipseShape):
            self._ellipse(s)
        elif isinstance(s, PolygonShape):
            self._polygon(s)
        elif isinstance(s, ImageShape):
            self._image(s)
        elif isinstance(s, SpecialShape):
            self._special(s)
        elif isinstance(s, CodeShape):
            self._code(s)
        else:
            self._generic(s)
        if s is not None:
            self._common(s)
        self.lay.addStretch(1)
        from .widgets import shrinkable

        shrinkable(self.host)
        # il contenuto non deve mai comprimersi: se non ci sta, il pannello scorre
        self._fix_height()
        QTimer.singleShot(0, self._fix_height)

    def _fix_height(self):
        self.lay.invalidate()
        self.lay.activate()
        self.host.setMinimumHeight(self.lay.sizeHint().height())

    # ---- helper
    def _mod(self, label, **kw):
        if self.shape is not None:
            self.ed.modify(self.shape, label, **kw)

    def _form(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        f.setVerticalSpacing(3)
        f.setHorizontalSpacing(8)
        f.setLabelAlignment(Qt.AlignLeft)
        self.lay.addWidget(w)
        return f

    def _tool_options(self, n):
        self.lay.addWidget(section(tr("Strumenti") if n == 0 else f"{n} oggetti selezionati"))
        if n:
            inf = ops.info(self.ed.selection)
            lab = QLabel(tr("Perimetro totale {0:.1f} mm · area {1:.1f} mm²\n{2} chiuse · {3} aperte · {4} nodi", inf['perimeter'], inf['area'], inf['closed'], inf['open'], inf['nodes']))
            lab.setObjectName("muted")
            self.lay.addWidget(lab)
            return
        if getattr(self.cv.tool, "name", "") == "special":
            self._special_tool()
        f = self._form()
        o = self.cv.tool_options
        sides = QSpinBox()
        sides.setRange(3, 64)
        sides.setValue(o["sides"])
        sides.valueChanged.connect(lambda v: o.__setitem__("sides", v))
        f.addRow(tr("Lati del poligono"), sides)
        pts = QSpinBox()
        pts.setRange(3, 64)
        pts.setValue(o["star_points"])
        pts.valueChanged.connect(lambda v: o.__setitem__("star_points", v))
        f.addRow(tr("Punte della stella"), pts)
        ratio = _spin(0.05, 0.95, o["star_ratio"], 2, 0.05)
        ratio.valueChanged.connect(lambda v: o.__setitem__("star_ratio", v))
        f.addRow(tr("Rientranza stella"), ratio)
        rad = _spin(0, 500, o["corner_radius"], 2, 0.5, " mm")
        rad.valueChanged.connect(lambda v: o.__setitem__("corner_radius", v))
        f.addRow(tr("Raggio angoli rettangolo"), rad)
        self.lay.addWidget(section(tr("Testo nuovo")))
        self._font_controls(self.cv.text_defaults, None)
        tips = QLabel(tr("Suggerimenti\n· Clic su uno strumento e trascina sul piano\n· Doppio clic su un testo per modificarlo\n"
                      "· Doppio clic su una forma per modificarne i nodi\n· Spazio + trascina per spostare la vista"))
        tips.setObjectName("muted")
        tips.setWordWrap(True)
        self.lay.addWidget(tips)

    def _gallery(self, current, on_pick):
        """Griglia di pulsanti con tutte le forme della galleria."""
        grid = QGridLayout()
        grid.setSpacing(4)
        host = QWidget()
        host.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (key, spec) in enumerate(shapes_lib.SHAPES.items()):
            b = QToolButton()
            b.setIcon(shape_icon(key))
            b.setIconSize(QSize(32, 32))
            b.setStyleSheet("padding: 2px;")
            b.setToolTip(spec[0])
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setAutoRaise(False)
            b.setFixedSize(44, 44)
            b.clicked.connect(lambda _=False, k=key: on_pick(k))
            grid.addWidget(b, i // 6, i % 6)
        self.lay.addWidget(host)

    def _special_tool(self):
        o = self.cv.tool_options
        cur = o.get("special", "arrow")
        self.lay.addWidget(section(tr("Galleria forme")))

        def pick(k):
            o["special"] = k
            self.rebuild()
        self._gallery(cur, pick)
        spec = shapes_lib.SHAPES[cur]
        lab = QLabel(tr("<b>{0}</b> · trascina sul piano (Maiusc = proporzioni giuste, Ctrl = dal centro) oppure fai clic per una forma da 30 mm.", spec[0]))
        lab.setWordWrap(True)
        lab.setObjectName("muted")
        self.lay.addWidget(lab)
        if spec[1] != "—":
            f = self._form()
            dec = spec[5]
            val = o.setdefault("special_param", {}).get(cur, spec[4])
            sp = _spin(spec[2], spec[3], val, dec, 1 if dec == 0 else 0.05)
            sp.valueChanged.connect(lambda v, k=cur: o["special_param"].__setitem__(k, v))
            f.addRow(spec[1], sp)

    def _special(self, s):
        self.lay.addWidget(section(s.describe()))

        def pick(k):
            if k != s.form:
                self.ed.modify(s, tr("Cambia forma"), form=k, param=shapes_lib.default_param(k))
                self.rebuild()
        self._gallery(s.form, pick)
        spec = shapes_lib.SHAPES[s.form]
        f = self._form()
        if spec[1] != "—":
            dec = spec[5]
            sp = _spin(spec[2], spec[3], s.param, dec, 1 if dec == 0 else 0.05)
            sp.valueChanged.connect(lambda v: self._mod(spec[1], param=v))
            f.addRow(spec[1], sp)
        lab = QLabel(tr("{0:.2f} × {1:.2f} mm (forma originale). Converti in tracciato (Ctrl+Maiusc+C) per modificarne i nodi.", s.w, s.h))
        lab.setObjectName("muted")
        lab.setWordWrap(True)
        self.lay.addWidget(lab)

    def _code(self, s):
        from ..core import codes

        self.lay.addWidget(section(s.describe()))
        f = self._form()
        ed = QLineEdit(s.data)
        ed.setToolTip(tr("Variabili: {n} numero progressivo, {data}, colonne del CSV"))
        ed.editingFinished.connect(lambda: ed.text() != s.data and self._mod(tr("Contenuto del codice"), data=ed.text()))
        f.addRow(tr("Contenuto"), ed)
        if s.variable:
            f.addRow("", QLabel(tr("Ora mostra: «{0}»", s.shown_data())))
        if s.error:
            err = QLabel(s.error)
            err.setStyleSheet(css("color:#E5484D;"))
            err.setWordWrap(True)
            f.addRow("", err)
        b = QPushButton(tr("Modifica codice…"))
        b.clicked.connect(lambda: self.window().code_dialog())
        f.addRow("", b)
        lab = QLabel(tr("Incidi i codici in riempimento e prova la lettura col telefono prima di una serie."))
        lab.setObjectName("muted")
        lab.setWordWrap(True)
        self.lay.addWidget(lab)

    def _font_controls(self, d, shape):
        """Controlli carattere: d = dizionario di valori (default o forma)."""
        f = self._form()
        fam = QComboBox()
        fam.setEditable(False)
        fam.setMaxVisibleItems(24)
        fam.addItem(tr("— Linea singola (incisione veloce) —"))
        fam.model().item(0).setEnabled(False)
        for key, lab in textmod.SINGLE_LINE_FONTS.items():
            fam.addItem(lab, key)
        fam.insertSeparator(fam.count())
        fam.addItem(tr("— Font di sistema —"))
        fam.model().item(fam.count() - 1).setEnabled(False)
        for name in textmod.system_families():
            fam.addItem(name, name)
            fam.setItemData(fam.count() - 1, QFont(name, 10), Qt.FontRole)
        i = fam.findData(d["family"])
        if i < 0:  # carattere non installato: ripiego su uno presente
            for alt in ("Arial", tr("Segoe UI"), "Inter", tr("DejaVu Sans"), tr("Liberation Sans")):
                i = fam.findData(alt)
                if i >= 0:
                    break
        if i < 0:
            i = next(k for k in range(fam.count()) if fam.itemData(k))
        fam.setCurrentIndex(i)
        if shape is None:
            d["family"] = fam.itemData(i)
        size = _spin(0.5, 500, d["size"], 2, 0.5, " mm")
        size.setToolTip(tr("Altezza reale delle MAIUSCOLE: 10 mm = una H alta 10 mm"))
        bold = QToolButton()
        bold.setIcon(style.icon("bold"))
        bold.setCheckable(True)
        bold.setChecked(d["bold"])
        italic = QToolButton()
        italic.setIcon(style.icon("italic"))
        italic.setCheckable(True)
        italic.setChecked(d["italic"])
        aligns = {}
        al_row = []
        for k, ic in (("left", "talign_left"), ("center", "talign_center"), ("right", "talign_right")):
            b = QToolButton()
            b.setIcon(style.icon(ic))
            b.setCheckable(True)
            b.setChecked(d["align"] == k)
            aligns[k] = b
            al_row.append(b)
        upper = QCheckBox("MAIUSCOLO")
        upper.setChecked(d["upper"])
        weld = QCheckBox(tr("Salda le lettere"))
        weld.setChecked(d["weld"])
        weld.setToolTip(tr("Unisce le lettere che si toccano: nessuna doppia bruciatura nei corsivi"))
        ls = _spin(-50, 50, d["letter_spacing"], 2, 0.1, " mm")
        lsp = _spin(0.3, 5, d["line_spacing"], 2, 0.1, " ×")
        f.addRow(tr("Carattere"), fam)
        f.addRow(tr("Altezza"), row(size, bold, italic))
        f.addRow(tr("Allineamento"), row(*al_row))
        f.addRow(tr("Spaziatura lettere"), ls)
        f.addRow(tr("Interlinea"), lsp)
        f.addRow("", row(upper, weld))
        arc = _spin(-360, 360, d.get("arc", 0.0), 0, 15, "°")
        arc.setToolTip(tr("Testo curvo: ampiezza dell'arco occupato dal testo.\n"
                       "Positivo = a ponte (lettere sopra il cerchio), negativo = a sorriso, ±360° = cerchio intero.\n"
                       "0 = testo dritto."))
        arc_info = QLabel("")
        arc_info.setObjectName("muted")
        arc_info.setFont(style.mono_font(8.5))

        def arc_text():
            if shape is None or not shape.arc:
                arc_info.setText(tr("dritto") if not arc.value() else "")
                return
            plain = textmod.text_path(shape.shown_text(), shape.family, shape.size, shape.bold, shape.italic,
                                      shape.align, shape.letter_spacing, shape.line_spacing, shape.upper)
            r = textmod.bend_radius(plain, shape.arc)
            arc_info.setText(tr("Ø {0:.1f} mm", abs(r) * 2))
        arc_text()
        f.addRow(tr("Curvatura"), row(arc, arc_info))

        def set_(key, val, label=tr("Carattere")):
            d[key] = val
            if shape is not None:
                self.ed.modify(shape, label, **{key: val})

        fam.currentIndexChanged.connect(lambda _: fam.currentData() and set_("family", fam.currentData()))
        size.valueChanged.connect(lambda v: set_("size", v, tr("Altezza testo")))
        bold.toggled.connect(lambda v: set_("bold", v))
        italic.toggled.connect(lambda v: set_("italic", v))
        upper.toggled.connect(lambda v: set_("upper", v))
        weld.toggled.connect(lambda v: set_("weld", v))
        ls.valueChanged.connect(lambda v: set_("letter_spacing", v))
        arc.valueChanged.connect(lambda v: (set_("arc", v, tr("Curvatura testo")), arc_text()))
        lsp.valueChanged.connect(lambda v: set_("line_spacing", v))
        for k, b in aligns.items():
            def on(checked, k=k):
                if checked:
                    for kk, bb in aligns.items():
                        if kk != k:
                            bb.blockSignals(True)
                            bb.setChecked(False)
                            bb.blockSignals(False)
                    set_("align", k)
            b.toggled.connect(on)

    def _text(self, s):
        self.lay.addWidget(section(tr("Testo")))
        te = QPlainTextEdit(s.text)
        te.setObjectName("textedit")
        te.setFixedHeight(84)
        te.setPlaceholderText(tr("Scrivi qui il testo (Invio = nuova riga)"))
        te.textChanged.connect(lambda: self._typed(te.toPlainText()))
        self.lay.addWidget(te)
        self.text_edit = te
        vb = QToolButton()
        vb.setText(tr("Inserisci variabile"))
        vb.setIcon(style.icon("variable"))
        vb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        vb.setPopupMode(QToolButton.InstantPopup)
        from PySide6.QtWidgets import QMenu
        from ..core import variables

        vm = QMenu(vb)
        items = [(tr("Numero di serie  {N}"), "{N}"), ("Numero a 3 cifre  {N:3}", "{N:3}"), ("Data  {DATA}", "{DATA}"),
                 ("Anno  {ANNO}", "{ANNO}"), ("Ora  {ORA}", "{ORA}")]
        items += [(f"Colonna CSV «{c}»", "{" + c + "}") for c in variables.columns()]
        for lab, tok in items:
            vm.addAction(lab, lambda tok=tok: te.insertPlainText(tok))
        vm.addSeparator()
        vm.addAction(tr("Numerazione e CSV…"), self.variables_requested.emit)
        vb.setMenu(vm)
        self.lay.addWidget(vb)
        if s.variable:
            shown = QLabel(tr("Ora mostra: «{0}»", s.shown_text()) + (tr("  (copia {0})", s.var_offset + 1) if s.var_offset else ""))
            shown.setWordWrap(True)
            shown.setObjectName("muted")
            self.lay.addWidget(shown)
        d = s.params()
        self._font_controls(d, s)
        if s.single_line:
            hint = QLabel(tr("Carattere a linea singola: usa un livello in modalità Linea per inciderlo con una passata."))
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            self.lay.addWidget(hint)

        if isinstance(s, TextPathShape):
            b = QPushButton(tr("Posizione sulla curva…"))
            b.clicked.connect(lambda: self.window().text_path_dialog())
            self.lay.addWidget(b)
    def _typed(self, txt):
        s = self.shape
        if s is None:
            return
        if not self._typing.isActive():
            self.ed.begin(tr("Modifica testo"))
        s.text = txt
        s.invalidate()
        self.ed.preview_changed()
        self._typing.start()

    def focus_text(self):
        if self.text_edit is not None:
            self.text_edit.setFocus()
            self.text_edit.selectAll()

    def _rect(self, s):
        self.lay.addWidget(section(tr("Rettangolo")))
        f = self._form()
        r = _spin(0, 1000, s.radius, 2, 0.5, " mm")
        r.valueChanged.connect(lambda v: self._mod(tr("Raggio angoli"), radius=v))
        f.addRow(tr("Raggio angoli"), r)

    def _ellipse(self, s):
        self.lay.addWidget(section(tr("Ellisse")))
        lab = QLabel(tr("{0:.2f} × {1:.2f} mm (forma originale, prima delle trasformazioni)", s.w, s.h))
        lab.setObjectName("muted")
        self.lay.addWidget(lab)

    def _polygon(self, s):
        self.lay.addWidget(section(tr("Stella") if s.star else tr("Poligono")))
        f = self._form()
        sides = QSpinBox()
        sides.setRange(3, 64)
        sides.setValue(s.sides)
        sides.valueChanged.connect(lambda v: self._mod(tr("Lati"), sides=v))
        f.addRow(tr("Punte") if s.star else tr("Lati"), sides)
        if s.star:
            ratio = _spin(0.05, 0.95, s.star, 2, 0.05)
            ratio.valueChanged.connect(lambda v: self._mod(tr("Rientranza"), star=v))
            f.addRow(tr("Rientranza"), ratio)

    def _image(self, s):
        self.lay.addWidget(section(tr("Immagine")))
        f = self._form()
        img = self.ed.doc.images.get(s.image_id)
        if img is not None:
            dpi = img.width / max(s.w, 1e-6) * 25.4
            lab = QLabel(tr("{0} × {1} px  ·  {2:.0f} dpi alla dimensione attuale", img.width, img.height, dpi))
            lab.setObjectName("muted")
            self.lay.addWidget(lab)

        def slider(lo, hi, val, scale, label, key):
            sl = QSlider(Qt.Horizontal)
            sl.setRange(int(lo * scale), int(hi * scale))
            sl.setValue(int(val * scale))
            vl = QLabel(f"{val:g}")
            vl.setFixedWidth(36)
            vl.setFont(style.mono_font(9))
            sl.valueChanged.connect(lambda x: vl.setText(f"{x / scale:g}"))
            sl.sliderReleased.connect(lambda: self._mod(label, **{key: sl.value() / scale}))
            f.addRow(label, row(sl, vl, stretch=False))
            return sl

        slider(-100, 100, s.brightness, 1, tr("Luminosità"), "brightness")
        slider(-100, 100, s.contrast, 1, tr("Contrasto"), "contrast")
        slider(0.2, 4.0, s.gamma, 100, tr("Gamma"), "gamma")
        dp = QCheckBox(tr("Mostra il dithering sul disegno (come verrà inciso)"))
        dp.setChecked(self.cv.dither_preview)
        dp.toggled.connect(lambda v: (setattr(self.cv, "dither_preview", v), self.cv.sync()))
        self.lay.addWidget(dp)
        pb = QPushButton(style.icon("photo_prep"), tr("Prepara foto…"))
        pb.setToolTip(tr("Ritaglio, regolazioni, sfondo, forma e metodo di incisione con l'anteprima dei punti veri; "
                         "oppure la foto diventa linee e riempimenti  Ctrl+Alt+F"))
        pb.clicked.connect(self.photo_requested.emit)
        self.lay.addWidget(pb)
        if s.photo:
            pl = QLabel(tr("Foto preparata: riaprendo la finestra riparti dall'originale"))
            pl.setObjectName("muted")
            pl.setWordWrap(True)
            self.lay.addWidget(pl)
        tb = QPushButton(style.icon("trace"), tr("Vettorizza…"))
        tb.setToolTip(tr("Trasforma l'immagine in tracciati (contorno o linea centrale)  Alt+T"))
        tb.clicked.connect(self.trace_requested.emit)
        self.lay.addWidget(tb)
        cs = self.ed.doc.layers.get(s.layer)
        if cs is not None and cs.mode != "image":
            warn = QLabel(tr("⚠ Questa immagine è su un livello non in modalità Immagine: non verrà incisa."))
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color:{C['warn']};")
            self.lay.addWidget(warn)

    def _generic(self, s):
        self.lay.addWidget(section(s.describe()))

    def _common(self, s):
        self.lay.addWidget(hline())
        inf = ops.info([s])
        b = s.bounds()
        lab = QLabel(tr("{0:.2f} × {1:.2f} mm  ·  perimetro {2:.1f} mm", b.width(), b.height(), inf['perimeter'])
                     + (tr("  ·  area {0:.1f} mm²", inf['area']) if inf["closed"] and not isinstance(s, ImageShape) else "")
                     + (tr("\n{0} nodi · ", inf['nodes']) + (tr("chiusa") if not inf["open"] else tr("{0} parti aperte", inf['open']))
                        if not isinstance(s, ImageShape) else ""))
        lab.setObjectName("muted")
        lab.setWordWrap(True)
        self.lay.addWidget(lab)
        lock = QCheckBox(tr("Bloccata (non si sposta né si modifica)"))
        lock.setChecked(s.locked)
        lock.toggled.connect(lambda v: self.ed.lock(v))
        self.lay.addWidget(lock)
