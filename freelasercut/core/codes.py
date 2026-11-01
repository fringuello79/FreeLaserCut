# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Codici QR e codici a barre come forme vettoriali da incidere (in riempimento).

QR: libreria segno (BSD). Codici a barre 1D: libreria python-barcode (MIT). Qui si trasformano i moduli
in contorni puliti (moduli vicini uniti), con zona di rispetto e versione «in negativo» per i materiali
in cui il laser schiarisce (alluminio anodizzato, ardesia, legno verniciato scuro…).
"""
import pyclipper
from PySide6.QtGui import QPainterPath

from . import geom
from freelasercut.i18n import tr  # noqa: E402

KINDS = {  # codice -> (nome, 2D?)
    "qr": ("QR", True),
    "code128": ("Code 128", False),
    "ean13": ("EAN-13", False),
    "ean8": ("EAN-8", False),
    "upca": ("UPC-A", False),
    "code39": ("Code 39", False),
}
ECC = ("L", "M", "Q", "H")
S = 1000.0  # Clipper lavora in interi: µm


class CodeError(ValueError):
    pass


def _need(module, pip_name):
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise CodeError(tr("Manca la libreria «{0}»: riavvia FreeLaserCut da run_freelasercut.bat per installarla",
                           pip_name)) from exc


def qr_matrix(data, ecc="M"):
    segno = _need("segno", "segno")

    if not data:
        raise CodeError(tr("Scrivi il contenuto del codice"))
    try:
        q = segno.make(data, error=ecc.lower(), micro=False, boost_error=False)
    except Exception as exc:  # noqa: BLE001 - dati troppo lunghi o non codificabili
        raise CodeError(tr("Il QR non può contenere questi dati: {0}", exc)) from exc
    return [[bool(v) for v in row] for row in q.matrix]


def bars(kind, data):
    """Codice a barre 1D -> (stringa di moduli '1010…', testo leggibile)."""
    barcode = _need("barcode", "python-barcode")
    from barcode.errors import BarcodeError

    if not data:
        raise CodeError(tr("Scrivi il contenuto del codice"))
    name = {"code128": "code128", "ean13": "ean13", "ean8": "ean8", "upca": "upca", "code39": "code39"}[kind]
    try:
        kw = {"add_checksum": False} if kind == "code39" else {}
        b = barcode.get_barcode_class(name)(data, **kw)
        mods = b.build()[0]
        human = b.get_fullcode() if hasattr(b, "get_fullcode") else data
    except (BarcodeError, ValueError, TypeError, KeyError) as exc:
        hint = {"ean13": tr("12 o 13 cifre"), "ean8": tr("7 o 8 cifre"), "upca": tr("11 o 12 cifre"),
                "code39": tr("lettere maiuscole, cifre e - . $ / + % spazio")}.get(kind, "")
        raise CodeError(tr("Dati non validi per {0}{1}", KINDS[kind][0], f" ({hint})" if hint else "")) from exc
    return mods, human


def _union(rects):
    pc = pyclipper.Pyclipper()
    for x0, y0, x1, y1 in rects:
        pc.AddPath([(round(x0 * S), round(y0 * S)), (round(x1 * S), round(y0 * S)), (round(x1 * S), round(y1 * S)),
                    (round(x0 * S), round(y1 * S))], pyclipper.PT_SUBJECT, True)
    return pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO) if rects else []


def _invert(paths, x0, y0, x1, y1):
    pc = pyclipper.Pyclipper()
    pc.AddPath([(round(x0 * S), round(y0 * S)), (round(x1 * S), round(y0 * S)), (round(x1 * S), round(y1 * S)),
                (round(x0 * S), round(y1 * S))], pyclipper.PT_SUBJECT, True)
    if paths:
        pc.AddPaths(paths, pyclipper.PT_CLIP, True)
    return pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _to_path(paths):
    return geom.polys_to_path([geom.Poly([(x / S, y / S) for x, y in p], True) for p in paths])


def code_path(kind, data, w=30.0, h=None, ecc="M", quiet=2, invert=False, text=True, font="Arial"):
    """Forma del codice in mm. Origine nell'angolo in basso a sinistra della zona di rispetto.
    w = larghezza del simbolo (senza zona di rispetto); h = altezza delle barre (codici 1D)."""
    if kind not in KINDS:
        raise CodeError(tr("Tipo di codice sconosciuto"))
    quiet = max(0, int(quiet))
    if KINDS[kind][1]:
        m = qr_matrix(data, ecc)
        n = len(m)
        mod = w / n
        rects = []
        for r, row in enumerate(m):
            y1 = (n - r + quiet) * mod
            c = 0
            while c < n:
                if row[c]:
                    c0 = c
                    while c < n and row[c]:
                        c += 1
                    rects.append(((c0 + quiet) * mod, y1 - mod, (c + quiet) * mod, y1))
                else:
                    c += 1
        side = (n + 2 * quiet) * mod
        paths = _union(rects)
        if invert:
            paths = _invert(paths, 0, 0, side, side)
        return _to_path(paths)
    mods, human = bars(kind, data)
    mod = w / len(mods)
    h = float(h or max(8.0, w * 0.35))
    txt_h = 0.0
    tp = None
    if text and human:
        from . import text as textmod

        size = max(1.5, min(h * 0.22, mod * 9))
        tp = textmod.text_path(human, font, size, align="center")
        txt_h = size * 1.75
    rects = []
    i = 0
    while i < len(mods):
        if mods[i] == "1":
            i0 = i
            while i < len(mods) and mods[i] == "1":
                i += 1
            rects.append(((i0 + quiet) * mod, txt_h, (i + quiet) * mod, txt_h + h))
        else:
            i += 1
    total_w = (len(mods) + 2 * quiet) * mod
    paths = _union(rects)
    if invert:
        paths = _invert(paths, 0, 0, total_w, txt_h + h + quiet * mod)
    out = _to_path(paths)
    if tp is not None:
        tp.translate(total_w / 2, txt_h * 0.12)
        if invert:  # testo «in negativo»: già dentro il fondo inciso, va tolto dal fondo
            polys = geom.flatten(out, 0.01)
            tpolys = [p for p in geom.flatten(tp, 0.01) if p.closed]
            if tpolys:
                res = geom.boolean(polys, tpolys, "difference")
                return geom.polys_to_path(res)
        out.addPath(tp)
    return out
