# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: Free Laser Cook (funzione in prova, dietro il codice amministratore).

A  il conto: energia per lato (numero fatto a mano), passate, dose uguale con laser di potenza diversa, laser
   debole (si rallenta, poi più passate), passate a mano, pollame, bordi del piano, dati mancanti;
B  il G-code: intestazione, solo M4, aria spenta, una sola pausa «gira» con il suo messaggio, fine; il laser brucia
   solo dentro il cibo; lunghezza bruciata = area / interlinea; passate incrociate; ovale; righe della griglia a 45°
   (e incrociate), firma dentro il suo riquadro, giro dell'aroma fuori dal cibo prima di ogni lato;
C  ricette: incluse, salva / rileggi / elimina, esporta / importa, file sbagliati, valori fuori scala corretti;
D  finestra: nascosta senza codice, visibile con il codice, accortezze da spuntare tutte, ricetta → valori, salva fra
   le mie, forma selezionata nel disegno, blocchi, guida;
E  testi delle ricette incluse tradotti in tutte le lingue.
Uso: python tests/test_v206_cook.py [classica|banco]
"""
import hashlib
import json
import math
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from dataclasses import replace  # noqa: E402

from freelasercut import admin, grbl  # noqa: E402
from freelasercut.core import cook as C  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
hidden = []


def _hook(tp, ex, tb):
    hidden.append(ex)
    import traceback

    traceback.print_exception(tp, ex, tb)


sys.excepthook = _hook


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def near(a, b, tol):
    return abs(a - b) <= tol


def burns(job):
    """Tratti con il laser acceso: [(x0, y0, x1, y1, S)] sul piano, e i comandi M visti."""
    x = y = s = 0.0
    mode, segs = "0", []
    ox, oy = job.out_to_bed
    for ln in job.lines:
        t = ln.split(";")[0].strip().upper()
        if not t:
            continue
        g = re.match(r"G([01])\b", t)
        if g:
            mode = g.group(1)
        if t.startswith("M5"):
            s = 0.0
        vals = {k: float(v) for k, v in re.findall(r"([XYS])(-?[\d.]+)", t)}
        if t.startswith(("G10", "M")) and "S" not in vals:
            continue
        s = vals.get("S", s)
        if t.startswith("G10"):
            continue
        nx, ny = vals.get("X", x), vals.get("Y", y)
        if mode == "1" and s > 0 and (nx, ny) != (x, y):
            segs.append((x + ox, y + oy, nx + ox, ny + oy, s))
        x, y = nx, ny
    return segs


def length(segs):
    return sum(math.hypot(c - a, d - b) for a, b, c, d, _s in segs)


PROF = MachineProfile()
BED = (PROF.bed_x, PROF.bed_y)
VMAX = min(PROF.max_rate_x, PROF.max_rate_y)
BEEF = C.find("manzo_fettina", True)
RECT = C.shape_polys("rect", 100, 100, 100, 80)


def plan_of(recipe=BEEF, watts=40.0, polys=RECT, **kw):
    return C.compute(recipe, watts, polys, bed=BED, vmax=VMAX, **kw)


# ====================================================================== A. il conto
# fettina di manzo, 3 mm girata: strato 1,5 mm, 20 → 60 °C
# E = 1,05e-3 g/mm³ · 1,5 mm · 3,5 J/gK · 40 K / (0,85 · 0,45) = 0,2205 / 0,3825 = 0,5765 J/mm²
p = plan_of()
check("A energia per lato della fettina di manzo media: 0,576 J/mm² (conto a mano)", near(p.energy_side, 0.5765, 0.001),
      p.energy_side)
check("A …con 0,10 J/mm² per passata fanno 6 passate per lato, due lati", p.passes == 6 and p.sides == 2, (p.passes, p.sides))
# D = P / (v · d): 40 W · pct / (200 mm/s · 1 mm) = 0,0961 → pct = 48,0%
check("A …a 12000 mm/min e 1 mm di interlinea con 40 W serve il 48% (conto a mano)", near(p.power, 48.04, 0.2)
      and p.speed == 12000, (p.power, p.speed))
check("A la dose vera non supera quella della ricetta", p.dose <= BEEF.dose_pass + 1e-9 and near(p.dose * p.passes,
                                                                                                 p.energy_side, 0.002))
check("A nessun avviso e nessun blocco sulla ricetta di partenza", p.ok and not p.warnings, p.warnings)
check("A al sangue meno passate, ben cotta di più", plan_of(doneness="al_sangue").passes < p.passes
      < plan_of(doneness="ben_cotta").passes)
check("A temperatura scelta a mano al posto del grado di cottura", near(plan_of(target=80.0).energy_side,
                                                                     0.5765 * 60 / 40, 0.002))
check("A fetta più spessa: più passate, in proporzione", plan_of(thickness=6.0).passes == 12
      and any("6 mm" in w for w in plan_of(thickness=7.0).warnings))
nf = plan_of(replace(BEEF, flip=False))
check("A senza girare: un lato solo, tutto lo spessore (il doppio delle passate)", nf.sides == 1 and nf.passes == 12,
      (nf.sides, nf.passes))
ok_all, worst = True, 0.0
for r in C.builtin():
    for watts in (48.0, 20.0, 10.0, 5.0):
        q = plan_of(r, watts)
        good = (q.ok and 1.0 <= q.power <= 100.0 and C.MIN_SPEED <= q.speed <= VMAX and 1 <= q.passes <= C.MAX_PASSES
                and q.dose <= r.dose_pass * 1.02 and q.dose * q.passes >= q.energy_side * 0.97)
        worst = max(worst, abs(q.dose * q.passes - q.energy_side) / q.energy_side)
        if not good:
            print("   ", r.key, watts, q.blockers, q.power, q.speed, q.passes, q.dose)
        ok_all = ok_all and good
check("A tutte le ricette incluse con 48, 20, 10 e 5 W: piano valido, dose entro quella della ricetta, energia per "
      "lato rispettata", ok_all, f"scarto massimo {worst * 100:.1f}%")
a, b = plan_of(watts=48.0), plan_of(watts=10.0)
check("A laser più debole: stessa dose e stesse passate, al 100% e più piano (non più caldo)",
      near(a.dose, b.dose, 0.002) and a.passes == b.passes and b.power == 100.0 and b.speed < a.speed, (b.power, b.speed))
c = plan_of(watts=0.5)
check("A laser debolissimo: velocità minima e più passate, ognuna con quello che il laser riesce a dare",
      c.speed == C.MIN_SPEED and c.passes == 12 and c.power > 90.0
      and near(c.dose * c.passes, c.energy_side, 0.001), (c.speed, c.passes, c.power))
d = plan_of(replace(BEEF, thickness=30.0, flip=False), watts=0.3, thickness=30.0)
check("A …e se le passate sarebbero troppe, il piano si blocca con il motivo", not d.ok and d.passes == C.MAX_PASSES,
      d.blockers)
m = plan_of(passes=10)
check("A passate a mano: usate, con l'avviso di quante ne darebbe il conto", m.passes == 10 and near(m.dose, 0.0577, 0.002)
      and any("10" in w and "6" in w for w in m.warnings), m.warnings)
check("A passate a mano vicine al conto: nessun avviso", not plan_of(passes=7).warnings)
hi = plan_of(replace(BEEF, dose_pass=0.4))
check("A dose alta per passata: avviso «brucia fuori, crudo dentro»", hi.ok and any("J/mm²" in w for w in hi.warnings))
check("A testa quasi a fuoco: avviso", any("15 mm" in w for w in plan_of(replace(BEEF, defocus_mm=3.0)).warnings))
# cottura rapida: righe a 2 mm e una volta e mezza la dose (mai oltre 0,20 J/mm²): stessa energia, laser al massimo
fd, fi = C.fast_values(BEEF)
check("A cottura rapida: per la fettina 0,15 J/mm² a 2 mm; per il marshmallow 0,075; una dose già alta non si abbassa",
      (fd, fi) == (0.15, 2.0) and C.fast_values(C.find("marshmallow", True)) == (0.075, 2.0)
      and C.fast_values(replace(BEEF, dose_pass=0.3, interval=3.0)) == (0.3, 3.0), (fd, fi))
slow = plan_of(watts=48.0)
quick = plan_of(replace(BEEF, dose_pass=fd, interval=fi), watts=48.0)
ts, tq = C.build_job(slow, PROF).seconds, C.build_job(quick, PROF).seconds
check("A …stessa energia per lato, meno passate, laser al 100%, nessun avviso", near(quick.energy_side, slow.energy_side, 1e-9)
      and quick.passes == 4 and quick.power == 100.0 and near(quick.dose * quick.passes, quick.energy_side, 0.002)
      and not quick.warnings, (quick.passes, quick.power, quick.speed))
check("A …e il tempo della fettina media scende a meno della metà (da 11 a meno di 5 minuti con 48 W)",
      tq < ts * 0.5 and 600 < ts < 720 and tq < 300, (round(ts), round(tq)))
rare = plan_of(replace(BEEF, dose_pass=fd, interval=fi), watts=48.0, doneness="al_sangue")
tr_ = C.build_job(rare, PROF).seconds
# limite fisico: tutta l'energia / tutta la potenza = 0,432 J/mm² · 8000 mm² · 2 lati / 48 W = 144 s
check("A …al sangue ancora meno, e mai sotto il limite fisico energia / potenza (144 s)", 144 < tr_ < tq and tr_ < 240,
      round(tr_))
check("A righe larghe con la testa poco alzata: avviso delle strisce", any("strisce" in w for w in plan_of(
    replace(BEEF, dose_pass=fd, interval=fi, defocus_mm=10.0)).warnings))
CHICK = C.find("pollo_fettina", True)
pc = plan_of(CHICK)
check("A pollame: avviso del termometro sempre, e la ricetta inclusa arriva oltre 74 °C", pc.ok and pc.target >= C.POULTRY_T
      and any("74" in w for w in pc.warnings))
check("A pollame sotto 74 °C: bloccato", not plan_of(CHICK, target=65.0).ok)
tk = plan_of(C.find("tataki_manzo", True))
check("A tataki: ricetta di superficie, avviso «dentro resta crudo»", tk.ok and tk.recipe.surface
      and len(tk.warnings) == 1)
toast = C.find("pane_tostato", True)
# pane: strato 1 mm, 20 → 150 °C, 30% d'acqua che evapora:
# 0,30e-3 · 1 · (2,7 · 130 + 0,30 · 2260) / (0,55 · 0,45) = 0,30e-3 · 1029 / 0,2475 = 1,247 J/mm²
check("A pane tostato: conta lo strato di superficie e l'acqua che evapora (conto a mano 1,247 J/mm²)",
      near(C.energy_side(toast, 150.0, 12.0), 1.2473, 0.002) and near(C.energy_side(toast, 150.0, 30.0), 1.2473, 0.002))
check("A cibo fuori dal piano: bloccato", not plan_of(polys=C.shape_polys("rect", 400, 100, 100, 80)).ok)
check("A cibo troppo piccolo: bloccato", not plan_of(polys=C.shape_polys("rect", 100, 100, 4, 80)).ok)
check("A senza forma o senza potenza del laser: bloccato, senza errori", not plan_of(polys=[]).ok and not plan_of(watts=0).ok)
SMOKY = replace(BEEF, smoke=dict(BEEF.smoke, wood="ciliegio"))
check("A aroma con il cibo troppo vicino al bordo: bloccato; lontano dal bordo va, con l'avviso sul legno",
      not plan_of(SMOKY, polys=C.shape_polys("rect", 3, 100, 100, 80)).ok and plan_of(SMOKY).ok
      and len(plan_of(SMOKY).warnings) == 1)

# ====================================================================== B. il G-code
p = plan_of()
job = C.build_job(p, PROF)
L = [ln.split(";")[0].strip() for ln in job.lines]
L = [ln for ln in L if ln]
check("B intestazione: G90 G21, laser spento, origine azzerata (G10 L2 P2 + G55), aria spenta, poi M4",
      L[:7] == ["G90 G21", "M5 S0", "G10 L2 P2 X0 Y0", "G55", "M9", "M4 S0", L[6]] and L[6].startswith("G0"), L[:7])
check("B solo potenza dinamica: nessun M3 nel lavoro", not any(ln.startswith("M3") for ln in L))
check("B fine: laser spento, ritorno a X0 Y0, G54", L[-3:] == ["M5 S0", "G0 X0 Y0", "G54"], L[-3:])
i0 = [i for i, ln in enumerate(L) if ln == "M0"]
check("B una sola pausa per girare, con il laser spento prima e riacceso dopo", len(i0) == 1 and L[i0[0] - 1] == "M5 S0"
      and L[i0[0] + 1] == "M4 S0" and p.pauses == 1 and len(job.pauses) == 1)
msgs = grbl._pause_messages(job.lines)
check("B il messaggio della pausa arriva al programma («Gira il cibo…»)", len(msgs) == 1
      and "Gira" in list(msgs.values())[0], msgs)
bare = replace(BEEF, sear=dict(BEEF.sear, mode="none"), signature="")
pb = plan_of(bare)
jb = C.build_job(pb, PROF)
sb = burns(jb)
inside = all(100 - 1e-3 <= min(a, c) and max(a, c) <= 200 + 1e-3 and 100 - 1e-3 <= min(b, d_) and max(b, d_) <= 180 + 1e-3
             for a, b, c, d_, _s in sb)
check("B sola cottura: il laser è acceso soltanto dentro il cibo", inside and len(sb) > 100)
check("B …sempre alla potenza della cottura", {s for *_x, s in sb} == {round(pb.power / 100 * PROF.s_max, 1)},
      {s for *_x, s in sb})
# 100 × 80 mm a 1 mm di interlinea: 8000 mm per passata, 12 passate
check("B lunghezza bruciata = area / interlinea × passate (96000 mm)", near(length(sb), 96000.0, 5.0), length(sb))
cook_ph = [ph for ph in pb.phases if ph["kind"] == "cook"]
check("B fasi: 6 + 6 passate di cottura, ognuna da 8000 mm", len(cook_ph) == 12
      and all(near(ph["mm"], 8000.0, 1.0) for ph in cook_ph))
# energia = lunghezza / velocità × potenza = area × dose × passate
check("B energia sul piatto = area × dose × passate", near(pb.joule, 8000.0 * pb.dose * 12, 5.0), pb.joule)
vert = sum(math.hypot(c - a, d_ - b) for a, b, c, d_, _s in sb if abs(c - a) < 1e-6)
check("B passate incrociate: metà per il lungo e metà per il largo", near(vert, 48000.0, 5.0), vert)
flat = burns(C.build_job(plan_of(replace(bare, alternate=False)), PROF))
check("B senza passate incrociate: tutte per il lungo", all(abs(d_ - b) < 1e-6 for _a, b, _c, d_, _s in flat))
check("B tempo stimato e ingombro del lavoro", jb.seconds > 300 and near(jb.bounds.width(), 100, 0.01)
      and near(jb.bounds.height(), 80, 0.01) and not jb.warnings, (jb.seconds, jb.bounds))
one = C.build_job(plan_of(replace(bare, flip=False)), PROF)
check("B senza girare: nessuna pausa", not any(ln.strip() == "M0" for ln in one.lines) and not one.pauses)
nog = replace(PROF, no_g55=True) if hasattr(PROF, "no_g55") else PROF
jn = C.build_job(plan_of(bare), nog)
check("B macchina senza G55: si lavora in G54, senza G10", not any("G10" in ln or "G55" in ln for ln in jn.lines)
      and "G54" in jn.lines[:8])
# ovale
EL = C.shape_polys("ellipse", 100, 100, 100, 80)
pe = plan_of(bare, polys=EL)
se = burns(C.build_job(pe, PROF))
out = max(max(((x - 150) / 50) ** 2 + ((y - 140) / 40) ** 2 for x, y in ((a, b), (c, d_))) for a, b, c, d_, _s in se)
check("B ovale: il laser resta dentro l'ellisse e l'area è π/4 · 100 · 80", out <= 1.01 and near(pe.area, math.pi * 50 * 40, 15),
      (out, pe.area))
check("B …e la lunghezza bruciata per passata è l'area dell'ovale", near(length(se) / 12, pe.area, pe.area * 0.02))
# righe della griglia
smax = PROF.s_max
sg = [s for s in burns(job) if s[4] == smax]
ang = {round(math.degrees(math.atan2(d_ - b, c - a)) % 180) for a, b, c, d_, _s in sg if math.hypot(c - a, d_ - b) > 30}
check("B righe della griglia: al 100%, tutte a 45°", ang == {45}, ang)
offs = sorted({round((b - a) / math.sqrt(2), 2) for a, b, c, d_, _s in sg if math.hypot(c - a, d_ - b) > 30})
steps = {round(v - u, 1) for u, v in zip(offs, offs[1:])}
check("B …a 8 mm l'una dall'altra", steps == {8.0}, steps)
last_cook = max(ph["last"] for ph in p.phases if ph["kind"] == "cook")
check("B …e vengono dopo tutte le passate di cottura, sul lato che resta in alto",
      [ph["kind"] for ph in p.phases][-2:] == ["sear", "sign"] and min(ph["first"] for ph in p.phases
                                                                    if ph["kind"] == "sear") >= last_cook)
cross = plan_of(replace(BEEF, sear=dict(BEEF.sear, mode="crosshatch"), signature=""))
sx = [s for s in burns(C.build_job(cross, PROF)) if s[4] == smax]
angx = {round(math.degrees(math.atan2(d_ - b, c - a)) % 180) for a, b, c, d_, _s in sx if math.hypot(c - a, d_ - b) > 30}
check("B griglia incrociata: righe a 45° e a 135°", angx == {45, 135}, angx)
# firma
sp = C.signature_polys("FLC", p.box)
xs = [x for q in sp for x, _y in q.pts]
ys = [y for q in sp for _x, y in q.pts]
check("B firma: al centro del cibo, larga al massimo il 60% e alta al massimo il 30%",
      near((min(xs) + max(xs)) / 2, 150, 0.01) and near((min(ys) + max(ys)) / 2, 140, 0.01)
      and max(xs) - min(xs) <= 60.01 and max(ys) - min(ys) <= 24.01, (max(xs) - min(xs), max(ys) - min(ys)))
check("B firma dritta: la L ha l'asta a sinistra e il piede in basso",
      (lambda q: q.pts[0][1] > q.pts[1][1] and q.pts[2][0] > q.pts[1][0])(C.signature_polys("L", p.box)[0]))
check("B firma: una riga di 16 caratteri al massimo, solo quelli che il carattere sa scrivere",
      C.clean_signature("  Chef  Ale è qui da sempre!!  ") == "Chef Ale qui da" and C.signature_polys("", p.box) == [])
sign_ph = [ph for ph in p.phases if ph["kind"] == "sign"]
check("B la firma è l'ultima cosa che il laser scrive", len(sign_ph) == 1 and sign_ph[0]["mm"] > 20
      and p.phases[-1]["kind"] == "sign")
# aroma
ps = plan_of(replace(SMOKY, sear=dict(BEEF.sear, mode="none"), signature=""))
js = C.build_job(ps, PROF)
smoke_ph = [ph for ph in ps.phases if ph["kind"] == "smoke"]
per = 2 * (100 + 12 + 80 + 12)
check("B aroma: due giri sul legno prima di ogni lato (4 giri del rettangolo a 6 mm dal cibo)",
      len(smoke_ph) == 2 and all(near(ph["mm"], 2 * per, 0.5) for ph in smoke_ph)
      and [ph["kind"] for ph in ps.phases][0] == "smoke" and ps.phases[7]["kind"] == "smoke", [ph["mm"] for ph in smoke_ph])
ss = [s for s in burns(js) if s[4] == smax]
check("B …il giro dell'aroma non tocca mai il cibo", all(
    (min(a, c) < 100 - 5.9 or max(a, c) > 200 + 5.9 or min(b, d_) < 100 - 5.9 or max(b, d_) > 180 + 5.9) for a, b, c, d_, _s in ss)
      and near(length(ss), 4 * per, 1.0))
check("B …ed è lento (900 mm/min) rispetto alla cottura", any(re.search(r"F900\b", ln) for ln in js.lines))
mv = js.motion_bounds
check("B la testa non esce mai dal piano", mv.left() >= 0 and mv.top() >= 0 and mv.right() <= BED[0] and mv.bottom() <= BED[1])

# ---------------------------------------------------------------------- sul simulatore: si ferma per girare
if UI == "classica":
    from freelasercut.grbl import SIM_PORT, GrblController

    ctl = GrblController()
    ctl.connect_port(SIM_PORT)
    spin(2.5)
    ctl.home()
    t_ = time.time()
    while not ctl.homed and time.time() - t_ < 20:
        spin(0.05)
    ctl.sim.speedup = 200
    small = plan_of(replace(BEEF, signature="OK"), polys=C.shape_polys("rect", 20, 20, 30, 20), passes=2)
    js = C.build_job(small, PROF)
    paused, done = [], {}
    ctl.user_pause.connect(paused.append)
    ctl.job_finished.connect(lambda ok, msg: done.update(ok=ok, msg=msg))
    errs_ = []
    ctl.error_raised.connect(lambda *e: errs_.append(e))
    ctl.stream_job(js.lines)
    t_ = time.time()
    while not paused and time.time() - t_ < 90:
        spin(0.05)
    spin(0.5)
    check("B simulatore: il lavoro si ferma da solo a metà con «Gira il cibo…», laser spento", len(paused) == 1
          and "Gira" in paused[0] and ctl.user_paused and ctl.job_active and ctl.sim.power == 0, paused)
    check("B simulatore: Riprendi fa ripartire il lato B", ctl.resume_user_pause())
    t_ = time.time()
    while "ok" not in done and time.time() - t_ < 90:
        spin(0.05)
    check("B simulatore: il lavoro finisce senza errori della scheda, laser spento, testa a casa", done.get("ok") is True
          and not errs_ and ctl.sim.power == 0 and [round(v) for v in ctl.last_status["MPos"][:2]] == [0, 0],
          (done, errs_[:1], ctl.last_status.get("MPos")))
    ctl.disconnect_port()
    spin(0.3)

# ====================================================================== C. ricette
keys = [r.key for r in C.builtin()]
check("C 11 ricette incluse con chiavi diverse: carne, pollame, pesce, verdura, pane, formaggio, dolce",
      len(keys) == 11 and len(set(keys)) == 11 and {r.kind for r in C.builtin()} == set(C.KINDS) - {"altro"})
check("C le ricette incluse dicono di non essere state provate su una macchina", not any(r.tested for r in C.builtin()))
check("C all'inizio nessuna ricetta dell'utente", C.load_user() == [] and len(C.library()) == 11)
mine = C.store(replace(BEEF, key="x", name="Fettina di Ale", thickness=4.0, signature="ALE"))
back = C.load_user()
check("C salva fra le mie e rileggi: stessi valori, non più «inclusa»", len(back) == 1 and back[0].key == "fettina_di_ale"
      and back[0].name == "Fettina di Ale" and back[0].thickness == 4.0 and back[0].signature == "ALE"
      and not back[0].builtin and back[0].doneness == BEEF.doneness and back[0].sear == BEEF.sear, back[0].key if back else "")
check("C le mie vengono prima di quelle incluse", C.library()[0].key == mine.key and len(C.library()) == 12)
C.store(replace(mine, thickness=5.0))
check("C stesso nome: sostituita, non doppia", len(C.load_user()) == 1 and C.load_user()[0].thickness == 5.0)
fx = os.path.join(TMP, "scambio", "ricette.flcook")
C.export_recipes(fx, C.load_user() + [C.find("zucchina_fette", True)])
raw = json.load(open(fx, encoding="utf-8"))
check("C esporta: file .flcook leggibile (formato, versione, ricette)", raw["format"] == "flcook" and raw["version"] == 1
      and len(raw["recipes"]) == 2)
imp = C.import_recipes(fx)
check("C importa: le stesse ricette, sempre come ricette dell'utente", [r.key for r in imp] == ["fettina_di_ale", "zucchina_a_fette"]
      and not any(r.builtin for r in imp) and imp[0].thickness == 5.0)
check("C elimina", C.remove(mine.key) == 1 and C.load_user() == [] and C.remove("non_c_e") == 0)
bad = os.path.join(TMP, "rotto.flcook")
errs = 0
for text in ("questo non è json", "[1, 2]", '{"format": "altro", "recipes": []}', '{"format": "flcook", "recipes": []}',
             '{"format": "flcook", "recipes": [{"note": "senza nome"}, 7]}'):
    open(bad, "w", encoding="utf-8").write(text)
    try:
        C.import_recipes(bad)
    except ValueError:
        errs += 1
try:
    C.import_recipes(os.path.join(TMP, "non_esiste.flcook"))
except ValueError:
    errs += 1
check("C file sbagliati (non JSON, altro formato, vuoto, senza ricette leggibili, inesistente): messaggio, mai un errore",
      errs == 6)
open(bad, "w", encoding="utf-8").write(json.dumps({"format": "flcook", "version": 1, "recipes": [
    {"name": "  Strana  ", "kind": "drago", "thickness": 900, "absorb": -3, "efficiency": "boh", "dose_pass": 50,
     "speed": 5, "interval": 0, "doneness": [["a", "Uno", 1000], ["a", "Doppio", 50], "x", ["b", "", "nan"]],
     "default": "zzz", "sear": {"mode": "napalm", "power": 900, "passes": "tre"}, "smoke": "tanto", "signature": "çiao\nmondo",
     "builtin": True, "sconosciuto": 1}]}))
w = C.import_recipes(bad)[0]
check("C valori fuori scala: corretti, non rifiutati", w.name == "Strana" and w.kind == "altro" and w.thickness == 60.0
      and w.absorb == 0.05 and w.efficiency == 0.45 and w.dose_pass == 1.0 and w.speed == C.MIN_SPEED and w.interval == 0.3
      and w.doneness == [("a", "Uno", 250.0)] and w.default == "a" and w.sear["mode"] == "none" and w.sear["power"] == 100.0
      and w.sear["passes"] == 1 and w.smoke["wood"] == "none" and w.signature == "iao mondo" and not w.builtin,
      (w.kind, w.thickness, w.absorb, w.efficiency, w.dose_pass, w.speed, w.interval, w.doneness, w.sear, w.signature))
check("C …e con quei valori il conto non si rompe", isinstance(plan_of(w, thickness=w.thickness).blockers, list))

# ====================================================================== D. finestra
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
win = MainWindow()
win.show()
spin(0.2)
check("D senza codice: Free Laser Cook è nascosto e non si apre", not win.acts["cook"].isVisible() and win.cook_dialog() is None)
pal = getattr(getattr(win, "banco", None), "palette", None)
if pal is not None:
    check("D Banco: senza codice la ricerca dei comandi non lo trova",
          win.acts["cook"] not in (pal.collect(), [a for a, _p in pal.entries])[1])
check("D con il codice compare in Strumenti, con il cappello da chef", win.admin_dialog(code="prova") is True
      and win.acts["cook"].isVisible() and "cook" in win.TOOLS_MENU and not win.acts["cook"].icon().isNull()
      and os.path.exists(os.path.join(ROOT, "freelasercut", "assets", "icons", "chef_hat.svg")))
if pal is not None:
    check("D Banco: con il codice la ricerca lo trova", win.acts["cook"] in (pal.collect(), [a for a, _p in pal.entries])[1])
check("D scheda nella guida «?»", help_texts.lookup("cook") is not None and "fornello" in help_texts.lookup("cook")[1])
dlg = win.cook_dialog()
spin(0.1)
check("D la finestra si apre una volta sola, sulla fettina di manzo", dlg is not None and win.cook_dialog() is dlg
      and dlg.base().key == "manzo_fettina" and dlg.recipe_box.count() == 11)
check("D avviso in testa: il laser non è un fornello", "fornello" in dlg.banner.text())
scr = dlg.screen().availableGeometry()
check("D la finestra sta nello schermo", dlg.width() <= max(scr.width(), 1200) and dlg.height() <= max(scr.height(), 800),
      (dlg.width(), dlg.height()))
check("D riepilogo con passate, potenza, tempo e battuta dello chef", "6" in dlg.summary.text() and "mm/min" in dlg.summary.text()
      and dlg.chef.text() and dlg._job is not None)
check("D cinque accortezze da spuntare; «Si cucina!» spento finché ne manca una", len(dlg.checks) == 5
      and not dlg.b_start.isEnabled() and dlg.b_prev.isEnabled() and dlg.b_frame.isEnabled())
got = []
dlg.action.disconnect()
dlg.action.connect(lambda kind, j: got.append((kind, j)))
dlg._emit_job("start")
check("D avvio senza accortezze: non parte", got == [])
for k, cb in list(dlg.checks.items())[:-1]:
    cb.setChecked(True)
check("D quattro su cinque: ancora spento", not dlg.b_start.isEnabled() and dlg.missing_checks() == ["stay"])
dlg.checks["stay"].setChecked(True)
dlg._emit_job("start")
check("D tutte spuntate: parte il lavoro della ricetta", dlg.b_start.isEnabled() and len(got) == 1 and got[0][0] == "start"
      and any("Free Laser Cook" in ln for ln in got[0][1].lines[:1]))
dlg._emit_job("preview")
check("D «Mostra sul piano» manda lo stesso lavoro al flusso normale", got[-1][0] == "preview" and len(got[-1][1].lines) > 1000)
i_ch = next(i for i, r in enumerate(dlg.recipes) if r.key == "pollo_fettina")
dlg.recipe_box.setCurrentIndex(i_ch)
check("D cambio ricetta: valori della ricetta nei campi, avviso del pollame nel riepilogo",
      dlg.temp.value() == 76.0 and dlg.grade.count() == 1 and "74" in dlg.summary.text() and "pollo" in dlg.chef.text().lower(),
      dlg.chef.text())
dlg.temp.setValue(60)
check("D pollo a 60 °C: bloccato, niente lavoro, pulsanti spenti", dlg._job is None and not dlg.b_start.isEnabled()
      and not dlg.b_prev.isEnabled() and "⚠" in dlg.summary.text())
dlg.recipe_box.setCurrentIndex(next(i for i, r in enumerate(dlg.recipes) if r.key == "manzo_fettina"))
dlg.grade.setCurrentIndex(dlg.grade.findData("ben_cotta"))
check("D grado di cottura: cambia la temperatura e le passate", dlg.temp.value() == 70.0 and dlg._plan.passes == 8,
      (dlg.temp.value(), dlg._plan.passes))
t_slow = dlg._plan.seconds
dlg.fast.setChecked(True)
check("D «Cottura rapida»: dose e interlinea rapide nei campi, tempo a meno della metà", dlg.dose.value() == 0.15
      and dlg.interval.value() == 2.0 and dlg._plan.power == 100.0 and dlg._plan.seconds < t_slow * 0.5,
      (dlg.dose.value(), dlg.interval.value(), round(t_slow), round(dlg._plan.seconds)))
dlg.fast.setChecked(False)
check("D …tolta la spunta tornano i valori della ricetta", dlg.dose.value() == 0.10 and dlg.interval.value() == 1.0
      and near(dlg._plan.seconds, t_slow, 1.0))
dlg.passes.setValue(5)
check("D passate per lato a mano", dlg._plan.passes == 5)
dlg.passes.setValue(0)
dlg.x0.setValue(430)
check("D cibo fuori dal piano: bloccato con il motivo", dlg._job is None and "⚠" in dlg.summary.text())
dlg.x0.setValue(100)
dlg.wood.setCurrentIndex(dlg.wood.findData("ciliegio"))
check("D tavoletta di ciliegio: giro dell'aroma nel lavoro e avviso sul legno", dlg._job is not None
      and any(ph["kind"] == "smoke" for ph in dlg._plan.phases) and "MDF" in dlg.summary.text() and dlg.laps.isEnabled())
dlg.sign.setText("ALE")
dlg.thick.setValue(4.0)
saved = dlg.keep("La fettina di Ale")
check("D «Salva fra le mie»: ricetta con ★ in cima, con i valori della finestra", saved is not None
      and dlg.recipe_box.itemText(0).startswith("★ La fettina di Ale") and dlg.base().key == "la_fettina_di_ale"
      and dlg.base().thickness == 4.0 and dlg.base().signature == "ALE" and dlg.base().smoke["wood"] == "ciliegio"
      and dlg.base().entry()[0] == "ben_cotta" and dlg.b_del.isEnabled() and dlg.sign.text() == "ALE")
fo = os.path.join(TMP, "dal_dialogo")
check("D esporta dalla finestra (aggiunge l'estensione) e reimporta", dlg.export_file(fo) == 1 and os.path.exists(fo + ".flcook")
      and dlg.delete() is True and dlg.recipe_box.count() == 11 and dlg.import_file(fo + ".flcook") == 1
      and dlg.base().key == "la_fettina_di_ale" and dlg.recipe_box.count() == 12)
check("D file sbagliato dalla finestra: nessuna ricetta aggiunta", dlg.import_file(bad.replace("rotto", "non_esiste")) == 0
      and dlg.recipe_box.count() == 12)
check("D le ricette incluse non si eliminano", (dlg.recipe_box.setCurrentIndex(3), dlg.b_del.isEnabled(), dlg.delete())[1:]
      == (False, False))
# forma selezionata nel disegno
r = RectShape(60, 40, layer=1)
r.set_transform(QTransform.fromTranslate(200, 150))
win.editor.add([r])
win.editor.select([r])
dlg.shape.setCurrentIndex(dlg.shape.findData("selection"))
bx = dlg._plan.box
check("D «La forma selezionata nel disegno»: si cuoce quella, dov'è", dlg._job is not None and near(bx[2] - bx[0], 60, 0.01)
      and near(bx[3] - bx[1], 40, 0.01) and near(dlg._plan.area, 2400, 1) and not dlg.w.isEnabled(), bx)
win.editor.select([])
dlg.refresh()
check("D …senza selezione: bloccato con il motivo, senza errori", dlg._job is None and "⚠" in dlg.summary.text())
dlg.shape.setCurrentIndex(dlg.shape.findData("ellipse"))
check("D ovale: anteprima del piatto disegnata", dlg._job is not None and not dlg.preview.pixmap().isNull())
dlg._remember()
check("D ricorda ricetta, potenza del laser e posizione", win.qs.value("cook/recipe") == dlg.base().key
      and float(win.qs.value("cook/watts")) == dlg.watts.value())
dlg.close()
spin(0.2)
check("D chiusa: si può riaprire", win._cook_dlg is None and win.cook_dialog() is not None)
win._cook_dlg.close()

# ====================================================================== E. traduzioni delle ricette incluse
miss = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for r in C.builtin():
        for s in [r.name, r.note] + [d[1] for d in r.doneness]:
            if not cat.get(s):
                miss.setdefault(lang, []).append(s)
check("E nomi, note e gradi di cottura delle ricette incluse tradotti in en, es, fr, pt", not miss, miss)
check("E nessun errore nascosto negli eventi della finestra", not hidden, hidden[:1])

win.editor.dirty = False
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
