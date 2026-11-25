# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.10: nel Banco la scheda di uno strato non si allarga più (segnalato da Rino; Ale, 25/11/2026).

Fino alla 0.22.9, togliendo la spunta «Incidi» la riga sotto il nome diventava «… · non inciso»: la scheda passava da
271 a 339 pixel in un riquadro largo 300, e la modalità (LINEA), Velocità e Potenza uscivano dal bordo. Con «aria» e
«pausa prima» si arrivava a 434. Ora «non inciso» sta sulla riga del nome (come proposto da Ale) e le due righe di
testo non possono allargare la scheda: se non ci stanno finiscono con «…», e il testo intero è nel suggerimento.

Casi: larghezza della scheda uguale con lo strato inciso e non inciso, e con tutte le aggiunte; caselle dentro il
riquadro; «non inciso» sulla riga del nome solo quando lo strato non si incide; riga sotto senza «non inciso»; testo
intero nel suggerimento; nome lungo accorciato con «…»; traduzioni. Difetto rimesso apposta: la riga sotto con
un'etichetta normale (come nella 0.22.9) allarga di nuovo la scheda.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco"
for k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QSpinBox  # noqa: E402

app = QApplication([])

from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui import banco as B  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info != "" and not cond else ""))


w = MainWindow()
w.resize(1400, 850)
w.show()
app.processEvents()
r = RectShape(30, 20)
w.editor.doc.add(r)
w.editor.changed.emit()
app.processEvents()
rail = w.findChildren(B.LayerRail)[0]
cs = w.editor.doc.layer(r.layer)
rail.open_index = cs.index


def refresh():
    rail.rebuild()
    app.processEvents()
    w.banco.relayout()
    app.processEvents()
    app.processEvents()
    return rail.box.itemAt(0).widget()


def inside(card):
    """Le caselle della scheda aperta stanno dentro il riquadro degli strati?"""
    vp = rail.area.viewport()
    bad = []
    for wd in card.findChildren(QComboBox) + card.findChildren(QSpinBox):
        if not wd.isVisible():
            continue
        right = wd.mapTo(vp, wd.rect().topRight()).x()
        if right > vp.width():
            bad.append((type(wd).__name__, right))
    return bad


def texts(card):
    return [lab.text() for lab in card.findChildren(QLabel) if lab.isVisible()]


cs.output, cs.air, cs.pause_before = True, False, False
c0 = refresh()
w0 = c0.minimumSizeHint().width()
view = rail.area.viewport().width()
check("strato inciso: la scheda sta nel riquadro", w0 <= view and not inside(c0), (w0, view, inside(c0)))
check("…e «non inciso» non c'è", not any("non inciso" in t for t in texts(c0)), texts(c0))

cs.output = False
c1 = refresh()
w1 = c1.minimumSizeHint().width()
check("Incidi tolto (il caso di Rino): la scheda non si allarga", w1 == w0 and c1.width() <= view, (w0, w1, c1.width(), view))
check("…caselle (LINEA, Velocità, Potenza) dentro il riquadro", not inside(c1), inside(c1))
off = [lab for lab in c1.findChildren(QLabel) if lab.objectName() == "bcOff"]
name = [lab for lab in c1.findChildren(QLabel) if lab.objectName() == "bcTitle" and lab.text().startswith(cs.label()[:2])]
check("«non inciso» sulla riga del nome, accanto al nome dello strato (proposta di Ale)",
      len(off) == 1 and off[0].text() == "non inciso" and name
      and abs(off[0].mapTo(c1, off[0].rect().center()).y() - name[0].mapTo(c1, name[0].rect().center()).y()) <= 3,
      [(lab.objectName(), lab.text()) for lab in c1.findChildren(QLabel)])
summ = [lab for lab in c1.findChildren(B._ElideLabel) if lab.objectName() == "bcMuted"]
check("…e non più nella riga sotto", summ and "non inciso" not in summ[0].fulltext, summ and summ[0].fulltext)
head = c1.findChild(B._ClickFrame)
check("il suggerimento della riga dice tutto (nome, non inciso, valori)", head is not None and "non inciso" in head.toolTip()
      and "mm/min" in head.toolTip(), head and head.toolTip())

cs.air, cs.pause_before, cs.passes, cs.speed = True, True, 12, 12000
c2 = refresh()
check("con aria, pausa prima e 12 passate (prima 434 pixel): stessa larghezza, caselle dentro",
      c2.minimumSizeHint().width() == w0 and not inside(c2), (c2.minimumSizeHint().width(), inside(c2)))
s2 = [lab for lab in c2.findChildren(B._ElideLabel) if lab.objectName() == "bcMuted"][0]
check("…la riga troppo lunga finisce con «…», il testo intero resta", s2.text() != s2.fulltext and s2.text().endswith("…")
      and "pausa prima" in s2.fulltext, (s2.text(), s2.fulltext))

cs.name = "Strato con un nome lunghissimo per vedere se allarga la scheda"
c3 = refresh()
check("nome lunghissimo: accorciato, la scheda non si allarga", c3.minimumSizeHint().width() == w0 and not inside(c3),
      c3.minimumSizeHint().width())
cs.name = ""

for lang, word in (("en", "not engraved"), ("es", "no se graba"), ("fr", "non gravé"), ("pt", "não gravado")):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    check(f"«non inciso» tradotto ({lang})", cat.get("non inciso") == word, cat.get("non inciso"))

# difetto rimesso apposta: la riga sotto con un'etichetta normale, come nella 0.22.9
real = B._ElideLabel


class Plain(QLabel):
    def __init__(self, text, name=None):
        super().__init__(text)
        self.fulltext = text
        if name:
            self.setObjectName(name)


B._ElideLabel = Plain
cs.output = False
c4 = refresh()
B._ElideLabel = real
check("difetto rimesso apposta (riga normale, come nella 0.22.9): la prova se ne accorge",
      c4.minimumSizeHint().width() > view, (c4.minimumSizeHint().width(), view))

print(f"{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
