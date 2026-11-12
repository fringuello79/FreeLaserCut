# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Mezzetinte (retino): le misure dei punti (0.19.0).

Il retino è una griglia di punti tondi distanti una «cella» l'uno dall'altro; ogni punto è grande quanto è scura la
foto in quel posto. Con «Dimensione del punto» al 100% l'area del punto è uguale allo scuro della foto (metà grigio =
punto che copre metà cella); con più di 100% tutti i punti sono più grossi (incisione più scura), con meno sono più
piccoli e staccati (più chiara). La distanza fra i punti non cambia.

Qui ci sono solo i conti (niente immagini): servono al programma per incidere e alle finestre per dire all'utente
quanto sono grandi i punti che sta per fare.
"""
import math

SIZE_MIN, SIZE_MAX, SIZE_DEFAULT = 50.0, 150.0, 100.0  # % del diametro del punto
LIGHT = 0.05  # lo «scuro» di una zona chiara della foto (5%): il punto più piccolo che ci si aspetta di vedere
FULL = math.sqrt(0.5)  # raggio (in celle) con cui i punti coprono tutta la cella: oltre non cresce più niente


def clamp_size(value):
    """La dimensione del punto in %, sempre un numero fra SIZE_MIN e SIZE_MAX (un file rovinato o di una versione
    futura non deve far inciampare l'incisione)."""
    try:
        s = float(value)
    except (TypeError, ValueError):
        return SIZE_DEFAULT
    if s != s or s in (float("inf"), float("-inf")):
        return SIZE_DEFAULT
    return min(SIZE_MAX, max(SIZE_MIN, s))


def radius(dark, size_pct=SIZE_DEFAULT):
    """Raggio del punto, in celle, per uno scuro 0..1."""
    return clamp_size(size_pct) / 100.0 * math.sqrt(min(1.0, max(0.0, dark)) / math.pi)


def dots(cell_mm, size_pct, dpi):
    """Le misure dei punti che verranno incisi. -> dict:
    step: distanza fra le righe (mm); cell: la cella davvero usata (mai meno di due righe); clamped: la cella chiesta
    era più piccola; big: diametro del punto nel nero pieno; small: diametro del punto nelle zone chiare (5%);
    merged: nel nero pieno i punti si fondono (nessun bianco fra loro); fine: i punti delle zone chiare sarebbero più
    fini di una riga: il laser non può farli tondi, lì escono puntini singoli e irregolari (una cella sì e una no)."""
    step = 25.4 / max(float(dpi), 10.0)
    cell = max(float(cell_mm), 2.0 * step)
    r_big = radius(1.0, size_pct)
    return {
        "step": step,
        "cell": cell,
        "clamped": cell > float(cell_mm) + 1e-9,
        "big": 2.0 * min(r_big, FULL) * cell,
        "small": 2.0 * radius(LIGHT, size_pct) * cell,
        "merged": r_big >= FULL,
        "fine": 2.0 * radius(LIGHT, size_pct) * cell < step,
    }
