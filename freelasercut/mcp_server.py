# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Server MCP di FreeLaserCut: Claude (app desktop o Claude Code) disegna e prepara i lavori in FreeLaserCut.

Si avvia da solo quando Claude lo chiama:   python -m freelasercut.mcp_server
Parla MCP su stdin/stdout (JSON-RPC 2.0, un messaggio per riga) e inoltra i comandi a FreeLaserCut
aperto sul PC (server locale 127.0.0.1, vedi freelasercut/remote.py). Se FreeLaserCut è chiuso lo apre.

Solo libreria standard: parte in un attimo e non dipende da Qt.
"""
import json
import os
import socket
import subprocess
import sys
import time

from . import __version__
from .profile import config_dir

PROTOCOL = "2025-06-18"

INSTRUCTIONS = (
    "FreeLaserCut è il programma di incisione e taglio laser dell'utente (Longer B1 40W, diodo blu 450 nm, GRBL). "
    "Unità: millimetri. Coordinate del piano: origine in basso a sinistra (davanti a sinistra), Y verso l'alto. "
    "Prima guarda lo stato (flc_status), poi crea/modifica; dopo modifiche importanti mostra il risultato con "
    "flc_snapshot. Livelli = colori 0..29: ogni livello ha modalità (line = taglio/contorno, fill = "
    "riempimento, image = immagine), velocità in mm/min e potenza in %. Per i valori usa la libreria materiali "
    "(flc_materials). Il laser non parte mai da solo: flc_machine con start_job apre una conferma che "
    "l'utente deve accettare davanti alla macchina. Non chiedere mai di saltare quella conferma."
)


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


N = {"type": "number"}
S = {"type": "string"}
B = {"type": "boolean"}
I = {"type": "integer"}
IDS = {"description": "id di una forma, lista di id, 'selection' o 'all' (default: selezione)",
       "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}
ANCHOR = {"type": "string", "description": "punto della forma da mettere in x,y: center (default), bottom_left, "
                                            "bottom_right, top_left, top_right, left, right"}

TOOLS = [
    ("flc_status", "status", "Stato di FreeLaserCut: progetto, numero di forme, selezione, livelli, macchina (connessa, "
     "stato, posizione della testa), misure del piano.", _obj({})),
    ("flc_list_shapes", "list_shapes", "Elenco delle forme del progetto con id, tipo, livello, posizione e misure (mm).",
     _obj({})),
    ("flc_snapshot", "snapshot", "Immagine PNG del disegno sul piano (o solo di alcune forme), per vedere il risultato.",
     _obj({"width": I, "ids": IDS})),
    ("flc_add_shape", "add_shape",
     "Crea una forma. type: rect, ellipse, circle, polygon, star, special (galleria: vedi flc_list_forms), "
     "path (svg_path = attributo d di un path SVG in mm, Y in giù come in SVG). width/height in mm; x,y = posizione "
     "del punto anchor (default: centro del piano). layer 0..29 (default: livello corrente).",
     _obj({"type": S, "width": N, "height": N, "x": N, "y": N, "anchor": ANCHOR, "layer": I, "corner_radius": N,
           "sides": I, "points": I, "ratio": N, "form": S, "param": N, "svg_path": S, "rotation": N}, ["type"])),
    ("flc_add_text", "add_text",
     "Crea un testo. size = altezza delle maiuscole in mm. font: nome di un font di sistema oppure un font a linea "
     "singola (futural, rowmans, scripts… vedi flc_list_fonts), veloci da incidere. arc = gradi d'arco per il "
     "testo curvo (+ a ponte, - a sorriso, 360 = cerchio). Il testo può contenere {N} {N:3} {DATA} {ANNO} {ORA}.",
     _obj({"text": S, "x": N, "y": N, "size": N, "font": S, "layer": I, "bold": B, "italic": B,
           "align": {"type": "string", "enum": ["left", "center", "right"]}, "arc": N, "anchor": ANCHOR,
           "letter_spacing": N, "upper": B, "weld": B}, ["text"])),
    ("flc_list_forms", "list_forms", "Forme della galleria (type=special): freccia, cuore, ingranaggio, scudo, "
     "medaglia con anello, etichetta con foro, targa… con il loro parametro.", _obj({})),
    ("flc_list_fonts", "list_fonts", "Font disponibili (a linea singola e di sistema).", _obj({"query": S})),
    ("flc_select", "select", "Seleziona forme (anche sullo schermo).", _obj({"ids": IDS})),
    ("flc_delete", "delete", "Elimina forme.", _obj({"ids": IDS}, ["ids"])),
    ("flc_transform", "transform",
     "Sposta, ridimensiona e ruota forme. dx/dy = spostamento; oppure x,y = nuova posizione del punto anchor. "
     "width/height = nuove misure (keep_ratio di default); scale = fattore; rotate = gradi in senso antiorario.",
     _obj({"ids": IDS, "dx": N, "dy": N, "x": N, "y": N, "width": N, "height": N, "keep_ratio": B, "rotate": N,
           "scale": N, "anchor": ANCHOR})),
    ("flc_set_text", "set_text", "Cambia un testo esistente (contenuto, altezza, font, curvatura, stile).",
     _obj({"id": S, "text": S, "size": N, "font": S, "arc": N, "bold": B, "italic": B, "align": S}, ["id"])),
    ("flc_set_shape_layer", "set_shape_layer", "Sposta forme su un livello (colore 0..29).",
     _obj({"ids": IDS, "layer": I}, ["ids", "layer"])),
    ("flc_arrange", "arrange",
     "Operazioni sulle forme: group, ungroup, weld, union, difference (la prima meno la seconda), intersection, xor, "
     "align_left/right/top/bottom/hcenter/vcenter/center, distribute_h, distribute_v, flip_h, flip_v, to_path, "
     "break_apart, lock, unlock, duplicate, bring_front, send_back, center_on_bed.",
     _obj({"action": S, "ids": IDS}, ["action"])),
    ("flc_offset", "offset", "Contorno parallelo (offset) di forme chiuse.",
     _obj({"distance": N, "ids": IDS, "direction": {"type": "string", "enum": ["out", "in", "both"]},
           "corner": {"type": "string", "enum": ["round", "miter", "square"]}, "keep_original": B}, ["distance"])),
    ("flc_array", "array", "Copie in serie: kind=grid (cols × rows, spazi gap_x/gap_y in mm) o circular (count "
     "copie attorno a center [x,y], su angle gradi). Il testo variabile si numera da solo nelle copie.",
     _obj({"kind": {"type": "string", "enum": ["grid", "circular"]}, "ids": IDS, "cols": I, "rows": I, "gap_x": N,
           "gap_y": N, "count": I, "center": {"type": "array", "items": N}, "angle": N})),
    ("flc_undo", "undo", "Annulla l'ultima operazione.", _obj({})),
    ("flc_redo", "redo", "Ripete l'operazione annullata.", _obj({})),
    ("flc_set_layer", "set_layer",
     "Impostazioni di un livello: mode (line, fill, offset_fill, image), speed_mm_min, power_max_pct, power_min_pct, "
     "passes, air, output (incidere sì/no), interval_mm, dpi, dither (grayscale, threshold, floyd, jarvis, stucki, "
     "atkinson, bayer, halftone), crosshatch, angle, kerf_mm, name.",
     _obj({"index": I, "mode": S, "speed_mm_min": N, "power_max_pct": N, "power_min_pct": N, "passes": I, "air": B,
           "output": B, "interval_mm": N, "dpi": N, "dither": S, "name": S, "crosshatch": B, "angle": N,
           "kerf_mm": N}, ["index"])),
    ("flc_list_layers", "list_layers", "Livelli usati e le loro impostazioni.", _obj({})),
    ("flc_materials", "list_materials", "Libreria materiali (tabella Longer B1 40W + voci dell'utente). query "
     "per filtrare, es. 'tiglio 3' o 'acrilico'.", _obj({"query": S})),
    ("flc_apply_material", "apply_material", "Applica a un livello i valori di un materiale della libreria.",
     _obj({"layer": I, "name": S, "operation": {"type": "string", "enum": ["incisione", "taglio"]},
           "thickness_mm": N}, ["layer", "name"])),
    ("flc_set_variables", "set_variables", "Testo variabile: prossimo numero di serie, incremento, cifre, avanzamento "
     "automatico, file CSV.", _obj({"serial": I, "step": I, "pad": I, "auto": B, "csv_path": S})),
    ("flc_import_file", "import_file", "Importa un file dal PC: SVG, DXF, PNG/JPG/BMP, progetti .lbrn2, e i file "
     "Gerber di un circuito stampato con i fori Excellon. Per un circuito passa in more_paths gli altri file della "
     "stessa basetta (rame, contorno, fori): restano a registro. mirror: specchia (lato sotto; se manca lo decide dal "
     "file). negative: true = incide lo spazio fra le piste (metodo della vernice, predefinito se c'è il rame), "
     "false = incide le piste. Due facce: passando insieme il rame del lato sopra e quello del lato sotto, il lato "
     "sopra va sul piano di lavoro attuale e il lato sotto, specchiato, su un piano nuovo nella stessa posizione "
     "(mirror non conta); rimettere la basetta al suo posto dopo averla girata resta compito di chi incide.",
     _obj({"path": S, "x": N, "y": N, "more_paths": {"type": "array", "items": S}, "mirror": B, "negative": B}, ["path"])),
    ("flc_open_project", "open_project", "Apre un progetto .flcut, .lbrn2 o .lbrn.", _obj({"path": S}, ["path"])),
    ("flc_save_project", "save_project", "Salva il progetto (.flcut).", _obj({"path": S})),
    ("flc_new_project", "new_project", "Nuovo progetto vuoto (rifiuta se ci sono modifiche non salvate).", _obj({})),
    ("flc_trace_image", "trace_image", "Vettorizza un'immagine: mode outline (contorni) o centerline (linea centrale).",
     _obj({"id": S, "mode": {"type": "string", "enum": ["outline", "centerline"]}, "threshold": N, "detail": N,
           "smooth": N, "min_size_mm": N, "layer": I, "keep_image": B}, ["id"])),
    ("flc_estimate_job", "estimate_job", "Prepara il lavoro e restituisce tempo stimato, ingombro, avvisi.",
     _obj({"only_selection": B})),
    ("flc_save_gcode", "save_gcode", "Salva il G-code del lavoro in un file.",
     _obj({"path": S, "only_selection": B}, ["path"])),
    ("flc_camera", "camera",
     "Telecamera del piano: list (camere trovate), open (index), snapshot (foto attuale, rectified=true per la vista raddrizzata 1:1 sul piano), status "
     "(calibrata? precisione, zona vista), calibrate (apre la calibrazione AutoCam sullo schermo; method target = "
     "bersaglio inciso su cartone, spot = puntino laser, auto).",
     _obj({"action": {"type": "string", "enum": ["snapshot", "status", "calibrate", "list", "open"]}, "index": I,
           "rectified": B, "width": I,
           "method": {"type": "string", "enum": ["auto", "spot", "target"]}})),
    ("flc_machine", "machine",
     "Macchina: setting (x = numero impostazione, y = valore: solo $27, $24, $25, $1), console (ultime righe "
     "scambiate con la scheda, per capire allarmi ed errori), connect, disconnect, home, unlock, goto (x, y in mm sul piano), frame (laser=true per il contorno con "
     "il puntino), pause, resume, stop, air_on, air_off, start_job. start_job NON avvia: apre la conferma sullo "
     "schermo, che l'utente deve accettare.",
     _obj({"action": S, "x": N, "y": N, "laser": B}, ["action"])),
]
BY_NAME = {t[0]: t for t in TOOLS}


def log(msg):
    """Diario in %APPDATA%\\FreeLaserCut\\mcp.log: serve a capire se Claude ha avviato il server e cosa ha chiesto."""
    try:
        path = os.path.join(config_dir(), "mcp.log")
        if os.path.exists(path) and os.path.getsize(path) > 200_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ collegamento a FreeLaserCut
def _info():
    try:
        with open(os.path.join(config_dir(), "remote.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _launch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from . import linux

    if linux.appimage_path():  # Linux, AppImage: si apre il programma dal file .AppImage (0.18.0)
        cmd, env = linux.relaunch_command()
        subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, cwd=os.path.expanduser("~"))
        return
    exe = sys.executable
    if os.name == "nt":
        pw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = pw if os.path.exists(pw) else exe
    kw = {"cwd": root}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe, "-m", "freelasercut"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kw)


def call(cmd, args, timeout=120.0, launch=True):
    info = _info()
    for attempt in range(2):
        try:
            if info is None:
                raise ConnectionRefusedError
            with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as s:
                s.settimeout(timeout)
                s.sendall((json.dumps({"token": info["token"], "cmd": cmd, "args": args}) + "\n").encode("utf-8"))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(1 << 20)
                    if not chunk:
                        break
                    buf += chunk
            return json.loads(buf.decode("utf-8"))
        except (OSError, ValueError):
            if attempt or not launch:
                break
            _launch()  # FreeLaserCut chiuso: lo apro e aspetto che sia pronto
            t0 = time.time()
            old = info
            while time.time() - t0 < 45:
                time.sleep(1.0)
                info = _info()
                if info and info != old:
                    try:
                        socket.create_connection(("127.0.0.1", int(info["port"])), timeout=2).close()
                        break
                    except OSError:
                        continue
    log(f"FreeLaserCut non risponde al comando {cmd}")
    return {"ok": False, "error": "FreeLaserCut non risponde: aprilo sul PC (collegamento FreeLaserCut sul Desktop) e riprova."}


# ------------------------------------------------------------------ MCP (JSON-RPC su stdio)
def _send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(mid, res):
    _send({"jsonrpc": "2.0", "id": mid, "result": res})


def _tool_result(reply):
    if not reply.get("ok"):
        return {"content": [{"type": "text", "text": "Errore: " + str(reply.get("error"))}], "isError": True}
    res = reply.get("result")
    if isinstance(res, dict) and "png_base64" in res:
        meta = {k: v for k, v in res.items() if k != "png_base64"}
        return {"content": [{"type": "image", "data": res["png_base64"], "mimeType": "image/png"},
                            {"type": "text", "text": json.dumps(meta, ensure_ascii=False)}]}
    return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}
    if method == "tools/call":
        log(f"strumento {params.get('name')} {json.dumps(params.get('arguments') or {}, ensure_ascii=False)[:300]}")
    elif method in ("initialize", "tools/list"):
        log(f"{method} da {(params.get('clientInfo') or {}).get('name', '')}")
    if method == "initialize":
        return _result(mid, {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": {"name": "freelasercut", "version": __version__},
                             "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(mid, {})
    if method == "tools/list":
        return _result(mid, {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, _, d, sch in TOOLS]})
    if method == "tools/call":
        name = params.get("name")
        if name not in BY_NAME:
            return _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"tool sconosciuto: {name}"}})
        return _result(mid, _tool_result(call(BY_NAME[name][1], params.get("arguments") or {})))
    if method in ("resources/list", "prompts/list"):
        return _result(mid, {method.split("/")[0]: []})
    if mid is not None and not method.startswith("notifications/"):
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"metodo non supportato: {method}"}})


def main():
    log(f"avviato (FreeLaserCut {__version__}, Python {sys.version.split()[0]}, {sys.executable})")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON non valido"}})
            continue
        try:
            if isinstance(msg, list):
                for m in msg:
                    handle(m)
            else:
                handle(msg)
        except Exception as ex:  # noqa: BLE001
            log(f"errore: {type(ex).__name__}: {ex}")
            if isinstance(msg, dict) and msg.get("id") is not None:
                _send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(ex)}})


if __name__ == "__main__":
    main()
