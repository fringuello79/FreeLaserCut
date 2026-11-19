# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7: barra in alto personalizzabile (Visualizza → Personalizza la barra…, tasto destro sulle barre).

Di partenza la barra è quella di sempre; i comandi scelti vanno dopo quelli di sempre, prima dello spazio di destra,
nell'ordine scelto; la scelta resta ai prossimi avvii; comandi che non esistono, doppioni, comandi già nella barra o
senza icona: scartati; al massimo FAV_MAX; finestra: cerca, aggiungi, togli, su, giù, svuota, Annulla non cambia
niente, OK salva; nel Banco la voce non c'è. Testi tradotti.
Uso: python tests/test_v207_barra.py [classica|banco]
"""
import json
import os
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.dialogs_favbar import FavBarDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "")


def spin():
    for _ in range(5):
        app.processEvents()


def bar_keys(w):
    """I comandi della barra in alto, nell'ordine, fino allo spazio di destra (separatori come «-»)."""
    rev = {v: k for k, v in w.acts.items()}
    out = []
    for a in w.main_bar.actions():
        if a is w._fav_anchor:
            break
        out.append("-" if a.isSeparator() else rev.get(a, "?"))
    return out


w = MainWindow()
w.show()
spin()
if UI == "banco":
    check("Banco: «Personalizza la barra…» non c'è (il Banco non ha la barra in alto) e non si apre",
          not w.acts["fav_bar"].isVisible() and w.fav_bar_dialog() is None)
else:
    base = list(w.MAIN_BAR)
    check("di partenza la barra in alto è quella di sempre", bar_keys(w) == base, bar_keys(w)[-6:])
    check("la voce è in Visualizza, con la sua scheda nella guida",
          w.acts["fav_bar"] in w.m_view.actions() and "fav_bar" in help_texts.HELP and w.acts["fav_bar"].isVisible())
    pm = w.createPopupMenu()
    check("tasto destro su una barra: c'è «Personalizza la barra…»", w.acts["fav_bar"] in pm.actions())
    cand = w.fav_candidates()
    check("si possono aggiungere solo comandi con l'icona che non sono già nella barra",
          cand and all(not w.acts[k].icon().isNull() for k in cand) and not set(cand) & set(base)
          and "photo" in cand and "fav_bar" not in cand and "identify" not in cand, len(cand))
    keys = w.set_fav_bar(["photo", "nonesiste", "photo", "new", 42, "makerhub_site", "fav_bar"])
    check("comandi che non esistono, doppioni, già nella barra o senza icona: scartati",
          keys == ["photo", "makerhub_site"], keys)
    check("…messi dopo quelli di sempre con un separatore, nell'ordine scelto", bar_keys(w) == base + ["-", "photo",
                                                                                                       "makerhub_site"],
          bar_keys(w)[-4:])
    check("…e l'azione è la stessa del menu (fa la stessa cosa)",
          w.main_bar.widgetForAction(w.acts["photo"]) is not None)
    w.set_fav_bar(["makerhub_site", "photo"])
    check("cambiare l'ordine li rimette in quell'ordine, senza doppioni nella barra",
          bar_keys(w) == base + ["-", "makerhub_site", "photo"], bar_keys(w)[-4:])
    check("la scelta si salva nelle impostazioni", list(w.qs.value("fav_bar")) == ["makerhub_site", "photo"])
    w2 = MainWindow()
    spin()
    check("al prossimo avvio la barra ha gli stessi comandi", bar_keys(w2) == base + ["-", "makerhub_site", "photo"])
    w2.editor.dirty = False
    w2.close()
    many = w.set_fav_bar(cand)
    check("al massimo {0} comandi".format(w.FAV_MAX), len(many) == w.FAV_MAX and bar_keys(w)[len(base) + 1:] == many)
    w.set_fav_bar([])
    check("lista vuota: la barra torna quella di sempre, senza separatore in più", bar_keys(w) == base)
    w.qs.setValue("fav_bar", "photo")
    check("impostazione salvata come testo singolo (un solo comando): letta lo stesso", w.fav_bar_keys() == ["photo"])
    w.qs.setValue("fav_bar", [])
    # ---- finestra
    d = FavBarDialog(w)
    check("finestra: a destra vuota, a sinistra tutti i comandi che si possono aggiungere",
          d.keys() == [] and d.all.count() == len(cand))
    d.search.setText("foto")
    vis = [d.all.item(i) for i in range(d.all.count()) if not d.all.item(i).isHidden()]
    check("«Cerca» lascia solo i comandi che contengono la parola (nel nome o nella spiegazione)", vis
          and all("foto" in (it.text() + " " + (it.toolTip() or "")).lower() for it in vis)
          and len(vis) < d.all.count(), [it.text() for it in vis][:5])
    d.search.setText("")
    check("Aggiungi (anche con il nome del comando) e doppioni rifiutati", d.add("photo") and d.add("trace") is False
          and d.add("makerhub_site") and not d.add("photo") and d.keys() == ["photo", "makerhub_site"])
    d.chosen.setCurrentRow(1)
    check("Su sposta il comando scelto", d.move(-1) and d.keys() == ["makerhub_site", "photo"] and d.chosen.currentRow() == 0)
    check("Giù lo rimette", d.move(1) and d.keys() == ["photo", "makerhub_site"] and not d.move(1))
    d.chosen.setCurrentRow(0)
    check("Togli", d.remove() and d.keys() == ["makerhub_site"])
    check("…e il comando tolto torna a sinistra", any(d.all.item(i).data(0x0100) == "photo" for i in range(d.all.count())))
    d.reject()
    check("Annulla: la barra non cambia", bar_keys(w) == base and w.fav_bar_keys() == [])
    d = FavBarDialog(w)
    d.add("photo")
    d.add("relief" if "relief" in cand and w.acts["relief"].isVisible() else "makerhub_site")
    d.accept()
    check("OK: salva e mette i comandi nella barra", bar_keys(w)[:len(base)] == base and len(w.fav_bar_keys()) == 2
          and bar_keys(w)[len(base) + 1] == "photo")
    d = FavBarDialog(w)
    check("riaperta, la finestra mostra la scelta salvata", d.keys() == w.fav_bar_keys())
    d.b_clear.click()
    d.accept()
    check("Svuota + OK: barra di sempre", bar_keys(w) == base and w.fav_bar_keys() == [])
    d = FavBarDialog(w)
    for k in cand:
        d.add(k)
    check("nella finestra al massimo {0}: poi «Aggiungi» si spegne".format(w.FAV_MAX),
          len(d.keys()) == w.FAV_MAX and not d.b_add.isEnabled())
    d.reject()

missing = []
keys = ["Personalizza la barra…", "Personalizza la barra", "Comandi", "Nella barra", "Aggiungi →", "← Togli", "Su",
        "Giù", "Svuota", "Aggiunge alla barra in alto i comandi che usi di più, nell'ordine che vuoi"]
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k) for k in keys if not cat.get(k)]
check("testi tradotti nelle 4 lingue", not missing, missing[:4])

w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
