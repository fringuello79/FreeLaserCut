# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.2: foto e disegni su livelli separati, formati delle immagini.
- un portachiavi con foto e scritta: prima, se finivano sullo stesso livello, se ne incideva una sola;
- foto su un livello non Immagine: ora c'è l'avviso (prima veniva saltata in silenzio);
- LightBurn: stesso colore con foto e disegni → la foto su un livello suo, i disegni restano;
- immagini a 16 bit, foto dei telefoni ruotate (EXIF), trasparenza nei PNG senza canale alfa."""
import sys, os, io, tempfile, base64
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication
app = QApplication([])
from freelasercut.core import io_formats, gcode, lbrn
from freelasercut.core.document import Document, ImageShape, RectShape, TextShape
from freelasercut.profile import MachineProfile
from freelasercut.ui.editor import Editor
from freelasercut.grbl import SIM_PORT

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

D = tempfile.mkdtemp()
def photo(name="foto.png"):
    im = Image.new("RGB", (60, 40), "white")
    ImageDraw.Draw(im).ellipse((10, 5, 50, 35), fill="black")
    p = os.path.join(D, name)
    im.save(p)
    return p

def layers_of(doc):
    return {leaf.layer: doc.layer(leaf.layer).mode for s in doc.shapes for leaf, _ in s.leaves()}

def engraved(doc):
    job = gcode.generate(doc, MachineProfile(), gcode.JobOptions())
    kinds = {st.index: (st.mode, st.lines) for st in job.layers}
    return job, kinds

# ------------------------------------------------------------------ portachiavi: foto, poi scritta sul livello della foto
ed = Editor()
msgs = []
ed.message.connect(msgs.append)
img = io_formats.import_file(photo(), ed.doc)
ed.add(img, "Importa")
ed.doc.layer(img[0].layer).mode = "image"
ed.current_layer = img[0].layer  # dopo aver toccato la foto il livello corrente è il suo
t = TextShape("Ale", "Arial", 8, layer=ed.current_layer)
ed.add(t, "Testo")
lay = layers_of(ed.doc)
check("portachiavi: la scritta creata sul livello della foto finisce su un altro livello", t.layer != img[0].layer and
      lay[img[0].layer] == "image" and lay[t.layer] != "image", lay)
check("…e la barra di stato lo dice", msgs and "livello" in msgs[-1], msgs[-1:] if msgs else None)
job, kinds = engraved(ed.doc)
check("…nel lavoro ci sono tutte e due: foto e scritta", len(kinds) == 2 and all(n > 0 for _, n in kinds.values()), kinds)
# un livello di taglio già usato non deve «accogliere» la scritta: va su un livello nuovo, con le impostazioni di base
ed = Editor()
img = io_formats.import_file(photo("k.png"), ed.doc)
ed.add(img, "Importa")
cut = RectShape(40, 20, layer=1)
ed.add(cut)
ed.doc.layer(1).mode, ed.doc.layer(1).power_max, ed.doc.layer(1).passes = "line", 100.0, 3
t = TextShape("Ale", "Arial", 8, layer=img[0].layer)
ed.add(t, "Testo")
check("scritta sul livello della foto con un taglio già su C01: va su un livello NUOVO, non sul taglio",
      t.layer not in (img[0].layer, 1) and ed.doc.layer(t.layer).power_max != 100.0 and ed.doc.layer(1).passes == 3,
      (t.layer, ed.doc.layer(t.layer).power_max))
# ------------------------------------------------------------------ prima la scritta, poi la foto sullo stesso livello
ed = Editor()
t = TextShape("Ale", "Arial", 8, layer=0)
ed.add(t, "Testo")
img = io_formats.import_file(photo("b.png"), ed.doc)   # le immagini arrivano sul livello 0
ed.add(img, "Importa")
check("foto importata dove c'è già una scritta (C00): va su un livello Immagine suo, la scritta resta",
      t.layer == 0 and img[0].layer != 0 and ed.doc.layer(img[0].layer).mode == "image" and ed.doc.layer(0).mode != "image",
      layers_of(ed.doc))
job, kinds = engraved(ed.doc)
check("…nel lavoro foto e scritta", len(kinds) == 2 and all(n > 0 for _, n in kinds.values()), kinds)
# ------------------------------------------------------------------ Cambia livello con foto e scritta selezionate insieme
ed.select([t] + img)
ed.set_layer(5)
check("foto e scritta selezionate e messe insieme su C05: non si mescolano", t.layer == 5 and img[0].layer != 5 and
      ed.doc.layer(img[0].layer).mode == "image", layers_of(ed.doc))
ed.undo()
after = sorted((type(l).__name__, l.layer) for s in ed.doc.shapes for l, _ in s.leaves())
check("Annulla rimette tutto com'era (scritta su C00, foto sul suo livello Immagine)",
      after == [("ImageShape", 1), ("TextShape", 0)] and ed.doc.layer(1).mode == "image", after)
# solo la foto su un livello vuoto: il livello diventa Immagine
ed = Editor()
img = io_formats.import_file(photo("c.png"), ed.doc)
ed.add(img, "Importa")
ed.select(img)
ed.set_layer(7)
check("solo la foto su un livello vuoto: resta lì e il livello diventa Immagine", img[0].layer == 7 and
      ed.doc.layer(7).mode == "image")
r = RectShape(10, 10, layer=7)
ed.add(r)
check("rettangolo disegnato sul livello della foto: va altrove, la foto resta su C07", img[0].layer == 7 and r.layer != 7)
# ------------------------------------------------------------------ avviso per le foto su un livello non Immagine
doc = Document()
im = io_formats.import_file(photo("d.png"), doc)[0]
im.layer = 3
doc.add(im)
doc.layer(3).mode = "line"
job = gcode.generate(doc, MachineProfile(), gcode.JobOptions())
check("foto su un livello Linea (progetto vecchio): avviso chiaro invece del silenzio",
      any("foto su un livello che non è in modalità Immagine" in w for w in job.warnings), job.warnings)
# ------------------------------------------------------------------ LightBurn: stesso colore, foto e scritta
png = io.BytesIO(); Image.new("L", (20, 10), 0).save(png, "PNG")
DATA = base64.b64encode(png.getvalue()).decode()
xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.1.04" FormatVersion="1">
  <CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="30"/><speed Value="150"/></CutSetting>
  <CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><maxPower Value="40"/><speed Value="100"/></CutSetting_Img>
  <Shape Type="Bitmap" CutIndex="0" W="20" H="10" Data="{DATA}"><XForm>1 0 0 -1 50 60</XForm></Shape>
  <Shape Type="Rect" CutIndex="0" W="30" H="8" Cr="0"><XForm>1 0 0 1 50 40</XForm></Shape>
</LightBurnProject>"""
fp = os.path.join(D, "misto.lbrn2"); open(fp, "w", encoding="utf-8").write(xml)
doc, warns = lbrn.load(fp)
imgs = [l for s in doc.shapes for l, _ in s.leaves() if isinstance(l, ImageShape)]
vecs = [l for s in doc.shapes for l, _ in s.leaves() if not isinstance(l, ImageShape)]
check("LightBurn, stesso colore con foto e rettangolo: il rettangolo resta su C00 con le sue impostazioni (riempimento)",
      vecs[0].layer == 0 and doc.layer(0).mode == "fill" and abs(doc.layer(0).power_max - 30) < 1e-6,
      (doc.layer(0).mode, doc.layer(0).power_max))
check("…la foto va su un livello suo con le impostazioni da immagine", imgs[0].layer != 0 and
      doc.layer(imgs[0].layer).mode == "image" and abs(doc.layer(imgs[0].layer).power_max - 40) < 1e-6 and
      doc.layer(imgs[0].layer).label() != "C00", doc.layer(imgs[0].layer).label())
check("…e un avviso spiega dove è finita la foto", any("le foto sono sul livello" in w for w in warns), warns)
job = gcode.generate(doc, MachineProfile(), gcode.JobOptions())
check("…nel lavoro ci sono tutte e due", len([st for st in job.layers if st.lines > 0]) == 2)
# ------------------------------------------------------------------ formati
i16 = np.full((40, 60), 30000, np.uint16); Image.fromarray(i16).save(os.path.join(D, "g16.png"))
doc = Document(); s = io_formats.import_file(os.path.join(D, "g16.png"), doc)[0]
check("PNG a 16 bit: il grigio resta grigio (prima diventava bianco)", abs(doc.images[s.image_id].getpixel((0, 0)) - 117) <= 1,
      doc.images[s.image_id].getpixel((0, 0)))
im = Image.new("RGB", (80, 40), "white"); ImageDraw.Draw(im).rectangle((0, 0, 10, 10), fill="black")
ex = Image.Exif(); ex[0x0112] = 6; im.save(os.path.join(D, "tel.jpg"), exif=ex.tobytes(), dpi=(254, 254))
doc = Document(); s = io_formats.import_file(os.path.join(D, "tel.jpg"), doc)[0]
check("foto del telefono in verticale (EXIF): arriva dritta, non coricata", doc.images[s.image_id].size == (40, 80) and
      abs(s.w - 4) < 0.05 and abs(s.h - 8) < 0.05, (doc.images[s.image_id].size, s.w, s.h))
Image.new("RGB", (20, 20), "white").save(os.path.join(D, "trns.png"), transparency=(255, 255, 255))
doc = Document(); s = io_formats.import_file(os.path.join(D, "trns.png"), doc)[0]
check("PNG con colore trasparente (senza canale alfa): la trasparenza resta", doc.images[s.image_id].mode == "RGBA" and
      doc.images[s.image_id].getpixel((0, 0))[3] == 0)
for ext, mode in ((".webp", "RGB"), (".gif", "P"), (".tif", "RGB"), (".bmp", "1"), (".jpg", "CMYK")):
    p = os.path.join(D, "f" + ext)
    base = Image.new("RGB", (30, 20), "white"); ImageDraw.Draw(base).rectangle((5, 5, 15, 15), fill="black")
    base.convert(mode).save(p)
    doc = Document(); sh = io_formats.import_file(p, doc)
    a = np.asarray(doc.images[sh[0].image_id].convert("L"))
    if not (a[10, 10] < 60 and a[1, 1] > 200):
        check(f"formato {ext} ({mode}): nero e bianco al loro posto", False, (a[10, 10], a[1, 1]))
        break
else:
    check("WEBP, GIF, TIFF, BMP a 1 bit, JPEG CMYK: nero e bianco al loro posto", True)
# ------------------------------------------------------------------ verifica solo a macchina ferma
import time
from freelasercut.grbl import GrblController, SIM_PORT
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()
c = GrblController()
c.connect_port(SIM_PORT)
c.sim.speedup = 1
until(lambda: c.board_settings and c.last_status.get("state") == "Idle")
done, sent, msgs = [], [], []
c.check_finished.connect(done.append)
c.line_sent.connect(sent.append)
c.message.connect(msgs.append)
JOB = ["G90 G21", "M4 S0", "G1 X50 Y50 S800 F3000", "G1 X60 Y50", "M5 S0"]
c.jog(200, 0, 600)  # spostamento lungo e lento: la macchina è in «Jog»
until(lambda: c.last_status.get("state") == "Jog", 5)
check("verifica chiesta mentre la testa si muove: rifiutata, niente inviato",
      c.check_job(JOB) is False and not any(l.startswith("G1") for l in sent) and msgs and "non è ferma" in msgs[-1],
      (c.last_status.get("state"), msgs[-1:] if msgs else None))
c.jog_cancel()
until(lambda: c.last_status.get("state") == "Idle", 10)
# lo stato dice ancora «Idle» (report vecchio) ma la scheda non è ferma (qui: in pausa): $C rifiutato con error:8
c.sim.state = "Hold"
c.last_status["state"] = "Idle"
sent.clear()
ok = c.check_job(JOB)
until(lambda: done, 5)
errs_shown = []
c.error_raised.connect(lambda code, text, line: errs_shown.append(line))
check("$C rifiutato dalla scheda (error:8): la verifica si chiude e le righe del lavoro NON partono",
      ok and done and done[-1][0][2] == "NON_PRONTA" and not any(l.startswith(("G1", "M4")) for l in sent) and
      not c.checking, (done[-1][:1] if done else None, sent))
check("…e il rifiuto si spiega una volta sola (niente secondo messaggio d'errore per $C)", "$C" not in errs_shown, errs_shown)
c.sim.state = "Idle"
until(lambda: c.last_status.get("state") == "Idle", 10)
done.clear(); sent.clear()
check("a macchina ferma la verifica parte: prima $C, le righe solo dopo il suo «ok»",
      c.check_job(JOB) and until(lambda: done, 10) and done[-1] == [] and sent[0] == "$C" and "G90 G21" in sent, sent[:3])
long_line = "G1 X1 Y1 ; " + "x" * 10 + " " + "Y1 " * 60
too = ["G90", "G1 " + " ".join(f"X{i}" for i in range(200))]
until(lambda: c.last_status.get("state") == "Idle" and not c.busy and not c.checking, 10)
until(lambda: False, 1.0)
msgs.clear()
check("riga più lunga del buffer della scheda: lavoro rifiutato subito con il motivo (prima restava fermo in silenzio)",
      c.check_job(too) is False and any("troppo lunga" in m for m in msgs), msgs)
# ------------------------------------------------------------------ la scheda si riavvia a metà lavoro
fin = []
c.job_finished.connect(lambda ok, msg: fin.append((ok, msg)))
until(lambda: c.last_status.get("state") == "Idle" and not c.busy and not c.checking, 10)
c.sim.speedup = 1
c.stream_job(["G90 G21", "M4 S0"] + [f"G1 X{10 + i} Y10 S100 F600" for i in range(40)] + ["M5 S0"])
until(lambda: c.job_active and c.last_status.get("state") == "Run", 5)
c.sim._reset()  # calo di tensione / watchdog: la scheda riparte da sola e manda il banner
check("scheda riavviata durante il lavoro: il lavoro risulta interrotto (prima restava «in lavoro» per sempre)",
      until(lambda: fin, 5) and fin[-1][0] is False and not c.job_active, fin[-1:])
c.disconnect_port()

# ------------------------------------------------------------------ copie delle impostazioni con codifica diversa
from freelasercut import board_backup
bd = tempfile.mkdtemp()
open(os.path.join(bd, "vecchia.txt"), "wb").write("# FreeLaserCut\n# motivo: modificata a mano, perché è così\n$100=80\n"
                                                    .encode("cp1252"))
try:
    lst = board_backup.list_backups(bd)
    ok = len(lst) == 1 and lst[0][1]["count"] == 1
    board_backup.save({100: "80.000", 101: "80.000"}, [], "prova", "COM3", folder=bd) if "folder" in \
        board_backup.save.__code__.co_varnames else None
except Exception as ex:  # noqa: BLE001
    ok = False
    print(ex)
check("copia salvata da un editor in un'altra codifica (accenti): si legge, niente blocchi alla connessione", ok)

# ------------------------------------------------------------------ velocità in mm/s: aprire un campo non la cambia
os.environ["FLC_SPEED_UNIT"] = "mm/s"
from freelasercut import units
drift = []
for v in (1000, 100, 250, 50, 10):
    sp = units.SpeedSpin(val=v)
    sp.interpretText(); sp.interpretText()
    si = units.SpeedIntSpin(); si.setRange(1, 36000); si.setValue(v); si.interpretText()
    if sp.value() != v or si.value() != v:
        drift.append((v, sp.value(), si.value()))
sp = units.SpeedSpin(val=1000); sp.lineEdit().setText("20"); sp.interpretText()
check("velocità mostrate in mm/s: rileggere il campo non le cambia (prima 1000 → 1002, 50 → 48 mm/min)",
      not drift and sp.value() == 1200, drift)
os.environ.pop("FLC_SPEED_UNIT", None)

# ------------------------------------------------------------------ finestra: Porta la testa qui, limiti, allarme, puntino
os.environ.setdefault("FLC_UI", "classica")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from PySide6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
w.qs.setValue("fire_pct", 15.0)
w2 = MainWindow()
check("puntino oltre il 5% salvato: alla riapertura riparte dal 5% (la conferma va data di nuovo)",
      w2.laser.fire_pct.value() <= 5.0, w2.laser.fire_pct.value())
w2.editor.dirty = False; w2.close()
r = RectShape(20, 10); r.apply(QTransform.fromTranslate(100, 100)); w.editor.doc.add(r)
w.ctl.connect_port(SIM_PORT); w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.canvas.head_pos() is not None)
# origine utente lontana dal disegno: la fisso sulla scheda (G10 L20), così il dato arriva dalla scheda stessa
w.ctl.goto_machine(30, 40) if hasattr(w.ctl, "goto_machine") else w.ctl.jog_to(30, 40)
until(lambda: w.ctl.last_status.get("state") == "Idle" and abs(w.canvas.head_pos().x() - 30) < 0.2, 8)
w.ctl.set_work_origin()
until(lambda: abs(w.work_origin_on_bed()[0] - 30) < 0.2 and abs(w.work_origin_on_bed()[1] - 40) < 0.2, 8)
lp = w.laser
lp.start_from.setCurrentIndex(lp.start_from.findData("origin"))
lp.anchor.value = 0
got = w.goto_anchor()
ox, oy = w.work_origin_on_bed()
check("«Origine utente»: Porta la testa qui va sull'origine, dove il lavoro inciderà davvero (non sul disegno)",
      got is not None and abs(got[0] - ox) < 0.01 and abs(got[1] - oy) < 0.01 and abs(ox - 30) < 0.2 and
      "origine utente" in w.statusBar().currentMessage(), (got, (ox, oy)))
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
# limiti software con l'asse Y invertito
class FakeJob:
    preview = None
    out_to_bed = (0.0, 0.0)
    def __init__(self, x0, y0, x1, y1):
        from PySide6.QtCore import QRectF
        self.motion_bounds = QRectF(x0, y0, x1 - x0, y1 - y0)
w.ctl.sim.settings[20] = "1"; w.ctl.request_settings()
until(lambda: w.ctl.soft_limits() is not None, 5)
w.profile.invert_y = True
inside = w._soft_limit_problem(FakeJob(10, 10, 100, 100))
outside = w._soft_limit_problem(FakeJob(10, 10, 100, 500))
check("limiti software con l'asse Y invertito: dentro va bene, fuori si blocca", inside is None and outside is not None,
      (inside, (outside or "")[:40]))
w.profile.invert_y = False
# un suggerimento in alto non deve nascondere l'allarme
w.show(); app.processEvents()
w.banner.hide()
w.show_banner("Novità di prova", "info", [], hint=True)
w._alarm_dismissed = False
w.on_status({"state": "Alarm", "MPos": [0, 0, 0], "WPos": [0, 0, 0]})
check("allarme mentre c'è un suggerimento in alto: compare l'allarme", w._banner_kind == "alarm" and w.banner.isVisible(),
      w._banner_kind)
w.banner.hide()
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
