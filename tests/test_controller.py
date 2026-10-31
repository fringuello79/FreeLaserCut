# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import tempfile; os.environ['APPDATA']=tempfile.mkdtemp(); os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from freelasercut.grbl import GrblController, SIM_PORT
from freelasercut.core import resume
R=[]
def check(n, ok, info=''):
    R.append(bool(ok)); print(('  OK  ' if ok else '  KO  ')+n, info)
def spin(t):
    e=time.time()+t
    while time.time()<e: app.processEvents(); time.sleep(0.01)
c = GrblController(); got={}
c.check_finished.connect(lambda r: got.__setitem__('check', r))
c.job_error.connect(lambda i,l,code,t: got.setdefault('jerr', []).append((i,l,code)))
c.job_finished.connect(lambda ok,m: got.__setitem__('job', ok))
c.connect_port(SIM_PORT); spin(2.0); c.sim.speedup = 50
good = ['G90 G21','M4 S0'] + [f'G1 X{10+i} Y10 S300 F3000' for i in range(200)] + ['M5']
c.check_job(good); t=time.time()
while 'check' not in got and time.time()-t<30: spin(0.05)
check('verifica $C di un lavoro corretto: nessun errore, nessun movimento', got.get('check')==[] and c.sim.pos[0]==0, f'{got.get("check")}  pos {c.sim.pos[:2]}')
spin(1.0)
bad = list(good); bad.insert(50, 'G99 X5'); bad.insert(120, 'M77')
got.pop('check',None); c.check_job(bad); t=time.time()
while 'check' not in got and time.time()-t<30: spin(0.05)
errs = got.get('check') or []
check('verifica $C trova le 2 righe sbagliate con il numero esatto', [e[0] for e in errs]==[50,120], str([(e[0],e[1],e[2]) for e in errs]))
spin(1.0)
check('dopo la verifica la scheda torna pronta', c.last_status.get('state')=='Idle' and not c.checking, c.last_status.get('state'))
# pausa su errore durante il lavoro
c.stream_job(bad); t=time.time()
while 'jerr' not in got and time.time()-t<30: spin(0.05)
spin(0.5)
check('errore durante il lavoro: pausa immediata con la riga giusta', got.get('jerr',[[None]])[0][0]==50 and c.last_status.get('state')=='Hold', f"{got.get('jerr')} stato {c.last_status.get('state')}")
c.stop_job(); spin(1.0)
# override
c.set_override('feed', 150); c.set_override('power', 70); spin(0.6)
check('override velocità 150% e potenza 70%', c.sim.ov[0]==150 and c.sim.ov[2]==70 and c.last_status.get('ov',[0,0,0])[0]==150, str(c.sim.ov))
c.set_override('feed', 100); c.set_override('power', 100); spin(0.3)
# ripresa
prog = resume.resume_program(good, 120)
st = resume.analyse(good, 120)
check('ripresa: stato ricostruito alla riga 120', st['x']==10+117 and st['laser']=='M4' and st['s']==300, f"x={st['x']} {st['laser']} S{st['s']}")
got.pop('job',None); c.sim.burn_marks.clear(); c.stream_job(prog); t=time.time()
while 'job' not in got and time.time()-t<60: spin(0.05)
xs = [m[0] for m in c.sim.burn_marks]
check('ripresa eseguita: brucia solo dal punto di interruzione in poi', got.get('job') and min(xs) >= 127-1e-6 and abs(max(xs)-209)<1e-6, f'X da {min(xs):.1f} a {max(xs):.1f}')
ok, why = resume.can_resume(['G92 X0 Y0','G1 X1'], 2); check('ripresa rifiutata per lavori a posizione attuale (G92)', not ok)
# fire
c.fire(True, 1.0, timeout_s=0.5); spin(0.3); fired = c.sim.laser and c.sim.s_word==10
spin(0.6)
check('fire all\'1% con spegnimento automatico', fired and not c.fire_active and c.sim.s_word==0, f'acceso={fired} poi S={c.sim.s_word}')
c.disconnect_port(); spin(0.2)
print(f'{sum(R)}/{len(R)} superati')
sys.exit(0 if all(R) else 1)
