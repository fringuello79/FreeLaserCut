# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Pannelli Macchina e Console, registro degli errori, sorveglianza dei blocchi e chiusura del programma.

0.19.2: tolta da qui la finestra della versione 0.1 (con il suo pannello di controllo e il suo avvio), che non era
più usata da nessuno: la finestra del programma è ui/main_window.py."""
import html
import os
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__
from .grbl import SIM_PORT, GrblController
from .grbl_codes import KEY_SETTINGS, SETTINGS, TRAVEL_MAX, TRAVEL_MIN, VENDOR_SETTINGS, bad_travel
from .profile import MachineProfile
from .theme import C, tc
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
        # 0.17.4: area di lavoro a mano, anche senza laser collegato (prima solo da «Riconosci la macchina», collegati)
        al = QHBoxLayout()
        al.addWidget(QLabel(tr("Area di lavoro")))
        self.area_x, self.area_y = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.area_x, self.area_y):
            sp.setRange(10, 3000)
            sp.setDecimals(0)
            sp.setSuffix(" mm")
            sp.setMinimumWidth(92)
            sp.setToolTip(tr("Misura vera del piano su cui si muove la testa (X × Y). Con il laser collegato, «Leggi dalla "
                             "macchina» la prende dalla scheda ($130/$131), se è credibile."))
        al.addWidget(self.area_x)
        al.addWidget(QLabel("×"))
        al.addWidget(self.area_y)
        self.btn_area = QPushButton(tr("Usa questa area"))
        self.btn_area.clicked.connect(self.set_area)
        al.addWidget(self.btn_area)
        al.addStretch(1)
        pl.addLayout(al)
        # 0.18.5: comando dell'air assist (richiesta su GitHub): alcune schede lo accendono con M7 invece di M8
        ar = QHBoxLayout()
        ar.addWidget(QLabel(tr("Air assist")))
        self.air_cmd = QComboBox()
        self.air_cmd.addItem(tr("M8 (il più comune)"), "M8")
        self.air_cmd.addItem("M7", "M7")
        self.air_cmd.addItem(tr("Nessun comando"), "")
        self.air_cmd.setToolTip(tr("Il comando che accende l'aria nei lavori, nel test materiale e con il pulsante Aria. "
                                   "Se con M8 la tua pompa non parte, prova M7. «Nessun comando» se l'aria la accendi a "
                                   "mano o resta sempre accesa."))
        self.air_cmd.activated.connect(lambda *_: self.set_air(self.air_cmd.currentData()))
        ar.addWidget(self.air_cmd)
        ar.addStretch(1)
        pl.addLayout(ar)
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
        self.btn_backups = QPushButton(tr("Copie delle impostazioni…"))
        self.btn_backups.setToolTip(tr("Copie automatiche dei parametri della scheda: confronto e ripristino"))
        self.btn_backups.clicked.connect(self.open_backups)
        tl.addWidget(self.btn_backups)
        lay.addWidget(tc, 1)

        ctl.settings_ready.connect(self.on_settings)
        ctl.info_ready.connect(self.on_info)
        self.refresh_profile()
        self.set_connected(False)

    def open_backups(self):
        from PySide6.QtWidgets import QApplication

        for w in QApplication.topLevelWidgets():
            if hasattr(w, "board_backup_dialog"):
                return w.board_backup_dialog()
        return None

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
        if self.ctl.port == SIM_PORT:
            # 0.17.6: i valori finti del simulatore non entrano mai nel profilo della macchina vera (un utente si era
            # ritrovato il profilo del suo laser con area, scheda e accelerazioni del simulatore)
            return
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
        text = tr("Scrivere ${0} = {1} sulla macchina?\n({2}, valore attuale {3})", n, new, desc, old)
        default = QMessageBox.Yes
        if bad_travel({n: new}):  # 0.17.2: area di lavoro non credibile, chiedo di ricontrollare
            text = tr("${0} = {1} non sembra un'area di lavoro credibile (di solito è fra {2:g} e {3:g} mm, con il punto "
                      "per i decimali: per esempio 400.000).", n, new, TRAVEL_MIN, TRAVEL_MAX) + "\n\n" + text
            default = QMessageBox.No
        ans = QMessageBox.question(self, tr("Modifica impostazione"), text, QMessageBox.Yes | QMessageBox.No, default)
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
        for sp, v in ((self.area_x, p.bed_x), (self.area_y, p.bed_y)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        on = p.air_cmds()[0]
        if self.air_cmd.findData(on) < 0:  # profilo importato con un altro comando ammesso (M106)
            self.air_cmd.addItem(on, on)
        self.air_cmd.setCurrentIndex(self.air_cmd.findData(on))
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

    def set_area(self):
        """Area di lavoro scritta a mano: entra nel profilo, che si salva, e il piano si ridisegna."""
        if self.ctl.job_active:
            return
        p = self.profile
        p.bed_x, p.bed_y = float(self.area_x.value()), float(self.area_y.value())
        try:
            p.save()
        except OSError as exc:
            QMessageBox.warning(self, tr("Profilo"), tr("Impossibile salvare il profilo:\n{0}", exc))
        self.refresh_profile()
        self.on_profile(p)
        _main(self).statusBar().showMessage(tr("Area di lavoro {0:g} × {1:g} mm salvata nel profilo «{2}»", p.bed_x,
                                               p.bed_y, p.name), 6000)

    def set_air(self, on):
        """Comando dell'air assist scelto a mano: entra nel profilo, che si salva, e vale da subito."""
        p = self.profile
        on = str(on or "").upper()
        p.air_on, p.air_off = on, ("" if not on else "M107" if on == "M106" else "M9")
        try:
            p.save()
        except OSError as exc:
            QMessageBox.warning(self, tr("Profilo"), tr("Impossibile salvare il profilo:\n{0}", exc))
        self.refresh_profile()
        self.on_profile(p)
        _main(self).statusBar().showMessage(
            tr("Air assist: {0}, salvato nel profilo «{1}»", on or tr("Nessun comando"), p.name), 6000)

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
        colors = {"sent": C["accent_hi"], "recv": tc("#B9C4DC"), "err": C["danger"], "sys": C["warn"]}
        prefix = {"sent": "›", "recv": " ", "err": "✕", "sys": "•"}[kind]
        t = time.strftime("%H:%M:%S")
        self.log.appendHtml(
            f'<span style="color:{tc("#4E5C7A")}">{t}</span> <span style="color:{colors[kind]}">{prefix} {html.escape(text)}</span>'
        )

    def send(self):
        cmd = self.input.text().strip()
        if not cmd:
            return
        from .wifi_setup import has_secret

        if not has_secret(cmd):  # 0.18.17: un comando con la password del Wi-Fi non resta nella memoria della console
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


_FAULT_FH = None  # registro dei crash nativi e dei blocchi (flc_crash.log), aperto da _install_crash_log


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
            from . import startup_guard

            if startup_guard._state["stage"] != "finito":  # 0.18.16: errore prima che la finestra compaia: in
                text = "\n".join(startup_guard.system_lines()) + "\n" + text  # testa i dati di sistema e la fase
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {__version__}\n{text}")
        except OSError:
            pass
        if QApplication.instance() is not None and os.environ.get("FLC_NO_DIALOGS") != "1":
            _hide_splash()
            QMessageBox.critical(None, tr("FreeLaserCut — errore"),
                                 tr("Si è verificato un errore imprevisto:\n\n{0}\n\nDettagli salvati in:\n{1}", exc, log_path)
                                 + "\n\n" + tr("Per farti aiutare: Aiuto → Crea rapporto per l'assistenza."))

    sys.excepthook = hook
    # crash "nativi" (Qt che si chiude di colpo, senza eccezione Python): faulthandler scrive comunque
    # nel registro la riga Python in cui è successo, così il problema si può ritrovare
    try:
        import faulthandler

        from . import startup_guard

        global _FAULT_FH
        # 0.18.16: se la guardia d'avvio l'ha già aperto (e già intestato) in questa cartella, uso quello: lo stesso
        # file non si apre due volte
        _FAULT_FH = startup_guard.fault_file(config_dir())
        if _FAULT_FH is None:
            _FAULT_FH = open(os.path.join(config_dir(), "flc_crash.log"), "a", encoding="utf-8")  # noqa: SIM115
            _FAULT_FH.write(f"\n=== avvio {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {__version__}\n")
            _FAULT_FH.flush()
        faulthandler.enable(file=_FAULT_FH, all_threads=True)
    except (OSError, RuntimeError):
        pass


_HANG = {"beat": 0.0, "dumped": 0, "since": 0.0}
HANG_S = 8.0  # la finestra non risponde da più di così: scrivo nel registro che cosa sta facendo il programma
HANG_MAX = 6  # al massimo tante volte per avvio (il registro entra nel rapporto per l'assistenza)


def start_hang_watch(app):
    """0.18.8: quando il programma «si pianta» non c'è nessun errore da leggere. Un timer nella finestra segna il
    tempo ogni secondo; un filo a parte controlla: se il segno è fermo da più di HANG_S scrive in flc_crash.log che
    cosa stanno facendo tutti i fili in quel momento. Così il rapporto per l'assistenza dice dov'era fermo."""
    import threading

    if _FAULT_FH is None or _HANG.get("timer") is not None:
        return False
    _HANG["beat"] = time.time()
    timer = QTimer(app)
    timer.setInterval(1000)
    timer.timeout.connect(lambda: _HANG.__setitem__("beat", time.time()))
    timer.start()
    _HANG["timer"] = timer

    def watch():
        import faulthandler

        while True:
            time.sleep(1.0)
            fh = _FAULT_FH
            if fh is None or fh.closed:
                return
            late = time.time() - _HANG["beat"]
            try:
                if late > HANG_S and not _HANG["since"] and _HANG["dumped"] < HANG_MAX:
                    _HANG["since"] = _HANG["beat"]
                    _HANG["dumped"] += 1
                    fh.write(f"\n=== blocco {time.strftime('%H:%M:%S')}: la finestra non risponde da {late:.0f} s\n")
                    fh.flush()
                    faulthandler.dump_traceback(file=fh, all_threads=True)
                    fh.flush()
                elif late < 2.0 and _HANG["since"]:
                    fh.write(f"=== ripresa {time.strftime('%H:%M:%S')}: era ferma da "
                             f"{time.time() - _HANG['since']:.0f} s\n")
                    fh.flush()
                    _HANG["since"] = 0.0
            except (OSError, ValueError, RuntimeError):
                return

    threading.Thread(target=watch, daemon=True, name="flc-sorveglia-blocchi").start()
    return True


def finish_exit(code=0, grace=3.0):
    """0.18.9: la finestra è chiusa, il programma deve finire davvero. Aspetta al massimo `grace` secondi i fili
    che ancora lavorano; se qualcuno non finisce lo scrive in flc_crash.log (chi era e che cosa stava facendo) e
    poi chiude comunque il processo. Senza, un filo rimasto appeso lasciava FreeLaserCut aperto senza finestra:
    l'installatore di un aggiornamento trovava «FreeLaserCut è aperto» e bisognava chiuderlo da Gestione attività."""
    import threading

    end = time.time() + max(0.0, grace)
    me = threading.current_thread()
    busy = [t for t in threading.enumerate() if t is not me and not t.daemon and t.is_alive()]
    for t in busy:
        t.join(max(0.0, end - time.time()))
    stuck = [t for t in busy if t.is_alive()]
    fh = _FAULT_FH
    try:
        if stuck and fh is not None and not fh.closed:
            import faulthandler

            fh.write(f"\n=== chiusura {time.strftime('%H:%M:%S')}: dopo {grace:g} s lavoravano ancora: "
                     + ", ".join(t.name for t in stuck) + "\n")
            fh.flush()
            faulthandler.dump_traceback(file=fh, all_threads=True)
        if fh is not None and not fh.closed:
            fh.flush()
    except (OSError, ValueError, RuntimeError):
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    if sys.platform == "win32":  # come nelle prove: os._exit con Qt ancora in piedi su Windows può dare 0xC0000005
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            k32.TerminateProcess(k32.GetCurrentProcess(), int(code) & 0xFFFFFFFF)
        except Exception:  # noqa: BLE001
            pass
    os._exit(int(code) if isinstance(code, int) else 0)
