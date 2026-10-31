# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
import sys, os, time, math
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import tempfile; os.environ['APPDATA']=tempfile.mkdtemp()
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtTest import QTest
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle('Fusion'); style.load_fonts(); app.setFont(style.ui_font(9.5))
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from freelasercut.ui.main_window import MainWindow
from freelasercut.core.document import RectShape, EllipseShape, PathShape, TextShape, PolygonShape, GroupShape
w = MainWindow(); w.resize(1600, 980); w.show()
cv, ed = w.canvas, w.editor
R = []
def check(n, ok, info=''):
    R.append(bool(ok)); print(('  OK  ' if ok else '  KO  ')+n, info)
def spin(t=0.05):
    e=time.time()+t
    while time.time()<e: app.processEvents(); time.sleep(0.005)
spin(0.8)
vp = cv.viewport()
def V(x, y):
    p = cv.to_view(QPointF(x, y)); return QPoint(int(round(p.x())), int(round(p.y())))
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent
def _send(t, p, btn, btns, mods):
    ev = QMouseEvent(t, QPointF(p), QPointF(vp.mapToGlobal(p)), btn, btns, mods)
    QApplication.sendEvent(vp, ev)
def drag(a, b, mods=Qt.NoModifier, steps=8):
    _send(QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton, mods); spin()
    for i in range(1, steps+1):
        p = a + (b - a) * (i / steps)
        _send(QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton, mods); spin(0.01)
    _send(QEvent.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton, mods); spin()
cv.snap_objects = False
# --- rettangolo con lo strumento
w.tool_actions['rect'].trigger(); spin()
drag(V(50, 50), V(130, 100))
r = ed.doc.shapes[-1]; b = r.bounds()
check('strumento rettangolo: 80×50 mm disegnato col mouse', isinstance(r, RectShape) and abs(b.width()-80)<0.6 and abs(b.height()-50)<0.6, f'{b.width():.2f}×{b.height():.2f}')
check('dopo il disegno torna lo strumento Selezione e la forma è selezionata', cv.tool.name=='select' and ed.selection==[r])
# --- ellisse con Maiusc = cerchio
w.tool_actions['ellipse'].trigger(); spin()
drag(V(200, 50), V(240, 70), Qt.ShiftModifier)
e = ed.doc.shapes[-1]; b = e.bounds()
check('ellisse con Maiusc = cerchio', isinstance(e, EllipseShape) and abs(b.width()-b.height())<0.01, f'{b.width():.2f}×{b.height():.2f}')
# --- sposta trascinando
ed.select([r]); spin()
b0 = r.bounds()


drag(V(50, 62), V(70, 72))   # afferra il bordo sinistro lontano dalle maniglie

b1 = ed.doc.shapes[0].bounds()
check('trascina per spostare: +20 X, +10 Y', abs(b1.left()-b0.left()-20)<0.6 and abs(b1.top()-b0.top()-10)<0.6, f'Δ {b1.left()-b0.left():.2f}, {b1.top()-b0.top():.2f}')
# --- scala dalla maniglia angolo (proporzioni bloccate)
r = ed.doc.shapes[0]; ed.select([r]); spin()
b = r.bounds()
drag(V(b.right(), b.bottom()), V(b.right()+40, b.bottom()+10))
b2 = ed.doc.shapes[0].bounds()
check('maniglia d\'angolo: scala proporzionale', abs(b2.width()/b2.height() - b.width()/b.height())<0.01 and b2.width() > b.width()+30, f'{b2.width():.1f}×{b2.height():.1f}')
# --- annulla / ripeti
ed.undo(); spin(); b3 = ed.doc.shapes[0].bounds()
check('annulla la scala', abs(b3.width()-b.width())<1e-6)
ed.redo(); spin(); b4 = ed.doc.shapes[0].bounds()
check('ripeti la scala', abs(b4.width()-b2.width())<1e-6)
# --- rotazione con Maiusc (15°)
r = ed.doc.shapes[0]; ed.select([r]); spin()
b = r.bounds(); c = b.center()
hv = cv.to_view(QPointF(c.x(), b.bottom())); rot = QPoint(int(hv.x()), int(hv.y()-26))
end = cv.to_view(QPointF(c.x()+100, c.y()))   # 90° in senso orario
drag(rot, QPoint(int(end.x()), int(end.y())), Qt.ShiftModifier, 20)
t = ed.doc.shapes[0].tf; ang = math.degrees(math.atan2(t.m12(), t.m11()))
check('rotazione con la maniglia, Maiusc = scatti di 15°', abs(abs(ang)-90)<0.01, f'{ang:.2f}°')
# --- barra numerica: larghezza con espressione
ed.select([e]); spin()
w.numeric.fw.setText('2in'); w.numeric.fw._commit(); spin()
check('barra numerica: larghezza "2in" = 50,8 mm (proporzioni bloccate)', abs(e.bounds().width()-50.8)<1e-6 and abs(e.bounds().height()-50.8)<1e-6, f'{e.bounds().width():.2f}')
# --- penna: triangolo chiuso cliccando sul primo nodo
w.tool_actions['line'].trigger(); spin()
for p in (V(300,50), V(360,50), V(330,100)):
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p); spin()
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, V(300,50)); spin()
tri = ed.doc.shapes[-1]
check('penna: triangolo chiuso cliccando il primo nodo', isinstance(tri, PathShape) and tri.closed(), tri.describe())
# --- penna: curva di Bézier trascinando
w.tool_actions['line'].trigger(); spin()
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, V(50, 200)); spin()
drag(V(120, 200), V(140, 230))
QTest.keyClick(vp, Qt.Key_Return); spin()
cur = ed.doc.shapes[-1]
from freelasercut.core import nodes as N
subs = N.from_path(cur.path())
check('penna: trascinare crea una curva (nodo morbido con maniglie)', len(subs)==1 and subs[0].nodes[-1].cin is not None, f'{len(subs[0].nodes)} nodi')
# --- modifica nodi: rettangolo -> doppio clic -> sposta un angolo
ed.select([ed.doc.shapes[0]]); spin()
rr = ed.doc.shapes[0]
QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, V(rr.bounds().left()+0.0, rr.bounds().center().y())); spin()
check('doppio clic su una forma: strumento Nodi', cv.tool.name=='nodes')
sp = cv.tool.subs[0]; n0 = sp.nodes[0]; nx0, ny0 = n0.x, n0.y
drag(V(nx0, ny0), V(nx0-15, ny0-15))
p2 = ed.doc.shapes[0]
check('nodi: la forma parametrica diventa tracciato e il nodo si sposta', isinstance(p2, PathShape) and any(abs(n.x-(nx0-15))<0.6 and abs(n.y-(ny0-15))<0.6 for n in N.from_path(p2.path())[0].nodes))
ed.undo(); spin()
check('annulla la modifica dei nodi: torna rettangolo', isinstance(ed.doc.shapes[0], RectShape))
QTest.keyClick(vp, Qt.Key_Escape); spin()
# --- testo
w.tool_actions['text'].trigger(); spin()
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, V(60, 300)); spin(0.3)
tx = ed.doc.shapes[-1]
w.props.text_edit.setPlainText('Ciao FLC'); spin(0.9)
check('testo: clic, scrittura nel pannello, una sola voce di annullamento', isinstance(tx, TextShape) and tx.text=='Ciao FLC' and ed.undo_label()=='Modifica testo')
# --- booleana con le azioni
a = RectShape(30,30); a.apply(__import__('PySide6.QtGui',fromlist=['QTransform']).QTransform.fromTranslate(300,300))
b_ = EllipseShape(30,30); b_.apply(__import__('PySide6.QtGui',fromlist=['QTransform']).QTransform.fromTranslate(315,300))
ed.add([a,b_]); ed.select([a,b_]); spin()
w.acts['difference'].trigger(); spin()
check('menu Disponi > Differenza', len(ed.selection)==1 and isinstance(ed.selection[0], PathShape))
# --- selezione a finestra / a contatto
ed.clear_selection(); spin()
drag(V(40, 40), V(250, 120))   # da sinistra a destra: solo ciò che è tutto dentro
inside = len(ed.selection)
ed.clear_selection(); spin()
drag(V(250, 120), V(100, 60))  # da destra a sinistra: anche ciò che tocca
check('selezione a finestra (dentro) vs a contatto (tocca)', inside >= 1 and len(ed.selection) >= inside, f'dentro {inside}, contatto {len(ed.selection)}')
# --- livelli: assegna colore dalla tavolozza
ed.select([tx]); spin(); w.palette.pick(5); spin()
check('tavolozza: il testo passa al livello 05', tx.layer==5 or ed.selection[0].layer==5)
# --- G-code dall'interfaccia
ed.doc.layer(5).mode='fill'
job = w.build_job()
check('G-code generato dall\'interfaccia con anteprima sul piano', job is not None and len(job.lines) > 50 and len(cv._preview_items)==2, f'{len(job.lines)} righe, {job.seconds:.0f} s')
# --- salva e riapri
p = os.path.join(os.environ['APPDATA'], 'prova.flcut'); ed.doc.path = p; w.file_save(); n = len(ed.doc.shapes)
w.editor.dirty=False; w.file_open(p); spin()
check('salva e riapri il progetto', len(ed.doc.shapes)==n)

print(f'\n{sum(R)}/{len(R)} superati')
sys.exit(0 if all(R) else 1)
