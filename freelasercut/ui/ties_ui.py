# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Distanze fisse sul piano (0.23.0, in prova): quote disegnate, doppio clic per il valore, tasto destro per il menu.

Le quote sono solo a schermo: non sono forme, non finiscono nel G-code e non si incidono. Il calcolo è in core/ties.py,
le modifiche passano dall'editor (un passo di Annulla ciascuna).
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF

from ..core import ties
from . import style
from freelasercut.i18n import tr  # noqa: E402

TIE_LINE = "#0CA678"  # verde: diversa dalla selezione (azzurra) e dalla misura (arancio)
TIE_WARN = "#E8590C"  # arancio: chi segue esce dall'area di lavoro o è bloccata e non rispetta la distanza
TIE_OFF = "#868E96"  # grigio: spenta
TIE_HALO = "#1A2233"


def reason_text(why, follower=None, ref=None, axis=""):
    """Perché una distanza fissa non si può aggiungere, in parole."""
    name = follower.describe() if follower is not None else ""
    if why == "same":
        return tr("Distanza fissa: servono due oggetti diversi")
    if why == "locked":
        return tr("«{0}» è bloccata: non può seguire un altro oggetto (sbloccala, oppure scambia i due)", name)
    if why == "cycle":
        return tr("Distanza fissa: «{0}» segue già, anche di seguito, l'altro oggetto (si inseguirebbero)",
                  ref.describe() if ref is not None else "")
    if why == "busy":
        return tr("«{0}» ha già una distanza fissa lungo {1}: toglila prima (tasto destro sulla quota)", name,
                  {"p": tr("X e Y")}.get(axis, axis.upper()))
    return ""


def _pen(color, w, style_=Qt.SolidLine):
    from PySide6.QtGui import QPen

    pen = QPen(QColor(color), w, style_)
    pen.setCapStyle(Qt.RoundCap)
    pen.setCosmetic(True)
    return pen


def items(doc, include_off=True):
    """[(chi segue, indice del legame, legame, riferimento)] da disegnare sul piano attivo."""
    shapes = doc.shapes
    by = {s.id: s for s in shapes}
    act = ties.active(shapes)
    out = []
    for s in shapes:
        on_ids = {id(t) for t in act.get(s.id, ())}
        for k, t in enumerate(getattr(s, "ties", None) or ()):
            ref = by.get(t["ref"])
            if ref is None or ref is s:
                continue  # addormentato: non si disegna
            if id(t) in on_ids or (include_off and t.get("on") is False):
                out.append((s, k, t, ref))
    return out


def label_text(t):
    return f"{t['d']:.2f} mm"


def draw(cv, p, tf):
    """Disegna le quote e ricorda dove sono le etichette (per i clic). Niente se non ce ne sono."""
    cv._tie_hits = []
    if not getattr(cv, "show_ties", True):
        return
    its = items(cv.editor.doc)
    if not its:
        return
    bed = QRectF(0, 0, cv.bed_x, cv.bed_y) if getattr(cv, "bed_x", None) else None
    f1 = style.ui_font(9, style.QFont.Weight.Bold)
    m1 = QFontMetricsF(f1)
    p.save()
    p.setRenderHint(p.RenderHint.Antialiasing, True)
    for s, k, t, ref in its:
        rr, rs = ref.bounds(), s.bounds()
        off = t.get("on") is False
        bad = (not off and (abs(ties.shift(t, rr, rs)[0]) > 1e-4 or abs(ties.shift(t, rr, rs)[1]) > 1e-4)) or \
              (bed is not None and not off and not bed.adjusted(-1e-6, -1e-6, 1e-6, 1e-6).contains(rs))
        col = TIE_OFF if off else TIE_WARN if bad else TIE_LINE
        (x0, y0), (x1, y1) = ties.ends(t, rr, rs)
        va, vb = tf.map(QPointF(x0, y0)), tf.map(QPointF(x1, y1))
        dash = Qt.DashLine if off else Qt.SolidLine
        p.setPen(_pen(TIE_HALO, 3.6))
        p.drawLine(va, vb)
        p.setPen(_pen(col, 1.6, dash))
        p.drawLine(va, vb)
        # segni alle estremità, perpendicolari alla quota
        lx, ly = vb.x() - va.x(), vb.y() - va.y()
        ln = math.hypot(lx, ly)
        nx, ny = (-ly / ln, lx / ln) if ln > 1e-6 else (0.0, 1.0)
        p.setPen(_pen(col, 1.6))
        for v in (va, vb):
            p.drawLine(QPointF(v.x() - nx * 6, v.y() - ny * 6), QPointF(v.x() + nx * 6, v.y() + ny * 6))
        txt = label_text(t)
        w, h = m1.horizontalAdvance(txt) + 12, m1.height() + 4
        box = QRectF(0, 0, w, h)
        mid = (va + vb) / 2
        # sempre di fianco alla linea, mai sopra: non copre i segni né i punti dove si aggancia la Misura
        off = abs(nx) * (w / 2) + abs(ny) * (h / 2) + 6
        box.moveCenter(QPointF(mid.x() + nx * off, mid.y() + ny * off))
        p.setPen(_pen(col, 1.2))
        p.setBrush(QColor(TIE_HALO))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#FFFFFF") if not off else QColor("#CED4DA"))
        p.setFont(f1)
        p.drawText(box, Qt.AlignCenter, txt)
        cv._tie_hits.append((QRectF(box), s.id, k))
    p.restore()


def hit(cv, view_pt):
    """(chi segue, indice) della quota sotto il punto (coordinate della vista), oppure None."""
    for box, sid, k in reversed(getattr(cv, "_tie_hits", None) or ()):
        if box.adjusted(-3, -3, 3, 3).contains(view_pt):
            s = cv.editor.doc.find(sid)
            if s is not None and k < len(s.ties):
                return s, k
    return None


def edit_value(cv, follower, index, value=None):
    """Doppio clic sulla quota: nuova distanza (value per le prove; senza, la chiede). -> True se cambiata."""
    t = follower.ties[index]
    if value is None:
        from PySide6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getDouble(cv, tr("Distanza fissa"), tr("Distanza (mm):"), t["d"], 0.0, ties.D_MAX, 2)
        if not ok:
            return False
    cv.editor.set_tie_distance(follower, index, value)
    return True


def menu(cv, follower, index, global_pos, run=True):
    """Menu del tasto destro sulla quota. run=False: lo prepara e lo restituisce senza aprirlo (prove)."""
    from PySide6.QtWidgets import QMenu

    ed = cv.editor
    t = follower.ties[index]
    m = QMenu(cv)
    m.addAction(tr("Cambia la distanza…"), lambda: edit_value(cv, follower, index))
    if t.get("on") is False:
        def on():
            why = ed.set_tie_on(follower, index, True)
            if why:
                ed.message.emit(reason_text(why, follower, ed.doc.find(t["ref"]), t["axis"]))
        m.addAction(tr("Riaccendi la distanza fissa"), on)
    else:
        m.addAction(tr("Spegni la distanza fissa (resta salvata)"), lambda: ed.set_tie_on(follower, index, False))
    m.addAction(tr("Togli la distanza fissa"), lambda: ed.remove_ties([follower], index))
    if run:
        m.exec(global_pos)
    return m


# ------------------------------------------------------------------ dallo strumento Misura
def anchor_at(rect, x, y, tol):
    """Uno dei 9 punti dell'ingombro vicino a (x, y): [bx, by] oppure None."""
    best, bd = None, tol
    for ex in ties.EDGES:
        for ey in ties.EDGES:
            px, py = ties.point(rect, (ex, ey))
            d = math.hypot(px - x, py - y)
            if d <= bd:
                best, bd = [ex, ey], d
    return best


def shape_anchor(doc, x, y, tol, exclude=None):
    """(forma di primo livello, punto) per un'estremità della misura: la più in alto nell'ordine di disegno."""
    for s in reversed(doc.shapes):
        if s is exclude or s.hidden:
            continue
        a = anchor_at(s.bounds(), x, y, tol)
        if a is not None:
            return s, a
    return None, None


def tie_from_measure(doc, a, b, tol):
    """Dalla misura da a a b (punti sul piano) la distanza fissa da proporre. -> (riferimento, chi segue, legame) oppure
    (None, None, motivo)."""
    ref, ea = shape_anchor(doc, a.x(), a.y(), tol)
    fol, eb = shape_anchor(doc, b.x(), b.y(), tol, exclude=ref)
    if ref is None or fol is None:
        return None, None, "ends"
    dx, dy = b.x() - a.x(), b.y() - a.y()
    rr, rs = ref.bounds(), fol.bounds()
    if abs(dy) <= tol and abs(dx) > tol:
        t = ties.make_xy(ref.id, rr, rs, "x", ea[0], eb[0])
    elif abs(dx) <= tol and abs(dy) > tol:
        t = ties.make_xy(ref.id, rr, rs, "y", ea[1], eb[1])
    else:
        t = ties.make_p(ref.id, rr, rs, ea, eb)
    if t is None:
        return None, None, "ends"
    return ref, fol, t
