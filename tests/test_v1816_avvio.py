# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.16: guardia d'avvio. Due persone hanno scritto che su Windows 10 il programma «non si avvia», e non
restava nessuna traccia: l'avvio è con pythonw.exe (senza finestra di testo) e il registro degli errori si accendeva
solo dopo Qt, l'istanza unica, la schermata d'avvio e le librerie pesanti. La causa non si conosce: qui non si
«corregge Windows 10», si fa in modo che qualsiasi errore d'avvio venga scritto e mostrato.

Il dato: un avvio = una sequenza di fasi (lingua, Qt, applicazione, istanza unica, schermata d'avvio, finestra
principale, apertura) che finisce in uno di questi modi: finestra aperta; errore di Python; crash nativo; un altro
FreeLaserCut già aperto che risponde; uno già aperto che non risponde.

Casi provati:
A la guardia da sola: dove scrive (cartella dei dati, cartella temporanea, vecchia cartella «Freeburn»), che cosa
  scrive (dati di sistema, niente nome utente: stesse regole del rapporto per l'assistenza), che cosa mostra (testo
  fisso inglese + italiano, finestra di sistema solo su Windows e mai nelle prove), i segni degli avvii non finiti,
  il file dei crash aperto una volta sola, niente Qt né numpy caricati, tempo;
B processi veri (python -m freelasercut): avvio normale; Qt che non si carica; errore e crash nativo alla creazione
  dell'applicazione; libreria pesante che non si carica; errore all'apertura della finestra; l'avvio dopo un crash;
C istanza unica: nessuno aperto, uno che risponde, una versione vecchia che non risponde ma chiude, uno che sta
  partendo, uno bloccato (con la finestra principale mai arrivata, o muto del tutto);
D il passo in più nella prova dell'installatore su Windows; le traduzioni.

Non provato qui: Windows 10 vero (le macchine di GitHub non lo sono) e la finestra di sistema vista da una persona.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="flc_avvio_")
os.environ["APPDATA"] = os.path.join(TMP, "dati")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "dati")
os.environ["FLC_SETTINGS_INI"] = os.path.join(TMP, "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.makedirs(os.environ["APPDATA"])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if sys.platform == "win32":  # un crash messo apposta non deve far comparire la finestra «ha smesso di funzionare»
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)  # si eredita dai processi lanciati da qui

from freelasercut import __version__  # noqa: E402
from freelasercut import startup_guard as g  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def fresh_guard():
    g._state.update(stage="avvio", dir=None, fault=None, mark=None, installed=False)


HOME = os.path.expanduser("~")
USER = os.environ.get("USERNAME") or os.environ.get("USER") or ""

# ================================================================== A. la guardia da sola
loaded = subprocess.run(
    [sys.executable, "-c",
     "import sys, time; t = time.perf_counter(); from freelasercut import startup_guard as g; g.install(); "
     "g.stage('lingua'); g.done(); print(round(time.perf_counter() - t, 3)); "
     "print(sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'numpy', 'cv2', 'numba', 'shiboken6')))"],
    cwd=ROOT, capture_output=True, text=True, timeout=60, env=dict(os.environ, APPDATA=os.path.join(TMP, "a0")))
lines = loaded.stdout.split("\n")
check("la guardia usa solo la libreria standard: accenderla non carica Qt, numpy, OpenCV né numba",
      loaded.returncode == 0 and len(lines) > 1 and lines[1].strip() == "[]", (loaded.stdout, loaded.stderr[-300:]))
check("accenderla, segnare una fase e chiuderla costa meno di un secondo e mezzo anche su una macchina carica "
      "(di solito una ventina di millesimi)", loaded.returncode == 0 and float(lines[0]) < 1.5, lines[0])

from freelasercut import profile  # noqa: E402

fresh_guard()
check("la cartella dei registri è la stessa dei dati del programma (profile.config_dir), calcolata senza importarlo",
      os.path.normcase(g.config_base()) == os.path.normcase(profile.config_dir()) == os.path.normcase(g.log_dir()))
blocked = os.path.join(TMP, "non-una-cartella")
with open(blocked, "w") as fh:
    fh.write("x")
old = os.environ["APPDATA"]
os.environ["APPDATA"] = blocked  # un file al posto della cartella: lì non si può scrivere
fresh_guard()
d = g.log_dir()
check("se nella cartella dei dati non si può scrivere, i registri vanno nella cartella temporanea",
      d is not None and os.path.isdir(d) and os.path.normcase(tempfile.gettempdir()) in os.path.normcase(d), d)
os.environ["APPDATA"] = os.path.join(TMP, "vecchi")
os.makedirs(os.path.join(TMP, "vecchi", "Freeburn"))
with open(os.path.join(TMP, "vecchi", "Freeburn", "materiali.json"), "w") as fh:
    fh.write("{}")
fresh_guard()
d = g.log_dir()
check("con i dati delle versioni fino alla 0.5.0 ancora da copiare, la guardia non crea la cartella nuova al posto loro",
      d is not None and not os.path.exists(os.path.join(TMP, "vecchi", "FreeLaserCut")), d)
check("…e la copia dei vecchi dati poi avviene come sempre",
      os.path.exists(os.path.join(profile.config_dir(), "materiali.json")))
os.environ["APPDATA"] = old
fresh_guard()

from freelasercut import diag  # noqa: E402

samples = [f'File "{HOME}{os.sep}AppData{os.sep}x.py", line 3', f"{HOME.replace(os.sep, '/')}/Documenti/a b.svg",
           HOME.upper() + os.sep + "X", "niente da togliere C:\\Programmi\\x", "", None,
           f"C:\\Users\\{USER}\\Desktop\\x.py e /home/{USER}/y" if USER else "senza utente"]
check("i percorsi passano dalle stesse regole del rapporto per l'assistenza (via la cartella e il nome dell'utente)",
      all(g.sanitize(s) == diag.sanitize(s) for s in samples) and HOME not in g.sanitize(samples[0])
      and "~" in g.sanitize(samples[0]), [(g.sanitize(s), diag.sanitize(s)) for s in samples if g.sanitize(s) != diag.sanitize(s)])
g._state["stage"] = "qt"
sl = g.system_lines()
text = "\n".join(sl)
check("in testa a ogni traccia: versione di FreeLaserCut, versione di Python e 32/64 bit, sistema, fase dell'avvio",
      sl[0] == f"FreeLaserCut {__version__}" and re.search(r"^Python \d+\.\d+\.\d+\S* a (32|64) bit", sl[1])
      and any(l.startswith("Sistema: ") for l in sl) and sl[-1] == "Fase dell'avvio: caricamento di Qt (import di PySide6)", sl)
check("…senza dati personali (né la cartella né il nome dell'utente)", HOME not in text and (len(USER) < 3 or USER not in text), text)
if sys.platform == "win32":
    check("…su Windows: nome, versione e numero di build, 32/64 bit del sistema, processore",
          re.search(r"Sistema: Windows .*build \d+", text) and re.search(r"a (32|64) bit \(", text)
          and "Processore: " in text, text)
    check("…senza usare il modulo platform (che su Windows interroga un servizio che può non rispondere)",
          "import platform" not in open(os.path.join(ROOT, "freelasercut", "startup_guard.py"), encoding="utf-8").read()
          .split("def system_lines")[1].split("else:")[0])
path = os.path.join(g.log_dir(), "flc.log")
t = g.error_text(path)
check("il messaggio a schermo: testo fisso in inglese e in italiano, con il percorso del file e l'indirizzo",
      "FreeLaserCut could not start." in t and "FreeLaserCut non è riuscito ad avviarsi." in t and t.count(g.EMAIL) == 2
      and g.EMAIL == "freelasercut@gmail.com" and t.rstrip().endswith(path) and t.index("could not") < t.index("non è riuscito"), t)
src = open(os.path.join(ROOT, "freelasercut", "startup_guard.py"), encoding="utf-8").read()
check("…non passa dalle traduzioni e non usa Qt (deve comparire proprio quando loro non partono)",
      "i18n" not in src.split('"""', 2)[2] and not re.search(r"\btr\(", src) and not re.search(r"^\s*(from|import) PySide6", src, re.M))
t2 = g.error_text(None, "ImportError: DLL load failed")
check("se nemmeno il file si è potuto scrivere il messaggio lo dice, chiede una foto e riporta l'errore",
      "could not be saved" in t2 and "foto" in t2 and "ImportError: DLL load failed" in t2 and g.EMAIL in t2)
t3 = g.previous_text("C:\\cartella")
check("il messaggio dopo un avvio morto di colpo: inglese e italiano, i due file da mandare, la cartella, l'indirizzo",
      "closed unexpectedly" in t3 and "si è chiuso di colpo" in t3 and t3.count("flc_crash.log") == 2 and "C:\\cartella" in t3
      and t3.count(g.EMAIL) == 2)

boxes = []
real_box, real_sys = g._box, g.sys
g._box = lambda text, title="FreeLaserCut": boxes.append(text) or True
fake = types.SimpleNamespace(platform="win32", stderr=None, modules={}, maxsize=sys.maxsize)
g.sys = fake
env_keep = {k: os.environ.pop(k, None) for k in ("FLC_NO_DIALOGS", "QT_QPA_PLATFORM")}
os.environ["FLC_NO_DIALOGS"] = "1"
check("nelle prove non compare nessuna finestra, nemmeno su Windows (resterebbe aperta per sempre)",
      g.quiet() and g.show("ciao") is False and not boxes)
os.environ.pop("FLC_NO_DIALOGS")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
check("…e nemmeno negli avvii «senza schermo» di Qt", g.quiet() and g.show("ciao") is False and not boxes)
os.environ.pop("QT_QPA_PLATFORM")
shown = g.show("testo di prova")
check("su Windows, in un avvio vero, il messaggio compare nella finestra di sistema (e con pythonw, che non ha "
      "un'uscita per gli errori, non inciampa)", shown is True and boxes == ["testo di prova"], (shown, boxes))
g._box = lambda *a, **k: 1 / 0
check("se nemmeno la finestra di sistema si apre, non nasce un altro errore: resta il file", g.show("x") is False)
g.sys = types.SimpleNamespace(platform="linux", stderr=None, modules={})
g._box = lambda text, title="FreeLaserCut": boxes.append(text) or True
check("fuori da Windows niente finestra di sistema: il messaggio va sull'uscita degli errori",
      g.show("y") is False and boxes == ["testo di prova"])
g.sys, g._box = real_sys, real_box
for k, v in env_keep.items():
    if v is not None:
        os.environ[k] = v
if sys.platform == "win32":
    try:
        r = subprocess.run([sys.executable, "-c", "from freelasercut import startup_guard as g; print(g._box('prova: si chiude da sola'))"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30, env=dict(os.environ, FLC_AVVIO_FINESTRA_MS="700"))
        box_ok, box_info = r.returncode == 0 and "True" in r.stdout, (r.returncode, r.stdout, r.stderr[-300:])
    except subprocess.TimeoutExpired:
        box_ok, box_info = False, "la finestra non si è chiusa da sola in 30 secondi"
    check("la finestra di sistema vera di Windows si apre e (nelle prove) si chiude da sola", box_ok, box_info)

try:
    raise ValueError(f"file rotto: {os.path.join(HOME, 'Documenti', 'x.svg')}")
except ValueError:
    et, ev, tb = sys.exc_info()
g._state["stage"] = "finestra"
written = g.write_error(et, ev, tb)
log = read(written or "")
check("un errore viene scritto in flc.log con l'intestazione, i dati di sistema, la fase e la traccia",
      written and os.path.basename(written) == "flc.log" and "errore all'avvio" in log and f"FreeLaserCut {__version__}" in log
      and "Fase dell'avvio: caricamento della finestra principale" in log and "ValueError: file rotto" in log
      and "Traceback" in log, log[-600:])
check("…senza la cartella dell'utente nei percorsi", HOME not in log and "~" in log, log[-300:])
with open(os.path.join(g.log_dir(), "flc_crash.log"), "a", encoding="utf-8") as fh:
    fh.write(f'  File "{os.path.join(HOME, "x", "y.py")}", line 3 in boot\n')
g.scrub()
check("prima di chiedere i registri, il nome utente viene tolto anche dalle righe scritte dal sistema dei crash",
      HOME not in read(os.path.join(g.log_dir(), "flc_crash.log")) and "y.py" in read(os.path.join(g.log_dir(), "flc_crash.log")))

# ---- i segni degli avvii non finiti
d = g.log_dir()
gone = subprocess.Popen([sys.executable, "-c", "pass"])
gone.wait()
alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
now = time.time()


def mark(pid, when, stage="app", ver="0.18.16"):
    with open(os.path.join(d, f"avvio-{pid}.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"{when:.0f}\n{stage}\n{ver}\n")


mark(gone.pid, now - 30, "qt")
check("il segno fresco di un processo che non c'è più non vuol dire «sta partendo»", g.starting_elsewhere() is False)
mark(alive.pid, now - 5, "finestra")
check("un altro FreeLaserCut che sta partendo adesso viene riconosciuto (non è «bloccato»)", g.starting_elsewhere() is True)
dead = g._previous_unfinished(d)
check("un avvio il cui processo non c'è più risulta «non finito», con la fase in cui era; il suo segno viene tolto",
      len(dead) == 1 and dead[0][1] == "qt" and not os.path.exists(os.path.join(d, f"avvio-{gone.pid}.txt")), dead)
check("il segno di un FreeLaserCut che sta partendo adesso resta dov'è", os.path.exists(os.path.join(d, f"avvio-{alive.pid}.txt")))
mark(alive.pid, now - g.STALE_S - 60, "splash")
check("…ma se «parte» da più di un quarto d'ora è un avvio morto (quel numero di processo è di qualcun altro)",
      g.starting_elsewhere() is False and [x[1] for x in g._previous_unfinished(d)] == ["splash"])
mark(alive.pid, now - g.STARTING_S - 30, "splash")
check("…e uno che parte da più di due minuti non conta più come «sta partendo»", g.starting_elsewhere() is False)
alive.kill()
alive.wait()
check("ucciso il processo, il suo avvio risulta non finito", [x[1] for x in g._previous_unfinished(d)] == ["splash"])
check("senza segni non c'è niente da riferire", g._previous_unfinished(d) == [] and g.starting_elsewhere() is False)
with open(os.path.join(d, "avvio-12345678.txt"), "w") as fh:
    fh.write("non sono numeri")
check("un segno rovinato non fa inciampare: viene tolto", len(g._previous_unfinished(d)) == 1 and g._previous_unfinished(d) == [])

# ---- fasi, guasti di prova, file dei crash
os.environ[g.FAULT_ENV] = "splash"
try:
    g.stage("app")
    g.stage("splash")
    raised = False
except RuntimeError as ex:
    raised = "splash" in str(ex)
os.environ.pop(g.FAULT_ENV)
check("FLC_PROVA_GUASTO=<fase> fa nascere l'errore in quella fase e non in un'altra (serve alle prove)", raised and g._state["stage"] == "splash")
check("le fasi dell'avvio sono quelle usate dal programma, ognuna con il suo nome leggibile",
      all(f'stage("{k}")' in read(os.path.join(ROOT, "freelasercut", "__main__.py")) + read(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"))
          for k in ("lingua", "qt", "app", "unica", "splash", "finestra", "apri"))
      and list(g.STAGES)[1:8] == ["lingua", "qt", "app", "unica", "splash", "finestra", "apri"])
fresh_guard()
hook0 = sys.excepthook
g.install()
fh = g._state["fault"]
check("accesa, la guardia prende gli errori non gestiti, apre il registro dei crash e lascia il segno dell'avvio in corso",
      sys.excepthook is g._hook and fh is not None and os.path.basename(fh.name) == "flc_crash.log"
      and os.path.exists(os.path.join(d, f"avvio-{os.getpid()}.txt")))
import faulthandler  # noqa: E402

check("…con il registro dei crash nativi acceso da subito", faulthandler.is_enabled())
check("_install_crash_log riceve lo stesso file già aperto (non lo apre due volte)…",
      g.fault_file(profile.config_dir()) is fh and not fh.closed)
from freelasercut import app as flc_app  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication.instance() or QApplication([])
headers0 = read(fh.name).count("=== avvio")
flc_app._install_crash_log()
check("…lo usa così com'è, senza scrivere una seconda intestazione, e da lì gli errori passano al registro di sempre",
      flc_app._FAULT_FH is fh and read(fh.name).count("=== avvio") == headers0 and sys.excepthook is not g._hook
      and faulthandler.is_enabled())
g.stage("apri")
log0 = read(os.path.join(d, "flc.log"))
try:
    raise RuntimeError("finestra rotta di prova")
except RuntimeError:
    sys.excepthook(*sys.exc_info())
log1 = read(os.path.join(d, "flc.log"))[len(log0):]
check("un errore prima che la finestra compaia, già nel registro di sempre, ha comunque in testa i dati di sistema e la fase",
      "finestra rotta di prova" in log1 and "Fase dell'avvio: apertura della finestra principale" in log1 and "Sistema: " in log1, log1[-400:])
g.done()
log0 = read(os.path.join(d, "flc.log"))
try:
    raise RuntimeError("errore durante l'uso")
except RuntimeError:
    sys.excepthook(*sys.exc_info())
log1 = read(os.path.join(d, "flc.log"))[len(log0):]
check("ad avvio finito il segno non c'è più e gli errori di dopo restano scritti com'erano (senza l'intestazione d'avvio)",
      not os.path.exists(os.path.join(d, f"avvio-{os.getpid()}.txt")) and "errore durante l'uso" in log1 and "Fase dell'avvio" not in log1)
other = os.path.join(TMP, "altrove")
os.makedirs(other)
check("se il registro dei crash era finito nella cartella temporanea, la guardia lo chiude e lascia aprire quello giusto",
      g.fault_file(other) is None and fh.closed and g._state["fault"] is None)
sys.excepthook = hook0
fresh_guard()

# ================================================================== B. processi veri
FAKE_QT = os.path.join(TMP, "finto-qt")
os.makedirs(os.path.join(FAKE_QT, "PySide6"))
with open(os.path.join(FAKE_QT, "PySide6", "__init__.py"), "w") as fh:
    fh.write('raise ImportError("DLL load failed while importing QtCore: Impossibile trovare il modulo specificato.")\n')
FAKE_NP = os.path.join(TMP, "finto-numpy")
os.makedirs(os.path.join(FAKE_NP, "numpy"))
with open(os.path.join(FAKE_NP, "numpy", "__init__.py"), "w") as fh:
    fh.write('raise ImportError("DLL load failed while importing _multiarray_umath: libreria non adatta a questo processore")\n')
N = [0]


WAIT = float(os.environ.get("FLC_PROVA_ATTESA", "90"))  # secondi concessi a ogni avvio (di solito ne bastano 4)


def start(data=None, timeout=WAIT, **extra):
    """Un avvio vero: python -m freelasercut, senza schermo, con una cartella dei dati sua.
    -> (codice d'uscita, uscita, cartella dei registri, secondi)"""
    if data is None:
        N[0] += 1
        data = os.path.join(TMP, f"avvio{N[0]}")
        os.makedirs(data)
    env = dict(os.environ, APPDATA=data, XDG_CONFIG_HOME=data, FLC_SETTINGS_INI=os.path.join(data, "p.ini"),
               QT_QPA_PLATFORM="offscreen", FLC_NO_FIRST_RUN="1", FLC_NO_UPDATE="1", FLC_MULTI="1", FLC_UI="classica",
               FLC_NO_DIALOGS="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONFAULTHANDLER", None)
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-m", "freelasercut"], cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as ex:
        rc, out = "TEMPO SCADUTO", str(ex.stdout or "") + str(ex.stderr or "")
    return rc, out, os.path.join(data, "FreeLaserCut"), time.time() - t0


def marks(folder):
    return [n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.startswith("avvio-")]


# ---- avvio normale
rc, out, folder, took = start(FLC_PROVA_GUASTO="esci")
crash = read(os.path.join(folder, "flc_crash.log"))
OPENED = "FLC: avvio finito, finestra aperta"  # lo scrive la guardia (solo nelle prove) quando la finestra è sullo schermo
check("avvio normale: la finestra si apre e il programma esce con 0", rc == 0 and OPENED in out, (rc, out[-400:]))
check("…senza errori scritti, senza messaggi, senza segni rimasti",
      "errore all'avvio" not in read(os.path.join(folder, "flc.log")) and "could not start" not in out and not marks(folder),
      (read(os.path.join(folder, "flc.log"))[-300:], marks(folder)))
check("…il registro dei crash ha una sola intestazione per avvio (il file è stato aperto una volta sola), con i dati di sistema",
      crash.count("=== avvio") == 1 and f"FreeLaserCut {__version__}" in crash and "Sistema: " in crash and "Fatal" not in crash, crash)
NORMAL = took

# ---- Qt che non si carica
rc, out, folder, took = start(PYTHONPATH=FAKE_QT)
log = read(os.path.join(folder, "flc.log"))
check("Qt che non si carica: il programma esce con un codice diverso da 0, in fretta (nessuna finestra che aspetta)",
      rc not in (0, "TEMPO SCADUTO") and took < 30, (rc, took))
check("…l'errore è scritto in flc.log con versione, Python, sistema e la fase «caricamento di Qt»",
      "errore all'avvio" in log and f"FreeLaserCut {__version__}" in log and re.search(r"Python \d+\.\d+\.\d+\S* a (32|64) bit", log)
      and "Sistema: " in log and "Fase dell'avvio: caricamento di Qt" in log
      and "ImportError: DLL load failed while importing QtCore" in log, log[-700:])
check("…il messaggio (inglese e italiano, con il file e l'indirizzo) è sull'uscita degli errori",
      "FreeLaserCut could not start." in out and "non è riuscito ad avviarsi" in out and "flc.log" in out and g.EMAIL in out, out[-500:])
check("…e non restano segni: l'errore è già stato detto", not marks(folder), marks(folder))
check("…nel file non c'è la cartella dell'utente", HOME not in log or HOME in TMP, log[-300:])

# ---- creazione dell'applicazione: errore di Python
rc, out, folder, took = start(FLC_PROVA_GUASTO="app")
log = read(os.path.join(folder, "flc.log"))
check("errore alla creazione dell'applicazione: codice diverso da 0, scritto con la sua fase e i dati di sistema",
      rc not in (0, "TEMPO SCADUTO") and "Fase dell'avvio: creazione dell'applicazione (QApplication)" in log
      and "Sistema: " in log and "RuntimeError: guasto di prova" in log and took < 30, (rc, log[-400:]))

# ---- creazione dell'applicazione: crash nativo
rc, out, folder, took = start(FLC_PROVA_GUASTO="nativo:app")
crash = read(os.path.join(folder, "flc_crash.log"))
check("crash nativo alla creazione dell'applicazione: il processo muore con un codice diverso da 0, senza finestre che aspettano",
      rc not in (0, "TEMPO SCADUTO") and took < 30, (rc, took))
check("…e nel registro dei crash resta scritto dove (la riga di Python), sotto l'intestazione con i dati di sistema",
      re.search(r"Fatal Python error|Windows fatal exception", crash) and "__main__.py" in crash and "Sistema: " in crash, crash[-600:])
check("…resta il segno dell'avvio non finito, con la fase", len(marks(folder)) == 1 and "app" in read(os.path.join(folder, marks(folder)[0])),
      marks(folder))
data = os.path.dirname(folder)
with open(os.path.join(folder, "flc_crash.log"), "a", encoding="utf-8") as fh:  # come le scrive il sistema dei crash
    fh.write(f'  File "{os.path.join(HOME, "cartella", "modulo_di_prova.py")}", line 3 in boot\n')
rc, out, folder, took = start(data=data, FLC_PROVA_GUASTO="esci")
log = read(os.path.join(folder, "flc.log"))
check("l'avvio dopo se ne accorge: parte normalmente e scrive che quello di prima si è interrotto, con fase e dati di sistema",
      rc == 0 and OPENED in out and "l'avvio precedente" in log and "si è interrotto" in log
      and "Fase dell'avvio: creazione dell'applicazione (QApplication)" in log and "Sistema: " in log, (rc, log[-500:]))
check("…lo dice (inglese e italiano, i due file, la cartella, l'indirizzo) e toglie il segno",
      "closed unexpectedly while starting" in out and "si è chiuso di colpo" in out and g.EMAIL in out and not marks(folder), out[-500:])
crash = read(os.path.join(folder, "flc_crash.log"))
check("…e dal registro dei crash, prima di chiederlo, è sparita la cartella dell'utente (il resto c'è ancora)",
      "modulo_di_prova.py" in crash and os.path.join(HOME, "cartella") not in crash
      and re.search(r"Fatal Python error|Windows fatal exception", crash), crash[-400:])
rc, out, folder, took = start(data=data, FLC_PROVA_GUASTO="esci")
check("un altro avvio ancora: non lo ripete", rc == 0 and OPENED in out and "closed unexpectedly" not in out
      and read(os.path.join(folder, "flc.log")).count("l'avvio precedente") == 1, out[-300:])
if sys.platform != "win32":  # su Windows Qt, in questo caso, apre una sua finestra d'errore che aspetterebbe un clic
    rc, out, folder, took = start(QT_QPA_PLATFORM="piattaforma-che-non-esiste")
    crash = read(os.path.join(folder, "flc_crash.log"))
    check("un crash nativo vero (Qt che non trova la sua parte grafica e fa chiudere il processo): scritto nel registro dei crash",
          rc not in (0, "TEMPO SCADUTO") and "Fatal Python error: Aborted" in crash and "__main__.py" in crash and len(marks(folder)) == 1,
          (rc, crash[-400:]))

# ---- librerie pesanti
rc, out, folder, took = start(PYTHONPATH=FAKE_NP)
log = read(os.path.join(folder, "flc.log"))
check("una libreria pesante che non si carica (numpy): codice diverso da 0, errore scritto con dati di sistema",
      rc not in (0, "TEMPO SCADUTO") and "ImportError: DLL load failed while importing _multiarray_umath" in log
      and "Sistema: " in log and took < 30, (rc, log[-500:]))
stage_np = re.findall(r"Fase dell'avvio: (.*)", log)
check("…con la fase in cui è successo, fra quelle dopo la creazione dell'applicazione",
      stage_np and stage_np[-1] in [g.STAGES[k] for k in ("unica", "splash", "finestra", "apri")], stage_np)
check("…e il messaggio a schermo", "FreeLaserCut could not start." in out and g.EMAIL in out and not marks(folder), out[-300:])
rc, out, folder, took = start(FLC_PROVA_GUASTO="finestra")
log = read(os.path.join(folder, "flc.log"))
check("errore al caricamento della finestra principale: scritto con la sua fase",
      rc not in (0, "TEMPO SCADUTO") and "Fase dell'avvio: caricamento della finestra principale" in log, (rc, log[-300:]))
rc, out, folder, took = start(FLC_PROVA_GUASTO="apri")
log = read(os.path.join(folder, "flc.log"))
check("errore all'apertura della finestra (qui il registro di sempre è già acceso): scritto, con dati di sistema e fase, ed esce",
      rc not in (0, "TEMPO SCADUTO") and "guasto di prova" in log and "Fase dell'avvio: apertura della finestra principale" in log
      and "Sistema: " in log and took < 30, (rc, took, log[-400:]))

# ---- --self-test e tempi
rc0 = subprocess.run([sys.executable, "-c",
                      "import sys; sys.argv = ['x', '--self-test']; import freelasercut.selftest as s; s.run = lambda: print('PROVA DI AVVIO'); "
                      "import freelasercut.__main__ as m; m.boot(); "
                      "print('guardia', m.__dict__.get('guard') is not None or sys.excepthook is not sys.__excepthook__)"],
                     cwd=ROOT, capture_output=True, text=True, timeout=60, env=dict(os.environ, APPDATA=os.path.join(TMP, "st")))
check("--self-test invariato: parte la prova di avvio e la guardia non tocca la cartella dei dati",
      rc0.returncode == 0 and "PROVA DI AVVIO" in rc0.stdout and "guardia False" in rc0.stdout
      and not os.path.exists(os.path.join(TMP, "st", "FreeLaserCut")), (rc0.stdout, rc0.stderr[-300:]))
main_src = read(os.path.join(ROOT, "freelasercut", "__main__.py"))
head = main_src.split("def boot")[0]
check("in testa a __main__.py non c'è più nessun import di Qt: stanno dentro boot(), dopo l'accensione della guardia",
      "PySide6" not in head and main_src.index("guard.install()") < main_src.index("from PySide6"))

# ================================================================== C. istanza unica
from freelasercut import single  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402

import uuid  # noqa: E402

NAME = f"flc-avvio-{os.getpid()}-{uuid.uuid4().hex[:8]}"  # un nome mai usato: un posto rimasto occupato da un'altra corsa falserebbe la prova
_FWD = ("import sys, json; sys.path.insert(0, sys.argv[1]); from PySide6.QtCore import QCoreApplication; a = QCoreApplication([]); "
        "from freelasercut import single; print(single.forward_state([], name=sys.argv[2], reply_ms=int(sys.argv[3])))")


def ask(name, reply_ms=1500, appdata=None):
    """Un secondo avvio vero, mentre questo processo fa girare il «primo»."""
    res = {}

    def run():
        env = dict(os.environ, APPDATA=appdata or os.path.join(TMP, "c"))
        env.pop("FLC_MULTI", None)
        r = subprocess.run([sys.executable, "-c", _FWD, ROOT, name, str(reply_ms)], capture_output=True, text=True, env=env, timeout=60)
        res["out"] = (r.stdout.strip().splitlines() or [r.stderr[-200:]])[-1]

    t = threading.Thread(target=run)
    t.start()
    while t.is_alive():
        qapp.processEvents()
        time.sleep(0.005)
    return res.get("out")


os.environ.pop("FLC_MULTI", None)
t0 = time.time()
check("nessun FreeLaserCut aperto: «none», e subito", single.forward_state([], name=NAME) == "none" and time.time() - t0 < 1.5)
got = []
lst = single.Listener(qapp, name=NAME, on_request=got.append)
check("uno aperto che risponde: «ok» (e la richiesta gli è arrivata)", ask(NAME) == "ok" and got == [[]], got)
check("forward() resta com'era per chi lo usa: vero solo se la richiesta è arrivata", single.forward([], name=NAME + "x") is False)
lst.close()
lst = single.Listener(qapp, name=NAME + "w")  # un primo avvio vero: la finestra non c'è ancora
check("uno che sta partendo (finestra non ancora pronta): risponde «sto partendo», quindi «ok»; la richiesta resta da parte",
      ask(NAME + "w") == "ok" and lst.pending == [[]], lst.pending)
lst.born -= single.STARTING_S + 60
check("uno che «sta partendo» da minuti senza finestra: «stuck» (è rimasto vivo senza finestra)", ask(NAME + "w") == "stuck")
lst.close()
old = QLocalServer()  # una versione fino alla 0.18.15: legge la richiesta, non risponde, chiude
old.listen(NAME + "v")


def old_conn():
    s = old.nextPendingConnection()
    s.readyRead.connect(lambda: (s.readAll(), s.disconnectFromServer()))


old.newConnection.connect(old_conn)
check("una versione vecchia già aperta, che non risponde ma chiude la connessione: «ok» come prima", ask(NAME + "v") == "ok")
old.close()
mute = subprocess.Popen([sys.executable, "-c",
                         "import sys, time; from PySide6.QtCore import QCoreApplication; from PySide6.QtNetwork import QLocalServer; "
                         "a = QCoreApplication([]); s = QLocalServer(); print(s.listen(sys.argv[1]), flush=True); time.sleep(120)",
                         NAME + "m"], stdout=subprocess.PIPE, text=True)
held = mute.stdout.readline().strip()
check("(la prova) il finto FreeLaserCut bloccato tiene davvero il posto", held == "True", held)
t0 = time.time()
r = ask(NAME + "m", 1200)
check("uno che tiene il posto ma non risponde più (bloccato): «stuck», dopo l'attesa della risposta",
      r == "stuck" and 1.0 < time.time() - t0 < 20, (r, time.time() - t0))
cdir = os.path.join(TMP, "c", "FreeLaserCut")
os.makedirs(cdir, exist_ok=True)
with open(os.path.join(cdir, f"avvio-{mute.pid}.txt"), "w") as fh:
    fh.write(f"{time.time():.0f}\nfinestra\n{__version__}\n")
check("…ma se quel FreeLaserCut sta caricando le librerie proprio adesso (segno d'avvio fresco) non è bloccato: «ok»",
      ask(NAME + "m", 1200) == "ok")
rc, out, folder, took = start(FLC_MULTI=None, FLC_PROVA_ISTANZA=NAME + "m", FLC_PROVA_GUASTO="esci",
                              APPDATA=os.path.join(TMP, "c"), XDG_CONFIG_HOME=os.path.join(TMP, "c"))
check("…e allora il secondo avvio vero esce lasciandogli il posto (non apre un'altra finestra)", rc == 0 and OPENED not in out, (rc, out[-300:]))
os.remove(os.path.join(cdir, f"avvio-{mute.pid}.txt"))
check("senza finestre (prove) alla domanda «aprirne un altro?» si risponde sì da soli", single.open_anyway() is True)
rc, out, folder, took = start(FLC_MULTI=None, FLC_PROVA_ISTANZA=NAME + "m", FLC_PROVA_GUASTO="esci")
check("avvio vero con un FreeLaserCut bloccato: prima usciva in silenzio, ora (qui, senza finestre) parte lo stesso",
      rc == 0 and OPENED in out, (rc, took, out[-300:]))
mute.kill()
mute.wait()
boot_src = main_src[main_src.index('guard.stage("unica")'):main_src.index('guard.stage("splash")')]
check("nel programma: con «stuck» si chiede alla persona, e se dice di no si esce",
      'state == "stuck" and not single.open_anyway()' in boot_src and boot_src.index('state == "ok"') < boot_src.index("stuck"))

# ================================================================== D. installatore e traduzioni
yml = read(os.path.join(ROOT, ".github", "workflows", "installatore.yml"))
step = yml[yml.index("Errore d'avvio messo apposta (deve restare scritto)"):yml.index("# ---------------------------------------------------------------- Linux")]
check("la prova dell'installatore su Windows lancia il pythonw.exe installato con un guasto messo apposta e controlla il file",
      "pythonw.exe" in step and "FLC_PROVA_GUASTO: qt" in step and "flc.log" in step and "ExitCode -eq 0" in step
      and "Sistema: Windows" in step and "QT_QPA_PLATFORM: offscreen" in step, step[:300])
check("…senza poter fermare la pubblicazione se inciampa per conto suo", "continue-on-error: true" in step)
keys = ["FreeLaserCut risulta già aperto, ma non risponde.", "Apri un altro FreeLaserCut"]
keys += [k for k in re.findall(r'"((?:[^"\\]|\\.)*)"', read(os.path.join(ROOT, "freelasercut", "single.py"))) if k.startswith("Forse sta facendo")]
single_src = read(os.path.join(ROOT, "freelasercut", "single.py"))
long_key = "".join(json.loads(f'"{p}"') for p in re.findall(r'"((?:[^"\\]|\\.)*)"', single_src[single_src.index("setInformativeText(tr("):single_src.index("yes = box.addButton")]))
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    check(f"traduzioni {lang}: i tre testi della domanda «è già aperto ma non risponde»",
          all(loc.get(k) for k in keys[:2]) and loc.get(long_key) and "FreeLaserCut" in loc[keys[0]] and "pythonw" in loc[long_key],
          [k[:30] for k in keys[:2] + [long_key] if not loc.get(k)])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code_)  # niente pulizie di Qt: qui sono rimasti aperti apposta server e connessioni di prova
