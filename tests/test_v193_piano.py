# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.3: piano mostrato ruotato di 90° e angolo dell'homing.

MODELLO DEL DATO
- Tre sistemi: il PIANO come si vede (u orizzontale, v in alto, 0..bed_x × 0..bed_y); il TELAIO della macchina (x da
  sinistra, y dal davanti, 0..corsa X × 0..corsa Y: il piano di sempre quando non è ruotato); le coordinate MACCHINA
  del G-code (telaio + verso degli assi + coordinate negative).
- profile.view_rot = quarti di giro antiorari del piano mostrato (0, 1 «a sinistra», 3 «a destra»; 2 non offerto).
- Invarianti: è sempre una rotazione vera (mai uno specchio); un punto del piano e il suo punto macchina si
  ritrovano a vicenda; il G-code di un disegno è lo stesso che uscirebbe dal disegno non ruotato nella stessa
  posizione sulla macchina; il file del progetto e quello del profilo restano nelle coordinate della macchina.
- «Casa» a fine lavoro (coordinate assolute) = l'angolo dello 0 della macchina, non sempre davanti a sinistra.
- Nella configurazione guidata l'angolo indicato adesso vale più di una prova delle frecce fatta prima.

MATRICE DEI CASI
 1 matematica: 4 orientamenti × assi normali/invertiti × coordinate positive/negative/non note
 2 «casa»: 4 angoli dello 0 × coordinate positive/negative × piano ruotato o no; i due casi dei rapporti
 3 profilo: area della macchina nel file, lettura di $130/$131, vecchie versioni, profilo da condividere
 4 G-code: assoluto, dalla testa, dall'origine utente; linea e riempimento; anteprima sul piano; rotativo rifiutato
 5 file del progetto: salva ruotato = coordinate macchina; apri e salva senza toccare = identico; più piani; gruppi
 6 finestra: configurazione guidata (6 passi, avviso, tre scelte), disegno aperto che resta dov'è sulla macchina,
   cronologia azzerata, niente «modificato», frecce, pallino dello 0, telecamera, Importa ruotato, pannello Macchina
 7 rapporti del 13–14/11: angolo scelto ignorato (Falcon A1), testa nell'angolo sbagliato a fine lavoro (K40)
 8 sul simulatore: un lavoro con il piano ruotato brucia dove deve e torna vicino allo 0"""
import io, itertools, json, os, sys, tempfile, time, zipfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import gcode_preview
from freelasercut.core import document as docmod, gcode
from freelasercut.core.document import Document, GroupShape, PathShape, RectShape
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.profile import MachineProfile

BANCO = "banco" in sys.argv[1:]
if BANCO:
    os.environ["FLC_UI"] = "banco"
results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()
def spin(sec):
    e = time.time() + sec
    while time.time() < e:
        app.processEvents(); time.sleep(0.01)

TX, TY = 400.0, 920.0  # la macchina di Brenda: X corto, Y lungo
CONFIGS = list(itertools.product(range(4), (False, True), (False, True), (None, False, True)))


def prof(k=0, ix=False, iy=False, neg=None, tx=TX, ty=TY):
    p = MachineProfile(bed_x=tx, bed_y=ty, invert_x=ix, invert_y=iy, negative_space=neg)
    p.set_view_rot(k)
    return p


# ====================================================================== 1. matematica
bad = []
for k, ix, iy, neg in CONFIGS:
    p = prof(k, ix, iy, neg)
    if p.travel() != (TX, TY) or (p.bed_x, p.bed_y) != ((TY, TX) if k % 2 else (TX, TY)):
        bad.append(("misure", k, ix, iy, neg))
    lo = (-TX, -TY) if neg else (0.0, 0.0)
    for u, v in ((0, 0), (p.bed_x, 0), (0, p.bed_y), (p.bed_x, p.bed_y), (123.25, 77.5)):
        mx, my = p.to_machine(u, v)
        uu, vv = p.to_bed(mx, my)
        if abs(uu - u) > 1e-9 or abs(vv - v) > 1e-9:
            bad.append(("andata e ritorno", k, ix, iy, neg))
        if not (lo[0] - 1e-9 <= mx <= lo[0] + TX + 1e-9 and lo[1] - 1e-9 <= my <= lo[1] + TY + 1e-9):
            bad.append(("fuori dalla corsa", k, ix, iy, neg, u, v))
    a, b, d = p.to_machine(10, 20), p.to_machine(13, 27), p.to_machine_delta(3, 7)
    if abs(b[0] - a[0] - d[0]) > 1e-9 or abs(b[1] - a[1] - d[1]) > 1e-9:
        bad.append(("spostamento", k, ix, iy, neg))
    back = p.from_machine_delta(*d)
    if abs(back[0] - 3) > 1e-9 or abs(back[1] - 7) > 1e-9:
        bad.append(("spostamento al contrario", k, ix, iy, neg))
check("piano ↔ macchina: 48 combinazioni (orientamento, verso degli assi, coordinate), punti dentro la corsa, andata "
      "e ritorno esatti, spostamenti coerenti con i punti", not bad, str(bad[:3]))
dets = []
for k in range(4):
    p = prof(k)
    fx, fy = p.frame_delta(1, 0), p.frame_delta(0, 1)
    dets.append(fx[0] * fy[1] - fx[1] * fy[0])
    px_, py_ = p.plane_delta(1, 0), p.plane_delta(0, 1)
    dets.append(px_[0] * py_[1] - px_[1] * py_[0])
check("è sempre una rotazione vera, mai uno specchio (determinante +1 nei quattro orientamenti)",
      dets == [1] * 8, str(dets))
p = prof(1)
check("ruotato a sinistra (0 davanti a sinistra): lo 0 va in basso a destra, X sale, Y corre da destra a sinistra",
      p.to_bed(0, 0) == (TY, 0.0) and p.from_machine_delta(1, 0) == (0.0, 1.0)
      and tuple(p.from_machine_delta(0, 1)) == (-1.0, 0.0), (p.to_bed(0, 0), p.from_machine_delta(1, 0)))
p = prof(3)
check("ruotato a destra: lo 0 va in alto a sinistra, Y corre da sinistra a destra, X scende",
      p.to_bed(0, 0) == (0.0, TX) and tuple(p.from_machine_delta(0, 1)) == (1.0, 0.0)
      and tuple(p.from_machine_delta(1, 0)) == (0.0, -1.0), p.to_bed(0, 0))
p = prof(0, True, False, True)
q = MachineProfile(bed_x=TX, bed_y=TY, invert_x=True, negative_space=True)
check("piano non ruotato: gli stessi numeri di prima (profilo senza il dato nuovo)",
      all(p.to_machine(u, v) == q.to_machine(u, v) and p.to_bed(u - 500, v - 500) == q.to_bed(u - 500, v - 500)
          for u, v in ((0, 0), (17.3, 801.25), (400, 920))))
p = prof(1); changed = p.set_view_rot(1); same = (p.bed_x, p.bed_y)
check("scegliere lo stesso orientamento non cambia niente; valori strani valgono «non ruotato»",
      changed is False and same == (TY, TX) and prof("x").rot() == 0 and MachineProfile(view_rot=None).rot() == 0
      and MachineProfile(view_rot=5).rot() == 1)
p = prof(1); p.set_view_rot(3); a = (p.bed_x, p.bed_y, p.travel()); p.set_view_rot(0)
check("da sinistra a destra il piano resta largo e basso; tornando a «non ruotato» tornano le misure della macchina",
      a == (TY, TX, (TX, TY)) and (p.bed_x, p.bed_y) == (TX, TY))

# ====================================================================== 2. «casa» a fine lavoro
bad = []
for k, ix, iy, neg in CONFIGS:
    for mask in (None, 0, 1, 2, 3):
        p = prof(k, ix, iy, neg)
        if mask is not None:
            p.raw_settings = {"23": str(mask)}
        hp = p.home_point()
        hm = p.to_machine(*hp)
        if not (0 <= hp[0] <= p.bed_x and 0 <= hp[1] <= p.bed_y):
            bad.append(("fuori", k, ix, iy, neg, mask, hp))
        if not neg:  # coordinate positive o non ancora note: casa è lo 0 della macchina
            want = (10.0, 10.0)
        elif mask is None:  # negative e $23 non letto: come fino alla 0.19.2, davanti a sinistra della macchina
            fx, fy = p.plane_to_frame(*hp)
            if abs(fx - 10) > 1e-9 or abs(fy - 10) > 1e-9:
                bad.append(("negative senza $23", k, ix, iy, mask, (fx, fy)))
            continue
        else:  # negative: homing verso il meno = estremo opposto allo 0, verso il più = lo 0
            want = (TX - 10.0 if mask & 1 else 10.0, TY - 10.0 if mask & 2 else 10.0)
        if abs(abs(hm[0]) - want[0]) > 1e-9 or abs(abs(hm[1]) - want[1]) > 1e-9:
            bad.append((k, ix, iy, neg, mask, hp, hm, want))
check("«casa»: con le coordinate positive è a 10 mm dallo 0 della macchina; con quelle negative segue il verso "
      "dell'homing ($23) e, se non è noto, resta davanti a sinistra come prima (240 combinazioni, sempre dentro il piano)",
      not bad, str(bad[:3]))
b1n = MachineProfile(); b1n.negative_space = True
check("Longer B1 che conta in negativo, $23 non letto: casa resta a 10,10 (com'era)", b1n.home_point() == (10.0, 10.0))
b1n.raw_settings = {"23": "3"}
check("…e con $23=3 letto (homing verso il meno): sempre davanti a sinistra, dove va davvero la testa",
      b1n.home_point() == (10.0, 10.0) and b1n.home_machine() == (-450.0, -440.0))
b1n.raw_settings = {"23": "0"}
check("GRBL classico ($23=0, coordinate negative): casa è lo 0, nell'angolo opposto", b1n.home_point() == (440.0, 430.0))
k40 = MachineProfile(bed_x=300.0, bed_y=200.0, invert_y=True, negative_space=False)
check("K40 del rapporto (0 dietro a sinistra): casa in alto a sinistra sul piano = X10 Y10 per la macchina",
      k40.home_point() == (10.0, 190.0) and k40.to_machine(*k40.home_point()) == (10.0, 10.0), k40.home_point())
check("Longer B1 (0 davanti a sinistra): casa come prima, a 10,10", MachineProfile().home_point() == (10.0, 10.0))
tiny = MachineProfile(bed_x=6.0, bed_y=8.0)
check("piano più piccolo del margine: casa resta dentro", tiny.home_point() == (6.0, 8.0) or
      all(0 <= c <= m for c, m in zip(tiny.home_point(), (6.0, 8.0))), tiny.home_point())

# ====================================================================== 3. profilo
p = prof(3, False, True, False); p.name = "Prova ruotata"
os.makedirs(os.path.dirname(p.path()), exist_ok=True)
path = p.save()
d = json.load(open(path, encoding="utf-8"))
check("nel file del profilo l'area è quella della macchina (400 × 920) e c'è l'orientamento",
      (d["bed_x"], d["bed_y"], d["view_rot"]) == (TX, TY, 3), (d["bed_x"], d["bed_y"], d.get("view_rot")))
q = MachineProfile.load(path)
check("riaperto: piano 920 × 400, corse 400 × 920, stessa conversione",
      (q.bed_x, q.bed_y, q.rot(), q.travel()) == (TY, TX, 3, (TX, TY)) and q.to_machine(100, 50) == p.to_machine(100, 50))
old = {k_: v for k_, v in d.items() if k_ != "view_rot"}
check("una versione precedente (che non conosce il dato) legge l'area giusta della macchina",
      (old["bed_x"], old["bed_y"]) == (TX, TY))
with open(path, "w", encoding="utf-8") as fh:
    json.dump(old, fh)
q = MachineProfile.load(path)
check("profilo salvato da una versione precedente: non ruotato, misure come sono", (q.rot(), q.bed_x, q.bed_y) == (0, TX, TY))
settings = {"130": "410.000", "131": "915.000", "30": "1000", "32": "1", "22": "1"}
q = MachineProfile.from_machine(settings, [], base=prof(1))
check("$130/$131 letti dalla scheda sono corse della macchina: con il piano ruotato il piano diventa 915 × 410",
      q.travel() == (410.0, 915.0) and (q.bed_x, q.bed_y) == (915.0, 410.0), (q.bed_x, q.bed_y))
q = MachineProfile.from_machine({"130": "234500", "131": "915"}, [], base=prof(1))
check("corsa non credibile su un asse: resta quella di prima, l'altra si aggiorna", q.travel() == (TX, 915.0), q.travel())
from freelasercut import profile_share
exp = os.path.join(tempfile.mkdtemp(), "condiviso.json")
profile_share.export_profile(prof(1), exp)
shared = json.load(open(exp, encoding="utf-8"))["profile"]
check("profilo da condividere: area della macchina, senza l'orientamento di chi lo esporta",
      (shared["bed_x"], shared["bed_y"]) == (TX, TY) and "view_rot" not in shared, str(shared.get("view_rot")))
msgs = [m for _lv, m, _fix in prof(1).checks()]
check("i controlli del profilo parlano dell'area della macchina e dicono che il piano è ruotato",
      any("400×920" in m for m in msgs) and any("ruotato" in m for m in msgs), str([m for m in msgs if "mm" in m]))
check("…e con il piano non ruotato non lo dicono", not any("ruotato" in m for m in prof(0).checks_text())
      if hasattr(MachineProfile, "checks_text") else not any("ruotato" in m for _l, m, _f in prof(0).checks()))

# ====================================================================== 4. G-code
def flag(x0=0.0, y0=0.0):
    """Una «F» storta: non ha simmetrie, così uno specchio o un giro sbagliato si vedono."""
    pp = QPainterPath()
    pp.moveTo(0, 0); pp.lineTo(0, 60); pp.lineTo(35, 60); pp.lineTo(35, 50); pp.lineTo(10, 50); pp.lineTo(10, 35)
    pp.lineTo(25, 35); pp.lineTo(25, 25); pp.lineTo(10, 25); pp.lineTo(10, 0); pp.closeSubpath()
    s = PathShape(pp)
    s.apply(QTransform.fromTranslate(x0, y0))
    return s


def frame_doc(mode="line"):
    """Il disegno nel telaio della macchina (com'è nel file)."""
    d = Document()
    s = flag(120.0, 300.0)
    d.add(s)
    r = RectShape(30, 12)
    r.apply(QTransform().rotate(20) * QTransform.fromTranslate(60, 700))
    d.add(r)
    cs = d.layer(1); cs.mode = mode; cs.power_max = 40; cs.speed = 3000
    if mode == "fill":
        cs.interval = 0.5
    return d


def on_plane(d, p):
    """Lo stesso disegno come lo vede chi ha il piano ruotato."""
    to_plane, _ = docmod.plane_transforms(p)
    out = Document()
    for s in d.shapes:
        c = s.clone(new_id=False)
        if to_plane is not None:
            c.apply(to_plane)
        out.add(c)
    for i, cs in d.layers.items():
        out.layers[i] = cs
    return out


def burns(lines, p=None):
    """Tratti bruciati di un G-code, come insieme di coppie di punti (verso ignorato), al centesimo."""
    pv = gcode_preview.parse(list(lines), profile=p)
    out = set()
    for x0, y0, x1, y1, _s, burn, _f in pv.segs:
        if burn:
            a, b = (round(float(x0), 2) + 0.0, round(float(y0), 2) + 0.0), (round(float(x1), 2) + 0.0, round(float(y1), 2) + 0.0)
            out.add((min(a, b), max(a, b)))
    return out


def burn_points(lines, p=None, step=0.25):
    """Punti bruciati campionati lungo i tratti (per confrontare riempimenti fatti con righe in un altro verso)."""
    pv = gcode_preview.parse(list(lines), profile=p)
    pts = []
    for x0, y0, x1, y1, _s, burn, _f in pv.segs:
        if burn:
            n = max(1, int(np.hypot(x1 - x0, y1 - y0) / step))
            for i in range(n + 1):
                pts.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n))
    return np.array(pts)


def last_rapid(lines):
    g0 = [l for l in lines if l.startswith("G0")]
    return g0[-1] if g0 else ""


bad, bad_home, bad_prev, n_seg = [], [], [], 0
for k, ix, iy, neg in CONFIGS:
    if k == 0:
        continue
    ref_p, p = prof(0, ix, iy, neg), prof(k, ix, iy, neg)
    fd = frame_doc()
    ref = gcode.generate(fd, ref_p, gcode.JobOptions(start_from="absolute"))
    job = gcode.generate(on_plane(fd, p), p, gcode.JobOptions(start_from="absolute"))
    a, b = burns(ref.lines), burns(job.lines)
    n_seg = len(a)
    if a != b or not a:
        bad.append((k, ix, iy, neg, len(a), len(b), sorted(a ^ b)[:2]))
    # a fine lavoro: vicino allo 0 della macchina
    lr = last_rapid(job.lines)
    hm = p.to_machine(*p.home_point())
    if not (abs(float(lr.split("X")[1].split()[0]) - hm[0]) < 1e-6 and abs(float(lr.split("Y")[1].split()[0]) - hm[1]) < 1e-6):
        bad_home.append((k, ix, iy, neg, lr, hm))
    if burns(ref.lines) and last_rapid(ref.lines) != lr:  # e il piano ruotato non cambia dove va
        bad_home.append(("diverso dal non ruotato", k, ix, iy, neg, lr, last_rapid(ref.lines)))
    # anteprima riportata sul piano: sta sopra il disegno come si vede
    pv = job.preview
    ox, oy = job.out_to_bed
    bb = on_plane(fd, p).bounds()
    seg = pv.segs[pv.segs[:, 5] > 0]
    if not len(seg):
        bad_prev.append((k, ix, iy, neg, "vuota")); continue
    xs = np.concatenate([seg[:, 0], seg[:, 2]]) + ox
    ys = np.concatenate([seg[:, 1], seg[:, 3]]) + oy
    if max(abs(xs.min() - bb.left()), abs(xs.max() - bb.right()), abs(ys.min() - bb.top()), abs(ys.max() - bb.bottom())) > 0.05:
        bad_prev.append((k, ix, iy, neg, (xs.min(), xs.max(), ys.min(), ys.max()), (bb.left(), bb.right(), bb.top(), bb.bottom())))
check(f"coordinate assolute: il G-code del piano ruotato brucia gli stessi {n_seg} tratti del disegno non ruotato "
      "nella stessa posizione sulla macchina (36 combinazioni)", not bad, str(bad[:2]))
check("…a fine lavoro la testa torna a «casa», nello stesso punto della macchina del lavoro non ruotato", not bad_home, str(bad_home[:2]))
check("…e l'anteprima del lavoro sta sopra il disegno come si vede sul piano", not bad_prev, str(bad_prev[:2]))

bad = []
for mode_start in ("current", "origin"):
    for k, ix, iy, neg in CONFIGS:
        if k == 0:
            continue
        ref_p, p = prof(0, ix, iy, neg), prof(k, ix, iy, neg)
        fd = frame_doc()
        head_frame = (150.0, 400.0)  # la testa (o l'origine utente) nello stesso punto della macchina
        head_plane = p.frame_to_plane(*head_frame)
        for anchor_ref in (4,):  # il centro è lo stesso punto in tutti gli orientamenti
            kw = dict(start_from=mode_start, anchor=anchor_ref)
            ref = gcode.generate(fd, ref_p, gcode.JobOptions(current_pos=head_frame, work_origin=head_frame, **kw))
            job = gcode.generate(on_plane(fd, p), p, gcode.JobOptions(current_pos=head_plane, work_origin=head_plane, **kw))
            if burns(ref.lines) != burns(job.lines) or not burns(job.lines):
                bad.append((mode_start, k, ix, iy, neg))
            ox, oy = job.out_to_bed
            if abs(ox - head_plane[0]) > 1e-6 or abs(oy - head_plane[1]) > 1e-6:
                bad.append(("anteprima", mode_start, k, ix, iy, neg, job.out_to_bed, head_plane))
check("partenza dalla testa e dall'origine utente: stessi tratti rispetto al punto di partenza, anteprima sul punto "
      "(72 combinazioni)", not bad, str(bad[:2]))

# riempimento: le righe seguono lo schermo (asse lungo della macchina), ma la zona bruciata è la stessa
p0, p1 = prof(0), prof(1)
fd = frame_doc("fill")
ref = burn_points(gcode.generate(fd, p0, gcode.JobOptions()).lines)
job_fill = gcode.generate(on_plane(fd, p1), p1, gcode.JobOptions())
got = burn_points(job_fill.lines)
def grid(pts, cell=0.5):
    g_ = np.zeros((int(TX / cell) + 8, int(TY / cell) + 8), dtype=bool)
    g_[(pts[:, 0] / cell).astype(int) + 2, (pts[:, 1] / cell).astype(int) + 2] = True
    return g_
def grow(g_, n=2):
    out = g_.copy()
    for dx in range(-n, n + 1):
        for dy in range(-n, n + 1):
            out |= np.roll(np.roll(g_, dx, 0), dy, 1)
    return out
ga, gb = grid(ref), grid(got)
miss_a, miss_b = int((ga & ~grow(gb)).sum()), int((gb & ~grow(ga)).sum())
check("riempimento con il piano ruotato: brucia la stessa zona della macchina (entro 1 mm, cioè due righe)",
      ga.sum() > 2000 and miss_a == 0 and miss_b == 0, (int(ga.sum()), int(gb.sum()), miss_a, miss_b))
pvf = gcode_preview.parse(list(job_fill.lines))
segf = pvf.segs[pvf.segs[:, 5] > 0]
along_y = np.abs(segf[:, 3] - segf[:, 1]).sum(); along_x = np.abs(segf[:, 2] - segf[:, 0]).sum()
check("…con le righe lungo l'asse Y della macchina (seguono lo schermo), come dice la configurazione",
      along_y > 20 * max(along_x, 1e-9), (round(along_x, 1), round(along_y, 1)))
fd.layer(1).angle = 90.0
job90 = gcode.generate(on_plane(fd, p1), p1, gcode.JobOptions())
pv9 = gcode_preview.parse(list(job90.lines)); s9 = pv9.segs[pv9.segs[:, 5] > 0]
check("…e con «Angolo di scansione» a 90° tornano lungo l'asse X",
      np.abs(s9[:, 2] - s9[:, 0]).sum() > 20 * max(np.abs(s9[:, 3] - s9[:, 1]).sum(), 1e-9))
rot_opts = gcode.JobOptions(rotary={"kind": "roller", "mm_per_rev": 100.0, "roller_d": 30.0, "object_d": 60.0})
jr = gcode.generate(on_plane(frame_doc(), p1), p1, rot_opts)
jn = gcode.generate(on_plane(frame_doc(), p1), p1, gcode.JobOptions())
check("rotativo con il piano ruotato: rifiutato con un avviso, il lavoro esce senza scalare niente",
      any("rotativo" in w_.lower() for w_ in jr.warnings) and burns(jr.lines) == burns(jn.lines) and jr.rotary_k == 1.0,
      str(jr.warnings[:1]))
jr0 = gcode.generate(frame_doc(), p0, rot_opts)
check("…con il piano non ruotato il rotativo lavora come prima", jr0.rotary_k != 1.0 and
      not any("non si può" in w_ for w_ in jr0.warnings))
# K40 del rapporto: fine lavoro
dk = Document(); r = RectShape(40, 20); r.apply(QTransform.fromTranslate(100, 100)); dk.add(r)
cs = dk.layer(1); cs.mode = "line"; cs.power_max = 30; cs.speed = 2000
jk = gcode.generate(dk, k40, gcode.JobOptions(start_from="absolute"))
check("K40 (rapporto del 13/11): a fine lavoro «G0 X10 Y10», non più «G0 X10 Y190»",
      "X10" in last_rapid(jk.lines) and "Y10" in last_rapid(jk.lines) and "Y190" not in last_rapid(jk.lines), last_rapid(jk.lines))
jb = gcode.generate(dk, MachineProfile(), gcode.JobOptions(start_from="absolute"))
check("Longer B1: fine lavoro com'era (X10 Y10)", "X10" in last_rapid(jb.lines) and "Y10" in last_rapid(jb.lines))
# anteprima di un file G-code esterno
pv = gcode_preview.parse(["G21 G90", "M4", "G0 X0 Y0", "G1 X30 Y0 S500 F600", "G1 X30 Y10", "M5"])
gcode.unmap_preview(pv, prof(1))
sg = pv.segs[pv.segs[:, 5] > 0]
check("anteprima di un file G-code esterno con il piano ruotato a sinistra: X della macchina va verso l'alto",
      np.allclose(sg[0, :4], (0, 0, 0, 30)) and np.allclose(sg[1, :4], (0, 30, -10, 30)) and
      (pv.min_x, pv.max_x, pv.min_y, pv.max_y) == (-10.0, 0.0, 0.0, 30.0), str(sg[:, :4].tolist()))
pv = gcode_preview.parse(["G21 G90", "M4", "G0 X0 Y0", "G1 X30 Y0 S500 F600", "M5"])
gcode.unmap_preview(pv, prof(0, True, False))
check("…e con il piano non ruotato resta il ribaltamento degli assi invertiti di sempre",
      np.allclose(pv.segs[pv.segs[:, 5] > 0][0, :4], (0, 0, -30, 0)))

# ====================================================================== 5. file del progetto
def project_json(path):
    with zipfile.ZipFile(path) as z:
        return z.read("project.json").decode("utf-8")


tmp = tempfile.mkdtemp()
fd = frame_doc()
g = GroupShape([flag(0, 0), RectShape(5, 5)]); g.apply(QTransform().rotate(33.3) * QTransform.fromTranslate(211.123456789, 97.987654321))
fd.add(g)
fd.add_plate("Secondo"); fd.plates[1].shapes.append(flag(33.3333333333, 808.0808080808))
docmod.set_door(None)
f_plain = os.path.join(tmp, "telaio.flcut"); fd.save(f_plain)
plain = project_json(f_plain)
bad = []
for k in (1, 2, 3):
    p = prof(k)
    docmod.set_door(p)
    d = Document.load(f_plain)
    to_plane, to_frame = docmod.plane_transforms(p)
    # ogni forma è dove deve essere sul piano
    for s_file, s_now in zip(fd.all_shapes(), d.all_shapes()):
        c0 = s_file.bounds().center(); c1 = s_now.bounds().center()
        exp = p.frame_to_plane(c0.x(), c0.y())
        if abs(exp[0] - c1.x()) > 1e-6 or abs(exp[1] - c1.y()) > 1e-6:
            bad.append(("posizione", k, exp, (c1.x(), c1.y())))
    f2 = os.path.join(tmp, f"ruotato{k}.flcut"); d.save(f2)
    if project_json(f2) != plain:
        bad.append(("apri e salva", k))
    # tocco una forma sola: cambia solo lei, e resta nelle coordinate della macchina
    d.shapes[0].apply(QTransform.fromTranslate(5.0, 0.0))
    f3 = os.path.join(tmp, f"toccato{k}.flcut"); d.save(f3)
    j0, j3 = json.loads(plain), json.loads(project_json(f3))
    if j3["shapes"][1:] != j0["shapes"][1:] or j3["plates"] != j0["plates"]:
        bad.append(("toccata una, cambiate altre", k))
    moved = np.array(j3["shapes"][0]["tf"][6:8]) - np.array(j0["shapes"][0]["tf"][6:8])
    want = p.frame_delta(5.0, 0.0)
    if not np.allclose(moved, want, atol=1e-9):
        bad.append(("spostamento nel file", k, moved.tolist(), want))
    if any(str(v) == "-0.0" for s_ in j3["shapes"] for v in s_["tf"]):
        bad.append(("-0.0 nel file", k))
    # salvato dal piano ruotato, riaperto non ruotato: il disegno è quello della macchina
    docmod.set_door(None)
    d0 = Document.load(f3)
    c = d0.shapes[0].bounds().center(); c_exp = fd.shapes[0].bounds().center()
    if abs(c.x() - (c_exp.x() + want[0])) > 1e-6 or abs(c.y() - (c_exp.y() + want[1])) > 1e-6:
        bad.append(("riaperto non ruotato", k))
check("file del progetto: aperto con il piano ruotato ogni forma (anche gruppi e secondo piano) è al suo posto; "
      "apri e salva senza toccare = project.json identico; toccandone una cambia solo lei, in coordinate macchina",
      not bad, str(bad[:3]))
docmod.set_door(None)
d = Document.load(f_plain); f4 = os.path.join(tmp, "liscio.flcut"); d.save(f4)
check("piano non ruotato: il file si salva esattamente come prima", project_json(f4) == plain)
p = prof(1); docmod.set_door(p)
d = Document(); r = RectShape(30, 10); r.apply(QTransform.fromTranslate(700.0, 50.0)); d.add(r)
f5 = os.path.join(tmp, "nuovo.flcut"); d.save(f5)
docmod.set_door(None)
d0 = Document.load(f5); b = d0.shapes[0].bounds()
check("disegno nuovo fatto sul piano ruotato a sinistra (30 × 10 in orizzontale a 700,50): nel file è 10 × 30, "
      "in verticale, dove il laser lo incide", abs(b.width() - 10) < 1e-6 and abs(b.height() - 30) < 1e-6 and
      np.allclose((b.center().x(), b.center().y()), p.plane_to_frame(715.0, 55.0)), (b.left(), b.top(), b.width(), b.height()))
for k in (1, 3):
    tp, tfm = docmod.plane_transforms(prof(k))
    q_ = prof(k)
    pt = tp.map(QPointF(123.0, 456.0)); bk = tfm.map(pt)
    if not (np.allclose((pt.x(), pt.y()), q_.frame_to_plane(123.0, 456.0)) and np.allclose((bk.x(), bk.y()), (123.0, 456.0))
            and abs(tp.determinant() - 1.0) < 1e-12):
        check(f"la porta del file usa la stessa rotazione del profilo (k={k})", False); break
else:
    check("la porta del file usa la stessa rotazione del profilo, ed è una rotazione vera", True)
check("piano non ruotato: nessuna porta (il file non viene toccato)", docmod.plane_transforms(prof(0)) == (None, None)
      and docmod.plane_transforms(None) == (None, None))

# ====================================================================== 6–7. finestra principale
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs_setup import PlanePreview, SetupWizard
from freelasercut import camera_calib
w = MainWindow()
tag = "[banco] " if BANCO else ""
w.profile.bed_x, w.profile.bed_y = 450.0, 440.0
w.plane_changed()
check(tag + "all'avvio: piano non ruotato, pallino dello 0 in basso a sinistra, nessuna freccia degli assi",
      w.canvas.plane_rot == 0 and w.canvas.machine_zero == (0.0, 0.0) and w.ctl.axis_rot == 0)
r = RectShape(60, 20); r.apply(QTransform.fromTranslate(100.0, 300.0))
w.editor.add([r], "prova")
rid = r.id
mach_before = w.profile.to_machine(130.0, 310.0)  # il centro del rettangolo, sulla macchina
w.editor.dirty = False
d = SetupWizard(w)
check(tag + "configurazione guidata: 6 passi; il quarto chiede come vedere il piano, con «Non ruotato (consigliato)» scelto",
      d.stack.count() == 6 and d.rot_choice() == 0 and set(d.rot_radio) == {0, 1, 3})
d.go(3)
texts = " ".join(l.text() for l in d.stack.widget(3).findChildren(type(d.rot_lab)))
check(tag + "…con l'avviso voluto: di norma non serve, solo per macchine con un lato molto più lungo, cambia solo come si vede",
      "Di norma non serve ruotare il piano" in texts and "lato molto più lungo" in texts and
      "assi, punto zero e file restano quelli della macchina" in texts)
check(tag + "…e le note: righe dei riempimenti, rotativo, cronologia", "Angolo di scansione" in texts and "rotativo" in texts
      and "Annulla" in texts)
g1 = d.rot_prev[1].geometry_now(); g3 = d.rot_prev[3].geometry_now(); g0 = d.rot_prev[0].geometry_now()
check(tag + "i tre disegnini: non ruotato 0 in basso a sinistra; a sinistra 0 in basso a destra con X che sale; a destra 0 "
      "in alto a sinistra con Y verso destra",
      abs(g0[1].x() - g0[0].left()) < 1 and abs(g0[1].y() - g0[0].bottom()) < 1 and
      abs(g1[1].x() - g1[0].right()) < 1 and abs(g1[1].y() - g1[0].bottom()) < 1 and g1[2].y() < g1[1].y() - 5 and g1[3].x() < g1[1].x() - 5 and
      abs(g3[1].x() - g3[0].left()) < 1 and abs(g3[1].y() - g3[0].top()) < 1 and g3[3].x() > g3[1].x() + 5 and g3[2].y() > g3[1].y() + 5)
d.rot_radio[1].setChecked(True)
check(tag + "scelto «Ruotato a sinistra»: la scritta dice le misure sullo schermo (largo 440, alto 450)",
      "440" in d.rot_lab.text() and "450" in d.rot_lab.text() and d.rot_prev[1].on and not d.rot_prev[0].on, d.rot_lab.text())
d.go(5)
check(tag + "il riepilogo dice «Piano: ruotato a sinistra»", "ruotato a sinistra" in d.summary.text(), d.summary.text()[-60:])
d.accept()
p = w.profile
check(tag + "dopo Fine: profilo ruotato a sinistra, piano 440 × 450 sulla tela, corse 450 × 440",
      p.rot() == 1 and (w.canvas.bed_x, w.canvas.bed_y) == (440.0, 450.0) and p.travel() == (450.0, 440.0))
saved = json.load(open(p.path(), encoding="utf-8"))
check(tag + "nel file del profilo: area della macchina 450 × 440 e orientamento 1",
      (saved["bed_x"], saved["bed_y"], saved["view_rot"]) == (450.0, 440.0, 1))
s = w.editor.doc.find(rid)
c = s.bounds().center()
check(tag + "il rettangolo aperto è rimasto dov'era sulla macchina (stesse coordinate macchina del centro), ora in verticale",
      np.allclose(w.profile.to_machine(c.x(), c.y()), mach_before) and abs(s.bounds().width() - 20) < 1e-6
      and abs(s.bounds().height() - 60) < 1e-6, (c.x(), c.y()))
check(tag + "non è una modifica del progetto: niente «modificato»; la cronologia di Annulla è azzerata",
      w.editor.dirty is False and not w.editor.undo_stack and not w.editor.redo_stack)
check(tag + "pallino dello 0 in basso a destra e frecce degli assi accese",
      w.canvas.plane_rot == 1 and w.canvas.machine_zero == (440.0, 0.0) and
      w.canvas.machine_axes == ((0.0, 1.0), (-1.0, 0.0)), (w.canvas.machine_zero, w.canvas.machine_axes))
ax = {n: (z, t) for n, z, t in w.canvas.machine_axes_view()}
check(tag + "sulla tela: la freccia X sale, la freccia Y va verso sinistra",
      ax["X"][1].y() < ax["X"][0].y() - 20 and abs(ax["X"][1].x() - ax["X"][0].x()) < 1 and
      ax["Y"][1].x() < ax["Y"][0].x() - 20 and abs(ax["Y"][1].y() - ax["Y"][0].y()) < 1)
img = w.canvas.grab()
check(tag + "la tela si ridisegna senza errori con il piano ruotato", not img.isNull() and img.width() > 50)

# salva / riapri con la finestra
fp = os.path.join(tmp, "dalla-finestra.flcut")
w.editor.doc.path = fp; w.editor.doc.save(fp)
j = json.loads(project_json(fp))
check(tag + "salvando dalla finestra il rettangolo è nel file com'era prima di ruotare il piano (60 × 20 a 100,300)",
      np.allclose(j["shapes"][0]["tf"][6:8], (100.0, 300.0)) and np.allclose(j["shapes"][0]["tf"][:2], (1.0, 0.0)), str(j["shapes"][0]["tf"]))
w.editor.dirty = False
w.file_open(fp)
s2 = w.editor.doc.shapes[0]; c2 = s2.bounds().center()
check(tag + "riaprendolo si rivede in verticale nello stesso punto del piano", np.allclose((c2.x(), c2.y()), (c.x(), c.y())))

# progetto .lbrn2: è legato al piatto come un progetto di FreeLaserCut
lb = os.path.join(tmp, "progetto.lbrn2")
with open(lb, "w", encoding="utf-8") as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.4.00" FormatVersion="1" '
             'MaterialHeight="0" MirrorX="False" MirrorY="False">\n<CutSetting type="Cut"><index Value="0"/>'
             '<name Value="C00"/><maxPower Value="20"/><speed Value="100"/></CutSetting>\n'
             '<Shape Type="Rect" CutIndex="0" W="60" H="20" Cr="0"><XForm>1 0 0 1 130 310</XForm></Shape>\n'
             '</LightBurnProject>\n')
from freelasercut.core import lbrn
raw_doc, _warn = lbrn.load(lb)  # com'è nel file: coordinate della macchina
rc_ = raw_doc.shapes[0].bounds()
w.editor.dirty = False
w.file_open(lb)
lb1 = w.editor.doc.shapes[0].bounds()
check(tag + "un progetto .lbrn2 aperto con il piano ruotato si vede girato come il piatto (60 × 20 diventa 20 × 60, "
      "nello stesso punto della macchina)", abs(lb1.width() - rc_.height()) < 1e-6 and abs(lb1.height() - rc_.width()) < 1e-6
      and np.allclose((lb1.center().x(), lb1.center().y()), w.profile.frame_to_plane(rc_.center().x(), rc_.center().y())),
      (lb1.center().x(), lb1.center().y()))
w.import_files([lb])  # progetto non vuoto: le forme si aggiungono, nelle posizioni del progetto
lb2 = w.editor.doc.shapes[-1].bounds()
check(tag + "…e importato in un progetto che ha già qualcosa finisce nello stesso punto",
      len(w.editor.doc.shapes) == 2 and np.allclose((lb2.center().x(), lb2.center().y()), (lb1.center().x(), lb1.center().y())))
w.editor.dirty = False
w.file_open(fp)

# frecce
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected, 5); spin(1.0)
sent.clear(); w.ctl.jog(10.0, 0.0, 1500)
ok1 = until(lambda: any(l.startswith("$J=") for l in sent), 3)
j1 = [l for l in sent if l.startswith("$J=")]
sent.clear(); w.ctl.jog(0.0, 10.0, 1500)
ok2 = until(lambda: any(l.startswith("$J=") for l in sent), 3)
j2 = [l for l in sent if l.startswith("$J=")]
check(tag + "frecce con il piano ruotato a sinistra: «destra» sullo schermo = Y−10 per la macchina, «su» = X+10",
      ok1 and ok2 and "Y-10.000" in j1[0] and "X" not in j1[0].split("G21")[1] and "X10.000" in j2[0]
      and "Y" not in j2[0].split("G21")[1], (j1, j2))
check(tag + "…cioè lo stesso spostamento che dà il profilo", w.profile.to_machine_delta(10.0, 0.0) == (0.0, -10.0)
      and w.profile.to_machine_delta(0.0, 10.0) == (10.0, 0.0))
d = SetupWizard(w)
d.go(1); d.go(2)
sent.clear(); d.jog("right")
ok = until(lambda: any(l.startswith("$J=") for l in sent), 3)
jw = [l for l in sent if l.startswith("$J=")]
check(tag + "nella prova delle frecce della configurazione «destra» è la destra della macchina (X+10), anche con il piano ruotato",
      ok and "X10.000" in jw[0], str(jw))
d.reject()
check(tag + "uscendo con Annulla le frecce del programma tornano a seguire il piano", w.ctl.axis_rot == 1)
spin(0.5)

# testa sul piano
st = {"state": "Idle", "MPos": [30.0, 100.0, 0.0], "WPos": [30.0, 100.0, 0.0]}
w.on_status(st)
hp = w.canvas.head_pos()
check(tag + "la testa a X30 Y100 della macchina si vede a (340, 30) sul piano ruotato a sinistra",
      hp is not None and np.allclose((hp.x(), hp.y()), (340.0, 30.0)), str(hp))

# lavoro dalla finestra
w.laser.start_from.setCurrentIndex(w.laser.start_from.findData("absolute"))
w.build_job()
job = w.job
check(tag + "il lavoro preparato dalla finestra brucia il rettangolo dov'era sulla macchina (100..160 × 300..320)",
      job is not None and (lambda pts: abs(pts[:, 0].min() - 100) < 0.05 and abs(pts[:, 0].max() - 160) < 0.05 and
                           abs(pts[:, 1].min() - 300) < 0.05 and abs(pts[:, 1].max() - 320) < 0.05)(burn_points(job.lines)),
      "" if job is not None else "nessun lavoro")

# pannello Macchina: area = corse
w.machine.refresh_profile()
check(tag + "pannello Macchina: l'area mostrata è quella della macchina (450 × 440), non quella del piano ruotato",
      (w.machine.area_x.value(), w.machine.area_y.value()) == (450.0, 440.0))
c_before = w.editor.doc.shapes[0].bounds().center(); m_before = w.profile.to_machine(c_before.x(), c_before.y())
w.machine.area_y.setValue(430.0); w.machine.set_area()
c_after = w.editor.doc.shapes[0].bounds().center()
check(tag + "cambiando la corsa Y a 430 il piano diventa 430 × 450 e il disegno resta dov'è sulla macchina",
      (w.canvas.bed_x, w.canvas.bed_y) == (430.0, 450.0) and w.profile.travel() == (450.0, 430.0) and
      np.allclose(w.profile.to_machine(c_after.x(), c_after.y()), m_before), (c_after.x(), c_after.y()))

# telecamera: una calibrazione vale per l'orientamento con cui è fatta
check(tag + "la calibrazione della telecamera sa con quale orientamento del piano viene fatta", camera_calib.PLANE_ROT == 1)
cal = os.path.join(tmp, "cam.json")
with open(cal, "w", encoding="utf-8") as fh:
    json.dump({"version": 1, "H": np.eye(3).tolist(), "coef": None, "order": 0, "center": [0, 0], "scale": [1, 1],
               "bed": [450, 440], "frame_size": [640, 480]}, fh)
try:
    camera_calib.CameraModel.load(cal); refused = False
except ValueError:
    refused = True
check(tag + "una calibrazione fatta con il piano non ruotato viene rifiutata con il piano ruotato (va rifatta)", refused)

# Importa ruotato di 90°
svg = os.path.join(tmp, "largo.svg")
with open(svg, "w", encoding="utf-8") as fh:
    fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="20mm" viewBox="0 0 80 20">'
             '<rect x="0" y="0" width="80" height="20" fill="none" stroke="#000"/></svg>')
n0 = len(w.editor.doc.shapes)
w.import_files([svg])
b1 = w.editor.doc.shapes[-1].bounds()
w.import_files([svg], turn=True)
b2 = w.editor.doc.shapes[-1].bounds()
check(tag + "«Importa» mette il disegno dritto come lo vedi (80 × 20); «Importa ruotato di 90°» lo gira (20 × 80), al centro del piano",
      len(w.editor.doc.shapes) == n0 + 2 and abs(b1.width() - 80) < 0.01 and abs(b1.height() - 20) < 0.01 and
      abs(b2.width() - 20) < 0.01 and abs(b2.height() - 80) < 0.01 and
      abs(b2.center().x() - w.profile.bed_x / 2) < 0.01 and abs(b2.center().y() - w.profile.bed_y / 2) < 0.01,
      (b1.width(), b1.height(), b2.width(), b2.height()))
check(tag + "il comando è nel menu File, dopo «Importa», e ha la sua scheda d'aiuto",
      "import_rot" in w.acts and w.acts["import_rot"] in w.m_file.actions() and
      w.m_file.actions().index(w.acts["import_rot"]) == w.m_file.actions().index(w.acts["import"]) + 1)
from freelasercut.ui import help_texts
check(tag + "scheda d'aiuto di «Importa ruotato di 90°»", help_texts.lookup("import_rot") is not None)
check(tag + "verso di «Importa ruotato»: quello del piano mostrato; con il piano non ruotato un quarto di giro a sinistra",
      w.import_turn() == 1)

# torna non ruotato dalla configurazione: tutto come prima
m_now = [w.profile.to_machine(s_.bounds().center().x(), s_.bounds().center().y()) for s_ in w.editor.doc.shapes]
d = SetupWizard(w); d.go(3); d.rot_radio[0].setChecked(True); d.go(5); d.accept()
m_then = [w.profile.to_machine(s_.bounds().center().x(), s_.bounds().center().y()) for s_ in w.editor.doc.shapes]
check(tag + "rimesso «Non ruotato»: piano 450 × 430, disegni fermi sulla macchina, pallino in basso a sinistra, frecce normali",
      w.profile.rot() == 0 and (w.canvas.bed_x, w.canvas.bed_y) == (450.0, 430.0) and np.allclose(m_now, m_then) and
      w.canvas.machine_zero == (0.0, 0.0) and w.canvas.plane_rot == 0 and w.ctl.axis_rot == 0 and w.import_turn() == 1)
check(tag + "…e la calibrazione della telecamera torna a valere per il piano non ruotato", camera_calib.PLANE_ROT == 0)

# durante un lavoro l'orientamento non cambia
w.ctl._job_active = True
d = SetupWizard(w); d.go(3); d.rot_radio[3].setChecked(True); d.go(5); d.accept()
w.ctl._job_active = False
check(tag + "con un lavoro in corso la configurazione non cambia l'orientamento del piano", w.profile.rot() == 0)

# ---- rapporto del 14/11 (Falcon A1): assi già «provati», poi l'utente indica l'angolo dietro a sinistra
p = w.profile
p.invert_x, p.invert_y, p.tested_x, p.tested_y, p.axes_tested, p.origin_corner = False, False, True, True, True, ""
p.negative_space = False
w._sync_axes()
check(tag + "Falcon A1 del rapporto, prima: assi «provati» normali, lo 0 risulta davanti a sinistra", p.corner_now() == "fl")
d = SetupWizard(w)
d.go(1); d.picker.choose("bl")
check(tag + "scelto l'angolo dietro a sinistra: la finestra dice che gli assi lo seguono e che vanno confermati con le frecce",
      "dietro a sinistra" in d.corner_lab.text() and "frecce" in d.corner_lab.text(), d.corner_lab.text())
d.go(2); d.go(3); d.go(5)
check(tag + "…il riepilogo dice «Lo 0 è dietro a sinistra» e Y invertito (fino alla 0.19.2 restava davanti a sinistra)",
      "dietro a sinistra" in d.summary.text() and "da provare" in d.summary.text(), d.summary.text()[:120])
d.accept()
p = w.profile
check(tag + "…dopo Fine: Y invertito, X resta provato, Y torna «da provare», lo 0 è dietro a sinistra",
      (p.invert_x, p.invert_y, p.tested_x, p.tested_y, p.origin_corner) == (False, True, True, False, "bl")
      and p.corner_now() == "bl", (p.invert_x, p.invert_y, p.tested_x, p.tested_y, p.origin_corner))
check(tag + "…e il pallino verde dello 0 è in alto a sinistra sul piano (prima era sempre in basso a sinistra)",
      w.canvas.machine_zero == (0.0, p.bed_y), str(w.canvas.machine_zero))
check(tag + "…«casa» a fine lavoro è lì: in alto a sinistra", p.home_point() == (10.0, p.bed_y - 10.0), str(p.home_point()))
d = SetupWizard(w); d.go(1); d.picker.choose("bl"); d.go(2); d.jog("down"); spin(0.5); d.go(5); d.accept()  # «giù» si allontana dal bordo
p = w.profile
check(tag + "confermato con la freccia: Y provato e invertito, l'angolo resta dietro a sinistra",
      (p.invert_y, p.tested_y) == (True, True) and p.corner_now() == "bl")
d = SetupWizard(w); d.go(1); d.picker.choose("bl"); d.go(5); d.accept()
p = w.profile
check(tag + "indicare di nuovo lo stesso angolo non toglie niente: assi provati come prima",
      (p.invert_x, p.invert_y, p.tested_x, p.tested_y) == (False, True, True, True))
d = SetupWizard(w); d.go(1); d.picker.choose("bl"); d.go(2); d.jog("up"); spin(0.3); d.fix(1); d.go(5); d.accept()
p = w.profile
check(tag + "le frecce fatte dopo hanno l'ultima parola: «correggi» rimette Y normale e lo 0 risulta davanti a sinistra",
      (p.invert_y, p.tested_y) == (False, True) and p.corner_now() == "fl")
d = SetupWizard(w); d.go(1); d.go(2); d.go(3); d.go(5); d.accept()
p = w.profile
check(tag + "Avanti senza toccare niente: assi e prove restano com'erano", (p.invert_x, p.invert_y, p.tested_x, p.tested_y)
      == (False, False, True, True))

w.ctl.disconnect_port()
spin(0.3)
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
docmod.set_door(None)
camera_calib.PLANE_ROT = 0

# ====================================================================== 8. sul simulatore
if not BANCO:
    def run_job(job):
        os.environ["FLC_SIM_NEGATIVE"] = "0"
        c = GrblController(); res = {}
        c.job_finished.connect(lambda ok, m: res.update(ok=ok, msg=m))
        c.error_raised.connect(lambda code, t, l: res.setdefault("err", []).append((code, l)))
        c.connect_port(SIM_PORT); spin(2.0); c.sim.speedup = 40
        c.home(); spin(1.0)
        c.sim.burn_marks.clear()
        c.stream_job(job.lines); t = time.time()
        while "ok" not in res and time.time() - t < 120:
            spin(0.05)
        spin(0.3)
        marks = np.array([c.sim.to_bed(x, y) for x, y in c.sim.burn_marks])
        pos = c.sim.to_bed(*c.sim.pos[:2])
        c.disconnect_port(); spin(0.2)
        return res, marks, pos

    for k, name in ((1, "a sinistra"), (3, "a destra")):
        p = MachineProfile(); p.negative_space = False
        p.set_view_rot(k)
        dd = Document()
        r = RectShape(60, 20)  # largo sullo schermo
        u0, v0 = 200.0, 100.0
        r.apply(QTransform.fromTranslate(u0, v0)); dd.add(r)
        cs = dd.layer(1); cs.mode = "line"; cs.power_max = 50; cs.speed = 3000
        job = gcode.generate(dd, p, gcode.JobOptions(start_from="absolute"))
        res, m, pos = run_job(job)
        corners = [p.plane_to_frame(u, v) for u in (u0, u0 + 60) for v in (v0, v0 + 20)]
        ex = (min(c_[0] for c_ in corners), min(c_[1] for c_ in corners), max(c_[0] for c_ in corners), max(c_[1] for c_ in corners))
        got = (m[:, 0].min(), m[:, 1].min(), m[:, 0].max(), m[:, 1].max()) if len(m) else None
        check(f"simulatore, piano ruotato {name}: il rettangolo largo 60 × 20 sullo schermo viene bruciato alto 60 e "
              "largo 20 nel punto giusto della macchina, senza errori", res.get("ok") and not res.get("err") and got is not None
              and np.allclose(got, ex, atol=0.06), f"{got} atteso {ex}")
        check(f"…e a fine lavoro la testa è a 10 mm dallo 0 della macchina", np.allclose(pos, (10.0, 10.0), atol=0.05), str(pos))

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
