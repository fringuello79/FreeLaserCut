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

from .grbl_codes import ALARMS, ERRORS
from .sim import SimSerial

SIM_PORT = "SIMULATORE"
RX_BUFFER = 127
POLL_INTERVAL = 0.2
_SETTING_RE = re.compile(r"^\$(\d+)=(.*)$")
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


class GrblController(QObject):
    connection_changed = Signal(bool, str)  # connesso?, messaggio
    line_received = Signal(str)
    line_sent = Signal(str)
    status_changed = Signal(object)  # dict
    alarm_raised = Signal(int, str)
    error_raised = Signal(int, str, str)  # codice, testo, riga che l'ha causato
    message = Signal(str)  # [MSG:...] e banner
    settings_ready = Signal(object)  # {numero: "valore"}
    info_ready = Signal(object)  # ["[VER:...]", "[OPT:...]"]
    job_progress = Signal(int, int)  # fatte, totali
    job_finished = Signal(bool, str)  # completato?, messaggio
    homed_changed = Signal(bool, object)  # homing fatto?, spazio macchina negativo? (None = non ancora noto)
    job_error = Signal(int, str, int, str)  # indice riga, riga, codice, spiegazione (il lavoro è già in pausa)
    check_finished = Signal(object)  # [(indice, riga, codice, spiegazione)] — verifica $C conclusa
    check_progress = Signal(int, int)

    def __init__(self):
        super().__init__()
        self._ser = None
        self.port = None
        self._running = False
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        self._pending = collections.deque()
        self._inflight = collections.deque()
        self._wco = [0.0, 0.0, 0.0]
        self.last_status = {"state": "Disconnesso"}
        self.status_time = 0.0
        self.rx_buffer = RX_BUFFER
        self.homed = False
        self.negative_space = None
        self._check_space = False
        self._job_total = 0
        self._job_done = 0
        self._job_active = False
        self.job_lines = []  # righe del lavoro in corso (per la ripresa)
        self.job_acked = 0  # righe confermate dalla scheda
        self.pause_on_error = True
        self._check = None  # verifica in corso: {"total", "done", "errors"}
        self._fire_timer = None
        self.fire_active = False

    # ------------------------------------------------------------------ porta
    @property
    def connected(self):
        return self._ser is not None

    def connect_port(self, port, baud=115200):
        self.disconnect_port()
        try:
            if port == SIM_PORT:
                ser = SimSerial()
            else:
                if serial is None:
                    raise RuntimeError(tr("pyserial non è installato"))
                ser = serial.Serial(port, baud, timeout=0.1, write_timeout=2)
        except Exception as exc:  # noqa: BLE001
            self.connection_changed.emit(False, f"Impossibile aprire {port}: {exc}")
            return False
        self._ser = ser
        self.port = port
        self.rx_buffer = RX_BUFFER  # prudente finché $I non dice quanto è grande
        self.homed = False
        self._check_space = False
        self._clear_queues()
        self._running = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._write_raw(b"\r\n\r\n")
        self.connection_changed.emit(True, f"Connesso a {port}")
        # le schede Arduino si resettano all'apertura: attendo il banner
        threading.Timer(1.5, self._after_connect).start()
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
        with self._lock:
            self._pending.append(_Cmd(line, tag))
        self._pump()

    def _pump(self):
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
        self.send_line("$H")

    def unlock(self):
        self.send_line("$X")

    def soft_reset(self):
        self.realtime(0x18)
        self._clear_queues()
        if self._job_active:
            self._job_active = False
            self.job_finished.emit(False, "Lavoro interrotto (reset)")

    def feed_hold(self):
        self.realtime(b"!")

    def resume(self):
        self.realtime(b"~")

    def jog(self, dx=0.0, dy=0.0, feed=3000):
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
        clean = _clean_lines(lines)
        if not clean:
            self.job_finished.emit(False, tr("Il file non contiene comandi G-code"))
            return
        self._job_total = len(clean)
        self._job_done = 0
        self._job_active = True
        self.job_lines = clean
        self.job_acked = 0
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
        self._check = {"total": len(clean), "done": 0, "errors": [], "exiting": False}
        self.send_line("$C")
        with self._lock:
            for i, line in clean:
                c = _Cmd(line, "check")
                c.data = i
                self._pending.append(c)
        self._pump()
        return True

    @property
    def checking(self):
        return self._check is not None

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
    def fire(self, on, pct=1.0, max_pct=5.0, timeout_s=20.0, s_max=1000.0):
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
        self.send_line(f"M3 S{min(laser_pct, 5.0) / 100.0 * s_max:.1f}")
        for x, y in points[1:]:
            self.send_line(f"G53 G1 X{x:.3f} Y{y:.3f} F{feed:.0f}")
        self.send_line("M5 S0")

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
    def _poll_loop(self):
        while self._running:
            self._write_raw(b"?")
            time.sleep(POLL_INTERVAL)

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
                self._dispatch(line)

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
            self.status_time = time.time()
            if self._check_space and st["state"] == "Idle" and "MPos" in st:
                # dopo l'homing: GRBL classico mette la macchina in coordinate negative (0 = fondo corsa)
                self._check_space = False
                mx, my = st["MPos"][0], st["MPos"][1]
                self.negative_space = mx < -1.0 or my < -1.0
                self.homed = True
                self.homed_changed.emit(True, self.negative_space)
            self.status_changed.emit(st)
            return

        is_ok = line == "ok"
        is_err = line.startswith("error")
        if is_ok or is_err:
            with self._lock:
                head = self._inflight.popleft() if self._inflight else None
            if head is not None and head.tag != "job":
                self.line_received.emit(line)
            if is_err:
                code = _code(line)
                text = ERRORS.get(code, "Errore sconosciuto")
                if head is not None and head.tag == "check" and self._check is not None:
                    self._check["errors"].append((head.data, head.line, code, text))
                elif head is not None and head.tag == "job" and self._job_active and self.pause_on_error:
                    # sicurezza: alla prima riga rifiutata il lavoro si ferma subito in pausa
                    self.feed_hold()
                    self.job_error.emit(int(head.data), head.line, code, text)
                    self.error_raised.emit(code, text, head.line)
                else:
                    self.error_raised.emit(code, text, head.line if head else "")
            if head is not None:
                self._finish(head, is_ok)
            self._pump()
            return

        self.line_received.emit(line)
        if line.startswith("ALARM"):
            code = _code(line)
            if code in (1, 2, 3, 6, 7, 8, 9, 10) and self.homed:
                self.homed = False  # posizione non più garantita
                self.homed_changed.emit(False, self.negative_space)
            self.alarm_raised.emit(code, ALARMS.get(code, "Allarme sconosciuto"))
            return
        if line.lower().startswith("grbl"):
            # la scheda si è riavviata: tutto ciò che era in volo è perso
            self._clear_queues()
            if self._check is not None and self._check.get("exiting"):
                res = self._check["errors"]
                self._check = None
                self.check_finished.emit(res)
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
            self.settings_ready.emit(dict(cmd.data))
        elif cmd.tag == "info":
            for l in cmd.data:
                m = _OPT_RE.match(l)
                if m:
                    # [OPT:VPH,63,256] -> buffer RX della scheda: lo uso quasi tutto (più fluido sul raster)
                    self.rx_buffer = max(RX_BUFFER, min(int(m.group(3)) - 2, 1022))
            self.info_ready.emit(list(cmd.data))
        elif ok and cmd.line.upper().replace(" ", "") == "$H":
            self._check_space = True  # al prossimo stato Idle capisco come sono le coordinate
        elif cmd.tag == "check" and self._check is not None:
            self._check["done"] += 1
            if self._check["done"] % 200 == 0 or self._check["done"] == self._check["total"]:
                self.check_progress.emit(self._check["done"], self._check["total"])
            if self._check["done"] >= self._check["total"]:
                # uscita dal check mode: GRBL fa un reset morbido e lo segnala col banner
                self._check["exiting"] = True
                self.send_line("$C", tag="check_exit")
        elif cmd.tag == "check_exit" and self._check is not None:
            res = self._check["errors"]
            self._check = None
            self.check_finished.emit(res)
        elif cmd.tag == "job" and self._job_active:
            self.job_acked = int(cmd.data) + 1
            self._job_done += 1
            self.job_progress.emit(self._job_done, self._job_total)
            if self._job_done >= self._job_total:
                self._job_active = False
                self.job_finished.emit(True, f"Lavoro completato: {self._job_total} righe")


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
