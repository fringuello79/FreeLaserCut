# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.5: effetto «Ritratto a matita»; punto di partenza delle immagini; spiegazioni del retino;
Longer Ray5 10W e 20W separati; nessun riferimento particolare ad altri programmi (restano le estensioni apribili)."""
import sys, os, time, math, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import json
import numpy as np
import cv2
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication([])
from freelasercut.core import photo, photo_fx
from freelasercut.core.document import CutSettings, ImageShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# «ritratto» di prova: sfondo chiaro, viso medio, capelli e vestito scuri, occhi, bocca, rumore leggero
rng = np.random.default_rng(3)
W, H = 1000, 1200
im = Image.new("L", (W, H), 225)
d = ImageDraw.Draw(im)
d.rectangle((0, 900, W, H), fill=60)            # vestito
d.ellipse((260, 120, 740, 700), fill=45)        # capelli
d.ellipse((320, 220, 680, 820), fill=170)       # viso
d.ellipse((400, 420, 460, 470), fill=30)        # occhi
d.ellipse((540, 420, 600, 470), fill=30)
d.arc((420, 560, 580, 700), 20, 160, fill=40, width=8)  # bocca
g = np.clip(np.asarray(im, np.float32) + rng.normal(0, 4, (H, W)), 0, 255).astype(np.float32)
WMM = 100.0

check("«Ritratto a matita» tra gli effetti, subito dopo «Matita», senza direzione delle righe",
      list(photo_fx.EFFECTS)[1:3] == ["pencil", "drawing"] and photo_fx.EFFECTS["drawing"][1] is False)
out, sc = photo_fx.apply(g, "drawing", WMM, 0.5, 0.5)
check("immagine valida: stessa misura, grigi 0..255", out.dtype == np.float32 and out.shape == g.shape and
      out.min() >= 0 and out.max() <= 255 and sc == 1.0)
white, _ = photo_fx.apply(np.full((400, 500), 255.0, np.float32), "drawing", 40.0, 1.0, 1.0)
check("foto bianca: niente da incidere (lo sfondo bianco resta bianco)", (white < 250).mean() == 0.0,
      float((white < 250).mean()))
flat, _ = photo_fx.apply(np.full((400, 500), 128.0, np.float32), "drawing", 40.0, 0.5, 0.5)
check("foto tutta grigia: nessun errore, nessun contorno inventato", flat.min() > 60, float(flat.min()))
bg = out[30:100, 30:200].mean(); face = out[600:700, 380:620].mean(); hair = out[150:230, 300:400].mean()
check("i toni seguono la foto: sfondo chiaro > viso > capelli", bg > face > hair, (round(bg), round(face), round(hair)))
check("sfondo chiaro quasi carta (poco da incidere)", bg > 215, round(bg))
z = out[150:230, 300:400]
check("le ombre sono a tratteggio (tratti e spazi tra i tratti), non una macchia uniforme", z.std() > 25, round(float(z.std()), 1))
edge = out[700:830, 480:520]  # mento: bordo viso/capelli-vestito
check("i contorni ci sono: tratti scuri sul bordo del viso", (out[805:830, 300:700] < 110).mean() > 0.01 or
      (edge < 110).mean() > 0.01)
lo = photo_fx.apply(g, "drawing", WMM, 0.1, 0.5)[0].mean(); hi = photo_fx.apply(g, "drawing", WMM, 0.9, 0.5)[0].mean()
check("«Intensità» più alta: disegno più scuro", hi < lo - 10, (round(lo), round(hi)))
d0 = photo_fx.apply(g, "drawing", WMM, 0.5, 0.0)[0]; d1 = photo_fx.apply(g, "drawing", WMM, 0.5, 1.0)[0]
check("«Dettaglio» cambia il disegno", np.abs(d0 - d1).mean() > 1.0, round(float(np.abs(d0 - d1).mean()), 2))
check("sempre lo stesso risultato (anteprima e incisione uguali)", np.array_equal(out, photo_fx.apply(g, "drawing", WMM, 0.5, 0.5)[0]))
rng2 = np.random.default_rng(9)
nb = np.clip(250 + rng2.normal(0, 2, (600, 800)), 0, 255).astype(np.float32)
o_nb = photo_fx.apply(nb, "drawing", 80.0, 0.5, 0.5)[0]
check("sfondo quasi bianco con il rumore della foto: resta carta (il rumore non diventa tratti)",
      (o_nb < 240).mean() < 0.005 and (o_nb < 200).mean() == 0, round(float((o_nb < 240).mean()), 4))
ng = np.clip(128 + rng2.normal(0, 3, (600, 800)), 0, 255).astype(np.float32)
o_ng = photo_fx.apply(ng, "drawing", 80.0, 0.5, 0.5)[0]
check("grigio uniforme con rumore: tratteggio, ma niente contorni neri inventati", (o_ng < 100).mean() < 0.01,
      round(float((o_ng < 100).mean()), 4))
tiny = np.full((1400, 1400), 255, np.float32); cv2.circle(tiny, (700, 700), 60, 60, -1)
o_t = photo_fx.apply(tiny, "drawing", 100.0, 0.5, 0.5)[0]
ring = np.zeros((1400, 1400), np.uint8); cv2.circle(ring, (700, 700), 63, 1, 6)
check("soggetto piccolo su un foglio bianco grande: il contorno c'è", (o_t[ring > 0] < 150).mean() > 0.5,
      round(float((o_t[ring > 0] < 150).mean()), 2))
half = cv2.resize(g, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
m_half = photo_fx.apply(half, "drawing", WMM, 0.5, 0.5)[0].mean()
check("misure in mm: l'anteprima ridotta ha gli stessi toni della foto vera", abs(m_half - out.mean()) < 8,
      (round(float(out.mean()), 1), round(float(m_half), 1)))
huge = cv2.resize(g, (6000, 7200), interpolation=cv2.INTER_LINEAR)
t = time.time(); big, sc = photo_fx.apply(huge, "drawing", 100.0, 0.5, 0.5); dt = time.time() - t
check("foto da 43 megapixel larga 10 cm: pochi secondi, alla risoluzione utile al laser",
      dt < 6.0 and big.shape[1] <= 100 * photo_fx.WORK_PX_PER_MM + 2 and sc < 1.0, (round(dt, 2), big.shape))
# ------------------------------------------------------------------ dentro «Prepara foto»
st = photo.PhotoSettings(effect="drawing", width_mm=WMM, mask="oval")
a = np.asarray(photo.process(im, st))
check("con la forma ovale: gli angoli restano bianchi", a[0:20, 0:20].min() >= 250 and a.shape == (H, W))
rt = photo.PhotoSettings.from_dict(photo.PhotoSettings(effect="drawing", effect_strength=65, effect_detail=30,
                                                       width_mm=WMM).to_dict())
check("si salva nel progetto e si ritrova", (rt.effect, rt.effect_strength, rt.effect_detail) == ("drawing", 65.0, 30.0))
from freelasercut.ui.dialogs_photo import PhotoDialog
dlg = PhotoDialog(ImageShape("x", 100, 120), im.convert("RGB"), CutSettings(index=0), (100.0, 120.0))
dlg.effect.setCurrentIndex(dlg.effect.findData("drawing"))
check("nella finestra: intensità e «Dettaglio», senza direzione delle righe",
      dlg.fx_strength.isVisibleTo(dlg) and dlg.fx_detail_name.text() == "Dettaglio" and not dlg.fx_angle.isVisibleTo(dlg))
dlg._refresh()
check("anteprima della finestra senza errori", "Errore" not in dlg.info.text(), dlg.info.text())
check("«Matita» c'è ancora, come prima", dlg.effect.findData("pencil") >= 0 and
      np.array_equal(photo_fx.apply(g, "pencil", WMM, 0.5, 0.5)[0], np.clip(photo_fx.pencil(g, W / WMM, 0.5, 0.5), 0, 255).astype(np.float32)))


# ================================================================== punto di partenza delle immagini
import re
from PySide6.QtGui import QTransform
from freelasercut.core import gcode
from freelasercut.core.document import Document, IMAGE_STARTS
from freelasercut.grbl import GrblController, SIM_PORT
from freelasercut.profile import MachineProfile


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)


def run_job(job, negative=False):
    os.environ["FLC_SIM_NEGATIVE"] = "1" if negative else "0"
    c = GrblController(); res = {}
    c.job_finished.connect(lambda ok, m: res.update(ok=ok, msg=m))
    c.error_raised.connect(lambda code, t, l: res.setdefault("err", []).append((code, l)))
    c.connect_port(SIM_PORT); spin(2.0); c.sim.speedup = 40
    c.home(); spin(1.0 if not negative else 8)
    c.sim.burn_marks.clear()
    c.stream_job(job.lines); t = time.time()
    while "ok" not in res and time.time() - t < 120:
        spin(0.05)
    spin(0.3)
    marks = np.array([c.sim.to_bed(x, y) for x, y in c.sim.burn_marks]) if c.sim.burn_marks else np.zeros((0, 2))
    c.disconnect_port(); spin(0.2)
    return res, marks


check("quattro partenze: dall'alto, dal basso, da sinistra, da destra", list(IMAGE_STARTS) == ["top", "bottom", "left", "right"])
check("progetti di prima: partenza dall'alto", CutSettings().image_start == "top" and
      CutSettings.from_dict({"mode": "image"}).image_start == "top")
check("valore sconosciuto (versione futura o file rovinato): dall'alto, nessun errore",
      CutSettings.from_dict({"image_start": "diagonale"}).image_start == "top" and
      CutSettings.from_dict({"image_start": ["x"]}).image_start == "top")
check("si salva nel progetto", CutSettings.from_dict(CutSettings(image_start="left").to_dict()).image_start == "left")

# foto 20 × 10 mm: nera solo nel quarto in alto a sinistra e in una striscia in basso a destra
pic = np.full((100, 200), 255, np.uint8); pic[:50, :100] = 0; pic[80:, 150:] = 0
prof = MachineProfile()
STEP = 25.4 / 50


def job_for(start, negative=False):
    doc = Document()
    doc.images["p"] = Image.fromarray(pic)
    s = ImageShape("p", 20, 10, layer=0); s.apply(QTransform.fromTranslate(100, 100)); doc.add(s)
    c = doc.layer(0); c.mode, c.dither, c.dpi, c.power_max, c.speed = "image", "threshold", 50, 40, 3000
    c.overscan, c.image_start = 1.0, start
    p = MachineProfile(); p.negative_space = negative
    p.scan_offsets = []  # senza correzione avanti/indietro i tratti finiscono esattamente sui bordi dei punti
    return gcode.generate(doc, p, gcode.JobOptions(start_from="absolute"))


def burns(job):
    """Tratti incisi dal G-code (G0/G1, coordinate e S modali): [(x0, y0, x1, y1)]."""
    out, x, y, mode, sv = [], None, None, "G0", 0.0
    for l in job.lines:
        if l.startswith(";"):
            continue
        mg = re.match(r"G([01])\b", l)
        if mg:
            mode = "G" + mg.group(1)
        mx, my, ms = re.search(r"X(-?[\d.]+)", l), re.search(r"Y(-?[\d.]+)", l), re.search(r"S([\d.]+)", l)
        if ms:
            sv = float(ms.group(1))
        nx = float(mx.group(1)) if mx else x
        ny = float(my.group(1)) if my else y
        if mode == "G1" and sv > 0 and x is not None and (nx, ny) != (x, y):
            out.append((x, y, nx, ny))
        x, y = nx, ny
    return out


def burned_cells(job):
    """Punti della foto toccati dal laser (centri dei pixel lungo ogni tratto)."""
    cells = set()
    for x0, y0, x1, y1 in burns(job):
        L = math.hypot(x1 - x0, y1 - y0)
        for i in range(int(round(L / STEP))):
            t = (i + 0.5) * STEP / L
            cells.add((int(math.floor((x0 + t * (x1 - x0) - 100) / STEP + 0.5)),
                       int(math.floor((y0 + t * (y1 - y0) - 100) / STEP + 0.5))))
    return cells


jobs = {k: job_for(k) for k in IMAGE_STARTS}
check("G-code per ogni partenza, senza avvisi", all(j.lines and not j.warnings for j in jobs.values()),
      {k: len(j.lines) for k, j in jobs.items()})
runs = {}
for k, j in jobs.items():
    res, m = run_job(j)
    runs[k] = (res, m)
check("eseguito sulla macchina simulata senza errori, con ogni partenza",
      all(r.get("ok") and not r.get("err") and len(m) > 20 for r, m in runs.values()),
      {k: (r.get("ok"), len(m), str(r.get("err", ""))[:60]) for k, (r, m) in runs.items()})
first = {k: m[0] for k, (r, m) in runs.items()}
check("dall'alto: il primo punto inciso è in alto (nel quarto nero in alto a sinistra)",
      first["top"][1] > 104.5 and first["top"][0] < 110.5, first["top"])
check("dal basso: il primo punto inciso è in basso (nella striscia in basso a destra)",
      first["bottom"][1] < 102.5 and first["bottom"][0] > 114.5, first["bottom"])
check("da sinistra: il primo punto inciso è a sinistra, in alto", first["left"][0] < 101 and first["left"][1] > 104.5, first["left"])
check("da destra: il primo punto inciso è a destra, in basso (la striscia)", first["right"][0] > 119 and first["right"][1] < 102.5,
      first["right"])


def mostly_vertical(job):
    b = burns(job)
    return sum(1 for x0, y0, x1, y1 in b if abs(x1 - x0) < 1e-6 and abs(y1 - y0) > 0) / max(1, len(b)), len(b)


v_left, n_left = mostly_vertical(jobs["left"])
v_top, n_top = mostly_vertical(jobs["top"])
check("da sinistra / da destra: righe verticali (la testa incide muovendosi solo in Y)",
      v_left > 0.99 and mostly_vertical(jobs["right"])[0] > 0.99 and v_top < 0.01, (round(v_left, 3), round(v_top, 3)))
cells = {k: burned_cells(j) for k, j in jobs.items()}
ref = cells["top"]
diff = {k: len(c ^ ref) / max(1, len(ref)) for k, c in cells.items()}
check("con ogni partenza si incidono esattamente gli stessi punti (cambia solo il percorso)" + f" [{len(ref)} punti]",
      len(ref) > 200 and max(diff.values()) == 0,
      {k: round(v, 4) for k, v in diff.items()})
res_n, m_n = run_job(job_for("left", negative=True), negative=True)
n_left = len(runs["left"][1])
check("righe verticali anche con le coordinate negative della macchina: si parte a sinistra, stesso lavoro",
      res_n.get("ok") and not res_n.get("err") and m_n[0][0] < 101 and m_n[0][1] > 104.5 and
      abs(len(m_n) - n_left) <= max(3, 0.03 * n_left), (len(m_n), n_left, m_n[0] if len(m_n) else None))


def job_offsets(start, offsets):
    doc = Document()
    doc.images["p"] = Image.fromarray(pic)
    s_ = ImageShape("p", 20, 10, layer=0); s_.apply(QTransform.fromTranslate(100, 100)); doc.add(s_)
    c = doc.layer(0); c.mode, c.dither, c.dpi, c.power_max, c.speed = "image", "threshold", 50, 40, 3000
    c.image_start = start
    p = MachineProfile(); p.scan_offsets = offsets
    return gcode.generate(doc, p, gcode.JobOptions(start_from="absolute")).lines


OFF = [[3000.0, 0.4], [6000.0, 0.6]]
check("correzione avanti/indietro (misurata lungo X): usata per le righe orizzontali, non per quelle verticali",
      job_offsets("top", OFF) != job_offsets("top", []) and job_offsets("left", OFF) == job_offsets("left", []))
fast_t, slow_t = jobs["top"].seconds, jobs["left"].seconds
check("stima del tempo calcolata anche per le righe verticali", fast_t > 0 and slow_t > 0, (round(fast_t, 1), round(slow_t, 1)))

# ================================================================== finestra delle impostazioni di taglio
from freelasercut.ui.panels_design import CutSettingsDialog
cs_img = CutSettings(index=0, mode="image", dither="floyd", image_start="right")
dl = CutSettingsDialog(cs_img, prof)
check("retino: cella e angolo spiegati passando sopra con il cursore",
      "Mezzetinte" in dl.hcell.toolTip() and "Mezzetinte" in dl.hangle.toolTip() and dl.hcell_name.toolTip())
check("retino: con un altro metodo cella e angolo sono grigi (non servono)", not dl.hcell.isEnabled() and not dl.hangle.isEnabled())
dl.dither.setCurrentIndex(dl.dither.findData("halftone"))
check("retino: con «Mezzetinte» cella e angolo si possono cambiare", dl.hcell.isEnabled() and dl.hangle.isEnabled())
check("«Partenza» nella scheda Immagine: le quattro scelte, si apre con quella del livello",
      dl.istart.count() == 4 and dl.istart.currentData() == "right" and dl.istart.toolTip())
dl.istart.setCurrentIndex(dl.istart.findData("bottom"))
check("…e la scelta torna nelle impostazioni del livello", dl.values()["image_start"] == "bottom")
check("etichetta «Partenza della foto», diversa da «Partenza» del pannello Laser (che resta com'era)",
      json.load(open(os.path.join(ROOT, "freelasercut", "locale", "en.json"), encoding="utf-8"))["Partenza"] == "Start from"
      and any(w_.text() == "Partenza della foto" for w_ in dl.findChildren(QLabel)))

# ================================================================== Longer Ray5
from freelasercut import machines
cat = {c[0]: c for c in machines.CATALOG}
check("Longer Ray5 10W e 20W separati (prima una voce sola), il vecchio nome non c'è più",
      "Longer Ray5 10W" in cat and "Longer Ray5 20W" in cat and "Longer Ray5 10W / 20W" not in cat and len(cat) >= 49)  # 51 dalla 0.17.2 (Mecpow X3S)
check("Ray5 10W: 400 × 400 mm, 10.000 mm/min, spot 0,06 mm (pagina Longer)",
      cat["Longer Ray5 10W"][2:4] == (400, 400) and cat["Longer Ray5 10W"][5] == 10000 and
      machines.SPOTS["Longer Ray5 10W"] == (0.06, 0.06))
check("Ray5 20W: dichiarati 400 × 365, qui 365 × 365 per prudenza, con la nota",
      cat["Longer Ray5 20W"][2:4] == (365, 365) and machines.AREA_NOTE["Longer Ray5 20W"] == (400, 365) and
      "400 × 365" in machines.NOTES["Longer Ray5 20W"])
check("fonti ufficiali Longer per i due modelli", all("longer" in machines.SOURCES[n] for n in ("Longer Ray5 10W", "Longer Ray5 20W")))
idn = machines.identify(banner=["Grbl 1.1h ['$' for help]", "[LGT V1.0]"], settings={130: 400, 131: 365})
check("un Ray5 20W collegato (area 400 × 365 letta dalla scheda) viene riconosciuto", idn.model == "Longer Ray5 20W",
      (idn.model, idn.candidates))
idn = machines.identify(banner=["Grbl 1.1h ['$' for help]", "[LGT V1.0]"], settings={130: 400, 131: 400})
check("Longer 400 × 400: si sceglie tra Ray5 5W e 10W", sorted(idn.candidates) == ["Longer Ray5 10W", "Longer Ray5 5W"],
      idn.candidates)

# ================================================================== niente citazioni particolari di altri programmi
import json
from freelasercut.ui import help_texts, main_window
LOC = os.path.join(ROOT, "freelasercut", "locale")
hits = [l for l in ("en", "es", "fr", "pt") for k, v in json.load(open(os.path.join(LOC, l + ".json"), encoding="utf-8")).items()
        if "lightburn" in (k + v).lower()]
hits += [k for k, v in help_texts.HELP.items() if "lightburn" in str(v).lower()]
check("testi del programma e traduzioni: nessuna citazione particolare", not hits, hits[:5])
check("i progetti .lbrn2 e .lbrn si aprono ancora (nel filtro di Apri)", "*.lbrn2 *.lbrn" in main_window.OPEN_FILTER)

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
