# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Testo variabile: numeri di serie, data e ora, campi da un file CSV.

Nel testo si scrivono dei segnaposto tra graffe:
  {N}        numero di serie            {N:3}  con 3 cifre (001, 002…)
  {DATA}     data di oggi (gg/mm/aaaa)  {ANNO} anno       {ORA} ora (hh:mm)
  {Nome}     colonna "Nome" della riga corrente del CSV
Ogni copia di una serie a griglia può avere uno scostamento (copia 1 = N, copia 2 = N+passo…):
così una tavola di 20 portachiavi esce numerata in un solo lavoro, e il lavoro dopo continua.
"""
import csv
import re
import time

_TOKEN = re.compile(r"\{([^{}]+)\}")

STATE = {
    "serial": 1,  # numero corrente
    "step": 1,  # incremento
    "pad": 0,  # cifre minime predefinite
    "csv": "",  # percorso del CSV
    "rows": [],  # righe del CSV (dict)
    "row": 0,  # riga corrente
    "auto": True,  # avanza da solo a fine lavoro
}
_listeners = []


def on_change(fn):
    _listeners.append(fn)


def changed():
    for fn in list(_listeners):
        fn()


def has_vars(text):
    return bool(text) and _TOKEN.search(text) is not None


def columns():
    rows = STATE.get("rows") or []
    return list(rows[0].keys()) if rows else []


def expand(text, offset=0, state=None):
    """Sostituisce i segnaposto. I segnaposto sconosciuti restano come sono (si vede subito l'errore)."""
    if not has_vars(text):
        return text
    st = state or STATE
    now = time.localtime()
    rows = st.get("rows") or []
    row = rows[(st.get("row", 0) + offset) % len(rows)] if rows else {}
    low = {k.lower(): v for k, v in row.items()}

    def sub(m):
        key = m.group(1).strip()
        up = key.upper()
        if up == "N" or up.startswith("N:"):
            pad = st.get("pad", 0)
            if ":" in key:
                try:
                    pad = int(key.split(":", 1)[1])
                except ValueError:
                    pass
            n = int(st.get("serial", 1)) + offset * int(st.get("step", 1))
            return str(n).zfill(pad)
        if up == "DATA":
            return time.strftime("%d/%m/%Y", now)
        if up == "ANNO":
            return time.strftime("%Y", now)
        if up == "ORA":
            return time.strftime("%H:%M", now)
        if key.lower() in low:
            return str(low[key.lower()])
        return m.group(0)

    return _TOKEN.sub(sub, text)


def load_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","
        rows = [dict(r) for r in csv.DictReader(fh, dialect=dialect)]
    STATE["csv"] = path
    STATE["rows"] = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]
    STATE["row"] = 0
    changed()
    return len(rows)


def advance(copies=1):
    """Dopo un lavoro: avanza numero di serie e riga del CSV di tante posizioni quante sono le copie."""
    STATE["serial"] = int(STATE["serial"]) + int(STATE["step"]) * copies
    if STATE.get("rows"):
        STATE["row"] = (STATE["row"] + copies) % len(STATE["rows"])
    changed()


def to_dict():
    d = {k: v for k, v in STATE.items() if k != "rows"}
    d["rows"] = STATE.get("rows", [])
    return d


def from_dict(d):
    STATE.update({"serial": 1, "step": 1, "pad": 0, "csv": "", "rows": [], "row": 0, "auto": True})
    if d:
        STATE.update({k: v for k, v in d.items() if k in STATE})
    changed()
