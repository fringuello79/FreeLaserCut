# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: modifiche promesse agli utenti nelle risposte ai rapporti del 18/11/2026 (freeburn/promesse-utenti-2026-11-18.md).

I  FLC-20261118-1022-7487: il punto di riferimento della barra numerica resta l'ultimo scelto anche dopo il riavvio
   (valore rovinato → centro);
H  FLC-20261118-0900-681F: test materiali, potenza e velocità delle scritte scelte nella finestra e ricordate, usate
   nel G-code; numeri arrotondati (niente «33.3333%» né «41.7»), in mm/min e in mm/s; numeri troppo larghi per la
   colonna rimpiccioliti invece di sovrapporsi;
T  testi nuovi tradotti in tutte le lingue.
Uso: python tests/test_v206_rapporti.py [classica|banco]
"""
import json
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
INI = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_SETTINGS_INI"] = INI
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import units  # noqa: E402
from freelasercut.core import material_test as mtest  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.settings_store import app_settings  # noqa: E402
from freelasercut.ui.dialogs_materials import MaterialTestDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402
from freelasercut.ui.panels_design import saved_anchor  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "")


print("--- I. punto di riferimento che resta dopo il riavvio")
w = MainWindow()
a = w.numeric.anchor
check("la prima volta il punto di riferimento è il centro", a.value == 4 and saved_anchor() == 4, a.value)
a.value = 0
a.changed.emit(0)  # come un clic sul quadratino in basso a sinistra
check("scelto in basso a sinistra: lo si ricorda", saved_anchor() == 0
      and str(app_settings().value("num_anchor")) == "0")
w.close()
w2 = MainWindow()
check("dopo il riavvio resta in basso a sinistra (e la barra lo usa)", w2.numeric.anchor.value == 0)
w2.numeric.anchor.value = 8
w2.numeric.anchor.changed.emit(8)
w2.close()
w3 = MainWindow()
check("e poi in alto a destra", w3.numeric.anchor.value == 8)
w3.close()
app_settings().setValue("num_anchor", "storto")
check("valore rovinato nelle impostazioni: torna al centro", saved_anchor() == 4)
app_settings().setValue("num_anchor", 12)
check("valore fuori dalla griglia: torna al centro", saved_anchor() == 4)

print("--- H. test materiali: numeri arrotondati")
units.set_speed_unit("mm/min")
check("potenze intere; un decimale solo sotto il 10 %",
      [mtest.power_label(v) for v in (33.3333, 100.0, 66.6667, 2.5, 7.25, 9.96)] ==
      ["33%", "100%", "67%", "2.5%", "7.2%", "10%"], [mtest.power_label(v) for v in (33.3333, 100.0, 66.6667, 2.5, 7.25, 9.96)])
check("velocità in mm/min intere (1666.67 → 1667)",
      [mtest.speed_label(v) for v in (1666.6667, 3000.0, 2500.4)] == ["1667", "3000", "2500"])
units.set_speed_unit("mm/s")
check("velocità in mm/s intere (41.7 → 42); un decimale solo sotto 10 mm/s",
      [mtest.speed_label(v) for v in (2500.0, 450.0, 600.0)] == ["42", "7.5", "10"],
      [mtest.speed_label(v) for v in (2500.0, 450.0, 600.0)])
prof = MachineProfile()
spec = mtest.TestSpec(p_min=10, p_max=60, rows=4, s_min=1000, s_max=6000, cols=7, cell=5, gap=1)
job = mtest.build(spec, prof)
check("sul test inciso le potenze non hanno decimali lunghi", not re.search(r"\d\.\d\d", str(mtest.power_label(26.6667))))
units.set_speed_unit("mm/min")

print("--- H. test materiali: potenza e velocità delle scritte")


def label_moves(job):
    """Righe G1 del blocco delle scritte: dopo le celle, prima dei riferimenti."""
    txt = "\n".join(job.lines)
    return txt


base = mtest.TestSpec(rows=2, cols=2)
j1 = mtest.build(base, prof)
j2 = mtest.build(mtest.TestSpec(rows=2, cols=2, label_power=60.0, label_speed=900.0), prof)
s60 = f"S{int(round(prof.s_max * 0.6))}"
check("le scritte si incidono con la potenza e la velocità scelte",
      s60 in "\n".join(j2.lines) and "F900" in "\n".join(j2.lines) and s60 not in "\n".join(j1.lines), s60)
check("di partenza come prima: 25 % e 3000 mm/min", base.label_power == 25.0 and base.label_speed == 3000.0
      and "F3000" in "\n".join(j1.lines))
nolab = mtest.build(mtest.TestSpec(rows=2, cols=2, labels=False, label_power=60.0, label_speed=900.0), prof)
check("senza etichette i valori delle scritte non contano", s60 not in "\n".join(nolab.lines))
narrow = mtest.TestSpec(rows=2, cols=8, cell=4, gap=0.5, s_min=10000, s_max=30000)  # numeri a 5 cifre
short = mtest.TestSpec(rows=2, cols=8, cell=4, gap=0.5, s_min=100, s_max=800)  # numeri a 3 cifre: ci stanno
units.set_speed_unit("mm/min")
bn, bs = mtest.build(narrow, prof).bounds, mtest.build(short, prof).bounds
check("colonne strette e numeri a 5 cifre: le scritte non escono dal test (una sì e una no su due righe)",
      abs(bn.right() - bs.right()) < 0.3 and abs(bn.left() - bs.left()) < 0.3, (bn, bs))
mid = mtest.TestSpec(rows=2, cols=5, cell=8, gap=1, s_min=10000, s_max=30000)
bm = mtest.build(mid, prof).bounds
check("colonne medie: numeri un po' più piccoli, tutti sulla stessa riga, dentro il test",
      bm.right() <= mtest.layout(mid).x0c + mtest.layout(mid).W + 0.3, bm)  # 0,13 mm: la freccia di «mm/min →», com era
w = MainWindow()
dlg = MaterialTestDialog(prof, None, parent=w)
check("nella finestra: potenza e velocità delle scritte, di partenza 25 % e 3000 mm/min",
      dlg.label_power.value() == 25.0 and dlg.label_speed.value() == 3000.0 and dlg.spec().label_power == 25.0)
dlg.label_power.setValue(55.0)
dlg.label_speed.setValue(1200.0)
check("cambiandole cambia il test", dlg.spec().label_power == 55.0 and dlg.spec().label_speed == 1200.0
      and "F1200" in "\n".join(dlg.build().lines))
dlg.labels.setChecked(False)
check("senza etichette i due campi si spengono", not dlg.label_power.isEnabled() and not dlg.label_speed.isEnabled())
dlg.labels.setChecked(True)
dlg.close()
dlg2 = MaterialTestDialog(prof, None, parent=w)
check("riaprendo la finestra si ricordano", dlg2.label_power.value() == 55.0 and dlg2.label_speed.value() == 1200.0)
dlg2.close()
units.set_speed_unit("mm/s")
dlg3 = MaterialTestDialog(prof, None, parent=w)
check("in mm/s la velocità delle scritte si mostra in mm/s e resta la stessa", dlg3.label_speed.value() == 1200.0
      and "20" in dlg3.label_speed.text())
dlg3.close()
units.set_speed_unit("mm/min")
w.close()

print("--- T. traduzioni")
keys = ("Scritte", "Potenza delle scritte del test: alzala se vengono troppo leggere",
        "Velocità delle scritte del test: abbassala se vengono troppo leggere")
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k) for k in keys if not cat.get(k) or cat[k] == k]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing)

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
