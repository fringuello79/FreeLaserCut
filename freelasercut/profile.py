# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Profilo macchina: descrive il laser e genera i limiti per il G-code.

Il profilo "Longer B1 40W" nasce con i valori di targa e viene poi
riscritto con i valori reali letti dalla macchina ($I e $$).
"""
import json
import os
import re
from dataclasses import asdict, dataclass, field
from freelasercut.i18n import tr  # noqa: E402


LEGACY_DIR = "Freeburn"  # nome delle versioni fino alla 0.5.0
FIRST_RUN_FLAG = "avviso_sicurezza_ok"


def config_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "FreeLaserCut")
    if not os.path.isdir(path):
        old = os.path.join(base, LEGACY_DIR)
        if os.path.isdir(old):  # aggiornamento da Freeburn: profili, materiali, camera e impostazioni restano
            try:
                import shutil

                shutil.copytree(old, path, ignore=shutil.ignore_patterns("remote.json", "*.log"))
                with open(os.path.join(path, FIRST_RUN_FLAG), "w", encoding="utf-8") as fh:
                    fh.write("dati copiati da Freeburn\n")
            except OSError:
                pass
    os.makedirs(os.path.join(path, "profiles"), exist_ok=True)
    return path


def migrate_qsettings():
    """Copia una volta le preferenze (porta, finestre, cartelle) dal vecchio nome Freeburn."""
    from PySide6.QtCore import QSettings

    new = QSettings("FreeLaserCut", "FreeLaserCut")
    if new.value("_migrato_da_freeburn") or new.allKeys():
        return new
    old = QSettings(LEGACY_DIR, LEGACY_DIR)
    for k in old.allKeys():
        new.setValue(k, old.value(k))
    new.setValue("_migrato_da_freeburn", 1)
    new.sync()
    return new


def _f(settings, n, default):
    try:
        return float(settings[n])
    except (KeyError, ValueError, TypeError):
        return default


@dataclass
class MachineProfile:
    name: str = "Longer B1 40W"
    model: str = "Longer B1 40W"
    source: str = tr("valori di targa")  # oppure "letto dalla macchina"
    firmware: str = ""
    vendor_fw: str = ""  # es. "LGT V1.2.3" (firmware Longer)
    board: str = ""  # es. "LS_ESP32"
    rx_buffer: int = 128
    planner_blocks: int = 16
    negative_space: object = None  # True/False dopo il primo homing, None = non ancora noto
    hard_limits: bool = False
    junction_dev: float = 0.01
    baud: int = 115200
    bed_x: float = 450.0
    bed_y: float = 440.0
    s_max: float = 1000.0
    s_min: float = 0.0
    laser_mode: bool = True
    homing: bool = True
    soft_limits: bool = False
    max_rate_x: float = 36000.0
    max_rate_y: float = 36000.0
    accel_x: float = 2500.0
    accel_y: float = 2500.0
    steps_x: float = 80.0
    steps_y: float = 80.0
    spot_x_mm: float = 0.10
    spot_y_mm: float = 0.15
    focus_mm: float = 50.0
    optical_power: str = "44–48 W (4 diodi, 450–460 nm)"
    air_on: str = "M8"
    air_off: str = "M9"
    raw_settings: dict = field(default_factory=dict)

    @classmethod
    def from_machine(cls, settings, info_lines=None, base=None):
        p = base or cls()
        s = {int(k): v for k, v in settings.items()}
        p.raw_settings = {str(k): v for k, v in sorted(s.items())}
        p.source = tr("letto dalla macchina")
        p.s_max = _f(s, 30, p.s_max)
        p.s_min = _f(s, 31, p.s_min)
        p.laser_mode = _f(s, 32, 1) >= 1
        p.homing = _f(s, 22, 1) >= 1
        p.soft_limits = _f(s, 20, 0) >= 1
        p.max_rate_x = _f(s, 110, p.max_rate_x)
        p.max_rate_y = _f(s, 111, p.max_rate_y)
        p.accel_x = _f(s, 120, p.accel_x)
        p.accel_y = _f(s, 121, p.accel_y)
        p.steps_x = _f(s, 100, p.steps_x)
        p.steps_y = _f(s, 101, p.steps_y)
        p.hard_limits = _f(s, 21, 0) >= 1
        p.junction_dev = _f(s, 11, p.junction_dev)
        travel_x, travel_y = _f(s, 130, 0), _f(s, 131, 0)
        if travel_x > 10:
            p.bed_x = travel_x
        if travel_y > 10:
            p.bed_y = travel_y
        for line in info_lines or []:
            m = re.match(r"\[VER:([^\]]*)\]", line)
            if m:
                p.firmware = m.group(1).strip(":")
            m = re.match(r"\[OPT:[^,\]]*,(\d+),(\d+)", line)
            if m:
                p.planner_blocks, p.rx_buffer = int(m.group(1)), int(m.group(2))
            m = re.match(r"\[MSG:FW:([^|\]]*)(?:\|MB:([^\]]*))?", line)
            if m:
                p.vendor_fw = m.group(1).strip()
                p.board = (m.group(2) or "").strip()
            m = re.match(r"^\[(LGT[^\]]*)\]$", line)
            if m and not p.vendor_fw:
                p.vendor_fw = m.group(1).strip()
        return p

    def firmware_label(self):
        parts = [x for x in (self.vendor_fw, f"GRBL {self.firmware}" if self.firmware else "", self.board) if x]
        return "  ·  ".join(parts)

    def bed_offset(self):
        """Da coordinate macchina (MPos) a coordinate del piano (0..bed): piano = MPos + offset."""
        if self.negative_space:
            return (self.bed_x, self.bed_y)
        return (0.0, 0.0)

    def to_machine(self, x, y):
        ox, oy = self.bed_offset()
        return x - ox, y - oy

    def to_bed(self, mx, my):
        ox, oy = self.bed_offset()
        return mx + ox, my + oy

    def checks(self):
        """Lista di (livello, messaggio, correzione_suggerita|None). livello: ok/info/warn."""
        out = []
        if self.laser_mode:
            out.append(("ok", tr("Modalità laser attiva ($32=1): la potenza segue la velocità"), None))
        else:
            out.append(("warn", tr("Modalità laser disattivata: nelle curve e in accelerazione il legno si brucia di più"),
                        (32, "1")))
        if self.s_max == 1000:
            out.append(("ok", tr("Potenza su scala S0–S1000 (1000 livelli)"), None))
        else:
            out.append(("info", tr("Potenza massima S{0:g}: FreeLaserCut scala le percentuali su questo valore", self.s_max), None))
        if self.homing:
            out.append(("ok", tr("Homing attivo ($22=1): l'origine macchina è sempre la stessa"), None))
        else:
            out.append(("info", tr("Homing disattivato: l'origine è dove si trova la testa all'accensione"), None))
        if abs(self.bed_x - 450) > 5 or abs(self.bed_y - 440) > 5:
            out.append(("info", tr("Corsa dichiarata dalla scheda {0:g}×{1:g} mm (targa 450×440)", self.bed_x, self.bed_y), None))
        else:
            out.append(("ok", tr("Area di lavoro {0:g}×{1:g} mm", self.bed_x, self.bed_y), None))
        if not self.soft_limits and self.homing:
            out.append(("info", tr("Soft limits disattivi ($20=0): FreeLaserCut controlla comunque i bordi prima di inviare"), None))
        if self.max_rate_x < 3000 or self.max_rate_y < 3000:
            out.append(("warn", tr("Velocità massima molto bassa: incisioni raster lente"), None))
        if self.board:
            out.append(("ok", tr("Scheda {0}, buffer {1} byte e {2} blocchi: FreeLaserCut usa il buffer pieno per un raster più fluido", self.board, self.rx_buffer, self.planner_blocks), None))
        if self.hard_limits:
            out.append(("info", tr("Finecorsa di sicurezza attivi ($21=1): se la testa li tocca la macchina va in "
                                "allarme e serve l'homing"), None))
        acc = min(self.accel_x, self.accel_y)
        if acc < 1000:
            out.append(("info", tr("Accelerazione {0:g} mm/s²: dolce per il telaio; FreeLaserCut ne tiene conto nella stima dei tempi", acc), None))
        if self.negative_space is None:
            out.append(("info", tr("Fai un homing: FreeLaserCut impara come la scheda conta le coordinate "
                                "e allinea piano, camera e testa"), None))
        else:
            how = tr("negative (0 = fine corsa)") if self.negative_space else tr("positive dall'origine")
            out.append(("ok", tr("Coordinate macchina {0}: riconosciute all'homing", how), None))
        return out

    # ---------------------------------------------------------------- file
    def path(self):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", self.name).strip("_") or "profilo"
        return os.path.join(config_dir(), "profiles", f"{safe}.json")

    def save(self):
        path = self.path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @classmethod
    def load_default(cls):
        p = cls()
        if os.path.exists(p.path()):
            try:
                return cls.load(p.path())
            except (OSError, ValueError, TypeError):
                pass
        return p
