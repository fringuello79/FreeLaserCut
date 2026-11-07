# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Effetti artistici per le foto da incidere (senza interfaccia: si provano da soli).

Ogni effetto lavora sul grigio della foto (float32 0..255, bianco = niente laser) e restituisce un grigio della
stessa grandezza. Le misure degli effetti (larghezza delle righe, grandezza dei punti, morbidezza dei tratti)
sono in millimetri sul materiale: così l'anteprima ridotta e la foto vera danno lo stesso risultato, e il passo
delle righe resta quello scelto qualunque sia la risoluzione della foto.

strength e detail vanno da 0 a 1 (i due cursori della finestra «Prepara foto»); angle in gradi per le righe.
"""
import cv2
import numpy as np

from freelasercut.i18n import tr  # noqa: E402

# chiave: (nome, ha la direzione delle righe, testo del cursore «dettaglio»)
EFFECTS = {
    "none": (tr("Nessuno"), False, ""),
    "pencil": (tr("Matita"), False, tr("Finezza del tratto")),
    "drawing": (tr("Ritratto a matita"), False, tr("Dettaglio")),
    "sketch": (tr("Schizzo del soggetto (sfondo tolto)"), False, tr("Dettaglio")),
    "charcoal": (tr("Carboncino"), False, tr("Finezza del tratto")),
    "ink": (tr("China (contorni)"), False, tr("Dettaglio")),
    "cartoon": (tr("Fumetto"), False, tr("Numero di toni")),
    "lines": (tr("Incisione a linee"), True, tr("Righe fitte")),
    "waves": (tr("Linee ondulate"), True, tr("Righe fitte")),
    "stipple": (tr("Puntinismo"), False, tr("Punti piccoli")),
    "posterize": (tr("Posterizza"), False, tr("Numero di toni")),
    "emboss": (tr("Rilievo"), False, tr("Dettaglio")),
}
ANGLES = (0, 45, 90, 135)
# lavoro al massimo a questa risoluzione (punti per mm): oltre i 254-318 dpi del laser non serve, e su una foto da
# 24 megapixel gli effetti più pesanti (fumetto, carboncino) resterebbero veloci
WORK_PX_PER_MM = 14.0


def _px(mm, ppm, lo=0.5):
    return max(lo, mm * ppm)


def _blur(g, sigma):
    return cv2.GaussianBlur(g, (0, 0), max(0.3, sigma))


def _darkness(g, ppm, contrast=1.0):
    """0 = bianco, 1 = nero, con i toni allargati (le foto spente danno comunque righe e punti ben distinti)."""
    s = _blur(g, _px(0.12, ppm))
    lo, hi = np.percentile(s, (1, 99))
    if hi - lo > 8:
        s = (s - lo) * (255.0 / (hi - lo))
    d = 1.0 - np.clip(s, 0, 255) / 255.0
    return np.clip(d, 0, 1) ** contrast


def _levels(g, levels):
    """Pochi toni piatti; il più chiaro è bianco pieno (lo sfondo chiaro non si incide), il più scuro nero."""
    idx = np.clip(np.floor(g / 256.0 * levels), 0, levels - 1)
    return (255.0 * (1.0 - (levels - 1 - idx) / (levels - 1))).astype(np.float32)


def pencil(g, ppm, strength, detail):
    """Schizzo a matita: la foto divisa per il suo negativo sfocato (si vedono solo i passaggi di tono)."""
    blur = _px(0.25 + (1.0 - detail) * 1.6, ppm)
    inv = 255.0 - g
    b = _blur(inv, blur)
    sk = np.clip(g * 256.0 / np.maximum(256.0 - b, 1.0), 0, 255)
    k = 0.6 + strength * 1.8  # più forte = tratti più scuri
    return np.clip(255.0 - (255.0 - sk) * k, 0, 255)


def charcoal(g, ppm, strength, detail, seed=7):
    """Carboncino: tratti larghi e scuri, ombre della foto e trama della carta."""
    sk = pencil(g, ppm, 0.5, detail * 0.7) / 255.0
    sk = sk ** (1.6 + strength * 1.6)
    tone = cv2.createCLAHE(2.0, (8, 8)).apply(np.clip(_blur(g, _px(0.3, ppm)), 0, 255).astype(np.uint8))
    base = sk * (0.45 + 0.55 * tone.astype(np.float32) / 255.0)
    rng = np.random.default_rng(seed)
    h, w = g.shape
    grain = _blur(rng.normal(0, 1, (h, w)).astype(np.float32), _px(0.05, ppm, 0.6))
    streak = cv2.blur(rng.normal(0, 1, (h, w)).astype(np.float32), (1, max(3, int(_px(0.8, ppm)))))
    out = base + (grain * 0.05 + streak * 0.12) * (1.0 - base)
    return np.clip(out, 0, 1) * 255.0


def ink(g, ppm, strength, detail):
    """China: solo le linee principali, nere su bianco (differenza di gaussiane «estesa»)."""
    f = cv2.bilateralFilter(np.clip(g, 0, 255).astype(np.uint8), 7, 30, 5).astype(np.float32) / 255.0
    sigma = _px(0.06 + (1.0 - detail) * 0.35, ppm, 0.6)
    a, b = _blur(f, sigma), _blur(f, sigma * 1.6)
    eps = 0.002 - strength * 0.014  # più forte = più linee
    d = a - 0.985 * b
    out = np.where(d >= eps, 1.0, 1.0 + np.tanh(80.0 * (d - eps)))
    return np.where(out < 0.5, 0.0, 255.0).astype(np.float32)


def cartoon(g, ppm, strength, detail):
    """Fumetto: pochi toni piatti (foto lisciata) con i contorni a china sopra."""
    u8 = np.clip(g, 0, 255).astype(np.uint8)
    h, w = u8.shape
    small = cv2.resize(u8, (max(8, w // 2), max(8, h // 2)), interpolation=cv2.INTER_AREA)
    for _ in range(3 + int(strength * 6)):
        small = cv2.bilateralFilter(small, 9, 30, 7)
    sm = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    k = max(3, int(_px(0.35, ppm)) | 1)
    sm = cv2.medianBlur(sm, min(k, 15)).astype(np.float32)
    levels = 3 + int(round(detail * 4))  # 3..7 toni
    q = _levels(sm, levels)
    lines = ink(g, ppm, 0.35 + strength * 0.4, 0.35)
    return np.minimum(q, lines)


def lines(g, ppm, strength, detail, angle=0, wave=False):
    """Incisione a linee (come le banconote): righe parallele che si ingrossano dove la foto è scura."""
    h, w = g.shape
    period = _px(0.45 + (1.0 - detail) * 1.4, ppm, 3.0)  # passo delle righe sul materiale
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.deg2rad(angle)
    u = -xx * np.sin(t) + yy * np.cos(t)
    if wave:
        v = xx * np.cos(t) + yy * np.sin(t)
        u = u + period * 0.9 * np.sin(v / (period * 2.2))
    phase = (u / period) % 1.0
    dist = np.abs(phase - 0.5) * 2.0  # 0 al centro della riga, 1 tra due righe
    dark = _darkness(g, ppm, 1.5 - strength)
    return np.where(dist < dark * 0.95, 0.0, 255.0).astype(np.float32)


def stipple(g, ppm, strength, detail, seed=11):
    """Puntinismo: punti tondi (misura in mm), più fitti dove la foto è scura."""
    h, w = g.shape
    dot = _px(0.12 + (1.0 - detail) * 0.35, ppm, 1.0)  # diametro del punto
    cell = dot * 1.25
    gw, gh = max(1, int(w / cell)), max(1, int(h / cell))
    dark = cv2.resize(_darkness(g, ppm, 1.0), (gw, gh), interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng(seed)
    p = np.clip(dark ** (1.4 - strength * 0.8), 0, 1)  # più forte = più punti nei mezzitoni
    on = rng.random((gh, gw)) < p
    out = np.full((h, w), 255, np.uint8)
    ys, xs = np.nonzero(on)
    jit = rng.uniform(-0.18, 0.18, (len(xs), 2)) * cell
    r = max(1, int(round(dot / 2)))
    for (x, y), (jx, jy) in zip(zip(xs, ys), jit):
        cv2.circle(out, (int((x + 0.5) * cell + jx), int((y + 0.5) * cell + jy)), r, 0, -1, cv2.LINE_AA)
    return out.astype(np.float32)


def posterize(g, ppm, strength, detail):
    """Pochi toni netti: sul legno diventano livelli di bruciatura ben distinti."""
    u8 = np.clip(g, 0, 255).astype(np.uint8)
    sm = u8
    for _ in range(1 + int(strength * 4)):
        sm = cv2.bilateralFilter(sm, 9, 30, 7)
    levels = 2 + int(round(detail * 4))  # 2..6 toni
    return _levels(sm.astype(np.float32), levels)


def emboss(g, ppm, strength, detail):
    """Rilievo: la foto sembra sbalzata, con la luce da in alto a sinistra."""
    s = _blur(g, _px(0.05 + (1.0 - detail) * 0.4, ppm, 0.6))
    k = np.array([[-2, -1, 0], [-1, 0, 1], [0, 1, 2]], np.float32)
    e = cv2.filter2D(s, -1, k) * (0.6 + strength * 2.4) / max(1.0, ppm / 6.0)
    # solo le ombre si incidono: le zone piatte restano bianche (sul legno un grigio dappertutto brucerebbe tutto),
    # più un velo leggero della foto perché resti riconoscibile
    shade = np.minimum(e, 0.0) * 1.4
    veil = (255.0 - g) * 0.18
    return np.clip(255.0 + shade - veil, 0, 255)


# ------------------------------------------------------------------ ritratto a matita
# Come un disegno fatto a mano: contorni a tratti di matita che seguono i bordi (un po' più lunghi del bordo, come
# fa chi disegna), ombre a tratteggio diagonale (incrociato dove è più scuro) e la grana della carta. I chiari
# restano carta bianca: sul legno si incidono solo i tratti.

def _line_kernel(length, angle_deg, width=1):
    """Segmento lungo `length` pixel con l'angolo dato, normalizzato (somma 1): un tratto di matita."""
    n = int(length) | 1
    k = np.zeros((n, n), np.float32)
    c = n // 2
    t = np.deg2rad(angle_deg)
    dx, dy = np.cos(t) * c, -np.sin(t) * c
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1.0,
             max(1, int(width)), cv2.LINE_AA)
    return k / max(float(k.sum()), 1e-6)


def _pencil_strokes(s, ppm, detail):
    """Contorni a tratti: 1 = carta, 0 = tratto pieno. Ogni bordo è ripassato con un tratto nella sua direzione."""
    f = _blur(s, _px(0.08 + (1.0 - detail) * 0.25, ppm, 0.6)) / 255.0
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    # le piccole variazioni (pelle, grana, rumore della foto) non diventano tratti: soglia relativa alla foto, ma mai
    # sotto un minimo assoluto (su uno sfondo quasi bianco il rumore non deve sembrare un bordo)
    mag = np.maximum(mag - max(float(np.percentile(mag, 70)) * (1.2 - detail * 0.8), _EDGE_FLOOR), 0)
    length = _px(0.9 + (1.0 - detail) * 1.6, ppm, 5)
    width = max(1, int(round(0.07 * ppm)))
    kernels = [_line_kernel(length, i * 22.5, width) for i in range(8)]
    # direzione di ogni bordo: la più forte delle 8 (un filtro alla volta, per non tenere 8 copie della foto)
    best = np.zeros(mag.shape, np.uint8)
    top = cv2.filter2D(mag, -1, kernels[0])
    for i in range(1, 8):
        r = cv2.filter2D(mag, -1, kernels[i])
        better = r > top
        best[better] = i
        np.maximum(top, r, out=top)
    del top
    out = np.zeros_like(mag)
    for i, k in enumerate(kernels):
        out += cv2.filter2D(np.where(best == i, mag, 0).astype(np.float32), -1, k)
    norm = max(float(np.percentile(out, 99.5)), _STROKE_FULL)
    strokes = 1.0 - np.clip(out / norm, 0, 1)
    # niente tratti dove intorno è tutto (quasi) bianco: lo sfondo chiaro resta carta
    k = max(3, int(length) | 1)
    near = cv2.erode(s.astype(np.float32), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    gate = np.clip((_PAPER - near) / 10.0, 0, 1)
    return 1.0 - (1.0 - strokes) * gate


# soglie assolute dei contorni (gradiente di Sobel sul grigio 0..1 già sfumato)
_EDGE_FLOOR = 0.04
_STROKE_FULL = 0.25
_PAPER = 247.0  # sopra questo grigio, con tutto il vicinato chiaro, è carta


def _pencil_tones(strength):
    """Distribuzione dei toni di un disegno a matita: tanta carta chiara, mezzi toni distesi, poche ombre piene."""
    v = np.arange(256, dtype=np.float64)
    bright = np.exp(-(255.0 - v) / 9.0) / 9.0
    mid = ((v >= 105) & (v <= 225)) / 120.0
    dark = np.exp(-(v - 90.0) ** 2 / (2 * 11.0 ** 2)) / (11.0 * np.sqrt(2 * np.pi))
    p = (0.52 - 0.3 * strength) * bright + (0.37 + 0.12 * strength) * mid + (0.11 + 0.18 * strength) * dark
    p = np.convolve(p, np.ones(9) / 9.0, "same")
    return np.cumsum(p) / p.sum()


def _hatching(shape, ppm, angle, rng):
    """Trama di tratti paralleli (rumore «strisciato» nella direzione della mano), media 0. Si disegna sempre a
    WORK_PX_PER_MM e poi si porta alla grandezza della foto: anteprima ridotta e foto vera hanno la stessa trama."""
    h, w = shape
    hw, hh = _mm_grid(shape, ppm)
    t = cv2.filter2D(rng.random((hh, hw), dtype=np.float32), -1,
                     _line_kernel(_px(2.5, WORK_PX_PER_MM, 9), angle, 1))
    t = cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA if hw > w else cv2.INTER_LINEAR)
    return (t - t.mean()) / (t.std() + 1e-6)


def _mm_grid(shape, ppm):
    h, w = shape
    sc = WORK_PX_PER_MM / ppm
    return max(8, int(round(w * sc))), max(8, int(round(h * sc)))


def drawing(g, ppm, strength, detail, seed=5):
    """Ritratto a matita: contorni a tratti + ombre a tratteggio + grana della carta."""
    s = cv2.bilateralFilter(np.clip(g, 0, 255).astype(np.uint8), int(min(max(_px(0.5, ppm), 3), 15)) | 1, 25,
                            _px(0.35, ppm, 1.0))
    lo, hi = (float(v) for v in np.percentile(s, (1, 99.5)))
    sf = s.astype(np.float32)
    lin = np.clip((sf - lo) * 255.0 / (hi - lo), 0, 255) if hi - lo > 8 else sf
    # toni: metà quelli della foto, metà quelli tipici di un disegno a matita
    hist = np.bincount(s.ravel(), minlength=256).astype(np.float64)
    lut = np.searchsorted(_pencil_tones(strength), np.cumsum(hist) / hist.sum()).clip(0, 255).astype(np.float32)
    J = _blur(0.5 * lut[s] + 0.5 * lin, _px(0.15, ppm)) / 255.0
    d = np.clip(1.0 - J, 0, 1)
    d = d * d * (3 - 2 * d)  # chiari ancora più chiari (carta), ombre piene
    d = np.clip(d * (0.75 + 0.5 * strength), 0, 1)
    d = d * np.clip((250.0 - sf) / 12.0, 0, 1)  # il bianco della foto resta carta (lo sfondo non si incide)
    rng = np.random.default_rng(seed)
    h1 = _hatching(g.shape, ppm, 45, rng)
    h2 = _hatching(g.shape, ppm, 135, rng)
    t1 = 1.0 - np.clip(d * 1.25, 0, 1) * np.clip(0.55 + 0.35 * h1, 0, 1)  # tratteggio dei mezzi toni
    t2 = 1.0 - np.clip((d - 0.35) * 1.8, 0, 1) * np.clip(0.55 + 0.35 * h2, 0, 1)  # incrociato nelle ombre
    strokes = _pencil_strokes(sf, ppm, detail) ** (0.6 + strength * 1.2)
    hw, hh = _mm_grid(g.shape, ppm)
    paper = cv2.resize(_blur(rng.standard_normal((hh, hw), dtype=np.float32), _px(0.04, WORK_PX_PER_MM, 0.6)),
                       (g.shape[1], g.shape[0]), interpolation=cv2.INTER_AREA if hw > g.shape[1] else cv2.INTER_LINEAR)
    paper /= paper.std() + 1e-6
    out = strokes * t1 * t2 * (1.0 - 0.04 * np.clip(paper, -2, 2) * d)
    return np.clip(out, 0, 1) * 255.0


# ------------------------------------------------------------------ schizzo del soggetto (sfondo tolto)
# Come uno schizzo a matita o a penna: il soggetto in primo piano con i contorni, ombre a tratteggio regolare (incrociato
# solo nelle ombre più scure), occhi e ombre profonde pieni, tanta carta bianca e lo sfondo che sparisce. Il soggetto lo
# trova core/subject.py con GrabCut di OpenCV: aiuti disegnati da chi prepara la foto (riquadro, «tieni», «togli») o,
# senza aiuti, il riquadro centrale della foto. Niente intelligenza artificiale, niente dati scaricati.
from . import subject as _subject  # noqa: E402

_MASK_CACHE = _subject._CACHE


def subject_mask(rgb, hints=None):
    """1 = soggetto in primo piano, 0 = sfondo (stessa grandezza della foto), o None se non c'è un soggetto chiaro."""
    return _subject.subject_mask(rgb, hints)


def _streaks(shape, ppm, angle, rng, length_mm):
    """Tratti di grafite nella direzione della mano (rumore «strisciato», media 0), disegnati a WORK_PX_PER_MM:
    anteprima ridotta e foto vera hanno la stessa trama."""
    h, w = shape
    hw, hh = _mm_grid(shape, ppm)
    t = cv2.filter2D(rng.random((hh, hw), dtype=np.float32), -1, _line_kernel(_px(length_mm, WORK_PX_PER_MM, 9), angle, 1))
    t = cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA if hw > w else cv2.INTER_LINEAR)
    return (t - t.mean()) / (t.std() + 1e-6)


def sketch(g, ppm, strength, detail, rgb=None, seed=3, hints=None):
    """Schizzo del soggetto a matita: grafite sfumata a tratti, contorni, scuri pieni, grana della carta, sfondo bianco."""
    if rgb is None or rgb.shape[:2] != g.shape:
        rgb = np.dstack([np.clip(g, 0, 255).astype(np.uint8)] * 3)
    m = subject_mask(rgb, hints)
    s = cv2.bilateralFilter(np.clip(g, 0, 255).astype(np.uint8), int(min(max(_px(0.4, ppm), 3), 15)) | 1, 20,
                            _px(0.3, ppm, 1.0))
    sf = s.astype(np.float32)
    if m is None:
        m = np.ones_like(sf)
    sel = sf[m > 0.5] if (m > 0.5).any() else sf.ravel()
    lo, hi = (float(v) for v in np.percentile(sel, (1, 99)))
    lin = np.clip((sf - lo) * 255.0 / max(hi - lo, 8.0), 0, 255) / 255.0  # toni del soggetto, non dello sfondo
    lin = _blur(lin, _px(0.25, ppm, 0.6))
    # quanta grafite: i chiari restano carta, le ombre vere si scuriscono (Intensità = più scuro)
    d = np.clip((1.0 - lin) ** (1.5 - 0.5 * strength) * (0.55 + 0.35 * strength), 0, 1)
    rng = np.random.default_rng(seed)
    # tratti lunghi e corti nella stessa direzione della mano; nelle ombre più scure un secondo strato incrociato
    t1 = np.clip(0.5 + 0.22 * (0.6 * _streaks(sf.shape, ppm, 60, rng, 3.0) + 0.4 * _streaks(sf.shape, ppm, 60, rng, 1.2)),
                 0, 1)
    t2 = np.clip(0.5 + 0.25 * _streaks(sf.shape, ppm, 150, rng, 2.0), 0, 1)
    # grana della carta: la grafite non entra nei «dentini» più bassi
    hw, hh = _mm_grid(sf.shape, ppm)
    paper = cv2.resize(_blur(rng.standard_normal((hh, hw)).astype(np.float32), _px(0.05, WORK_PX_PER_MM, 0.6)),
                       (sf.shape[1], sf.shape[0]), interpolation=cv2.INTER_AREA if hw > sf.shape[1] else cv2.INTER_LINEAR)
    paper = np.clip(0.5 + 0.18 * paper / (paper.std() + 1e-6), 0, 1)
    # la grafite copre in proporzione allo scuro; tratti e carta la rendono irregolare (mai un grigio piatto)
    l1 = np.clip(d * 1.5 * (0.15 + 0.85 * t1) * (0.7 + 0.6 * (paper - 0.5)), 0, 1)
    l2 = np.clip(np.clip((d - 0.45) * 1.8, 0, 1) * (0.1 + 0.9 * t2) * 1.3, 0, 1)
    tone = (1.0 - 0.85 * l1) * (1.0 - 0.6 * l2)
    # contorni: differenza di sfocature (lineamenti) e tratti di matita lungo i bordi più forti (Dettaglio = più fini)
    sig = _px(0.10 + 0.22 * (1.0 - detail), ppm, 0.7)
    e = (_blur(sf, sig) - 0.985 * _blur(sf, sig * 1.6)) / 255.0
    xd = np.clip(np.where(e >= 0.0, 1.0, 1.0 + np.tanh((50.0 + 70.0 * strength) * e)), 0, 1)
    strokes = _pencil_strokes(sf, ppm, 0.35 + 0.45 * detail) ** (0.5 + 0.5 * strength)
    deep = np.clip((0.12 - lin) / 0.1, 0, 1) * (0.45 + 0.3 * strength)  # occhi, naso, ombre profonde
    out = tone * (0.45 + 0.55 * xd) * strokes * (1.0 - deep)
    mm = np.clip((_blur(m, _px(1.2, ppm, 2)) - 0.15) / 0.7, 0, 1)  # il disegno sfuma nella carta fuori dal soggetto
    out = 1.0 - (1.0 - out) * mm
    out = np.where(sf >= 252.0, np.maximum(out, 1.0), out)  # il bianco della foto resta carta
    return np.clip(out, 0, 1) * 255.0


_FUNCS = {"pencil": pencil, "drawing": drawing, "sketch": sketch, "charcoal": charcoal, "ink": ink, "cartoon": cartoon, "stipple": stipple,
          "posterize": posterize, "emboss": emboss}


def apply(g, effect, width_mm, strength=0.5, detail=0.5, angle=0, rgb=None, hints=None):
    """g: grigio float32 0..255. width_mm: larghezza della foto sul materiale (0 = sconosciuta, 10 punti/mm).
    -> (grigio, fattore di scala usato): per le foto molto definite l'effetto si calcola a WORK_PX_PER_MM."""
    if effect not in EFFECTS or effect == "none":
        return g, 1.0
    h, w = g.shape
    ppm = w / width_mm if width_mm and width_mm > 0 else 10.0
    scale = 1.0
    if ppm > WORK_PX_PER_MM:
        scale = WORK_PX_PER_MM / ppm
        size = (max(8, int(round(w * scale))), max(8, int(round(h * scale))))
        g = cv2.resize(g, size, interpolation=cv2.INTER_AREA)
        if rgb is not None:
            rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
        ppm = WORK_PX_PER_MM
    strength = float(min(max(strength, 0.0), 1.0))
    detail = float(min(max(detail, 0.0), 1.0))
    if effect in ("lines", "waves"):
        out = lines(g, ppm, strength, detail, angle if angle in ANGLES else 0, wave=effect == "waves")
    elif effect == "sketch":  # i colori aiutano a trovare il soggetto
        out = sketch(g, ppm, strength, detail, rgb, hints=hints)
    else:
        out = _FUNCS[effect](g, ppm, strength, detail)
    return np.clip(out, 0, 255).astype(np.float32), scale
