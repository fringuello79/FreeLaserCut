# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Riconosci la macchina: porte USB con chip e driver, lettura della scheda, profilo adattato in automatico."""
import glob
import os
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import machines
from ..grbl import SIM_PORT
from ..profile import MachineProfile, config_dir
from ..theme import C
from . import style
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402

_LINUX = sys.platform.startswith("linux")


class _Probe(QObject):
    log = Signal(str)
    done = Signal(object)


def saved_profiles():
    """[(nome, percorso)] dei profili salvati."""
    out = []
    for path in sorted(glob.glob(os.path.join(config_dir(), "profiles", "*.json"))):
        try:
            out.append((MachineProfile.load(path).name, path))
        except (OSError, ValueError, TypeError):
            continue
    return out


def use_preset(qs, name):
    """Crea (o riprende) il profilo di un modello del catalogo e lo rende quello attivo al prossimo avvio."""
    p = machines.preset_profile(name)
    path = p.path()
    if os.path.exists(path):
        try:
            p = MachineProfile.load(path)  # già usato: tiene i valori letti dalla macchina
        except (OSError, ValueError, TypeError):
            pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            p.save()
    except OSError:
        return None
    qs.setValue("profile_path", path)
    return p


class MachineWizard(QDialog):
    """Riconoscimento e adattamento il più automatico possibile del laser collegato."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("Riconosci la macchina"))
        self.setMinimumSize(760, 600)
        self.ports = []
        self.result = None
        self.ident = None
        v = QVBoxLayout(self)
        v.setSpacing(6)
        intro = QLabel(tr("FreeLaserCut guarda le porte USB, interroga la scheda e prepara il profilo giusto: area di lavoro, "
                       "scala di potenza, buffer e firmware. Scegli la porta e premi <b>Riconosci</b>."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        # ---- profili salvati
        pr = QHBoxLayout()
        pr.addWidget(QLabel(tr("Profilo attivo")))
        self.prof_combo = QComboBox()
        self.prof_combo.setToolTip(tr("Le macchine già riconosciute: scegline una per usarla subito"))
        pr.addWidget(self.prof_combo, 1)
        b = QPushButton(tr("Usa questo profilo"))
        b.clicked.connect(self._use_saved)
        pr.addWidget(b)
        v.addLayout(pr)
        self._fill_profiles()
        # ---- modelli pronti (anche senza la macchina collegata)
        mr = QHBoxLayout()
        mr.addWidget(QLabel(tr("Oppure il tuo modello")))
        self.model_combo = QComboBox()
        self.model_combo.addItems(machines.catalog_names())
        self.model_combo.setToolTip(tr("Incisori GRBL più diffusi: area di lavoro e velocità di targa. Collegando la macchina "
                                       "i valori veri si rileggono dalla scheda."))
        mr.addWidget(self.model_combo, 1)
        b = QPushButton(tr("Usa questo modello"))
        b.clicked.connect(self._use_model)
        mr.addWidget(b)
        v.addLayout(mr)
        # ---- porte
        v.addWidget(section(tr("Porte USB del computer")))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("Porta"), tr("Chip USB"), "VID:PID",
                                              tr("Descrizione del sistema") if _LINUX else tr("Descrizione di Windows"),
                                              tr("Driver")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        for i in range(5):
            hh.setSectionResizeMode(i, QHeaderView.Stretch if i == 3 else QHeaderView.ResizeToContents)
        self.table.setMaximumHeight(170)
        self.table.itemSelectionChanged.connect(self._port_selected)
        v.addWidget(self.table)
        self.drv_hint = QLabel()
        self.drv_hint.setWordWrap(True)
        self.drv_hint.setObjectName("muted")
        v.addWidget(self.drv_hint)
        br = QHBoxLayout()
        buttons = [(tr("Aggiorna"), "refresh", self.refresh,
                    tr("Cerca di nuovo le porte (dopo aver collegato il cavo o installato un driver)"))]
        if _LINUX:  # 0.18.0: su Linux i driver ci sono già; serve il permesso di aprire la porta
            buttons.append((tr("Permesso della porta USB…"), "settings", self.linux_permission,
                            tr("Come dare al tuo utente il permesso di usare la porta USB del laser (gruppo dialout)")))
        else:
            buttons += [
                (tr("Installa driver dal PC…"), "open", self.install_driver,
                 tr("Scegli sul computer il programma (.exe/.msi) o il file .inf del driver USB e installalo")),
                (tr("Scarica il driver"), "import", self.download_driver, tr("Apre la pagina ufficiale del driver per il chip della porta")),
                (tr("Gestione dispositivi"), "settings", self.device_manager, tr("Apre Gestione dispositivi di Windows")),
            ]
        for text, icon, fn, tip in buttons:
            b = QPushButton(style.icon(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            br.addWidget(b)
        br.addStretch(1)
        self.btn_probe = QPushButton(style.icon("verify", "#FFFFFF"), tr("Riconosci"))
        self.btn_probe.setObjectName("primary")
        self.btn_probe.clicked.connect(self.run_probe)
        br.addWidget(self.btn_probe)
        v.addLayout(br)
        # ---- esito
        v.addWidget(section(tr("Macchina riconosciuta")))
        self.summary = QLabel("—")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        v.addWidget(self.summary)
        f = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Nome del profilo, es. Longer B1 40W"))
        f.addRow(tr("Nome"), self.name)
        bed = QWidget()
        bl = QHBoxLayout(bed)
        bl.setContentsMargins(0, 0, 0, 0)
        self.bed_x = QDoubleSpinBox()
        self.bed_y = QDoubleSpinBox()
        for s in (self.bed_x, self.bed_y):
            s.setRange(10, 3000)
            s.setDecimals(0)
            s.setSuffix(tr(" mm"))
        bl.addWidget(self.bed_x)
        bl.addWidget(QLabel("×"))
        bl.addWidget(self.bed_y)
        bl.addStretch(1)
        f.addRow(tr("Area di lavoro"), bed)
        v.addLayout(f)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        self.log.setStyleSheet(f"font-size:8pt; color:{C['muted']};")
        v.addWidget(self.log, 1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.btn_save = QPushButton(tr("Salva solo il profilo"))
        self.btn_save.clicked.connect(lambda: self.apply(connect=False))
        self.btn_apply = QPushButton(style.icon("connect", "#FFFFFF"), tr("Usa il profilo e connetti"))
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(lambda: self.apply(connect=True))
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.reject)
        for b in (self.btn_save, self.btn_apply, close):
            bb.addWidget(b)
        v.addLayout(bb)
        self._set_result_enabled(False)
        self.refresh()

    # ------------------------------------------------------------------ profili salvati
    def _fill_profiles(self):
        self.prof_combo.clear()
        cur = self.main.profile.path()
        for name, path in saved_profiles():
            self.prof_combo.addItem(name, path)
            if os.path.normcase(path) == os.path.normcase(cur):
                self.prof_combo.setCurrentIndex(self.prof_combo.count() - 1)
        if not self.prof_combo.count():
            self.prof_combo.addItem(tr("{0} (predefinito)", self.main.profile.name), "")

    def _use_saved(self):
        path = self.prof_combo.currentData()
        if not path:
            return
        try:
            p = MachineProfile.load(path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, tr("Profilo"), tr("Impossibile leggere il profilo:\n{0}", exc))
            return
        self.main.set_active_profile(p)
        self.log.appendPlainText(f"Profilo attivo: {p.name}")

    def _use_model(self):
        p = use_preset(self.main.qs, self.model_combo.currentText())
        if p is None:
            QMessageBox.warning(self, tr("Profilo"), tr("Impossibile salvare il profilo."))
            return
        self.main.set_active_profile(p)
        self._fill_profiles()
        self.log.appendPlainText(tr("Profilo attivo: {0} ({1:g} × {2:g} mm)", p.name, p.bed_x, p.bed_y))
        name = self.model_combo.currentText()
        if name in machines.NOTES:
            self.log.appendPlainText(machines.NOTES[name])
        if name in machines.SOURCES:
            self.log.appendPlainText(tr("Valori di targa da: {0}", machines.SOURCES[name]))

    # ------------------------------------------------------------------ porte e driver
    def refresh(self):
        from .. import netport

        self.ports = machines.describe_ports() + [machines.PortInfo(p, tr("Wi-Fi (rete)")) for p in
                                                  netport.saved(getattr(self.main, "qs", None))]
        self.table.setRowCount(0)
        sel = 0
        for i, p in enumerate(self.ports + [machines.PortInfo(SIM_PORT, tr("Simulatore (senza macchina)"))]):
            r = self.table.rowCount()
            self.table.insertRow(r)
            drv = machines.DRIVERS.get(p.driver, ("", ""))[0]
            vals = (("★ " if p.likely else "") + p.device, p.chip or "—", p.vid_pid() or "—", p.description, drv or "—")
            for c, t in enumerate(vals):
                it = QTableWidgetItem(t)
                it.setData(Qt.UserRole, i)
                self.table.setItem(r, c, it)
            if self.main.ctl.connected and p.device == self.main.ctl.port:
                sel = r
        if self.table.rowCount():
            self.table.selectRow(sel)
        if not any(p.likely for p in self.ports) and _LINUX:
            self.drv_hint.setText(tr("Nessuna porta sembra un laser. Accendi la macchina e collega il cavo USB, poi "
                                     "«Aggiorna»: su Linux i driver dei chip USB (CH340, CP210x, FTDI) sono già nel "
                                     "sistema e la porta compare come /dev/ttyUSB0 o /dev/ttyACM0."))
        elif not any(p.likely for p in self.ports):
            self.drv_hint.setText(tr("Nessuna porta sembra un laser. Accendi la macchina e collega il cavo USB; se non "
                                  "compare nulla manca il driver del chip USB: «Scarica il driver» (CH340 è il più "
                                  "comune) o «Installa driver dal PC…» se l'hai già scaricato."))
        else:
            self._port_selected()

    def _port(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        i = self.table.item(r, 0).data(Qt.UserRole)
        return self.ports[i] if i < len(self.ports) else machines.PortInfo(SIM_PORT, tr("Simulatore"))

    def _port_selected(self):
        p = self._port()
        if p is None:
            return
        if p.device == SIM_PORT:
            self.drv_hint.setText(tr("Simulatore: una macchina finta per provare FreeLaserCut senza laser."))
        elif p.device.startswith("tcp://"):
            self.drv_hint.setText(tr("Collegamento via Wi-Fi: non serve nessun driver USB."))
        elif _LINUX and p.device.startswith("/dev/"):
            if os.access(p.device, os.R_OK | os.W_OK):
                self.drv_hint.setText(tr("Chip {0}: su Linux il driver è già nel sistema e il tuo utente può usare "
                                         "questa porta.", p.chip or "USB"))
            else:
                self.drv_hint.setText(tr("Chip {0}: il driver c'è, ma il tuo utente non ha il permesso di usare {1}. "
                                         "Premi «Permesso della porta USB…».", p.chip or "USB", p.device))
        elif p.driver:
            name, url = machines.DRIVERS[p.driver]
            self.drv_hint.setText(tr("Chip {0}: {1}. Se la porta compare qui, il driver è già installato.", p.chip, name))
        else:
            self.drv_hint.setText(tr("Chip USB non riconosciuto: se la porta è del laser, FreeLaserCut la può usare lo stesso."))

    def download_driver(self):
        p = self._port()
        fam = p.driver if p is not None and p.driver else "wch"
        url = machines.DRIVERS[fam][1]
        if not url:
            QMessageBox.information(self, tr("Driver"), tr("Questo chip usa il driver già incluso in Windows: non serve scaricare nulla."))
            return
        QDesktopServices.openUrl(QUrl(url))

    def install_driver(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Scegli il driver USB da installare"), os.path.expanduser("~/Downloads"),
                                              tr("Driver (*.exe *.msi *.inf);;Tutti i file (*)"))
        if not path:
            return
        if sys.platform != "win32":
            QMessageBox.information(self, tr("Driver"), tr("L'installazione dei driver è prevista solo su Windows."))
            return
        if QMessageBox.question(self, tr("Installa driver"), tr("Installare il driver\n{0}\n\nWindows chiederà l'autorizzazione dell'amministratore.", path)) != QMessageBox.Yes:
            return
        try:
            if path.lower().endswith(".inf"):
                import ctypes

                ctypes.windll.shell32.ShellExecuteW(None, "runas", "pnputil.exe", f'/add-driver "{path}" /install', None, 1)
            else:
                os.startfile(path)  # noqa: S606 — programma di installazione scelto dall'utente
        except OSError as exc:
            QMessageBox.warning(self, tr("Driver"), tr("Installazione non avviata:\n{0}", exc))
            return
        self.log.appendPlainText(tr("Installazione del driver avviata: al termine scollega e ricollega il cavo, poi «Aggiorna»."))

    def linux_permission(self):
        """Linux: il permesso di aprire /dev/ttyUSB0 (gruppo dialout o uucp), con il comando da copiare."""
        from PySide6.QtGui import QGuiApplication

        from .. import linux

        p = self._port()
        dev = p.device if p is not None and p.device.startswith("/dev/") else None
        cmd, group = linux.permission_command(dev)
        ok = dev is not None and os.access(dev, os.R_OK | os.W_OK)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Permesso della porta USB"))
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        state = (tr("Il tuo utente può già usare {0}: non serve fare niente.", dev) if ok else
                 tr("Il tuo utente non può ancora usare {0}.", dev) if dev else "")
        box.setText(tr("<b>Su Linux la porta USB del laser si apre solo se il tuo utente è nel gruppo «{0}».</b><br><br>"
                       "Si fa una volta sola:<ol><li>apri un terminale;</li><li>scrivi <code>{1}</code> e premi Invio "
                       "(chiede la tua password);</li><li>esci dalla sessione e rientra, oppure riavvia il computer;</li>"
                       "<li>torna qui e premi «Aggiorna».</li></ol>{2}<br><br>Se non funziona, mandaci un rapporto da "
                       "<i>Aiuto → Invia un rapporto all'assistenza</i>: dentro c'è già lo stato delle porte.",
                       group, cmd, state))
        copy = box.addButton(tr("Copia il comando"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is copy:
            QGuiApplication.clipboard().setText(cmd)
        return cmd

    def device_manager(self):
        if sys.platform == "win32":
            try:
                os.startfile("devmgmt.msc")  # noqa: S606
            except OSError as exc:
                QMessageBox.warning(self, tr("Gestione dispositivi"), str(exc))

    # ------------------------------------------------------------------ riconoscimento
    def run_probe(self):
        p = self._port()
        if p is None:
            return
        ctl = self.main.ctl
        self.btn_probe.setEnabled(False)
        self.log.clear()
        if ctl.connected and ctl.port == p.device:
            # già connessi: leggo dalla connessione aperta, senza staccarla
            self.log.appendPlainText(tr("Leggo $I e $$ dalla connessione aperta su {0}…", p.device))
            panel = self.main.machine

            def got(data):
                try:
                    ctl.settings_ready.disconnect(got)
                except (RuntimeError, TypeError):
                    pass
                self._done(dict(baud=self.main.profile.baud, banner=[], info=list(panel.info), settings=dict(data)), p)
            ctl.settings_ready.connect(got)
            QTimer.singleShot(8000, lambda: self.btn_probe.setEnabled(True))
            ctl.request_info()
            ctl.request_settings()
            return
        if ctl.connected:
            if ctl.job_active:
                QMessageBox.warning(self, tr("Lavoro in corso"), tr("C'è un lavoro in corso sulla macchina connessa."))
                self.btn_probe.setEnabled(True)
                return
            ctl.disconnect_port()
        sig = _Probe(self)
        self._probe_port = p
        sig.log.connect(self.log.appendPlainText)
        sig.done.connect(self._probe_done)
        opener = None
        if p.device == SIM_PORT:
            from ..sim import SimSerial

            opener = lambda _p, _b: SimSerial()  # noqa: E731
        bauds = (self.main.profile.baud,) + tuple(b for b in machines._BAUDS if b != self.main.profile.baud)

        def work():
            try:
                r = machines.probe(p.device, bauds=bauds, opener=opener, log=sig.log.emit)
            except Exception as exc:  # noqa: BLE001
                sig.log.emit(f"Errore: {exc}")
                r = None
            sig.done.emit(r)
        from . import bg

        bg.run(work, self, sig)

    def _probe_done(self, r):
        self._done(r, self._probe_port)

    def _done(self, r, port):
        self.btn_probe.setEnabled(True)
        if not r:
            self.summary.setText(tr("<span style='color:{0}'>La scheda non risponde su {1}.</span> Controlla che il laser sia acceso, che nessun altro programma usi la porta e il driver USB.", C['warn'], port.device))
            self._set_result_enabled(False)
            return
        self.result = (r, port)
        ident = machines.identify(r["banner"], r["info"], r["settings"], port, r["baud"])
        self.ident = ident
        conf_col = {"alta": C["success"], "media": C["accent_hi"], "bassa": C["warn"]}[ident.confidence]
        icons = {"ok": "✓", "info": "ℹ", "warn": "⚠"}
        notes = "".join(f"<li>{icons.get(k, '•')} {t}</li>" for k, t in ident.notes)
        self.summary.setText(
            tr("<b style='font-size:10.5pt'>{0}</b> &nbsp;<span style='background:{1}; color:white; border-radius:6px; padding:1px 6px'>affidabilità {2}</span><br>{3} · {4} baud", ident.name(), conf_col, {"alta": tr("alta"), "media": tr("media"), "bassa": tr("bassa")}.get(ident.confidence, ident.confidence), ident.summary() or tr("nessun dettaglio dalla scheda"), r['baud']) + (tr("<ul style='margin-left:-18px'>{0}</ul>", notes) if notes else ""))
        # 0.17.6: con il simulatore il profilo si chiama «Simulatore», così non sovrascrive quello della macchina vera
        self.name.setText(tr("Simulatore") if port.device == SIM_PORT else ident.name())
        bx, by = ident.bed
        self.bed_x.setValue(bx or self.main.profile.bed_x)
        self.bed_y.setValue(by or self.main.profile.bed_y)
        self.log.appendPlainText(f"Risposta a {r['baud']} baud: {len(r['info'])} righe $I, {len(r['settings'])} impostazioni.")
        self._set_result_enabled(True)

    def _set_result_enabled(self, on):
        for w in (self.name, self.bed_x, self.bed_y, self.btn_save, self.btn_apply):
            w.setEnabled(on)

    def apply(self, connect=True):
        if self.result is None or self.ident is None:
            return
        r, port = self.result
        name = self.name.text().strip() or self.ident.name()
        if port.device == SIM_PORT:  # 0.17.6: mai sopra il profilo di una macchina vera
            name = tr("Simulatore")
        p = machines.build_profile(self.ident, r["settings"], r["info"], name)
        p.bed_x, p.bed_y = self.bed_x.value(), self.bed_y.value()
        try:
            path = p.save()
        except OSError as exc:
            QMessageBox.warning(self, tr("Profilo"), tr("Impossibile salvare il profilo:\n{0}", exc))
            return
        self.main.set_active_profile(p)
        self.main.qs.setValue("port", port.device)
        self.log.appendPlainText(f"Profilo «{p.name}» salvato in {path}")
        if connect:
            self.main.refresh_ports()
            i = self.main.port_combo.findData(port.device)
            if i >= 0:
                self.main.port_combo.setCurrentIndex(i)
            if not self.main.ctl.connected:
                QTimer.singleShot(300, self.main.toggle_connection)
            self.accept()
        else:
            self._fill_profiles()
