# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Controller GRBL 1.1 per FreeLaserCut.

- Streaming con character-counting (buffer RX di GRBL ~128 byte): la macchina
  non resta mai a secco di comandi e non va mai in overflow.
- Comandi realtime (?, !, ~, Ctrl-X, jog-cancel) fuori dal buffer.
- Lettura di $I e $$ con raccolta delle risposte per comando.
- Segnali Qt thread-safe verso l'interfaccia.
"""
import collections
import re
import threading
import time

from PySide6.QtCore import QObject, Signal
from freelasercut.i18n import tr  # noqa: E402

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None

from .grbl_codes import ALARMS, ERRORS, bad_travel
from .sim import SimSerial
from . import netport

SIM_PORT = "SIMULATORE"
RX_BUFFER = 127
POINTER_MAX = 20.0  # % massimo del puntino (oltre POINTER_WARN FreeLaserCut avvisa)
POINTER_WARN = 5.0
POLL_INTERVAL = 0.2
# 0.18.4: alcune schede (visto su un Creality Falcon A1, ESP32-S3 con USB nativo) ogni tanto non mandano un «ok».
# Se alla fine mancano al massimo LOST_OK_MAX risposte e la scheda è ferma e muta da un po', sono risposte perse:
# la verifica e il lavoro si chiudono normalmente (con un avviso) invece di restare fermi.
LOST_OK_MAX = 3
LOST_OK_CHECK_S = 2.0  # in verifica le risposte arrivano in millesimi di secondo
LOST_OK_JOB_S = 3.0
_SETTING_RE = re.compile(r"^\$(\d+)=(.*)$")
_WRITE_RE = re.compile(r"^\$\d+\s*=")
_DWELL_RE = re.compile(r"G0*4(?!\d)", re.I)  # pausa G4 (non G40, G43…)
_STATUS_RE = re.compile(r"<[^<>]*>")
_OPT_RE = re.compile(r"^\[OPT:([^,\]]*),(\d+),(\d+)")
_USB_HINTS = ("CH340", "CH341", "1A86", "USB-SERIAL", "USB SERIAL", "CP210", "FTDI", "ESP32", "USB JTAG")


def list_serial_ports():
    """Ritorna [(porta, etichetta, probabile_laser)], le porte probabili per prime."""
    out = []
    if list_ports is not None:
        for p in list_ports.comports():
            desc = p.description or ""
            blob = f"{desc} {p.hwid or ''}".upper()
            likely = any(h in blob for h in _USB_HINTS)
            out.append((p.device, f"{p.device} — {desc}", likely))
    out.sort(key=lambda t: (not t[2], t[0]))
    out.append((SIM_PORT, tr("Simulatore (senza macchina)"), False))
    return out


class _Cmd:
    __slots__ = ("line", "tag", "length", "data")

    def __init__(self, line, tag=None):
        self.line = line
        self.tag = tag
        self.length = len(line) + 1
        self.data = {} if tag == "settings" else []


def parse_status(text, last_wco):
    """'<Idle|MPos:1,2,3|FS:0,0|WCO:0,0,0>' -> dict."""
    parts = text.strip().strip("<>").split("|")
    state = parts[0].split(":")[0]
    st = {"state": state, "substate": parts[0], "feed": 0.0, "power": 0.0}
    for p in parts[1:]:
        key, _, val = p.partition(":")
        try:
            if key in ("MPos", "WPos", "WCO"):
                st[key] = [float(v) for v in val.split(",")]
            elif key == "FS":
                f = val.split(",")
                st["feed"] = float(f[0])
                st["power"] = float(f[1]) if len(f) > 1 else 0.0
            elif key == "F":
                st["feed"] = float(val)
            elif key == "Ov":
                st["ov"] = [int(v) for v in val.split(",")]
            elif key == "Bf":
                st["buffer"] = [int(v) for v in val.split(",")]
            elif key == "Pn":
                st["pins"] = val
        except ValueError:
            pass
    if "WCO" not in st and "MPos" in st and "WPos" in st:
        # il firmware del B1 manda MPos e WPos ma non WCO: lo ricavo dalla differenza
        st["WCO"] = [m - w for m, w in zip(st["MPos"], st["WPos"])]
    wco = st.get("WCO", last_wco)
    st["WCO"] = wco
    if "MPos" in st and "WPos" not in st:
        st["WPos"] = [m - w for m, w in zip(st["MPos"], wco)]
    elif "WPos" in st and "MPos" not in st:
        st["MPos"] = [w + c for w, c in zip(st["WPos"], wco)]
    return st


def _garbled(line):
    """Riga illeggibile: soprattutto caratteri sostituiti (�) o di controllo."""
    if len(line) < 6:
        return False
    bad = sum(1 for ch in line if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\t"))
    return bad >= 0.25 * len(line)


class GrblController(QObject):
    connection_changed = Signal(bool, str)  # connesso?, messaggio
    line_received = Signal(str)
    line_sent = Signal(str)
    status_changed = Signal(object)  # dict
    alarm_raised = Signal(int, str)
    error_raised = Signal(int, str, str)  # codice, testo, riga che l'ha causato
    message = Signal(str)  # [MSG:...] e banner
    settings_ready = Signal(object)  # {numero: "valore"}
    travel_suspect = Signal(object)  # [(numero, "valore")]: $130/$131 non credibili anche alla seconda lettura
    info_ready = Signal(object)  # ["[VER:...]", "[OPT:...]"]
    job_progress = Signal(int, int)  # fatte, totali
    job_finished = Signal(bool, str)  # completato?, messaggio
    homed_changed = Signal(bool, object)  # homing fatto?, spazio macchina negativo? (None = non ancora noto)
    job_error = Signal(int, str, int, str)  # indice riga, riga, codice, spiegazione (il lavoro è già in pausa)
    check_finished = Signal(object)  # [(indice, riga, codice, spiegazione)] — verifica $C conclusa; None = interrotta
    check_progress = Signal(int, int)
    autofocus_done = Signal(bool, str, object)  # riuscito?, messaggio, Z del tocco (coordinate macchina) o None

    def __init__(self):
        super().__init__()
        self._ser = None
        self.port = None
        self._running = False
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        # un solo _pump per volta (finestra e lettura della scheda lo chiamano da thread diversi): altrimenti due
        # gruppi di righe potevano partire in ordine diverso da quello delle risposte attese
        self._pump_lock = threading.RLock()
        self._pending = collections.deque()
        self._inflight = collections.deque()
        self._wco = [0.0, 0.0, 0.0]
        self.last_status = {"state": "Disconnesso"}
        self.status_time = 0.0
        self.rx_buffer = RX_BUFFER
        self.homed = False
        self.negative_space = None
        self._check_space = False
        self._home_alarm = False  # allarme arrivato mentre l'homing era in corso: quell'homing non vale
        self._last_alarm = (0, 0.0)  # (codice, ora): un riavvio subito dopo un allarme ne è la conseguenza
        self._job_total = 0
        self._job_done = 0
        self._job_active = False
        self._job_idle = 0  # report "Idle" di fila dopo l'ultima riga confermata
        self.job_lines = []  # righe del lavoro in corso (per la ripresa)
        self.job_acked = 0  # righe confermate dalla scheda
        self.pause_on_error = True
        self._check = None  # verifica in corso: {"total", "done", "errors"}
        self.board_settings = {}  # ultimo $$ letto dalla scheda {numero: "valore"}
        self.board_info = []  # ultimo $I
        self._backup_done = False  # copia delle impostazioni già fatta in questa connessione
        self._travel_retry = False  # $130/$131 non credibili: ho già riletto $$ una volta
        self.line_resets = 0  # riavvii dalle linee DTR/RTS (0.17.3)
        self.baud = 115200  # velocità della porta seriale aperta
        self.last_backup = None
        self.auto_backup = True
        self.last_reply = 0.0  # ora dell'ultimo ok/error ricevuto
        self.axis_sign = (1.0, 1.0)  # dal profilo: -1 sugli assi invertiti
        self.stale_check_exit = False  # sto facendo uscire la scheda da un check mode rimasto acceso
        self.trusted_buffer = False  # scheda nota: uso tutto il buffer dichiarato in [OPT]
        self.check_stalled = False  # l'ultima verifica non ha ricevuto tutte le risposte
        self.lost_replies = 0  # 0.18.4: risposte «ok» mai arrivate alla fine dell'ultima verifica o dell'ultimo lavoro
        self.no_g55 = False  # la scheda ha risposto error:20 a G55
        self._check_end_t = 0.0
        self._fire_timer = None
        self.fire_active = False
        self._af = None  # autofocus in corso: {"z": Z del tocco}

    # ------------------------------------------------------------------ porta
    @property
    def connected(self):
        return self._ser is not None

    def connect_port(self, port, baud=115200):
        self.disconnect_port()
        try:
            if port == SIM_PORT:
                ser = SimSerial()
            elif netport.is_net(port):  # Wi-Fi / cavo di rete (FluidNC, grblHAL, ESP3D: telnet)
                ser = netport.NetSerial.from_port(port)
            else:
                if serial is None:
                    raise RuntimeError(tr("pyserial non è installato"))
                ser = serial.Serial(port, baud, timeout=0.1, write_timeout=2)
        except Exception as exc:  # noqa: BLE001
            from . import linux

            hint = linux.serial_hint(port, exc)  # Linux: manca il permesso del gruppo dialout (0.18.0)
            self.connection_changed.emit(False, f"Impossibile aprire {port}: {exc}" + (f"\n{hint}" if hint else ""))
            return False
        self._ser = ser
        self.port = port
        self.baud = int(baud or 115200)
        self._travel_retry = False
        self.rx_buffer = RX_BUFFER  # prudente finché $I non dice quanto è grande
        self.homed = False
        self._check_space = False
        self.board_settings = {}
        self.board_info = []
        self._backup_done = False
        self.stale_check_exit = False
        self.trusted_buffer = False
        self.check_stalled = False
        self.lost_replies = 0
        self.no_g55 = False
        self.last_reply = time.time()
        self._check = None
        self._clear_queues()
        self._running = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._write_raw(b"\r\n\r\n")
        self.connection_changed.emit(True, f"Connesso a {port}")
        # le schede Arduino si resettano all'apertura: attendo il banner
        threading.Timer(1.5, self._after_connect).start()
        t0 = time.time()
        threading.Timer(self.WAKE_AFTER_S, lambda: self._wake_if_silent(t0)).start()
        return True

    WAKE_AFTER_S = 2.5

    def _wake_if_silent(self, t0):
        """Alcune schede ESP32 (per esempio con il chip USB CH9102) dopo l'apertura della porta restano mute finché non
        si preme il loro pulsante di reset. Se in questi secondi la scheda non ha mai risposto, le mando un reset
        morbido (Ctrl+X, come il pulsante «reset» di GRBL): una scheda muta non sta eseguendo niente per noi.
        Una volta sola; niente in Wi-Fi e con il simulatore. Se non basta, la finestra principale lo dice."""
        if not self.connected or self.port == SIM_PORT or netport.is_net(self.port or ""):
            return False
        if self.status_time > t0 or self.last_reply > t0:
            return False
        self.message.emit(tr("La scheda non risponde: le mando un reset (Ctrl+X), come il pulsante sulla scheda"))
        self.realtime(0x18)
        self._clear_queues()  # $I e $$ mandati prima sono persi: li richiedo quando la scheda è ripartita

        def again():
            if not self.connected:
                return
            if self.status_time <= t0 and self.last_reply <= t0 and self._line_reset():
                # 0.17.3: muta anche dopo il Ctrl+X (visto con CH9102 + grblHAL: all'apertura della porta l'ESP32
                # finisce in modalità di programmazione, dove GRBL non gira). Riavvio vero dalle linee della porta,
                # come il pulsante: poi la scheda ha bisogno di qualche secondo per ripartire.
                threading.Timer(self.BOOT_WAIT_S, again_info).start()
                return
            again_info()

        def again_info():
            if self.connected:
                self.request_info()
                self.request_settings()
        threading.Timer(1.5, again).start()
        return True

    BOOT_WAIT_S = 3.0  # dopo il riavvio dalle linee DTR/RTS: avvio dell'ESP32 e di GRBL

    def _line_reset(self):
        """Riavvio dalla porta USB, come il pulsante di reset di una scheda ESP32: è la sequenza dello strumento
        ufficiale di programmazione (esptool, «hard reset»). DTR spento = pin di avvio libero, quindi la scheda
        riparte normale e non in programmazione; RTS acceso per un attimo = reset. Le due linee restano spente.
        Solo porte seriali vere; False se la porta non le gestisce."""
        from .machines import hard_reset

        ser = self._ser
        if ser is None or self.port == SIM_PORT or netport.is_net(self.port or "") \
                or not hasattr(ser, "dtr") or not hasattr(ser, "rts"):
            return False
        self.message.emit(tr("La scheda non risponde nemmeno al Ctrl+X: la riavvio dalla porta USB, come il pulsante "
                             "di reset"))
        if not hard_reset(ser):  # porta che non gestisce le linee: resta l'avviso della finestra
            return False
        self.line_resets += 1
        return True

    def _after_connect(self):
        if self.connected:
            self.request_info()
            self.request_settings()

    def disconnect_port(self, reason=None):
        ser = self._ser
        if ser is None:
            return
        self._running = False
        self._ser = None
        try:
            ser.write(b"M5\n")
            ser.close()
        except Exception:  # noqa: BLE001
            pass
        self._clear_queues()
        self._end_check(None)
        if self._af is not None:
            self._af_fail(tr("Connessione chiusa durante l'autofocus."))
        if self._job_active:
            self._job_active = False
            self.job_finished.emit(False, tr("Connessione chiusa durante il lavoro"))
        self.last_status = {"state": "Disconnesso"}
        self.connection_changed.emit(False, reason or "Disconnesso")

    # --------------------------------------------------------------- scrittura
    def _write_raw(self, data):
        ser = self._ser
        if ser is None:
            return
        try:
            with self._wlock:
                ser.write(data)
        except Exception as exc:  # noqa: BLE001
            self.disconnect_port(tr("Errore di scrittura: {0}", exc))

    def _clear_queues(self):
        with self._lock:
            self._pending.clear()
            self._inflight.clear()

    def send_line(self, line, tag=None):
        line = line.strip()
        if not line or not self.connected:
            return
        if (tag is None and not self._backup_done and _WRITE_RE.match(line) and self.board_settings
                and self.port != SIM_PORT):
            # prima di cambiare un'impostazione della scheda: copia di tutte le impostazioni ($$)
            self._backup_done = True
            try:
                from . import board_backup

                self.last_backup = board_backup.save(self.board_settings, self.board_info,
                                                     tr("prima della modifica {0}", line), self.port or "")
            except (OSError, ValueError):
                self.last_backup = None
        with self._lock:
            self._pending.append(_Cmd(line, tag))
        self._pump()

    def _pump(self):
        with self._pump_lock:
            to_send = []
            with self._lock:
                used = sum(c.length for c in self._inflight)
                while self._pending and used + self._pending[0].length <= self.rx_buffer:
                    cmd = self._pending.popleft()
                    self._inflight.append(cmd)
                    used += cmd.length
                    to_send.append(cmd)
            for cmd in to_send:
                self._write_raw((cmd.line + "\n").encode())
                if cmd.tag != "job":
                    self.line_sent.emit(cmd.line)

    def realtime(self, byte):
        self._write_raw(bytes([byte]) if isinstance(byte, int) else byte)

    # --------------------------------------------------------- comandi utente
    def request_settings(self):
        self.send_line("$$", tag="settings")

    def request_info(self):
        self.send_line("$I", tag="info")

    def write_setting(self, number, value):
        self.send_line(f"${number}={value}")

    def home(self):
        self._home_alarm = False
        self.send_line("$H")

    def unlock(self):
        self.send_line("$X")

    def soft_reset(self):
        self.realtime(0x18)
        self._clear_queues()
        if self._af is not None:
            self._af_fail(tr("Autofocus interrotto."))
        self._end_check(None)
        if self._job_active:
            self._job_active = False
            self.job_finished.emit(False, "Lavoro interrotto (reset)")

    def feed_hold(self):
        self.realtime(b"!")

    def resume(self):
        self.realtime(b"~")

    def jog(self, dx=0.0, dy=0.0, feed=3000):
        sx, sy = self.axis_sign  # assi invertiti nel profilo: «su» sul piano resta «su» per la testa
        dx, dy = dx * sx, dy * sy
        parts = []
        if dx:
            parts.append(f"X{dx:.3f}")
        if dy:
            parts.append(f"Y{dy:.3f}")
        if parts:
            self.send_line(f"$J=G91 G21 {' '.join(parts)} F{feed:.0f}")

    def jog_to(self, x, y, feed=6000):
        """Va a una posizione assoluta di lavoro (doppio clic sul piano)."""
        self.send_line(f"$J=G90 G21 X{x:.3f} Y{y:.3f} F{feed:.0f}")

    def jog_cancel(self):
        self.realtime(0x85)

    def set_work_origin(self):
        self.send_line("G10 L20 P1 X0 Y0")

    def go_to_origin(self, feed=6000):
        self.send_line(f"$J=G90 G21 X0 Y0 F{feed:.0f}")

    def air(self, on):
        self.send_line("M8" if on else "M9")

    @property
    def wco(self):
        return tuple(self._wco[:2])

    def frame(self, min_x, min_y, max_x, max_y, feed=6000):
        """Contorno: la testa percorre il perimetro del lavoro a laser spento (jog)."""
        pts = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)]
        for x, y in pts:
            self.send_line(f"$J=G90 G21 X{x:.3f} Y{y:.3f} F{feed:.0f}")

    def goto_machine(self, x, y, feed=6000):
        """Spostamento in coordinate macchina (G53), a laser spento."""
        self.send_line(f"$J=G53 G21 X{x:.3f} Y{y:.3f} F{feed:.0f}")

    # ------------------------------------------------------- invio di un lavoro
    def stream_job(self, lines):
        if self.last_status.get("state") == "Check" or self.stale_check_exit:
            self.exit_stale_check()
            self.job_finished.emit(False, tr("La scheda era ancora in modalità di prova: la sto facendo uscire. "
                                             "Riprova tra qualche secondo."))
            return
        clean = _clean_lines(lines)
        if not clean:
            self.job_finished.emit(False, tr("Il file non contiene comandi G-code"))
            return
        too_long = self._too_long(clean)
        if too_long:
            self.job_finished.emit(False, too_long)
            return
        self._job_total = len(clean)
        self._job_done = 0
        self._job_idle = 0
        self._job_active = True
        self.job_lines = clean
        self.job_acked = 0
        self.lost_replies = 0
        self.last_reply = time.time()  # 0.18.4: il silenzio si conta da qui (risposte perse alla fine del lavoro)
        with self._lock:
            for i, line in enumerate(clean):
                c = _Cmd(line, "job")
                c.data = i
                self._pending.append(c)
        self.job_progress.emit(0, self._job_total)
        self._pump()

    # ------------------------------------------------------- verifica ($C)
    def check_job(self, lines):
        """Fa analizzare il lavoro alla scheda in modalità di controllo: nessun movimento, nessun laser.
        Alla fine la scheda fa un reset morbido (la posizione resta valida)."""
        clean = [(i, l) for i, l in enumerate(_clean_lines(lines))]
        if not clean or not self.connected:
            return False
        state = self.last_status.get("state")
        if state == "Check" or self.stale_check_exit:
            return False  # scheda ancora in modalità di prova: un altro $C la farebbe uscire e partire davvero
        if state != "Idle" or self._job_active or self._check is not None or self.busy:
            # $C si accetta solo a macchina ferma: altrimenti la scheda risponde error:8, NON entra in prova e le
            # righe accodate dietro verrebbero eseguite davvero, con il laser (per esempio durante un contorno)
            self.message.emit(tr("Verifica non avviata: la macchina non è ferma ({0}). Aspetta che finisca, poi riprova.",
                                 state or "?"))
            return False
        too_long = self._too_long(l for _, l in clean)
        if too_long:
            self.message.emit(too_long)
            return False
        self._check = {"total": len(clean), "done": 0, "errors": [], "exiting": False, "lines": clean}
        self.lost_replies = 0
        self.last_reply = time.time()
        self.send_line("$C", tag="check_enter")  # le righe partono solo dopo il suo «ok» (vedi _finish)
        return True

    def _too_long(self, lines):
        """Una riga più lunga del buffer della scheda non partirebbe mai e il lavoro resterebbe fermo in silenzio."""
        for n, l in enumerate(lines):
            if len(l) + 1 > self.rx_buffer:
                return tr("Riga {0} troppo lunga per la scheda ({1} caratteri, al massimo {2}): il lavoro non è partito.",
                          n + 1, len(l), self.rx_buffer - 1)
        return None

    @property
    def checking(self):
        return self._check is not None

    def exit_stale_check(self):
        """La scheda è rimasta in modalità di prova (verifica interrotta, FreeLaserCut chiuso a metà): la faccio uscire.
        GRBL esce con un reset morbido: finché non arriva il banner non mando altro."""
        if self._check is not None or self.stale_check_exit or not self.connected:
            return
        self.stale_check_exit = True
        self._clear_queues()
        # niente riga vuota prima: GRBL risponde «ok» anche a quella e le risposte successive slitterebbero di una
        self.send_line("$C", tag="check_exit_stale")
        self.message.emit(tr("La scheda era rimasta in modalità di prova ($C): la faccio uscire"))
        threading.Timer(4.0, self._stale_timeout).start()

    def _stale_timeout(self):
        if self.stale_check_exit:  # nessun banner: riprovo con un reset
            self.stale_check_exit = False
            self.soft_reset()

    def _end_check(self, result):
        """Chiude la verifica (se ce n'è una): result = elenco degli errori, None = interrotta.
        Sotto il lucchetto: con il controllo delle risposte perse la verifica si chiude una volta sola."""
        with self._lock:
            if self._check is None:
                return
            self._check = None
        self._check_end_t = time.time()
        self.check_finished.emit(result)

    def stream_baud(self, default=115200):
        """Velocità della porta per la stima dei comandi al secondo (gcode.stream_vmax): quella aperta, o default se
        la macchina non è collegata. None in Wi-Fi e con il simulatore (lì la porta seriale non c'è)."""
        if self.connected:
            if self.port == SIM_PORT or netport.is_net(self.port or ""):
                return None
            return self.baud
        return default

    def soft_limits(self):
        """Limiti software attivi sulla scheda ($20=1): corsa ($130, $131) in mm, altrimenti None."""
        s = self.board_settings
        try:
            if float(s.get(20, 0)) < 1:
                return None
            tx, ty = float(s.get(130, 0)), float(s.get(131, 0))
        except (TypeError, ValueError):
            return None
        return (tx, ty) if tx > 0 and ty > 0 else None

    # ------------------------------------------------------- override dal vivo
    def set_override(self, kind, pct):
        """kind: feed | power. pct 10..200. Comandi realtime GRBL (non passano dal buffer)."""
        pct = int(max(10, min(200, round(pct))))
        reset, p10, m10, p1, m1 = (0x90, 0x91, 0x92, 0x93, 0x94) if kind == "feed" else (0x99, 0x9A, 0x9B, 0x9C, 0x9D)
        seq = [reset]
        d = pct - 100
        seq += [p10 if d > 0 else m10] * (abs(d) // 10)
        seq += [p1 if d > 0 else m1] * (abs(d) % 10)
        self._write_raw(bytes(seq))

    # ------------------------------------------------------- fire (puntatore a bassa potenza)
    def fire(self, on, pct=1.0, max_pct=POINTER_MAX, timeout_s=20.0, s_max=1000.0):
        if on:
            if self._job_active:
                return False
            pct = max(0.1, min(pct, max_pct))
            self.send_line(f"M3 S{pct / 100.0 * s_max:.1f}")
            self.send_line("G1 F1000")
            self.fire_active = True
            if self._fire_timer is not None:
                self._fire_timer.cancel()
            self._fire_timer = threading.Timer(timeout_s, lambda: self.fire(False))  # spegnimento automatico
            self._fire_timer.start()
        else:
            if self._fire_timer is not None:
                self._fire_timer.cancel()
                self._fire_timer = None
            if self.fire_active or self.connected:
                self.send_line("M5 S0")
            self.fire_active = False
        return True

    def frame_path(self, points, feed=6000, laser_pct=0.0, s_max=1000.0):
        """Percorre una spezzata in coordinate macchina: a laser spento con il jog (interrompibile),
        oppure con un filo di laser per vedere il contorno sul materiale."""
        if not points:
            return
        if laser_pct <= 0:
            for x, y in points:
                self.send_line(f"$J=G53 G21 X{x:.3f} Y{y:.3f} F{feed:.0f}")
            return
        x0, y0 = points[0]
        self.send_line(f"G53 G0 X{x0:.3f} Y{y0:.3f}")
        self.send_line(f"M3 S{min(laser_pct, POINTER_MAX) / 100.0 * s_max:.1f}")
        for x, y in points[1:]:
            self.send_line(f"G53 G1 X{x:.3f} Y{y:.3f} F{feed:.0f}")
        self.send_line("M5 S0")

    # ------------------------------------------------------------- autofocus
    @property
    def autofocusing(self):
        return self._af is not None

    def jog_z(self, dz, feed=300):
        if dz:
            self.send_line(f"$J=G91 G21 Z{dz:.3f} F{feed:.0f}")

    def autofocus(self, distance, travel, feed, slow, toward_minus=True):
        """0.17.12: autofocus con sonda (G38.2). Ritorna False (con il motivo in autofocus_done) se non può partire.
        Alla fine: autofocus_done(True, messaggio, z del tocco) oppure (False, motivo, None)."""
        from . import autofocus as af

        why = None
        if not self.connected:
            why = tr("Collega prima il laser.")
        elif self._job_active or self._check is not None or self._af is not None:
            why = tr("C'è già qualcosa in corso: aspetta che la macchina sia ferma.")
        elif self.last_status.get("state") not in ("Idle",):
            why = tr("La macchina non è ferma e pronta (stato: {0}). Se è in allarme, sbloccala o fai l'homing.",
                     self.last_status.get("state", "?"))
        elif af.pin_state(self.last_status.get("pins")) == "touch":
            why = af.explain_alarm(4)
        if why:
            self.autofocus_done.emit(False, why, None)
            return False
        self._af = {"z": None}
        cmds = af.lines(distance, travel, feed, slow, toward_minus)
        for i, line in enumerate(cmds):
            self.send_line(line, tag="af_end" if i == len(cmds) - 1 else "af")
        return True

    def _af_fail(self, why):
        """Autofocus fermato: niente più righe dell'autofocus, la scheda torna in coordinate assolute."""
        with self._lock:
            self._pending = collections.deque(c for c in self._pending if c.tag not in ("af", "af_end"))
        self._af = None
        self.autofocus_done.emit(False, why, None)

    def stop_job(self):
        """Arresto sicuro: pausa immediata, poi reset (svuota il buffer), laser spento."""
        self.feed_hold()
        time.sleep(0.15)
        self.soft_reset()

    @property
    def job_active(self):
        return self._job_active

    @property
    def busy(self):
        with self._lock:
            return bool(self._pending or self._inflight)

    @property
    def sim(self):
        """L'oggetto simulatore, se connessi al simulatore (per la camera simulata)."""
        return self._ser if isinstance(self._ser, SimSerial) else None

    # ----------------------------------------------------------------- lettura
    CHECK_STALL_S = 6.0  # in modalità di prova le risposte arrivano subito: 6 s senza risposte = ferma

    def _poll_loop(self):
        while self._running:
            self._write_raw(b"?")
            time.sleep(POLL_INTERVAL)
            self._watch_check()

    def _watch_check(self):
        lost = []
        with self._lock:
            chk = self._check
            waiting = len(self._inflight)
            quiet = time.time() - self.last_reply
            if (chk is not None and waiting and not self._pending and not chk["exiting"]
                    and waiting <= LOST_OK_MAX and quiet > LOST_OK_CHECK_S
                    and all(c.tag == "check" for c in self._inflight)):
                # 0.18.4: tutte le righe sono partite e ne mancano solo poche: la scheda ha perso le loro risposte
                lost = list(self._inflight)
                self._inflight.clear()
            stalled = (not lost and chk is not None and waiting and quiet > self.CHECK_STALL_S)
            if stalled:
                self._check = None  # sotto il lucchetto: il filo di lettura non la chiude due volte
        if lost:
            self.lost_replies = len(lost)
            chk["done"] += len(lost)
            self.check_progress.emit(chk["done"], chk["total"])
            self.message.emit(tr("La scheda non ha risposto alle ultime {0} righe della verifica (risposte perse, "
                                 "succede con alcune schede con l'USB nativo): le considero controllate.", len(lost)))
            chk["exiting"] = True
            self.send_line("$C", tag="check_exit")
            return
        if stalled:
            # la scheda non risponde più (risposte perse): chiudo la verifica invece di restare fermo,
            # passo al buffer prudente e la faccio uscire dalla modalità di prova
            self.check_stalled = True
            was_big = self.rx_buffer > RX_BUFFER
            self.rx_buffer = RX_BUFFER
            errs = list(chk["errors"])
            if was_big:
                why = tr("La scheda ha smesso di rispondere durante la verifica ({0} righe "
                         "senza risposta). FreeLaserCut passa a una comunicazione più "
                         "prudente: rifai la verifica.", waiting)
            else:  # 0.18.4: la comunicazione era già prudente, rifare la verifica darebbe lo stesso risultato
                why = tr("La scheda ha smesso di rispondere durante la verifica ({0} righe senza risposta). Prova a "
                         "scollegare e ricollegare il cavo USB; se succede ancora, togli la spunta «Verifica il "
                         "G-code con la scheda prima di partire» e manda un rapporto "
                         "all'assistenza.", waiting)
            errs.append((-1, "", "NO_RISPOSTA", why))
            self._check_end_t = time.time()
            self._clear_queues()
            self.check_finished.emit(errs)
            self.exit_stale_check()

    def _watch_job_end(self):
        """0.18.4: tutte le righe sono partite, la macchina è ferma (Idle) e la scheda è muta da qualche secondo,
        ma mancano al massimo LOST_OK_MAX conferme: le risposte si sono perse e il lavoro è finito."""
        with self._lock:
            n = len(self._inflight)
            # le conferme arrivano in ordine: quelle che mancano sono sempre delle ultime righe, ma la risposta persa
            # può essere di una riga poco prima. Con una pausa G4 fra le ultime righe la scheda potrebbe essere
            # ancora ferma ad aspettare (in pausa risulta Idle): lì non decido io
            tail = self.job_lines[-(n + LOST_OK_MAX):] if n else []
            ok = (not self._pending and 0 < n <= LOST_OK_MAX
                  and all(c.tag == "job" for c in self._inflight)
                  and not any(_DWELL_RE.search(l) for l in tail)
                  and time.time() - self.last_reply > LOST_OK_JOB_S)
            if not ok:
                self._job_idle = 0
                return
            self._job_idle += 1
            if self._job_idle < 2:  # due report Idle di fila, come per la fine normale
                return
            lost = list(self._inflight)
            self._inflight.clear()
        self.lost_replies = len(lost)
        self._job_done = self._job_total
        self.job_acked = self._job_total
        self.job_progress.emit(self._job_done, self._job_total)
        self._job_active = False
        self.job_finished.emit(True, tr("Lavoro completato: {0} righe (la scheda non ha confermato le ultime {1}: "
                                        "risposte perse, la macchina ha finito)", self._job_total, len(lost)))

    def _read_loop(self):
        while self._running:
            ser = self._ser
            if ser is None:
                break
            try:
                raw = ser.readline()
            except Exception as exc:  # noqa: BLE001
                if self._running:
                    self.disconnect_port(f"Connessione persa: {exc}")
                break
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line:
                try:
                    self._dispatch(line)
                except Exception:  # noqa: BLE001  un errore su una riga non deve fermare la lettura della scheda
                    import traceback

                    traceback.print_exc()

    def _dispatch(self, line):
        """Le schede ESP32 (come quella del B1) possono infilare un report di stato <...>
        in mezzo a un'altra riga, es. '$134=300.000<Idle|...>' oppure 'o<Idle|...>k'.
        Separo i report e ricompongo il resto, così nessun 'ok' va perso."""
        if "<" in line and ">" in line:
            for st in _STATUS_RE.findall(line):
                self._handle(st)
            line = _STATUS_RE.sub("", line).strip()
            if not line:
                return
        self._handle(line)

    def _handle(self, line):
        if line.startswith("<"):
            st = parse_status(line, self._wco)
            self._wco = st["WCO"]
            self.last_status = st
            if (st["state"] == "Check" and self._check is None and not self.stale_check_exit
                    and time.time() - self._check_end_t > 3.0):  # subito dopo una verifica il report può essere vecchio
                self.exit_stale_check()
            self.status_time = time.time()
            if self._check_space and st["state"] == "Idle" and "MPos" in st:
                # dopo l'homing: GRBL classico mette la macchina in coordinate negative (0 = fondo corsa)
                self._check_space = False
                mx, my = st["MPos"][0], st["MPos"][1]
                self.negative_space = mx < -1.0 or my < -1.0
                self.homed = True
                self.homed_changed.emit(True, self.negative_space)
            if self._job_active and self._job_done >= self._job_total:
                # tutte le righe sono nella scheda, ma gli ultimi movimenti sono ancora nel suo buffer:
                # il lavoro è finito solo quando la macchina è ferma (due report Idle di fila)
                self._job_idle = self._job_idle + 1 if st["state"] == "Idle" else 0
                if self._job_idle >= 2:
                    self._job_active = False
                    self.job_finished.emit(True, f"Lavoro completato: {self._job_total} righe")
            elif self._job_active and st["state"] == "Idle":
                self._watch_job_end()
            elif self._job_active:
                self._job_idle = 0
            self.status_changed.emit(st)
            return

        is_ok = line == "ok"
        is_err = line.startswith("error")
        if is_ok or is_err:
            self.last_reply = time.time()
            with self._lock:
                head = self._inflight.popleft() if self._inflight else None
            if head is not None and head.tag != "job":
                self.line_received.emit(line)
            if is_err:
                code = _code(line)
                text = ERRORS.get(code, "Errore sconosciuto")
                chk = self._check
                if head is not None and head.tag == "check" and chk is not None:
                    chk["errors"].append((head.data, head.line, code, text))
                    if code == 20 and head.line.strip().upper() == "G55":
                        self.no_g55 = True
                elif head is not None and head.tag == "job" and self._job_active and self.pause_on_error:
                    # sicurezza: alla prima riga rifiutata il lavoro si ferma subito in pausa
                    self.feed_hold()
                    self.job_error.emit(int(head.data), head.line, code, text)
                    self.error_raised.emit(code, text, head.line)
                elif head is not None and head.tag in ("af", "af_end") and self._af is not None:
                    if code == 20 and "G38" in head.line.upper():
                        why = tr("La scheda non conosce il comando della sonda (G38.2): il suo firmware non ha "
                                 "l'autofocus con sonda.")
                    else:
                        why = tr("La scheda ha rifiutato «{0}»: {1}", head.line, text)
                    self._af_fail(why)
                    if head.tag == "af":
                        self.send_line("G90")
                    head = None  # già gestita
                elif head is None or head.tag != "check_enter":  # il $C rifiutato lo spiega già la verifica
                    self.error_raised.emit(code, text, head.line if head else "")
            if head is not None:
                self._finish(head, is_ok)
            self._pump()
            return

        if _garbled(line):
            # 0.17.3: l'ESP32 all'avvio scrive i suoi messaggi a 115200 baud: a un'altra velocità sono caratteri
            # illeggibili. Nella console una riga che lo spiega, invece di una riga di simboli
            self.line_received.emit(tr("(messaggio di avvio della scheda a un'altra velocità: illeggibile, è normale)"))
            return
        self.line_received.emit(line)
        if line.startswith("[PRB:") and self._af is not None:
            # [PRB:x,y,z:1] posizione macchina del tocco; :0 = nessun tocco
            body = line[5:].rstrip("]")
            pos, _, ok = body.rpartition(":")
            try:
                if ok.strip() == "1":
                    self._af["z"] = float(pos.split(",")[2])
            except (IndexError, ValueError):
                pass
        if line.startswith("ALARM") and self._af is not None:
            from . import autofocus as af

            code = _code(line)
            with self._lock:  # la scheda in allarme rifiuta il resto: lo tolgo io
                self._pending.clear()
                self._inflight.clear()
            self._af_fail(af.explain_alarm(code))
            self.realtime(0x18)  # reset: la scheda torna in coordinate assolute (G90), resta da sbloccare
        if line.startswith("ALARM"):
            code = _code(line)
            with self._lock:
                homing = any(c.line.strip().upper().replace(" ", "") == "$H" for c in list(self._inflight) + list(self._pending))
            self._last_alarm = (code, time.time())
            if homing or self._check_space:
                # homing non riuscito (es. 6 = reset durante l'homing, 8/9 = finecorsa non trovato): la posizione letta
                # dopo non è lo zero della macchina e non deve decidere come sono le coordinate
                self._home_alarm = True
                self._check_space = False
            check = self._check
            if check is not None:
                # allarme durante la verifica (es. 2 = limiti software): la scheda ha scartato tutto e aspetta un
                # reset. La riga colpevole è la prima non ancora confermata.
                with self._lock:
                    head = next((c for c in self._inflight if c.tag == "check"), None)
                    self._pending.clear()
                    self._inflight.clear()
                text = ALARMS.get(code, "Allarme sconosciuto")
                errs = list(check["errors"])
                errs.append((int(head.data) if head is not None else -1, head.line if head is not None else "",
                             f"ALARM:{code}", text))
                self._check = None
                self._check_end_t = time.time()
                self.realtime(0x18)  # esce dallo stato critico: la testa è ferma (verifica), resta solo da sbloccare
            if code in (1, 2, 3, 6, 7, 8, 9, 10) and self.homed:
                self.homed = False  # posizione non più garantita
                self.homed_changed.emit(False, self.negative_space)
            if self._job_active and self._job_done >= self._job_total:
                # allarme mentre la scheda finiva gli ultimi movimenti: il lavoro non è completo
                self._job_active = False
                self.job_finished.emit(False, tr("Lavoro interrotto da un allarme della macchina"))
            self.alarm_raised.emit(code, ALARMS.get(code, "Allarme sconosciuto"))
            if check is not None:
                self.check_finished.emit(errs)
            return
        if line.lower().startswith("grbl"):
            # la scheda si è riavviata: tutto ciò che era in volo è perso (anche un homing a metà)
            self._clear_queues()
            self._check_space = False
            self.stale_check_exit = False
            chk = self._check
            if chk is not None:
                # fine normale (uscita dal check mode) oppure reset a metà verifica
                self._end_check(chk["errors"] if chk.get("exiting") else None)
            if self._job_active:
                # riavvio a metà lavoro (calo di tensione, watchdog): il lavoro è perso, non «ancora in corso»
                self._job_active = False
                code, t = self._last_alarm
                if code and time.time() - t < 3.0:  # la scheda si è riavviata da sola dopo un allarme: dico quale
                    self.job_finished.emit(False, tr("Lavoro interrotto dall'allarme {0}: {1}", code,
                                                     ALARMS.get(code, "Allarme sconosciuto")))
                else:
                    self.job_finished.emit(False, tr("La scheda si è riavviata durante il lavoro: lavoro interrotto"))
            self.message.emit(line)
            return
        if line.startswith("[MSG:"):
            self.message.emit(line[5:].rstrip("]"))

        with self._lock:
            head = self._inflight[0] if self._inflight else None
        if head is None:
            return
        if head.tag == "settings":
            m = _SETTING_RE.match(line)
            if m:
                head.data[int(m.group(1))] = m.group(2).strip()
        elif head.tag == "info" and line.startswith("["):
            head.data.append(line)

    def _finish(self, cmd, ok=True):
        if cmd.tag == "settings":
            bad = bad_travel(cmd.data) if ok and cmd.data else []
            if bad and not self._travel_retry and self.connected:
                # 0.17.2: area di lavoro non credibile (visto $131=234500): spesso è un carattere perso nella
                # lettura. Non la uso, lo dico e rileggo $$ una volta; se resta così lo dice la finestra.
                self._travel_retry = True
                self.message.emit(tr("La scheda ha risposto {0}: non è un'area di lavoro credibile, rileggo le "
                                     "impostazioni", ", ".join(f"${n}={v}" for n, v in bad)))
                threading.Timer(0.4, self.request_settings).start()
                return
            if ok and cmd.data and not bad:
                self._travel_retry = False
            if ok and cmd.data:
                self.board_settings = dict(cmd.data)
                if not self._backup_done and self.auto_backup and self.port != SIM_PORT and not bad:
                    try:  # una copia a ogni connessione (se i valori sono cambiati dall'ultima)
                        from . import board_backup

                        self.last_backup = board_backup.save(self.board_settings, self.board_info,
                                                             tr("lettura alla connessione"), self.port or "")
                    except (OSError, ValueError):  # la copia è un aiuto: se non riesce, la connessione va avanti
                        pass
            if bad:
                self.travel_suspect.emit(bad)
            self.settings_ready.emit(dict(cmd.data))
        elif cmd.tag == "info":
            for l in cmd.data:
                m = _OPT_RE.match(l)
                if m:
                    # [OPT:VPH,63,256] -> buffer RX della scheda: lo uso quasi tutto (più fluido sul raster)
                    full = max(RX_BUFFER, min(int(m.group(3)) - 2, 1022))
                    txt = " ".join(cmd.data).upper()
                    # buffer grande solo per le schede che lo gestiscono davvero (provate): con altri firmware
                    # alcune risposte si perdono e la verifica o il lavoro restano fermi (visto su Acmer)
                    self.trusted_buffer = any(k in txt for k in ("LGT", "GRBLHAL", "FLUIDNC"))
                    self.rx_buffer = full if self.trusted_buffer else RX_BUFFER
            self.board_info = list(cmd.data)
            self.info_ready.emit(list(cmd.data))
        elif ok and cmd.line.upper().replace(" ", "") == "$H":
            if self._home_alarm:  # «ok» arrivato dopo un allarme: l'homing non è riuscito
                self._home_alarm = False
            else:
                self._check_space = True  # al prossimo stato Idle capisco come sono le coordinate
        elif cmd.tag == "check_enter":
            chk = self._check
            if chk is None:
                return
            if ok:  # la scheda è in modalità di prova: ora, e solo ora, le righe da controllare
                self.last_reply = time.time()
                with self._lock:
                    if chk is self._check:  # nel frattempo nessuno l'ha chiusa
                        for i, line in chk["lines"]:
                            c = _Cmd(line, "check")
                            c.data = i
                            self._pending.append(c)
            else:
                with self._lock:
                    if chk is not self._check:
                        return
                    self._check = None
                self._check_end_t = time.time()
                self.check_finished.emit([(-1, "$C", "NON_PRONTA", tr(
                    "La scheda non è entrata in modalità di prova (non era ferma): niente è stato inviato. Aspetta "
                    "che la macchina sia ferma e rifai la verifica."))])
        elif cmd.tag == "check" and self._check is not None:
            chk = self._check
            if chk is None:
                return
            chk["done"] += 1
            if chk["done"] % 200 == 0 or chk["done"] == chk["total"]:
                self.check_progress.emit(chk["done"], chk["total"])
            if chk["done"] >= chk["total"] and not chk["exiting"]:
                # uscita dal check mode: GRBL fa un reset morbido e lo segnala col banner
                chk["exiting"] = True
                self.send_line("$C", tag="check_exit")
        elif cmd.tag == "check_exit" and self._check is not None:
            chk = self._check
            if chk is not None:
                self._end_check(chk["errors"])
        elif cmd.tag == "af_end" and self._af is not None:
            z = self._af.get("z")
            self._af = None
            if ok:
                self.autofocus_done.emit(True, tr("Autofocus fatto: la testa è alla distanza di fuoco."), z)
        elif cmd.tag == "job" and self._job_active:
            self.job_acked = int(cmd.data) + 1
            self._job_done += 1
            self.job_progress.emit(self._job_done, self._job_total)
            if self._job_done >= self._job_total:
                self._job_idle = 0  # la fine arriva dal report di stato, quando la testa si è fermata


def _clean_lines(lines):
    out = []
    for raw in lines:
        line = raw.split(";")[0].strip()
        line = re.sub(r"\(.*?\)", "", line).strip()
        if line:
            out.append(line)
    return out


def _code(line):
    try:
        return int(line.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0
