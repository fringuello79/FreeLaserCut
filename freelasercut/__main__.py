# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Avvio: prima la guardia (errori d'avvio scritti e mostrati anche senza Qt), poi la finestra d'avvio con il logo,
poi le librerie pesanti e la finestra principale."""
import sys


def boot():
    if "--self-test" in sys.argv[1:]:  # 0.18.0: prova di avvio (workflow e versione per Linux)
        from . import selftest

        selftest.run()
        return
    # 0.18.16: da qui in poi qualsiasi errore finisce in flc.log (o flc_crash.log) e viene mostrato, anche se Qt non
    # si carica. Gli import di Qt stanno qui dentro, non in testa al file, proprio per questo.
    from . import startup_guard as guard

    guard.install()
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
    guard.stage("finestra")
    from .ui.main_window import main

    main(app, splash)


if __name__ == "__main__":
    boot()
