# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.4: grandezza dei caratteri (richiesta di un utente con un portatile Mac: «nel laptop risulta molto
piccolo», in tutte e due le interfacce).

Due cose insieme:
1. sul Mac lo schermo conta 72 punti per pollice e non 96: le grandezze scritte in punti uscivano un quarto più piccole
   che su Windows (9 punti = 9 pixel invece di 12). Ora dove lo schermo dichiara meno di 96 le grandezze in punti si
   moltiplicano per 96/quel valore: stessi pixel su tutti i sistemi;
2. Impostazioni → Grandezza dei caratteri (anche nelle Preferenze): Piccoli 85%, Normali, Grandi 115%, Molto grandi 130%,
   Grandissimi 150%. Vale dal riavvio.

Tutte le grandezze passano da freelasercut/fontscale.py. Qui: i conti, ogni punto del programma che scrive una
grandezza, lo schermo a 72 punti per pollice simulato in un processo a parte, la scelta nel menu e nelle Preferenze, e
difetti rimessi apposta.

Uso: python tests/test_v224_caratteri.py [classica|banco]
"""
import json
import os
import re
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
os.environ.pop("FLC_FONT_PERCENT", None)
os.environ.pop("QT_FONT_DPI", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from freelasercut import fontscale as F  # noqa: E402

# ====================================================================== A. i conti
check("A senza setup i fattori valgono 1 (prove e moduli da soli: grandezze di sempre)", (F.k_pt(), F.k_px()) == (1.0, 1.0)
      and F.pt(8.5) == 8.5 and F.px(9) == 9 and F.css("font-size: 9pt;") == "font-size: 9pt;")
check("A fattore della piattaforma: 72 → 4/3, 96 → 1, sopra 96 → 1 (non si tocca), valori assurdi → 1",
      abs(F.platform_factor(72) - 4 / 3) < 1e-9 and F.platform_factor(96) == 1.0 and F.platform_factor(120) == 1.0
      and F.platform_factor(95.8) == 1.0 and F.platform_factor(0) == 1.0 and F.platform_factor("boh") == 1.0
      and F.platform_factor(10) == 1.0 and F.platform_factor(None) == 1.0)
check("A scelta salvata ripulita: una di quelle possibili, la più vicina; il resto 100",
      [F.clean_percent(x) for x in (100, "115", 120, 149, 85.0, 60, 0, -5, "abc", None, 1000, 300)]
      == [100, 115, 115, 150, 85, 85, 100, 100, 100, 100, 100, 150])
F.setup(100, 72)
check("A schermo a 72: i punti × 4/3 (9 → 12, 8,5 → 11,33), i pixel fermi", F.pt(9) == 12.0 and F.pt(8.5) == 11.33
      and F.px(9) == 9 and F.percent == 100 and abs(F.platform - 4 / 3) < 1e-9)
check("A foglio di stile a 72: solo le grandezze in punti",
      F.css("QLabel { font-size: 9pt; } b { font-size:7.5pt } i { font-size: 14px; }")
      == "QLabel { font-size: 12pt; } b { font-size:10pt } i { font-size: 14px; }")
F.setup(130, 96)
check("A scelta 130%: punti e pixel × 1,3", F.pt(10) == 13.0 and F.px(10) == 13 and F.css("a{font-size:10pt;font-size: 10px}")
      == "a{font-size:13pt;font-size: 13px}")
F.setup(150, 72)
check("A i due fattori si moltiplicano (150% su uno schermo a 72: punti × 2, pixel × 1,5)", F.pt(9) == 18.0 and F.px(10) == 15)
check("A testi senza grandezze, o non testi: restano come sono", F.css("color: red;") == "color: red;" and F.css(None) is None
      and F.css("font-size: grande;") == "font-size: grande;")
F.reset()


class FakeQs:
    def __init__(self, v):
        self.v = v

    def value(self, key, default=None):
        return self.v if key == F.KEY and self.v is not None else default


check("A scelta dalle preferenze; senza preferenze 100", F.saved_percent(FakeQs("130")) == 130 and F.saved_percent(FakeQs(None)) == 100
      and F.saved_percent(None) == 100 and F.saved_percent(FakeQs("rotto")) == 100)
os.environ["FLC_FONT_PERCENT"] = "85"
check("A la variabile FLC_FONT_PERCENT vince sulle preferenze (per chi è rimasto con caratteri troppo grandi)",
      F.saved_percent(FakeQs("150")) == 85)
os.environ.pop("FLC_FONT_PERCENT")

# ====================================================================== B. ogni punto del programma che scrive una grandezza
PKG = os.path.join(ROOT, "freelasercut")
# fogli di stile dell'applicazione: si portano alla grandezza giusta tutti insieme, quando si applicano
GLOBAL = {os.path.join("freelasercut", "theme.py"), os.path.join("freelasercut", "ui", "style.py")}
# pagine web (telefono, MakerHub) e targa dei ringraziamenti e schermata d'avvio, che hanno misure loro in pixel
SKIP = {os.path.join("freelasercut", x) for x in ("phone.py", "makerhub_link.py", "splash.py", "fontscale.py",
                                                  os.path.join("ui", "dialogs_thanks.py"),
                                                  os.path.join("ui", "dialogs_testphoto.py"))}
raw_css, raw_pt, raw_qfont = [], [], []
for base, _d, files in os.walk(PKG):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, ROOT)
        if rel in SKIP:
            continue
        lines = open(path, encoding="utf-8").read().split("\n")
        banco_qss = False
        for i, ln in enumerate(lines):
            if rel.endswith(os.path.join("ui", "banco.py")):
                if ln.startswith("BANCO_QSS = ") or ln.startswith("PALETTE_QSS = "):
                    banco_qss = True
                elif banco_qss and ln.startswith('""")'):
                    banco_qss = False
            if "font-size" in ln and rel not in GLOBAL and not banco_qss:
                ctx = "\n".join(lines[max(0, i - 14):i + 17])  # la chiamata può stare qualche riga sopra o sotto
                if "fontscale.css(" not in ctx:
                    raw_css.append(f"{rel}:{i + 1}")
            m = re.search(r"setPointSizeF?\((.*)\)", ln)
            if os.sep + "core" + os.sep in path:
                m = None  # i testi del disegno hanno le loro misure, in mm
            if m and "fontscale.pt(" not in m.group(1) and "pointSizeF()" not in m.group(1):
                raw_pt.append(f"{rel}:{i + 1}")
            if re.search(r"QFont\(\s*[\"'][^\"']+[\"']\s*,\s*\d", ln):
                raw_qfont.append(f"{rel}:{i + 1}")
check("B nessun foglio di stile o testo con «font-size» fuori da fontscale.css()", not raw_css, raw_css)
check("B nessuna grandezza in punti data a un carattere senza fontscale.pt()", not raw_pt, raw_pt)
check("B nessun carattere creato con la grandezza scritta nel costruttore", not raw_qfont, raw_qfont)
banco_src = open(os.path.join(PKG, "ui", "banco.py"), encoding="utf-8").read()
check("B i fogli di stile del Banco si portano alla grandezza giusta quando si applicano",
      "fontscale.css(BANCO_QSS)" in banco_src and banco_src.count("PALETTE_QSS") >= 1)

# ====================================================================== C. schermo a 72 punti per pollice (processo a parte)
PROBE = r'''
import json, os, sys, tempfile
T = tempfile.mkdtemp()
os.environ["APPDATA"] = T; os.environ["XDG_CONFIG_HOME"] = T
os.environ["FLC_SETTINGS_INI"] = os.path.join(T, "p.ini")
sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStatusBar, QToolButton
app = QApplication([])
from freelasercut import fontscale
from freelasercut.ui import main_window as mw, style
if mode == "prima":
    app.setStyle("Fusion"); style.load_fonts(); app.setFont(style.ui_font(9))
    app.setStyleSheet(mw.QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)
else:
    mw.apply_look(app)
win = mw.MainWindow()
win.show()
app.processEvents()
def px(w):
    w.ensurePolished()
    return QFontInfo(w.font()).pixelSize()
kinds = {}
for cls in (QLabel, QPushButton, QToolButton):
    sizes = sorted({px(w) for w in win.findChildren(cls)})
    kinds[cls.__name__] = sizes
out = {"dpi": round(app.primaryScreen().logicalDotsPerInchY()), "app": QFontInfo(app.font()).pixelSize(),
       "menu": px(win.menuBar()), "status": px(win.statusBar()), "ui9": QFontInfo(style.ui_font(9)).pixelSize(),
       "mono": QFontInfo(style.mono_font(8.5)).pixelSize(), "kinds": kinds, "k": [fontscale.k_pt(), fontscale.k_px()]}
print("ESITO " + json.dumps(out))
os._exit(0)
'''
probe = os.path.join(TMP, "sonda.py")
open(probe, "w", encoding="utf-8").write(PROBE)


def run_probe(mode, dpi=None, pct=None):
    env = dict(os.environ)
    env.pop("QT_FONT_DPI", None)
    env.pop("FLC_FONT_PERCENT", None)
    if dpi:
        env["QT_FONT_DPI"] = str(dpi)
    if pct:
        env["FLC_FONT_PERCENT"] = str(pct)
    r = subprocess.run([sys.executable, probe, ROOT, mode], capture_output=True, text=True, env=env, timeout=150)
    line = next((x for x in r.stdout.splitlines() if x.startswith("ESITO ")), None)
    return json.loads(line[6:]) if line else {"errore": (r.stderr or r.stdout)[-400:]}


base = run_probe("ora")
check("C schermo a 96 (Windows, Linux): fattori 1, carattere dell'applicazione alto 12 pixel", base.get("k") == [1.0, 1.0]
      and base.get("app") == 12 and base.get("dpi") == 96, base)
mac_before = run_probe("prima", dpi=72)
if mac_before.get("dpi") != 72:
    check("C schermo a 72 non simulabile su questo sistema: salto le prove della sezione (non è un errore)", True)
else:
    check("C prima della 0.22.4, schermo a 72 (Mac): tutto un quarto più piccolo (9 pixel invece di 12)",
          mac_before["app"] == 9 and mac_before["menu"] < base["menu"] and mac_before["ui9"] == 9, mac_before)
    mac = run_probe("ora", dpi=72)
    check("C ora, schermo a 72: fattore 4/3 e carattere dell'applicazione di nuovo alto 12 pixel",
          abs(mac["k"][0] - 4 / 3) < 1e-6 and mac["k"][1] == 1.0 and mac["app"] == 12, mac)
    check("C …menu, barra di stato e caratteri creati nel codice alti come a 96",
          (mac["menu"], mac["status"], mac["ui9"], mac["mono"]) == (base["menu"], base["status"], base["ui9"], base["mono"]),
          (mac, base))
    check("C …e così le scritte, i pulsanti e i pulsanti delle barre di tutta la finestra (stesse altezze in pixel)",
          mac["kinds"] == base["kinds"], (mac["kinds"], base["kinds"]))
    big = run_probe("ora", dpi=72, pct=130)
    check("C schermo a 72 con la scelta 130%: 12 × 1,3 = 16 pixel", big["app"] in (15, 16) and big["k"][1] == 1.3, big)
big96 = run_probe("ora", pct=130)
check("C schermo a 96 con la scelta 130%: carattere da 16 pixel, tutte le scritte più grandi di prima",
      big96.get("app") in (15, 16) and min(big96["kinds"]["QLabel"]) > min(base["kinds"]["QLabel"])
      and max(big96["kinds"]["QPushButton"]) > max(base["kinds"]["QPushButton"]), big96)
small = run_probe("ora", pct=85)
check("C scelta 85%: carattere da 10 pixel", small.get("app") == 10, small)

# ====================================================================== D. finestra: menu, Preferenze, salvataggio
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QRadioButton  # noqa: E402

app = QApplication([])
asked = []
ANSWER = {"q": QMessageBox.No}


def fake_question(*a, **k):
    asked.append(a[2] if len(a) > 2 else "")
    return ANSWER["q"]


QMessageBox.question = staticmethod(fake_question)
from freelasercut.ui import help_texts, main_window as mw  # noqa: E402,F401

win = mw.MainWindow()
win.show()
app.processEvents()
acts = win.font_actions
check("D Impostazioni → Grandezza dei caratteri: cinque voci, «Normali (100%)» scelta",
      list(acts) == [85, 100, 115, 130, 150] and [a.isChecked() for a in acts.values()] == [False, True, False, False, False]
      and acts[100].text() == "Normali (100%)" and win.m_font.title() == "Grandezza dei caratteri"
      and win.m_font.menuAction() in win.m_settings.actions(), [a.text() for a in acts.values()])
check("D ogni voce spiega che cosa cambia e che qualche scritta può restare tagliata",
      all("tagliata" in a.statusTip() for a in acts.values()))
check("D scelta nuova: si salva e chiede di riavviare (qui: no)", win.choose_font_size(130) is True
      and int(win.qs.value(F.KEY)) == 130 and len(asked) == 1 and "prossimo avvio" in asked[0], asked)
check("D la grandezza in uso non cambia fino al riavvio", F.percent == 100 and F.k_px() == 1.0)
check("D tornare a quella in uso: si salva, nessuna domanda", win.choose_font_size(100) is False
      and int(win.qs.value(F.KEY)) == 100 and len(asked) == 1)
check("D valore che non è fra le scelte: rifiutato, niente salvato", win.choose_font_size(137) is False
      and int(win.qs.value(F.KEY)) == 100)
acts[115].trigger()
check("D dal menu: stessa strada (salvato 115, domanda)", int(win.qs.value(F.KEY)) == 115 and len(asked) == 2)
closed = []
win.close = lambda: (closed.append(1), True)[1]
ANSWER["q"] = QMessageBox.Yes
win.choose_font_size(150)
check("D con «Sì» il programma si riavvia", closed == [1] and win._restart is True)
ANSWER["q"] = QMessageBox.No
win._restart = False
from freelasercut.ui.dialogs_prefs import PreferencesDialog  # noqa: E402

dlg = PreferencesDialog(win)
radios = [r.text() for r in dlg.findChildren(QRadioButton)]
check("D Preferenze → Interfaccia: la riga «Grandezza dei caratteri» con le cinque scelte",
      all(any(r.startswith(n) for r in radios) for n in ("Piccoli", "Normali", "Grandi (115%)", "Molto grandi", "Grandissimi")),
      radios)
dlg.filter("caratteri")
vis = [w for k, w, _t in dlg._rows if not w.isHidden()]
check("D la ricerca delle Preferenze la trova scrivendo «caratteri»", len(vis) >= 1
      and any(any(x.text() == "Grandezza dei caratteri" for x in w.findChildren(QLabel)) for w in vis))
dlg.reject()
pal = getattr(getattr(win, "banco", None), "palette", None)
if pal is not None:
    pal.collect()
    check("D Banco: la ricerca dei comandi trova le cinque voci", all(a in [x for x, _p in pal.entries] for a in acts.values()))
from freelasercut.settings_store import app_settings  # noqa: E402

qs2 = app_settings()
qs2.setValue(F.KEY, 130)
qs2.sync()
mw.apply_look(app)
check("D all'avvio dopo: la scelta salvata diventa quella in uso (130%)", F.percent == 130 and F.k_px() == 1.3
      and abs(app.font().pointSizeF() - 9 * 1.3) < 0.01, (F.percent, app.font().pointSizeF()))
check("D …e il foglio di stile dell'applicazione ha le grandezze × 1,3 (10 punti → 13, 8,5 → 11,05)",
      "font-size: 13pt" in app.styleSheet() and "font-size: 11.05pt" in app.styleSheet()
      and "font-size: 8.5pt" not in app.styleSheet())
qs2.setValue(F.KEY, "pippo")
qs2.sync()
mw.apply_look(app)
check("D preferenza rovinata: si parte con 100, senza errori", F.percent == 100 and app.font().pointSizeF() == 9.0)
qs2.setValue(F.KEY, 100)
qs2.sync()
F.reset()

# ====================================================================== E. difetti rimessi apposta
caught = []
orig = F.platform_factor
F.platform_factor = lambda dpi: 1.0  # 1. niente correzione per lo schermo a 72
F.setup(100, 72)
caught.append(F.pt(9) != 12.0)
F.platform_factor = orig
orig_css = F.css
qs2.setValue(F.KEY, 130)
qs2.sync()
F.css = lambda text: text  # 2. fogli di stile non toccati
mw.apply_look(app)
caught.append(F.percent == 130 and "font-size: 11.05pt" not in app.styleSheet())
F.css = orig_css
qs2.setValue(F.KEY, 100)
qs2.sync()
orig_pt = F.pt
F.setup(130, 96)
F.pt = lambda size: float(size)  # 3. caratteri creati nel codice non toccati
from freelasercut.ui import style  # noqa: E402

caught.append(style.ui_font(9).pointSizeF() == 9.0)
F.pt = orig_pt
caught.append(style.ui_font(9).pointSizeF() == 11.7)  # (senza il difetto torna giusto)
orig_setup = F.setup
F.reset()
qs2.setValue(F.KEY, 150)
qs2.sync()
F.setup = lambda *a, **k: (1.0, 1.0)  # 4. la scelta salvata non viene letta all'avvio
mw.apply_look(app)
caught.append(F.percent != 150)
F.setup = orig_setup
qs2.setValue(F.KEY, 100)
qs2.sync()
src = "x.setStyleSheet('font-size: 9pt;')"  # 5. un foglio di stile nuovo scritto senza fontscale.css()
caught.append("fontscale.css(" not in src and "font-size" in src)
F.reset()
mw.apply_look(app)
check("E difetti rimessi apposta (schermo a 72 non corretto, fogli di stile fermi, caratteri fermi, scelta non letta, "
      "foglio di stile nuovo fuori dal passaggio): tutti visti", all(caught) and len(caught) == 6, caught)

# ====================================================================== F. testi
missing = {}
TEXTS = ("Grandezza dei caratteri", "Piccoli", "Normali", "Grandi", "Molto grandi", "Grandissimi",
         "Grandezza delle scritte di menu, pannelli e finestre. Con i caratteri più grandi qualche scritta può restare "
         "tagliata: in quel caso scegli una misura più piccola.",
         "La nuova grandezza dei caratteri sarà usata dal prossimo avvio di FreeLaserCut. Riavviare adesso?")
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [t for t in TEXTS if not cat.get(t)]
    if miss:
        missing[lang] = miss
check("F testi nuovi tradotti in inglese, spagnolo, francese e portoghese", not missing, missing)

win.close = lambda: True
print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
