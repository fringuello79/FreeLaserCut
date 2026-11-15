# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.1: rapporto del 15/11/2026 «il software è tutto rallentato» (PC con 4 processori, telecamera USB sempre
aperta, nessun blocco nel registro). Due cose: la telecamera USB che nessuno guarda va a riposo; il registro e il
rapporto dicono quanto e dove la finestra rallenta.

Matrice dei casi (telecamera finta con la coda del driver come le vere: i fotogrammi non letti restano in coda):
1 usata (richieste ogni 0,1 s): legge alla velocità della camera, mai a riposo;
2 nessuna richiesta per più di IDLE_AFTER: a riposo, non legge più;
3 risveglio con «un fotogramma dopo adesso» (calibrazione): mai uno vecchio rimasto in coda; 5 volte di fila;
4 risveglio con after=0 e tempo per aspettare: un fotogramma nuovo; con timeout 0: subito quello che c'è, mai None;
5 frames(3) al risveglio: 3 fotogrammi nuovi, in ordine;
6 la guardia fiamme che chiede ogni 0,4 s: mai a riposo;
7 sorgenti senza riposo (rete, simulata): leggono sempre come prima; close a riposo: il filo finisce;
8 rallentamenti: una finestra ferma 1,2 s si conta e il registro dice dove; scatti brevi no; un blocco lungo resta
  «blocco» una volta sola e non diventa anche «rallentamento»; al massimo SLOW_MAX righe;
9 rapporto: riga «Prestazioni», numero di forme, fotogrammi/s della telecamera e «a riposo».
"""
import io
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut import app as flc_app  # noqa: E402
from freelasercut import camera as cam  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


cam.IDLE_AFTER = 0.6  # più corto per la prova


class FakeUsb(cam._FrameSource):
    """Camera a 30 fotogrammi/s; il driver tiene in coda gli ultimi QUEUE fotogrammi non letti (come MSMF)."""

    IDLE = True
    FPS = 30.0
    QUEUE = 8

    def __init__(self):
        self.t_cam = time.time()
        self.k = 0  # ultimo fotogramma letto
        self.grabs = 0
        super().__init__()

    def _grab(self):
        self.grabs += 1
        step = 1.0 / self.FPS
        k_now = int((time.time() - self.t_cam) / step)  # ultimo fotogramma già ripreso
        if k_now > self.k:  # ripresi e non letti: dalla coda, subito (la coda tiene gli ultimi QUEUE)
            self.k = max(self.k + 1, k_now - self.QUEUE + 1)
            time.sleep(0.004)  # la conversione del fotogramma (cv2 lascia lavorare gli altri fili)
        else:  # aspetto il prossimo
            self.k += 1
            time.sleep(max(0.0, self.t_cam + self.k * step - time.time()))
        return np.full((3, 4), self.t_cam + self.k * step, dtype=np.float64)


def shot_time(f):
    return float(f[0, 0])


# 1. usata
src = FakeUsb()
n0, t0 = src.n_read, time.time()
while time.time() - t0 < 1.0:
    src.get(after=0, timeout=0.05)
    time.sleep(0.1)
rate = (src.n_read - n0) / (time.time() - t0)
check("1 usata: legge alla velocità della camera (circa 30/s), mai a riposo", 22 <= rate <= 35 and not src.idle,
      f"{rate:.1f}/s idle={src.idle}")

# 2. a riposo
time.sleep(cam.IDLE_AFTER + 0.4)
check("2 nessuna richiesta: a riposo", src.idle)
n1 = src.grabs
time.sleep(1.0)
check("2 …e non legge più", src.grabs - n1 == 0, src.grabs - n1)

# 3. risveglio con «dopo adesso»
ok3, worst = True, 0.0
for _ in range(5):
    time.sleep(cam.IDLE_AFTER + 0.3)
    if not src.idle:
        ok3 = False
    t_req = time.time()
    f = src.get(after=t_req, timeout=2.0)
    if f is None or shot_time(f) < t_req:
        ok3 = False
        worst = max(worst, t_req - (shot_time(f) if f is not None else 0))
check("3 risveglio: il fotogramma reso è stato ripreso dopo la richiesta (mai dalla coda), 5 volte", ok3, worst)

# 4. after=0
time.sleep(cam.IDLE_AFTER + 0.3)
t_req = time.time()
f = src.get(after=0, timeout=1.0)
check("4 a riposo, after=0 con tempo per aspettare: fotogramma nuovo", f is not None and shot_time(f) >= t_req,
      None if f is None else t_req - shot_time(f))
check("4 …arrivato presto (meno di 0,3 s)", time.time() - t_req < 0.3, time.time() - t_req)
time.sleep(cam.IDLE_AFTER + 0.3)
t_req = time.time()
f = src.get(after=0, timeout=0)
check("4 a riposo, after=0 con timeout 0: subito quello che c'è, mai None", f is not None and time.time() - t_req < 0.05)
time.sleep(0.25)
check("4 …e la richiesta ha svegliato la lettura", not src.idle and src._t > t_req)

# 5. frames
time.sleep(cam.IDLE_AFTER + 0.3)
t_req = time.time()
fr = src.frames(3, after=t_req)
ts = [shot_time(x) for x in fr]
check("5 frames(3) al risveglio: 3 fotogrammi ripresi dopo la richiesta, in ordine",
      len(ts) == 3 and all(t >= t_req for t in ts) and ts == sorted(ts) and len(set(ts)) == 3, ts)

# 6. guardia fiamme
last_t, misses, idle_seen = 0.0, 0, False
t0 = time.time()
while time.time() - t0 < 3.0:
    f = src.get(after=last_t, timeout=0.0)
    if f is None:
        misses += 1
    else:
        last_t = src._t
    idle_seen |= src.idle
    time.sleep(0.4)
check("6 richieste ogni 0,4 s come la guardia fiamme: mai a riposo, sempre un fotogramma nuovo",
      not idle_seen and misses == 0, (idle_seen, misses))

# 7. sorgenti senza riposo e chiusura
src.close()


class FakeNet(FakeUsb):
    IDLE = False


net = FakeNet()
time.sleep(cam.IDLE_AFTER + 0.6)
g = net.grabs
time.sleep(0.5)
check("7 sorgente senza riposo (rete, simulata): continua a leggere come prima", not net.idle and net.grabs - g >= 10,
      net.grabs - g)
net.close()
check("7 solo le telecamere USB vanno a riposo", cam.CameraSource.IDLE and not cam.NetCamera.IDLE
      and not cam.SimCamera.IDLE)
before = {t.ident for t in threading.enumerate()}
s2 = FakeUsb()
time.sleep(cam.IDLE_AFTER + 0.3)
mine = [t for t in threading.enumerate() if t.ident not in before]
s2.close()
time.sleep(0.3)
check("7 chiusa mentre è a riposo: il filo di lettura finisce subito", mine and not any(t.is_alive() for t in mine))
check("7 fotogrammi/s per il rapporto", 0 <= s2.fps() < 40, s2.fps())

# 8. rallentamenti
fh = io.StringIO()
H = flc_app._HANG
H.update(beat=time.time(), since=0.0, dumped=0, slow_n=0, slow_max=0.0, slow_sum=0.0, slow_logged=0, slow_late=0.0,
         slow_where="", t0=time.time() - 60, cpu0=time.process_time())
for late in (0.1, 0.25, 0.35, 0.2, 0.1):  # scatti normali del controllo
    flc_app._hang_step(late, fh=fh)
check("8 scatti brevi (fino a 0,35 s): niente rallentamenti", H["slow_n"] == 0 and "rallentamento" not in fh.getvalue())


STUCK = """
def stuck_here(sec, seq, step, fh):
    import threading, time
    done = threading.Event()

    def watcher():  # la sorveglianza vera gira in un altro filo mentre la finestra è ferma qui
        for late in seq:
            step(late, fh=fh)
            time.sleep(0.05)
        done.set()

    threading.Thread(target=watcher, daemon=True).start()
    t_end = time.time() + sec
    while time.time() < t_end and not done.is_set():
        sum(range(2000))  # occupato nel filo della finestra
"""
ns = {}
exec(compile(STUCK, os.path.join(tempfile.gettempdir(), "freelasercut", "ui", "finto.py"), "exec"), ns)


ns["stuck_here"](2.0, [0.4, 0.8, 1.1, 1.4], flc_app._hang_step, fh)
flc_app._hang_step(0.1, fh=fh)
txt = fh.getvalue()
check("8 finestra ferma 1,2 s: contata una volta, con la durata", H["slow_n"] == 1 and abs(H["slow_max"] - 1.2) < 0.01,
      (H["slow_n"], H["slow_max"]))
check("8 …il registro dice «rallentamento» e dov'era ferma (file, riga, funzione)",
      "=== rallentamento" in txt and "finto.py:" in txt and "stuck_here" in txt, txt)
check("8 …solo nomi di file, nessun percorso", tempfile.gettempdir() not in txt and "/ui/" not in txt, txt)
fh2 = open(os.path.join(tempfile.mkdtemp(), 'crash.log'), 'w+', encoding='utf-8')
H["beat"] = time.time() - 9.0
flc_app._hang_step(9.0, fh=fh2)
flc_app._hang_step(9.2, fh=fh2)
H["beat"] = time.time()
flc_app._hang_step(0.1, fh=fh2)
fh2.seek(0)
t2 = fh2.read()
check("8 blocco oltre HANG_S: «blocco» una volta sola e «ripresa», non anche «rallentamento»",
      t2.count("=== blocco") == 1 and "=== ripresa" in t2 and "rallentamento" not in t2, t2[:300])
fh3 = io.StringIO()
H["slow_logged"] = 0
for _ in range(flc_app.SLOW_MAX + 5):
    flc_app._hang_step(1.5, fh=fh3)
    flc_app._hang_step(0.1, fh=fh3)
check("8 al massimo SLOW_MAX righe nel registro, ma contati tutti",
      fh3.getvalue().count("=== rallentamento") == flc_app.SLOW_MAX and H["slow_n"] >= flc_app.SLOW_MAX + 5,
      fh3.getvalue().count("=== rallentamento"))
pt = flc_app.perf_text()
check("9 riga Prestazioni: processore, rallentamenti con il più lungo, blocchi, fili",
      pt.startswith("Prestazioni:") and "processore" in pt and "la più lunga" in pt and "blocchi" in pt
      and "fili" in pt, pt)

# 9. rapporto con la finestra vera
from freelasercut import diag  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
for _ in range(5):
    app.processEvents()
for i in range(3):
    w.editor.doc.add(RectShape(10, 10))
fake = FakeUsb()
fake.index, fake.mode, fake.black = 0, "dshow", False
old_src = getattr(w.camera, "src", None)
w.camera.src = fake
time.sleep(cam.IDLE_AFTER + 0.4)
env = diag.env_text(w, "FLC-PROVA")
check("9 rapporto: riga Prestazioni", "Prestazioni:" in env, env)
check("9 rapporto: numero di forme del progetto", "Forme nel progetto: 3" in env, env)
check("9 rapporto: telecamera con fotogrammi/s e «a riposo»", "fotogrammi/s" in env and "a riposo" in env, env)
w.camera.src = old_src
fake.close()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
