# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Puzzle da foto: la foto (o nessuna) diventa un puzzle da incidere e tagliare.

Due livelli: la foto in modalità Immagine e i tagli in modalità Linea, messi per ultimi nell'ordine del lavoro
(prima si incide, poi si taglia: un pezzo già staccato non si inciderebbe più al suo posto). Dentro il livello del
taglio FreeLaserCut taglia prima i lati interni e per ultimo il contorno, così il foglio non si sposta.
"""
import math
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core import geom, puzzle as pzmod
from ..core.document import GroupShape, ImageShape, PathShape, default_layer
from freelasercut.i18n import tr  # noqa: E402

TAB_SIZES = ((0.9, tr("Piccoli")), (1.0, tr("Normali")), (1.1, tr("Grandi")))
PREVIEW = (460, 360)
CUT_COLOR = "#E5484D"


def _gray(img):
    """Foto in grigi su fondo bianco (le parti trasparenti diventano bianche: non si incidono)."""
    from PIL import Image

    if img.mode in ("RGBA", "LA", "PA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        return bg.convert("L")
    return img.convert("L")


def fit_photo(img, w_mm, h_mm, outline=None):
    """La foto riempie il puzzle w × h mm (ritaglio al centro se le proporzioni sono diverse); fuori dalla forma
    diventa bianca (niente da incidere sugli scarti)."""
    from PIL import Image, ImageDraw

    g = _gray(img)
    target = w_mm / max(h_mm, 1e-6)
    W, H = g.size
    if W / H > target:  # foto più larga: taglio ai lati
        nw = max(1, round(H * target))
        x0 = (W - nw) // 2
        g = g.crop((x0, 0, x0 + nw, H))
    elif W / H < target:
        nh = max(1, round(W / target))
        y0 = (H - nh) // 2
        g = g.crop((0, y0, W, y0 + nh))
    if outline:
        sx, sy = g.width / w_mm, g.height / h_mm
        mask = Image.new("L", g.size, 0)
        ImageDraw.Draw(mask).polygon([(x * sx, y * sy) for x, y in outline], fill=255)
        g = Image.composite(g, Image.new("L", g.size, 255), mask)
    return g


def cuts_path(pz, x0, y0):
    """Tagli del puzzle sul piano: (x0, y0) è l'angolo in basso a sinistra; la Y del puzzle va in giù, quella del
    piano in su."""
    p = QPainterPath()
    H = pz.height
    # lati interni prima e contorno per ultimo già nel tracciato: l'ordine resta giusto anche se l'ottimizzazione
    # dei percorsi è spenta
    for k, line in [(k, c) for k, c in enumerate(pz.cuts) if k > 0] + [(0, pz.cuts[0])]:
        pts = [(x0 + x, y0 + H - y) for x, y in line]
        closed = k == 0
        if closed and math.dist(pts[0], pts[-1]) < 1e-6:
            pts = pts[:-1]
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        if closed:
            p.closeSubpath()
    return p


class PuzzleDialog(QDialog):
    def __init__(self, parent=None, photo=None, size=(200.0, 150.0), outline=None, photo_name=""):
        """photo: immagine PIL (o None). size: misure di partenza (mm). outline: contorno della forma selezionata
        in coordinate del puzzle (Y in giù, dentro size), o None."""
        super().__init__(parent)
        self.setWindowTitle(tr("Puzzle da foto"))
        self.setMinimumWidth(820)
        self.photo = photo
        self.sel_outline = outline
        self.seed = 1
        self.puzzle = None
        self._gray = _gray(photo) if photo is not None else None
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        f = QFormLayout()
        self.photo_lbl = QLabel(photo_name or (tr("La foto selezionata") if photo is not None else tr("Nessuna foto")))
        self.photo_lbl.setWordWrap(True)
        pick = QPushButton(tr("Scegli foto…"))
        pick.clicked.connect(self._pick_photo)
        none = QPushButton(tr("Senza foto"))
        none.setToolTip(tr("Solo i tagli: per un puzzle da dipingere o da incidere dopo"))
        none.clicked.connect(self._no_photo)
        ph = QHBoxLayout()
        ph.addWidget(self.photo_lbl, 1)
        ph.addWidget(pick)
        ph.addWidget(none)
        f.addRow(tr("Foto"), ph)
        self.shape = QComboBox()
        for k, lab in pzmod.SHAPES.items():
            if k != "selected" or outline:
                self.shape.addItem(lab, k)
        self.shape.setToolTip(tr("Forma del puzzle. «La forma selezionata»: un contorno chiuso che hai disegnato "
                                 "(selezionalo insieme alla foto prima di aprire questa finestra)."))
        if outline:
            self.shape.setCurrentIndex(self.shape.findData("selected"))
        f.addRow(tr("Forma"), self.shape)
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
        for sp, val in ((self.w, size[0]), (self.h, size[1])):
            sp.setRange(20.0, 1500.0)
            sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setValue(val)
        f.addRow(tr("Larghezza"), self.w)
        f.addRow(tr("Altezza"), self.h)
        self.keep = QCheckBox(tr("Proporzioni della foto"))
        self.keep.setToolTip(tr("Cambiando una misura cambia anche l'altra. Se la togli, la foto riempie il puzzle "
                                "e quello che avanza ai lati viene tagliato via."))
        self.keep.setChecked(photo is not None)
        self.keep.setVisible(photo is not None)
        f.addRow("", self.keep)
        self.count = QSpinBox()
        self.count.setRange(pzmod.COUNT_MIN, pzmod.COUNT_MAX)
        self.count.setValue(30)
        self.count.setToolTip(tr("Numero di pezzi (circa: righe e colonne vengono scelte per avere pezzi quasi quadrati)"))
        f.addRow(tr("Pezzi"), self.count)
        self.tabs = QComboBox()
        for val, lab in TAB_SIZES:
            self.tabs.addItem(lab, val)
        self.tabs.setCurrentIndex(1)
        self.tabs.setToolTip(tr("Grandezza delle teste degli incastri: più grandi = pezzi più robusti"))
        f.addRow(tr("Incastri"), self.tabs)
        shuffle = QPushButton(tr("Rimescola"))
        shuffle.setToolTip(tr("Un altro puzzle con le stesse misure: ogni volta i pezzi sono diversi"))
        shuffle.clicked.connect(self._shuffle)
        f.addRow("", shuffle)
        h.addLayout(f, 1)
        self.preview = QLabel()
        self.preview.setFixedSize(*PREVIEW)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#FFFFFF; border-radius:8px;")
        h.addWidget(self.preview)
        v.addLayout(h)
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        tip = QLabel(tr("FreeLaserCut crea due livelli: la foto (<b>Immagine</b>) e i tagli (<b>Linea</b>), con il "
                        "taglio per ultimo. Prima di avviare imposta velocità, potenza e passate del taglio per il tuo "
                        "legno (o scegli il materiale). I lati interni si tagliano prima del contorno."))
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        v.addWidget(tip)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Crea il puzzle"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh)
        self._lock = False
        self.w.valueChanged.connect(lambda _v: self._linked(self.w))
        self.h.valueChanged.connect(lambda _v: self._linked(self.h))
        for sig in (self.shape.currentIndexChanged, self.count.valueChanged, self.tabs.currentIndexChanged,
                    self.keep.toggled):
            sig.connect(self._later)
        self.shape.currentIndexChanged.connect(self._shape_changed)
        self._shape_changed()
        self._refresh()

    # ---------------------------------------------------------------- valori
    def kind(self):
        return self.shape.currentData() or "rect"

    def size_mm(self):
        if self.kind() == "selected" and self.sel_outline:
            xs, ys = [p[0] for p in self.sel_outline], [p[1] for p in self.sel_outline]
            return max(xs) - min(xs), max(ys) - min(ys)  # la forma ha le sue misure (anche sotto i 20 mm)
        return float(self.w.value()), float(self.h.value())

    def outline(self):
        """Contorno nelle coordinate del puzzle (Y in giù) o None per il rettangolo."""
        if self.kind() == "selected":
            return self.sel_outline
        w, h = self.size_mm()
        return pzmod.outline_for(self.kind(), w, h)

    def values(self):
        return dict(kind=self.kind(), size=self.size_mm(), count=self.count.value(), seed=self.seed,
                    tab_style=float(self.tabs.currentData()), photo=self.photo)

    # ---------------------------------------------------------------- eventi
    def _linked(self, which):
        if not self._lock and self.keep.isChecked() and self._gray is not None and self.kind() != "selected":
            r = self._gray.width / max(self._gray.height, 1)
            self._lock = True
            if which is self.w:
                self.h.setValue(self.w.value() / r)
            else:
                self.w.setValue(self.h.value() * r)
            self._lock = False
        self._later()

    def _shape_changed(self, *_):
        sel = self.kind() == "selected"
        for x in (self.w, self.h, self.keep):
            x.setEnabled(not sel)  # la forma selezionata ha già le sue misure

    def _later(self, *_):
        self._timer.start()

    def accept(self):
        """Il puzzle creato è sempre quello delle misure scritte (anche premendo Invio subito dopo averle cambiate)."""
        self._timer.stop()
        self._refresh()
        if self.puzzle is None or not self.puzzle.pieces:
            return
        super().accept()

    def _shuffle(self):
        self.seed += 1
        self._refresh()

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Scegli la foto del puzzle"), "",
                                              tr("Immagini (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"))
        if not path:
            return
        from PIL import Image

        from ..core.io_formats import _upright_8bit

        try:
            img = Image.open(path)
            img.load()
            img = _upright_8bit(img)
        except Exception as ex:  # noqa: BLE001 - file non leggibile: lo dico e resto com'ero
            QMessageBox.warning(self, tr("Puzzle da foto"), tr("Non riesco ad aprire la foto: {0}", ex))
            return
        import os

        self.set_photo(img, os.path.basename(path))

    def set_photo(self, img, name=""):
        self.photo = img
        self._gray = _gray(img) if img is not None else None
        self.photo_lbl.setText(name or (tr("Nessuna foto") if img is None else tr("La foto selezionata")))
        self.keep.setVisible(img is not None)
        self.keep.setChecked(img is not None)
        if img is not None and self.kind() != "selected":
            self._linked(self.w)
        self._refresh()

    def _no_photo(self):
        self.set_photo(None)

    # ---------------------------------------------------------------- anteprima
    def _refresh(self):
        w, h = self.size_mm()
        from PySide6.QtWidgets import QApplication

        QApplication.setOverrideCursor(Qt.WaitCursor)  # con centinaia di pezzi serve un secondo o due
        try:
            self.puzzle = pzmod.generate(w, h, self.count.value(), seed=self.seed, shape=self.outline(),
                                         tab_style=float(self.tabs.currentData()))
        except Exception as ex:  # noqa: BLE001 - forma impossibile: niente puzzle, lo dico
            self.puzzle = None
            self.info.setText(tr("<span style='color:{0}'>Non riesco a creare il puzzle con questa forma: {1}</span>",
                                 CUT_COLOR, ex))
            self.ok_btn.setEnabled(False)
            return
        finally:
            QApplication.restoreOverrideCursor()
        pz = self.puzzle
        self.ok_btn.setEnabled(bool(pz.pieces))
        size = sum(pzmod._area(p) for p in pz.pieces) / max(len(pz.pieces), 1)
        text = tr("<b>{0} pezzi</b> · lato di circa {1:.0f} mm · collo più stretto {2:.1f} mm",
                  len(pz.pieces), math.sqrt(size), pz.neck_mm)
        if pz.warnings:
            text += "<br><span style='color:{0}'>".format(CUT_COLOR) + "<br>".join(sorted(set(pz.warnings))) + "</span>"
        self.info.setText(text)
        self.preview.setPixmap(self.render_preview(*PREVIEW))

    def render_preview(self, pw, ph):
        pz = self.puzzle
        pm = QPixmap(pw, ph)
        pm.fill(QColor("#FFFFFF"))
        if pz is None:
            return pm
        k = min((pw - 16) / pz.width, (ph - 16) / pz.height)
        ox, oy = (pw - pz.width * k) / 2, (ph - pz.height * k) / 2
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        tf = QTransform(k, 0, 0, k, ox, oy)
        outline = QPainterPath()
        outline.moveTo(*pz.outline[0])
        for q in pz.outline[1:]:
            outline.lineTo(*q)
        outline.closeSubpath()
        outline = tf.map(outline)
        if self._gray is not None:
            g = fit_photo(self._gray, pz.width, pz.height)
            g = g.resize((max(1, int(pz.width * k)), max(1, int(pz.height * k))))
            qi = QImage(g.tobytes(), g.width, g.height, g.width, QImage.Format_Grayscale8).copy()
            p.save()
            p.setClipPath(outline)
            p.setOpacity(0.85)
            p.drawImage(QPointF(ox, oy), qi)
            p.restore()
        pen = QPen(QColor(CUT_COLOR))
        pen.setWidthF(1.2)
        p.setPen(pen)
        for line in pz.cuts:
            path = QPainterPath()
            path.moveTo(*line[0])
            for q in line[1:]:
                path.lineTo(*q)
            p.drawPath(tf.map(path))
        p.end()
        return pm


# ==================================================================== dal programma
def _selection(win):
    """Dalla selezione: (foto ImageShape o None, forma chiusa [(x,y)] sul piano o None, forme usate, problema).
    problema: testo da mostrare se la selezione non si può usare (gruppo con una foto dentro, foto ruotata)."""
    img, outline, used = None, None, []
    for s in win.editor.selection:
        if isinstance(s, ImageShape):
            if img is None:
                img = s
                used.append(s)
            continue
        if isinstance(s, GroupShape) and any(isinstance(leaf, ImageShape) for leaf, _ in s.leaves()):
            return None, None, [], tr("La foto è dentro un gruppo: separa il gruppo (Disponi → Separa) e riprova.")
        if outline is not None:
            continue
        best = None
        for leaf, tf in s.leaves():
            for poly in geom.flatten(tf.map(leaf.local_path()), 0.1):
                if poly.closed and len(poly.pts) >= 3 and (best is None or abs(poly.area()) > abs(best.area())):
                    best = poly
        if best is not None:
            outline = list(best.pts)
            used.append(s)
    if img is not None:
        win._unmirror_photo(img)  # uno specchio nella posizione passa nei pixel: la foto resta com'è sul piano
        t = img.tf
        if abs(t.m12()) > 1e-6 or abs(t.m21()) > 1e-6 or t.m11() <= 0 or t.m22() <= 0:
            return None, None, [], tr("La foto è ruotata: rimettila dritta (rotazione 0°) e riprova.")
    return img, outline, used, None


def run_puzzle(win):
    doc = win.editor.doc
    img, outline_bed, used, problem = _selection(win)
    if problem:
        QMessageBox.warning(win, tr("Puzzle da foto"), problem)
        return None
    photo = doc.images.get(img.image_id) if img is not None else None
    if outline_bed is not None:
        xs, ys = [p[0] for p in outline_bed], [p[1] for p in outline_bed]
        area = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    elif img is not None:
        area = img.bounds()
    else:
        w, h = min(200.0, win.profile.bed_x * 0.8), min(150.0, win.profile.bed_y * 0.8)
        vp = win.canvas.viewport().rect().center()
        c = win.canvas.to_bed(QPointF(vp))
        if not (0 <= c.x() <= win.profile.bed_x and 0 <= c.y() <= win.profile.bed_y):
            c = QPointF(win.profile.bed_x / 2, win.profile.bed_y / 2)
        area = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
    local = None
    if outline_bed is not None:  # coordinate del puzzle: dall'angolo in alto a sinistra, Y in giù
        local = [(x - area.left(), area.bottom() - y) for x, y in outline_bed]
    dlg = PuzzleDialog(win, photo, (area.width(), area.height()), local)
    if dlg.exec() != QDialog.Accepted or dlg.puzzle is None:
        return None
    pz, val = dlg.puzzle, dlg.values()
    if val["kind"] != "selected":  # misure scelte nella finestra: stesso centro della zona di partenza
        c = area.center()
        area = QRectF(c.x() - pz.width / 2, c.y() - pz.height / 2, pz.width, pz.height)
    x0, y0 = area.left(), area.top()  # Y in su: top() è il lato in basso
    photo = val["photo"]
    same_photo = img is not None and photo is not None and photo is doc.images.get(img.image_id)
    free = win._free_layers(2)
    cut_layer = free[0] if free else None
    img_layer = -1
    if photo is not None:
        img_layer = img.layer if same_photo else (free[1] if len(free) > 1 else None)
    if cut_layer is None or img_layer is None:
        QMessageBox.warning(win, tr("Puzzle da foto"), tr("Servono due livelli liberi: liberane qualcuno e riprova."))
        return None
    shapes = []
    win.editor.begin(tr("Puzzle da foto"))
    try:
        # livelli liberi presi da zero, con le impostazioni di partenza: niente nomi, priorità o «non incidere»
        # rimasti da un uso precedente
        fresh = [cut_layer] + ([img_layer] if photo is not None and not same_photo else [])
        for i in fresh:
            doc.layers[i] = default_layer(i)
        if photo is not None:
            nid = uuid.uuid4().hex[:12]
            doc.images[nid] = fit_photo(photo, pz.width, pz.height, None if val["kind"] == "rect" else pz.outline)
            s = ImageShape(nid, pz.width, pz.height, layer=img_layer)
            if same_photo:
                s.brightness, s.contrast, s.gamma = img.brightness, img.contrast, img.gamma
            s.set_transform(QTransform.fromTranslate(x0, y0))
            shapes.append(s)
            doc.layer(img_layer).mode = "image"
        cut = PathShape(cuts_path(pz, x0, y0), cut_layer)
        shapes.append(cut)
        cs_cut = doc.layer(cut_layer)
        cs_cut.mode = "line"
        cs_cut.name = tr("Puzzle: taglio")
        # il taglio per ultimo: prima si incide la foto, poi si staccano i pezzi
        others = [c.priority for c in doc.used_layers() if c.index != cut_layer]
        if photo is not None:
            others.append(doc.layer(img_layer).priority)
        cs_cut.priority = max(others + [0]) + 1
        group = GroupShape(shapes, layer=shapes[0].layer)
        # diventano il puzzle (e spariscono) solo la foto usata e la forma usata come contorno: il resto resta com'è
        used = [u for u in used if (isinstance(u, ImageShape) and same_photo and u is img)
                or (not isinstance(u, ImageShape) and val["kind"] == "selected")]
        if used:
            win.editor.replace(used, [group], tr("Puzzle da foto"))
        else:
            win.editor.add([group], tr("Puzzle da foto"))
        win.editor.commit()
    except Exception:
        win.editor.cancel()  # niente a metà: il documento torna com'era
        raise
    win.statusBar().showMessage(tr("Puzzle da {0} pezzi creato. Prima di avviare imposta velocità, potenza e passate "
                                   "del livello {1} per tagliare il tuo legno.", len(pz.pieces),
                                   cs_cut.label()), 12000)
    return group
