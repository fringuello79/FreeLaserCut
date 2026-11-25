# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.9 (richiesta di Ale): «Apri un'altra finestra», per lavorare su due progetti insieme.

A. il comando: voce nel menu File, scheda dell'aiuto, comando giusto per il processo nuovo (non passa la mano alla
   finestra già aperta, ha la sua sigla, non cerca aggiornamenti), file passati con il percorso intero.
B. la finestra in più: salvataggio automatico suo, non tocca quello della finestra principale, non si collega da sola,
   chiudendola bene il suo salvataggio sparisce.
C. finestre chiuse male: il salvataggio rimasto si riconosce (solo se la finestra non c'è più), si riapre in un'altra
   finestra come «Progetto recuperato» oppure si butta.
D. una finestra vera: si apre un secondo FreeLaserCut, è vivo (il suo salvataggio non è «rimasto»); ucciso, lo diventa.
E. difetti rimessi apposta.

Uso: python tests/test_v229_finestra.py [classica|banco]
"""
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CONF = tempfile.mkdtemp()
os.environ["APPDATA"] = CONF
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
os.environ.pop("FLC_WINDOW", None)
os.environ.pop("FLC_RECOVER", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
ANSWER = {"r": QMessageBox.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER["r"])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import single  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.profile import config_dir  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
DIR = config_dir()


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info != "" and not cond else ""),
          flush=True)


def pump(t=0.2):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def finestra(token=""):
    """Una MainWindow come finestra principale (token vuoto) o come finestra in più."""
    if token:
        os.environ["FLC_WINDOW"] = token
    else:
        os.environ.pop("FLC_WINDOW", None)
    w = mw.MainWindow()
    os.environ.pop("FLC_WINDOW", None)
    return w


def disegna(w):
    w.editor.add([RectShape(20, 10, layer=1)])
    w.editor.dirty = True


# ====================================================================== A. il comando
print("--- A. il comando")
chiamate = []
vera_open = single.open_window


def finta_popen(cmd, **kw):
    chiamate.append((cmd, kw))
    return None


single.open_window = lambda paths=(), recover=False, popen=None: vera_open(paths, recover, popen=finta_popen)
w = finestra()
pump()
a1, a2 = w.acts.get("new_window"), w.acts.get("open_in_window")
check("A le due azioni ci sono, con la spiegazione", a1 is not None and a2 is not None and a1.statusTip() and a2.statusTip())
check("A …nel menu File, dopo «Apri…»", [a for a in w.m_file.actions() if a in (a1, a2)] == [a1, a2]
      and w.m_file.actions().index(a1) == w.m_file.actions().index(w.acts["open"]) + 1)
check("A …con la scheda dell'aiuto", all(help_texts.lookup(k) for k in ("new_window", "open_in_window")))
check("A …e fra le azioni della finestra (nel Banco si trovano dalla ricerca dei comandi)", a1 in w.actions() and a2 in w.actions())
a1.trigger()
cmd, kw = chiamate[-1]
env = kw["env"]
check("A «Apri un'altra finestra» avvia un altro FreeLaserCut (python -m freelasercut), staccato da questo",
      cmd[0] == sys.executable and cmd[1:3] == ["-m", "freelasercut"] and len(cmd) == 3
      and (kw.get("start_new_session") or kw.get("creationflags")), (cmd, sorted(kw)))
check("A …che non passa la mano alla finestra già aperta, ha la sua sigla e non cerca aggiornamenti",
      env.get("FLC_MULTI") == "1" and env.get("FLC_WINDOW", "").isalnum() and env.get("FLC_NO_UPDATE") == "1"
      and "FLC_RECOVER" not in env, {k: env.get(k) for k in ("FLC_MULTI", "FLC_WINDOW", "FLC_NO_UPDATE")})
check("A …dalla cartella del programma (così «-m freelasercut» lo trova)", kw["cwd"] == ROOT, kw.get("cwd"))
a1.trigger()
check("A due finestre in più hanno due sigle diverse", chiamate[-1][1]["env"]["FLC_WINDOW"] != env["FLC_WINDOW"])
w.new_window(["progetto.flcut"])
check("A un file passato arriva con il percorso intero", chiamate[-1][0][3:] == [os.path.abspath("progetto.flcut")])


def _rotta(*a, **k):
    raise OSError("non parte")


single.open_window = _rotta
check("A se il processo non parte: avviso e niente errore", w.new_window() is False)
single.open_window = lambda paths=(), recover=False, popen=None: vera_open(paths, recover, popen=finta_popen)

# ====================================================================== B. la finestra in più
print("--- B. la finestra in più")
disegna(w)
w.autosave()
principale = os.path.join(DIR, "autosave.flcut")
check("B finestra principale: salvataggio automatico di sempre e segno «da recuperare»",
      os.path.exists(principale) and w.qs.value("autosave_pending") in (True, "true"))
collegate = []
vero_auto = mw.MainWindow._auto_connect
mw.MainWindow._auto_connect = lambda self: collegate.append(getattr(self, "_window_token", ""))
w2 = finestra("abc123")
pump(1.3)
check("B la finestra in più non si collega da sola al laser", "abc123" not in collegate, collegate)
w0 = finestra()
pump(1.3)
check("B (una finestra principale sì, come sempre)", "" in collegate, collegate)
mw.MainWindow._auto_connect = vero_auto
w0.close()
w.qs.setValue("autosave_pending", True)
t_princ = os.path.getmtime(principale)
disegna(w2)
w2.autosave()
suo = os.path.join(DIR, "autosave-abc123.flcut")
check("B la finestra in più salva nel suo file, e quello della principale non cambia",
      os.path.exists(suo) and os.path.getmtime(principale) == t_princ and w2._autosave_path() == suo)
check("B …e segna che è viva: il suo salvataggio non risulta «rimasto»", suo not in single.orphans(DIR), single.orphans(DIR))
w2.editor.dirty = False
w2.close()
pump()
check("B chiusa bene: il suo salvataggio sparisce e il segno della principale resta",
      not os.path.exists(suo) and w.qs.value("autosave_pending") in (True, "true"), w.qs.value("autosave_pending"))
check("B …e non lascia il segno «sono viva»", not os.path.exists(os.path.join(DIR, "autosave-abc123.lock")))

# ====================================================================== C. finestre chiuse male
print("--- C. finestre chiuse male")
w3 = finestra("morta1")
disegna(w3)
w3.autosave()
rimasto = os.path.join(DIR, "autosave-morta1.flcut")
w3._window_lock.unlock()  # come se il processo non ci fosse più
check("C un salvataggio senza finestra viva si riconosce", single.orphans(DIR) == [rimasto], single.orphans(DIR))
ANSWER["r"] = QMessageBox.Yes
del chiamate[:]
w._offer_window_recovery()
check("C «Sì»: si riapre in un'altra finestra, come progetto recuperato",
      len(chiamate) == 1 and chiamate[0][0][3:] == [rimasto] and chiamate[0][1]["env"].get("FLC_RECOVER") == "1",
      [c[0] for c in chiamate])
w4 = finestra("nuova9")
os.environ["FLC_RECOVER"] = "1"
mw.open_paths(w4, [rimasto])
os.environ.pop("FLC_RECOVER")
check("C la finestra nuova lo carica senza nome di file, da salvare, e toglie il salvataggio rimasto",
      len(w4.editor.doc.all_shapes()) == 1 and w4.editor.doc.path is None and w4.editor.dirty
      and not os.path.exists(rimasto), (len(w4.editor.doc.all_shapes()), w4.editor.doc.path))
w4.editor.dirty = False
w4.close()
open(rimasto, "w").close()
ANSWER["r"] = QMessageBox.No
del chiamate[:]
w._offer_window_recovery()
check("C «No»: il salvataggio rimasto si butta e non si apre niente", not os.path.exists(rimasto) and not chiamate)
del chiamate[:]
w3._offer_recovery()
pump(0.3)
check("C una finestra in più non propone recuperi (lo fa la principale)", not chiamate)
w3.editor.dirty = False
w3.close()
ANSWER["r"] = QMessageBox.Yes

# ====================================================================== D. una finestra vera
print("--- D. una finestra vera")
processi = []


def vera_popen(cmd, **kw):
    kw["env"] = dict(kw["env"], QT_QPA_PLATFORM="offscreen")
    p = subprocess.Popen(cmd, **kw)
    processi.append((p, kw["env"]["FLC_WINDOW"]))
    return p


vera_open([], False, popen=vera_popen)
proc, tok = processi[0]
segno = os.path.join(DIR, f"autosave-{tok}.lock")
end = time.time() + 120
while time.time() < end and not os.path.exists(segno) and proc.poll() is None:
    time.sleep(0.2)
check("D il secondo FreeLaserCut parte e segna che è vivo", os.path.exists(segno) and proc.poll() is None, proc.poll())
suo2 = os.path.join(DIR, f"autosave-{tok}.flcut")
open(suo2, "w").close()
check("D finché è vivo il suo salvataggio non è «rimasto»", suo2 not in single.orphans(DIR))
proc.kill()
proc.wait(20)
time.sleep(0.5)
check("D ucciso (finestra chiusa male): ora il suo salvataggio è «rimasto»", suo2 in single.orphans(DIR), single.orphans(DIR))
os.remove(suo2)

# ====================================================================== E. difetti rimessi apposta
print("--- E. difetti rimessi apposta")
visti = 0
# 1. un solo file per tutte le finestre (com'era)
vero_path = single.autosave_path
single.autosave_path = lambda folder, token="": vero_path(folder, "")
w5 = finestra("difet1")
visti += w5._autosave_path() == principale
single.autosave_path = vero_path
# 2. la finestra in più, chiudendosi, toglie il segno della principale (com'era)
w.qs.setValue("autosave_pending", True)
w5._window_token_vero, w5._window_token = w5._window_token, ""
w5.editor.dirty = False
w5.close()
visti += w.qs.value("autosave_pending") not in (True, "true")
w.qs.setValue("autosave_pending", True)
# 3. il controllo «la finestra c'è ancora?» saltato: il progetto di una finestra aperta sarebbe proposto come
# «rimasto» (e con «No» cancellato)
w6 = finestra("difet3")
f6 = os.path.join(DIR, "autosave-difet3.flcut")
open(f6, "w").close()
vecchio = time.time() - 120
os.utime(os.path.join(DIR, "autosave-difet3.lock"), (vecchio, vecchio))
check("E (un segno vecchio di due minuti, con la finestra viva, non è «rimasto»)", f6 not in single.orphans(DIR))


class _SempreLibero:
    def tryLock(self, _ms=0):
        return True

    def unlock(self):
        pass


vero_lock = single._lock
single._lock = lambda path: _SempreLibero()
visti += f6 in single.orphans(DIR)
single._lock = vero_lock
w6.editor.dirty = False
w6.close()
if os.path.exists(f6):
    os.remove(f6)
check("E 3 difetti rimessi apposta (un file solo per tutte le finestre, segno della principale tolto dalla finestra "
      "in più, finestra viva scambiata per chiusa male): tutti visti", visti == 3, visti)
w.editor.dirty = False
w.close()

print()
print(f"{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
