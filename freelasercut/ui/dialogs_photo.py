# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""«Prepara foto»: tutto quello che serve a una foto prima dell'incisione, in una finestra.

A sinistra le regolazioni, a destra l'originale (trascina per ritagliare) e come verrà incisa:
i punti veri alla risoluzione del livello, con il metodo scelto. Seconda scheda: la foto diventa
linee e riempimenti vettoriali, divisi in fasce di tono su livelli diversi."""
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import photo
from ..core.document import DITHER_LABELS, DITHERS, LAYER_COLORS
from ..theme import C
from . import style
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402

PREVIEW_SIDE = 1100  # lato lungo dell'immagine usata per le anteprime (la foto vera si elabora solo ad Applica)
MATERIAL_TINT = {False: ((236, 214, 178), (60, 38, 24)), True: ((58, 60, 64), (210, 210, 205))}  # (fondo, punto)


def _qimage_gray(arr):
    a = np.ascontiguousarray(arr.astype(np.uint8))
    return QImage(a.data, a.shape[1], a.shape[0], a.shape[1], QImage.Format_Grayscale8).copy()


def _qimage_rgb(arr):
    a = np.ascontiguousarray(arr.astype(np.uint8))
    return QImage(a.data, a.shape[1], a.shape[0], 3 * a.shape[1], QImage.Format_RGB888).copy()


class _View(QWidget):
    """Immagine adattata al riquadro; facoltativi: rettangolo di ritaglio trascinabile e tracciati sopra."""

    crop_changed = Signal(tuple)

    def __init__(self, title, croppable=False):
        super().__init__()
        self.setMinimumSize(280, 240)
        self.title = title
        self.qimg = None
        self.crop = None  # (x0, y0, x1, y1) frazioni
        self.croppable = croppable
        self._drag = None
        self.paths = []  # [(QPainterPath in mm, QColor, riempito)]
        self.mm = None  # (w, h) dei tracciati
        self.faint = False
        self.note = ""
        if croppable:
            self.setCursor(Qt.CrossCursor)

    def _target(self):
        m = 10
        top = 22
        if self.qimg is None or self.qimg.width() == 0:
            return QRectF(m, top, max(1, self.width() - 2 * m), max(1, self.height() - top - m))
        iw, ih = self.qimg.width(), self.qimg.height()
        k = min((self.width() - 2 * m) / iw, (self.height() - top - m) / ih)
        w, h = iw * k, ih * k
        return QRectF((self.width() - w) / 2, top + (self.height() - top - m - h) / 2, w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(C["bg"]))
        p.setPen(QColor(C["muted"]))
        p.setFont(style.ui_font(8.5))
        p.drawText(QRectF(10, 2, self.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        if self.note:
            p.drawText(QRectF(10, 2, self.width() - 20, 18), Qt.AlignRight | Qt.AlignVCenter, self.note)
        t = self._target()
        if self.qimg is not None:
            if self.faint:
                p.fillRect(t, QColor("white"))
                p.setOpacity(0.3)
            p.drawImage(t, self.qimg)
            p.setOpacity(1.0)
        if self.paths and self.mm:
            w, h = self.mm
            k = min(t.width() / w, t.height() / h)
            tf = QTransform.fromScale(k, -k) * QTransform.fromTranslate(t.left(), t.top() + h * k)
            p.save()
            p.setTransform(tf)
            for path, col, filled in self.paths:
                pen = QPen(col, 1.2)
                pen.setCosmetic(True)
                p.setPen(pen)
                if filled:
                    c2 = QColor(col)
                    c2.setAlpha(150)
                    p.setBrush(c2)
                else:
                    p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            p.restore()
        if self.croppable and self.crop is not None:
            x0, y0, x1, y1 = self.crop
            r = QRectF(t.left() + x0 * t.width(), t.top() + y0 * t.height(), (x1 - x0) * t.width(), (y1 - y0) * t.height())
            shade = QColor(0, 0, 0, 120)
            for rr in (QRectF(t.left(), t.top(), t.width(), r.top() - t.top()),
                       QRectF(t.left(), r.bottom(), t.width(), t.bottom() - r.bottom()),
                       QRectF(t.left(), r.top(), r.left() - t.left(), r.height()),
                       QRectF(r.right(), r.top(), t.right() - r.right(), r.height())):
                if rr.width() > 0 and rr.height() > 0:
                    p.fillRect(rr, shade)
            pen = QPen(QColor(C["accent"]), 1.5, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        p.end()

    def _frac(self, pos):
        t = self._target()
        return (min(max((pos.x() - t.left()) / max(t.width(), 1), 0.0), 1.0),
                min(max((pos.y() - t.top()) / max(t.height(), 1), 0.0), 1.0))

    def mousePressEvent(self, e):
        if self.croppable and e.button() == Qt.LeftButton:
            self._drag = self._frac(e.position())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            a, b = self._drag, self._frac(e.position())
            self.crop = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            x0, y0, x1, y1 = self.crop or (0, 0, 1, 1)
            if x1 - x0 < 0.03 or y1 - y0 < 0.03:  # clic senza trascinare: niente ritaglio
                self.crop = (0.0, 0.0, 1.0, 1.0)
            self.crop_changed.emit(tuple(self.crop))
            self.update()

    def mouseDoubleClickEvent(self, e):
        if self.croppable:
            self.crop = (0.0, 0.0, 1.0, 1.0)
            self.crop_changed.emit(self.crop)
            self.update()


def _slider(lo, hi, val):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(int(round(val)))
    return s


class PhotoDialog(QDialog):
    """shape: ImageShape; original: PIL dell'immagine originale; cs: livello della foto.

    Dopo exec(): mode() -> "image" | "vector" | "test"; settings() per la foto; vector_params()."""

    def __init__(self, shape, original, cs, size_mm, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Prepara foto"))
        self.shape, self.cs = shape, cs
        self.original = original
        self._mode = "image"
        st = photo.PhotoSettings.from_dict(shape.photo)
        # anteprime su una copia ridotta: la foto vera si elabora solo ad Applica
        prev = original.copy()
        prev.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.LANCZOS)
        self.prev_src = prev
        self.size_mm = size_mm  # (larghezza, altezza) attuali sul piano

        from PySide6.QtGui import QGuiApplication

        scr = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.resize(min(1400, int(g.width() * 0.9)), min(860, int(g.height() * 0.9)))
        root = QHBoxLayout(self)
        left_box = QWidget()
        lv = QVBoxLayout(left_box)
        lv.setContentsMargins(0, 0, 6, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left_box)
        scroll.setFixedWidth(440)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side = QVBoxLayout()
        side.addWidget(scroll, 1)
        root.addLayout(side, 0)

        f0 = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem(tr("— scegli il materiale —"), None)
        for key, (label, _v) in photo.PRESETS.items():
            self.preset.addItem(label, key)
        self.preset.setToolTip(tr("Imposta metodo, gamma, contrasto, negativo e risoluzione adatti al materiale.\n"
                                  "Velocità e potenza restano quelle del livello (libreria materiali)."))
        f0.addRow(tr("Materiale"), self.preset)
        for cb in (self.preset,):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
        lv.addLayout(f0)

        self.tabs = QTabWidget()
        lv.addWidget(self.tabs)
        # ---------------------------------------------------------------- scheda Foto
        t1 = QWidget()
        f = QFormLayout(t1)
        f.addRow(section(tr("Orientamento e ritaglio")))
        b_l = QPushButton("↺ 90°")
        b_r = QPushButton("↻ 90°")
        self.flip = QCheckBox(tr("Specchia"))
        self.flip.setChecked(st.flip)
        rr = QHBoxLayout()
        rr.addWidget(b_l)
        rr.addWidget(b_r)
        rr.addWidget(self.flip)
        f.addRow(tr("Ruota"), rr)
        self.rotate = st.rotate
        b_l.clicked.connect(lambda: self._rot(-90))
        b_r.clicked.connect(lambda: self._rot(90))
        crow = QHBoxLayout()
        self.crop_lab = QLabel("")
        self.crop_lab.setObjectName("muted")
        b_nocrop = QPushButton(tr("Togli ritaglio"))
        b_nocrop.clicked.connect(lambda: self._set_crop((0.0, 0.0, 1.0, 1.0)))
        crow.addWidget(self.crop_lab, 1)
        crow.addWidget(b_nocrop)
        f.addRow(tr("Ritaglio"), crow)

        f.addRow(section(tr("Dimensione e risoluzione")))
        self.width_mm = QDoubleSpinBox()
        self.width_mm.setRange(2.0, 2000.0)
        self.width_mm.setDecimals(1)
        self.width_mm.setSuffix(" mm")
        self.width_mm.setValue(round(size_mm[0], 1))
        self.size_lab = QLabel("")
        self.size_lab.setObjectName("muted")
        wr = QHBoxLayout()
        wr.addWidget(self.width_mm)
        wr.addWidget(self.size_lab, 1)
        f.addRow(tr("Larghezza"), wr)
        self.dpi = QSpinBox()
        self.dpi.setRange(50, 1000)
        self.dpi.setSingleStep(10)
        self.dpi.setSuffix(" dpi")
        self.dpi.setValue(int(round(cs.dpi)))
        self.dpi.setToolTip(tr("Punti per pollice del livello: 254 dpi = 10 punti per mm (righe a 0,1 mm)"))
        self.dots_lab = QLabel("")
        self.dots_lab.setObjectName("muted")
        self.dots_lab.setWordWrap(True)
        f.addRow(tr("Risoluzione"), self.dpi)
        f.addRow("", self.dots_lab)

        f.addRow(section(tr("Regolazioni")))
        self.bri = _slider(-100, 100, shape.brightness)
        self.con = _slider(-100, 100, shape.contrast)
        self.gam = _slider(20, 300, shape.gamma * 100)
        self.gam.setToolTip(tr("Più di 1 schiarisce i mezzitoni (il legno tende a scurire), meno di 1 li scurisce"))
        self.auto = QCheckBox(tr("Livelli automatici"))
        self.auto.setToolTip(tr("Allarga i toni: il punto più chiaro diventa bianco e il più scuro nero"))
        self.auto.setChecked(st.auto_levels)
        self.local = _slider(0, 100, st.local_contrast)
        self.local.setToolTip(tr("Contrasto locale: tira fuori i dettagli nelle zone scure e chiare (CLAHE)"))
        self.sharp = _slider(0, 100, st.sharpen)
        self.noise = _slider(0, 100, st.denoise)
        self.noise.setToolTip(tr("Liscia la grana della foto conservando i bordi"))
        self.labels = {}
        for lab, w, fmt in ((tr("Luminosità"), self.bri, "{:+d}"), (tr("Contrasto"), self.con, "{:+d}"),
                            (tr("Gamma"), self.gam, "g"), (tr("Contrasto locale"), self.local, "{:d}"),
                            (tr("Nitidezza"), self.sharp, "{:d}"), (tr("Riduci rumore"), self.noise, "{:d}")):
            vl = QLabel("")
            vl.setFixedWidth(40)
            vl.setFont(style.mono_font(9))
            self.labels[w] = (vl, fmt)
            h = QHBoxLayout()
            h.addWidget(w, 1)
            h.addWidget(vl)
            f.addRow(lab, h)
            w.valueChanged.connect(lambda _v, ww=w: self._val_label(ww))
            self._val_label(w)
        f.addRow("", self.auto)

        f.addRow(section(tr("Sfondo e forma")))
        self.bg = QCheckBox(tr("Togli lo sfondo uniforme"))
        self.bg.setChecked(st.bg_remove)
        self.bg.setToolTip(tr("Lo sfondo è il colore lungo i bordi della foto: le zone simili collegate ai bordi "
                              "diventano bianche e non si incidono"))
        f.addRow("", self.bg)
        self.bg_tol = _slider(0, 100, st.bg_tolerance)
        f.addRow(tr("Tolleranza"), self.bg_tol)
        self.mask = QComboBox()
        for k, lab in (("none", tr("Rettangolo")), ("oval", tr("Ovale")), ("rounded", tr("Angoli arrotondati"))):
            self.mask.addItem(lab, k)
        self.mask.setCurrentIndex(max(0, self.mask.findData(st.mask)))
        f.addRow(tr("Forma"), self.mask)
        self.fade = _slider(0, 100, st.edge_fade)
        self.fade.setToolTip(tr("Bordi che sfumano nel bianco"))
        f.addRow(tr("Bordi sfumati"), self.fade)

        f.addRow(section(tr("Incisione")))
        self.dither = QComboBox()
        for d in DITHERS:
            self.dither.addItem(DITHER_LABELS[d], d)
        self.dither.setCurrentIndex(max(0, self.dither.findData(cs.dither)))
        for cb in (self.dither, self.mask):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
        f.addRow(tr("Metodo"), self.dither)
        self.neg = QCheckBox(tr("Negativo"))
        self.neg.setToolTip(tr("Per i materiali che il laser schiarisce: ardesia, alluminio anodizzato"))
        self.neg.setChecked(cs.negative)
        f.addRow("", self.neg)
        self.real = QCheckBox(tr("Zona centrale 1:1 (punti veri)"))
        self.real.setToolTip(tr("Mostra la zona centrale alla risoluzione vera del laser, punto per punto"))
        f.addRow("", self.real)
        self.b_test = QPushButton(style.icon("library"), tr("Prova foto: 4 metodi a confronto…"))
        self.b_test.setToolTip(tr("Aggiunge sul piano 4 quadrati della zona centrale, uno per metodo, su livelli "
                                  "separati: incidili e scegli il migliore"))
        self.b_test.clicked.connect(self._make_test)
        f.addRow(self.b_test)
        self.tabs.addTab(t1, tr("Foto"))

        # ---------------------------------------------------------------- scheda Linee e riempimento
        t2 = QWidget()
        g = QFormLayout(t2)
        intro = QLabel(tr("La foto diventa vettoriale: fasce di tono come riempimenti (la più scura con più potenza) "
                          "e, se vuoi, il contorno e le linee dei dettagli. Ogni fascia va su un livello suo."))
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        g.addRow(intro)
        self.tones = QSpinBox()
        self.tones.setRange(1, 4)
        self.tones.setValue(2)
        g.addRow(tr("Toni di riempimento"), self.tones)
        self.v_detail = _slider(0, 100, 55)
        g.addRow(tr("Dettaglio"), self.v_detail)
        self.v_smooth = _slider(0, 100, 50)
        g.addRow(tr("Morbidezza"), self.v_smooth)
        self.v_speck = _slider(0, 300, 50)
        self.v_speck.setToolTip(tr("Macchie più piccole di così vengono ignorate"))
        g.addRow(tr("Ignora macchie"), self.v_speck)
        self.v_outline = QCheckBox(tr("Contorno delle zone scure (linea)"))
        self.v_outline.setChecked(True)
        g.addRow("", self.v_outline)
        self.v_edges = QCheckBox(tr("Linee dei dettagli (bordi netti della foto)"))
        g.addRow("", self.v_edges)
        self.v_keep = QCheckBox(tr("Tieni anche la foto"))
        g.addRow("", self.v_keep)
        self.v_info = QLabel("")
        self.v_info.setObjectName("muted")
        self.v_info.setWordWrap(True)
        g.addRow(self.v_info)
        self.tabs.addTab(t2, tr("Linee e riempimento"))
        lv.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        side.addWidget(bb)

        right = QVBoxLayout()
        views = QHBoxLayout()
        self.v_orig = _View(tr("Originale · trascina per ritagliare, doppio clic per togliere"), croppable=True)
        self.v_res = _View(tr("Come verrà incisa"))
        views.addWidget(self.v_orig, 1)
        views.addWidget(self.v_res, 1)
        right.addLayout(views, 1)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        right.addWidget(self.info)
        root.addLayout(right, 1)

        self.crop = tuple(st.crop)
        self.v_orig.crop = self.crop
        self.v_orig.crop_changed.connect(self._set_crop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._refresh)
        for w in (self.bri, self.con, self.gam, self.local, self.sharp, self.noise, self.bg_tol, self.fade,
                  self.v_detail, self.v_smooth, self.v_speck):
            w.valueChanged.connect(self._later)
        for w in (self.auto, self.bg, self.flip, self.neg, self.real, self.v_outline, self.v_edges):
            w.toggled.connect(self._later)
        for w in (self.mask, self.dither):
            w.currentIndexChanged.connect(self._later)
        self.tones.valueChanged.connect(self._later)
        self.width_mm.valueChanged.connect(self._later)
        self.dpi.valueChanged.connect(self._later)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.tabs.currentChanged.connect(self._tab)
        self._orig_rotated = None
        self._tab()
        self._show_original()
        self._refresh()

    # ------------------------------------------------------------------ helpers
    def _val_label(self, w):
        lab, fmt = self.labels[w]
        v = w.value()
        lab.setText(f"{v / 100:.2f}" if fmt == "g" else fmt.format(v))

    def _later(self, *_):
        self._timer.start()

    def _rot(self, d):
        self.rotate = (self.rotate + d) % 360
        # ritaglio: lo ruoto insieme alla foto
        x0, y0, x1, y1 = self.crop
        if d > 0:
            self.crop = (1 - y1, x0, 1 - y0, x1)
        else:
            self.crop = (y0, 1 - x1, y1, 1 - x0)
        self.v_orig.crop = self.crop
        self._show_original()
        self._later()

    def _set_crop(self, c):
        self.crop = tuple(float(v) for v in c)
        self.v_orig.crop = self.crop
        self.v_orig.update()
        self._later()

    def _apply_preset(self):
        key = self.preset.currentData()
        if not key:
            return
        v = photo.PRESETS[key][1]
        self.dither.setCurrentIndex(max(0, self.dither.findData(v["dither"])))
        self.dpi.setValue(int(v["dpi"]))
        self.neg.setChecked(bool(v["negative"]))
        self.gam.setValue(int(round(v["gamma"] * 100)))
        self.con.setValue(int(round(v["contrast"])))

    def _tab(self, *_):
        vec = self.tabs.currentIndex() == 1
        self.ok_btn.setText(tr("Crea linee e riempimenti") if vec else tr("Applica alla foto"))
        self.v_res.title = tr("Linee e riempimenti") if vec else tr("Come verrà incisa")
        self._later()

    def settings(self):
        return photo.PhotoSettings(crop=self.crop, rotate=self.rotate, flip=self.flip.isChecked(),
                                   bg_remove=self.bg.isChecked(), bg_tolerance=float(self.bg_tol.value()),
                                   denoise=float(self.noise.value()), auto_levels=self.auto.isChecked(),
                                   local_contrast=float(self.local.value()), sharpen=float(self.sharp.value()),
                                   mask=self.mask.currentData(), edge_fade=float(self.fade.value()))

    def adjust(self):
        return dict(brightness=float(self.bri.value()), contrast=float(self.con.value()), gamma=self.gam.value() / 100.0)

    def layer_values(self):
        return dict(dither=self.dither.currentData(), dpi=float(self.dpi.value()), negative=self.neg.isChecked())

    def vector_params(self):
        return dict(tones=self.tones.value(), detail=self.v_detail.value() / 100.0, smooth=self.v_smooth.value() / 100.0,
                    outlines=self.v_outline.isChecked(), edges=self.v_edges.isChecked(),
                    min_size_mm=self.v_speck.value() / 100.0, keep=self.v_keep.isChecked())

    def target_size(self, processed):
        """(larghezza, altezza) in mm della foto preparata (la larghezza scelta, l'altezza segue le proporzioni)."""
        w = self.width_mm.value()
        return w, w * processed.height / max(processed.width, 1)

    def mode(self):
        return self._mode

    # ------------------------------------------------------------------ anteprime
    def _show_original(self):
        g, _a = photo.to_gray(self.prev_src)
        if self.prev_src.mode not in ("L", "1"):
            rgb = np.asarray(self.prev_src.convert("RGB"))
            img = _qimage_rgb(photo.orient(rgb, self.rotate, self.flip.isChecked()))
        else:
            img = _qimage_gray(photo.orient(g, self.rotate, self.flip.isChecked()))
        self.v_orig.qimg = img
        self.v_orig.update()

    def _refresh(self):
        self._show_original()
        st = self.settings()
        try:
            proc = photo.process(self.prev_src, st)
        except Exception as ex:  # noqa: BLE001
            self.info.setText(tr("Errore: {0}", ex))
            return
        a = self.adjust()
        w_mm, h_mm = self.target_size(proc)
        dpi = float(self.dpi.value())
        dots = photo.dots_count(w_mm, h_mm, dpi)
        self.size_lab.setText(tr("× {0:.1f} mm", h_mm))
        self.dots_lab.setText(tr("{0:.1f} milioni di punti · {1:.0f} righe", dots / 1e6, h_mm / (25.4 / dpi)))
        x0, y0, x1, y1 = st.crop
        self.crop_lab.setText(tr("nessuno") if st.crop == (0.0, 0.0, 1.0, 1.0) else
                              tr("{0:.0f}% × {1:.0f}%", (x1 - x0) * 100, (y1 - y0) * 100))
        if self.tabs.currentIndex() == 1:
            self._refresh_vectors(proc, w_mm, h_mm, a)
            return
        self.v_res.paths = []
        self.v_res.faint = False
        lv = self.layer_values()
        try:
            if self.real.isChecked():
                full = photo.process(self.original, st)  # punti veri: serve la foto vera
                dots_img, k = photo.engrave_preview(full, w_mm, h_mm, dpi, lv["dither"], negative=lv["negative"],
                                                    region=(0.4, 0.4, 0.6, 0.6), halftone_cell=self.cs.halftone_cell,
                                                    halftone_angle=self.cs.halftone_angle, **a)
                self.v_res.note = tr("zona centrale 1:1")
            else:
                dots_img, k = photo.engrave_preview(proc, w_mm, h_mm, dpi, lv["dither"], negative=lv["negative"],
                                                    halftone_cell=self.cs.halftone_cell,
                                                    halftone_angle=self.cs.halftone_angle, **a)
                self.v_res.note = tr("ridotta") if k < 0.999 else ""
        except Exception as ex:  # noqa: BLE001
            self.info.setText(tr("Errore: {0}", ex))
            return
        bg, ink = MATERIAL_TINT[lv["negative"]]
        bg, ink = np.float32(bg), np.float32(ink)
        rgb = bg + (ink - bg) * dots_img[..., None]
        self.v_res.qimg = _qimage_rgb(rgb)
        self.v_res.update()
        self.info.setText(tr("{0} · {1:.1f} × {2:.1f} mm · {3:.0f} dpi", DITHER_LABELS[lv["dither"]], w_mm, h_mm, dpi))

    def _refresh_vectors(self, proc, w_mm, h_mm, a):
        p = self.vector_params()
        try:
            r = photo.to_vectors(proc, w_mm, h_mm, tones=p["tones"], detail=p["detail"], smooth=p["smooth"],
                                 outlines=p["outlines"], edges=p["edges"], min_size_mm=p["min_size_mm"], **a)
        except Exception as ex:  # noqa: BLE001
            self.v_info.setText(tr("Errore: {0}", ex))
            return
        paths = []
        n = len(r["fills"])
        for i, (path, dark) in enumerate(r["fills"]):
            col = QColor.fromHsvF(0.07, 0.75, max(0.25, 0.95 - 0.6 * (i + 1) / max(n, 1)))
            paths.append((path, col, True))
        if r["outline"] is not None:
            paths.append((r["outline"], QColor(LAYER_COLORS[1]), False))
        if r["edges"] is not None:
            paths.append((r["edges"], QColor(LAYER_COLORS[3]), False))
        g = np.asarray(proc.convert("L"))
        self.v_res.qimg = _qimage_gray(g)
        self.v_res.faint = True
        self.v_res.paths = paths
        self.v_res.mm = (w_mm, h_mm)
        self.v_res.note = ""
        self.v_res.update()
        self._vectors = r
        self.info.setText(tr("{0:.1f} × {1:.1f} mm · i colori mostrano le fasce: più scuro = più potenza", w_mm, h_mm))
        self.v_info.setText(tr("{0} fasce di riempimento", n) + (tr(" · contorno") if r["outline"] is not None else "")
                            + (tr(" · linee dei dettagli") if r["edges"] is not None else ""))

    # ------------------------------------------------------------------ uscita
    def _make_test(self):
        self._mode = "test"
        self.accept()

    def _accept(self):
        self._mode = "vector" if self.tabs.currentIndex() == 1 else "image"
        self.accept()
