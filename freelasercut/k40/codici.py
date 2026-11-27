# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Codici di velocità delle schede Lihuiyu (K40).

Il codice dice alla scheda quanto aspettare fra un passo e l'altro (1 passo = 1/1000 di pollice). Forma:
- taglio:  «CV» + valore (2 × 3 cifre) + accelerazione (1 cifra) [+ passo (3 cifre) + diagonale (2 × 3 cifre)] [+ «C»]
- raster:  «V» + valore + accelerazione + «G» + passo fra le righe (3 cifre, in passi)

Valore = 65536 − (b + m · T), T = millisecondi per passo = 25,4 / (mm/s). m = 12120 per le schede M (2000 per A, B,
B1; doppio per la B2). Sulla M2 vera la velocità è il 91,98 % di quella chiesta: con correggi=True si usa
m = 11148 (verificato sulla K40 di Evo: 27,587 mm/s chiesti 30 → 0,03 % di scarto).

La «C» finale (codici «1/12 con tempi diversi»): solo sotto i 7 mm/s su B2, M2 e M3, come MeerK40t con le
impostazioni di partenza. 0.22.7: con la «C» a ogni velocità (senza_giri=True, l'idea era togliere la rincorsa a
inizio e fine lavoro) la K40 di Evo andava a circa 2,6 mm/s qualunque velocità si chiedesse e perdeva la posizione
(rapporto FLC-20261124-2055-C71A): senza_giri resta solo per le prove e non si usa. Sul raster la «C» non esiste.
0.23.4 (rapporto 0FFD): quella prova del 24/11 aveva anche l'errore delle «F» di riempimento nei pacchetti, corretto
nella 0.22.8, quindi non dice niente sulla «C» da sola. MeerK40t con le impostazioni di partenza («Twitch Vectors»
spento) mette la «C» a tutti i lavori normali con la stessa formula di qui. Nel ponte FLC_K40_SENZA_GIRI=1 la accende
per provarla sulla macchina vera; di solito resta spenta.
"""
import math

SCHEDE = ("A", "B", "B1", "B2", "M", "M1", "M2", "M3")
CON_DIAGONALE = ("B1", "B2", "M1", "M2", "M3")
DIAG = 0.261199033289  # rapporto della correzione in diagonale (quello del programma originale)
CORREZIONE_M2 = 0.919493599053179  # velocità vera / chiesta con la pendenza originale (11148 / 12120 circa)
V_MIN, V_MAX = 0.5, 500.0


def accelerazione(v, raster=False, orizzontale=True, correggi=False):
    """Fascia di accelerazione 1–4 per la velocità (mm/s)."""
    if correggi:
        v = v / CORREZIONE_M2  # le fasce sono state trovate con i codici originali
    if v <= 25.4:
        return 1
    if v <= 60:
        return 2
    if raster and orizzontale:
        if v < 127:
            return 2
        return 3 if v < 320 else 4
    return 3 if v < 127 else 4


def _retta(scheda, acc, con_c, correggi):
    """-> (b, m) della scheda per la fascia di accelerazione e la «C»."""
    b = {1: 784.0, 2: 784.0, 3: 896.0, 4: 1024.0}[acc]
    if scheda in ("A", "B", "B1"):
        return b, 2000.0
    m = 11148.0 if correggi else 12120.0
    if scheda == "B2":
        m *= 2
        return (b, m / 12.0) if con_c else (b, m)
    if con_c:
        return 8.0, m / 12.0
    return {1: 5120.0, 2: 5120.0, 3: 5632.0, 4: 6144.0}[acc], m


def _sedici(valore):
    valore = int(valore)
    return "%03d%03d" % ((valore >> 8) & 0xFFFFFF, valore & 0xFF)


def codice(scheda, v, passo_raster=0, correggi=True, senza_giri=False, orizzontale=True):
    """Codice di velocità (stringa ASCII). v in mm/s; passo_raster in passi (0 = taglio). 0.23.4: passo_raster può
    essere una coppia (g0, g1), raster in un verso solo come in MeerK40t: «V…G{g0}G{g1}», la scheda scende di g0
    alla prima inversione, g1 alla seconda e così via (MeerK40t usa (passo, 0): giù a fine riga, ritorno sulla riga
    nuova a laser spento)."""
    if scheda not in SCHEDE:
        raise ValueError(f"scheda sconosciuta: {scheda}")
    if not (V_MIN <= v <= V_MAX) or not math.isfinite(v):
        raise ValueError("velocità fuori misura")
    coppia = isinstance(passo_raster, tuple)
    raster = any(passo_raster) if coppia else passo_raster != 0
    acc = accelerazione(v, raster, orizzontale, correggi)
    lenta = scheda in ("B2", "M2", "M3") and v < 7  # sotto i 7 mm/s la «C» serve comunque
    con_c = (not raster) and (lenta or (senza_giri and scheda not in ("A", "B", "B1")))
    b, m = _retta(scheda, acc, con_c, correggi)
    t = 25.4 / v
    valore = max(0, int(65536 - (b + m * t)))
    s = _sedici(valore)
    if raster and coppia:
        return "V%s%d" % (s, acc) + "".join("G%03d" % min(abs(int(g)), 999) for g in passo_raster)
    if raster:
        return "V%s%dG%03d" % (s, acc, min(abs(int(passo_raster)), 999))
    if scheda not in CON_DIAGONALE:
        return "CV%s1C" % s if con_c else "CV%s%d" % (s, acc)
    passo = min(int(math.floor(v) + 1), 128)
    d = min(max(DIAG * m * t / passo, 0), 0xFFFF)
    if con_c:
        return "CV%s1%03d%sC" % (s, passo, _sedici(d))
    return "CV%s%d%03d%s" % (s, acc, passo, _sedici(d))


def velocita_vera(scheda, codice_v):
    """La velocità che la scheda fa davvero con questo codice (mm/s), con la pendenza misurata (11148 per le schede M).
    Per il tempo stimato dei lavori e per le prove."""
    if scheda not in SCHEDE:
        raise ValueError(f"scheda sconosciuta: {scheda}")
    raster = codice_v.startswith("V")
    con_c = codice_v.endswith("C") and not raster
    s = codice_v[1:] if raster else codice_v[2:]
    valore = 65536 - ((int(s[0:3]) << 8) + int(s[3:6]))
    b, m = _retta(scheda, int(s[6]), con_c, True)
    t = (valore - b) / m
    return 25.4 / t if t > 0 else float("inf")
