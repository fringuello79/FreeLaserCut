# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9: rapporti del 19/11/2026.

A  Wi-Fi con i router moderni (Mauro C., FLC-20261116-1539-DBAF, MKS DLC32 e Iliadbox): la sicurezza WPA2/WPA3 insieme
   si riconosce (nmcli «WPA2 WPA3», netsh «WPA2/WPA3», «SAE PSK») e avvisa prima di scrivere; WPA2 e WPA3 da soli
   come prima; «Il laser non trova la rete» dice anche la causa «router recente» con la prova dell'hotspot del
   telefono, mette in testa WPA2/WPA3 quando la rete scelta è così, e ha il pulsante «Usa la rete del laser» che
   spiega come collegarsi alla rete propria e poi trova il laser a 192.168.4.1 (salvato fra i collegamenti, senza
   dire che è entrato nella rete di casa);
B  porte CH341 su Linux (Gianni, FLC-20261119-1022-1D5D): /dev/ttyCH341USB* (driver del produttore) nell'elenco delle
   porte, nel riconoscimento e nel rapporto per l'assistenza, senza doppioni; porta scritta a mano: controllata
   (vuota, /dev/ che non c'è, nome Windows sbagliato), ricordata, nell'elenco, scelta, non copiata nella finestra
   della velocità come porta;
C  camera della testa e homing (marcello, FLC-20261119-1051-D533, Sculpfun S9): con l'homing attivo nel profilo ma non
   fatto, «Controlla con un puntino», «Laser qui», «Camera qui» non muovono la testa e dicono perché; dopo l'homing
   sì; le macchine senza homing ($22=0) restano come prima; la calibrazione completa propone ancora lei l'homing;
D  testi nuovi nelle 4 lingue.
Uso: python tests/test_v209_rapporti.py [classica|banco]
"""
import json
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_PROVA_RETE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import grbl, linux, machines, wifi_setup as ws  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.sim import SimSerial  # noqa: E402
from freelasercut.ui import dialogs_wifi as dw  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def plain(d_):
    return re.sub(r"<[^>]+>", "", d_.title.text() + " " + d_.body.text())


print("--- A. Wi-Fi")
check("«WPA2 WPA3» (nmcli) = insieme", ws._security("WPA2 WPA3") == "mixed")
check("«WPA2/WPA3-Personal» (netsh) = insieme", ws._security("WPA2/WPA3-Personal") == "mixed")
check("«SAE PSK» = insieme", ws._security("SAE PSK") == "mixed")
check("solo WPA3 / solo SAE = WPA3 come prima", ws._security("WPA3-Personal") == "wpa3" and ws._security("SAE") == "wpa3")
check("solo WPA2 = WPA2 come prima", ws._security("WPA2-Personal") == "wpa2" and ws._security("WPA2") == "wpa2")
N = ws.Network
codes = [c.code for c in ws.check_network("Iliadbox", "passwordgiusta", N("Iliadbox", 80, "2.4", "mixed"))]
check("rete WPA2/WPA3: avviso prima di scrivere (non blocca)", "wpa_mixed" in codes
      and not any(c.block for c in ws.check_network("Iliadbox", "passwordgiusta", N("Iliadbox", 80, "2.4", "mixed"))))
check("…l'avviso c'è nel testo, con la prova dell'hotspot",
      "hotspot" in dw.check_text(ws.Check("wpa_mixed")) and "WPA2" in dw.check_text(ws.Check("wpa_mixed")))
check("…e fra le cause se non entra", "wpa_mixed" in ws.likely_causes("Iliadbox", "x" * 8, N("Iliadbox", 80, "2.4", "mixed")))
check("rete WPA2: nessun avviso nuovo", "wpa_mixed" not in [c.code for c in ws.check_network(
    "Casa", "passwordgiusta", N("Casa", 80, "2.4", "wpa2"))])

w = mw.MainWindow()
w.resize(1300, 860)
w.show()
until(lambda: False, 0.3)


class Pc:
    """Il Wi-Fi del PC, finto (risponde come nmcli): la rete di casa è un Iliadbox con WPA2/WPA3."""

    def __init__(self):
        self.sys = ws.System(run=self.run, platform="linux")
        self.sys.local_ip = lambda: "127.0.0.9"

    def run(self, args, timeout=12, input_text=None):
        a = list(args)
        if a[:5] == ["nmcli", "-t", "-f", "TYPE,STATE", "dev"]:
            return 0, "wifi:connected\nethernet:connected\n"
        if "list" in a:
            return 0, "yes:Iliadbox:80:2437 MHz:WPA2 WPA3\nno:Vicino:30:2462 MHz:WPA2"
        return 0, ""


ctl = w.ctl
type(ctl).WAKE_AFTER_S = 3600


def usb(kind, **wifi):
    if ctl.connected:
        ctl.disconnect_port()
        until(lambda: not ctl.connected, 3)
    SimSerial.preset = None
    ctl.connect_port(SIM_PORT)
    ctl.sim.speedup = 50
    wf_ = ctl.sim.wifi_board(kind, **wifi)
    until(lambda: ctl.last_status.get("state") == "Idle" and ctl.board_info and ctl.board_settings, 20)
    app.processEvents()
    return wf_


# la scheda non vede l'Iliadbox (come quella di Mauro): nella «casa» del simulatore c'è solo un'altra rete
usb("mks", silent=True, mode="STA", ap="MKS_DLC32_SIM", nets={"Altra": "passwordgiusta"})
d = dw.WifiWizard(w, system=Pc().sys)
d.start()
until(lambda: d.state == "B", 20)
if d.state == "B":
    d.press("net")
until(lambda: d.state == "net", 10)
until(lambda: d.list.count() > 0, 20)
d.ssid.setText("Iliadbox")
d.pwd.setText("passwordgiusta")
d.press("write")
until(lambda: d.state in ("not_found", "not_tried", "failed", "ok", "unknown"), 60)
body = plain(d)
check("rete non trovata: «Il laser non trova la rete»", d.state == "not_found", d.state)
check("…con WPA2/WPA3 come prima causa e il router recente subito dopo",
      body.index("WPA2 e WPA3 insieme") < body.index("router è di quelli recenti") < body.index("5 GHz"), body[:400])
check("…e la prova con l'hotspot del telefono", "hotspot del telefono" in body)
check("…pulsante «Usa la rete del laser»", d.has("own") and d.has("retry"))
d.press("own")
body = plain(d)
check("«Usa la rete del laser»: come collegarsi (nome della rete, password predefinita), pulsante per collegarsi",
      d.state == "own_use" and ws.OWN_NET_PASSWORD in body and "MKS_DLC32" in body and d.has("own_connect"), body[:300])
real_probe = ws.probe
ws.probe = lambda host, port, timeout=1.2: {"host": host, "port": port, "ver": "1.1h"} if host == ws.OWN_NET_IP else None
d.press("own_connect")
until(lambda: d.state in ("ok", "no_port"), 15)
body = plain(d)
check("…trova il laser a 192.168.4.1 e lo salva fra i collegamenti", d.state == "ok" and d.result
      and "192.168.4.1" in d.result and d.result in __import__("freelasercut.netport", fromlist=["saved"]).saved(w.qs),
      (d.state, d.result))
check("…senza dire che è entrato nella rete di casa", "Iliadbox" not in body and "entrato nella rete" not in body, body)
ws.probe = real_probe
d.close()
d2 = dw.WifiWizard(w, system=Pc().sys)
d2.ssid_sent = "Casa"
d2.nets = [N("Casa", 80, "2.4", "wpa2")]
d2._outcome_not_found()
body = plain(d2)
check("rete WPA2 non trovata: prima le cause di sempre (5 GHz), il router recente in fondo",
      body.index("5 GHz") < body.index("router è di quelli recenti") and "WPA2 e WPA3 insieme" not in body)
d2.close()
if ctl.connected:
    ctl.disconnect_port()
    until(lambda: not ctl.connected, 3)

print("--- B. porte CH341 e porta scritta a mano")
fake = {"/dev/ttyCH341USB0": True, "/dev/ttyCH341USB1": True, "/dev/ttyUSB0": True}


def globber(pat):
    import fnmatch

    return [p for p in fake if fnmatch.fnmatch(p, pat)]


check("porte del driver WCH trovate (CH341, in ordine)", linux.vendor_ttys(globber) == ["/dev/ttyCH341USB0",
                                                                                     "/dev/ttyCH341USB1"])
rep = linux.tty_report(globber)
check("…anche nel rapporto per l'assistenza", any("ttyCH341USB0" in r for r in rep) and any("ttyUSB0" in r for r in rep))
check("…rapporto senza porte: dice che cerca anche CH341", "ttyCH341USB" in linux.tty_report(lambda p: [])[0])


class P:
    def __init__(self, dev):
        self.device, self.description, self.hwid, self.vid, self.pid, self.manufacturer = dev, "", "", None, None, ""


ports = machines.describe_ports([P("/dev/ttyS0")], extra=["/dev/ttyCH341USB0"])
ch = [p for p in ports if p.device == "/dev/ttyCH341USB0"]
check("nel riconoscimento: porta CH341, probabile laser, prima delle altre", ch and ch[0].likely and ch[0].chip == "CH341"
      and ports[0].device == "/dev/ttyCH341USB0")
ports = machines.describe_ports([P("/dev/ttyCH341USB0")], extra=["/dev/ttyCH341USB0"])
check("…senza doppioni se il sistema la elenca già", [p.device for p in ports].count("/dev/ttyCH341USB0") == 1)
real_vt = linux.vendor_ttys
linux.vendor_ttys = lambda globber=None: ["/dev/ttyCH341USB0"]
real_plat = sys.platform
# 0.21.1: le prove con le porte di Linux (/dev/…) si fanno solo dove /dev c'è; su Windows (GitHub) erano rosse
LINUX = sys.platform.startswith("linux")
if LINUX:
    check("elenco del controllo (Wi-Fi guidato) con la CH341 su Linux",
          any(p == "/dev/ttyCH341USB0" and k for p, _l, k in grbl.list_serial_ports()))
linux.vendor_ttys = real_vt
check("porta vuota rifiutata", mw.manual_port_problem("  ") is not None)
if LINUX:
    check("porta fuori da /dev rifiutata (Linux)", mw.manual_port_problem("COM8") is not None)
    check("porta in /dev che non c'è rifiutata", mw.manual_port_problem("/dev/ttyNONCE99") is not None)
    check("porta in /dev che c'è accettata", mw.manual_port_problem("/dev/null") is None)
mw.sys.platform = "win32"
check("Windows: COM8 e \\\\.\\COM12 sì, «porta» no", mw.manual_port_problem("COM8") is None
      and mw.manual_port_problem("\\\\.\\COM12") is None and mw.manual_port_problem("porta") is not None)
mw.sys.platform = real_plat
w.refresh_ports()
check("in fondo alla tendina delle porte: «Scrivi la porta a mano…»",
      w.port_combo.itemData(w.port_combo.count() - 1) == mw.MANUAL_PORT)
GOOD, BAD = ("/dev/null", "/dev/ttyNONCE99") if LINUX or sys.platform == "darwin" else ("COM250", "porta")
check("porta a mano aggiunta: nell'elenco e scelta", w.add_manual_port(GOOD) == GOOD
      and w.port_combo.currentData() == GOOD and GOOD in w.manual_ports())
w.refresh_ports()
check("…ricordata (resta dopo «Aggiorna»)", w.port_combo.findData(GOOD) >= 0)
check("porta sbagliata: non aggiunta", w.add_manual_port(BAD) is None and BAD not in w.manual_ports())
from freelasercut.ui.dialogs_serial import SerialSpeedDialog  # noqa: E402

try:
    sd = SerialSpeedDialog(w)
    vals = [sd.port.itemData(i) for i in range(sd.port.count())]
    check("finestra della velocità: «Scrivi la porta a mano…» non è una porta", mw.MANUAL_PORT not in vals
          and GOOD in vals)
    sd.close()
except TypeError as exc:
    check("finestra della velocità", False, exc)

print("--- C. camera della testa e homing")
ctl.connect_port(SIM_PORT)
until(lambda: ctl.connected and ctl.last_status.get("state") == "Idle", 10)
hc = w.camera.head
w.profile.homing = True
ctl.homed = False
why = hc._can_move(need_model=False)
check("homing attivo ma non fatto: la testa non si muove, e si dice perché", why and "homing" in why.lower(), why)
sent = []
ctl.line_sent.connect(sent.append)
hc.laser_to(100, 100)
check("«Laser qui»: nessun movimento", not any(s.startswith(("G0", "G1", "G53", "$J")) for s in sent), sent[:5])
check("«Controlla con un puntino»: non parte", hc.check_calibration(dot=True, ask=False) is None)
check("calibrazione completa: non rifiutata per l'homing (lo propone lei)",
      hc._can_move(need_model=False, need_home=False) is None or "homing" not in (hc._can_move(need_model=False, need_home=False) or "").lower())
ctl.homed = True
check("dopo l'homing: si muove", hc._can_move(need_model=False) is None, hc._can_move(need_model=False))
ctl.homed = False
w.profile.homing = False
check("macchina senza homing ($22=0): come prima, si muove", hc._can_move(need_model=False) is None)
w.profile.homing = True
ctl.disconnect_port()

print("--- E. Prepara foto con una forma (Evoluzione2, 19/11)")
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from freelasercut.core import ops  # noqa: E402
from freelasercut.core.document import Document, ImageShape, PathShape  # noqa: E402
from freelasercut.ui.dialogs_photo import PhotoDialog  # noqa: E402

ed = w.editor
doc = Document()
doc.images["a"] = Image.fromarray(np.full((200, 300), 40, np.uint8))
s = ImageShape("a", 60, 40, layer=2)
doc.add(s)
doc.layer(2).mode = "image"
ed.set_document(doc)
ed.select([s])


def run_dialog(mask):
    def ex(self):
        self.show()
        app.processEvents()
        self.mask.setCurrentIndex(self.mask.findData(mask))
        self._timer.stop()
        self._refresh()
        self._accept()
        return QDialog.Accepted
    orig = PhotoDialog.exec
    PhotoDialog.exec = ex
    w.photo_dialog()
    PhotoDialog.exec = orig
    until(lambda: False, 0.05)


def photo():
    return [l for x in ed.doc.shapes for l, _ in x.leaves() if isinstance(l, ImageShape)][0]


n_undo = len(ed.undo_stack)
run_dialog("heart")
top = ed.doc.shapes
g = top[0] if len(top) == 1 else None
check("cuore da Prepara foto: foto ritagliata come dalla pagina principale (gruppo del ritaglio, sagoma)",
      g is not None and ops.is_clip_group(g) and photo().clip and any(ops.is_form_outline(c) for c in g.children),
      [x.kind for x in top])
b = g.bounds() if g is not None else None
check("…l'ingombro è il cuore, non il rettangolo (per misure e nesting)",
      b is not None and b.width() < 60.0 - 5 and photo().bounds().width() < 60.0 - 5, b)
check("…un solo Annulla", len(ed.undo_stack) == n_undo + 1)
ed.select([g])
check("…tasto destro: «Contorno da tagliare»", "photo_cut_outline" in w.context_menu_keys())
cut = ed.cut_outline(0.0)
check("…e il contorno da tagliare segue il cuore", cut and abs(cut[0].bounds().height() - b.height()) < 0.2,
      cut[0].bounds() if cut else None)
ed.undo()
ed.select(ed.doc.shapes[:1])
from freelasercut.core import photo_clip  # noqa: E402

h_heart = photo_clip.coverage(photo().clip, photo().w, photo().h)
run_dialog("star")
g = ed.doc.shapes[0]
check("riaperta con la stella: la sagoma diventa la stella", ops.is_clip_group(g) and photo().clip
      and abs(photo_clip.coverage(photo().clip, photo().w, photo().h) - h_heart) > 0.03,
      (photo_clip.coverage(photo().clip, photo().w, photo().h), h_heart))
ed.select([g])
run_dialog("none")
check("riaperta con «nessuna»: il ritaglio si toglie, la foto torna sola e intera",
      len(ed.doc.shapes) == 1 and isinstance(ed.doc.shapes[0], ImageShape) and not ed.doc.shapes[0].clip
      and abs(ed.doc.shapes[0].bounds().height() - 40.0) < 0.01)
ed.undo()
ed.undo()
ed.undo()
check("Annulla tre volte: di nuovo la foto di partenza", len(ed.doc.shapes) == 1 and not photo().clip)
# sagoma disegnata dalla persona (pagina principale): Prepara foto con una forma non la tocca
from PySide6.QtGui import QPainterPath  # noqa: E402

pp = QPainterPath()
pp.addEllipse(photo().bounds().center(), 15, 15)
user = PathShape(pp, layer=1)
ed.add(user)
ed.select([photo(), user])
ed.clip_photo()
g = ed.doc.shapes[0]
before = photo().bounds()
ed.select([g])
run_dialog("heart")
check("foto già ritagliata con una forma disegnata: la sagoma resta quella (la forma tocca solo i pixel)",
      ops.is_clip_group(ed.doc.shapes[0]) and abs(photo().bounds().width() - before.width()) < 0.05
      and not any(ops.is_form_outline(c) for c in ed.doc.shapes[0].children))
check("ruolo nuovo della sagoma letto anche da «Togli il ritaglio» (livello di prima)",
      ops.outline_layer(type("L", (), {"role": "clip:4:form"})()) == 4
      and ops.outline_layer(type("L", (), {"role": "clip:4"})()) == 4)

print("--- D. traduzioni")
cats = {}
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8") as fh:
        cats[lang] = json.load(fh)
keys = ["Usa la rete del laser", "Usa il laser dalla sua rete", "Scrivi la porta a mano…", "Porta del laser",
        "CH341 (driver del produttore)"]
miss = [(lang, k) for lang, c in cats.items() for k in keys if k not in c]
check("testi principali nelle 4 lingue", not miss, miss[:4])

w.close()
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
