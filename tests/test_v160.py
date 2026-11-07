# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.16.0: materiali imparati. FreeLaserCut impara dalle foto dei test come risponde il TUO materiale:
- curva energia → scuro (sempre crescente) e colori veri, dalla foto di un test letto con la taratura da foto;
- ogni foto in più affina la curva (le più vecchie pesano meno, al massimo 12);
- potenza per il tono che vuoi, potenze consigliate per le foto, velocità più bassa se al 100 % non ci arriva;
- toni delle foto in scala di grigi corretti (scurezze equidistanti sul legno vero);
- anteprima realistica e Prepara foto con il risultato previsto su quel materiale;
- esporta / importa un file per dare la curva a qualcuno."""
import json
import math
import os
import re
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
import cv2
import numpy as np
from PIL import Image
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication([])
ANSWER = [QMessageBox.Yes]
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER[0])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import gcode_preview
from freelasercut.core import burn_curve as bc, gcode, material_test as mt, render, test_photo as tp
from freelasercut.core.document import Document, ImageShape, RectShape
from freelasercut.profile import MachineProfile

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


prof = MachineProfile()


# foto sintetica di un test inciso: energia del G-code vero → scuro con un legno di risposta nota
def photo(spec, kk=300.0, wood=(150, 190, 225.), burnt=(30, 40, 55.), seed=1, k=8.0, light=1.0):
    job = mt.build(spec, prof)
    pv = gcode_preview.parse(job.lines, profile=prof)
    B = pv.segs[pv.segs[:, 5] > 0]
    xa, ya, xb, yb = mt.layout(spec).outer
    W, H = int((xb + 20) * k), int((yb + 20) * k)
    energy = np.zeros((H, W))
    for x0, y0, x1, y1, s, _, f in B:
        e = (s / prof.s_max * 100) / max(f, 1)
        cv2.line(energy, (int(x0 * k), int(H - y0 * k)), (int(x1 * k), int(H - y1 * k)), float(e), max(1, int(0.1 * k) + 1))
    dk = 1 - np.exp(-energy * kk)
    rng = np.random.default_rng(seed)
    wood, burnt = np.array(wood) * light, np.array(burnt) * light
    img = wood * (1 - dk[..., None]) + burnt * dk[..., None] + rng.normal(0, 3, (H, W, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def learn(spec, **kw):
    res = tp.analyze(photo(spec, **kw), spec)
    return res, bc.samples_from_result(res, spec)


# ================================================================== la curva
spec = mt.TestSpec(markers=True, rows=6, cols=5, title="Tiglio")
res, (smp, bare) = learn(spec)
check("la foto del test dà anche i colori: materiale nudo e ogni quadrato",
      res.bare_rgb is not None and res.cell_rgb.shape == (6, 5, 3) and res.bare_rgb[0] > res.bare_rgb[2]
      and float(res.cell_rgb[-1, 0].sum()) < float(sum(res.bare_rgb)) * 0.5, (res.bare_rgb, res.cell_rgb[-1, 0]))
check("un campione per quadrato, energia = potenza / velocità / interlinea",
      len(smp) == 30 and abs(smp[0][0] - bc.energy(spec.p_min, spec.s_min, spec.interval)) < 1e-12)
c = bc.BurnCurve("Tiglio", machine=prof.name).add_photo(smp, bare)
ys = np.array(c.ys)
check("curva imparata: sempre crescente, nero massimo come il quadrato più scuro",
      c.ok and np.all(np.diff(ys) >= -1e-9) and abs(c.d_max - res.dark.max()) < 0.03, f"{c.d_max:.3f} / {res.dark.max():.3f}")
err = [abs(c.dark(e) - d) for e, d, *_ in smp]
check("la curva rifà le misure da cui è nata (errore medio < 0,03)", np.mean(err) < 0.03, f"{np.mean(err):.3f}")
spec2 = mt.TestSpec(markers=True, rows=5, cols=4, p_min=15, p_max=70, s_min=2000, s_max=8000, interval=0.12)
res2, _ = learn(spec2, seed=5)
err2 = [abs(c.dark_at(p, v, spec2.interval) - res2.dark[r, k]) for r, p in enumerate(res2.powers)
        for k, v in enumerate(res2.speeds)]
check("prevede un test mai visto (altre potenze, velocità e interlinea): errore medio < 0,04",
      np.mean(err2) < 0.04, f"medio {np.mean(err2):.3f}, max {np.max(err2):.3f}")
check("più energia = mai più chiaro, anche fuori dai valori misurati",
      all(c.dark(a) <= c.dark(b) + 1e-12 for a, b in zip([0, 1e-5, 1e-3, 0.01, 0.1, 1, 10], [1e-5, 1e-3, 0.01, 0.1, 1, 10, 100]))
      and c.dark(0) == 0.0 and c.dark(-1) == 0.0)
ok = True
for d in np.linspace(0.02, c.d_max * 0.98, 25):
    e = c.energy_for(d)
    ok &= abs(c.dark(e) - d) < 0.01
check("energia per uno scuro voluto: tornando indietro si ritrova lo stesso scuro", ok)
check("oltre il nero massimo: l'energia minima che ci arriva, non infinita",
      c.energy_for(0.999) == c.energy_for(c.d_max) and math.isfinite(c.energy_for(0.999)))
p50 = c.power_for(c.d_max * 0.5, 3000, 0.1)
check("potenza per un tono: a velocità doppia serve potenza doppia, con righe a metà distanza metà potenza",
      abs(c.power_for(c.d_max * 0.5, 6000, 0.1) - 2 * p50) < 1e-6 and abs(c.power_for(c.d_max * 0.5, 3000, 0.05) - p50 / 2) < 1e-6
      and abs(c.dark_at(p50, 3000, 0.1) - c.d_max * 0.5) < 0.01, f"{p50:.2f} %")
sug = c.suggest(3000, 0.1)
check("potenze consigliate per le foto: inizio < metà < scuro, dentro 0–100",
      0 < sug["start"] < sug["mid"] < sug["dark"] <= 100 and sug["slow"] is None, sug)
fast = c.suggest(40000, 0.1)
check("troppo veloce per arrivare al nero: potenza al 100 % e velocità più bassa consigliata",
      fast["dark"] == 100.0 and fast["slow"] is not None and fast["slow"] < 40000
      and abs(c.dark_at(100, fast["slow"], 0.1) - 0.92 * c.d_max) < 0.02, fast)
check("fuori dai valori provati nel test: segnato come stima", c.measured(smp[5][0]) and not c.measured(smp[0][0] / 50))

# ================================================================== correzione dei toni delle foto
q = np.linspace(0, 1, 11)
pw = c.tone_map(q, 3000, 0.1, 3, 40)
dk = np.array([c.dark_at(p, 3000, 0.1) for p in pw])
dl = np.array([c.dark_at(p, 3000, 0.1) for p in 3 + 37 * q])
check("toni corretti: dal bianco alla potenza minima al nero con lo scuro della massima, potenza sempre crescente",
      abs(pw[0] - 3) < 1e-9 and pw[-1] <= 40 + 1e-9 and abs(dk[-1] - c.dark_at(40, 3000, 0.1)) < 0.01
      and np.all(np.diff(pw) >= -1e-9), np.round(pw, 1).tolist())
sat = c.tone_map(np.array([0.98, 0.99, 1.0]), 3000, 0.1, 3, 100)
check("massima oltre la saturazione del legno: il nero pieno non prende di colpo il 100 %",
      sat[2] < 100 and sat[2] - sat[0] < 10, np.round(sat, 1).tolist())
step_c, step_l = np.diff(dk), np.diff(dl)
check("toni corretti: scurezze equidistanti sul legno (senza: i toni scuri si impastano)",
      step_c.std() < 0.2 * step_c.mean() and step_l.std() > 2 * step_c.std(),
      f"passi {np.round(step_c, 3).tolist()} / senza {np.round(step_l, 3).tolist()}")
check("toni: potenza minima uguale o oltre la massima → come prima (in proporzione)",
      np.allclose(c.tone_map(q, 3000, 0.1, 40, 40), 40) and np.allclose(c.tone_map(q, 3000, 0.1, 50, 20), 50 - 30 * q))

# ================================================================== colori
col0, colm = c.color(0.0), c.color(c.d_max)
dark_cell = res.cell_rgb[np.unravel_index(np.argmax(res.dark), res.dark.shape)]
check("colori: scuro 0 = il materiale nudo, nero massimo = il quadrato più bruciato",
      np.abs(col0 - np.array(bare)).max() < 1.5 and np.abs(colm - dark_cell).max() < 25, (np.round(colm), dark_cell))
lum = [float(np.dot(c.color(d), (0.3, 0.59, 0.11))) for d in np.linspace(0, c.d_max, 8)]
check("colori sempre più scuri con lo scuro", all(a >= b - 1.0 for a, b in zip(lum, lum[1:])), np.round(lum).tolist())
res_dim, (smp_dim, bare_dim) = learn(spec, light=0.7, seed=3)
check("stesso legno con meno luce: stesso scuro misurato (confronto con il nudo)",
      np.abs(res_dim.dark - res.dark).max() < 0.05, f"{np.abs(res_dim.dark - res.dark).max():.3f}")

slate_spec = mt.TestSpec(markers=True, rows=6, cols=5, title="Ardesia")
res_sl, (smp_sl, bare_sl) = learn(slate_spec, kk=200, wood=(64, 66, 70.), burnt=(205, 210, 212.), seed=8)
sl = bc.BurnCurve("Ardesia").add_photo(smp_sl, bare_sl)
check("materiale che il laser schiarisce (ardesia): sfumatura vera, non tutti i quadrati al massimo",
      sl.ok and 0.4 < sl.d_max < 0.95 and (res_sl.dark > 0.98 * res_sl.dark.max()).sum() < 20
      and np.std(np.diff(np.array([sl.dark_at(p, 3000, 0.1) for p in sl.tone_map(np.linspace(0, 1, 9), 3000, 0.1, 5, 60)])))
      < 0.03 and sl.color(sl.d_max)[0] > sl.color(0)[0] + 80,
      f"max {res_sl.dark.max():.2f}, colori {np.round(sl.color(0))} → {np.round(sl.color(sl.d_max))}")
check("legno normale: lettura uguale a prima (scuro rispetto al nudo)",
      abs(res.dark.max() - 0.781) < 0.02)

# ================================================================== si affina
c2 = bc.BurnCurve.from_dict(c.to_dict())
check("salvata e riletta: identica", c2.xs == c.xs and c2.ys == c.ys and c2.ramp_c == c.ramp_c and c2.uid == c.uid)
c2.add_photo(*bc.samples_from_result(res2, spec2))
check("seconda foto: si aggiunge alle misure (2 foto, campioni sommati)", c2.photos == 2 and len(c2.samples) == 50)
darker = bc.BurnCurve("Lotto che cambia").add_photo(smp, bare)
d_before = darker.dark_at(20, 3000, 0.1)
for i in range(3):
    darker.add_photo(*learn(spec, kk=700, seed=10 + i)[1])
d_new = learn(spec, kk=700, seed=20)[0]
check("il legno cambia (lotto più scuro): dopo 3 foto nuove la curva segue il legno nuovo",
      darker.dark_at(20, 3000, 0.1) > d_before + 0.02 and
      abs(darker.dark_at(20, 3000, 0.1) - bc.BurnCurve("x").add_photo(*bc.samples_from_result(d_new, spec)).dark_at(20, 3000, 0.1)) < 0.05,
      f"{d_before:.3f} → {darker.dark_at(20, 3000, 0.1):.3f}")
many = bc.BurnCurve("Tante")
for i in range(bc.MAX_PHOTOS + 3):
    many.add_photo(smp, bare)
check(f"al massimo {bc.MAX_PHOTOS} foto nella curva (le più vecchie escono)",
      many.photos == bc.MAX_PHOTOS + 3 and len({s[2] for s in many.samples}) == bc.MAX_PHOTOS
      and len(many.samples) == 30 * bc.MAX_PHOTOS)
bad = c.to_dict()
bad["samples"] = bad["samples"][:5] + [[float("nan"), 0.5, 0, 1, 1, 1, 10, 100], ["x"], [0, 0.3, 0, 1, 1, 1, 0, 1], [1]]
try:
    cb = bc.BurnCurve.from_dict(bad)
    okb = len(cb.samples) == 5
except Exception as ex:  # noqa: BLE001
    okb, cb = False, ex
check("file rovinato: i campioni sbagliati si scartano, il resto si legge", okb, cb if not okb else "")
few = bc.BurnCurve("Poco").add_photo(smp[:2], bare)
check("troppo pochi campioni: nessuna curva, nessun errore",
      not few.ok and few.dark(0.1) == 0.0 and few.energy_for(0.3) is None and few.suggest(3000, 0.1) is None
      and np.allclose(few.tone_map(q, 3000, 0.1, 0, 50), 50 * q))

# ================================================================== archivio, esporta, importa
check("archivio vuoto all'inizio", bc.load_all() == [])
bc.put(c)
bc.put(c2)
check("salvate nella cartella delle impostazioni: una curva per uid", len(bc.load_all()) == 1 and bc.get(c.uid).photos == 2
      and os.path.dirname(bc.store_path()).endswith("FreeLaserCut"))
other = bc.BurnCurve("Noce").add_photo(*learn(spec, kk=120, wood=(70, 100, 140.), burnt=(20, 25, 35.), seed=7)[1])
bc.put(other)
check("due materiali, il più recente in cima", [x.name for x in bc.load_all()] == ["Noce", "Tiglio"])
tmp = tempfile.mkdtemp()
p_exp = os.path.join(tmp, "noce.json")
bc.export_file(other, p_exp)
data = json.load(open(p_exp, encoding="utf-8"))
check("esporta: un file .json da dare a qualcuno, con la curva e basta",
      data["format"] == bc.FORMAT and len(data["curves"]) == 1 and data["curves"][0]["name"] == "Noce")
got = bc.import_file(p_exp)
check("importa un file con una curva che c'è già: arriva con un uid nuovo", len(got) == 1 and got[0].uid != other.uid
      and got[0].ys == other.ys)
p_bad = os.path.join(tmp, "altro.json")
json.dump({"format": "altro", "curves": []}, open(p_bad, "w"))
try:
    bc.import_file(p_bad)
    okx = False
except ValueError:
    okx = True
check("importa un file che non è di FreeLaserCut: errore chiaro", okx)
bc.remove(other.uid)
check("elimina", [x.name for x in bc.load_all()] == ["Tiglio"])
copy_ = bc.get(c.uid)
copy_.name = "cambiato"
copy_.samples.clear()
check("le curve lette sono copie: cambiarle senza salvare non tocca quella in uso",
      bc.get(c.uid).name == "Tiglio" and len(bc.get(c.uid).samples) == 50)
raw = open(bc.store_path(), "rb").read()
open(bc.store_path(), "wb").write(b"\xef\xbb\xbf" + raw)
check("archivio salvato con il Blocco note (BOM): si legge", [x.name for x in bc.load_all()] == ["Tiglio"])
with open(bc.store_path(), "w", encoding="utf-8") as fh:
    fh.write("{rotto")
check("archivio rovinato: nessuna curva, nessun errore", bc.load_all() == [] and bc.get(c.uid) is None)
bc.put(c2)
kept = [f for f in os.listdir(os.path.dirname(bc.store_path())) if f.startswith("curve_materiali.illeggibile")]
check("…e non si perde: salvando una curva nuova il file rovinato resta da parte con un altro nome",
      len(kept) == 1 and open(os.path.join(os.path.dirname(bc.store_path()), kept[0])).read() == "{rotto"
      and [x.name for x in bc.load_all()] == ["Tiglio"], kept)
bc.save_all([c2])
cur = c2

# ================================================================== G-code: toni corretti
def image_job(curve_uid, dither="grayscale"):
    doc = Document()
    doc.images["g"] = Image.fromarray((np.tile(np.linspace(255, 0, 200), (100, 1))).astype(np.uint8))
    im = ImageShape("g", 40, 20, layer=0)
    im.apply(QTransform.fromTranslate(100, 100))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi, cs.power_max, cs.power_min, cs.speed = "image", dither, 254, 40, 3, 3000
    cs.burn_curve = curve_uid
    job = gcode.generate(doc, prof)
    S = []
    for line in job.lines:
        mm, mx = re.search(r"S([\d.]+)", line), re.search(r"X([\d.]+)", line)
        if line.startswith(("G1", "X")) and mm and mx:
            S.append((float(mx.group(1)), float(mm.group(1))))
    S = np.array([s for s in S if 101 <= s[0] <= 139 and s[1] > 0])
    return S, job, doc


lin, _, _ = image_job("")
cor, job_c, doc_c = image_job(cur.uid)
smax = prof.s_max


def lin_r(S):
    d = np.array([cur.dark_at(s / smax * 100, 3000, 25.4 / 254) for s in S[:, 1]])
    return np.corrcoef(S[:, 0], d)[0, 1]


check("foto in scala di grigi con il materiale imparato: potenza dentro minima–massima, cresce con il grigio",
      cor[:, 1].min() >= 3 / 100 * smax - 1 and cor[:, 1].max() <= 40 / 100 * smax + 1
      and np.corrcoef(cor[:, 0], cor[:, 1])[0, 1] > 0.9 and not job_c.warnings, job_c.warnings)
check("scuro previsto lungo la sfumatura: lineare con la correzione, molto meno senza",
      lin_r(cor) > 0.99 and lin_r(cor) > lin_r(lin) + 0.03, f"{lin_r(cor):.4f} contro {lin_r(lin):.4f}")
miss, job_m, _ = image_job("non-esiste")
check("materiale imparato che non c'è più: avviso e toni come prima",
      np.allclose(miss, lin) and any("non c'è (eliminato" in w for w in job_m.warnings), job_m.warnings)
d1, _, _ = image_job("", "jarvis")
d2, job_d, _ = image_job(cur.uid, "jarvis")
check("metodi a punti (Jarvis…): il G-code non cambia, nessun avviso", np.array_equal(d1, d2) and not job_d.warnings)
fd, fpath = tempfile.mkstemp(suffix=".flcut")
os.close(fd)
doc_c.save(fpath)
back = Document.load(fpath)
check("il progetto salvato si ricorda il materiale imparato del livello", back.layer(0).burn_curve == cur.uid)
from freelasercut.core.document import CutSettings

old = CutSettings.from_dict({"index": 2, "mode": "image"})
weird = CutSettings.from_dict({"index": 2, "burn_curve": 5})
check("progetti di prima (senza il campo) o valore strano: nessun materiale imparato",
      old.burn_curve == "" and weird.burn_curve == "")

# ================================================================== anteprima realistica
pv = gcode_preview.parse(job_c.lines, profile=prof)
img_c, rect = render.render(pv, smax, render.CURVE_PREFIX + cur.uid)
img_g, _ = render.render(pv, smax, "betulla")
row = img_c[img_c.shape[0] // 2]
check("anteprima realistica sul materiale imparato: fondo = legno nudo della foto, sfumatura verso il bruciato vero",
      np.abs(img_c[1, 1].astype(float) - np.array(cur.bare)).max() < 3 and
      float(row[-12].astype(float).sum()) < float(row[12].astype(float).sum()) - 150 and not np.array_equal(img_c, img_g),
      (img_c[1, 1].tolist(), row[12].tolist(), row[-12].tolist()))
check("«curve:» sconosciuta o curva vuota: si usa l'anteprima generica",
      render.resolve_curve("curve:boh") is None and render.resolve_curve(bc.BurnCurve("x")) is None
      and render.resolve_curve("betulla") is None and render.resolve_curve(cur) is cur)

# ================================================================== interfaccia
from freelasercut.ui import dialogs_curves as DC
from freelasercut.ui.dialogs_testphoto import PhotoResultDialog

spec_t = mt.TestSpec(markers=True, rows=6, cols=5, title="Tiglio")
prd = PhotoResultDialog(res, spec_t)
check("risultato della foto: pulsante «Impara questo materiale…»", prd.b_learn.isEnabled())
ld = DC.LearnDialog(res, spec_t)
check("stesso nome di un materiale imparato: propone di affinarlo", ld.r_add.isChecked() and ld.pick.currentData() == cur.uid)
ld_e = DC.LearnDialog(res, mt.TestSpec(markers=True, title=""))
check("test senza titolo: propone un materiale nuovo (non mescola due legni diversi)", ld_e.r_new.isChecked())
ld.r_new.setChecked(True)
ld.name.setText("  ")
check("nuovo materiale senza nome: «Impara» spento", not ld.b_ok.isEnabled())
ld.name.setText("Tiglio nuovo")
ld._learn()
check("nuovo materiale imparato e salvato", ld.result() == QDialog.Accepted and ld.curve.name == "Tiglio nuovo"
      and bc.get(ld.curve.uid) is not None and len(bc.load_all()) == 2)
flat = tp.PhotoResult(np.zeros((6, 5)), res.powers, res.speeds, [0, 1, 2, 3], False, res.rectified, res.px_mm,
                      res.origin, bare_rgb=res.bare_rgb, cell_rgb=res.cell_rgb)
prd_f, ld_f = PhotoResultDialog(flat, spec_t), DC.LearnDialog(flat, spec_t)
check("foto senza segni: niente da imparare (pulsante spento, avviso)",
      not prd_f.b_learn.isEnabled() and not ld_f.b_ok.isEnabled() and ld_f.warn.isVisibleTo(ld_f))
DC.LearnDialog.exec = lambda self: (self.r_add.setChecked(True), self._learn(), QDialog.Accepted)[2]
before = bc.get(cur.uid).photos
prd.learn()
check("dal risultato: affina il materiale con lo stesso nome (una foto in più)", bc.get(cur.uid).photos == before + 1
      and prd.learned is not None and not prd.b_learn.isEnabled())
cur = bc.get(cur.uid)

from freelasercut.ui.main_window import MainWindow

w = MainWindow()
check("Laser → Materiali imparati…", "learned" in w.acts and any(a is w.acts["learned"] for m in w.menuBar().actions()
                                                                  if m.menu() for a in m.menu().actions()))
doc = w.editor.doc
doc.images["g"] = Image.fromarray((np.tile(np.linspace(255, 0, 200), (100, 1))).astype(np.uint8))
im = ImageShape("g", 40, 20, layer=2)
im.apply(QTransform.fromTranslate(50, 50))
r = RectShape(20, 10, layer=3)
r.apply(QTransform.fromTranslate(150, 50))
w.editor.add([im, r], "prova")
doc.layer(2).mode, doc.layer(2).dither, doc.layer(2).speed = "image", "grayscale", 3000
doc.layer(3).mode, doc.layer(3).speed = "fill", 6000
dlg = DC.CurvesDialog(w)
names = [dlg.list.item(i).text() for i in range(dlg.list.count())]
check("finestra Materiali imparati: l'elenco dei materiali", sorted(names) == ["Tiglio", "Tiglio nuovo"], names)
dlg.list.setCurrentRow(names.index("Tiglio"))
dlg.layer.setCurrentIndex(dlg.layer.findData(2))
check("livello immagine: velocità e interlinea dal livello, tono spento, potenze per le foto",
      dlg.speed.value() == 3000 and abs(dlg.interval.value() - 25.4 / doc.layer(2).dpi) < 1e-3 and not dlg.tone.isEnabled()
      and "Per le foto" in dlg.result.text())
r_img = dlg.compute()
dlg.apply()
cs2 = w.editor.doc.layer(2)
check("applica al livello immagine: potenze consigliate e toni corretti per quel materiale",
      cs2.power_min == r_img["power_min"] and cs2.power_max == r_img["power_max"] and cs2.burn_curve == cur.uid)
w.editor.undo()
check("si annulla con Ctrl+Z", w.editor.doc.layer(2).burn_curve == "")
dlg._fill_layers()
dlg.layer.setCurrentIndex(dlg.layer.findData(3))
dlg.tone.setValue(50)
r50 = dlg.compute()
dlg.apply()
cs3 = w.editor.doc.layer(3)
check("livello riempimento: il tono scelto diventa la potenza (alla velocità del livello)",
      cs3.power_max == r50["power"] and cs3.speed == 6000 and abs(cur.dark_at(r50["power"], 6000, cs3.interval)
                                                                   - cur.d_max * 0.5) < 0.02, r50)
dlg._fill_layers()
dlg.layer.setCurrentIndex(dlg.layer.findData(3))
dlg.speed.setValue(40000)
dlg.tone.setValue(100)
r100 = dlg.compute()
ANSWER[0] = QMessageBox.No
p_before = w.editor.doc.layer(3).power_max
check("tono troppo scuro per quella velocità: lo dice e, se rispondi No, non cambia niente",
      r100["slow"] is not None and "velocità" in dlg.result.text() and not dlg.apply()
      and w.editor.doc.layer(3).power_max == p_before)
ANSWER[0] = QMessageBox.Yes
dlg.apply()
cs3 = w.editor.doc.layer(3)
check("…se rispondi Sì: velocità più bassa e potenza giusta per quel tono",
      cs3.speed < 40000 and cs3.power_max <= 100 and abs(cur.dark_at(cs3.power_max, cs3.speed, cs3.interval)
                                                         - cur.d_max) < 0.03, (cs3.speed, cs3.power_max))
w.editor.doc.layer(3).crosshatch = True
dlg._fill_layers()
dlg.layer.setCurrentIndex(dlg.layer.findData(3))
dlg.speed.setValue(6000)
dlg.tone.setValue(50)
r_x = dlg.compute()
w.editor.doc.layer(3).crosshatch = False
dlg._layer_changed()
dlg.speed.setValue(6000)
r_n = dlg.compute()
check("tratteggio incrociato: ripassa tutto, il tono vuole metà potenza", abs(r_x["power"] - r_n["power"] / 2) < 0.15,
      (r_x["power"], r_n["power"]))
dlg.interval.setValue(0.05)
r_iv = dlg.compute()
dlg.apply()
check("interlinea cambiata nella finestra: va anche sul livello, con la potenza calcolata per lei",
      abs(w.editor.doc.layer(3).interval - 0.05) < 1e-9 and w.editor.doc.layer(3).power_max == r_iv["power"])
ln = RectShape(10, 10, layer=4)
ln.apply(QTransform.fromTranslate(10, 150))
w.editor.add([ln], "linea")
w.editor.doc.layer(4).mode = "line"
dlg._fill_layers()
check("i livelli Linea (tagli) non sono nell'elenco", dlg.layer.findData(4) < 0 and dlg.layer.findData(3) >= 0)
from freelasercut.core import materials as mats_

cs_m = w.editor.doc.layer(2)
cs_m.burn_curve = cur.uid
mats_.apply_to_layer(mats_.builtin()[0], cs_m)
check("un materiale della libreria applicato al livello toglie la curva imparata dell'altro", cs_m.burn_curve == "")
p_exp2 = os.path.join(tmp, "tiglio.json")
dlg.export_curve(p_exp2)
got2 = dlg.import_curves(p_exp2)
check("esporta e reimporta dalla finestra", os.path.exists(p_exp2) and len(got2) == 1 and dlg.list.count() == 3)
dlg.list.setCurrentRow(0)
uid0 = dlg.current().uid
dlg.delete()
check("elimina dalla finestra (dopo conferma)", dlg.list.count() == 2 and bc.get(uid0) is None)
dlg.close()

# anteprima del lavoro: parte dal materiale imparato usato dal disegno
w.editor.doc.layer(2).burn_curve = cur.uid
from freelasercut.ui.dialogs import PreviewDialog

job = w.build_job()
pvd = PreviewDialog(gcode_preview.parse(job.lines, profile=prof), job, prof, (prof.bed_x, prof.bed_y), w)
check("anteprima del lavoro: i materiali imparati nell'elenco, parte da quello del disegno",
      pvd.material.currentData() == render.CURVE_PREFIX + cur.uid and pvd.material.findData("betulla") >= 0)
pvd.r_real.setChecked(True)
check("resa realistica con il materiale imparato", pvd._real_item is not None)
pvd.close()

# Prepara foto: risultato previsto sul materiale e potenza consigliata
from freelasercut.ui.dialogs_photo import PhotoDialog

cs2 = w.editor.doc.layer(2)
cs2.power_min, cs2.power_max = 0, 80
pd = PhotoDialog(im, doc.images["g"], cs2, (40, 20), w)
check("Prepara foto: «Sul materiale» parte dal materiale imparato del livello",
      pd.learned.currentData() == cur.uid and pd.learned_pw.isVisibleTo(pd))
qi = pd.v_res.qimg
left, right = qi.pixelColor(3, qi.height() // 2), qi.pixelColor(qi.width() - 4, qi.height() // 2)
bare_q = DC._qcolor(cur.bare)
check("Prepara foto: «Come verrà incisa» con i colori del materiale (bianco = legno nudo, nero = bruciato vero)",
      abs(left.red() - bare_q.red()) < 6 and right.red() < left.red() - 60, (left.name(), right.name(), bare_q.name()))
lv = pd.layer_values()
check("senza spunta: la potenza del livello resta, il materiale si ricorda", lv["burn_curve"] == cur.uid and "power_max" not in lv)
pd.learned_pw.setChecked(True)
lv = pd.layer_values()
sg = cur.suggest(cs2.speed, 25.4 / pd.dpi.value(), cs2.passes)
check("con la spunta: potenze consigliate", (lv["power_min"], lv["power_max"]) == (sg["start"], sg["dark"]), lv)
pd.learned.setCurrentIndex(0)
check("«Generico»: niente materiale, anteprima come prima", pd.layer_values()["burn_curve"] == ""
      and not pd.learned_pw.isVisibleTo(pd))
pd.close()
cs2.burn_curve = "di-un-altro-pc"
pd2 = PhotoDialog(im, doc.images["g"], cs2, (40, 20), w)
check("Prepara foto con un materiale imparato su un altro computer: resta scelto e non si perde",
      pd2.layer_values()["burn_curve"] == "di-un-altro-pc")
pd2.close()
cs2.burn_curve = cur.uid

# impostazioni del livello
from freelasercut.ui.panels_design import CutSettingsDialog

csd = CutSettingsDialog(cs2, prof, w)
check("impostazioni del livello (Immagine): «Materiale imparato»", csd.curve.currentData() == cur.uid
      and csd.values()["burn_curve"] == cur.uid and csd.curve.isEnabled())
csd.dither.setCurrentIndex(csd.dither.findData("jarvis"))
check("…solo con il metodo Scala di grigi", not csd.curve.isEnabled())
cs2.burn_curve = "sparita"
csd2 = CutSettingsDialog(cs2, prof, w)
check("materiale del livello che non c'è su questo PC: si vede e non si perde",
      csd2.curve.currentData() == "sparita" and csd2.values()["burn_curve"] == "sparita")

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.TerminateProcess(k32.GetCurrentProcess(), code)
os._exit(code)
