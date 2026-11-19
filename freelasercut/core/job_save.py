# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.0: il lavoro in corso salvato sul disco, per riprenderlo anche dopo che è mancata la corrente al PC.

All'avvio del lavoro si scrivono il G-code (ultimo-lavoro.gcode) e una scheda (ultimo-lavoro.json) con il numero di
righe, l'impronta del G-code e la riga a cui è arrivata la macchina; durante il lavoro si aggiorna solo la scheda.
Finito bene, si cancella tutto. Al riavvio, se la scheda dice che il lavoro non è finito, il programma propone di
riprenderlo. Tutto resta sul PC: niente viene mandato altrove.
"""
import hashlib
import json
import os
import time

GCODE = "ultimo-lavoro.gcode"
CARD = "ultimo-lavoro.json"


def _paths(folder):
    return os.path.join(folder, GCODE), os.path.join(folder, CARD)


def _digest(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        try:
            os.fsync(fh.fileno())  # deve restare anche se il PC si spegne di colpo
        except OSError:
            pass
    os.replace(tmp, path)


def start(folder, lines, plate=None, name=""):
    """Salva il lavoro che parte. -> la scheda (dizionario) o None se non si riesce a scrivere."""
    try:
        os.makedirs(folder, exist_ok=True)
        text = "\n".join(lines) + "\n"
        g, c = _paths(folder)
        _write_atomic(g, text)
        card = {"version": 1, "lines": len(lines), "sha1": _digest(text), "acked": 0, "started": time.time(),
                "updated": time.time(), "plate": plate, "name": str(name or "")[:120]}
        _write_atomic(c, json.dumps(card))
        return card
    except (OSError, ValueError):
        return None


def progress(folder, card, acked):
    """Aggiorna la riga raggiunta (solo la scheda, poche decine di byte). -> True se scritta."""
    if card is None:
        return False
    try:
        card["acked"] = int(acked)
        card["updated"] = time.time()
        _write_atomic(_paths(folder)[1], json.dumps(card))
        return True
    except (OSError, TypeError, ValueError):
        return False


def clear(folder):
    for p in _paths(folder):
        try:
            os.remove(p)
        except OSError:
            pass


def load(folder):
    """-> (righe, riga raggiunta, scheda) se c'è un lavoro non finito da riprendere, altrimenti None. Un G-code
    che non corrisponde alla scheda (rovinato, cambiato a mano) non si riprende."""
    g, c = _paths(folder)
    try:
        with open(c, encoding="utf-8") as fh:
            card = json.load(fh)
        with open(g, encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
    except (OSError, ValueError):
        return None
    if not isinstance(card, dict) or _digest(text) != card.get("sha1"):
        return None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    try:
        acked = int(card.get("acked", 0))
    except (TypeError, ValueError):
        return None
    if len(lines) != card.get("lines") or not 0 < acked < len(lines):
        return None
    return lines, acked, card
