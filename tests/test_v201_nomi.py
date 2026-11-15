# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.1: il nome del progetto dato dall'importazione segue i file che restano (segnalazione di Evoluzione2,
15/11/2026: «importo Pippo, poi Pluto; cancello gli oggetti di Pippo: in alto c'è sempre Pippo e salvando il
progetto me lo propone con il nome di Pippo», col rischio di sovrascrivere il progetto di Pippo).

Matrice dei casi:
1 Pippo + Pluto: il nome resta «Pippo» (come nella 0.20.0); cambiare l'ordine delle forme non lo cambia;
2 cancellate tutte le forme di Pippo: «Pluto» nel titolo, in Salva con nome, Esporta SVG e Salva G-code;
3 Annulla la cancellazione: di nuovo «Pippo»; Ripeti: «Pluto»;
4 forme di Pippo spostate su un altro piano: il nome resta «Pippo»;
5 dentro un gruppo: il gruppo con una forma di Pippo tiene il nome; cancellato il gruppo, «Pluto»;
6 cancellato tutto quello che viene dai file (restano forme disegnate): «Senza titolo»; un nuovo file importato
  dà di nuovo il nome; Annulla dell'importazione: «Senza titolo»;
7 progetto salvato con nome, o aperto da file: cancellando le forme il nome resta quello del file;
8 progetto nuovo con forme disegnate e poi un file: il nome non cambia (come nella 0.20.0); Nuovo progetto azzera;
9 Banco.
"""
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut.core.document import Document, GroupShape, RectShape  # noqa: E402
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


def svg(name, x=10, n=1):
    p = os.path.join(d, name)
    rects = "".join(f'<rect x="{x + 12 * i}" y="10" width="10" height="20" fill="none" stroke="black"/>'
                    for i in range(n))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
                 f'{rects}</svg>')
    return p


asked = []
SAVE_TO = []


def fake_save(parent, title, start, *a, **k):
    asked.append(os.path.basename(start))
    return (SAVE_TO.pop(0), "") if SAVE_TO else ("", "")


QFileDialog.getSaveFileName = staticmethod(fake_save)


def proposals():
    """(Salva con nome, Esporta SVG, Salva G-code): i nomi proposti."""
    del asked[:]
    w.file_save_as()
    w.editor.select(list(w.editor.doc.shapes))
    w.file_export()
    w.save_gcode()
    return list(asked)


def of(name):
    return [s for s in w.editor.doc.shapes if s.origin == name]


w = MainWindow()
w.show()
spin()
ed = w.editor

# 1
w.import_files([svg("Pippo.svg", 10, 2)])
spin()
w.import_files([svg("Pluto.svg", 50, 2)])
spin()
check("1 Pippo e poi Pluto: il progetto si chiama «Pippo»", ed.doc.name == "Pippo", ed.doc.name)
ed.select(of("Pippo.svg"))
if hasattr(ed, "order"):
    ed.order("top") if True else None
spin()
check("1 cambiato l'ordine delle forme (Pippo in cima): sempre «Pippo»", ed.doc.name == "Pippo", ed.doc.name)

# 2
ed.select(of("Pippo.svg"))
ed.delete()
spin()
check("2 cancellate le forme di Pippo: il progetto si chiama «Pluto»", ed.doc.name == "Pluto", ed.doc.name)
check("2 …e il titolo della finestra lo dice", "Pluto" in w.windowTitle() and "Pippo" not in w.windowTitle(),
      w.windowTitle())
p = proposals()
check("2 Salva con nome, Esporta SVG e Salva G-code propongono «Pluto»",
      p == ["Pluto.flcut", "Pluto.svg", "Pluto.gcode"], p)

# 3
ed.undo()
spin()
check("3 Annulla la cancellazione: di nuovo «Pippo»", ed.doc.name == "Pippo" and of("Pippo.svg"), ed.doc.name)
ed.redo()
spin()
check("3 Ripeti: «Pluto»", ed.doc.name == "Pluto", ed.doc.name)
ed.undo()
spin()

# 4
if hasattr(ed, "add_plate") and hasattr(ed, "move_to_plate"):
    i2 = ed.add_plate()
    i2 = i2 if isinstance(i2, int) else len(ed.doc.plates) - 1
    ed.set_plate(0)
    spin()
    ed.move_to_plate(of("Pippo.svg"), i2)
    spin()
    check("4 forme di Pippo spostate su un altro piano: il nome resta «Pippo»",
          ed.doc.name == "Pippo" and not of("Pippo.svg"), ed.doc.name)
    ed.undo()
    spin()
    check("4 …e riportate qui: sempre «Pippo»", ed.doc.name == "Pippo" and of("Pippo.svg"), ed.doc.name)

# 5
extra = RectShape(8, 8)
ed.add([extra])
ed.select(of("Pippo.svg") + [extra])
ed.group()
spin()
grp = [s for s in ed.doc.shapes if isinstance(s, GroupShape) and not s.origin]
check("5 le forme di Pippo stanno solo dentro un gruppo nuovo: il nome resta «Pippo»",
      len(grp) == 1 and not of("Pippo.svg") and ed.doc.name == "Pippo", (len(grp), ed.doc.name))
ed.select(grp)
ed.delete()
spin()
check("5 cancellato il gruppo: «Pluto»", ed.doc.name == "Pluto" and of("Pluto.svg"), ed.doc.name)

# 6
drawn = RectShape(15, 15)
ed.add([drawn])
ed.select(of("Pluto.svg"))
ed.delete()
spin()
check("6 restano solo forme disegnate: «Senza titolo»", ed.doc.name == tr("Senza titolo") and ed.doc.shapes,
      ed.doc.name)
p = proposals()
check("6 …e niente propone più «Pippo» o «Pluto»", not any("Pippo" in x or "Pluto" in x for x in p), p)
w.import_files([svg("Paperino.svg", 30)])
spin()
check("6 un nuovo file: il progetto prende il suo nome", ed.doc.name == "Paperino", ed.doc.name)
ed.undo()
spin()
check("6 Annulla dell'importazione: di nuovo «Senza titolo»", ed.doc.name == tr("Senza titolo"), ed.doc.name)
ed.redo()
spin()

# 7 salvato con nome
target = os.path.join(d, "Fumetti.flcut")
SAVE_TO.append(target)
del asked[:]
w.file_save_as()
spin()
check("7 salvato come Fumetti.flcut: il progetto si chiama «Fumetti»", ed.doc.name == "Fumetti"
      and os.path.exists(target), ed.doc.name)
ed.select(of("Paperino.svg"))
ed.delete()
spin()
check("7 …cancellando le forme del file importato il nome resta «Fumetti»", ed.doc.name == "Fumetti"
      and "Fumetti" in w.windowTitle(), (ed.doc.name, w.windowTitle()))
ed.undo()
w.file_save()
w.editor.dirty = False
w.file_open(target)
spin()
ed = w.editor
ed.select(of("Paperino.svg"))
ed.delete()
spin()
check("7 progetto aperto da file: il nome resta quello del file", w.project_stem() == "Fumetti"
      and "Fumetti" in w.windowTitle(), (w.project_stem(), w.windowTitle()))
check("7 il dato non finisce nel file del progetto", "name_auto" not in open(target, "rb").read().decode("utf-8", "replace"))

# 3b l'ordine d'importazione, non quello alfabetico
w.editor.dirty = False
w.file_new()
spin()
ed = w.editor
w.import_files([svg("Zeta.svg", 10)])
spin()
w.import_files([svg("Alfa.svg", 50)])
spin()
check("3b Zeta e poi Alfa: «Zeta»", ed.doc.name == "Zeta", ed.doc.name)
ed.select(of("Zeta.svg"))
ed.delete()
spin()
check("3b cancellato Zeta: «Alfa»", ed.doc.name == "Alfa", ed.doc.name)
ed.undo()
spin()
check("3b Annulla: di nuovo «Zeta» (il primo importato, non il primo in ordine alfabetico)", ed.doc.name == "Zeta",
      ed.doc.name)

# 8
w.editor.dirty = False
w.file_new()
spin()
ed = w.editor
check("8 Nuovo progetto: «Senza titolo», nome non automatico", ed.doc.name == tr("Senza titolo")
      and not ed.doc.name_auto)
ed.add([RectShape(10, 10)])
w.import_files([svg("Topolino.svg")])
spin()
check("8 progetto con forme già disegnate: importare non cambia il nome (come prima)",
      ed.doc.name == tr("Senza titolo"), ed.doc.name)
check("8 documento nuovo: nome non automatico", Document().name_auto is False)

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati", flush=True)

from _uscita import esci  # noqa: E402

esci(code_)
