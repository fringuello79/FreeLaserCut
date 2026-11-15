# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.1: la finestra non deve mai allargarsi da sola oltre lo schermo (Evoluzione2, 15/11/2026, con la 0.20.0:
«appena si carica un progetto si sposta tutto a destra, perdendo i menu sulla destra; anche la barra in alto va fuori
schermo»). La causa: la scritta «File: …» nella barra in basso alzava la larghezza minima della barra oltre quella
dello schermo, e la finestra si allargava per contenerla.

Matrice dei casi (in ogni lingua, Classica e Banco, finestra di 1366 px come i portatili più comuni, o più larga se
all'avvio non ci sta: sui server Windows di GitHub, senza schermo e con caratteri di ripiego, la barra in basso è
larga circa 2000 px già all'avvio, anche con la 0.19.5; per questo le misure sono relative all'avvio):
1 avvio: la finestra ha la larghezza chiesta, o quella minima se più grande;
2 importato un file dal nome lunghissimo, poi un secondo file, tutto selezionato, progetto salvato e riaperto: la larghezza minima della barra non supera mai quella dell'avvio e la finestra resta larga 1366;
3 la scritta «File: …» non chiede spazio (minimo 0) ma si vede quando c'è posto (finestra di 1920 px), con il testo
  intero nel suggerimento e nel nome accessibile;
4 la scritta accorciata sta sempre nella sua larghezza.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.environ.get("FLC_TEST_CHILD") == "1"

if not CHILD:
    ui = sys.argv[1] if len(sys.argv) > 1 else "classica"
    ok_all, total = True, 0
    # in più, in italiano, la finestra partita già alla sua larghezza minima (come sui server senza schermo): lì
    # anche pochi pixel in più la allargherebbero
    for lang, narrow in (("it", ""), ("en", ""), ("es", ""), ("fr", ""), ("pt", ""), ("it", "1")):
        env = dict(os.environ, FLC_TEST_CHILD="1", FLC_LANG=lang, FLC_UI=ui, FLC_TEST_NARROW=narrow)
        tag = lang + (" stretta" if narrow else "")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), ui], env=env, capture_output=True, text=True,
                           timeout=600)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("OK  ", "NO  "))]
        for ln in lines:  # «OK»/«KO» in testa: tests/run_tests.py riporta solo queste righe
            print(("OK  " if ln.startswith("OK") else "KO  ") + f"[{tag}] {ln[4:]}", flush=True)
        for ln in r.stdout.splitlines():
            if ln.startswith("INFO"):
                print(f"OK  [{tag}] {ln}", flush=True)
        total += len(lines)
        if r.returncode != 0 or not lines or any(ln.startswith("NO") for ln in lines):
            ok_all = False
            if lines and r.returncode != 0:
                print(f"KO  [{tag}] uscita con codice {r.returncode}: {(r.stderr or '')[-600:]}", flush=True)
            if not lines:
                print(f"KO  [{tag}] la prova non è partita: {r.stderr[-800:]}")
    good = total if ok_all else total - 1
    print(f"\n{good}/{total} superati", flush=True)
    sys.exit(0 if ok_all else 1)

# ---------------------------------------------------------------------------------------------- figlio: una lingua
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
from freelasercut.ui.main_window import MainWindow, ShrinkLabel  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(n=12):
    for _ in range(n):
        app.processEvents()


SCREEN = 1 if os.environ.get("FLC_TEST_NARROW") else 1366  # 1: la finestra parte alla sua larghezza minima
w = MainWindow()
w.resize(SCREEN, 740)
w.show()
spin()
sb = w.statusBar()
start_sb = sb.minimumSizeHint().width()
print(f"INFO avvio: finestra minima {w.minimumSizeHint().width()} px, barra in basso {start_sb} px", flush=True)
BASE = w.width()  # 1366, o la larghezza minima della finestra se all'avvio non ci sta (server senza schermo)
check("1 avvio: la finestra ha la larghezza chiesta (o la minima, se più grande)",
      BASE == max(SCREEN, w.minimumSizeHint().width()), (BASE, w.minimumSizeHint().width()))

d = tempfile.mkdtemp()


def svg(name, x):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
                 f'<rect x="{x}" y="10" width="30" height="20" fill="none" stroke="black"/></svg>')
    return p


worst = [0, ""]


def look(tag):
    spin()
    m = sb.minimumSizeHint().width()
    if m > worst[0]:
        worst[:] = [m, tag]
    return m <= start_sb and w.width() == BASE and w.minimumSizeHint().width() <= BASE


LONG = "Progetto con un nome di file davvero lunghissimo per vedere cosa succede alla barra in basso.svg"
steps = []
w.import_files([svg(LONG, 10)])
steps.append(("importato un file dal nome lunghissimo", look("import1")))
w.import_files([svg("Pluto.svg", 50)])
steps.append(("importato un secondo file", look("import2")))
w.editor.select(list(w.editor.doc.shapes))
steps.append(("selezionato tutto (forme di due file)", look("selez")))
path = os.path.join(d, "Un progetto salvato con un nome lungo anche lui.flcut")
w.editor.doc.path = path
w.file_save()
w.editor.dirty = False
w.file_open(path)
steps.append(("progetto salvato e riaperto", look("aperto")))
w.editor.select(list(w.editor.doc.shapes))
steps.append(("selezione nel progetto riaperto", look("selez2")))
for name, ok in steps:
    check(f"2 {name}: barra e finestra non si allargano", ok,
          (sb.minimumSizeHint().width(), start_sb, w.width()))
check("2 il caso peggiore resta entro la larghezza della barra all'avvio", worst[0] <= start_sb, worst)

lab = w.lbl_origin
check("3 la scritta «File: …» non chiede spazio (minimo 0)", isinstance(lab, ShrinkLabel)
      and lab.minimumSizeHint().width() == 0)
w.resize(BASE + 554, 900)
spin()
check("3 con posto (554 px in più: 1920 sul portatile) la scritta si vede, abbastanza larga da leggere",
      lab.isVisible() and lab.width() >= 120 and lab.text().startswith(("File", "Fich", "Arqu")), (lab.width(), lab.text()))
check("3 testo intero nel nome accessibile e nel suggerimento",
      LONG in lab.accessibleName() and LONG in lab.toolTip(), lab.accessibleName())
widths = [BASE + 554, BASE + 234, BASE] + ([BASE - 126] if BASE - 126 >= w.minimumSizeHint().width() else [])
for width in widths:
    w.resize(width, 900)
    spin()
    fits = lab.fontMetrics().horizontalAdvance(lab.text()) <= max(lab.width(), 0) or not lab.text()
    check(f"4 finestra larga {width - BASE:+d} px rispetto all'avvio: la scritta mostrata sta nella sua larghezza", fits and w.width() == width,
          (lab.width(), lab.fontMetrics().horizontalAdvance(lab.text()), w.width()))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati", flush=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402  (su Windows os._exit con i fili di Qt vivi dà «access violation»)

esci(code_)
