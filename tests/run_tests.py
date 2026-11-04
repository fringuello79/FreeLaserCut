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
    while "h" not in homed and time.time() - t < 15:
        spin(0.1)
    check("homing in coordinate negative riconosciuto", homed.get("n") is True, str(c.last_status.get("MPos")))
    p = MachineProfile()
    p.negative_space = True
    mx, my = p.to_machine(300, 200)
    c.goto_machine(mx, my, 20000)
    spin(1.5)
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


def run_suite(name, label):
    import subprocess

    print(label)
    # UTF-8 esplicito: su Windows l'uscita catturata sarebbe in cp1252 e "×", "Δ", "→" farebbero cadere la suite
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    r = subprocess.run([sys.executable, path], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=900)
    for line in r.stdout.splitlines():
        if line.strip().startswith(("OK", "KO")):
            print("  " + line.strip())
            results.append((line.strip(), line.strip().startswith("OK")))
    if r.returncode != 0 and not any(l.strip().startswith("KO") for l in r.stdout.splitlines()):
        print("  KO  la suite si è interrotta:\n" + (r.stderr or "")[-1500:])
        results.append((name, False))


if __name__ == "__main__":
    print("Parser");  test_parsers()
    print("Macchina (simulatore)");  test_machine()
    print("Macchina con report di stato a metà riga (come la scheda ESP32 del B1)");  test_machine(glitch=True)
    print("Coordinate macchina negative");  test_negative_space()
    run_suite("test_gcode.py", "Generatore G-code (eseguito sul simulatore)")
    run_suite("test_controller.py", "Controller: verifica, errori, override, ripresa, fire")
    run_suite("test_editor_ui.py", "Editor: mouse e tastiera sulla tela")
    run_suite("test_v03.py", "Materiali, test materiale, vettorizzazione, testo variabile e curvo")
    run_suite("test_v04.py", "Progetti LightBurn, galleria forme, comandi da Claude (MCP)")
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
    run_suite("test_v108.py", "Progetti LightBurn: foto non più specchiate, testi al loro posto")
    run_suite("test_v110.py", "Guardia fiamme, taratura da foto del test, controllo dal telefono")
    run_suite("test_v111.py", "Fiamma con il cuore bianco, nomi sotto i comandi")
    run_suite("test_v120.py", "Laser in Wi-Fi, copie delle impostazioni della scheda, 39 modelli pronti")
    run_suite("test_v121.py", "Scheda rimasta in prova, verifica senza risposte, schede senza G55")
    run_suite("test_v122.py", "Assi invertibili, velocità in mm/s, MKS DLC32")
    run_suite("test_v123.py", "Anteprima che segue il punto di riferimento, puntino fino al 20%")
    run_suite("test_v124.py", "Porta la testa sul punto scelto del disegno")
    run_suite("test_v125.py", "Foto da LightBurn uguali in «Prepara foto», maniglie incomplete")
    run_suite("test_v130.py", "Segni del piano spiegati, modalità esperto, configurazione guidata della macchina")
    if "--camera" in sys.argv:
        print("Camera AutoCam (circa 6 minuti)");  test_camera()
    ko = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(ko)}/{len(results)} test superati" + (f" — falliti: {ko}" if ko else ""))
    sys.exit(1 if ko else 0)
