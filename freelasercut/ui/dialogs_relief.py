# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Rilievo 3D su tavola (0.17.16, funzione in prova, sbloccabile con il codice amministratore).

1. Modello: immagine in grigi o modello .stl/.obj, misure, posizione, profondità totale, spessore della tavola.
2. Materiale e parametri: potenza, velocità, interlinea (uguali per tutte le passate).
3. Test di profondità, obbligatorio: scala di gradini fatta con lo stesso metodo del lavoro; si misurano col calibro
   il primo e l'ultimo gradino e si giudica a vista. Accettato entro il 10%, altrimenti si corregge e si rifà.
   «Salta il test» si può, con un avviso esplicito dei rischi.
4. Lavoro: passate, tempo, anteprima del rilievo previsto; poi Anteprima / Contorno / Avvia del flusso normale.
"""
import os

import numpy as np
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import units
from ..core import relief as R
from freelasercut.i18n import tr  # noqa: E402

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
MESH_EXT = (".stl", ".obj")


def _dspin(lo, hi, val, dec=1, step=1.0, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


class ReliefDialog(QDialog):
    action = Signal(str, object)  # ("preview"|"frame"|"start"|"save", GcodeJob) come il test materiale

    def __init__(self, profile, head_bed=None, parent=None, qs=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Rilievo 3D su tavola (in prova)"))
        self.profile = profile
        self.head_bed = head_bed
        self.qs = qs if qs is not None else QSettings()
        self.src = None  # ("image", array) | ("mesh", Mesh)
        self.src_name = ""
        self.model = None  # DepthModel accettato in questa sessione
        self.accepted_key = None  # chiave dei parametri per cui il test è stato accettato
        self.accepted_depth = 0.0  # profondità misurata sull'ultimo gradino del test accettato (mm)
        self.skip_ok = False  # «Salta il test» confermato
        self.test_n = None  # passate dei gradini del test attuale
        self._job = None
        self._test_job = None
        root = QHBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        left = QVBoxLayout(host)
        scroll.setWidget(host)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # niente comandi tagliati a destra
        self._scroll, self._host = scroll, host
        root.addWidget(scroll, 0)
        right = QVBoxLayout()
        root.addLayout(right, 1)

        # ---- 1. modello
        g1 = QGroupBox(tr("1 · Modello"))
        f1 = QFormLayout(g1)
        self.b_open = QPushButton(tr("Apri un'immagine in grigi o un modello 3D…"))
        self.b_open.clicked.connect(self.open_file)
        self.lbl_file = QLabel(tr("nessun file"))
        self.lbl_file.setObjectName("muted")
        f1.addRow(self.b_open)
        f1.addRow(self.lbl_file)
        self.white = QComboBox()
        self.white.addItem(tr("Il bianco è in alto (non inciso)"), True)
        self.white.addItem(tr("Il nero è in alto (non inciso)"), False)
        f1.addRow(tr("Immagine"), self.white)
        self.up = QComboBox()
        for k, lab in (("z", tr("Z verso l'alto")), ("y", tr("Y verso l'alto")), ("x", tr("X verso l'alto"))):
            self.up.addItem(lab, k)
        f1.addRow(tr("Modello 3D"), self.up)
        self.bg = QComboBox()
        self.bg.addItem(tr("Intorno al modello si scende al fondo (l'oggetto esce in rilievo)"), "bottom")
        self.bg.addItem(tr("Intorno al modello non si incide"), "surface")
        f1.addRow(tr("Sfondo"), self.bg)
        self.width = _dspin(5, 400, 60, 1, 5, " mm")
        self.lbl_h = QLabel("")
        wr = QHBoxLayout()
        wr.addWidget(self.width)
        wr.addWidget(self.lbl_h, 1)
        f1.addRow(tr("Larghezza"), wr)
        self.x0 = _dspin(0, 3000, 20, 1, 5, " mm")
        self.y0 = _dspin(0, 3000, 20, 1, 5, " mm")
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
        self.depth = _dspin(0.1, R.MAX_DEPTH, 2.0, 2, 0.1, " mm")
        self.depth.setToolTip(tr("Profondità del punto più basso. Al massimo {0:g} mm a testa ferma.", R.MAX_DEPTH))
        f1.addRow(tr("Profondità totale"), self.depth)
        self.thick = _dspin(1, 100, 10, 1, 0.5, " mm")
        f1.addRow(tr("Spessore della tavola"), self.thick)
        left.addWidget(g1)

        # ---- 2. materiale e parametri
        g2 = QGroupBox(tr("2 · Materiale e parametri"))
        f2 = QFormLayout(g2)
        self.material = QComboBox()
        self.material.setEditable(True)
        try:
            from ..core import materials

            for m in materials.library():
                if self.material.findText(m.name) < 0:
                    self.material.addItem(m.name)
        except Exception:  # noqa: BLE001
            pass
        self.material.setCurrentText(self.qs.value("relief/material", "MDF") or "MDF")
        f2.addRow(tr("Materiale"), self.material)
        self.power = _dspin(1, 100, float(self.qs.value("relief/power", 80)), 1, 5, " %")
        f2.addRow(tr("Potenza"), self.power)
        self.speed = units.SpeedSpin(100, 30000, float(self.qs.value("relief/speed", 3000)), 250)
        f2.addRow(tr("Velocità"), self.speed)
        self.interval = _dspin(0.05, 0.5, float(self.qs.value("relief/interval", 0.1)), 2, 0.05, " mm")
        self.interval.setToolTip(tr("Distanza fra le righe e lato dei punti della mappa"))
        f2.addRow(tr("Interlinea"), self.interval)
        self.dither = QCheckBox(tr("Sfuma i gradini fra uno strato e l'altro"))
        self.dither.setChecked(True)
        self.alternate = QCheckBox(tr("Direzioni alternate (righe lungo X e lungo Y)"))
        self.alternate.setChecked(True)
        self.air = QCheckBox(tr("Aria compressa accesa (consigliata)"))
        self.air.setChecked(True)
        for w in (self.dither, self.alternate, self.air):
            f2.addRow("", w)
        left.addWidget(g2)

        # ---- 3. test di profondità
        g3 = QGroupBox(tr("3 · Test di profondità (obbligatorio)"))
        v3 = QVBoxLayout(g3)
        self.lbl_test = QLabel("")
        self.lbl_test.setWordWrap(True)
        v3.addWidget(self.lbl_test)
        f3 = QFormLayout()
        self.tx = _dspin(0, 3000, 20, 1, 5, " mm")
        self.ty = _dspin(0, 3000, 5, 1, 5, " mm")
        tr_ = QHBoxLayout()
        tr_.addWidget(QLabel("X"))
        tr_.addWidget(self.tx)
        tr_.addWidget(QLabel("Y"))
        tr_.addWidget(self.ty)
        f3.addRow(tr("Test in basso a sinistra"), tr_)
        v3.addLayout(f3)
        tb = QHBoxLayout()
        self.b_tprev = QPushButton(tr("Mostra il test"))
        self.b_tframe = QPushButton(tr("Contorno"))
        self.b_tstart = QPushButton(tr("Avvia il test"))
        self.b_tprev.clicked.connect(lambda: self._emit_test("preview"))
        self.b_tframe.clicked.connect(lambda: self._emit_test("frame"))
        self.b_tstart.clicked.connect(lambda: self._emit_test("start"))
        for b in (self.b_tprev, self.b_tframe, self.b_tstart):
            tb.addWidget(b)
        v3.addLayout(tb)
        f4 = QFormLayout()
        self.d1 = _dspin(0, 10, 0, 2, 0.01, " mm")
        self.dn = _dspin(0, 20, 0, 2, 0.01, " mm")
        self.lbl_d1 = QLabel(tr("Primo gradino (a sinistra)"))
        self.lbl_dn = QLabel(tr("Ultimo gradino (a destra)"))
        f4.addRow(self.lbl_d1, self.d1)
        f4.addRow(self.lbl_dn, self.dn)
        self.judge = QComboBox()
        for k, lab in (("clean", tr("Fondo pulito")), ("dark", tr("Fondo molto annerito")),
                       ("edges", tr("Bordi bruciati")), ("flames", tr("Ci sono state fiamme"))):
            self.judge.addItem(lab, k)
        f4.addRow(tr("A vista"), self.judge)
        v3.addLayout(f4)
        self.b_check = QPushButton(tr("Controlla le misure"))
        self.b_check.clicked.connect(self.check_test)
        v3.addWidget(self.b_check)
        self.lbl_res = QLabel("")
        self.lbl_res.setWordWrap(True)
        v3.addWidget(self.lbl_res)
        self.skip = QCheckBox(tr("Salta il test (sconsigliato)"))
        self.skip.toggled.connect(self._skip_toggled)
        v3.addWidget(self.skip)
        left.addWidget(g3)
        left.addStretch(1)

        # ---- 4. lavoro (a destra)
        self.preview = QLabel()
        self.preview.setMinimumSize(380, 300)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#20242c; border-radius:6px;")
        right.addWidget(QLabel(tr("4 · Rilievo previsto")))
        right.addWidget(self.preview, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        jb = QHBoxLayout()
        self.b_prev = QPushButton(tr("Mostra sul piano"))
        self.b_frame = QPushButton(tr("Contorno"))
        self.b_save = QPushButton(tr("Salva G-code…"))
        self.b_start = QPushButton(tr("Avvia il rilievo"))
        self.b_start.setObjectName("primary")
        self.b_prev.clicked.connect(lambda: self._emit_job("preview"))
        self.b_frame.clicked.connect(lambda: self._emit_job("frame"))
        self.b_save.clicked.connect(lambda: self._emit_job("save"))
        self.b_start.clicked.connect(lambda: self._emit_job("start"))
        for b in (self.b_prev, self.b_frame, self.b_save, self.b_start):
            jb.addWidget(b)
        right.addLayout(jb)

        for w in (self.width, self.x0, self.y0, self.depth, self.thick, self.power, self.speed, self.interval,
                  self.tx, self.ty):
            w.valueChanged.connect(self.refresh)
        for w in (self.white, self.up, self.bg):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.dither, self.alternate, self.air):
            w.toggled.connect(self.refresh)
        self.material.currentTextChanged.connect(self.refresh)
        for c in (self.white, self.up, self.bg, self.material, self.judge):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)  # le voci lunghe non allargano
            c.setMinimumContentsLength(16)
        self.refresh()
        sb = scroll.verticalScrollBar().sizeHint().width()
        scroll.setMinimumWidth(host.minimumSizeHint().width() + sb + 2 * scroll.frameWidth() + 4)
        self.resize(max(1180, scroll.minimumWidth() + 520), 780)

    # ------------------------------------------------------------------ dati
    def key(self):
        return R.calib_key(self.profile.name, self.material.currentText(), self.power.value(), self.speed.value(),
                           self.interval.value())

    def base_model(self):
        """Modello per il piano: quello del test accettato; con «Salta» la taratura salvata o quello prudente."""
        if self.model is not None and self.accepted_key == self.key():
            return self.model
        m, _d = R.find_calibration(self.key())
        return m if m is not None else R.DepthModel.prior()

    def grid(self):
        p = self.interval.value()
        w = self.width.value()
        asp = self._aspect()
        h = w / asp if asp else w
        nx, ny = max(2, int(round(w / p))), max(2, int(round(h / p)))
        return p, nx, ny

    def _aspect(self):
        if self.src is None:
            return 1.0
        kind, obj = self.src
        if kind == "image":
            hh, ww = obj.shape[:2]
            return ww / max(hh, 1)
        wx, wy = R.mesh_aspect(obj, self.up.currentData())
        return wx / wy if wy > 1e-12 else 1.0

    def heightmap(self):
        if self.src is None:
            return None
        p, nx, ny = self.grid()
        kind, obj = self.src
        if kind == "image":
            return R.heightmap_from_image(obj, nx, ny, bool(self.white.currentData()))
        return R.heightmap_from_mesh(obj, nx, ny, self.up.currentData(), self.bg.currentData())

    def plan(self):
        """(mappa delle passate, modello, errore) per il lavoro vero."""
        h = self.heightmap()
        if h is None:
            return None, None, tr("Apri prima un'immagine o un modello 3D.")
        model = self.base_model()
        why = R.check_depth(self.depth.value(), self.thick.value(), model)
        if why:
            return None, model, why
        return R.pass_map(h, self.depth.value(), model, self.dither.isChecked()), model, ""

    def total_passes(self):
        model = self.base_model()
        return max(1, int(np.floor(float(model.passes(self.depth.value())) + 0.5)))

    def ready(self):
        """Si può avviare il rilievo? (test accettato con questi parametri, oppure «Salta» confermato)"""
        tested = (self.accepted_key == self.key() and self.model is not None
                  and self.depth.value() <= self.accepted_depth * (1 + R.TOLERANCE) + 1e-9)
        return tested or self.skip_ok

    # ------------------------------------------------------------------ azioni
    def open_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("Rilievo 3D: apri"), self.qs.value("relief/dir", os.path.expanduser("~")),
                tr("Immagini e modelli 3D (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.stl *.obj)"))
        if not path:
            return False
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in MESH_EXT:
                from ..core import sculpt

                self.src = ("mesh", sculpt.load(path))
            elif ext in IMG_EXT:
                from PIL import Image

                with Image.open(path) as im:
                    self.src = ("image", np.asarray(im.convert("L")))
            else:
                raise ValueError(tr("Formato non supportato: servono immagini o file .stl/.obj."))
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, tr("Rilievo 3D"), tr("Non riesco ad aprire il file: {0}", ex))
            return False
        self.src_name = os.path.basename(path)
        self.qs.setValue("relief/dir", os.path.dirname(path))
        self.lbl_file.setText(self.src_name)
        self.refresh()
        return True

    def _at_head(self):
        if self.head_bed is not None:
            self.x0.setValue(max(0.0, self.head_bed[0]))
            self.y0.setValue(max(0.0, self.head_bed[1]))

    def _skip_toggled(self, on):
        if not on:
            self.skip_ok = False
            self.refresh()
            return
        m, d = R.find_calibration(self.key())
        base = (tr("Userò la taratura salvata il {0} per questo materiale e questi parametri.", d.get("date", "?"))
                if m is not None else
                tr("Non c'è una taratura salvata per questo materiale e questi parametri: userò valori prudenti e il "
                   "lavoro resterà «non tarato»."))
        r = QMessageBox.warning(
            self, tr("Salta il test"),
            tr("Senza il test di profondità su questa tavola:\n\n• la profondità può venire molto diversa da quella "
               "voluta e il pezzo può essere da buttare;\n• con troppa energia si può bucare la tavola o far prendere "
               "fuoco al materiale;\n• lo stesso legno cambia da una tavola all'altra.\n\n{0}\n\nSaltare il test lo "
               "stesso?", base), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self.skip_ok = r == QMessageBox.Yes
        if not self.skip_ok:
            self.skip.blockSignals(True)
            self.skip.setChecked(False)
            self.skip.blockSignals(False)
        self.refresh()

    def test_job(self):
        n = self.total_passes()
        self.test_n = R.test_steps(n)
        nmap = R.test_map(self.test_n, self.interval.value())
        return R.build_job(nmap, self.interval.value(), self.tx.value(), self.ty.value(), self.power.value(),
                           self.speed.value(), self.profile, self.alternate.isChecked(), tr("test di profondità"),
                           air=self.air.isChecked())

    def _emit_test(self, kind):
        self._remember()
        self._test_job = self.test_job()
        self.refresh()
        self.action.emit(kind, self._test_job)

    def check_test(self):
        """Misure del calibro + giudizio a vista → modello, accettazione e correzioni."""
        if not self.test_n:
            self.lbl_res.setText(tr("Prima incidi il test: le misure valgono per i gradini di quel test."))
            return False
        n = self.test_n[-1]
        judgment = self.judge.currentData()
        new_power, redo, msg = R.after_judgment(judgment, self.power.value())
        try:
            model = R.fit(self.d1.value(), self.dn.value(), n)
        except ValueError as ex:
            self.lbl_res.setText(tr("Misure non accettate: {0}", ex))
            return False
        if redo:
            self.model, self.accepted_key = None, None
            self.power.setValue(new_power)
            self.lbl_res.setText(msg)
            return False
        ok, err = R.accept(self.dn.value(), self.depth.value())
        top, _ = R.limits(self.depth.value(), self.thick.value(), model)
        if self.depth.value() > top + 1e-9:
            self.model, self.accepted_key = None, None
            self.lbl_res.setText(tr("Su questo materiale con questi parametri si arriva bene fino a {0:.1f} mm: "
                                    "riduci la profondità totale e rifai il test.", top))
            return False
        if ok:
            self.model, self.accepted_key, self.accepted_depth = model, self.key(), self.dn.value()
            try:
                R.save_calibration(self.key(), model, self.d1.value(), self.dn.value(), n, judgment)
            except OSError:
                pass
            txt = tr("Test accettato: l'ultimo gradino è a {0:+.0f}% dalla profondità voluta. Una passata toglie "
                     "{1:.2f} mm; servono {2} passate.", err * 100, model.a, max(1, int(round(float(model.passes(
                         self.depth.value()))))))
            self.lbl_res.setText(txt + (" " + msg if msg else ""))
        else:
            self.model, self.accepted_key = None, None
            # il prossimo test usa il modello misurato: lo salvo come taratura provvisoria per questa chiave
            try:
                R.save_calibration(self.key(), model, self.d1.value(), self.dn.value(), n, judgment)
            except OSError:
                pass
            need = max(1, int(round(float(model.passes(self.depth.value())))))
            self.lbl_res.setText(tr("L'ultimo gradino è a {0:+.0f}% dalla profondità voluta (tolleranza ±{1:.0f}%). "
                                    "Con le misure servono {2} passate invece di {3}: rifai il test con i valori "
                                    "corretti.", err * 100, R.TOLERANCE * 100, need, n))
        self.refresh()
        return ok

    def build(self):
        nmap, model, why = self.plan()
        if why:
            raise ValueError(why)
        return R.build_job(nmap, self.interval.value(), self.x0.value(), self.y0.value(), self.power.value(),
                           self.speed.value(), self.profile, self.alternate.isChecked(), self.src_name,
                           air=self.air.isChecked())

    def _emit_job(self, kind):
        if kind == "start" and not self.ready():
            QMessageBox.information(self, tr("Rilievo 3D"), tr("Prima fai il test di profondità e fai accettare le "
                                                               "misure (oppure spunta «Salta il test»)."))
            return
        try:
            self._job = self.build()
        except ValueError as ex:
            QMessageBox.warning(self, tr("Rilievo 3D"), str(ex))
            return
        self._remember()
        self.action.emit(kind, self._job)

    def _remember(self):
        self.qs.setValue("relief/material", self.material.currentText())
        self.qs.setValue("relief/power", self.power.value())
        self.qs.setValue("relief/speed", self.speed.value())
        self.qs.setValue("relief/interval", self.interval.value())

    # ------------------------------------------------------------------ stato e anteprima
    def refresh(self, *_):
        is_mesh = self.src is not None and self.src[0] == "mesh"
        self.up.setEnabled(is_mesh)
        self.bg.setEnabled(is_mesh)
        self.white.setEnabled(self.src is not None and not is_mesh)
        p, nx, ny = self.grid()
        self.lbl_h.setText(tr("× {0:.1f} mm", ny * p))
        if self.accepted_key is not None and self.accepted_key != self.key():
            self.model, self.accepted_key = None, None  # parametri cambiati: il test va rifatto
        n = self.total_passes()
        steps = R.test_steps(n)
        tw = len(steps) * R.STEP_W
        self.lbl_test.setText(tr("Scala di {0} gradini ({1:.0f} × {2:.0f} mm) da incidere su un ritaglio della stessa "
                                 "tavola: passate {3}. Poi misura col calibro il primo e l'ultimo gradino. L'ultimo "
                                 "deve arrivare a {4:.2f} mm (±{5:.0f}%).", len(steps), tw, R.STEP_H,
                                 ", ".join(str(s) for s in steps), self.depth.value(), R.TOLERANCE * 100))
        from .main_window import _hms

        t_test = approx_seconds(R.test_map(steps, self.interval.value()), self.interval.value(), self.speed.value(),
                                self.alternate.isChecked())
        self.lbl_test.setText(self.lbl_test.text() + "\n" + tr("Durata del test: circa {0}.", _hms(t_test)))
        self.lbl_dn.setText(tr("Ultimo gradino ({0} passate)", steps[-1]))
        nmap, model, why = self.plan()
        deeper = (self.accepted_key == self.key() and self.model is not None
                  and self.depth.value() > self.accepted_depth * (1 + R.TOLERANCE) + 1e-9)
        state = (tr("Il test è stato accettato fino a {0:.2f} mm: per una profondità maggiore rifai il test.",
                    self.accepted_depth) if deeper else
                 tr("Tarato: test accettato.") if self.accepted_key == self.key() and self.model is not None else
                 tr("NON TARATO: test saltato.") if self.skip_ok else tr("Da tarare: fai il test di profondità."))
        if why:
            self.summary.setText(why + "\n" + state)
            self.preview.clear()
        else:
            secs = approx_seconds(nmap, p, self.speed.value(), self.alternate.isChecked())
            from .main_window import _hms

            top, reasons = R.limits(self.depth.value(), self.thick.value(), model)
            self.summary.setText(tr("{0} passate · {1:.1f} × {2:.1f} mm · profondità {3:.2f} mm (massimo {4:.2f}) · "
                                    "tempo stimato {5}\n{6}", int(nmap.max()), nx * p, ny * p, self.depth.value(),
                                    top, _hms(secs), state))
            spot = max(float(getattr(self.profile, "spot_x_mm", 0.1)), float(getattr(self.profile, "spot_y_mm", 0.1)))
            img = R.shaded(R.predicted(nmap, model, p, spot), p)
            self._set_preview(img)
        ok = self.ready() and not why
        self.b_start.setEnabled(ok)
        for b in (self.b_prev, self.b_frame, self.b_save):
            b.setEnabled(not why)

    def _set_preview(self, img):
        h, w = img.shape
        qimg = QImage(np.ascontiguousarray(img).data, w, h, w, QImage.Format_Grayscale8).copy()
        pm = QPixmap.fromImage(qimg).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)


def approx_seconds(nmap, pitch, speed, alternate=True, overscan=2.0):
    """Stima veloce (prima di generare il G-code): per ogni passata e ogni riga, dal primo all'ultimo punto più
    l'overscan, alla velocità di lavoro."""
    v = max(float(speed), 1.0) / 60.0
    tot = 0.0
    for k, m in enumerate(R.masks(nmap), start=1):
        mm = m.T if (alternate and k % 2 == 0) else m
        rows = np.flatnonzero(mm.any(axis=1))
        for r in rows:
            idx = np.flatnonzero(mm[r])
            tot += ((idx[-1] - idx[0] + 1) * pitch + 2 * overscan) / v
    return tot
