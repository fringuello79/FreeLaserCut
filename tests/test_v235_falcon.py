# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5: due rapporti di Creality Falcon del 26/11/2026.

1. FLC-20261126-1305-4A62 (Roberto C., Falcon A1 10W, 0.23.2): «devo invertire i comandi di movimento dell'asse X».
   Dal registro: dopo l'homing la testa è a MPos 0,0 (angolo dell'homing, a sinistra). Il Falcon si riavvia da solo
   (coperchio, a volte durante uno spostamento: ~15 volte in 8 minuti) e ogni riavvio azzerava «homing fatto»: la
   protezione della 0.21.1 (la freccia verso il finecorsa non si manda) si spegneva, la freccia ← partiva da X=0,
   la scheda andava in allarme 3 e si riavviava, e la testa non andava a sinistra: «X è al contrario». Ora
   - la scheda ricorda che l'homing è stato fatto da quando la porta è aperta (homed_once), anche dopo allarmi e riavvii;
   - la prova delle frecce blocca la freccia verso il finecorsa anche dopo un riavvio;
   - un allarme dopo una freccia partita dallo 0 verso il bordo si spiega come finecorsa, non come asse sbagliato.
2. FLC-20261126-2240-9917 (Luca, Falcon A1 Pro, 0.23.2): «non trova il laser in rete». In Wi-Fi il Falcon A1 Pro
   (e A1C, T1) non apre una porta GRBL: usa i WebSocket del programma di Creality (staff di LightBurn, forum,
   12/01/2026). Ora la scheda «A1 Pro Laser Master» si riconosce, e il Wi-Fi guidato lo dice subito.
Uso: python tests/test_v235_falcon.py [banco]
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import machines, wifi_setup  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import dialogs_setup  # noqa: E402
from freelasercut.ui.dialogs_setup import SetupWizard  # noqa: E402
from freelasercut.ui.dialogs_wifi import WifiWizard as WifiDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + f"[{UI}] " + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


# ====================================================================== A. riconoscimento del Falcon A1 Pro (9917)
print("--- A. Falcon A1 Pro dalla scheda")
INFO_A1PRO = ["[VER:1.1f.20231005:]", "[Firmware:Version v1.0.4]", "[OPT:VNMCZHL,512,65536,4,0]", "[AXS:4:XYZA]",
              "[NEWOPT:ENUMS,RT+,HOME,NOPROBE,REBOOT,SED,TMC=15]", "[FIRMWARE:grblHAL]", "[DRIVER:Allwinner]",
              "[BOARD:A1 Pro Laser Master]", "[KINEMATICS:CoreXY v2.02]"]
SET_A1PRO = {0: "10", 22: "43", 23: "3", 30: "1000.000", 32: "1", 110: "36000.000", 111: "36000.000",
             130: "363.000", 131: "273.000"}
ident = machines.identify(info=INFO_A1PRO, settings=SET_A1PRO)
check("A1 Pro: Creality, «Creality Falcon A1 Pro 20W», grblHAL (prima: «Laser GRBL» generico)",
      (ident.vendor, ident.model, ident.family) == ("Creality", "Creality Falcon A1 Pro 20W", "grblHAL"),
      (ident.vendor, ident.model, ident.family))
check("…con la nota che dice di usare il cavo USB", any("cavo USB" in t for _k, t in ident.notes), ident.notes)
check("…il modello esiste nel catalogo", any(c[0] == ident.model for c in machines.CATALOG))
INFO_A1 = ["[VER:1.1f.20220810:]", "[OPT:VcHL,127,65536]", "[software versions: CV40-MASTER-Release V1.0.6]"]
SET_A1 = {22: "1", 23: "3", 130: "381.000", 131: "305.000"}
ida1 = machines.identify(info=INFO_A1, settings=SET_A1)
check("Falcon A1 10W (CV40-MASTER): sempre il Falcon A1 10W", ida1.model == "Creality Falcon A1 10W", ida1.model)

print("--- A2. chi in Wi-Fi non parla GRBL")
check("creality_net: scheda A1 Pro", wifi_setup.creality_net(INFO_A1PRO))
check("creality_net: modello del profilo A1 Pro (anche scollegato)", wifi_setup.creality_net((), "Creality Falcon A1 Pro 20W"))
check("creality_net: A1C (CV40mini) e T1 (CV60)", wifi_setup.creality_net(["[software versions: CV40MINI-Release]"])
      and wifi_setup.creality_net(["CV60"]))
check("creality_net: NON il Falcon A1 10W, né un Longer, né un profilo generico",
      not wifi_setup.creality_net(INFO_A1, "Creality Falcon A1 10W")
      and not wifi_setup.creality_net(["[LGT B1 V1.2]"], "Longer B1 40W") and not wifi_setup.creality_net((), "Laser GRBL"))

w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.4)

print("--- A3. Wi-Fi guidato")
w.set_active_profile(MachineProfile(name="Creality Falcon A1 Pro 20W", model="Creality Falcon A1 Pro 20W",
                                    bed_x=358.0, bed_y=268.0))
d = WifiDialog(w)
d.start()
spin(0.1)
check("profilo Falcon A1 Pro, laser scollegato: pagina «sistema di Creality», niente ricerca in rete",
      d.state == "creality" and "cavo USB" in d.body.text() and not d.has("find"), (d.state, d.body.text()[:80]))
d.close()
w.set_active_profile(MachineProfile(name="Laser GRBL", model="Laser GRBL", bed_x=358.0, bed_y=268.0))
d = WifiDialog(w)
d.start()
spin(0.1)
check("profilo generico, scollegato: come prima (caso E, con «Trova il laser in rete»)", d.state == "E" and d.has("find"),
      d.state)
d._then_cable = False  # come dopo «Trova il laser in rete»
d._found("192.168.1.10", [])
check("nessun laser trovato: la pagina ricorda Falcon A1 Pro, A1C e T1 e il cavo USB",
      d.state == "find_none" and "Falcon A1 Pro" in d.body.text() and "cavo USB" in d.body.text(), d.body.text()[:200])
d.close()

# ====================================================================== B. grbl: homing fatto da quando è aperta
print("--- B. homing ricordato dopo i riavvii della scheda")
ctl = w.ctl
ctl.homed, ctl.homed_once = False, False
ctl._check_space = True
ctl._handle("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
check("dopo l'homing: homed e homed_once", ctl.homed is True and ctl.homed_once is True, (ctl.homed, ctl.homed_once))
ctl._reset_asked_t = 0.0
ctl._handle("Grbl 1.1f ['$' for help]")
check("riavvio da solo (banner, come il Falcon col coperchio): homed spento, homed_once resta",
      ctl.homed is False and ctl.homed_once is True, (ctl.homed, ctl.homed_once))
ctl._handle("ALARM:3")
check("allarme 3: homed_once resta (dice solo che le coordinate sono quelle dell'homing)", ctl.homed_once is True)
ctl.homed_once = False

# ====================================================================== C. prova delle frecce (4A62)
print("--- C. prova delle frecce sul Falcon A1 dopo un riavvio")
RAW = {'0': '10', '1': '250', '3': '4', '10': '3', '20': '0', '21': '1', '22': '1', '23': '3', '27': '5.000',
       '100': '80.000', '101': '80.000', '110': '36000.000', '111': '36000.000', '120': '1000.000', '121': '1000.000',
       '130': '381.000', '131': '305.000'}


def roberto():
    """Il profilo del rapporto 4A62 (0.23.2): ancora lo 0 davanti a sinistra, assi «provati», non invertiti."""
    return MachineProfile(name="Creality Falcon A1 10W", model="Creality Falcon A1 10W", bed_x=381.0, bed_y=305.0,
                          negative_space=False, hard_limits=True, homing=True, invert_x=False, invert_y=False,
                          origin_corner="fl", tested_x=True, tested_y=True, axes_tested=True, raw_settings=dict(RAW))


jogs = []
w.ctl.jog = lambda dx=0.0, dy=0.0, feed=3000, tag=None: jogs.append((dx, dy))


def wizard(homed, homed_once, mpos):
    p = roberto()
    p.save()
    w.set_active_profile(p)
    w.ctl.homed, w.ctl.homed_once = homed, homed_once
    w.ctl.last_status = {"state": "Idle", "MPos": list(mpos)}
    d = SetupWizard(w)
    d._can_jog = lambda: True
    d.go(1)
    d.picker.choose("bl")
    d.go(2)
    del jogs[:]
    return d


# il caso del registro: homing alle 13:02:53, riavvio alle 13:04:25, freccia ← alle 13:04:33 da X=0, Y=28,68
d = wizard(False, True, (0.0, 28.68, 0.0))
d.jog("left")
check("dopo l'homing e un riavvio: ← dal bordo sinistro NON parte (prima partiva e la scheda andava in allarme)",
      not jogs and "finecorsa" in d.arrows_lab.text(), (jogs, d.arrows_lab.text()))
d.jog("right")
check("…→ parte (allontana dal bordo)", jogs and jogs[-1][0] > 0, jogs)
d._confirm(True)
check("…e con «Sì» X è provato, non invertito", d.tested[0] is True and d.inv[0] is False)
d.reject()
d = wizard(False, True, (30.0, 28.68, 0.0))
d.jog("left")
check("testa lontana dal bordo (X=30): ← parte come sempre", jogs and jogs[-1][0] < 0, jogs)
d.reject()
d = wizard(False, False, (0.0, 0.0, 0.0))
d.jog("left")
check("homing mai fatto da quando è collegata: la freccia parte come prima (le coordinate non dicono niente)",
      bool(jogs), jogs)
w.ctl.alarm_raised.emit(3, "Reset durante il movimento")
spin(0.05)
check("…se la scheda va in allarme subito, partita dallo 0 verso il bordo: «finecorsa, non è l'asse al contrario»",
      "Non vuol dire che l'asse è al contrario" in d.arrows_lab.text() and not d.confirm_box.isVisibleTo(d), d.arrows_lab.text())
d.reject()
d = wizard(False, False, (40.0, 0.0, 0.0))
d.jog("left")
w.ctl.board_rebooted.emit()
spin(0.05)
check("allarme o riavvio con la testa lontana dallo 0: il messaggio di sempre (non vale come prova)",
      "Non vuol dire" not in d.arrows_lab.text() and "non vale come prova" in d.arrows_lab.text(), d.arrows_lab.text())
d.reject()
d = wizard(False, True, (0.0, 0.0, 0.0))
check("all'inizio della prova dopo l'homing: dice da quali frecce cominciare (→ e ↓)",
      "destra" in d.arrows_lab.text() and "verso di te" in d.arrows_lab.text(), d.arrows_lab.text())
d.reject()

# ====================================================================== D. difetti rimessi apposta
print("--- D. difetti rimessi apposta")
real = SetupWizard._home_block


def old_block(self, axis, dd):  # come nella 0.23.2: senza «homed» nessun blocco
    if not self.main.ctl.homed:
        return False
    return real(self, axis, dd)


SetupWizard._home_block = old_block
d = wizard(False, True, (0.0, 28.68, 0.0))
d.jog("left")
SetupWizard._home_block = real
check("difetto 1 (protezione spenta dal riavvio): la prova se ne accorge (la freccia parte)", bool(jogs))
d.reject()
real_edge = SetupWizard._edge_start
SetupWizard._edge_start = lambda self, axis, dd: False
d = wizard(False, False, (0.0, 0.0, 0.0))
d.jog("left")
w.ctl.alarm_raised.emit(3, "x")
spin(0.05)
SetupWizard._edge_start = real_edge
check("difetto 2 (allarme al bordo spiegato come gli altri): la prova se ne accorge",
      "Non vuol dire che l'asse è al contrario" not in d.arrows_lab.text())
d.reject()

print("--- E. traduzioni")
src = {f: open(os.path.join(ROOT, "freelasercut", *f.split("/")), encoding="utf-8").read()
       for f in ("ui/dialogs_setup.py", "ui/dialogs_wifi.py", "machines.py")}
probe = ["Non vuol dire che l'asse è al contrario", "Questo laser in Wi-Fi usa il sistema di Creality",
         "Creality Falcon A1 Pro riconosciuto dalla scheda", "Se è un Creality Falcon A1 Pro, A1C o T1"]
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    found = [any(p in k and v and v != k for k, v in cat.items()) for p in probe]
    check(f"testi nuovi tradotti ({lang})", all(found), found)

w.close()
n = sum(results)
print(f"\n{n}/{len(results)} superati")
sys.exit(0 if n == len(results) else 1)
