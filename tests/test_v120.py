# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.0: laser collegati via Wi-Fi (TCP «telnet», come FluidNC, grblHAL, ESP3D), copie automatiche
delle impostazioni della scheda ($$) con confronto e ripristino, e nuovi modelli pronti nel catalogo."""
import sys, os, time, tempfile, socket, threading
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2] if len(a) > 2 else "") or QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import netport, board_backup as bb, machines
from freelasercut.sim import SimSerial
from freelasercut.grbl import GrblController

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()


class NetBoard:
    """Una scheda GRBL «in Wi-Fi» per le prove: il simulatore dietro un server TCP (come FluidNC sulla porta 23)."""

    def __init__(self, telnet_noise=True):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.noise = telnet_noise
        self.sims = []
        self.received = bytearray()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        sim = SimSerial()
        sim.speedup = 50
        self.sims.append(sim)
        c.settimeout(0.05)
        if self.noise:
            c.sendall(b"\xff\xfb\x01\xff\xfb\x03")  # negoziazione telnet: WILL ECHO, WILL SUPPRESS-GO-AHEAD
        alive = [True]

        def out():
            while alive[0]:
                l = sim.readline()
                if l:
                    try:
                        c.sendall(l)
                    except OSError:
                        return
        threading.Thread(target=out, daemon=True).start()
        while True:
            try:
                d = c.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                break
            self.received += d
            sim.write(d)
        alive[0] = False

    def close(self):
        self.srv.close()


# ================================================================== indirizzi
check("indirizzi accettati: IP, IP:porta, nome.local, tcp://…",
      netport.parse_address("192.168.1.50") == ("192.168.1.50", 23) and
      netport.parse_address("192.168.1.50:8888") == ("192.168.1.50", 8888) and
      netport.parse_address("tcp://fluidnc.local:23/") == ("fluidnc.local", 23))
check("indirizzi non validi: rifiutati", all(netport.parse_address(x) is None for x in
                                             ("", "192.168.1.50:abc", "a b", "host:0", "host:70000", "http://x:1:2")))
check("nome della porta di rete", netport.make_port("10.0.0.7", 23) == "tcp://10.0.0.7:23" and
      netport.is_net("tcp://10.0.0.7:23") and not netport.is_net("COM3") and
      netport.label("tcp://10.0.0.7:23") == "Wi-Fi  10.0.0.7:23")

# ================================================================== collegamento TCP con il controller vero
board = NetBoard()
addr = netport.make_port("127.0.0.1", board.port)
ctl = GrblController()
check("connessione via Wi-Fi: si apre come una porta USB", ctl.connect_port(addr) and ctl.connected and ctl.port == addr)
check("la scheda risponde: stato Idle e impostazioni lette ($$), anche con la negoziazione telnet all'inizio",
      until(lambda: ctl.last_status.get("state") == "Idle" and ctl.board_settings) and 130 in ctl.board_settings,
      ctl.last_status.get("state"))
check("$I letto anche in rete", until(lambda: any(l.startswith("[VER") for l in ctl.board_info)), ctl.board_info[:1])
done = []
ctl.job_finished.connect(lambda ok, msg: done.append(ok))
ctl.stream_job(["G90 G21", "M4 S0"] + [f"G1 X{10 + i} Y{10 + i % 3} S200 F3000" for i in range(40)] + ["M5"])
check("un lavoro intero passa dal Wi-Fi e finisce", until(lambda: done, 30) and done[0] is True, done)
check("i comandi immediati arrivano come byte singoli (? per lo stato)", b"?" in board.received)

# ================================================================== copie delle impostazioni
saved = bb.list_backups()
check("alla connessione: copia automatica delle impostazioni della scheda", len(saved) == 1 and
      saved[0][1]["reason"] and saved[0][1]["count"] == len(ctl.board_settings) and saved[0][1]["ver"], saved[:1])
txt = open(saved[0][0], encoding="utf-8").read()
check("la copia è testo leggibile: «$numero=valore», da incollare anche nella console",
      txt.startswith(bb.HEADER) and "\n$130=" in txt and bb.parse(txt) == {int(k): str(v) for k, v in ctl.board_settings.items()})
before = dict(ctl.board_settings)
ctl.write_setting(130, "300.000")
check("prima di cambiare un valore: nessun doppione se la copia ha già gli stessi valori", len(bb.list_backups()) == 1)
until(lambda: False, 0.3)
ctl.request_settings()
check("il valore è cambiato sulla scheda", until(lambda: ctl.board_settings.get(130, "").startswith("300")),
      ctl.board_settings.get(130))
ch = bb.diff(ctl.board_settings, bb.parse(txt))
check("confronto con la copia: trova solo $130", [c[0] for c in ch] == [130] and ch[0][2] == before[130], ch)
for line in bb.restore_lines(ctl.board_settings, bb.parse(txt)):
    ctl.send_line(line)
ctl.request_settings()
check("ripristino: la scheda torna come nella copia",
      until(lambda: ctl.board_settings.get(130) == before[130]) and not bb.diff(ctl.board_settings, bb.parse(txt)))
ctl.disconnect_port()
check("in rete: disconnessione pulita", not ctl.connected)
p2 = bb.save({**before, 130: "999"}, [], "prova")
check("valori diversi: nuova copia; ne restano al massimo 40", p2 and len(bb.list_backups()) == 2)
for i in range(45):
    bb.save({**before, 131: str(i)}, [], "prova")
check("le copie vecchie si tolgono da sole (ultime 40)", len(bb.list_backups()) == bb.KEEP)
check("$$ incollato a mano: si legge", bb.parse("$0=10\n  $130 = 450.000 \nok\n<Idle|MPos:0,0,0>") == {0: "10", 130: "450.000"})
sim_ctl = GrblController()
n0 = len(bb.list_backups())
from freelasercut.grbl import SIM_PORT
sim_ctl.connect_port(SIM_PORT)
until(lambda: sim_ctl.board_settings)
check("con il simulatore nessuna copia automatica", len(bb.list_backups()) == n0)
sim_ctl.disconnect_port()

# ================================================================== riconoscimento della macchina in rete
r = machines.probe(addr, settle=0.3)
check("«Riconosci la macchina» funziona anche via Wi-Fi", r and r["settings"].get(130) and r["info"], r and r["info"][:1])

# ================================================================== catalogo dei modelli
names = machines.catalog_names()
check("catalogo: almeno 39 modelli pronti più il generico", len(names) >= 40, len(names))
check("ordine: B1 40W per primo, poi alfabetico, il generico per ultimo",
      names[0] == "Longer B1 40W" and names[-1] == machines.GENERIC and names[1:-1] == sorted(names[1:-1], key=str.lower))
new = [c[0] for c in machines.CATALOG if c[0] in machines.SOURCES]
check("ogni modello nuovo ha la pagina ufficiale da cui vengono i valori", len(new) >= 20 and
      all(machines.SOURCES[n].startswith("https://") for n in new), len(new))
check("nessuna fonte che non sia del produttore (niente preset di altri programmi)",
      not any("lightburn" in u.lower() or "amazon" in u.lower() for u in machines.SOURCES.values()))
p = machines.preset_profile("AlgoLaser Delta 22W")
check("profilo pronto AlgoLaser Delta 22W: 440 × 415 mm, 30000 mm/min, spot 0,16 × 0,14",
      (p.bed_x, p.bed_y, p.max_rate_x, p.spot_x_mm, p.spot_y_mm) == (440.0, 415.0, 30000.0, 0.16, 0.14))
p = machines.preset_profile("Ortur Aufero Laser 1 (AL1)")
check("profilo pronto Aufero Laser 1: 180 × 180 mm", (p.bed_x, p.bed_y, p.max_rate_x) == (180.0, 180.0, 5000.0))
check("tutti i modelli si trasformano in un profilo valido", all(
    machines.preset_profile(n).bed_x > 50 and machines.preset_profile(n).max_rate_x > 1000 for n in names))
ident = machines.identify(info=["[VER:1.1h.20240101:]", "[MSG:FW:AL_D1_133_120|MB:ALGO_LASER_V3.1]"],
                          settings={130: "440.000", 131: "415.000", 30: "1000", 32: "1"})
check("scheda ALGO_LASER con area 440 × 415: AlgoLaser Delta 22W", ident.vendor == "AlgoLaser" and
      ident.model == "AlgoLaser Delta 22W", f"{ident.vendor} / {ident.model}")
ident = machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20200101:ORTUR]"],
                          settings={130: "390.000", 131: "390.000"})
check("scheda Ortur con area 390 × 390: Aufero Laser 2", ident.model == "Ortur Aufero Laser 2 (AL2)", ident.model)
ident = machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20200101:]"],
                          settings={130: "418.000", 131: "418.000"})
check("scheda senza nome con un'area unica (418 × 418): proposto Two Trees TTS-20 Pro, da confermare",
      ident.model == "Two Trees TTS-20 Pro" and any("solo dall'area" in t for _, t in ident.notes))
ident = machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20200101:]"],
                          settings={130: "400.000", 131: "400.000"})
check("area comune (400 × 400) senza nome: nessun modello inventato, elenco dei possibili", not ident.model and
      len(ident.candidates) >= 3, ident.candidates[:4])
check("nota per i modelli che chiedono un passo in più (LC-40: firmware GRBL)",
      "GRBL" in machines.NOTES["Genmitsu Jinsoku LC-40"])

# ================================================================== finestra principale
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import dialogs_net, dialogs_backup
w = MainWindow()
check("accanto alla porta: pulsante Wi-Fi", w.btn_wifi.isVisible() or w.btn_wifi.parent() is not None)
d = dialogs_net.NetDialog(w.qs, w)
d.host.setText("127.0.0.1")
d.num.setValue(board.port)
seen = []
d.tested.connect(lambda ok, info: seen.append((ok, info)))
d.test()
check("«Prova il collegamento»: la scheda risponde", until(lambda: seen, 8) and seen[0][0], seen)
d._ok()
check("indirizzo ricordato e proposto nell'elenco delle porte", netport.saved(w.qs) == [addr] and
      (w.refresh_ports(), w.port_combo.findData(addr) >= 0)[1])
w.port_combo.setCurrentIndex(w.port_combo.findData(addr))
w.toggle_connection()
check("Connetti dalla finestra principale su un laser in Wi-Fi", until(lambda: w.ctl.connected and w.ctl.board_settings),
      w.ctl.port)
check("pulsante Wi-Fi spento mentre si è connessi", not w.btn_wifi.isEnabled())
bd = w.board_backup_dialog()
check("Laser → Copie delle impostazioni della scheda: elenco con le copie", bd.table.rowCount() >= 1 and bd.b_restore.isEnabled())
w.ctl.write_setting(131, "123.000")
until(lambda: False, 0.3)
w.ctl.request_settings()
until(lambda: w.ctl.board_settings.get(131, "").startswith("123"))
bd.fill()
# la copia più vecchia con $131 originale
target = [p for p, m in bb.list_backups() if bb.parse(open(p, encoding="utf-8").read()).get(131) == before[131]][0]
bd.fill(target)
asked.clear()
lines = bd.restore()
check("ripristino dalla finestra: chiede conferma con l'elenco dei valori e li rimanda", asked and "$131" in asked[0] and
      lines and any(l.startswith("$131=") for l in lines), lines)
check("…e la scheda li ha", until(lambda: w.ctl.board_settings.get(131) == before[131]))
d2 = dialogs_net.NetDialog(w.qs, w)
d2.list.setCurrentRow(0)
d2._forget()
check("«Dimentica l'indirizzo»", netport.saved(w.qs) == [])
w.ctl.disconnect_port()
bd.close()
board.close()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
