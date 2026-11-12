# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Nesting manuale (0.18.16): i pezzi dentro un'area disegnata sul piano, punto per punto.

Per sfruttare un avanzo di forma qualsiasi (un trapezio di legno rimasto): si clicca sul piano lungo il bordo del
pezzo di materiale fino a chiudere il contorno, e il nesting usa esattamente quell'area.
Regole:
- clic = un punto; clic su un punto già messo = lo toglie (per rimetterlo meglio); clic sul primo punto (con almeno
  3 punti), Invio o «Chiudi l'area» = fine; Backspace toglie l'ultimo; Esc annulla;
- con la spunta «Porta il laser…» a ogni punto messo la testa ci va con il laser acceso al minimo (la Lucciola, con il
  suo limite di potenza e i suoi avvisi): si vede sul materiale se il punto è dentro o fuori dal pezzo;
- l'area chiusa diventa una forma sul livello T1 (mai incisa) e si apre «Ottimizza lo spazio» con quell'area;
- se i pezzi non entrano tutti non si sposta niente: «Disegna una nuova area» oppure «Annulla».
"""
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainterPath, QPolygonF
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ..core.document import ImageShape, PathShape
from ..theme import C
from .editor import TOOL_LAYER
from .tools import Tool, _mods, _pen
from freelasercut.i18n import tr  # noqa: E402

HIT_PX = 9  # un clic entro tanti punti dello schermo da un punto già messo lo prende
POINT_FEED = 3000  # mm/min con cui la testa va sul punto


def polygon_area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0


def self_crossing(pts):
    """Il contorno si incrocia da solo? (un'area a «otto» non è un pezzo di materiale)"""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue  # lati vicini: si toccano nel punto in comune
            c, d = pts[j], pts[(j + 1) % n]
            if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
                return True
    return False


def choose_mode(parent):
    """Prima scelta di «Ottimizza lo spazio»: -> "auto", "manual" oppure None (annullato)."""
    if os.environ.get("FLC_NO_DIALOGS"):
        return "auto"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(tr("Ottimizza lo spazio (nesting)"))
    box.setTextFormat(Qt.RichText)
    box.setText(tr("<b>Dove vanno sistemati i pezzi?</b><br><br>"
                   "<b>Nesting automatico</b>: sul piano di lavoro, su un rettangolo su misura o sulla forma del "
                   "materiale già disegnata.<br><br>"
                   "<b>Nesting manuale</b>: disegni tu l'area sul piano, punto per punto, per esempio lungo il bordo di "
                   "un avanzo di forma irregolare. I pezzi andranno esattamente lì dentro."))
    auto = box.addButton(tr("Nesting automatico"), QMessageBox.AcceptRole)
    manual = box.addButton(tr("Nesting manuale"), QMessageBox.ActionRole)
    box.addButton(tr("Annulla"), QMessageBox.RejectRole)
    box.setDefaultButton(auto)
    box.exec()
    hit = box.clickedButton()
    return "auto" if hit is auto else "manual" if hit is manual else None


def ask_new_area(parent, left, total):
    """I pezzi non entrano: -> True = disegna una nuova area, False = annulla."""
    if os.environ.get("FLC_NO_DIALOGS"):
        return False
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("L'area non basta"))
    box.setTextFormat(Qt.RichText)
    box.setText(tr("<b>Nell'area che hai disegnato non entrano tutti i pezzi</b>: ne restano fuori {0} su {1}.<br><br>"
                   "Non ho spostato niente. Puoi disegnare una nuova area più grande, oppure annullare (e magari "
                   "permettere più rotazioni o ridurre la distanza tra i pezzi).", left, total))
    again = box.addButton(tr("Disegna una nuova area"), QMessageBox.AcceptRole)
    box.addButton(tr("Annulla"), QMessageBox.RejectRole)
    box.setDefaultButton(again)
    box.exec()
    return box.clickedButton() is again


class NestAreaTool(Tool):
    """Lo strumento che disegna l'area: solo tratti dritti, un punto per clic."""

    name = "nest_area"
    label = tr("Area del nesting")

    def __init__(self, cv, panel):
        super().__init__(cv)
        self.panel = panel
        self.pts = []  # [(x, y)] in mm, coordinate del piano
        self.cursor_pt = None
        self.ending = False

    def deactivate(self):
        if not self.ending:  # scelto un altro strumento a metà: è un annullamento
            self.panel.cancel(from_tool=True)

    def hit(self, view_pt):
        """Indice del punto già messo sotto il clic, o None."""
        for i, (x, y) in enumerate(self.pts):
            v = self.cv.to_view(QPointF(x, y))
            if math.hypot(v.x() - view_pt.x(), v.y() - view_pt.y()) <= HIT_PX:
                return i
        return None

    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        _, _, alt = _mods(e)
        i = self.hit(e.position())
        if i is not None:
            if i == 0 and len(self.pts) >= 3:
                self.panel.finish()  # clic sul primo punto: l'area si chiude
            else:
                self.panel.remove_point(i)  # clic su un punto messo: lo tolgo, per rimetterlo meglio
            return
        q = p if alt else self.cv.snap(p)
        self.panel.add_point(q.x(), q.y())

    def move(self, e, p):
        _, _, alt = _mods(e)
        self.cursor_pt = p if alt else self.cv.snap(p)
        if self.pts:
            a = self.pts[-1]
            dx, dy = self.cursor_pt.x() - a[0], self.cursor_pt.y() - a[1]
            self.cv.status.emit(tr("Area del nesting  L {0:.1f} mm  ·  clic: punto  ·  clic su un punto: lo toglie  ·  "
                                   "clic sul primo punto o Invio: chiude", math.hypot(dx, dy)))

    def double_click(self, e, p):
        pass  # il secondo clic del doppio clic cade sul punto appena messo e lo toglie: resta com'era

    def wants_key(self, e):
        return e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete)

    def key(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self.panel.finish()
            return True
        if k == Qt.Key_Escape:
            self.panel.cancel()
            return True
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            if self.pts:
                self.panel.remove_point(len(self.pts) - 1)
            return True
        return False

    def draw(self, p, tf):
        if not self.pts:
            return
        view = [tf.map(QPointF(x, y)) for x, y in self.pts]
        if len(view) >= 3:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(60, 160, 255, 38))
            p.drawPolygon(QPolygonF(view))
        path = QPainterPath()
        path.moveTo(view[0])
        for v in view[1:]:
            path.lineTo(v)
        p.setPen(_pen(C["accent_hi"], 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if self.cursor_pt is not None:
            c = tf.map(self.cursor_pt)
            p.setPen(_pen(C["accent_hi"], 1.0, Qt.DashLine))
            p.drawLine(view[-1], c)
            if len(view) >= 2:
                p.drawLine(c, view[0])
        for i, v in enumerate(view):
            p.setBrush(QColor(C["success"] if i == 0 else "#FFFFFF"))
            p.setPen(_pen(C["accent_lo"], 1))
            r = 5.0 if i == 0 else 4.0
            p.drawRect(QRectF(v.x() - r, v.y() - r, 2 * r, 2 * r))


class NestAreaPanel(QDialog):
    """La finestrella che guida il disegno dell'area: istruzioni, spunta del laser, chiudi, annulla."""

    done = Signal(object)  # la forma dell'area (livello T1), oppure None se annullato

    def __init__(self, main, parts=None):
        super().__init__(main)
        self.main, self.ed, self.cv, self.ctl = main, main.editor, main.canvas, main.ctl
        self.parts = list(parts) if parts is not None else None  # i pezzi scelti prima di cominciare
        self.shape = None
        self._closed = False
        self.laser_note = ""
        self.setWindowTitle(tr("Nesting manuale: disegna l'area"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(430)
        v = QVBoxLayout(self)
        how = QLabel(tr("<b>Clicca sul piano lungo il bordo del pezzo di materiale</b>, un punto dopo l'altro, fino a "
                        "tornare al primo punto (quello verde).<br>"
                        "• Un clic su un punto già messo lo <b>toglie</b>: poi lo rimetti dove serve.<br>"
                        "• Per finire: clic sul primo punto, tasto Invio, oppure il pulsante qui sotto.<br>"
                        "• Backspace toglie l'ultimo punto, Esc annulla."))
        how.setWordWrap(True)
        how.setTextFormat(Qt.RichText)
        v.addWidget(how)
        self.laser = QCheckBox(tr("Porta il laser, acceso al minimo, su ogni punto che metto"))
        self.laser.setToolTip(tr("A ogni punto la testa ci va con il laser acceso alla potenza della Lucciola: vedi sul "
                                 "materiale se il punto cade dentro o fuori dal pezzo. Servono il laser collegato, "
                                 "l'homing fatto e gli occhiali protettivi."))
        self.laser.toggled.connect(self._laser_toggled)
        v.addWidget(self.laser)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        row = QHBoxLayout()
        self.b_cancel = QPushButton(tr("Annulla"))
        self.b_cancel.clicked.connect(lambda: self.cancel())
        self.b_done = QPushButton(tr("Chiudi l'area e continua"))
        self.b_done.setObjectName("primary")
        self.b_done.clicked.connect(lambda: self.finish())
        row.addStretch(1)
        row.addWidget(self.b_cancel)
        row.addWidget(self.b_done)
        v.addLayout(row)
        self.tool = NestAreaTool(self.cv, self)
        self._refresh()

    # ------------------------------------------------------------------ avvio e fine
    def start(self):
        cv = self.cv
        cv.tool.deactivate()
        cv.tool = self.tool  # non passa da set_tool: non è uno strumento della barra
        self.tool.activate()
        cv.viewport().setCursor(self.tool.cursor())
        cv.viewport().update()
        self.show()
        self._place()
        return self

    def _place(self):
        try:  # in alto a destra della finestra, fuori dal centro del piano
            g = self.main.geometry()
            self.move(g.right() - self.width() - 40, g.top() + 110)
        except RuntimeError:
            pass

    def _leave_tool(self):
        self.tool.ending = True
        if self.cv.tool is self.tool:
            self.cv.set_tool("select")
        if self.laser.isChecked():
            self.main.laser.glow_stop()

    def cancel(self, from_tool=False):
        if self._closed:
            return
        self._closed = True
        self.tool.ending = True
        if not from_tool:
            self._leave_tool()
        elif self.laser.isChecked():
            self.main.laser.glow_stop()
        self.main.statusBar().showMessage(tr("Nesting manuale annullato"), 5000)
        self.done.emit(None)
        self.close()

    def closeEvent(self, ev):
        if not self._closed:  # chiusa con la X: è un annullamento
            self._closed = True
            self._leave_tool()
            self.done.emit(None)
        super().closeEvent(ev)

    def finish(self):
        """Chiude l'area: forma sul livello T1, selezionata insieme ai pezzi. False (con il motivo) se non si può."""
        if self._closed:
            return False
        pts = list(self.tool.pts)
        if len(pts) < 3:
            return self._say(tr("Servono almeno 3 punti per chiudere un'area."), True)
        if polygon_area(pts) < 1.0:
            return self._say(tr("L'area è troppo piccola (meno di 1 mm²): i punti sono quasi in fila."), True)
        if self_crossing(pts):
            return self._say(tr("Il contorno si incrocia da solo: togli un punto (cliccandoci sopra) e rimettilo "
                                "seguendo il bordo del pezzo in ordine."), True)
        path = QPainterPath()
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        shape = PathShape(path, layer=TOOL_LAYER)
        if self.parts is None:
            parts = [s for s in self.ed.doc.shapes if not s.locked and not s.hidden and s.layer != TOOL_LAYER]
        else:
            alive = set(self.ed.doc.shapes)
            parts = [s for s in self.parts if s in alive]
        self._closed = True
        self._leave_tool()
        self.ed.add([shape], tr("Area del nesting"), select=False)
        self.ed.select([shape] + parts)
        self.shape = shape
        self.done.emit(shape)
        self.close()
        return True

    # ------------------------------------------------------------------ punti
    def add_point(self, x, y):
        self.tool.pts.append((float(x), float(y)))
        self.laser_note = self.point_laser(x, y) if self.laser.isChecked() else ""
        self._refresh()

    def remove_point(self, i):
        if 0 <= i < len(self.tool.pts):
            del self.tool.pts[i]
            self.laser_note = ""
            self._refresh(tr("Punto tolto: clicca dove lo vuoi rimettere."))

    def _say(self, text, bad=False):
        self._refresh(("⚠ " if bad else "") + text)
        return not bad

    def _refresh(self, note=""):
        n = len(self.tool.pts)
        text = tr("Punti messi: {0}.", n)
        if n >= 3:
            text += " " + tr("Area: {0:.0f} mm².", polygon_area(self.tool.pts))
        for extra in (self.laser_note, note):
            if extra:
                text += "<br>" + extra
        self.info.setText(text)
        self.b_done.setEnabled(n >= 3)
        self.cv.viewport().update()

    # ------------------------------------------------------------------ laser sul punto
    def laser_ready(self):
        """None se il laser può andare sui punti, altrimenti il motivo."""
        c = self.ctl
        if not c.connected:
            return tr("Il laser non è collegato.")
        if c.job_active or c.checking:
            return tr("C'è un lavoro in corso.")
        if self.main.profile.homing and not c.homed:
            return tr("Fai prima l'homing: serve perché la testa vada nel punto giusto del piano.")
        if c.last_status.get("state") not in ("Idle", "Run", "Jog"):
            return tr("La macchina non è pronta (stato: {0}).", c.last_status.get("state", "?"))
        return None

    def _laser_toggled(self, on):
        if not on:
            self.main.laser.glow_stop()
            self.laser_note = ""
            self._refresh()
            return
        why = self.laser_ready()
        if why is None and not self.main.laser._glow_on and not self.main.laser.glow_start_on():
            why = tr("Il laser al minimo non è stato acceso.")
        if why:
            self.laser.blockSignals(True)
            self.laser.setChecked(False)
            self.laser.blockSignals(False)
            self._refresh("⚠ " + why)
            return
        self.laser_note = tr("Laser acceso al minimo: a ogni punto la testa ci va. Occhiali indossati.")
        self._refresh()

    def point_laser(self, x, y):
        """Manda la testa sul punto (laser già acceso al minimo). -> testo da mostrare."""
        lp = self.main.laser
        if not lp._glow_on:  # spenta nel frattempo (5 minuti fermi, allarme…): la spunta non vale più
            self.laser.blockSignals(True)
            self.laser.setChecked(False)
            self.laser.blockSignals(False)
            return "⚠ " + tr("Il laser al minimo si è spento: rimetti la spunta per riaccenderlo.")
        why = self.laser_ready()
        if why:
            return "⚠ " + why
        prof = self.main.profile
        if not (0.0 <= x <= prof.bed_x and 0.0 <= y <= prof.bed_y):
            return "⚠ " + tr("Questo punto è fuori dall'area di lavoro: la testa non ci va.")
        mx, my = prof.to_machine(x, y)
        self.ctl.send_line(f"G53 G1 X{mx:.3f} Y{my:.3f} F{POINT_FEED}")
        return tr("La testa va sul punto X {0:.1f}  Y {1:.1f}.", x, y)


def area_shapes(doc):
    return [s for s in doc.shapes if s.layer == TOOL_LAYER and not isinstance(s, ImageShape)]
