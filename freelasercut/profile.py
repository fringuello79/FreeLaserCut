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

    from .settings_store import app_settings

    new = app_settings()
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
    # scansione avanti e indietro: [[velocità mm/min, sfasamento mm fra righe di andata e ritorno], ...]
    scan_offsets: list = field(default_factory=list)
    # la scheda non conosce G55 (es. firmware Acmer): il sistema «assoluto» si fa in G54 togliendo il suo offset
    no_g55: bool = False
    # assi invertiti rispetto al piano di FreeLaserCut (0,0 davanti a sinistra): per esempio macchine con l'origine
    # dietro, o motori montati al contrario. Il piano resta come lo vedi; cambiano coordinate inviate e jog.
    invert_x: bool = False
    invert_y: bool = False
    # angolo dello 0 scelto nella configurazione guidata: "fl" davanti a sinistra, "bl" dietro a sinistra, "fr" davanti
    # a destra, "br" dietro a destra; "" = non indicato. Serve solo per gli assi non ancora provati con le frecce:
    # quando l'homing dice se le coordinate sono negative, il loro verso si ricalcola da qui.
    origin_corner: str = ""
    # assi provati con le frecce (o decisi a mano con le spunte): il loro verso è un fatto, non si ricalcola più
    tested_x: bool = False
    tested_y: bool = False
    axes_tested: bool = False  # tutti e due (dalla 0.13.0; resta per i profili già salvati)
    # 0.17.12: asse Z motorizzato e autofocus con sonda (comando GRBL G38.2). La sonda deve essere collegata
    # all'ingresso «Probe» della scheda, non a un finecorsa.
    z_motor: bool = False
    af_probe: bool = False
    af_distance: float = 8.0  # dopo il tocco la testa si allontana di tanto: distanza di fuoco dal materiale (mm)
    af_travel: float = 30.0  # corsa massima in cerca del materiale (mm): oltre, si ferma con un errore
    af_feed: float = 200.0  # velocità di ricerca (mm/min)
    af_slow: float = 40.0  # secondo tocco, lento e preciso (mm/min)
    af_toward_minus: bool = True  # verso il materiale = Z− (normale); False per le macchine al contrario

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
        from .grbl_codes import travel_ok

        if travel_ok(travel_x):  # 0.17.2: un valore non credibile (es. 234500) non diventa il piano
            p.bed_x = travel_x
        if travel_ok(travel_y):
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

    def scan_offset(self, speed):
        """Sfasamento (mm) fra le righe di andata e quelle di ritorno alla velocità data (mm/min).
        Fra due valori della tabella si interpola; fuori dalla tabella il valore cresce in proporzione alla
        velocità, perché il ritardo del laser è un tempo. Tabella vuota = nessuna correzione."""
        pts = []
        for item in self.scan_offsets or []:
            try:
                s, d = float(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if s > 0:
                pts.append((s, d))
        if not pts or speed <= 0:
            return 0.0
        pts.sort()
        if speed <= pts[0][0]:
            return pts[0][1] * speed / pts[0][0]
        if speed >= pts[-1][0]:
            return pts[-1][1] * speed / pts[-1][0]
        for (sa, da), (sb, db) in zip(pts, pts[1:]):
            if sa <= speed <= sb:
                return da + (db - da) * (speed - sa) / (sb - sa)
        return 0.0

    def firmware_label(self):
        parts = [x for x in (self.vendor_fw, f"GRBL {self.firmware}" if self.firmware else "", self.board) if x]
        return "  ·  ".join(parts)

    def bed_offset(self):
        """Da coordinate macchina (MPos) a coordinate del piano (0..bed): piano = MPos + offset."""
        if self.negative_space:
            return (self.bed_x, self.bed_y)
        return (0.0, 0.0)

    def axis_sign(self):
        """(+1|-1, +1|-1): verso degli assi della macchina rispetto al piano."""
        return (-1.0 if self.invert_x else 1.0, -1.0 if self.invert_y else 1.0)

    @staticmethod
    def corner_inversion(corner, negative=None):
        """(inverti X, inverti Y) che mettono lo 0 della macchina nell'angolo indicato del piano.
        Con le coordinate positive (quasi tutti i laser a diodo) lo 0 è dove gli assi partono; con le coordinate
        negative (GRBL classico dopo l'homing) lo 0 sta all'altra estremità, quindi il verso si rovescia."""
        corner = corner or "fl"
        neg = bool(negative)
        return (("r" in corner[1:]) != neg, (corner[0] == "b") != neg)

    def corner_now(self):
        """Angolo del piano in cui cade lo 0 della macchina con le impostazioni attuali (sempre ricavato dal verso
        degli assi e dalle coordinate: così non resta mai indietro rispetto a quello che fa la macchina)."""
        neg = bool(self.negative_space)
        return ("b" if self.invert_y != neg else "f") + ("r" if self.invert_x != neg else "l")

    def recompute_untested_axes(self):
        """Dopo l'homing (coordinate negative o no ora note): il verso degli assi NON provati segue l'angolo scelto.
        Gli assi provati con le frecce restano come sono. -> True se è cambiato qualcosa."""
        if not self.origin_corner:
            return False
        ix, iy = self.corner_inversion(self.origin_corner, self.negative_space)
        old = (self.invert_x, self.invert_y)
        if not self.tested_x:
            self.invert_x = ix
        if not self.tested_y:
            self.invert_y = iy
        return (self.invert_x, self.invert_y) != old

    def to_machine(self, x, y):
        ox, oy = self.bed_offset()
        if self.invert_x:
            x = self.bed_x - x
        if self.invert_y:
            y = self.bed_y - y
        return x - ox, y - oy

    def to_bed(self, mx, my):
        ox, oy = self.bed_offset()
        bx, by = mx + ox, my + oy
        if self.invert_x:
            bx = self.bed_x - bx
        if self.invert_y:
            by = self.bed_y - by
        return bx, by

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
        # 0.17.4: prima il confronto era sempre con la targa del Longer B1 (450×440), anche per le altre macchine
        nom = self.nominal_area()
        if nom and min(abs(self.bed_x - nom[0]) + abs(self.bed_y - nom[1]),
                       abs(self.bed_x - nom[1]) + abs(self.bed_y - nom[0])) > 10:
            out.append(("info", tr("Area di lavoro {0:g}×{1:g} mm (il produttore dichiara {2:g}×{3:g})", self.bed_x,
                                   self.bed_y, nom[0], nom[1]), None))
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
        if "axes_tested" in known and "tested_x" not in known:  # profilo salvato dalla 0.13.0/0.13.1
            if known["axes_tested"]:
                known["tested_x"] = known["tested_y"] = True
            else:
                # quelle versioni salvavano un angolo anche senza sceglierlo (o ricavato da una prova a metà):
                # non lo do per vero, altrimenti il primo homing potrebbe capovolgere gli assi
                known["origin_corner"] = ""
        p = cls(**known)
        p.fix_bed()
        return p

    def nominal_area(self):
        """Area dichiarata dal produttore per il modello del profilo (mm), o None se il modello non è nel catalogo."""
        if self.model == "Longer B1 40W":
            return 450.0, 440.0
        try:
            from . import machines
        except ImportError:
            return None
        for n, _v, bx, by, *_ in machines.CATALOG:
            if n == self.model:
                return tuple(float(v) for v in machines.AREA_NOTE.get(n, (bx, by)))
        return None

    def fix_bed(self):
        """0.17.4: un profilo salvato con un'area non credibile (visto 365 × 32764 mm, dalla lettura della scheda delle
        versioni precedenti) torna all'area del modello, o a 400 mm per il laser generico; l'asse buono resta.
        Ritorna l'area di prima se l'ha cambiata (anche in self.bed_fixed), altrimenti None."""
        from .grbl_codes import travel_ok

        self.bed_fixed = None
        if travel_ok(self.bed_x) and travel_ok(self.bed_y):
            return None
        old = (self.bed_x, self.bed_y)
        if self.model == "Longer B1 40W":
            nx, ny = 450.0, 440.0
        else:
            from . import machines

            pre = machines.preset_profile(self.model) if self.model in machines.catalog_names() else None
            nx, ny = (pre.bed_x, pre.bed_y) if pre is not None else (400.0, 400.0)
        if not travel_ok(self.bed_x):
            self.bed_x = nx
        if not travel_ok(self.bed_y):
            self.bed_y = ny
        self.bed_fixed = old
        return old

    @classmethod
    def load_default(cls):
        p = cls()
        if os.path.exists(p.path()):
            try:
                return cls.load(p.path())
            except (OSError, ValueError, TypeError):
                pass
        return p
