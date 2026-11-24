# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""FreeLaserCut — software di incisione laser per macchine GRBL (Longer B1 40W)."""
import os as _os

# OpenCV in silenzio mentre si sondano le porte camera inesistenti
_os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
_os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")

__version__ = "0.22.7"
# nome della versione (0.20.7, 0.20.8 e 0.20.9: «0.20.VI», scelto da Ale in onore di GTA VI; dalla 0.21.0: nessun
# nome, si vede il numero). Si vede sulla schermata di avvio
# e nella barra del titolo. Il numero vero, quello degli aggiornamenti, dei file e dei rapporti, resta __version__:
# un nome con lettere non si confronta con le versioni di prima
__codename__ = "0.22.7 Evo"


def display_version():
    """La versione da mostrare: il nome, se c'è, altrimenti il numero."""
    return __codename__ or __version__
__author__ = "fringuello79"
__license__ = "GPL-3.0-or-later"

# contributo volontario allo sviluppo (Aiuto → Sostieni FreeLaserCut)
PROJECT_URL = "https://github.com/fringuello79/FreeLaserCut"
DONATE_URL = "https://github.com/sponsors/fringuello79"
DONATE_PAYPAL_URL = "https://paypal.me/alessandrofelli"
