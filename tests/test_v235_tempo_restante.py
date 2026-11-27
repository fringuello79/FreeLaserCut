# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5 (Deborah K., 27/11/2026): il tempo rimanente durante il lavoro «salta su e giù».

Fino alla 0.23.4: tempo trascorso / righe confermate × righe che mancano, ricalcolato a ogni risposta della scheda.
Le righe durano tempi molto diversi, le risposte arrivano a raffiche e la pausa contava come lavoro. Ora
(`freelasercut/job_clock.py`): ogni riga pesa la sua stima di tempo, il rapporto vero/stimato si misura sul lavoro
fatto (senza le righe ancora nel buffer della scheda), le pause non contano, il numero scende di un secondo al
secondo, si corregge piano e non risale mai; arrotondato.

Prove: (A) lavori simulati (tagli lunghi e poi una foto, macchina più lenta della stima, risposte a raffiche):
salti verso l'alto, errore a 25/50/75 % e confronto con il calcolo di prima; (B) pausa: il numero resta fermo e
alla ripresa non salta; (C) senza stima: righe contate, levigato; stime sbagliate ignorate; arrotondamento;
(D) stima dalle righe dell'anteprima (commenti, righe vuote); (E) il controllo con il simulatore e la finestra
(Classica o Banco) e la pagina del telefono; (F) difetti rimessi apposta (niente levigatura, pausa contata come
lavoro, righe ancora nel buffer della scheda contate come fatte).
Uso: python tests/test_v235_tempo_restante.py [classica|banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Yes))

from freelasercut import gcode_preview, job_clock  # noqa: E402
from freelasercut.job_clock import JobClock, cumulative_from_preview, round_left  # noqa: E402


# ====================================================================== A. lavori simulati
def simula(est, lento=1.25, buffer=15, raffica=15, pausa=None, stima=True, passo=0.25):
    """est: secondi stimati di ogni riga. La macchina impiega est × lento. La scheda conferma una riga quando entra
    nel suo buffer (fino a `buffer` righe avanti) e le conferme arrivano a gruppi di `raffica`. pausa: (inizio, durata)
    in secondi veri. -> lista di (t, vero che manca, nuovo, vecchio)."""
    est = np.asarray(est, float)
    vere = est * lento
    fine = np.cumsum(vere)  # quando la macchina finisce ogni riga (senza pausa)
    tot = len(est)
    clk = JobClock(tot, now=0.0)
    if stima:
        clk.set_estimate(np.cumsum(est))
    out, t, done = [], 0.0, 0
    durata = float(fine[-1]) + (pausa[1] if pausa else 0.0)
    while t < durata:
        t += passo
        in_pausa = pausa is not None and pausa[0] <= t < pausa[0] + pausa[1]
        tl = t - (min(max(t - pausa[0], 0.0), pausa[1]) if pausa else 0.0)  # tempo di lavoro della macchina
        finite = int(np.searchsorted(fine, tl, side="right"))
        conf = min(tot, finite + buffer)
        conf = (conf // raffica) * raffica if conf < tot else tot  # conferme a raffiche
        done = max(done, conf)
        clk.tick(t, paused=in_pausa)
        clk.progress(done)
        nuovo = clk.left(t)
        vecchio = (t / done * (tot - done)) if done > 20 else None  # il calcolo della 0.23.4 (pausa compresa)
        vero = max(0.0, durata - t)
        out.append((t, vero, nuovo, vecchio))
    return out


def salti_su(campioni, col, soglia=5.0):
    """Quante volte, da un secondo all'altro, il numero sale di più di soglia secondi."""
    n, prima, t_prima = 0, None, None
    for c in campioni:
        v = c[col]
        if v is None:
            continue
        if prima is not None and c[0] - t_prima >= 0.99:
            if v - prima > soglia:
                n += 1
            prima, t_prima = v, c[0]
        elif prima is None:
            prima, t_prima = v, c[0]
    return n


def errore_a(campioni, col, frazione):
    durata = campioni[-1][0]
    c = min(campioni, key=lambda c: abs(c[0] - frazione * durata))
    return abs(c[col] - c[1]) / max(c[1], 1.0) if c[col] is not None else 1.0


print("--- A. lavori simulati")
# 200 tagli lunghi (0,8 s stimati) e poi una foto di 6000 righe corte (0,02 s): 280 s stimati, 350 veri
est = [0.8] * 200 + [0.02] * 6000
s = simula(est)
check("A tagli e poi foto, macchina 25 % più lenta: il numero nuovo non risale mai",
      all(b[2] <= a[2] + 0.01 for a, b in zip(s, s[1:]) if a[2] is not None and b[2] is not None))
check("A …il calcolo di prima invece saltava o sbagliava molto (prova che il caso è difficile)",
      salti_su(s, 3) > 0 or max(errore_a(s, 3, f) for f in (0.25, 0.5, 0.75)) > 0.3,
      (salti_su(s, 3), [round(errore_a(s, 3, f), 2) for f in (0.25, 0.5, 0.75)]))
err = [errore_a(s, 2, f) for f in (0.25, 0.5, 0.75)]
check("A errore del numero nuovo a 25, 50 e 75 % del lavoro: sotto il 15 %", max(err) < 0.15,
      [round(e, 3) for e in err])
vec = [errore_a(s, 3, f) for f in (0.25, 0.5, 0.75)]
check("A …e più piccolo di quello di prima", sum(err) < sum(vec), ([round(e, 2) for e in err],
                                                                    [round(e, 2) for e in vec]))
# foto da sola, conferme a raffiche di 15: prima il numero tremolava
s2 = simula([0.03] * 8000, lento=1.0, raffica=15)
salite = sum(1 for a, b in zip(s2, s2[1:]) if a[2] is not None and b[2] is not None and b[2] - a[2] > 1.0)
check("A foto (8000 righe), risposte a raffiche: il numero nuovo non risale mai di più di 1 s fra due letture",
      salite == 0, salite)
fermo = [c for c in s2 if c[2] is not None]
scende = all(b[2] <= a[2] + 1.0 for a, b in zip(fermo, fermo[1:]))
check("A …e scende con il tempo (circa un secondo al secondo)", scende and abs((fermo[0][2] - fermo[-1][2])
      - (fermo[-1][0] - fermo[0][0])) < 0.25 * (fermo[-1][0] - fermo[0][0]))
s3 = simula([0.5] * 400, lento=0.7)
c3 = min(s3, key=lambda c: abs(c[0] - 0.5 * s3[-1][0]))
check("A lavoro corto (2 minuti e 20) con la macchina più veloce della stima (70 %): a metà lavoro sbaglia di meno "
      "di 15 s", abs(c3[2] - c3[1]) < 15, (round(c3[2]), round(c3[1])))
check("A …e il numero non risale mai", all(b[2] <= a[2] + 0.01 for a, b in zip(s3, s3[1:])
                                          if a[2] is not None and b[2] is not None))
check("A fine lavoro: il numero arriva a 0 (o quasi)", s[-1][2] is not None and s[-1][2] < 5, s[-1][2])

# ====================================================================== B. pausa
print("--- B. pausa")
sp = simula([0.1] * 3000, lento=1.0, pausa=(100.0, 60.0))
durante = [c[2] for c in sp if 101.0 <= c[0] < 159.0]
check("B pausa di 60 s: il numero resta fermo (varia meno di 2 s)", max(durante) - min(durante) < 2.0,
      (round(min(durante), 1), round(max(durante), 1)))
dopo = [c for c in sp if 158.0 <= c[0] <= 170.0]
check("B …alla ripresa non salta", salti_su(dopo, 2, 2.0) == 0)
err_p = errore_a(sp, 2, 0.75)
check("B …e dopo la pausa resta giusto (errore sotto il 10 % a tre quarti)", err_p < 0.10, round(err_p, 3))
vecchio_dopo = [c for c in sp if abs(c[0] - 200) < 0.2][0]
check("B …mentre prima la pausa faceva salire il tempo che manca", vecchio_dopo[3] > vecchio_dopo[1] * 1.15,
      (round(vecchio_dopo[3]), round(vecchio_dopo[1])))

# ====================================================================== C. senza stima, stime sbagliate, arrotondamento
print("--- C. senza stima e casi limite")
s4 = simula([0.05] * 4000, lento=1.0, stima=False)
primi = [c for c in s4 if c[2] is not None]
check("C senza stima: niente numero prima di 20 righe, poi c'è", s4[0][2] is None and primi)
check("C …levigato anche contando le righe: mai su di più di 1 s",
      sum(1 for a, b in zip(primi, primi[1:]) if b[2] - a[2] > 1.0) == 0)
c = JobClock(10, now=0.0)
check("C stima con un numero di righe diverso: ignorata", c.set_estimate([1.0] * 9) is False and not c.has_estimate)
check("C stima vuota, a zero o non numerica: ignorata", c.set_estimate([0.0] * 10) is False
      and c.set_estimate(None) is False and c.set_estimate([float("nan")] * 10) is False)
c = JobClock(0, now=0.0)
check("C lavoro senza righe: nessun errore, nessun numero", c.left(1.0) is None)
check("C arrotondamento: 5 s sotto il minuto, 10 s sotto i 10 minuti, poi al minuto",
      [round_left(x) for x in (0, 3, 41, 59.5, 61, 125, 599, 601, 3725)] == [0, 5, 45, 60, 60, 120, 600, 600, 3720],
      [round_left(x) for x in (0, 3, 41, 59.5, 61, 125, 599, 601, 3725)])

# ====================================================================== D. stima dalle righe dell'anteprima
print("--- D. stima dalle righe dell'anteprima")
righe = ["; commento", "G90 G21", "", "M4 S0", "G0 X10 Y10", "(nota)", "G1 X60 S500 F600", "G1 Y40",
         "G1 X10 ; ritorno", "G1 Y10", "M5"]
pv = gcode_preview.parse(righe)
from freelasercut.grbl import _clean_lines_index  # noqa: E402

pulite, idx = _clean_lines_index(righe)
cum = cumulative_from_preview(pv, idx)
check("D righe pulite e posizione fra quelle ricevute (commenti e righe vuote saltati)",
      pulite[0] == "G90 G21" and list(idx) == [1, 3, 4, 6, 7, 8, 9, 10], list(idx))
check("D una stima per ogni riga mandata, che finisce con il tempo stimato dell'anteprima", cum is not None
      and len(cum) == len(pulite) and abs(cum[-1] - pv.seconds) < 1e-6, (None if cum is None else cum[-1],
                                                                          pv.seconds))
check("D le righe senza movimento non pesano, il taglio da 50 mm a 10 mm/s sì (circa 5 s)",
      cum[0] == 0 and cum[1] == 0 and 4.9 < cum[3] - cum[2] < 5.6, list(np.round(cum, 2)))
check("D anteprima senza tempi: nessuna stima (si contano le righe)", cumulative_from_preview(object(), idx) is None)

# ====================================================================== E. controllo, finestra e telefono
print("--- E. il controllo con il simulatore e la finestra")
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


def spin(t):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.01)


w = MainWindow()
w._confirm_discard = lambda: True
spin(0.2)
ctl = w.ctl
ctl.connect_port(SIM_PORT, 115200)
spin(2.0)
ctl.sim.speedup = 4
job = ["G90 G21", "M4 S0", "G0 X20 Y20"]
for k in range(60):
    y = 20 + k * 0.5
    job += [f"G1 X{80 if k % 2 == 0 else 20} Y{y:.2f} S300 F3000", f"G1 Y{y + 0.5:.2f}"]
job += ["M5", "G0 X0 Y0"]
pvj = gcode_preview.parse(job, profile=w.profile)
w._run(job, preview=pvj)
spin(1.5)
check("E lavoro partito: il controllo ha la stima riga per riga", ctl.job_active and ctl.job_clock is not None
      and ctl.job_clock.has_estimate)
v1 = ctl.job_time_left()
spin(1.0)
v2 = ctl.job_time_left()
check("E il tempo che manca c'è e scende", v1 is not None and v2 is not None and v2 < v1, (v1, v2))
if UI == "classica":
    check("E Classica: la riga sotto la barra dice «restante ~»", "restante ~" in w.laser.eta.text()
          or "remaining" in w.laser.eta.text(), w.laser.eta.text())
else:
    bc = w.banco
    check("E Banco: la cabina mostra il tempo che manca e l'ora di fine", bc.cockpit_on
          and ":" in bc.cockpit.left.text() and bc.cockpit.eta.text() != "", (bc.cockpit.left.text(),
                                                                                bc.cockpit.eta.text()))
ph = getattr(w, "phone", None)
if ph is not None and hasattr(ph, "refresh"):
    try:
        ph.refresh()
        snap = ph.snapshot
        check("E pagina del telefono: «mancano circa» con il tempo nuovo, arrotondato",
              snap.get("left") is not None and snap["left"] % 5 == 0, snap.get("left"))
    except Exception as ex:  # noqa: BLE001
        check("E pagina del telefono: aggiornamento senza errori", False, repr(ex))
else:
    check("E pagina del telefono: c'è il suo controllo", False)
ctl.feed_hold()
spin(1.0)
p1 = ctl.job_time_left()
spin(2.0)
p2 = ctl.job_time_left()
check("E in pausa (Hold) il tempo che manca resta fermo", ctl.last_status.get("state", "").startswith("Hold")
      and p1 is not None and abs(p2 - p1) < 0.6, (ctl.last_status.get("state"), p1, p2))
ctl.resume()
spin(1.5)
p3 = ctl.job_time_left()
check("E alla ripresa riparte senza salti", p3 is not None and p3 <= p2 + 1.0, (p2, p3))
t0 = time.time()
while ctl.job_active and time.time() - t0 < 120:
    spin(0.2)
check("E a lavoro finito: nessun tempo che manca", not ctl.job_active and ctl.job_time_left() is None)
# file senza anteprima: si contano le righe, nessun errore
w._run(["G90 G21", "M4 S0"] + [f"G1 X{10 + (i % 2) * 5} Y{10 + i * 0.1:.2f} S200 F6000" for i in range(80)]
       + ["M5"])
spin(1.0)
check("E lavoro senza stima (righe passate da fuori): si contano le righe, nessun errore",
      ctl.job_clock is not None and not ctl.job_clock.has_estimate)
ctl.stop_job()
spin(1.0)

# ====================================================================== F. difetti rimessi apposta
print("--- F. difetti rimessi apposta")
vero = (job_clock.TAU_S, job_clock.MAX_RATE)
job_clock.TAU_S, job_clock.MAX_RATE = 1e-6, 1e9  # niente levigatura né limite: il numero segue ogni raffica
s5 = simula([0.8] * 200 + [0.02] * 6000)
job_clock.TAU_S, job_clock.MAX_RATE = vero
salite5 = sum(1 for a, b in zip(s5, s5[1:]) if a[2] is not None and b[2] is not None and b[2] - a[2] > 1.0)
check("F senza levigatura il numero risale (la prova lo vede)", salite5 > 0, salite5)
vero_tick = JobClock.tick


def tick_senza_pausa(self, now=None, paused=None):
    return vero_tick(self, now, False)


JobClock.tick = tick_senza_pausa
sp2 = simula([0.1] * 3000, lento=1.0, pausa=(100.0, 60.0))
JobClock.tick = vero_tick
durante2 = [c[2] for c in sp2 if 101.0 <= c[0] < 159.0]
check("F la pausa contata come lavoro: la prova vede il numero che si muove", max(durante2) - min(durante2) >= 2.0,
      (round(min(durante2), 1), round(max(durante2), 1)))

vero_buf = job_clock.RIGHE_NEL_BUFFER
job_clock.RIGHE_NEL_BUFFER = 0  # le righe confermate contate come già fatte (sono ancora nel buffer della scheda)
s6 = simula([0.8] * 200 + [0.02] * 6000)
job_clock.RIGHE_NEL_BUFFER = vero_buf
check("F righe nel buffer contate come fatte: la prova vede l'errore grande (oltre il 30 % a metà)",
      errore_a(s6, 2, 0.5) > 0.3, round(errore_a(s6, 2, 0.5), 3))

ctl.disconnect_port()
w.close()
spin(0.2)
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
