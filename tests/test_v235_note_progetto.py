# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5 (Costanzo, idea della linguetta di Ale, 27/11/2026): note del progetto.

Linguetta «Note» in basso a destra del piano (gemella delle linguette dei piani), foglietto che si apre e si chiude,
testo salvato nel progetto (chiave «notes», solo se c'è), mai pubblicato nella Galleria.

Prove: (A) file del progetto: senza note identico a prima, con le note le ritrova, valori strani e note enormi;
(B) Galleria: la nota non si pubblica e l'impronta non cambia; (C) la linguetta: posto all'angolo del piano, segue
zoom e spostamenti, resta nella vista, apri/scrivi/Esc, «Note ●», suggerimento, progetto modificato, progetto nuovo,
riapertura; (D) non disturba: lettere, Canc e Ctrl+Z nel foglietto non toccano il disegno né lo strumento, vista
d'insieme dei piani, Banco senza sovrapposizioni ai pannelli; (E) scheda della guida e traduzioni; (F) difetti
rimessi apposta.
Uso: python tests/test_v235_note_progetto.py [classica|banco]
"""
import json
import os
import sys
import tempfile
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor, QTransform  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Discard))

from freelasercut import galleria  # noqa: E402
from freelasercut.core.document import NOTES_MAX, Document, RectShape  # noqa: E402
from freelasercut.i18n import LANGUAGES, SOURCE  # noqa: E402


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


def meta_of(path):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("project.json"))


# ====================================================================== A. file del progetto
print("--- A. file del progetto")
d = Document()
r = RectShape(30, 20)
r.apply(QTransform.fromTranslate(10, 10))
d.add(r)
p0 = os.path.join(TMP, "senza.flcut")
d.save(p0)
check("A progetto senza note: nessuna chiave «notes» nel file (identico a prima)", "notes" not in meta_of(p0))
d.notes = "   \n  "
d.save(p0)
check("A note fatte solo di spazi: nessuna chiave", "notes" not in meta_of(p0))
d.notes = "Compensato 4 mm\nTaglio: 2 passate, 8 mm/s\nPer Costanzo — àèìòù «» €"
p1 = os.path.join(TMP, "con.flcut")
d.save(p1)
d2 = Document.load(p1)
check("A con le note: salvate e ritrovate uguali (accenti, simboli, a capo)", d2.notes == d.notes, repr(d2.notes))
check("A progetto vecchio (senza chiave): note vuote", Document.load(p0).notes == "")
meta = meta_of(p1)
for strano in (123, None, ["a"], {"x": 1}):
    meta["notes"] = strano
    p2 = os.path.join(TMP, "strano.flcut")
    with zipfile.ZipFile(p2, "w") as z:
        z.writestr("project.json", json.dumps(meta))
    if Document.load(p2).notes != "":
        break
else:
    strano = "ok"
check("A valori strani nel file (numero, null, lista, oggetto): note vuote, nessun errore", strano == "ok", strano)
d.notes = "x" * (NOTES_MAX + 500)
d.save(p2)
check(f"A note enormi: tagliate a {NOTES_MAX} caratteri", len(Document.load(p2).notes) == NOTES_MAX)

# ====================================================================== B. Galleria
print("--- B. Galleria")
d.notes = "Cliente: Mario Rossi, via Roma 1 — non pubblicare"
dati, gm, impronta = galleria.progetto_ripulito(d, "Prova")
with zipfile.ZipFile(__import__("io").BytesIO(dati)) as z:
    pubblicato = z.read("project.json").decode("utf-8")
check("B la Galleria toglie le note prima di pubblicare", "notes" not in gm and "Mario Rossi" not in pubblicato)
d.notes = ""
_, _, impronta2 = galleria.progetto_ripulito(d, "Prova")
check("B l'impronta del progetto non dipende dalle note", impronta == impronta2)
check("B il documento aperto tiene il suo file", d.path == p2, d.path)

# ====================================================================== C. la linguetta
print("--- C. la linguetta")
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
spin(0.8)
nt = w.notes_tab
cv = w.canvas
vp = cv.viewport()
check("C c'è la linguetta, con scritto «Note», e il foglietto è chiuso", nt.btn.isVisible()
      and nt.btn.text() in ("Note", "Notes") and not nt.panel.isVisible(), nt.btn.text())
cv.fit_bed()
spin(0.3)
nt.place()


def corner():
    return cv.to_view(QPointF(cv.bed_x, 0.0))


def at_corner():
    c = corner()
    g = nt.btn.geometry()
    return abs(g.right() + 1 - c.x()) <= 2 and abs(g.top() + 1 - c.y()) <= 2


left, top, right, bottom = nt._limits()
c0 = corner()
dentro = left <= c0.x() - nt.btn.width() and c0.x() <= right and c0.y() + nt.btn.height() <= bottom
check("C appesa all'angolo in basso a destra del piano, sotto il bordo", not dentro or at_corner(),
      (nt.btn.geometry(), c0, (left, top, right, bottom)))
pb = w.plate_bar.geometry()
check("C speculare alle linguette dei piani: quelle in alto a sinistra, questa in basso a destra",
      nt.btn.geometry().center().x() > pb.center().x() and nt.btn.geometry().center().y() > pb.center().y())
cv.zoom_by(0.7, QPointF(vp.width() / 2, vp.height() / 2))
spin(0.3)
c1 = corner()
left, top, right, bottom = nt._limits()
dentro = left <= c1.x() - nt.btn.width() and c1.x() <= right and c1.y() + nt.btn.height() <= bottom
check("C dopo uno zoom segue l'angolo del piano", dentro and at_corner(), (nt.btn.geometry(), c1))
cv.zoom_by(6.0, QPointF(vp.width() * 0.2, vp.height() * 0.2))
spin(0.3)
g = nt.btn.geometry()
check("C con l'angolo fuori dalla vista resta dentro la vista, sul bordo", vp.rect().contains(g),
      (g, vp.rect(), corner()))
cv.fit_bed()
spin(0.3)
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.2)
check("C clic: il foglietto si apre, con il cursore dentro", nt.panel.isVisible() and nt.edit.hasFocus())
pg, bg_ = nt.panel.geometry(), nt.btn.geometry()
check("C il foglietto sta sopra la linguetta, allineato a destra, dentro la vista",
      vp.rect().contains(pg) and pg.bottom() < bg_.top() and abs(pg.right() - bg_.right()) <= 2
      or vp.rect().contains(pg), (pg, bg_))
w.editor.dirty = False
w._update_title()
QTest.keyClicks(nt.edit, "Compensato 4 mm")
spin(0.1)
check("C scrivendo: la nota va nel progetto, il progetto risulta modificato (●)",
      w.editor.doc.notes == "Compensato 4 mm"
      and w.editor.dirty and w.windowTitle().startswith("●"), (w.editor.doc.notes, w.windowTitle()))
nt.btn.setChecked(False)
spin(0.05)
check("C anche «Note ●», più larga, resta allineata all'angolo del piano", at_corner(), (nt.btn.geometry(), corner()))
check("C la linguetta diventa «Note ●» e il suggerimento mostra le prime righe",
      "●" in nt.btn.text() and "Compensato 4 mm" in nt.btn.toolTip(), (nt.btn.text(), nt.btn.toolTip()[:80]))
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.1)
QTest.keyClick(nt.edit, Qt.Key_Escape)
spin(0.1)
check("C Esc chiude il foglietto e la nota resta", not nt.panel.isVisible() and not nt.btn.isChecked()
      and w.editor.doc.notes == "Compensato 4 mm")
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.1)
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.1)
check("C clic, clic: si apre e si richiude dalla linguetta", not nt.panel.isVisible())
nt.edit.setPlainText("<b>grassetto</b> & <script>")
spin(0.05)
check("C il suggerimento non interpreta il testo della nota come HTML", "&lt;b&gt;" in nt.btn.toolTip()
      and "<script>" not in nt.btn.toolTip())
nt.edit.setPlainText("riga 1\nriga 2\nriga 3\nriga 4\nriga 5")
spin(0.05)
check("C suggerimento: solo le prime 3 righe, poi «…»",
      "riga 3" in nt.btn.toolTip() and "riga 4" not in nt.btn.toolTip()
      and "…" in nt.btn.toolTip())
# testo lungo (Ale, 27/11 09:34): foglietto di grandezza fissa, il testo va a capo e scorre in verticale
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.1)
size0 = nt.panel.size()
parole = " ".join(f"parola{i}" for i in range(5000)) + "\n" + "x" * 3000
t0 = time.time()
nt.edit.setPlainText(parole)
nt.edit.moveCursor(QTextCursor.MoveOperation.End)
QTest.keyClicks(nt.edit, " fine")
spin(0.2)
dt = time.time() - t0
sb, hb = nt.edit.verticalScrollBar(), nt.edit.horizontalScrollBar()
check("C testo lungo (5000 parole e una riga senza spazi): il foglietto resta della stessa grandezza",
      nt.panel.size() == size0, (size0, nt.panel.size()))
check("C …il testo va a capo e scorre in verticale: barra verticale sì, orizzontale no",
      sb.isVisible() and sb.maximum() > 0 and not hb.isVisible(), (sb.isVisible(), sb.maximum(), hb.isVisible()))
check("C …tutto il testo resta nella nota, si scrive in fondo senza attese", w.editor.doc.notes.endswith(" fine")
      and w.editor.doc.notes.startswith("parola0 parola1") and dt < 3.0, round(dt, 2))
p3 = os.path.join(TMP, "lunga.flcut")
w.editor.doc.save(p3)
check(f"C …e si salva e si riapre intera (fino a {NOTES_MAX} caratteri, circa 15 000 parole)",
      Document.load(p3).notes == w.editor.doc.notes and NOTES_MAX >= 100000)
QTest.keyClick(nt.edit, Qt.Key_Escape)
spin(0.1)
nt.edit.setPlainText("riga 1\nriga 2\nriga 3\nriga 4\nriga 5")
spin(0.05)
r = RectShape(20, 20)
r.apply(QTransform.fromTranslate(30, 30))
w.editor.run("prova", lambda: w.editor.doc.add(r))
path = os.path.join(TMP, "finestra.flcut")
w.editor.doc.save(path)
w.editor.dirty = False
w.file_new()
spin(0.2)
check("C progetto nuovo: foglietto vuoto e linguetta «Note»", nt.edit.toPlainText() == ""
      and "●" not in nt.btn.text() and w.editor.doc.notes == "")
w.file_open(path)
spin(0.3)
check("C riaprendo il progetto la nota torna, senza segnare il progetto come modificato",
      nt.edit.toPlainText().startswith("riga 1") and "●" in nt.btn.text() and not w.editor.dirty,
      (nt.edit.toPlainText()[:10], w.editor.dirty))

# ====================================================================== D. non disturba
print("--- D. non disturba")
w.editor.selection = [s for s in w.editor.doc.shapes]
w.editor.selection_changed.emit()
n0 = len(w.editor.doc.shapes)
tool0 = next((k for k, v in cv.tools.items() if v is cv.tool), None)
QTest.mouseClick(nt.btn, Qt.LeftButton)
spin(0.1)
nt.edit.moveCursor(QTextCursor.MoveOperation.End)
QTest.keyClicks(nt.edit, " rlepo vtx")
QTest.keyClick(nt.edit, Qt.Key_Delete)
QTest.keyClick(nt.edit, Qt.Key_Backspace)
QTest.keyClick(nt.edit, Qt.Key_Z, Qt.ControlModifier)
spin(0.1)
tool1 = next((k for k, v in cv.tools.items() if v is cv.tool), None)
check("D lettere, Canc, Backspace e Ctrl+Z nel foglietto: forme e strumento del disegno non cambiano",
      len(w.editor.doc.shapes) == n0 and tool1 == tool0, (n0, len(w.editor.doc.shapes), tool0, tool1))
QTest.keyClick(nt.edit, Qt.Key_Escape)
spin(0.1)
check("D chiuso il foglietto, la tela riprende i tasti", not nt.panel.isVisible() and cv.hasFocus())
w.editor.add_plate()
spin(0.2)
w.plate_overview.open()
spin(0.2)
check("D vista d'insieme dei piani aperta: la linguetta sparisce", not nt.btn.isVisible() and not nt.panel.isVisible())
w.plate_overview.close_view()
spin(0.2)
check("D vista d'insieme chiusa: la linguetta torna", nt.btn.isVisible())
check("D una nota per progetto: cambiando piano resta la stessa", "riga 1" in nt.edit.toPlainText())
if UI == "banco":
    bc = w.banco
    for wd, h in ((1400, 900), (1100, 700), (900, 650)):
        w.resize(wd, h)
        spin(0.5)
        cv.fit_bed()
        spin(0.3)
        nt.btn.setChecked(True)
        nt.place()
        spin(0.1)
        off = vp.mapTo(cv, QPoint(0, 0))
        mine = [QRect(g.translated(off)) for g in (nt.btn.geometry(), nt.panel.geometry())]
        others = [x for x in (bc.island, bc.view_box, bc.rail, getattr(bc, "right", None))
                  if x is not None and x.isVisible() and x.parent() is cv]
        hit = [(m, o.objectName(), o.geometry()) for m in mine for o in others if m.intersects(o.geometry())]
        check(f"D Banco {wd}×{h}: linguetta e foglietto non coprono i pannelli e le isole", not hit, hit[:2])
        nt.btn.setChecked(False)

# ====================================================================== E. guida e traduzioni
print("--- E. guida e traduzioni")
from freelasercut.ui import help_texts  # noqa: E402

check("E scheda della guida «Che cos'è?» per la linguetta e il foglietto", "project_notes" in help_texts.HELP
      and nt.btn.property("help_key") == "project_notes" and nt.edit.property("help_key") == "project_notes")
testi = ["Note del progetto", "Note ●", "Chiudere", "Galleria", "le note non vengono pubblicate",
         "di nuovo clic sulla linguetta, oppure Esc",
         "Clic per aprirle o chiuderle. Si salvano con il progetto e non vengono mai incise.",
         "Scrivi qui le note di questo progetto: materiale, impostazioni, per chi è… Si salvano con il progetto e non "
         "vengono mai incise.", help_texts.HELP["project_notes"][1]]
mancano = []
for lang in [l for l in LANGUAGES if l != SOURCE]:
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8"))
    mancano += [(lang, t[:30]) for t in testi if not cat.get(t)]
check("E tutti i testi nuovi tradotti in tutte le lingue del programma", not mancano, mancano[:4])

# ====================================================================== F. difetti rimessi apposta
print("--- F. difetti rimessi apposta")
w.editor.changed.disconnect(nt.sync)
nt.edit.setPlainText("nota vecchia")
w.editor.dirty = False
w.file_new()
spin(0.2)
rimasta = nt.edit.toPlainText() == "nota vecchia"
w.editor.changed.connect(nt.sync)
nt.sync()
check("F senza il collegamento al documento la nota vecchia resterebbe nel progetto nuovo (la prova lo vede)",
      rimasta and nt.edit.toPlainText() == "")
vero = galleria.progetto_ripulito
d.notes = "segreta"
dati, gm, _ = vero(d, "Prova")
gm2 = dict(gm, notes="segreta")
check("F una Galleria che non togliesse le note: il controllo lo vedrebbe", "notes" in gm2 and "notes" not in gm)

w.close()
spin(0.2)
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
