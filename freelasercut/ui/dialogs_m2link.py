# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7, sperimentale (funzioni in prova): configurazione della xTool M2 e collegamento diretto.

Configurazione: indirizzo IP, modulo laser (automatico = quello che dice la macchina, oppure 10/20/40 W), costruttore
del modulo (automatico, TO o COS), spessore del materiale; un pulsante crea il profilo «xTool M2» con l'area giusta
per il piano. Collegamento: la prima volta la M2 chiede di premere il suo pulsante (abbinamento); il gettone che dà
resta salvato. Invio: la cornice a potenza zero o il lavoro; la M2 si mette in attesa e il lavoro parte solo con il
pulsante sulla macchina. Da qui: pausa, ripresa, annullamento.

Le chiamate alla macchina sono bloccanti: girano in un filo a parte; risultati ed eventi arrivano in una coda che un
timer legge nel filo dell'interfaccia.
"""
import os
import queue
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QVBoxLayout,
)

from ..core import xtool_m2, xtool_m2_link, xtool_xs
from ..i18n import tr

STATE_TEXT = {
    "idle": "Pronta", "workready": "Lavoro caricato: premi il pulsante sulla M2", "workplay": "Sta lavorando",
    "workpause": "In pausa", "finish": "Lavoro finito",
}


def state_text(mode):
    m = str(mode or "").lower()
    if m.startswith("p_"):
        m = {"p_idle": "idle", "p_processing": "workplay", "p_pause": "workpause", "p_finish": "finish",
             "p_ready": "workready"}.get(m, m)
    return tr(STATE_TEXT[m]) if m in STATE_TEXT else (str(mode) or "—")


def m2_profile(laser_w, maker):
    """Profilo «xTool M2» con l'area del modulo (per il piano: FreeLaserCut non le manda G-code GRBL)."""
    from ..profile import MachineProfile

    bw, bh = xtool_m2.HEAD_PLANE[(int(laser_w), maker)][2:]
    return MachineProfile(name="xTool M2", model="xTool M2", source=tr("valori di targa"), bed_x=bw, bed_y=bh,
                          s_max=1000.0, laser_mode=True, homing=True, optical_power=f"{int(laser_w)} W",
                          max_rate_x=36000.0, max_rate_y=36000.0)


def cut_layers_default(doc):
    return {cs.index for cs in doc.used_layers() if cs.mode == "line" and xtool_xs.kind_of(cs) == xtool_xs.CUT}


class M2LinkDialog(QDialog):
    def __init__(self, main, parent=None, link_factory=None):
        super().__init__(parent or main)
        self.main = main
        self.qs = main.qs
        self.link = None
        self.link_factory = link_factory or xtool_m2_link.M2Link
        self.q = queue.Queue()
        self.busy = False
        self.watts = None  # modulo in uso dopo il collegamento
        self.maker = "TO"
        self.mode = ""
        self.setWindowTitle(tr("xTool M2: collegamento diretto (sperimentale)"))
        v = QVBoxLayout(self)
        note = QLabel(tr("Funzione in prova, non ufficiale: FreeLaserCut parla con la M2 come fa xTool Studio. Non è "
                         "ancora stata provata su una M2 vera: la prima volta manda solo la cornice, poi un quadratino "
                         "a bassa potenza. Il lavoro parte solo premendo il pulsante sulla macchina."))
        note.setWordWrap(True)
        v.addWidget(note)

        cfg = QGroupBox(tr("Configurazione della M2"))
        f = QFormLayout(cfg)
        self.ip = QLineEdit(str(self.qs.value("m2_ip", "") or ""))
        self.ip.setPlaceholderText("192.168.1.50")
        self.ip.setToolTip(tr("L'indirizzo della M2 nella tua rete (lo mostra xTool Studio o il router). Con il cavo "
                              "USB la M2 crea una rete sua: usa l'indirizzo che le dà"))
        f.addRow(tr("Indirizzo IP"), self.ip)
        self.laser = QComboBox()
        self.laser.addItem(tr("Automatico (lo dice la macchina)"), 0)
        for w in xtool_xs.LASERS:
            self.laser.addItem(tr("{0} W", w), w)
        self.laser.setCurrentIndex(max(0, self.laser.findData(_int(self.qs.value("m2_laser_w", 0)))))
        self.laser.setToolTip(tr("Il modulo laser montato. Se scegli un valore e la macchina ne dice un altro, il "
                                 "lavoro non parte"))
        f.addRow(tr("Modulo laser"), self.laser)
        self.maker_box = QComboBox()
        self.maker_box.addItem(tr("Automatico (lo dice la macchina)"), "")
        for m in xtool_m2.MAKERS:
            self.maker_box.addItem(m, m)
        self.maker_box.setCurrentIndex(max(0, self.maker_box.findData(str(self.qs.value("m2_maker", "") or ""))))
        self.maker_box.setToolTip(tr("Chi ha costruito il modulo laser: cambia lo scostamento fra testa e laser. Lo "
                                     "dice la macchina; senza macchina vale «TO»"))
        f.addRow(tr("Costruttore del modulo"), self.maker_box)
        self.thick = QDoubleSpinBox()
        self.thick.setRange(0.0, xtool_m2.Z_DISTANCE - xtool_m2.FOCUS_GAP)
        self.thick.setDecimals(1)
        self.thick.setSingleStep(0.5)
        self.thick.setSuffix(" mm")
        self.thick.setValue(min(max(_float(self.qs.value("xtool_thickness", 3.0)), 0.0), self.thick.maximum()))
        f.addRow(tr("Spessore del materiale"), self.thick)
        self.b_profile = QPushButton(tr("Usa l'area della M2 per il piano"))
        self.b_profile.setToolTip(tr("Crea (o aggiorna) il profilo «xTool M2» con l'area del modulo scelto e lo rende "
                                     "attivo, così disegni direttamente sull'area della macchina"))
        self.b_profile.clicked.connect(self.make_profile)
        f.addRow("", self.b_profile)
        v.addWidget(cfg)

        row = QHBoxLayout()
        self.b_connect = QPushButton(tr("Collega"))
        self.b_connect.clicked.connect(self.toggle_connect)
        row.addWidget(self.b_connect)
        self.b_forget = QPushButton(tr("Dimentica l'abbinamento"))
        self.b_forget.setToolTip(tr("Cancella il gettone salvato: al prossimo collegamento la M2 chiederà di nuovo il "
                                    "pulsante"))
        self.b_forget.clicked.connect(self.forget)
        row.addWidget(self.b_forget)
        v.addLayout(row)
        self.status = QLabel(tr("Non collegata"))
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        v.addWidget(self.bar)

        job = QHBoxLayout()
        self.b_frame = QPushButton(tr("Invia la cornice (potenza zero)"))
        self.b_frame.clicked.connect(lambda: self.send(frame=True))
        job.addWidget(self.b_frame)
        self.b_job = QPushButton(tr("Invia il lavoro"))
        self.b_job.clicked.connect(lambda: self.send(frame=False))
        job.addWidget(self.b_job)
        v.addLayout(job)
        ctl = QHBoxLayout()
        self.b_pause = QPushButton(tr("Pausa"))
        self.b_pause.clicked.connect(lambda: self.control("PAUSE"))
        self.b_resume = QPushButton(tr("Riprendi"))
        self.b_resume.clicked.connect(lambda: self.control("RESUME"))
        self.b_cancel = QPushButton(tr("Annulla il lavoro"))
        self.b_cancel.clicked.connect(lambda: self.control("CANCEL"))
        for b in (self.b_pause, self.b_resume, self.b_cancel):
            ctl.addWidget(b)
        v.addLayout(ctl)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.update_buttons()

    # --- configurazione -------------------------------------------------------------------------
    def chosen_w(self):
        return int(self.laser.currentData() or 0) or None

    def chosen_maker(self):
        return str(self.maker_box.currentData() or "") or None

    def save_config(self):
        self.qs.setValue("m2_ip", self.ip.text().strip())
        self.qs.setValue("m2_laser_w", int(self.laser.currentData() or 0))
        self.qs.setValue("m2_maker", str(self.maker_box.currentData() or ""))
        self.qs.setValue("xtool_thickness", float(self.thick.value()))

    def job_head(self):
        """(watt, costruttore) per il lavoro: quello della macchina collegata, altrimenti la configurazione."""
        w = self.watts or self.chosen_w() or 10
        maker = self.maker if self.link is not None and self.link.connected else (self.chosen_maker() or "TO")
        return int(w), maker

    def make_profile(self):
        w, maker = self.job_head()
        p = m2_profile(w, maker)
        try:
            p.save()
        except OSError as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("Non riesco a salvare il profilo:\n{0}", ex))
            return None
        self.main.set_active_profile(p)
        self.status.setText(tr("Profilo «xTool M2» attivo: area {0:g} × {1:g} mm (modulo {2} W, {3})", p.bed_x,
                               p.bed_y, w, maker))
        return p

    def forget(self):
        self.qs.setValue("m2_token", "")
        self.status.setText(tr("Abbinamento dimenticato: al prossimo collegamento premi il pulsante sulla M2"))

    # --- fili --------------------------------------------------------------------------------------
    def run_bg(self, tag, fn, *args):
        self.busy = True
        self.update_buttons()

        def go():
            try:
                self.q.put(("done", tag, fn(*args), None))
            except Exception as e:  # noqa: BLE001 - l'errore arriva alla finestra
                self.q.put(("done", tag, None, e))

        threading.Thread(target=go, daemon=True).start()

    def on_event(self, name, data):
        self.q.put(("event", name, data, None))

    def poll(self):
        while True:
            try:
                kind, name, data, err = self.q.get_nowait()
            except queue.Empty:
                return
            if kind == "event":
                self.handle_event(name, data)
            else:
                self.busy = False
                self.finished(name, data, err)
                self.update_buttons()

    def handle_event(self, name, data):
        if name == "pairing":
            self.status.setText(tr("Prima volta con questa M2: premi il pulsante sulla macchina (entro {0:g} "
                                   "secondi)", float(data or 60)))
        elif name == "paired":
            self.qs.setValue("m2_token", str(data or ""))
        elif name == "upload":
            self.bar.setVisible(True)
            self.bar.setValue(int(round(float(data or 0) * 100)))
        elif name == "state":
            self.mode = str(data or "")
            self.status.setText(tr("M2: {0}", state_text(self.mode)))
        elif name == "process":
            msg = {"ready": tr("Lavoro caricato: premi il pulsante sulla M2 per avviarlo"),
                   "start": tr("Lavoro avviato"), "pause": tr("In pausa"), "resume": tr("Ripreso"),
                   "cancel": tr("Lavoro annullato"), "finish": tr("Lavoro finito")}.get(str(data))
            if msg:
                self.status.setText(tr("M2: {0}", msg))
        elif name == "alarm":
            self.status.setText(tr("La M2 segnala un allarme: {0}", str(data)[:200]))
        elif name == "closed":
            self.status.setText(tr("Collegamento chiuso: {0}", str(data or "")))
            self.watts = None
        self.update_buttons()

    def finished(self, tag, result, err):
        self.bar.setVisible(False)
        if err is not None:
            text = str(err) if isinstance(err, xtool_m2_link.M2Error) else tr("Errore: {0}", err)
            self.status.setText(text)
            if tag == "connect" and self.link is not None:
                self.link = None
            return
        if tag == "connect":
            self.after_connect(result or {})
        elif tag == "send":
            self.status.setText(tr("Lavoro caricato: premi il pulsante sulla M2 per avviarlo"))

    # --- collegamento ----------------------------------------------------------------------------
    def toggle_connect(self):
        if self.link is not None and self.link.connected:
            link, self.link = self.link, None
            self.watts = None
            self.status.setText(tr("Non collegata"))
            threading.Thread(target=link.close, daemon=True).start()
            self.update_buttons()
            return
        host = self.ip.text().strip()
        if not host:
            self.status.setText(tr("Scrivi l'indirizzo IP della M2"))
            return
        self.save_config()
        self.status.setText(tr("Collegamento con {0}…", host))
        self.link = self.link_factory(host, token=str(self.qs.value("m2_token", "") or ""), on_event=self.on_event)
        self.run_bg("connect", self.link.connect)

    def after_connect(self, info):
        head = info.get("head") or {}
        fw = xtool_m2_link.firmware_of(info.get("machine") or {})
        try:
            self.watts, self.maker = xtool_m2_link.check_head(head, self.chosen_w(), self.chosen_maker())
            ok = None
        except xtool_m2_link.M2Error as e:
            self.watts, ok = None, str(e)
        self.info.setText(tr("Firmware {0} · testa: {1} · costruttore: {2}", fw or "?", head.get("type") or "?",
                             head.get("manufacture") or "?"))
        self.status.setText(ok or tr("Collegata: modulo {0} W ({1}). {2}", self.watts, self.maker,
                                     state_text(self.link.mode if self.link else "")))
        if fw and not xtool_m2_link.is_m2_version(fw):
            self.status.setText(self.status.text() + "\n" + tr("Attenzione: questa versione del firmware non sembra "
                                                               "quella di una M2"))

    # --- invio --------------------------------------------------------------------------------------
    def build(self, frame=False):
        """-> (righe, resoconto) per il modulo in uso; None (con il motivo nello stato) se non si può."""
        doc = self.main.editor.doc
        shapes = list(self.main.editor.selection or doc.shapes)
        w, maker = self.job_head()
        try:
            lines, rep = xtool_m2.build(doc, shapes, laser_w=w, thickness=float(self.thick.value()),
                                        cut_layers=cut_layers_default(doc), maker=maker)
        except xtool_m2.OutsideArea:
            bw, bh = xtool_m2.HEAD_PLANE[(w, maker)][2:]
            self.status.setText(tr("Il disegno esce dall'area della M2 con questo modulo ({0:g} × {1:g} mm): non "
                                   "invio niente", bw, bh))
            return None
        except ValueError:
            self.status.setText(tr("Niente da inviare: nessun oggetto su un livello che esce"))
            return None
        if frame:
            lines = xtool_m2.frame(rep["box"], w, float(self.thick.value()), maker)
        return lines, rep

    def send(self, frame=False):
        if self.link is None or not self.link.connected or self.watts is None:
            self.status.setText(tr("Prima collega la M2"))
            return None
        built = self.build(frame)
        if built is None:
            return None
        lines, rep = built
        self.save_config()
        box = rep["box"]
        what = tr("la cornice (laser spento)") if frame else tr("il lavoro")
        text = tr("Invio {0} alla M2: modulo {1} W, spessore {2:g} mm, ingombro {3:g} × {4:g} mm.\nLa macchina si "
                  "mette in attesa: parte solo quando premi il suo pulsante. Coperchio chiuso e materiale a "
                  "posto?", what, self.watts, self.thick.value(), box[2] - box[0], box[3] - box[1])
        if not os.environ.get("FLC_NO_DIALOGS") and QMessageBox.question(self, self.windowTitle(), text) != QMessageBox.Yes:
            return None
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self.status.setText(tr("Invio alla M2…"))
        self.run_bg("send", self.link.send_job, data, self.watts, float(self.thick.value()))
        return data

    def control(self, action):
        if self.link is None or not self.link.connected:
            return
        self.run_bg("control", self.link.control, action)

    def update_buttons(self):
        on = self.link is not None and self.link.connected
        m = self.mode.lower()
        working = m in ("workplay", "workpause", "workready", "p_processing", "p_pause")
        self.b_connect.setText(tr("Scollega") if on else tr("Collega"))
        self.b_connect.setEnabled(not self.busy or on)
        for wdg in (self.ip, self.laser, self.maker_box, self.b_forget):
            wdg.setEnabled(not on and not self.busy)
        ready = on and not self.busy and self.watts is not None and not working
        self.b_frame.setEnabled(ready)
        self.b_job.setEnabled(ready)
        self.b_pause.setEnabled(on and m in ("workplay", "p_processing"))
        self.b_resume.setEnabled(on and m in ("workpause", "p_pause"))
        self.b_cancel.setEnabled(on and working)

    def done(self, r):
        self.timer.stop()
        if self.link is not None:
            link, self.link = self.link, None
            threading.Thread(target=link.close, daemon=True).start()
        super().done(r)


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _float(v, d=3.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d
