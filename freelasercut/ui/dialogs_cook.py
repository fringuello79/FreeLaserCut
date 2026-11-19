# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Free Laser Cook (0.20.6, funzione in prova, sbloccabile con il codice amministratore).

1. Cosa cuciniamo: ricetta (incluse e tue, da importare, esportare e salvare), cottura, spessore, forma e posizione.
2. Il fuoco: potenza ottica del laser, altezza della testa, dose per passata, velocità, interlinea, passate.
3. I tocchi dello chef: righe della griglia, firma, aroma del legno.
4. Prima di accendere: le accortezze, da spuntare tutte; poi Anteprima / Contorno / Avvia del flusso normale.
"""
import os
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from ..core import cook as C
from ..core import geom
from freelasercut.i18n import tr  # noqa: E402

FOOD_COLORS = {"carne": "#b5544a", "pollame": "#e2c9a6", "pesce": "#f0a184", "verdura": "#7fae5b", "pane": "#d9b27c",
               "formaggio": "#f1d27a", "dolce": "#f6efe6", "altro": "#c9b8a0"}
WOOD_COLOR = "#a8703f"


def _dspin(lo, hi, val, dec=1, step=1.0, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


def _ispin(lo, hi, val, suffix=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(val)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


def checklist():
    """Le accortezze da spuntare prima di accendere: (chiave, testo)."""
    return [
        ("eyes", tr("Occhiali per 450 nm indossati (o carter chiuso): il cibo umido riflette più del legno")),
        ("support", tr("Il cibo è su un supporto pulito e solo suo (ardesia, ghisa, legno massello non trattato), "
                       "mai sul piano del laser")),
        ("air", tr("Aria compressa spenta e aspirazione accesa: è fumo di cucina, ma dentro un laser")),
        ("probe", tr("Termometro a sonda a portata di mano: decide lui quando è cotto, non il conto")),
        ("stay", tr("Resto qui fino alla fine, con un coperchio o un panno umido pronti: il grasso può prendere "
                    "fuoco")),
    ]


class CookDialog(QDialog):
    action = Signal(str, object)  # ("preview"|"frame"|"start"|"save", GcodeJob) come il test materiale

    def __init__(self, profile, head_bed=None, parent=None, qs=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Free Laser Cook (in prova)"))
        self.profile = profile
        self.head_bed = head_bed
        self.qs = qs if qs is not None else QSettings()
        self.recipes = []
        self._plan = None
        self._job = None
        self._loading = False
        root = QHBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        left = QVBoxLayout(host)
        scroll.setWidget(host)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll, 0)
        right = QVBoxLayout()
        root.addLayout(right, 1)

        self.banner = QLabel(tr(
            "<b>Il laser non è un fornello.</b> Non è fatto per cuocere e la macchina non è un attrezzo da cucina: "
            "con le dovute accortezze però si può fare, per gioco e per un assaggio. I numeri sono stime di "
            "partenza: quando è cotto lo dice il termometro."))
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background:#3a2f16; color:#f5d98a; border-radius:6px; padding:8px;")
        left.addWidget(self.banner)

        # ---- 1. cosa cuciniamo
        g1 = QGroupBox(tr("1 · Cosa cuciniamo"))
        f1 = QFormLayout(g1)
        self.recipe_box = QComboBox()
        f1.addRow(tr("Ricetta"), self.recipe_box)
        self.lbl_note = QLabel("")
        self.lbl_note.setObjectName("muted")
        self.lbl_note.setWordWrap(True)
        f1.addRow(self.lbl_note)
        rb = QHBoxLayout()
        self.b_import = QPushButton(tr("Importa…"))
        self.b_export = QPushButton(tr("Esporta…"))
        self.b_keep = QPushButton(tr("Salva fra le mie…"))
        self.b_del = QPushButton(tr("Elimina"))
        self.b_import.setToolTip(tr("Aggiunge alle tue le ricette di un file .flcook"))
        self.b_export.setToolTip(tr("Scrive le tue ricette in un file .flcook da passare a un amico"))
        self.b_keep.setToolTip(tr("Salva la ricetta con i valori che vedi adesso, con un nome tuo"))
        self.b_import.clicked.connect(lambda: self.import_file())
        self.b_export.clicked.connect(lambda: self.export_file())
        self.b_keep.clicked.connect(lambda: self.keep())
        self.b_del.clicked.connect(lambda: self.delete())
        for b in (self.b_import, self.b_export, self.b_keep, self.b_del):
            rb.addWidget(b)
        f1.addRow(rb)
        self.grade = QComboBox()
        self.temp = _dspin(30, 250, 60, 0, 1, " °C")
        self.temp.setToolTip(tr("Temperatura da raggiungere: al cuore per le fette, in superficie per pane, tataki "
                                "e dolci"))
        dr = QHBoxLayout()
        dr.addWidget(self.grade, 1)
        dr.addWidget(self.temp)
        f1.addRow(tr("Cottura"), dr)
        self.thick = _dspin(0.5, 60, 3, 1, 0.5, " mm")
        f1.addRow(tr("Spessore"), self.thick)
        self.shape = QComboBox()
        for k, lab in (("rect", tr("Rettangolo")), ("ellipse", tr("Ovale")),
                       ("selection", tr("La forma selezionata nel disegno"))):
            self.shape.addItem(lab, k)
        self.shape.setToolTip(tr("Per una fettina dalla forma strana: fotografa il piano, ricalca il contorno, "
                                 "selezionalo e scegli «La forma selezionata nel disegno»"))
        f1.addRow(tr("Forma"), self.shape)
        self.w = _dspin(5, 3000, 100, 1, 5, " mm")
        self.h = _dspin(5, 3000, 70, 1, 5, " mm")
        sr = QHBoxLayout()
        sr.addWidget(self.w)
        sr.addWidget(QLabel("×"))
        sr.addWidget(self.h)
        f1.addRow(tr("Misure"), sr)
        self.x0 = _dspin(0, 3000, 100, 1, 5, " mm")
        self.y0 = _dspin(0, 3000, 100, 1, 5, " mm")
        pr = QHBoxLayout()
        pr.addWidget(QLabel("X"))
        pr.addWidget(self.x0)
        pr.addWidget(QLabel("Y"))
        pr.addWidget(self.y0)
        self.b_head = QPushButton(tr("Qui la testa"))
        self.b_head.setEnabled(head_bed is not None)
        self.b_head.clicked.connect(self._at_head)
        pr.addWidget(self.b_head)
        f1.addRow(tr("Angolo in basso a sinistra"), pr)
        left.addWidget(g1)

        # ---- 2. il fuoco
        g2 = QGroupBox(tr("2 · Il fuoco"))
        f2 = QFormLayout(g2)
        self.watts = _dspin(1, 200, 40, 1, 1, " W")
        self.watts.setToolTip(tr("La potenza ottica scritta dal produttore: serve a trasformare la dose in potenza "
                                 "e velocità"))
        f2.addRow(tr("Potenza ottica del laser"), self.watts)
        self.defocus = _dspin(0, 100, 20, 0, 1, " mm")
        self.defocus.setToolTip(tr("Di quanto alzare la testa rispetto al fuoco, a mano: la riga deve diventare "
                                   "larga 2-3 mm. A fuoco il laser incide e carbonizza, non cuoce"))
        f2.addRow(tr("Testa alzata dal fuoco di"), self.defocus)
        self.dose = _dspin(0.01, 1.0, 0.10, 2, 0.01, " J/mm²")
        self.dose.setToolTip(tr("Energia lasciata da una passata. Bassa e ripetuta cuoce; alta in una volta sola "
                                "brucia fuori e lascia crudo dentro"))
        f2.addRow(tr("Dose per passata"), self.dose)
        self.speed = _dspin(C.MIN_SPEED, C.MAX_SPEED, 12000, 0, 500, " mm/min")
        f2.addRow(tr("Velocità preferita"), self.speed)
        self.interval = _dspin(0.3, 5.0, 1.0, 1, 0.1, " mm")
        f2.addRow(tr("Interlinea"), self.interval)
        self.passes = _ispin(0, C.MAX_PASSES, 0)
        self.passes.setSpecialValueText(tr("automatico"))
        self.passes.setToolTip(tr("Passate per lato: in automatico le calcola il conto; a mano dopo la prima prova"))
        f2.addRow(tr("Passate per lato"), self.passes)
        self.fast = QCheckBox(tr("Cottura rapida (tutta la potenza, righe più larghe)"))
        self.fast.setToolTip(tr("Raddoppia l'interlinea e alza la dose della passata: il laser lavora al massimo e "
                                "il tempo scende a meno della metà. Più colore fuori; se restano strisce, alza la "
                                "testa di altri 5 mm"))
        self.fast.toggled.connect(self._fast_toggled)
        f2.addRow(self.fast)
        self.alternate = QCheckBox(tr("Passate incrociate (una per il lungo, una per il largo)"))
        self.flip = QCheckBox(tr("Gira a metà cottura (pausa con il messaggio «Gira il cibo»)"))
        f2.addRow(self.alternate)
        f2.addRow(self.flip)
        left.addWidget(g2)

        # ---- 3. i tocchi dello chef
        g3 = QGroupBox(tr("3 · I tocchi dello chef"))
        f3 = QFormLayout(g3)
        self.sear = QComboBox()
        for k, lab in (("none", tr("Nessuna")), ("grill", tr("Righe della griglia")),
                       ("crosshatch", tr("Griglia incrociata"))):
            self.sear.addItem(lab, k)
        f3.addRow(tr("Segni della griglia"), self.sear)
        self.sear_power = _dspin(1, 100, 100, 0, 5, " %")
        self.sear_speed = _dspin(300, C.MAX_SPEED, 1800, 0, 100, " mm/min")
        gr = QHBoxLayout()
        gr.addWidget(self.sear_power)
        gr.addWidget(self.sear_speed)
        f3.addRow(tr("Potenza e velocità"), gr)
        self.sear_spacing = _dspin(3, 50, 8, 1, 1, " mm")
        self.sear_angle = _dspin(0, 180, 45, 0, 15, "°")
        ga = QHBoxLayout()
        ga.addWidget(self.sear_spacing)
        ga.addWidget(self.sear_angle)
        f3.addRow(tr("Passo e angolo"), ga)
        self.sign = QLineEdit()
        self.sign.setMaxLength(16)
        self.sign.setPlaceholderText(tr("facoltativa: le tue iniziali, «FLC»…"))
        self.sign.setToolTip(tr("Scritta a linea singola al centro, sul lato che resta in alto. A testa alzata il "
                                "tratto è largo: poche lettere grandi"))
        f3.addRow(tr("Firma"), self.sign)
        self.wood = QComboBox()
        for k in C.WOODS:
            self.wood.addItem(tr("Nessuno") if k == "none" else tr("Tavoletta di {0}", C.wood_label(k)), k)
        self.wood.setToolTip(tr("Con il cibo su una tavoletta sottile di legno massello, prima di ogni lato il laser "
                                "fa qualche giro lento sul legno attorno al cibo: il fumo lo profuma"))
        self.laps = _ispin(1, 10, 2)
        wr = QHBoxLayout()
        wr.addWidget(self.wood, 1)
        wr.addWidget(QLabel(tr("giri")))
        wr.addWidget(self.laps)
        f3.addRow(tr("Aroma del legno"), wr)
        left.addWidget(g3)

        # ---- 4. prima di accendere
        g4 = QGroupBox(tr("4 · Prima di accendere"))
        v4 = QVBoxLayout(g4)
        self.checks = {}
        for key, text in checklist():
            cb = QCheckBox(text)
            cb.setStyleSheet("QCheckBox { spacing: 8px; }")
            cb.toggled.connect(self._update_buttons)
            self.checks[key] = cb
            v4.addWidget(cb)
        self.lbl_after = QLabel(tr("Dopo: pulisci la lente (i vapori di grasso la sporcano) e lava il supporto."))
        self.lbl_after.setObjectName("muted")
        self.lbl_after.setWordWrap(True)
        v4.addWidget(self.lbl_after)
        left.addWidget(g4)
        left.addStretch(1)

        # ---- a destra: piatto previsto, riepilogo, pulsanti
        self.preview = QLabel()
        self.preview.setMinimumSize(380, 300)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#20242c; border-radius:6px;")
        right.addWidget(QLabel(tr("Il piatto previsto")))
        right.addWidget(self.preview, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        right.addWidget(self.summary)
        self.chef = QLabel("")
        self.chef.setWordWrap(True)
        self.chef.setStyleSheet("font-style: italic;")
        right.addWidget(self.chef)
        jb = QHBoxLayout()
        self.b_prev = QPushButton(tr("Mostra sul piano"))
        self.b_frame = QPushButton(tr("Contorno"))
        self.b_save = QPushButton(tr("Salva G-code…"))
        self.b_start = QPushButton(tr("Si cucina!"))
        self.b_start.setObjectName("primary")
        self.b_prev.clicked.connect(lambda: self._emit_job("preview"))
        self.b_frame.clicked.connect(lambda: self._emit_job("frame"))
        self.b_save.clicked.connect(lambda: self._emit_job("save"))
        self.b_start.clicked.connect(lambda: self._emit_job("start"))
        for b in (self.b_prev, self.b_frame, self.b_save, self.b_start):
            jb.addWidget(b)
        right.addLayout(jb)

        for wdg in (self.temp, self.thick, self.w, self.h, self.x0, self.y0, self.watts, self.defocus, self.dose,
                    self.speed, self.interval, self.passes, self.sear_power, self.sear_speed, self.sear_spacing,
                    self.sear_angle, self.laps):
            wdg.valueChanged.connect(self.refresh)
        for wdg in (self.shape, self.sear, self.wood):
            wdg.currentIndexChanged.connect(self.refresh)
        for wdg in (self.alternate, self.flip):
            wdg.toggled.connect(self.refresh)
        self.sign.textChanged.connect(self.refresh)
        self.grade.currentIndexChanged.connect(self._done_changed)
        self.recipe_box.currentIndexChanged.connect(self._recipe_changed)
        for c in (self.recipe_box, self.grade, self.shape, self.sear, self.wood):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(14)

        self.watts.setValue(self._start_watts())
        for name, wdg in (("x0", self.x0), ("y0", self.y0), ("w", self.w), ("h", self.h)):
            try:
                v = float(self.qs.value("cook/" + name, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                wdg.setValue(v)
        self.reload(str(self.qs.value("cook/recipe", "") or "manzo_fettina"))
        sb = scroll.verticalScrollBar().sizeHint().width()
        scroll.setMinimumWidth(host.minimumSizeHint().width() + sb + 2 * scroll.frameWidth() + 4)
        self.resize(max(1120, scroll.minimumWidth() + 480), 800)

    # ------------------------------------------------------------------ ricette
    def _start_watts(self):
        try:
            saved = float(self.qs.value("cook/watts", 0) or 0)
        except (TypeError, ValueError):
            saved = 0.0
        if saved > 0:
            return saved
        from ..grbl import optical_watts

        win = self.parent()
        w = win.material_watts() if hasattr(win, "material_watts") else None
        return float(w or optical_watts(getattr(self.profile, "optical_power", "")) or 40.0)

    def reload(self, select=None):
        """Rilegge le ricette (tue con ★, poi quelle incluse) e sceglie quella con la chiave data."""
        cur = select or (self.base().key if self.recipes else "")
        self.recipes = C.library()
        self._loading = True
        self.recipe_box.clear()
        for r in self.recipes:
            self.recipe_box.addItem(("★ " if not r.builtin else "") + f"{r.label()} · {C.kind_label(r.kind)}")
        idx = next((i for i, r in enumerate(self.recipes) if r.key == cur), None)
        if idx is None:
            idx = next((i for i, r in enumerate(self.recipes) if r.builtin), 0)
        self.recipe_box.setCurrentIndex(idx)
        self._loading = False
        self._recipe_changed()

    def base(self):
        """La ricetta scelta nell'elenco, com'è salvata."""
        i = self.recipe_box.currentIndex()
        return self.recipes[i] if 0 <= i < len(self.recipes) else C.builtin()[0]

    def _recipe_changed(self, *_):
        if self._loading:
            return
        r = self.base()
        self._loading = True
        self.lbl_note.setText((tr(r.note) if r.builtin else r.note)
                              + ("" if r.tested else " " + tr("Valori calcolati, non ancora provati.")))
        self.grade.clear()
        for d in r.doneness:
            self.grade.addItem(f"{r.doneness_label(d)} · {d[2]:g} °C", d[0])
        e = r.entry()
        self.grade.setCurrentIndex(max(0, self.grade.findData(e[0])))
        self.temp.setValue(e[2])
        self.thick.setValue(r.thickness)
        self.defocus.setValue(r.defocus_mm)
        self.dose.setValue(r.dose_pass)
        self.speed.setValue(r.speed)
        self.interval.setValue(r.interval)
        self.passes.setValue(0)
        self.fast.setChecked(False)
        self.alternate.setChecked(r.alternate)
        self.flip.setChecked(r.flip)
        self.sear.setCurrentIndex(max(0, self.sear.findData(r.sear["mode"])))
        self.sear_power.setValue(r.sear["power"])
        self.sear_speed.setValue(r.sear["speed"])
        self.sear_spacing.setValue(r.sear["spacing"])
        self.sear_angle.setValue(r.sear["angle"])
        self.sign.setText(r.signature)
        self.wood.setCurrentIndex(max(0, self.wood.findData(r.smoke["wood"])))
        self.laps.setValue(r.smoke["laps"])
        self.b_del.setEnabled(not r.builtin)
        self._loading = False
        self.refresh()

    def _fast_toggled(self, on):
        """Cottura rapida: mette dose e interlinea rapide; tolta la spunta tornano quelle della ricetta."""
        if self._loading:
            return
        r = self.base()
        dose, interval = C.fast_values(r) if on else (r.dose_pass, r.interval)
        self._loading = True
        self.dose.setValue(dose)
        self.interval.setValue(interval)
        self._loading = False
        self.refresh()

    def _done_changed(self, *_):
        if self._loading:
            return
        e = self.base().entry(self.grade.currentData())
        self.temp.setValue(e[2])  # fa partire refresh

    def recipe(self):
        """La ricetta con i valori che si vedono adesso nella finestra."""
        r = self.base()
        sear = dict(r.sear, mode=self.sear.currentData(), power=self.sear_power.value(),
                    speed=self.sear_speed.value(), spacing=self.sear_spacing.value(), angle=self.sear_angle.value())
        smoke = dict(r.smoke, wood=self.wood.currentData(), laps=self.laps.value())
        return C.clean(replace(r, thickness=self.thick.value(), defocus_mm=self.defocus.value(),
                               dose_pass=self.dose.value(), speed=self.speed.value(), interval=self.interval.value(),
                               alternate=self.alternate.isChecked(), flip=self.flip.isChecked(), sear=sear,
                               signature=self.sign.text(), smoke=smoke))

    def keep(self, name=None):
        """Salva fra le tue la ricetta con i valori attuali. -> la ricetta salvata, o None."""
        r = self.recipe()
        if name is None:
            name, ok = QInputDialog.getText(self, tr("Salva fra le mie"), tr("Nome della ricetta"),
                                            text=r.label() if r.builtin else r.name)
            if not ok:
                return None
        name = " ".join(str(name).split())[:60]
        if not name:
            return None
        r = C.as_user(r)
        e = r.entry(self.grade.currentData())
        done = [(d[0], d[1], self.temp.value() if d[0] == e[0] else d[2]) for d in r.doneness]
        saved = C.store(replace(r, name=name, doneness=done, default=e[0], tested=False))
        self.reload(saved.key)
        return saved

    def delete(self):
        r = self.base()
        if r.builtin:
            return False
        if QMessageBox.question(self, tr("Free Laser Cook"), tr("Eliminare la ricetta «{0}»?", r.name)) != QMessageBox.Yes:
            return False
        C.remove(r.key)
        self.reload()
        return True

    def import_file(self, path=None):
        """Aggiunge alle tue le ricette di un file .flcook (stessa chiave = sostituita). -> quante ne ha aggiunte."""
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Importa ricette"),
                                                  str(self.qs.value("cook/dir", os.path.expanduser("~"))),
                                                  tr("Ricette di Free Laser Cook (*.flcook);;Tutti i file (*)"))
        if not path:
            return 0
        try:
            items = C.import_recipes(path)
        except ValueError as ex:
            QMessageBox.warning(self, tr("Free Laser Cook"), str(ex))
            return 0
        self.qs.setValue("cook/dir", os.path.dirname(path))
        for r in reversed(items):
            C.store(r)
        self.reload(items[0].key)
        QMessageBox.information(self, tr("Free Laser Cook"), tr(
            "Ricette aggiunte alle tue: {0}. Sono valori di chi le ha scritte, per il suo laser: la prima volta "
            "prova su un pezzetto.", len(items)))
        return len(items)

    def export_file(self, path=None):
        """Scrive le tue ricette (se non ne hai, quella che vedi) in un file .flcook. -> quante ne ha scritte."""
        items = C.load_user() or [C.as_user(self.recipe())]
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, tr("Esporta ricette"), os.path.join(
                str(self.qs.value("cook/dir", os.path.expanduser("~"))), "ricette" + C.FILE_EXT),
                tr("Ricette di Free Laser Cook (*.flcook)"))
        if not path:
            return 0
        if not path.lower().endswith(C.FILE_EXT):
            path += C.FILE_EXT
        try:
            C.export_recipes(path, items)
        except OSError as ex:
            QMessageBox.warning(self, tr("Free Laser Cook"), tr("Non riesco a scrivere il file: {0}", ex))
            return 0
        self.qs.setValue("cook/dir", os.path.dirname(path))
        return len(items)

    # ------------------------------------------------------------------ forma e piano
    def _at_head(self):
        if self.head_bed is not None:
            self.x0.setValue(max(0.0, self.head_bed[0]))
            self.y0.setValue(max(0.0, self.head_bed[1]))

    def selection_polys(self):
        """Contorni chiusi delle forme selezionate nel disegno (coordinate del piano)."""
        ed = getattr(self.parent(), "editor", None)
        out = []
        for s in getattr(ed, "selection", None) or []:
            for leaf, tf in s.leaves():
                try:
                    out += [p for p in geom.flatten(tf.map(leaf.local_path()), 0.05) if p.closed and len(p.pts) >= 3]
                except (AttributeError, TypeError):
                    continue
        return out

    def polys(self):
        if self.shape.currentData() == "selection":
            return self.selection_polys()
        return C.shape_polys(self.shape.currentData(), self.x0.value(), self.y0.value(), self.w.value(),
                             self.h.value())

    def plan(self):
        prof = self.profile
        return C.compute(self.recipe(), self.watts.value(), self.polys(), doneness=self.grade.currentData(),
                         target=self.temp.value(), thickness=self.thick.value(), passes=self.passes.value(),
                         bed=(prof.bed_x, prof.bed_y), vmax=min(prof.max_rate_x, prof.max_rate_y))

    def build(self):
        """(Plan, GcodeJob) con i valori attuali; il lavoro è None se il piano ha un blocco."""
        plan = self.plan()
        job = C.build_job(plan, self.profile) if plan.ok else None
        if job is not None and job.warnings:
            plan.blockers += job.warnings
        return plan, job

    def missing_checks(self):
        return [k for k, cb in self.checks.items() if not cb.isChecked()]

    def ready(self):
        return self._plan is not None and self._plan.ok and self._job is not None and not self.missing_checks()

    def _emit_job(self, kind):
        self.refresh()
        if self._job is None:
            QMessageBox.warning(self, tr("Free Laser Cook"), "\n".join(self._plan.blockers))
            return
        if kind == "start" and self.missing_checks():
            QMessageBox.information(self, tr("Free Laser Cook"), tr("Prima spunta tutte le accortezze del punto 4: "
                                                                    "lo chef non accende senza."))
            return
        self._remember()
        self.action.emit(kind, self._job)

    def _remember(self):
        self.qs.setValue("cook/recipe", self.base().key)
        self.qs.setValue("cook/watts", self.watts.value())
        for name, wdg in (("x0", self.x0), ("y0", self.y0), ("w", self.w), ("h", self.h)):
            self.qs.setValue("cook/" + name, wdg.value())

    # ------------------------------------------------------------------ stato e anteprima
    def summary_html(self, plan):
        r = plan.recipe
        if not plan.ok:
            return "<br>".join("⚠ " + b for b in plan.blockers)
        sides = (tr("{0} passate per lato, {1} lati", plan.passes, plan.sides) if plan.sides == 2
                 else tr("{0} passate, senza girare", plan.passes))
        rows = [
            f"<b>{r.label()}</b> · {r.doneness_label(plan.entry)} · {plan.target:g} °C · {plan.thickness:g} mm",
            tr("{0} · potenza <b>{1:.0f}%</b> · velocità <b>{2:g} mm/min</b> · interlinea {3:g} mm", sides, plan.power,
               plan.speed, plan.interval),
            tr("Dose {0:.2f} J/mm² per passata, {1:.2f} J/mm² per lato · energia sul piatto {2:.1f} kJ "
               "({3:.1f} Wh)", plan.dose, plan.dose * plan.passes, plan.joule / 1000.0, plan.joule / 3600.0),
            tr("Tempo di cottura stimato <b>{0}</b>, più le pause · testa alzata di {1:g} mm dal fuoco",
               C.mmss(plan.seconds), plan.defocus),
        ]
        rows += ["⚠ " + w for w in plan.warnings]
        return "<br>".join(rows)

    def refresh(self, *_):
        if self._loading:
            return
        sel = self.shape.currentData() == "selection"
        for wdg in (self.w, self.h, self.x0, self.y0):
            wdg.setEnabled(not sel)
        self.b_head.setEnabled(not sel and self.head_bed is not None)
        on = self.sear.currentData() != "none"
        for wdg in (self.sear_spacing, self.sear_angle):
            wdg.setEnabled(on)
        for wdg in (self.sear_power, self.sear_speed):
            wdg.setEnabled(on or bool(C.clean_signature(self.sign.text())))
        self.laps.setEnabled(self.wood.currentData() != "none")
        try:
            self._plan, self._job = self.build()
        except Exception as ex:  # noqa: BLE001 — mostra l'errore invece di chiudere la finestra
            self._plan, self._job = None, None
            self.summary.setText(tr("Errore: {0}", ex))
            self.chef.setText("")
            self._update_buttons()
            return
        self.summary.setText(self.summary_html(self._plan))
        self.chef.setText(C.chef_says(self._plan))
        self._draw()
        self._update_buttons()

    def _update_buttons(self, *_):
        ok = self._job is not None
        for b in (self.b_prev, self.b_frame, self.b_save):
            b.setEnabled(ok)
        self.b_start.setEnabled(self.ready())
        miss = len(self.missing_checks())
        self.b_start.setToolTip("" if not miss else tr("Mancano {0} accortezze da spuntare al punto 4", miss))

    def _draw(self):
        """Il piatto visto dall'alto: tavoletta, giro dell'aroma, cibo, righe della griglia, firma."""
        plan = self._plan
        size = self.preview.size()
        pw, ph = max(size.width(), 380), max(size.height(), 300)
        pm = QPixmap(pw, ph)
        pm.fill(QColor("#20242c"))
        if plan is None or not plan.polys:
            self.preview.setPixmap(pm)
            return
        r = plan.recipe
        smoke = r.smoke["wood"] != "none"
        m = (r.smoke["margin"] + 8.0) if smoke else 10.0
        x0, y0, x1, y1 = plan.box[0] - m, plan.box[1] - m, plan.box[2] + m, plan.box[3] + m
        k = min((pw - 20) / (x1 - x0), (ph - 20) / (y1 - y0))
        ox, oy = (pw - (x1 - x0) * k) / 2.0, (ph - (y1 - y0) * k) / 2.0

        def pt(x, y):
            return QPointF(ox + (x - x0) * k, ph - oy - (y - y0) * k)

        def path_of(polys):
            path = QPainterPath()
            for q in polys:
                path.moveTo(pt(*q.pts[0]))
                for a in q.pts[1:]:
                    path.lineTo(pt(*a))
                if q.closed:
                    path.closeSubpath()
            return path

        g = QPainter(pm)
        g.setRenderHint(QPainter.Antialiasing)
        board = QRectF(pt(x0 + 2, y1 - 2), pt(x1 - 2, y0 + 2))
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(WOOD_COLOR) if smoke else QColor("#3b4150"))
        g.drawRoundedRect(board, 8, 8)
        if smoke:
            g.setPen(QPen(QColor("#2a1608"), max(2.0, 2.5 * k)))
            g.setBrush(Qt.NoBrush)
            g.drawPath(path_of(C.smoke_polys(plan.box, r.smoke["margin"])))
        food = path_of(plan.polys)
        food.setFillRule(Qt.OddEvenFill)
        g.setPen(QPen(QColor(0, 0, 0, 90), 1.5))
        g.setBrush(QColor(FOOD_COLORS.get(r.kind, FOOD_COLORS["altro"])))
        g.drawPath(food)
        if plan.ok:
            from ..core.gcode import _scanlines

            dark = QPen(QColor(45, 25, 15, 210), max(1.5, 2.5 * k), Qt.SolidLine, Qt.FlatCap)
            if r.sear["mode"] != "none":
                g.setPen(dark)
                for ang in [r.sear["angle"]] + ([r.sear["angle"] + 90.0] if r.sear["mode"] == "crosshatch" else []):
                    lines, rot = _scanlines(plan.polys, r.sear["spacing"], ang)
                    for y, segs in lines or []:
                        for a, b in segs:
                            g.drawLine(pt(a * rot[0] - y * rot[1], a * rot[1] + y * rot[0]),
                                       pt(b * rot[0] - y * rot[1], b * rot[1] + y * rot[0]))
            sign = C.signature_polys(r.signature, plan.box)
            if sign:
                g.setPen(QPen(QColor(35, 18, 10, 235), max(1.5, 2.5 * k), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                g.setBrush(Qt.NoBrush)
                g.drawPath(path_of(sign))
        g.end()
        self.preview.setPixmap(pm)
