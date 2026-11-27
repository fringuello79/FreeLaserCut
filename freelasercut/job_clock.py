# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tempo che manca alla fine del lavoro (0.23.5, Deborah K.: «il tempo rimanente salta su e giù»).

Fino alla 0.23.4 il tempo rimanente era «tempo trascorso / righe fatte × righe che mancano», ricalcolato a ogni
risposta della scheda. Le righe però durano tempi molto diversi (un taglio lungo contro un puntino di una foto), le
risposte arrivano a raffiche (la scheda ne accetta molte insieme finché il suo buffer è libero) e il tempo in pausa
contava come lavoro: il numero saltava su e giù di continuo.

Ora:
- ogni riga pesa quanto la stima del suo tempo (la stessa del «Tempo stimato», con accelerazioni e velocità della
  macchina: `gcode_preview.parse`, `seg_times` e `seg_line`); senza stima (prove, file senza anteprima) si contano
  le righe come prima;
- il rapporto fra tempo vero e tempo stimato si misura sul lavoro fatto, partendo dalla stima (che vale per i primi
  secondi) e passando via via a quello misurato;
- il tempo in pausa non conta;
- il numero mostrato scende di un secondo al secondo e si corregge piano verso il calcolo (costante TAU_S; al massimo
  MAX_RATE secondi al secondo verso l'alto, MAX_RATE_GIU verso il basso): non salta a ogni risposta e non risale
  mai, scende solo più piano o più in fretta;
  in pausa resta fermo; arrotondato (5 s sotto il minuto, 10 s sotto i 10 minuti, poi al minuto).
Nessuna dipendenza da Qt: lo usa il controllo della scheda (`grbl.py`), da due fili (lettura e interfaccia).
"""
import math
import threading
import time

PRIOR_S = 10.0  # peso della stima all'inizio, in secondi stimati
TAU_S = 10.0  # tempo con cui il numero mostrato segue il calcolo
MAX_RATE = 0.75  # correzione verso l'alto, in secondi al secondo: il numero scende più piano ma non risale
MAX_RATE_GIU = 3.0  # correzione verso il basso: può scendere fino a 4 s al secondo (lavoro più veloce della stima)
MIN_RIGHE_SENZA_STIMA = 20  # senza stima: righe da vedere prima di dire un tempo (come prima)
# La scheda conferma una riga quando entra nel suo buffer, non quando è fatta: le ultime righe confermate (circa quante
# ne tiene il buffer di GRBL) sono ancora da fare. Con i tagli lunghi sono parecchi secondi.
RIGHE_NEL_BUFFER = 15


class JobClock:
    def __init__(self, total, now=None):
        self.total = max(0, int(total))
        self._cum = None  # secondi stimati cumulati per riga (indice = riga pulita), o None
        self._lock = threading.Lock()
        self.done = 0
        self.active = 0.0  # secondi di lavoro, senza le pause
        self.paused = False
        self._last = time.monotonic() if now is None else now
        self._shown = None
        self._shown_t = None

    # ------------------------------------------------------------------ dati
    def set_estimate(self, cum):
        """cum: sequenza (anche numpy) dei secondi stimati cumulati, uno per riga mandata. Ignorata se non torna."""
        try:
            n = len(cum)
            last = float(cum[-1]) if n else 0.0
        except (TypeError, ValueError, IndexError):
            return False
        if n != self.total or not (last > 0.0) or not math.isfinite(last):
            return False
        with self._lock:
            self._cum = cum
        return True

    @property
    def has_estimate(self):
        return self._cum is not None

    def tick(self, now=None, paused=None):
        """Fa avanzare il tempo di lavoro (non in pausa). paused: nuovo stato, se noto."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if not self.paused:
                self.active += max(0.0, now - self._last)
            self._last = now
            if paused is not None:
                self.paused = bool(paused)

    def progress(self, done):
        with self._lock:
            self.done = max(0, min(int(done), self.total))

    # ------------------------------------------------------------------ calcolo
    def _est(self, n):
        if n <= 0:
            return 0.0
        return float(self._cum[min(n, self.total) - 1])

    def raw_left(self, now=None):
        """Secondi che mancano secondo i dati di adesso (senza la levigatura), o None se ancora non si sa."""
        self.tick(now)
        with self._lock:
            n = self.done
            if self._cum is not None:
                tot = self._est(self.total)
                fatto = self._est(n - RIGHE_NEL_BUFFER) if n < self.total else tot
                w = min(PRIOR_S, 0.2 * tot)
                ratio = (self.active + w) / (fatto + w) if fatto + w > 0 else 1.0
                return max(0.0, (tot - fatto) * ratio)
            if n < MIN_RIGHE_SENZA_STIMA or self.active <= 0:
                return None
            fatte = max(1, n - RIGHE_NEL_BUFFER) if n < self.total else n
            return max(0.0, self.active / fatte * (self.total - fatte))

    def left(self, now=None):
        """Secondi che mancano da mostrare: scendono di un secondo al secondo e si correggono piano. None: non si sa."""
        now = time.monotonic() if now is None else now
        raw = self.raw_left(now)
        with self._lock:
            if raw is None:
                return None
            if self._shown is None:
                self._shown, self._shown_t = raw, now
                return raw
            dt = max(0.0, now - self._shown_t)
            self._shown_t = now
            if self.paused:  # in pausa il numero resta fermo (la scheda intanto può ancora riempire il suo buffer)
                return self._shown
            pred = self._shown - dt
            a = 1.0 - math.exp(-dt / TAU_S)
            self._shown = max(0.0, pred + max(-MAX_RATE_GIU * dt, min(MAX_RATE * dt, a * (raw - pred))))
            if self.done >= self.total:
                self._shown = min(self._shown, raw + 5.0)
            return self._shown


def cumulative_from_preview(preview, raw_index):
    """Secondi stimati cumulati per ogni riga mandata. preview: `gcode_preview.parse` delle righe originali;
    raw_index: per ogni riga mandata, la sua posizione fra le righe originali. -> array numpy o None."""
    try:
        import numpy as np

        times = getattr(preview, "seg_times", None)
        lines = getattr(preview, "seg_line", None)
        if times is None or lines is None or len(times) != len(lines) or not len(raw_index):
            return None
        idx = np.asarray(raw_index, dtype=np.int64)
        n_raw = int(max(int(idx.max()) + 1, int(lines.max()) + 1 if len(lines) else 0))
        per_raw = np.bincount(np.asarray(lines, dtype=np.int64), weights=np.asarray(times, dtype=np.float64),
                              minlength=n_raw)
        cum = np.cumsum(per_raw[idx])
        if not len(cum) or not (cum[-1] > 0):
            return None
        return cum
    except Exception:  # noqa: BLE001 — una stima che non torna non deve mai fermare un lavoro
        return None


def round_left(sec):
    """Arrotondamento per lo schermo: 5 s sotto il minuto, 10 s sotto i 10 minuti, poi al minuto."""
    sec = max(0.0, float(sec))
    if sec < 60:
        return int(math.ceil(sec / 5.0) * 5)
    if sec < 600:
        return int(round(sec / 10.0) * 10)
    return int(round(sec / 60.0) * 60)
