# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Avvio: prima la guardia (errori d'avvio scritti e mostrati anche senza Qt), poi la finestra d'avvio con il logo,
poi le librerie pesanti e la finestra principale."""
import sys


def _heavy_libs():
    """0.22.9: le librerie che tengono fermo l'avvio più a lungo. Nessuna crea finestre o oggetti di Qt: si possono
    caricare fuori dal thread dell'interfaccia (splash.Splash.preload)."""
    import numpy  # noqa: F401

    import cv2  # noqa: F401

    try:
        import numba  # noqa: F401
    except Exception:  # noqa: BLE001 — senza numba il programma va lo stesso (più piano)
        pass


def boot():
    # 0.19.0: prima di tutto, su un processore troppo vecchio per le librerie nuove si mettono davanti quelle
    # compatibili (vedi startup_guard.compat_libs). Sui PC normali non fa niente.
    from . import startup_guard as guard

    guard.compat_libs()
    if "--self-test" in sys.argv[1:]:  # 0.18.0: prova di avvio (workflow e versione per Linux)
        from . import selftest

        selftest.run()
        return
    # 0.18.16: da qui in poi qualsiasi errore finisce in flc.log (o flc_crash.log) e viene mostrato, anche se Qt non
    # si carica. Gli import di Qt stanno qui dentro, non in testa al file, proprio per questo.
    guard.install()
    # 0.19.3: Windows 10 più vecchio della versione 1809: Qt non si caricherebbe. Lo si dice chiaro e si esce
    if guard.check_windows():
        sys.exit(3)
    guard.stage("lingua")
    from . import i18n

    i18n.set_language(i18n.startup_language())
    from . import linux

    linux.startup()  # Linux: certificati per HTTPS, X11 su Wayland (su Windows non fa niente)
    guard.stage("qt")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fringuello79.FreeLaserCut")
        except Exception:  # noqa: BLE001
            pass
    guard.stage("app")
    app = QApplication(sys.argv)
    app._flc_translators = i18n.install_qt_translations(app)  # pulsanti standard di Qt nella stessa lingua
    # istanza unica: se FreeLaserCut è già aperto, lo porto in primo piano (con gli eventuali file) ed esco
    guard.stage("unica")
    try:
        from . import single

        state = single.forward_state(sys.argv[1:])
        if state == "ok":
            print(i18n.tr("FreeLaserCut è già aperto: porto in primo piano la sua finestra."))
            return
        if state == "stuck" and not single.open_anyway():
            return  # 0.18.16: un FreeLaserCut rimasto vivo senza rispondere: prima si usciva in silenzio
        if not single.window_token():  # 0.22.9: una finestra in più non prende il posto di quella principale
            app._flc_single = single.Listener(app)
    except Exception:  # noqa: BLE001 — se il controllo non funziona si parte comunque
        pass
    guard.stage("splash")
    splash = None
    try:
        from .splash import show_splash

        splash = show_splash()
    except Exception:  # noqa: BLE001 — senza schermata d'avvio si parte lo stesso
        splash = None
    # 0.22.9: le librerie pesanti in un thread a parte, mentre la schermata d'avvio resta fluida (splash.preload)
    guard.stage("librerie")
    if splash is not None:
        try:
            splash.preload(_heavy_libs)
        except Exception:  # noqa: BLE001 — si caricano comunque qui sotto
            pass
    guard.stage("finestra")
    from .ui.main_window import main

    main(app, splash)


if __name__ == "__main__":
    boot()
