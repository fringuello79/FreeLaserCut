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


def run_suite(name, label, *args):
    import subprocess

    print(label)
    # UTF-8 esplicito: su Windows l'uscita catturata sarebbe in cp1252 e "×", "Δ", "→" farebbero cadere la suite
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONFAULTHANDLER="1")
    # preferenze pulite per ogni prova: su Windows il registro è in comune e una prova lasciava valori alla successiva
    env.setdefault("FLC_SETTINGS_INI", os.path.join(tempfile.mkdtemp(), "prova.ini"))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    r = subprocess.run([sys.executable, path, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=900)
    for line in r.stdout.splitlines():
        if line.strip().startswith(("OK", "KO")):
            print("  " + line.strip())
            results.append((line.strip(), line.strip().startswith("OK")))
    if r.returncode != 0 and not any(l.strip().startswith("KO") for l in r.stdout.splitlines()):
        print(f"  KO  la suite si è interrotta (codice {r.returncode}):\n" + (r.stderr or "")[-2500:])
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
    run_suite("test_v1811_makerhub.py", "MakerHub (in prova): collegamento diretto alla Scatola a incastri nel menu Strumenti")
    run_suite("test_v1811_makerhub.py", "MakerHub nell'interfaccia Banco", "banco")
    run_suite("test_v1811_aggancio.py", "Aggancio mentre si sposta: angoli, mezzerie, centri e nodi dell'oggetto, non il punto del mouse")
    run_suite("test_v1811_aggancio.py", "Aggancio mentre si sposta nell'interfaccia Banco", "banco")
    if "--camera" in sys.argv:
        print("Camera AutoCam (circa 6 minuti)");  test_camera()
    ko = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(ko)}/{len(results)} test superati" + (f" — falliti: {ko}" if ko else ""))
    sys.exit(1 if ko else 0)
