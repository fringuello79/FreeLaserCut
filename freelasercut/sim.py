# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Simulatore GRBL 1.1 che si comporta come un Longer B1 40W.

Serve per provare FreeLaserCut senza macchina e per i test automatici.
Come la scheda vera: i comandi realtime (?, !, ~, Ctrl-X, jog-cancel) sono
gestiti subito; le righe vanno in coda, i movimenti in un planner da 15
blocchi eseguito in parallelo, e l'"ok" arriva quando il blocco entra nel planner.
"""
import collections
import math
import os
import random
import re
import threading
import time

_WORD = re.compile(r"([A-Z])\s*(-?\d*\.?\d+)")
PLANNER_SIZE = 15
_G_OK = {0, 1, 2, 3, 4, 10, 17, 18, 19, 20, 21, 28, 30, 38.2, 38.3, 38.4, 38.5, 40, 43.1, 49, 53, 54, 55, 56,
         57, 58, 59, 61, 80, 90, 91, 91.1, 92, 92.1, 93, 94}


class SimSerial:
    def __init__(self, *args, speedup=1.0, negative=None, glitch=None, **kwargs):
        self.is_open = True
        self.speedup = speedup
        # GRBL classico: dopo l'homing le coordinate macchina sono negative (0 = fondo corsa)
        self.negative = os.environ.get("FLC_SIM_NEGATIVE") == "1" if negative is None else negative
        # schede ESP32: report di stato infilati a metà riga
        self.glitch = os.environ.get("FLC_SIM_GLITCH") == "1" if glitch is None else glitch
        self._rng = random.Random(5)
        self._out = bytearray()
        self._cv = threading.Condition()
        self._line = bytearray()
        self._rx = collections.deque()
        self._rx_cv = threading.Condition()
        self._planner = collections.deque()
        self._pl_cv = threading.Condition()
        self._cancel = threading.Event()
        self._generation = 0
        self.pos = [0.0, 0.0, 0.0]
        self.cs_offsets = {n: [0.0, 0.0, 0.0] for n in range(1, 7)}  # G54..G59
        self.active_cs = 1
        self.g92 = [0.0, 0.0, 0.0]
        self.check_mode = False
        # varianti di firmware per le prove: scheda senza G55, risposte perse in verifica, $I diverso
        self.no_g55 = False
        self.g55_stalls = False  # in verifica: error:2 su G55 e poi silenzio (OMTech K40)
        self._g55_mute = False
        self.drop_check_after = None  # in verifica, dopo N righe le risposte smettono di arrivare
        self._check_lines = 0
        self.lose_ok_at = set()  # 0.18.4: numeri (da 1) degli «ok» che non partono; _oks li conta tutti
        self._oks = 0
        self.info_text = None
        self._cpos = None  # verifica: posizione "letta" dal parser (la testa non si muove)
        self._critical = False  # allarme critico (limiti): la scheda ignora tutto finché non arriva un reset
        self.state = "Idle"
        self.feed = 0.0
        self.power = 0.0
        self.absolute = True
        self.laser = False
        self.s_word = 0.0
        self.f_word = 1000.0
        self.burn_marks = []  # punti (mm) dove il laser ha segnato il materiale
        self.motion = 0
        # 0.17.12, autofocus: superficie del materiale (Z macchina) e dove è collegata la sonda.
        # None = nessuna sonda: il report dice sempre Pn:P, come il B1 vero (ingresso sonda non collegato).
        self.surface_z = None
        self.probe_wiring = "probe"  # "probe" (ingresso Probe) | "zlimit" (finecorsa Z, come IO34 sulla DLC32)
        self.probe_supported = True  # False: firmware senza G38.2 (error:20)
        # 0.18.1: sonda «normalmente chiusa» (segnale attivo a riposo, come quella di Giuseppe): con $6=0 la scheda
        # la vede sempre toccata e serve $6=1. Il report e G38.2 usano il segnale dopo l'inversione di $6.
        self.probe_nc = False
        # parametri letti dal Longer B1 40W vero (report del 29/10/2026)
        self.settings = {
            0: "10",
            1: "25",
            2: "0",
            3: "2",
            4: "0",
            5: "1",
            6: "0",
            10: "1",
            11: "0.010",
            12: "0.002",
            13: "0",
            20: "1",
            21: "1",
            22: "1",
            23: "3",
            24: "250.000",
            25: "2000.000",
            26: "250.000",
            27: "1.000",
            28: "1000.000",
            30: "1000.000",
            31: "0.000",
            32: "1",
            37: "1",
            39: "1",
            40: "200",
            41: "40",
            42: "1700",
            43: "5",
            44: "1",
            45: "1",
            46: "1",
            47: "1",
            48: "1",
            49: "1",
            50: "0",
            51: "MKS_DLC",
            52: "12345678",
            53: "RAY5-TEST",
            54: "88888888",
            100: "80.000",
            101: "80.000",
            102: "250.000",
            103: "100.000",
            104: "100.000",
            105: "100.000",
            110: "36000.000",
            111: "36000.000",
            112: "1000.000",
            113: "1000.000",
            114: "1000.000",
            115: "1000.000",
            120: "500.000",
            121: "500.000",
            122: "10.000",
            123: "200.000",
            124: "200.000",
            125: "200.000",
            130: "450.000",
            131: "440.000",
            132: "200.000",
            133: "300.000",
            134: "300.000",
            135: "300.000",
        }
        threading.Thread(target=self._processor, daemon=True).start()
        threading.Thread(target=self._executor, daemon=True).start()
        self._emit("\r\nGrbl 1.1h ['$' for help]\r\n")

    # ---- interfaccia stile pyserial ------------------------------------
    def write(self, data):
        for b in data:
            if b == ord("?"):
                self._status()
            elif b == 0x18:
                self._reset()
            elif b == 0x85:
                if self.state == "Jog":
                    self._cancel.set()
            elif b == ord("!"):
                if self.state in ("Run", "Jog", "Idle") and (self._planner or self.state != "Idle"):
                    self.state = "Hold"
            elif b == ord("~"):
                if self.state == "Hold":
                    self.state = "Run" if self._planner else "Idle"
            elif b >= 0x80:
                self._override(b)
            elif b in (10, 13):
                if self._line:
                    line = self._line.decode(errors="replace").strip()
                    self._line.clear()
                    with self._rx_cv:
                        self._rx.append(line)
                        self._rx_cv.notify()
            else:
                self._line.append(b)
        return len(data)

    def _override(self, b):
        """Override realtime GRBL: 0x90-0x94 velocità, 0x99-0x9D potenza."""
        if not hasattr(self, "ov"):
            self.ov = [100, 100, 100]
        f, s = self.ov[0], self.ov[2]
        f = {0x90: 100, 0x91: f + 10, 0x92: f - 10, 0x93: f + 1, 0x94: f - 1}.get(b, f)
        s = {0x99: 100, 0x9A: s + 10, 0x9B: s - 10, 0x9C: s + 1, 0x9D: s - 1}.get(b, s)
        self.ov = [max(10, min(200, f)), 100, max(10, min(200, s))]

    def readline(self):
        with self._cv:
            if b"\n" not in self._out:
                self._cv.wait(timeout=0.1)
            i = self._out.find(b"\n")
            if i < 0:
                return b""
            line = bytes(self._out[: i + 1])
            del self._out[: i + 1]
            return line

    def reset_input_buffer(self):
        with self._cv:
            self._out.clear()

    def flush(self):
        pass

    def close(self):
        self.is_open = False
        self._cancel.set()
        with self._rx_cv:
            self._rx_cv.notify_all()
        with self._pl_cv:
            self._pl_cv.notify_all()

    # ---- uscita ---------------------------------------------------------
    def _emit(self, text):
        if self.glitch and not text.startswith("<") and len(text.strip()) >= 2 and self._rng.random() < 0.3:
            cut = self._rng.randint(1, len(text.rstrip()) - 1)
            text = text[:cut] + self._status_text() + text[cut:]
        with self._cv:
            self._out += text.encode()
            self._cv.notify_all()

    @property
    def wco(self):
        off = self.cs_offsets[self.active_cs]
        return [off[i] + self.g92[i] for i in range(3)]

    def bed_size(self):
        return float(self.settings[130]), float(self.settings[131])

    def to_bed(self, x, y):
        if self.negative:
            bx, by = self.bed_size()
            return x + bx, y + by
        return x, y

    def _ok(self):
        self._oks += 1
        if self._oks in self.lose_ok_at:
            return  # 0.18.4: risposta persa, come nel registro di un Creality Falcon A1 (ESP32-S3, USB nativo)
        self._emit("ok\r\n")

    def _status_text(self):
        # stesso formato del B1 vero: MPos e WPos, niente WCO
        x, y, z = self.pos
        wx, wy, wz = self.wco
        return (f"<{self.state}|MPos:{x:.3f},{y:.3f},{z:.3f}|WPos:{x - wx:.3f},{y - wy:.3f},{z - wz:.3f}"
                f"|FS:{self.feed:.0f},{self.power:.0f}{self._pins()}"
                + (f"|Ov:{self.ov[0]},{self.ov[1]},{self.ov[2]}" if hasattr(self, "ov") else "") + ">")

    def _touching(self):
        return self.surface_z is not None and self.pos[2] <= self.surface_z + 1e-6

    def _probe_invert(self):
        try:
            return int(float(self.settings.get(6, 0))) == 1
        except (TypeError, ValueError):
            return False

    def _probe_seen(self):
        """L'ingresso «Probe» come lo legge GRBL (dopo $6). Senza sonda (surface_z None) l'ingresso libero risulta
        attivo, come sul B1 vero: con $6=0 il report dice sempre Pn:P."""
        if self.surface_z is None:
            active = True
        elif self.probe_wiring != "probe":
            return False
        else:
            active = self._touching() != bool(self.probe_nc)
        return active != self._probe_invert()

    def _pins(self):
        pins = "P" if self._probe_seen() else ""
        if self.surface_z is not None and self.probe_wiring == "zlimit" and self._touching():
            pins += "Z"
        return f"|Pn:{pins}" if pins else ""

    def _probe(self, up, gen):
        """G38.2 (solo Z, come serve all'autofocus): scende fino al tocco, oppure ALARM:5 a fine corsa."""
        words = dict(_WORD.findall(up.replace("G38.2", "")))
        if "Z" not in words:
            return self._emit("error:26\r\n")
        if "F" in words:
            self.f_word = float(words["F"])
        self._wait_idle(gen)
        z0 = self.pos[2]
        dz = float(words["Z"])
        target = z0 + dz if not self.absolute else float(words["Z"]) + self.wco[2]
        if self.probe_wiring == "probe" and self._probe_seen():
            # già «toccata» prima di partire: sonda appoggiata, ingresso libero o segnale al contrario ($6)
            self.state = "Alarm"
            return self._emit("ALARM:4\r\n")
        hit = None
        if self.surface_z is not None and target < z0 and target <= self.surface_z <= z0:
            hit = self.surface_z
        if hit is not None and self.probe_wiring == "zlimit":
            # sonda sul finecorsa Z: G38.2 non la vede; con i limiti hardware ($21=1) il tocco ferma tutto
            self.pos[2] = hit
            if float(self.settings.get(21, 0)) >= 1:
                self.state = "Alarm"
                self._critical = True
                self._emit("ALARM:1\r\n[MSG:Reset to continue]\r\n")
                return
            hit = None
        if hit is None:
            self.pos[2] = target
            self.state = "Alarm"
            self._emit("ALARM:5\r\n")
            return
        self.pos[2] = hit
        x, y, z = self.pos
        self._emit(f"[PRB:{x:.3f},{y:.3f},{z:.3f}:1]\r\n")
        return self._ok()

    def _status(self):
        with self._cv:
            self._out += (self._status_text() + "\r\n").encode()
            self._cv.notify_all()

    def _reset(self):
        self._generation += 1
        self._cancel.set()
        with self._rx_cv:
            self._rx.clear()
        with self._pl_cv:
            self._planner.clear()
            self._pl_cv.notify_all()
        # come GRBL: il reset esce dal check mode; un allarme resta finché non si sblocca o si fa l'homing
        alarm = self.state == "Alarm"
        self._critical = False
        self.check_mode = False
        self._g55_mute = False
        self._cpos = None
        self.absolute = True  # come GRBL: dopo il reset il parser torna in G90
        self.state = "Alarm" if alarm else "Idle"
        self.feed = 0
        self.power = 0
        self.laser = False
        self._emit("\r\nGrbl 1.1h ['$' for help]\r\n")
        if alarm:
            self._emit("[MSG:'$H'|'$X' to unlock]\r\n")

    def _limits(self):
        bx, by = self.bed_size()
        lo = (-bx, -by) if self.negative else (0.0, 0.0)
        hi = (0.0, 0.0) if self.negative else (bx, by)
        return lo, hi

    def _outside(self, p):
        lo, hi = self._limits()
        return not (lo[0] - 0.001 <= p[0] <= hi[0] + 0.001 and lo[1] - 0.001 <= p[1] <= hi[1] + 0.001)

    def _soft_limit_alarm(self):
        """Limiti software ($20=1) superati: allarme 2 critico, come GRBL anche in modalità verifica."""
        self.check_mode = False
        self._cpos = None
        self.state = "Alarm"
        self._critical = True
        self._emit("ALARM:2\r\n")
        self._emit("[MSG:Reset to continue]\r\n")

    # ---- thread ---------------------------------------------------------
    def _processor(self):
        while self.is_open:
            with self._rx_cv:
                while not self._rx and self.is_open:
                    self._rx_cv.wait(timeout=0.2)
                if not self.is_open:
                    return
                line = self._rx.popleft()
            gen = self._generation
            try:
                self._process(line, gen)
            except Exception:  # noqa: BLE001
                self._emit("error:2\r\n")

    def _executor(self):
        while self.is_open:
            with self._pl_cv:
                while not self._planner and self.is_open:
                    self._pl_cv.wait(timeout=0.2)
                if not self.is_open:
                    return
                block = self._planner[0]
            target, feed, power, gen = block
            if gen == self._generation:
                if self.state not in ("Hold",):
                    self.state = "Run"
                self.power = power
                self._move_to(target, feed, gen)
            with self._pl_cv:
                if self._planner and self._planner[0] is block:
                    self._planner.popleft()
                self._pl_cv.notify_all()
                if not self._planner and self.state == "Run":
                    self.state = "Idle"
                    self.power = 0
                    self.feed = 0

    def _move_to(self, target, feed, gen):
        self._cancel.clear()
        start = list(self.pos)
        dist = math.dist(start[:2], target[:2])
        rate = max(feed, 1.0) / 60.0 * self.speedup  # mm/s
        duration = min(dist / rate, 6.0) if dist > 0 else 0
        steps = max(int(duration / 0.01), 1)
        self.feed = feed
        marking = self.power >= 0.1 * float(self.settings[30])  # sotto il 10% non segna il cartone
        if marking:
            sub = max(int(dist / 0.3), 1)  # traccia fitta per l'incisione simulata
            for i in range(sub + 1):
                t = i / sub
                self.burn_marks.append((start[0] + (target[0] - start[0]) * t, start[1] + (target[1] - start[1]) * t))
        for i in range(1, steps + 1):
            if self._cancel.is_set() or gen != self._generation:
                break
            while self.state == "Hold" and gen == self._generation and self.is_open:
                time.sleep(0.02)
            t = i / steps
            self.pos = [start[k] + (target[k] - start[k]) * t for k in range(3)]
            if duration:
                time.sleep(duration / steps)

    def _wait_idle(self, gen):
        while self._planner and gen == self._generation and self.is_open:
            time.sleep(0.01)

    # ---- interprete -------------------------------------------------------
    def _process(self, line, gen):
        if self._critical:
            return  # stato critico: nessuna risposta finché non arriva Ctrl-X
        up = line.upper().replace(" ", "")
        if self.check_mode and up != "$C" and self.g55_stalls:
            # 0.18.15: come la scheda di un OMTech K40 (rapporto FLC-20261111-2131-0A9C): in verifica risponde
            # error:2 alla riga G55 e da lì non risponde più a niente, finché non si esce dalla verifica
            if self._g55_mute:
                return
            if up == "G55":
                self._g55_mute = True
                return self._emit("error:2\r\n")
        if self.check_mode and up != "$C" and self.drop_check_after is not None:
            self._check_lines += 1
            if self._check_lines > self.drop_check_after:
                return  # risposta persa (come nel registro di un Acmer S1)
        if self.check_mode and up in ("$H", "$I", "$$"):
            return self._emit("error:8\r\n")
        if up == "$C" and not self.check_mode and (self._planner or self.state in ("Run", "Jog", "Hold", "Home")):
            return self._emit("error:8\r\n")  # come GRBL: $C solo a macchina ferma (Idle)
        if up.startswith("$") and not up.startswith("$J="):
            self._wait_idle(gen)
        if up == "$$":
            for k in sorted(self.settings):
                self._emit(f"${k}={self.settings[k]}\r\n")
            return self._ok()
        if up == "$I" and self.info_text:
            self._emit(self.info_text)
            return self._ok()
        if up == "$I":
            self._emit("[LGT V1.2.3]\r\n[VER:1.1.2023080801:]\r\n[OPT:VPH,63,256]\r\n"
                       "[MSG:FW:LGT V1.2.3|MB:LS_ESP32-SIM]\r\n[MSG:No Wifi]\r\n")
            return self._ok()
        if up in ("$G",):
            self._emit(f"[GC:G0 G54 G17 G21 {'G90' if self.absolute else 'G91'} G94 M5 M9 T0 F0 S0]\r\n")
            return self._ok()
        if up == "$H":
            self.state = "Home"
            bx, by = self.bed_size()
            pull = float(self.settings[27])
            home = [-bx + pull, -by + pull, 0.0] if self.negative else [0.0, 0.0, 0.0]
            self._move_to(home, 3000, gen)
            self.state = "Idle"
            return self._ok()
        if up == "$C":
            self.check_mode = not self.check_mode
            self._check_lines = 0
            self._g55_mute = False
            if self.check_mode:
                self.state = "Check"
                self._cpos = list(self.pos)
                self._emit("[MSG:Enabled]\r\n")
                return self._ok()
            self._emit("[MSG:Disabled]\r\n")
            self._ok()
            self._reset()  # come GRBL: uscire dal check mode fa un reset
            return
        if up == "$X":
            self.state = "Idle"
            self._emit("[MSG:Caution: Unlocked]\r\n")
            return self._ok()
        m = re.match(r"^\$(\d+)=(.+)$", up)
        if m:
            self.settings[int(m.group(1))] = m.group(2)
            return self._ok()
        if self.state == "Alarm":
            return self._emit("error:9\r\n")
        if up.startswith("$J="):
            body = up[3:]
            words = dict(_WORD.findall(body))
            rel = "G91" in body
            machine = "G53" in body
            target = list(self.pos)
            for i, ax in enumerate("XYZ"):
                if ax in words:
                    v = float(words[ax])
                    target[i] = self.pos[i] + v if rel else (v if machine else v + self.wco[i])
            bx, by = self.bed_size()
            lo_x, hi_x = (-bx, 0.0) if self.negative else (0.0, bx)
            lo_y, hi_y = (-by, 0.0) if self.negative else (0.0, by)
            if not (lo_x - 0.001 <= target[0] <= hi_x + 0.001 and lo_y - 0.001 <= target[1] <= hi_y + 0.001):
                return self._emit("error:15\r\n")
            self._wait_idle(gen)
            self.state = "Jog"
            self._ok()
            self._move_to(target, float(words.get("F", 1000)), gen)
            if self.state == "Jog":
                self.state = "Idle"
            return
        if up.startswith("$"):
            return self._emit("error:3\r\n")
        if "G38.2" in up:
            if not self.probe_supported or self.check_mode:
                return self._emit("error:20\r\n")
            for g in re.findall(r"G(\d+(?:\.\d+)?)", up):
                if g == "91":
                    self.absolute = False
                elif g == "90":
                    self.absolute = True
            return self._probe(up, gen)
        words = _WORD.findall(up)
        # validazione come GRBL: lettere e codici non supportati -> error:20
        for letter, val in words:
            v = float(val)
            if letter not in "GMSFXYZIJKPLRTN":
                return self._emit("error:20\r\n")
            if letter == "G" and (v not in _G_OK or (self.no_g55 and v == 55)):
                return self._emit("error:20\r\n")
            if letter == "M" and v not in (0, 1, 2, 3, 4, 5, 7, 8, 9, 30):
                return self._emit("error:20\r\n")
        leftovers = _WORD.sub("", up).strip()
        if leftovers:
            return self._emit("error:1\r\n")
        d = {}
        motion = None
        for letter, val in words:
            v = float(val)
            if letter == "G":
                if v in (0, 1, 2, 3):
                    motion = int(v)
                elif 54 <= v <= 59 and float(v).is_integer():
                    self.active_cs = int(v) - 53
                elif v == 90:
                    self.absolute = True
                elif v == 91:
                    self.absolute = False
            elif letter == "M":
                if v in (3, 4):
                    self.laser = True
                elif v == 5:
                    self.laser = False
            elif letter == "S":
                self.s_word = v
            elif letter == "F":
                self.f_word = v
            else:
                d[letter] = v
        if re.search(r"G10(?!\d)", up):
            self._wait_idle(gen)
            n = int(d.get("P", 1)) or self.active_cs
            if n < 1 or n > 6:
                return self._emit("error:29\r\n")
            off = self.cs_offsets[n]
            for i, ax in enumerate("XYZ"):
                if ax in d:
                    if "L20" in up:
                        off[i] = self.pos[i] - d[ax] - self.g92[i]
                    elif "L2" in up:
                        off[i] = d[ax]
            return self._ok()
        if "G92.1" in up:
            self.g92 = [0.0, 0.0, 0.0]
            return self._ok()
        if re.search(r"G92(?![.\d])", up):
            self._wait_idle(gen)
            off = self.cs_offsets[self.active_cs]
            for i, ax in enumerate("XYZ"):
                if ax in d:
                    self.g92[i] = self.pos[i] - off[i] - d[ax]
            return self._ok()
        m_cs = re.search(r"G5([4-9])(?![.\d])", up)
        if m_cs and not any(ax in d for ax in "XYZ"):
            self.active_cs = int(m_cs.group(1)) - 3
            return self._ok()
        if self.check_mode:
            # verifica: nessun movimento, ma GRBL calcola comunque la destinazione e applica i limiti software
            if any(ax in d for ax in "XYZ"):
                base = self._cpos if self._cpos is not None else list(self.pos)
                target = list(base)
                for i, ax in enumerate("XYZ"):
                    if ax in d:
                        target[i] = (d[ax] + self.wco[i]) if self.absolute else base[i] + d[ax]
                if motion is not None:
                    self.motion = motion
                pts = [target]
                if self.motion in (2, 3) and ("I" in d or "J" in d):
                    from .gcode_preview import _arc
                    pts = [[px, py, target[2]] for px, py in _arc(base[0], base[1], target[0], target[1], d, 1.0,
                                                                  self.motion == 2)]
                if float(self.settings.get(20, 0)) >= 1 and any(self._outside(q) for q in pts):
                    return self._soft_limit_alarm()
                self._cpos = target
            return self._ok()
        if any(ax in d for ax in "XYZ"):
            base = self._planner[-1][0] if self._planner else self.pos
            target = list(base)
            for i, ax in enumerate("XYZ"):
                if ax in d:
                    target[i] = (d[ax] + self.wco[i]) if self.absolute else base[i] + d[ax]
            if motion is not None:
                self.motion = motion
            is_rapid = self.motion == 0
            feed = float(self.settings[110]) / 3 if is_rapid else self.f_word
            power = self.s_word if (self.laser and not is_rapid) else 0.0
            targets = [target]
            if self.motion in (2, 3) and ("I" in d or "J" in d):
                from .gcode_preview import _arc
                pts = _arc(base[0], base[1], target[0], target[1], d, 1.0, self.motion == 2)
                targets = [[px, py, target[2]] for px, py in pts]
            for tg in targets:
                with self._pl_cv:
                    while len(self._planner) >= PLANNER_SIZE and gen == self._generation and self.is_open:
                        self._pl_cv.wait(timeout=0.1)
                    if gen != self._generation:
                        return
                    self._planner.append((tg, feed, power, gen))
                    self._pl_cv.notify_all()
        self._ok()
