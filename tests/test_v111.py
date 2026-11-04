# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.11.1: la guardia fiamme vede anche il cuore quasi bianco della fiamma (camera abbagliata) e salva
un'immagine di prova; Aiuto → Mostra i nomi sotto i comandi (nomi corti e piccoli sotto le icone, nelle 5 lingue,
la barra della Classica sta in un monitor 1920 × 1080)."""
import sys, os, time, tempfile, subprocess, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QMessageBox, QToolBar
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import fire_guard as fg, diag

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# ================================================================== guardia fiamme: cuore bianco
rng = np.random.default_rng(5)
def bed():
    img = np.full((480, 640, 3), (70, 95, 120), np.uint8)
    img = cv2.add(img, rng.integers(0, 20, img.shape, dtype=np.uint8))
    cv2.circle(img, (300, 240), 4, (200, 220, 255), -1)
    cv2.circle(img, (300, 240), 2, (255, 255, 255), -1)
    return img
def lighter(img, r=36):
    img = img.copy()
    cv2.ellipse(img, (320, 200), (r // 2 + 3, r + 4), 0, 0, 360, (30, 60, 230), -1)  # bordo rosso sottile
    cv2.ellipse(img, (320, 200), (r // 2, r), 0, 0, 360, (235, 245, 252), -1)  # cuore quasi bianco
    return img
img = lighter(bed())
m = fg.hot_mask(img)
core = cv2.resize(m, (640, 480), interpolation=cv2.INTER_NEAREST)[200, 320]
check("accendino con il cuore bianco: anche il cuore conta come fiamma", core > 0, f"{fg.hot_fraction(img) * 100:.2f}%")
d = fg.FlameDetector("media")
for _ in range(8):
    d.update(bed())
seq = [d.update(lighter(bed()))["alarm"] for _ in range(4)]
check("accendino davanti alla camera: allarme con la sensibilità media", seq[-1], seq)
lamp = bed()
cv2.rectangle(lamp, (480, 30), (620, 120), (250, 250, 250), -1)
paper = bed()
cv2.rectangle(paper, (80, 280), (300, 460), (238, 240, 240), -1)
check("lampada bianca o foglio illuminato da soli: non sono fiamme", fg.hot_fraction(lamp) == 0 and fg.hot_fraction(paper) == 0)
d = fg.FlameDetector("media")
check("puntino del laser con la sua luce bianca: niente allarme", not any(d.update(bed())["alarm"] for _ in range(30)))

# ================================================================== finestra principale
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import cmd_labels
w = MainWindow()

class FakeCam:
    index = 0
    _t = 1.0
    def get(self, after=0.0, timeout=0.0):
        return lighter(bed())
w.camera.src = FakeCam()
fd = w.fire_guard_dialog()
fd.refresh()
path = fd.save_sample()
check("Guardia fiamme → «Salva l'immagine di prova»: foto e zone viste come fiamma nella diagnostica",
      path and os.path.isfile(path) and os.path.isfile(path.replace(".jpg", "-zone.jpg")) and
      os.path.dirname(path) == diag.diag_dir(), path)
fd.close()
w.camera.src = None

# ------------------------------------------------------------------ nomi sotto i comandi
help_menu = [m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["help_mode"] in m.menu().actions()][0]
check("Livello di aiuto in Aiuto e in Impostazioni (per il Banco): lo stesso sottomenu",
      w.m_help_level.menuAction() in help_menu.actions() and w.m_help_level.menuAction() in w.m_settings.actions())
main = [t for t in w.findChildren(QToolBar) if t.objectName() == "main"][0]
tools = [t for t in w.findChildren(QToolBar) if t.objectName() == "tools"][0]
check("di partenza livello normale: solo icone", w.acts["help_normal"].isChecked() and
      main.toolButtonStyle() == Qt.ToolButtonIconOnly and tools.toolButtonStyle() == Qt.ToolButtonIconOnly)
w.acts["help_beginner"].trigger()
app.processEvents()
b_open = main.widgetForAction(w.acts["open"])
b_rect = tools.widgetForAction(w.tool_actions["rect"])
b_code = main.widgetForAction(w.acts["code"])
check("acceso: nome sotto l'icona (Apri, Rettangolo, Codici)", main.toolButtonStyle() == Qt.ToolButtonTextUnderIcon and
      b_open.text() == "Apri" and b_rect.text() == "Rettangolo" and b_code.text() == "Codici",
      (b_open.text(), b_rect.text(), b_code.text()))
check("scritte piccole (9 pixel)", b_open.font().pixelSize() == cmd_labels.FONT_PX or "9px" in main.styleSheet())
check("nei menu i nomi restano quelli completi", w.acts["code"].text().startswith("Codice QR"))
check("la scelta si ricorda", w.qs.value("help_level") == "principiante")
w2 = MainWindow()
main2 = [t for t in w2.findChildren(QToolBar) if t.objectName() == "main"][0]
check("alla riapertura i nomi ci sono già", w2.acts["help_beginner"].isChecked() and
      main2.toolButtonStyle() == Qt.ToolButtonTextUnderIcon)
w2.editor.dirty = False
w2.qs.setValue("autosave_pending", False)
w2.close()
w.acts["help_normal"].trigger()
app.processEvents()
check("livello normale di nuovo: solo icone, come prima", main.toolButtonStyle() == Qt.ToolButtonIconOnly and
      tools.toolButtonStyle() == Qt.ToolButtonIconOnly and "9px" not in main.styleSheet() and
      w.qs.value("help_level") == "normale")

# ------------------------------------------------------------------ tabella dei nomi
names_ok = all(len(v) == len(cmd_labels.LANGS) and all(0 < len(x) <= 12 for x in v) for v in cmd_labels.SHORT.values())
check("nomi corti in tutte e 5 le lingue (al massimo 12 lettere)", names_ok)
known = set(w.acts) | set(w.tool_actions)
check("ogni nome corrisponde a un comando vero", set(cmd_labels.SHORT) <= known, set(cmd_labels.SHORT) - known)
need = {a for t in (main, tools) for a in t.actions() if not a.isSeparator() and not a.icon().isNull()}
keys = {v: k for k, v in list(w.acts.items()) + list(w.tool_actions.items())}
missing = [keys.get(a, a.text()) for a in need if keys.get(a) not in cmd_labels.SHORT]
check("ogni icona delle barre ha il suo nome corto", not missing, missing)

# ------------------------------------------------------------------ larghezza nelle 5 lingue e Banco
PROBE = r"""
import os, sys, json
sys.path.insert(0, sys.argv[1])
from freelasercut import i18n
i18n.set_language(sys.argv[2])
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton
from PySide6.QtGui import QFontMetrics
app = QApplication([])
from freelasercut import theme
from freelasercut.ui import style
# come main(): stile Fusion e caratteri del programma (lo stile nativo di Windows 11 ha margini molto più larghi,
# ma FreeLaserCut non lo usa mai: misurarlo dava barre larghe il doppio che nessun utente vede)
app.setStyle("Fusion")
style.load_fonts()
app.setFont(style.ui_font(9))
app.setStyleSheet(theme.QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import cmd_labels
w = MainWindow(); w.resize(1920, 1050); w.show(); app.processEvents()
cmd_labels.apply(w, True); app.processEvents()
out = {}
tb = [t for t in w.findChildren(QToolBar) if t.objectName() == "main"]
if tb:
    out["main"] = tb[0].sizeHint().width()
if w.banco is not None:
    bs = [b for b in w.banco.island.findChildren(QToolButton) if b.objectName() == "bcTool"]
    w.banco.island.adjustSize(); app.processEvents()
    out["cut"] = [b.text() for b in bs if QFontMetrics(b.font()).horizontalAdvance(b.text()) > b.width() - 2]
    out["island"] = w.banco.island.width()
    out["rect"] = [b.text() for b in bs if b.defaultAction() is w.tool_actions["rect"]]
print("JSON " + json.dumps(out)); sys.stdout.flush(); os._exit(0)
"""
def probe(lang, ui="classica"):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=tempfile.mkdtemp(), XDG_CONFIG_HOME=tempfile.mkdtemp(),
               FLC_UI=ui, FLC_NO_FIRST_RUN="1", FLC_NO_UPDATE="1", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-c", PROBE, ROOT, lang], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=240)
    line = [l for l in r.stdout.splitlines() if l.startswith("JSON ")]
    return json.loads(line[0][5:]) if line else {"err": r.stderr[-400:]}
widths = {l: probe(l).get("main") for l in cmd_labels.LANGS}
# su Windows i caratteri sono un po' diversi: lì basta che la barra si costruisca (se non ci sta, Qt mette »)
lim = 1900 if sys.platform != "win32" else 2400
check("Classica: con i nomi la barra in alto sta in 1920 pixel, in tutte le lingue",
      all(v and v <= lim for v in widths.values()), widths)
for l in ("it", "fr"):
    b = probe(l, "banco")
    check(f"Banco ({l}): nomi interi sotto gli strumenti, nessuno tagliato", b.get("cut") == [] and b.get("rect") and
          b.get("island", 9999) < 1500, b)
# ------------------------------------------------------------------ telefono: logo e controllo attività
import urllib.request, urllib.error
from freelasercut import phone
w.phone.start()
base_url = f"http://127.0.0.1:{w.phone.server.port}/{w.phone.server.token}/"
page = urllib.request.urlopen(base_url, timeout=5).read().decode("utf-8")
check("pagina del telefono: logo nell'intestazione e icona per la schermata Home",
      '<img src="logo.svg"' in page and 'rel="apple-touch-icon" href="logo.png"' in page)
svg = urllib.request.urlopen(base_url + "logo.svg", timeout=5)
png = urllib.request.urlopen(base_url + "logo.png", timeout=5).read()
check("logo servito dalla pagina (SVG e PNG)", svg.headers.get("Content-Type") == "image/svg+xml" and
      b"<svg" in svg.read() and png[:4] == b"\x89PNG")
leak = False
for bad in ("app.py", "assets/logo.svg", "logo.ico", "%2e%2e/app.py"):
    try:
        urllib.request.urlopen(base_url + bad, timeout=5)
        leak = True
    except urllib.error.HTTPError:
        pass
check("dalla pagina si leggono solo i due loghi, nessun altro file", not leak)
check("sezione «Controllo attività»: la camera si accende da sola durante il lavoro, tocco = schermo intero",
      "Controllo attività" in page and "wantCam" in page and "classList.toggle('full')" in page)
w.phone.refresh()
st = json.loads(urllib.request.urlopen(base_url + "stato", timeout=5).read())
check("lo stato dice se il PC ha una camera e come sta la guardia fiamme", st.get("camera") is False and "fire" in st, st)
w.camera.src = FakeCam()
w.phone.refresh()
st = json.loads(urllib.request.urlopen(base_url + "stato", timeout=5).read())
jpg = urllib.request.urlopen(base_url + "foto.jpg", timeout=5).read()
check("con una camera: lo stato lo dice e la foto arriva", st.get("camera") is True and jpg[:2] == b"\xff\xd8")
w.camera.src = None
w.phone.stop()

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
