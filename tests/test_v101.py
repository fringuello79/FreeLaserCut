# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.1: avvio più robusto (segnalazioni di un utente).
- un errore all'avvio non resta nascosto dietro la schermata d'avvio, e il programma esce pulito;
- istanza unica: il secondo avvio porta in primo piano la finestra già aperta (con i file passati);
- scelta dell'interfaccia: doppio clic su una scheda = Inizia, pulsante che dice cosa parte;
- installatore: controllo del programma aperto, messaggi chiari, cartella, collegamento di diagnostica."""
import sys, os, time, tempfile, subprocess
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # QSettings su Linux: niente scritture fuori dalla prova
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_MULTI", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
app = QApplication([])
SEEN = []
def _critical(parent, title, text, *a, **k):
    from PySide6.QtWidgets import QSplashScreen
    vis = [w for w in QApplication.topLevelWidgets() if isinstance(w, QSplashScreen) and w.isVisible()]
    SEEN.append((title, text, len(vis)))
    return QMessageBox.Ok
QMessageBox.critical = staticmethod(_critical)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import single
from freelasercut.app import _install_crash_log
from freelasercut.profile import config_dir
from freelasercut.splash import show_splash
from freelasercut.ui import main_window as mw

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)
def spin_until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

TMP = tempfile.mkdtemp()
SVG = os.path.join(TMP, "quadrato.svg")
with open(SVG, "w", encoding="utf-8") as fh:
    fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="20mm" viewBox="0 0 20 20">'
             '<rect x="2" y="2" width="16" height="16" fill="none" stroke="black"/></svg>')
LOG = os.path.join(config_dir(), "flc.log")

# ------------------------------------------------------------------ schermata d'avvio ed errori
sp = show_splash(); spin(0.1)
check("schermata d'avvio non più «sempre in primo piano»", not (sp.windowFlags() & Qt.WindowStaysOnTopHint))
_install_crash_log()
try:
    raise ValueError("prova errore")
except ValueError:
    sys.excepthook(*sys.exc_info())
check("errore imprevisto: la schermata d'avvio si chiude prima del messaggio", SEEN and SEEN[-1][2] == 0 and not sp.isVisible(), SEEN[-1:])
check("errore imprevisto: scritto nel registro flc.log", os.path.exists(LOG) and "prova errore" in open(LOG, encoding="utf-8").read())

# errore mentre si crea la finestra principale: splash chiuso, messaggio, uscita pulita con codice 1
class Broken:
    def __init__(self):
        raise RuntimeError("finestra rotta")
real_mw = mw.MainWindow
mw.MainWindow = Broken
sp2 = show_splash(); spin(0.1)
n0 = len(SEEN)
code = None
try:
    mw.main(app, sp2)
except SystemExit as e:
    code = e.code
mw.MainWindow = real_mw
check("errore nella finestra principale: uscita pulita (codice 1)", code == 1, code)
check("errore nella finestra principale: messaggio mostrato a splash chiuso", len(SEEN) == n0 + 1 and SEEN[-1][2] == 0
      and "finestra rotta" in SEEN[-1][1] and not sp2.isVisible())
check("errore nella finestra principale: nel registro", "finestra rotta" in open(LOG, encoding="utf-8").read())

# ------------------------------------------------------------------ istanza unica
NAME = "flc-prova-%d" % os.getpid()
t0 = time.time()
check("nessun FreeLaserCut aperto: l'avvio prosegue (e subito)", single.forward([SVG], name=NAME) is False and time.time() - t0 < 1.5,
      f"{time.time() - t0:.2f} s")
got = []
lst = single.Listener(app, name=NAME, on_request=got.append)
check("il primo avvio resta in ascolto", lst.listening)
check("secondo avvio: trova quello aperto", single.forward([SVG, os.path.join(TMP, "non-esiste.svg")], name=NAME) is True)
spin_until(lambda: got)
check("secondo avvio: passa i file esistenti, con il percorso completo", got == [[os.path.abspath(SVG)]], got)
got.clear()
check("secondo avvio senza file", single.forward([], name=NAME) and spin_until(lambda: got) and got == [[]], got)
os.environ["FLC_MULTI"] = "1"
check("FLC_MULTI=1: si possono aprire più copie", single.forward([], name=NAME) is False)
os.environ.pop("FLC_MULTI")
lst.close()
check("nomi diversi per utenti diversi (named pipe per utente)", single.server_name().startswith("FreeLaserCut-") and
      len(single.server_name()) > 20)

# avvio vero: main() aggancia la finestra, apre i file da riga di comando; poi un secondo avvio la porta avanti
lst2 = single.Listener(app, name=NAME + "b")
app._flc_single = lst2
argv0 = sys.argv
sys.argv = ["freelasercut", SVG]
holder = {}
def _later():  # ripetuto: quit() conta solo quando il ciclo degli eventi di main() è partito
    if lst2.window is not None:
        holder["win"] = lst2.window
        app.exit(0)  # exit, non quit: quit chiuderebbe le finestre (e chiederebbe di salvare)
tick = QTimer(); tick.timeout.connect(_later); tick.start(300)
code = None
try:
    mw.main(app, None)
except SystemExit as e:
    code = e.code
tick.stop()
sys.argv = argv0
win = holder.get("win")
check("avvio: la finestra si aggancia all'istanza unica", win is not None and isinstance(win, real_mw))
n_shapes = len(win.editor.doc.shapes) if win else -1
check("avvio: il file passato all'avvio si apre", n_shapes == 1, n_shapes)
win.showMinimized(); spin(0.2)
check("secondo avvio con un file: arriva alla finestra aperta", single.forward([SVG], name=NAME + "b"))
spin_until(lambda: len(win.editor.doc.shapes) == 2)
check("secondo avvio: il file si importa nella finestra già aperta", len(win.editor.doc.shapes) == 2, len(win.editor.doc.shapes))
check("secondo avvio: la finestra non è più ridotta a icona", not win.isMinimized() and win.isVisible())
# richiesta arrivata prima che la finestra esista: tenuta da parte e poi eseguita
lst3 = single.Listener(app, name=NAME + "c")
single.forward([], name=NAME + "c"); spin_until(lambda: lst3.pending)
check("richiesta durante l'avvio: tenuta da parte", lst3.pending == [[]])
lst3.attach(win)
check("richiesta durante l'avvio: eseguita quando c'è la finestra", lst3.pending == [])
lst3.close(); lst2.close()

# avvio vero da riga di comando con FreeLaserCut «già aperto» (qui: un Listener col nome reale)
got = []
lreal = single.Listener(app, on_request=got.append)
env = dict(os.environ)
env.pop("FLC_MULTI", None)
t0 = time.time()
p = subprocess.Popen([sys.executable, "-m", "freelasercut", SVG], cwd=ROOT, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
spin_until(lambda: p.poll() is not None, 60)
out = p.stdout.read().decode("utf-8", "replace")
spin_until(lambda: got, 3)
check("python -m freelasercut con FreeLaserCut già aperto: esce subito senza aprire un'altra copia",
      p.returncode == 0 and time.time() - t0 < 30, f"rc={p.returncode} {time.time() - t0:.1f} s {out.strip()[-120:]}")
check("... e passa il file a quello aperto", got == [[os.path.abspath(SVG)]], got)
lreal.close()

# ------------------------------------------------------------------ scelta dell'interfaccia
from freelasercut.ui.banco import ChoiceDialog, settings
d = ChoiceDialog(); d.resize(700, 420); d.show(); spin(0.2)
check("pulsante: dice quale interfaccia parte", "Banco" in d.ok.text(), d.ok.text())
QTest.mouseClick(d.b_classic, Qt.LeftButton, Qt.NoModifier, d.b_classic.rect().center()); spin(0.1)
check("clic su Classica: il pulsante cambia testo", "Classica" in d.ok.text() and d.choice == "classica", d.ok.text())
check("clic singolo: la finestra resta aperta", d.isVisible())
QTest.mouseDClick(d.b_banco, Qt.LeftButton, Qt.NoModifier, d.b_banco.rect().center()); spin(0.2)
check("doppio clic su Banco: parte subito con il Banco", d.result() == QDialog.Accepted and not d.isVisible()
      and settings().value("ui_mode") == "banco", (d.result(), settings().value("ui_mode")))

# ------------------------------------------------------------------ installatore
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8").read()
check("installatore: controlla se FreeLaserCut è aperto (installazione e disinstallazione)",
      "Function ${UN}FlcInUso" in nsi and 'FLC_ASPETTA_CHIUSO "un." "Quit"' in nsi and 'FLC_ASPETTA_CHIUSO "" "Abort"' in nsi)
check("installatore: messaggio chiaro se i file non si tolgono o non si scrivono",
      "flc_togli_ko" in nsi and "FileErrorText" in nsi and nsi.count("Non riesco") >= 2)
check("installatore: spiega la cartella e rifiuta «Programmi»",
      "MUI_DIRECTORYPAGE_TEXT_TOP" in nsi and "$PROGRAMFILES64" in nsi and "MUI_PAGE_CUSTOMFUNCTION_LEAVE DirLeave" in nsi)
check("installatore: collegamento «FreeLaserCut (diagnostica)» con python.exe e console",
      "(diagnostica).lnk" in nsi and "python\\python.exe" in nsi and "/s /k" in nsi)

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
