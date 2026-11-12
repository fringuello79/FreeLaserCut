# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Guardia d'avvio (0.18.16): qualsiasi errore prima che la finestra compaia viene scritto e mostrato.

Perché: il programma parte con pythonw.exe, che non ha una finestra di testo, e il registro degli errori
(_install_crash_log) si accende solo quando Qt, l'istanza unica, la schermata d'avvio e le librerie pesanti sono già
caricati. Un errore prima di quel momento non lasciava traccia e non mostrava niente: «non si avvia» e basta.

Che cosa fa, con la sola libreria standard (niente Qt, niente numpy: deve funzionare proprio quando loro non
funzionano):
- errori di Python: scritti in flc.log, nella cartella dei dati del programma (la stessa di profile.config_dir();
  se non si può scrivere lì, nella cartella temporanea), con in testa versione, Python, Windows e build, 32/64 bit e
  la fase dell'avvio; i percorsi passano dalle stesse regole del rapporto per l'assistenza (via il nome utente);
- crash «nativi» (una libreria che fa chiudere il processo di colpo): faulthandler acceso da subito su flc_crash.log,
  lo stesso file che poi usa _install_crash_log, senza aprirlo due volte;
- un avvio che muore senza poter dire niente lascia un segno (avvio-<processo>.txt con la fase): l'avvio successivo
  se ne accorge, lo scrive e lo dice;
- messaggio a schermo anche senza Qt: su Windows una finestra di sistema, in inglese e in italiano, con il percorso
  del file e l'indirizzo a cui mandarlo. Testo fisso: le traduzioni potrebbero essere proprio quello che non parte.

Non può fare niente se a non partire è Python stesso (per esempio un Windows a 32 bit: lì è Windows a dirlo).
"""
import os
import sys
import time

EMAIL = "freelasercut@gmail.com"
LOG = "flc.log"
CRASH = "flc_crash.log"
MARK = "avvio-"  # avvio-<numero del processo>.txt: c'è finché l'avvio è in corso
STALE_S = 900.0  # un segno più vecchio di così è di un avvio morto, anche se quel numero di processo esiste ancora
STARTING_S = 120.0  # un altro FreeLaserCut che sta partendo da meno di così non è «bloccato»
FAULT_ENV = "FLC_PROVA_GUASTO"  # prove: «<fase>» = errore di Python in quella fase, «nativo:<fase>» = crash nativo
BOX_MS_ENV = "FLC_AVVIO_FINESTRA_MS"  # prove: la finestra di sistema si chiude da sola dopo tanti millisecondi

# le fasi dell'avvio, nell'ordine: chiave (per le prove) -> come sta scritta nel registro
STAGES = {
    "avvio": "avvio",
    "lingua": "lingua e impostazioni di sistema",
    "qt": "caricamento di Qt (import di PySide6)",
    "app": "creazione dell'applicazione (QApplication)",
    "unica": "controllo dell'istanza unica",
    "splash": "schermata d'avvio",
    "finestra": "caricamento della finestra principale (numpy, OpenCV, numba)",
    "apri": "apertura della finestra principale",
    "finito": "avvio finito",
}

_state = {"stage": "avvio", "dir": None, "fault": None, "mark": None, "installed": False}


# ============================================================================ dove si scrive
def config_base():
    """La cartella dei dati di FreeLaserCut: lo stesso percorso di profile.config_dir(), calcolato senza importare
    niente e senza crearla."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "FreeLaserCut")


def _writable(d, create):
    try:
        if not os.path.isdir(d):
            if not create:
                return False
            os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, f".prova-{os.getpid()}")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def log_dir():
    """Dove scrivere i registri: la cartella dei dati; se non è scrivibile, la cartella temporanea. None se nemmeno
    quella. La cartella dei dati non la creo se c'è ancora quella delle versioni fino alla 0.5.0 («Freeburn»): la
    crea profile.config_dir() copiandoci dentro i vecchi dati, e deve trovarla assente."""
    if _state["dir"] and os.path.isdir(_state["dir"]):
        return _state["dir"]
    import tempfile

    base = config_base()
    legacy = os.path.isdir(os.path.join(os.path.dirname(base), "Freeburn"))
    for d, create in ((base, not legacy), (os.path.join(tempfile.gettempdir(), "FreeLaserCut"), True)):
        if _writable(d, create):
            _state["dir"] = d
            return d
    return None


# ============================================================================ che cosa si scrive
def version():
    try:
        from . import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "?"


def _home_variants():
    out = set()
    for h in (os.path.expanduser("~"), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")):
        if h and len(h) > 3:
            out.add(h)
            out.add(h.replace("\\", "/"))
            out.add(h.replace("/", "\\"))
    return sorted(out, key=len, reverse=True)


def sanitize(text):
    """Toglie dai testi la cartella dell'utente (che contiene il suo nome): diventa «~». Le stesse regole di
    diag.sanitize, riscritte qui perché diag ha bisogno di Qt (una prova controlla che diano lo stesso risultato)."""
    import re

    if not text:
        return text
    for h in _home_variants():
        text = re.sub(re.escape(h), "~", text, flags=re.IGNORECASE)
    try:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if len(user) >= 3:
            text = re.sub(r"([\\/])" + re.escape(user) + r"([\\/])", r"\1~\2", text, flags=re.IGNORECASE)
    except re.error:
        pass
    return text


def windows_text():
    """«Windows 10 Pro 22H2, build 19045.5131»: dal registro di sistema (il modulo platform di Python, per saperlo,
    interroga un servizio di Windows che può non rispondere)."""
    win = sys.getwindowsversion()
    name, display, build, patch = f"Windows {win.major}", "", str(win.build), ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            def value(n):
                try:
                    return str(winreg.QueryValueEx(key, n)[0])
                except OSError:
                    return ""

            name = value("ProductName") or name
            display = value("DisplayVersion") or value("ReleaseId")
            build = value("CurrentBuild") or build
            patch = value("UBR")
    except Exception:  # noqa: BLE001
        pass
    if build.isdigit() and int(build) >= 22000:  # Windows 11 nel registro si chiama ancora «Windows 10»
        name = name.replace("Windows 10", "Windows 11")
    return f"{name} {display}".strip() + f", build {build}" + (f".{patch}" if patch else "")


def system_lines(stage=None):
    """Le righe in testa a ogni traccia: versione, Python, sistema e build, 32/64 bit, processore, fase dell'avvio.
    Niente dati personali."""
    py_bits = 64 if sys.maxsize > 2 ** 32 else 32
    lines = [f"FreeLaserCut {version()}",
             f"Python {sys.version.split()[0]} a {py_bits} bit ({os.path.basename(sys.executable or '?')})"]
    try:
        if sys.platform == "win32":
            arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "?")
            os_bits = 64 if "64" in arch else 32
            lines.append(f"Sistema: {windows_text()}, a {os_bits} bit ({arch})")
            if os.environ.get("PROCESSOR_IDENTIFIER"):
                lines.append("Processore: " + os.environ["PROCESSOR_IDENTIFIER"])
        else:
            import platform

            lines.append(f"Sistema: {platform.platform()} ({platform.machine()})")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Sistema: non letto ({type(exc).__name__})")
    key = stage or _state["stage"]
    lines.append("Fase dell'avvio: " + STAGES.get(key, key))
    return lines


def _append(name, text):
    """Aggiunge il testo al registro. -> il percorso del file, o None se non si è potuto scrivere."""
    d = log_dir()
    if not d:
        return None
    path = os.path.join(d, name)
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(text)
        return path
    except OSError:
        return None


def scrub(names=(LOG, CRASH)):
    """Prima di chiedere a qualcuno di mandarci i registri: via il nome utente anche dalle righe scritte da altri
    (faulthandler scrive i percorsi così come sono; il rapporto per l'assistenza li ripulisce, un file mandato a
    mano no). Riscrive il file solo se cambia qualcosa; di un file enorme tiene la coda."""
    d = log_dir()
    for name in names if d else ():
        path = os.path.join(d, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            clean = sanitize(text[-400_000:])
            if clean != text:
                with open(path, "w", encoding="utf-8", errors="replace") as fh:
                    fh.write(clean)
        except OSError:
            pass


def write_error(exc_type, exc, tb):
    """La traccia di un errore d'avvio in flc.log, con i dati di sistema in testa. -> percorso del file o None."""
    import traceback

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    head = f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {version()} — errore all'avvio\n"
    return _append(LOG, head + "\n".join(system_lines()) + "\n" + sanitize(text))


# ============================================================================ come lo si dice
def error_text(path, detail=""):
    """Il messaggio per chi non vede partire il programma. Testo fisso, in inglese e in italiano."""
    if path:
        en = f"The error has been saved in the file below: please send it to {EMAIL}"
        it = f"L'errore è stato salvato nel file qui sotto: mandalo a {EMAIL}"
    else:
        en = f"The error could not be saved to a file: please send a photo of this window to {EMAIL}"
        it = f"Non è stato possibile salvare l'errore in un file: manda una foto di questa finestra a {EMAIL}"
    text = f"FreeLaserCut could not start.\n{en}\n\nFreeLaserCut non è riuscito ad avviarsi.\n{it}"
    if path:
        text += "\n\n" + path
    if detail:
        text += "\n\n" + detail
    return text


def previous_text(folder):
    """Il messaggio quando l'avvio di prima è morto senza poter dire niente."""
    return ("The last time, FreeLaserCut closed unexpectedly while starting. It is trying again now.\n"
            f"If it does not open, please send the files flc.log and flc_crash.log from the folder below to {EMAIL}"
            "\n\nL'ultima volta FreeLaserCut si è chiuso di colpo mentre si avviava. Ora ci riprova.\n"
            f"Se non si apre, manda i file flc.log e flc_crash.log della cartella qui sotto a {EMAIL}"
            f"\n\n{folder}")


def quiet():
    """Niente finestre: prove automatiche e avvii senza schermo (una finestra lì resterebbe aperta per sempre)."""
    if os.environ.get(BOX_MS_ENV):
        return False
    return (os.environ.get("FLC_NO_DIALOGS") == "1"
            or os.environ.get("QT_QPA_PLATFORM", "").split(":")[0] in ("offscreen", "minimal"))


def _box(text, title="FreeLaserCut"):
    """La finestra di sistema di Windows, senza Qt. -> True se è stata mostrata."""
    import ctypes

    flags = 0x10 | 0x10000 | 0x40000  # icona d'errore, in primo piano, sopra le altre finestre
    user32 = ctypes.windll.user32
    try:
        ms = int(os.environ.get(BOX_MS_ENV, "0"))
    except ValueError:
        ms = 0
    if ms > 0 and hasattr(user32, "MessageBoxTimeoutW"):  # solo nelle prove: si chiude da sola
        user32.MessageBoxTimeoutW(None, str(text), str(title), flags, 0, ms)
    else:
        user32.MessageBoxW(None, str(text), str(title), flags)
    return True


def _hide_qt_windows():
    """Se Qt è già partito, la schermata d'avvio non deve coprire il messaggio. Non importa niente di nuovo."""
    try:
        qw = sys.modules.get("PySide6.QtWidgets")
        app = qw.QApplication.instance() if qw is not None else None
        if app is not None:
            for w in app.topLevelWidgets():
                w.hide()
    except Exception:  # noqa: BLE001
        pass


def show(text):
    """Mostra il messaggio: sempre sull'uscita degli errori (se c'è: con pythonw non c'è), e su Windows in una
    finestra di sistema. -> True se la finestra è stata mostrata."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    if quiet() or sys.platform != "win32":
        return False
    try:
        _hide_qt_windows()
        return _box(text)
    except Exception:  # noqa: BLE001 — se nemmeno questo va, resta il file
        return False


def _hook(exc_type, exc, tb):
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc, tb)
        return
    try:
        path = write_error(exc_type, exc, tb)
        scrub((LOG,))
    except Exception:  # noqa: BLE001
        path = None
    try:
        if sys.stderr is not None:
            import traceback

            traceback.print_exception(exc_type, exc, tb)
    except Exception:  # noqa: BLE001
        pass
    detail = "" if path else f"{exc_type.__name__}: {exc}"[:300]
    show(error_text(path, detail))


# ============================================================================ il segno dell'avvio in corso
def _alive(pid):
    """Quel processo esiste ancora?"""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.OpenProcess.restype = ctypes.c_void_p
            k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
            h = k.OpenProcess(0x1000, 0, pid)  # solo il permesso di chiedere se è vivo
            if not h:
                return ctypes.GetLastError() == 5  # «accesso negato»: c'è, ma non è nostro
            code = ctypes.c_ulong(0)
            k.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            k.CloseHandle.argtypes = (ctypes.c_void_p,)
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == 259  # 259 = ancora in esecuzione
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _marks(d):
    """I segni d'avvio presenti: [(percorso, processo, quando, fase, versione)]."""
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if not (n.startswith(MARK) and n.endswith(".txt") and n[len(MARK):-4].isdigit()):
            continue
        p = os.path.join(d, n)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            out.append((p, int(n[len(MARK):-4]), float(lines[0]), lines[1] if len(lines) > 1 else "?",
                        lines[2] if len(lines) > 2 else "?"))
        except (OSError, ValueError, IndexError):
            out.append((p, int(n[len(MARK):-4]), 0.0, "?", "?"))
    return out


def _write_mark():
    p = _state["mark"]
    if not p:
        return
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f"{time.time():.0f}\n{_state['stage']}\n{version()}\n")
    except OSError:
        pass


def _clear_mark():
    p, _state["mark"] = _state["mark"], None
    if p:
        try:
            os.remove(p)
        except OSError:
            pass


def _previous_unfinished(d):
    """Gli avvii di prima che non sono arrivati in fondo e non hanno potuto dirlo (il loro processo non c'è più).
    I loro segni vengono tolti. Quelli di un FreeLaserCut che sta partendo adesso restano dove sono."""
    dead = []
    now = time.time()
    for path, pid, when, stage, ver in _marks(d):
        if pid != os.getpid() and _alive(pid) and now - when < STALE_S:
            continue
        dead.append((when, stage, ver))
        try:
            os.remove(path)
        except OSError:
            pass
    return sorted(dead)


def starting_elsewhere():
    """Un altro FreeLaserCut sta partendo proprio adesso (da meno di due minuti)? Mentre carica le librerie non
    risponde alle richieste, ma non è bloccato."""
    d = log_dir()
    now = time.time()
    return bool(d) and any(pid != os.getpid() and _alive(pid) and now - when < STARTING_S
                           for _p, pid, when, _s, _v in _marks(d))


def _report_previous(dead):
    when, stage, ver = dead[-1]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when)) if when else "?"
    head = (f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {version()} — l'avvio precedente ({stamp}, "
            f"FreeLaserCut {ver}) si è interrotto senza un errore di Python: vedi {CRASH}\n")
    _append(LOG, head + "\n".join(system_lines(stage)) + "\n")
    show(previous_text(log_dir() or "?"))


# ============================================================================ accensione
def stage(key):
    """Segna in che fase è l'avvio (finisce in testa alle tracce e nel segno dell'avvio in corso).
    Nelle prove, FLC_PROVA_GUASTO=<fase> fa nascere lì un errore di Python e «nativo:<fase>» un crash nativo."""
    _state["stage"] = key
    _write_mark()
    fault = os.environ.get(FAULT_ENV, "")
    if fault == key:
        raise RuntimeError(f"guasto di prova nella fase «{key}»")
    if fault == "nativo:" + key:
        import faulthandler

        faulthandler._sigsegv()


def done():
    """La finestra principale è sullo schermo: l'avvio è finito, il segno si toglie."""
    _state["stage"] = "finito"
    _clear_mark()
    if os.environ.get(FAULT_ENV) == "esci":  # prove: un avvio normale che lo dice e poi si chiude da solo
        try:
            if sys.stdout is not None:
                print("FLC: avvio finito, finestra aperta", flush=True)
            qc = sys.modules["PySide6.QtCore"]
            qc.QTimer.singleShot(400, lambda: qc.QCoreApplication.exit(0))
        except Exception:  # noqa: BLE001
            pass


def fault_file(folder=None):
    """Il file di flc_crash.log già aperto dalla guardia, per _install_crash_log (che così non lo apre due volte).
    Se quello aperto non sta nella cartella chiesta (era stato messo nella cartella temporanea), lo chiudo e
    rispondo None: lo aprirà chi chiede, al posto giusto."""
    fh = _state["fault"]
    if fh is None or folder is None:
        return fh
    try:
        same = os.path.normcase(os.path.abspath(os.path.dirname(fh.name))) == os.path.normcase(os.path.abspath(folder))
    except (OSError, TypeError, AttributeError):
        same = False
    if same:
        return fh
    try:
        import faulthandler

        faulthandler.disable()
        fh.close()
    except Exception:  # noqa: BLE001
        pass
    _state["fault"] = None
    return None


def install():
    """Da chiamare come prima cosa. Non fa niente di lento: apre un file, ne scrive uno piccolo, guarda una cartella."""
    if _state["installed"]:
        return
    _state["installed"] = True
    sys.excepthook = _hook
    d = log_dir()
    if not d:
        return
    dead = _previous_unfinished(d)
    if dead:  # stiamo per chiedere di mandarci i registri: prima via il nome utente (il file non è ancora aperto)
        scrub()
    try:
        import faulthandler

        fh = open(os.path.join(d, CRASH), "a", encoding="utf-8", errors="replace")  # noqa: SIM115 — resta aperto
        info = " · ".join(system_lines()[1:-1])
        fh.write(f"\n=== avvio {time.strftime('%Y-%m-%d %H:%M:%S')}  FreeLaserCut {version()}\n{info}\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
        _state["fault"] = fh
    except (OSError, RuntimeError, ValueError):
        pass
    _state["mark"] = os.path.join(d, f"{MARK}{os.getpid()}.txt")
    _write_mark()
    import atexit

    atexit.register(_clear_mark)  # un'uscita normale (anche con un errore di Python già detto) toglie il segno
    if dead:
        try:
            _report_previous(dead)
        except Exception:  # noqa: BLE001
            pass
