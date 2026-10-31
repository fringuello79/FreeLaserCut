# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""v0.4: progetti LightBurn, galleria forme, comandi remoti / MCP, correzione dell'errore 'not callable'."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
errors = []
sys.excepthook = lambda t, e, tb: errors.append(f"{t.__name__}: {e}")

from freelasercut.core import gcode, lbrn, shapes_lib  # noqa: E402
from freelasercut.core.document import Document, GroupShape, PathShape, RectShape, SpecialShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(bool(ok))
    print(("  OK  " if ok else "  KO  ") + name, info)


# ------------------------------------------------------------ LightBurn
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.1.04" DeviceName="LONGER B1" FormatVersion="1">
  <VariableText><Start Value="0"/><End Value="999"/><Current Value="12"/><Increment Value="1"/><AutoAdvance Value="1"/></VariableText>
  <CutSetting type="Cut"><index Value="0"/><name Value="Taglio"/><minPower Value="10"/><maxPower Value="90"/>
    <speed Value="10"/><numPasses Value="2"/><priority Value="1"/></CutSetting>
  <CutSetting type="Scan"><index Value="1"/><name Value="C01"/><maxPower Value="35"/><speed Value="120"/>
    <interval Value="0.08"/><crossHatch Value="1"/><priority Value="0"/><doOutput Value="0"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="2"><XForm>1 0 0 1 100 50</XForm></Shape>
  <Shape Type="Ellipse" CutIndex="1" Rx="10" Ry="5"><XForm>1 0 0 1 30 30</XForm></Shape>
  <Shape Type="Group"><XForm>2 0 0 2 10 10</XForm><Children>
    <Shape Type="Path" CutIndex="1" VertID="7" PrimID="3"><XForm>1 0 0 1 0 0</XForm>
      <VertList>V0 0c0x1c1x1V10 0c0x1c1x1V10 10c0x1c1x1V0 10c0x1c1x1</VertList><PrimList>LineClosed</PrimList></Shape>
    <Shape Type="Path" CutIndex="1" VertID="7" PrimID="3"><XForm>1 0 0 1 20 0</XForm></Shape>
  </Children></Shape>
  <Shape Type="Path" CutIndex="0" VertID="9" PrimID="4"><XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x3c0y5c1x1V10 0c0x1c1x7c1y5</VertList><PrimList>B0 1</PrimList></Shape>
</LightBurnProject>"""
fp = os.path.join(tempfile.mkdtemp(), "prova.lbrn2")
with open(fp, "w", encoding="utf-8") as fh:
    fh.write(SAMPLE)
doc, warn = lbrn.load(fp)
l0, l1 = doc.layers[0], doc.layers[1]
check("LightBurn: impostazioni dei livelli (mm/s → mm/min, passate, uscita, riempimento)",
      l0.mode == "line" and l0.speed == 600 and l0.power_max == 90 and l0.power_min == 10 and l0.passes == 2
      and l0.name == "Taglio" and l1.mode == "fill" and l1.speed == 7200 and abs(l1.interval - 0.08) < 1e-9
      and l1.crosshatch and not l1.output, f"{l0.speed}, {l1.speed}")
rect = doc.shapes[0]
b = rect.bounds()
check("LightBurn: rettangolo centrato sull'XForm, con raggio", isinstance(rect, RectShape) and rect.radius == 2
      and abs(b.center().x() - 100) < 1e-6 and abs(b.center().y() - 50) < 1e-6 and abs(b.width() - 40) < 1e-6)
g = doc.shapes[2]
gb = g.bounds()
check("LightBurn: gruppo scalato e geometria condivisa (VertID)", isinstance(g, GroupShape) and len(g.children) == 2
      and abs(gb.left() - 10) < 1e-6 and abs(gb.width() - 60) < 1e-6 and abs(gb.height() - 20) < 1e-6,
      f"{gb.left():.2f} {gb.width():.2f}×{gb.height():.2f}")
curve = doc.shapes[3]
el = [curve.path().elementAt(i) for i in range(curve.path().elementCount())]
check("LightBurn: curva di Bézier con maniglie c0/c1", isinstance(curve, PathShape) and len(el) == 4
      and abs(el[1].x - 3) < 1e-6 and abs(el[2].x - 7) < 1e-6 and abs(el[1].y - 5) < 1e-6)
from freelasercut.core import variables  # noqa: E402

check("LightBurn: numerazione del progetto", variables.STATE["serial"] == 12 and variables.STATE["auto"])
job = gcode.generate(doc, MachineProfile(), gcode.JobOptions())
check("LightBurn: il progetto genera il G-code", job.lines and not [w for w in job.warnings if "esce" in w],
      f"{len(job.lines)} righe")

# ------------------------------------------------------------ galleria
okshapes = []
for key in shapes_lib.SHAPES:
    s = SpecialShape(key, 40, 30)
    p = s.path()
    bb = p.boundingRect()
    d = SpecialShape.__new__(SpecialShape)
    from freelasercut.core.document import shape_from_dict  # noqa: E402

    s2 = shape_from_dict(s.to_dict())
    if not p.isEmpty() and abs(bb.width() - 40) < 0.05 and abs(bb.height() - 30) < 0.05 and s2.params() == s.params():
        okshapes.append(key)
check("galleria: tutte le forme riempiono il riquadro e si salvano", len(okshapes) == len(shapes_lib.SHAPES),
      f"{len(okshapes)}/{len(shapes_lib.SHAPES)} {set(shapes_lib.SHAPES) - set(okshapes)}")

# ------------------------------------------------------------ finestra, errore Qt 'shape', comandi remoti
from freelasercut.ui import style  # noqa: E402
from freelasercut.theme import QSS  # noqa: E402

style.load_fonts()
app.setStyleSheet(QSS + style.QSS_EXTRA)
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
r = RectShape(30, 20)
w.editor.add([r])
app.processEvents()
items = w.canvas.scene().items(w.canvas.to_view(QPointF(r.bounds().center())) if False else r.bounds().center())
for it in items:
    it.shape()  # prima era un attributo: Qt lo chiamava e dava "'RectShape' object is not callable"
w.canvas.scene().collidingItems(items[0]) if items else None
app.processEvents()
check("niente più errore 'object is not callable' quando Qt interroga le forme", not errors, str(errors))

rs = w.remote
check("server locale per Claude in ascolto", rs is not None and rs.port, f"porta {rs.port if rs else None}")


def cmd(c, **a):
    return rs.handle(json.dumps({"token": rs.token, "cmd": c, "args": a}).encode())


bad = rs.handle(json.dumps({"token": "x", "cmd": "status"}).encode())
check("comandi rifiutati senza token", not bad["ok"])
a = cmd("add_shape", type="special", form="shield", width=40, height=50, x=200, y=200, layer=3)
t = cmd("add_text", text="CIAO", size=6, x=200, y=205, font="futural", layer=4)
st = cmd("set_layer", index=4, mode="line", speed_mm_min=3000, power_max_pct=25)
sn = cmd("snapshot", width=400)
est = cmd("estimate_job")
mv = cmd("transform", ids=[a["result"]["id"]], x=100, y=100, anchor="bottom_left")
start = cmd("machine", action="start_job")
check("comandi remoti: forme, testo, livello, immagine, stima, spostamento",
      a["ok"] and t["ok"] and st["ok"] and sn["ok"] and len(sn["result"]["png_base64"]) > 1000 and est["ok"]
      and mv["ok"] and abs(mv["result"][0]["x"] - 100) < 1e-6, str([x.get("error") for x in (a, t, st, sn, est, mv)]))
check("il laser non parte da remoto senza la macchina e senza conferma", not start["ok"] and "connessa" in start["error"])

# ------------------------------------------------------------ server MCP (stdio)
env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
p = subprocess.Popen([sys.executable, "-m", "freelasercut.mcp_server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     text=True, env=env)
out, _ = p.communicate("\n".join(json.dumps(m) for m in (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                    "clientInfo": {"name": "t", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n", timeout=30)
lines = [json.loads(x) for x in out.splitlines() if x.strip()]
tools = lines[1]["result"]["tools"] if len(lines) > 1 else []
check("server MCP: inizializzazione ed elenco degli strumenti", lines and lines[0]["result"]["serverInfo"]["name"] == "freelasercut"
      and len(tools) >= 25 and all(t["inputSchema"]["type"] == "object" for t in tools), f"{len(tools)} strumenti")
w.editor.dirty = False
w.close()
print(f"\n{sum(R)}/{len(R)} superati")
sys.exit(0 if all(R) else 1)
