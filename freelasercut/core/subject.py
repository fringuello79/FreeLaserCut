# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Il soggetto di una foto (per «Schizzo del soggetto»): cosa tenere e cosa diventa carta bianca.

Tutto dentro FreeLaserCut, con GrabCut di OpenCV (già incluso), senza modelli né dati scaricati:

1. **Aiuti di chi disegna**: un riquadro intorno al soggetto (fuori è sfondo), pennellate «tieni» e «togli»;
2. senza aiuti, il riquadro centrale della foto con tre prove a maggioranza (come prima).

Gli aiuti sono in frazioni dell'immagine (0..1): {"rect": [x0, y0, x1, y1] | None,
"keep": [[raggio, [x, y, x, y, ...]], ...], "remove": [...]}, raggio in frazioni della diagonale.
"""
import json

import cv2
import numpy as np

WORK = 360  # lato massimo della foto per GrabCut (veloce; la maschera poi si ingrandisce)


# ====================================================================== maschera del soggetto
_CACHE = {}


def has_hints(hints):
    return bool(hints) and bool(hints.get("rect") or hints.get("keep") or hints.get("remove"))


def _paint(lab, strokes, value, w, h):
    diag = (w * w + h * h) ** 0.5
    for item in strokes or []:
        try:
            r, pts = float(item[0]), [float(v) for v in item[1]]
        except (TypeError, ValueError, IndexError):
            continue
        xy = np.array(pts[: len(pts) // 2 * 2], np.float32).reshape(-1, 2) * (w, h)
        if not len(xy):
            continue
        t = max(1, int(round(r * diag * 2)))
        if len(xy) == 1:
            cv2.circle(lab, (int(xy[0, 0]), int(xy[0, 1])), max(1, t // 2), value, -1)
        else:
            cv2.polylines(lab, [np.round(xy).astype(np.int32)], False, value, t, cv2.LINE_8)


def _clean(fg, keep_seeds=None):
    """Componenti grandi (e quelle toccate da «tieni»), buchi chiusi, bordi morbidi."""
    sh, sw = fg.shape
    n, lab, st, _c = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n <= 1:
        return None
    big = st[1:, cv2.CC_STAT_AREA].max()
    ids = {i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.3 * big}
    if keep_seeds is not None:
        ids |= {int(i) for i in np.unique(lab[keep_seeds > 0]) if i > 0}
    keep = np.isin(lab, sorted(ids)).astype(np.uint8)
    if not 0.01 <= keep.mean() <= 0.97:
        return None
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    ff = keep.copy()
    cv2.floodFill(ff, np.zeros((sh + 2, sw + 2), np.uint8), (0, 0), 1)
    return keep | (1 - ff)


# ultimo calcolo senza aiuti: il soggetto non si è trovato da solo (la finestra lo dice)
last = {"auto_failed": False}


def subject_mask(rgb, hints=None):
    """1 = soggetto, 0 = sfondo (float32, grandezza di rgb), o None se non c'è un soggetto chiaro."""
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if rgb.ndim == 2:
        rgb = cv2.cvtColor(rgb, cv2.COLOR_GRAY2RGB)
    elif rgb.shape[2] == 4:
        rgb = np.ascontiguousarray(rgb[:, :, :3])
    h, w = rgb.shape[:2]
    k = min(1.0, WORK / max(h, w))
    small = cv2.resize(rgb, (max(8, int(round(w * k))), max(8, int(round(h * k)))), interpolation=cv2.INTER_AREA)
    key = (w, h, hash(small.tobytes()), json.dumps(hints or {}, sort_keys=True))
    if key in _CACHE:  # l'anteprima si ricalcola a ogni cursore: la maschera resta la stessa
        if not has_hints(hints):
            last["auto_failed"] = _CACHE[key] is None
        return _CACHE[key]
    out = None
    try:
        out = _compute(small, hints if has_hints(hints) else None)
        if out is not None:
            out = cv2.resize(out.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    except cv2.error:
        out = None
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = out
    if not has_hints(hints):
        last["auto_failed"] = out is None
    return out


def _grabcut(small, lab, iters=5):
    if not ((lab == cv2.GC_FGD) | (lab == cv2.GC_PR_FGD)).any() or not ((lab == cv2.GC_BGD) | (lab == cv2.GC_PR_BGD)).any():
        return None
    lab = lab.copy()
    cv2.setRNGSeed(11)
    cv2.grabCut(np.ascontiguousarray(small), lab, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                iters, cv2.GC_INIT_WITH_MASK)
    return ((lab == cv2.GC_FGD) | (lab == cv2.GC_PR_FGD)).astype(np.uint8)


def _touching(region, seeds):
    """Le parti di `region` (componenti connesse) che toccano i segni del pennello."""
    if not seeds.any() or not region.any():
        return np.zeros_like(region)
    n, lab = cv2.connectedComponents(region, connectivity=8)
    ids = [int(i) for i in np.unique(lab[seeds > 0]) if i > 0]
    return np.isin(lab, ids).astype(np.uint8)


def _compute(small, hints):
    """Gli aiuti sono modifiche prevedibili di quello che si vede:
    - riquadro: il soggetto sta dentro (fuori è sempre sfondo); dentro, GrabCut trova i bordi; se non trova
      niente di sensato resta tutto il riquadro;
    - «togli»: sparisce la parte sotto il pennello e quello che le sta attaccato con colori simili (il canestro
      intero, l'ombra), solo intorno a dove hai passato il pennello;
    - «tieni»: torna la parte sotto il pennello e quello che le sta attaccato con colori simili.
    Mai «tutta la foto» perché un calcolo non è riuscito: si parte sempre da quello che c'era."""
    sh, sw = small.shape[:2]
    if hints is None:
        out = _rect_only(small)  # riquadro centrale, tre prove a maggioranza
        last["auto_failed"] = out is None
        return out
    inside = np.ones((sh, sw), np.uint8)
    r = hints.get("rect")
    if r:
        x0, y0, x1, y1 = (float(v) for v in r)
        a, b = int(min(x0, x1) * sw), int(min(y0, y1) * sh)
        c, d = int(np.ceil(max(x0, x1) * sw)), int(np.ceil(max(y0, y1) * sh))
        inside[:] = 0
        inside[max(0, b):min(sh, d), max(0, a):min(sw, c)] = 1
        lab = np.where(inside > 0, cv2.GC_PR_FGD, cv2.GC_BGD).astype(np.uint8)
        fg = _grabcut(small, lab)
        base = _clean(fg) if fg is not None else None
        if base is None or (base & inside).sum() < 0.12 * inside.sum():
            base = inside.copy()  # GrabCut non ha trovato un soggetto: vale il riquadro così com'è
        base &= inside
    else:
        base = _rect_only(small)
        if base is None:
            base = np.ones((sh, sw), np.uint8)
    seeds = np.zeros((sh, sw), np.uint8)
    _paint(seeds, hints.get("keep"), 1, sw, sh)
    rem = np.zeros((sh, sw), np.uint8)
    _paint(rem, hints.get("remove"), 1, sw, sh)
    if seeds.any() or rem.any():
        lab = np.where(base > 0, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
        lab[inside == 0] = cv2.GC_BGD
        lab[seeds > 0] = cv2.GC_FGD
        lab[rem > 0] = cv2.GC_BGD
        gc = _grabcut(small, lab)
        if gc is None:
            gc = base.copy()
        # solo vicino al pennello: il resto del disegno non cambia
        near = max(5, int(0.12 * (sw * sw + sh * sh) ** 0.5))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (near | 1, near | 1))
        added = _touching(((gc > 0) & (base == 0)).astype(np.uint8), seeds) & cv2.dilate(seeds, k)
        removed = _touching(((gc == 0) & (base > 0)).astype(np.uint8), rem) & cv2.dilate(rem, k)
        base = ((base > 0) | (added > 0)) & (removed == 0)
        base = base.astype(np.uint8)
        base[seeds > 0] = 1
        base[rem > 0] = 0
        base &= inside
    last["auto_failed"] = False
    return base


def _rect_only(small):
    sh, sw = small.shape[:2]
    mx, my = max(1, int(sw * 0.04)), max(1, int(sh * 0.04))
    votes = np.zeros((sh, sw), np.uint8)
    for seed in (11, 22, 33):
        cv2.setRNGSeed(seed)
        mask = np.zeros((sh, sw), np.uint8)
        cv2.grabCut(np.ascontiguousarray(small), mask, (mx, my, sw - 2 * mx, sh - 2 * my),
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 4, cv2.GC_INIT_WITH_RECT)
        votes += ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    fg = (votes >= 2).astype(np.uint8)
    out = _clean(fg)
    if out is None or not 0.03 <= out.mean() <= 0.92:
        return None
    return out


# ====================================================================== aiuti e foto ritagliata / ruotata
def hints_to_crop(hints, crop):
    """Aiuti disegnati sulla foto intera (orientata) → frazioni della parte ritagliata."""
    if not has_hints(hints):
        return None
    x0, y0, x1, y1 = (float(v) for v in crop)
    cw, ch = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    diag_k = ((1 + 1) ** 0.5) / ((cw * cw + ch * ch) ** 0.5)  # il raggio è in frazioni della diagonale

    def pt(xs):
        out = []
        for i in range(0, len(xs) - 1, 2):
            out += [(xs[i] - x0) / cw, (xs[i + 1] - y0) / ch]
        return out
    res = {"rect": None, "keep": [], "remove": []}
    r = hints.get("rect")
    if r:
        res["rect"] = [(r[0] - x0) / cw, (r[1] - y0) / ch, (r[2] - x0) / cw, (r[3] - y0) / ch]
    for kind in ("keep", "remove"):
        for item in hints.get(kind) or []:
            try:
                res[kind].append([float(item[0]) * diag_k, pt([float(v) for v in item[1]])])
            except (TypeError, ValueError, IndexError):
                continue
    return res


def rotate_hints(hints, d):
    """Aiuti dopo una rotazione di 90° (d > 0 orario, come il ritaglio) o uno specchio (d == 0)."""
    if not has_hints(hints):
        return hints

    def f(x, y):
        if d == 0:
            return 1 - x, y
        return (1 - y, x) if d > 0 else (y, 1 - x)

    def pts(xs):
        out = []
        for i in range(0, len(xs) - 1, 2):
            out += list(f(xs[i], xs[i + 1]))
        return out
    res = {"rect": None, "keep": [], "remove": []}
    r = hints.get("rect")
    if r:
        a, b = f(r[0], r[1])
        c, e = f(r[2], r[3])
        res["rect"] = [min(a, c), min(b, e), max(a, c), max(b, e)]
    for kind in ("keep", "remove"):
        res[kind] = [[item[0], pts(item[1])] for item in hints.get(kind) or []]
    return res
