# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.11: di MakerHub resta il collegamento diretto (funzione in prova, dietro il codice amministratore).

MakerHub (maker-hub.it) è un servizio esterno. La 0.18.10 aveva anche «FreeLaserCut Live» (codice, ascolto, disegni
che arrivano sul piano): sul loro sito non è ancora attivo, quindi è stato tolto. Qui non parte nessuna chiamata di
rete: l'apertura del browser è sostituita da un finto che annota l'indirizzo.

Casi provati:
1 indirizzo: è quello verificato da Ale, https e di maker-hub.it; gli indirizzi diversi non si aprono;
2 il Live non c'è più: niente rete, fili, finestra, menu in alto; l'import di SVG e DXF è tornato quello di prima;
3 icona: logo a colori, grande come le altre icone degli strumenti, angoli trasparenti, leggibile sul tema chiaro e
  su quello scuro, anche spenta;
4 finestra: nascosta senza codice (e non apre niente); con il codice sta nel menu Strumenti con gli altri strumenti;
  un clic apre il browser sull'indirizzo giusto e la barra in basso dice che cosa fare; browser che non si apre;
  ricerca dei comandi del Banco; di nuovo nascosta;
5 testi: scheda d'aiuto, traduzioni nuove nelle 4 lingue, traduzioni del Live tolte.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
boxes = []
QMessageBox.question = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Ok)
opened = []
browser = [True]  # False = il sistema non riesce ad aprire il browser
QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or browser[0])

from freelasercut import admin, theme  # noqa: E402
from freelasercut import makerhub as mh  # noqa: E402
from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import Document  # noqa: E402
from freelasercut.ui import help_texts, style  # noqa: E402

results = []
URL = "https://app.maker-hub.it/?pagina=laser&scheda=scatola&da=freelasercut"  # verificato da Ale l'11/11/2026


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


# ================================================================== 1. indirizzo
check("l'indirizzo è quello della Scatola a incastri, con il segno che arrivi da FreeLaserCut",
      mh.BOX_URL == URL and mh.safe_url(mh.BOX_URL) == URL)
check("si aprono solo indirizzi https di maker-hub.it: mai http, un altro sito, un sosia, utente@",
      mh.safe_url("https://maker-hub.it/") and not any(mh.safe_url(u) for u in (
          "http://app.maker-hub.it/", "https://example.com/", "https://maker-hub.it.example.com/",
          "https://finto-maker-hub.it/", "https://maker-hub.it@example.com/", "https://utente:x@maker-hub.it/",
          "javascript:alert(1)", "file:///C:/Windows/win.ini", "", None, "https://[::1")))
good, mh.BOX_URL = mh.BOX_URL, "https://example.com/?pagina=laser"
check("se l'indirizzo non fosse di MakerHub il browser non verrebbe aperto", mh.open_box() is False and not opened, opened)
mh.BOX_URL = good

# ================================================================== 2. il Live non c'è più
code = src("freelasercut", "makerhub.py")
check("makerhub.py non fa rete e non avvia fili: niente richieste, niente «ponte», niente token",
      not re.search(r"urllib\.request|urlopen|http\.client|socket|requests|threading|/ponte|token|QNetwork", code))
check("i file del Live sono stati tolti dal programma e dalle prove",
      not os.path.exists(os.path.join(ROOT, "freelasercut", "ui", "dialogs_makerhub.py"))
      and not os.path.exists(os.path.join(ROOT, "tests", "test_v1810_makerhub.py"))
      and "test_v1810" not in src("tests", "run_tests.py") and "test_v1811_makerhub.py" in src("tests", "run_tests.py"))
others = [os.path.join(d, f) for d, _s, fs in os.walk(os.path.join(ROOT, "freelasercut")) for f in fs
          if f.endswith(".py") and f != "makerhub.py"]
left = [os.path.relpath(p, ROOT) for p in others
        if re.search(r"makerhub_token|makerhub_tools|makerhub_send_machine|dialogs_makerhub|maker-hub\.it/ponte|plan_job",
                     open(p, encoding="utf-8").read())]
check("nel resto del programma non resta niente del collegamento con il loro server", not left, left)
check("l'import di SVG e DXF è tornato quello di prima (senza il parametro aggiunto per il Live)",
      "layer_of" not in src("freelasercut", "core", "io_formats.py"))
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="70mm" viewBox="0 0 100 70">'
       '<rect x="0" y="0" width="100" height="70" fill="none" stroke="#FF0000"/></svg>')
shapes = io_formats.import_svg(svg.encode(), Document())
b = shapes[0].bounds()
check("un SVG con le misure in mm (come quelli scaricati da MakerHub) si importa a misura vera",
      len(shapes) == 1 and abs(b.width() - 100) < 0.01 and abs(b.height() - 70) < 0.01, b)

# ================================================================== 3. icona
ic = mh.icon()
ref = style.icon("puzzle")
sizes = sorted(s.width() for s in ic.availableSizes())
check("icona: c'è, a più risoluzioni, e nella misura base è grande come quelle degli altri strumenti",
      not ic.isNull() and sizes == sorted(s.width() for s in ref.availableSizes()) + [60] and sizes[0] == 20
      and ic.actualSize(QSize(16, 16)) == ref.actualSize(QSize(16, 16))
      and ic.actualSize(QSize(20, 20)) == ref.actualSize(QSize(20, 20)), (sizes, [s.width() for s in ref.availableSizes()]))
img = ic.pixmap(QSize(40, 40)).toImage()
mid = img.pixelColor(20, 4)  # nella fascia arancione sopra il chip
corner = img.pixelColor(0, 0)
round_ = img.pixelColor(4, 4)  # dentro il riquadro, ma nello spicchio tolto dall'angolo tondo
check("il logo è a colori (arancione MakerHub), con gli angoli tondi e trasparenti e il segno bianco dentro",
      mid.red() > 200 and 60 < mid.green() < 130 and mid.blue() < 60 and mid.alpha() == 255 and corner.alpha() == 0
      and round_.alpha() < 60 and any(img.pixelColor(x, 20).lightness() > 230 for x in range(8, 32)),
      (mid.getRgb(), corner.getRgb(), round_.getRgb()))
inked = [x for x in range(40) if img.pixelColor(x, 20).alpha() > 128]
ref_img = ref.pixmap(QSize(40, 40)).toImage()
ref_ink = [x for x in range(40) for y in range(40) if ref_img.pixelColor(x, y).alpha() > 128]
check("il riquadro occupa la casella come i disegni delle altre icone (un po' di margine, non tutta)",
      2 <= inked[0] <= 4 and 35 <= inked[-1] <= 37 and abs((inked[-1] - inked[0]) - (max(ref_ink) - min(ref_ink))) <= 5,
      (inked[0], inked[-1], min(ref_ink), max(ref_ink)))


def lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b_):
    la, lb = sorted((lum(a), lum(b_)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


orange = mid.getRgb()[:3]
worst = min(contrast(orange, rgb(t[k])) for t in (theme.DARK, theme.LIGHT) for k in ("panel", "panel2"))
check("l'arancione si stacca dal fondo dei menu sia nel tema scuro sia in quello chiaro (contrasto ≥ 3)",
      worst >= 3.0, round(worst, 2))
off = ic.pixmap(QSize(40, 40), QIcon.Mode.Disabled).toImage().pixelColor(20, 4)
check("spenta (voce non disponibile) è grigia e attenuata, come le altre",
      abs(off.red() - off.green()) < 12 and abs(off.green() - off.blue()) < 12 and 40 < off.alpha() < 200, off.getRgb())

# ================================================================== 4. finestra
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
from freelasercut.ui.main_window import MainWindow  # noqa: E402

threads0 = {t.name for t in threading.enumerate()}
w = MainWindow()
w.resize(1400, 900)
act = w.acts["makerhub_box"]
pal = getattr(getattr(w, "banco", None), "palette", None)
check("senza codice: la voce è nascosta e non apre niente", not act.isVisible() and w.makerhub_box() is False and not opened)
if pal is not None:
    check("Banco: senza codice la ricerca dei comandi non la trova",
          act not in (pal.collect(), [a_ for a_, _p in pal.entries])[1])
tops = [a_.text().replace("&", "") for a_ in w.menuBar().actions()]
check("in alto non c'è più il menu MakerHub, e non restano la finestra né l'ascolto della 0.18.10",
      "MakerHub" not in tops and not hasattr(w, "makerhub") and "makerhub" not in w.acts
      and not [t.name for t in threading.enumerate() if "makerhub" in t.name.lower()], tops)
check("con il codice la voce compare", w.admin_dialog(code="prova") is True and act.isVisible()
      and w.acts["relief"].isVisible() and w.acts["print_cut"].isVisible())
tools = [m.menu() for m in w.menuBar().actions() if m.menu() is not None and w.acts["puzzle"] in m.menu().actions()]
acts = tools[0].actions() if tools else []
check("sta nel menu Strumenti, insieme a Puzzle, Scultura 3D e alle altre funzioni in prova, prima delle voci per le foto",
      len(tools) == 1 and act in acts and acts.index(w.acts["puzzle"]) < acts.index(w.acts["sculpt"]) < acts.index(act)
      and acts.index(act) == acts.index(w.acts["print_cut"]) + 1 and acts.index(act) < acts.index(w.acts["photo"]),
      [a_.text() for a_ in acts][-12:])
check("si chiama «MakerHub – Scatola a incastri» e ha il logo", act.text() == "MakerHub – Scatola a incastri"
      and not act.icon().isNull() and act.icon().pixmap(QSize(40, 40)).toImage().pixelColor(20, 4).red() > 200)
if pal is not None:
    check("Banco: con il codice la ricerca dei comandi la trova", act in (pal.collect(), [a_ for a_, _p in pal.entries])[1])
del opened[:], boxes[:]
dialogs0 = len(w.findChildren(QDialog))
act.trigger()
msg = w.statusBar().currentMessage()
check("un clic apre nel browser, una volta, proprio la pagina della Scatola a incastri", opened == [URL], opened)
check("…e la barra in basso dice che cosa fare: scaricare l'SVG, File → Importa, niente seconda compensazione del kerf",
      "SVG" in msg and "File → Importa" in msg and "kerf" in msg and "non compensarlo di nuovo" in msg, msg)
check("…senza finestre né domande", not boxes and len(w.findChildren(QDialog)) == dialogs0)
browser[0] = False
del opened[:]
ok = w.makerhub_box()
msg = w.statusBar().currentMessage()
check("se il browser non si apre lo dice, con l'indirizzo da copiare", ok is False and opened == [URL] and URL in msg, msg)
browser[0] = True
time.sleep(0.3)
app.processEvents()
check("nessun filo in più dopo l'avvio e il clic: FreeLaserCut non resta in ascolto di niente",
      not [t for t in threading.enumerate() if "makerhub" in t.name.lower()])
check("il laser e la macchina non vengono toccati", not w.ctl.job_active and not w.ctl.connected and not w.editor.doc.shapes)
check("nascondendo di nuovo le funzioni in prova la voce sparisce e non apre più niente",
      w.admin_dialog() is False and not act.isVisible() and not opened[1:] and w.makerhub_box() is False and opened == [URL])

# ================================================================== 5. testi
h = help_texts.lookup("makerhub_box")
check("scheda d'aiuto: dice che è un servizio esterno, come si porta il disegno qui e che non va compensato di nuovo",
      h is not None and "esterno" in h[1] and "File → Importa" in h[1] and "kerf" in h[1]
      and help_texts.lookup("makerhub") is None, h)
keys = set()
for text in (code, src("freelasercut", "ui", "main_window.py")):
    for m in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', text):
        parts = re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1))
        try:
            k = "".join(json.loads(p_) for p_ in parts)
        except ValueError:
            continue
        if "MakerHub" in k or "browser" in k:
            keys.add(k)
check("testi nuovi da tradurre trovati", len(keys) == 4, sorted(keys))
menu_names = {"en": "File → Import", "es": "Archivo → Importar", "fr": "Fichier → Importer", "pt": "Arquivo → Importar"}
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    brand = [k for k in keys if "MakerHub" in k and "MakerHub" not in (loc.get(k) or "MakerHub")]
    tip = next((loc.get(k) or "" for k in keys if "File → Importa" in k), "")
    check(f"traduzioni {lang}: i 4 testi, con il nome MakerHub intatto e il menu File → Importa chiamato come in quella lingua",
          not miss and not bad and not brand and menu_names[lang] in tip, (miss, bad, brand, tip))
    old = [k for k in loc if re.search(r"Collega MakerHub|FreeLaserCut Live|Manda a FreeLaserCut|Genera il codice|"
                                       r"Di' a MakerHub|^Aggiorna l'elenco$|Scollegato: FreeLaserCut", k)]
    check(f"traduzioni {lang}: i testi del Live non ci sono più", not old and len([k for k in loc if "MakerHub" in k]) == 3,
          (old[:3], [k for k in loc if "MakerHub" in k]))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
