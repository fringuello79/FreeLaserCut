# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: modifiche promesse agli utenti nelle risposte ai rapporti del 18/11/2026 (freeburn/promesse-utenti-2026-11-18.md).

I  FLC-20261118-1022-7487: il punto di riferimento della barra numerica resta l'ultimo scelto anche dopo il riavvio
   (valore rovinato → centro);
H  FLC-20261118-0900-681F: test materiali, potenza e velocità delle scritte scelte nella finestra e ricordate, usate
   nel G-code; numeri arrotondati (niente «33.3333%» né «41.7»), in mm/min e in mm/s; numeri troppo larghi per la
   colonna rimpiccioliti invece di sovrapporsi;
G  FLC-20261118-1316-895B: in Wi-Fi (porta di rete, scheda dietro un modulo) le righe partono a pacchi piccoli (al
   massimo 80 byte e 4 righe in viaggio); dopo una riga arrivata rovinata (error:1, error:2) una per volta; sul cavo e
   con FluidNC/grblHAL tutto come prima; riga più lunga del pacco che parte da sola; avviso con la spiegazione;
   l'informazione nel rapporto;
A  FLC-20261117-1408-E933 (Creality con firmware «CV50-Pro»): la scheda interrompe l'elenco delle impostazioni e
   l'«ok» non arriva; le letture viaggiano da sole, una lettura senza risposta si chiude dopo 2 s, $$ si rilegge una
   volta, poi si usa quello che è arrivato e lo si dice; i comandi dopo hanno le loro risposte (niente sfasamento) e la
   scheda non risulta più occupata per sempre;
T  testi nuovi tradotti in tutte le lingue.
Uso: python tests/test_v206_rapporti.py [classica|banco]
"""
import json
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
INI = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_SETTINGS_INI"] = INI
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import units  # noqa: E402
from freelasercut.core import material_test as mtest  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.settings_store import app_settings  # noqa: E402
from freelasercut.ui.dialogs_materials import MaterialTestDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402
from freelasercut.ui.panels_design import saved_anchor  # noqa: E402

UI = os.environ["FLC_UI"]
WIFI_HINT = ("La riga è giusta: è arrivata rovinata alla scheda. Succede con il Wi-Fi disturbato o con disturbi "
             "elettrici (pompa dell'aria, compressore, aspiratore sulla stessa presa). Da ora FreeLaserCut manda "
             "una riga per volta, più lentamente. Controlla il pezzo: la riga saltata può aver lasciato un segno "
             "sbagliato. Se succede ancora, prova con il cavo USB e alimenta pompa e compressore da un'altra presa.")
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "")


print("--- I. punto di riferimento che resta dopo il riavvio")
w = MainWindow()
a = w.numeric.anchor
check("la prima volta il punto di riferimento è il centro", a.value == 4 and saved_anchor() == 4, a.value)
a.value = 0
a.changed.emit(0)  # come un clic sul quadratino in basso a sinistra
check("scelto in basso a sinistra: lo si ricorda", saved_anchor() == 0
      and str(app_settings().value("num_anchor")) == "0")
w.close()
w2 = MainWindow()
check("dopo il riavvio resta in basso a sinistra (e la barra lo usa)", w2.numeric.anchor.value == 0)
w2.numeric.anchor.value = 8
w2.numeric.anchor.changed.emit(8)
w2.close()
w3 = MainWindow()
check("e poi in alto a destra", w3.numeric.anchor.value == 8)
w3.close()
app_settings().setValue("num_anchor", "storto")
check("valore rovinato nelle impostazioni: torna al centro", saved_anchor() == 4)
app_settings().setValue("num_anchor", 12)
check("valore fuori dalla griglia: torna al centro", saved_anchor() == 4)

print("--- H. test materiali: numeri arrotondati")
units.set_speed_unit("mm/min")
check("potenze intere; un decimale solo sotto il 10 %",
      [mtest.power_label(v) for v in (33.3333, 100.0, 66.6667, 2.5, 7.25, 9.96)] ==
      ["33%", "100%", "67%", "2.5%", "7.2%", "10%"], [mtest.power_label(v) for v in (33.3333, 100.0, 66.6667, 2.5, 7.25, 9.96)])
check("velocità in mm/min intere (1666.67 → 1667)",
      [mtest.speed_label(v) for v in (1666.6667, 3000.0, 2500.4)] == ["1667", "3000", "2500"])
units.set_speed_unit("mm/s")
check("velocità in mm/s intere (41.7 → 42); un decimale solo sotto 10 mm/s",
      [mtest.speed_label(v) for v in (2500.0, 450.0, 600.0)] == ["42", "7.5", "10"],
      [mtest.speed_label(v) for v in (2500.0, 450.0, 600.0)])
prof = MachineProfile()
spec = mtest.TestSpec(p_min=10, p_max=60, rows=4, s_min=1000, s_max=6000, cols=7, cell=5, gap=1)
job = mtest.build(spec, prof)
check("sul test inciso le potenze non hanno decimali lunghi", not re.search(r"\d\.\d\d", str(mtest.power_label(26.6667))))
units.set_speed_unit("mm/min")

print("--- H. test materiali: potenza e velocità delle scritte")


def label_moves(job):
    """Righe G1 del blocco delle scritte: dopo le celle, prima dei riferimenti."""
    txt = "\n".join(job.lines)
    return txt


base = mtest.TestSpec(rows=2, cols=2)
j1 = mtest.build(base, prof)
j2 = mtest.build(mtest.TestSpec(rows=2, cols=2, label_power=60.0, label_speed=900.0), prof)
s60 = f"S{int(round(prof.s_max * 0.6))}"
check("le scritte si incidono con la potenza e la velocità scelte",
      s60 in "\n".join(j2.lines) and "F900" in "\n".join(j2.lines) and s60 not in "\n".join(j1.lines), s60)
check("di partenza come prima: 25 % e 3000 mm/min", base.label_power == 25.0 and base.label_speed == 3000.0
      and "F3000" in "\n".join(j1.lines))
nolab = mtest.build(mtest.TestSpec(rows=2, cols=2, labels=False, label_power=60.0, label_speed=900.0), prof)
check("senza etichette i valori delle scritte non contano", s60 not in "\n".join(nolab.lines))
narrow = mtest.TestSpec(rows=2, cols=8, cell=4, gap=0.5, s_min=10000, s_max=30000)  # numeri a 5 cifre
short = mtest.TestSpec(rows=2, cols=8, cell=4, gap=0.5, s_min=100, s_max=800)  # numeri a 3 cifre: ci stanno
units.set_speed_unit("mm/min")
bn, bs = mtest.build(narrow, prof).bounds, mtest.build(short, prof).bounds
check("colonne strette e numeri a 5 cifre: le scritte non escono dal test (una sì e una no su due righe)",
      abs(bn.right() - bs.right()) < 0.3 and abs(bn.left() - bs.left()) < 0.3, (bn, bs))
mid = mtest.TestSpec(rows=2, cols=5, cell=8, gap=1, s_min=10000, s_max=30000)
bm = mtest.build(mid, prof).bounds
check("colonne medie: numeri un po' più piccoli, tutti sulla stessa riga, dentro il test",
      bm.right() <= mtest.layout(mid).x0c + mtest.layout(mid).W + 0.3, bm)  # 0,13 mm: la freccia di «mm/min →», com era
w = MainWindow()
dlg = MaterialTestDialog(prof, None, parent=w)
check("nella finestra: potenza e velocità delle scritte, di partenza 25 % e 3000 mm/min",
      dlg.label_power.value() == 25.0 and dlg.label_speed.value() == 3000.0 and dlg.spec().label_power == 25.0)
dlg.label_power.setValue(55.0)
dlg.label_speed.setValue(1200.0)
check("cambiandole cambia il test", dlg.spec().label_power == 55.0 and dlg.spec().label_speed == 1200.0
      and "F1200" in "\n".join(dlg.build().lines))
dlg.labels.setChecked(False)
check("senza etichette i due campi si spengono", not dlg.label_power.isEnabled() and not dlg.label_speed.isEnabled())
dlg.labels.setChecked(True)
dlg.close()
dlg2 = MaterialTestDialog(prof, None, parent=w)
check("riaprendo la finestra si ricordano", dlg2.label_power.value() == 55.0 and dlg2.label_speed.value() == 1200.0)
dlg2.close()
units.set_speed_unit("mm/s")
dlg3 = MaterialTestDialog(prof, None, parent=w)
check("in mm/s la velocità delle scritte si mostra in mm/s e resta la stessa", dlg3.label_speed.value() == 1200.0
      and "20" in dlg3.label_speed.text())
dlg3.close()
units.set_speed_unit("mm/min")
w.close()

print("--- G. invio prudente in Wi-Fi")
from freelasercut import diag, grbl  # noqa: E402


class FakePort:
    def __init__(self):
        self.out = []

    def write(self, data):
        self.out.append(bytes(data))
        return len(data)


def make_ctl(port):
    c = grbl.GrblController()
    c._ser = FakePort()
    c.port = port
    return c


def inflight(c):
    return sum(x.length for x in c._inflight), len(c._inflight)


job = [f"G1 X{100 + i * 0.123:.3f} Y{50 + i * 0.077:.3f} S{(i * 37) % 1000}" for i in range(60)]
usb = make_ctl("COM4")
usb.stream_job(job)
b_usb, n_usb = inflight(usb)
check("sul cavo come prima: il buffer pieno (fino a 127 byte)", 100 < b_usb <= grbl.RX_BUFFER and usb.window() == (127, None),
      (b_usb, n_usb))
net = make_ctl("tcp://192.168.1.50:8080")
net.stream_job(job)
b_net, n_net = inflight(net)
check("in Wi-Fi: al massimo 80 byte e 4 righe in viaggio", b_net <= grbl.NET_BYTES and n_net <= grbl.NET_LINES
      and net.window() == (80, 4), (b_net, n_net))
sent_before = len(net._ser.out)
net._handle("ok")
check("a ogni «ok» parte la riga dopo, sempre nel limite", len(net._ser.out) == sent_before + 1
      and inflight(net)[1] <= grbl.NET_LINES and net.job_acked == 1, (len(net._ser.out), inflight(net)))
fluid = make_ctl("tcp://192.168.1.60:23")
fluid.trusted_buffer = True
fluid.rx_buffer = 255
fluid.stream_job(job)
check("FluidNC o grblHAL in rete (parlano direttamente in Wi-Fi): tutto il buffer, come prima",
      fluid.window() == (255, None) and inflight(fluid)[0] > grbl.NET_BYTES)
off = make_ctl("tcp://192.168.1.70:23")
off.net_prudent = False
check("si può spegnere (per le prove): torna come prima", off.window() == (127, None))
long_line = "G1 X" + "1" * 90 + " Y2"
lone = make_ctl("tcp://192.168.1.80:23")
lone.stream_job([long_line, "G1 X1 Y1"])
check("una riga più lunga del pacco parte da sola (niente lavoro fermo)", inflight(lone) == (len(long_line) + 1, 1),
      inflight(lone))
errs = []
net.job_error.connect(lambda i, line, code, text: errs.append((i, line, code)))
net._handle("error:2")
check("riga arrivata rovinata (error:2): il lavoro va in pausa come prima e da qui si manda una riga per volta",
      errs and errs[0][2] == 2 and net.net_lines == 1 and net.garbled_lines == 1 and net.window() == (80, 1), errs)
for _ in range(6):
    net._handle("ok")
check("una riga per volta davvero", inflight(net)[1] <= 1, inflight(net))
usb_errs = []
usb.job_error.connect(lambda i, line, code, text: usb_errs.append(code))
usb._handle("error:2")
check("sul cavo un error:2 non cambia il modo di mandare", usb_errs == [2] and usb.window() == (127, None)
      and usb.garbled_lines == 0)
other = make_ctl("tcp://192.168.1.90:23")
other.stream_job(job)
other._handle("error:20")
check("un altro errore (comando non supportato) non è una riga rovinata", other.net_lines == grbl.NET_LINES
      and other.garbled_lines == 0)
fresh = make_ctl("tcp://192.168.1.50:8080")
check("a ogni nuova connessione si riparte da 4 righe", fresh.net_lines == grbl.NET_LINES and fresh.garbled_lines == 0)


class W:
    ctl = net


env = diag.env_text(W())
check("nel rapporto per l'assistenza: come si manda e quante righe sono arrivate rovinate",
      "Invio: 80 byte · 1 righe in viaggio · righe arrivate rovinate: 1" in env, env)
w = MainWindow()
w.ctl.port = "tcp://192.168.1.50:8080"
shown = []
_exec = QMessageBox.exec
QMessageBox.exec = lambda self: shown.append((self.text(), self.informativeText())) or 0
w.ctl.stop_job = lambda: None
w.ctl.resume = lambda: None
w._job_error(214, "X170.854 S0", 2, "numero non valido")
w.ctl.port = "COM4"
w._job_error(214, "X170.854 S0", 2, "numero non valido")
QMessageBox.exec = _exec
check("in Wi-Fi l'avviso spiega che la riga è arrivata rovinata e cosa fare; sul cavo no",
      len(shown) == 2 and "rovinata" in shown[0][1] and "presa" in shown[0][1] and shown[1][1] == "", shown)
w.ctl.port = None
w.close()

print("--- A. scheda che interrompe le risposte lunghe")
import time as _t  # noqa: E402

cr = make_ctl("COM4")
msgs = []
cr.message.connect(msgs.append)
got = {}
cr.settings_ready.connect(lambda d: got.setdefault("settings", []).append(d))
cr.request_info()
cr.request_settings()
check("$I e $$ non partono insieme: $$ aspetta la risposta di $I",
      [c.line for c in cr._inflight] == ["$I"] and [c.line for c in cr._pending] == ["$$"])
for l in ("[VER:1.1f.20220810:]", "[OPT:VHL,127,65536]", "[software versions: CV50-Pro-MASTER-Release V1.0.1]", "ok"):
    cr._dispatch(l)
check("arrivato l'«ok» di $I parte $$", [c.line for c in cr._inflight] == ["$$"])
for l in ("$0=10", "$1=250", "$2=0", "$3=4", "$10=3", "$11=0.010", "$12=0.002", "$13=0", "$"):
    cr._dispatch(l)
cr.send_line("$H")
check("mentre $$ aspetta, il comando dopo non parte (la sua risposta non verrebbe presa per quella di $$)",
      [c.line for c in cr._inflight] == ["$$"] and [c.line for c in cr._pending] == ["$H"])
cr._watch_query()
check("finché la scheda ha parlato da poco la lettura resta aperta", [c.line for c in cr._inflight] == ["$$"])
cr._inflight[0].t -= 5
cr.last_line_t -= 5
cr._watch_query()
check("dopo 2 s di silenzio senza «ok» la lettura si chiude, lo dice e parte il comando dopo",
      [c.line for c in cr._inflight] == ["$H"] and msgs and "rileggo" in msgs[-1] and "settings" not in got, msgs)
cr._dispatch("ok")
check("l'«ok» che arriva è del comando giusto ($H): nessuno sfasamento", not cr._inflight and not cr.busy)
_t.sleep(0.8)
check("$$ si rilegge una volta da solo", [c.line for c in cr._inflight] == ["$$"])
for l in ("$0=10", "$1=250", "$2=0", "$3=4", "$10=3", "$11=0.010", "$12=0.002", "$13=0", "$20=0", "$21=1", "$22=1", "$2"):
    cr._dispatch(l)
cr._inflight[0].t -= 5
cr.last_line_t -= 5
cr._watch_query()
check("di nuovo interrotto: si usa quello che è arrivato e si dice fino a dove",
      got.get("settings") and got["settings"][-1].get(22) == "1" and "fino a $22" in msgs[-1] and not cr.busy, msgs[-1:])
cr._dispatch("ok")
check("un «ok» in ritardo dopo la chiusura non rompe niente", not cr.busy)
ok_ctl = make_ctl("COM5")
ok_ctl.request_settings()
for l in ("$0=10", "$130=400.000", "$131=415.000", "ok"):
    ok_ctl._dispatch(l)
ok_ctl._watch_query()
check("con una scheda normale tutto come prima (niente avvisi, impostazioni complete)",
      not ok_ctl.busy and ok_ctl.board_settings.get(131) == "415.000" and ok_ctl.lost_replies == 0)
jobc = make_ctl("COM6")
jobc.stream_job(job)
jobc.request_settings()
check("durante un lavoro una lettura aspetta la fine (le righe del lavoro continuano)",
      all(c.tag == "job" for c in jobc._inflight) and len(jobc._inflight) > 1)

print("--- T. traduzioni")
keys = ("Scritte", "Potenza delle scritte del test: alzala se vengono troppo leggere",
        "Velocità delle scritte del test: abbassala se vengono troppo leggere", WIFI_HINT)
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k) for k in keys if not cat.get(k) or cat[k] == k]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing)

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
