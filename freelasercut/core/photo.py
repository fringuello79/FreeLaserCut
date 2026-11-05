# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Preparazione delle foto per l'incisione (senza interfaccia: si prova da sola).

Lavora sull'immagine originale e restituisce una nuova immagine in scala di grigi: ritaglio,
orientamento, rimozione di uno sfondo uniforme, riduzione del rumore, livelli automatici,
contrasto locale, nitidezza, forma (ovale/arrotondata) e bordi sfumati. Luminosità, contrasto e
gamma restano sulla forma (non distruttivi) e il metodo di incisione resta sul livello, come prima.

Bianco = niente laser: lo sfondo tolto e i bordi sfumati diventano bianchi.
Contiene anche la conversione automatica di una foto in linee e riempimenti (vettoriale).
"""
from dataclasses import asdict, dataclass, fields

import cv2
import numpy as np
from PIL import Image

from freelasercut.i18n import tr  # noqa: E402

MASKS = ("none", "oval", "rounded")


@dataclass
class PhotoSettings:
    crop: tuple = (0.0, 0.0, 1.0, 1.0)  # x0, y0, x1, y1 in frazioni dell'immagine orientata (y dall'alto)
    rotate: int = 0  # 0, 90, 180, 270 gradi (senso orario)
    flip: bool = False  # specchio orizzontale
    bg_remove: bool = False
    bg_tolerance: float = 18.0  # 0..100
    denoise: float = 0.0  # 0..100
    auto_levels: bool = False
    local_contrast: float = 0.0  # 0..100 (CLAHE)
    sharpen: float = 0.0  # 0..100
    mask: str = "none"  # none | oval | rounded
    edge_fade: float = 0.0  # 0..100: % del lato corto sfumato verso il bianco
    # effetto artistico (photo_fx.EFFECTS): matita, carboncino, china, fumetto, linee, puntinismo…
    effect: str = "none"
    effect_strength: float = 50.0  # 0..100
    effect_detail: float = 50.0  # 0..100
    effect_angle: int = 0  # direzione delle righe (0, 45, 90, 135)
    # larghezza della foto sul materiale (mm): gli effetti la usano per dare a righe e punti le misure giuste;
    # 0 = non nota (10 punti/mm). Non è una modifica della foto (vedi is_identity)
    width_mm: float = 0.0

    def to_dict(self):
        d = asdict(self)
        d["crop"] = list(self.crop)
        return d

    @classmethod
    def from_dict(cls, d):
        if not d:
            return cls()
        names = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in d.items() if k in names})
        s.crop = tuple(float(v) for v in s.crop) if len(tuple(s.crop)) == 4 else (0.0, 0.0, 1.0, 1.0)
        s.rotate = int(s.rotate) % 360 // 90 * 90
        if s.mask not in MASKS:
            s.mask = "none"
        from .photo_fx import ANGLES, EFFECTS

        if s.effect not in EFFECTS:
            s.effect = "none"
        if s.effect_angle not in ANGLES:
            s.effect_angle = 0
        return s

    def is_identity(self):
        from dataclasses import replace

        return replace(self, width_mm=0.0) == PhotoSettings()


# --------------------------------------------------------------------------- preset per materiale
# Solo parametri dell'immagine (metodo, gamma, contrasto, negativo, risoluzione): velocità e potenza
# dipendono dalla macchina e stanno nella libreria materiali.
PRESETS = {
    "wood_light": (tr("Legno chiaro (betulla, pioppo, faggio)"),
                   dict(dither="jarvis", dpi=254.0, negative=False, gamma=1.3, contrast=10.0)),
    "wood_dark": (tr("Legno scuro (noce, ciliegio)"), dict(dither="stucki", dpi=254.0, negative=False, gamma=1.1, contrast=25.0)),
    "slate": (tr("Ardesia, pietra (il laser schiarisce)"), dict(dither="jarvis", dpi=254.0, negative=True, gamma=1.0, contrast=15.0)),
    "leather": (tr("Cuoio, pelle"), dict(dither="stucki", dpi=254.0, negative=False, gamma=1.2, contrast=10.0)),
    "paper": (tr("Carta, cartoncino"), dict(dither="floyd", dpi=254.0, negative=False, gamma=1.4, contrast=0.0)),
    "anodized": (tr("Alluminio anodizzato nero (il laser schiarisce)"),
                 dict(dither="jarvis", dpi=318.0, negative=True, gamma=1.0, contrast=10.0)),
    "grayscale": (tr("Scala di grigi (macchine con potenza regolabile fine)"),
                  dict(dither="grayscale", dpi=254.0, negative=False, gamma=1.0, contrast=0.0)),
}


# --------------------------------------------------------------------------- elaborazione
def to_gray(pil):
    """PIL -> (grigio uint8, alfa 0..1 float32 o None). La trasparenza va sul bianco."""
    if pil.mode in ("RGBA", "LA", "P", "PA"):
        rgba = np.asarray(pil.convert("RGBA")).astype(np.float32)
        a = rgba[..., 3] / 255.0
        lum = 0.299 * rgba[..., 0] + 0.587 * rgba[..., 1] + 0.114 * rgba[..., 2]
        g = lum * a + 255.0 * (1.0 - a)
        return np.clip(g, 0, 255).astype(np.uint8), a
    return np.asarray(pil.convert("L")).copy(), None


def orient(arr, rotate, flip):
    if flip:
        arr = arr[:, ::-1]
    k = (rotate // 90) % 4
    if k:
        arr = np.rot90(arr, -k)  # senso orario
    return np.ascontiguousarray(arr)


def crop_px(shape, crop):
    h, w = shape[:2]
    x0, y0, x1, y1 = crop
    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
    a, b = int(round(x0 * w)), int(round(x1 * w))
    c, d = int(round(y0 * h)), int(round(y1 * h))
    if b - a < 4 or d - c < 4:  # ritaglio troppo piccolo: si ignora
        return 0, 0, w, h
    return a, c, b, d


def background_mask(rgb_or_gray, tolerance):
    """Sfondo uniforme: i pixel simili al colore dei bordi E collegati ai bordi. Ritorna 0..1 (1 = sfondo)."""
    img = rgb_or_gray
    if img.ndim == 2:
        img = img[..., None]
    h, w = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32) if img.shape[2] == 3 else img.astype(np.float32)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]).reshape(-1, lab.shape[2])
    ref = np.median(border, axis=0)
    dist = np.sqrt(((lab - ref) ** 2).sum(axis=2))
    thr = 4.0 + tolerance * 1.2  # 0..100 -> 4..124 (distanza nel colore Lab, 255 = estremi)
    similar = (dist <= thr).astype(np.uint8)
    # solo le zone simili collegate al bordo (il bianco di un occhio in mezzo al viso resta)
    n, lbl = cv2.connectedComponents(similar, connectivity=4)
    edge = set(np.unique(np.concatenate([lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1]])).tolist()) - {0}
    bg = np.isin(lbl, list(edge)) if edge else np.zeros((h, w), bool)
    m = bg.astype(np.float32)
    r = max(1, int(round(min(h, w) / 400)))
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)  # i puntini di rumore nello sfondo non restano grigi
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    return cv2.GaussianBlur(m, (0, 0), max(0.8, r))  # bordo morbido, niente scalini


def shape_mask(h, w, mask, fade):
    """Forma e bordi sfumati: 1 = foto, 0 = bianco."""
    m = np.ones((h, w), np.float32)
    fade_px = fade / 100.0 * min(h, w) * 0.5
    if mask == "oval":
        m = np.zeros((h, w), np.float32)
        cv2.ellipse(m, (w // 2, h // 2), (max(1, w // 2 - 1), max(1, h // 2 - 1)), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
    elif mask == "rounded":
        m = np.zeros((h, w), np.float32)
        r = int(min(h, w) * 0.12)
        cv2.rectangle(m, (r, 0), (w - 1 - r, h - 1), 1.0, -1)
        cv2.rectangle(m, (0, r), (w - 1, h - 1 - r), 1.0, -1)
        for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
            cv2.circle(m, (cx, cy), r, 1.0, -1, cv2.LINE_AA)
    if fade_px >= 1:
        # distanza dal bordo della forma -> sfumatura lineare verso il bianco
        inside = (m > 0.5).astype(np.uint8)
        inside[0, :] = inside[-1, :] = 0
        inside[:, 0] = inside[:, -1] = 0
        d = cv2.distanceTransform(inside, cv2.DIST_L2, 5)
        m = np.minimum(m, np.clip(d / fade_px, 0.0, 1.0))
    return m


def process(pil, st):
    """Immagine originale (PIL) + PhotoSettings -> nuova immagine PIL 'L' pronta per il livello Immagine."""
    gray, alpha = to_gray(pil)
    rgb = np.asarray(pil.convert("RGB")) if (st.bg_remove and pil.mode not in ("L", "1", "I", "F")) else None
    gray = orient(gray, st.rotate, st.flip)
    if alpha is not None:
        alpha = orient(alpha, st.rotate, st.flip)
    if rgb is not None:
        rgb = orient(rgb, st.rotate, st.flip)
    a, c, b, d = crop_px(gray.shape, st.crop)
    gray = gray[c:d, a:b]
    if alpha is not None:
        alpha = alpha[c:d, a:b]
    if rgb is not None:
        rgb = rgb[c:d, a:b]
    h, w = gray.shape
    keep = np.ones((h, w), np.float32)  # 1 = foto, 0 = bianco
    if alpha is not None:
        keep = np.minimum(keep, alpha)
    if st.bg_remove:
        keep = np.minimum(keep, 1.0 - background_mask(rgb if rgb is not None else gray, st.bg_tolerance))
    g = gray.astype(np.float32)
    if st.denoise > 0:
        sig = 10.0 + st.denoise * 0.9
        d = max(3, int(round(3 + st.denoise / 25)))
        g = cv2.bilateralFilter(g, d, sig, sig * 0.08 + 1.0)
    if st.auto_levels:
        sel = g[keep > 0.5] if (keep > 0.5).any() else g.ravel()
        lo, hi = np.percentile(sel, (0.5, 99.5))
        if hi - lo > 8:
            g = (g - lo) * (255.0 / (hi - lo))
    g = np.clip(g, 0, 255)
    if st.local_contrast > 0:
        clahe = cv2.createCLAHE(clipLimit=1.0 + st.local_contrast / 25.0, tileGridSize=(8, 8))
        g = clahe.apply(g.astype(np.uint8)).astype(np.float32)
    if st.sharpen > 0:
        sigma = max(1.0, min(h, w) / 600.0)
        blur = cv2.GaussianBlur(g, (0, 0), sigma)
        g = g + (st.sharpen / 50.0) * (g - blur)
    if st.effect and st.effect != "none":
        from . import photo_fx

        # dopo le regolazioni, prima di forma e sfondo (che restano bianchi, cioè senza righe né punti)
        g, scale = photo_fx.apply(np.clip(g, 0, 255).astype(np.float32), st.effect, st.width_mm,
                                  st.effect_strength / 100.0, st.effect_detail / 100.0, st.effect_angle)
        if scale != 1.0:  # foto molto definita: l'effetto è stato calcolato più piccolo (basta per il laser)
            h, w = g.shape
            keep = cv2.resize(keep, (w, h), interpolation=cv2.INTER_AREA)
    keep = np.minimum(keep, shape_mask(h, w, st.mask, st.edge_fade))
    g = g * keep + 255.0 * (1.0 - keep)
    return Image.fromarray(np.clip(np.rint(g), 0, 255).astype(np.uint8), "L")


def engrave_preview(pil, w_mm, h_mm, dpi, dither, brightness=0.0, contrast=0.0, gamma=1.0, negative=False,
                    halftone_cell=1.0, halftone_angle=45.0, max_dots=900_000, region=None):
    """Come verrà incisa: i punti veri alla risoluzione del livello (0 = bianco, 1 = punto acceso / nero).

    region: (x0, y0, x1, y1) in frazioni per vedere una zona a grandezza reale; senza, tutta la foto
    (ridotta se i punti sono troppi: ritorna anche il fattore di riduzione)."""
    from . import imaging

    dark = imaging.to_dark(pil)
    H, W = dark.shape
    step = 25.4 / max(dpi, 10.0)
    nx, ny = max(1, int(round(w_mm / step))), max(1, int(round(h_mm / step)))
    k = 1.0
    if region is not None:
        x0, y0, x1, y1 = region
        a, b = int(x0 * W), max(int(x1 * W), int(x0 * W) + 1)
        c, d = int(y0 * H), max(int(y1 * H), int(y0 * H) + 1)
        dark = dark[c:d, a:b]
        nx, ny = max(1, int(round(nx * (x1 - x0)))), max(1, int(round(ny * (y1 - y0))))
    elif nx * ny > max_dots:
        k = (max_dots / (nx * ny)) ** 0.5
        nx, ny = max(1, int(nx * k)), max(1, int(ny * k))
    interp = cv2.INTER_AREA if nx < dark.shape[1] else cv2.INTER_LINEAR
    grid = cv2.resize(dark.astype(np.float32), (nx, ny), interpolation=interp)
    grid = imaging.adjust(grid, brightness, contrast, gamma, negative)
    cell_px = max(halftone_cell / step * k, 2.0)
    return imaging.dither(grid, dither, cell_px, halftone_angle), k


def dots_count(w_mm, h_mm, dpi):
    step = 25.4 / max(dpi, 10.0)
    return (w_mm / step) * (h_mm / step)


# --------------------------------------------------------------------------- foto -> linee e riempimenti
def to_vectors(pil, w_mm, h_mm, tones=2, detail=0.5, smooth=0.5, outlines=True, edges=False, min_size_mm=0.5,
               brightness=0.0, contrast=0.0, gamma=1.0):
    """Foto -> tracciati vettoriali divisi per livello.

    tones: quante tonalità di riempimento (1..4): fasce di scuro separate (la più scura con più potenza),
    senza sovrapposizioni. outlines: contorno delle zone scure come linea. edges: linee dei dettagli
    (bordi netti della foto, linea centrale). Ritorna dict con 'fills' = [(QPainterPath, scuro 0..1)]
    dal più chiaro al più scuro, 'outline' e 'edges' = QPainterPath o None, 'thresholds'."""
    from . import imaging, trace

    dark = imaging.adjust(imaging.to_dark(pil), brightness, contrast, gamma)
    # leggera sfocatura: le fasce non devono seguire la grana della foto
    H, W = dark.shape
    px_mm = W / max(w_mm, 1e-6)
    sig = max(0.6, (1.0 - detail) * 0.8 * px_mm)  # fasce morbide, non la grana della foto
    dark = cv2.GaussianBlur(dark.astype(np.float32), (0, 0), sig)
    tones = max(1, min(int(tones), 4))
    v = dark[dark > 0.04]
    if v.size < 16:
        return {"fills": [], "outline": None, "edges": None, "thresholds": []}
    if tones == 1:
        ts = [trace.otsu(dark)]
    else:
        # soglie ai quantili delle zone non bianche: fasce con aree simili
        qs = np.linspace(0, 1, tones + 2)[1:-1]
        ts = sorted(set(round(float(t), 3) for t in np.quantile(v, qs)))
    fills = []
    for i, t in enumerate(ts):
        hi = ts[i + 1] if i + 1 < len(ts) else None
        band = (dark >= t) & (dark < hi) if hi is not None else (dark >= t)
        bd = np.where(band, 1.0, 0.0).astype(np.float32)
        path, _ = trace.trace(bd, w_mm, h_mm, "outline", threshold=0.5, detail=detail, smooth=smooth,
                              min_size_mm=min_size_mm)
        if not path.isEmpty():
            mean = float(dark[band].mean()) if band.any() else t
            fills.append((path, mean))
    outline = None
    if outlines:
        t0 = ts[0]
        path, _ = trace.trace(np.where(dark >= t0, 1.0, 0.0).astype(np.float32), w_mm, h_mm, "outline", threshold=0.5,
                              detail=detail, smooth=smooth, min_size_mm=min_size_mm)
        outline = path if not path.isEmpty() else None
    edge_path = None
    if edges:
        g = np.clip((1.0 - dark) * 255, 0, 255).astype(np.uint8)
        lo = int(30 + (1.0 - detail) * 60)
        e = cv2.Canny(g, lo, lo * 2.5)
        e = cv2.dilate(e, np.ones((3, 3), np.uint8))
        path, _ = trace.trace((e > 0).astype(np.float32), w_mm, h_mm, "centerline", threshold=0.5, detail=detail,
                              smooth=smooth, min_size_mm=max(min_size_mm, 1.0))
        edge_path = path if not path.isEmpty() else None
    return {"fills": fills, "outline": outline, "edges": edge_path, "thresholds": ts}
