# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.6: lingue dell'interfaccia (inglese predefinito, italiano, spagnolo, francese, portoghese)."""
import ast
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="flc_test_"))
os.environ["FLC_NO_FIRST_RUN"] = "1"

from freelasercut import i18n  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(cond)
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


# ------------------------------------------------------------ meccanismo
check("lingue disponibili", list(i18n.LANGUAGES) == ["en", "it", "es", "fr", "pt"])
i18n.set_language("it")
check("italiano = testo originale", i18n.tr("Apri…") == "Apri…" and i18n.tr("Porta {0}", "COM3") == "Porta COM3")
i18n.set_language("en")
check("inglese dal catalogo", i18n.tr("Salva") == "Save", i18n.tr("Salva"))
check("modello con argomenti", "COM7" in i18n.tr("Porta: {0}", "COM7") if "Porta: {0}" in i18n._catalog else True)
check("testo sconosciuto resta com'è", i18n.tr("zzz non esiste {0}", 5) == "zzz non esiste 5")
i18n.set_language("xx")
check("lingua sconosciuta -> inglese", i18n.language() == "en")
os.environ["FLC_LANG"] = "fr"
check("FLC_LANG ha la precedenza", i18n.startup_language() == "fr")
del os.environ["FLC_LANG"]

# ------------------------------------------------------------ cataloghi completi e coerenti
src = set()
pkg = os.path.join(ROOT, "freelasercut")
for root, _, fs in os.walk(pkg):
    for f in fs:
        if f.endswith(".py") and not f == "help_texts.py":
            for n in ast.walk(ast.parse(open(os.path.join(root, f), encoding="utf-8").read())):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args \
                        and isinstance(n.args[0], ast.Constant):
                    src.add(n.args[0].value)
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(pkg, "locale", f"{lang}.json"), encoding="utf-8"))
    i18n.set_language(lang)
    missing = [s for s in src if s not in cat and any(c.isalpha() and c.islower() for c in s)
               and s not in ("FreeLaserCut", "Atkinson", "Jarvis", "Stucki", "AutoCam", "Homing")]
    check(f"{lang}: catalogo completo", len(missing) == 0, f"{len(cat)} voci, mancano {len(missing)}")
    check(f"{lang}: nessuna voce scartata dal controllo", len(i18n._catalog) == len(cat), f"{len(i18n._catalog)}/{len(cat)}")

# ------------------------------------------------------------ la finestra si apre in ogni lingua
code = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from freelasercut import i18n
i18n.set_language(sys.argv[2])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from freelasercut.ui import main_window as M
w = M.MainWindow()
menus = [a.text() for a in w.menuBar().actions()]
langs = [a.text() for a in w.m_language.actions()]
print("MENU", "|".join(menus)); print("LINGUE", "|".join(langs)); print("SOSTIENI", w.support_button.text())
sys.stdout.flush(); os._exit(0)
"""
for lang, first_menu in (("en", "&File"), ("it", "&File"), ("es", None), ("fr", None), ("pt", None)):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=tempfile.mkdtemp(prefix="flc_test_"), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-c", code, ROOT, lang], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=240)
    out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if line[:4] in ("MENU", "LING", "SOST"))
    ok = r.returncode == 0 and "MENU" in out and len(out.get("LINGUE", "").split("|")) == 5
    if ok and lang != "it":
        ok = out["MENU"] != "&File|&Modifica|&Disponi|&Visualizza|&Laser|&Strumenti|&Aiuto"
    check(f"finestra in {lang}", ok, out.get("MENU", r.stderr[-300:]) + " · " + out.get("SOSTIENI", ""))

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
