# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Diagnostica: registro della comunicazione con la scheda e rapporto per l'assistenza.

- CommLog tiene in memoria gli ultimi scambi con la scheda (comandi, risposte, cambi di stato, allarmi,
  avanzamento del lavoro) e li salva da solo in diagnostica/ quando qualcosa va storto: allarme, errore,
  lavoro interrotto, connessione persa, oppure un lavoro che sembra fermo (nessun avanzamento per un po'
  con la macchina ferma).
- make_report() crea un unico file .zip da allegare a una segnalazione: versione, sistema, profilo della
  macchina, impostazioni $$ e $I lette, registro errori e registro della comunicazione.
  Niente progetti, immagini o dati personali: i percorsi della cartella utente diventano «~».
"""
import json
import os
import platform
import re
import sys
import time
import zipfile
from collections import deque

from PySide6.QtCore import QObject, QTimer

from . import __version__
from .profile import config_dir

MAX_LINES = 600
KEEP_FILES = 10
STALL_SECONDS = 20.0


def diag_dir():
    p = os.path.join(config_dir(), "diagnostica")
    os.makedirs(p, exist_ok=True)
    return p


def _home_variants():
    out = set()
    for h in (os.path.expanduser("~"), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")):
        if h and len(h) > 3:
            out.add(h)
            out.add(h.replace("\\", "/"))
            out.add(h.replace("/", "\\"))
    return sorted(out, key=len, reverse=True)


def sanitize(text):
    """Toglie dai testi la cartella dell'utente (che contiene il suo nome): diventa «~»."""
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


class CommLog(QObject):
    """Registro circolare della comunicazione con la scheda GRBL."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.lines = deque(maxlen=MAX_LINES)
        self.saved = []  # file salvati in questa sessione
        self.state = None
        self._last_status = None
        self._progress_t = time.time()
        self._progress_n = -1
        self._stall_noted = False
        self.on_stall = None  # f(messaggio, file): per avvisare l'interfaccia
        self.settings = {}  # ultime $$ lette
        self.info = []  # ultime $I lette
        ctl.settings_ready.connect(lambda d: setattr(self, "settings", dict(d)))
        ctl.info_ready.connect(lambda l: setattr(self, "info", list(l)))
        ctl.line_sent.connect(lambda l: self.add(">", l))
        ctl.line_received.connect(lambda l: self.add("<", l))
        ctl.status_changed.connect(self._status)
        ctl.alarm_raised.connect(lambda c, t: self._anomaly(f"ALLARME {c}: {t}"))
        ctl.error_raised.connect(lambda c, t, l: self._error(c, t, l))
        ctl.connection_changed.connect(self._connection)
        ctl.job_progress.connect(self._progress)
        ctl.job_finished.connect(self._finished)
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._watch)
        self._timer.start()

    # ---------------------------------------------------------------- registrazione
    def add(self, kind, text):
        self.lines.append((time.time(), kind, str(text)))

    def _status(self, st):
        self._last_status = st
        state = st.get("state", "")
        if state != self.state:
            self.state = state
            pos = st.get("MPos") or st.get("WPos") or []
            extra = (" MPos " + ",".join(f"{v:.2f}" for v in pos[:2])) if pos else ""
            self.add("=", f"stato {state}{extra} F{st.get('feed', 0):.0f} S{st.get('power', 0):.0f}")

    def _error(self, code, text, line):
        self.add("!", f"error:{code} {text}" + (f"  [{line}]" if line else ""))
        self.save("errore")

    def _connection(self, ok, msg):
        self.add("#", ("connessa: " if ok else "disconnessa: ") + (msg or ""))
        if not ok and msg and msg.startswith(("Connessione persa", "Errore")):
            self.save("connessione")

    def _progress(self, done, total):
        self._progress_t = time.time()
        self._stall_noted = False
        if done <= 3 or done == total or done - self._progress_n >= 200:
            self._progress_n = done
            self.add("~", f"lavoro {done}/{total}")

    def _finished(self, ok, msg):
        self.add("#", f"fine lavoro ({'ok' if ok else 'interrotto'}): {msg}")
        if not ok:
            self.save("lavoro-interrotto")

    def _anomaly(self, text):
        self.add("!", text)
        self.save("allarme")

    def _watch(self):
        """Un lavoro attivo che non avanza da un po' con la macchina ferma: lo annoto e salvo il registro."""
        ctl = self.ctl
        if not getattr(ctl, "job_active", False):
            self._progress_t = time.time()
            return
        idle = (self.state or "") in ("Idle", "Alarm", "Hold", "Door", "")
        if not self._stall_noted and idle and time.time() - self._progress_t > STALL_SECONDS:
            self._stall_noted = True
            msg = (f"il lavoro non avanza da {STALL_SECONDS:.0f} s (stato {self.state or '?'}, "
                   f"righe confermate {getattr(ctl, '_job_done', '?')}/{getattr(ctl, '_job_total', '?')}, "
                   f"in attesa {len(getattr(ctl, '_inflight', []))})")
            self.add("!", msg)
            path = self.save("lavoro-fermo")
            if self.on_stall is not None:
                self.on_stall(msg, path)

    # ---------------------------------------------------------------- salvataggio
    def text(self):
        out = [f"FreeLaserCut {__version__} — registro della comunicazione con la scheda",
               f"porta: {getattr(self.ctl, 'port', None) or '-'}  ·  creato {time.strftime('%Y-%m-%d %H:%M:%S')}",
               "legenda: > inviato  < ricevuto  = cambio di stato  ~ avanzamento  # evento  ! problema", ""]
        for t, kind, line in self.lines:
            ms = int((t % 1) * 1000)
            out.append(f"{time.strftime('%H:%M:%S', time.localtime(t))}.{ms:03d} {kind} {line}")
        return sanitize("\n".join(out) + "\n")

    def save(self, reason):
        try:
            d = diag_dir()
            path = os.path.join(d, f"comunicazione-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.text())
            self.saved.append(path)
            files = sorted(f for f in os.listdir(d) if f.startswith("comunicazione-"))
            for old in files[:-KEEP_FILES]:
                try:
                    os.remove(os.path.join(d, old))
                except OSError:
                    pass
            return path
        except OSError:
            return None


def system_info(win=None):
    """Testo con versione, sistema, schermo, interfaccia e macchina (niente dati personali)."""
    from PySide6 import __version__ as pyside_ver
    from PySide6.QtCore import qVersion
    from PySide6.QtGui import QGuiApplication

    lines = [f"FreeLaserCut {__version__}",
             f"Sistema: {platform.platform()} ({platform.machine()})",
             f"Python {sys.version.split()[0]} · PySide6 {pyside_ver} · Qt {qVersion()}",
             f"Avvio: {'installato' if 'Programs' in sys.executable or 'WindowsApps' in sys.executable else 'sorgente'}"
             f" · {'Microsoft Store' if 'WindowsApps' in sys.executable else ''}".rstrip(" ·")]
    try:
        for i, s in enumerate(QGuiApplication.screens()):
            g = s.geometry()
            lines.append(f"Schermo {i + 1}: {g.width()}×{g.height()} · scala {s.devicePixelRatio():g} · {s.logicalDotsPerInch():.0f} dpi")
    except Exception:  # noqa: BLE001
        pass
    for mod in ("numpy", "cv2", "numba", "PIL", "serial"):
        try:
            m = __import__(mod)
            lines.append(f"{mod} {getattr(m, '__version__', '?')}")
        except Exception as ex:  # noqa: BLE001
            lines.append(f"{mod}: NON caricato ({type(ex).__name__}: {ex})")
    if win is not None:
        try:
            from .i18n import language

            lines.append(f"Lingua: {language()}")
        except Exception:  # noqa: BLE001
            pass
        try:
            from .ui.banco import ui_mode

            lines.append(f"Interfaccia: {ui_mode()}")
        except Exception:  # noqa: BLE001
            pass
        p = getattr(win, "profile", None)
        if p is not None:
            lines.append("")
            lines.append("Profilo della macchina:")
            try:
                from dataclasses import asdict

                for k, v in asdict(p).items():
                    lines.append(f"  {k} = {v}")
            except Exception:  # noqa: BLE001
                lines.append(f"  {getattr(p, 'name', '?')}")
        ctl = getattr(win, "ctl", None)
        if ctl is not None:
            lines.append(f"Connessa: {getattr(ctl, 'connected', False)} · porta {getattr(ctl, 'port', None) or '-'}"
                         f" · homing fatto: {getattr(ctl, 'homed', False)}")
    return sanitize("\n".join(lines) + "\n")


def make_report(path, win=None, comm=None, extra=None):
    """Crea il rapporto .zip in `path`. Ritorna l'elenco dei file messi dentro."""
    cfg = config_dir()
    names = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sistema.txt", system_info(win))
        names.append("sistema.txt")
        if comm is not None:
            z.writestr("comunicazione-ora.log", comm.text())
            names.append("comunicazione-ora.log")
            if comm.settings or comm.info:
                txt = "\n".join(comm.info) + "\n\n" + "\n".join(f"${k}={v}" for k, v in sorted(
                    comm.settings.items(), key=lambda kv: (len(str(kv[0])), str(kv[0]))))
                z.writestr("impostazioni-grbl.txt", sanitize(txt + "\n"))
                names.append("impostazioni-grbl.txt")
        for fn in ("flc.log", "flc_crash.log"):
            fp = os.path.join(cfg, fn)
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()[-400_000:]  # le ultime ~400 KB bastano
                z.writestr(fn, sanitize(txt))
                names.append(fn)
        d = os.path.join(cfg, "diagnostica")
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d))[-KEEP_FILES:]:
                with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as fh:
                    z.writestr("diagnostica/" + fn, sanitize(fh.read()))
                names.append("diagnostica/" + fn)
        for name, data in (extra or {}).items():
            z.writestr(name, sanitize(data if isinstance(data, str) else json.dumps(data, indent=1, ensure_ascii=False)))
            names.append(name)
    return names
