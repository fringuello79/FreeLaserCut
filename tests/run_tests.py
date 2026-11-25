# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Test automatici di FreeLaserCut sul simulatore.  Uso:  python tests/run_tests.py [--camera]"""
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="flc_test_")
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.setdefault("FLC_UI", "classica")  # le suite storiche provano la finestra classica; il Banco ha test_v07

import numpy as np  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from freelasercut import gcode_preview  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController, parse_status  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
results = []


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(f"  {'OK ' if cond else 'KO '} {name} {info}")


def test_parsers():
    st = parse_status("<Run|WPos:1.000,2.000,0.000|FS:1200,500|WCO:5,5,0>", [0, 0, 0])
    check("parse_status WPos->MPos", st["MPos"][:2] == [6.0, 7.0] and st["power"] == 500)
    pv = gcode_preview.parse(["G21 G90", "M4", "G0 X10 Y10", "G1 X20 Y10 S500 F600", "G2 X20 Y10 I-5 J0", "M5"])
    check("preview ingombro", abs(pv.width - 10) < 0.01 and abs(pv.min_x - 10) < 1e-6, f"{pv.width:.2f}x{pv.height:.2f}")
    check("preview arco", abs(pv.cut_len - (10 + 2 * math.pi * 5)) < 0.2, f"{pv.cut_len:.2f} mm")
    st = parse_status("<Idle|MPos:120.000,80.000,0.000|WPos:20.000,30.000,0.000|FS:0,0|Pn:P>", [0, 0, 0])
    check("WCO ricavato da MPos-WPos (formato B1)", st["WCO"][:2] == [100.0, 50.0])
    prof = MachineProfile()
    prof.accel_x = prof.accel_y = 500
    prof.max_rate_x = prof.max_rate_y = 36000
    pv = gcode_preview.parse(["G90", "M4", "G1 X100 S500 F6000", "M5"], profile=prof)
    check("stima tempi con accelerazione", abs(pv.seconds - 1.2) < 1e-6, f"{pv.seconds:.3f} s (atteso 1.200)")
    info = ["[LGT V1.2.3]", "[VER:1.1.2023080801:]", "[OPT:VPH,63,256]", "[MSG:FW:LGT V1.2.3|MB:LS_ESP32]"]
    p = MachineProfile.from_machine({30: "1000.000", 32: "1", 130: "450.000", 131: "440.000"}, info)
    check("identità firmware B1", p.vendor_fw == "LGT V1.2.3" and p.board == "LS_ESP32" and p.rx_buffer == 256)


def test_machine(glitch=False):
    os.environ["FLC_SIM_GLITCH"] = "1" if glitch else "0"
    tag = " [report a metà riga]" if glitch else ""
    c = GrblController()
    got = {}
    c.settings_ready.connect(lambda d: got.__setitem__("settings", d))
    c.info_ready.connect(lambda d: got.__setitem__("info", d))
    c.error_raised.connect(lambda *a: got.setdefault("errors", []).append(a[0]))
    c.job_finished.connect(lambda ok, m: got.__setitem__("job", ok))
    check("connessione al simulatore" + tag, c.connect_port(SIM_PORT))
    spin(2.5)
    sets = got.get("settings", {})
    check("lettura $$" + tag, len(sets) >= 60 and all("<" not in v for v in sets.values()), f"{len(sets)} parametri")
    check("lettura $I" + tag, any("VER" in l for l in got.get("info", [])))
    check("buffer RX 256 letto da $I", c.rx_buffer == 254, str(c.rx_buffer))
    p = MachineProfile.from_machine(got["settings"], got["info"])
    check("profilo B1 dai valori letti", p.bed_x == 450 and p.s_max == 1000 and p.laser_mode and p.accel_x == 500)
    homed = {}
    c.homed_changed.connect(lambda h, n: homed.update(h=h, n=n))
    c.home()
    spin(1.2)
    check("homing riconosciuto, coordinate positive", homed.get("h") is True and homed.get("n") is False)
    c.jog(50, 30, 12000)
    spin(1.2)
    check("jog", c.last_status["MPos"][:2] == [50.0, 30.0], str(c.last_status["MPos"]))
    c.jog(-500, 0)
    spin(0.5)
    check("jog fuori area rifiutato (error:15)", 15 in got.get("errors", []))
    c.goto_machine(200, 100, 20000)
    spin(1.5)
    c.set_work_origin()
    spin(0.6)
    check("origine di lavoro (WCO)", np.allclose(c.wco, (200, 100), atol=0.01), str(c.wco))
    job = ["G90 G21", "M4 S0"] + [f"G1 X{i % 20} Y{(i // 20) % 2} S300 F12000" for i in range(300)] + ["M5"]
    c.stream_job(job)
    t = time.time()
    while "job" not in got and time.time() - t < 60:
        spin(0.1)
    check("streaming 303 righe" + tag, got.get("job") is True, f"{time.time() - t:.1f}s")
    c.disconnect_port()
    spin(0.3)


def test_negative_space():
    os.environ["FLC_SIM_GLITCH"] = "0"
    os.environ["FLC_SIM_NEGATIVE"] = "1"
    c = GrblController()
    homed = {}
    c.homed_changed.connect(lambda h, n: homed.update(h=h, n=n))
    c.connect_port(SIM_PORT)
    spin(2.5)
    c.home()
    t = time.time()
    while "h" not in homed and time.time() - t < 40:  # 0.20.7: il Mac di GitHub è più lento, 15 s non bastavano
        spin(0.1)
    check("homing in coordinate negative riconosciuto", homed.get("n") is True, str(c.last_status.get("MPos")))
    p = MachineProfile()
    p.negative_space = True
    mx, my = p.to_machine(300, 200)
    c.goto_machine(mx, my, 20000)
    t = time.time()  # 0.20.7: aspetta che arrivi (al massimo 15 s), non un tempo fisso
    while time.time() - t < 15:
        spin(0.25)
        bx, by = p.to_bed(*c.last_status["MPos"][:2])
        if abs(bx - 300) < 0.01 and abs(by - 200) < 0.01 and c.last_status.get("state", "Idle") == "Idle":
            break
    bx, by = p.to_bed(*c.last_status["MPos"][:2])
    check("vai-qui sul piano con coordinate negative", abs(bx - 300) < 0.01 and abs(by - 200) < 0.01, f"piano {bx:.1f},{by:.1f}")
    c.disconnect_port()
    spin(0.3)
    os.environ["FLC_SIM_NEGATIVE"] = "0"


def test_camera():
    from freelasercut.camera import AutoCam, SimCamera

    for occlude, negative in ((False, False), (True, False), (False, True)):
        os.environ["FLC_SIM_NEGATIVE"] = "1" if negative else "0"
        c = GrblController()
        c.connect_port(SIM_PORT)
        spin(2.0)
        c.home()
        spin(1.0 if not negative else 12.0)
        prof = MachineProfile()
        prof.negative_space = negative
        cam = SimCamera(c.sim, occlude=occlude)
        spin(0.5)
        ac = AutoCam(c, cam, prof, grid_n=5, method="auto")
        res = {}
        ac.need_user.connect(lambda m, ac=ac: ac.continue_())
        ac.finished.connect(lambda m, msg: res.update(model=m, msg=msg))
        ac.start()
        t = time.time()
        while "msg" not in res and time.time() - t < 400:
            spin(0.1)
        m = res.get("model")
        name = "AutoCam " + ("bersaglio (testa che copre il puntino)" if occlude else "puntino laser")
        name += " · coordinate negative" if negative else ""
        if m is None:
            check(name, False, res.get("msg", "timeout"))
        else:
            rng = np.random.default_rng(3)
            pts = np.column_stack([rng.uniform(5, 445, 300), rng.uniform(5, 435, 300)])
            err = np.linalg.norm(m.img_to_bed(cam.true_img(pts)) - pts, axis=1)
            check(name, err.max() < 0.6, f"errore vero max {err.max():.2f} mm, medio {err.mean():.2f} mm")
        cam.close()
        c.disconnect_port()
        spin(0.3)
    os.environ["FLC_SIM_NEGATIVE"] = "0"
    # camera montata bassa: vede solo una fascia del piano, la testa copre il puntino
    c = GrblController()
    c.connect_port(SIM_PORT)
    spin(2.0)
    c.home()
    spin(1.0)
    cam = SimCamera(c.sim, occlude=True, view=1.45)
    spin(0.5)
    ac = AutoCam(c, cam, MachineProfile(), grid_n=5, method="target")
    res = {}
    ac.need_user.connect(lambda m: ac.continue_())
    ac.finished.connect(lambda m, msg: res.update(model=m, msg=msg))
    ac.start()
    t = time.time()
    while "msg" not in res and time.time() - t < 400:
        spin(0.1)
    m = res.get("model")
    if m is None or m.valid is None:
        check("AutoCam con camera bassa (vede solo una parte del piano)", False, res.get("msg", "timeout"))
    else:
        vx, vy, vw, vh = m.valid
        rng = np.random.default_rng(4)
        pts = np.column_stack([rng.uniform(vx + 5, vx + vw - 5, 300), rng.uniform(vy + 5, vy + vh - 5, 300)])
        tp = cam.true_img(pts)
        ok = (tp[:, 0] > 5) & (tp[:, 0] < cam.W - 5) & (tp[:, 1] > 5) & (tp[:, 1] < cam.H - 5)
        err = np.linalg.norm(m.img_to_bed(tp[ok]) - pts[ok], axis=1)
        check("AutoCam con camera bassa (vede solo una parte del piano)", err.max() < 0.6 and "alzala" in res["msg"],
              f"zona {vw:.0f}×{vh:.0f} mm, errore max {err.max():.2f} mm")
    cam.close()
    c.disconnect_port()
    spin(0.3)


PARALLEL = 1  # quante suite insieme (0.18.16): 1 = una alla volta, come sempre; GitHub ne fa girare 4
_queue = []  # suite in attesa quando girano insieme: (nome, etichetta, argomenti)


# ---------------------------------------------------------------- indice delle prove per area (0.19.2)
# Le suite hanno il nome della versione in cui sono nate (test_v07, test_v1817_wifi…): comodo per la storia, ma non
# si vede quali parti del programma sono coperte. tests/INDICE.md le raggruppa per area, a partire dalle descrizioni
# scritte qui sotto nelle chiamate run_suite(); si rigenera da solo a ogni lancio di questo file.
AREAS = (
    ("Wi-Fi, rete e telefono", ("wi-fi", "wifi", " rete", "telefono")),
    ("Telecamera e guardia fiamme", ("telecamer", "camera", "autocam", "fiamm")),
    ("Nesting e piani di lavoro", ("nesting", "piani di lavoro", "più pannelli")),
    ("Materiali", ("material",)),
    ("Foto e immagini", ("foto", "immagin", "mezzetinte", "retino", "schizzo", "ritratto", "effetti")),
    ("Lavoro e G-code", ("g-code", "verifica", "flusso completo", "contorno", "anteprima", "rotativo", "scansione",
                         "aria", "override", "tagli", "preparazione del lavoro")),
    ("Macchina, connessione e profili", ("macchina", "scheda", "porta", "homing", "g55", "esp32", "modelli", "profil",
                                         "assi", "cnc", "swift", "ray5", "mecpow", "controller", "lucciola",
                                         "puntino", "testa", "area di lavoro", "risposte", "catalogo", "autofocus",
                                         "sonda")),
    ("Disegno e modifica", ("editor", "forme", "nodi", "forbici", "testo", "raggio", "distanz", "selezione", "aggancio",
                            "gerber", "codici", "qr", "puzzle", "scultura", "rilievo", "stampa e taglia", "lbrn",
                            "strumento")),
    ("Interfaccia", ("interfaccia", "banco", "menu", "lingue", "aspetto", "guida", "barra", "linguette", "scorciatoie",
                     "preferenze", "schermi", "segni del piano", "suggerimenti", "nomi sotto", "tema")),
    ("Avvio, installazione, aggiornamenti e assistenza", ("avvio", "install", "aggiorn", "rapporto", "uscita", "chius",
                                                          "processori", "makerhub", "pacchetti", "prove", "youtube",
                                                          "ricevitore")),
)


def suite_list(path=None):
    """[(file, descrizione, argomento)] letti dalle chiamate run_suite() di questo file, nell'ordine."""
    import re

    text = open(path or os.path.abspath(__file__), encoding="utf-8").read()
    pat = re.compile(r'^\s*run_suite\("([^"]+)",\s*"((?:[^"\\]|\\.)*)"(?:,\s*"([^"]*)")?\)', re.M)
    return [(m.group(1), m.group(2).replace('\\"', '"'), m.group(3) or "") for m in pat.finditer(text)]


def index_text(suites=None):
    suites = suite_list() if suites is None else suites
    groups = {name: [] for name, _k in AREAS}
    groups["Altro"] = []
    for f, label, arg in suites:
        low = (label + " " + f).lower()
        area = next((name for name, keys in AREAS if any(k in low for k in keys)), "Altro")
        groups[area].append((f, label, arg))
    out = ["# Prove automatiche di FreeLaserCut, per area", "",
           "Generato da `tests/run_tests.py` (non modificare a mano): ogni suite sta nell'area della sua descrizione.",
           f"Suite: {len(suites)}. Lancio completo: `python tests/run_tests.py`; una sola: `python tests/<file> [banco]`.", ""]
    for name, items in groups.items():
        if not items:
            continue
        out += [f"## {name} ({len(items)})", ""]
        out += [f"- `{f}`{' (Banco)' if arg == 'banco' else f' ({arg})' if arg else ''}: {label}" for f, label, arg in items]
        out.append("")
    return "\n".join(out)


def write_index():
    """Aggiorna tests/INDICE.md se è cambiato. -> True se l'ha riscritto. Non fa mai fallire le prove."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "INDICE.md")
    try:
        text = index_text()
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != text:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            return True
    except OSError:
        pass
    return False


# 0.20.0: suite lente (secondi): sui server di GitHub la camera della testa simulata supera i 900 s
SLOW = {"test_v200_camera_testa.py": 2400, "test_v202_camera_testa.py": 2400}  # 0.20.6: casi «grandangolo» e «lente»


def parallel_from(argv, env):
    """Quante suite far girare insieme: «--insieme N» oppure la variabile FLC_PROVE_INSIEME; fra 1 e 16."""
    text = env.get("FLC_PROVE_INSIEME", "1")
    if "--insieme" in argv and argv.index("--insieme") + 1 < len(argv):
        text = argv[argv.index("--insieme") + 1]
    try:
        return max(1, min(16, int(text)))
    except ValueError:
        return 1


def _run_one(name, args):
    """Una suite in un processo a parte. -> (codice d'uscita, uscita, errori)"""
    import subprocess

    # UTF-8 esplicito: su Windows l'uscita catturata sarebbe in cp1252 e "×", "Δ", "→" farebbero cadere la suite
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONFAULTHANDLER="1")
    # preferenze pulite per ogni prova: su Windows il registro è in comune e una prova lasciava valori alla successiva
    env["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    limit = SLOW.get(name, 900)  # 0.20.0: le calibrazioni simulate della camera della testa sui server di GitHub
    if sys.platform == "darwin":  # 0.20.8: il Mac di GitHub è una macchina virtuale con 3 processori e senza scheda grafica
        limit *= 2
    try:
        r = subprocess.run([sys.executable, path, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=limit)
    except subprocess.TimeoutExpired as ex:
        out = ex.stdout if isinstance(ex.stdout, str) else (ex.stdout or b"").decode("utf-8", "replace")
        return 124, out, f"tempo scaduto ({limit} s)"
    return r.returncode, r.stdout or "", r.stderr or ""


def _failed(rc, out):
    return rc != 0 or any(l.strip().startswith("KO") for l in out.splitlines())


def _report(name, label, rc, out, err):
    print(label)
    for line in out.splitlines():
        if line.strip().startswith(("OK", "KO")):
            print("  " + line.strip())
            results.append((line.strip(), line.strip().startswith("OK")))
    if rc != 0 and not any(l.strip().startswith("KO") for l in out.splitlines()):
        print(f"  KO  la suite si è interrotta (codice {rc}):\n" + (err or "")[-2500:])
        results.append((name, False))


TIMES = {}  # 0.21.2: secondi per suite («nome argomenti»), per l'elenco delle più lente in fondo
RETRIED = []  # 0.21.2: suite fallite insieme alle altre e riprovate da sole, con l'esito


def _timed(runner, name, args):
    t0 = time.time()
    try:
        return runner(name, args)
    finally:
        key = " ".join((name, *args))
        TIMES[key] = TIMES.get(key, 0.0) + time.time() - t0


def timing_summary(n=10):
    """0.21.2 (voce 2 della coda: su GitHub il giro di Windows è arrivato a 51 minuti su 60): le suite riprovate da
    sole e le n più lente, da leggere in fondo al registro quando un giro dura più del solito. -> testo"""
    lines = []
    if RETRIED:
        lines.append("Suite riprovate da sole: " + ", ".join(f"{k} ({'riuscita' if ok else 'fallita'})" for k, ok in RETRIED))
    if TIMES:
        top = sorted(TIMES.items(), key=lambda kv: -kv[1])[:n]
        lines.append(f"Le {len(top)} più lente: " + ", ".join(f"{k} {v:.0f} s" for k, v in top))
        lines.append(f"Tempo di tutte le suite sommato: {sum(TIMES.values()) / 60:.1f} min")
    return "\n".join(lines)


def run_suite(name, label, *args):
    if PARALLEL <= 1:
        _report(name, label, *_timed(_run_one, name, args))
    else:
        _queue.append((name, label, args))  # girano insieme alla fine: vedi flush()


def flush(runner=None):
    """Fa girare le suite in coda, PARALLEL alla volta, e le riporta nell'ordine di sempre.
    Una suite che fallisce mentre gira insieme ad altre viene riprovata da sola, e conta la seconda volta: così il
    carico della macchina non fa diventare rossa una prova buona, e una prova rotta resta rossa."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    runner = runner or _run_one
    todo, outs = list(_queue), {}
    del _queue[:]
    if not todo:
        return
    with ThreadPoolExecutor(PARALLEL) as ex:
        futs = {ex.submit(_timed, runner, n, a): i for i, (n, _l, a) in enumerate(todo)}
        for k, f in enumerate(as_completed(futs), 1):
            outs[futs[f]] = f.result()
            print(f"  [{k}/{len(todo)}] {todo[futs[f]][0]} {' '.join(todo[futs[f]][2])}".rstrip(), flush=True)
    for i, (name, label, args) in enumerate(todo):
        rc, out, err = outs[i]
        if _failed(rc, out):
            rc, out, err = _timed(runner, name, args)
            RETRIED.append((" ".join((name, *args)), not _failed(rc, out)))
            label += "  [fallita insieme alle altre, riprovata da sola: " + ("fallita di nuovo]" if _failed(rc, out)
                                                                             else "riuscita]")
        _report(name, label, rc, out, err)


if __name__ == "__main__":
    PARALLEL = parallel_from(sys.argv, os.environ)
    if "--indice" in sys.argv:  # solo l'indice per area, senza far girare le prove
        print("tests/INDICE.md", "aggiornato" if write_index() else "già aggiornato")
        sys.exit(0)
    write_index()
    print("Parser");  test_parsers()
    print("Macchina (simulatore)");  test_machine()
    print("Macchina con report di stato a metà riga (come la scheda ESP32 del B1)");  test_machine(glitch=True)
    print("Coordinate macchina negative");  test_negative_space()
    run_suite("test_gcode.py", "Generatore G-code (eseguito sul simulatore)")
    run_suite("test_controller.py", "Controller: verifica, errori, override, ripresa, fire")
    run_suite("test_editor_ui.py", "Editor: mouse e tastiera sulla tela")
    run_suite("test_v03.py", "Materiali, test materiale, vettorizzazione, testo variabile e curvo")
    run_suite("test_v04.py", "Progetti .lbrn2, galleria forme, comandi da Claude (MCP)")
    run_suite("test_v05.py", "Barra numerica, livelli in tabella, guida ?, riconoscimento macchina, anteprima")
    run_suite("test_v06.py", "Lingue: inglese, italiano, spagnolo, francese, portoghese")
    run_suite("test_v07.py", "Interfaccia Banco: ricerca comandi, strati, percorso, menu radiale, cabina, Officina")
    run_suite("test_v08.py", "Ottimizza lo spazio (nesting) e modelli di laser pronti")
    run_suite("test_v09.py", "QR e codici a barre, testo su tracciato, rotativo, più pannelli e linee comuni")
    run_suite("test_v091.py", "Flusso completo sul simulatore: pannello Laser stabile, fine lavoro a testa ferma, piano pulito")
    run_suite("test_v10.py", "Foto veloci, Prepara foto, foto in linee e riempimento, prova foto")
    run_suite("test_v101.py", "Avvio robusto: errori visibili, istanza unica, scelta interfaccia, installatore")
    run_suite("test_v102.py", "Anteprima che non copre la foto, zoom a punti veri in Prepara foto")
    run_suite("test_v103.py", "Suggerimenti pronti, nesting nella barra, piano più reattivo e identico")
    run_suite("test_v104.py", "Rapporto per l'assistenza, registro della comunicazione, installatore")
    run_suite("test_v104_verifica.py", "Verifica: allarme dei limiti software, Stop/reset/Disconnetti, corsa letta dalla scheda")
    run_suite("test_v104_aggiorna.py", "Aggiornamento dal programma: Release di GitHub, SHA-256, installatore /AGGIORNA")
    run_suite("test_v105.py", "Correzione della scansione avanti e indietro, prova da incidere, Acmer S1")
    run_suite("test_v106.py", "Aspetto: tema scuro, chiaro o come Windows, colore principale")
    run_suite("test_v107.py", "Telecamera: la scelta si ricorda, «Nessuna» non accende la webcam")
    run_suite("test_v108.py", "Progetti .lbrn2: foto non più specchiate, testi al loro posto")
    run_suite("test_v110.py", "Guardia fiamme, taratura da foto del test, controllo dal telefono")
    run_suite("test_v111.py", "Fiamma con il cuore bianco, nomi sotto i comandi")
    run_suite("test_v120.py", "Laser in Wi-Fi, copie delle impostazioni della scheda, 39 modelli pronti")
    run_suite("test_v121.py", "Scheda rimasta in prova, verifica senza risposte, schede senza G55")
    run_suite("test_v122.py", "Assi invertibili, velocità in mm/s, MKS DLC32")
    run_suite("test_v123.py", "Anteprima che segue il punto di riferimento, puntino fino al 20%")
    run_suite("test_v124.py", "Porta la testa sul punto scelto del disegno")
    run_suite("test_v125.py", "Foto dei progetti .lbrn2 uguali in «Prepara foto», maniglie incomplete")
    run_suite("test_v130.py", "Segni del piano spiegati, modalità esperto, configurazione guidata della macchina")
    run_suite("test_v132.py", "Foto e disegni su livelli separati, formati delle immagini")
    run_suite("test_v133.py", "Effetti per le foto (matita, china, linee, puntinismo…)")
    run_suite("test_v134.py", "Profili macchina da condividere, YouTube, 8 modelli nuovi verificati")
    run_suite("test_v135.py", "Ritratto a matita, partenza delle immagini, retino spiegato, Longer Ray5 10W e 20W")
    run_suite("test_v136.py", "Puzzle da foto, installatore che chiude il collegamento con Claude")
    run_suite("test_v140.py", "Schizzo del soggetto (sfondo tolto), Scultura 3D da modello a strati e a incastro")
    run_suite("test_v141.py", "Anteprima 3D con la scheda grafica, con l'anteprima semplice di riserva")
    run_suite("test_v142.py", "Scultura 3D: niente blocchi con i modelli scomodi, avvisi, Annulla, sistemazione veloce")
    run_suite("test_v150.py", "Piani di lavoro: più lavori in un progetto, si prepara il prossimo mentre il laser incide")
    run_suite("test_v150.py", "Piani di lavoro nell'interfaccia Banco", "banco")
    run_suite("test_v160.py", "Materiali imparati: la curva del tuo legno dalle foto dei test, toni e anteprima")
    run_suite("test_v160.py", "Materiali imparati nell'interfaccia Banco", "banco")
    run_suite("test_v161.py", "Velocità della porta seriale a mano, avviso se la scheda non risponde")
    run_suite("test_v161.py", "Velocità della porta seriale nell'interfaccia Banco", "banco")
    run_suite("test_v162.py", "Homing interrotto da un allarme non valido, messaggio dell'allarme, codice QR davanti")
    run_suite("test_v162.py", "Homing interrotto e codice QR nell'interfaccia Banco", "banco")
    run_suite("test_v163.py", "Scheda muta dopo la connessione: reset morbido automatico, una volta sola")
    run_suite("test_v170.py", "Schizzo del soggetto: tratto a matita nuovo, aiuti (riquadro, tieni, togli)")
    run_suite("test_v170.py", "Schizzo del soggetto nell'interfaccia Banco", "banco")
    run_suite("test_v172.py", "Area di lavoro non credibile, foto troppo fitte per la porta, override, Mecpow X3S")
    run_suite("test_v172.py", "Area non credibile, foto fitte e override nell'interfaccia Banco", "banco")
    run_suite("test_v173.py", "ESP32 muto dopo la connessione: riavvio dalle linee DTR/RTS; strumento Misura leggibile")
    run_suite("test_v173.py", "Riavvio dalle linee DTR/RTS e strumento Misura nell'interfaccia Banco", "banco")
    run_suite("test_v175.py", "Calibrazione della camera con i punti messi a mano sui dischi incisi")
    run_suite("test_v175.py", "Punti a mano della camera nell'interfaccia Banco", "banco")
    run_suite("test_v176.py", "Pennelli precisi dello Schizzo del soggetto, velo rosso; il simulatore non tocca il profilo")
    run_suite("test_v176.py", "Pennelli precisi e simulatore nell'interfaccia Banco", "banco")
    run_suite("test_v177.py", "Invia un rapporto all'assistenza: rapporto più completo, consenso, invio ed email")
    run_suite("test_v177.py", "Rapporto all'assistenza nell'interfaccia Banco", "banco")
    run_suite("test_v178.py", "Ricevitore dei rapporti attivo: pulsante Invia")
    run_suite("test_v1711.py", "Aggiornamento dal programma: errori visibili e nuovi tentativi")
    run_suite("test_v1711.py", "Aggiornamento dal programma nell'interfaccia Banco", "banco")
    run_suite("test_v1712.py", "Pennello veloce, zoom sull'originale e autofocus con sonda")
    run_suite("test_v1712.py", "Pennello, zoom e autofocus nell'interfaccia Banco", "banco")
    run_suite("test_v1713.py", "Raccordo su un angolo solo (rettangolo e strumento Nodi)")
    run_suite("test_v1713.py", "Raccordo su un angolo solo nell'interfaccia Banco", "banco")
    run_suite("test_v1714.py", "Acmer P3 nel catalogo e profili dei produttori (.lbdev)")
    run_suite("test_v1716.py", "Rilievo 3D su tavola (in prova), distanza esatta e forbici")
    run_suite("test_v1716.py", "Rilievo 3D, distanza esatta e forbici nell'interfaccia Banco", "banco")
    run_suite("test_v1717.py", "Forbici: pezzi agganciati in una forma sola; Unisci estremi corretto")
    run_suite("test_sculpfun_c1.py", "Sculpfun C1 3W e 6W nel catalogo")
    run_suite("test_v180.py", "Versione per Linux: AppImage, aggiornamento, porta USB, menu, avviso sul collaudo")
    run_suite("test_v180.py", "Versione per Linux nell'interfaccia Banco", "banco")
    run_suite("test_v181_camera.py", "Telecamera del Falcon A1 (USB, mai nera) e telecamere di rete")
    run_suite("test_v181_camera.py", "Telecamere del Falcon A1 nell'interfaccia Banco", "banco")
    run_suite("test_v181_sonda.py", "Autofocus: segnale della sonda al contrario ($6)")
    run_suite("test_v181_sonda.py", "Autofocus: sonda al contrario nell'interfaccia Banco", "banco")
    run_suite("test_v181_anteprima.py", "Anteprima del Riempimento per livello intero, come il G-code")
    run_suite("test_v181_anteprima.py", "Anteprima del Riempimento nell'interfaccia Banco", "banco")
    run_suite("test_v182_raggio.py", "Raggio degli angoli nella barra in alto; raggio anche per poligoni e stelle")
    run_suite("test_v182_raggio.py", "Raggio degli angoli nella barra del Banco", "banco")
    run_suite("test_v183_selezione.py", "Selezione: un clic sceglie un oggetto solo; nesting senza selezione finale")
    run_suite("test_v183_selezione.py", "Selezione e nesting nell'interfaccia Banco", "banco")
    run_suite("test_v183_gerber.py", "Circuiti stampati: importazione dei file Gerber e dei fori Excellon")
    run_suite("test_v183_gerber.py", "Circuiti stampati (Gerber) nell'interfaccia Banco", "banco")
    run_suite("test_v184_risposte.py", "Risposte perse alla fine di verifica e lavoro (Creality Falcon A1)")
    run_suite("test_v185_stampa_taglia.py", "Stampa e taglia (in prova): crocette, PDF in misure vere, allineamento al foglio")
    run_suite("test_v185_stampa_taglia.py", "Stampa e taglia nell'interfaccia Banco", "banco")
    run_suite("test_v185_aria.py", "Comando dell'air assist a scelta: M8, M7 o nessuno")
    run_suite("test_v185_aria.py", "Comando dell'air assist nell'interfaccia Banco", "banco")
    run_suite("test_v186_menu.py", "Menu del tasto destro sul piano (interfaccia classica)")
    run_suite("test_v186_menu.py", "Tasto destro nel Banco: resta il menu radiale", "banco")
    run_suite("test_v187_lucciola.py", "Lucciola: laser acceso al minimo, potenza limitata, spegnimento da solo")
    run_suite("test_v187_lucciola.py", "Lucciola nell'interfaccia Banco", "banco")
    run_suite("test_v188_chiusure.py", "Chiusura improvvisa dopo l'invio di un rapporto; traccia quando la finestra si pianta")
    run_suite("test_v188_chiusure.py", "Chiusure improvvise e blocchi nell'interfaccia Banco", "banco")
    run_suite("test_v189_uscita.py", "Finestra chiusa = programma chiuso: timer e chiusura garantita")
    run_suite("test_v1811_aggancio.py", "Aggancio mentre si sposta: angoli, mezzerie, centri e nodi dell'oggetto, non il punto del mouse")
    run_suite("test_v1811_aggancio.py", "Aggancio mentre si sposta nell'interfaccia Banco", "banco")
    run_suite("test_v1812_ray5_40w.py", "Longer Ray5 40W nel catalogo")
    run_suite("test_v1812_pacchetti.py", "Costruzione su GitHub: lo specchio dei pacchetti che non risponde non ferma più la Release")
    run_suite("test_v1814_makerhub.py", "MakerHub (in prova): i quattro strumenti nel menu e il disegno che arriva dal loro sito")
    run_suite("test_v1814_makerhub.py", "MakerHub nell'interfaccia Banco", "banco")
    run_suite("test_v1815_g55.py", "Scheda che rifiuta G55 con un altro errore e poi tace (OMTech K40)")
    run_suite("test_v1815_g55.py", "Scheda che rifiuta G55 nell'interfaccia Banco", "banco")
    run_suite("test_v1816_swift.py", "Atomstack Swift 7W e 12W nel catalogo; 460800 baud fra le velocità provate")
    run_suite("test_v1816_cnc3018.py", "CNC 3018 con il laser al posto del mandrino (Genmitsu 3018-PRO) nel catalogo")
    run_suite("test_v1816_prove.py", "Prove su GitHub: una volta sola per versione, quattro suite insieme, secondo tentativo da sole")
    run_suite("test_v1816_avvio.py", "Guardia d'avvio: gli errori prima della finestra vengono scritti e mostrati, anche senza Qt")
    run_suite("test_v1816_nesting_manuale.py", "Nesting manuale: area disegnata sul piano, laser sui punti, T1 mai inciso")
    run_suite("test_v1816_nesting_manuale.py", "Nesting manuale nell'interfaccia Banco", "banco")
    run_suite("test_v1817_nesting_manuale.py", "Nesting manuale: solo i pezzi selezionati, forme sotto ignorate, contorno che sparisce")
    run_suite("test_v1817_nesting_manuale.py", "Nesting manuale (correzioni) nell'interfaccia Banco", "banco")
    run_suite("test_v1817_wifi.py", "Collegamento Wi-Fi del laser: procedura guidata, famiglie di schede, privacy della password")
    run_suite("test_v1817_wifi.py", "Collegamento Wi-Fi del laser nell'interfaccia Banco", "banco")
    run_suite("test_v190_interfaccia.py", "Doppio clic = strumento bloccato; scritte delle linguette dei piani")
    run_suite("test_v190_interfaccia.py", "Strumento bloccato e linguette nell'interfaccia Banco", "banco")
    run_suite("test_v190_cpu.py", "Processori vecchi: istruzioni lette all'avvio e librerie compatibili")
    run_suite("test_v190_nesting_finestra.py", "Nesting manuale in una finestra sola, homing dalla spunta del laser")
    run_suite("test_v190_nesting_finestra.py", "Nesting manuale in una finestra sola nell'interfaccia Banco", "banco")
    run_suite("test_v190_mezzetinte.py", "Mezzetinte: dimensione del punto e misure collegate")
    run_suite("test_v190_telecamera.py", "Telecamera senza calibrazione e foto del piano dal telefono")
    run_suite("test_v190_telecamera.py", "Telecamera senza calibrazione e foto dal telefono nell'interfaccia Banco", "banco")
    run_suite("test_v190_wifi_registro.py", "Wi-Fi guidato: il registro viene salvato a fine procedura")
    run_suite("test_v191_wifi.py", "Wi-Fi sul vero: telecamere lontane dalla porta del laser, scheda con «$wifi»")
    run_suite("test_v191_wifi.py", "Wi-Fi sul vero nell'interfaccia Banco", "banco")
    run_suite("test_v192_wifi.py", "Wi-Fi delle Longer: interruttore «$50», messaggi e attesa della scheda vera")
    run_suite("test_v192_wifi.py", "Wi-Fi delle Longer nell'interfaccia Banco", "banco")
    run_suite("test_v192_g55.py", "Scheda che su G55 tace o risponde con un errore, in verifica e nel lavoro: lavoro fermato e rifatto senza")
    run_suite("test_v192_g55.py", "Scheda senza G55 nell'interfaccia Banco", "banco")
    run_suite("test_v192_strumenti.py", "Barra degli strumenti: pulsante Strumenti e comando unico per MakerHub")
    run_suite("test_v192_strumenti.py", "Menu Strumenti e comando unico per MakerHub nell'interfaccia Banco", "banco")
    run_suite("test_v192_acmer_p2.py", "Acmer P2 da 10, 20 e 33 W nel catalogo dei modelli: dati ufficiali, riconoscimento della scheda")
    run_suite("test_v192_analisi.py", "Scorciatoie valide, ordine dei tagli, preparazione del lavoro con Annulla, materiali per potenza, Preferenze, ricerca comandi, anteprime")
    run_suite("test_v192_analisi.py", "Banco sugli schermi piccoli, avvio fermo al suo posto, barra della selezione, ricerca e Preferenze", "banco")
    run_suite("test_v192_analisi.py", "Tema chiaro: testi leggibili sulle righe selezionate", "chiaro")
    run_suite("test_v193_piano.py", "Piano mostrato ruotato di 90°, angolo dell'homing: «casa» a fine lavoro, angolo scelto nella configurazione guidata, file in coordinate macchina")
    run_suite("test_v193_piano.py", "Piano ruotato e angolo dell'homing nell'interfaccia Banco", "banco")
    run_suite("test_v193_avvio.py", "Avvio robusto: Windows troppo vecchio detto chiaro, icona giusta sulla barra di Windows")
    run_suite("test_v193_cerca.py", "Ricerca comandi: casella «Cerca un comando» nella barra in basso della classica")
    run_suite("test_v193_cerca.py", "Ricerca comandi nell'interfaccia Banco: resta la finestrella", "banco")
    run_suite("test_v194_sculpfun_e1.py", "Sculpfun E1 nel catalogo: 12 W, Pro 21 W e modulo infrarosso, riconoscimento dall'area di lavoro")
    run_suite("test_v195_nodi.py", "Strumento Nodi: più nodi selezionati insieme, nodi di più forme, unione di due nodi (J fonde, Maiusc+J collega)")
    run_suite("test_v195_nodi.py", "Strumento Nodi con più nodi e unione nell'interfaccia Banco", "banco")
    run_suite("test_v195_movimento.py", "Scheda Movimento: Puntino e Lucciola al centro delle frecce, joystick virtuale sul simulatore")
    run_suite("test_v195_movimento.py", "Puntino, Lucciola e joystick nell'interfaccia Banco", "banco")
    run_suite("test_v195_varie.py", "Nesting manuale che sporge dai pannelli, elenco delle scorciatoie, Sculpfun E1 dalla scheda e tabella Sculpfun, Riconosci → Applica che tiene angolo e assi")
    run_suite("test_v195_varie.py", "Nesting manuale e scorciatoie nell'interfaccia Banco", "banco")
    run_suite("test_v196_tracciati.py", "Tracciati puliti: Semplifica tracciati con lo scarto misurato, disegno a mano libera, Allinea e Distribuisci sui nodi")
    run_suite("test_v196_tracciati.py", "Semplifica tracciati, mano libera e nodi nell'interfaccia Banco", "banco")
    run_suite("test_v196_varie.py", "DXF con valori vuoti, freccette nei campi della barra, vista di ogni piano, G-code CRLF")
    run_suite("test_v196_varie.py", "Freccette nei campi, vista dei piani e CRLF nell'interfaccia Banco", "banco")
    run_suite("test_v200_camera_testa.py", "Camera della testa: calibrazione col puntino inciso, laser e camera dove vuoi, origine dalla camera, tavola da due angoli, foto del piano a mosaico, telecamere cercate di nuovo")
    run_suite("test_v200_camera_testa.py", "Camera della testa nell'interfaccia Banco", "banco")
    run_suite("test_v200_selezione.py", "Selezione più visibile: linea piena con alone del colore d'accento")
    run_suite("test_v200_selezione.py", "Selezione più visibile nell'interfaccia Banco", "banco")
    run_suite("test_v200_nomi.py", "Nome del progetto dal file importato e file di provenienza delle forme")
    run_suite("test_v200_nomi.py", "Nome del progetto e file di provenienza nell'interfaccia Banco", "banco")
    run_suite("test_v201_aria.py", "Air assist delle schede MKS DLC32 (M7) e scelta dell'aria che resta rifacendo il profilo")
    run_suite("test_v201_aria.py", "Air assist delle MKS DLC32 nell'interfaccia Banco", "banco")
    run_suite("test_v202_barra.py", "Barra in basso: «File: …» leggibile, posizione e velocità vuote senza spazio, laser collegato senza allargare")
    run_suite("test_v202_barra.py", "Barra in basso leggibile nell'interfaccia Banco", "banco")
    run_suite("test_v203_soggetto.py", "Schizzo del soggetto: ricerca automatica che si spegne, il soggetto parte vuoto e resta solo quello dipinto con Tieni")
    run_suite("test_v203_soggetto.py", "Schizzo del soggetto che parte da vuoto nell'interfaccia Banco", "banco")
    run_suite("test_v203_ritaglio.py", "Foto ritagliata a forma: cuore, stella, nuvola, cerchio ed esagono in Prepara foto, ritaglio con una forma del disegno, foto ruotata in negativo che non incide fuori")
    run_suite("test_v203_ritaglio.py", "Foto ritagliata a forma nell'interfaccia Banco", "banco")
    run_suite("test_v203_testo.py", "Testo: anteprima del carattere sul testo vero scorrendo l'elenco, spaziatura delle lettere senza salti e delle righe")
    run_suite("test_v203_testo.py", "Testo: anteprima del carattere e spaziature nell'interfaccia Banco", "banco")
    run_suite("test_v203_misure.py", "Barra delle misure: caselle X, Y, L, A, R e rotazione larghe quanto serve al numero (la prima cifra non esce più tagliata)")
    run_suite("test_v203_misure.py", "Barra delle misure nell'interfaccia Banco: numeri interi senza allargare la barra", "banco")
    run_suite("test_v203_telecamere.py", "Telecamera della testa e del piano: si scelgono sempre (quella già usata passa di qua), «Calibra» sempre possibile, calibrazione nuova mai scartata senza chiedere")
    run_suite("test_v203_telecamere.py", "Scelta delle telecamere e calibrazione sempre possibile nell'interfaccia Banco", "banco")
    run_suite("test_v204_piano_veloce.py", "Editor veloce con i disegni complessi: forme e selezione disegnate una volta sola e non a ogni movimento del mouse, clic sui gruppi, tracciati letti in blocco")
    run_suite("test_v204_piano_veloce.py", "Editor veloce con i disegni complessi nell'interfaccia Banco", "banco")
    run_suite("test_v204_piano_veloce.py", "Editor veloce con i disegni complessi su uno schermo al 125%", "scala125")
    run_suite("test_v205_scatti_wifi.py", "PC lenti: misure della selezione, istantanee per Annulla e punti dell'aggancio senza fermare la finestra, scatti dei trascinamenti nel rapporto; Wi-Fi delle Makerbase: «Il laser non trova la rete»")
    run_suite("test_v205_scatti_wifi.py", "PC lenti e Wi-Fi delle Makerbase nell'interfaccia Banco", "banco")
    run_suite("test_v205_richieste.py", "Angoli del rettangolo raccordati verso l'interno, riga dei Livelli che segue il livello assegnato, anteprima dell'offset sul piano, opzioni dello strumento Forme subito; finestra della camera della testa ridimensionabile, pulsante dello sfondo del piano; Linux: libgthread nell'AppImage e libreria mancante detta all'avvio; ringraziamenti sulla schermata di avvio, in Aiuto e nel rapporto")
    run_suite("test_v205_richieste.py", "Angoli verso l'interno, Livelli, offset, Forme, camera della testa, sfondo del piano e ringraziamenti nell'interfaccia Banco", "banco")
    run_suite("test_v206_richieste.py", "Foto ritagliata con una forma: misure, maniglie, Allinea e aggancio del lavoro sulla sola parte che si vede, Contorno da tagliare; Prepara foto: forma sull'originale e riquadro del ritaglio che si sposta e si allarga; ingranaggio a evolvente con modulo, angolo di pressione, gioco, foro e alleggerimenti; precisazione dei ringraziamenti")
    run_suite("test_v206_richieste.py", "Foto ritagliata, Contorno da tagliare, Prepara foto, ingranaggio e ringraziamenti nell'interfaccia Banco", "banco")
    run_suite("test_v206_rapporti.py", "Rapporti del 18/11: punto di riferimento che resta dopo il riavvio, scritte del test materiali con potenza e velocità scelte e numeri arrotondati, invio prudente in Wi-Fi, schede che interrompono le risposte lunghe, lente molto grandangolare della camera della testa, tasto destro su una foto")
    run_suite("test_v206_rapporti.py", "Rapporti del 18/11 nell'interfaccia Banco", "banco")
    run_suite("test_v207_svg_grigi.py", "SVG con contorno e riempimento separati da soli; riempimenti in toni di grigio con la potenza dal grigio di ogni forma (nero = massima, bianco = non si incide), forme sopra che coprono quelle sotto, fori vuoti; loghi neri, colori e file di prima come prima; anteprima dei toni; salvataggio; traduzioni")
    run_suite("test_v207_svg_grigi.py", "SVG con riempimenti grigi nell'interfaccia Banco", "banco")
    run_suite("test_v207_svg_vuoti.py", "SVG con tracciati senza disegno (<path/> senza «d», come nei file di xTool Creative Space): il resto del file si importa; SVG sani byte per byte identici; attributi con «>» o apostrofi non rovinati; da file e .svgz; rettangoli e cerchi con trasformazioni speculari al posto giusto")
    run_suite("test_v207_scia.py", "Scia dell'incisione sul piano: si spegne dal menu Visualizza (ricordato), ridisegno al massimo 4 volte al secondo, nascosta con l'anteprima del lavoro guardando un altro piano senza gli altri piani")
    run_suite("test_v207_scia.py", "Scia dell'incisione nell'interfaccia Banco", "banco")
    run_suite("test_v207_piano.py", "G-code «del piano» di un programma esterno adattato al laser del profilo (watt, velocità massima, assi, G55, fuori dal piano), solo con le funzioni in prova; il collegamento diretto con la M2 non c'è")
    run_suite("test_v207_piano.py", "G-code «del piano» nell'interfaccia Banco", "banco")
    run_suite("test_v206_cook.py", "Free Laser Cook (in prova): conto dell'energia e delle passate, G-code a testa alzata con pausa per girare, righe della griglia, firma e giro dell'aroma sul legno; ricette incluse, salvate, esportate e importate; finestra dietro il codice con le accortezze da spuntare")
    run_suite("test_v206_cook.py", "Free Laser Cook nell'interfaccia Banco", "banco")
    run_suite("test_v207_barra.py", "Barra in alto personalizzabile: i comandi che usi di più dopo quelli di sempre, nell'ordine scelto, ricordati; finestra con Cerca, Aggiungi, Togli, Su, Giù, Svuota; tasto destro sulle barre")
    run_suite("test_v207_barra.py", "Barra personalizzabile: nel Banco la voce non c'è", "banco")
    run_suite("test_v208_mac.py", "Versione per macOS (anteprima): pacchetto con permessi di camera e rete locale, avvio isolato, numba solo su Apple Silicon, permesso della camera chiesto dal filo della finestra, avviso di errore all'avvio")
    run_suite("test_v209_laser.py", "Più laser configurati, ognuno con il suo nome: tendina nel pannello Laser, nome, laser nuovo da un modello o copia, tolto dall'elenco, porta ricordata per ogni laser, profilo e piano che cambiano")
    run_suite("test_v209_laser.py", "Più laser e tendina dei laser nell'interfaccia Banco", "banco")
    run_suite("test_v209_disegno.py", "Guide dai righelli (aggancio, salvate nel progetto, piano ruotato), deformazione a 4 punti (prospettiva) e a 16 punti (griglia), larghezza delle fessure degli incastri")
    run_suite("test_v209_disegno.py", "Guide, deformazione e fessure nell'interfaccia Banco", "banco")
    run_suite("test_v209_rapporti.py", "Rapporti del 19/11: Wi-Fi con WPA2/WPA3 insieme e router recenti, rete propria del laser; porte CH341 su Linux e porta scritta a mano; camera della testa ferma senza homing; Prepara foto con una forma che ritaglia la foto come dalla pagina principale")
    run_suite("test_v209_rapporti.py", "Wi-Fi dei router recenti, porte a mano e homing della camera della testa nell'interfaccia Banco", "banco")
    run_suite("test_v210_tastiera.py", "La testa con la tastiera: Alt+Maiusc+frecce, passi Alt+1…5, Z, origine, anche con oggetti selezionati e in Stampa e taglia (Ctrl+1, Ctrl+2); niente durante il lavoro; tasti tutti diversi")
    run_suite("test_v210_tastiera.py", "La testa con la tastiera nell'interfaccia Banco", "banco")
    run_suite("test_v210_disegno.py", "Linea tratteggiata, Ritaglia con la forma e al piano, rampa dei riempimenti (timbri), Z che scende a ogni passata, Separa sui tracciati con più figure e Scomponi sui gruppi")
    run_suite("test_v210_disegno.py", "Tratteggio, ritaglio, rampa, Z per passata, Separa e Scomponi nell'interfaccia Banco", "banco")
    run_suite("test_v210_ripresa.py", "Lavoro in corso salvato sul disco e ripreso dopo la riapertura del programma, Scarta, file rovinati; Parti da qui nell'anteprima")
    run_suite("test_v210_ripresa.py", "Ripresa dal disco e Parti da qui nell'interfaccia Banco", "banco")
    run_suite("test_v211_joystick.py", "Joystick pronto e fedele: pezzetti al ritmo del tempo vero, la testa gira subito anche con code da 15, 63 e 127 posti, velocità vera, bordo, rilascio, simulatore con i jog in coda come le schede vere")
    run_suite("test_v211_joystick.py", "Joystick pronto e fedele nell'interfaccia Banco", "banco")
    run_suite("test_v211_falcon.py", "Angolo dello 0 e assi che non si contraddicono più (Falcon A1 del rapporto 2E95): avviso con correzione, configurazione guidata, catalogo, prova delle frecce dall'angolo dell'homing, simulatore; freccia «Continuo» mai muta al bordo")
    run_suite("test_v211_falcon.py", "Angolo dello 0, assi e freccia «Continuo» nell'interfaccia Banco", "banco")
    run_suite("test_v211_grigio.py", "Grigio delle forme scelto nel pannello Proprietà: riga Grigio, tono e potenza, più forme insieme, gruppi, Annulla, G-code e salvataggio")
    run_suite("test_v211_grigio.py", "Grigio delle forme nell'interfaccia Banco", "banco")
    run_suite("test_v211_foto.py", "Prepara foto anche sulla foto ritagliata con una forma: menu in alto, tasto destro e pannello Proprietà")
    run_suite("test_v211_foto.py", "Prepara foto sulla foto ritagliata nell'interfaccia Banco", "banco")
    run_suite("test_v212_moduli.py", "Moduli aggiuntivi: cartella dei dati, modulo.json, versione adatta, errori che restano del modulo (importazione, registrazione, comando), niente comandi a metà né al posto di quelli del programma, traduzioni, riga nel rapporto, spenti nello Store; nessun comando né file per macchine non GRBL nel programma")
    run_suite("test_v212_moduli.py", "Moduli aggiuntivi nell'interfaccia Banco", "banco")
    run_suite("test_v212_lucciola.py", "Finestre chiuse che restavano attaccate ai segnali (rapporti 75E8 e ABFC): Lucciola dopo Stampa e taglia, copie della scheda dopo un cambio di collegamento, nessuna lambda sui segnali di controllore, scheda Laser e finestra principale")
    run_suite("test_v212_lucciola.py", "Finestre chiuse attaccate ai segnali nell'interfaccia Banco", "banco")
    run_suite("test_v212_lucciola_tasto.py", "Lucciola dalla tastiera (Alt+Maiusc+L): come il pulsante, tetto di potenza, niente raggio senza macchina, in lavoro o in allarme, Stop che la spegne davvero anche nel programma, con Stampa e taglia davanti")
    run_suite("test_v212_lucciola_tasto.py", "Lucciola dalla tastiera nell'interfaccia Banco", "banco")
    run_suite("test_v212_velocita.py", "Velocità costante a laser spento (riempimenti e immagini) e «Spostamenti a vuoto più lenti» (macchina): righe intere a velocità di lavoro senza G0, salti fra le forme e fra i livelli che restano, G-code identico alla 0.21.1 con le caselle spente, tetto alla velocità della scheda, Contorno, stima del tempo, file vecchi")
    run_suite("test_v212_velocita.py", "Velocità costante e spostamenti a vuoto nell'interfaccia Banco", "banco")
    run_suite("test_v212_joystick_fisico.py", "Joystick fisico (G13, pad, joystick USB) con un controller finto: zona morta e taratura del centro, si arma solo dal centro, programma in secondo piano e finestre aperte, guardiano e scollegamento, homing obbligatorio, tetto della «Velocità jog» e mai oltre 6000, nessun comando del laser, lavoro e allarme, un solo padrone fra schermo, tastiera e levetta, verso, pressione lunga per Homing e X0 Y0, controller ricordato, da riaccendere a ogni avvio, libreria che manca")
    run_suite("test_v212_joystick_fisico.py", "Joystick fisico nell'interfaccia Banco", "banco")
    run_suite("test_v212_continuo.py", "«Continuo» e joystick quando il piano del profilo è più grande della corsa della scheda (rapporto 3802): bordo vero con coordinate positive e negative, assi invertiti e piano ruotato, nessun error:15, rifiuto spiegato sotto le frecce con «Usa le misure della macchina», avviso al collegamento, simulatore con la corsa del profilo")
    run_suite("test_v212_continuo.py", "«Continuo» e joystick al bordo vero nell'interfaccia Banco", "banco")
    run_suite("test_v212_calibrazione.py", "Calibrazione della camera con la scheda che si riavvia da sola (rapporti E933 e 44A1): riavvii chiesti e no, homing tolto, la calibrazione si ferma con il messaggio e senza altri movimenti, inizio e fine nel registro, passaggio al cartone spiegato")
    run_suite("test_v212_primo_avvio.py", "Primo avvio (rapporto E698, Mac M1): finestra della scelta distrutta prima della finestra principale, pulizia della memoria sospesa durante la costruzione e riattivata anche se fallisce, porte del sistema del Mac in fondo e segnate")
    run_suite("test_v212_primo_avvio.py", "Primo avvio nell'interfaccia Banco", "banco")
    run_suite("test_v212_catalogo.py", "Catalogo: VEVOR A7 5W (come l'Atomstack A5 Pro) e Sculpfun iCube Ultra Dual 12W e 1.2W IR (area prudente 135 × 135, dichiarata 150 × 135, famiglia nel riconoscimento, nota sul raggio a 1064 nm, accelerazione 500, tabella dei materiali Sculpfun con interlinea 0,05), traduzioni")
    run_suite("test_v201_finestra.py", "La finestra non si allarga mai oltre lo schermo (scritta «File:» della barra in basso), in tutte le lingue")
    run_suite("test_v201_finestra.py", "Finestra che resta nello schermo nell'interfaccia Banco", "banco")
    run_suite("test_v201_nomi.py", "Il nome del progetto dato dall'importazione segue i file che restano sul piano")
    run_suite("test_v201_nomi.py", "Nome del progetto che segue i file nell'interfaccia Banco", "banco")
    run_suite("test_v201_lentezza.py", "Telecamera USB a riposo quando nessuno la guarda, rallentamenti nel registro e nel rapporto")
    run_suite("test_v201_carverall_jl9.py", "Carverall JL9 (X1 Pro) 20W nel catalogo: dati ufficiali, riconoscimento dall'area di lavoro")
    run_suite("test_v202_camera_testa.py", "Calibrazione completa della camera della testa (griglia incisa, lente, inclinazione, verifica onesta), mosaico preciso, camera del piano aiutata, vista raddrizzata e zoom, crocetta dal centro camera")
    run_suite("test_v202_camera_testa.py", "Calibrazione completa e vista della testa nell'interfaccia Banco", "banco")
    run_suite("test_v202_pausa.py", "Pausa prima di un livello: G-code con M0, invio diretto che si ferma e riprende, Annulla durante la pausa")
    run_suite("test_v202_pausa.py", "Pausa prima di un livello nell'interfaccia Banco", "banco")
    run_suite("test_v202_linee_piatte.py", "Linee orizzontali, verticali e punti dentro la selezione col rettangolo e negli ingombri")
    run_suite("test_v202_linee_piatte.py", "Linee piatte nella selezione nell'interfaccia Banco", "banco")
    run_suite("test_v220_galleria.py", "Galleria dei lavori condivisi (in prova): comandi nel menu File, modulo, progetto ripulito e che cosa parte davvero, foto senza EXIF, risposte e file ostili, voti, segnalazioni, «I miei lavori», apertura come progetto nuovo")
    run_suite("test_v220_galleria.py", "Galleria dei lavori condivisi nell'interfaccia Banco", "banco")
    run_suite("test_v220_aria.py", "Configurazione guidata della macchina, passo dell'aria: due prove a laser spento (M8 e M7), aria che si spegne sempre, casi in cui la prova non si fa, scelta salvata nel profilo")
    run_suite("test_v220_aria.py", "Configurazione guidata della macchina, passo dell'aria nell'interfaccia Banco", "banco")
    run_suite("test_v220_incastri.py", "Adatta gli incastri allo spessore: spessore trovato da solo, fessure e fori allargati al centro, tacche più profonde, linguette più lunghe, bordi a dita con le punte ferme, angoli e tetti obliqui, incastri troppo vicini lasciati come sono, andata e ritorno")
    run_suite("test_v220_incastri.py", "Adatta gli incastri allo spessore nell'interfaccia Banco", "banco")
    run_suite("test_v221_vuoti.py", "Vuoti nelle righe di foto e riempimenti: salto veloce solo se resta lungo dopo le rincorse, mai all'indietro (foto con l'effetto Matita)")
    run_suite("test_v221_vuoti.py", "Vuoti nelle righe di foto e riempimenti nell'interfaccia Banco", "banco")
    run_suite("test_v221_import.py", "DXF con i colori numerati e del layer (il taglio rosso non si perde); SVG senza unità a 72, 90 o 96 dpi (Illustrator)")
    run_suite("test_v221_import.py", "DXF e SVG importati nell'interfaccia Banco", "banco")
    run_suite("test_v222_contorno.py", "Contorno con la partenza dalla posizione della testa: finito il giro la testa torna da dove è partita e il lavoro non si sposta (9 pallini, laser spento e puntino, rettangolo e convesso)")
    run_suite("test_v222_contorno.py", "Contorno con la partenza dalla testa nell'interfaccia Banco", "banco")
    run_suite("test_v222_banco_rete.py", "Rete di sicurezza del Banco: dopo un avvio fallito si parte in Classica con la fascia, alla seconda la scelta diventa Classica; Officina sul secondo monitor spenta sul Mac; prova d'avvio di GitHub anche nel Banco")
    run_suite("test_v223_studio.py", "Studia la macchina (in prova): prove guidate su K40 (scheda M2 Nano) e Ruida con schede finte, in qualsiasi ordine; il laser non si accende mai (comandi permessi, chiavi sbagliate innocue), diario e rapporto, indirizzo nascosto, difetti rimessi apposta")
    run_suite("test_v223_studio.py", "Studia la macchina nell'interfaccia Banco", "banco")
    run_suite("test_v223_png_trasparenti.py", "Immagini con lo sfondo trasparente: sulla tela si vede solo la parte piena, il clic sul trasparente prende quello che c'è sotto, il trasparente non si incide mai (negativo, luminosità, contrasto); stesso G-code di prima senza trasparenza")
    run_suite("test_v223_png_trasparenti.py", "Immagini con lo sfondo trasparente nell'interfaccia Banco", "banco")
    run_suite("test_v224_caratteri.py", "Grandezza dei caratteri dell'interfaccia: stessi pixel sugli schermi a 72 punti per pollice (Mac), scelta in Impostazioni e nelle Preferenze (85–150%), ogni foglio di stile e ogni carattere passa dallo stesso punto")
    run_suite("test_v224_caratteri.py", "Grandezza dei caratteri nell'interfaccia Banco", "banco")
    run_suite("test_v224_atomstack.py", "Atomstack X30 Pro / S30 Pro / A30 Pro: modelli nel catalogo e scheda riconosciuta dalla versione del firmware (la marca non la scrive), con X20 Pro e X40 Pro fra i candidati")
    run_suite("test_v225_k40_libusb.py", "Studia la macchina, K40 con il driver libusb-win32: motivo scritto quando non c'è collegamento, pyusb nell'installatore, prove K1–K3 attraverso pyusb (finto) fino alla scheda finta")
    run_suite("test_v225_k40_libusb.py", "Studia la macchina, K40 con il driver libusb-win32, nell'interfaccia Banco", "banco")
    run_suite("test_v225_k40_giro.py", "Studia la macchina, K40: ritorno a casa senza i 25 s di attesa e con «pronta» confrontato da vicino e da lontano, prova K4 «un solo lavoro» che conta i giri a fine corsa, pulsante «Fai tutte le prove» con i risultati spiegati")
    run_suite("test_v225_k40_giro.py", "Studia la macchina, K40, prove guidate nell'interfaccia Banco", "banco")
    run_suite("test_v225_test_forma.py", "Test materiale con la forma selezionata o con il pezzo di una foto (la zona con più grigi trovata da sola), richiesta di Stefano Modena")
    run_suite("test_v225_test_forma.py", "Test materiale con la forma o la foto nell'interfaccia Banco", "banco")
    run_suite("test_v225_telefono.py", "Telefono: frecce e joystick per muovere la testa (solo se permesso sul PC, a macchina ferma, laser spento, arresto da solo se il telefono tace), pagina con comandi in rilievo")
    run_suite("test_v225_telefono.py", "Telefono: frecce e joystick nell'interfaccia Banco", "banco")
    run_suite("test_v225_qt69.py", "Pacchetto per i Mac Intel con macOS 13 Ventura (pull request #29): menu tenuti vivi e guida senza filtro sempre acceso con PySide6 6.9, linea centrale giusta anche senza numba")
    run_suite("test_v226_k40_driver.py", "Driver K40 (M2 Nano), primo pezzo: codici di velocità con e senza la rincorsa, rette a passi, dal G-code ai comandi della scheda, letti da un lettore indipendente")
    run_suite("test_v226_ruida_estesa.py", "Studia la macchina, Ruida: la lettura estesa legge anche le impostazioni note fuori dalle zone (numero dell'impostazione e byte sul cavo), solo letture, in rete e su USB")
    run_suite("test_v226_veste_grafica.py", "Nuova veste grafica: icona con una misura per ogni uso e angoli trasparenti, logo nuovo in finestra, sito e installatori, schermata di avvio blu e arancio con il motto nella lingua del programma, almeno 4 secondi, nomi che scorrono a righe alternate")
    run_suite("test_v226_veste_grafica.py", "Nuova veste grafica nell'interfaccia Banco", "banco")
    run_suite("test_v226_verifica_grblhal.py", "Verifica del G-code con le schede GrblHAL che si riavviano uscendo dalla prova (Ortur): il lavoro parte quando la scheda è ripartita, senza $C in più, senza righe perse, con l'homing tenuto")
    run_suite("test_v226_verifica_grblhal.py", "Verifica del G-code con GrblHAL nell'interfaccia Banco", "banco")
    run_suite("test_v226_rapporti.py", "Dai rapporti del 24/11: anteprima dei lavori grandi con i trasferimenti a scelta, «Spezza» sulle forme chiuse, comandi dei nodi col tasto destro")
    run_suite("test_v226_rapporti.py", "Dai rapporti del 24/11 nell'interfaccia Banco", "banco")
    run_suite("test_v226_rotativo_z.py", "Rotativo sul motore della Z (interruttore della macchina): Y che diventa Z, prova del giro con il passo piccolo, conferme, passi della Z controllati, homing, contorno in X e Z, autofocus e frecce della Z spenti; simulatore con le impostazioni del rotativo di Giuseppe")
    run_suite("test_v226_rotativo_z.py", "Rotativo sul motore della Z nell'interfaccia Banco", "banco")
    run_suite("test_v226_k40_ponte.py", "K40 (M2 Nano) collegabile, funzione in prova: il ponte che parla GRBL alla scheda, con la scheda finta che segna ogni pericolo (laser acceso senza dati, D fuori dal lavoro, fuori dal piano): casa, frecce a pezzetti, lavori, pausa, stop, cavo staccato, verifica, verso degli assi")
    run_suite("test_v226_k40_ponte.py", "K40 (M2 Nano) collegabile nell'interfaccia Banco", "banco")
    run_suite("test_v227_k40.py", "K40 collegata dopo la prima prova sulla macchina vera: lavori con «I» e senza «C», il quadrato di Evo sulla scheda finta, frecce e contorno con uno spostamento veloce, «Continuo» a pezzi, joystick con la coda corta, attese stimate, diario dei byte")
    run_suite("test_v227_k40.py", "K40 collegata dopo la prima prova, nell'interfaccia Banco", "banco")
    run_suite("test_v229_k40.py", "K40 collegata: contorno a laser spento come un lavoro solo (niente soste agli angoli), campi della potenza spenti con la potenza sulla manopola, ogni livello inciso accende il laser")
    run_suite("test_v229_k40.py", "K40 collegata: contorno e campi della potenza, nell'interfaccia Banco", "banco")
    run_suite("test_v229_finestra.py", "Apri un'altra finestra: comando e menu, processo a parte con la sua sigla, salvataggio automatico per finestra, finestre chiuse male riconosciute e riaperte, una finestra vera avviata e uccisa")
    run_suite("test_v229_finestra.py", "Apri un'altra finestra nell'interfaccia Banco", "banco")
    run_suite("test_v229_hurricane.py", "Atomstack Hurricane (CO2 da 55 W) nel catalogo: area, velocità, porta seriale a 460800, fonte e nota tradotta, riconoscimento")
    run_suite("test_v229_avvio.py", "Schermata d'avvio fluida: le librerie pesanti si caricano a parte mentre la schermata si ridisegna di continuo")
    run_suite("test_v2210_strati_banco.py", "Banco: la scheda di uno strato non si allarga togliendo «Incidi» (Rino): «non inciso» sulla riga del nome, righe accorciate con «…»")
    run_suite("test_v230_homing.py", "Configurazione guidata: l'angolo dello 0 scelto non si perde (rapporto BCAB, Falcon A1): la freccia vale con «Sì» o «No», allarme o riavvio a metà spostamento non valgono, contrasto fra angolo e frecce: si chiede")
    run_suite("test_v230_homing.py", "Configurazione guidata: l'angolo dello 0 scelto non si perde, interfaccia Banco", "banco")
    run_suite("test_v230_aria.py", "Macchina, pulsante Aria: con un lavoro in corso o in pausa si spegne e si accende subito (comando immediato di GRBL), il pulsante segue l'aria della scheda (rapporto 8595)")
    run_suite("test_v230_aria.py", "Macchina, pulsante Aria subito anche nel Banco", "banco")
    run_suite("test_v230_distanze_fisse.py", "Disegno, distanze fisse (in prova): chi segue tiene la distanza dal riferimento spostato, ridimensionato, ruotato o cambiato nei nodi; catene; giri e due legami sullo stesso asse rifiutati; un passo di Annulla; copie senza legami; file, piano ruotato e gruppi")
    run_suite("test_v230_distanze_fisse_ui.py", "Disegno, distanze fisse nell'interfaccia: Distanza esatta con «Mantieni», Misura → «Fissa questa distanza», quote sul piano, doppio clic e tasto destro, comandi solo con il codice")
    run_suite("test_v230_distanze_fisse_ui.py", "Disegno, distanze fisse nell'interfaccia Banco", "banco")
    run_suite("test_v231_punto.py", "Lavoro e G-code, punto di partenza (9 pallini): con la partenza dal disegno un clic sposta solo il rombo e non rifà l'anteprima del lavoro (con una foto ci voleva qualche secondo); con la partenza dalla testa o dall'origine, con il rotativo e cambiando partenza si rifà")
    run_suite("test_v231_punto.py", "Lavoro e G-code, punto di partenza nell'interfaccia Banco", "banco")
    run_suite("test_v232_k40_raster.py", "Macchina K40 (scheda M2 Nano): foto e riempimenti nel modo raster della scheda, niente colpi a fine riga; stessi punti bruciati del lavoro normale (foto, riempimenti, casi apposta, 300 G-code a caso), uscita dal modo raster quando serve, ponte con stop, passo fra le righe")
    run_suite("test_v232_verifica_console.py", "Lavoro e G-code, verifica ($C): le righe e i loro «ok» non vanno uno per uno nella console (la finestra restava ferma con le foto grandi)")
    if "--camera" in sys.argv:
        print("Camera AutoCam (circa 6 minuti)");  test_camera()
    flush()
    print("\n" + timing_summary())
    ko = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(ko)}/{len(results)} test superati" + (f" — falliti: {ko}" if ko else ""))
    sys.exit(1 if ko else 0)
