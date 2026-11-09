# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Prova di avvio senza toccare le impostazioni: «FreeLaserCut-….AppImage --self-test» (0.18.0).

Apre la finestra principale con impostazioni e dati in una cartella temporanea, controlla le librerie e stampa le
stesse informazioni del rapporto per l'assistenza. Esce con 0 se tutto va, 1 se qualcosa non va.
La usano il workflow di GitHub (su Ubuntu con X11 vero e su altre distribuzioni) e chi prova la versione per Linux:
il testo che stampa si può incollare in una segnalazione.
"""
import os
import sys
import tempfile
import traceback


def run():
    tmp = tempfile.mkdtemp(prefix="flc-selftest-")
    os.environ["APPDATA"] = tmp                 # dati di FreeLaserCut (profili, materiali, registri)
    os.environ["XDG_CONFIG_HOME"] = tmp         # impostazioni Qt (QSettings) su Linux
    os.environ["FLC_SETTINGS_INI"] = os.path.join(tmp, "prova.ini")  # preferenze (su Windows sarebbero nel registro)
    os.environ["FLC_NO_FIRST_RUN"] = "1"
    os.environ["FLC_NO_UPDATE"] = "1"
    os.environ["FLC_MULTI"] = "1"               # non disturba un FreeLaserCut già aperto
    os.environ.setdefault("FLC_UI", "classica")
    ok = True
    out = []

    def say(text):
        out.append(text)
        print(text, flush=True)

    try:
        from . import __version__, linux

        linux.startup()
        say(f"FreeLaserCut {__version__} — prova di avvio")
        for mod in ("numpy", "cv2", "numba", "PIL", "serial", "pyclipper", "segno", "barcode", "ezdxf"):
            try:
                m = __import__(mod)
                say(f"  {mod} {getattr(m, '__version__', '')}".rstrip())
            except Exception as ex:  # noqa: BLE001
                ok = False
                say(f"  {mod}: NON caricato ({type(ex).__name__}: {ex})")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([sys.argv[0]])
        linux.after_qapp(app)
        from .ui.main_window import MainWindow

        w = MainWindow()
        w.show()
        app.processEvents()
        say(f"  finestra principale: ok ({w.width()}×{w.height()}, piattaforma Qt {app.platformName()})")
        from . import diag, updater

        say(f"  aggiornamento: {updater.mode()}")
        say("")
        say(diag.system_info(w).rstrip())
        w.editor.dirty = False
        w.close()
        app.processEvents()
    except Exception:  # noqa: BLE001
        ok = False
        say(traceback.format_exc())
    say("ESITO: " + ("tutto a posto" if ok else "PROBLEMA (vedi sopra)"))
    sys.stdout.flush()
    if sys.platform == "win32":  # su Windows os._exit dopo Qt può uscire con 0xC0000005 invece del codice giusto
        sys.exit(0 if ok else 1)
    os._exit(0 if ok else 1)  # niente distruttori di Qt in uscita: l'esito è già scritto
