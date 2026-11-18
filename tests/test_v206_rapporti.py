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
L  camera della testa con lente molto grandangolare (camera di Ale, 18/11): il conto inverso torna su tutta l'immagine
   anche con una lente forte; con i puntini misurati dalla sua foto il modello completo è valido, viene scelto e sbaglia
   meno di un pixel; la vista dice quale calibrazione è in uso; le misure dell'ultima calibrazione entrano nel rapporto;
M  tasto destro su una foto (Ale, 17/11): compaiono «Prepara foto» e «Vettorizza immagine»; su altre forme, su più
   oggetti o sul vuoto il menu resta com'era;
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

print("--- L. camera della testa: lente molto grandangolare")
import math  # noqa: E402

import numpy as np  # noqa: E402

from freelasercut import head_camera as hc  # noqa: E402
from freelasercut import head_camera_ui as hcu  # noqa: E402
from freelasercut import head_grid as hg  # noqa: E402

# puntini della griglia misurati dalla foto di Ale del 18/11 (vista della testa, 644 × 362): x, y in pixel e posto
# nello schema (colonna, riga) con le righe sfalsate di mezzo passo
ALE_DOTS = [
    (320.0, 43.4, 0, -3), (372.4, 43.4, 1, -3), (267.5, 45.4, -1, -3), (422.7, 45.4, 2, -3), (469.5, 48.6, 3, -3),
    (217.7, 48.7, -2, -3), (171.8, 53.6, -3, -3), (511.6, 53.2, 4, -3), (293.4, 87.0, -1, -2), (347.9, 86.2, 0, -2),
    (400.9, 86.6, 1, -2), (240.5, 89.0, -2, -2), (450.9, 88.5, 2, -2), (190.9, 92.3, -3, -2), (496.5, 91.2, 3, -2),
    (536.4, 94.5, 4, -2), (146.6, 96.4, -4, -2), (321.3, 132.5, -1, -1), (376.4, 132.0, 0, -1),
    (429.0, 132.4, 1, -1), (265.9, 133.7, -2, -1), (477.3, 133.6, 2, -1), (520.9, 134.6, 3, -1),
    (213.6, 135.2, -3, -1), (557.9, 136.0, 4, -1), (165.9, 137.3, -4, -1), (455.6, 179.1, 1, 0),
    (502.0, 178.2, 2, 0), (542.4, 177.5, 3, 0), (239.0, 181.4, -3, 0), (404.3, 179.7, 0, 0), (143.0, 182.2, -5, 0),
    (188.3, 181.8, -4, 0), (559.9, 218.4, 3, 1), (522.7, 221.4, 2, 1), (479.5, 224.1, 1, 1), (430.6, 226.4, 0, 1),
    (165.7, 227.2, -5, 1), (213.7, 228.3, -4, 1), (266.5, 229.0, -3, 1), (322.1, 228.9, -2, 1),
    (377.8, 227.9, -1, 1), (540.2, 261.4, 2, 2), (500.0, 266.3, 1, 2), (146.0, 269.4, -6, 2), (454.4, 270.5, 0, 2),
    (191.0, 272.6, -5, 2), (241.1, 274.8, -4, 2), (403.9, 273.6, -1, 2), (295.0, 276.1, -3, 2),
    (350.2, 275.6, -2, 2), (553.5, 297.5, 2, 3), (517.0, 304.0, 1, 3), (474.6, 310.3, 0, 3), (171.5, 312.5, -6, 3),
    (218.3, 316.6, -5, 3), (427.3, 315.2, -1, 3), (376.3, 318.4, -2, 3), (269.3, 319.4, -4, 3),
    (322.9, 319.9, -3, 3),
]
SHOT = (644, 362)
Pd = np.array([(a, b) for a, b, _i, _j in ALE_DOTS], float)
Xd = np.array([(i + 0.5 * j, -j * math.sqrt(3) / 2) for _a, _b, i, j in ALE_DOTS], float) * 7.6
ctl = np.array([(3 * j + 2 * i) % 5 == 0 for _a, _b, i, j in ALE_DOTS])


def obs_of(sel):
    return {"P": Pd[sel], "L": np.zeros((int(sel.sum()), 2)), "X": Xd[sel]}


xn = (Pd[~ctl] - np.array(SHOT) / 2) / (math.hypot(*SHOT) / 2)
Maff = np.linalg.lstsq(np.c_[xn, np.ones(len(xn))], Xd[~ctl], rcond=None)[0]
par = {"A": Maff[:2].T.copy(), "t": Maff[2].copy(), "g": np.zeros(2), "k1": 0.0, "k2": 0.0, "q": np.zeros(2)}
fits = {}
for kind in hg.KINDS:
    par, _rms = hg.fit(obs_of(~ctl), SHOT, par, kind)
    e_ctl, _sc = hg.errors_px(par, obs_of(ctl), SHOT)
    if hg.params_ok(par, SHOT):
        fits[kind] = (par, e_ctl)
check("puntini della foto di Ale: lente e modello completo sono validi (prima erano scartati negli angoli)",
      set(fits) == set(hg.KINDS), sorted(fits))
best = hg.choose_kind(fits)
e_best = fits[best][1] * 2  # la schermata è a metà risoluzione: pixel della camera
check("…viene scelto il modello completo e sui punti di controllo sbaglia meno di 1,5 pixel della camera (limite 3)",
      best == "full" and e_best.max() < 1.5 and np.percentile(e_best, 95) <= hg.GOOD_P95_PX, (best, e_best.max()))
check("…il modello a un solo coefficiente, l'unico che restava, sbagliava oltre il limite",
      (fits["k1"][1] * 2).max() > hg.GOOD_MAX_PX, (fits["k1"][1] * 2).max())
check("…la lente trovata è forte e positiva (grandangolo)", fits["full"][0]["k1"] > 0.2 and fits["full"][0]["k2"] > 0.2,
      (fits["full"][0]["k1"], fits["full"][0]["k2"]))
yy, xx = np.mgrid[0:720:24, 0:1280:24]
px = np.c_[xx.ravel(), yy.ravel()].astype(float)
worst = {}
for k1, k2 in ((0.306, 0.319), (0.6, 0.5), (0.45, 0.0), (-0.18, 0.05), (-0.3, 0.0)):
    mm = hc.HeadModel(None, None, (1280, 720), k=k1, A=[[60, 0], [0, -60]], t=[5, 35], g=[0.02, 0.03], k2=k2,
                      q=[-0.012, -0.013])
    back = mm.bed_to_img(np.zeros(2), mm.img_to_bed(np.zeros(2), px))
    worst[(k1, k2)] = float(np.abs(back - px).max()) if np.isfinite(back).all() else float("inf")
check("pixel → piano → pixel torna su tutta l'immagine con lenti deboli, forti, positive e negative",
      max(worst.values()) < 1e-6, worst)
fold = hc.HeadModel(None, None, (1280, 720), k=-0.6, A=[[60, 0], [0, -60]], t=[0, 0])
far = fold.bed_to_img(np.zeros(2), np.array([[500.0, 0.0], [10.0, 5.0]]))
check("un punto che con quella lente non può stare nell'immagine resta «non visibile», uno vicino sì",
      not np.isfinite(far[0]).all() and np.isfinite(far[1]).all(), far)
check("la vista dice quale calibrazione è in uso: nessuna, col puntino, completa, poco precisa",
      "nessuna" in hcu.calibration_state(None)
      and "puntino" in hcu.calibration_state(hc.HeadModel([[0.08, 0], [0, -0.08]], [0, 35], (640, 480))))
mg = hg.params_model(fits["full"][0], SHOT)
mg.method = "grid"
mg.quality = {"max_mm": 0.12}
st_ok = hcu.calibration_state(mg)
mg.quality = {"max_mm": 0.9, "approx": True}
st_ap = hcu.calibration_state(mg)
check("…con l'errore massimo, e «poco precisa» quando lo è", "completa" in st_ok and "0.12" in st_ok
      and "poco precisa" in st_ap and "0.90" in st_ap, (st_ok, st_ap))
rep = {"frame_size": SHOT, "obs_fit": obs_of(~ctl), "obs_ctl": obs_of(ctl), "by_kind": {"k1": 2.7, "full": 0.5},
       "quality": {"model": "full", "max_px": 1.0}, "backlash": (0.02, 0.01), "provisional": object()}
saved = hg.save_measures(rep, "Calibrazione da rifare: prova", kept=False)
data = json.load(open(saved, encoding="utf-8")) if saved else {}
check("le misure dell'ultima calibrazione si salvano (puntini visti, testa, errori per modello), riuscita o no",
      saved == hg.measures_file() and data.get("tenuta") is False and len(data["obs_ctl"]["P"]) == int(ctl.sum())
      and len(data["obs_fit"]["X"]) == int((~ctl).sum()) and data["by_kind"]["full"] == 0.5
      and "prova" in data["messaggio"] and "provisional" not in data, list(data))
check("…ed entrano nel rapporto per l'assistenza", '"obs_fit"' in diag.head_measures_text())
check("…un guasto nel salvataggio non ferma niente", hg.save_measures(rep, "", path=os.path.join(TMP, "no", "x.json")) is None)

print("--- M. tasto destro su una foto")
from PIL import Image  # noqa: E402

from freelasercut.core.document import ImageShape, RectShape  # noqa: E402

w = MainWindow()
ed = w.editor
ed.doc.images["f"] = Image.new("L", (40, 30), 128)
img = ImageShape("f", 40, 30, layer=1)
rect = RectShape(20, 10, layer=1)
ed.add([img, rect], "prova")
ed.select([rect])
base_rect = w.context_menu_keys()
ed.select([img])
k_img = w.context_menu_keys()
check("su una foto: «Prepara foto» e «Vettorizza immagine», subito dopo taglia/copia/incolla",
      k_img[:9] == ["cut", "copy", "paste", "duplicate", "delete", "-", "photo", "trace", "-"]
      and w.acts["trace"].isEnabled(), k_img[:10])
check("…il resto del menu della foto è quello di prima", [k for k in k_img if k not in ("photo", "trace")][6:] ==
      [k for k in base_rect if k != "simplify"][5:] or set(base_rect) - {"simplify"} <= set(k_img), (k_img, base_rect))
check("su un rettangolo il menu non cambia", "trace" not in base_rect and "photo" not in base_rect)
ed.select([img, rect])
check("su una foto insieme ad altro: niente voci della foto (il comando non potrebbe partire)",
      "trace" not in w.context_menu_keys())
ed.select([])
check("sul vuoto il menu non cambia", "trace" not in w.context_menu_keys() and "paste" in w.context_menu_keys())
w.close()

print("--- T. traduzioni")
keys = ("Scritte", "Potenza delle scritte del test: alzala se vengono troppo leggere",
        "Velocità delle scritte del test: abbassala se vengono troppo leggere", WIFI_HINT,
        "In uso: nessuna calibrazione", "In uso: calibrazione col puntino del {0}",
        "In uso: calibrazione completa del {0}", "In uso: calibrazione completa del {0} · errore massimo {1:.2f} mm",
        "In uso: calibrazione completa del {0} · poco precisa, errore massimo {1:.2f} mm")
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
