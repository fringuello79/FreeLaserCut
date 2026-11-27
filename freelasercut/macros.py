# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Macro (0.23.5, idea di Mauro D.): pulsanti personali nella scheda Movimento che mandano alla scheda poche righe
di G-code o di comandi GRBL scritte dall'utente (per esempio l'autofocus della propria macchina, l'aria, la testa in
posizione di parcheggio).

Solo calcolo e controlli, niente Qt: la finestra e i pulsanti sono in ui/macro_ui.py.
Regole di sicurezza:
- partono solo con la macchina collegata, ferma e pronta (Idle), senza lavori, verifiche o autofocus in corso;
- non con la K40 (la sua scheda non capisce il G-code);
- se una macro accende il laser (M3/M4) o cambia le impostazioni della scheda ($n=…, $RST…) il programma chiede
  conferma ogni volta;
- se una macro accende il laser e non lo rispegne, alla fine si aggiunge «M5».
"""
import json
import re

from .i18n import tr

KEY = "macros_v1"  # preferenza: elenco JSON [{"name": ..., "code": ...}]
MAX_MACROS = 12
MAX_LINES = 40
MAX_LINE_LEN = 120  # GRBL accetta 80 caratteri (grblHAL e FluidNC di più): il controllo vero lo fa la scheda
MAX_NAME = 24

_LASER_ON = re.compile(r"(?<![A-Z0-9.])M0*[34](?![0-9.])", re.I)
_LASER_OFF = re.compile(r"(?<![A-Z0-9.])M0*5(?![0-9.])", re.I)
_SETTINGS = re.compile(r"^\$(\d+\s*=|RST\b|N\d*\s*=|I\s*=|SLP\b)", re.I)


def clean_name(name):
    name = " ".join(str(name or "").split())
    return name[:MAX_NAME]


def parse(code):
    """Testo scritto dall'utente -> (righe da mandare, errori). Commenti «;…» e «(…)» e righe vuote tolti."""
    lines, errors = [], []
    for n, raw in enumerate(str(code or "").splitlines(), 1):
        line = raw.split(";", 1)[0]
        line = re.sub(r"\([^)]*\)", "", line).strip()
        if not line:
            continue
        if any(ord(c) < 32 or ord(c) == 127 or ord(c) > 126 for c in line):
            errors.append(tr("riga {0}: ci sono caratteri che la scheda non capisce", n))
            continue
        if len(line) > MAX_LINE_LEN:
            errors.append(tr("riga {0}: troppo lunga (al massimo {1} caratteri)", n, MAX_LINE_LEN))
            continue
        lines.append(line)
    if len(lines) > MAX_LINES:
        errors.append(tr("troppe righe: al massimo {0}", MAX_LINES))
    if not lines and not errors:
        errors.append(tr("non c'è nessun comando"))
    return lines, errors


def risks(lines):
    """Che cosa fa di delicato la macro: {"laser", "settings"}."""
    out = set()
    for line in lines:
        if _LASER_ON.search(line):
            out.add("laser")
        if _SETTINGS.match(line):
            out.add("settings")
    return out


def with_laser_off(lines):
    """Se l'ultimo comando del laser accende (M3/M4), alla fine si aggiunge M5."""
    last = None
    for line in lines:
        for m in re.finditer(r"(?<![A-Z0-9.])M0*([345])(?![0-9.])", line, re.I):
            last = m.group(1)
    if last in ("3", "4"):
        return list(lines) + ["M5"]
    return list(lines)


def load(qs):
    """Le macro salvate, ripulite: un valore rovinato vale come nessuna macro."""
    try:
        data = json.loads(qs.value(KEY, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    if not isinstance(data, list):
        return out
    for d in data:
        if not isinstance(d, dict):
            continue
        name, code = clean_name(d.get("name")), d.get("code")
        if name and isinstance(code, str) and len(code) <= MAX_LINES * (MAX_LINE_LEN + 80):
            out.append({"name": name, "code": code})
        if len(out) >= MAX_MACROS:
            break
    return out


def save(qs, macros):
    data = [{"name": clean_name(m["name"]), "code": m["code"]} for m in macros[:MAX_MACROS] if clean_name(m["name"])]
    qs.setValue(KEY, json.dumps(data, ensure_ascii=False))
    return data


def why_not(ctl):
    """Motivo per cui una macro ora non può partire, o None."""
    from .grbl import K40_PORT

    if not ctl.connected:
        return tr("Collega prima il laser.")
    if ctl.port == K40_PORT:
        return tr("Con la K40 le macro non si possono usare: la sua scheda non capisce il G-code.")
    if ctl.job_active or getattr(ctl, "_check", None) is not None or ctl.autofocusing or ctl.busy:
        return tr("C'è già qualcosa in corso: aspetta che la macchina sia ferma.")
    state = ctl.last_status.get("state")
    if state != "Idle":
        return tr("La macchina non è ferma e pronta (stato: {0}). Se è in allarme, sbloccala o fai l'homing.",
                  state or "?")
    return None


def run(ctl, lines):
    """Manda le righe (già controllate e confermate) come la Console: anche la copia delle impostazioni della scheda
    prima di cambiarne una resta attiva. Ritorna le righe mandate."""
    sent = with_laser_off(lines)
    for line in sent:
        ctl.send_line(line)
    return sent
