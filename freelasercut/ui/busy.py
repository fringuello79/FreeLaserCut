# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Calcoli lunghi senza finestra bloccata (0.19.2).

Preparare un lavoro grande (foto da milioni di punti, migliaia di tracciati) può richiedere molti secondi. Fatto nel
filo dell'interfaccia senza mai cedere il passo, Windows scrive «non risponde» e non si può annullare.

Qui c'è il modo unico di farlo, lo stesso già usato dal nesting e dalla scultura: il calcolo resta nel filo
dell'interfaccia (legge forme, font e tracciati di Qt: spostarlo in un altro filo non è sicuro) ma chiama spesso
`tick()`. Il tick, al massimo una ventina di volte al secondo:

- lascia ridisegnare la finestra;
- dopo `DELAY` secondi mostra «Preparo il lavoro…» con il pulsante Annulla (finestra modale: finché c'è, il resto
  del programma non riceve clic né tasti, quindi il disegno non può cambiare a metà calcolo);
- se l'utente annulla, solleva `Cancelled`, che interrompe il calcolo.

Finché la finestrella non è comparsa i clic e i tasti restano in coda (non si perdono e non arrivano a metà
calcolo). I comandi che arrivano dalla rete (assistente, telefono) aspettano la fine del calcolo.

Nelle prove automatiche (`FLC_NO_DIALOGS`) `ticker()` restituisce None e il calcolo gira come ha sempre fatto;
`FLC_BUSY=1` lo riaccende (prova dedicata), `FLC_BUSY_DELAY` cambia l'attesa prima della finestrella.
"""
import os
import time

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

from ..i18n import tr

DELAY = 0.7  # secondi prima di mostrare la finestrella: i lavori normali non la vedono mai
STEP = 0.05  # secondi fra due passi ceduti alla finestra


class Cancelled(Exception):
    """L'utente ha premuto Annulla durante un calcolo lungo."""


class Busy:
    """Un calcolo lungo in corso. Si usa così:

        busy = Busy(finestra, tr("Preparo il lavoro…"))
        try:
            risultato = calcolo(tick=busy.tick)
        except Cancelled:
            risultato = None
        finally:
            busy.close()
    """

    active = 0  # quanti calcoli lunghi sono in corso (uno dentro l'altro non mostra una seconda finestrella)

    def __init__(self, parent, label, delay=None):
        self.parent = parent
        self.label = label
        self.delay = float(os.environ.get("FLC_BUSY_DELAY", DELAY if delay is None else delay))
        self.t0 = self.last = time.perf_counter()
        self.dialog = None
        self.cancelled = False
        self.ticks = 0
        Busy.active += 1

    def tick(self):
        now = time.perf_counter()
        if now - self.last < STEP:
            return
        self.last = now
        self.ticks += 1
        if self.dialog is None and now - self.t0 >= self.delay:
            self._show()
        flags = QEventLoop.ExcludeSocketNotifiers
        if self.dialog is None:
            flags |= QEventLoop.ExcludeUserInputEvents
        QApplication.processEvents(flags)
        if self.cancelled or (self.dialog is not None and self.dialog.wasCanceled()):
            self.cancelled = True
            raise Cancelled()

    def _show(self):
        d = QProgressDialog(self.label, tr("Annulla"), 0, 0, self.parent)
        d.setObjectName("busyDialog")
        d.setWindowTitle("FreeLaserCut")
        d.setWindowModality(Qt.ApplicationModal)
        d.setMinimumDuration(0)
        d.setAutoClose(False)
        d.setAutoReset(False)
        d.setMinimumWidth(320)
        d.setValue(0)
        d.show()
        self.dialog = d

    def close(self):
        Busy.active = max(0, Busy.active - 1)
        if self.dialog is not None:
            d, self.dialog = self.dialog, None
            d.reset()
            d.hide()
            d.deleteLater()


def enabled():
    """Nelle prove automatiche i calcoli girano senza cedere il passo (come sempre), salvo FLC_BUSY=1."""
    if os.environ.get("FLC_BUSY") == "1":
        return True
    return not os.environ.get("FLC_NO_DIALOGS") and os.environ.get("FLC_BUSY") != "0"


def start(parent, label):
    """Un Busy pronto, oppure None se non serve (prove automatiche, o un altro calcolo lungo già in corso)."""
    if not enabled() or Busy.active:
        return None
    return Busy(parent, label)
