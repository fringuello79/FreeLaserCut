# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Autofocus con sonda (0.17.12): asse Z motorizzato e comando GRBL standard G38.2.

A laser spento la testa scende piano verso il materiale finché la sonda lo tocca, risale di 2 mm, lo ritocca
lentamente (più preciso) e si allontana della distanza di fuoco. La corsa è limitata: se entro `travel` mm la
sonda non tocca niente, la scheda si ferma da sola con l'allarme 5.

Per GRBL la sonda è l'ingresso «Probe» della scheda (sulla MKS DLC32 dalla V2.0 è IO22, dal firmware ufficiale
MKS: Machines/i2s_out_xyz_mks_dlc32.h, PROBE_PIN GPIO_NUM_22). Una sonda collegata al finecorsa Z (IO34 sulla
DLC32) per GRBL è un finecorsa: G38.2 non la vede e, con i limiti hardware attivi ($21=1), il tocco ferma tutto
con l'allarme 1. Nel report di stato la sonda toccata è «Pn:…P…», il finecorsa Z «Pn:…Z…».
"""
from .i18n import tr

BACKOFF = 2.0  # risalita prima del secondo tocco (mm)
INVERT = 6  # 0.18.1: $6 = inverti il pin della sonda (GRBL 1.1 e grblHAL; FluidNC non ce l'ha)
STUCK_S = 3.0  # sonda «TOCCATA» di fila per tanto tempo: probabilmente segnale al contrario o ingresso libero


def invert_now(settings):
    """Il valore attuale di $6 (0 o 1) dall'ultimo $$ letto, oppure None se la scheda non ce l'ha o non si legge."""
    settings = settings or {}
    raw = settings.get(INVERT, settings.get(str(INVERT)))
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return int(v) if v in (0.0, 1.0) else None


def invert_target(settings):
    """Il valore da scrivere in $6 per invertire il segnale della sonda (1 − attuale), oppure None."""
    v = invert_now(settings)
    return None if v is None else 1 - v


def lines(distance, travel, feed, slow, toward_minus=True):
    """Le righe G-code dell'autofocus (in relativo, poi di nuovo in assoluto)."""
    d = -1.0 if toward_minus else 1.0
    return [
        "M5",  # laser spento, sempre
        "G91 G21",
        f"G38.2 Z{d * travel:.3f} F{feed:.0f}",
        f"G0 Z{-d * BACKOFF:.3f}",
        f"G38.2 Z{d * (BACKOFF + 1.0):.3f} F{slow:.0f}",
        f"G0 Z{-d * distance:.3f}",
        "G90",
    ]


def pin_state(pins):
    """Dal campo Pn del report di stato: «touch» (sonda toccata), «zlimit» (finecorsa Z premuto), «free»."""
    pins = pins or ""
    if "P" in pins:
        return "touch"
    if "Z" in pins:
        return "zlimit"
    return "free"


def pin_text(pins):
    st = pin_state(pins)
    if st == "touch":
        return tr("Sonda: TOCCATA")
    if st == "zlimit":
        return tr("La scheda vede un FINECORSA Z, non la sonda: la sonda va collegata all'ingresso «Probe» della "
                  "scheda (sulla MKS DLC32 è IO22), non al finecorsa Z (IO34)")
    return tr("Sonda: libera (toccala con un dito o con un pezzo di metallo: qui deve comparire «TOCCATA»)")


def explain_alarm(code):
    """Perché l'autofocus si è fermato, detto in modo semplice."""
    if code == 4:
        return tr("La sonda risultava già toccata prima di partire. Se non lo è, la scheda la legge al contrario: "
                  "nella finestra «Asse Z e autofocus» premi «Inverti il segnale della sonda» (impostazione $6) e riprova.")
    if code == 5:
        return tr("La sonda non ha toccato niente entro la corsa massima. Avvicina la testa al materiale, controlla "
                  "che la sonda sia collegata all'ingresso «Probe» della scheda o, se la testa si allontanava, "
                  "cambia il verso verso il materiale.")
    if code == 1:
        return tr("La scheda si è fermata per un finecorsa (allarme 1): spesso vuol dire che la sonda è collegata "
                  "al finecorsa Z invece che all'ingresso «Probe». Fai l'homing prima di continuare.")
    return tr("La scheda si è fermata con l'allarme {0}.", code)
