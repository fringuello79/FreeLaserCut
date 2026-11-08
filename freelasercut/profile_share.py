# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Esporta / importa un profilo macchina (.flcprofile), per condividerlo con chi ha la stessa macchina.

Un profilo importato arriva da qualcun altro: ogni valore viene controllato (numeri in intervalli ragionevoli,
comandi dell'aria solo tra quelli noti), i dati che dipendono dalla singola macchina (assi già provati, coordinate
negative scoperte con l'homing) ripartono da zero, e il profilo è segnato «dalla comunità», separato dai modelli
del catalogo verificati sulle pagine dei produttori. Niente viene scritto nella scheda.
"""
import json
import math
from dataclasses import asdict, fields

from . import __version__
from .profile import MachineProfile
from freelasercut.i18n import tr  # noqa: E402

EXT = ".flcprofile"
FORMAT = 1
COMMUNITY = tr("dalla comunità (importato)")
# comandi dell'aria ammessi: un profilo condiviso non deve poter mandare alla scheda altro (es. accendere il laser)
AIR_OK = ("", "M7", "M8", "M9", "M106", "M107")
# intervalli accettati: fuori da qui il profilo è rifiutato (meglio un errore chiaro che una macchina contro il telaio)
RANGES = {
    "bed_x": (10.0, 3000.0), "bed_y": (10.0, 3000.0),
    "max_rate_x": (60.0, 200000.0), "max_rate_y": (60.0, 200000.0),
    "accel_x": (1.0, 100000.0), "accel_y": (1.0, 100000.0),
    "steps_x": (1.0, 10000.0), "steps_y": (1.0, 10000.0),
    "s_max": (1.0, 100000.0), "s_min": (0.0, 100000.0),
    "spot_x_mm": (0.005, 2.0), "spot_y_mm": (0.005, 2.0),
    "focus_mm": (0.0, 500.0), "junction_dev": (0.0, 10.0),
    "rx_buffer": (64, 4096), "planner_blocks": (1, 512), "baud": (9600, 2000000),
    "af_distance": (0.0, 100.0), "af_travel": (1.0, 200.0), "af_feed": (1.0, 3000.0), "af_slow": (1.0, 1000.0),
}
TEXT_MAX = 120
# legati alla singola macchina di chi esporta: si riparte da zero
RESET = {"tested_x": False, "tested_y": False, "axes_tested": False, "negative_space": None, "origin_corner": ""}


def export_profile(profile, path):
    data = asdict(profile)
    for k in RESET:  # chi importa deve provarli sulla sua macchina
        data.pop(k, None)
    doc = {"freelasercut_profile": FORMAT, "exported_by": f"FreeLaserCut {__version__}", "profile": data}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    return path


def _num(name, v, kind):
    try:
        x = kind(v)
    except (TypeError, ValueError):
        raise ValueError(tr("valore non valido per «{0}»: {1}", name, v)) from None
    if isinstance(x, float) and not math.isfinite(x):
        raise ValueError(tr("valore non valido per «{0}»: {1}", name, v))
    lo, hi = RANGES[name]
    if not lo <= x <= hi:
        raise ValueError(tr("«{0}» fuori dai limiti ({1}): {2:g}", name, f"{lo:g}–{hi:g}", x))
    return x


def read_profile(path):
    """-> MachineProfile controllato. ValueError con il motivo se il file non è un profilo valido."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(tr("il file non si legge: {0}", ex)) from None
    if not isinstance(doc, dict) or doc.get("freelasercut_profile") != FORMAT or not isinstance(doc.get("profile"), dict):
        raise ValueError(tr("non è un profilo macchina di FreeLaserCut"))
    src = doc["profile"]
    types = {f.name: f.type for f in fields(MachineProfile)}
    base = MachineProfile()
    out = {}
    for k, v in src.items():
        if k not in types or k in RESET:
            continue
        default = getattr(base, k)
        if k in RANGES:
            out[k] = _num(k, v, int if isinstance(default, int) and not isinstance(default, bool) else float)
        elif isinstance(default, bool):
            if not isinstance(v, bool):
                raise ValueError(tr("valore non valido per «{0}»: {1}", k, v))
            out[k] = v
        elif k in ("air_on", "air_off"):
            v = str(v).strip().upper()
            if v not in AIR_OK:
                raise ValueError(tr("comando dell'aria non ammesso in un profilo condiviso: {0}", v))
            out[k] = v
        elif k == "raw_settings":
            if not isinstance(v, dict):
                raise ValueError(tr("valore non valido per «{0}»: {1}", k, "…"))
            clean = {}
            for sk, sv in v.items():  # solo per consultazione: $n = numero
                if str(sk).isdigit() and len(str(sv)) <= 20:
                    try:
                        float(sv)
                    except (TypeError, ValueError):
                        continue
                    clean[str(int(sk))] = str(sv)
            out[k] = clean
        elif k == "scan_offsets":
            if not isinstance(v, list):
                raise ValueError(tr("valore non valido per «{0}»: {1}", k, "…"))
            pairs = []
            for item in v[:50]:
                try:
                    s, d = float(item[0]), float(item[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if 0 < s <= 200000 and abs(d) <= 5 and math.isfinite(s) and math.isfinite(d):
                    pairs.append([s, d])
            out[k] = pairs
        elif isinstance(default, str):
            out[k] = str(v)[:TEXT_MAX].replace("\n", " ").strip()
    if "bed_x" not in out or "bed_y" not in out:
        raise ValueError(tr("nel profilo manca l'area di lavoro"))
    if out.get("s_min", 0.0) > out.get("s_max", base.s_max):
        raise ValueError(tr("potenza minima maggiore della massima"))
    p = MachineProfile(**out)
    if not p.name:
        p.name = tr("Profilo importato")
    p.source = COMMUNITY
    return p


# ====================================================================== profili dei produttori (0.17.14)
DEVICE_EXT = ".lbdev"
MAKER = tr("dal file del produttore")
_GRBL_NAMES = ("GRBL", "FLUIDNC", "GRBLHAL")


def read_device_file(path):
    """Profilo macchina dal file che molti produttori mettono sulla microSD o nel sito (.lbdev, testo JSON).
    Si leggono solo i dati della macchina: nome, area di lavoro, velocità della porta, scala di potenza,
    origine, asse Z, aria e la correzione della scansione avanti e indietro. ValueError con il motivo."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(tr("il file non si legge: {0}", ex)) from None
    devs = doc.get("DeviceList") if isinstance(doc, dict) else None
    if not isinstance(devs, list) or not devs or not isinstance(devs[0], dict):
        raise ValueError(tr("non è un profilo macchina che FreeLaserCut sa leggere"))
    d = devs[0]
    s = d.get("Settings") if isinstance(d.get("Settings"), dict) else {}
    kind = f"{d.get('Name', '')} {d.get('ProfilePath', '')}".upper()
    if not any(k in kind for k in _GRBL_NAMES):
        raise ValueError(tr("la macchina del file non usa una scheda GRBL ({0}): FreeLaserCut funziona solo con le "
                            "schede GRBL", str(d.get("Name", "?"))[:40]))
    out = {"bed_x": _num("bed_x", d.get("Width"), float), "bed_y": _num("bed_y", d.get("Height"), float)}
    name = str(d.get("DisplayName") or "").replace("\n", " ").strip()[:TEXT_MAX] or tr("Profilo del produttore")
    out["name"] = out["model"] = name
    if "BaudRate" in s:
        out["baud"] = _num("baud", s["BaudRate"], int)
    if "S_Scale" in s:
        out["s_max"] = _num("s_max", s["S_Scale"], float)
    # stime di velocità e accelerazioni (mm/s e mm/s²): collegando la macchina si leggono quelle vere ($110…$121)
    for src, dst, k in (("Sim_MaxSpeedX", "max_rate_x", 60.0), ("Sim_MaxSpeedY", "max_rate_y", 60.0),
                        ("Sim_MaxAccelX", "accel_x", 1.0), ("Sim_MaxAccelY", "accel_y", 1.0)):
        try:
            v = float(s[src]) * k
            out[dst] = _num(dst, v, float)
        except (KeyError, TypeError, ValueError):
            pass
    # origine della macchina: AlignH 0 sinistra / 2 destra, AlignV 0 dietro (in alto) / 2 davanti (in basso)
    h, v = s.get("AlignH"), s.get("AlignV")
    if h in (0, 2) and v in (0, 2):
        out["origin_corner"] = ("f" if v == 2 else "b") + ("l" if h == 0 else "r")
    if s.get("EnableZ") is True:
        out["z_motor"] = True
    if s.get("AirAssistM7") is True:
        out["air_on"] = "M7"
    # correzione della scansione: velocità in mm/s; il valore del file è metà dello sfasamento misurato fra andata
    # e ritorno, FreeLaserCut tiene lo sfasamento intero (e ne applica metà per verso)
    pairs = []
    if d.get("ReverseIntervalCompensation", True):
        for item in (d.get("ReverseIntervals") or [])[:50]:
            try:
                sp, sh = float(item["Speed"]) * 60.0, 2.0 * float(item["LineShift"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 < sp <= 200000 and abs(sh) <= 5 and math.isfinite(sp) and math.isfinite(sh):
                pairs.append([round(sp, 1), round(sh, 4)])
    out["scan_offsets"] = pairs
    if out.get("s_min", 0.0) > out.get("s_max", MachineProfile().s_max):
        raise ValueError(tr("potenza minima maggiore della massima"))
    p = MachineProfile(**out)
    p.source = MAKER
    return p


def read_any(path):
    """Profilo FreeLaserCut (.flcprofile) o file del produttore (.lbdev), secondo il contenuto."""
    if str(path).lower().endswith(DEVICE_EXT):
        return read_device_file(path)
    return read_profile(path)
