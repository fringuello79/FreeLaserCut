# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.9, dalle prove di Evo con la K40 vera e la 0.22.8 (funziona tutto; il contorno si
ferma un paio di secondi a ogni angolo; la potenza dei livelli non serve, è sulla manopola).

A. contorno a laser spento con la K40: uno spostamento veloce fino al primo punto, poi un lavoro solo senza soste, a
   30 mm/s al massimo; laser mai acceso; la testa torna al punto di partenza; con le altre macchine le righe di sempre.
B. finestra: con il profilo K40 i campi della potenza sono spenti (impostazioni rapide; nel Banco il cursore), con un
   altro profilo tornano.
C. difetti rimessi apposta.
D. (Ale, 25/11) la potenza dei livelli non conta: sulla K40 ogni livello inciso accende al massimo, anche se è a 0 %;
   con le altre macchine non cambia niente; un difetto rimesso apposta.

Uso: python tests/test_v229_k40.py [classica|banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox, QSlider  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from k40_scheda_finta import MIL, SchedaFinta  # noqa: E402

from freelasercut import grbl  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.k40.ponte import K40Serial  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
K = 0.02


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info != "" and not cond else ""),
          flush=True)


def until(fn, t=20.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.005)
    return bool(fn())


class Finto:
    """GrblController quanto basta per frame_path: raccoglie le righe."""

    def __init__(self, port):
        self.port, self.righe = port, []

    def send_line(self, riga, tag=None):
        self.righe.append(riga)


def righe_contorno(port, pts, feed=6000, back=None):
    f = Finto(port)
    grbl.GrblController.frame_path(f, pts, feed, 0.0, 1000.0, back=back)
    return f.righe


def esegui(righe):
    """Le righe al ponte con la scheda finta (dopo la casa). -> (scheda, secondi veri / K, ponte)"""
    b = SchedaFinta(scala=K, veloce_mm_s=40.0)
    p = K40Serial(b, scala_tempo=K)
    time.sleep(0.1)

    def cmd(r):
        p.write((r + "\n").encode())
        end = time.time() + 30
        while time.time() < end:
            x = p.readline()
            if x and (x.strip() == b"ok" or x.startswith(b"error") or x.startswith(b"ALARM")):
                return x.decode().strip()
        return "niente"

    def fermo():
        p.write(b"?")
        end = time.time() + 1
        while time.time() < end:
            x = p.readline()
            if x.startswith(b"<"):
                return x.startswith(b"<Idle")
        return False

    cmd("$H")
    until(fermo)
    t0 = time.time()
    esiti = [cmd(r) for r in righe]
    until(fermo, 60)
    return b, (time.time() - t0) / K, p, esiti


# ====================================================================== A. contorno
print("--- A. contorno della K40")
PTS = [(60.0, 40.0), (95.0, 40.0), (95.0, 75.0), (60.0, 75.0), (60.0, 40.0)]
rk = righe_contorno(grbl.K40_PORT, PTS)
check("A K40: niente frecce ($J): M5, uno spostamento veloce al primo punto, poi G1 a laser spento",
      rk[0] == "M5 S0" and rk[1].startswith("G53 G0 X60.000 Y40.000") and len(rk) == 6
      and all(r.startswith("G53 G1 ") and " S0 " in r for r in rk[2:]) and not any("$J" in r for r in rk), rk)
check("A K40: velocità del contorno al massimo 1800 mm/min (30 mm/s)", all(r.endswith("F1800") for r in rk[2:]), rk[2:])
check("A K40: una velocità più bassa resta quella chiesta",
      all(r.endswith("F1200") for r in righe_contorno(grbl.K40_PORT, PTS, feed=1200)[2:]))
rb = righe_contorno(grbl.K40_PORT, PTS, back=(10.0, 20.0))
check("A K40: con il punto di ritorno, l'ultima riga ci torna (sempre a laser spento)",
      rb[-1].startswith("G53 G1 X10.000 Y20.000 S0"), rb[-1])
rn = righe_contorno("COM3", PTS)
check("A le altre macchine: le frecce di sempre, una per punto", len(rn) == 5 and all(r.startswith("$J=G53 G21 ") for r in rn)
      and rn[0].endswith("F6000"), rn)
b, dur, p, esiti = esegui(rk)
check("A sulla scheda finta: tutte le righe accettate", all(e == "ok" for e in esiti), esiti)
check("A …un solo spostamento veloce e un solo lavoro (nessuna sosta agli angoli)",
      b.comandi.count("S1P") == 1 and b.comandi.count("FNSE") == 1, (b.comandi.count("S1P"), b.comandi.count("FNSE")))
check("A …il laser non si accende mai (nessuna «D», niente bruciato)", b.d_ricevute == 0 and not b.accesi,
      (b.d_ricevute, len(b.accesi)))
check("A …la testa torna al punto di partenza del giro, senza pericoli e senza «I» in moto",
      abs(b.x - round(60 * MIL)) <= 1 and abs(b.y - round(40 * MIL)) <= 1 and not b.pericoli and b.interrotti == 0,
      (b.x / MIL, b.y / MIL, b.pericoli, b.interrotti))
# giro: 140 mm a 30 mm/s = 4,7 s; + spostamento veloce (100 mm: circa 3,3 s di attesa) + 0,5 s veri di silenzio (25 qui)
check("A …tempo: il giro va a 30 mm/s senza fermate (con le frecce erano 4 soste in più)", dur < 4.7 + 3.5 + 25 + 6,
      round(dur, 1))
p.close()

# ====================================================================== B. finestra
print("--- B. campi della potenza")
w = MainWindow()
r = RectShape(20, 10, layer=1)
w.editor.add([r])
app.processEvents()
w.layers._load_quick()
check("B profilo normale: potenza max e min si possono cambiare", w.layers.q_pmax.isEnabled() and w.layers.q_pmin.isEnabled())
w.on_profile(MachineProfile.k40())
app.processEvents()
check("B profilo K40: potenza max e min spente, con la spiegazione; la velocità resta",
      not w.layers.q_pmax.isEnabled() and not w.layers.q_pmin.isEnabled() and "manopola" in w.layers.q_pmax.toolTip()
      and w.layers.q_speed.isEnabled(), w.layers.q_pmax.toolTip())
if UI == "banco":
    rail = w.banco.rail
    rail.open_index = 1
    rail.rebuild()
    app.processEvents()
    sl = [s for s in rail.inner.findChildren(QSlider)]
    spenti = [s for s in sl if not s.isEnabled()]
    check("B Banco, profilo K40: il cursore della potenza è spento, quello della velocità no",
          len(sl) == 2 and len(spenti) == 1 and "manopola" in spenti[0].toolTip(), (len(sl), len(spenti)))
p0 = MachineProfile()
w.on_profile(p0)
app.processEvents()
check("B tornando a un laser normale i campi della potenza tornano", w.layers.q_pmax.isEnabled()
      and w.layers.q_pmax.toolTip() == "")
if UI == "banco":
    w.banco.rail.rebuild()
    app.processEvents()
    check("B Banco, laser normale: tutti e due i cursori accesi",
          all(s.isEnabled() for s in w.banco.rail.inner.findChildren(QSlider)))
w.close()

# ====================================================================== C. difetti rimessi apposta
print("--- C. difetti rimessi apposta")
visti = 0
# 1. il contorno della K40 di nuovo con le frecce
vera_porta = grbl.K40_PORT
grbl.K40_PORT = "nessuna"
rj = righe_contorno(vera_porta, PTS)
grbl.K40_PORT = vera_porta
b, dur, p, esiti = esegui(rj)
visti += b.comandi.count("S1P") > 1 and b.comandi.count("FNSE") == 0
p.close()
# 2. il contorno con il laser acceso per sbaglio (M3 e S > 0)
b, dur, p, esiti = esegui(["M3 S500" if x == "M5 S0" else x.replace(" S0 ", " S500 ") for x in rk])
visti += b.d_ricevute > 0 and bool(b.accesi)
p.close()
check("C 2 difetti rimessi apposta (contorno con le frecce, laser acceso nel contorno): tutti visti", visti == 2, visti)

# ====================================================================== D. la potenza dei livelli non conta (25/11)
print("--- D. K40: la potenza dei livelli non conta (Ale, 25/11: deve incidere sempre)")
import re  # noqa: E402

from PySide6.QtGui import QTransform  # noqa: E402

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document  # noqa: E402
from freelasercut.k40 import da_gcode  # noqa: E402
from freelasercut.k40 import scrittore as S  # noqa: E402


def lavoro(prof, pmax, pmin=0.0, mode="line"):
    d = Document()
    r = RectShape(20.0, 10.0)
    r.apply(QTransform.fromTranslate(40.0, 40.0))
    d.add(r)
    cs = d.layer(r.layer)
    cs.power_max, cs.power_min, cs.mode = pmax, pmin, mode
    return gcode.generate(d, prof, gcode.JobOptions(start_from="absolute", no_g55=True))


def s_values(job):
    return [float(m) for ln in job.lines for m in re.findall(r"S([0-9.]+)", ln) if not ln.startswith(";")]


K40P = MachineProfile.k40()
for pm in (0.0, 5.0, 37.0, 100.0):
    j = lavoro(K40P, pm)
    on = [v for v in s_values(j) if v > 0]
    check(f"D K40, livello a {pm:g} %: il laser si accende (S pieno) nelle linee incise",
          on and max(on) == K40P.s_max and not any("potenza 0%" in w for w in j.warnings), (s_values(j)[:6], j.warnings))
j = lavoro(K40P, 0.0)
tratti = sum(1 for p in da_gcode.traduci(j.lines)[0] if p[0] == S.DATI)
check("D …e la scheda riceve davvero tratti a laser acceso (traduzione per la M2 Nano)", tratti > 0, tratti)
j = lavoro(K40P, 60.0, pmin=30.0, mode="fill")
check("D K40, riempimento con potenza minima 30 %: fra una riga e l'altra il laser è spento (S0), non acceso",
      0.0 in s_values(j) and set(s_values(j)) <= {0.0, K40P.s_max}, sorted(set(s_values(j))))
check("D K40: l'avviso dice ancora che la potenza si regola dalla manopola",
      any("manopola" in w for w in lavoro(K40P, 0.0).warnings))
B1 = MachineProfile()
j = lavoro(B1, 37.0)
check("D altre macchine: la potenza del livello resta quella scelta (37 % = S370)", 370.0 in s_values(j)
      and B1.s_max not in s_values(j), sorted(set(s_values(j))))
check("D altre macchine: livello a 0 % → avviso e laser spento, come sempre",
      any("potenza 0%" in w for w in lavoro(B1, 0.0).warnings) and not any(v > 0 for v in s_values(lavoro(B1, 0.0))))
# difetto rimesso apposta: senza la correzione (la potenza del livello passa alla K40) il livello a 0 % non incide
_repl = gcode.replace
gcode.replace = lambda cs, **k: cs if "power_max" in k and k.get("power_min") == 0.0 and len(k) == 2 else _repl(cs, **k)
j = lavoro(K40P, 0.0)
gcode.replace = _repl
check("D difetto rimesso apposta (potenza del livello passata alla K40, come fino alla 0.22.8): la prova se ne accorge",
      not any(v > 0 for v in s_values(j)), sorted(set(s_values(j))))

print()
print(f"{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
