# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7, sperimentale: collegamento diretto con la xTool M2 (`core/xtool_m2_link.py`), finestra di configurazione e
collegamento (`ui/dialogs_m2link.py`) e G-code «del piano» da adattare al laser (`core/plane_gcode.py`).

Il collegamento si prova contro una M2 finta (`tests/m2_finta.py`) che risponde come la macchina vista con la M2
virtuale: buste BA BE con CRC, abbinamento col pulsante (406), gettone, finestre del file (anche senza CRC),
notifiche a lista o a oggetto, file rovinato, macchina occupata, testa diversa, collegamento chiuso dalla macchina.
Uso: python tests/test_v207_xtool_m2_link.py [classica|banco]
"""
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from m2_finta import M2Finta  # noqa: E402

from freelasercut.core import plane_gcode, xtool_m2  # noqa: E402
from freelasercut.core import xtool_m2_link as L  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


def link_for(fake, **kw):
    ev = []
    lk = L.M2Link("127.0.0.1", port=fake.port, on_event=lambda n, d: ev.append((n, d)), **kw)
    return lk, ev


def wait(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return cond()


print("--- buste e pezzi del protocollo")
env = L.envelope(b'{"a":1}', L.T_JSON)
check("busta: firma BA BE, lunghezza, CRC del contenuto e della testa", env[:2] == b"\xba\xbe"
      and int.from_bytes(env[2:5], "big") == 7 and int.from_bytes(env[8:10], "big") == L.crc16(env[:8])
      and int.from_bytes(env[6:8], "big") == L.crc16(b'{"a":1}'))
check("CRC-16/ARC: valore di riferimento di «123456789» = 0xBB3D", L.crc16(b"123456789") == 0xBB3D)
up = L.Unpacker()
two = env + L.envelope(b"\x02", L.T_FILE, with_crc=False)
got = up.feed(b"\x00\x13garbage" + two[:5]) + up.feed(two[5:17]) + up.feed(two[17:])
check("buste spezzate, unite e con byte rovinati davanti: ricomposte tutte e due", got == [(4, b'{"a":1}'), (33, b"\x02")])
bad = bytearray(L.envelope(b'{"b":2}', L.T_JSON))
bad[-1] ^= 0xFF
check("contenuto rovinato (CRC sbagliato): scartato", L.Unpacker().feed(bytes(bad)) == [])
check("richiesta di finestra del file: canale, scostamento a 5 byte, misura a 3 byte",
      L.parse_file_request(bytes([1, 50]) + (5 * 2 ** 20).to_bytes(5, "big") + (123456).to_bytes(3, "big"))
      == (50, 5 * 2 ** 20, 123456) and L.parse_file_request(b"\x81\x01") is None)
check("pacchetto dati del file: 129, canale, scostamento, dati", L.file_data(7, 1048576, b"xy")
      == bytes([129, 7]) + (1048576).to_bytes(5, "big") + b"xy")
check("notifiche: lista di eventi con «name» e oggetto semplice",
      L.events_of({"url": "/u", "data": [{"name": "/a", "mode": "Idle"}, {"name": "/b"}]}) == [("/a", {"name": "/a", "mode": "Idle"}), ("/b", {"name": "/b"})]
      and L.events_of({"url": "/u", "data": {"mode": "X"}}) == [("/u", {"mode": "X"})])
check("modo e azione dalle notifiche", L.mode_of({"curMode": {"mode": "P_IDLE"}}) == "P_IDLE"
      and L.mode_of({"mode": "WorkReady"}) == "WorkReady" and L.action_of({"content": {"action": "START"}}) == "start")
check("versione della M2: NN.141.NNN", L.is_m2_version("V40.141.012.01.ht05") and L.is_m2_version("40.141.099")
      and not L.is_m2_version("40.130.021") and not L.is_m2_version(""))
check("testa: modulo e costruttore automatici", L.check_head({"type": "LASER_BLUE_20W", "manufacture": "COS"}) == (20, "COS"))
for info, want, why in (({"type": "LASER_BLUE_10W"}, 40, "modulo diverso"), ({"type": "LASER_RED_3W"}, None, "infrarosso"),
                        ({"type": "INKJET_PRINTER"}, None, "inchiostro"),
                        ({"type": "LASER_BLUE_10W", "direction": "horizontal"}, None, "testa orizzontale")):
    try:
        L.check_head(info, want)
        ok = False
    except L.M2Error:
        ok = True
    check(f"testa: {why} = il lavoro non parte", ok)
try:
    L.check_head({"type": "LASER_BLUE_10W", "manufacture": "TO"}, None, "COS")
    ok = False
except L.M2Error:
    ok = True
check("costruttore scelto diverso da quello della macchina: il lavoro non parte", ok)

print("--- collegamento senza abbinamento")
f = M2Finta().start()
lk, ev = link_for(f)
info = lk.connect()
check("collegata: informazioni della macchina e della testa", info["head"]["type"] == "LASER_BLUE_10W"
      and L.firmware_of(info["machine"]) == "V40.141.099" and lk.connected)
first = f.requests[0]
check("prima richiesta: /v1/user/parity da ospite (mk-guest, chiave fissa, fuso orario), senza dati di account",
      first[0] == "/v1/user/parity" and first[3]["userID"] == "mk-guest" and first[3]["userKey"] == L.USER_KEY
      and set(first[3]) == {"userID", "userKey", "timezone", "token"} and not first[4])
check("dopo l'abbinamento ogni richiesta porta il sessionToken", all(r[4] for r in f.requests[1:]))
check("nessun evento di abbinamento (la macchina non l'ha chiesto)", not [e for e in ev if e[0] in ("pairing", "paired")])
time.sleep(3.5)
check("canale dei file aperto con lo stesso id del canale delle istruzioni", len(f.files_ws) == 1
      and list(f.files_ws)[0] == lk.session)
data = os.urandom(6 * 1024 * 1024 + 12345)  # più di una finestra (5 MB) e pacchetti da 1 MB
task = lk.send_job(data, 10, 3.0)
check("lavoro grande: arrivato identico in più finestre, MD5 giusto", len(f.files) == 1 and f.files[0][1] == data
      and f.files[0][2] and f.files[0][0] == "gcode.txt")
check("parametri del lavoro come quelli di xTool Studio", f.params == {
    "taskID": task, "filetype": "TXT", "filename": "gcode.txt", "mode": "MOTOR", "type": "PROCESS",
    "workhead": "BLUE_10W", "processMode": "PLANE", "thickness": 3.0, "smokeFanSpeed": 3}, f.params)
urls = [r[0] for r in f.requests]
i_up, i_par = urls.index("/v1/filetransfer/upload"), urls.index("/v1/project/process/parameter")
check("prima dell'invio: testa, stato, coperchio e testa a zero; poi file, poi parametri",
      all(urls.index(u) < i_up for u in ("/v1/project/laser-head/info", "/v1/project/running/status",
                                         "/v1/project/peripheral/lid", "/v1/project/control/absolute-move"))
      and i_up < i_par)
check("upload: tipo 1, MD5, pacchetti da 1 MB", [r for r in f.requests if r[0] == "/v1/filetransfer/upload"][0][3]["packetsize"] == L.PACKET)
check("la macchina aspetta il pulsante: niente avvio da FreeLaserCut", f.mode == "WorkReady"
      and not [r for r in f.requests if r[0] == "/v1/project/device/control"])
check("avanzamento dell'invio fino al 100 %", [e for e in ev if e[0] == "upload"][-1][1] == 1.0)
f.press()
check("pulsante: avvio, fine, di nuovo pronta (eventi alla finestra)", wait(lambda: ("state", "Idle") in ev[-3:]
      and ("process", "finish") in ev and ("process", "start") in ev))
lk.send_job(b"G1X1Y1S0F100\n", 10, 0.0)
f.press()
wait(lambda: f.mode == "WorkPlay")
lk.control("PAUSE")
check("Pausa da FreeLaserCut", wait(lambda: ("process", "pause") in ev))
lk.control("RESUME")
check("Riprendi", wait(lambda: ("process", "resume") in ev))
lk.control("CANCEL")
check("Annulla: lavoro annullato, macchina pronta", wait(lambda: ("process", "cancel") in ev and f.mode == "Idle"))
try:
    lk.control("FIRE")
    ok = False
except ValueError:
    ok = True
check("comandi diversi da START/PAUSE/RESUME/CANCEL rifiutati", ok)
f.busy = True
n = len(f.files)
try:
    lk.send_job(b"x", 10)
    ok = False
except L.M2Error as e:
    ok = "occupata" in str(e)
check("macchina occupata: errore chiaro e nessun file mandato", ok and len(f.files) == n)
f.busy = False
try:
    lk.send_job(b"x", 40)
    ok = False
except L.M2Error as e:
    ok = "40 W" in str(e)
check("modulo da 40 W chiesto, montato quello da 10: nessun file mandato", ok and len(f.files) == n)
f.drop_all()
check("la macchina chiude il collegamento: evento «closed», non più collegata",
      wait(lambda: not lk.connected and any(e[0] == "closed" for e in ev)))
try:
    lk.send_job(b"x", 10)
    ok = False
except L.M2Error:
    ok = True
check("dopo la chiusura l'invio dice che la M2 non è collegata", ok)
lk.close()
f.stop()

print("--- abbinamento con il pulsante")
f = M2Finta(pairing=True, crc_on_request=False, list_events=False).start()
lk, ev = link_for(f, pair_timeout=8)
threading.Timer(1.5, f.press).start()
lk.connect()
check("406: evento «premi il pulsante», poi gettone nuovo dato alla finestra",
      [e[0] for e in ev][:2] == ["pairing", "paired"] and lk.token == f.token and ev[1][1] == f.token)
check("in attesa del pulsante si chiede /v1/user/auth-status", "/v1/user/auth-status" in [r[0] for r in f.requests])
data = os.urandom(300000)
lk.send_job(data, 10, 1.5)
check("finestre del file senza CRC e notifiche a oggetto: il lavoro arriva lo stesso", f.files[-1][1] == data
      and f.mode == "WorkReady")
lk.close()
lk2, ev2 = link_for(f, token=f.token, pair_timeout=3)
lk2.connect()
check("con il gettone salvato non si chiede più il pulsante", lk2.connected and not [e for e in ev2 if e[0] == "pairing"])
lk2.close()
lk3, ev3 = link_for(f, pair_timeout=2)
f.pressed = False
t0 = time.time()
try:
    lk3.connect()
    ok = False
except L.PairingNeeded:
    ok = True
check("pulsante non premuto: abbinamento non riuscito dopo il tempo, collegamento chiuso", ok and not lk3.connected
      and time.time() - t0 < 8)
lk3.close()
f.stop()
f = M2Finta(corrupt=True).start()
lk, ev = link_for(f)
lk.connect()
try:
    lk.send_job(b"G1X1Y1\n", 10)
    ok = False
except L.M2Error as e:
    ok = "scartato" in str(e)
check("la macchina scarta il file (MD5): errore, nessun parametro mandato", ok and f.params is None)
lk.close()
f.stop()
lk = L.M2Link("127.0.0.1", port=1)
try:
    lk.connect(timeout=2)
    ok = False
except L.M2Error as e:
    ok = "Non riesco a collegarmi" in str(e)
check("indirizzo sbagliato: errore chiaro", ok)
lk.close()

print("--- G-code del piano")
from freelasercut.profile import MachineProfile  # noqa: E402

p = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0, optical_power="20 W", max_rate_x=6000.0,
                   max_rate_y=6000.0)
src = [plane_gcode.MARK, "; potenza-W=10", "; nome=prova", "G0 X10 Y20", "G1 X50 Y20 S800 F3000",
       "G1 X50 Y60 S500 F12000", "G0 X-15 Y60", "G1 X-14 Y60 S0", "M3 S1000", "G0 X10 Y20"]
out, rep = plane_gcode.convert(src, p)
check("riconosciuto dalla riga del segno", plane_gcode.is_plane(src) and not plane_gcode.is_plane(["G0 X0"]))
check("potenza riportata ai watt: 80 % per 10 W = 40 % su 20 W", "G1 X50 Y20 S400 F3000" in out and near(rep["ratio"], 0.5))
check("oltre la velocità massima: rallentato e potenza abbassata nella stessa proporzione (12000 → 6000, 50 % → 12,5 %)",
      "G1 X50 Y60 S125 F6000" in out and rep["capped"] == 1)
check("spostamenti spenti fuori dal piano portati sul bordo", "G0 X0 Y60" in out and rep["clamped"] == 2)
check("comandi diversi da G0/G1 nel file ignorati (M3 S1000)", not [x for x in out if x.startswith("M3")])
check("sistema assoluto e potenza che segue la velocità come i lavori di FreeLaserCut",
      out[2:8] == ["G90 G21", "M5 S0", "M9", "G10 L2 P2 X0 Y0", "G55", "M4 S0"] and out[-3:] == ["G54", "M9", "; fine"])
check("ingombro e nome", rep["box"] == (10.0, 20.0, 50.0, 60.0) and rep["name"] == "prova")
pr = MachineProfile(name="R", bed_x=300.0, bed_y=200.0, optical_power="10 W")
pr.invert_y = True
out2, _r = plane_gcode.convert(src, pr)
check("assi invertiti del profilo: Y della macchina = corsa − Y del piano", "G1 X50 Y180 S800 F3000" in out2)
out3, _r = plane_gcode.convert(src, pr, no_g55=True, g54_offset=(5.0, 7.0))
check("scheda senza G55: G54 e offset tolto", "G54" in out3[:8] and "G55" not in out3 and "G1 X45 Y173 S800 F3000" in out3)
try:
    plane_gcode.convert(src[:3] + ["G0 X10 Y10", "G1 X310 Y10 S100 F600"], p)
    ok = False
except plane_gcode.OutsideBed:
    ok = True
check("tratto acceso fuori dal piano: il lavoro non si fa", ok)
try:
    plane_gcode.convert(src[:3] + ["G0 X10 Y10", "G1 X20 Y10 S0 F600"], p)
    ok = False
except ValueError:
    ok = True
check("niente da incidere: errore", ok)
pw = MachineProfile(name="W", bed_x=300.0, bed_y=200.0, optical_power="")
out4, rep4 = plane_gcode.convert(src, pw)
check("profilo senza watt: potenze come nel file", "G1 X50 Y20 S800 F3000" in out4 and rep4["ratio"] == 1.0)
pk = MachineProfile(name="K", bed_x=300.0, bed_y=200.0, optical_power="5 W")
out5, rep5 = plane_gcode.convert(src, pk)
check("laser più debole: oltre il 100 % si ferma al 100 % e lo dice", "G1 X50 Y20 S1000 F3000" in out5 and rep5["s_limited"] == 1)
out6, _r = plane_gcode.convert([plane_gcode.MARK, "G0 X1 Y1", "G1 X2 Y1 S500"], pw)
check("G1 senza velocità: 1000 mm/min (GRBL non parte senza F)", "G1 X2 Y1 S500 F1000" in out6)

print("--- nel programma")
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
from PySide6.QtWidgets import QMessageBox  # noqa: E402

said = []
QMessageBox.warning = staticmethod(lambda *a, **k: said.append(a[2]) or QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: said.append(a[2]) or QMessageBox.Ok)
from freelasercut import admin  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui import dialogs_m2link as D  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
check("senza il codice delle funzioni in prova il comando non si vede e non si apre",
      not w.acts["m2_link"].isVisible() and w.m2_link_dialog() is None)
gpath = os.path.join(TMP, "piano.gcode")
with open(gpath, "w", encoding="utf-8") as fh:
    fh.write("\n".join(src) + "\n")
said.clear()
w.run_gcode_file(gpath)
check("G-code del piano con le funzioni bloccate: non si usa e lo dice", said and "in prova" in said[-1]
      and w.canvas.preview is None if hasattr(w.canvas, "preview") else bool(said))
admin.set_unlocked(w.qs, True)
w._apply_admin()
acts = w.m_file.actions()
check("sbloccate: il comando compare nel menu File subito dopo il lavoro per la M2, con la sua scheda d'aiuto",
      w.acts["m2_link"].isVisible() and acts.index(w.acts["m2_link"]) == acts.index(w.acts["export_m2"]) + 1
      and "m2_link" in help_texts.HELP and "sperimentale" in w.acts["m2_link"].text())
lines_conv, note = w._plane_gcode(src, "piano.gcode")
check("G-code del piano sbloccato: adattato al profilo attivo, con la nota per la conferma", lines_conv is not None
      and "G55" in lines_conv and "Longer" in note or (lines_conv is not None and w.profile.name in note))
said.clear()
out_bad, _n = w._plane_gcode(src[:3] + ["G0 X10 Y10", "G1 X900 Y10 S100 F600"], "x.gcode")
check("fuori dal piano: avviso e nessun lavoro", out_bad is None and said and "esce dal piano" in said[-1])

doc = Document()
c = doc.layer(1)
c.mode, c.power_max, c.speed, c.passes = "line", 30, 1500, 1
r = RectShape(40, 30, layer=1)
r.set_transform(QTransform.fromTranslate(20, 20))
doc.add(r)
w.editor.set_document(doc)
f = M2Finta(head="LASER_BLUE_20W", maker="COS", pairing=True).start()
dlg = D.M2LinkDialog(w, link_factory=lambda host, token, on_event: L.M2Link(host, token=token, on_event=on_event,
                                                                             port=f.port, pair_timeout=6))
check("finestra: in prova, configurazione con IP, modulo, costruttore, spessore; senza collegamento non si invia",
      "sperimentale" in dlg.windowTitle() and dlg.laser.count() == 4 and dlg.maker_box.count() == 3
      and not dlg.b_job.isEnabled() and not dlg.b_frame.isEnabled() and dlg.send() is None)
dlg.ip.setText("")
dlg.toggle_connect()
check("IP vuoto: lo chiede", "IP" in dlg.status.text() and dlg.link is None)
dlg.ip.setText("127.0.0.1")
dlg.laser.setCurrentIndex(dlg.laser.findData(0))
dlg.toggle_connect()
check("prima volta: la finestra dice di premere il pulsante", wait(lambda: "pulsante" in dlg.status.text(), 5))
f.press()
check("abbinata e collegata: modulo e costruttore presi dalla macchina (20 W, COS), gettone salvato",
      wait(lambda: dlg.watts == 20, 8) and dlg.maker == "COS" and w.qs.value("m2_token") == f.token
      and dlg.b_job.isEnabled() and "20" in dlg.status.text())
check("configurazione salvata", w.qs.value("m2_ip") == "127.0.0.1" and int(w.qs.value("m2_laser_w")) == 0)
dlg.thick.setValue(2.0)
sent = dlg.send(frame=True)
check("cornice inviata: solo potenza zero, come quella di xTool Studio (M1001 S1P1B0), testa da 20 W", sent is not None and wait(lambda: len(f.files) == 1, 8)
      and all(int(x.split("S")[1].split("F")[0]) == 0 for x in f.files[0][1].decode().splitlines()
              if x.startswith("G1") and "S" in x) and "M1001 S1P1B0" in f.files[0][1].decode()
      and '# WorkingInfo={"head":4}' in f.files[0][1].decode())
check("dopo l'invio: «premi il pulsante sulla M2», niente avvio da qui", wait(lambda: not dlg.busy, 5)
      and "pulsante" in dlg.status.text() and f.params["workhead"] == "BLUE_20W" and f.params["thickness"] == 2.0)
check("lavoro in attesa: si può annullare, non si manda un altro lavoro", dlg.b_cancel.isEnabled() and not dlg.b_job.isEnabled())
dlg.control("CANCEL")
check("annullato dalla finestra", wait(lambda: f.mode == "Idle" and dlg.b_job.isEnabled(), 5))
expect, _rep = xtool_m2.build(doc, laser_w=20, thickness=2.0, maker="COS",
                              cut_layers=D.cut_layers_default(doc))
dlg.send(frame=False)
check("lavoro inviato: lo stesso del generatore per il modulo e il costruttore della macchina (salvo la data)",
      wait(lambda: len(f.files) == 2, 8) and
      [x for x in f.files[1][1].decode().splitlines() if not x.startswith("# date")]
      == [x for x in expect if not x.startswith("# date")])
f.press()
check("pulsante sulla macchina: la finestra segue avvio e fine", wait(lambda: "finito" in dlg.status.text().lower()
                                                                     or "Pronta" in dlg.status.text(), 6))
dlg.laser.setCurrentIndex(dlg.laser.findData(40))
check("modulo non modificabile mentre è collegata", not dlg.laser.isEnabled())
dlg.toggle_connect()
check("Scollega", wait(lambda: dlg.link is None and "Non collegata" in dlg.status.text(), 3))
dlg.laser.setCurrentIndex(dlg.laser.findData(40))
dlg.toggle_connect()
check("collegata con il modulo da 40 W scelto ma 20 montato: lo dice e non lascia inviare",
      wait(lambda: "40 W" in dlg.status.text(), 8) and dlg.watts is None and not dlg.b_job.isEnabled())
dlg.toggle_connect()
wait(lambda: dlg.link is None, 3)
dlg.laser.setCurrentIndex(dlg.laser.findData(40))
dlg.maker_box.setCurrentIndex(dlg.maker_box.findData("TO"))
prof = dlg.make_profile()
check("profilo «xTool M2» dall'area del modulo scelto (40 W TO: 426 × 308) e reso attivo",
      prof is not None and (prof.bed_x, prof.bed_y) == (426.0, 308.0) and w.profile.name == "xTool M2"
      and w.qs.value("profile_path") == prof.path() and prof.optical_power == "40 W")
dlg.maker_box.setCurrentIndex(dlg.maker_box.findData("COS"))
check("40 W COS: 426 × 312", (dlg.make_profile().bed_x, w.profile.bed_y) == (426.0, 312.0))
dlg.forget()
check("Dimentica l'abbinamento: gettone cancellato", not w.qs.value("m2_token"))
dlg.close()
f.stop()
check("stato leggibile", D.state_text("WorkReady").startswith("Lavoro caricato") and D.state_text("P_IDLE") == "Pronta")

print("--- traduzioni")
import json  # noqa: E402

missing = []
keys = ["xTool M2: collega e invia (sperimentale)…", "xTool M2: collegamento diretto (sperimentale)",
        "Configurazione della M2", "Indirizzo IP", "Costruttore del modulo", "Automatico (lo dice la macchina)",
        "Invia la cornice (potenza zero)", "Invia il lavoro", "Annulla il lavoro", "Dimentica l'abbinamento",
        "Usa l'area della M2 per il piano", "Lavoro caricato: premi il pulsante sulla M2 per avviarlo",
        "G-code del piano, adattato a «{0}».", "Collega", "Scollega", "Riprendi", "Pausa"]
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for key in keys:
        if not cat.get(key):
            missing.append((lang, key))
check("le voci nuove ci sono nelle 4 lingue", not missing, missing[:6])

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
