# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Comandi da remoto (per Claude via MCP): un piccolo server locale dentro FreeLaserCut.

Ascolta solo su 127.0.0.1. Ogni richiesta è una riga JSON {"token", "cmd", "args"} e riceve una riga
JSON {"ok", "result" | "error"}. Il token sta in %APPDATA%\\FreeLaserCut\\remote.json e lo legge il server MCP.

Sicurezza: disegnare, modificare, importare, salvare e muovere la testa si può fare da remoto.
Avviare un lavoro col laser NO: il comando prepara il lavoro e apre la conferma sullo schermo,
che deve premere una persona davanti alla macchina.
"""
import base64
import json
import math
import os
import secrets

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtNetwork import QHostAddress, QTcpServer

from .core import gcode, gcode as _g, materials, ops, shapes_lib, variables  # noqa: F401
from .core.document import (
    LAYER_COLORS, MODES, EllipseShape, GroupShape, ImageShape, PathShape, PolygonShape, RectShape, SpecialShape,
    TextShape,
)
from .profile import config_dir

PORT = 47321


def info_path():
    return os.path.join(config_dir(), "remote.json")


def read_info():
    try:
        with open(info_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class RemoteError(Exception):
    pass


class RemoteServer:
    def __init__(self, win):
        self.win = win
        self.token = secrets.token_hex(16)
        self.server = QTcpServer()
        self.server.newConnection.connect(self._new)
        self.port = None
        for port in (PORT, PORT + 1, PORT + 2, 0):
            if self.server.listen(QHostAddress.LocalHost, port):
                self.port = self.server.serverPort()
                break
        if self.port:
            try:
                with open(info_path(), "w", encoding="utf-8") as fh:
                    json.dump({"port": self.port, "token": self.token, "pid": os.getpid()}, fh)
            except OSError:
                pass
        self.log = []  # ultimi comandi ricevuti (mostrati nella barra di stato)
        from collections import deque

        self.console = deque(maxlen=200)  # ultime righe scambiate con la scheda (per la diagnosi)
        win.ctl.line_received.connect(lambda l: self._cons("<", l))
        win.ctl.line_sent.connect(lambda l: self._cons(">", l))

    def _cons(self, d, line):
        line = str(line)
        if line.startswith("<") and line.endswith(">") and self.console and self.console[-1][2] == line:
            return  # stati ripetuti uguali: non servono
        import time as _t

        self.console.append((_t.strftime("%H:%M:%S"), d, line))

    # ------------------------------------------------------------ rete
    def _new(self):
        while self.server.hasPendingConnections():
            s = self.server.nextPendingConnection()
            s.setProperty("buf", b"")
            s.readyRead.connect(lambda s=s: self._read(s))
            s.disconnected.connect(s.deleteLater)

    def _read(self, sock):
        buf = bytes(sock.property("buf") or b"") + bytes(sock.readAll())
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            reply = self.handle(line)
            sock.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            sock.flush()
        sock.setProperty("buf", buf)

    def handle(self, raw):
        try:
            req = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {"ok": False, "error": "richiesta non valida"}
        if req.get("token") != self.token:
            return {"ok": False, "error": "token non valido"}
        cmd = req.get("cmd", "")
        fn = getattr(self, "c_" + cmd, None)
        if fn is None:
            return {"ok": False, "error": f"comando sconosciuto: {cmd}"}
        try:
            res = fn(**(req.get("args") or {}))
            self.win.statusBar().showMessage(f"Claude: {cmd.replace('_', ' ')}", 4000)
            return {"ok": True, "result": res}
        except RemoteError as ex:
            return {"ok": False, "error": str(ex)}
        except TypeError as ex:
            return {"ok": False, "error": f"argomenti non validi per {cmd}: {ex}"}
        except Exception as ex:  # noqa: BLE001 — l'errore torna a Claude, FreeLaserCut resta in piedi
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------ aiuti
    @property
    def ed(self):
        return self.win.editor

    @property
    def doc(self):
        return self.win.editor.doc

    def _find(self, ids):
        if ids is None or ids == "selection":
            sel = list(self.ed.selection)
            if not sel:
                raise RemoteError("nessuna forma selezionata: indica gli id (vedi list_shapes)")
            return sel
        if ids == "all":
            return list(self.doc.shapes)
        ids = [ids] if isinstance(ids, str) else list(ids)
        by = {s.id: s for s in self.doc.shapes}
        out = [by[i] for i in ids if i in by]
        missing = [i for i in ids if i not in by]
        if missing:
            raise RemoteError(f"forme non trovate: {missing}")
        return out

    def _desc(self, s):
        b = s.bounds()
        d = {"id": s.id, "type": s.kind, "name": s.describe(), "layer": s.layer,
             "x": round(b.left(), 3), "y": round(b.top(), 3), "width": round(b.width(), 3),
             "height": round(b.height(), 3), "center": [round(b.center().x(), 3), round(b.center().y(), 3)],
             "locked": s.locked}
        if isinstance(s, TextShape):
            d.update(text=s.text, shown_text=s.shown_text(), font=s.family, size=s.size, arc=s.arc)
        if isinstance(s, SpecialShape):
            d.update(form=s.form, param=s.param)
        if isinstance(s, GroupShape):
            d["children"] = len(s.children)
        return d

    def _place(self, s, x=None, y=None, anchor="center"):
        """Mette la forma con il punto di ancoraggio in (x, y). anchor: center | bottom_left | top_left …"""
        b = s.path().boundingRect()
        if x is None or y is None:
            x = self.win.profile.bed_x / 2 if x is None else x
            y = self.win.profile.bed_y / 2 if y is None else y
        ax = {"left": b.left(), "right": b.right()}.get(anchor.split("_")[-1] if "_" in anchor else "", b.center().x())
        ay = {"bottom": b.top(), "top": b.bottom()}.get(anchor.split("_")[0] if "_" in anchor else "", b.center().y())
        if anchor in ("left", "right"):
            ax = b.left() if anchor == "left" else b.right()
        s.apply(QTransform.fromTranslate(x - ax, y - ay))

    def _layer(self, layer):
        if layer is None:
            return self.ed.current_layer
        layer = int(layer)
        if not 0 <= layer <= 29:
            raise RemoteError("il livello va da 0 a 29")
        return layer

    # ------------------------------------------------------------ lettura
    def c_status(self):
        p = self.win.profile
        ctl = self.win.ctl
        st = ctl.last_status or {}
        return {"document": self.doc.name, "shapes": len(self.doc.shapes), "selection": [s.id for s in self.ed.selection],
                "bed_mm": [p.bed_x, p.bed_y], "units": "mm, origine in basso a sinistra (davanti a sinistra), Y verso l'alto",
                "machine": {"connected": ctl.connected, "state": st.get("state"), "homed": ctl.homed,
                            "head_bed_mm": (lambda h: [round(h.x(), 2), round(h.y(), 2)] if h is not None else None)(
                                self.win.canvas.head_pos())},
                "layers": self.c_list_layers(), "undo": self.ed.undo_label()}

    def c_list_shapes(self):
        return [self._desc(s) for s in self.doc.shapes]

    def c_list_layers(self):
        out = []
        for cs in self.doc.used_layers():
            out.append({"index": cs.index, "name": cs.label(), "color": LAYER_COLORS[cs.index % 30], "mode": cs.mode,
                        "speed_mm_min": cs.speed, "power_max_pct": cs.power_max, "power_min_pct": cs.power_min,
                        "passes": cs.passes, "air": cs.air, "output": cs.output, "interval_mm": cs.interval,
                        "dpi": cs.dpi, "dither": cs.dither, "priority": cs.priority})
        return out

    def c_snapshot(self, width=900, ids=None):
        """Immagine PNG del disegno (piano + forme con i colori dei livelli)."""
        shapes = self._find(ids) if ids else list(self.doc.shapes)
        p = self.win.profile
        rect = QRectF(0, 0, p.bed_x, p.bed_y)
        if shapes:
            rect = ops.union_bounds(shapes).adjusted(-5, -5, 5, 5) if ids else rect.united(ops.union_bounds(shapes))
        width = int(max(200, min(1600, width)))
        k = width / max(rect.width(), 1e-6)
        h = int(max(100, rect.height() * k))
        img = QImage(width, h, QImage.Format_RGB32)
        img.fill(QColor("#FFFFFF"))
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.setTransform(QTransform.fromTranslate(-rect.left(), -rect.bottom()) * QTransform.fromScale(k, -k))
        pen = QPen(QColor("#C8CFDB"))
        pen.setCosmetic(True)
        q.setPen(pen)
        q.drawRect(QRectF(0, 0, p.bed_x, p.bed_y))
        for s in shapes:
            for leaf, tf in s.leaves():
                if leaf.hidden:
                    continue
                if isinstance(leaf, ImageShape):
                    pil = self.doc.images.get(leaf.image_id)
                    if pil is not None:
                        from PIL.ImageQt import ImageQt

                        qi = QImage(ImageQt(pil.convert("RGBA")))
                        q.save()
                        q.setTransform(QTransform.fromScale(1, -1) * QTransform.fromTranslate(0, leaf.h) * tf
                                       * QTransform.fromTranslate(-rect.left(), -rect.bottom()) * QTransform.fromScale(k, -k))
                        q.drawImage(QRectF(0, 0, leaf.w, leaf.h), qi)
                        q.restore()
                    continue
                pen = QPen(QColor(LAYER_COLORS[leaf.layer % 30] if leaf.layer < 30 else "#888888"))
                pen.setCosmetic(True)
                pen.setWidthF(1.4)
                q.setPen(pen)
                q.drawPath(tf.map(leaf.local_path()))
        q.end()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return {"png_base64": base64.b64encode(bytes(ba)).decode("ascii"), "width": width, "height": h,
                "area_mm": [round(rect.left(), 1), round(rect.top(), 1), round(rect.width(), 1), round(rect.height(), 1)]}

    # ------------------------------------------------------------ creazione
    def c_add_shape(self, type, width=30.0, height=None, x=None, y=None, anchor="center", layer=None, corner_radius=0.0,
                    sides=6, points=5, ratio=0.5, form=None, param=None, svg_path=None, rotation=0.0):
        """type: rect | ellipse | circle | polygon | star | special | path. Misure in mm."""
        height = width if height is None else height
        lay = self._layer(layer)
        t = type.lower()
        if t == "rect":
            s = RectShape(width, height, corner_radius, layer=lay)
        elif t in ("ellipse", "circle"):
            s = EllipseShape(width, height if t == "ellipse" else width, layer=lay)
        elif t == "polygon":
            s = PolygonShape(width, height, int(sides), 0.0, layer=lay)
        elif t == "star":
            s = PolygonShape(width, height, int(points), float(ratio), layer=lay)
        elif t == "special":
            if form not in shapes_lib.SHAPES:
                raise RemoteError(f"form deve essere una di: {', '.join(shapes_lib.SHAPES)}")
            s = SpecialShape(form, width, height, param, layer=lay)
        elif t == "path":
            if not svg_path:
                raise RemoteError("serve svg_path (attributo d di un tracciato SVG, in mm, convenzione SVG con Y in giù)")
            import svgelements as se

            from .core.io_formats import _svgpath_to_qpath

            qp = _svgpath_to_qpath(se.Path(svg_path), 1.0)
            s = PathShape(qp, layer=lay)
        else:
            raise RemoteError("type deve essere rect, ellipse, circle, polygon, star, special o path")
        if rotation:
            s.apply(QTransform().rotate(rotation))
        self._place(s, x, y, anchor)
        self.ed.add([s], "Claude: forma")
        return self._desc(s)

    def c_add_text(self, text, x=None, y=None, size=10.0, font="Arial", layer=None, bold=False, italic=False,
                   align="center", arc=0.0, anchor="center", letter_spacing=0.0, upper=False, weld=False):
        """size = altezza delle maiuscole in mm. font: nome di sistema oppure 'futural' (linea singola)…"""
        from .core import text as textmod

        fam = font
        if not textmod.is_single_line(font):
            from PySide6.QtGui import QFontDatabase

            fams = {f.lower(): f for f in QFontDatabase.families()}
            fam = fams.get(font.lower(), font)
        s = TextShape(text, fam, float(size), self._layer(layer), bold=bold, italic=italic, align=align, arc=arc,
                      letter_spacing=letter_spacing, upper=upper, weld=weld)
        self._place(s, x, y, anchor)
        self.ed.add([s], "Claude: testo")
        return self._desc(s)

    def c_list_forms(self):
        return {k: {"name": v[0], "param": v[1], "min": v[2], "max": v[3], "default": v[4]} for k, v in shapes_lib.SHAPES.items()}

    def c_list_fonts(self, query=""):
        from PySide6.QtGui import QFontDatabase

        from .core import text as textmod

        single = [{"font": k, "name": v} for k, v in textmod.SINGLE_LINE_FONTS.items()]
        sysf = [f for f in QFontDatabase.families() if query.lower() in f.lower()][:200]
        return {"single_line": single, "system": sysf}

    # ------------------------------------------------------------ modifica
    def c_select(self, ids="all"):
        self.ed.select(self._find(ids))
        return [s.id for s in self.ed.selection]

    def c_delete(self, ids):
        sel = self._find(ids)
        self.ed.select(sel)
        self.ed.delete()
        return {"deleted": len(sel)}

    def c_transform(self, ids=None, dx=0.0, dy=0.0, x=None, y=None, width=None, height=None, keep_ratio=True,
                    rotate=0.0, scale=None, anchor="center"):
        """Sposta (dx, dy o posizione x, y del punto anchor), ridimensiona (width/height o scale) e ruota (gradi)."""
        shapes = self._find(ids)
        for s in shapes:
            if s.locked:
                raise RemoteError(f"la forma {s.id} è bloccata")
        b = ops.union_bounds(shapes)
        c = b.center()
        tf = QTransform()
        sx = sy = 1.0
        if scale:
            sx = sy = float(scale)
        if width:
            sx = float(width) / max(b.width(), 1e-9)
            sy = sx if keep_ratio and not height else sy
        if height:
            sy = float(height) / max(b.height(), 1e-9)
            sx = sy if keep_ratio and not width else sx
        if sx != 1 or sy != 1:
            tf = tf * ops.about(QTransform.fromScale(sx, sy), c.x(), c.y())
        if rotate:
            tf = tf * ops.about(QTransform().rotate(rotate), c.x(), c.y())
        if tf != QTransform():
            self.ed.transform(tf, "Claude: trasforma", shapes)
        if x is not None or y is not None:
            b = ops.union_bounds(shapes)
            ax = {"left": b.left(), "right": b.right()}
            ay = {"bottom": b.top(), "top": b.bottom()}
            parts = anchor.split("_")
            px = next((ax[p] for p in parts if p in ax), b.center().x())
            py = next((ay[p] for p in parts if p in ay), b.center().y())
            dx = (x - px) if x is not None else 0.0
            dy = (y - py) if y is not None else 0.0
        if dx or dy:
            self.ed.transform(QTransform.fromTranslate(dx, dy), "Claude: sposta", shapes)
        return [self._desc(s) for s in shapes]

    def c_set_text(self, id, text=None, size=None, font=None, arc=None, bold=None, italic=None, align=None):
        s = self._find(id)[0]
        if not isinstance(s, TextShape):
            raise RemoteError("non è un testo")
        kw = {k: v for k, v in dict(text=text, size=size, family=font, arc=arc, bold=bold, italic=italic,
                                     align=align).items() if v is not None}
        self.ed.modify(s, "Claude: testo", **kw)
        return self._desc(s)

    def c_set_shape_layer(self, ids, layer):
        self.ed.select(self._find(ids))
        self.ed.set_layer(self._layer(layer))
        return [self._desc(s) for s in self.ed.selection]

    def c_arrange(self, action, ids=None, value=None):
        """action: group | ungroup | weld | union | difference | intersection | xor | align_left/right/top/bottom/
        hcenter/vcenter/center | distribute_h | distribute_v | flip_h | flip_v | to_path | break_apart |
        lock | unlock | duplicate | bring_front | send_back | center_on_bed"""
        self.ed.select(self._find(ids))
        e = self.ed
        a = action
        simple = {"group": e.group, "ungroup": e.ungroup, "weld": e.weld, "to_path": e.convert_to_path,
                  "break_apart": e.break_apart, "duplicate": e.duplicate, "flip_h": lambda: e.flip(True),
                  "flip_v": lambda: e.flip(False), "lock": lambda: e.lock(True), "unlock": lambda: e.lock(False),
                  "bring_front": lambda: e.order("front"), "send_back": lambda: e.order("back"),
                  "distribute_h": lambda: e.distribute("h", "gap"), "distribute_v": lambda: e.distribute("v", "gap")}
        if a in simple:
            simple[a]()
        elif a in ("union", "difference", "intersection", "xor"):
            e.boolean(a)
        elif a.startswith("align_"):
            e.align(a[6:])
        elif a == "center_on_bed":
            p = self.win.profile
            e.move_to(4, QRectF(0, 0, p.bed_x, p.bed_y))
        else:
            raise RemoteError(f"azione sconosciuta: {a}")
        return [self._desc(s) for s in e.selection]

    def c_offset(self, distance, ids=None, direction="out", corner="round", keep_original=True):
        self.ed.select(self._find(ids))
        self.ed.offset(float(distance), direction, corner, keep_original)
        return [self._desc(s) for s in self.ed.selection]

    def c_array(self, kind="grid", ids=None, cols=2, rows=1, gap_x=5.0, gap_y=5.0, count=6, center=None, angle=360.0):
        """kind grid: cols × rows con spazi gap_x/gap_y (mm). kind circular: count copie attorno a center [x, y]."""
        self.ed.select(self._find(ids))
        if kind == "grid":
            self.ed.grid_array(int(cols), int(rows), float(gap_x), float(gap_y))
        else:
            b = self.ed.selection_bounds()
            c = center or [b.center().x(), b.bottom() + b.height()]
            self.ed.circular_array(int(count), (float(c[0]), float(c[1])), 0.0, float(angle))
        return {"selected": len(self.ed.selection)}

    def c_undo(self):
        self.ed.undo()
        return self.ed.undo_label()

    def c_redo(self):
        self.ed.redo()
        return self.ed.redo_label()

    # ------------------------------------------------------------ livelli e materiali
    def c_set_layer(self, index, mode=None, speed_mm_min=None, power_max_pct=None, power_min_pct=None, passes=None,
                    air=None, output=None, interval_mm=None, dpi=None, dither=None, name=None, crosshatch=None,
                    angle=None, kerf_mm=None):
        idx = self._layer(index)
        cs = self.doc.layer(idx)
        if mode is not None and mode not in MODES:
            raise RemoteError(f"mode: {', '.join(MODES)}")
        if power_max_pct is not None and not 0 <= power_max_pct <= 100:
            raise RemoteError("potenza tra 0 e 100%")
        vals = dict(mode=mode, speed=speed_mm_min, power_max=power_max_pct, power_min=power_min_pct, passes=passes,
                    air=air, output=output, interval=interval_mm, dpi=dpi, dither=dither, name=name,
                    crosshatch=crosshatch, angle=angle, kerf=kerf_mm)
        vals = {k: v for k, v in vals.items() if v is not None}

        def do():
            for k, v in vals.items():
                setattr(cs, k, v)
        self.ed.run("Claude: livello", do)
        return [l for l in self.c_list_layers() if l["index"] == idx]

    def c_list_materials(self, query=""):
        q = query.lower().split()
        out = []
        for m in materials.library():
            hay = f"{m.name} {m.operation} {m.thickness:g}".lower()
            if all(t in hay for t in q):
                out.append({"name": m.name, "operation": m.operation, "thickness_mm": m.thickness, "power_pct": m.power,
                            "speed_mm_min": m.speed, "passes": m.passes, "defocus_mm": m.defocus, "note": m.note,
                            "source": m.source})
        return out

    def c_apply_material(self, layer, name, operation=None, thickness_mm=None):
        cands = [m for m in materials.library() if name.lower() in m.name.lower()
                 and (operation is None or m.operation == operation)
                 and (thickness_mm is None or abs(m.thickness - float(thickness_mm)) < 0.01)]
        if not cands:
            raise RemoteError("materiale non trovato: usa list_materials")
        m = cands[0]
        cs = self.doc.layer(self._layer(layer))
        self.ed.run(f"Claude: materiale {m.name}", materials.apply_to_layer, m, cs)
        return {"applied": f"{m.name} {m.label()}", "settings": m.summary()}

    def c_set_variables(self, serial=None, step=None, pad=None, auto=None, csv_path=None):
        if csv_path:
            variables.load_csv(csv_path)
        for k, v in dict(serial=serial, step=step, pad=pad, auto=auto).items():
            if v is not None:
                variables.STATE[k] = v
        variables.changed()
        return {k: v for k, v in variables.STATE.items() if k != "rows"} | {"csv_rows": len(variables.STATE["rows"])}

    # ------------------------------------------------------------ file
    def c_import_file(self, path, x=None, y=None):
        if not os.path.exists(path):
            raise RemoteError(f"file non trovato: {path}")
        n0 = len(self.doc.shapes)
        at = QPointF(x, y) if x is not None and y is not None else None
        self.win.import_files([path], at=at)
        return [self._desc(s) for s in self.doc.shapes[n0:]]

    def c_open_project(self, path):
        if not os.path.exists(path):
            raise RemoteError(f"file non trovato: {path}")
        if self.ed.dirty and self.doc.shapes:
            raise RemoteError("il progetto aperto ha modifiche non salvate: salvalo prima (save_project) "
                              "o chiedi all'utente")
        self.ed.dirty = False
        self.win.file_open(path)
        return self.c_status()

    def c_save_project(self, path=None):
        if path:
            if not path.lower().endswith(".flcut"):
                path = (path[:-5] if path.lower().endswith(".fbrn") else path) + ".flcut"
            self.doc.save(path)
            self.ed.dirty = False
            self.win._add_recent(path)
            self.win._update_title()
            return {"saved": path}
        if not self.doc.path:
            raise RemoteError("il progetto non ha ancora un nome: passa path")
        self.doc.save(self.doc.path)
        self.ed.dirty = False
        self.win._update_title()
        return {"saved": self.doc.path}

    def c_new_project(self):
        if self.ed.dirty and self.doc.shapes:
            raise RemoteError("ci sono modifiche non salvate: salva prima o chiedi all'utente")
        from .core.document import Document

        variables.from_dict(None)
        self.ed.set_document(Document())
        self.win._update_title()
        return self.c_status()

    def c_trace_image(self, id, mode="outline", threshold=None, detail=0.6, smooth=0.5, min_size_mm=0.3, layer=None,
                      keep_image=True):
        from .core import imaging, trace

        img = self._find(id)[0]
        if not isinstance(img, ImageShape):
            raise RemoteError("non è un'immagine")
        pil = self.doc.images.get(img.image_id)
        dark = imaging.adjust(imaging.to_dark(pil), img.brightness, img.contrast, img.gamma)
        path, info = trace.trace(dark, img.w, img.h, mode, threshold, False, detail, smooth, min_size_mm)
        ps = PathShape(path, self._layer(layer if layer is not None else 1))
        ps.set_transform(img.tf)
        if keep_image:
            self.ed.add(ps, "Claude: vettorizza")
        else:
            self.ed.replace([img], [ps], "Claude: vettorizza")
        return self._desc(ps) | info

    # ------------------------------------------------------------ camera
    def c_camera(self, action="snapshot", rectified=False, width=1000, method="target", index=None):
        """action: snapshot (foto attuale; rectified=True = raddrizzata sul piano) | status | calibrate
        (apre la procedura sullo schermo: le conferme le dà l'utente)."""
        panel = getattr(self.win, "camera", None)
        if panel is None:
            raise RemoteError("pannello Camera non disponibile")
        if action == "list":
            items = [{"index": panel.combo.itemData(i), "label": panel.combo.itemText(i)}
                     for i in range(panel.combo.count()) if panel.combo.itemData(i) is not None]
            if not items:
                panel.search()
            return {"cameras": items, "note": "ricerca avviata, riprova fra qualche secondo" if not items else ""}
        if action == "open":
            if index is None:
                raise RemoteError("serve index (vedi action=list)")
            i = panel.combo.findData(int(index))
            if i < 0:
                raise RemoteError("camera non trovata: usa action=list")
            panel.combo.setCurrentIndex(i)
            panel.on_select(i)
            return {"camera_open": panel.src is not None}
        src = panel.src
        if action == "status":
            m = panel.model
            return {"camera_open": src is not None, "frame_size": list(src.size) if src is not None else None,
                    "calibrated": m is not None,
                    "precision_mm": None if m is None else m.rms_mm,
                    "visible_area_mm": None if m is None or m.valid is None else [round(v, 1) for v in m.valid],
                    "method": (panel.saved or {}).get("method") if m is not None else None,
                    "calibration_running": panel.autocam is not None,
                    "progress": f"{panel.cal_bar.value()}/{panel.cal_bar.maximum()}" if panel.cal_bar.isVisible() else None,
                    "message": panel.cal_text.text() or panel.state.text()}
        if src is None:
            raise RemoteError("nessuna camera aperta: scegline una nella scheda Camera")
        if action == "calibrate":
            idx = panel.method.findData(method)
            if idx >= 0:
                panel.method.setCurrentIndex(idx)
            QTimer.singleShot(100, panel.calibrate)
            return {"status": "procedura aperta sullo schermo: l'utente deve confermare (cartone, occhiali, aspirazione)"}
        if action != "snapshot":
            raise RemoteError("action: snapshot | status | calibrate")
        frame = src.get(after=0, timeout=3)
        if frame is None:
            raise RemoteError("la camera non manda immagini")
        if rectified:
            if panel.model is None:
                raise RemoteError("camera non ancora calibrata")
            frame = panel.model.rectify(frame, 2.0)
        import cv2

        h, w = frame.shape[:2]
        width = int(max(200, min(1600, width)))
        if w > width:
            frame = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", frame)
        return {"png_base64": base64.b64encode(buf.tobytes()).decode("ascii"), "width": frame.shape[1],
                "height": frame.shape[0], "original_size": [w, h], "rectified": bool(rectified)}

    # ------------------------------------------------------------ lavoro e macchina
    def c_estimate_job(self, only_selection=False):
        self.win.laser.only_sel.setChecked(bool(only_selection))
        job = self.win.build_job(show=True)
        if job is None:
            raise RemoteError("non riesco a preparare il lavoro (vedi lo schermo)")
        b = job.bounds
        return {"seconds": round(job.seconds), "lines": len(job.lines),
                "bounds_mm": [round(b.left(), 2), round(b.top(), 2), round(b.width(), 2), round(b.height(), 2)] if b else None,
                "warnings": job.warnings,
                "layers": [{"name": l.name, "mode": l.mode, "items": l.items, "cut_m": round(l.cut_mm / 1000, 3)} for l in job.layers]}

    def c_save_gcode(self, path, only_selection=False):
        self.win.laser.only_sel.setChecked(bool(only_selection))
        job = self.win.build_job(show=True)
        if job is None or not job.lines:
            raise RemoteError("lavoro vuoto")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(job.lines) + "\n")
        return {"saved": path, "lines": len(job.lines), "seconds": round(job.seconds)}

    def c_machine(self, action, x=None, y=None, laser=False, feed=3000.0):
        """action: setting (x = numero, y = valore; solo $27 ritorno dopo homing, $24/$25 velocità homing, $1) |
        console (ultime righe con la scheda) | connect | disconnect | home | unlock | goto (x, y in mm sul piano) | frame (laser=True per il puntino) |
        pause | resume | stop | air_on | air_off | start_job (apre la conferma sullo schermo: NON parte da solo)"""
        w, ctl = self.win, self.win.ctl
        if action == "setting":
            # solo impostazioni che non possono far partire il laser o rompere la meccanica
            allowed = {27: (0.5, 10.0), 24: (25, 2000), 25: (200, 6000), 1: (0, 255)}
            n = int(x) if x is not None else None
            if n not in allowed or y is None or not allowed[n][0] <= float(y) <= allowed[n][1]:
                raise RemoteError(f"impostazione non consentita da remoto (consentite: {sorted(allowed)})")
            if ctl.job_active:
                raise RemoteError("c'è un lavoro in corso")
            ctl.write_setting(n, f"{float(y):g}")
            QTimer.singleShot(400, lambda: ctl.send_line("$$"))
            return {"written": f"${n}={float(y):g}", "note": "rileggo le impostazioni ($$): verifica con action=console"}
        if action == "console":
            return [f"{t} {d} {l}" for t, d, l in list(self.console)[-60:]]
        if action == "connect":
            if not ctl.connected:
                w.toggle_connection()
            return {"connected": ctl.connected}
        if action == "disconnect":
            if ctl.connected and not ctl.job_active:
                w.toggle_connection()
            return {"connected": ctl.connected}
        if not ctl.connected:
            raise RemoteError("la macchina non è connessa: usa machine(action='connect')")
        if action == "stop":
            ctl.stop_job()
        elif action == "pause":
            ctl.feed_hold()
        elif action == "resume":
            ctl.resume()
        elif action in ("home", "unlock", "goto", "frame", "air_on", "air_off", "start_job") and ctl.job_active:
            raise RemoteError("c'è un lavoro in corso")
        elif action == "home":
            ctl.home()
        elif action == "unlock":
            ctl.unlock()
        elif action == "goto":
            w.goto_bed(float(x), float(y))
        elif action == "frame":
            w.frame_job("box_laser" if laser else "box")
        elif action in ("air_on", "air_off"):
            w.laser.b_air.setChecked(action == "air_on")
        elif action == "start_job":
            # mai partire da soli: la conferma (occhiali, materiale, aria) la dà una persona sullo schermo
            QTimer.singleShot(100, w.start_job)
            return {"status": "conferma richiesta sullo schermo di FreeLaserCut: il lavoro parte solo se l'utente "
                              "preme Avvia nella finestra di conferma"}
        else:
            raise RemoteError(f"azione sconosciuta: {action}")
        return {"done": action, "state": (ctl.last_status or {}).get("state")}


def stop(server):
    try:
        info = read_info()
        if info and info.get("pid") == os.getpid():
            os.remove(info_path())
    except OSError:
        pass
