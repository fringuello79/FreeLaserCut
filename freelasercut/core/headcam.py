# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Telecamera sulla testa del laser (0.19.6): i conti, senza interfaccia e senza macchina.

Modello, tutto nelle coordinate della MACCHINA in mm (MPos): non cambiano se si ruota il piano mostrato o si
invertono gli assi, che riguardano solo come il piano si vede.
- La testa (il punto del laser) è in M. Il mirino, cioè il centro dell'immagine c, guarda il punto M + O.
- Un pixel m guarda il punto M + O + A·(m − c), con A matrice 2×2 in mm per pixel (scala, rotazione e specchio).
Calibrazione (vedi headcam_cal.py): un segno inciso nel punto P; spostando la testa di d il segno si sposta
nell'immagine di s = −A⁻¹·d, quindi A·s = −d (minimi quadrati su più spostamenti); con il segno visto in m e la
testa in M: O = P − M − A·(m − c).
Progetto e casi provati: documento «aggiornamento-0.19.6».
"""
import math
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from freelasercut.i18n import tr  # noqa: E402

SCALE_MIN, SCALE_MAX = 0.002, 2.0  # mm per pixel credibili
OFFSET_MAX = 500.0  # mm
MARK_R = 0.8  # raggio del segno inciso per la calibrazione (mm): disco pieno Ø 1,6
MARK_POWER = 30.0  # % di partenza
MARK_FEED = 600.0  # mm/min


@dataclass
class HeadCal:
    A: np.ndarray  # 2×2, mm per pixel, coordinate macchina
    offset: np.ndarray  # (2,) mm: mirino − laser
    size: tuple = (1280, 720)  # immagine della calibrazione (w, h)
    resid: float = 0.0  # mm: scarto medio del calcolo della scala
    when: str = ""
    extra: dict = field(default_factory=dict)

    # ---- controlli
    def problem(self):
        """None se la calibrazione è credibile, altrimenti il motivo (testo breve)."""
        A, O = np.asarray(self.A, float), np.asarray(self.offset, float)
        if A.shape != (2, 2) or O.shape != (2,) or not (np.all(np.isfinite(A)) and np.all(np.isfinite(O))):
            return tr("dati della calibrazione non validi")
        det = float(np.linalg.det(A))
        if abs(det) < 1e-12:
            return tr("scala della camera nulla")
        s = math.sqrt(abs(det))
        if not SCALE_MIN <= s <= SCALE_MAX:
            return tr("scala {0:.4f} mm per pixel fuori dai limiti", s)
        if float(np.hypot(*O)) > OFFSET_MAX:
            return tr("distanza fra laser e mirino oltre {0:.0f} mm", OFFSET_MAX)
        w, h = self.size
        if not (16 <= int(w) <= 20000 and 16 <= int(h) <= 20000):
            return tr("misura dell'immagine non valida")
        return None

    # ---- grandezze leggibili
    @property
    def scale(self):
        """mm per pixel (media dei due assi)."""
        return math.sqrt(abs(float(np.linalg.det(self.A))))

    @property
    def mirrored(self):
        return float(np.linalg.det(self.A)) < 0

    @property
    def angle(self):
        """Gradi: direzione, sulla macchina, dell'asse u dell'immagine (verso destra)."""
        return math.degrees(math.atan2(self.A[1, 0], self.A[0, 0]))

    def center(self, size=None):
        w, h = size or self.size
        return np.array([(w - 1) / 2.0, (h - 1) / 2.0])

    # ---- conversioni
    def crosshair(self, head):
        """Punto (macchina) sotto il mirino con la testa in `head`."""
        return np.asarray(head, float) + self.offset

    def head_for_crosshair(self, target):
        """Dove mettere la testa perché il mirino guardi `target`."""
        return np.asarray(target, float) - self.offset

    def px_to_machine(self, head, px, size=None):
        m = np.asarray(px, float) - self.center(size)
        return np.asarray(head, float) + self.offset + self.A @ m

    def machine_to_px(self, head, pt, size=None):
        d = np.asarray(pt, float) - np.asarray(head, float) - self.offset
        return self.center(size) + np.linalg.solve(self.A, d)

    # ---- file
    def to_dict(self):
        return {"A": [[float(v) for v in r] for r in np.asarray(self.A)], "offset": [float(v) for v in self.offset],
                "size": [int(self.size[0]), int(self.size[1])], "resid": float(self.resid), "when": self.when,
                **({"extra": self.extra} if self.extra else {})}

    @classmethod
    def from_dict(cls, d):
        """Dizionario salvato -> HeadCal, oppure None se manca o non è credibile."""
        if not isinstance(d, dict) or "A" not in d or "offset" not in d:
            return None
        try:
            cal = cls(np.array(d["A"], float), np.array(d["offset"], float), tuple(int(v) for v in d.get("size", (1280, 720))),
                      float(d.get("resid", 0.0)), str(d.get("when", "")), dict(d.get("extra") or {}))
        except (TypeError, ValueError):
            return None
        return None if cal.problem() else cal


def new_cal(A, offset, size, resid):
    return HeadCal(np.asarray(A, float), np.asarray(offset, float), (int(size[0]), int(size[1])), float(resid),
                   time.strftime("%d/%m/%Y %H:%M"))


# ======================================================================= calcoli della calibrazione
def fit_A(moves, shifts):
    """Spostamenti della testa d_i (mm, macchina) e spostamenti dello stesso punto fermo nell'immagine s_i (pixel):
    A·s_i = −d_i ai minimi quadrati. -> (A, scarto medio in mm) oppure (None, inf) se i dati non bastano."""
    D = np.asarray(moves, float).reshape(-1, 2)
    Sx = np.asarray(shifts, float).reshape(-1, 2)
    if len(D) < 2 or len(D) != len(Sx):
        return None, float("inf")
    StS = Sx.T @ Sx
    if abs(np.linalg.det(StS)) < 1e-9:  # spostamenti tutti nella stessa direzione: non bastano
        return None, float("inf")
    A = -(D.T @ Sx) @ np.linalg.inv(StS)
    res = (A @ Sx.T).T + D
    return A, float(np.sqrt((res ** 2).sum(1).mean()))


def offset_from_mark(mark, head, px, A, size):
    """Il segno inciso in `mark` (macchina) si vede nel pixel `px` con la testa in `head`: -> offset O."""
    c = np.array([(size[0] - 1) / 2.0, (size[1] - 1) / 2.0])
    return np.asarray(mark, float) - np.asarray(head, float) - np.asarray(A, float) @ (np.asarray(px, float) - c)


def mark_gcode(ux, uy, s_value, feed=MARK_FEED, r=MARK_R):
    """G-code del segno: disco pieno di raggio r attorno a (ux, uy) in coordinate di LAVORO, solo tratti dritti
    (vale su ogni scheda), laser in M4. Finisce con il laser spento e la testa sul centro."""
    out = ["G90 G21", "M4 S0"]
    rings = [r * k / 3.0 for k in (3, 2, 1)]
    for rr in rings:
        pts = [(ux + rr * math.cos(2 * math.pi * i / 24), uy + rr * math.sin(2 * math.pi * i / 24)) for i in range(25)]
        out.append(f"G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f}")
        out.append(f"G1 F{feed:.0f} S{s_value:.0f}")
        out += [f"G1 X{x:.3f} Y{y:.3f}" for x, y in pts[1:]]
        out.append("S0")
    # il centro: un trattino simmetrico (un segno storto sposterebbe il baricentro che la camera misura)
    out += [f"G0 X{ux - 0.05:.3f} Y{uy:.3f}", f"G1 F{feed:.0f} S{s_value:.0f}", f"G1 X{ux + 0.05:.3f} Y{uy:.3f}",
            "S0", "M5 S0", f"G0 X{ux:.3f} Y{uy:.3f}"]
    return out


# ======================================================================= trovare il segno nell'immagine
def _gray(frame):
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g.astype(np.float32), (0, 0), 1.2)


def _avg(frames):
    fs = [f.astype(np.float32) for f in frames if f is not None]
    return sum(fs) / len(fs) if fs else None


def detect_mark(frame, near, radius, ref_area=None):
    """Macchia scura (il segno inciso) vicino a `near` (pixel), entro `radius` pixel.
    -> ((u, v), area in pixel) oppure (None, 0). Fra più macchie sceglie la più vicina, pesata sulla somiglianza
    di area con `ref_area` se è nota."""
    if frame is None:
        return None, 0
    g = _gray(frame)
    h, w = g.shape
    cx, cy = float(near[0]), float(near[1])
    r = int(max(8, radius))
    x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None, 0
    win = g[y0:y1, x0:x1]
    bg = float(np.median(win))
    mad = float(np.median(np.abs(win - bg))) + 1e-6
    thr = bg - max(18.0, 6.0 * mad)
    mask = (win < thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    best, best_score = None, -1.0
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < 6 or area > 0.6 * mask.size:
            continue
        bw, bh = stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]
        fill = area / float(max(1, bw * bh))
        if fill < 0.35 or max(bw, bh) > 4 * max(1, min(bw, bh)):  # righe e venature: no
            continue
        u, v = cents[k][0] + x0, cents[k][1] + y0
        dist = math.hypot(u - cx, v - cy) / r
        sim = 1.0 if not ref_area else min(area, ref_area) / max(area, ref_area)
        score = sim * (1.0 - 0.7 * min(dist, 1.0))
        if score > best_score:
            best, best_score = (k, area), score
    if best is None:
        return None, 0
    k, area = best
    # baricentro della forma, senza pesare lo scuro: le venature sotto il segno (più chiare da un lato) sposterebbero
    # un baricentro pesato di qualche decimo di pixel sempre dalla stessa parte
    blob = cv2.morphologyEx((labels == k).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    ys, xs = np.nonzero(blob)
    return (float(xs.mean()) + x0, float(ys.mean()) + y0), area


def detect_new_mark(before_frames, after_frames, near=None):
    """Il segno comparso fra le foto prima e dopo (differenza): -> ((u, v), area) oppure (None, 0)."""
    b, a = _avg(before_frames), _avg(after_frames)
    if b is None or a is None or b.shape != a.shape:
        return None, 0
    gb, ga = _gray(b), _gray(a)
    d = np.clip(gb - ga, 0, None)
    peak = float(d.max())
    if peak < 20.0:
        return None, 0
    mask = (d > 0.45 * peak).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    best, best_s = None, 0.0
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < 6:
            continue
        s = float(d[labels == k].sum())
        if near is not None:
            s /= 1.0 + math.hypot(cents[k][0] - near[0], cents[k][1] - near[1]) / 200.0
        if s > best_s:
            best, best_s = k, s
    if best is None:
        return None, 0
    ys, xs = np.nonzero(labels == best)
    wts = d[ys, xs]
    return (float((xs * wts).sum() / wts.sum()), float((ys * wts).sum() / wts.sum())), int(stats[best, cv2.CC_STAT_AREA])


# ======================================================================= video raddrizzato
def view_orientation(A_bed):
    """Come girare il fotogramma (quarti di giro antiorari k, specchio orizzontale prima) perché sul video la X del
    piano vada a destra e la Y in su. A_bed: A espressa nelle coordinate del piano mostrato. -> (k, flip)."""
    A = np.asarray(A_bed, float)
    best = None
    for flip in (False, True):
        F = np.array([[-1.0, 0.0], [0.0, 1.0]]) if flip else np.eye(2)
        for k in range(4):
            # pixel mostrato -> pixel originale: prima lo specchio, poi k quarti di giro (y dell'immagine in giù)
            # un quarto di giro antiorario porta lo spostamento (du, dv) in (dv, −du): Q = [[0, 1], [−1, 0]];
            # shown = Q^k·F·raw, quindi raw = F·Q^−k·shown
            Qi = np.eye(2)
            for _ in range(k):
                Qi = Qi @ np.array([[0.0, -1.0], [1.0, 0.0]])
            M = A @ F @ Qi  # mm sul piano per pixel mostrato
            # vogliamo: destra (+u) = +X, giù (+v) = −Y
            score = M[0, 0] - M[1, 1] - abs(M[1, 0]) - abs(M[0, 1])
            if best is None or score > best[0]:
                best = (score, k, flip)
    return best[1], best[2]


def orient_frame(frame, k, flip):
    """Applica view_orientation al fotogramma."""
    out = cv2.flip(frame, 1) if flip else frame
    for _ in range(k % 4):
        out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return out


def shown_to_raw(px, raw_size, k, flip):
    """Pixel del video raddrizzato -> pixel del fotogramma originale (per i clic sul video)."""
    w, h = raw_size
    u, v = float(px[0]), float(px[1])
    # si disfano i quarti di giro (ognuno: originale (u, v) -> (v, W − 1 − u), con W la larghezza prima del giro)
    sizes = []
    cw, ch = w, h
    for _ in range(k % 4):
        sizes.append((cw, ch))
        cw, ch = ch, cw
    for cw, ch in reversed(sizes):
        u, v = cw - 1 - v, u
    if flip:
        u = w - 1 - u
    return u, v


def raw_to_shown(px, raw_size, k, flip):
    """Pixel del fotogramma originale -> pixel del video raddrizzato (per disegnare sul video)."""
    w, h = raw_size
    u, v = float(px[0]), float(px[1])
    if flip:
        u = w - 1 - u
    cw, ch = w, h
    for _ in range(k % 4):
        u, v = v, cw - 1 - u
        cw, ch = ch, cw
    return u, v


def nice_ruler(mm_per_px, target_px):
    """Lunghezza «tonda» del righello (mm) vicina a target_px pixel: 0,1 0,2 0,5 1 2 5 10 20 50."""
    want = mm_per_px * target_px
    best = 0.1
    for v in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100):
        if v <= want:
            best = v
    return float(best)


# ======================================================================= tavola da due angoli (fase 2)
def board_from_corners(c1, c2, height):
    """Spigoli 1 e 2 dello stesso lato (coordinate del piano) e l'altra misura in mm (verso sinistra andando dall'1
    al 2: con l'1 in basso a sinistra e il 2 in basso a destra la tavola sta sopra). -> dict con i quattro angoli,
    larghezza, altezza, angolo in gradi; None se i due punti coincidono o l'altezza non è positiva."""
    a, b = np.asarray(c1, float), np.asarray(c2, float)
    v = b - a
    L = float(np.hypot(*v))
    if L < 1.0 or not (height > 0):
        return None
    t = v / L
    nrm = np.array([-t[1], t[0]])
    pts = [a, b, b + nrm * height, a + nrm * height]
    return {"corners": [tuple(map(float, p)) for p in pts], "width": L, "height": float(height),
            "angle": math.degrees(math.atan2(t[1], t[0]))}


def find_corner(frame, near, radius):
    """Spigolo di una tavola chiara (o scura) sul fondo vicino a `near`: due bordi dritti nell'immagine e il loro
    incrocio. -> ((u, v), sicurezza 0–1) oppure (None, 0). Facoltativo: se non è sicuro si usa il mirino."""
    if frame is None:
        return None, 0.0
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    r = int(max(20, radius))
    x0, x1 = max(0, int(near[0]) - r), min(w, int(near[0]) + r)
    y0, y1 = max(0, int(near[1]) - r), min(h, int(near[1]) + r)
    win = cv2.GaussianBlur(g[y0:y1, x0:x1], (0, 0), 2.0)
    if win.size < 400:
        return None, 0.0
    _t, bw = cv2.threshold(win, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(bw, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(20, int(0.25 * min(win.shape))))
    if lines is None or len(lines) < 2:
        return None, 0.0
    lines = lines[:, 0, :]
    l1 = lines[0]
    l2 = next((ln for ln in lines[1:] if abs(math.sin(ln[1] - l1[1])) > math.sin(math.radians(45))), None)
    if l2 is None:
        return None, 0.0
    (r1, t1), (r2, t2) = l1, l2
    M = np.array([[math.cos(t1), math.sin(t1)], [math.cos(t2), math.sin(t2)]])
    try:
        xy = np.linalg.solve(M, np.array([r1, r2]))
    except np.linalg.LinAlgError:
        return None, 0.0
    u, v = float(xy[0]) + x0, float(xy[1]) + y0
    if not (x0 <= u < x1 and y0 <= v < y1):
        return None, 0.0
    contrast = float(abs(np.mean(win[bw > 0]) - np.mean(win[bw == 0]))) if (bw > 0).any() and (bw == 0).any() else 0.0
    conf = max(0.0, min(1.0, contrast / 60.0)) * max(0.0, 1.0 - math.hypot(u - near[0], v - near[1]) / r)
    return (u, v), conf
