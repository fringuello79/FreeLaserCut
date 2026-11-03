# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Taratura da foto: legge la foto di un test materiale inciso con i quattro riferimenti agli angoli.

1. trova i riferimenti (ArUco 4×4 di OpenCV) nella foto, anche se è storta, in prospettiva o specchiata;
2. raddrizza la foto (10 pixel per mm) usando le posizioni dei riferimenti sul piano;
3. misura quanto è scuro ogni quadrato rispetto al materiale nudo tra i quadrati;
4. propone i valori: incisione scura, incisione leggera e intervallo di potenza per le foto.

Non usa Qt e non serve la macchina: basta la foto e la griglia con cui è stato inciso il test.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import material_test as mtest
from freelasercut.i18n import tr  # noqa: E402

PX_MM = 10.0


class PhotoError(Exception):
    """Problema leggibile da mostrare alla persona."""


@dataclass
class Suggestion:
    kind: str  # "scura" | "leggera" | "foto"
    title: str
    power: float
    speed: float
    power_min: float = 0.0  # solo per «foto»
    cell: tuple = None  # (riga, colonna) nella griglia
    text: str = ""


@dataclass
class PhotoResult:
    dark: np.ndarray  # [righe, colonne] 0 = come il materiale, 1 = nero
    powers: list
    speeds: list
    found: list  # id dei riferimenti trovati
    mirrored: bool
    rectified: np.ndarray  # foto raddrizzata (BGR)
    px_mm: float
    origin: tuple  # angolo (x, y) del piano in alto a sinistra della foto raddrizzata
    suggestions: list = field(default_factory=list)
    uneven: float = 0.0  # quanto varia il materiale nudo (0 = uniforme)

    def best(self, kind):
        for s in self.suggestions:
            if s.kind == kind:
                return s
        return None


def _detect(gray):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    p = cv2.aruco.DetectorParameters()
    try:
        p.detectInvertedMarker = True  # materiali scuri: l'incisione viene più chiara
    except AttributeError:
        pass
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    det = cv2.aruco.ArucoDetector(d, p)
    corners, ids, _ = det.detectMarkers(gray)
    out = {}
    if ids is not None:
        for c, i in zip(corners, ids.ravel()):
            if 0 <= int(i) <= 3 and int(i) not in out:
                out[int(i)] = c.reshape(4, 2).astype(np.float64)
    return out


def find_markers(image_bgr):
    """{id: 4 angoli in pixel} e se la foto risulta specchiata. Prova anche la foto ribaltata e rimpicciolita."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    h, w = gray.shape[:2]
    best = ({}, False)
    scales = [1.0]
    if max(h, w) > 2000:
        scales.insert(0, 2000.0 / max(h, w))
    for sc in scales:
        g = gray if sc == 1.0 else cv2.resize(gray, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)
        for flip in (False, True):
            gg = cv2.flip(g, 1) if flip else g
            m = _detect(gg)
            if flip:
                for k, c in m.items():
                    c[:, 0] = (g.shape[1] - 1) - c[:, 0]
            if sc != 1.0:
                for c in m.values():
                    c /= sc
            if len(m) > len(best[0]):
                best = (m, flip)
            if len(best[0]) == 4:
                return best
    return best


def analyze(image_bgr, spec):
    if image_bgr is None or image_bgr.size == 0:
        raise PhotoError(tr("Non riesco a leggere l'immagine."))
    if image_bgr.ndim == 2:
        image_bgr = cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2BGR)
    if spec.mode != "fill":
        raise PhotoError(tr("La lettura della foto funziona con i test di riempimento (incisione)."))
    L = mtest.layout(spec)
    if not L.marks:
        raise PhotoError(tr("Questo test non ha i riferimenti agli angoli: incidilo con «Riferimenti per leggere la foto»."))
    found, mirrored = find_markers(image_bgr)
    if len(found) < 2:
        raise PhotoError(tr("Nella foto trovo {0} riferimenti su 4: ne servono almeno 2 (meglio tutti). Rifai la foto "
                            "dall'alto, con tutto il test dentro l'inquadratura, luce uniforme e senza riflessi.", len(found)))
    src, dst = [], []
    pos = {mid: (mx, my) for mid, mx, my in L.marks}
    for mid, c in found.items():
        for (bx, by), (u, v) in zip(mtest.marker_corners(*pos[mid]), c):
            src.append((bx, by))
            dst.append((u, v))
    H_bed_img, _ = cv2.findHomography(np.array(src, np.float64), np.array(dst, np.float64), 0)
    if H_bed_img is None:
        raise PhotoError(tr("Non riesco a raddrizzare la foto: rifalla più dall'alto."))
    xa, ya, xb, yb = L.outer
    k = PX_MM
    S = np.array([[k, 0, -k * xa], [0, -k, k * yb], [0, 0, 1]], np.float64)  # piano → foto raddrizzata (y in giù)
    M = S @ np.linalg.inv(H_bed_img)
    Wpx, Hpx = int(round((xb - xa) * k)), int(round((yb - ya) * k))
    rect = cv2.warpPerspective(image_bgr, M, (Wpx, Hpx), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    lum = cv2.cvtColor(rect, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float64)

    def box(x, y, w, h, inset):
        u0 = int(round((x - xa + inset) * k))
        u1 = int(round((x + w - xa - inset) * k))
        v0 = int(round((yb - (y + h) + inset) * k))
        v1 = int(round((yb - y - inset) * k))
        return max(0, v0), min(Hpx, max(v0 + 1, v1)), max(0, u0), min(Wpx, max(u0 + 1, u1))

    # materiale nudo: strisce tra i quadrati (e intorno), lontano dai bordi incisi
    bare = np.zeros(lum.shape, bool)
    gx1 = L.gx0 + spec.cols * L.pitch - spec.gap
    gy1 = L.gy0 + spec.rows * L.pitch - spec.gap
    v0, v1, u0, u1 = box(L.gx0 - spec.gap, L.gy0 - spec.gap * 0.5, gx1 - L.gx0 + spec.gap * 2, gy1 - L.gy0 + spec.gap, 0)
    bare[v0:v1, u0:u1] = True
    cut = max(0.25, spec.gap * 0.25)
    for r in range(spec.rows):
        for c in range(spec.cols):
            x, y, s = mtest.cell_rect(spec, L, r, c)
            a0, a1, b0, b1 = box(x - cut, y - cut, s + 2 * cut, s + 2 * cut, 0)
            bare[a0:a1, b0:b1] = False
    if L.lab:  # le etichette stanno a sinistra e in basso
        a0, a1, b0, b1 = box(L.x0c - 4, L.y0c - 6, L.lab + 4, gy1 - L.y0c + 6, 0)
        bare[a0:a1, b0:b1] = False
        a0, a1, b0, b1 = box(L.x0c - 4, L.y0c - 6, gx1 - L.x0c + 6, L.lab + 6, 0)
        bare[a0:a1, b0:b1] = False
    vals = lum[bare]
    if vals.size < 20:
        raise PhotoError(tr("Tra i quadrati non c'è abbastanza materiale nudo da misurare: usa uno spazio più largo."))
    bg = float(np.median(vals))
    uneven = float(np.subtract(*np.percentile(vals, [90, 10]))) / max(bg, 1.0)
    dark = np.zeros((spec.rows, spec.cols))
    for r in range(spec.rows):
        for c in range(spec.cols):
            x, y, s = mtest.cell_rect(spec, L, r, c)
            a0, a1, b0, b1 = box(x, y, s, s, s * 0.2)
            m = float(np.median(lum[a0:a1, b0:b1]))
            dark[r, c] = abs(bg - m) / max(bg, 1.0) if bg > 1 else 0.0
    # su materiale scuro l'incisione può venire più chiara: conta la differenza, ma col segno prevalente
    powers = mtest._steps(spec.p_min, spec.p_max, spec.rows)
    speeds = mtest._steps(spec.s_min, spec.s_max, spec.cols)
    res = PhotoResult(np.clip(dark, 0, 1), powers, speeds, sorted(found), mirrored, rect, k, (xa, yb), uneven=uneven)
    res.suggestions = suggest(res.dark, powers, speeds)
    return res


def suggest(dark, powers, speeds):
    rows, cols = dark.shape
    dmax = float(dark.max()) if dark.size else 0.0
    out = []
    if dmax < 0.08:
        return out
    cells = [(powers[r] / max(speeds[c], 1.0), r, c) for r in range(rows) for c in range(cols)]
    cells.sort()
    # incisione scura: il quadrato col minimo di energia che arriva quasi al massimo (più veloce = meno bruciato)
    for e, r, c in cells:
        if dark[r, c] >= 0.9 * dmax:
            out.append(Suggestion("scura", tr("Incisione scura"), round(powers[r], 1), round(speeds[c]), cell=(r, c),
                                  text=tr("Il quadrato più leggero che arriva quasi al massimo del nero.")))
            break
    # incisione leggera: il quadrato più vicino a metà del nero massimo
    tgt = 0.45 * dmax
    _, r, c = min(((abs(dark[r, c] - tgt), r, c) for _, r, c in cells))
    out.append(Suggestion("leggera", tr("Incisione leggera"), round(powers[r], 1), round(speeds[c]), cell=(r, c),
                          text=tr("Un tono a metà: per scritte delicate, sfondi, segni leggeri.")))
    # foto in scala di grigi: la colonna (velocità) con la sfumatura più ampia e regolare
    best = None
    for c in range(cols):
        col = dark[:, c]
        rng = float(col.max() - col.min())
        mono = float(np.sum(np.diff(col) >= -0.03)) / max(1, rows - 1)
        score = rng * (0.5 + 0.5 * mono)
        if best is None or score > best[0]:
            best = (score, c)
    if best and rows >= 2:
        c = best[1]
        col = dark[:, c]
        cmax = float(col.max())
        r_lo = next((r for r in range(rows) if col[r] >= 0.08 * dmax), 0)
        r_hi = next((r for r in range(rows) if col[r] >= 0.9 * cmax), rows - 1)
        if r_hi <= r_lo:
            r_hi = min(rows - 1, r_lo + 1)
        out.append(Suggestion("foto", tr("Foto (scala di grigi)"), round(powers[r_hi], 1), round(speeds[c]),
                              power_min=round(powers[r_lo], 1), cell=(r_hi, c),
                              text=tr("Potenza minima = dove il segno comincia a vedersi, massima = dove diventa "
                                      "quasi nero, alla velocità con la sfumatura migliore.")))
    return out
