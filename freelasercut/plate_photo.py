# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Foto del piano senza calibrazione AutoCam (0.19.0, chiesto da Ale).

Due casi:
- «Mostra senza calibrazione»: la telecamera si vede sotto il piano così com'è, intera e non deformata, adattata
  all'area di lavoro. Serve per guardare, non per posizionare: NON è allineata al piano.
- «Foto del piano dal telefono»: una foto fatta con il telefono (mandata dalla pagina del controllo dal telefono) si
  allinea indicando i 4 angoli dell'area di lavoro: da quei 4 punti si raddrizza la prospettiva. Precisione
  indicativa (dipende da quanto bene si indicano gli angoli; la lente del telefono non viene corretta).

Qui niente Qt: solo i conti sulle immagini (BGR, come le dà la telecamera).
"""
import math

import cv2
import numpy as np

BACK = (34, 26, 15)  # il colore del piano dove la foto non arriva (lo stesso della foto calibrata)
MAX_SIDE = 2400  # lato lungo massimo di una foto dal telefono tenuta in memoria


def decode(data):
    """I byte di una foto (JPEG, PNG…) -> immagine BGR, girata come l'ha scattata il telefono; None se non è una
    foto. Le foto enormi vengono ridotte."""
    if not data:
        return None
    try:
        img = cv2.imdecode(np.frombuffer(bytes(data), np.uint8), cv2.IMREAD_COLOR)
    except (cv2.error, ValueError):
        return None
    if img is None or img.ndim != 3 or min(img.shape[:2]) < 16:
        return None
    h, w = img.shape[:2]
    k = MAX_SIDE / max(h, w)
    if k < 1.0:
        img = cv2.resize(img, (max(1, int(round(w * k))), max(1, int(round(h * k)))), interpolation=cv2.INTER_AREA)
    return img


def bed_pixels(bed, ppm):
    return max(2, int(round(bed[0] * ppm))), max(2, int(round(bed[1] * ppm)))


def fit_raw(frame, bed, ppm=2.0):
    """La foto così com'è dentro l'area di lavoro: intera, con le sue proporzioni, centrata. -> immagine grande
    quanto il piano (riga 0 = Y massimo, come la foto calibrata)."""
    W, H = bed_pixels(bed, ppm)
    h, w = frame.shape[:2]
    k = min(W / w, H / h)
    nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
    small = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    out = np.empty((H, W, 3), np.uint8)
    out[:] = BACK
    x0, y0 = (W - nw) // 2, (H - nh) // 2
    out[y0:y0 + nh, x0:x0 + nw] = small[:, :, :3]
    return out


def order_corners(pts):
    """4 punti cliccati in un ordine qualsiasi -> [alto-sinistra, alto-destra, basso-destra, basso-sinistra] come
    si vedono nella foto (in senso orario partendo da quello più in alto a sinistra)."""
    p = [(float(x), float(y)) for x, y in pts]
    cx, cy = sum(x for x, _ in p) / 4.0, sum(y for _, y in p) / 4.0
    ring = sorted(p, key=lambda q: math.atan2(q[1] - cy, q[0] - cx))  # senso orario sullo schermo (y verso il basso)
    start = min(range(4), key=lambda i: ring[i][0] + ring[i][1])
    return ring[start:] + ring[:start]


def rotate(corners, quarter_turns):
    """La foto è stata fatta da un lato della macchina: sposta di un quarto di giro quale angolo è l'origine."""
    n = int(quarter_turns) % 4
    return list(corners[n:]) + list(corners[:n])


def check_corners(pts, size):
    """None se i 4 punti vanno bene, altrimenti il motivo ("few", "close", "flat", "crossed")."""
    if len(pts) != 4:
        return "few"
    w, h = size
    c = order_corners(pts)
    side = min(math.dist(c[i], c[(i + 1) % 4]) for i in range(4))
    if side < 0.03 * max(w, h):
        return "close"  # due punti quasi nello stesso posto
    area = abs(sum(c[i][0] * c[(i + 1) % 4][1] - c[(i + 1) % 4][0] * c[i][1] for i in range(4))) / 2.0
    if area < 0.01 * w * h:
        return "flat"  # punti quasi in fila: non è un'area

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    turns = [cross(c[i], c[(i + 1) % 4], c[(i + 2) % 4]) for i in range(4)]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        return "crossed"  # un angolo rientra: i 4 punti non sono gli angoli di un rettangolo visto di sbieco
    return None


def homography(corners, bed, ppm=2.0):
    """corners: [alto-sx, alto-dx, basso-dx, basso-sx] nella foto, cioè gli angoli (0, Ymax), (Xmax, Ymax),
    (Xmax, 0), (0, 0) del piano. -> matrice foto -> immagine del piano vista dall'alto."""
    W, H = bed_pixels(bed, ppm)
    src = np.array(corners, np.float32)
    dst = np.array([(0, 0), (W, 0), (W, H), (0, H)], np.float32)
    return cv2.getPerspectiveTransform(src, dst)


def rectify(frame, corners, bed, ppm=2.0):
    """La foto raddrizzata sull'area di lavoro (riga 0 = Y massimo, colonna 0 = X 0)."""
    W, H = bed_pixels(bed, ppm)
    return cv2.warpPerspective(frame, homography(corners, bed, ppm), (W, H), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=BACK)


def to_bed(corners, bed, pts):
    """Punti della foto -> millimetri sul piano (per le prove e per sapere dove cade un punto)."""
    Hm = homography(corners, bed, 1.0)
    out = cv2.perspectiveTransform(np.array(pts, np.float32).reshape(-1, 1, 2), Hm).reshape(-1, 2)
    return [(float(x), float(bed_pixels(bed, 1.0)[1] - y)) for x, y in out]
