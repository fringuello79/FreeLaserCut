# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Il soggetto di una foto (per «Schizzo del soggetto»): cosa tenere e cosa diventa carta bianca.

Tutto dentro FreeLaserCut, con GrabCut di OpenCV (già incluso), senza modelli né dati scaricati:

1. **Aiuti di chi disegna**: un riquadro intorno al soggetto (fuori è sfondo), pennellate «tieni» e «togli»;
2. senza aiuti, il riquadro centrale della foto con tre prove a maggioranza (come prima).

Gli aiuti sono in frazioni dell'immagine (0..1): {"rect": [x0, y0, x1, y1] | None,
"keep": [[raggio, [x, y, x, y, ...], ordine, segui_bordi], ...], "remove": [...], "auto": bool},
raggio in frazioni della diagonale.

0.17.6 (dalle prove di un utente: «togli toglie molto più di quello selezionato»): di partenza i pennelli sono
**precisi**, come una gomma: tengono o tolgono esattamente dove passano, nell'ordine in cui sono stati dati.
Il comportamento «intelligente» di prima (si allarga ai pezzi attaccati con colori simili) resta per i tratti
dati con «Segui i bordi» (segui_bordi = 1). Il riquadro di partenza tiene tutto quello che sta dentro; con
"auto" il soggetto si cerca da solo dentro il riquadro, come prima. Gli aiuti salvati prima della 0.17.6 (senza
questi campi) si comportano come allora.
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


def _smart(item):
    """Tratto «intelligente» (segue i bordi)? Quelli salvati prima della 0.17.6 non hanno il campo: sì, come allora."""
    try:
        return bool(item[3]) if len(item) > 3 else True
    except TypeError:
        return True


def _ordered(hints, smart):
    """Tratti di un tipo (intelligenti o precisi) nell'ordine in cui sono stati dati: [(valore, tratto)]."""
    out = []
    for kind, val in (("keep", 1), ("remove", 0)):
        for i, item in enumerate(hints.get(kind) or []):
            if _smart(item) != smart:
                continue
            try:
                n = float(item[2]) if len(item) > 2 else (i if val else 1e6 + i)
            except (TypeError, ValueError):
                n = 1e6 + i
            out.append((n, val, item))
    return [(v, it) for _n, v, it in sorted(out, key=lambda t: t[0])]


def _rect_auto(hints):
    """Riquadro con ricerca automatica del soggetto dentro? Gli aiuti di prima della 0.17.6 non hanno il campo: sì."""
    return bool(hints.get("auto", True)) if "auto" in hints else True


def _rect_px(rect, w, h):
    x0, y0, x1, y1 = (float(v) for v in rect)
    a, b = int(min(x0, x1) * w), int(min(y0, y1) * h)
    c, d = int(np.ceil(max(x0, x1) * w)), int(np.ceil(max(y0, y1) * h))
    return max(0, a), max(0, b), min(w, c), min(h, d)


def _apply_precise(mask, hints):
    """Riquadro e tratti precisi sulla maschera alla grandezza vera (bordi netti, esattamente dove passa il
    pennello). mask: float32 h×w, modificata e restituita."""
    h, w = mask.shape
    r = hints.get("rect")
    if r:
        a, b, c, d = _rect_px(r, w, h)
        inside = np.zeros((h, w), np.uint8)
        inside[b:d, a:c] = 1
    else:
        inside = None
    tr_ = _ordered(hints, smart=False)
    if tr_:
        lab = np.full((h, w), 255, np.uint8)  # 255 = non toccato
        for val, item in tr_:
            _paint(lab, [item], val, w, h)
        mask = np.where(lab == 1, 1.0, np.where(lab == 0, 0.0, mask)).astype(np.float32)
    if inside is not None:
        mask = mask * inside
    return mask


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
            if has_hints(hints):
                out = _apply_precise(out, hints)
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
        a, b, c, d = _rect_px(r, sw, sh)
        inside[:] = 0
        inside[b:d, a:c] = 1
        base = inside.copy()  # 0.17.6: di partenza dentro il riquadro resta tutto
        if _rect_auto(hints):  # il soggetto si cerca da solo dentro il riquadro
            lab = np.where(inside > 0, cv2.GC_PR_FGD, cv2.GC_BGD).astype(np.uint8)
            fg = _grabcut(small, lab)
            found = _clean(fg) if fg is not None else None
            if found is not None and (found & inside).sum() >= 0.12 * inside.sum():
                base = found & inside  # altrimenti vale il riquadro così com'è
    else:
        base = _rect_only(small)
        if base is None:
            base = np.ones((sh, sw), np.uint8)
    seeds = np.zeros((sh, sw), np.uint8)
    rem = np.zeros((sh, sw), np.uint8)
    for val, item in _ordered(hints, smart=True):  # solo i tratti «Segui i bordi»: i precisi dopo, a grandezza vera
        _paint(seeds if val else rem, [item], 1, sw, sh)
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
    if "auto" in hints:
        res["auto"] = hints["auto"]
    r = hints.get("rect")
    if r:
        res["rect"] = [(r[0] - x0) / cw, (r[1] - y0) / ch, (r[2] - x0) / cw, (r[3] - y0) / ch]
    for kind in ("keep", "remove"):
        for item in hints.get(kind) or []:
            try:  # ordine e «Segui i bordi» (item[2:]) restano
                res[kind].append([float(item[0]) * diag_k, pt([float(v) for v in item[1]])] + list(item[2:]))
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
    if "auto" in hints:
        res["auto"] = hints["auto"]
    r = hints.get("rect")
    if r:
        a, b = f(r[0], r[1])
        c, e = f(r[2], r[3])
        res["rect"] = [min(a, c), min(b, e), max(a, c), max(b, e)]
    for kind in ("keep", "remove"):
        res[kind] = [[item[0], pts(item[1])] + list(item[2:]) for item in hints.get(kind) or []]
    return res
