# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Disponi → Ottimizza lo spazio: i pezzi si sistemano sul materiale sprecandone il meno possibile."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import geom, nesting
from ..core.document import ImageShape
from ..theme import C
from .editor import TOOL_LAYER
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, suffix=" mm", dec=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, e):
        self.clicked.emit()


def _wrapped(cb):
    """Una spunta con il testo che va a capo (QCheckBox da solo non lo fa): serve nella finestra stretta del nesting
    manuale. Il testo passa a un'etichetta di fianco, cliccabile come quello di una spunta."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    lab = _ClickLabel(cb.text())
    lab.setWordWrap(True)
    lab.setToolTip(cb.toolTip())
    lab.clicked.connect(lambda: cb.toggle() if cb.isEnabled() else None)
    cb.setAccessibleName(cb.text())
    cb.setText("")
    h.addWidget(cb, 0, Qt.AlignTop)
    h.addWidget(lab, 1)
    cb.wrapped_label = lab
    return row


def _primary(button, on):
    button.setObjectName("primary" if on else "")
    button.style().unpolish(button)
    button.style().polish(button)


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
    changed = Signal()  # nesting manuale: è cambiato qualcosa che la finestra che mi ospita deve sapere (altezza, esito)

    def __init__(self, main, manual=None, host=None):
        """manual: la forma dell'area disegnata con il nesting manuale (0.18.16). Con quella i pezzi vanno lì dentro
        tutti oppure nessuno: se non entrano non si sposta niente e si chiede una nuova area. I pezzi (0.18.17) sono
        solo quelli selezionati prima di disegnare l'area: alla chiusura dell'area sono loro la selezione.
        host (0.19.0): la finestra del nesting manuale; allora questa non è una finestra a sé ma il suo passo 2, con
        in vista solo distanza e rotazioni e il resto dietro «Altre opzioni»."""
        super().__init__(host if host is not None else main)
        man = manual is not None
        if host is not None:
            self.setWindowFlags(Qt.Widget)
        self.manual = manual
        self.again = False  # nesting manuale: l'area non va bene e si vuole disegnarne un'altra
        self.placed = False  # nesting manuale: i pezzi sono stati sistemati almeno una volta
        self.no_fit = None  # nesting manuale: (pezzi rimasti fuori, pezzi in tutto) dell'ultimo tentativo andato male
        self.last, self.results = None, []
        self._ended = False
        # il passo «area aggiunta» nella cronologia: alla fine tutto il comando diventa un solo Ctrl+Z
        stack = main.editor.undo_stack
        self._hist0 = stack[-1] if manual is not None and stack else None
        self.main = main
        self.ed = main.editor
        qs = main.qs
        self.setWindowTitle(tr("Ottimizza lo spazio"))
        v = QVBoxLayout(self)
        if host is not None:
            v.setContentsMargins(0, 0, 0, 0)
        else:
            self.setMinimumWidth(520)
        intro = QLabel(tr("Sistema i pezzi sul materiale sprecandone il meno possibile: usa la sagoma vera di ogni pezzo "
                          "(non il rettangolo che lo contiene), li ruota se lo permetti e li compatta verso l'origine. "
                          "Si annulla con Ctrl+Z."))
        intro.setWordWrap(True)
        intro.setVisible(not man)  # nel nesting manuale le scritte sono ridotte all'osso
        v.addWidget(intro)
        self.sheet = manual if manual is not None else sheet_shape(self.ed)
        self.parts = pieces(self.ed, self.sheet)
        self.what = QLabel()
        self.what.setWordWrap(True)
        self.what.setObjectName("muted")
        v.addWidget(self.what)
        f = QFormLayout()
        # nesting manuale (0.19.0): le opzioni che si toccano di rado stanno dietro «Altre opzioni» (self.more); quelle
        # che lì non hanno senso (il materiale è l'area disegnata, niente altri pannelli) in un riquadro mai mostrato
        self.more = QWidget(self)
        mv = QVBoxLayout(self.more)
        mv.setContentsMargins(0, 0, 0, 0)
        f2 = QFormLayout()
        mv.addLayout(f2)
        self.more.hide()
        self.unused = QWidget(self)
        fu = QFormLayout(self.unused)
        self.unused.hide()
        f_area, f_rare, box = (fu, f2, mv) if man else (f, f, v)
        self.area = QComboBox()
        self.area.addItem(tr("Piano di lavoro intero"), "bed")
        if self.sheet is not None:
            self.area.addItem(tr("Forma selezionata sul livello T1 (il materiale)"), "sheet")
        self.area.addItem(tr("Rettangolo su misura"), "custom")
        self.area.setToolTip(tr("Disegna il contorno del pannello (anche un avanzo irregolare) sul livello T1, selezionalo "
                                "insieme ai pezzi e i pezzi andranno lì dentro"))
        f_area.addRow(tr("Materiale"), self.area)
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        p = main.profile
        self.cx, self.cy = _spin(-5000, 5000, 0.0), _spin(-5000, 5000, 0.0)
        self.cw, self.ch = _spin(1, 5000, min(300.0, p.bed_x)), _spin(1, 5000, min(200.0, p.bed_y))
        for lab, w in (("X", self.cx), ("Y", self.cy), (tr("L"), self.cw), (tr("A"), self.ch)):
            cl.addWidget(QLabel(lab))
            cl.addWidget(w)
        f_area.addRow("", self.custom)
        self.gap = _spin(0, 50, float(qs.value("nest_gap", 2.0)))
        self.gap.setToolTip(tr("Spazio libero tra un pezzo e l'altro: almeno lo spessore del taglio più un po' di sicurezza"))
        f.addRow(tr("Distanza tra i pezzi"), self.gap)
        self.margin = _spin(0, 50, float(qs.value("nest_margin", 1.0)))
        self.margin.setToolTip(tr("Spazio lasciato libero lungo il bordo del materiale"))
        f_rare.addRow(tr("Margine dal bordo"), self.margin)
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
        f_rare.addRow(tr("Precisione"), self.prec)
        v.addLayout(f)
        self.keep = QCheckBox(tr("Tieni insieme le forme che stanno una dentro l'altra"))
        self.keep.setChecked(qs.value("nest_keep", "true") in (True, "true"))
        self.keep.setToolTip(tr("Così un'incisione resta dentro il suo contorno di taglio anche se non sono raggruppati"))
        box.addWidget(_wrapped(self.keep) if man else self.keep)
        self.holes = QCheckBox(tr("Usa anche i fori interni dei pezzi (solo se sono tagliati da parte a parte)"))
        self.holes.setChecked(False)
        box.addWidget(_wrapped(self.holes) if man else self.holes)
        self.multi = QCheckBox(tr("Se non entrano, continua su altri pannelli uguali (affiancati a destra)"))
        self.multi.setChecked(qs.value("nest_multi", "false") in (True, "true"))
        self.multi.setToolTip(tr("Ogni pannello in più ha il suo contorno sul livello T1 e il suo numero: incidi un "
                                 "pannello alla volta selezionandolo, con «Solo gli oggetti selezionati»"))
        if man:
            fu.addRow(self.multi)
        else:
            v.addWidget(self.multi)
        self.keep_area = QCheckBox(tr("Lascia sul piano l'area disegnata, come riferimento per i prossimi nesting"))
        self.keep_area.setChecked(manual is not None and qs.value("nest_keep_area", "false") in (True, "true"))
        self.keep_area.setToolTip(tr("Di regola, finito il nesting, il contorno dell'area sparisce. Con la spunta resta "
                                     "sul livello T1 (mai inciso): per riusarlo selezionalo insieme ai pezzi e scegli "
                                     "il nesting automatico."))
        self.keep_area.setVisible(man)
        box.addWidget(_wrapped(self.keep_area) if man else self.keep_area)
        self.common = QCheckBox(tr("Linee di taglio comuni: i pezzi si toccano e i lati in comune si tagliano una volta sola"))
        # 0.18.3: parte sempre spenta e non si ricorda più: unisce i contorni in un tracciato unico, e chi l'aveva
        # spuntata una volta se la ritrovava attiva a ogni nesting («non riesco più a modificare i pezzi»)
        self.common.setChecked(False)
        self.common.setToolTip(tr("Meno tempo e meno materiale. Funziona con i lati dritti (rettangoli, poligoni). "
                                  "I contorni di taglio diventano un unico tracciato per livello; il kerf non si applica "
                                  "ai lati condivisi."))
        self.common.toggled.connect(lambda on: self.gap.setEnabled(not on))
        self.gap.setEnabled(not self.common.isChecked())
        box.addWidget(_wrapped(self.common) if man else self.common)
        self.more_link = _ClickLabel()
        self.more_link.setCursor(Qt.PointingHandCursor)
        self.more_link.clicked.connect(lambda: self.toggle_more())
        self.more_link.setVisible(man)
        v.addWidget(self.more_link)
        if man:
            v.addWidget(self.more)
            self.toggle_more(False)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        v.addWidget(self.result)
        # nesting manuale: «l'area non basta» si risolve qui, senza un'altra finestra
        self.nofit = QWidget(self)
        hn = QHBoxLayout(self.nofit)
        hn.setContentsMargins(0, 0, 0, 0)
        self.b_redraw = QPushButton(tr("Ridisegna l'area"))
        self.b_redraw.clicked.connect(lambda: self.redraw())
        self.b_options = QPushButton(tr("Cambia le opzioni"))
        self.b_options.clicked.connect(lambda: self.change_options())
        hn.addWidget(self.b_redraw)
        hn.addWidget(self.b_options)
        self.nofit.hide()
        if man:
            v.addWidget(self.nofit)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.b_close = QPushButton(tr("Annulla") if man else tr("Chiudi"))
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
        if self.manual is not None:  # l'area è quella disegnata: non si cambia e non si continua su altri pannelli
            self.setWindowTitle(tr("Ottimizza lo spazio: nesting manuale"))
            self.area.setItemText(self.area.findData("sheet"), tr("L'area che hai disegnato"))
            self.area.setEnabled(False)
            self.multi.setChecked(False)
            self.multi.hide()
        self._area_changed()
        self._describe()

    def _describe(self):
        n = len(self.parts)
        if not n:
            self.what.setText(tr("Non ci sono pezzi da disporre (le forme bloccate, nascoste o sul livello T1 restano ferme)."))
            self.b_run.setEnabled(False)
        elif self.manual is not None:
            self.what.setText(tr("Pezzi da sistemare: {0}, quelli che avevi selezionato. Il resto non si tocca.", n))
        elif self.ed.selection:
            self.what.setText(tr("Pezzi: le {0} forme selezionate. Le altre forme sul piano restano ferme e vengono evitate.", n))
        else:
            self.what.setText(tr("Pezzi: tutte le {0} forme del progetto (nessuna selezione). Le forme bloccate restano ferme "
                                 "e vengono evitate.", n))

    def _area_changed(self, *_):
        self.custom.setVisible(self.area.currentData() == "custom")

    # ------------------------------------------------------------------ nesting manuale: la finestra stretta (0.19.0)
    def toggle_more(self, on=None):
        """«Altre opzioni»: margine, precisione e le spunte che si toccano di rado."""
        on = self.more.isHidden() if on is None else bool(on)
        self.more.setVisible(on)
        text = tr("Nascondi le altre opzioni") if on else tr("Altre opzioni")
        self.more_link.setText(f"<a href='#' style='color:{C['accent_hi']}'>{text}</a>")
        self.changed.emit()

    def change_options(self):
        """«Cambia le opzioni» dopo «l'area non basta»: si riprova con meno distanza o più rotazioni."""
        self.nofit.hide()
        self.toggle_more(True)
        self.gap.setFocus()

    def redraw(self):
        """«Ridisegna l'area»: quella di adesso sparisce e si torna a disegnare, con gli stessi pezzi."""
        doc = self.ed.doc
        self.again = True
        if self.manual in doc.shapes:
            self.ed.run(tr("Togli l'area del nesting"), lambda: doc.remove([self.manual]))
        self.ed.select([s for s in self.parts if s in doc.shapes])
        self.reject()

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
        if self.manual is not None:
            # 0.18.17: nel nesting manuale contano solo i pezzi selezionati e l'area tracciata. Una forma che sta
            # sotto l'area o a cavallo del tracciato (una foto di riferimento, un altro disegno) non è un ostacolo
            obstacles = []
            qs.setValue("nest_keep_area", self.keep_area.isChecked())
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
        if self.manual is not None and left:
            # nesting manuale: tutti dentro l'area oppure niente. Non sposto nessun pezzo e chiedo che cosa fare
            self.result.setText(tr("<span style='color:#E5484D'>Nell'area disegnata non entrano tutti i pezzi: ne "
                                   "restano fuori {0} su {1}. Non ho spostato niente.</span>", len(left), len(self.parts)))
            self.results, self.last = [], None
            self.no_fit = (len(left), len(self.parts))
            self.nofit.show()  # 0.19.0: si sceglie qui che cosa fare, la finestra resta aperta
            self.changed.emit()
            return None
        self.no_fit = None
        self.nofit.hide()
        info = {"saved": 0.0}
        if placed_groups:
            self.ed.run(tr("Ottimizza lo spazio"), self._apply, results, shifts, area, obstacles, common, info)
        for s in self.ed.doc.shapes:
            if hasattr(s, "_nest_new"):
                del s._nest_new
        # 0.18.3: a fine nesting restano selezionati solo i pezzi che non sono entrati. Prima venivano selezionati
        # tutti i pezzi sistemati: un unico riquadro che sembrava un oggetto solo
        self.ed.select(left)
        if self.manual is not None:  # 0.18.17: nesting fatto, il contorno dell'area ha finito il suo compito
            self._area_sync()
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
        if self.manual is not None:
            if placed_groups and not self.placed:  # fatto: ora si chiude con «Fatto», oppure si riprova
                self.placed = True
                self.b_close.setText(tr("Fatto"))
                self.b_run.setText(tr("Disponi di nuovo"))
                _primary(self.b_run, False)
                _primary(self.b_close, True)
            self.changed.emit()
        return self.last

    # ------------------------------------------------------------------ nesting manuale: fine del comando (0.18.17)
    def _area_sync(self):
        """L'area disegnata resta sul piano (livello T1) solo con la spunta; altrimenti sparisce."""
        doc, area = self.ed.doc, self.manual
        keep = self.keep_area.isChecked()
        if not keep and area in doc.shapes:
            if area in self.ed.selection:
                self.ed.select([s for s in self.ed.selection if s is not area])
            self.ed.run(tr("Togli l'area del nesting"), lambda: doc.remove([area]))
        elif keep and area not in doc.shapes and not self.again:
            self.ed.run(tr("Area del nesting"), lambda: doc.add(area))

    def end_manual(self):
        """Il comando «nesting manuale» ha finito il suo ciclo (finestra chiusa, in qualsiasi modo): il contorno
        dell'area sparisce (salvo la spunta), e tutto il comando diventa un solo passo di Ctrl+Z."""
        if self.manual is None or self._ended:
            return
        self._ended = True
        from . import nest_manual

        self.main.qs.setValue("nest_keep_area", self.keep_area.isChecked())
        if not self.again:
            self._area_sync()  # tolta l'area, restano selezionati i pezzi: la selezione di prima del comando
        if self._hist0 is not None:
            # annullando si torna a prima del comando, con selezionati i pezzi che lo erano allora
            nest_manual.collapse_history(self.ed, self._hist0, tr("Nesting manuale"), [s.id for s in self.parts])

    def done(self, r):
        self.end_manual()
        super().done(r)

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
