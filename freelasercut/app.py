# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Finestra principale di FreeLaserCut (F0: connessione, macchina, controllo, console)."""
import html
import os
import sys
import time

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__, gcode_preview
from .grbl import SIM_PORT, GrblController, list_serial_ports
from .grbl_codes import KEY_SETTINGS, SETTINGS, STATE_COLORS, VENDOR_SETTINGS
from .profile import MachineProfile
from .theme import C, QSS
from .workspace import BedView
from freelasercut.i18n import tr  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
STATE_IT = {
    "Idle": tr("Pronta"), "Run": tr("In lavoro"), "Jog": "Jog", "Hold": tr("In pausa"), "Door": tr("Porta aperta"),
    "Home": tr("Homing"), "Alarm": tr("Allarme"), "Check": tr("Verifica"), "Sleep": tr("Riposo"), "Disconnesso": tr("Disconnessa"),
}


def card(title=None):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(10)
    if title:
        t = QLabel(title)
        t.setObjectName("h2")
        lay.addWidget(t)
    return f, lay


def muted(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


# =============================================================== pannello Controllo
class ControlPanel(QWidget):
    def __init__(self, ctl: GrblController, settings: QSettings):
        super().__init__()
        self.ctl = ctl
        self.qs = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        # --- jog
        jog_card, jl = card(tr("Movimento"))
        grid = QGridLayout()
        grid.setSpacing(6)
        arrows = [("↖", -1, 1), ("▲", 0, 1), ("↗", 1, 1), ("◀", -1, 0), None, ("▶", 1, 0),
                  ("↙", -1, -1), ("▼", 0, -1), ("↘", 1, -1)]
        self.jog_buttons = []
        for i, a in enumerate(arrows):
            r, c = divmod(i, 3)
            if a is None:
                b = QToolButton()
                b.setText("0,0")
                b.setObjectName("jogcenter")
                b.setToolTip(tr("Vai all'origine di lavoro (X0 Y0)"))
                b.clicked.connect(lambda: self.ctl.go_to_origin(self.feed.value()))
            else:
                sym, dx, dy = a
                b = QToolButton()
                b.setText(sym)
                b.setObjectName("jog")
                b.setAutoRepeat(False)
                b.clicked.connect(lambda _=False, dx=dx, dy=dy: self.jog(dx, dy))
            grid.addWidget(b, r, c)
            self.jog_buttons.append(b)
        row = QHBoxLayout()
        row.addLayout(grid)
        row.addStretch(1)
        jl.addLayout(row)

        jl.addWidget(muted(tr("Passo (mm)")))
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        saved = float(self.qs.value("jog_step", 10))
        for v in (0.1, 1, 10, 50, 100):
            b = QToolButton()
            b.setObjectName("seg")
            b.setText(f"{v:g}")
            b.setCheckable(True)
            b.setChecked(abs(v - saved) < 1e-6)
            b.setProperty("step", v)
            self.step_group.addButton(b)
            seg.addWidget(b)
        if self.step_group.checkedButton() is None:
            self.step_group.buttons()[2].setChecked(True)
        self.step_group.buttonClicked.connect(lambda b: self.qs.setValue("jog_step", b.property("step")))
        seg.addStretch(1)
        jl.addLayout(seg)

        fr = QHBoxLayout()
        fr.addWidget(muted(tr("Velocità jog")))
        self.feed = QSpinBox()
        self.feed.setRange(100, 36000)
        self.feed.setSingleStep(500)
        self.feed.setSuffix(tr(" mm/min"))
        self.feed.setValue(int(self.qs.value("jog_feed", 3000)))
        self.feed.valueChanged.connect(lambda v: self.qs.setValue("jog_feed", v))
        fr.addWidget(self.feed)
        fr.addStretch(1)
        jl.addLayout(fr)
        lay.addWidget(jog_card)

        # --- macchina
        mc, ml = card(tr("Macchina"))
        g = QGridLayout()
        g.setSpacing(6)
        self.btn_home = QPushButton(tr("⌂  Homing"))
        self.btn_home.setToolTip(tr("Ciclo di homing ($H): la testa va ai finecorsa"))
        self.btn_home.clicked.connect(self.ctl.home)
        self.btn_unlock = QPushButton(tr("⊘  Sblocca"))
        self.btn_unlock.setToolTip(tr("Sblocca dopo un allarme ($X)"))
        self.btn_unlock.clicked.connect(self.ctl.unlock)
        self.btn_origin = QPushButton(tr("⌖  Origine qui"))
        self.btn_origin.setToolTip(tr("Imposta la posizione attuale come origine di lavoro X0 Y0"))
        self.btn_origin.clicked.connect(self.ctl.set_work_origin)
        self.btn_air = QPushButton(tr("≋  Aria"))
        self.btn_air.setCheckable(True)
        self.btn_air.setToolTip(tr("Air assist acceso/spento (M8/M9)"))
        self.btn_air.toggled.connect(self.ctl.air)
        self.btn_reset = QPushButton(tr("⟲  Reset"))
        self.btn_reset.setToolTip(tr("Reset software GRBL (Ctrl-X): ferma tutto e spegne il laser"))
        self.btn_reset.clicked.connect(self.ctl.soft_reset)
        for i, b in enumerate((self.btn_home, self.btn_unlock, self.btn_origin, self.btn_air)):
            g.addWidget(b, i // 2, i % 2)
        g.addWidget(self.btn_reset, 2, 0, 1, 2)
        ml.addLayout(g)
        lay.addWidget(mc)

        # --- lavoro
        jc, jbl = card(tr("Lavoro G-code"))
        jbl.addWidget(muted(tr("Puoi già inviare un file .gcode/.nc preparato con un altro programma. "
                            "La preparazione dei lavori dentro FreeLaserCut arriva con la fase F1.")))
        fl = QHBoxLayout()
        self.btn_open = QPushButton(tr("Apri file…"))
        self.btn_open.clicked.connect(self.open_file)
        self.file_label = muted(tr("Nessun file"))
        fl.addWidget(self.btn_open)
        fl.addWidget(self.file_label, 1)
        jbl.addLayout(fl)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.hide()
        jbl.addWidget(self.summary)
        self.btn_frame = QPushButton(tr("⬚  Contorno"))
        self.btn_frame.setToolTip(tr("La testa percorre il perimetro del lavoro a laser spento: verifica il posizionamento"))
        self.btn_frame.clicked.connect(self.frame_job)
        jbl.addWidget(self.btn_frame)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat(tr("%p%"))
        jbl.addWidget(self.progress)
        self.eta = muted("")
        jbl.addWidget(self.eta)
        bl = QHBoxLayout()
        self.btn_start = QPushButton(tr("▶  Avvia"))
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start_job)
        self.btn_pause = QPushButton(tr("⏸  Pausa"))
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.pause_job)
        self.btn_stop = QPushButton(tr("■  Stop"))
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self.ctl.stop_job)
        for b in (self.btn_start, self.btn_pause, self.btn_stop):
            bl.addWidget(b)
        jbl.addLayout(bl)
        lay.addWidget(jc)
        lay.addStretch(1)

        self.job_lines = []
        self.job_name = ""
        self.preview = None
        self._job_t0 = 0.0
        ctl.job_progress.connect(self.on_progress)
        ctl.job_finished.connect(self.on_finished)
        self.set_connected(False)

    def step(self):
        b = self.step_group.checkedButton()
        return float(b.property("step")) if b else 10.0

    def jog(self, dx, dy):
        s = self.step()
        self.ctl.jog(dx * s, dy * s, self.feed.value())

    def set_connected(self, ok):
        for w in self.jog_buttons + [self.btn_home, self.btn_unlock, self.btn_origin, self.btn_air, self.btn_reset]:
            w.setEnabled(ok)
        self.update_job_buttons(ok)

    def update_job_buttons(self, ok=None):
        ok = self.ctl.connected if ok is None else ok
        active = self.ctl.job_active
        self.btn_start.setEnabled(ok and bool(self.job_lines) and not active)
        self.btn_pause.setEnabled(ok and active)
        self.btn_stop.setEnabled(ok and active)
        self.btn_open.setEnabled(not active)
        has_box = self.preview is not None and self.preview.has_bounds
        self.btn_frame.setEnabled(ok and has_box and not active)

    def open_file(self):
        start = self.qs.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, tr("Apri G-code"), start,
                                              tr("G-code (*.gcode *.nc *.gc *.ngc *.txt);;Tutti i file (*)"))
        if not path:
            return
        self.qs.setValue("last_dir", os.path.dirname(path))
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        self.load_job(os.path.basename(path), lines)

    def load_job(self, name, lines):
        self.job_lines = lines
        self.job_name = name
        n = sum(1 for l in lines if l.split(";")[0].strip())
        self.file_label.setText(tr("{0}  ·  {1} righe", name, n))
        self.progress.setValue(0)
        self.eta.setText("")
        win = _main(self)
        self.preview = gcode_preview.parse(lines, profile=win.profile)
        win.bed.set_preview(self.preview, win.work_origin_on_bed())
        self.refresh_summary()
        self.update_job_buttons()

    def refresh_summary(self):
        pv = self.preview
        if pv is None:
            self.summary.hide()
            return
        if not pv.has_bounds:
            self.summary.setText(tr("Il file non contiene tratti con laser acceso."))
            self.summary.setStyleSheet(f"color:{C['warn']};")
            self.summary.show()
            return
        prof = _main(self).profile
        ox, oy = _main(self).work_origin_on_bed()
        x0, y0, x1, y1 = pv.min_x + ox, pv.min_y + oy, pv.max_x + ox, pv.max_y + oy
        inside = x0 >= -0.01 and y0 >= -0.01 and x1 <= prof.bed_x + 0.01 and y1 <= prof.bed_y + 0.01
        pw = pv.max_power / max(prof.s_max, 1) * 100
        text = (tr("Ingombro <b>{0:.1f} × {1:.1f} mm</b>, da X{2:.1f} Y{3:.1f}<br>Tempo stimato <b>~{4}</b>  ·  potenza max {5:.0f}%  ·  incisione {6:.2f} m", pv.width, pv.height, pv.min_x, pv.min_y, gcode_preview.fmt_time(pv.seconds), pw, pv.cut_len / 1000))
        if not inside:
            text += tr("<br><span style='color:{0}; font-weight:600'>⚠ Il lavoro esce dall'area di lavoro: sposta l'origine o il disegno</span>", C['danger'])
        if pv.decimated:
            text += f"<br><span style='color:{C['muted']}'>Anteprima semplificata (file molto grande)</span>"
        self.summary.setStyleSheet("")
        self.summary.setText(text)
        self.summary.show()

    def frame_job(self):
        pv = self.preview
        if pv is None or not pv.has_bounds:
            return
        self.ctl.frame(pv.min_x, pv.min_y, pv.max_x, pv.max_y, max(self.feed.value(), 3000))

    def start_job(self):
        box = QMessageBox(self)
        box.setWindowTitle(tr("Avvio lavoro"))
        box.setIcon(QMessageBox.Warning)
        box.setText(tr("<b>Stai per avviare «{0}»</b>", html.escape(self.job_name)))
        box.setInformativeText(
            tr("Prima di partire:\n"
            "•  occhiali protettivi per 450 nm indossati da chi è vicino\n"
            "•  materiale fissato e messo a fuoco (lente 50 mm)\n"
            "•  air assist e aspirazione fumi attivi\n"
            "•  non lasciare la macchina incustodita\n\nAvviare?")
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText(tr("Avvia"))
        box.button(QMessageBox.Cancel).setText(tr("Annulla"))
        if box.exec() != QMessageBox.Yes:
            return
        self._job_t0 = time.time()
        _main(self).bed.clear_trail()
        self.ctl.stream_job(self.job_lines)
        self.update_job_buttons()

    def pause_job(self, paused):
        if paused:
            self.ctl.feed_hold()
            self.btn_pause.setText(tr("▶  Riprendi"))
        else:
            self.ctl.resume()
            self.btn_pause.setText(tr("⏸  Pausa"))

    def on_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        if done and self._job_t0:
            el = time.time() - self._job_t0
            rest = el / done * (total - done)
            self.eta.setText(tr("{0}/{1} righe  ·  trascorso {2}  ·  restante ~{3}", done, total, _hms(el), _hms(rest)))
        self.update_job_buttons()

    def on_finished(self, ok, msg):
        self.eta.setText(msg)
        self.btn_pause.blockSignals(True)
        self.btn_pause.setChecked(False)
        self.btn_pause.setText(tr("⏸  Pausa"))
        self.btn_pause.blockSignals(False)
        self.update_job_buttons()


def _hms(sec):
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# =============================================================== pannello Macchina
class MachinePanel(QWidget):
    def __init__(self, ctl: GrblController, profile: MachineProfile, on_profile):
        super().__init__()
        self.ctl = ctl
        self.profile = profile
        self.on_profile = on_profile
        self.settings = {}
        self.info = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        pc, pl = card(tr("Profilo macchina"))
        self.profile_title = QLabel()
        self.profile_title.setObjectName("h2")
        pl.addWidget(self.profile_title)
        self.profile_sub = muted("")
        pl.addWidget(self.profile_sub)
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(6)
        pl.addLayout(self.checks_box)
        bl = QHBoxLayout()
        self.btn_read = QPushButton(tr("Leggi dalla macchina"))
        self.btn_read.setObjectName("primary")
        self.btn_read.clicked.connect(self.read_machine)
        self.btn_save = QPushButton(tr("Salva profilo"))
        self.btn_save.clicked.connect(self.save_profile)
        self.btn_copy = QPushButton(tr("Copia report"))
        self.btn_copy.setToolTip(tr("Copia $I e $$ negli appunti, da incollare a Claude"))
        self.btn_copy.clicked.connect(self.copy_report)
        for b in (self.btn_read, self.btn_save, self.btn_copy):
            bl.addWidget(b)
        pl.addLayout(bl)
        lay.addWidget(pc)

        tc, tl = card("Impostazioni GRBL ($$)")
        tl.addWidget(muted(tr("In evidenza i parametri che contano per il laser. Doppio clic su un valore per modificarlo.")))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["$", tr("Valore"), tr("Descrizione")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemChanged.connect(self.on_item_changed)
        tl.addWidget(self.table, 1)
        lay.addWidget(tc, 1)

        ctl.settings_ready.connect(self.on_settings)
        ctl.info_ready.connect(self.on_info)
        self.refresh_profile()
        self.set_connected(False)

    def set_connected(self, ok):
        self.btn_read.setEnabled(ok)
        self.table.setEnabled(ok)

    def read_machine(self):
        self.ctl.request_info()
        self.ctl.request_settings()

    def on_info(self, lines):
        self.info = lines

    def on_settings(self, data):
        self.settings = data
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for n in sorted(data):
            r = self.table.rowCount()
            self.table.insertRow(r)
            desc, unit = SETTINGS.get(n, ("", ""))
            key = n in KEY_SETTINGS
            it_n = QTableWidgetItem(f"${n}")
            it_n.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_v = QTableWidgetItem(data[n])
            it_v.setData(Qt.UserRole, n)
            if n in VENDOR_SETTINGS:
                it_v.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)  # sola lettura
            it_d = QTableWidgetItem(f"{desc}  ({unit})" if unit else desc)
            it_d.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if key:
                f = QFont()
                f.setBold(True)
                for it in (it_n, it_v, it_d):
                    it.setFont(f)
                it_n.setForeground(Qt.white)
                it_v.setForeground(Qt.white)
            else:
                for it in (it_n, it_d):
                    it.setForeground(Qt.gray)
            self.table.setItem(r, 0, it_n)
            self.table.setItem(r, 1, it_v)
            self.table.setItem(r, 2, it_d)
        self.table.blockSignals(False)
        self.profile = MachineProfile.from_machine(data, self.info, base=_main(self).profile)
        self.refresh_profile()
        self.on_profile(self.profile)

    def on_item_changed(self, item):
        n = item.data(Qt.UserRole)
        if n is None:
            return
        new = item.text().strip()
        old = self.settings.get(n, "")
        if new == old:
            return
        desc = SETTINGS.get(n, ("parametro", ""))[0]
        ans = QMessageBox.question(self, tr("Modifica impostazione"),
                                   tr("Scrivere ${0} = {1} sulla macchina?\n({2}, valore attuale {3})", n, new, desc, old))
        if ans == QMessageBox.Yes:
            self.ctl.write_setting(n, new)
            QTimer.singleShot(400, self.ctl.request_settings)
        else:
            self.table.blockSignals(True)
            item.setText(old)
            self.table.blockSignals(False)

    def refresh_profile(self):
        p = self.profile
        self.profile_title.setText(p.name)
        fw = f"\nFirmware: {p.firmware_label()}" if p.firmware else ""
        self.profile_sub.setText(
            tr("{0:g}×{1:g} mm  ·  S0–S{2:g}  ·  spot {3}×{4} mm  ·  {5}\nFonte: {6}{7}", p.bed_x, p.bed_y, p.s_max, p.spot_x_mm, p.spot_y_mm, p.optical_power, p.source, fw)
        )
        while self.checks_box.count():
            w = self.checks_box.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        icons = {"ok": ("✓", C["success"]), "info": ("i", C["accent_hi"]), "warn": ("!", C["warn"])}
        for level, msg, fix in p.checks():
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            sym, col = icons[level]
            badge = QLabel(sym)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(20, 20)
            badge.setStyleSheet(f"background:{col}; color:white; border-radius:10px; font-weight:700;")
            rl.addWidget(badge, 0, Qt.AlignTop)
            t = QLabel(msg)
            t.setWordWrap(True)
            rl.addWidget(t, 1)
            if fix and self.ctl.connected:
                b = QPushButton(tr("Imposta ${0}={1}", fix[0], fix[1]))
                b.clicked.connect(lambda _=False, f=fix: (self.ctl.write_setting(*f),
                                                          QTimer.singleShot(400, self.ctl.request_settings)))
                rl.addWidget(b)
            self.checks_box.addWidget(row)

    def save_profile(self):
        path = self.profile.save()
        QMessageBox.information(self, tr("Profilo salvato"), tr("Profilo «{0}» salvato in:\n{1}", self.profile.name, path))

    def copy_report(self):
        lines = [f"FreeLaserCut {__version__} — report macchina", f"Porta: {self.ctl.port or '-'}", ""]
        lines += self.info or [tr("($I non ancora letto)")]
        lines.append("")
        lines += [f"${n}={v}" for n, v in sorted(self.settings.items())] or [tr("($$ non ancora letto)")]
        QGuiApplication.clipboard().setText("\n".join(lines))
        _main(self).statusBar().showMessage(tr("Report copiato negli appunti"), 4000)


# =============================================================== pannello Console
class ConsolePanel(QWidget):
    def __init__(self, ctl: GrblController):
        super().__init__()
        self.ctl = ctl
        self.history = []
        self.hidx = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(5)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        lay.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("Comando GRBL o G-code (es. $$, $I, G0 X10 Y10)  ·  ↑↓ cronologia"))
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)
        self.btn = QPushButton(tr("Invia"))
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        quick = QHBoxLayout()
        for label, cmd in (("$$", "$$"), ("$I", "$I"), ("$G", "$G"), ("$#", "$#"), (tr("Pulisci"), None)):
            b = QToolButton()
            b.setObjectName("seg")
            b.setText(label)
            if cmd:
                b.clicked.connect(lambda _=False, c=cmd: self.ctl.send_line(c))
            else:
                b.clicked.connect(self.log.clear)
            quick.addWidget(b)
        quick.addStretch(1)
        lay.addLayout(quick)
        ctl.line_sent.connect(lambda l: self.add(l, "sent"))
        ctl.line_received.connect(self.on_received)
        ctl.error_raised.connect(lambda c, t, l: self.add(f"error:{c} — {t}" + (f"  [{l}]" if l else ""), "err"))
        ctl.alarm_raised.connect(lambda c, t: self.add(f"ALLARME {c} — {t}", "err"))
        ctl.connection_changed.connect(lambda ok, m: self.add(m, "sys"))
        ctl.job_finished.connect(lambda ok, m: self.add(m, "sys"))
        self.set_connected(False)

    def on_received(self, line):
        if line.startswith("error") or line.startswith("ALARM"):
            return  # gestiti con descrizione
        self.add(line, "recv")

    def add(self, text, kind):
        colors = {"sent": C["accent_hi"], "recv": "#B9C4DC", "err": C["danger"], "sys": C["warn"]}
        prefix = {"sent": "›", "recv": " ", "err": "✕", "sys": "•"}[kind]
        t = time.strftime("%H:%M:%S")
        self.log.appendHtml(
            f'<span style="color:#4E5C7A">{t}</span> <span style="color:{colors[kind]}">{prefix} {html.escape(text)}</span>'
        )

    def send(self):
        cmd = self.input.text().strip()
        if not cmd:
            return
        self.history.append(cmd)
        self.hidx = len(self.history)
        self.ctl.send_line(cmd)
        self.input.clear()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress and self.history:
            if event.key() == Qt.Key_Up:
                self.hidx = max(0, self.hidx - 1)
                self.input.setText(self.history[self.hidx])
                return True
            if event.key() == Qt.Key_Down:
                self.hidx = min(len(self.history), self.hidx + 1)
                self.input.setText(self.history[self.hidx] if self.hidx < len(self.history) else "")
                return True
        return super().eventFilter(obj, event)

    def set_connected(self, ok):
        self.input.setEnabled(ok)
        self.btn.setEnabled(ok)


# =============================================================== finestra
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from .profile import migrate_qsettings

        self.qs = migrate_qsettings()
        self.ctl = GrblController()
        self.profile = MachineProfile.load_default()
        self.setWindowTitle(tr("FreeLaserCut"))
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "logo.svg")))
        self.resize(1440, 900)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build_topbar())
        self.alarm_bar = self._build_alarm_bar()
        v.addWidget(self.alarm_bar)

        split = QSplitter(Qt.Horizontal)
        self.bed = BedView(self.profile.bed_x, self.profile.bed_y)
        split.addWidget(self.bed)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(400)
        self.control = ControlPanel(self.ctl, self.qs)
        self.machine = MachinePanel(self.ctl, self.profile, self.on_profile)
        self.console = ConsolePanel(self.ctl)
        self.tabs.addTab(self.control, tr("Controllo"))
        self.tabs.addTab(self.machine, tr("Macchina"))
        from .camera_panel import CameraPanel
        self.camera = CameraPanel(self.ctl, self)
        self.tabs.addTab(self.camera, tr("Camera"))
        self.tabs.addTab(self.console, tr("Console"))
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 1)
        split.setSizes([1000, 440])
        v.addWidget(split, 1)
        self._build_statusbar()

        self.bed.step_provider = self.control.step
        self.bed.jog_requested.connect(lambda dx, dy: self.ctl.jog(dx, dy, self.control.feed.value()))
        self.bed.goto_requested.connect(self.goto)
        self.ctl.connection_changed.connect(self.on_connection)
        self.ctl.status_changed.connect(self.on_status)
        self.ctl.alarm_raised.connect(self.on_alarm)
        self.ctl.homed_changed.connect(self.on_homed)
        self.ctl.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.ctl.error_raised.connect(lambda c, t, l: self.statusBar().showMessage(tr("Errore {0}: {1}", c, t), 6000))
        self.refresh_ports()
        self.on_connection(False, "")

    # ---- costruzione
    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(62)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(10)
        logo = QSvgWidget(os.path.join(ASSETS, "logo.svg"))
        logo.setFixedSize(38, 38)
        h.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        brand = QLabel(tr("FreeLaserCut"))
        brand.setObjectName("brand")
        tag = QLabel(tr("Laser studio · v{0}", __version__))
        tag.setObjectName("tagline")
        tv.addWidget(brand)
        tv.addWidget(tag)
        h.addLayout(tv)
        h.addSpacing(24)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(300)
        h.addWidget(self.port_combo)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("⟳")
        self.btn_refresh.setToolTip(tr("Aggiorna l'elenco delle porte"))
        self.btn_refresh.clicked.connect(self.refresh_ports)
        h.addWidget(self.btn_refresh)
        self.btn_connect = QPushButton(tr("Connetti"))
        self.btn_connect.setObjectName("primary")
        self.btn_connect.setMinimumWidth(120)
        self.btn_connect.clicked.connect(self.toggle_connection)
        h.addWidget(self.btn_connect)
        h.addSpacing(8)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.setFixedHeight(26)
        self.pill.setAlignment(Qt.AlignCenter)
        self.pill.setMinimumWidth(96)
        h.addWidget(self.pill, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self.top_profile = QLabel()
        self.top_profile.setObjectName("muted")
        h.addWidget(self.top_profile)
        return bar

    def _build_alarm_bar(self):
        f = QFrame()
        f.setObjectName("alarm")
        self._banner_frame = f
        self._banner_kind = None
        self._alarm_dismissed = False
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 8, 14, 8)
        self.alarm_text = QLabel()
        self.alarm_text.setWordWrap(True)
        self.alarm_text.setStyleSheet("color:#FFD9DA; font-weight:600;")
        h.addWidget(self.alarm_text, 1)
        b1 = QPushButton(tr("Sblocca ($X)"))
        b1.clicked.connect(lambda: (self.ctl.unlock(), self.alarm_bar.hide()))
        b2 = QPushButton(tr("Homing ($H)"))
        b2.clicked.connect(lambda: (self.ctl.home(), self.alarm_bar.hide()))
        bx = QToolButton()
        bx.setText("✕")
        bx.clicked.connect(self._dismiss_banner)
        for b in (b1, b2, bx):
            h.addWidget(b)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 8, 12, 0)
        wl.addWidget(f)
        wrap.hide()
        return wrap

    def _dismiss_banner(self):
        if self._banner_kind == "alarm":
            self._alarm_dismissed = True
        self.alarm_bar.hide()

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_pos = QLabel("X —   Y —")
        self.lbl_pos.setObjectName("coord")
        self.lbl_mpos = QLabel("")
        self.lbl_mpos.setObjectName("muted")
        self.lbl_fs = QLabel("")
        self.lbl_fs.setObjectName("muted")
        for w in (self.lbl_fs, self.lbl_mpos, self.lbl_pos):
            sb.addPermanentWidget(w)
            sb.addPermanentWidget(QLabel("   "))

    # ---- connessione
    def refresh_ports(self):
        last = self.qs.value("port", "")
        self.port_combo.clear()
        best = None
        for dev, label, likely in list_serial_ports():
            self.port_combo.addItem(("★  " if likely else "") + label, dev)
            if dev == last:
                best = self.port_combo.count() - 1
            elif likely and best is None:
                best = self.port_combo.count() - 1
        if best is not None:
            self.port_combo.setCurrentIndex(best)

    def toggle_connection(self):
        if self.ctl.connected:
            if self.ctl.job_active:
                if QMessageBox.question(self, tr("Lavoro in corso"), tr("C'è un lavoro in corso. Fermarlo e disconnettere?")) \
                        != QMessageBox.Yes:
                    return
                self.ctl.stop_job()
            self.ctl.disconnect_port()
            return
        port = self.port_combo.currentData()
        if not port:
            return
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText(tr("Connessione…"))
        QApplication.processEvents()
        if self.ctl.connect_port(port, self.profile.baud):
            self.qs.setValue("port", port)
        self.btn_connect.setEnabled(True)

    def on_connection(self, ok, msg):
        self.btn_connect.setText(tr("Disconnetti") if ok else tr("Connetti"))
        self.btn_connect.setObjectName("danger" if ok else "primary")
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self.port_combo.setEnabled(not ok)
        self.btn_refresh.setEnabled(not ok)
        self.control.set_connected(ok)
        self.machine.set_connected(ok)
        self.machine.refresh_profile()
        self.console.set_connected(ok)
        if hasattr(self, "camera"):
            self.camera.update_state()
        if not ok:
            self.set_pill("Disconnesso")
            self.bed.hide_head()
            self.lbl_pos.setText("X —   Y —")
            self.lbl_mpos.setText("")
            self.lbl_fs.setText("")
            if msg and msg.startswith(("Impossibile", "Connessione persa", "Errore")):
                QMessageBox.warning(self, tr("Connessione"), msg + tr("\n\nControlla che il cavo USB sia collegato, "
                                    "la macchina accesa e che nessun altro programma (LightBurn, LaserGRBL) usi la porta."))
        else:
            self.set_pill("Idle")
            self.statusBar().showMessage(msg, 4000)
            QTimer.singleShot(2500, self._suggest_homing)
        self.on_profile(self.profile)

    def _suggest_homing(self):
        if self.ctl.connected and not self.ctl.homed and not self.alarm_bar.isVisible():
            self.show_banner(tr("Fai l'homing: così testa, piano di lavoro e camera parlano le stesse coordinate."), "info")

    def set_pill(self, state):
        color = STATE_COLORS.get(state, "#4E5C7A")
        self.pill.setText(STATE_IT.get(state, state))
        self.pill.setStyleSheet(f"background:{color};")

    def on_status(self, st):
        state = st.get("state", "")
        self.set_pill(state)
        w = st.get("WPos", [0, 0, 0])
        m = st.get("MPos", [0, 0, 0])
        self.lbl_pos.setText(f"X {w[0]:8.2f}   Y {w[1]:8.2f}")
        self.lbl_mpos.setText(tr("macchina {0:.2f}, {1:.2f}", m[0], m[1]))
        pw = st.get("power", 0) / max(self.profile.s_max, 1) * 100
        self.lbl_fs.setText(tr("F {0:.0f} mm/min   ·   potenza {1:.0f}%", st.get('feed', 0), pw))
        bx, by = self.profile.to_bed(m[0], m[1])
        self.bed.set_head(bx, by, state, st.get("power", 0))
        wco = tuple(st.get("WCO", [0, 0, 0])[:2])
        if wco != getattr(self, "_last_wco", None):
            self._last_wco = wco
            self.bed.set_preview_offset(self.work_origin_on_bed())
            self.control.refresh_summary()
        if state == "Alarm" and not self.alarm_bar.isVisible() and not self._alarm_dismissed:
            self.show_banner(tr("⚠  La macchina è bloccata (allarme): fai l'homing oppure sblocca."), "alarm")
        elif state != "Alarm":
            self._alarm_dismissed = False
            if self._banner_kind == "alarm" and self.alarm_bar.isVisible() and state in ("Idle", "Run", "Jog"):
                self.alarm_bar.hide()

    def work_origin_on_bed(self):
        """Dove sta l'origine di lavoro (X0 Y0 del G-code) sul piano disegnato."""
        wx, wy = self.ctl.wco
        return self.profile.to_bed(wx, wy)

    def show_banner(self, text, kind="alarm"):
        self._banner_kind = kind
        if kind == "alarm":
            self._banner_frame.setStyleSheet(f"QFrame#alarm {{ background:#3A1418; border:1px solid {C['danger']}; border-radius:10px; }}")
            self.alarm_text.setStyleSheet("color:#FFD9DA; font-weight:600;")
        else:
            self._banner_frame.setStyleSheet(f"QFrame#alarm {{ background:#10264D; border:1px solid {C['accent']}; border-radius:10px; }}")
            self.alarm_text.setStyleSheet("color:#D6E6FF; font-weight:600;")
        self.alarm_text.setText(text)
        self.alarm_bar.show()

    def on_homed(self, homed, negative):
        if homed:
            changed = self.profile.negative_space != negative
            self.profile.negative_space = negative
            if changed:
                try:
                    self.profile.save()
                except OSError:
                    pass
            self._last_wco = None
            if self._banner_kind == "info":
                self.alarm_bar.hide()
            self.machine.refresh_profile()
            self.statusBar().showMessage(tr("Homing completato: piano e macchina allineati"), 5000)
        self.camera.update_state()

    def on_alarm(self, code, text):
        self.show_banner(f"⚠  Allarme {code}: {text}", "alarm")

    def on_profile(self, p):
        self.profile = p
        self.top_profile.setText(tr("Profilo: {0}  ·  {1}", p.name, p.source))
        if (self.bed.bed_x, self.bed.bed_y) != (p.bed_x, p.bed_y):
            self.bed.set_bed(p.bed_x, p.bed_y)

    def goto(self, x, y):
        if not self.ctl.connected:
            self.statusBar().showMessage(tr("Connetti la macchina per muovere la testa"), 3000)
            return
        if self.ctl.job_active or self.camera.autocam is not None:
            return
        # il piano (e la foto della camera) è in coordinate del piano: le converto in coordinate macchina
        mx, my = self.profile.to_machine(x, y)
        self.ctl.goto_machine(mx, my, max(self.control.feed.value(), 3000))

    def closeEvent(self, event):
        if self.ctl.job_active:
            if QMessageBox.question(self, tr("Lavoro in corso"), tr("C'è un lavoro in corso. Fermarlo e uscire?")) \
                    != QMessageBox.Yes:
                event.ignore()
                return
            self.ctl.stop_job()
        self.camera.shutdown()
        self.ctl.disconnect_port()
        super().closeEvent(event)


def _main(widget):
    """La finestra principale anche se il pannello è staccato (in un pannello fluttuante window() è il pannello)."""
    w = widget.window()
    if hasattr(w, "profile"):
        return w
    for t in QApplication.topLevelWidgets():
        if hasattr(t, "profile") and hasattr(t, "statusBar"):
            return t
    return w


def _hide_splash():
    """Chiude la schermata d'avvio, se c'è ancora: altrimenti potrebbe coprire un messaggio d'errore."""
    from PySide6.QtWidgets import QSplashScreen

    for w in QApplication.topLevelWidgets():
        if isinstance(w, QSplashScreen) and w.isVisible():
            try:
                w.close()
            except RuntimeError:
                pass


def _install_crash_log():
    """Errori imprevisti: scritti in %APPDATA%\\FreeLaserCut\\flc.log e mostrati a schermo."""
    import traceback

    from .profile import config_dir

    log_path = os.path.join(config_dir(), "flc.log")

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        if tb is None:  # errore partito da Qt (senza traccia Python): salvo almeno dove eravamo
            text += "".join(traceback.format_stack(limit=12))
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {__version__}\n{text}")
        except OSError:
            pass
        if QApplication.instance() is not None:
            _hide_splash()
            QMessageBox.critical(None, tr("FreeLaserCut — errore"),
                                 tr("Si è verificato un errore imprevisto:\n\n{0}\n\nDettagli salvati in:\n{1}", exc, log_path))

    sys.excepthook = hook
    # crash "nativi" (Qt che si chiude di colpo, senza eccezione Python): faulthandler scrive comunque
    # nel registro la riga Python in cui è successo, così il problema si può ritrovare
    try:
        import faulthandler

        global _FAULT_FH
        _FAULT_FH = open(os.path.join(config_dir(), "flc_crash.log"), "a", encoding="utf-8")  # noqa: SIM115
        _FAULT_FH.write(f"\n=== avvio {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {__version__}\n")
        _FAULT_FH.flush()
        faulthandler.enable(file=_FAULT_FH, all_threads=True)
    except (OSError, RuntimeError):
        pass


def main():
    _install_crash_log()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:  # icona giusta nella barra delle applicazioni di Windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fringuello79.FreeLaserCut")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("FreeLaserCut")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(os.path.join(ASSETS, "logo.svg")))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
