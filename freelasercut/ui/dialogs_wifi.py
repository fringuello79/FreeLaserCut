# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Impostazioni → Collegamento Wi-Fi del laser… (0.18.17): la procedura guidata.

Guarda da sola che cosa c'è (collegamento, stato della macchina, tipo di scheda, rete del PC) e porta al caso giusto:
A già in Wi-Fi · B cavo USB e scheda con il Wi-Fi · C scheda senza Wi-Fi · D scheda che non accetta i comandi ·
E nessun collegamento (con il cavo, oppure senza cavo passando dalla rete propria del laser).
La logica (comandi, messaggi, controlli, rete del PC, ricerca in rete) è in wifi_setup.py, senza Qt.
La password della rete non viene mai salvata e non compare in console, registro, copie o rapporto.
"""
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from .. import netport, wifi_setup
from ..grbl import SIM_PORT, list_serial_ports
from . import bg
from freelasercut.i18n import tr  # noqa: E402

REPLY_S = 4.0  # attesa della risposta a un comando
WAIT_S = 30.0  # attesa dei messaggi della scheda dopo il riavvio
REOPEN_S = 20.0  # riapertura della porta USB caduta al riavvio
USB_WAIT_S = 30.0  # attesa del cavo
FIND_S = 10.0  # durata massima di «Trova il laser in rete»
BUSY = ("Run", "Hold", "Jog", "Home", "Check", "Door")


class Talker(QObject):
    """Un comando alla volta alla scheda: raccoglie le righe di risposta fino a «ok» / «error» (o al tempo scaduto)."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self._cb = None
        self._lines = []
        self._n = 0
        self._tag = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._finish(None))
        ctl.reply_ready.connect(self._on_reply)

    def ask(self, cmd, cb, timeout=None):
        """cb(esito, righe): esito True = ok, False = rifiutato, None = nessuna risposta."""
        self._cb, self._lines = cb, []
        self._timer.start(int((REPLY_S if timeout is None else timeout) * 1000))
        if not self.ctl.connected:
            QTimer.singleShot(0, lambda: self._finish(None))
            return
        # ogni domanda ha la sua etichetta: la risposta è quella che il controllo abbina a questo comando, anche se
        # intanto rispondono altri comandi (per esempio $I e $$ appena dopo il collegamento)
        self._n += 1
        self._tag = f"ask:{self._n}:{id(self)}"
        self.ctl.send_line(cmd, tag=self._tag)

    def _on_reply(self, tag, ok, lines):
        if self._cb is None or tag != self._tag:
            return
        self._lines = list(lines)
        self._finish(bool(ok))

    def _finish(self, result):
        cb, self._cb = self._cb, None
        self._timer.stop()
        if cb is not None:
            cb(result, list(self._lines))

    def stop(self):
        self._cb = None
        self._timer.stop()
        try:
            self.ctl.reply_ready.disconnect(self._on_reply)
        except (RuntimeError, TypeError):
            pass


def cause_text(code):
    return {
        "band5": tr("la rete è a 5 GHz: la scheda del laser vede solo le reti a 2,4 GHz"),
        "wrong_password": tr("la password non è giusta (maiuscole e minuscole contano)"),
        "wpa3": tr("la rete accetta solo WPA3: molte schede vogliono WPA2"),
        "special": tr("nome o password hanno spazi o caratteri particolari che alcune schede leggono male"),
        "weak": tr("il segnale è debole dove sta il laser"),
        "guest": tr("è una rete per gli ospiti: spesso non lascia entrare questi apparecchi"),
        "not_seen": tr("il PC non vede una rete con questo nome: controlla com'è scritto"),
    }.get(code, code)


def check_text(c):
    return {
        "ssid_empty": tr("Scrivi il nome della rete."),
        "ssid_long": tr("Il nome della rete è troppo lungo (al massimo 32 caratteri)."),
        "pwd_short": tr("La password è troppo corta: servono almeno 8 caratteri."),
        "pwd_long": tr("La password è troppo lunga (al massimo 63 caratteri)."),
        "enterprise": tr("Questa è una rete aziendale con nome utente e password: le schede dei laser non la sanno usare."),
        "semicolon": tr("Con questa scheda nome e password non possono contenere «;» né «(»."),
        "band5": tr("Questa rete è a 5 GHz: la scheda del laser vede solo i 2,4 GHz. Se il router ha anche la rete a "
                    "2,4 GHz, scegli quella."),
        "guest": tr("Sembra una rete per gli ospiti: laser e PC devono stare sulla stessa rete di casa."),
        "other_net": tr("Non è la rete a cui è collegato questo PC: laser e PC devono stare sulla stessa rete."),
        "wpa3": tr("Questa rete accetta solo WPA3: molte schede vogliono WPA2 e potrebbero non entrare."),
        "open": tr("È una rete aperta, senza password: chiunque nei dintorni potrebbe collegarsi al laser."),
        "special": tr("Nome o password hanno spazi o caratteri particolari ($ ; ( ) [ ], accenti, emoji): alcune schede "
                      "li leggono male."),
        "weak": tr("Il segnale di questa rete qui è debole."),
    }.get(c.code, c.code)


def router_guide():
    return tr("<b>Prenota l'indirizzo nel router</b> (consigliato): così il laser avrà sempre lo stesso indirizzo.<br>"
              "1. Apri la pagina del router dal browser (di solito <i>192.168.1.1</i> o <i>192.168.0.1</i>; è scritto "
              "sull'etichetta del router).<br>"
              "2. Cerca la sezione <i>DHCP</i> o <i>Dispositivi collegati</i> e trova il laser (spesso si chiama "
              "<i>ESP…</i> o <i>MKS…</i>) con l'indirizzo che vedi qui sopra.<br>"
              "3. Scegli <i>Prenota</i>, <i>Indirizzo fisso</i> o <i>Assegnazione statica</i> per quel dispositivo e salva.<br>"
              "Se non lo fai e un giorno l'indirizzo cambia, FreeLaserCut prova comunque a ritrovare il laser da solo.")


# i passi in cui la procedura è arrivata in fondo, bene o male: lì si salva il registro (0.19.0)
END_STATES = ("ok", "failed", "not_tried", "unknown", "no_port", "other_subnet", "find_none", "mute", "serial_lost",
              "E2_fail", "off_done")
NOT_TRIED_S = 5.0  # la rete propria ripartita entro tanti secondi dal riavvio, senza «Connecting»: non ha provato


class WifiWizard(QDialog):
    worked = Signal(int, str, object)  # (giro, che cosa, risultato) dai lavori in secondo piano

    def __init__(self, main, system=None):
        super().__init__(main)
        self.main, self.ctl, self.qs = main, main.ctl, main.qs
        self.sys = system or wifi_setup.System()
        self.state = ""
        self.family, self.lgt, self.mode, self.ip = None, False, None, None
        self.switch = None  # il valore di «$wifi» sulle schede che ce l'hanno (0.19.1)
        self.nets, self.pc_ssid, self.pc_ip = [], None, None
        self.ssid_sent, self.net_sent, self.pwd_len = "", None, 0
        self.result = None  # "tcp://indirizzo:porta" salvato
        self.cordless = False  # strada senza cavo: il PC è (stato) sulla rete del laser
        self.confirm = self._confirm  # le prove lo sostituiscono
        self._gen = 0
        self._ports0 = set()
        self._buttons = {}
        self.setWindowTitle(tr("Collegamento Wi-Fi del laser"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 13pt;")
        self.title.setTextFormat(Qt.RichText)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setOpenExternalLinks(True)
        v.addWidget(self.body)
        # ---- pagina «rete»
        self.form = QWidget()
        fv = QVBoxLayout(self.form)
        fv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        self.list.itemClicked.connect(self._pick_net)
        fv.addWidget(self.list)
        f = QFormLayout()
        self.ssid = QLineEdit()
        self.ssid.setPlaceholderText(tr("nome della rete (anche scritto a mano, per le reti nascoste)"))
        self.ssid.textChanged.connect(self._validate)
        f.addRow(tr("Rete"), self.ssid)
        row = QHBoxLayout()
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.textChanged.connect(self._validate)
        self.eye = QToolButton()
        self.eye.setText("👁")
        self.eye.setCheckable(True)
        self.eye.setToolTip(tr("Mostra la password"))
        self.eye.toggled.connect(lambda on: self.pwd.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row.addWidget(self.pwd, 1)
        row.addWidget(self.eye)
        f.addRow(tr("Password"), row)
        fv.addLayout(f)
        self.adv = QGroupBox(tr("Avanzate"))
        self.adv.setCheckable(True)
        self.adv.setChecked(False)
        af = QFormLayout(self.adv)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        self.port.setToolTip(tr("La porta su cui la scheda accetta i comandi dalla rete: 8080 per le schede Makerbase e "
                                "Longer, 23 per FluidNC e Grbl_ESP32"))
        af.addRow(tr("Porta"), self.port)
        self.adv.toggled.connect(self.port.setVisible)
        self.port.setVisible(False)
        fv.addWidget(self.adv)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setTextFormat(Qt.RichText)
        fv.addWidget(self.warn)
        v.addWidget(self.form)
        self.choice = QListWidget()  # più laser trovati, più reti del laser
        self.choice.setMaximumHeight(120)
        v.addWidget(self.choice)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.brow = QHBoxLayout()
        v.addLayout(self.brow)
        self.talk = Talker(self.ctl, self)
        self._info = list(self.ctl.board_info or [])  # l'ultima risposta a $I (mentre la scheda la riscrive è vuota)
        self.ctl.info_ready.connect(self._on_info)
        self.worked.connect(self._on_worked)
        self.ctl.line_received.connect(self._on_board_line)
        self.ctl.connection_changed.connect(self._on_connection)
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)
        self._t0 = 0.0
        self._page("", "")

    # ================================================================== pagine
    def _page(self, title, body, buttons=(), form=False, choice=False, busy=None):
        """Mostra una pagina. buttons: [(chiave, testo, funzione)] (l'ultimo è quello principale).
        busy: None = niente barra; 0 = barra che scorre; n > 0 = barra che si riempie in n secondi."""
        self.title.setText(f"<b>{title}</b>" if title else "")
        self.body.setText(body)
        self.form.setVisible(form)
        self.choice.setVisible(choice)
        self.bar.setVisible(busy is not None)
        if busy is not None:
            self.bar.setRange(0, 0 if not busy else int(busy * 4))
            self.bar.setValue(0)
        while self.brow.count():
            it = self.brow.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._buttons = {}
        self.brow.addStretch(1)
        for i, (key, text, fn) in enumerate(buttons):
            b = QPushButton(text)
            if i == len(buttons) - 1 and len(buttons) > 0:
                b.setObjectName("primary")
                b.setDefault(True)
            b.clicked.connect(lambda _=False, f=fn: f())
            self.brow.addWidget(b)
            self._buttons[key] = b
        self.adjustSize()

    def _on_info(self, lines):
        if lines:
            self._info = list(lines)

    def info(self):
        cur = list(self.ctl.board_info or [])
        if cur:
            self._info = cur
        return self._info

    def has(self, key):
        return key in self._buttons

    def press(self, key):
        """Preme un pulsante della pagina (per le prove e per la tastiera)."""
        self._buttons[key].click()

    def _close_btn(self):
        return ("close", tr("Chiudi"), self.accept)

    def _set(self, state):
        self.state = state
        self._gen += 1
        self._tick.stop()
        self._note(state)
        return self._gen

    def _note(self, state):
        """0.19.0: ogni passo lascia una riga nel registro della comunicazione e, quando la procedura arriva in fondo
        (riuscita o no), il registro viene salvato nella cartella «diagnostica»: se qualcosa non va ci sono le righe
        scambiate con la scheda. La password non c'è: nel registro le righe arrivano già mascherate."""
        log = getattr(self.main, "comm_log", None)
        if log is None:
            return
        log.add("#", f"Wi-Fi guidato: {state}")
        if state in END_STATES:
            self.log_file = log.save("wifi")

    # ================================================================== pagina 0: che cosa c'è adesso
    def start(self):
        if self.sys.pending():  # FreeLaserCut chiuso mentre il PC era sulla rete del laser: prima si torna a casa
            self._go_back_home()
        self.detect()
        return self

    def detect(self):
        ctl = self.ctl
        st = (ctl.last_status or {}).get("state", "") if ctl.connected else ""
        if ctl.connected and (ctl.job_active or ctl.checking or st in BUSY):
            self._set("busy")
            return self._page(tr("C'è un lavoro in corso"),
                              tr("Finisci o ferma il lavoro, poi riapri <i>Impostazioni → Collegamento Wi-Fi del laser</i>. "
                                 "Adesso non mando nessun comando alla scheda."), [self._close_btn()])
        if ctl.connected and st == "Alarm":
            self._set("alarm")
            return self._page(tr("La macchina è in allarme"),
                              tr("Prima va sbloccata: poi continuo da solo."),
                              [self._close_btn(), ("unlock", tr("Sblocca la macchina"), self._unlock)])
        if ctl.connected and ctl.port == SIM_PORT and getattr(ctl.sim, "wifi", None) is None:
            self._set("sim")
            from .. import admin

            btn = [self._close_btn()]
            if admin.unlocked(self.qs):  # solo con le funzioni in prova sbloccate
                btn.append(("fake", tr("Prova con una scheda finta"), self._fake_board))
            return self._page(tr("Sei collegato al simulatore"),
                              tr("Il simulatore non ha un Wi-Fi da impostare: serve un laser vero. Scollega il "
                                 "simulatore, collega il laser con il cavo USB e riapri questa finestra."), btn)
        if ctl.connected and netport.is_net(ctl.port or ""):
            return self._case_a()
        if ctl.connected:
            return self._probe()
        return self._case_e()

    def _unlock(self):
        self.ctl.unlock()
        g = self._set("unlocking")
        self._page(tr("Sblocco la macchina…"), "", [], busy=0)
        QTimer.singleShot(1200, lambda: g == self._gen and self.detect())

    def _fake_board(self):
        self.ctl.sim.wifi_board("lgt")
        self.detect()

    # ---- riconoscimento della scheda (collegata col cavo, o dalla sua rete propria)
    def _probe(self):
        g = self._set("probe")
        self._page(tr("Guardo che scheda è…"), tr("Qualche secondo: leggo come la scheda gestisce il Wi-Fi."), [], busy=0)
        self.family, self.mode, self.ip = None, None, None
        self.switch = None
        self._silent = 0

        def go():
            if g != self._gen:
                return
            self.lgt = wifi_setup.is_lgt(self.info())
            self.talk.ask("[ESP110]", lambda ok, lines: g == self._gen and self._probe_esp(ok, lines))

        # appena collegata la scheda sta ancora rispondendo a $I e $$: aspetto che abbia finito
        wait = 0 if (self.info() or self.ctl.board_settings) else 2500
        QTimer.singleShot(wait, go)

    def _probe_esp(self, ok, lines):
        g = self._gen
        if ok:
            self.family, self.mode = "esp", wifi_setup.parse_mode(lines)
            self.switch = None

            def ask_ip(*_):
                self.talk.ask("[ESP111]", lambda ok2, l2: g == self._gen and self._probed(wifi_setup.find_ip(" ".join(l2))))
            if wifi_setup.has_wifi_switch(self.info()):  # 0.19.1: schede con l'interruttore «$wifi» (Mecpow)
                def got_switch(ok2, l2):
                    if g != self._gen:
                        return
                    self.switch = wifi_setup.parse_switch(l2) if ok2 else None
                    ask_ip()
                return self.talk.ask("$wifi", got_switch)
            return ask_ip()
        self._silent += ok is None
        self.talk.ask("$Sta/SSID", lambda ok2, l2: g == self._gen and self._probe_named(ok2, l2))

    def _probe_named(self, ok, lines):
        g = self._gen
        if ok:
            self.family = "named"
            return self.talk.ask("$I", lambda ok2, l2: g == self._gen and self._probe_named_state(l2))
        self._silent += ok is None
        ctl = self.ctl
        if self._silent >= 2:
            self._set("mute")
            return self._page(tr("La scheda non risponde"),
                              tr("Ho mandato due comandi e non è arrivata nessuna risposta. Controlla che il laser sia "
                                 "acceso e che il cavo sia quello giusto, poi riprova."),
                              [self._close_btn(), ("retry", tr("Riprova"), self.detect)])
        if wifi_setup.wifi_numbers(ctl.board_settings):
            self.family = "numeric"
            self.mode = "OFF" if str(ctl.board_settings.get(50, "")).strip() == "0" else None
            return self._probed(None)
        if wifi_setup.esp32_hints(self.info(), ctl.board_settings):
            return self._case_d()
        return self._case_c()

    def _probe_named_state(self, lines):
        for l in lines:
            m = wifi_setup.parse_message(l)
            if m and m[0] == "connected":
                self.mode = "STA"
                return self._probed(m[1])
        self._probed(None)

    def _probed(self, ip):
        self.ip = ip
        self.port.setValue(wifi_setup.default_port(self.family, " ".join(self.info())))
        if self.cordless:
            return self._page_net()
        self._case_b()

    # ================================================================== caso A: già in Wi-Fi
    def _board_name(self):
        info = " ".join(self.info())
        for key in ("FW:", "[VER:"):
            if key in info:
                return info.split(key, 1)[1].split("]")[0].split("|")[0].strip(": ")
        return ""

    def _case_a(self):
        self._set("A")
        a = netport.parse_address(self.ctl.port) or ("?", 0)
        self.pc_ip = self.sys.local_ip()
        same = wifi_setup.same_subnet(a[0], self.pc_ip)
        txt = tr("Il laser è già collegato via Wi-Fi.<br>Indirizzo: <b>{0}</b> · porta <b>{1}</b>", a[0], a[1])
        name = self._board_name()
        if name:
            txt += "<br>" + tr("Scheda: {0}", name)
        if same is not None:
            txt += "<br>" + (tr("Laser e PC sono sulla stessa rete: sì.") if same else
                             tr("Laser e PC <b>non</b> sembrano sulla stessa rete (indirizzo del PC: {0}).", self.pc_ip))
        self.result = self.ctl.port
        self._page(tr("Già collegato via Wi-Fi"), txt,
                   [("off", tr("Spegni il Wi-Fi della scheda"), self._wifi_off),
                    ("change", tr("Cambia rete"), self._case_e_change),
                    ("router", tr("Prenota l'indirizzo nel router"), self._show_router), self._close_btn()])

    def _show_router(self):
        self.body.setText(self.body.text().split("<hr>")[0] + "<hr>" + router_guide())
        self.adjustSize()

    def _wifi_off(self):
        if not self.confirm(tr("Spengo il Wi-Fi della scheda? Dopo, per usare il laser servirà il cavo USB.")):
            return
        g = self._set("off")
        self._page(tr("Spengo il Wi-Fi della scheda…"), "", [], busy=0)
        fam = self.family or "esp"
        cmds = list(wifi_setup.commands(fam, "off", self.lgt)) + [c for f in ("esp", "named") if f != fam
                                                                  for c in wifi_setup.commands(f, "off")]

        def step(i):
            if g != self._gen:
                return
            if i >= len(cmds):
                return self._page(tr("Non sono riuscito a spegnere il Wi-Fi"),
                                  tr("La scheda ha rifiutato i comandi: il Wi-Fi resta com'era."), [self._close_btn()])
            self.talk.ask(cmds[i], lambda ok, _l: done() if ok else step(i + 1))

        def done():
            self._set("off_done")
            self._restart(lambda: None)
            self._page(tr("Wi-Fi della scheda spento"),
                       tr("Da adesso il laser si usa con il cavo USB. Per riaccendere il Wi-Fi riapri questa finestra con "
                          "il cavo collegato."), [self._close_btn()])
        step(0)

    # ================================================================== caso B: USB, scheda con il Wi-Fi
    def _case_b(self):
        g = self._set("B")
        st = wifi_setup.board_state(self.mode, self.ip)
        self.board_wifi = st
        self.pc_ip = self.sys.local_ip()
        text = {"off": tr("Il Wi-Fi della scheda è <b>spento</b>."),
                "own": tr("La scheda sta facendo la <b>sua rete propria</b> ({0}): non è ancora nella rete di casa.",
                          self.ip or wifi_setup.OWN_NET_IP),
                "idle": tr("Il Wi-Fi della scheda è acceso, ma <b>non è collegata a nessuna rete</b>."),
                "net": tr("La scheda è <b>già in una rete</b>, con l'indirizzo {0}.", self.ip or "?")}[st]
        if self.family == "numeric":
            text += "<br>" + tr("(Scheda di un tipo che non ho potuto collaudare: se qualcosa non va, te lo dico.)")
        nxt = [self._close_btn(), ("net", tr("Avanti: scegli la rete"), self._page_net)]
        if st == "net" and wifi_setup.same_subnet(self.ip, self.pc_ip) is not False:
            self._page(tr("Scheda con il Wi-Fi trovata"), text + "<br>" + tr("Provo se risponde…"), [], busy=0)
            return self._try_ports(self.ip, lambda hit: g == self._gen and (
                self._done(hit["host"], hit["port"], hit, already=True) if hit else
                self._page(tr("Scheda con il Wi-Fi trovata"), text + "<br>" + tr(
                    "A quell'indirizzo però non risponde: conviene ricollegarla alla rete."), nxt)))
        self._page(tr("Scheda con il Wi-Fi trovata"), text, nxt)

    # ================================================================== casi C e D
    def _case_c(self):
        self._set("C")
        self._page(tr("Questa scheda non ha il Wi-Fi"),
                   tr("Si usa con il cavo USB. Non ho mandato nessuna impostazione alla scheda.<br><br>"
                      "Chi vuole comunque fare a meno del cavo può mettere accanto al laser un piccolo computer che porta "
                      "la porta USB in rete: è una soluzione fai-da-te, non una funzione di FreeLaserCut."),
                   [self._close_btn()])

    def _case_d(self):
        self._set("D")
        txt = tr("La tua scheda ha il Wi-Fi, ma non accetta i comandi per impostarlo dal cavo: il Wi-Fi si imposta "
                 "<b>dallo schermo del laser o dall'app del produttore</b>. Non ho cambiato niente e non ho riavviato "
                 "la scheda.<br><br>Quando l'hai fatto, premi <i>Trova il laser in rete</i>.")
        if wifi_setup.is_mks_like(self.info()):
            txt += "<br><br>" + tr("Per le schede Makerbase e Longer c'è anche lo strumento del produttore, MKS Laser "
                                   "Tool (solo Windows).")
        self._page(tr("Il Wi-Fi di questa scheda si imposta dal laser"), txt,
                   [self._close_btn(), ("find", tr("Trova il laser in rete"), self._find)])

    # ================================================================== caso E: nessun collegamento
    def _case_e(self):
        self._set("E")
        self._page(tr("Il laser non è collegato"),
                   tr("<b>Hai il cavo USB a portata di mano?</b><br>Con il cavo è la strada più sicura. Senza cavo si può "
                      "fare se il laser, acceso, mostra una sua rete Wi-Fi (per esempio «MKS_DLC»)."),
                   [self._close_btn(), ("find", tr("Trova il laser in rete"), self._find),
                    ("nocable", tr("No, senza cavo"), self._e2), ("cable", tr("Sì, ho il cavo"), self._e1)])

    def _case_e_change(self):
        """Cambia rete (dal caso A): serve il cavo o la rete propria del laser."""
        self._set("E")
        self._page(tr("Cambiare la rete del laser"),
                   tr("Per dare al laser un'altra rete serve il cavo USB (oppure, senza cavo, la rete propria del laser). "
                      "<b>Hai il cavo USB a portata di mano?</b>"),
                   [self._close_btn(), ("nocable", tr("No, senza cavo"), self._e2), ("cable", tr("Sì, ho il cavo"), self._e1)])

    # ---- E1: con il cavo
    def _usb_ports(self):
        return {p for p, _l, _k in list_serial_ports() if p != SIM_PORT}

    def _e1(self):
        if self.ctl.connected:
            self.ctl.disconnect_port()
        likely = [p for p, _l, k in list_serial_ports() if k and p != SIM_PORT]
        if likely:  # il cavo c'è già: mi collego da solo alla porta del laser
            return self._usb_connect(likely[0])
        self._set("E1")
        self._ports0 = self._usb_ports()
        self._t0 = time.time()
        self._page(tr("Collega il cavo USB e accendi il laser"),
                   tr("Appena il computer vede la porta del laser mi collego da solo."), [self._close_btn()],
                   busy=USB_WAIT_S)
        self._tick.start()

    def _usb_connect(self, port):
        g = self._set("usb_connect")
        self._page(tr("Mi collego al laser su {0}…", port), "", [], busy=0)
        ok = self.ctl.connect_port(port, self.main.profile.baud)
        if not ok:
            return self._usb_missing()
        self.qs.setValue("port", port)
        QTimer.singleShot(2600, lambda: g == self._gen and self.detect())

    def _usb_missing(self):
        self._set("E1_none")
        self._page(tr("Non vedo la porta del laser"),
                   tr("In 30 secondi non è comparsa nessuna porta nuova. Le cause più comuni:<br>"
                      "• il laser è spento;<br>"
                      "• il cavo USB è di quelli che servono solo a ricaricare (provane un altro);<br>"
                      "• manca il driver del chip USB della scheda (CH340 o CP210x): <i>Laser → Riconosci la macchina</i> "
                      "dice quale serve."),
                   [self._close_btn(), ("retry", tr("Riprova"), self._e1)])

    # ---- E2: senza cavo, dalla rete propria del laser
    def _e2(self):
        g = self._set("E2_scan")
        self._page(tr("Cerco la rete del laser…"), tr("Guardo le reti Wi-Fi che questo PC vede."), [], busy=0)

        def work():
            has = self.sys.has_wifi()
            nets = self.sys.scan() if has else []
            self.worked.emit(g, "e2", (has, nets, self.sys.current() if has else None))
        bg.run(work, self)

    def _e2_scanned(self, has, nets, cur):
        self.nets, self.pc_ssid = nets, cur
        if not has:
            self._set("E2_nowifi")
            return self._page(tr("Questo PC non ha il Wi-Fi"),
                              tr("È collegato alla rete con il cavo: non può agganciarsi alla rete del laser, quindi "
                                 "senza cavo USB da qui non si può fare il primo passaggio."),
                              [self._close_btn(), ("find", tr("Trova il laser in rete"), self._find),
                               ("cable", tr("Uso il cavo USB"), self._e1)])
        own = [n for n in nets if wifi_setup.is_own_net(n.ssid)]
        if not own:
            return self._find(then_cable=True)
        self._set("E2_pick")
        self.choice.clear()
        for n in own:
            self.choice.addItem(n.ssid)
        self.choice.setCurrentRow(0)
        self._page(tr("Ho trovato la rete del laser"),
                   tr("Per un minuto collego questo PC alla rete del laser, gli do la rete di casa e poi riporto il PC "
                      "sulla rete di prima{0}. Intanto il PC resta senza Internet.",
                      f" («{cur}»)" if cur else ""),
                   [self._close_btn(), ("join", tr("Vai"), self._e2_join)], choice=len(own) > 1)

    def _e2_join(self, password=None):
        ssid = self.choice.currentItem().text() if self.choice.currentItem() else ""
        g = self._set("E2_join")
        self.cordless, self.own_ssid = True, ssid
        self._page(tr("Collego il PC alla rete «{0}»…", ssid), "", [], busy=0)
        pw = wifi_setup.OWN_NET_PASSWORD if password is None else password

        def work():
            ok = self.sys.join(ssid, pw)
            t_end = time.time() + 15
            while ok and time.time() < t_end and self.sys.current() != ssid:
                time.sleep(0.5)
            self.worked.emit(g, "joined", bool(ok and self.sys.current() == ssid))
        bg.run(work, self)

    def _e2_joined(self, ok):
        if not ok:
            self._set("E2_manual")
            return self._page(tr("Collega tu il PC alla rete del laser"),
                              tr("Il sistema non me lo lascia fare da solo. Dall'icona del Wi-Fi del computer collegati "
                                 "alla rete <b>«{0}»</b> (la password predefinita delle schede Makerbase è "
                                 "<i>12345678</i>), poi premi <i>Fatto</i>.", self.own_ssid),
                              [("cancel", tr("Annulla"), self._e2_abort), ("done", tr("Fatto"), self._e2_link)])
        self._e2_link()

    def _e2_link(self):
        g = self._set("E2_link")
        self._page(tr("Mi collego alla scheda…"), "", [], busy=0)
        self._try_ports(wifi_setup.OWN_NET_IP, lambda hit: g == self._gen and self._e2_linked(hit))

    def _e2_linked(self, hit):
        if not hit:
            self._go_back_home()
            self._set("E2_fail")
            return self._page(tr("La scheda non risponde sulla sua rete"),
                              tr("Ho riportato il PC sulla rete di prima. Per il primo passaggio serve il cavo USB."),
                              [self._close_btn(), ("cable", tr("Uso il cavo USB"), self._e1)])
        g = self._gen
        self.ctl.connect_port(netport.make_port(hit["host"], hit["port"]))
        QTimer.singleShot(1800, lambda: g == self._gen and self._probe())

    def _e2_abort(self):
        self._go_back_home()
        self.detect()

    def _go_back_home(self):
        """Riporta il PC sulla rete di prima (sempre: dopo un errore, alla chiusura, al prossimo avvio)."""
        self.cordless = False
        try:
            return self.sys.back()
        except Exception:  # noqa: BLE001
            return None

    # ================================================================== pagina «rete»
    def _page_net(self):
        g = self._set("net")
        self.warn.setText("")
        self._page(tr("A quale rete collego il laser?"),
                   tr("Scegli la rete di casa: <b>la stessa di questo PC</b>, a 2,4 GHz. La password serve solo adesso: "
                      "non viene salvata."),
                   [self._close_btn(), ("write", tr("Collega il laser a questa rete"), self._write)], form=True)
        self._validate()
        if self.cordless and self.nets:  # le reti le ho già viste prima di passare alla rete del laser
            return self._fill_nets()

        def work():
            self.worked.emit(g, "nets", (self.sys.scan(), self.sys.current(), self.sys.local_ip()))
        bg.run(work, self)

    def _fill_nets(self):
        self.list.clear()
        for n in self.nets:
            if wifi_setup.is_own_net(n.ssid):
                continue
            bits = [n.ssid]
            if n.band:
                bits.append(n.band.replace(".", ",") + " GHz")
            if n.signal is not None:
                bits.append(f"{n.signal}%")
            if n.current or n.ssid == self.pc_ssid:
                bits.append(tr("la rete di questo PC"))
            it = QListWidgetItem("  ·  ".join(bits))
            it.setData(Qt.UserRole, n)
            self.list.addItem(it)
        if not self.ssid.text() and self.pc_ssid:
            self.ssid.setText(self.pc_ssid)  # preselezionata la rete del PC
        for i in range(self.list.count()):
            n = self.list.item(i).data(Qt.UserRole)
            if n.ssid == self.ssid.text() and (n.band == "2.4" or not any(
                    m.ssid == n.ssid and m.band == "2.4" for m in self.nets)):
                self.list.setCurrentRow(i)
                break
        self._validate()

    def _pick_net(self, it):
        self.ssid.setText(it.data(Qt.UserRole).ssid)
        self._validate()

    def _net_obj(self):
        """La rete dell'elenco che corrisponde al nome scritto (quella a 2,4 GHz, se c'è)."""
        same = [n for n in self.nets if n.ssid == self.ssid.text()]
        it = self.list.currentItem()
        if it is not None and it.data(Qt.UserRole) in same:
            return it.data(Qt.UserRole)
        return next((n for n in same if n.band == "2.4"), same[0] if same else None)

    def checks(self):
        return wifi_setup.check_network(self.ssid.text(), self.pwd.text(), self._net_obj(), self.pc_ssid,
                                        self.family or "esp", self.nets)

    def _validate(self, *_):
        if self.state != "net":
            return
        cs = self.checks()
        lines = [("<span style='color:#E5484D'>✕ {0}</span>" if c.block else "<span style='color:#D9A400'>⚠ {0}</span>")
                 .format(check_text(c)) for c in cs if not (c.code in ("ssid_empty", "pwd_short") and not self.pwd.text()
                                                            and not self.ssid.text())]
        self.warn.setText("<br>".join(lines))
        if "write" in self._buttons:
            self._buttons["write"].setEnabled(not any(c.block for c in cs))

    def _confirm(self, text):
        if os.environ.get("FLC_NO_DIALOGS"):
            return True
        return QMessageBox.question(self, self.windowTitle(), text) == QMessageBox.Yes

    # ================================================================== scrivi, riavvia, aspetta
    def _write(self):
        cs = self.checks()
        if any(c.block for c in cs):
            return self._validate()
        if any(c.code == "other_net" for c in cs) and not self.confirm(
                tr("«{0}» non è la rete a cui è collegato questo PC. Se il laser va su un'altra rete, da qui non lo "
                   "raggiungi. La uso lo stesso?", self.ssid.text())):
            return
        ssid, pwd = self.ssid.text(), self.pwd.text()
        self.ssid_sent, self.net_sent, self.pwd_len = ssid, self._net_obj(), len(pwd)
        self.causes = wifi_setup.likely_causes(ssid, pwd, self.net_sent, self.nets, self.family or "esp")
        self.pwd.clear()  # la password non resta nemmeno nella finestra
        g = self._set("write")
        self._page(tr("Scrivo la rete nella scheda…"), "", [], busy=0)
        ctl = self.ctl
        if ctl.board_settings and ctl.port != SIM_PORT:
            try:
                from .. import board_backup

                board_backup.save(ctl.board_settings, self.info(), tr("Wi-Fi"), ctl.port or "")
            except (OSError, ValueError):
                pass
        steps = [("ssid", ssid)] + ([("password", pwd)] if pwd else []) + [("sta", None)]
        if getattr(self, "switch", None) is not None and self.family == "esp":
            steps.append(("switch", None))  # 0.19.1: senza «$wifi=1» queste schede al riavvio tornano alla rete propria

        def step(i, k=0):
            if g != self._gen:
                return
            if i >= len(steps):
                return self._restart(self._wait)
            what, val = steps[i]
            cands = wifi_setup.commands(self.family, what, self.lgt)
            if k >= len(cands):  # la scheda ha rifiutato tutte le forme di questo comando: niente riavvio a metà
                return self._case_d()
            cmd = cands[k] if val is None else cands[k].format(val)

            def got(ok, _lines):
                if g != self._gen:
                    return
                if ok is None:
                    self._set("mute")
                    return self._page(tr("La scheda non risponde"),
                                      tr("Ha smesso di rispondere mentre scrivevo la rete. Non l'ho riavviata. Controlla "
                                         "il collegamento e riprova."),
                                      [self._close_btn(), ("retry", tr("Riprova"), self.detect)])
                step(i + 1) if ok else step(i, k + 1)
            self.talk.ask(cmd, got)
        step(0)

    def _restart(self, then):
        """Riavvia la scheda con il primo comando che accetta; se nessuno, lo chiede alla persona."""
        g = self._gen
        cands = wifi_setup.commands(self.family or "esp", "restart", self.lgt)

        def step(k):
            if g != self._gen:
                return
            if k >= len(cands):
                self._set("power")
                return self._page(tr("Spegni e riaccendi il laser"),
                                  tr("La rete è scritta nella scheda, ma la scheda non si riavvia da sola: spegni il "
                                     "laser, riaccendilo e premi <i>Fatto</i>."),
                                  [self._close_btn(), ("done", tr("Fatto"), then)])
            self.talk.ask(cands[k], lambda ok, _l: g == self._gen and (then() if ok is not False else step(k + 1)), 2.5)
        step(0)

    def _wait(self):
        self._set("wait")
        self._t0 = time.time()
        self._lost_at = None
        self._msg = None
        self._tried = False  # la scheda ha detto che sta provando a collegarsi («Connecting…»)?
        self._port_back = self.ctl.port
        self._page(tr("La scheda si sta collegando a «{0}»…", self.ssid_sent),
                   tr("Di solito bastano dieci secondi."), [], busy=WAIT_S)
        self._tick.start()
        if self.cordless:  # dalla rete del laser non arrivano messaggi: riporto il PC a casa e poi cerco il laser
            g = self._gen

            def home():
                time.sleep(1.0)
                self._go_back_home_bg()
                self.worked.emit(g, "home", None)
            if self.ctl.connected:
                self.ctl.disconnect_port()
            bg.run(home, self)

    def _go_back_home_bg(self):
        try:
            self.sys.back()
        except Exception:  # noqa: BLE001
            pass
        self.cordless = False

    def _on_board_line(self, line):
        if self.state != "wait":
            return
        m = wifi_setup.parse_message(line)
        if not m:
            return
        if m[0] == "connected" and m[1]:
            self._tick.stop()
            self._connected(m[1])
        elif m[0] == "connecting":
            self._tried = True
        elif m[0] == "failed":
            self._tick.stop()
            self._outcome_failed()
        elif m[0] == "own":
            self._tick.stop()
            # 0.19.1: rete propria ripartita subito, senza nessun tentativo: non è la password, è la scheda che non
            # ha tenuto «rete di casa». Dirlo, invece di far cercare all'utente un errore che non c'è
            if not self._tried and time.time() - self._t0 < NOT_TRIED_S:
                self._outcome_not_tried()
            else:
                self._outcome_failed()
        elif m[0] == "services":
            # 0.19.1: servizi di rete partiti senza rete propria: la scheda è in una rete ma non dice l'indirizzo
            # (Mecpow). Glielo chiedo subito, senza aspettare 30 secondi. Se sta ancora partendo, riprovo al giro dopo
            if m[1].isdigit() and 0 < int(m[1]) < 65536:
                self.port.setValue(int(m[1]))
            g = self._gen
            QTimer.singleShot(1000, lambda: g == self._gen and self.state == "wait" and self._ask_ip_now(g))

    def _ask_ip_now(self, g):
        if not (self.family == "esp" and self.ctl.connected):
            return

        def got(ok, lines):
            ip = wifi_setup.find_ip(" ".join(lines)) if ok else None
            if g == self._gen and self.state == "wait" and ip and ip != "0.0.0.0" and not ip.startswith("192.168.4."):
                self._tick.stop()
                self._connected(ip)
        self.talk.ask("[ESP111]", got)

    def _on_connection(self, ok, _msg):
        if self.state == "wait" and not ok and not self.cordless and self._lost_at is None:
            self._lost_at = time.time()  # la porta è caduta al riavvio: la riapro io

    def _on_tick(self):
        el = time.time() - self._t0
        if self.bar.maximum() > 0:
            self.bar.setValue(min(self.bar.maximum(), int(el * 4)))
        if self.state == "E1":
            new = sorted(self._usb_ports() - self._ports0)
            if new:
                self._tick.stop()
                return self._usb_connect(new[0])
            if el >= USB_WAIT_S:
                self._tick.stop()
                self._usb_missing()
            return
        if self.state != "wait":
            return
        if self._lost_at is not None and not self.ctl.connected:
            if time.time() - self._lost_at > REOPEN_S:
                self._tick.stop()
                return self._outcome_serial()
            if int((time.time() - self._lost_at) * 4) % 8 == 4 and self._port_back and not netport.is_net(self._port_back):
                if self.ctl.connect_port(self._port_back, self.main.profile.baud):
                    self._t0 = time.time() - WAIT_S / 4  # riaperta: il tempo dei messaggi riparte (quasi) da capo
            return
        if el >= WAIT_S and not self.cordless:
            self._tick.stop()
            self._wait_timeout()

    def _wait_timeout(self):
        """Nessun messaggio in 30 secondi: chiedo l'indirizzo alla scheda, se sa dirlo."""
        g = self._gen
        if self.family == "esp" and self.ctl.connected:
            return self.talk.ask("[ESP111]", lambda ok, lines: g == self._gen and self._after_silence(
                wifi_setup.find_ip(" ".join(lines)) if ok else None))
        if self.family == "named" and self.ctl.connected:  # FluidNC lo dice nella risposta a $I
            return self.talk.ask("$I", lambda ok, lines: g == self._gen and self._after_silence(next(
                (m[1] for m in map(wifi_setup.parse_message, lines) if m and m[0] == "connected"), None)))
        self._after_silence(None)

    def _after_silence(self, ip):
        if ip and ip.startswith("192.168.4."):
            return self._outcome_failed()
        if ip and ip != "0.0.0.0":
            return self._connected(ip)
        self._set("unknown")
        self._page(tr("Non so se si è collegata"),
                   tr("La scheda non ha detto niente in 30 secondi. Provo a cercarla in rete."),
                   [self._close_btn(), ("retry", tr("Riprova"), self._page_net),
                    ("find", tr("Trova il laser in rete"), self._find)])

    # ================================================================== esiti
    def _connected(self, ip):
        g = self._set("check")
        self.ip = ip
        self.pc_ip = self.pc_ip or self.sys.local_ip()
        if wifi_setup.same_subnet(ip, self.pc_ip) is False:
            self._set("other_subnet")
            return self._page(tr("Collegata, ma su un'altra rete"),
                              tr("La scheda è entrata in «{0}» con l'indirizzo <b>{1}</b>, mentre questo PC ha <b>{2}</b>: "
                                 "non sono sulla stessa rete (rete per gli ospiti, un altro router, oppure il router "
                                 "tiene separati gli apparecchi). Da qui il laser potrebbe non essere raggiungibile.",
                                 self.ssid_sent, ip, self.pc_ip),
                              [self._close_btn(), ("change", tr("Cambia rete"), self._page_net),
                               ("keep", tr("Va bene così"), lambda: self._check_port(ip))])
        self._check_port(ip)

    def _check_port(self, ip):
        g = self._set("check")
        self._page(tr("Collegata: provo l'indirizzo {0}…", ip), "", [], busy=0)
        self._try_ports(ip, lambda hit: g == self._gen and (self._done(hit["host"], hit["port"], hit) if hit
                                                            else self._outcome_no_port(ip)))

    def _try_ports(self, ip, cb):
        """Prova la porta scelta, poi 8080 e 23. cb(dict | None) nel filo della finestra."""
        g = self._gen
        ports = list(dict.fromkeys([self.port.value(), *wifi_setup.PORTS]))
        self._try_cb = cb

        def work():
            hit = None
            for _ in range(3):  # appena entrata in rete la scheda può metterci un attimo ad accettare collegamenti
                for p in ports:
                    hit = wifi_setup.probe(ip, p, timeout=1.2)
                    if hit:
                        break
                if hit:
                    break
                time.sleep(0.6)
            self.worked.emit(g, "port", hit)
        bg.run(work, self)

    def _done(self, host, port, hit=None, already=False):
        self._set("ok")
        self.result = netport.make_port(host, port)
        netport.remember(self.qs, self.result)
        netport.set_info(self.qs, self.result, self.main.profile.name, (hit or {}).get("ver", ""))
        txt = (tr("La scheda è già nella rete e risponde.") if already else
               tr("✔ Il laser è entrato nella rete «{0}» e risponde.", self.ssid_sent)) if (already or self.ssid_sent) \
            else tr("✔ Ho trovato il laser in rete e risponde.")
        txt += "<br>" + tr("Indirizzo: <b>{0}</b> · porta <b>{1}</b>. L'ho salvato fra i collegamenti.", host, port)
        self._page(tr("Collegamento Wi-Fi pronto"), txt,
                   [("router", tr("Prenota l'indirizzo nel router"), self._show_router), self._close_btn(),
                    ("use", tr("Usa il Wi-Fi adesso"), self._use_now)])

    def _use_now(self):
        """Passa dal cavo al Wi-Fi: scollega, sceglie l'indirizzo salvato e si collega."""
        m = self.main
        if self.ctl.connected and self.ctl.port != self.result:
            self.ctl.disconnect_port()
        m.qs.setValue("port", self.result)
        m.refresh_ports()
        i = m.port_combo.findData(self.result)
        if i >= 0:
            m.port_combo.setCurrentIndex(i)
        if not self.ctl.connected:
            m.toggle_connection(quiet=True)
        self.accept()

    def _outcome_no_port(self, ip):
        self._set("no_port")
        self.result = None
        tried = " · ".join(str(p) for p in dict.fromkeys([self.port.value(), *wifi_setup.PORTS]))
        self._page(tr("È in rete, ma non accetta i comandi"),
                   tr("La scheda ha l'indirizzo <b>{0}</b>, ma non risponde ai comandi sulle porte provate ({1}).<br>"
                      "• Apri <a href='http://{0}'>http://{0}</a> nel browser: se compare la pagina della scheda, lì c'è "
                      "scritta la porta («Telnet»).<br>"
                      "• Poi riprova mettendo quella porta in <i>Avanzate</i>.", ip, tried),
                   [self._close_btn(), ("retry", tr("Riprova"), lambda: self._check_port(ip))])

    def _outcome_not_tried(self):
        self._set("not_tried")
        self.result = None
        self._page(tr("La scheda non ha provato a collegarsi"),
                   tr("La scheda ha accettato nome e password di «{0}», ma al riavvio ha riacceso subito la sua rete "
                      "propria (192.168.4.1) senza provare a entrare nella rete di casa. <b>Non è un problema di "
                      "password o di segnale</b>: su questa scheda la rete di casa si attiva in un modo che "
                      "FreeLaserCut non conosce ancora (dallo schermo del laser, dall'app del produttore o con una "
                      "sua impostazione).<br>• Mandaci un rapporto da <i>Aiuto → Invia un rapporto all'assistenza</i>: "
                      "dentro ci sono le risposte della scheda (senza la password) e possiamo aggiungerla.",
                      self.ssid_sent),
                   [self._close_btn(), ("retry", tr("Riprova"), self._page_net)])

    def _outcome_failed(self):
        self._set("failed")
        why = "".join(f"<br>• {cause_text(c)}" for c in getattr(self, "causes", ["wrong_password"]))
        self._page(tr("Il laser non è entrato nella rete"),
                   tr("La scheda non è riuscita a collegarsi a «{0}» ed è tornata alla sua rete propria (192.168.4.1). "
                      "Le cause più probabili, in ordine:", self.ssid_sent) + why,
                   [self._close_btn(), ("retry", tr("Correggi e riprova"), self._page_net)])

    def _outcome_serial(self):
        self._set("serial_lost")
        self._page(tr("La porta USB non è tornata"),
                   tr("Al riavvio la scheda ha chiuso la porta e in 20 secondi non l'ho più ritrovata. La rete è già "
                      "scritta nella scheda: <b>spegni e riaccendi il laser</b>, poi cercalo in rete."),
                   [self._close_btn(), ("find", tr("Trova il laser in rete"), self._find)])

    # ================================================================== trova il laser in rete
    def _find(self, then_cable=False):
        g = self._set("find")
        self._then_cable = bool(then_cable)
        self._page(tr("Cerco il laser nella rete di casa…"),
                   tr("Guardo solo gli indirizzi della rete locale di questo PC, per una decina di secondi."), [],
                   busy=FIND_S)
        self._t0 = time.time()
        self._tick.start()

        skip = [netport.parse_address(self.ctl.port)] if self.ctl.connected and netport.is_net(self.ctl.port) else []

        def work():
            ip = self.sys.local_ip()
            self.worked.emit(g, "found", (ip, wifi_setup.find_lasers(wifi_setup.subnet_hosts(ip), max_s=FIND_S,
                                                                     skip=skip)))
        bg.run(work, self)

    def _found(self, ip, found):
        self.pc_ip = ip
        self.found = found
        if len(found) == 1:
            return self._done(found[0]["host"], found[0]["port"], found[0])
        if not found:
            self._set("find_none")
            btn = [self._close_btn(), ("retry", tr("Cerca ancora"), self._find)]
            txt = tr("In questa rete non ho trovato nessun laser che risponde.")
            if self._then_cable:
                txt = tr("Non vedo una rete del laser e in questa rete non c'è nessun laser che risponde: per il primo "
                         "passaggio <b>serve il cavo USB</b>.")
            if not self.ctl.connected:
                btn.append(("cable", tr("Uso il cavo USB"), self._e1))
            return self._page(tr("Nessun laser trovato"), txt, btn)
        self._set("find_many")
        self.choice.clear()
        for f in found:
            it = QListWidgetItem(f"{f['host']}:{f['port']}   {f['ver']}")
            it.setData(Qt.UserRole, f)
            self.choice.addItem(it)
        self.choice.setCurrentRow(0)
        self._page(tr("Ho trovato più di un laser"), tr("Scegli quello da usare."),
                   [self._close_btn(), ("pick", tr("Usa questo"), self._pick_found)], choice=True)

    def _pick_found(self):
        f = self.choice.currentItem().data(Qt.UserRole)
        self._done(f["host"], f["port"], f)

    # ================================================================== lavori in secondo piano
    def _on_worked(self, gen, what, res):
        if gen != self._gen:
            return
        if what == "nets":
            self.nets, self.pc_ssid, self.pc_ip = res
            self._fill_nets()
        elif what == "e2":
            self._e2_scanned(*res)
        elif what == "joined":
            self._e2_joined(res)
        elif what == "port":
            self._try_cb(res)
        elif what == "found":
            self._tick.stop()
            self._found(*res)
        elif what == "home":
            QTimer.singleShot(6000 if not os.environ.get("FLC_PROVA_RETE") else 300, lambda: gen == self._gen and self._find())

    # ================================================================== chiusura
    def done(self, r):
        self._gen += 1
        self._tick.stop()
        self.talk.stop()
        self.pwd.clear()
        if self.cordless or self.sys.pending():  # mai lasciare il PC sulla rete del laser
            self._go_back_home()
        for sig, slot in ((self.ctl.line_received, self._on_board_line), (self.ctl.connection_changed, self._on_connection),
                          (self.ctl.info_ready, self._on_info)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(r)


# ====================================================================== all'avvio: la guardia e il laser da ritrovare
def restore_pc_network(system=None):
    """La «guardia»: se FreeLaserCut è stato chiuso mentre il PC era sulla rete del laser (strada senza cavo), al
    prossimo avvio il PC viene riportato sulla rete di prima. Non fa niente se non c'è niente in sospeso.
    -> il filo avviato, oppure None."""
    if not os.path.exists(wifi_setup.guard_path()):
        return None
    sysm = system or wifi_setup.System()

    def work():
        try:
            sysm.back()
        except Exception:  # noqa: BLE001
            pass
    t = threading.Thread(target=work, daemon=True, name="flc-wifi-guardia")
    t.start()
    return t


class _Bridge(QObject):
    done = Signal(object)


def refind(main, last, system=None):
    """All'avvio il laser non risponde all'indirizzo salvato: lo cerco in silenzio nella rete locale. Se lo trovo a
    un altro indirizzo ed è lo stesso di prima, aggiorno l'indirizzo e lo dico nella barra; se no, lo dico e basta."""
    sysm = system or wifi_setup.System()
    info = netport.info(main.qs, last)
    br = _Bridge(main)
    main._wifi_refind = br

    def finish(found):
        hit = wifi_setup.pick_same(found or [], info.get("ver", ""))
        if hit is None or main.ctl.connected:
            main.statusBar().showMessage(tr("Il laser non risponde all'indirizzo salvato: apri Impostazioni → "
                                            "Collegamento Wi-Fi del laser…"), 12000)
            return
        port = netport.make_port(hit["host"], hit["port"])
        if port != last:
            netport.forget(main.qs, last)
        netport.remember(main.qs, port)
        netport.set_info(main.qs, port, info.get("name", "") or main.profile.name, hit["ver"])
        main.qs.setValue("port", port)
        main.refresh_ports()
        i = main.port_combo.findData(port)
        if i >= 0:
            main.port_combo.setCurrentIndex(i)
        main.toggle_connection(quiet=True)
        main.statusBar().showMessage(tr("Il laser ha cambiato indirizzo: l'ho ritrovato a {0} e mi sono collegato lì",
                                        hit["host"]), 12000)

    br.done.connect(finish)

    def work():
        try:
            if sysm.pending():
                sysm.back()
            found = wifi_setup.find_lasers(wifi_setup.subnet_hosts(sysm.local_ip()), max_s=FIND_S)
        except Exception:  # noqa: BLE001
            found = []
        br.done.emit(found)
    threading.Thread(target=work, daemon=True, name="flc-wifi-refind").start()
    return br
