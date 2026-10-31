# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
import sys, os, time, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile; os.environ['APPDATA'] = tempfile.mkdtemp()
# su Windows la piattaforma 'offscreen' non vede i font di sistema: il testo 'O8' uscirebbe vuoto (nessuna finestra viene aperta)
os.environ['QT_QPA_PLATFORM'] = 'windows' if sys.platform == 'win32' else 'offscreen'
import numpy as np
from PySide6.QtGui import QGuiApplication, QTransform
from PIL import Image
app = QGuiApplication([])
from freelasercut.core.document import Document, RectShape, EllipseShape, TextShape, ImageShape, PolygonShape
from freelasercut.core import gcode
from freelasercut.grbl import GrblController, SIM_PORT
from freelasercut.profile import MachineProfile
R = []
def check(name, ok, info=''):
    R.append(ok); print(('  OK  ' if ok else '  KO  ') + name, info)
def spin(sec):
    t=time.time()
    while time.time()-t<sec: app.processEvents(); time.sleep(0.01)

def run_job(job, negative=False, prep=None):
    os.environ['FLC_SIM_NEGATIVE'] = '1' if negative else '0'
    c = GrblController(); res = {}
    c.job_finished.connect(lambda ok, m: res.update(ok=ok, msg=m))
    c.error_raised.connect(lambda code, t, l: res.setdefault('err', []).append((code, l)))
    c.connect_port(SIM_PORT); spin(2.0); c.sim.speedup = 40
    c.home(); spin(1.0 if not negative else 8)
    if prep: prep(c); spin(1.5)
    c.sim.burn_marks.clear()
    c.stream_job(job.lines); t = time.time()
    while 'ok' not in res and time.time()-t < 120: spin(0.05)
    spin(0.3)
    marks = [c.sim.to_bed(x, y) for x, y in c.sim.burn_marks]
    pos = c.sim.to_bed(*c.sim.pos[:2])
    c.disconnect_port(); spin(0.2)
    return res, np.array(marks) if marks else np.zeros((0,2)), pos

def box(m):
    return m[:,0].min(), m[:,1].min(), m[:,0].max(), m[:,1].max()

for negative in (False, True):
    tag = ' [coord. negative]' if negative else ''
    prof = MachineProfile(); prof.negative_space = negative
    doc = Document(); r = RectShape(40, 20); r.apply(QTransform.fromTranslate(100, 100)); doc.add(r)
    cs = doc.layer(1); cs.mode = 'line'; cs.power_max = 50; cs.speed = 3000
    job = gcode.generate(doc, prof, gcode.JobOptions(start_from='absolute'))
    res, m, pos = run_job(job, negative)
    b = box(m)
    check('linea, assoluto: rettangolo 40×20 a (100,100)' + tag, res.get('ok') and not res.get('err') and np.allclose(b, (100,100,140,120), atol=0.05), f'{np.round(b,2)}  fine a {np.round(pos,1)}')
    check('fine lavoro vicino a casa, lontano dai finecorsa (10,10)' + tag, math.dist(pos, (10,10)) < 0.05)
    # origine utente
    def set_origin(c):
        mx, my = prof.to_machine(200, 150); c.goto_machine(mx, my, 20000); spin(1.0); c.set_work_origin()
    job = gcode.generate(doc, prof, gcode.JobOptions(start_from='origin', anchor=0, work_origin=(200,150)))
    res, m, pos = run_job(job, negative, set_origin)
    b = box(m)
    check('linea, origine utente (200,150) ancoraggio basso-sinistra' + tag, res.get('ok') and np.allclose(b, (200,150,240,170), atol=0.05), f'{np.round(b,2)}')
    # posizione attuale, ancoraggio centro
    def goto_cur(c):
        mx, my = prof.to_machine(60, 70); c.goto_machine(mx, my, 20000)
    job = gcode.generate(doc, prof, gcode.JobOptions(start_from='current', anchor=4, current_pos=(60,70)))
    res, m, pos = run_job(job, negative, goto_cur)
    b = box(m)
    check('linea, posizione attuale (60,70) ancoraggio centro' + tag, res.get('ok') and np.allclose(b, (40,60,80,80), atol=0.05), f'{np.round(b,2)}  fine a {np.round(pos,1)}')

prof = MachineProfile()
# riempimento con overscan vicino al bordo: nessun movimento fuori dal piano
doc = Document(); r = RectShape(10, 10); r.apply(QTransform.fromTranslate(0.5, 0.5)); doc.add(r)
cs = doc.layer(1); cs.mode = 'fill'; cs.interval = 0.5; cs.overscan = 5; cs.power_max = 40; cs.speed = 6000
job = gcode.generate(doc, prof)
mb = job.motion_bounds
check('riempimento: overscan tagliato al bordo del piano', mb.left() >= -1e-6 and mb.top() >= -1e-6 and not job.warnings, f'movimento da X{mb.left():.2f} Y{mb.top():.2f}')
res, m, pos = run_job(job)
check('riempimento 10×10 passo 0,5: 20 righe dentro il quadrato', res.get('ok') and np.allclose(box(m), (0.5,0.75,10.5,10.25), atol=0.06) and len(set(np.round(m[:,1],3))) == 20, f'{np.round(box(m),2)} righe {len(set(np.round(m[:,1],3)))}')
# riempimento ruotato e crosshatch su cerchio
doc = Document(); e = EllipseShape(30, 30); e.apply(QTransform.fromTranslate(200, 200)); doc.add(e)
cs = doc.layer(1); cs.mode='fill'; cs.interval=1.0; cs.angle=30; cs.crosshatch=True; cs.power_max=40; cs.speed=6000
job = gcode.generate(doc, prof); res, m, _ = run_job(job)
d = np.hypot(m[:,0]-215, m[:,1]-215)
check('riempimento a 30° + crosshatch su cerchio Ø30: tutto dentro', res.get('ok') and d.max() <= 15.05, f'raggio max {d.max():.2f} mm, punti {len(m)}')
# kerf
doc = Document(); r = RectShape(20, 20); r.apply(QTransform.fromTranslate(100, 100)); doc.add(r)
cs = doc.layer(1); cs.mode='line'; cs.kerf=0.2; cs.power_max=50
job = gcode.generate(doc, prof); res, m, _ = run_job(job)
check('kerf 0,2 mm: contorno esterno allargato di 0,1 mm', np.allclose(box(m), (99.9,99.9,120.1,120.1), atol=0.02), f'{np.round(box(m),3)}')
# fori prima dei contorni (testo con buchi: "O")
doc = Document(); t = TextShape('O8', 'Arial' if sys.platform == 'win32' else 'DejaVu Sans', 20); t.apply(QTransform.fromTranslate(50, 50)); doc.add(t)
doc.layer(1).mode='line'
job = gcode.generate(doc, prof)
from freelasercut.core import geom
from freelasercut.core.gcode import order_polys
polys = geom.flatten(t.path())
ordered = order_polys(polys)
idx_in = [i for i,p in enumerate(ordered) if any(geom.contains(o, p) for o in ordered if o is not p)]
idx_out = [i for i,p in enumerate(ordered) if i not in idx_in]
ok = all(any(geom.contains(ordered[o], ordered[i]) for o in idx_out) and i < min(o for o in idx_out if geom.contains(ordered[o], ordered[i])) for i in idx_in)
check('ottimizzazione: i fori di "O8" tagliati prima dei contorni', ok and len(idx_in) == 3, f'{len(ordered)} contorni, {len(idx_in)} fori')
# testo a linea singola + immagine in scala di grigi
doc = Document(); t = TextShape('FLC 2026', 'futural', 8); t.apply(QTransform.fromTranslate(20, 300)); doc.add(t)
grad = Image.fromarray((np.tile(np.linspace(255, 0, 200), (100, 1))).astype(np.uint8))
doc.images['g1'] = grad
im = ImageShape('g1', 40, 20, layer=0); im.apply(QTransform.fromTranslate(100, 300)); doc.add(im)
cs0 = doc.layer(0); cs0.mode='image'; cs0.dither='grayscale'; cs0.dpi=127; cs0.power_max=60; cs0.power_min=0; cs0.speed=6000
doc.layer(1).mode='line'
job = gcode.generate(doc, prof)
S = []
for l in job.lines:
    if 'S' in l and l.startswith(('G1','X')):
        import re
        mm = re.search(r'S([\d.]+)', l); mx = re.search(r'X([\d.]+)', l)
        if mm and mx: S.append((float(mx.group(1)), float(mm.group(1))))
S = np.array([s for s in S if 100 <= s[0] <= 140 and s[1] > 0])
corr = np.corrcoef(S[:,0], S[:,1])[0,1] if len(S) > 10 else 0
check('immagine in grigi: potenza cresce con lo scuro (sfumatura)', corr > 0.95 and S[:,1].max() <= 600.01, f'correlazione {corr:.3f}, S max {S[:,1].max():.0f}')
check('stima tempo e righe', job.seconds > 0, f'{len(job.lines)} righe · {job.seconds:.0f} s · generato in {job.gen_ms:.0f} ms · avvisi {job.warnings}')
res, m, _ = run_job(job)
check('testo linea singola + immagine eseguiti senza errori', res.get('ok') and not res.get('err'), str(res.get('err', ''))[:120])
print(f'\n{sum(R)}/{len(R)} superati')
sys.exit(0 if all(R) else 1)
