# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Disponi → Ottimizza lo spazio: i pezzi si sistemano sul materiale sprecandone il meno possibile."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import geom, nesting
from ..core.document import ImageShape
from .editor import TOOL_LAYER
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, suffix=" mm", dec=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


def sheet_shape(editor):
    """La forma chiusa selezionata sul livello T1 (il contorno del materiale), se c'è."""
    for s in editor.selection:
        if s.layer == TOOL_LAYER and not isinstance(s, ImageShape) and s.closed():
            return s
    return None


def pieces(editor, sheet=None):
    """Pezzi da disporre: la selezione (senza il materiale), altrimenti tutte le forme visibili e non bloccate."""
    src = editor.selection if editor.selection else editor.doc.shapes
    return [s for s in src if s is not sheet and not s.locked and not s.hidden and s.layer != TOOL_LAYER]


class NestDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.ed = main.editor
        qs = main.qs
        self.setWindowTitle(tr("Ottimizza lo spazio"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Sistema i pezzi sul materiale sprecandone il meno possibile: usa la sagoma vera di ogni pezzo "
                          "(non il rettangolo che lo contiene), li ruota se lo permetti e li compatta verso l'origine. "
                          "Si annulla con Ctrl+Z."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.sheet = sheet_shape(self.ed)
        self.parts = pieces(self.ed, self.sheet)
        self.what = QLabel()
        self.what.setWordWrap(True)
        self.what.setObjectName("muted")
        v.addWidget(self.what)
        f = QFormLayout()
        self.area = QComboBox()
        self.area.addItem(tr("Piano di lavoro intero"), "bed")
        if self.sheet is not None:
            self.area.addItem(tr("Forma selezionata sul livello T1 (il materiale)"), "sheet")
        self.area.addItem(tr("Rettangolo su misura"), "custom")
        self.area.setToolTip(tr("Disegna il contorno del pannello (anche un avanzo irregolare) sul livello T1, selezionalo "
                                "insieme ai pezzi e i pezzi andranno lì dentro"))
        f.addRow(tr("Materiale"), self.area)
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        p = main.profile
        self.cx, self.cy = _spin(-5000, 5000, 0.0), _spin(-5000, 5000, 0.0)
        self.cw, self.ch = _spin(1, 5000, min(300.0, p.bed_x)), _spin(1, 5000, min(200.0, p.bed_y))
        for lab, w in (("X", self.cx), ("Y", self.cy), (tr("L"), self.cw), (tr("A"), self.ch)):
            cl.addWidget(QLabel(lab))
            cl.addWidget(w)
        f.addRow("", self.custom)
        self.gap = _spin(0, 50, float(qs.value("nest_gap", 2.0)))
        self.gap.setToolTip(tr("Spazio libero tra un pezzo e l'altro: almeno lo spessore del taglio più un po' di sicurezza"))
        f.addRow(tr("Distanza tra i pezzi"), self.gap)
        self.margin = _spin(0, 50, float(qs.value("nest_margin", 1.0)))
        self.margin.setToolTip(tr("Spazio lasciato libero lungo il bordo del materiale"))
        f.addRow(tr("Margine dal bordo"), self.margin)
        self.rot = QComboBox()
        for code, label in (("none", tr("Nessuna (orientamento invariato)")), ("180", tr("Solo capovolti (180°)")),
                            ("90", tr("Di 90° in 90°")), ("45", tr("Di 45° in 45°")), ("15", tr("Di 15° in 15° (più lento)"))):
            self.rot.addItem(label, code)
        self.rot.setCurrentIndex(max(0, self.rot.findData(qs.value("nest_rot", "90"))))
        self.rot.setToolTip(tr("Con le venature del legno o le foto conviene «Nessuna» o «Solo capovolti»"))
        f.addRow(tr("Rotazioni"), self.rot)
        self.prec = QComboBox()
        self.prec.addItem(tr("Normale"), "normal")
        self.prec.addItem(tr("Alta (più lenta)"), "high")
        f.addRow(tr("Precisione"), self.prec)
        v.addLayout(f)
        self.keep = QCheckBox(tr("Tieni insieme le forme che stanno una dentro l'altra"))
        self.keep.setChecked(qs.value("nest_keep", "true") in (True, "true"))
        self.keep.setToolTip(tr("Così un'incisione resta dentro il suo contorno di taglio anche se non sono raggruppati"))
        v.addWidget(self.keep)
        self.holes = QCheckBox(tr("Usa anche i fori interni dei pezzi (solo se sono tagliati da parte a parte)"))
        self.holes.setChecked(False)
        v.addWidget(self.holes)
        self.multi = QCheckBox(tr("Se non entrano, continua su altri pannelli uguali (affiancati a destra)"))
        self.multi.setChecked(qs.value("nest_multi", "false") in (True, "true"))
        self.multi.setToolTip(tr("Ogni pannello in più ha il suo contorno sul livello T1 e il suo numero: incidi un "
                                 "pannello alla volta selezionandolo, con «Solo gli oggetti selezionati»"))
        v.addWidget(self.multi)
        self.common = QCheckBox(tr("Linee di taglio comuni: i pezzi si toccano e i lati in comune si tagliano una volta sola"))
        # 0.18.3: parte sempre spenta e non si ricorda più: unisce i contorni in un tracciato unico, e chi l'aveva
        # spuntata una volta se la ritrovava attiva a ogni nesting («non riesco più a modificare i pezzi»)
        self.common.setChecked(False)
        self.common.setToolTip(tr("Meno tempo e meno materiale. Funziona con i lati dritti (rettangoli, poligoni). "
                                  "I contorni di taglio diventano un unico tracciato per livello; il kerf non si applica "
                                  "ai lati condivisi."))
        self.common.toggled.connect(lambda on: self.gap.setEnabled(not on))
        self.gap.setEnabled(not self.common.isChecked())
        v.addWidget(self.common)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        v.addWidget(self.result)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.b_close = QPushButton(tr("Chiudi"))
        self.b_close.clicked.connect(self.accept)
        self.b_run = QPushButton(tr("Disponi"))
        self.b_run.setObjectName("primary")
        self.b_run.setDefault(True)
        self.b_run.clicked.connect(self.run)
        bb.addWidget(self.b_close)
        bb.addWidget(self.b_run)
        v.addLayout(bb)
        self.area.currentIndexChanged.connect(self._area_changed)
        if self.sheet is not None:
            self.area.setCurrentIndex(self.area.findData("sheet"))
        self._area_changed()
        self._describe()

    def _describe(self):
        n = len(self.parts)
        if not n:
            self.what.setText(tr("Non ci sono pezzi da disporre (le forme bloccate, nascoste o sul livello T1 restano ferme)."))
            self.b_run.setEnabled(False)
        elif self.ed.selection:
            self.what.setText(tr("Pezzi: le {0} forme selezionate. Le altre forme sul piano restano ferme e vengono evitate.", n))
        else:
            self.what.setText(tr("Pezzi: tutte le {0} forme del progetto (nessuna selezione). Le forme bloccate restano ferme "
                                 "e vengono evitate.", n))

    def _area_changed(self, *_):
        self.custom.setVisible(self.area.currentData() == "custom")

    def area_polys(self):
        mode = self.area.currentData()
        if mode == "sheet" and self.sheet is not None:
            return geom.flatten(self.sheet.path(), 0.1)
        if mode == "custom":
            x, y, w, h = self.cx.value(), self.cy.value(), self.cw.value(), self.ch.value()
        else:
            x, y, w, h = 0.0, 0.0, self.main.profile.bed_x, self.main.profile.bed_y
        return [geom.Poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]

    def run(self):
        qs = self.main.qs
        qs.setValue("nest_gap", self.gap.value())
        qs.setValue("nest_margin", self.margin.value())
        qs.setValue("nest_rot", self.rot.currentData())
        qs.setValue("nest_keep", self.keep.isChecked())
        qs.setValue("nest_multi", self.multi.isChecked())
        qs.remove("nest_common")  # preferenza delle versioni fino alla 0.18.2
        moving = set(self.parts)
        obstacles = [s for s in self.ed.doc.shapes if s not in moving and s is not self.sheet and not s.hidden
                     and s.layer != TOOL_LAYER]
        common = self.common.isChecked()
        kw = dict(keep_touching=self.keep.isChecked(), spacing=0.0 if common else self.gap.value(),
                  margin=self.margin.value(), rotations=self.rot.currentData(), fill_holes=not self.holes.isChecked(),
                  precision=self.prec.currentData(), tick=lambda: (QApplication.processEvents(), False)[1])
        area = self.area_polys()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self.result.setText(tr("Calcolo in corso…"))
        QApplication.processEvents()
        try:
            if self.multi.isChecked():
                results, shifts = nesting.nest_sheets(self.parts, area, obstacles, **kw)
            else:
                results, shifts = [nesting.nest_shapes(self.parts, area, obstacles, **kw)], [0.0]
        finally:
            QGuiApplication.restoreOverrideCursor()
        results = [r for r in results if r is not None]
        placed_groups = [g for r in results for g in r.placements]
        placed = {s for g in placed_groups for s in g}
        left = [s for s in self.parts if s not in placed]
        info = {"saved": 0.0}
        if placed_groups:
            self.ed.run(tr("Ottimizza lo spazio"), self._apply, results, shifts, area, obstacles, common, info)
        for s in self.ed.doc.shapes:
            if hasattr(s, "_nest_new"):
                del s._nest_new
        # 0.18.3: a fine nesting restano selezionati solo i pezzi che non sono entrati. Prima venivano selezionati
        # tutti i pezzi sistemati: un unico riquadro che sembrava un oggetto solo
        self.ed.select(left)
        used_w = max((r.used_w for r in results), default=0.0)
        used_h = max((r.used_h for r in results), default=0.0)
        area_parts = sum(r.parts_area for r in results)
        eff = area_parts / max(1e-9, sum(r.used_w * r.used_h for r in results)) if results else 0.0
        msg = tr("<b>Pezzi sistemati: {0}</b> · materiale usato {1:.0f} × {2:.0f} mm · utilizzo {3:.0f}%",
                 len(placed_groups), used_w, used_h, min(1.0, eff) * 100)
        if len(results) > 1:
            msg += "<br>" + tr("Pannelli usati: {0} (contorni e numeri sul livello T1)", len(results))
        if common:
            msg += "<br>" + tr("Taglio in comune: {0:.0f} mm in meno da percorrere", info["saved"])
            if info["saved"] > 0:
                msg += "<br>" + tr("I contorni di taglio ora sono un tracciato unico per livello: Ctrl+Z per riavere i "
                                   "pezzi separati.")
        if left:
            msg += "<br>" + tr("<span style='color:#E5484D'>Pezzi che non entrano: {0}. Restano dove erano e sono "
                               "selezionati.</span>", len(left))
        self.result.setText(msg)
        self.main.statusBar().showMessage(msg.replace("<b>", "").replace("</b>", "").split("<br>")[0], 8000)
        self.last = results[0] if results else None
        self.results = results
        return self.last

    def _apply(self, results, shifts, area, obstacles, common, info):
        from ..core.document import PathShape, RectShape, TextShape

        doc = self.ed.doc
        for res in results:
            nesting.apply(res)
        x0, y0, x1, y1 = nesting._bounds(area)
        if len(results) > 1:  # contorni e numeri dei pannelli sul livello strumenti (mai incisi)
            for k, dx in enumerate(shifts):
                if k:
                    if self.sheet is not None and self.area.currentData() == "sheet":
                        out = self.sheet.clone()
                        out.apply(QTransform.fromTranslate(dx, 0))
                    else:
                        out = RectShape(x1 - x0, y1 - y0, layer=TOOL_LAYER)
                        out.apply(QTransform.fromTranslate(x0 + dx, y0))
                    out.layer = TOOL_LAYER
                    out._nest_new = True
                    doc.add(out)
                lab = TextShape(tr("Pannello {0}", k + 1), "Arial", max(4.0, min(10.0, (x1 - x0) / 30)), layer=TOOL_LAYER)
                lab.apply(QTransform.fromTranslate(x0 + dx, y1 + 3))
                doc.add(lab)
        if not common:
            return
        line_layers = {cs.index for cs in doc.used_layers() if cs.mode == "line"}
        for res, dx in zip(results, shifts):
            groups = list(res.placements)
            parts = [[p for s in g for p in nesting.shape_polys(s, 0.05)] for g in groups]
            shrunk = geom.offset([geom.Poly([(x + dx, y) for x, y in p.pts], p.closed) for p in area if p.closed],
                                 -self.margin.value(), "miter") if self.margin.value() > 0 else \
                [geom.Poly([(x + dx, y) for x, y in p.pts], p.closed) for p in area]
            static = shrunk + ([p for s in obstacles for p in nesting.shape_polys(s, 0.1)] if dx == 0 else [])
            for g, (mx, my) in zip(groups, nesting.compact(parts, static)):
                if mx or my:
                    for s in g:
                        s.apply(QTransform.fromTranslate(mx, my))
            for layer in sorted(line_layers):
                cut = [s for g in groups for s in g if s.layer == layer and not isinstance(s, TextShape)]
                if len(cut) < 2:
                    continue
                polys = [p for s in cut for p in geom.flatten(s.path(), 0.01)]
                merged, saved = nesting.merge_common_lines(polys)
                if saved <= 0.01:
                    continue
                info["saved"] += saved
                doc.remove(cut)
                ps = PathShape(geom.polys_to_path(merged), layer=layer)
                ps._nest_new = True
                doc.add(ps)
