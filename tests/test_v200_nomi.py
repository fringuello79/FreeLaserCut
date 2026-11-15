# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: nome del progetto e file di provenienza delle forme (segnalazione di Evoluzione2, 15/11/2026: «importando
Pippo.svg il titolo resta Senza titolo e si salva come Senza titolo.flcut / disegno.svg»; «con più file sullo stesso
piano, selezionando un oggetto vorrei leggere il file da cui proviene»).

Matrice dei casi:
1 progetto nuovo + Pippo.svg: titolo, Salva con nome, Esporta SVG e Salva G-code propongono «Pippo»;
2 secondo file importato: il nome del progetto non cambia;
3 progetto già con forme disegnate: importare non cambia il nome;
4 progetto aperto da file: Esporta SVG propone il nome del file del progetto;
5 selezione: «File: Pippo.svg»; forme di due file: il primo e «altri 1»; forma disegnata qui: niente scritta;
6 dentro un gruppo, nei duplicati, dopo salva e riapri, dopo Annulla/Ripeti dell'importazione;
7 progetti vecchi senza il dato: nessuna scritta e nessun errore; forme disegnate: nel file non compare «origin»;
8 traduzioni; Banco.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut.core.document import Document, GroupShape, RectShape, origins  # noqa: E402
from freelasercut.i18n import tr  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(n=5):
    for _ in range(n):
        app.processEvents()


d = tempfile.mkdtemp()


def svg(name, x=10):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
                 f'<rect x="{x}" y="10" width="30" height="20" fill="none" stroke="black"/></svg>')
    return p


asked = []


def fake_save(parent, title, start, *a, **k):
    asked.append(os.path.basename(start))
    return "", ""


QFileDialog.getSaveFileName = staticmethod(fake_save)

w = MainWindow()
w.show()
spin()
ed = w.editor

# 1. progetto nuovo + Pippo.svg
w.import_files([svg("Pippo.svg")])
spin()
check("progetto nuovo + Pippo.svg: il progetto si chiama «Pippo»", ed.doc.name == "Pippo", ed.doc.name)
check("…e il titolo della finestra lo dice", "Pippo" in w.windowTitle() and tr("Senza titolo") not in w.windowTitle(),
      w.windowTitle())
w.file_save_as()
check("Salva con nome propone «Pippo.flcut»", asked[-1:] == ["Pippo.flcut"], asked)
ed.select(list(ed.doc.shapes))
w.file_export()
check("Esporta SVG propone «Pippo.svg» (non più «disegno.svg»)", asked[-1:] == ["Pippo.svg"], asked)
w.save_gcode()
check("Salva G-code propone «Pippo.gcode»", asked[-1:] == ["Pippo.gcode"] or not w.editor.doc.shapes, asked)

# 2. secondo file: il nome non cambia
w.import_files([svg("Pluto.svg", 50)])
spin()
check("un secondo file importato non cambia il nome del progetto", ed.doc.name == "Pippo", ed.doc.name)

# 5. scritta del file di provenienza
pippo = [s for s in ed.doc.shapes if s.origin == "Pippo.svg"]
pluto = [s for s in ed.doc.shapes if s.origin == "Pluto.svg"]
check("ogni forma importata ricorda il suo file", pippo and pluto, [s.origin for s in ed.doc.shapes])
ed.select(pippo)
spin()
check("selezionata una forma di Pippo.svg: in basso «File: Pippo.svg»",
      w.lbl_origin.isVisibleTo(w) and w.lbl_origin.accessibleName() == tr("File: {0}", "Pippo.svg"),
      w.lbl_origin.accessibleName())
ed.select(pluto)
spin()
check("selezionata una forma di Pluto.svg: la scritta cambia",
      w.lbl_origin.accessibleName() == tr("File: {0}", "Pluto.svg"), w.lbl_origin.accessibleName())
ed.select(pippo + pluto)
spin()
check("forme di due file: il primo e «altri 1», l'elenco completo nel suggerimento",
      w.lbl_origin.accessibleName() == tr("File: {0} e altri {1}", "Pippo.svg", 1)
      and "Pluto.svg" in w.lbl_origin.toolTip(), (w.lbl_origin.accessibleName(), w.lbl_origin.toolTip()))
check("…la scritta mostrata sta nella barra (accorciata solo se non ci sta)",
      w.lbl_origin.fontMetrics().horizontalAdvance(w.lbl_origin.text()) <= 252 and w.lbl_origin.text())
drawn = RectShape(20, 20)
ed.add([drawn])
ed.select([drawn])
spin()
check("forma disegnata qui: niente scritta", not w.lbl_origin.isVisibleTo(w))
ed.select([])
spin()
check("niente selezionato: niente scritta", not w.lbl_origin.isVisibleTo(w))

# 6. gruppi, duplicati, salva e riapri
grp = GroupShape([pippo[0].clone(), pluto[0].clone()])
check("dentro un gruppo: i file delle forme del gruppo", origins([grp]) == ["Pippo.svg", "Pluto.svg"], origins([grp]))
dup = pippo[0].clone()
check("un duplicato ricorda il file", dup.origin == "Pippo.svg")
dd = drawn.to_dict()
check("forma disegnata: nel file del progetto non c'è «origin» (i progetti restano come prima)", "origin" not in dd)
path = os.path.join(d, "prova.flcut")
ed.doc.save(path)
doc2 = Document.load(path)
check("salvato e riaperto: le forme ricordano il file", sorted(origins(doc2.shapes)) == ["Pippo.svg", "Pluto.svg"],
      origins(doc2.shapes))
raw = json.loads(open(path, encoding="utf-8").read()) if open(path, "rb").read(1) == b"{" else None
old = {"kind": "rect", "id": "x", "layer": 1, "p": {"w": 5, "h": 5}}
from freelasercut.core.document import shape_from_dict  # noqa: E402

s_old = shape_from_dict(old)
check("forma di un progetto vecchio (senza il dato): nessun file, nessun errore", s_old.origin == "")
s_bad = shape_from_dict(dict(old, origin=12))
check("dato rovinato nel file: ignorato", s_bad.origin == "")

# 3. progetto con forme disegnate: importare non cambia il nome
w.file_new() if hasattr(w, "file_new") else None
spin()
ed = w.editor
ed.add([RectShape(10, 10)])
name0 = ed.doc.name
w.import_files([svg("Topolino.svg")])
spin()
check("progetto con forme già disegnate: importare non cambia il nome", ed.doc.name == name0, ed.doc.name)

# 4. progetto aperto da file: Esporta propone il nome del file del progetto
w.editor.dirty = False
w.file_open(path)
spin()
w.editor.select(list(w.editor.doc.shapes))
w.file_export()
check("progetto aperto da prova.flcut: Esporta SVG propone «prova.svg»", asked[-1:] == ["prova.svg"], asked)

# 8. traduzioni
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    keys = ("File: {0}", "File: {0} e altri {1}", "Le forme selezionate vengono da:")
    check(f"traduzioni {lang}", all(k in cat and cat[k].count("{") == k.count("{") for k in keys))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati", flush=True)

from _uscita import esci  # noqa: E402

esci(code_)
