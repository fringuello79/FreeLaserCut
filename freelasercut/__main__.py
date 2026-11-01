# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Avvio: prima la finestra d'avvio con il logo, poi le librerie pesanti e la finestra principale."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def boot():
    from . import i18n

    i18n.set_language(i18n.startup_language())
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fringuello79.FreeLaserCut")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app._flc_translators = i18n.install_qt_translations(app)  # pulsanti standard di Qt nella stessa lingua
    # istanza unica: se FreeLaserCut è già aperto, lo porto in primo piano (con gli eventuali file) ed esco
    try:
        from . import single

        if single.forward(sys.argv[1:]):
            print(i18n.tr("FreeLaserCut è già aperto: porto in primo piano la sua finestra."))
            return
        app._flc_single = single.Listener(app)
    except Exception:  # noqa: BLE001 — se il controllo non funziona si parte comunque
        pass
    splash = None
    try:
        from .splash import show_splash

        splash = show_splash()
    except Exception:  # noqa: BLE001 — senza schermata d'avvio si parte lo stesso
        splash = None
    from .ui.main_window import main

    main(app, splash)


if __name__ == "__main__":
    boot()
