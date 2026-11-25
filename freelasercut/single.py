# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Istanza unica: un secondo avvio non apre un'altra copia, ma porta in primo piano la finestra già aperta
(e le passa gli eventuali file, per esempio un progetto aperto con doppio clic).

Il primo FreeLaserCut ascolta su un QLocalServer (named pipe su Windows) con un nome legato all'utente;
il secondo prova a collegarsi: se ci riesce manda la richiesta ed esce.
Con FLC_MULTI=1 si possono aprire più copie (prove, sviluppo).
"""
import getpass
import hashlib
import os
import sys
import time

from PySide6.QtCore import QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAGIC = "FLC1"
END = "END"
REPLY_MS = 3000  # 0.18.16: quanto si aspetta che il FreeLaserCut già aperto risponda alla richiesta
STARTING_S = 120.0  # un FreeLaserCut che sta partendo da più di così, ancora senza finestra, è rimasto bloccato


def server_name():
    if os.environ.get("FLC_PROVA_ISTANZA"):  # prove: un nome a parte, per non parlare con un FreeLaserCut vero
        return os.environ["FLC_PROVA_ISTANZA"]
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "utente"
    return "FreeLaserCut-" + hashlib.sha1(user.encode("utf-8", "replace")).hexdigest()[:12]


def disabled():
    return os.environ.get("FLC_MULTI") == "1"


# ------------------------------------------------------------------ 0.22.9: «Apri un'altra finestra»
WINDOW_ENV = "FLC_WINDOW"  # sigla della finestra in più (la mette chi la apre): salvataggio automatico a parte
RECOVER_ENV = "FLC_RECOVER"  # il file passato è un salvataggio automatico rimasto: si apre come «recuperato»


def window_token(env=None):
    """La sigla di questa finestra, se è una finestra in più (solo lettere e cifre); altrimenti ""."""
    tok = (os.environ if env is None else env).get(WINDOW_ENV, "")
    return "".join(c for c in tok if c.isalnum())[:24]


def window_command(paths=(), recover=False, token=None, env=None, executable=None):
    """(comando, ambiente, cartella) per aprire un altro FreeLaserCut accanto a questo: un processo a parte (se una
    finestra si blocca l'altra va avanti), che non passa la mano alla finestra già aperta e ha la sua sigla."""
    import uuid

    from . import linux

    cmd, e = linux.relaunch_command([os.path.abspath(p) for p in paths], env, executable)
    e = dict(os.environ if e is None else e)
    e["FLC_MULTI"] = "1"
    e[WINDOW_ENV] = token or uuid.uuid4().hex[:10]
    e["FLC_NO_UPDATE"] = "1"  # gli aggiornamenti li cerca (e li propone) la finestra principale
    if recover:
        e[RECOVER_ENV] = "1"
    else:
        e.pop(RECOVER_ENV, None)
    cwd = None
    if "-m" in cmd:  # avvio con Python: dalla cartella che contiene il programma, così «-m freelasercut» lo trova
        cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return cmd, e, cwd


def open_window(paths=(), recover=False, popen=None):
    """Apre un'altra finestra di FreeLaserCut (processo nuovo, staccato da questo). OSError se non parte."""
    import subprocess

    cmd, env, cwd = window_command(paths, recover)
    kw = {"env": env, "cwd": cwd, "close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return (popen or subprocess.Popen)(cmd, **kw)


def autosave_path(folder, token=""):
    return os.path.join(folder, f"autosave-{token}.flcut" if token else "autosave.flcut")


def _lock(path):
    from PySide6.QtCore import QLockFile

    lock = QLockFile(path)
    lock.setStaleLockTime(0)  # «rimasto» solo se il processo che lo teneva non c'è più (mai per l'età)
    return lock


def hold_window(folder, token):
    """La finestra in più segna che è viva (finché il processo vive). -> il segno, da tenere; None se non serve."""
    if not token:
        return None
    lock = _lock(os.path.join(folder, f"autosave-{token}.lock"))
    lock.tryLock(0)
    return lock


def orphans(folder):
    """Salvataggi automatici di finestre in più che non ci sono più (chiuse male): elenco dei file."""
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for n in names:
        if not (n.startswith("autosave-") and n.endswith(".flcut")):
            continue
        lock = _lock(os.path.join(folder, n[:-len(".flcut")] + ".lock"))
        if lock.tryLock(0):  # nessuno la tiene: la finestra non c'è più
            lock.unlock()
            out.append(os.path.join(folder, n))
    return out


def payload(paths):
    files = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
    return ("\n".join([MAGIC, *files, END]) + "\n").encode("utf-8")


def forward(paths, timeout=1000, name=None):
    """True se un FreeLaserCut è già aperto e ha ricevuto la richiesta: allora questo avvio deve uscire."""
    return forward_state(paths, timeout, name) == "ok"


def forward_state(paths, timeout=1000, name=None, reply_ms=None):
    """Com'è andato il tentativo di passare la richiesta a un FreeLaserCut già aperto:
    "none"  nessuno è aperto: questo avvio prosegue;
    "ok"    è aperto e ha ricevuto la richiesta: questo avvio esce;
    "stuck" (0.18.16) qualcuno tiene occupato il posto ma non risponde, oppure sta «partendo» da minuti senza
            finestra: un FreeLaserCut rimasto vivo e bloccato. Prima si usciva in silenzio e il programma sembrava
            non avviarsi più; ora chi chiama lo dice alla persona (open_anyway)."""
    if disabled():
        return "none"
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(timeout):
        return "none"
    if sys.platform == "win32":  # Windows: lascio alla finestra già aperta il diritto di venire in primo piano
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_uint32(0xFFFFFFFF).value)
        except Exception:  # noqa: BLE001
            pass
    sock.write(payload(paths))
    sock.flush()
    sock.waitForBytesWritten(timeout)
    # la risposta: «FLC1 OK» (finestra portata avanti), «FLC1 AVVIO <secondi>» (sta ancora partendo). Le versioni
    # fino alla 0.18.15 non rispondono ma chiudono la connessione: vuol dire che la richiesta è arrivata
    reply = b""
    end = time.monotonic() + (REPLY_MS if reply_ms is None else reply_ms) / 1000.0
    while b"\n" not in reply and time.monotonic() < end:
        if sock.bytesAvailable() or sock.waitForReadyRead(100):
            reply += bytes(sock.readAll().data())
        elif sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            break
    heard = b"\n" in reply or sock.state() == QLocalSocket.LocalSocketState.UnconnectedState
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout)
    words = reply.decode("utf-8", "replace").split()
    if len(words) >= 3 and words[0] == MAGIC and words[1] == "AVVIO":
        try:
            return "stuck" if float(words[2]) > STARTING_S else "ok"
        except ValueError:
            return "ok"
    if heard:
        return "ok"
    # nessuna risposta: se un altro FreeLaserCut sta caricando le librerie proprio adesso è normale che non risponda
    try:
        from . import startup_guard

        if startup_guard.starting_elsewhere():
            return "ok"
    except Exception:  # noqa: BLE001
        pass
    return "stuck"


def open_anyway(parent=None):
    """Un FreeLaserCut è aperto ma non risponde: lo dico e chiedo se aprirne un altro. -> True = apri comunque.
    Senza finestre (prove, avvii senza schermo) si apre e basta."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMessageBox

    from .i18n import tr

    if os.environ.get("FLC_NO_DIALOGS") == "1" or QGuiApplication.platformName() in ("offscreen", "minimal"):
        return True
    box = QMessageBox(QMessageBox.Warning, "FreeLaserCut",
                      tr("FreeLaserCut risulta già aperto, ma non risponde."), parent=parent)
    box.setInformativeText(tr(
        "Forse sta facendo un calcolo lungo, oppure è rimasto bloccato senza finestra. Se la sua finestra non c'è, "
        "chiudilo da Gestione attività (Ctrl+Maiusc+Esc, voce «FreeLaserCut» o «pythonw») oppure riavvia il "
        "computer. Intanto puoi aprirne un altro."))
    yes = box.addButton(tr("Apri un altro FreeLaserCut"), QMessageBox.AcceptRole)
    box.addButton(tr("Annulla"), QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def activate(win):
    """Porta la finestra in primo piano, anche se era ridotta a icona."""
    if win.isMinimized():
        win.setWindowState((win.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    win.show()
    win.raise_()
    win.activateWindow()


class Listener(QObject):
    """Riceve le richieste dei secondi avvii. Finché la finestra non c'è, le tiene da parte."""

    def __init__(self, parent=None, name=None, on_request=None):
        super().__init__(parent)
        self.window = None
        self.pending = []
        self.born = time.monotonic()
        self.on_request = on_request  # per le prove: f(paths) al posto di finestra + apertura file
        self._buf = {}
        self.name = name or server_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            QLocalServer.removeServer(self.name)  # resto di un avvio finito male (Linux, macOS)
            self.server.listen(self.name)
        self.server.newConnection.connect(self._on_connection)

    @property
    def listening(self):
        return self.server.isListening()

    def attach(self, win):
        self.window = win
        pending, self.pending = self.pending, []
        for paths in pending:
            self._handle(paths)

    def close(self):
        self.server.close()

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if sock is None:
                break
            self._buf[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._done(s))
            self._read(sock)
            if sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                self._done(sock)

    def _read(self, sock):
        if sock not in self._buf:
            return
        self._buf[sock] += bytes(sock.readAll().data())
        lines = self._buf[sock].decode("utf-8", "replace").split("\n")
        if END in lines:
            del self._buf[sock]
            if lines and lines[0] == MAGIC:
                self._handle([p for p in lines[1:lines.index(END)] if p])
                # 0.18.16: rispondo, così chi ha chiesto sa che qui c'è qualcuno di vivo (e se la finestra c'è già)
                waiting = self.window is None and self.on_request is None
                sock.write((f"{MAGIC} AVVIO {time.monotonic() - self.born:.0f}\n" if waiting
                            else f"{MAGIC} OK\n").encode("utf-8"))
                sock.flush()
            sock.disconnectFromServer()

    def _done(self, sock):
        self._read(sock)
        self._buf.pop(sock, None)
        sock.deleteLater()

    def _handle(self, paths):
        if self.on_request is not None:
            self.on_request(paths)
            return
        if self.window is None:
            self.pending.append(paths)
            return
        activate(self.window)
        if paths:
            from .ui.main_window import open_paths

            open_paths(self.window, paths)
