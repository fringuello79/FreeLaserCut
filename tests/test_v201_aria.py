# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.1: air assist sulle schede Makerbase MKS DLC32 (due rapporti del 15/11/2026, stessa macchina fatta in casa
con una DLC32 V2.1: «l'aria non si accende, con l'altro programma va con M7»; il profilo creato dal riconoscimento
aveva M8).

Matrice dei casi:
1 DLC32 riconosciuta, modello no (telaio 390 × 360, $I e messaggio d'avvio del rapporto): profilo nuovo con M7/M9,
  nota sull'aria fra quelle del riconoscimento;
2 DLC32 riconosciuta come «Scheda Makerbase MKS DLC32» del catalogo (400 × 400): M7; nota del modello che lo dice;
3 altre marche e GRBL generico: M8 come prima; Acmer P2 (DLC32 con la marca nella scheda): M7 come prima, senza
  la nota Makerbase;
4 G-code di un livello con l'aria: M7 all'inizio, M9 alla fine, mai M8; livello senza aria: né M7 né M8;
5 «Riconosci la macchina → Applica» sopra un profilo che c'è già: comando scelto a mano (M8, M7, nessuno) resta;
  profilo vecchio con M7 senza il segno della scelta: resta M7; profilo vecchio con M8 e nessuna scelta: prende M7;
6 scelta a mano dal pannello Macchina: si salva con il segno della scelta, si rilegge dal file; profili vecchi senza
  il campo si aprono (scelta = no);
7 traduzioni della nota nelle 4 lingue.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import machines  # noqa: E402
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


# dati veri del rapporto FLC-20261115-0949-6EAA (impostazioni-grbl.txt), senza la rete
BANNER = ["[MSG:Using machine:MKS DLC32]"]
INFO = ["[PRODUCER:MKS DLC32]", "[V2.30(8M.H35.20221223)]", "[VER:1.1h.2022122301:]", "[OPT:VMPH,63,500]"]
SET = {0: "10", 22: "1", 30: "1000.000", 31: "0.000", 32: "1", 100: "80.000", 101: "80.000", 110: "11000.000",
       111: "11000.000", 120: "1000.000", 121: "1000.000", 130: "390.000", 131: "360.000"}


def built(banner=BANNER, info=INFO, settings=SET, name=None):
    ident = machines.identify(banner=banner, info=info, settings=dict(settings))
    return ident, machines.build_profile(ident, dict(settings), list(info), name)


def note_air(ident):
    return [t for _k, t in ident.notes if "Air assist" in t]


# 1. DLC32 senza modello
ident, p = built()
check("1 DLC32 del rapporto riconosciuta come Makerbase, nessun modello del catalogo",
      ident.vendor == "Makerbase" and not ident.model, f"{ident.vendor} / {ident.model}")
check("1 profilo nuovo: aria con M7, spenta con M9", p.air_cmds() == ("M7", "M9"), p.air_cmds())
check("1 …ma non come scelta della persona", p.air_chosen is False)
check("1 nel file i comandi sono scritti giusti (M7/M9)", (p.file_dict()["air_on"], p.file_dict()["air_off"]) == ("M7", "M9"))
check("1 nota sull'aria fra quelle del riconoscimento, con M7 e dove si cambia",
      len(note_air(ident)) == 1 and "M7" in note_air(ident)[0] and "Air assist" in note_air(ident)[0], ident.notes)
check("1 area letta dalla scheda (390 × 360)", p.travel() == (390.0, 360.0), p.travel())

# 2. DLC32 del catalogo
ident2, p2 = built(info=["[VER:1.1f.20210406:MKS DLC32]", "[OPT:VNMZHSL,128,256]"], banner=[],
                   settings={130: "400.000", 131: "400.000"})
check("2 «Scheda Makerbase MKS DLC32» del catalogo: M7", ident2.model == "Scheda Makerbase MKS DLC32"
      and p2.air_cmds() == ("M7", "M9"), (ident2.model, p2.air_cmds()))
check("2 modello pronto scelto a mano dall'elenco: M7", machines.preset_profile("Scheda Makerbase MKS DLC32").air_cmds()
      == ("M7", "M9"))
check("2 la nota del modello dice M7 e dove provare M8", "M7" in machines.NOTES["Scheda Makerbase MKS DLC32"]
      and "M8" in machines.NOTES["Scheda Makerbase MKS DLC32"])

# 3. le altre macchine non cambiano
ident3, p3 = built(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20190825:]", "[OPT:V,15,128]"],
                   settings={130: "300.000", 131: "300.000"})
check("3 GRBL generico: M8 come prima, nessuna nota sull'aria", p3.air_cmds() == ("M8", "M9") and not note_air(ident3),
      (p3.air_cmds(), ident3.notes))
ident4, p4 = built(banner=["[MSG:Using machine:MKS DLC32]"], info=["[VER:1.1h.2023031702:]", "[OPT:VMPH,63,256]"],
                   settings={51: "ACMER_P2_", 53: "MKS_DLC", 130: "420.000", 131: "400.000"})
check("3 Acmer P2 (monta la DLC32): M7 come prima, da qualunque strada",
      p4.air_cmds() == ("M7", "M9") and machines.preset_profile("Acmer P2 33W").air_cmds() == ("M7", "M9"),
      (ident4.vendor, ident4.model, p4.air_cmds()))
for name in ("Longer B1 40W", "Sculpfun iCube Pro Max 10W", "Atomstack A10 Pro"):
    if name in machines.catalog_names():
        q = machines.preset_profile(name)
        check(f"3 modello pronto {name}: M8 come prima", q.air_cmds() == ("M8", "M9"), q.air_cmds())
check("3 profilo nuovo vuoto: M8 come prima", MachineProfile().air_cmds() == ("M8", "M9"))

# 4. G-code
doc = Document()
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(30, 40))
doc.add(r)
lay = doc.layer(r.layer)
lay.air = True
job = gcode.generate(doc, p, gcode.JobOptions(start_from="absolute"))
cmds = [ln.split(";")[0].strip() for ln in job.lines]
check("4 lavoro con l'aria sulla DLC32: M7 prima di incidere, M9 alla fine, mai M8",
      "M7" in cmds and "M8" not in cmds and cmds.index("M7") < max(i for i, c in enumerate(cmds) if c == "M9"),
      [c for c in cmds if c.startswith("M")])
first_burn = next(i for i, c in enumerate(cmds) if c.startswith("G1 "))
check("4 …e M7 arriva prima del primo movimento di lavoro", cmds.index("M7") < first_burn)
lay.air = False
job0 = gcode.generate(doc, p, gcode.JobOptions(start_from="absolute"))
c0 = [ln.split(";")[0].strip() for ln in job0.lines]
check("4 livello senza aria: né M7 né M8", "M7" not in c0 and "M8" not in c0, c0[:12])
lay.air = True
jg = gcode.generate(doc, p3, gcode.JobOptions(start_from="absolute"))
cg = [ln.split(";")[0].strip() for ln in jg.lines]
check("4 GRBL generico: M8 come prima", "M8" in cg and "M7" not in cg)


# 5. rifare il profilo sopra uno che c'è già (come in «Riconosci la macchina → Applica»)
def reapply(old):
    _i, new = built(name=old.name)
    new.keep_user_orientation(old)
    return new


for chosen, want in (("M8", ("M8", "M9")), ("M7", ("M7", "M9")), ("", ("", ""))):
    old = MachineProfile(name="La mia DLC32", air_on=chosen, air_off="M9" if chosen else "", air_chosen=True)
    n = reapply(old)
    check(f"5 scelta a mano «{chosen or 'nessun comando'}» resta dopo Riconosci → Applica", n.air_cmds() == want
          and n.air_chosen, (n.air_cmds(), n.air_chosen))
old = MachineProfile(name="La mia DLC32", air_on="M7", air_off="M9")  # 0.18.5–0.20.0: scelta senza il segno
check("5 profilo vecchio con M7 (senza il segno della scelta): resta M7", reapply(old).air_cmds() == ("M7", "M9"))
old = MachineProfile(name="La mia DLC32", air_on="", air_off="")
check("5 profilo vecchio con «nessun comando»: resta così", reapply(old).air_cmds() == ("", ""))
old = MachineProfile(name="La mia DLC32", air_on="M8", air_off="M9")
n = reapply(old)
check("5 profilo vecchio con M8 mai scelto: prende M7 della scheda", n.air_cmds() == ("M7", "M9") and not n.air_chosen,
      (n.air_cmds(), n.air_chosen))
old = MachineProfile(name="La mia DLC32", air_on="M3 S1000", air_off="M9")  # scritto a mano, non ammesso
check("5 valore non ammesso nel profilo vecchio: non arriva mai alla scheda",
      reapply(old).air_cmds() in (("", ""), ("M7", "M9")) and "M3" not in reapply(old).air_cmds()[0])
check("5 …e non resta nemmeno scritto nel profilo nuovo", "M3" not in reapply(old).air_on, reapply(old).air_on)
# l'orientamento deciso dalla persona resta insieme all'aria
old = MachineProfile(name="La mia DLC32", air_on="M8", air_off="M9", air_chosen=True, origin_corner="fl",
                     invert_x=True, invert_y=True, tested_x=True, tested_y=True)
n = reapply(old)
check("5 insieme all'aria restano anche angolo e assi provati", n.air_cmds() == ("M8", "M9") and n.origin_corner == "fl"
      and n.invert_x and n.invert_y and n.axes_tested)

# 6. pannello Macchina
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
for _ in range(5):
    app.processEvents()
mp = w.machine
prof = MachineProfile(name="DLC32 di prova", air_on="M7", air_off="M9")
w.set_active_profile(prof) if hasattr(w, "set_active_profile") else None
for _ in range(3):
    app.processEvents()
mp.set_air("M8")
cur = mp.profile
check("6 scelta M8 dal pannello: profilo con M8 e il segno della scelta", cur.air_cmds() == ("M8", "M9")
      and cur.air_chosen, (cur.air_cmds(), cur.air_chosen))
back = MachineProfile.load(cur.path())
check("6 …salvata nel file e riletta uguale", back.air_cmds() == ("M8", "M9") and back.air_chosen is True)
mp.set_air("")
check("6 «Nessun comando»: niente aria, scelta ricordata", mp.profile.air_cmds() == ("", "") and mp.profile.air_chosen)
check("6 la tendina mostra la scelta", mp.air_cmd.currentData() == "", mp.air_cmd.currentData())
mp.set_air("M7")
check("6 di nuovo M7", mp.profile.air_cmds() == ("M7", "M9") and w.ctl.air_cmds == ("M7", "M9"), w.ctl.air_cmds)
f = os.path.join(tempfile.mkdtemp(), "vecchio.json")
data = MachineProfile(name="vecchio", air_on="M7").file_dict()
data.pop("air_chosen", None)
with open(f, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
old = MachineProfile.load(f)
check("6 profilo salvato prima della 0.20.1 (senza il campo): si apre, scelta = no, M7 resta",
      old.air_chosen is False and old.air_cmds() == ("M7", "M9"))

# 7. traduzioni
key = ("Air assist: su queste schede l'aria si accende di solito con {0}. Se la pompa non parte, controlla il comando "
       "in Macchina → Air assist e provalo con il pulsante Aria.")
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    check(f"7 nota tradotta in {lang} con il segnaposto", "{0}" in cat.get(key, ""))
    check(f"7 nota del modello DLC32 tradotta in {lang} con M7 e M8",
          all(c in cat.get(machines.NOTES["Scheda Makerbase MKS DLC32"], "") for c in ("M7", "M8")))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
