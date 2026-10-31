# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Libreria materiali e test materiale.

La libreria parte dalla tabella ufficiale Longer per il B1 40W; le voci proprie
(salvate dai livelli o dal risultato di un test) hanno la precedenza e si possono
modificare o eliminare. Il test incide una griglia potenza × velocità e alla fine
si sceglie il quadrato migliore: diventa una voce della libreria in un clic.
"""
from dataclasses import replace

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import material_test as mtest, materials as mats
from ..theme import C
from . import style
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402


def _dspin(lo, hi, val, dec=1, step=1.0, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setSuffix(suffix)
    return w


def _ispin(lo, hi, val, suffix=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(val)
    w.setSuffix(suffix)
    return w


# ===================================================================== libreria
class MaterialLibraryDialog(QDialog):
    """Sfoglia, cerca, applica e salva i materiali. `layer` è il CutSettings corrente (o None)."""

    apply_requested = Signal(object)  # Material
    test_requested = Signal(object)  # Material

    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Libreria materiali"))
        self.resize(860, 560)
        self.layer = layer
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Cerca: tiglio, acrilico 3, pelle…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.op = QComboBox()
        for k, lab in (("", tr("Tutte le operazioni")), ("incisione", tr("Incisione")), ("taglio", tr("Taglio"))):
            self.op.addItem(lab, k)
        self.op.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        top.addWidget(self.op)
        v.addLayout(top)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Materiale"), tr("Potenza"), tr("Velocità"), "×"])
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, hh.ResizeMode.Stretch)
        for i in (1, 2, 3):
            hh.setSectionResizeMode(i, hh.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self._show())
        self.tree.itemDoubleClicked.connect(lambda it, c: self._apply())
        split.addWidget(self.tree)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 0, 0, 0)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        self.title.setWordWrap(True)
        rv.addWidget(self.title)
        self.src = QLabel("")
        self.src.setObjectName("muted")
        rv.addWidget(self.src)
        f = QFormLayout()
        self.e_name = QLineEdit()
        self.e_op = QComboBox()
        self.e_op.addItems(["incisione", "taglio"])
        self.e_th = _dspin(0, 100, 0, 2, 0.5, " mm")
        self.e_th.setSpecialValueText("superficie")
        self.e_mode = QComboBox()
        for k, lab in (("fill", tr("Riempimento")), ("line", tr("Linea")), ("image", tr("Immagine"))):
            self.e_mode.addItem(lab, k)
        self.e_power = _dspin(0, 100, 30, 1, 1, " %")
        self.e_speed = _dspin(1, 36000, 1000, 0, 100, " mm/min")
        self.e_passes = _ispin(1, 100, 1)
        self.e_interval = _dspin(0.01, 2, 0.1, 3, 0.01, " mm")
        self.e_defocus = _dspin(0, 30, 0, 1, 0.5, " mm")
        self.e_defocus.setToolTip(tr("Quanto abbassare il fuoco sotto la superficie (lo si fa a mano: la lente è fissa)"))
        self.e_note = QLineEdit()
        for lab, w in ((tr("Nome"), self.e_name), (tr("Operazione"), self.e_op), (tr("Spessore"), self.e_th), (tr("Modalità"), self.e_mode),
                       (tr("Potenza"), self.e_power), (tr("Velocità"), self.e_speed), (tr("Passate"), self.e_passes),
                       (tr("Interlinea"), self.e_interval), (tr("Sfocatura"), self.e_defocus), (tr("Note"), self.e_note)):
            f.addRow(lab, w)
        rv.addLayout(f)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {C['muted']};")
        rv.addWidget(self.hint)
        rv.addStretch(1)
        b1 = QHBoxLayout()
        self.b_apply = QPushButton(style.icon("check"), tr("Applica al livello"))
        self.b_apply.setObjectName("primary")
        self.b_apply.clicked.connect(self._apply)
        self.b_test = QPushButton(style.icon("grid"), tr("Test intorno a questi valori…"))
        self.b_test.clicked.connect(self._test)
        b1.addWidget(self.b_apply)
        b1.addWidget(self.b_test)
        rv.addLayout(b1)
        b2 = QHBoxLayout()
        self.b_save = QPushButton(style.icon("save"), tr("Salva come voce mia"))
        self.b_save.setToolTip(tr("Salva i valori a destra nella tua libreria (sostituisce la voce con lo stesso nome, "
                               "operazione e spessore)"))
        self.b_save.clicked.connect(self._save)
        self.b_from_layer = QPushButton(style.icon("layers"), tr("Dal livello"))
        self.b_from_layer.setToolTip(tr("Riempie i campi con le impostazioni del livello corrente"))
        self.b_from_layer.clicked.connect(self._from_layer)
        self.b_from_layer.setEnabled(layer is not None)
        self.b_del = QPushButton(style.icon("delete"), tr("Elimina"))
        self.b_del.clicked.connect(self._delete)
        b2.addWidget(self.b_save)
        b2.addWidget(self.b_from_layer)
        b2.addWidget(self.b_del)
        rv.addLayout(b2)
        split.addWidget(right)
        split.setSizes([480, 380])
        v.addWidget(split, 1)
        bottom = QHBoxLayout()
        lab = QLabel(tr("Valori Longer per il B1 40W: sono un punto di partenza. Lotti e legni diversi cambiano: "
                     "un test materiale su uno scarto ti dà i valori giusti per il tuo pezzo."))
        lab.setWordWrap(True)
        lab.setObjectName("muted")
        bottom.addWidget(lab, 1)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        v.addLayout(bottom)
        if layer is None:
            self.b_apply.setEnabled(False)
            self.b_apply.setToolTip(tr("Seleziona prima un livello nel pannello Livelli"))
        else:
            self.b_apply.setText(tr("Applica a «{0}»", layer.label()))
        self.refresh()

    # ---------------------------------------------------------------- elenco
    def refresh(self):
        q = self.search.text().strip().lower().split()
        op = self.op.currentData()
        cur = self._current()
        self.tree.clear()
        user_keys = {m.key() for m in mats.load_user()}
        groups = {}
        mono = style.mono_font(9)
        for m in mats.library():
            hay = f"{m.name} {m.operation} {m.thickness:g} {m.note}".lower()
            if op and m.operation != op or any(t not in hay for t in q):
                continue
            g = groups.get(m.name)
            if g is None:
                g = groups[m.name] = QTreeWidgetItem([m.name])
                g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
                f = g.font(0)
                f.setWeight(f.Weight.DemiBold)
                g.setFont(0, f)
                self.tree.addTopLevelItem(g)
            it = QTreeWidgetItem([("★ " if m.key() in user_keys else "") + m.label(), f"{m.power:g}%", f"{m.speed:g}",
                                  f"{m.passes}"])
            for c in (1, 2, 3):
                it.setFont(c, mono)
            it.setData(0, Qt.UserRole, m)
            it.setToolTip(0, m.note or m.summary())
            g.addChild(it)
            if cur is not None and m.key() == cur.key():
                self.tree.setCurrentItem(it)
        self.tree.expandAll() if q or len(groups) < 8 else None
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            g = self.tree.topLevelItem(0)
            g.setExpanded(True)
            if g.childCount():
                self.tree.setCurrentItem(g.child(0))
        self._show()

    def _current(self):
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        return it.data(0, Qt.UserRole) if it is not None else None

    def _show(self):
        m = self._current()
        on = m is not None
        for w in (self.b_apply, self.b_test, self.b_save, self.b_del):
            w.setEnabled(on and (w is not self.b_apply or self.layer is not None))
        if not on:
            self.title.setText("")
            return
        user = m.key() in {u.key() for u in mats.load_user()}
        self.b_del.setEnabled(user)
        self.title.setText(f"{m.name} — {m.label()}")
        self.src.setText(tr("Voce tua") if user else tr("Tabella {0}", m.source))
        self.e_name.setText(m.name)
        self.e_op.setCurrentText(m.operation)
        self.e_th.setValue(m.thickness)
        self.e_mode.setCurrentIndex(max(0, self.e_mode.findData(m.mode)))
        self.e_power.setValue(m.power)
        self.e_speed.setValue(m.speed)
        self.e_passes.setValue(m.passes)
        self.e_interval.setValue(m.interval)
        self.e_defocus.setValue(m.defocus)
        self.e_note.setText(m.note)
        hints = []
        if m.defocus:
            hints.append(tr("Sfocatura {0:g} mm: abbassa il fuoco di {1:g} mm sotto la superficie (il raggio resta stretto anche a metà spessore).", m.defocus, m.defocus))
        if m.passes > 3:
            hints.append(tr("Tante passate: controlla che il materiale non si incendi e che l'aria sia accesa."))
        if m.operation == "taglio":
            hints.append(tr("Per i tagli FreeLaserCut accende sempre l'aria. Usa \"Tagli per ultimi\" se c'è anche un'incisione."))
        self.hint.setText("\n".join(hints))

    def edited(self):
        m = self._current() or mats.Material(tr("Nuovo materiale"), "incisione")
        return replace(m, name=self.e_name.text().strip() or m.name, operation=self.e_op.currentText(),
                       thickness=self.e_th.value(), mode=self.e_mode.currentData(), power=self.e_power.value(),
                       speed=self.e_speed.value(), passes=self.e_passes.value(), interval=self.e_interval.value(),
                       defocus=self.e_defocus.value(), note=self.e_note.text().strip(), source="Personale")

    # ---------------------------------------------------------------- azioni
    def _apply(self):
        if self.layer is None or self._current() is None:
            return
        self.apply_requested.emit(self.edited())
        self.accept()

    def _test(self):
        if self._current() is not None:
            self.test_requested.emit(self.edited())
            self.accept()

    def _save(self):
        m = self.edited()
        user = [u for u in mats.load_user() if u.key() != m.key()]
        user.insert(0, m)
        mats.save_user(user)
        self.search.clear()
        self.refresh()
        self._select(m)

    def _select(self, m):
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                if g.child(j).data(0, Qt.UserRole).key() == m.key():
                    g.setExpanded(True)
                    self.tree.setCurrentItem(g.child(j))
                    return

    def _from_layer(self):
        cs = self.layer
        if cs is None:
            return
        self.e_mode.setCurrentIndex(max(0, self.e_mode.findData(cs.mode if cs.mode != "offset_fill" else "fill")))
        self.e_op.setCurrentText("taglio" if cs.mode == "line" and cs.power_max >= 80 else "incisione")
        self.e_power.setValue(cs.power_max)
        self.e_speed.setValue(cs.speed)
        self.e_passes.setValue(cs.passes)
        self.e_interval.setValue(cs.interval)
        if cs.name:
            self.e_name.setText(cs.name.split(" · ")[0])

    def _delete(self):
        m = self._current()
        if m is None:
            return
        user = [u for u in mats.load_user() if u.key() != m.key()]
        mats.save_user(user)
        self.refresh()


# ===================================================================== test materiale
class _GridPreview(QWidget):
    """Schema della griglia: celle sfumate per energia, ordine di incisione numerato."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 260)
        self.spec = mtest.TestSpec()
        self.pick = None  # (riga, colonna) scelta come migliore

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C["bg"]))
        s = self.spec
        rows, cols = max(1, s.rows), max(1, s.cols)
        lab = 42
        W, H = self.width() - lab - 12, self.height() - 34 - 12
        cell = min(W / cols, H / rows)
        gap = cell * 0.18
        x0, y0 = lab, 12
        powers = mtest._steps(s.p_min, s.p_max, rows)
        speeds = mtest._steps(s.s_min, s.s_max, cols)
        emax = max(powers) / max(min(speeds), 1)
        order = sorted(((powers[r] / max(speeds[c], 1), r, c) for r in range(rows) for c in range(cols)))
        num = {(r, c): i + 1 for i, (_, r, c) in enumerate(order)}
        p.setFont(style.mono_font(7.5))
        for r in range(rows):
            for c in range(cols):
                en = powers[r] / max(speeds[c], 1) / max(emax, 1e-9)
                d = 1 - pow(2.718, -3.2 * en)
                col = QColor.fromRgbF(0.86 - 0.62 * d, 0.70 - 0.55 * d, 0.50 - 0.42 * d)
                rect = QRectF(x0 + c * cell + gap / 2, y0 + (rows - 1 - r) * cell + gap / 2, cell - gap, cell - gap)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(rect, 3, 3)
                if self.pick == (r, c):
                    p.setPen(QPen(QColor(C["accent_hi"]), 2.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 5, 5)
                if cell > 26:
                    p.setPen(QColor(255, 255, 255, 150) if d > 0.45 else QColor(0, 0, 0, 120))
                    p.drawText(rect, Qt.AlignCenter, str(num[(r, c)]))
        p.setPen(QColor(C["muted"]))
        for r in range(rows):
            p.drawText(QRectF(0, y0 + (rows - 1 - r) * cell, lab - 6, cell), Qt.AlignRight | Qt.AlignVCenter, f"{powers[r]:g}%")
        for c in range(cols):
            p.drawText(QRectF(x0 + c * cell - 6, y0 + rows * cell + 2, cell + 12, 16), Qt.AlignCenter, f"{speeds[c]:g}")
        p.drawText(QRectF(x0, y0 + rows * cell + 16, cols * cell, 16), Qt.AlignRight, tr("mm/min"))
        p.end()


class MaterialTestDialog(QDialog):
    """Imposta la griglia. Il dialogo resta aperto: Anteprima / Contorno / Avvia passano dalla finestra principale."""

    action = Signal(str, object)  # ("preview"|"frame"|"start"|"save", GcodeJob)

    def __init__(self, profile, head_bed=None, seed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Test materiale"))
        self.profile = profile
        self.head_bed = head_bed
        self.job = None
        h = QHBoxLayout(self)
        left = QVBoxLayout()
        h.addLayout(left, 0)
        f = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("Es. Tiglio 3 mm"))
        self.mode = QComboBox()
        self.mode.addItem(tr("Riempimento (incisione)"), "fill")
        self.mode.addItem(tr("Linea (taglio / contorno)"), "line")
        self.p_min, self.p_max = _dspin(0.5, 100, 10, 1, 5, " %"), _dspin(0.5, 100, 100, 1, 5, " %")
        self.rows = _ispin(1, 10, 5)
        self.s_min, self.s_max = _dspin(10, 36000, 1000, 0, 250, " mm/min"), _dspin(10, 36000, 10000, 0, 250, " mm/min")
        self.cols = _ispin(1, 10, 5)
        self.cell = _dspin(3, 40, 10, 1, 1, " mm")
        self.gap = _dspin(0.5, 20, 3, 1, 0.5, " mm")
        self.interval = _dspin(0.02, 1, 0.1, 3, 0.01, " mm")
        self.passes = _ispin(1, 50, 1)
        self.x0 = _dspin(0, 2000, 20, 1, 5, " mm")
        self.y0 = _dspin(0, 2000, 20, 1, 5, " mm")
        self.labels = QCheckBox(tr("Etichette (potenza e velocità)"))
        self.labels.setChecked(True)
        self.border = QCheckBox(tr("Ritaglia il test con una cornice"))
        pr = QHBoxLayout()
        pr.addWidget(self.p_min)
        pr.addWidget(QLabel("→"))
        pr.addWidget(self.p_max)
        pr.addWidget(QLabel("in"))
        pr.addWidget(self.rows)
        sr = QHBoxLayout()
        sr.addWidget(self.s_min)
        sr.addWidget(QLabel("→"))
        sr.addWidget(self.s_max)
        sr.addWidget(QLabel("in"))
        sr.addWidget(self.cols)
        cr = QHBoxLayout()
        cr.addWidget(self.cell)
        cr.addWidget(QLabel("spazio"))
        cr.addWidget(self.gap)
        posr = QHBoxLayout()
        posr.addWidget(QLabel("X"))
        posr.addWidget(self.x0)
        posr.addWidget(QLabel("Y"))
        posr.addWidget(self.y0)
        self.b_head = QPushButton(style.icon("position"), "")
        self.b_head.setToolTip(tr("Metti il test dove si trova ora la testa"))
        self.b_head.setEnabled(head_bed is not None)
        self.b_head.clicked.connect(self._at_head)
        posr.addWidget(self.b_head)
        f.addRow(tr("Titolo"), self.title)
        f.addRow(tr("Tipo"), self.mode)
        f.addRow(tr("Potenza"), pr)
        f.addRow(tr("Velocità"), sr)
        f.addRow(tr("Quadrato"), cr)
        f.addRow(tr("Interlinea"), self.interval)
        f.addRow(tr("Passate"), self.passes)
        f.addRow(tr("Angolo in basso a sinistra"), posr)
        f.addRow("", self.labels)
        f.addRow("", self.border)
        left.addWidget(section(tr("Griglia")))
        left.addLayout(f)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        left.addStretch(1)
        btn = QGridLayout()
        self.b_prev = QPushButton(style.icon("preview"), tr("Anteprima"))
        self.b_frame = QPushButton(style.icon("frame"), tr("Contorno"))
        self.b_save = QPushButton(style.icon("gcode"), tr("Salva G-code"))
        self.b_start = QPushButton(style.icon("play"), tr("Avvia il test"))
        self.b_start.setObjectName("primary")
        for i, (b, k) in enumerate(((self.b_prev, "preview"), (self.b_frame, "frame"), (self.b_save, "save"),
                                    (self.b_start, "start"))):
            b.clicked.connect(lambda _=False, k=k: self._emit(k))
            btn.addWidget(b, i // 2, i % 2)
        left.addLayout(btn)
        right = QVBoxLayout()
        h.addLayout(right, 1)
        right.addWidget(section(tr("Schema · i numeri sono l'ordine di incisione, dal più leggero")))
        self.grid = _GridPreview()
        right.addWidget(self.grid, 1)
        right.addWidget(section(tr("Dopo il test: quale quadrato è venuto meglio?")))
        pick = QHBoxLayout()
        self.pick_r = QComboBox()
        self.pick_c = QComboBox()
        pick.addWidget(QLabel(tr("Potenza")))
        pick.addWidget(self.pick_r, 1)
        pick.addWidget(QLabel(tr("Velocità")))
        pick.addWidget(self.pick_c, 1)
        right.addLayout(pick)
        self.pick_r.currentIndexChanged.connect(self._pick_changed)
        self.pick_c.currentIndexChanged.connect(self._pick_changed)
        sv = QHBoxLayout()
        self.th = _dspin(0, 100, 0, 1, 0.5, " mm")
        self.th.setSpecialValueText("superficie")
        sv.addWidget(QLabel(tr("Spessore")))
        sv.addWidget(self.th)
        self.b_lib = QPushButton(style.icon("library"), tr("Salva in libreria"))
        self.b_lib.clicked.connect(self._save_material)
        sv.addWidget(self.b_lib, 1)
        right.addLayout(sv)
        for w in (self.p_min, self.p_max, self.s_min, self.s_max, self.cell, self.gap, self.interval, self.x0, self.y0):
            w.valueChanged.connect(self._changed)
        for w in (self.rows, self.cols, self.passes):
            w.valueChanged.connect(self._changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.labels.toggled.connect(self._changed)
        self.border.toggled.connect(self._changed)
        self.title.textChanged.connect(self._changed)
        if seed is not None:
            self.seed(seed)
        self._changed()

    def seed(self, m):
        """Griglia intorno ai valori di un materiale: potenza ±40%, velocità ±50%."""
        self.title.setText(tr("{0} {1:g} mm", m.name, m.thickness) if m.thickness else m.name)
        self.mode.setCurrentIndex(1 if m.mode == "line" else 0)
        self.p_min.setValue(max(1.0, round(m.power * 0.6)))
        self.p_max.setValue(min(100.0, round(m.power * 1.4)) if m.power < 100 else 100.0)
        if m.power >= 100:
            self.p_min.setValue(70)
        self.s_min.setValue(max(50.0, round(m.speed * 0.5, -1)))
        self.s_max.setValue(min(36000.0, round(m.speed * 1.5, -1)))
        self.passes.setValue(m.passes)
        self.th.setValue(m.thickness)
        if m.mode == "line":
            self.rows.setValue(3)
            self.cols.setValue(4)

    def _mode_changed(self):
        self.interval.setEnabled(self.mode.currentData() == "fill")
        self._changed()

    def _at_head(self):
        if self.head_bed is not None:
            self.x0.setValue(max(0.0, self.head_bed[0]))
            self.y0.setValue(max(0.0, self.head_bed[1]))

    def spec(self):
        return mtest.TestSpec(mode=self.mode.currentData(), p_min=self.p_min.value(), p_max=self.p_max.value(),
                              rows=self.rows.value(), s_min=self.s_min.value(), s_max=self.s_max.value(),
                              cols=self.cols.value(), cell=self.cell.value(), gap=self.gap.value(),
                              interval=self.interval.value(), passes=self.passes.value(), x0=self.x0.value(),
                              y0=self.y0.value(), labels=self.labels.isChecked(), border=self.border.isChecked(),
                              title=self.title.text().strip())

    def _changed(self, *_):
        s = self.spec()
        self.grid.spec = s
        self.job = None
        for cb, vals, fmt in ((self.pick_r, mtest._steps(s.p_min, s.p_max, s.rows), "{:g} %"),
                              (self.pick_c, mtest._steps(s.s_min, s.s_max, s.cols), "{:g} mm/min")):
            cur = cb.currentIndex()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("—", None)
            for i, v in enumerate(vals):
                cb.addItem(fmt.format(round(v, 1)), i)
            cb.setCurrentIndex(min(cur, cb.count() - 1) if cur > 0 else 0)
            cb.blockSignals(False)
        self._pick_changed()
        try:
            job = self.build()
        except Exception as ex:  # noqa: BLE001 — mostra l'errore invece di chiudere
            self.info.setText(tr("Errore: {0}", ex))
            return
        b = job.bounds
        txt = f"<b>{b.width():.0f} × {b.height():.0f} mm</b> · tempo stimato <b>{_mmss(job.seconds)}</b>"
        if job.warnings:
            txt += "<br><span style='color:%s'>⚠ %s</span>" % (C["warn"] if "warn" in C else "#F5A524", job.warnings[0])
        self.info.setText(txt)
        self.b_start.setEnabled(not job.warnings)

    def build(self):
        if self.job is None:
            self.job = mtest.build(self.spec(), self.profile)
        return self.job

    def _emit(self, kind):
        self.action.emit(kind, self.build())

    def _pick_changed(self, *_):
        r, c = self.pick_r.currentData(), self.pick_c.currentData()
        self.grid.pick = (r, c) if r is not None and c is not None else None
        self.b_lib.setEnabled(self.grid.pick is not None)
        self.grid.update()

    def _save_material(self):
        if self.grid.pick is None:
            return
        s = self.spec()
        r, c = self.grid.pick
        pw = round(mtest._steps(s.p_min, s.p_max, s.rows)[r], 1)
        sp = round(mtest._steps(s.s_min, s.s_max, s.cols)[c])
        name = s.title or tr("Materiale provato")
        th = self.th.value()
        if th and name.endswith(f" {th:g} mm"):
            name = name[: -len(f" {th:g} mm")]
        m = mats.Material(name, "taglio" if s.mode == "line" else "incisione", th, pw, sp, s.passes, 0.0,
                          s.mode, s.interval, tr("Dal test materiale"), tr("Personale"))
        user = [u for u in mats.load_user() if u.key() != m.key()]
        mats.save_user([m] + user)
        QMessageBox.information(self, tr("Libreria materiali"), tr("Salvato: {0} — {1}\n{2}", m.name, m.label(), m.summary()))


def _mmss(sec):
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"
