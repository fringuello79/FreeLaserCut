# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Copie delle impostazioni della scheda GRBL ($$).

Prima che FreeLaserCut cambi un'impostazione della scheda (da Macchina, dalla console o da «Riconosci e adatta»),
salva da solo una copia di tutte le impostazioni lette ($$). Le copie sono file di testo leggibili, una riga
«$numero=valore» ciascuna: si possono anche incollare nella console. Il ripristino rimanda alla scheda solo i
valori diversi. Nessuna parte di questo modulo usa Qt.
"""
import os
import re
import time

from .profile import config_dir

KEEP = 40
_LINE = re.compile(r"^\s*\$(\d+)\s*=\s*(.*?)\s*$")
HEADER = "; FreeLaserCut: copia delle impostazioni della scheda ($$)"


def backup_dir():
    d = os.path.join(config_dir(), "impostazioni-scheda")
    os.makedirs(d, exist_ok=True)
    return d


def to_text(settings, info=(), reason="", port=""):
    lines = [HEADER, "; " + time.strftime("%Y-%m-%d %H:%M:%S")]
    if reason:
        lines.append("; motivo: " + reason)
    if port:
        lines.append("; porta: " + port)
    lines += ["; " + l for l in info or () if l.startswith("[")]
    lines += [f"${n}={v}" for n, v in sorted((int(k), str(v)) for k, v in settings.items())]
    return "\n".join(lines) + "\n"


def parse(text):
    """Testo di una copia (o di un $$ incollato) → {numero: "valore"}."""
    out = {}
    for line in str(text).splitlines():
        m = _LINE.match(line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def header_info(text):
    """Data, motivo, versione della scheda dalle righe «;» iniziali."""
    meta = {"date": "", "reason": "", "ver": ""}
    for line in str(text).splitlines()[:12]:
        if not line.startswith(";"):
            continue
        t = line[1:].strip()
        if re.match(r"^\d{4}-\d{2}-\d{2} ", t):
            meta["date"] = t
        elif t.startswith("motivo:"):
            meta["reason"] = t[7:].strip()
        elif t.startswith("[VER:"):
            meta["ver"] = t.strip("[]")[4:].strip(":")
    return meta


def list_backups(folder=None):
    """[(percorso, info)] dalla più recente."""
    folder = folder or backup_dir()
    out = []
    for fn in os.listdir(folder):
        if fn.lower().endswith(".txt"):
            p = os.path.join(folder, fn)
            try:  # una copia aperta e salvata da un editor in un'altra codifica non deve fermare niente
                with open(p, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
            except OSError:
                continue
            meta = header_info(txt)
            meta["count"] = len(parse(txt))
            meta["mtime"] = os.path.getmtime(p)
            out.append((p, meta))
    out.sort(key=lambda t: (t[1]["date"], t[1]["mtime"]), reverse=True)
    return out


def _same(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def save(settings, info=(), reason="manuale", port="", folder=None):
    """Salva la copia; se l'ultima copia ha già gli stessi valori non ne fa un'altra. Ritorna il percorso."""
    if not settings:
        return None
    folder = folder or backup_dir()
    prev = list_backups(folder)
    if prev:
        try:
            with open(prev[0][0], encoding="utf-8", errors="replace") as fh:
                old = parse(fh.read())
        except OSError:
            old = {}
        cur = {int(k): str(v) for k, v in settings.items()}
        if set(old) == set(cur) and all(_same(old[k], cur[k]) for k in cur):
            return prev[0][0]
    name = time.strftime("scheda-%Y%m%d-%H%M%S")
    path = os.path.join(folder, name + ".txt")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{name}-{n}.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_text(settings, info, reason, port))
    for p, _ in list_backups(folder)[KEEP:]:  # tengo le ultime KEEP copie
        try:
            os.remove(p)
        except OSError:
            pass
    return path


def diff(current, saved):
    """[(numero, valore attuale, valore della copia)] per le impostazioni che la scheda conosce e che cambiano."""
    cur = {int(k): str(v) for k, v in (current or {}).items()}
    out = []
    for n, v in sorted(saved.items()):
        if n in cur and not _same(cur[n], v):
            out.append((n, cur[n], v))
    return out


def restore_lines(current, saved):
    return [f"${n}={v}" for n, _, v in diff(current, saved)]
