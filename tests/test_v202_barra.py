# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.2: la scritta «File: …» della barra in basso si deve leggere (Evoluzione2, 15/11/2026, con la 0.20.1: «il
nome del file sulla barra in basso si legge solo in parte, e se si attiva "aggancia griglia" o altro tasto compare
e dopo qualche secondo riscompare»). Causa: con il laser scollegato la posizione della testa e la velocità/potenza,
vuote, tenevano comunque 550 px; alla scritta «File: …» (che dalla 0.20.1 usa solo lo spazio libero) non restava
niente, se non per i pochi secondi in cui un messaggio nascondeva il pulsante del laser.

Matrice dei casi (Classica e Banco; caratteri normali e caratteri più larghi del 30%, come su Windows):
1 laser scollegato, forme di un file selezionate, finestra di 1366 px: «File: Pippo.svg» intera e leggibile;
2 un messaggio di qualche secondo (Aggancia griglia) e poi niente: la scritta resta com'era, non si stringe;
3 laser «collegato» (posizione e velocità scritte), finestra larga: tutte le scritte intere, «File:» compresa;
4 laser collegato in una finestra stretta: la finestra non si allarga; le scritte si accorciano, il testo intero resta;
5 laser scollegato di nuovo: posizione e velocità non occupano più spazio;
6 in ogni passo la larghezza minima della barra non supera quella dell'avvio.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut.ui.main_window import MainWindow, ShrinkLabel  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(t=0.15):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


d = tempfile.mkdtemp()
P = os.path.join(d, "Pippo.svg")
with open(P, "w", encoding="utf-8") as fh:
    fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
             '<rect x="10" y="10" width="30" height="20" fill="none" stroke="black"/></svg>')

HEAD = "testa  123.45,   67.89  ·  lavoro 10.00, 20.00"
FS = "F 6000 mm/min · potenza 35%"


def shows_all(lab):
    return lab.isVisible() and lab.text() == lab.fullText() and \
        lab.width() >= lab.fontMetrics().horizontalAdvance(lab.fullText())


for tag, scale in (("caratteri normali", 1.0), ("caratteri più larghi (come Windows)", 1.3)):
    f = app.font()
    base_pt = f.pointSizeF() if f.pointSizeF() > 0 else 9.0
    if scale != 1.0:
        f.setPointSizeF(base_pt * scale)
        app.setFont(f)
    w = MainWindow()
    w.resize(1366, 800)
    w.show()
    spin()
    sb = w.statusBar()
    start_sb = sb.minimumSizeHint().width()
    base = w.width()
    worst = [0]
    # sui server Windows di GitHub (senza schermo, caratteri di ripiego) la barra è già più larga della finestra
    # all'avvio, anche con la 0.19.5 (stessa causa dei rossi noti della casella «Cerca un comando»): lì le prove
    # «la scritta si legge intera» non dicono niente e si saltano, con il motivo; restano quelle «la finestra non si
    # allarga mai», che valgono dappertutto
    roomy = start_sb <= 0.9 * base

    def check_room(name, cond, info=""):
        if roomy:
            check(name, cond, info)
        else:
            print(f"--  {name}  [saltata: barra già larga {start_sb} px all'avvio su {base} px, server senza schermo]",
                  flush=True)

    def look():
        spin()
        worst[0] = max(worst[0], sb.minimumSizeHint().width())
        return w.width() == base

    w.import_files([P])
    sb.clearMessage()
    ok = look()
    w.editor.select(list(w.editor.doc.shapes))
    ok &= look()
    lab = w.lbl_origin
    check_room(f"[{tag}] 1 laser scollegato, 1366 px: «File: Pippo.svg» intera e leggibile", shows_all(lab) and ok,
          (lab.width(), lab.text(), w.width()))
    check(f"[{tag}] 1 posizione e velocità vuote non occupano spazio", w.lbl_head.width() == 0 and w.lbl_fs.width() == 0,
          (w.lbl_head.width(), w.lbl_fs.width()))
    before = lab.width()
    w.acts["snap_grid"].trigger()
    sb.showMessage("Aggancia alla griglia", 300)
    spin(0.1)
    during = lab.width()
    spin(0.6)
    after = lab.width()
    w.acts["snap_grid"].trigger()
    check_room(f"[{tag}] 2 un messaggio e poi niente: la scritta non si stringe dopo", after >= before and shows_all(lab)
          and look(), (before, during, after))

    # 3 «collegato», finestra larga
    w.resize(base + 700, 800)
    spin()
    base_wide = w.width()
    w.lbl_head.setText(HEAD)
    w.lbl_fs.setText(FS)
    spin()
    check_room(f"[{tag}] 3 laser collegato, finestra larga: posizione, velocità e «File:» intere",
          shows_all(w.lbl_head) and shows_all(w.lbl_fs) and shows_all(lab) and w.width() == base_wide,
          (w.lbl_head.width(), w.lbl_fs.width(), lab.width(), w.width()))
    check_room(f"[{tag}] 3 la posizione tiene la sua larghezza (i numeri che cambiano non spostano il resto)",
          w.lbl_head.width() >= w.lbl_head.sizeHint().width() - 1, (w.lbl_head.width(), w.lbl_head.sizeHint().width()))
    x0, w0 = w.lbl_head.x(), w.lbl_head.width()
    w.lbl_head.setText("testa 1.0, 2.0 · lavoro 0, 0")
    spin()
    check_room(f"[{tag}] 3 numeri più corti: la scritta resta larga uguale e le altre non si spostano",
          (w.lbl_head.x(), w.lbl_head.width()) == (x0, w0), (x0, w0, w.lbl_head.x(), w.lbl_head.width()))
    w.lbl_head.setText(HEAD)

    # 4 «collegato», finestra stretta
    w.resize(1, 800)
    spin()
    narrow = w.width()
    w.lbl_head.setText(HEAD + " ")
    spin()
    check(f"[{tag}] 4 laser collegato, finestra alla larghezza minima: la finestra non si allarga",
          w.width() == narrow and sb.minimumSizeHint().width() <= start_sb, (narrow, w.width()))
    check(f"[{tag}] 4 …le scritte accorciate stanno nel loro spazio, il testo intero resta",
          all(x.fontMetrics().horizontalAdvance(x.text()) <= max(x.width(), 0) or not x.text()
              for x in (w.lbl_head, w.lbl_fs, lab)) and w.lbl_head.fullText() == HEAD + " ")

    # 5 scollegato
    w.resize(base, 800)
    spin()
    w.lbl_head.setText("")
    w.lbl_fs.setText("")
    spin()
    check_room(f"[{tag}] 5 scollegato di nuovo: posizione e velocità a zero, «File:» di nuovo intera",
          w.lbl_head.width() == 0 and w.lbl_fs.width() == 0 and shows_all(lab), (w.lbl_head.width(), lab.width()))
    check(f"[{tag}] 6 la larghezza minima della barra non ha mai superato quella dell'avvio", worst[0] <= start_sb,
          (worst[0], start_sb))
    check(f"[{tag}] 6 posizione e velocità sono scritte che si accorciano (minimo 0)",
          isinstance(w.lbl_head, ShrinkLabel) and isinstance(w.lbl_fs, ShrinkLabel)
          and w.lbl_head.minimumSizeHint().width() == 0 and w.lbl_fs.minimumSizeHint().width() == 0)
    w.editor.dirty = False
    w.qs.setValue("autosave_pending", False)
    w.close()
    w.deleteLater()
    spin()

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(code_)
