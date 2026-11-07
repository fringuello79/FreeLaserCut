# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Materiali imparati: FreeLaserCut impara il tuo materiale dalle foto dei test e lo usa.

* «Impara questo materiale» nel risultato della foto del test: nuova curva o affina una che c'è già;
* finestra Materiali imparati: la curva (scuro previsto per ogni potenza, alla velocità scelta), i colori
  veri del tuo legno, «che potenza per questo tono», applica a un livello, esporta / importa un file.
"""
import html
import re
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from ..core import burn_curve as bc
from ..theme import C, css
from . import style
from .editor import TOOL_LAYER
from freelasercut.i18n import tr  # noqa: E402
from .. import units


def _qcolor(rgb):
    r, g, b = (int(round(float(v))) for v in rgb)
    return QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def swatch_icon(curve, size=18):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    n = 6
    for i in range(n):  # dal nudo al nero massimo
        d = curve.d_max * i / (n - 1)
        p.setBrush(_qcolor(curve.color(d)))
        p.drawRect(QRectF(size * i / n, 0, size / n + 0.6, size))
    p.setPen(QPen(QColor(0, 0, 0, 90), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, size - 1, size - 1))
    p.end()
    return QIcon(pm)


def _when(t):
    try:
        return time.strftime("%d/%m/%Y", time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"


# ===================================================================== grafico
class CurvePlot(QWidget):
    """Scuro previsto per ogni potenza (0–100 %) alla velocità e interlinea scelte, con le misure vere e,
    sotto, i colori che avrà il tuo materiale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curve = None
        self.speed, self.interval, self.passes = 3000.0, 0.1, 1
        self.marker = None  # potenza da segnare
        self.band = None  # (da, a) potenze per le foto
        self.setMinimumSize(380, 240)

    def set(self, curve=None, speed=None, interval=None, passes=None, marker="keep", band="keep"):
        if curve is not None or curve is False:
            self.curve = curve or None
        if speed is not None:
            self.speed = float(speed)
        if interval is not None:
            self.interval = float(interval)
        if passes is not None:
            self.passes = int(passes)
        if marker != "keep":
            self.marker = marker
        if band != "keep":
            self.band = band
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C["panel"]))
        c = self.curve
        L, R, T, B = 40, 12, 10, 52
        w, h = self.width() - L - R, self.height() - T - B
        if c is None or not c.ok or w < 40 or h < 40:
            p.setPen(QColor(C["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Nessuna curva"))
            p.end()
            return
        ytop = max(0.3, min(1.0, c.d_max * 1.12))

        def X(pw):
            return L + w * pw / 100.0

        def Y(d):
            return T + h * (1.0 - d / ytop)

        grid = QColor(C["border"])
        txt = QColor(C["muted"])
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        p.setPen(QPen(grid, 1))
        for k in range(0, 101, 25):
            p.drawLine(QPointF(X(k), T), QPointF(X(k), T + h))
        for k in range(0, 5):
            yy = T + h * k / 4
            p.drawLine(QPointF(L, yy), QPointF(L + w, yy))
        p.setPen(txt)
        for k in range(0, 101, 25):
            p.drawText(QRectF(X(k) - 20, T + h + 26, 40, 14), Qt.AlignCenter, f"{k} %")
        for k in range(0, 5):
            d = ytop * (1 - k / 4)
            p.drawText(QRectF(0, T + h * k / 4 - 7, L - 4, 14), Qt.AlignRight | Qt.AlignVCenter, f"{d * 100:.0f}")
        # fascia per le foto
        if self.band:
            a, b = self.band
            p.fillRect(QRectF(X(a), T, max(1.0, X(b) - X(a)), h), QColor(226, 112, 11, 40))
        # misure vere (riportate a questa velocità e interlinea)
        for s in c.samples:
            pw = bc.power_for_energy(s[0], self.speed, self.interval, self.passes)
            if 0 < pw <= 100:
                col = _qcolor([s[3 + i] * c.bare[i] for i in range(3)])
                p.setPen(QPen(QColor(255, 255, 255, 160), 1))
                p.setBrush(col)
                p.drawEllipse(QPointF(X(pw), Y(s[1])), 3.2, 3.2)
        # curva
        path = QPainterPath()
        for i in range(0, 201):
            pw = i * 0.5
            d = c.dark_at(pw, self.speed, self.interval, self.passes)
            pt = QPointF(X(pw), Y(d))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor(C["accent"]), 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # colori del materiale
        band_y = T + h + 4
        n = max(20, int(w // 3))
        for i in range(n):
            pw = 100.0 * (i + 0.5) / n
            p.fillRect(QRectF(L + w * i / n, band_y, w / n + 0.7, 18),
                       _qcolor(c.color(c.dark_at(pw, self.speed, self.interval, self.passes))))
        if self.marker is not None and 0 <= self.marker <= 100:
            mx = X(self.marker)
            p.setPen(QPen(QColor(C["text"]), 1.4, Qt.DashLine))
            p.drawLine(QPointF(mx, T), QPointF(mx, band_y + 18))
        p.end()


# ===================================================================== imparare dalla foto
class LearnDialog(QDialog):
    """Dal risultato della foto del test: nuova curva o affina una esistente."""

    def __init__(self, res, spec, machine="", parent=None):
        super().__init__(parent)
        self.res, self.spec, self.machine = res, spec, machine
        self.curve = None
        self.setWindowTitle(tr("Impara questo materiale"))
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)
        head = QLabel(tr("FreeLaserCut misura come ha risposto il materiale in ogni quadrato e se lo ricorda: potrai "
                         "prevedere il risultato sul tuo legno, scegliere un tono e correggere i toni delle foto. Più "
                         "foto gli dai, più impara."))
        head.setWordWrap(True)
        v.addWidget(head)
        self.curves = bc.load_all()
        self.r_new = QRadioButton(tr("Nuovo materiale"))
        self.r_add = QRadioButton(tr("Affina un materiale già imparato"))
        grp = QButtonGroup(self)
        grp.addButton(self.r_new)
        grp.addButton(self.r_add)
        self.name = QLineEdit(spec.title.strip() or tr("Il mio materiale"))
        self.name.setPlaceholderText(tr("Nome (es. Tiglio 3 mm, tavola del negozio)"))
        self.pick = QComboBox()
        for c in self.curves:
            self.pick.addItem(swatch_icon(c), tr("{0} · {1} foto", c.name, c.photos), c.uid)
        f = QFormLayout()
        f.addRow(self.r_new, self.name)
        f.addRow(self.r_add, self.pick)
        v.addLayout(f)
        title = spec.title.strip().lower()
        same = next((i for i, c in enumerate(self.curves) if title and c.name.strip().lower() == title), None)
        if same is not None:
            self.pick.setCurrentIndex(same)
            self.r_add.setChecked(True)
        else:
            self.r_new.setChecked(True)
        if not self.curves:
            self.r_add.setEnabled(False)
            self.pick.setEnabled(False)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(css("color:#FFB4A8;"))
        notes = []
        dmax = float(res.dark.max()) if res.dark.size else 0.0
        if dmax < 0.08:
            notes.append(tr("I quadrati sono quasi tutti come il materiale nudo: da questa foto non c'è niente da "
                            "imparare."))
        elif res.uneven > 0.18:
            notes.append(tr("La luce della foto non è uniforme: si può imparare lo stesso, ma la curva sarà meno "
                            "precisa (una foto migliore la correggerà)."))
        self.warn.setText(" ".join(notes))
        self.warn.setVisible(bool(notes))
        v.addWidget(self.warn)
        self.machine_note = QLabel(tr("Imparato con un'altra macchina: con questa i valori possono essere diversi."))
        self.machine_note.setWordWrap(True)
        self.machine_note.setStyleSheet(css("color:#FFB4A8;"))
        v.addWidget(self.machine_note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.b_ok = bb.button(QDialogButtonBox.Ok)
        self.b_ok.setText(tr("Impara"))
        self.b_ok.setEnabled(dmax >= 0.08)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self._learn)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.r_new.toggled.connect(self._sync)
        self.name.textChanged.connect(self._sync)
        self.pick.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        new = self.r_new.isChecked()
        self.name.setEnabled(new)
        self.pick.setEnabled(not new and bool(self.curves))
        other = None if new or not self.curves else self.curves[max(0, self.pick.currentIndex())]
        self.machine_note.setVisible(bool(other is not None and other.machine and self.machine
                                          and other.machine != self.machine))
        ok = float(self.res.dark.max()) >= 0.08 if self.res.dark.size else False
        self.b_ok.setEnabled(ok and (not new or bool(self.name.text().strip())))

    def _learn(self):
        samples, bare = bc.samples_from_result(self.res, self.spec)
        if self.r_add.isChecked() and self.curves:
            c = bc.get(self.pick.currentData()) or self.curves[max(0, self.pick.currentIndex())]
        else:
            c = bc.BurnCurve(self.name.text().strip()[:80], machine=self.machine)
        c.add_photo(samples, bare)
        if not c.ok:
            QMessageBox.warning(self, self.windowTitle(), tr("Da questa foto non riesco a ricavare una curva: rifai il "
                                                            "test con potenze più diverse tra loro."))
            return
        try:
            bc.put(c)
        except OSError as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("Non riesco a salvare: {0}", ex))
            return
        self.curve = c
        self.accept()


def learned_message(c):
    return tr("«{0}» imparato: {1} foto, nero massimo {2:.0f} su 100.\n\nLo trovi in Laser → Materiali imparati: scegli "
              "un tono e applicalo a un livello, correggi i toni delle foto e guarda l'anteprima realistica sul tuo "
              "legno.", c.name, c.photos, c.d_max * 100)


# ===================================================================== finestra principale
class CurvesDialog(QDialog):
    test_requested = Signal()

    def __init__(self, win=None, parent=None):
        super().__init__(parent if parent is not None else win)
        self.win = win
        self.setWindowTitle(tr("Materiali imparati"))
        self.resize(900, 600)
        v = QVBoxLayout(self)
        intro = QLabel(tr("FreeLaserCut impara come risponde il tuo materiale dalle foto dei test: Test materiale con "
                          "«Riferimenti per leggere la foto» → Leggi la foto del test → Impara questo materiale."))
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        v.addWidget(intro)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.b_import = QPushButton(style.icon("import"), tr("Importa…"))
        self.b_export = QPushButton(style.icon("export"), tr("Esporta…"))
        row.addWidget(self.b_import)
        row.addWidget(self.b_export)
        lv.addLayout(row)
        row = QHBoxLayout()
        self.b_rename = QPushButton(tr("Rinomina…"))
        self.b_delete = QPushButton(style.icon("delete"), tr("Elimina"))
        row.addWidget(self.b_rename)
        row.addWidget(self.b_delete)
        lv.addLayout(row)
        self.b_test = QPushButton(style.icon("grid"), tr("Nuovo test materiale…"))
        lv.addWidget(self.b_test)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setBold(True)
        self.title.setFont(f)
        rv.addWidget(self.title)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        rv.addWidget(self.info)
        self.plot = CurvePlot()
        rv.addWidget(self.plot, 1)
        form = QFormLayout()
        self.layer = QComboBox()
        self.layer.setToolTip(tr("Il livello a cui applicare il tono: velocità, interlinea e passate vengono da lì"))
        form.addRow(tr("Livello"), self.layer)
        self.speed = units.SpeedSpin(10.0, 60000.0, 3000.0)
        form.addRow(tr("Velocità"), self.speed)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.005, 5.0)
        self.interval.setDecimals(4)
        self.interval.setSingleStep(0.01)
        self.interval.setValue(0.1)
        self.interval.setSuffix(" mm")
        self.interval.setToolTip(tr("Distanza fra le righe (per le foto: 25,4 / dpi). Con righe più vicine lo stesso "
                                    "tono vuole meno potenza."))
        form.addRow(tr("Interlinea"), self.interval)
        tone_row = QHBoxLayout()
        self.tone = QSlider(Qt.Horizontal)
        self.tone.setRange(5, 100)
        self.tone.setValue(90)
        self.tone.setToolTip(tr("Quanto scuro: 100 = il nero più profondo che il materiale ha dato nelle foto"))
        self.swatch = QLabel()
        self.swatch.setFixedSize(46, 22)
        tone_row.addWidget(self.tone, 1)
        tone_row.addWidget(self.swatch)
        self.tone_name = QLabel(tr("Tono"))
        form.addRow(self.tone_name, tone_row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        form.addRow("", self.result)
        rv.addLayout(form)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.b_apply = QPushButton(style.icon("check"), tr("Applica al livello"))
        brow.addWidget(self.b_apply)
        rv.addLayout(brow)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 620])
        v.addWidget(split, 1)
        self.empty = QLabel(tr("Ancora nessun materiale imparato. Incidi un Test materiale (riempimento) con "
                               "«Riferimenti per leggere la foto», fagli una foto dall'alto, poi «Leggi la foto del "
                               "test» e «Impara questo materiale»."))
        self.empty.setWordWrap(True)
        v.addWidget(self.empty)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(tr("Chiudi"))
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.right = right
        self.b_import.clicked.connect(self.import_curves)
        self.b_export.clicked.connect(self.export_curve)
        self.b_rename.clicked.connect(self.rename)
        self.b_delete.clicked.connect(self.delete)
        self.b_test.clicked.connect(self._test)
        self.b_apply.clicked.connect(self.apply)
        self.layer.currentIndexChanged.connect(self._layer_changed)
        for w in (self.speed, self.interval):
            w.valueChanged.connect(self._update)
        self.tone.valueChanged.connect(self._update)
        self._fill_layers()
        self.refresh()

    # ---------------------------------------------------------------- dati
    def _doc(self):
        ed = getattr(self.win, "editor", None)
        return getattr(ed, "doc", None)

    def _fill_layers(self):
        self.layer.blockSignals(True)
        self.layer.clear()
        doc = self._doc()
        if doc is not None:
            cur = getattr(getattr(self.win, "layers", None), "_current_cs", lambda: None)()
            # le linee di taglio no: il tono di un riempimento o di una foto non dice niente su un taglio
            layers = [cs for cs in doc.used_layers() if cs.index != TOOL_LAYER and cs.mode != "line"]
            if cur is not None and cur not in layers and cur.index != TOOL_LAYER and cur.mode != "line":
                layers.insert(0, cur)
            modes = {"line": tr("Linea"), "fill": tr("Riempimento"), "offset_fill": tr("Riempimento offset"),
                     "image": tr("Immagine")}
            for cs in layers:
                self.layer.addItem(f"{cs.label()} · {modes.get(cs.mode, cs.mode)}", cs.index)
            if cur is not None and self.layer.findData(cur.index) >= 0:
                self.layer.setCurrentIndex(self.layer.findData(cur.index))
        self.layer.blockSignals(False)
        self._layer_changed()

    @staticmethod
    def _layer_interval(cs):
        return 25.4 / max(cs.dpi, 10.0) if cs.mode == "image" else cs.interval

    @staticmethod
    def _passes(cs):
        """Passate che contano per l'energia: il tratteggio incrociato ripassa tutto a +90°."""
        if cs is None:
            return 1
        return cs.passes * (2 if cs.mode in ("fill", "offset_fill") and getattr(cs, "crosshatch", False) else 1)

    def _cs(self):
        doc = self._doc()
        i = self.layer.currentData()
        return doc.layer(i) if doc is not None and i is not None else None

    def _layer_changed(self, *_):
        cs = self._cs()
        if cs is not None:
            for w in (self.speed, self.interval):
                w.blockSignals(True)
            self.speed.setValue(cs.speed)
            self.interval.setValue(self._layer_interval(cs))
            for w in (self.speed, self.interval):
                w.blockSignals(False)
        self._update()

    def refresh(self, select_uid=None):
        cur = self.current()
        uid = select_uid or (cur.uid if cur is not None else None)
        self.curves = bc.load_all()
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.curves:
            it = QListWidgetItem(swatch_icon(c), c.name)
            it.setData(Qt.UserRole, c.uid)
            it.setToolTip(tr("{0} foto · aggiornato il {1}", c.photos, _when(c.updated)))
            self.list.addItem(it)
        self.list.blockSignals(False)
        row = next((i for i, c in enumerate(self.curves) if c.uid == uid), 0)
        has = bool(self.curves)
        self.empty.setVisible(not has)
        for w in (self.right, self.b_export, self.b_rename, self.b_delete):
            w.setEnabled(has)
        if has:
            self.list.setCurrentRow(row)
        self._show()

    def current(self):
        it = self.list.currentItem() if hasattr(self, "list") else None
        if it is None:
            return None
        uid = it.data(Qt.UserRole)
        return next((c for c in getattr(self, "curves", []) if c.uid == uid), None)

    def _show(self, *_):
        c = self.current()
        if c is None:
            self.title.setText("")
            self.info.setText("")
            self.plot.set(curve=False)
            self._update()
            return
        self.title.setText(c.name)
        d = c.describe()
        txt = tr("{0} foto · {1} misure · nero massimo {2:.0f} su 100 · aggiornato il {3}", d["photos"], d["samples"],
                 d["d_max"] * 100, _when(c.updated))
        prof = getattr(self.win, "profile", None)
        if c.machine:
            txt += " · " + html.escape(tr("imparato con {0}", c.machine))
            if prof is not None and getattr(prof, "name", "") and prof.name != c.machine:
                txt += "<br><span style='color:%s'>%s</span>" % (C["warn"], tr(
                    "Imparato con un'altra macchina: con questa i valori possono essere diversi."))
        self.info.setText(txt)
        self.plot.set(curve=c)
        self._update()

    # ---------------------------------------------------------------- calcolo
    def compute(self):
        """Cosa farebbe «Applica»: dict con mode, valori e testo, o None."""
        c, cs = self.current(), self._cs()
        if c is None or not c.ok:
            return None
        speed, iv = self.speed.value(), self.interval.value()
        passes = self._passes(cs)
        image = cs is not None and cs.mode == "image"
        if image:
            sug = c.suggest(speed, iv, passes)
            if sug is None:
                return None
            return dict(mode="image", power_min=sug["start"], power_max=sug["dark"], slow=sug["slow"], speed=speed,
                        passes=passes, interval=iv, outside=sug["outside"])
        d = c.d_max * self.tone.value() / 100.0
        pw = c.power_for(d, speed, iv, passes)
        if pw is None:
            return None
        slow = speed * 100.0 / pw if pw > 100.0 else None
        return dict(mode="vector", power=round(min(max(pw, 0.1), 100.0), 1), dark=d, slow=slow, speed=speed,
                    passes=passes, interval=iv, outside=not c.measured(bc.energy(pw, speed, iv, passes)))

    def _update(self, *_):
        c = self.current()
        cs = self._cs()
        image = cs is not None and cs.mode == "image"
        self.tone.setEnabled(not image)
        self.tone_name.setEnabled(not image)
        self.plot.set(speed=self.speed.value(), interval=self.interval.value(), passes=self._passes(cs))
        r = self.compute()
        self.b_apply.setEnabled(r is not None and cs is not None)
        if r is None:
            self.result.setText(tr("Scegli un livello del disegno per applicare il tono.") if c is not None and cs is None
                                else "")
            self.swatch.setStyleSheet("")
            self.plot.set(marker=None, band=None)
            return
        if r["mode"] == "image":
            self.plot.set(marker=None, band=(r["power_min"], r["power_max"]))
            txt = tr("Per le foto: potenza da <b>{0:g}</b> a <b>{1:g} %</b> a {2}, toni corretti per questo materiale.",
                     r["power_min"], r["power_max"], units.fmt(r["speed"]))
            col = c.color(c.d_max * 0.92)
        else:
            self.plot.set(marker=r["power"], band=None)
            txt = tr("Questo tono: <b>{0:g} %</b> a {1}", r["power"], units.fmt(r["speed"]))
            col = c.color(r["dark"])
        if r["slow"]:
            txt += "<br>" + tr("Al 100 % non ci arriva: serve una velocità di circa {0}.", units.fmt(r["slow"]))
        elif r.get("outside"):
            txt += "<br><small>" + tr("Fuori dai valori provati nei test: è una stima. Un test con questi valori "
                                      "la rende sicura.") + "</small>"
        self.result.setText(txt)
        q = _qcolor(col)
        self.swatch.setStyleSheet(f"background:{q.name()}; border:1px solid rgba(0,0,0,90); border-radius:3px;")

    # ---------------------------------------------------------------- azioni
    def apply(self):
        c, cs, r = self.current(), self._cs(), self.compute()
        if c is None or cs is None or r is None:
            return False
        speed = r["speed"]
        if r["slow"]:
            ans = QMessageBox.question(self, self.windowTitle(), tr(
                "Al 100 % di potenza a {0} il materiale non diventa così scuro. Uso la velocità {1}?",
                units.fmt(speed), units.fmt(r["slow"])))
            if ans != QMessageBox.Yes:
                return False
            speed = round(r["slow"])
            r = dict(r, speed=speed)
            if r["mode"] == "image":
                sug = c.suggest(speed, r["interval"], r["passes"])
                r.update(power_min=sug["start"], power_max=sug["dark"])
            else:
                r["power"] = round(min(c.power_for(r["dark"], speed, r["interval"], r["passes"]) or 100.0, 100.0), 1)

        iv = r["interval"]
        iv_changed = abs(iv - self._layer_interval(cs)) > 1e-4

        def do():
            cs.speed = speed
            if iv_changed:  # l'interlinea della finestra vale anche per il livello, se l'hai cambiata
                if cs.mode == "image":
                    cs.dpi = round(25.4 / iv, 1)
                else:
                    cs.interval = round(iv, 4)
            if r["mode"] == "image":
                cs.power_min, cs.power_max = r["power_min"], r["power_max"]
                cs.burn_curve = c.uid
            else:
                cs.power_max = r["power"]
        ed = getattr(self.win, "editor", None)
        if ed is not None:
            ed.run(tr("Materiale imparato: {0}", c.name), do)
        else:
            do()
        sb = getattr(self.win, "statusBar", None)
        if callable(sb):
            if r["mode"] == "image":
                msg = tr("{0}: foto da {1:g} a {2:g} % a {3}, toni corretti per «{4}»", cs.label(), r["power_min"],
                         r["power_max"], units.fmt(speed), c.name)
                if cs.dither != "grayscale":
                    msg += " — " + tr("la correzione dei toni vale con il metodo Scala di grigi")
            else:
                msg = tr("{0}: {1:g} % a {2} («{3}»)", cs.label(), r["power"], units.fmt(speed), c.name)
            sb().showMessage(msg, 10000)
        self._layer_changed()
        return True

    def rename(self):
        c = self.current()
        if c is None:
            return
        name, ok = QInputDialog.getText(self, tr("Rinomina"), tr("Nome del materiale"), QLineEdit.Normal, c.name)
        name = (name or "").strip()[:80]
        if ok and name:
            c.name = name
            if self._save(bc.put, c):
                self.refresh(c.uid)

    def delete(self):
        c = self.current()
        if c is None:
            return
        ans = QMessageBox.question(self, tr("Elimina"), tr("Eliminare «{0}» e tutto quello che FreeLaserCut ha imparato "
                                                          "da {1} foto?", c.name, c.photos))
        if ans == QMessageBox.Yes and self._save(bc.remove, c.uid):
            self.refresh()

    def export_curve(self, path=None):
        c = self.current()
        if c is None:
            return None
        if not path:
            safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in c.name).strip() or "materiale"
            if safe.split(" ")[0].upper() in ("CON", "PRN", "AUX", "NUL") or \
                    re.fullmatch(r"(COM|LPT)\d", safe.split(" ")[0].upper()):
                safe = "materiale " + safe
            path, _ = QFileDialog.getSaveFileName(self, tr("Esporta il materiale imparato"), f"{safe}.json",
                                                  tr("Materiale imparato (*.json)"))
        if not path:
            return None
        try:
            bc.export_file(c, path)
        except OSError as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("Non riesco a salvare: {0}", ex))
            return None
        return path

    def import_curves(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Importa un materiale imparato"), "",
                                                  tr("Materiale imparato (*.json)"))
        if not path:
            return []
        try:
            got = bc.import_file(path)
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("Questo file non contiene materiali imparati: {0}", ex))
            return []
        for c in got:
            if not self._save(bc.put, c):
                return []
        if got:
            self.refresh(got[0].uid)
        else:
            QMessageBox.information(self, self.windowTitle(), tr("Nel file non c'è nessun materiale utilizzabile."))
        return got

    def _save(self, fn, arg):
        try:
            fn(arg)
            return True
        except OSError as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("Non riesco a salvare: {0}", ex))
            return False

    def _test(self):
        self.test_requested.emit()
        self.accept()
