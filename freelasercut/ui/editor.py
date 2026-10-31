# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Controllore dell'editor: documento, selezione, cronologia (annulla/ripeti), appunti, operazioni.

Tela e pannelli non modificano mai il documento direttamente: passano da qui,
così ogni modifica è annullabile e tutte le viste restano sincronizzate.
"""
import json
import uuid

from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QGuiApplication, QTransform
from PySide6.QtCore import QMimeData

from ..core import ops
from ..core.document import Document, GroupShape, ImageShape, PathShape, TextShape, shape_from_dict
from freelasercut.i18n import tr  # noqa: E402

MIME = "application/x-freelasercut-shapes"
TOOL_LAYER = 30  # livello strumenti: mai inciso (guide, contorni del materiale)


class Editor(QObject):
    changed = Signal()  # il documento è cambiato (forme o livelli)
    live = Signal()  # anteprima durante un trascinamento (solo la tela si aggiorna)
    selection_changed = Signal()
    history_changed = Signal()
    message = Signal(str)

    MAX_HISTORY = 300

    def __init__(self, doc=None):
        super().__init__()
        self.doc = doc or Document()
        self.selection = []  # forme di primo livello, ultima = più recente
        self.current_layer = 1
        self.undo_stack = []
        self.redo_stack = []
        self._pending = None
        self.dirty = False
        self.clipboard = None

    # ================================================================ cronologia
    def begin(self, label):
        if self._pending is None:
            self._pending = (label, self.doc.snapshot(), [s.id for s in self.selection])

    def commit(self):
        if self._pending is None:
            return
        label, before, sel_before = self._pending
        self._pending = None
        after = self.doc.snapshot()
        if after == before:
            return
        self.undo_stack.append((label, before, sel_before, after, [s.id for s in self.selection]))
        if len(self.undo_stack) > self.MAX_HISTORY:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.dirty = True
        self.history_changed.emit()
        self.changed.emit()

    def cancel(self):
        if self._pending is None:
            return
        _, before, sel = self._pending
        self._pending = None
        self.doc.restore(before)
        self._reselect(sel)
        self.changed.emit()

    def preview_changed(self):
        """Durante un trascinamento: aggiorna la tela senza registrare nella cronologia."""
        self.live.emit()

    def _reselect(self, ids):
        by = {s.id: s for s in self.doc.shapes}
        self.selection = [by[i] for i in ids if i in by]
        self.selection_changed.emit()

    def undo(self):
        if not self.undo_stack:
            return
        label, before, sel_before, after, sel_after = self.undo_stack.pop()
        self.redo_stack.append((label, before, sel_before, after, sel_after))
        self.doc.restore(before)
        self._reselect(sel_before)
        self.dirty = True
        self.history_changed.emit()
        self.changed.emit()
        self.message.emit(f"Annullato: {label}")

    def redo(self):
        if not self.redo_stack:
            return
        label, before, sel_before, after, sel_after = self.redo_stack.pop()
        self.undo_stack.append((label, before, sel_before, after, sel_after))
        self.doc.restore(after)
        self._reselect(sel_after)
        self.dirty = True
        self.history_changed.emit()
        self.changed.emit()
        self.message.emit(f"Ripetuto: {label}")

    def undo_label(self):
        return self.undo_stack[-1][0] if self.undo_stack else ""

    def redo_label(self):
        return self.redo_stack[-1][0] if self.redo_stack else ""

    def run(self, label, fn, *a, **k):
        """Esegue fn come un'unica azione annullabile."""
        self.begin(label)
        try:
            res = fn(*a, **k)
        except Exception:
            self.cancel()
            raise
        self.commit()
        return res

    # ================================================================ documento
    def set_document(self, doc):
        self.doc = doc
        self.selection = []
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self.history_changed.emit()
        self.selection_changed.emit()
        self.changed.emit()

    # ================================================================ selezione
    def select(self, shapes, mode="replace"):
        shapes = [s for s in shapes if s is not None]
        if mode == "replace":
            self.selection = list(shapes)
        elif mode == "add":
            for s in shapes:
                if s not in self.selection:
                    self.selection.append(s)
        elif mode == "toggle":
            for s in shapes:
                if s in self.selection:
                    self.selection.remove(s)
                else:
                    self.selection.append(s)
        elif mode == "remove":
            self.selection = [s for s in self.selection if s not in shapes]
        self.selection_changed.emit()

    def clear_selection(self):
        if self.selection:
            self.selection = []
            self.selection_changed.emit()

    def select_all(self):
        self.select([s for s in self.doc.shapes if not s.hidden and not s.locked])

    def invert_selection(self):
        self.select([s for s in self.doc.shapes if s not in self.selection and not s.hidden and not s.locked])

    def select_open(self, only_fill=False):
        res = []
        for s in self.doc.shapes:
            if isinstance(s, (ImageShape,)) or s.hidden:
                continue
            if only_fill and self.doc.layer(s.layer).mode not in ("fill", "offset_fill"):
                continue
            if not s.closed():
                res.append(s)
        self.select(res)
        self.message.emit(f"{len(res)} forme aperte" + (tr(" su livelli di riempimento") if only_fill else ""))

    def select_layer(self, index):
        self.select([s for s in self.doc.shapes if s.layer == index and not s.hidden])

    def select_contained(self):
        if not self.selection:
            return
        cont = ops.contained_in(self.selection[-1], self.doc.shapes)
        self.select(cont, "add")

    def editable(self):
        return [s for s in self.selection if not s.locked]

    def selection_bounds(self):
        return ops.union_bounds(self.selection) if self.selection else QRectF()

    # ================================================================ forme
    def add(self, shapes, label=tr("Aggiungi"), select=True):
        shapes = shapes if isinstance(shapes, list) else [shapes]

        def do():
            for s in shapes:
                self.doc.add(s)
            if select:
                self.selection = list(shapes)
        self.run(label, do)
        if select:
            self.selection_changed.emit()
        return shapes

    def delete(self):
        sel = self.editable()
        if not sel:
            return
        self.run(tr("Elimina"), self.doc.remove, sel)
        self.select([])

    def transform(self, tf, label=tr("Trasforma"), shapes=None):
        shapes = shapes if shapes is not None else self.editable()
        if not shapes:
            return
        self.run(label, ops.transform_all, shapes, tf)

    def set_layer(self, index):
        sel = self.editable()
        if not sel:
            self.current_layer = index
            return

        def do():
            for s in sel:
                if isinstance(s, GroupShape):
                    for leaf, _ in s.leaves():
                        leaf.layer = index
                s.layer = index
                s.invalidate()
            self.doc.layer(index)
        self.run(tr("Cambia livello"), do)
        self.current_layer = index

    def replace(self, old, new, label):
        """Sostituisce forme mantenendo la posizione nell'ordine di disegno."""
        new = [n for n in (new if isinstance(new, list) else [new]) if n is not None]

        def do():
            ids = {s.id for s in old}
            idx = min((i for i, s in enumerate(self.doc.shapes) if s.id in ids), default=len(self.doc.shapes))
            self.doc.remove(old)
            for k, n in enumerate(new):
                self.doc.shapes.insert(min(idx + k, len(self.doc.shapes)), n)
                self.doc.layer(n.layer)
            self.selection = list(new)
        self.run(label, do)
        self.selection_changed.emit()
        return new

    def modify(self, shape, label, **params):
        """Cambia i parametri di una forma (es. testo, raggio) in modo annullabile."""
        def do():
            for k, v in params.items():
                setattr(shape, k, v)
            shape.invalidate()
        self.run(label, do)

    # ================================================================ appunti
    def copy(self):
        sel = self.selection
        if not sel:
            return
        data = {"shapes": [s.to_dict() for s in sel], "images": list({l.image_id for s in sel for l, _ in s.leaves()
                                                                       if isinstance(l, ImageShape)})}
        self.clipboard = (data, {iid: self.doc.images.get(iid) for iid in data["images"]})
        md = QMimeData()
        md.setData(MIME, json.dumps(data).encode())
        try:
            QGuiApplication.clipboard().setMimeData(md)
        except Exception:  # noqa: BLE001
            pass
        self.message.emit(f"Copiate {len(sel)} forme")

    def cut(self):
        self.copy()
        self.delete()

    def paste(self, at=None, in_place=False):
        if not self.clipboard:
            return []
        data, imgs = self.clipboard
        for iid, im in imgs.items():
            if im is not None and iid not in self.doc.images:
                self.doc.images[iid] = im
        shapes = []
        for d in data["shapes"]:
            s = shape_from_dict(d, self.doc.images)
            s.id = uuid.uuid4().hex[:12]
            if isinstance(s, GroupShape):
                for leaf, _ in s.leaves():
                    leaf.id = uuid.uuid4().hex[:12]
            shapes.append(s)
        if not in_place:
            b = ops.union_bounds(shapes)
            if at is not None:
                ops.transform_all(shapes, QTransform.fromTranslate(at.x() - b.center().x(), at.y() - b.center().y()))
            else:
                ops.transform_all(shapes, QTransform.fromTranslate(5, -5))
        return self.add(shapes, tr("Incolla"))

    def duplicate(self):
        sel = self.selection
        if not sel:
            return
        copies = [s.clone() for s in sel]
        self.add(copies, tr("Duplica"))

    # ================================================================ operazioni
    def _need(self, n, msg):
        if len(self.editable()) < n:
            self.message.emit(msg)
            return False
        return True

    def group(self):
        if not self._need(2, tr("Seleziona almeno due forme da raggruppare")):
            return
        sel = self.editable()
        g = ops.group(sel)
        self.replace(sel, g, "Raggruppa")

    def ungroup(self):
        groups = [s for s in self.editable() if isinstance(s, GroupShape)]
        if not groups:
            self.message.emit("Nessun gruppo selezionato")
            return
        kids = []
        self.begin(tr("Separa"))
        for g in groups:
            idx = self.doc.shapes.index(g)
            children = ops.ungroup(g)
            self.doc.shapes[idx:idx + 1] = children
            kids += children
        self.selection = kids
        self.commit()
        self.selection_changed.emit()

    def convert_to_path(self):
        sel = [s for s in self.editable() if not isinstance(s, (ImageShape, GroupShape, PathShape))]
        if not sel:
            self.message.emit(tr("Seleziona rettangoli, ellissi, poligoni o testi da convertire"))
            return
        self.begin(tr("Converti in tracciato"))
        out = []
        for s in sel:
            p = ops.to_path(s)
            idx = self.doc.shapes.index(s)
            self.doc.shapes[idx] = p
            out.append(p)
        self.selection = out
        self.commit()
        self.selection_changed.emit()

    def boolean(self, op):
        sel = [s for s in self.editable() if not isinstance(s, ImageShape)]
        if len(sel) != 2:
            self.message.emit(tr("Le operazioni booleane lavorano su due forme chiuse: seleziona prima quella da tenere"))
            return
        names = {"union": tr("Unione"), "difference": tr("Differenza"), "intersection": tr("Intersezione"), "xor": tr("Esclusione")}
        res = ops.boolean(sel[0], sel[1], op)
        if res is None:
            self.message.emit(tr("Il risultato è vuoto: le forme non si sovrappongono?"))
            return
        self.replace(sel, res, names[op])

    def weld(self):
        sel = [s for s in self.editable() if not isinstance(s, ImageShape)]
        if len(sel) < 1:
            return
        res = ops.weld(sel)
        if res is None:
            self.message.emit(tr("Nessuna forma chiusa da saldare"))
            return
        self.replace(sel, res, "Salda")

    def break_apart(self):
        out_all = []
        self.begin(tr("Scomponi"))
        for s in list(self.editable()):
            if isinstance(s, ImageShape):
                continue
            parts = ops.break_apart(s)
            if parts:
                idx = self.doc.shapes.index(s)
                self.doc.shapes[idx:idx + 1] = parts
                out_all += parts
        if out_all:
            self.selection = out_all
        self.commit()
        if out_all:
            self.select(out_all)
        else:
            self.message.emit(tr("Niente da scomporre"))

    def close_paths(self, tol=0.5):
        sel = [s for s in self.editable() if not isinstance(s, ImageShape)]
        res, n = ops.close_paths(sel, tol)
        if not n:
            self.message.emit(tr("Nessun tracciato da chiudere entro {0:g} mm", tol))
            return
        self.begin(tr("Chiudi tracciati"))
        new_sel = []
        for s, r in zip(sel, res):
            if r is not None:
                self.doc.shapes[self.doc.shapes.index(s)] = r
                new_sel.append(r)
            else:
                new_sel.append(s)
        self.selection = new_sel
        self.commit()
        self.selection_changed.emit()
        self.message.emit(f"Chiusi {n} tracciati")

    def auto_join(self, tol=0.05):
        sel = [s for s in self.editable() if not isinstance(s, (ImageShape, GroupShape))]
        if not sel:
            return
        res, n = ops.auto_join(sel, tol)
        self.replace(sel, res, "Unisci estremi")
        self.message.emit(f"{n} giunzioni")

    def reverse(self):
        sel = [s for s in self.editable() if not isinstance(s, (ImageShape, GroupShape))]
        if not sel:
            return
        self.replace(sel, [ops.reverse(s) for s in sel], "Inverti direzione")

    def offset(self, dist, direction, corner, keep_original=True, outer_only=False):
        sel = [s for s in self.editable() if not isinstance(s, ImageShape)]
        if not sel:
            return
        res = ops.offset_shapes(sel, dist, direction, corner, outer_only)
        if not res:
            self.message.emit(tr("L'offset non ha prodotto forme"))
            return
        if keep_original:
            self.add(res, tr("Offset"))
        else:
            self.replace(sel, res, "Offset")

    def delete_duplicates(self):
        dup = ops.find_duplicates(self.doc.shapes)
        if not dup:
            self.message.emit("Nessun duplicato")
            return
        self.run(tr("Elimina duplicati"), self.doc.remove, dup)
        self.select([s for s in self.selection if s not in dup])
        self.message.emit(f"Eliminati {len(dup)} duplicati")

    def align(self, kind):
        sel = self.editable()
        if len(sel) < 2:
            self.message.emit(tr("Seleziona almeno due forme da allineare"))
            return
        locked = [s for s in self.selection if s.locked]
        ref = locked[0].bounds() if locked else None
        self.run(tr("Allinea"), ops.align, sel, kind, ref)

    def distribute(self, axis, mode):
        if not self._need(3, tr("Seleziona almeno tre forme da distribuire")):
            return
        self.run(tr("Distribuisci"), ops.distribute, self.editable(), axis, mode)

    def same_size(self, which):
        if not self._need(2, tr("Seleziona almeno due forme: l'ultima dà la misura")):
            return
        sel = self.editable()
        self.run(tr("Stessa misura"), ops.same_size, sel, sel[-1], which)

    def flip(self, horizontal):
        if self.editable():
            self.run(tr("Rifletti"), ops.flip, self.editable(), horizontal)

    def rotate(self, deg):
        if self.editable():
            self.run(tr("Ruota"), ops.rotate, self.editable(), deg)

    def move_to(self, anchor, rect):
        if self.editable():
            self.run(tr("Sposta sul piano"), ops.move_to_anchor, self.editable(), anchor, rect)

    def grid_array(self, cols, rows, dx, dy, spacing="gap", shift=0.0, mirror=False, group=False):
        sel = self.editable()
        if not sel:
            return
        copies = ops.grid_array(sel, cols, rows, dx, dy, spacing, shift, mirror)
        if group:
            self.replace(sel, ops.group(sel + copies), "Serie a griglia")
        else:
            self.add(copies, tr("Serie a griglia"))
            self.select(sel + copies)

    def circular_array(self, count, center, start, end, rotate_copies=True, group=False):
        sel = self.editable()
        if not sel:
            return
        copies = ops.circular_array(sel, count, center, start, end, rotate_copies)
        if group:
            self.replace(sel, ops.group(sel + copies), "Serie circolare")
        else:
            self.add(copies, tr("Serie circolare"))
            self.select(sel + copies)

    def copy_along_path(self, count, rotate_copies=True):
        sel = self.editable()
        if len(sel) < 2:
            self.message.emit(tr("Seleziona prima le forme da copiare e per ultimo il tracciato guida"))
            return
        path = sel[-1]
        objs = sel[:-1]
        copies = ops.copy_along_path(objs, path, count, rotate_copies)
        self.add(copies, tr("Copia lungo tracciato"))

    def lock(self, locked=True):
        if not self.selection:
            return

        def do():
            for s in self.selection:
                s.locked = locked
        self.run(tr("Blocca") if locked else tr("Sblocca"), do)

    def order(self, where):
        sel = self.selection
        if not sel:
            return

        def do():
            rest = [s for s in self.doc.shapes if s not in sel]
            self.doc.shapes = rest + list(sel) if where == "front" else list(sel) + rest
        self.run(tr("Ordine"), do)
