# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Riconoscimento della macchina collegata (senza interfaccia: si prova anche col simulatore).

Tre livelli di indizi, dal più debole al più forte:
1. la porta USB: VID/PID dicono il chip ponte (CH340, CP210x, FTDI, ESP32 nativo) e quindi il driver;
2. il messaggio di avvio e $I: famiglia del firmware (GRBL 1.1, grblHAL, FluidNC, Grbl_ESP32),
   firmware del produttore (es. "LGT V1.2.3" = Longer), scheda, buffer di ricezione;
3. $$: area di lavoro ($130/$131), scala di potenza ($30), modalità laser ($32), homing ($22).

identify() mette insieme gli indizi e propone nome, profilo di partenza e avvisi.
probe() apre la porta, trova la velocità giusta e legge banner, $I e $$ (la porta deve essere libera).
"""
import re
import time
from dataclasses import dataclass, field

from .profile import MachineProfile
from freelasercut.i18n import tr  # noqa: E402

# chip ponte USB-seriale: (VID, PID) -> (nome, famiglia driver).  PID None = qualsiasi.
USB_CHIPS = {
    (0x1A86, 0x7523): ("CH340", "wch"),
    (0x1A86, 0x7522): ("CH340K", "wch"),
    (0x1A86, 0x5523): ("CH341", "wch"),
    (0x1A86, 0x55D3): ("CH343", "wch"),
    (0x1A86, 0x55D4): ("CH9102", "wch"),
    (0x10C4, 0xEA60): ("CP2102/CP2104", "silabs"),
    (0x10C4, 0xEA70): ("CP2105", "silabs"),
    (0x0403, 0x6001): ("FT232R", "ftdi"),
    (0x0403, 0x6015): ("FT231X", "ftdi"),
    (0x303A, None): (tr("ESP32 (USB nativo)"), "native"),
    (0x2341, None): ("Arduino", "arduino"),
    (0x2A03, None): ("Arduino", "arduino"),
}

DRIVERS = {
    "wch": (tr("Driver WCH CH34x (CH340/CH341/CH9102)"), "https://www.wch-ic.com/downloads/CH341SER_EXE.html"),
    "silabs": (tr("Driver Silicon Labs CP210x"), "https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers"),
    "ftdi": (tr("Driver FTDI VCP"), "https://ftdichip.com/drivers/vcp-drivers/"),
    "native": (tr("Driver USB seriale di Windows (già incluso)"), ""),
    "arduino": (tr("Driver Arduino (incluso nell'IDE Arduino)"), "https://www.arduino.cc/en/software"),
}

# parole chiave nel banner/$I -> produttore
VENDORS = (
    ("Longer", ("LGT", "LONGER")),
    ("Ortur", ("ORTUR",)),
    ("Sculpfun", ("SCULPFUN",)),
    ("Atomstack", ("ATOMSTACK",)),
    ("Two Trees", ("TWOTREES", "TWO TREES")),
    ("Creality", ("CREALITY",)),
    ("NEJE", ("NEJE",)),
    ("Comgrow", ("COMGROW",)),
)

_BAUDS = (115200, 250000, 230400, 57600, 38400, 9600)

# Incisori a diodo GRBL più diffusi: valori di targa per partire subito, anche senza la macchina collegata.
# Quando la colleghi, area di lavoro, scala di potenza, velocità e buffer si rileggono dalla scheda ($$, $I).
# (nome, produttore, area X, area Y mm, potenza ottica indicativa, velocità massima mm/min)
CATALOG = (
    ("Longer B1 40W", "Longer", 450, 440, "44–48 W", 36000),
    ("Longer B1 20W / 30W", "Longer", 450, 440, "20–30 W", 36000),
    ("Longer Ray5 10W / 20W", "Longer", 400, 400, "10–20 W", 20000),
    ("Ortur Laser Master 3 (10W)", "Ortur", 400, 400, "10 W", 20000),
    ("Ortur Laser Master 3 (20W / 40W)", "Ortur", 400, 380, "20–40 W", 20000),
    ("Ortur Laser Master 2 Pro S2", "Ortur", 400, 430, "5–10 W", 10000),
    ("xTool D1 Pro", "xTool", 430, 390, "10–40 W", 24000),
    ("Atomstack A10 Pro V2", "Atomstack", 410, 380, "10 W", 24000),
    ("Atomstack X20 Pro / S20 Pro / A20 Pro", "Atomstack", 400, 400, "20 W", 20000),
    ("Atomstack X40 Pro / S40 Pro / A40 Pro", "Atomstack", 400, 400, "40 W", 20000),
    ("Sculpfun S9", "Sculpfun", 410, 420, "5,5 W", 10000),
    ("Sculpfun S10", "Sculpfun", 410, 400, "10 W", 10000),
    ("Sculpfun S30 / S30 Pro / S30 Pro Max", "Sculpfun", 410, 400, "5–20 W", 25000),
    ("Creality Falcon 10W", "Creality", 400, 415, "10 W", 10000),
    ("Creality Falcon2 22W / 40W", "Creality", 400, 415, "22–40 W", 25000),
    ("Two Trees TS2", "Two Trees", 450, 450, "10–20 W", 10000),
    ("Two Trees TTS-55 Pro", "Two Trees", 300, 300, "5,5 W", 6000),
    ("Comgrow Z1", "Comgrow", 400, 410, "5–10 W", 10000),
)
GENERIC = tr("Altro laser GRBL (si legge dalla macchina)")


def catalog_names():
    return [c[0] for c in CATALOG] + [GENERIC]


def preset_profile(name):
    """Profilo pronto per un modello del catalogo (o generico): area, velocità e potenza indicativa."""
    if name == "Longer B1 40W":
        return MachineProfile()
    for n, vendor, bx, by, power, rate in CATALOG:
        if n == name:
            return MachineProfile(name=n, model=n, source=tr("valori di targa"), bed_x=float(bx), bed_y=float(by),
                                  optical_power=power, max_rate_x=float(rate), max_rate_y=float(rate),
                                  accel_x=1500.0, accel_y=1500.0, spot_x_mm=0.08, spot_y_mm=0.10, rx_buffer=128)
    return MachineProfile(name=tr("Laser GRBL"), model=tr("Laser GRBL"), source=tr("valori di targa"), bed_x=400.0,
                          bed_y=400.0, optical_power="", max_rate_x=10000.0, max_rate_y=10000.0, accel_x=1000.0,
                          accel_y=1000.0, spot_x_mm=0.10, spot_y_mm=0.10)


@dataclass
class PortInfo:
    device: str
    description: str = ""
    vid: int = None
    pid: int = None
    manufacturer: str = ""
    chip: str = ""
    driver: str = ""  # famiglia: wch / silabs / ftdi / native / arduino
    likely: bool = False

    def vid_pid(self):
        return f"{self.vid:04X}:{self.pid:04X}" if self.vid is not None and self.pid is not None else ""

    def label(self):
        bits = [self.device]
        if self.chip:
            bits.append(self.chip)
        elif self.description:
            bits.append(self.description)
        return " — ".join(bits)


def chip_for(vid, pid):
    if vid is None:
        return "", ""
    return USB_CHIPS.get((vid, pid)) or USB_CHIPS.get((vid, None)) or ("", "")


def describe_ports(comports=None):
    """Porte seriali con chip e driver riconosciuti; le probabili schede laser per prime."""
    if comports is None:
        try:
            from serial.tools import list_ports

            comports = list_ports.comports()
        except ImportError:
            comports = []
    out = []
    for p in comports:
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        chip, drv = chip_for(vid, pid)
        desc = getattr(p, "description", "") or ""
        blob = f"{desc} {getattr(p, 'hwid', '') or ''}".upper()
        likely = bool(chip) or any(h in blob for h in ("CH340", "CH341", "CP210", "USB-SERIAL", "USB SERIAL", "ESP32"))
        if not chip:  # Windows a volte non dà VID/PID ma li scrive nella descrizione
            m = re.search(r"VID[:_=]([0-9A-F]{4}).*PID[:_=]([0-9A-F]{4})", blob)
            if m:
                vid, pid = int(m.group(1), 16), int(m.group(2), 16)
                chip, drv = chip_for(vid, pid)
        out.append(PortInfo(p.device, desc, vid, pid, getattr(p, "manufacturer", "") or "", chip, drv, likely))
    out.sort(key=lambda t: (not t.likely, t.device))
    return out


@dataclass
class Identification:
    vendor: str = ""
    model: str = ""
    family: str = ""  # GRBL 1.1 / grblHAL / FluidNC / Grbl_ESP32 / sconosciuto
    version: str = ""
    vendor_fw: str = ""
    board: str = ""
    baud: int = 115200
    rx_buffer: int = 0
    planner_blocks: int = 0
    bed: tuple = (0.0, 0.0)
    s_max: float = 0.0
    laser_mode: bool = None
    homing: bool = None
    confidence: str = "bassa"  # alta / media / bassa
    notes: list = field(default_factory=list)  # (livello, testo)

    def name(self):
        if self.model:
            return self.model
        bx, by = self.bed
        size = f" {bx:g}×{by:g}" if bx and by else ""
        return f"{self.vendor or 'Laser GRBL'}{size}"

    def summary(self):
        bits = []
        if self.vendor_fw:
            bits.append(self.vendor_fw)
        if self.family:
            bits.append(f"{self.family} {self.version}".strip())
        if self.board:
            bits.append(tr("scheda {0}", self.board))
        if self.bed[0] and self.bed[1]:
            bits.append(tr("area {0:g}×{1:g} mm", self.bed[0], self.bed[1]))
        if self.rx_buffer:
            bits.append(tr("buffer {0} byte", self.rx_buffer))
        return " · ".join(bits)


def _num(settings, n):
    try:
        return float(settings.get(n, settings.get(str(n))))
    except (TypeError, ValueError):
        return None


def identify(banner=(), info=(), settings=None, port=None, baud=115200):
    """Mette insieme gli indizi di porta, avvio, $I e $$."""
    settings = settings or {}
    ident = Identification(baud=baud)
    text = "\n".join(list(banner) + list(info))
    up = text.upper()
    # famiglia e versione del firmware
    if "FLUIDNC" in up:
        ident.family = "FluidNC"
    elif "GRBLHAL" in up:
        ident.family = "grblHAL"
    elif "GRBL_ESP32" in up or "GRBL ESP32" in up:
        ident.family = "Grbl_ESP32"
    m = re.search(r"Grbl\s+(\d+\.\d+\w*)", text, re.I)
    if m and not ident.family:
        ident.family = "GRBL"
    if m:
        ident.version = m.group(1)
    m = re.search(r"\[VER:([^\]:]*)", text)
    if m and not ident.version:
        ident.version = m.group(1)
    m = re.search(r"\[OPT:[^,\]]*,(\d+),(\d+)", text)
    if m:
        ident.planner_blocks, ident.rx_buffer = int(m.group(1)), int(m.group(2))
    m = re.search(r"\[MSG:FW:([^|\]]*)(?:\|MB:([^\]]*))?", text)
    if m:
        ident.vendor_fw = m.group(1).strip()
        ident.board = (m.group(2) or "").strip()
    m = re.search(r"^\[(LGT[^\]]*)\]", text, re.M)
    if m and not ident.vendor_fw:
        ident.vendor_fw = m.group(1).strip()
    for vendor, keys in VENDORS:
        if any(k in up for k in keys):
            ident.vendor = vendor
            break
    # impostazioni
    bx, by = _num(settings, 130), _num(settings, 131)
    ident.bed = (bx or 0.0, by or 0.0)
    ident.s_max = _num(settings, 30) or 0.0
    lm, hm = _num(settings, 32), _num(settings, 22)
    ident.laser_mode = None if lm is None else lm >= 1
    ident.homing = None if hm is None else hm >= 1
    # modello
    if ident.vendor == "Longer" and bx and by and abs(bx - 450) <= 15 and abs(by - 440) <= 15:
        ident.model = "Longer B1 40W"
        ident.notes.append(("info", tr("Longer B1 riconosciuto da firmware e area di lavoro. La potenza del modulo non si "
                                    "legge dalla scheda: confermala nel nome (20, 30 o 40 W).")))
    if ident.vendor and not ident.model and bx and by:
        same = [n for n, v, cx, cy, *_ in CATALOG if v == ident.vendor and abs(bx - cx) <= 15 and abs(by - cy) <= 15]
        if len(same) == 1:
            ident.model = same[0]
    # affidabilità
    score = (2 if ident.vendor else 0) + (1 if ident.family else 0) + (1 if bx and by else 0) + (1 if ident.board else 0)
    ident.confidence = "alta" if score >= 4 else "media" if score >= 2 else "bassa"
    # avvisi utili
    if not text.strip() and not settings:
        ident.notes.append(("warn", tr("La scheda non ha risposto: controlla che sia accesa, il cavo e il driver USB.")))
    if ident.family == "FluidNC":
        ident.notes.append(("info", tr("FluidNC: lo streaming GRBL funziona; alcune impostazioni stanno nel file "
                                    "config.yaml e non compaiono in $$.")))
    if ident.family == "grblHAL":
        ident.notes.append(("info", tr("grblHAL: FreeLaserCut usa il buffer dichiarato dalla scheda per uno streaming più fluido.")))
    if ident.version.startswith("0."):
        ident.notes.append(("warn", tr("GRBL 0.9 o precedente: niente potenza dinamica M4; usa la potenza costante (M3).")))
    if ident.laser_mode is False:
        ident.notes.append(("warn", tr("Modalità laser spenta ($32=0): la testa si ferma a ogni cambio di potenza. "
                                    "Conviene $32=1.")))
    if ident.s_max and ident.s_max != 1000:
        ident.notes.append(("info", tr("Scala potenza S0–S{0:g}: FreeLaserCut la usa da sola.", ident.s_max)))
    if ident.homing is False:
        ident.notes.append(("info", tr("Homing disattivato: l'origine sarà dove si trova la testa all'accensione.")))
    if port is not None and port.driver in ("wch", "silabs", "ftdi"):
        ident.notes.append(("ok", tr("Chip USB {0}: driver «{1}» funzionante.", port.chip, DRIVERS[port.driver][0])))
    return ident


def base_profile(ident):
    """Profilo di partenza per la macchina riconosciuta (poi from_machine ci scrive i valori letti)."""
    if ident.model == "Longer B1 40W":
        p = MachineProfile()
    elif ident.model in catalog_names():
        p = preset_profile(ident.model)
        p.vendor_fw = ident.vendor_fw
    else:
        p = MachineProfile(name=ident.name(), model=ident.name(), optical_power="", spot_x_mm=0.10, spot_y_mm=0.10)
        p.vendor_fw = ident.vendor_fw
    p.baud = ident.baud
    return p


def build_profile(ident, settings, info, name=None):
    p = MachineProfile.from_machine(settings, list(info), base=base_profile(ident))
    if name:
        p.name = name
        p.model = name
    p.baud = ident.baud
    return p


# ---------------------------------------------------------------------- sonda
def _read_until(ser, deadline, done=None):
    lines = []
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode(errors="replace").strip()
        line = re.sub(r"<[^<>]*>", "", line).strip()  # report di stato infilati (ESP32)
        if not line:
            continue
        lines.append(line)
        if done and done(line):
            break
    return lines


def probe(port, bauds=_BAUDS, opener=None, settle=1.6, log=None):
    """Apre la porta e legge avvio, $I e $$.  Ritorna dict(baud, banner, info, settings) o None.

    opener(port, baud) -> oggetto tipo serial.Serial (per il simulatore e i test)."""
    if opener is None:
        import serial

        def opener(p, b):
            return serial.Serial(p, b, timeout=0.1, write_timeout=1)
    end_ok = lambda l: l == "ok" or l.startswith("error")  # noqa: E731
    for baud in bauds:
        if log:
            log(f"Provo {port} a {baud} baud…")
        try:
            ser = opener(port, baud)
        except Exception as exc:  # noqa: BLE001
            if log:
                log(f"Impossibile aprire {port}: {exc}")
            return None
        try:
            banner = _read_until(ser, time.time() + settle)  # le schede si riavviano all'apertura
            ser.write(b"\r\n\r\n")
            banner += _read_until(ser, time.time() + 0.4)
            ser.write(b"$I\n")
            info = _read_until(ser, time.time() + 2.5, end_ok)
            if not any(end_ok(l) or l.startswith("[") or "grbl" in l.lower() for l in banner + info):
                continue  # niente di sensato: velocità sbagliata
            ser.write(b"$$\n")
            raw = _read_until(ser, time.time() + 4.0, end_ok)
            settings = {}
            for l in raw:
                m = re.match(r"^\$(\d+)=(.*)$", l)
                if m:
                    settings[int(m.group(1))] = m.group(2).strip()
            return dict(baud=baud, banner=[l for l in banner if l not in ("ok",)],
                        info=[l for l in info if l.startswith("[")], settings=settings)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
    return None
