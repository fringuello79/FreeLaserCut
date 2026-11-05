# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Resa 3D fatta in casa (numpy + OpenCV), senza scheda grafica né OpenGL: funziona uguale su ogni PC, anche
vecchio o senza driver aggiornati, e si collauda da sola.

Z-buffer per punto: triangoli (rasterizzati a blocchi, tutti insieme con numpy) e facce piane con i fori (riempite
con OpenCV, profondità dal piano della faccia). Luce con ombra morbida sul pavimento, legno con le venature sulle facce
e bordi scuri (come il compensato tagliato al laser), antialiasing con la resa a grandezza doppia.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

LIGHT = np.array([0.35, -0.60, 0.75])  # luce principale: in alto, davanti a destra (fa anche l'ombra)
LIGHT = LIGHT / np.linalg.norm(LIGHT)
BG_TOP = np.array([238, 241, 246], np.float32)
BG_BOTTOM = np.array([206, 212, 222], np.float32)
WOOD = np.array([222, 188, 136], np.float32) / 255.0
BURNT = np.array([92, 60, 38], np.float32) / 255.0
CLAY = np.array([198, 192, 184], np.float32) / 255.0


@dataclass
class Scene:
    tris: list = field(default_factory=list)    # [(T,3,3) mondo, (3,) colore 0..1, normali ai vertici (T,3,3) o None]
    caps: list = field(default_factory=list)    # [(anelli [(N,3)], normale (3,), colore (3,), venature: bool)]
    ground: float = 0.0

    def add_tris(self, tri, color, normals=None):
        tri = np.asarray(tri, np.float64).reshape(-1, 3, 3)
        if len(tri):
            self.tris.append((tri, np.asarray(color, np.float32), normals))

    def add_cap(self, rings, normal, color, grain=True):
        self.caps.append(([np.asarray(r, np.float64) for r in rings], np.asarray(normal, np.float64),
                          np.asarray(color, np.float32), grain))

    def points(self):
        pts = [t.reshape(-1, 3) for t, *_ in self.tris] + [r for rings, *_ in self.caps for r in rings]
        return np.vstack(pts) if pts else np.zeros((1, 3))

    def bounds(self):
        p = self.points()
        return p.min(0), p.max(0)


@dataclass
class Camera:
    target: np.ndarray
    yaw: float = -35.0     # gradi, attorno all'asse verticale
    pitch: float = 22.0    # gradi sopra l'orizzonte
    dist: float = 400.0
    fov: float = 32.0

    def basis(self):
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        fwd = np.array([math.cos(p) * math.sin(y), math.cos(p) * math.cos(y), -math.sin(p)])
        right = np.cross(fwd, [0.0, 0.0, 1.0])
        right /= np.linalg.norm(right) + 1e-12
        up = np.cross(right, fwd)
        eye = np.asarray(self.target, np.float64) - fwd * self.dist
        return eye, right, up, fwd


def fit_camera(scene, yaw=-35.0, pitch=22.0):
    lo, hi = scene.bounds()
    c = (lo + hi) / 2
    r = float(np.linalg.norm(hi - lo)) / 2 or 1.0
    return Camera(c, yaw, pitch, r / math.tan(math.radians(32.0) / 2) * 1.12)


def _project(P, eye, right, up, fwd, f, W, H):
    d = P - eye
    xc, yc, zc = d @ right, d @ up, d @ fwd
    zc = np.maximum(zc, 1e-3)
    return W / 2 + f * xc / zc, H / 2 - f * yc / zc, zc


def _shade(n, base, view_dir):
    """Colori con la luce principale, una luce più debole dalla parte di chi guarda (così nessuna faccia verso di noi
    resta buia), un po' di luce ambiente e un riflesso leggero (n verso chi guarda)."""
    diff = 0.72 * np.clip(n @ LIGHT, 0, 1) + 0.38 * np.clip(-(n * view_dir).sum(-1), 0, 1)
    h = LIGHT - view_dir
    h = h / (np.linalg.norm(h, axis=-1, keepdims=True) + 1e-12)
    spec = np.clip((n * h).sum(-1), 0, 1) ** 24
    return np.clip(base * (0.38 + 0.68 * diff)[..., None] + 0.10 * spec[..., None], 0, 1)


def _raster_tris(S, Wd, cols, W, H):
    """Triangoli a schermo (T,3,2), 1/z ai vertici (T,3), colore (T,3) -> candidati (pixel, 1/z, colore)."""
    out_p, out_w, out_c = [], [], []
    if not len(S):
        return out_p, out_w, out_c
    x0 = np.floor(S[:, :, 0].min(1)).astype(np.int64)
    y0 = np.floor(S[:, :, 1].min(1)).astype(np.int64)
    x1 = np.ceil(S[:, :, 0].max(1)).astype(np.int64)
    y1 = np.ceil(S[:, :, 1].max(1)).astype(np.int64)
    vis = (x1 >= 0) & (y1 >= 0) & (x0 < W) & (y0 < H)
    size = np.maximum(x1 - x0, y1 - y0) + 1
    area = (S[:, 1, 0] - S[:, 0, 0]) * (S[:, 2, 1] - S[:, 0, 1]) - (S[:, 2, 0] - S[:, 0, 0]) * (S[:, 1, 1] - S[:, 0, 1])
    vis &= np.abs(area) > 1e-9
    prev = 0
    for B in (2, 4, 8, 16, 32, 64, 128, 256, 1 << 30):
        sel = np.nonzero(vis & (size > prev) & (size <= B))[0]
        prev = B
        if not len(sel):
            continue
        if B > 256:  # triangoli enormi (pochi): uno alla volta, solo dentro lo schermo
            for k in sel:
                bx0, by0 = max(0, x0[k]), max(0, y0[k])
                bx1, by1 = min(W, x1[k] + 1), min(H, y1[k] + 1)
                gy, gx = np.mgrid[by0:by1, bx0:bx1]
                _cands(S[k:k + 1], Wd[k:k + 1], cols[k:k + 1], area[k:k + 1], gx.reshape(1, -1), gy.reshape(1, -1),
                       W, H, out_p, out_w, out_c)
            continue
        oy, ox = np.mgrid[0:B, 0:B]
        ox, oy = ox.reshape(1, -1), oy.reshape(1, -1)
        chunk = max(1, 3_000_000 // (B * B))
        for s0 in range(0, len(sel), chunk):
            k = sel[s0:s0 + chunk]
            _cands(S[k], Wd[k], cols[k], area[k], x0[k, None] + ox, y0[k, None] + oy, W, H, out_p, out_w, out_c)
    return out_p, out_w, out_c


def _cands(S, Wd, cols, area, gx, gy, W, H, out_p, out_w, out_c):
    px, py = gx + 0.5, gy + 0.5
    ax, ay = S[:, 0, 0, None], S[:, 0, 1, None]
    bx, by = S[:, 1, 0, None], S[:, 1, 1, None]
    cx, cy = S[:, 2, 0, None], S[:, 2, 1, None]
    w0 = (bx - px) * (cy - py) - (cx - px) * (by - py)
    w1 = (cx - px) * (ay - py) - (ax - px) * (cy - py)
    w2 = (ax - px) * (by - py) - (bx - px) * (ay - py)
    A = area[:, None]
    l0, l1, l2 = w0 / A, w1 / A, w2 / A
    inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9) & (gx >= 0) & (gy >= 0) & (gx < W) & (gy < H)
    if not inside.any():
        return
    iw = l0 * Wd[:, 0, None] + l1 * Wd[:, 1, None] + l2 * Wd[:, 2, None]
    r, c = np.nonzero(inside)
    out_p.append((gy[r, c] * W + gx[r, c]).astype(np.int64))
    out_w.append(iw[r, c].astype(np.float32))
    if cols.ndim == 3:  # colori ai vertici
        cc = cols[r].astype(np.float32)
        out_c.append(np.clip(cc[:, 0] * l0[r, c, None] + cc[:, 1] * l1[r, c, None] + cc[:, 2] * l2[r, c, None],
                             0, 255).astype(np.uint8))
    else:
        out_c.append(cols[r])


def _grain(P, axis_u, axis_v):
    """Venature del compensato (da coordinate del mondo, quindi ferme sul pezzo): anelli larghi e fibre sottili."""
    u, v = P[:, axis_u], P[:, axis_v]
    rings = np.sin(u * 0.42 + 2.2 * np.sin(v * 0.035) + 0.9 * np.sin(u * 0.05 + v * 0.02))
    fine = np.sin(u * 3.1 + v * 0.13) * 0.5 + np.sin(u * 7.3 - v * 0.2) * 0.25
    return 0.92 + 0.07 * rings + 0.03 * fine


def render(scene, cam, W=640, H=480, ss=2, ground=True, shadow=True):
    """Immagine RGB (H, W, 3) uint8 della scena vista dalla camera."""
    Wr, Hr = int(W * ss), int(H * ss)
    eye, right, up, fwd = cam.basis()
    f = (Hr / 2) / math.tan(math.radians(cam.fov) / 2)
    P_all, W_all, C_all = [], [], []
    shadow_mask = np.zeros((Hr, Wr), np.uint8) if (ground and shadow) else None
    gz = scene.ground

    def to_ground(P):  # ombra: il punto portato sul pavimento lungo la luce
        t = (P[..., 2] - gz) / max(LIGHT[2], 1e-3)
        return P - LIGHT * t[..., None]

    # ---- triangoli
    for tri, color, vn in scene.tris:
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        cen = tri.mean(1)
        vd = cen - eye
        vd /= np.linalg.norm(vd, axis=1, keepdims=True) + 1e-12
        flip = (n * vd).sum(1) > 0  # luce sulle due facce (modelli con normali girate)
        if vn is None:
            n = np.where(flip[:, None], -n, n)
            col = (_shade(n, color[None, :], vd) * 255).astype(np.uint8)
        else:  # superficie liscia: colore calcolato ai vertici e sfumato dentro il triangolo
            vn2 = np.where(flip[:, None, None], -vn, vn)
            vdv = tri - eye
            vdv /= np.linalg.norm(vdv, axis=2, keepdims=True) + 1e-12
            col = (_shade(vn2, color[None, None, :], vdv) * 255).astype(np.uint8)
        sx, sy, zc = _project(tri.reshape(-1, 3), eye, right, up, fwd, f, Wr, Hr)
        front = (zc.reshape(-1, 3) > 1e-2).all(1)
        S = np.stack([sx, sy], -1).reshape(-1, 3, 2)[front]
        Wd = (1.0 / zc.reshape(-1, 3))[front]
        p, w, c = _raster_tris(S, Wd, col[front], Wr, Hr)
        P_all += p
        W_all += w
        C_all += c
        if shadow_mask is not None:
            g = to_ground(tri.reshape(-1, 3))
            gx, gy, gzc = _project(g, eye, right, up, fwd, f, Wr, Hr)
            poly = np.round(np.stack([gx, gy], -1).reshape(-1, 3, 2)).astype(np.int32)
            ok = (gzc.reshape(-1, 3) > 1e-2).all(1) & (np.abs(poly).max((1, 2)) < 1 << 20)
            if ok.any():
                cv2.fillPoly(shadow_mask, list(poly[ok]), 255)
    # ---- facce piane (con i fori)
    for rings, normal, color, grain in scene.caps:
        n = normal / (np.linalg.norm(normal) + 1e-12)
        cen = rings[0].mean(0)
        if np.dot(n, cen - eye) > 0:
            n = -n
        pts = []
        okc = True
        for r in rings:
            sx, sy, zc = _project(r, eye, right, up, fwd, f, Wr, Hr)
            if (zc < 1e-2).any():
                okc = False
                break
            pts.append(np.round(np.stack([sx, sy], -1) * 16).astype(np.int32))
        if not okc:
            continue
        allp = np.vstack(pts) / 16.0
        bx0, by0 = max(0, int(allp[:, 0].min()) - 1), max(0, int(allp[:, 1].min()) - 1)
        bx1, by1 = min(Wr, int(allp[:, 0].max()) + 2), min(Hr, int(allp[:, 1].max()) + 2)
        if bx1 <= bx0 or by1 <= by0:
            continue
        m = np.zeros((by1 - by0, bx1 - bx0), np.uint8)
        off = np.array([bx0 * 16, by0 * 16], np.int32)
        cv2.fillPoly(m, [p - off for p in pts], 1, cv2.LINE_8, 4)  # pari-dispari: i fori restano vuoti
        yy, xx = np.nonzero(m)
        if not len(yy):
            continue
        gx, gy = xx + bx0, yy + by0
        # profondità dal piano: punto = eye + z * raggio
        rx = (gx + 0.5 - Wr / 2) / f
        ry = -(gy + 0.5 - Hr / 2) / f
        ray = rx[:, None] * right + ry[:, None] * up + fwd
        den = ray @ normal
        num = np.dot(cen - eye, normal)
        z = num / np.where(np.abs(den) < 1e-12, 1e-12, den)
        good = z > 1e-2
        gx, gy, z, ray = gx[good], gy[good], z[good], ray[good]
        Pw = eye + ray * z[:, None]
        vd = ray / np.linalg.norm(ray, axis=1, keepdims=True)
        base = np.tile(color, (len(z), 1))
        if grain:
            ax = int(np.argmax(np.abs(n)))
            uv = [k for k in range(3) if k != ax]
            base = base * _grain(Pw, uv[0], uv[1])[:, None]
        col = (_shade(np.tile(n, (len(z), 1)), base, vd) * 255).astype(np.uint8)
        P_all.append(gy * Wr + gx)
        W_all.append((1.0 / z).astype(np.float32))
        C_all.append(col)
        if shadow_mask is not None:
            gpts = [np.round(np.stack(_project(to_ground(r), eye, right, up, fwd, f, Wr, Hr)[:2], -1)).astype(np.int32)
                    for r in rings[:1]]
            if all(np.abs(g).max() < 1 << 20 for g in gpts):
                cv2.fillPoly(shadow_mask, gpts, 255)
    # ---- immagine
    t = np.linspace(0, 1, Hr, dtype=np.float32)[:, None, None]
    img = (BG_TOP * (1 - t) + BG_BOTTOM * t) * np.ones((1, Wr, 1), np.float32)
    if ground:
        _ground(img, scene, eye, right, up, fwd, f, Wr, Hr, shadow_mask, P_all, W_all, C_all)
    img = img.astype(np.uint8).reshape(-1, 3)
    if P_all:
        p = np.concatenate(P_all)
        w = np.concatenate(W_all)
        c = np.concatenate(C_all)
        o = np.lexsort((-w, p))  # per ogni pixel prima il più vicino (1/z più grande)
        p, c = p[o], c[o]
        first = np.ones(len(p), bool)
        first[1:] = p[1:] != p[:-1]
        img[p[first]] = c[first]
    img = img.reshape(Hr, Wr, 3)
    if ss != 1:
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    return img


def _ground(img, scene, eye, right, up, fwd, f, Wr, Hr, shadow_mask, P_all, W_all, C_all):
    """Pavimento chiaro con la griglia leggera e l'ombra morbida della scultura."""
    lo, hi = scene.bounds()
    c = (lo + hi) / 2
    R = float(max(hi[0] - lo[0], hi[1] - lo[1])) * 1.4 + 40
    gz = scene.ground
    gy, gx = np.mgrid[0:Hr, 0:Wr]
    rx = (gx.ravel() + 0.5 - Wr / 2) / f
    ry = -(gy.ravel() + 0.5 - Hr / 2) / f
    ray = rx[:, None] * right + ry[:, None] * up + fwd
    den = ray[:, 2]
    z = (gz - eye[2]) / np.where(np.abs(den) < 1e-12, -1e-12, den)
    P = eye + ray * z[:, None]
    dx, dy = P[:, 0] - c[0], P[:, 1] - c[1]
    on = (z > 1e-2) & (np.abs(dx) < R) & (np.abs(dy) < R)
    if not on.any():
        return
    fade = np.clip(1.0 - np.maximum(np.abs(dx), np.abs(dy)) / R, 0, 1) ** 0.6
    grid = ((np.abs(((P[:, 0] + 1000) % 20) - 10) > 9.6) | (np.abs(((P[:, 1] + 1000) % 20) - 10) > 9.6))
    base = np.where(grid, 0.90, 0.97)
    sh = np.ones(len(z), np.float32)
    if shadow_mask is not None:
        k = max(3, int(Hr / 70) | 1)
        closed = cv2.morphologyEx(shadow_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))  # niente fessure fra i triangoli
        soft = cv2.GaussianBlur(closed, (k * 2 + 1, k * 2 + 1), 0).ravel().astype(np.float32) / 255.0
        sh = 1.0 - 0.38 * soft
    v = (base * sh)
    bg = img.reshape(-1, 3)
    floor = np.array([236, 233, 228], np.float32) * v[:, None]
    mix = fade[:, None]
    col = bg * (1 - mix) + floor * mix
    idx = np.nonzero(on)[0]
    P_all.append(idx.astype(np.int64))
    W_all.append((1.0 / z[idx]).astype(np.float32) * 0.999)
    C_all.append(np.clip(col[idx], 0, 255).astype(np.uint8))


# ==================================================================== scene pronte
PREVIEW_TRIS = 250_000  # oltre, l'anteprima usa un modello semplificato (la scultura si calcola sempre sull'originale)


def _decimate(V, F, limit=PREVIEW_TRIS):
    """Modello alleggerito per l'anteprima: i vertici nella stessa cella di una griglia diventano uno solo."""
    if len(F) <= limit:
        return V, F
    lo = V.min(0)
    span = float(np.ptp(V, axis=0).max()) or 1.0
    for n in (700, 520, 400, 300, 220, 160, 120, 80):
        q = np.floor((V - lo) / (span / n)).astype(np.int64)
        key = (q[:, 0] * (n + 2) + q[:, 1]) * (n + 2) + q[:, 2]
        uk, inv = np.unique(key, return_inverse=True)
        inv = inv.reshape(-1)
        F2 = inv[F]
        F2 = F2[(F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 0] != F2[:, 2])]
        if len(F2) <= limit:
            break
    V2 = np.zeros((len(uk), 3))
    np.add.at(V2, inv, V)
    V2 /= np.bincount(inv, minlength=len(uk))[:, None]
    return V2, F2


def mesh_scene(mesh, color=CLAY, limit=PREVIEW_TRIS):
    sc = Scene()
    V, F = _decimate(mesh.vertices, mesh.faces, limit)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])  # pesate con l'area
    acc = np.zeros_like(V)
    for k in range(3):
        np.add.at(acc, F[:, k], fn)
    vn = acc / (np.linalg.norm(acc, axis=1, keepdims=True) + 1e-12)
    # spigoli vivi (la normale del vertice e quella della faccia molto diverse): lì resta la faccia piatta
    fnu = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
    tv = vn[F]
    sharp = (tv * fnu[:, None, :]).sum(-1) < 0.6
    tv = np.where(sharp[..., None], fnu[:, None, :], tv)
    sc.add_tris(V[F], color, tv)
    sc.ground = float(mesh.vertices[:, 2].min())
    return sc


def sculpture_parts(sculpt):
    """Pezzi in ordine di montaggio, pronti da disegnare: (triangoli dei bordi (T,3,3), [(anelli 3D, normale verso
    fuori)] per le due facce). Li usano sia questa resa sia quella con la scheda grafica."""
    from . import sculpt as S

    t = sculpt.thickness
    out = []
    z1, o1 = np.zeros(1), np.ones(1)
    for pc in sorted(sculpt.pieces, key=lambda p: p.order):
        w0, w1 = S.piece_span(pc, t)
        ax = S.to_world(pc, z1, z1, o1)[0] - S.to_world(pc, z1, z1, z1)[0]
        rings = [np.asarray(x, np.float64) for x in pc.island.rings]
        caps = [([S.to_world(pc, r[:, 0], r[:, 1], np.full(len(r), wv)) for r in rings], ax * sign)
                for wv, sign in ((w0, -1.0), (w1, 1.0))]
        tris = []
        for r in rings:
            a = S.to_world(pc, r[:, 0], r[:, 1], np.full(len(r), w0))
            b = S.to_world(pc, r[:, 0], r[:, 1], np.full(len(r), w1))
            a2, b2 = np.roll(a, -1, 0), np.roll(b, -1, 0)
            tris.append(np.stack([a, a2, b2], 1))
            tris.append(np.stack([a, b2, b], 1))
        out.append((np.concatenate(tris) if tris else np.zeros((0, 3, 3)), caps))
    return out


def sculpture_ground(sculpt, parts=None):
    """Quota del pavimento: sotto il pezzo più basso (una punta troppo piccola per essere tagliata non lascia sospeso
    nulla)."""
    parts = sculpture_parts(sculpt) if parts is None else parts
    zs = [r[:, 2].min() for _t, caps in parts for rings, _n in caps for r in rings[:1] if len(r)]
    return float(min(zs)) if zs else float(sculpt.mesh.vertices[:, 2].min())


def sculpture_scene(sculpt, upto=None, lift=None, highlight=None, parts=None):
    """Scultura in legno: ogni pezzo estruso con lo spessore del materiale, facce chiare con le venature e bordi
    bruciati. upto: solo i primi pezzi (montaggio); lift: (indice, altezza) pezzo sollevato che sta arrivando."""
    sc = Scene()
    parts = sculpture_parts(sculpt) if parts is None else parts
    ground = sculpture_ground(sculpt, parts)
    if upto is not None:
        parts = parts[:upto]
    for k, (tris, caps) in enumerate(parts):
        dz = np.array([0.0, 0.0, lift[1] if (lift is not None and k == lift[0]) else 0.0])
        face = WOOD * (1.06 if highlight is not None and k == highlight else 1.0)
        for rings3, nrm in caps:
            sc.add_cap([r + dz for r in rings3], nrm, np.minimum(face, 1.0), grain=True)
        if len(tris):
            sc.add_tris(tris + dz, BURNT)
    sc.ground = ground
    return sc
