# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti della tela: selezione/trasformazione, nodi, penna, forme, testo, misura, posiziona laser.

Scorciatoie comuni:
  Maiusc  = vincola (proporzioni, quadrato/cerchio, angoli a 15°/45°, asse del trascinamento)
  Ctrl    = dal centro (forme, scala)
  Alt     = disattiva temporaneamente l'aggancio
  Frecce  = sposta di 1 mm (Maiusc 10 mm, Ctrl 0,1 mm)
  Esc     = annulla l'operazione o torna allo strumento Selezione
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainterPath, QPen, QTransform

from ..core import geom, nodes, ops
from ..core.document import (
    EllipseShape, GroupShape, ImageShape, PathShape, PolygonShape, RectShape, TextShape,
)
from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

HANDLE = 4.5  # mezzo lato delle maniglie (px)


def _pen(color, w=1.0, st=Qt.SolidLine):
    p = QPen(QColor(color), w, st)
    p.setCosmetic(True)
    return p


def _mods(e):
    m = e.modifiers()
    return bool(m & Qt.ShiftModifier), bool(m & Qt.ControlModifier), bool(m & Qt.AltModifier)


class Tool:
    name = "tool"
    label = ""

    def __init__(self, cv):
        self.cv = cv
        self.ed = cv.editor

    def activate(self):
        pass

    def deactivate(self):
        pass

    def static_hover(self):
        """True se, muovendo il mouse senza tasti premuti, lo strumento non disegna nulla che lo segua:
        allora il piano ridisegna solo i righelli (più veloce). Di serie no: ridisegno completo."""
        return False

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def press(self, e, p):
        pass

    def move(self, e, p):
        self._hover_snap(e, p)

    def release(self, e, p):
        pass

    def double_click(self, e, p):
        pass

    def key(self, e):
        if e.key() == Qt.Key_Escape:
            self.cv.set_tool("select")
            return True
        return False

    def draw(self, painter, tf):
        pass

    def wants_key(self, e):
        """True se lo strumento usa questo tasto (ha la precedenza sulle scorciatoie dei menu)."""
        return e.key() in (Qt.Key_Escape,) or (e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.name != "select")

    def _snap(self, e, p, exclude=frozenset()):
        _, _, alt = _mods(e)
        if alt:
            self.cv.snap_hint = None
            return p
        return self.cv.snap(p, exclude)

    def _hover_snap(self, e, p):
        self._snap(e, p)


# ======================================================================= selezione
class SelectTool(Tool):
    name = "select"
    label = tr("Selezione")

    def __init__(self, cv):
        super().__init__(cv)
        self.mode = None  # None | move | scale | rotate | band
        self.start = None
        self.start_view = None
        self.orig = {}
        self.box = None
        self.handle = None
        self.band = None
        self.moved = False
        self._click_one = None  # 0.18.3: forma di una selezione multipla premuta senza Maiusc/Ctrl (clic = solo lei)

    def cursor(self):
        return QCursor(Qt.ArrowCursor)

    # ---- maniglie in coordinate vista
    def _handles(self, tf):
        b = self.ed.selection_bounds()
        if b.isNull() or (b.width() == 0 and b.height() == 0):
            return {}
        x0, x1 = b.left(), b.right()
        y0, y1 = b.top(), b.bottom()
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        pts = {"bl": (x0, y0), "bm": (xm, y0), "br": (x1, y0), "ml": (x0, ym), "mr": (x1, ym),
               "tl": (x0, y1), "tm": (xm, y1), "tr": (x1, y1)}
        hv = {k: tf.map(QPointF(*v)) for k, v in pts.items()}
        top = hv["tm"]
        hv["rot"] = QPointF(top.x(), top.y() - 26)
        return hv

    def _hit_handle(self, view_pt, tf):
        for k, v in self._handles(tf).items():
            if abs(v.x() - view_pt.x()) <= HANDLE + 3 and abs(v.y() - view_pt.y()) <= HANDLE + 3:
                return k
        return None

    def press(self, e, p):
        if e.button() == Qt.RightButton:
            return
        shift, ctrl, alt = _mods(e)
        tf = self.cv.bed_to_view_tf()
        self.start = p
        self.start_view = e.position()
        self.moved = False
        self._click_one = None
        h = self._hit_handle(e.position(), tf) if self.ed.editable() else None
        if h:
            self.mode = "rotate" if h == "rot" else "scale"
            self.handle = h
            self._grab()
            return
        s = self.cv.hit_shape(p)
        if s is not None:
            if shift or ctrl:
                self.ed.select([s], "toggle")
            elif s not in self.ed.selection:
                self.ed.select([s])
            elif len(self.ed.selection) > 1:
                # 0.18.3: già selezionata insieme ad altre. Se trascini si spostano tutte (come prima); se è solo un
                # clic, al rilascio resta selezionata lei sola. Prima il clic non cambiava niente: dopo un nesting
                # (tutti i pezzi selezionati) sembrava un oggetto unico impossibile da scegliere pezzo per pezzo
                self._click_one = s
            if s in self.ed.selection and self.ed.editable():
                self.mode = "move"
                self._grab()
            else:
                self.mode = None
            return
        self.mode = "band"
        self.band = (e.position(), e.position())
        self._band_mode = "add" if shift else ("toggle" if ctrl else "replace")

    def _grab(self):
        self.orig = {s.id: (s, QTransform(s.tf)) for s in self.ed.editable()}
        self.box = self.ed.selection_bounds()
        self._nodes = None  # i nodi della selezione, per l'aggancio: si leggono al primo movimento

    def _move_nodes(self):
        """I nodi delle forme che si spostano, com'erano alla presa (0.18.11: sono loro ad agganciarsi, insieme
        agli angoli e alle mezzerie dell'ingombro). Troppi nodi, o solo immagini: lista vuota (basta l'ingombro)."""
        if self._nodes is None:
            from ..core import snapping

            pts = []
            for s, tf0 in self.orig.values():
                if isinstance(s, ImageShape):
                    continue
                path = s.path() if s.tf == tf0 else (s.tf.inverted()[0] * tf0).map(s.path())  # sempre com'era alla presa
                n = path.elementCount()
                if len(pts) + n > snapping.MAX_NODES:
                    pts = []
                    break
                for i in range(n):
                    el = path.elementAt(i)
                    if el.type in (QPainterPath.ElementType.MoveToElement, QPainterPath.ElementType.LineToElement):
                        pts.append((el.x, el.y))
                    elif el.type == QPainterPath.ElementType.CurveToElement and i + 2 < n:
                        end = path.elementAt(i + 2)
                        pts.append((end.x, end.y))
            self._nodes = pts
        return self._nodes

    def _apply(self, T):
        for s, tf0 in self.orig.values():
            s.tf = tf0 * T
            s.invalidate()
        self.cv.refresh_live([s for s, _ in self.orig.values()])

    def move(self, e, p):
        shift, ctrl, alt = _mods(e)
        if self.mode is None:
            # cursore informativo sulle maniglie
            tf = self.cv.bed_to_view_tf()
            h = self._hit_handle(e.position(), tf) if self.ed.editable() else None
            cur = {"bl": Qt.SizeBDiagCursor, "tr": Qt.SizeBDiagCursor, "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
                   "bm": Qt.SizeVerCursor, "tm": Qt.SizeVerCursor, "ml": Qt.SizeHorCursor, "mr": Qt.SizeHorCursor}.get(h)
            if h == "rot":
                self.cv.viewport().setCursor(Qt.CrossCursor)
            elif cur is not None:
                self.cv.viewport().setCursor(cur)
            elif self.cv.hit_shape(p) is not None:
                self.cv.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.cv.viewport().setCursor(Qt.ArrowCursor)
            self.cv.snap_hint = None
            return
        if not self.moved:
            if (e.position() - self.start_view).manhattanLength() < 3:
                return
            self.moved = True
            if self.mode in ("move", "scale", "rotate"):
                self.ed.begin({"move": tr("Sposta"), "scale": tr("Scala"), "rotate": tr("Ruota")}[self.mode])
        if self.mode == "band":
            self.band = (self.band[0], e.position())
            return
        if self.mode == "move":
            # 0.18.11: si agganciano gli angoli, le mezzerie, il centro e i nodi della SELEZIONE a quelli delle altre
            # forme (prima si agganciava il punto in cui il mouse aveva preso l'oggetto: l'angolo restava scostato)
            dx, dy = p.x() - self.start.x(), p.y() - self.start.y()
            keep_x = abs(dx) > abs(dy)  # con Maiusc: l'asse su cui ci si sposta
            if shift:  # il vincolo prima dell'aggancio: si cercano i bersagli dove l'oggetto va davvero
                dx, dy = (dx, 0.0) if keep_x else (0.0, dy)
            if alt:
                self.cv.snap_hint = None
            else:
                dx, dy = self.cv.snap_move(self.box, self._move_nodes(), dx, dy, frozenset(self.orig))
            if shift:  # …e dopo: l'aggancio non deve spostare sull'altro asse
                dx, dy = (dx, 0.0) if keep_x else (0.0, dy)
            self._apply(QTransform.fromTranslate(dx, dy))
            self.cv.status.emit(f"Sposta  ΔX {dx:+.2f}  ΔY {dy:+.2f} mm")
            return
        b = self.box
        if self.mode == "rotate":
            c = b.center()
            a0 = math.atan2(self.start.y() - c.y(), self.start.x() - c.x())
            a1 = math.atan2(p.y() - c.y(), p.x() - c.x())
            ang = math.degrees(a1 - a0)
            if shift:
                ang = round(ang / 15.0) * 15.0
            elif ctrl:
                ang = round(ang / 5.0) * 5.0
            r = QTransform()
            r.rotate(ang)
            self._apply(ops.about(r, c.x(), c.y()))
            self.cv.status.emit(f"Ruota  {ang:+.1f}°")
            return
        # scala
        h = self.handle
        x0, x1, y0, y1 = b.left(), b.right(), b.top(), b.bottom()
        ax = x1 if "l" in h[1:] or h in ("tl", "bl", "ml") else x0
        ay = y1 if h.startswith("b") else y0
        if ctrl:
            ax, ay = b.center().x(), b.center().y()
        pt = p if alt else self.cv.snap(p, frozenset(self.orig))
        w0 = max(b.width(), 1e-9)
        h0 = max(b.height(), 1e-9)
        hx = x0 if h in ("tl", "bl", "ml") else x1
        hy = y0 if h.startswith("b") else y1
        sx = (pt.x() - ax) / (hx - ax) if h not in ("tm", "bm") and abs(hx - ax) > 1e-9 else 1.0
        sy = (pt.y() - ay) / (hy - ay) if h not in ("ml", "mr") and abs(hy - ay) > 1e-9 else 1.0
        corner = h in ("tl", "tr", "bl", "br")
        if corner and not shift:  # angoli: proporzioni bloccate (Maiusc per sbloccarle)
            k = max(abs(sx), abs(sy))
            sx = math.copysign(k, sx) if sx else k
            sy = math.copysign(k, sy) if sy else k
        if abs(sx) < 1e-4:
            sx = 1e-4
        if abs(sy) < 1e-4:
            sy = 1e-4
        self._apply(ops.about(QTransform.fromScale(sx, sy), ax, ay))
        self.cv.status.emit(f"Scala  L {w0 * abs(sx):.2f}  A {h0 * abs(sy):.2f} mm  ({abs(sx) * 100:.1f}% × {abs(sy) * 100:.1f}%)")

    def release(self, e, p):
        if self.mode == "band" and self.band is not None:
            a, b = self.band
            if (b - a).manhattanLength() > 3:
                pa, pb = self.cv.to_bed(a), self.cv.to_bed(b)
                r = QRectF(pa, pb).normalized()
                crossing = b.x() < a.x()  # da destra a sinistra: anche ciò che tocca
                shapes = self.cv.shapes_in_rect(r, crossing)
                self.ed.select(shapes, self._band_mode)
            elif self._band_mode == "replace":
                self.ed.clear_selection()
            self.band = None
        elif self.mode in ("move", "scale", "rotate") and self.moved:
            self.ed.commit()
        one, self._click_one = self._click_one, None
        if one is not None and not self.moved and one in self.ed.selection and len(self.ed.selection) > 1:
            self.ed.select([one])
        self.mode = None
        self.cv.snap_hint = None

    def double_click(self, e, p):
        s = self.cv.hit_shape(p)
        if isinstance(s, TextShape):
            self.cv.edit_text.emit(s)
        elif s is not None and not isinstance(s, (ImageShape, GroupShape)):
            self.ed.select([s])
            self.cv.set_tool("nodes")

    def key(self, e):
        k = e.key()
        shift, ctrl, _ = _mods(e)
        if k == Qt.Key_Escape:
            if self.mode in ("move", "scale", "rotate") and self.moved:
                self.ed.cancel()
                self.mode = None
            else:
                self.ed.clear_selection()
            return True
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.ed.delete()
            return True
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}
        if k in steps and not self.ed.selection:
            if not e.isAutoRepeat():
                self.cv.jog_requested.emit(*steps[k])  # nessuna selezione: le frecce muovono la testa
            return True
        if k in steps and self.ed.editable():
            d = 10.0 if shift else (0.1 if ctrl else 1.0)
            dx, dy = steps[k]
            self.ed.transform(QTransform.fromTranslate(dx * d, dy * d), tr("Sposta"))
            return True
        return False

    def static_hover(self):
        return self.mode is None  # passando col mouse cambia solo il cursore: nulla da ridisegnare sul piano

    def draw(self, p, tf):
        hv = self._handles(tf)
        if hv and self.mode != "band":
            b0, b1 = hv["bl"], hv["tr"]
            p.setPen(_pen(C["accent"], 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(b0, b1).normalized())
            if self.ed.editable():
                p.setPen(_pen(C["accent_hi"], 1))
                p.drawLine(hv["tm"], hv["rot"])
                for k, v in hv.items():
                    if k == "rot":
                        p.setBrush(QColor(C["panel"]))
                        p.drawEllipse(v, HANDLE + 1, HANDLE + 1)
                    else:
                        p.setBrush(QColor("#FFFFFF"))
                        p.drawRect(QRectF(v.x() - HANDLE, v.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))
        if self.mode == "band" and self.band is not None:
            a, b = self.band
            crossing = b.x() < a.x()
            col = QColor(C["success"] if crossing else C["accent"])
            fill = QColor(col)
            fill.setAlpha(30)
            p.setPen(_pen(col.name(), 1, Qt.DashLine if crossing else Qt.SolidLine))
            p.setBrush(fill)
            p.drawRect(QRectF(a, b).normalized())


# ======================================================================= nodi
class _NodeItem:
    """Una forma che si sta modificando a nodi: la forma e i suoi sottopercorsi (coordinate del piano)."""
    __slots__ = ("shape", "subs", "began")

    def __init__(self, shape):
        self.shape = shape
        self.subs = nodes.from_path(shape.path())
        self.began = False  # già trasformata in tracciato in questo passo di modifica


class NodeTool(Tool):
    """Modifica nodi. 0.19.5: i nodi di tutte le forme selezionate, più nodi selezionati insieme (Ctrl/Maiusc+clic,
    rettangolo sul vuoto, Ctrl+A), spostamento/elimina/tipo su tutti, unione di due estremi (J fonde, Maiusc+J
    collega). Riferimento di un nodo: (k, si, ni) = forma k di self.items, sottopercorso si, nodo ni.
    `target`, `subs` e `sel_node` restano come prima e si riferiscono alla forma del nodo principale."""
    name = "nodes"
    label = tr("Modifica nodi")

    def __init__(self, cv):
        super().__init__(cv)
        self.items = []
        self.cur = 0  # forma del nodo principale (quella di target/subs)
        self.sel = []  # nodi selezionati, in ordine; l'ultimo è il principale
        self.drag = None  # (tipo, k, si, ni) tipo: node | in | out | seg ; per seg ni = (i, j, t)
        self.hover = None  # (tipo, k, si, ni)
        self.hover_seg = None  # (k, si, i, j, t, q)
        self.band = None  # (inizio, fine) in coordinate vista: rettangolo per scegliere i nodi
        self._band_add = False
        self._last = None
        self._txn = False  # passo di modifica aperto (begin)

    # ---- compatibilità: la forma e il nodo «principali»
    @property
    def target(self):
        return self.items[self.cur].shape if 0 <= self.cur < len(self.items) else None

    @property
    def subs(self):
        return self.items[self.cur].subs if 0 <= self.cur < len(self.items) else []

    @property
    def sel_node(self):
        if self.sel and self.sel[-1][0] == self.cur:
            return self.sel[-1][1:]
        return None

    @sel_node.setter
    def sel_node(self, v):
        self.sel = [] if v is None else [(self.cur,) + tuple(v)]

    @property
    def began(self):
        return self._txn

    def cursor(self):
        return QCursor(Qt.ArrowCursor)

    def activate(self):
        self._load()

    def deactivate(self):
        self.items = []
        self.sel = []
        self.band = None

    def _load(self, keep=False):
        old_sel = [(self.items[k].shape.id, si, ni) for k, si, ni in self.sel] if keep else []
        shapes = [s for s in self.ed.editable() if not isinstance(s, (ImageShape, GroupShape))]
        self.items = [_NodeItem(s) for s in shapes]
        self.cur = 0
        by_id = {it.shape.id: k for k, it in enumerate(self.items)}
        self.sel = [(by_id[i], si, ni) for i, si, ni in old_sel if i in by_id and self._valid((by_id[i], si, ni))]
        if self.sel:
            self.cur = self.sel[-1][0]
        self.hover = self.hover_seg = None

    def _valid(self, ref):
        k, si, ni = ref
        return 0 <= k < len(self.items) and 0 <= si < len(self.items[k].subs) and 0 <= ni < len(self.items[k].subs[si].nodes)

    def _stale(self):
        shapes = self.ed.doc.shapes
        return not self.items or any(it.shape not in shapes for it in self.items)

    def _node(self, ref):
        k, si, ni = ref
        return self.items[k].subs[si].nodes[ni]

    # ---- passo di modifica (un solo Annulla per azione)
    def _ensure_path(self, ks=None, label=None):
        """Prima modifica: le forme toccate diventano tracciati (in automatico, annullabile)."""
        if not self._txn:
            self.ed.begin(label or tr("Modifica nodi"))
            self._txn = True
        for k in (range(len(self.items)) if ks is None else sorted(set(ks))):
            it = self.items[k]
            if it.began:
                continue
            it.began = True
            s = it.shape
            if not isinstance(s, PathShape) or not s.tf.isIdentity():
                new = PathShape(nodes.to_path(it.subs), layer=s.layer)
                new.id = s.id
                idx = self.ed.doc.shapes.index(s)
                self.ed.doc.shapes[idx] = new
                self.ed.selection = [new if x is s else x for x in self.ed.selection]
                it.shape = new

    def _push(self, ks=None):
        for k in (range(len(self.items)) if ks is None else sorted(set(ks))):
            it = self.items[k]
            if it.began:
                it.shape.set_path(nodes.to_path(it.subs))
        self.ed.preview_changed()

    def _finish(self):
        if self._txn:
            self.ed.commit()
            self._txn = False
            for it in self.items:
                it.began = False
                it.subs = nodes.from_path(it.shape.path())
            self.sel = [r for r in self.sel if self._valid(r)]

    # ---- ricerca sotto il mouse
    def _hit(self, view_pt, tf):
        best = None
        single = self.sel[-1] if len(self.sel) == 1 else None
        for k, it in enumerate(self.items):
            for si, sp in enumerate(it.subs):
                for ni, nd in enumerate(sp.nodes):
                    for kind, pt in (("in", nd.cin), ("out", nd.cout), ("node", nd.pt())):
                        if pt is None:
                            continue
                        if kind != "node" and single != (k, si, ni):
                            continue
                        v = tf.map(QPointF(*pt))
                        d = math.hypot(v.x() - view_pt.x(), v.y() - view_pt.y())
                        if d <= 7 and (best is None or d < best[0] or kind == "node" and best[1] != "node" and d <= best[0] + 1):
                            best = (d, kind, k, si, ni)
        return best[1:] if best else None

    def _hit_seg(self, p):
        best = None
        tol = self.cv.px(6)
        for k, it in enumerate(self.items):
            for si, sp in enumerate(it.subs):
                for i, j in sp.segments():
                    t, d, q = nodes.nearest_on_segment(sp, i, j, (p.x(), p.y()))
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, k, si, i, j, t, q)
        return best[1:] if best else None

    # ---- mouse
    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        shift, ctrl, _ = _mods(e)
        add = shift or ctrl
        tf = self.cv.bed_to_view_tf()
        if self._stale():
            self._load(keep=True)
        h = self._hit(e.position(), tf) if self.items else None
        if h:
            kind, k, si, ni = h
            ref = (k, si, ni)
            if kind == "node":
                if add:  # Ctrl/Maiusc+clic: aggiunge o toglie il nodo
                    if ref in self.sel:
                        self.sel.remove(ref)
                        if self.sel:
                            self.cur = self.sel[-1][0]
                        self.drag = None
                        return
                    self.sel.append(ref)
                elif ref not in self.sel:
                    self.sel = [ref]
                else:  # già selezionato: diventa il principale, si trascinano tutti
                    self.sel.remove(ref)
                    self.sel.append(ref)
                self.cur = k
            self.drag = (kind, k, si, ni)
            self._last = p
            return
        seg = self._hit_seg(p) if self.items else None
        if seg:
            k, si, i, j, t, q = seg
            self.cur = k
            self.drag = ("seg", k, si, (i, j, t))
            self._last = p
            return
        s = self.cv.hit_shape(p)
        if s is not None and not isinstance(s, (ImageShape, GroupShape)):
            if add:  # aggiunge la forma a quelle che si modificano, i nodi scelti restano
                self.ed.select([s], "add")
                self._load(keep=True)
            else:
                self.ed.select([s])
                self._load()
            return
        # vuoto: rettangolo per scegliere i nodi (senza movimento = deseleziona)
        self.band = (e.position(), e.position())
        self._band_add = add

    def move(self, e, p):
        shift, ctrl, alt = _mods(e)
        if self.band is not None:
            self.band = (self.band[0], e.position())
            return
        if self.drag is None:
            tf = self.cv.bed_to_view_tf()
            self.hover = self._hit(e.position(), tf) if self.items else None
            self.hover_seg = None if self.hover else (self._hit_seg(p) if self.items else None)
            self.cv.snap_hint = None
            return
        kind, k, si, ni = self.drag
        if kind == "node":
            refs = list(self.sel) if (k, si, ni) in self.sel else [(k, si, ni)]
            self._ensure_path([r[0] for r in refs])
            nd = self._node((k, si, ni))
            q = p if alt else self.cv.snap(p, frozenset(self.items[r[0]].shape.id for r in refs))
            if shift:  # vincola orizzontale/verticale rispetto al punto di partenza
                if abs(q.x() - self._last.x()) > abs(q.y() - self._last.y()):
                    q = QPointF(q.x(), nd.y)
                else:
                    q = QPointF(nd.x, q.y())
            dx, dy = q.x() - nd.x, q.y() - nd.y
            for r in refs:
                self._node(r).move(dx, dy)
            self._last = p
            self._push([r[0] for r in refs])
            return
        self._ensure_path([k])
        sp = self.items[k].subs[si]
        if kind in ("in", "out"):
            nodes.move_handle(sp.nodes[ni], kind, p.x(), p.y())
        elif kind == "seg":
            i, j, t = ni
            if not sp.is_curve(i, j):
                nodes.curve_segment(sp, i, j)
            dx, dy = p.x() - self._last.x(), p.y() - self._last.y()
            # piega il segmento: le maniglie si spostano pesate sulla posizione afferrata
            wa = (1 - t) * 1.5
            wb = t * 1.5
            a, b = sp.nodes[i], sp.nodes[j]
            a.cout = (a.cout[0] + dx * wa, a.cout[1] + dy * wa)
            b.cin = (b.cin[0] + dx * wb, b.cin[1] + dy * wb)
            a.smooth = b.smooth = False
        self._last = p
        self._push([k])

    def release(self, e, p):
        if self.band is not None:
            a, b = self.band
            self.band = None
            r = QRectF(a, b).normalized()
            if r.width() < 3 and r.height() < 3:
                if not self._band_add:
                    self.sel = []
                return
            tf = self.cv.bed_to_view_tf()
            got = [(k, si, ni) for k, it in enumerate(self.items) for si, sp in enumerate(it.subs)
                   for ni, nd in enumerate(sp.nodes) if r.contains(tf.map(QPointF(*nd.pt())))]
            if self._band_add:
                self.sel += [g for g in got if g not in self.sel]
            else:
                self.sel = got
            if self.sel:
                self.cur = self.sel[-1][0]
            return
        if self.drag and self.drag[0] == "node" and self._txn and len(self.sel) <= 1:
            # rilascio di un estremo aperto su un altro estremo della stessa forma: unisce (come prima)
            k = self.drag[1]
            nodes.join_endpoints(self.items[k].subs, self.cv.px(6))
            self._push([k])
        self.drag = None
        self._finish()

    def double_click(self, e, p):
        seg = self._hit_seg(p) if self.items else None
        if seg:
            k, si, i, j, t, q = seg
            self.cur = k
            self._ensure_path([k])
            n = nodes.insert_node(self.items[k].subs[si], i, j, t)
            self.sel = [(k, si, n)]
            self._push([k])
            self._finish()

    # ---- tastiera
    _KEYS = (Qt.Key_D, Qt.Key_C, Qt.Key_S, Qt.Key_B, Qt.Key_I, Qt.Key_M, Qt.Key_L, Qt.Key_A, Qt.Key_J, Qt.Key_Delete,
             Qt.Key_Backspace, Qt.Key_Escape)

    def wants_key(self, e):
        m = e.modifiers()
        if e.key() == Qt.Key_A and (m & Qt.ControlModifier) and not (m & (Qt.AltModifier | Qt.ShiftModifier)):
            return bool(self.items)  # Ctrl+A: tutti i nodi (invece di «seleziona tutto» del menu)
        return e.key() in self._KEYS and not (m & (Qt.ControlModifier | Qt.AltModifier))

    def _op(self, fn, ks=None):
        self._ensure_path(ks)
        fn()
        self._push(ks)
        self._finish()
        return True

    def _targets(self):
        """Nodi su cui agire: quello sotto il mouse se non è fra i selezionati, altrimenti tutti i selezionati."""
        if self.hover and self.hover[0] == "node":
            ref = self.hover[1:]
            if ref not in self.sel:
                return [ref]
        return [r for r in self.sel if self._valid(r)]

    def select_all_nodes(self):
        self.sel = [(k, si, ni) for k, it in enumerate(self.items) for si, sp in enumerate(it.subs)
                    for ni in range(len(sp.nodes))]
        if self.sel:
            self.cur = self.sel[-1][0]
        self.cv.viewport().update()

    def delete_nodes(self, refs):
        refs = sorted(set(refs), key=lambda r: (r[0], -r[1], -r[2]))
        self.sel = []

        def do():
            for k, si, ni in refs:
                subs = self.items[k].subs
                if si < len(subs) and ni < len(subs[si].nodes):
                    nodes.delete_node(subs, si, ni)
        return self._op(do, [r[0] for r in refs])

    def key(self, e):
        k = e.key()
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        if k == Qt.Key_Escape:
            if self.sel:  # 0.19.5: prima toglie la scelta dei nodi, poi torna a Selezione
                self.sel = []
                return True
            self.cv.set_tool("select")
            return True
        if k == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.select_all_nodes()
            return True
        if k == Qt.Key_J:
            return self.join_selected("connect" if shift else "merge")
        refs = self._targets()
        if refs and k in (Qt.Key_D, Qt.Key_Delete, Qt.Key_Backspace):
            return self.delete_nodes(refs)
        if refs and k == Qt.Key_C:
            return self._op(lambda: [nodes.set_corner(self._node(r)) for r in refs], [r[0] for r in refs])
        if refs and k == Qt.Key_S:
            return self._op(lambda: [nodes.set_smooth(self.items[r[0]].subs[r[1]], r[2]) for r in refs],
                            [r[0] for r in refs])
        one = refs[-1] if refs else None
        if one and k == Qt.Key_B:
            kk, si, ni = one
            self.cur = kk
            self.sel = []
            return self._op(lambda: nodes.break_at(self.items[kk].subs, si, ni), [kk])
        if one and k == Qt.Key_A:
            kk, si, ni = one
            self.cur = kk
            return self.fillet_node(si, ni)
        if self.hover_seg and k in (Qt.Key_I, Qt.Key_M):
            kk, si, i, j, t, q = self.hover_seg
            tt = 0.5 if k == Qt.Key_M else t
            return self._op(lambda: nodes.insert_node(self.items[kk].subs[si], i, j, tt), [kk])
        if self.hover_seg and k == Qt.Key_L:
            kk, si, i, j, t, q = self.hover_seg
            return self._op(lambda: nodes.straighten(self.items[kk].subs[si], i, j), [kk])
        if self.hover_seg and k == Qt.Key_D:
            kk, si, i, j, t, q = self.hover_seg
            self.cur = kk
            return self._op(lambda: self._delete_segment(si, i, j), [kk])
        return False

    # ---- unione di due nodi (0.19.5)
    def join_selected(self, mode="merge"):
        """J = fondi i due estremi selezionati in un punto a metà strada; Maiusc+J = collegali con un tratto dritto.
        Due forme diverse diventano una sola, sul livello della forma del primo nodo selezionato."""
        refs = [r for r in self.sel if self._valid(r)]
        if len(refs) != 2:
            self.cv.status.emit(tr("Unisci nodi: seleziona due estremi (Ctrl+clic sul secondo)"))
            return True
        (ka, sa, na), (kb, sb, nb) = refs
        ia, ib = self.items[ka], self.items[kb]
        if not (nodes.is_open_end(ia.subs, sa, na) and nodes.is_open_end(ib.subs, sb, nb)):
            self.cv.status.emit(tr("Si possono unire solo due estremi di linee aperte"))
            return True
        # prova su una copia: niente annulla inutili se non si può
        if ka == kb:
            test = [s.copy() for s in ia.subs]
            why = nodes.join_two(test, (sa, na), (sb, nb), mode)
        else:
            test = [s.copy() for s in ia.subs] + [s.copy() for s in ib.subs]
            why = nodes.join_two(test, (sa, na), (len(ia.subs) + sb, nb), mode)
        if why:
            self.cv.status.emit(why)
            return True
        self.ed.begin(tr("Unisci nodi") if mode == "merge" else tr("Collega nodi"))
        self._txn = True
        self._ensure_path([ka, kb])
        if ka == kb:
            nodes.join_two(ia.subs, (sa, na), (sb, nb), mode)
        else:
            off = len(ia.subs)
            ia.subs.extend(ib.subs)
            nodes.join_two(ia.subs, (sa, na), (off + sb, nb), mode)
            gone = ib.shape
            self.ed.doc.shapes.remove(gone)
            self.ed.selection = [x for x in self.ed.selection if x is not gone]
            self.items.pop(kb)
            ka = ka if ka < kb else ka - 1
        self.cur = ka
        self.sel = []
        self.items[ka].shape.set_path(nodes.to_path(self.items[ka].subs))
        self.ed.preview_changed()
        self._finish()
        self.ed.selection_changed.emit()
        self.cv.status.emit(tr("Nodi uniti") if mode == "merge" else tr("Nodi collegati"))
        return True

    # ---- Allinea e Distribuisci sui nodi selezionati (0.19.6)
    def arrange_nodes(self, kind, axis=None):
        """kind: left | right | top | bottom | hcenter | vcenter | center (riferimento: ingombro dei nodi scelti, Y in
        su come per le forme) oppure "distribute" con axis "h"/"v" (distanze uguali fra il primo e l'ultimo nodo
        lungo l'asse, che restano fermi). Le maniglie seguono il nodo. -> True se ha fatto qualcosa."""
        if self._stale():  # forme cambiate da fuori (Annulla, altre finestre): si ricaricano tenendo la scelta
            self._load(keep=True)
        refs = list(dict.fromkeys(r for r in self.sel if self._valid(r)))
        need = 3 if kind == "distribute" else 2
        if len(refs) < need:
            self.cv.status.emit(tr("Seleziona almeno tre nodi da distribuire") if need == 3 else
                                tr("Seleziona almeno due nodi da allineare"))
            return False
        pts = [self._node(r).pt() for r in refs]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        target = {}
        if kind == "distribute":
            i = 0 if axis == "h" else 1
            order = sorted(range(len(refs)), key=lambda k: (pts[k][i], pts[k][1 - i]))
            a, b = pts[order[0]][i], pts[order[-1]][i]
            step = (b - a) / (len(order) - 1)
            for n, k in enumerate(order[1:-1], start=1):
                q = list(pts[k])
                q[i] = a + step * n
                target[k] = tuple(q)
        else:
            for k, (x, y) in enumerate(pts):
                nx = {"left": x0, "right": x1, "hcenter": (x0 + x1) / 2, "center": (x0 + x1) / 2}.get(kind, x)
                ny = {"bottom": y0, "top": y1, "vcenter": (y0 + y1) / 2, "center": (y0 + y1) / 2}.get(kind, y)
                target[k] = (nx, ny)
        moves = [(refs[k], q[0] - pts[k][0], q[1] - pts[k][1]) for k, q in target.items()]
        moves = [m for m in moves if abs(m[1]) > 1e-12 or abs(m[2]) > 1e-12]
        if not moves:
            return False
        keep = [(self.items[k].shape.id, si, ni) for k, si, ni in self.sel]
        label = tr("Distribuisci nodi") if kind == "distribute" else tr("Allinea nodi")

        def do():
            for r, dx, dy in moves:
                self._node(r).move(dx, dy)
        self._ensure_path([r[0] for r, _, _ in moves], label)
        do()
        self._push([r[0] for r, _, _ in moves])
        self._finish()
        by_id = {it.shape.id: k for k, it in enumerate(self.items)}  # la scelta dei nodi resta
        self.sel = [(by_id[i], si, ni) for i, si, ni in keep if i in by_id and self._valid((by_id[i], si, ni))]
        self.cv.viewport().update()
        return True

    def ask_radius(self):
        """Raggio del raccordo (si ricorda l'ultimo usato). None = annullato."""
        from PySide6.QtWidgets import QInputDialog

        last = float(self.cv.tool_options.get("fillet_radius", 3.0))
        r, ok = QInputDialog.getDouble(self.cv, tr("Arrotonda lo spigolo"), tr("Raggio del raccordo (mm)"), last,
                                       0.01, 1000.0, 2)
        return r if ok else None

    def fillet_node(self, si, ni, r=None):
        """0.17.13: tasto A sul nodo: arrotonda quello spigolo (raccordo su un angolo solo). Forma: quella principale."""
        if r is None:
            r = self.ask_radius()
            if r is None:
                return True
        self.cv.tool_options["fillet_radius"] = r
        why = nodes.fillet(self.subs[si].copy(), ni, r)  # prima una prova su una copia: niente annulla inutili
        if why:
            self.cv.status.emit(why)
            return True
        self.sel = []
        k = self.cur
        return self._op(lambda: nodes.fillet(self.items[k].subs[si], ni, r), [k])

    def _delete_segment(self, si, i, j):
        subs = self.subs
        sp = subs[si]
        if sp.closed:
            # apre il percorso togliendo il segmento i -> j
            nodes_ = sp.nodes[j:] + sp.nodes[:j]
            nodes_[0].cin = None
            nodes_[-1].cout = None
            subs[si] = nodes.SubPath(nodes_, False)
        else:
            a = nodes.SubPath(sp.nodes[:i + 1], False)
            b = nodes.SubPath(sp.nodes[j:], False)
            a.nodes[-1].cout = None
            b.nodes[0].cin = None
            subs[si:si + 1] = [x for x in (a, b) if len(x.nodes) >= 2]
        self.sel = []

    def draw(self, p, tf):
        if not self.items:
            return
        if self.hover_seg:  # 0.18.8: dopo aver tolto dei nodi il tratto evidenziato può non esistere più
            k, si, i, j = self.hover_seg[:4]
            if k >= len(self.items) or si >= len(self.items[k].subs) or max(i, j) >= len(self.items[k].subs[si].nodes):
                self.hover_seg = None
        if self.hover_seg:
            k, si, i, j, t, q = self.hover_seg
            sp = self.items[k].subs[si]
            seg = QPainterPath()
            a = sp.nodes[i]
            seg.moveTo(*a.pt())
            if sp.is_curve(i, j):
                _, c1, c2, e = sp.bezier(i, j)
                seg.cubicTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1])
            else:
                seg.lineTo(*sp.nodes[j].pt())
            p.setPen(_pen("#FFD43B", 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawPath(tf.map(seg))
        sel = set(self.sel)
        single = self.sel[-1] if len(self.sel) == 1 else None
        for k, it in enumerate(self.items):
            for si, sp in enumerate(it.subs):
                for ni, nd in enumerate(sp.nodes):
                    v = tf.map(QPointF(*nd.pt()))
                    ref = (k, si, ni)
                    selected = ref in sel
                    if single == ref:  # le maniglie solo quando il nodo selezionato è uno
                        p.setPen(_pen(C["muted"], 1))
                        for h in (nd.cin, nd.cout):
                            if h:
                                hv = tf.map(QPointF(*h))
                                p.drawLine(v, hv)
                                p.setBrush(QColor(C["accent_hi"]))
                                p.drawEllipse(hv, 3.5, 3.5)
                    hovered = self.hover and self.hover[0] == "node" and self.hover[1:] == ref
                    fill = C["accent"] if selected else ("#FFD43B" if hovered else "#FFFFFF")
                    p.setPen(_pen(C["accent_lo"] if not selected else "#FFFFFF", 1))
                    p.setBrush(QColor(fill))
                    if nd.smooth:
                        p.drawEllipse(v, 4, 4)
                    else:
                        p.drawRect(QRectF(v.x() - 3.5, v.y() - 3.5, 7, 7))
                    if ni == 0 and not sp.closed:
                        p.setPen(_pen(C["success"], 1.5))
                        p.setBrush(Qt.NoBrush)
                        p.drawEllipse(v, 7, 7)
        if self.band is not None:
            a, b = self.band
            p.setPen(_pen(C["accent_hi"], 1, Qt.DashLine))
            p.setBrush(QColor(77, 171, 247, 30))
            p.drawRect(QRectF(a, b).normalized())


# ======================================================================= penna (linee e Bézier)
class PenTool(Tool):
    name = "line"
    label = tr("Linee e curve")

    def __init__(self, cv):
        super().__init__(cv)
        self.nodes = []
        self.dragging = False
        self.cursor_pt = None

    def deactivate(self):
        self._finish(switch=False)

    def _constrain(self, p, shift):
        if not shift or not self.nodes:
            return p
        a = self.nodes[-1]
        dx, dy = p.x() - a.x, p.y() - a.y
        ang = math.atan2(dy, dx)
        ang = round(ang / (math.pi / 4)) * (math.pi / 4)
        L = math.hypot(dx, dy)
        return QPointF(a.x + L * math.cos(ang), a.y + L * math.sin(ang))

    def press(self, e, p):
        shift, ctrl, alt = _mods(e)
        if e.button() == Qt.RightButton:
            self._finish()
            return
        q = self._constrain(p if alt else self.cv.snap(p), shift)
        if len(self.nodes) >= 2:
            first = self.cv.to_view(QPointF(self.nodes[0].x, self.nodes[0].y))
            if math.hypot(first.x() - e.position().x(), first.y() - e.position().y()) <= 8:
                self._finish(close=True)
                return
        self.nodes.append(nodes.Node(q.x(), q.y()))
        self.dragging = True

    def move(self, e, p):
        shift, ctrl, alt = _mods(e)
        q = p if alt else self.cv.snap(p)
        if self.dragging and self.nodes:
            nd = self.nodes[-1]
            if math.hypot(q.x() - nd.x, q.y() - nd.y) > self.cv.px(3):
                nd.cout = (q.x(), q.y())
                nd.cin = (2 * nd.x - q.x(), 2 * nd.y - q.y())
                nd.smooth = True
        self.cursor_pt = self._constrain(q, shift)
        if self.nodes:
            a = self.nodes[-1]
            dx, dy = self.cursor_pt.x() - a.x, self.cursor_pt.y() - a.y
            self.cv.status.emit(f"Linea  L {math.hypot(dx, dy):.2f} mm  ·  {math.degrees(math.atan2(dy, dx)):.1f}°"
                                "  ·  clic: nodo  ·  trascina: curva  ·  Invio o clic destro: fine")

    def release(self, e, p):
        self.dragging = False

    def double_click(self, e, p):
        if self.nodes:
            self.nodes.pop()  # il doppio clic ha aggiunto un nodo in più
        self._finish()

    def _finish(self, close=False, switch=True):
        nds = self.nodes
        self.nodes = []
        self.dragging = False
        if len(nds) < 2:
            return
        sp = nodes.SubPath(nds, closed=close)
        shape = PathShape(nodes.to_path([sp]), layer=self.ed.current_layer)
        self.ed.add([shape], tr("Disegna linea"))
        if switch:
            self.cv.tool_done()  # finito il disegno si torna alla selezione (salvo strumento bloccato, 0.19.0)

    def wants_key(self, e):
        return e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Backspace)

    def key(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()
            return True
        if k == Qt.Key_Escape:
            if self.nodes:
                self._finish()
            else:
                self.cv.set_tool("select")
            return True
        if k == Qt.Key_Backspace and self.nodes:
            self.nodes.pop()
            return True
        return False

    def draw(self, p, tf):
        if not self.nodes:
            return
        path = nodes.to_path([nodes.SubPath(self.nodes, False)])
        if self.cursor_pt is not None:
            last = self.nodes[-1]
            if last.cout:
                path.cubicTo(last.cout[0], last.cout[1], self.cursor_pt.x(), self.cursor_pt.y(),
                             self.cursor_pt.x(), self.cursor_pt.y())
            else:
                path.lineTo(self.cursor_pt)
        p.setPen(_pen(C["accent_hi"], 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawPath(tf.map(path))
        for i, nd in enumerate(self.nodes):
            v = tf.map(QPointF(nd.x, nd.y))
            p.setBrush(QColor("#FFFFFF" if i else C["success"]))
            p.setPen(_pen(C["accent_lo"], 1))
            p.drawRect(QRectF(v.x() - 3.5, v.y() - 3.5, 7, 7))


class FreehandTool(Tool):
    """Mano libera (0.19.6): premi e trascina; al rilascio il tratto diventa un tracciato levigato (core/simplify),
    sul livello corrente, con un solo passo di Annulla. Finire vicino al punto di partenza chiude la forma.
    Il primo punto si aggancia come negli altri strumenti (Alt no); i punti del tratto seguono il mouse."""
    name = "freehand"
    label = tr("Mano libera")
    SMOOTH_PX = 2.5  # levigatura: scarto ammesso, in pixel dello schermo (convertiti in mm con lo zoom)
    CLOSE_PX = 8  # finire così vicino al punto di partenza chiude la forma
    MIN_PX = 4  # un tratto più corto è un clic: non disegna niente
    STEP_PX = 1.0  # distanza minima fra due punti raccolti
    ANGLE = 60.0  # spigoli vivi sopra questo cambio di direzione

    def __init__(self, cv):
        super().__init__(cv)
        self.pts = []
        self.active = False

    def deactivate(self):
        self.cancel()

    def cancel(self):
        self.pts = []
        self.active = False

    def press(self, e, p):
        if e.button() == Qt.RightButton:
            if self.active:  # tasto destro durante il tratto: annullato
                self.cancel()
                self.cv.viewport().update()
            return
        if e.button() != Qt.LeftButton:
            return
        q = self._snap(e, p)
        self.pts = [(q.x(), q.y())]
        self.active = True

    def move(self, e, p):
        if not self.active:
            self._hover_snap(e, p)
            self.cv.status.emit(tr("Mano libera: premi e trascina per disegnare · finisci sul punto di partenza per "
                                   "chiudere · Esc annulla il tratto"))
            return
        last = self.pts[-1]
        if math.hypot(p.x() - last[0], p.y() - last[1]) >= self.cv.px(self.STEP_PX):
            self.pts.append((p.x(), p.y()))

    def release(self, e, p):
        if not self.active or e.button() != Qt.LeftButton:
            return
        last = self.pts[-1]
        if math.hypot(p.x() - last[0], p.y() - last[1]) > 1e-9:
            self.pts.append((p.x(), p.y()))
        pts = self.pts
        self.cancel()
        shape = self.build(pts)
        self.cv.viewport().update()
        if shape is None:
            return
        self.ed.add([shape], tr("Disegno a mano libera"))
        self.cv.tool_done()

    def build(self, pts):
        """Punti del tratto (mm del piano) -> PathShape levigato, o None se il tratto è troppo corto."""
        from ..core import simplify

        if len(pts) < 2:
            return None
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        if length < self.cv.px(self.MIN_PX):
            return None
        close = self.cv.px(self.CLOSE_PX)
        closed = len(pts) > 3 and math.dist(pts[0], pts[-1]) <= close and length > 3 * close
        if closed:
            while len(pts) > 3 and math.dist(pts[0], pts[-1]) < self.cv.px(self.STEP_PX):
                pts = pts[:-1]  # gli ultimi punti sopra la partenza: la chiusura li sostituisce
        sp = nodes.SubPath([nodes.Node(x, y) for x, y in pts], closed)
        new, _ = simplify.simplify_subpath(sp, simplify.clamp_tol(self.cv.px(self.SMOOTH_PX)), self.ANGLE)
        return PathShape(nodes.to_path([new or sp]), layer=self.ed.current_layer)

    def wants_key(self, e):
        return e.key() == Qt.Key_Escape

    def key(self, e):
        if e.key() == Qt.Key_Escape:
            if self.active:
                self.cancel()
                self.cv.viewport().update()
            else:
                self.cv.set_tool("select")
            return True
        return False

    def draw(self, p, tf):
        if not self.active or len(self.pts) < 2:
            return
        path = QPainterPath()
        path.moveTo(*self.pts[0])
        for q in self.pts[1:]:
            path.lineTo(*q)
        p.setPen(_pen(C["accent_hi"], 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawPath(tf.map(path))


# ======================================================================= forme
class ShapeTool(Tool):
    kind = "rect"

    def __init__(self, cv):
        super().__init__(cv)
        self.a = None
        self.b = None

    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        _, _, alt = _mods(e)
        self.a = p if alt else self.cv.snap(p)
        self.b = self.a

    def move(self, e, p):
        shift, ctrl, alt = _mods(e)
        if self.a is None:
            self._hover_snap(e, p)
            return
        self.b = p if alt else self.cv.snap(p)
        r = self._rect(shift, ctrl)
        self.cv.status.emit(tr("{0}  {1:.2f} × {2:.2f} mm   Maiusc: proporzionale   Ctrl: dal centro", self.label, r.width(), r.height()))

    def _rect(self, shift, ctrl):
        a, b = self.a, self.b
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if shift:
            m = max(abs(dx), abs(dy))
            dx = math.copysign(m, dx or 1)
            dy = math.copysign(m, dy or 1)
        if ctrl:
            return QRectF(a.x() - abs(dx), a.y() - abs(dy), 2 * abs(dx), 2 * abs(dy))
        return QRectF(QPointF(a.x(), a.y()), QPointF(a.x() + dx, a.y() + dy)).normalized()

    def release(self, e, p):
        if self.a is None:
            return
        shift, ctrl, _ = _mods(e)
        r = self._rect(shift, ctrl)
        if r.width() < self.cv.px(4) and r.height() < self.cv.px(4):
            r = QRectF(self.a.x(), self.a.y(), 20, 20)  # clic semplice: forma da 20 mm
        s = self.make(r)
        s.apply(QTransform.fromTranslate(r.left(), r.top()))
        self.a = self.b = None
        self.ed.add([s], f"Disegna {self.label.lower()}")
        self.cv.tool_done()

    def make(self, r):
        raise NotImplementedError

    def draw(self, p, tf):
        if self.a is None:
            return
        from PySide6.QtWidgets import QApplication

        mods = QApplication.keyboardModifiers()
        r = self._rect(bool(mods & Qt.ShiftModifier), bool(mods & Qt.ControlModifier))
        s = self.make(r)
        s.apply(QTransform.fromTranslate(r.left(), r.top()))
        p.setPen(_pen(C["accent_hi"], 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawPath(tf.map(s.path()))


class RectTool(ShapeTool):
    name = "rect"
    label = tr("Rettangolo")

    def make(self, r):
        return RectShape(max(r.width(), 0.01), max(r.height(), 0.01), self.cv.tool_options.get("corner_radius", 0.0),
                         layer=self.ed.current_layer)


class EllipseTool(ShapeTool):
    name = "ellipse"
    label = tr("Ellisse")

    def make(self, r):
        return EllipseShape(max(r.width(), 0.01), max(r.height(), 0.01), layer=self.ed.current_layer)


class PolygonTool(ShapeTool):
    name = "polygon"
    label = tr("Poligono")

    def make(self, r):
        o = self.cv.tool_options
        return PolygonShape(max(r.width(), 0.01), max(r.height(), 0.01), o.get("sides", 6), 0.0,
                            layer=self.ed.current_layer)


class StarTool(ShapeTool):
    name = "star"
    label = tr("Stella")

    def make(self, r):
        o = self.cv.tool_options
        return PolygonShape(max(r.width(), 0.01), max(r.height(), 0.01), o.get("star_points", 5),
                            o.get("star_ratio", 0.5), layer=self.ed.current_layer)


class SpecialTool(ShapeTool):
    """Forme della galleria: freccia, cuore, ingranaggio, scudo, medaglia… Maiusc = proporzioni naturali."""

    name = "special"
    label = tr("Forme")

    def _form(self):
        return self.cv.tool_options.get("special", "arrow")

    def _rect(self, shift, ctrl):
        if not shift:
            return super()._rect(False, ctrl)
        from ..core import shapes_lib

        asp = shapes_lib.natural_aspect(self._form())
        a, b = self.a, self.b
        dx, dy = b.x() - a.x(), b.y() - a.y()
        w = max(abs(dx), abs(dy) * asp)
        h = w / asp
        dx, dy = math.copysign(w, dx or 1), math.copysign(h, dy or 1)
        if ctrl:
            return QRectF(a.x() - abs(dx), a.y() - abs(dy), 2 * abs(dx), 2 * abs(dy))
        return QRectF(QPointF(a.x(), a.y()), QPointF(a.x() + dx, a.y() + dy)).normalized()

    def release(self, e, p):
        if self.a is not None:
            shift, ctrl, _ = _mods(e)
            r = self._rect(shift, ctrl)
            if r.width() < self.cv.px(4) and r.height() < self.cv.px(4):  # clic: misura naturale, 30 mm di larghezza
                from ..core import shapes_lib

                asp = shapes_lib.natural_aspect(self._form())
                self.b = QPointF(self.a.x() + 30, self.a.y() + 30 / asp)
                s = self.make(QRectF(self.a, self.b).normalized())
                s.apply(QTransform.fromTranslate(self.a.x(), self.a.y()))
                self.a = self.b = None
                self.ed.add([s], f"Disegna {s.describe().lower()}")
                self.cv.tool_done()
                return
        super().release(e, p)

    def make(self, r):
        from ..core.document import SpecialShape

        f = self._form()
        return SpecialShape(f, max(r.width(), 0.01), max(r.height(), 0.01),
                            self.cv.tool_options.get("special_param", {}).get(f), layer=self.ed.current_layer)


# ======================================================================= testo
class TextTool(Tool):
    name = "text"
    label = tr("Testo")

    def cursor(self):
        return QCursor(Qt.IBeamCursor)

    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        hit = self.cv.hit_shape(p)
        if isinstance(hit, TextShape):
            self.ed.select([hit])
            self.cv.edit_text.emit(hit)
            return
        q = self.cv.snap(p)
        d = self.cv.text_defaults
        t = TextShape(tr("Testo"), d["family"], d["size"], layer=self.ed.current_layer,
                      bold=d["bold"], italic=d["italic"], align=d["align"], letter_spacing=d["letter_spacing"],
                      line_spacing=d["line_spacing"], upper=d["upper"], weld=d["weld"], arc=d.get("arc", 0.0))
        t.apply(QTransform.fromTranslate(q.x(), q.y()))
        self.ed.add([t], tr("Testo"))
        self.cv.set_tool("select")
        self.cv.edit_text.emit(t)


# ======================================================================= misura
MEASURE_LINE = "#E8590C"  # arancio scuro: si vede sul piano chiaro e sul legno
MEASURE_HALO = "#1A2233"  # bordo scuro sotto la linea
MEASURE_LABEL_BG = "#1A2233"  # etichetta della misura: testo bianco su fondo scuro, sempre leggibile


class MeasureTool(Tool):
    name = "measure"
    label = tr("Misura")

    def __init__(self, cv):
        super().__init__(cv)
        self.a = None
        self.b = None
        self.info = None

    def press(self, e, p):
        self.a = self.cv.snap(p)
        self.b = self.a

    def move(self, e, p):
        shift, _, alt = _mods(e)
        q = p if alt else self.cv.snap(p)
        if self.a is not None and e.buttons() & Qt.LeftButton:
            if shift:
                dx, dy = q.x() - self.a.x(), q.y() - self.a.y()
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
                L = math.hypot(dx, dy)
                q = QPointF(self.a.x() + L * math.cos(ang), self.a.y() + L * math.sin(ang))
            self.b = q
            dx, dy = self.b.x() - self.a.x(), self.b.y() - self.a.y()
            self.cv.status.emit(f"Distanza {math.hypot(dx, dy):.3f} mm   ΔX {dx:+.3f}   ΔY {dy:+.3f}   angolo "
                                f"{math.degrees(math.atan2(dy, dx)):.2f}°")
        else:
            s = self.cv.hit_shape(p)
            if s is not None:
                inf = ops.info([s])
                b = s.bounds()
                self.cv.status.emit(
                    tr("{0}  ·  {1:.2f} × {2:.2f} mm  ·  perimetro {3:.2f} mm", s.describe(), b.width(), b.height(), inf['perimeter'])
                    + (tr("  ·  area {0:.1f} mm²", inf['area']) if inf["closed"] else "")
                    + tr("  ·  {0} nodi  ·  ", inf['nodes']) + (tr("chiusa") if not inf["open"] else tr("{0} aperte", inf['open'])))

    def release(self, e, p):
        pass

    def key(self, e):
        if e.key() == Qt.Key_Escape:
            self.a = self.b = None
            self.cv.set_tool("select")
            return True
        return False

    def draw(self, p, tf):
        if self.a is None or self.b is None:
            return
        # 0.17.3: prima giallo chiaro sottile, sul piano chiaro si vedeva appena. Ora linea arancio scuro con un bordo
        # scuro sotto (si legge sul legno chiaro e sulle foto scure) e la misura su un'etichetta piena
        va, vb = tf.map(self.a), tf.map(self.b)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, True)
        halo = QColor(MEASURE_HALO)
        halo.setAlpha(200)
        p.setPen(_pen(halo, 4.5))
        p.drawLine(va, vb)
        p.setPen(_pen(MEASURE_LINE, 2.0))
        p.drawLine(va, vb)
        p.setBrush(QColor(MEASURE_LINE))
        p.setPen(_pen(MEASURE_HALO, 1.5))
        for v in (va, vb):
            p.drawEllipse(v, 4, 4)
        dx, dy = self.b.x() - self.a.x(), self.b.y() - self.a.y()
        txt = f"{math.hypot(dx, dy):.2f} mm"
        sub = f"ΔX {dx:+.2f}  ΔY {dy:+.2f}  {math.degrees(math.atan2(dy, dx)):.1f}°"
        f1 = style.ui_font(10, style.QFont.Weight.Bold)
        f2 = style.ui_font(8)
        from PySide6.QtGui import QFontMetricsF

        m1, m2 = QFontMetricsF(f1), QFontMetricsF(f2)
        w = max(m1.horizontalAdvance(txt), m2.horizontalAdvance(sub)) + 14
        h = m1.height() + m2.height() + 8
        # etichetta accanto al centro della linea, dalla parte di sopra, senza coprirla
        mid = (va + vb) / 2
        lx, ly = vb.x() - va.x(), vb.y() - va.y()
        ln = math.hypot(lx, ly) or 1.0
        nx, ny = -ly / ln, lx / ln
        if ny > 0 or (abs(ny) < 1e-6 and nx < 0):
            nx, ny = -nx, -ny
        off = abs(nx) * w / 2 + abs(ny) * h / 2 + 10
        box = QRectF(0, 0, w, h)
        box.moveCenter(QPointF(mid.x() + nx * off, mid.y() + ny * off))
        vp = QRectF(p.viewport())
        if box.top() < vp.top() + 22 or box.left() < vp.left() + 22 or box.right() > vp.right() - 4:
            box.moveCenter(QPointF(mid.x() - nx * off, mid.y() - ny * off))  # vicino al bordo: dall'altra parte
        p.setPen(_pen(MEASURE_LINE, 1.2))
        p.setBrush(QColor(MEASURE_LABEL_BG))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(f1)
        p.drawText(QRectF(box.left() + 7, box.top() + 3, w, m1.height()), Qt.AlignLeft | Qt.AlignVCenter, txt)
        p.setPen(QColor("#D6DEEC"))
        p.setFont(f2)
        p.drawText(QRectF(box.left() + 7, box.top() + 3 + m1.height(), w, m2.height()), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()


# ======================================================================= forbici (0.17.16)
TRIM_RED = "#E03131"


class TrimTool(Tool):
    """Forbici: passando sopra una linea si colora di rosso il tratto fra i due incroci più vicini; clic = lo toglie.
    Maiusc = ci si ferma anche agli angoli (nodi). Calcolo in core/trim.py (progetto «forbici-taglia-eccedenze»)."""
    name = "trim"
    label = tr("Forbici")

    def __init__(self, cv):
        super().__init__(cv)
        self.hover = None  # (forma, sottotracciato, u, maiusc, tracciato rosso)
        self._cache = {}  # id(forma) -> Trimmer, finché il documento non cambia

    def cursor(self):
        pm = style.pixmap("trim", "#FFFFFF", 26)
        halo = style.pixmap("trim", "#1B2333", 26)
        from PySide6.QtGui import QPainter, QPixmap

        out = QPixmap(30, 30)
        out.fill(Qt.transparent)
        q = QPainter(out)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):  # bordo scuro: si vede sul piano chiaro e sulle foto
            q.drawPixmap(2 + dx, 2 + dy, halo)
        q.drawPixmap(2, 2, pm)
        q.end()
        return QCursor(out, 15, 6)  # punta delle lame

    def activate(self):
        self._cache = {}
        self.hover = None
        try:
            self.ed.changed.connect(self._invalidate)
            self.ed.live.connect(self._invalidate)
            self.ed.plates_changed.connect(self._invalidate)
        except Exception:  # noqa: BLE001
            pass
        self.cv.status.emit(self._hint())

    def deactivate(self):
        for sig in (self.ed.changed, self.ed.live, self.ed.plates_changed):
            try:
                sig.disconnect(self._invalidate)
            except Exception:  # noqa: BLE001
                pass
        self.hover = None
        self._cache = {}

    def _invalidate(self, *_):
        self._cache = {}
        self.hover = None

    @staticmethod
    def _hint():
        return tr("Forbici: passa sopra una linea, il tratto fra due incroci diventa rosso; clic = lo togli. "
                  "Maiusc = fermati anche agli angoli. Esc = Selezione")

    def trimmer(self, shape):
        from ..core import trim

        t = self._cache.get(id(shape))
        if t is None or t.shape is not shape:
            t = trim.Trimmer(self.ed.doc, shape)
            self._cache[id(shape)] = t
        return t

    def find(self, p, shift=False):
        """Aggiorna e ritorna il tratto sotto il punto p (mm sul piano), o None con il motivo nella barra di stato."""
        from ..core import trim

        self.hover = None
        hit = trim.nearest(self.ed.doc, (p.x(), p.y()), self.cv.px(6))
        if hit is None:
            self.cv.status.emit(self._hint())
            return None
        s, si, u, _d = hit
        why = trim.target_ok(self.ed.doc, s)
        if why:
            self.cv.status.emit({"group": tr("È un gruppo: separalo prima (Disponi → Separa) per tagliarne le linee"),
                                 "locked": tr("Forma bloccata: sbloccala per tagliarla"),
                                 }.get(why, self._hint()))
            return None
        T = self.trimmer(s)
        lo, hi = T.piece(si, u, shift)
        sub = T.piece_subpath(si, lo, hi)
        if sub is None:
            return None
        self.hover = (s, si, u, shift, nodes.to_path([sub]))
        self.cv.status.emit(tr("Clic: togli il tratto rosso") if T.cuts[si] or shift else
                            tr("Nessun incrocio su questa linea: con un clic si toglie tutta"))
        return self.hover

    def move(self, e, p):
        shift, _, _ = _mods(e)
        self.find(p, shift)

    def press(self, e, p):
        if e.button() != Qt.LeftButton:
            return
        shift, _, _ = _mods(e)
        h = self.find(p, shift)
        if h is None:
            return
        s, si, u, corners, _path = h
        subs = self.trimmer(s).remaining(si, u, corners)
        self.ed.trim_shape(s, subs)
        self.hover = None
        self.find(p, shift)  # il tratto successivo sotto il mouse

    def draw(self, p, tf):
        if not self.hover:
            return
        path = tf.map(self.hover[4])
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        halo = QColor("#FFFFFF")
        halo.setAlpha(210)
        p.setPen(_pen(halo, 6))
        p.drawPath(path)
        p.setPen(_pen(TRIM_RED, 3))
        p.drawPath(path)
        p.restore()


# ======================================================================= posiziona laser
class PositionTool(Tool):
    name = "position"
    label = tr("Posiziona laser")

    def press(self, e, p):
        if e.button() == Qt.LeftButton:
            q = self.cv.snap(p)
            self.cv.goto_requested.emit(q.x(), q.y())


def make_tools(cv):
    return {t.name: t(cv) for t in (SelectTool, NodeTool, TrimTool, PenTool, FreehandTool, RectTool, EllipseTool, PolygonTool, StarTool,
                                     SpecialTool, TextTool, MeasureTool, PositionTool)}
