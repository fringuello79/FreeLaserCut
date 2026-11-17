# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: progetto per xTool Studio (file `.xs`), per le macchine xTool che lavorano solo con il loro programma
(xTool M2: niente GRBL, nessun programma di terzi può mandarle un lavoro).

FreeLaserCut non comanda la macchina: scrive un progetto con il disegno e con potenza, velocità e passate già
impostate; lo si apre in xTool Studio e il lavoro parte da lì.

Il formato è quello che xTool Studio 1.10.15 salva per la M2 (codice `JS002`): uno zip di JSON in chiaro,
«xcs-workspace-v2». Ricavato da due progetti salvati da Ale il 17/11/2026 e provato riaprendo in xTool Studio un
file scritto da noi:
- `project.json`, `meta/persistence-meta.json`, `.format` (= `v2`);
- `canvases/<id>.json` (livelli per colore) e `canvases/<id>/displays-0.json` (gli oggetti, in **mm**, origine in
  alto a sinistra, Y in giù; matrice `transform` = [a, b, c, d, tx, ty]: x = a·u + c·v + tx, y = b·u + d·v + ty);
- `profiles.json`: un profilo di partenza per tipo di lavorazione (`VECTOR_ENGRAVING` = «Incisione Linea»,
  `FILL_VECTOR_ENGRAVING` = «Incisione», `VECTOR_CUTTING` = «Taglia», `BITMAP_ENGRAVING` = foto), con `power` in %,
  `speed` in mm/s, `repeat` = passate;
- `devices/device-JS002-1.json`: i collegamenti (`bindings`) oggetti → profilo; i valori scelti stanno in una
  `patch` (`overrides`) legata al collegamento; quelli con `shadowOf` sono gli altri tipi tenuti pronti;
- `resources/<sha256>.png` + `.meta.json` per le foto, `resources/project-cover.png` per l'anteprima.

Che cosa scriviamo: ogni forma diventa un `PATH` con il contorno già in mm sulla tela (matrice identità), che è il
caso più semplice fra quelli che xTool Studio stesso salva; ogni foto un `BITMAP`.
"""
import hashlib
import io
import json
import math
import secrets
import time
import uuid
import zipfile

from PySide6.QtGui import QPainterPath

from .document import LAYER_COLORS, ImageShape

DEVICE_CODE = "JS002"
DEVICE_NAME = "M2"
BED = (426.0, 320.0)  # mm, moduli da 10 e 20 W (FAQ ufficiale xTool M2)
LASERS = (10, 20, 40)  # W; nei file visti c'è solo il 10 («laser_blue_10W»): 20 e 40 seguono lo stesso nome
APP_VERSION = "1.10.15"  # versione di xTool Studio di cui riproduciamo il formato
TOOL_LAYER = 30

LINE, FILL, CUT, PHOTO = "VECTOR_ENGRAVING", "FILL_VECTOR_ENGRAVING", "VECTOR_CUTTING", "BITMAP_ENGRAVING"


def _base_values(kind, laser):
    """Valori di partenza di xTool Studio per la M2 (dai progetti salvati)."""
    common = {"power": 1, "repeat": 1, "laser": laser, "processHead": "LASER",
              "powerCutoffType": "FOLLOW_ACTUALLY_POWER"}
    if kind == LINE:
        return {**common, "speed": 20, "kerfDistance": 0, "enableKerf": False, "powerCutoffValue": 3, "airPump": 15}
    if kind == FILL:
        return {**common, "speed": 80, "density": 100, "dpiX": 254, "dpiY": 254, "needGapNumDensity": True,
                "bitmapScanMode": "zMode", "scanAngle": 0, "angleType": 2, "crossAngle": False,
                "outlineTrace": False, "powerCutoffValue": 3, "airPump": 15, "ramp": False, "ramp_length": 0.5,
                "ramp_min_power": 1, "ramp_outer_edge": False, "fill_type": "regular",
                "offset_fill_direction": "IN_TO_OUT"}
    if kind == CUT:
        return {**common, "speed": 16, "cuttingDrop": False, "sinkingMethod": "one", "firstCuttingDropValue": 1,
                "cuttingDropValue": 1, "descentIntervalDescent": 1, "descentPerStep": 1, "enableBreakPoint": False,
                "breakPointGenMode": "auto", "breakPointSize": 0.5, "breakPointMode": "count",
                "breakPointCount": 2, "breakPointDistance": 100, "breakPointPower": 0, "kerfDistance": 0,
                "enableKerf": False, "enableOverCut": False, "overCutDistance": 0.5, "powerCutoffValue": 15,
                "airPump": 100}
    return {**common, "speed": 80, "density": 100, "bitmapScanMode": "zMode", "bitmapMode": "grayscale",
            "dpiX": 254, "dpiY": 254, "powerCutoffValue": 3, "airPump": 15}


def _num(v, nd=6):
    v = round(float(v), nd)
    return int(v) if v == int(v) else v


def kind_of(cs, cut_layers=None):
    """Tipo di lavorazione di xTool Studio per un livello di FreeLaserCut. Un livello in modalità Linea è un taglio
    («Taglia») se è fra `cut_layers`; senza indicazione, se ha più di una passata, ponticelli o compensazione del
    taglio; altrimenti è «Incisione Linea»."""
    if cs.mode == "image":
        return PHOTO
    if cs.mode in ("fill", "offset_fill"):
        return FILL
    if cut_layers is not None:
        return CUT if cs.index in cut_layers else LINE
    return CUT if (cs.passes > 1 or cs.tabs or abs(cs.kerf) > 1e-9) else LINE


def layer_values(cs, kind, laser):
    """I parametri del livello di FreeLaserCut con i nomi e le unità di xTool Studio."""
    v = _base_values(kind, laser)
    v["power"] = _num(min(max(cs.power_max, 1.0), 100.0), 1)
    v["speed"] = _num(max(cs.speed / 60.0, 1.0), 2)  # mm/min -> mm/s
    v["repeat"] = max(1, int(cs.passes))
    if kind == FILL:
        step = max(cs.interval, 0.01)
        v["density"] = _num(10.0 / step, 2)  # righe per cm
        v["dpiX"] = v["dpiY"] = _num(25.4 / step, 2)
        v["scanAngle"] = _num(cs.angle, 2)
        v["crossAngle"] = bool(cs.crosshatch)
    elif kind == PHOTO:
        v["dpiX"] = v["dpiY"] = _num(cs.dpi, 2)
        v["density"] = _num(cs.dpi / 2.54, 2)
    elif kind == CUT:
        if cs.tabs:
            v.update(enableBreakPoint=True, breakPointSize=_num(cs.tab_size, 2), breakPointMode="count",
                     breakPointCount=max(1, int(cs.tab_count)))
    if kind in (LINE, CUT) and abs(cs.kerf) > 1e-9:
        v.update(enableKerf=True, kerfDistance=_num(cs.kerf, 3))
    return v


# ------------------------------------------------------------------ tracciati
def _subpaths(qp, X, Y):
    """QPainterPath (mm del piano) -> [[inizio, [("L", p) | ("C", c1, c2, p)], chiuso]] in mm della tela."""
    subs, cur, i, n = [], None, 0, qp.elementCount()
    while i < n:
        e = qp.elementAt(i)
        t = e.type
        if t == QPainterPath.ElementType.MoveToElement:
            cur = [(X(e.x), Y(e.y)), [], False]
            subs.append(cur)
            i += 1
        elif t == QPainterPath.ElementType.LineToElement:
            cur[1].append(("L", (X(e.x), Y(e.y))))
            i += 1
        elif t == QPainterPath.ElementType.CurveToElement:
            e2, e3 = qp.elementAt(i + 1), qp.elementAt(i + 2)
            cur[1].append(("C", (X(e.x), Y(e.y)), (X(e2.x), Y(e2.y)), (X(e3.x), Y(e3.y))))
            i += 3
        else:
            i += 1
    out = []
    for start, segs, _ in subs:
        if not segs:
            continue
        end = segs[-1][-1]
        closed = math.hypot(end[0] - start[0], end[1] - start[1]) < 1e-6 and len(segs) >= 2
        out.append([start, segs, closed])
    return out


def _flat(sub, steps=8):
    pts, prev = [sub[0]], sub[0]
    for seg in sub[1]:
        if seg[0] == "L":
            pts.append(seg[1])
        else:
            _, c1, c2, p = seg
            for k in range(1, steps + 1):
                t = k / steps
                a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
                pts.append((a * prev[0] + b * c1[0] + c * c2[0] + d * p[0], a * prev[1] + b * c1[1] + c * c2[1] + d * p[1]))
        prev = seg[-1]
    return pts


def _area(pts):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2.0


def _inside(pt, poly):
    x, y = pt
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def _reversed(sub):
    start, segs, closed = sub
    pts = [start] + [s[-1] for s in segs]
    out = []
    for k in range(len(segs) - 1, -1, -1):
        s = segs[k]
        out.append(("L", pts[k]) if s[0] == "L" else ("C", s[2], s[1], pts[k]))
    return [pts[-1], out, closed]


def orient(subs):
    """Contorni esterni in un verso e buchi nell'altro, così il riempimento «nonzero» di xTool Studio lascia vuoti i
    buchi come il pari/dispari di FreeLaserCut (una «O» resta un anello)."""
    flats = [_flat(s) for s in subs]
    out = []
    for i, s in enumerate(subs):
        if not s[2]:
            out.append(s)
            continue
        depth = sum(1 for j, f in enumerate(flats) if j != i and subs[j][2] and _inside(flats[i][0], f))
        want_positive = depth % 2 == 0
        out.append(s if (_area(flats[i]) > 0) == want_positive else _reversed(s))
    return out


def d_path(subs):
    parts = []
    for start, segs, closed in subs:
        parts.append(f"M{_num(start[0], 4)} {_num(start[1], 4)}")
        for s in segs:
            if s[0] == "L":
                parts.append(f"L{_num(s[1][0], 4)} {_num(s[1][1], 4)}")
            else:
                parts.append("C" + " ".join(f"{_num(p[0], 4)} {_num(p[1], 4)}" for p in s[1:]))
        if closed:
            parts.append("Z")
    return "".join(parts)


def _bounds(subs):
    pts = [p for s in subs for p in _flat(s)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _display_common(kind, x, y, w, h, color, z):
    return {
        "id": str(uuid.uuid4()), "name": None, "type": kind, "x": _num(x), "y": _num(y), "angle": 0,
        "scale": {"x": 1, "y": 1}, "skew": {"x": 0, "y": 0}, "pivot": {"x": 0, "y": 0},
        "localSkew": {"x": 0, "y": 0}, "offsetX": 0, "offsetY": 0, "lockRatio": True, "isClosePath": False,
        "zOrder": z, "groupTags": [], "groupTag": str(uuid.uuid4()), "layerTag": color, "layerColor": color,
        "visible": True, "originColor": "#000000", "enableTransform": True, "visibleState": True,
        "lockState": False, "resourceOrigin": "", "customData": {"tabBreaks": {}, "startPoint": {}},
        "rootComponentId": "", "minCanvasVersion": "0.0.0", "alpha": 1,
        "fill": {"paintType": "color", "visible": False, "color": 0, "alpha": 1},
        "stroke": {"paintType": "color", "visible": False, "color": 0, "alpha": 1, "width": 1, "cap": "butt",
                   "join": "miter", "miterLimit": 4, "alignment": 0.5},
        "effects": [], "transform": [1, 0, 0, 1, 0, 0], "width": _num(w), "height": _num(h), "isFill": False,
    }


def path_display(subs, color, z, filled):
    x0, y0, x1, y1 = _bounds(subs)
    d = _display_common("PATH", x0, y0, x1 - x0, y1 - y0, color, z)
    d["isClosePath"] = all(s[2] for s in subs)
    d["isFill"] = bool(filled)
    d["fill"]["visible"] = bool(filled)
    d["stroke"]["visible"] = not filled
    d.update({"lineColor": 16421416, "fillColor": "#f9932b", "points": [], "fillRule": "nonzero", "graphicX": 0,
              "graphicY": 0, "isCompoundPath": len(subs) > 1, "pathCornerData": None, "dPath": d_path(subs)})
    return d


# ------------------------------------------------------------------ foto
def _photo_png(pil, m):
    """Foto e matrice pixel -> tela. Se la foto è dritta (solo scala e posizione) resta com'è; se è ruotata o
    specchiata viene ridisegnata dritta nel suo ingombro, alla stessa finezza (fuori bianco).
    -> (bytes PNG, larghezza px, altezza px, mm per pixel in x, in y, x, y sulla tela)."""
    from PIL import Image

    a, b, c, d, tx, ty = m
    W, H = pil.size
    if abs(b) < 1e-9 and abs(c) < 1e-9 and a > 0 and d > 0:
        out, sx, sy, x, y = pil, a, d, tx, ty
    else:
        corners = [(a * u + c * v + tx, b * u + d * v + ty) for u, v in ((0, 0), (W, 0), (W, H), (0, H))]
        x, y = min(p[0] for p in corners), min(p[1] for p in corners)
        s = math.sqrt(abs(a * d - b * c))  # mm per pixel
        ow = max(1, int(round((max(p[0] for p in corners) - x) / s)))
        oh = max(1, int(round((max(p[1] for p in corners) - y) / s)))
        det = a * d - b * c
        ia, ic, ib, id_ = d / det, -c / det, -b / det, a / det  # inversa: tela -> pixel
        # pixel di uscita (U, V) -> tela (x + U·s, y + V·s) -> pixel della foto
        ox, oy = x - tx, y - ty
        coeffs = (ia * s, ic * s, ia * ox + ic * oy, ib * s, id_ * s, ib * ox + id_ * oy)
        out = pil.convert("RGBA").transform((ow, oh), Image.AFFINE, coeffs, resample=Image.BICUBIC,
                                            fillcolor=(255, 255, 255, 0))
        sx = sy = s
    if "A" in out.getbands() or out.mode == "P":
        # le parti trasparenti (fuori dalla sagoma del ritaglio, attorno a una foto ruotata) diventano bianche = non
        # incise: così non dipende da come xTool Studio tratta la trasparenza
        rgba = out.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        out = Image.alpha_composite(white, rgba).convert("L" if pil.mode in ("L", "LA", "1") else "RGB")
    elif out.mode not in ("L", "RGB"):
        out = out.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue(), out.size[0], out.size[1], sx, sy, x, y


def bitmap_display(name, pw, ph, sx, sy, x, y, color, z, sha):
    d = _display_common("BITMAP", x, y, pw * sx, ph * sy, color, z)
    d.update({"scale": {"x": _num(sx), "y": _num(sy)}, "offsetX": _num(x), "offsetY": _num(y),
              "transform": [_num(sx), 0, 0, _num(sy), _num(x), _num(y)], "isFill": True})
    d["customData"] = {"from": {"xtool_trace_id": "sha256:" + sha}, "tabBreaks": {}, "startPoint": {}}
    d.update({
        "warpLocalOffset": None, "filterList": [], "grayValue": [0, 255], "sharpness": 50, "brightness": 0,
        "contrast": 0, "saturation": 0, "temperature": 0, "tone": 0, "colorInverted": False,
        "colorInvertedFillTransparent": False, "colorInvertedTransparentColor": "black",
        "filterAttrsMap": {"emboss": {"strength": 5}, "halftone": {"radius": 4, "angle": 45},
                           "binary": {"threshold": 128}, "sketch": {"strength": 2}, "dot": {"angle": 45, "scale": 14}},
        "mask": None, "originWidth": pw, "originHeight": ph, "modifyData": {}, "currentUrl": "",
        "dpi": {"dpiX": _num(25.4 / sx), "dpiY": _num(25.4 / sy)}, "isGray": False, "originAutoAdjust": None,
        "autoStrength": 0, "format": "png", "resourcePath": name, "opacity": 1, "filterList_V2": [],
    })
    return d


# ------------------------------------------------------------------ progetto
def _rid(prefix):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return prefix + ":" + "".join(secrets.choice(alphabet) for _ in range(12))


def _cover(displays, bed):
    from PIL import Image, ImageDraw

    k = 400.0 / bed[0]
    img = Image.new("RGBA", (400, max(1, int(bed[1] * k))), (255, 255, 255, 0))
    dr = ImageDraw.Draw(img)
    for d in displays:
        if d["type"] == "BITMAP":
            dr.rectangle([d["x"] * k, d["y"] * k, (d["x"] + d["width"]) * k, (d["y"] + d["height"]) * k],
                         outline=d["layerColor"], fill=(200, 200, 200, 255))
        else:
            for sub in d["_subs"]:
                pts = [(p[0] * k, p[1] * k) for p in _flat(sub)]
                if len(pts) >= 2:
                    dr.line(pts, fill=d["layerColor"], width=1)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build(doc, shapes=None, bed=BED, laser_w=10, cut_layers=None, name="FreeLaserCut", app_version=""):
    """-> ({nome del file nello zip: bytes}, resoconto). Il piano di FreeLaserCut (origine in basso a sinistra, Y in
    su) va sulla tela di xTool Studio (origine in alto a sinistra, Y in giù) con lo stesso angolo in basso a sinistra:
    quello che sta a (x, y) dal basso finisce a (x, altezza della M2 − y).
    resoconto: {"layers": [(livello, tipo, n. oggetti)], "skipped": [...], "outside": n. oggetti fuori dall'area}."""
    from . import photo_clip

    if laser_w not in LASERS:
        raise ValueError("laser_w")
    laser = f"laser_blue_{int(laser_w)}W"
    shapes = list(doc.shapes if shapes is None else shapes)
    bw, bh = float(bed[0]), float(bed[1])

    def X(x):
        return x

    def Y(y):
        return bh - y

    files, displays, per_layer = {}, [], {}
    report = {"layers": [], "skipped": [], "outside": 0}
    z = 0
    for s in shapes:
        if s.hidden:
            continue
        for leaf, tf in s.leaves():
            if leaf.hidden:
                continue
            cs = doc.layer(leaf.layer)
            if leaf.layer >= TOOL_LAYER or not cs.output:
                report["skipped"].append((leaf.layer, leaf.kind))
                continue
            color = LAYER_COLORS[leaf.layer % len(LAYER_COLORS)].lower()
            z += 1
            if isinstance(leaf, ImageShape):
                pil = doc.images.get(leaf.image_id)
                if pil is None or cs.mode != "image":
                    report["skipped"].append((leaf.layer, leaf.kind))
                    continue
                pil = photo_clip.clipped_image(pil, leaf)
                W, H = pil.size
                # pixel (u, v) -> mm locali della foto (u·w/W, h − v·h/H) -> piano (tf) -> tela (x, bh − y)
                kx, ky = leaf.w / W, leaf.h / H
                a = tf.m11() * kx
                b = -(tf.m12() * kx)
                c = -tf.m21() * ky
                d = tf.m22() * ky
                tx = tf.m21() * leaf.h + tf.dx()
                ty = bh - (tf.m22() * leaf.h + tf.dy())
                png, pw, ph, sx, sy, x, y = _photo_png(pil, (a, b, c, d, tx, ty))
                sha = hashlib.sha256(png).hexdigest()
                res = f"resources/{sha}.png"
                files[res] = png
                files[res + ".meta.json"] = {"ref": res, "metadata": {"kind": "image", "source": {
                    "type": "workspace", "value": f"{sha}.png"}}}
                disp = bitmap_display(res, pw, ph, sx, sy, x, y, color, z, sha)
            else:
                if cs.mode == "image":
                    report["skipped"].append((leaf.layer, leaf.kind))
                    continue
                subs = _subpaths(tf.map(leaf.local_path()), X, Y)
                if not subs:
                    continue
                filled = cs.mode in ("fill", "offset_fill")
                subs = orient(subs)
                disp = path_display(subs, color, z, filled)
                disp["_subs"] = subs
            if (disp["x"] < -1e-6 or disp["y"] < -1e-6 or disp["x"] + disp["width"] > bw + 1e-6
                    or disp["y"] + disp["height"] > bh + 1e-6):
                report["outside"] += 1
            displays.append(disp)
            per_layer.setdefault(leaf.layer, []).append(disp["id"])

    canvas_id, project_id = str(uuid.uuid4()), str(uuid.uuid4())
    base = {k: _rid("profile") for k in (LINE, FILL, CUT, PHOTO)}
    profiles = {pid: {"id": pid, "processingType": k, "values": _base_values(k, laser)} for k, pid in base.items()}
    patches, bindings = {}, []
    order = [cs.index for cs in doc.used_layers() if cs.index in per_layer]
    for idx in order:
        cs = doc.layer(idx)
        kind = kind_of(cs, cut_layers)
        patch = _rid("patch")
        patches[patch] = {"id": patch, "profileId": base[kind], "source": "custom",
                          "overrides": layer_values(cs, kind, laser)}
        main = _rid("binding")
        bindings.append({"bindingId": main, "canvasId": canvas_id, "mode": "LASER_PLANE",
                         "baseProfileId": base[kind], "displayIds": per_layer[idx], "patchIds": [patch]})
        if kind != PHOTO:  # gli altri tipi restano pronti, come fa xTool Studio
            for other in (LINE, FILL, CUT):
                if other != kind:
                    bindings.append({"bindingId": _rid("binding"), "canvasId": canvas_id, "mode": "LASER_PLANE",
                                     "baseProfileId": base[other], "displayIds": [], "shadowOf": main})
        report["layers"].append((idx, kind, len(per_layer[idx])))

    now = int(time.time() * 1000)
    colors = []
    for d in displays:
        if d["layerTag"] not in colors:
            colors.append(d["layerTag"])
    cover = _cover(displays, (bw, bh))
    for d in displays:
        d.pop("_subs", None)
    files["meta/persistence-meta.json"] = {"schemaVersion": "2.0.0", "protocol": "xcs-workspace-v2"}
    files["project.json"] = {
        "__v2__": True, "version": "2.0.0",
        "schemaMeta": {"schemaVersion": "2.1.0", "format": "directory", "migratedFrom": "1.0", "migratedAt": now},
        "projectId": project_id, "projectTraceID": project_id, "projectName": name,
        "activeCanvasId": canvas_id, "activeDeviceId": f"{DEVICE_CODE}-1",
        "versionInfo": {"source": "pc", "appVersion": APP_VERSION, "savedAt": now,
                        "ua": f"FreeLaserCut/{app_version}".rstrip("/"), "minRequiredVersion": "2.6.0",
                        "appMinRequiredVersion": "", "webMinRequiredVersion": ""},
        "created": now, "modify": now,
        "modules": {"canvases": [canvas_id], "devices": ["default", f"{DEVICE_CODE}-1"]},
        "cover": "resources/project-cover.png", "customProjectData": {"projectTraceID": project_id},
    }
    files["profiles.json"] = {"profiles": profiles}
    files[f"canvases/{canvas_id}.json"] = {
        "id": canvas_id, "title": "{panel}1", "hidden": False,
        "layerData": {c: {"name": c.upper(), "order": i + 1, "visible": True} for i, c in enumerate(colors)},
        "groupData": {}, "batchData": {"entryType": "BATCH_TEMPLATE", "bindings": []},
        "extendInfo": {"version": "2.16.5", "minCanvasVersion": "0.0.0", "displayProcessConfigMap": {},
                       "rulerPluginData": {"rulerGuide": []}, "type": "2d"},
        "chunkLayout": {"displayCount": len(displays), "chunkCount": 1, "chunkIndexes": [0]},
    }
    files[f"canvases/{canvas_id}/displays-0.json"] = {"canvasId": canvas_id, "chunkIndex": 0, "displays": displays}
    empty_mode = {"ignoredDisplayIds": [], "data": {}, "profileRefs": [], "patches": {}, "bindings": []}
    files["devices/device-default.json"] = {
        "id": "default", "deviceCode": "", "extId": "", "extName": "",
        "processing": {canvas_id: {"id": canvas_id, "activeMode": "LASER_PLANE", "modes": {"LASER_PLANE": empty_mode}}}}
    files[f"devices/device-{DEVICE_CODE}-1.json"] = {
        "id": f"{DEVICE_CODE}-1", "deviceCode": DEVICE_CODE, "extId": DEVICE_CODE, "extName": DEVICE_NAME,
        "power": [int(laser_w)],
        "processing": {canvas_id: {"id": canvas_id, "activeMode": "LASER_PLANE", "modes": {"LASER_PLANE": {
            "ignoredDisplayIds": [], "data": {"material": 0}, "profileRefs": list(base.values()),
            "patches": patches, "bindings": bindings}}}}}
    files["resources/project-cover.png.meta.json"] = {"ref": "resources/project-cover.png", "metadata": {
        "kind": "image", "source": {"type": "workspace", "value": "project-cover.png"}, "mimeType": "image/png"}}
    files["resources/project-cover.png"] = cover
    files[".format"] = b"v2"
    return files, report


def export_xs(doc, path, **kw):
    """Scrive il progetto `.xs`. Il file si apre in scrittura solo quando tutto il contenuto è pronto."""
    files, report = build(doc, **kw)
    order = ["meta/persistence-meta.json", "project.json", "profiles.json"]
    order += sorted(n for n in files if n.startswith("canvases/"))
    order += sorted(n for n in files if n.startswith("devices/"))
    order += sorted(n for n in files if n.startswith("resources/"))
    order.append(".format")
    blobs = [(n, files[n] if isinstance(files[n], bytes) else json.dumps(files[n], ensure_ascii=False, indent=2).encode("utf-8"))
             for n in order]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in blobs:
            z.writestr(n, data)
    return report
