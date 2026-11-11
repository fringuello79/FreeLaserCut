# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Lavori in secondo piano avviati da una finestra (0.18.8).

Un filo secondario che usa una finestra (per mandarle un segnale alla fine) ne tiene un riferimento. Se intanto la
finestra viene chiusa, l'ultimo riferimento può restare proprio al filo: quando finisce, gli oggetti di Qt della
finestra verrebbero distrutti da lì invece che dal filo della finestra, e il programma si chiude di colpo
(«access violation»: successo chiudendo la finestra del rapporto mentre l'invio era in corso).

`run(lavoro, finestra, …)` avvia il filo e tiene vivi gli oggetti indicati finché il filo non è finito del tutto;
poi li lascia andare dal filo della finestra.
"""
import threading

from PySide6.QtCore import QCoreApplication, QTimer

_held = []  # [(filo, oggetti da tenere vivi)]
_timer = None


def _sweep():
    global _timer
    alive = [(t, objs) for t, objs in _held if t.is_alive()]
    _held[:] = alive  # i fili finiti lasciano qui, nel filo della finestra, i loro oggetti
    if not alive and _timer is not None:
        _timer.stop()


def run(target, *keep, name=None):
    """Avvia target() in un filo secondario. `keep`: finestre e oggetti di Qt che target usa. -> il filo."""
    global _timer
    t = threading.Thread(target=target, daemon=True, name=name)
    _held.append((t, keep))
    app = QCoreApplication.instance()
    if app is not None:
        if _timer is None:
            _timer = QTimer(app)
            _timer.setInterval(250)
            _timer.timeout.connect(_sweep)
        if not _timer.isActive():
            _timer.start()
    t.start()
    return t


def pending():
    return len(_held)
