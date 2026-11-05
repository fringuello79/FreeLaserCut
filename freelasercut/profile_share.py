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
