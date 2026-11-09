# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""FreeLaserCut — software di incisione laser per macchine GRBL (Longer B1 40W)."""
import os as _os

# OpenCV in silenzio mentre si sondano le porte camera inesistenti
_os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
_os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")

__version__ = "0.17.16"
__author__ = "fringuello79"
__license__ = "GPL-3.0-or-later"

# contributo volontario allo sviluppo (Aiuto → Sostieni FreeLaserCut)
PROJECT_URL = "https://github.com/fringuello79/FreeLaserCut"
DONATE_URL = "https://github.com/sponsors/fringuello79"
DONATE_PAYPAL_URL = "https://paypal.me/alessandrofelli"
