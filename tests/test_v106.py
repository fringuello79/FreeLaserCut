# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.6: aspetto a scelta (Impostazioni → Aspetto): tema scuro, chiaro o come Windows, e colore
principale. Il tema chiaro non deve lasciare pezzi scuri: nessun colore «da tema scuro» nei fogli di stile."""
import sys, os, time, tempfile, subprocess, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_THEME", None)
os.environ.pop("FLC_ACCENT", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# ------------------------------------------------------------------ tavolozze (in un processo a parte per ogni tema)
PROBE = r"""
import os, sys, json
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from freelasercut import theme
from freelasercut.ui import style
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import banco
app.setStyleSheet(theme.QSS + style.QSS_EXTRA)
w = MainWindow(); w.show(); app.processEvents()
sheets = [app.styleSheet(), banco.BANCO_QSS] + [x.styleSheet() for x in app.allWidgets() if x.styleSheet()]
dark_left = sorted({k for k in theme.REMAP_LIGHT for s in sheets if k.lower() in s.lower()})
print("JSON " + json.dumps({"theme": theme.THEME, "accent": theme.ACCENT, "bg": theme.C["bg"], "accent_c": theme.C["accent"],
                            "light": theme.C["light"], "dark_left": dark_left, "n": len(sheets),
                            "looks": [a.text() for a in w.m_look.actions() if a.text()],
                            "checked": [a.text() for a in w.m_look.actions() if a.isChecked()]}))
sys.stdout.flush(); os._exit(0)
"""
def probe(theme=None, accent=None, ui="classica"):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=tempfile.mkdtemp(), XDG_CONFIG_HOME=tempfile.mkdtemp(),
               FLC_UI=ui, FLC_NO_FIRST_RUN="1", FLC_NO_UPDATE="1", PYTHONUTF8="1")
    for k, v in (("FLC_THEME", theme), ("FLC_ACCENT", accent)):
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run([sys.executable, "-c", PROBE, ROOT], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=240)
    line = [l for l in r.stdout.splitlines() if l.startswith("JSON ")]
    return json.loads(line[0][5:]) if line else {"err": r.stderr[-500:]}

d = probe()
check("di partenza: tema scuro e blu, come prima", d.get("theme") == "scuro" and d.get("bg") == "#0C1322" and
      d.get("accent_c") == "#2E7CF6" and d.get("light") is False, str(d)[:200])
l = probe("chiaro")
check("tema chiaro: sfondi chiari", l.get("light") is True and l.get("bg") == "#F2F4F8", str(l)[:200])
check("tema chiaro (Classica): nessun colore del tema scuro rimasto nei fogli di stile", l.get("dark_left") == [],
      f"{l.get('dark_left')} su {l.get('n')} fogli")
b = probe("chiaro", ui="banco")
check("tema chiaro (Banco): nessun colore del tema scuro rimasto nei fogli di stile", b.get("dark_left") == [],
      f"{b.get('dark_left')} su {b.get('n')} fogli")
g = probe("chiaro", "verde")
check("colore principale verde", g.get("accent_c") == "#1F9D63" and "Verde" in g.get("checked", []) and
      "Tema chiaro" in g.get("checked", []), g.get("checked"))
v = probe("scuro", "viola")
check("tema scuro con il viola", v.get("accent_c") == "#7C5CF0" and v.get("light") is False)
check("Impostazioni → Aspetto: tre temi e cinque colori", all(x in l.get("looks", []) for x in
      ("Tema scuro", "Tema chiaro", "Come Windows (chiaro o scuro)", "Blu", "Verde", "Viola", "Arancio", "Rosa")), l.get("looks"))
x = probe("fucsia", "oro")
check("valori sconosciuti: si torna a scuro e blu", x.get("theme") == "scuro" and x.get("accent") == "blu")

# ------------------------------------------------------------------ nel processo: funzioni e menu
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
answers = []
QMessageBox.question = staticmethod(lambda *a, **k: answers.pop(0) if answers else QMessageBox.No)
from freelasercut import theme
check("tema scuro: i colori scritti a mano restano com'erano", theme.css("background:#121826; color:#94A0B8") ==
      "background:#121826; color:#94A0B8" and theme.tc("#3A1418") == "#3A1418")
theme.LIGHT_UI = True
check("tema chiaro: i colori scritti a mano diventano chiari (maiuscole o minuscole)",
      theme.css("background:#121826; color:#94a0b8; border:#FF7A2E") == "background:#FFFFFF; color:#5C6880; border:#FF7A2E"
      and theme.tc("#3A1418") == "#FDE7E8")
theme.LIGHT_UI = False
c = theme.build("chiaro", "arancio")
check("tavolozza chiara con l'arancio: tinta chiara per le selezioni", c["accent"] == "#E2700B" and c["accent_lo"] == "#FDE3CC"
      and c["bg"] == "#F2F4F8")
check("tavolozza scura con il rosa: tinta scura per le selezioni", theme.build("scuro", "rosa")["accent_lo"] == "#86264A")
if sys.platform != "win32":
    check("«Come Windows» fuori da Windows: scuro", theme.build("sistema")["light"] is False)
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
check("la stessa voce Aspetto c'è nel menu Impostazioni (anche il Banco usa questo menu)",
      w.m_look.menuAction() in w.m_settings.actions())
answers[:] = [QMessageBox.No]
changed = w.choose_look(theme="chiaro")
check("scelta del tema chiaro: salvata, chiede di riavviare", changed and w.qs.value("ui_theme") == "chiaro" and not answers)
check("rifiutato il riavvio: la finestra resta aperta", not getattr(w, "_restart", False))
w.qs.setValue("ui_theme", "scuro")
check("scegliere quello già in uso non chiede niente", w.choose_look(accent="blu") is False)
# riavvio: la copia che si chiude smette di ascoltare, così la nuova non la trova «già aperta»
from PySide6.QtCore import QProcess
started = []
QProcess.startDetached = staticmethod(lambda *a, **k: started.append(a) or True)
closed = []
app._flc_single = type("L", (), {"close": lambda self: closed.append(1)})()
answers[:] = [QMessageBox.Yes]
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.show()
w.choose_look(theme="chiaro")
check("riavvio per il nuovo aspetto: istanza unica chiusa prima di riaprire", closed == [1] and started, f"{closed} {started}")
w.qs.setValue("ui_theme", "scuro")
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
