# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.2, chiesto da Ale: MakerHub con un solo comando e pulsante «Strumenti» nella barra di sinistra.

Prima: nel menu Strumenti un sottomenu «MakerHub» con quattro voci (Dima Lab, Forma Lab, Hinge Lab, Split Lab) che
aprivano tutte la stessa pagina del loro sito, dove lo strumento si sceglie comunque dopo.
Ora: un comando solo, «Strumenti MakerHub», con il loro logo. Nella barra di sinistra dell'interfaccia classica, sotto
«Posiziona laser» e un po' staccati: un pulsante nuovo «Strumenti», che apre l'elenco degli strumenti del menu
Strumenti (forma con misure esatte, codice QR, testo su tracciato… senza MakerHub), e subito sotto il pulsante di
MakerHub, senza menu. Sempre nella 0.19.2 MakerHub esce dalle funzioni in prova: si vede e funziona per tutti, senza
codice; Rilievo 3D e Stampa e taglia restano in prova.

Il dato: interfaccia (Classica / Banco) × funzioni in prova (nascoste / sbloccate) × da dove si apre (menu, barra,
ricerca dei comandi) × browser che si apre o no. Righe M1…M9 del documento.
"""
import ast
import json
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
UI = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_UI"] = UI
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
opened = []
browser = [True]
QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or browser[0])
import socket  # noqa: E402

from freelasercut import admin  # noqa: E402
from freelasercut import makerhub as mh  # noqa: E402
from freelasercut import makerhub_link as link  # noqa: E402
from freelasercut.ui import help_texts, style  # noqa: E402

_probe = socket.socket()
_probe.bind(("127.0.0.1", 0))
link.PORT = _probe.getsockname()[1]  # una porta libera qualsiasi: la prova può girare accanto a un FreeLaserCut aperto
_probe.close()
admin.check = lambda code: code == "prova"
results = []
hidden = []
sys.excepthook = lambda *a: hidden.append(a[1])
SITE = "https://app.maker-hub.it/?da=freelasercut"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
a = w.acts
OLD = ["makerhub_dima", "makerhub_forma", "makerhub_hinge", "makerhub_split"]
TOOL_KEYS = ["exact_shape", "code", "text_path", "puzzle", "sculpt", "relief", "print_cut", "variables", "photo", "trace"]
menu = next(m.menu() for m in w.menuBar().actions() if m.menu() is not None and a["puzzle"] in m.menu().actions())
bar = w.tools_bar
btn = w.btn_tools


def bar_items():
    """I pulsanti della barra di sinistra, dall'alto in basso: (azione o None, pulsante)."""
    out = []
    for act in bar.actions():
        wd = bar.widgetForAction(act)
        if isinstance(wd, QToolButton):
            out.append((act, wd))
    return out


# ================================================================== S1 / S2. senza il codice delle funzioni in prova
check("S1 programma appena installato, senza codice: MakerHub c'è nel menu Strumenti (con «ricevi qui i disegni»), "
      "mentre Rilievo 3D e Stampa e taglia restano nascosti",
      not admin.unlocked(w.qs) and a["makerhub_site"].isVisible() and a["makerhub_receive"].isVisible()
      and not a["relief"].isVisible() and not a["print_cut"].isVisible() and w.mh_link is None,
      (a["makerhub_site"].isVisible(), a["relief"].isVisible()))
w.makerhub_open()
check("S2 senza codice il comando apre il sito di MakerHub e accende la ricezione",
      opened == [SITE] and w.mh_link is not None and w.mh_link.running() and a["makerhub_receive"].isChecked(), opened)
w._makerhub_stop()
w.qs.setValue("makerhub/used", False)
del opened[:]
if UI == "classica":
    check("S1 …nella barra di sinistra il pulsante di MakerHub si vede, come il pulsante «Strumenti»",
          btn.isVisible() and bar.isVisible() and bar.widgetForAction(a["makerhub_site"]).isVisible())
    shown = [x for x in btn.menu().actions() if x.isVisible() and not x.isSeparator()]
    check("M4 senza il codice il menu del pulsante non mostra Rilievo 3D né Stampa e taglia (sono in prova)",
          a["relief"] not in shown and a["print_cut"] not in shown and len(shown) == 8, [x.text() for x in shown])

# ================================================================== M1. menu Strumenti, sbloccato
check("(con il codice le funzioni in prova si sbloccano)", w.admin_dialog(code="prova") is True)
until(lambda: False, 0.3)
acts = menu.actions()
site, rec = a["makerhub_site"], a["makerhub_receive"]
check("M1 menu Strumenti: una voce sola «Strumenti MakerHub» con il loro logo, subito dopo Stampa e taglia",
      site in acts and acts.index(site) == acts.index(a["print_cut"]) + 1 and site.text() == "Strumenti MakerHub"
      and site.isVisible() and not site.icon().isNull()
      and site.icon().pixmap(QSize(40, 40)).toImage().pixelColor(20, 4).red() > 200, [x.text() for x in acts])
check("M1 …sotto, «MakerHub: ricevi qui i disegni» con la spunta; poi le voci per testo variabile e foto",
      acts.index(rec) == acts.index(site) + 1 and rec.isCheckable() and rec.text() == "MakerHub: ricevi qui i disegni"
      and acts.index(rec) < acts.index(a["variables"]) < acts.index(a["photo"]) < acts.index(a["trace"]))
check("M1 …nessun sottomenu MakerHub e le quattro voci di prima non esistono più",
      not any(x.menu() is not None and "MakerHub" in x.text() for x in acts) and not hasattr(w, "m_makerhub")
      and not any(k in a for k in OLD) and sum("MakerHub" in x.text() for x in acts) == 2)
check("M1 …gli altri strumenti del menu sono quelli di prima, nello stesso ordine",
      [x for x in acts if x in [a[k] for k in TOOL_KEYS]] == [a[k] for k in TOOL_KEYS]
      and list(w.TOOLS_MENU) == TOOL_KEYS[:7] + ["-"] + TOOL_KEYS[7:])

# ================================================================== M3 / M4. barra di sinistra (interfaccia classica)
items = bar_items()
names = [next((k for k, v in w.tool_actions.items() if v is act), None) or
         ("makerhub_site" if act is a["makerhub_site"] else "btn_tools" if wd is btn else "?") for act, wd in items]
check("M3 barra di sinistra, dall'alto: gli attrezzi di prima, poi Misura, Posiziona laser, Strumenti, MakerHub",
      names == ["select", "nodes", "trim", "line", "rect", "ellipse", "polygon", "star", "special", "text", "measure",
                "position", "btn_tools", "makerhub_site"], names)
if UI == "classica":
    geo = {n: wd.geometry() for n, (act, wd) in zip(names, items)}
    step = geo["position"].top() - geo["measure"].top()
    gap = geo["btn_tools"].top() - geo["position"].top()
    check("M3 …«Strumenti» sta sotto «Posiziona laser», un po' staccato (più dello spazio fra due attrezzi vicini)",
          geo["btn_tools"].top() > geo["position"].bottom() and gap >= step + 12, (step, gap))
    check("M3 …e MakerHub subito sotto «Strumenti», attaccato come due attrezzi vicini",
          geo["makerhub_site"].top() - geo["btn_tools"].top() == step, (step, geo["makerhub_site"].top() - geo["btn_tools"].top()))
    check("M3 …i due pulsanti sono grandi come gli altri della barra, con l'icona della stessa misura (20 px), in colonna",
          geo["btn_tools"].size() == geo["position"].size() == geo["makerhub_site"].size()
          and geo["btn_tools"].left() == geo["position"].left() == geo["makerhub_site"].left()
          and btn.iconSize() == bar.iconSize() == QSize(20, 20) and mh.ICON_SIZE == 20,
          (geo["btn_tools"], geo["position"], geo["makerhub_site"], btn.iconSize()))
    check("M3 …tutti dentro la barra, anche con la finestra bassa (768 px)", all(bar.rect().contains(g) for g in geo.values()))
    w.resize(1366, 768)
    app.processEvents()
    geo2 = {n: wd.geometry() for n, (act, wd) in zip(names, bar_items())}
    check("M3 …a 1366 × 768 i due pulsanti nuovi si vedono ancora per intero",
          bar.rect().contains(geo2["btn_tools"]) and bar.rect().contains(geo2["makerhub_site"])
          and bar.widgetForAction(a["makerhub_site"]).isVisible() and btn.isVisible(), (bar.rect(), geo2["makerhub_site"]))
    w.resize(1400, 900)
    app.processEvents()
if UI == "classica":
    from PySide6.QtCore import Qt  # noqa: E402

    w.acts["help_beginner"].trigger()  # livello Principiante: i nomi sotto i comandi
    app.processEvents()
    mb = bar.widgetForAction(a["makerhub_site"])
    check("M3 con «i nomi sotto i comandi» anche i due pulsanti nuovi hanno il loro nome: «Strumenti» e «MakerHub»",
          btn.toolButtonStyle() == Qt.ToolButtonTextUnderIcon and btn.text() == "Strumenti"
          and mb.toolButtonStyle() == Qt.ToolButtonTextUnderIcon and mb.text() == "MakerHub"
          and abs(btn.geometry().center().x() - bar.widgetForAction(w.tool_actions["position"]).geometry().center().x()) <= 3
          and btn.height() == mb.height() == bar.widgetForAction(w.tool_actions["position"]).height()
          and bar.rect().contains(btn.geometry()) and bar.rect().contains(mb.geometry()),
          (btn.toolButtonStyle(), btn.text(), mb.text(), btn.geometry(), mb.geometry(),
           bar.widgetForAction(w.tool_actions["position"]).geometry()))
    w.acts["help_normal"].trigger()
    app.processEvents()
    check("M3 …e tornando al livello normale restano le sole icone", btn.toolButtonStyle() == Qt.ToolButtonIconOnly
          and btn.size() == bar.widgetForAction(w.tool_actions["position"]).size(), (btn.toolButtonStyle(), btn.size()))
svg = open(os.path.join(ROOT, "freelasercut", "assets", "icons", "tools.svg"), encoding="utf-8").read()
check("M3 l'icona «Strumenti» è un disegno nostro (nessuna sigla di raccolte di icone), a tratto come le altre, e si "
      "disegna davvero",
      "currentColor" in svg and 'stroke-width="2"' in svg and "lucide" not in svg.lower() and "license" not in svg.lower()
      and not btn.icon().isNull() and style.pixmap("tools", "#FF0000", 40).toImage().pixelColor(20, 31).red() > 150, svg[:80])
tm = btn.menu()
got = [x for x in tm.actions() if not x.isSeparator()]
check("M4 il pulsante «Strumenti» apre un menu con gli stessi comandi del menu Strumenti (le stesse azioni), nello "
      "stesso ordine, senza MakerHub",
      got == [a[k] for k in TOOL_KEYS] and site not in tm.actions() and rec not in tm.actions()
      and btn.popupMode() == QToolButton.InstantPopup and sum(x.isSeparator() for x in tm.actions()) == 1,
      [x.text() for x in tm.actions()])
check("M4 …con il codice compaiono anche Rilievo 3D e Stampa e taglia; il pulsante ha il suo suggerimento",
      all(x.isVisible() for x in got) and "QR" in btn.toolTip() and "misure esatte" in btn.toolTip(), btn.toolTip())
check("M4 il pulsante di MakerHub nella barra non ha menu: è il comando stesso, con il logo",
      bar.widgetForAction(site).menu() is None and bar.widgetForAction(site).defaultAction() is site
      and (UI != "classica" or bar.widgetForAction(site).isVisible()))

# ================================================================== M5 / M6. che cosa fa il clic
del opened[:]
bar.widgetForAction(site).click()
msg = w.statusBar().currentMessage()
check("M5 clic sul pulsante della barra: si apre, una volta, solo il sito di MakerHub", opened == [SITE], opened)
check("M5 …la ricezione si accende e la barra in basso dice di scegliere lo strumento e premere «Manda a FreeLaserCut»",
      w.mh_link is not None and w.mh_link.running() and rec.isChecked() and "scegli lo strumento" in msg
      and "Manda a FreeLaserCut" in msg and not any(n in msg for n in mh.TOOL_NAMES), msg)
del opened[:]
site.trigger()
check("M5 dal menu Strumenti fa la stessa cosa", opened == [SITE], opened)
w.makerhub_receive(False)
del opened[:]
site.trigger()
msg = w.statusBar().currentMessage()
check("M5 con la ricezione spenta dice di scaricare il file e usare File → Importa", opened == [SITE]
      and not w.mh_link.running() and "File → Importa" in msg and "Manda a" not in msg, msg)
browser[0] = False
del opened[:]
ok = w.makerhub_open()
check("M6 se il browser non si apre lo dice, con l'indirizzo da copiare", ok is False and SITE in w.statusBar().currentMessage(),
      w.statusBar().currentMessage())
browser[0] = True
real = mh.SITE_URL
mh.SITE_URL = "https://example.com/"
del opened[:]
check("M6 un indirizzo che non è di maker-hub.it non viene mai aperto", w.makerhub_open() is False and not opened, opened)
mh.SITE_URL = real
tip = site.statusTip()
check("M5 il suggerimento del comando nomina i quattro strumenti e dice che è un servizio esterno",
      all(n in tip for n in mh.TOOL_NAMES) and "esterno" in tip and "maker-hub.it" in tip, tip)

# ================================================================== M7. ricerca dei comandi
pal = getattr(w, "cmd_palette", None) or getattr(getattr(w, "banco", None), "palette", None)
if pal is not None:
    pal.collect()
    found = [x for x, _p in pal.entries if "MakerHub" in x.text()]
    check("M7 la ricerca dei comandi trova MakerHub una volta sola (più la voce della ricezione)",
          sorted(x.text() for x in found) == ["MakerHub: ricevi qui i disegni", "Strumenti MakerHub"], [x.text() for x in found])

# ================================================================== S6. nascondere di nuovo le funzioni in prova
w.makerhub_receive(True)
hid = w.admin_dialog() is False
until(lambda: False, 0.3)
check("S6 nascondendo di nuovo le funzioni in prova spariscono solo Rilievo 3D e Stampa e taglia: MakerHub resta nel "
      "menu e nella barra, e la ricezione resta accesa",
      hid and site.isVisible() and rec.isVisible() and not a["relief"].isVisible() and not a["print_cut"].isVisible()
      and (UI != "classica" or (btn.isVisible() and bar.widgetForAction(site).isVisible()))
      and w.mh_link.running() and rec.isChecked(), (site.isVisible(), a["relief"].isVisible(), w.mh_link.running()))
w._makerhub_stop()
w.qs.setValue("makerhub/used", True)
w.qs.setValue("makerhub/receive", True)
w._makerhub_resume()
on1 = w.mh_link.running()
w._makerhub_stop()
w.qs.setValue("makerhub/used", False)
w._makerhub_resume()
check("S5 senza codice, al riavvio: chi ha già usato MakerHub ritrova la ricezione accesa; chi non l'ha mai usato no",
      on1 and not w.mh_link.running(), (on1, w.mh_link.running()))

# ================================================================== M8. guida «?»
h = help_texts.lookup("makerhub_site")
check("M8 guida «?»: scheda di «Strumenti MakerHub», con i quattro nomi, «esterno» e «Manda a FreeLaserCut»",
      h is not None and h[0] == "Strumenti MakerHub" and all(n in h[1] for n in mh.TOOL_NAMES) and "esterno" in h[1]
      and "Manda a FreeLaserCut" in h[1], h)
hr = help_texts.lookup("makerhub_receive")
check("S7 le due schede di MakerHub non dicono più «(in prova)»; quelle di Rilievo 3D e Stampa e taglia sì",
      hr is not None and "(in prova)" not in h[0] and "(in prova)" not in hr[0]
      and "(in prova)" in help_texts.lookup("relief")[0] and "in prova" in a["print_cut"].text(), (h[0], hr[0]))
check("M8 …le schede delle quattro voci di prima non ci sono più; c'è quella del pulsante «Strumenti»",
      not any(help_texts.lookup(k) for k in OLD) and help_texts.lookup("tools_menu") is not None
      and btn.property("help_key") == "tools_menu" and site.property("help_key") == "makerhub_site")

# ================================================================== M9. traduzioni
src = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
keys = set()
for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
    try:
        k = "".join(ast.literal_eval(p_) for p_ in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
    except (SyntaxError, ValueError):
        continue
    if k in ("Strumenti MakerHub", "MakerHub: ricevi qui i disegni") or k.startswith(
            ("Apre nel browser gli strumenti di MakerHub", "Strumenti: forma con misure esatte",
             "Sul sito di MakerHub scegli lo strumento")):
        keys.add(k)
check("M9 testi nuovi trovati nel codice (6)", len(keys) == 6, sorted(k[:40] for k in keys))
GONE = ("Strumenti MakerHub (in prova)", "MakerHub – Ricevi qui i disegni (in prova)", "Ricevi qui i disegni", "dime per posizionare gli oggetti", "scatole, espositori, organizer",
        "fasce flessibili attorno a una sagoma", "progetti più grandi del piano, a incastro",
        "MakerHub – Dima Lab (in prova)")
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and (sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))
                                                   or ("MakerHub" in k and "MakerHub" not in loc[k]))]
    old = [k for k in loc if k in GONE or "nel menu a sinistra" in k]
    miss += [k for k in ("MakerHub – Ricevi qui i disegni",) if not loc.get(k)]
    check(f"M9 traduzioni {lang}: i testi nuovi, con «MakerHub» intatto; tolti quelli delle quattro voci di prima",
          not miss and not bad and not old, (miss, bad, [k[:30] for k in old]))

check("nessun errore nascosto nei comandi dell'interfaccia", not hidden, [repr(e)[:120] for e in hidden[:3]])
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
