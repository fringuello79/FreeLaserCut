# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.4: rapporto per l'assistenza.
- registro della comunicazione con la scheda, salvato da solo su allarme, errore, lavoro interrotto o fermo;
- Aiuto → Crea rapporto per l'assistenza: uno zip con sistema, profilo, $$/$I, registri; niente dati personali."""
import sys, os, time, tempfile, zipfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.exec = lambda self: 0
from freelasercut import diag
from freelasercut.grbl import SIM_PORT
from freelasercut.profile import config_dir
from freelasercut.ui.main_window import MainWindow

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)
def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

# ------------------------------------------------------------------ dati personali tolti
h0 = {k: os.environ.get(k) for k in ("USERPROFILE", "USERNAME")}
os.environ["USERPROFILE"], os.environ["USERNAME"] = r"C:\Users\mario", "mario"
check("percorsi della cartella utente diventano «~» (Windows, maiuscole qualsiasi)",
      diag.sanitize(r"C:\Users\mario\AppData\x.log e c:/users/MARIO/Desktop") == r"~\AppData\x.log e ~/Desktop",
      diag.sanitize(r"C:\Users\mario\AppData\x.log e c:/users/MARIO/Desktop"))
check("il nome utente dentro altri percorsi sparisce", "mario" not in diag.sanitize(r"D:\dati\mario\progetti").lower())
for k, v in h0.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

# ------------------------------------------------------------------ registro della comunicazione
w = MainWindow(); w.resize(1400, 900); w.show(); spin(0.3)
log = w.comm_log
check("registro della comunicazione attivo", isinstance(log, diag.CommLog))
w.ctl.connect_port(SIM_PORT, 115200)
check("simulatore connesso", until(lambda: w.ctl.connected))
w.ctl.request_info(); w.ctl.request_settings()
check("$$ e $I letti e tenuti per il rapporto", until(lambda: log.settings and log.info), (len(log.settings), len(log.info)))
txt = log.text()
check("nel registro: comandi inviati, risposte e cambi di stato", "> $$" in txt and "< " in txt and "= stato" in txt)
d = diag.diag_dir()
before = set(os.listdir(d))
w.ctl.alarm_raised.emit(2, "Limite software")
spin(0.1)
new = set(os.listdir(d)) - before
check("allarme: il registro si salva da solo", any("allarme" in f for f in new), sorted(new))

# lavoro che non avanza con la macchina ferma
msgs = []
log.on_stall = lambda m, p: msgs.append((m, p))
old = diag.STALL_SECONDS
diag.STALL_SECONDS = 0.3
w.ctl._job_active = True; w.ctl._job_total = 120; w.ctl._job_done = 7
log.state = "Idle"; log._progress_t = time.time() - 5; log._stall_noted = False
log._watch()
w.ctl._job_active = False
diag.STALL_SECONDS = old
check("lavoro fermo (nessun avanzamento a macchina ferma): annotato e salvato", msgs and msgs[0][1] and
      "lavoro-fermo" in os.path.basename(msgs[0][1]) and "7/120" in msgs[0][0], msgs[:1])
log.on_stall = w._job_stalled
w._job_stalled("prova", None); spin(0.05)
check("lavoro fermo: avviso nella barra di stato", "Crea rapporto" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
check("i registri salvati restano pochi (ultimi 10)", len([f for f in os.listdir(d) if f.startswith("comunicazione-")]) <= 10)

# ------------------------------------------------------------------ rapporto
home = os.path.expanduser("~")
with open(os.path.join(config_dir(), "flc.log"), "a", encoding="utf-8") as fh:
    fh.write(f"\n=== prova\nTraceback: File \"{home}/progetti/x.py\", line 3\nValueError: prova\n")
out = os.path.join(tempfile.mkdtemp(), "rapporto.zip")
path = w.make_support_report(out)
check("rapporto creato", path == out and os.path.exists(out))
with zipfile.ZipFile(out) as z:
    names = z.namelist()
    body = {n: z.read(n).decode("utf-8", "replace") for n in names}
check("contenuto: sistema, comunicazione, impostazioni GRBL, errori, registri salvati",
      {"sistema.txt", "comunicazione-ora.log", "impostazioni-grbl.txt", "flc.log"} <= set(names)
      and any(n.startswith("diagnostica/") for n in names), names)
s = body["sistema.txt"]
check("sistema.txt: versione, Python, Qt, schermo, librerie e profilo della macchina",
      "FreeLaserCut 0." in s and "Python" in s and "Qt" in s and "Schermo 1" in s and "numpy" in s and "bed_x" in s)
check("impostazioni GRBL nel rapporto", "$30=" in body["impostazioni-grbl.txt"] or "$130=" in body["impostazioni-grbl.txt"])
leak = [n for n, t in body.items() if home in t]
check("nessun percorso personale nel rapporto", not leak and "~/progetti/x.py" in body["flc.log"], leak)
check("nessun progetto o immagine nel rapporto", not any(n.endswith((".flcut", ".png", ".jpg", ".svg")) for n in names))
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8").read()
check("installatore: prepara i file di Python (primo avvio rapido) dopo averli copiati",
      "compileall" in nsi and nsi.index("compileall") > nsi.index('File /r "stage\\app"'))
acts = [a for m in w.menuBar().actions() if m.menu() for a in m.menu().actions()]
check("Aiuto → Crea rapporto per l'assistenza nel menu", w.acts["report"] in acts)

w.ctl.disconnect_port(); w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
