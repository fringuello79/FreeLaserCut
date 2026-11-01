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

from PySide6.QtCore import QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAGIC = "FLC1"
END = "END"


def server_name():
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "utente"
    return "FreeLaserCut-" + hashlib.sha1(user.encode("utf-8", "replace")).hexdigest()[:12]


def disabled():
    return os.environ.get("FLC_MULTI") == "1"


def payload(paths):
    files = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
    return ("\n".join([MAGIC, *files, END]) + "\n").encode("utf-8")


def forward(paths, timeout=1000, name=None):
    """True se un FreeLaserCut è già aperto e ha ricevuto la richiesta: allora questo avvio deve uscire."""
    if disabled():
        return False
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(timeout):
        return False
    if sys.platform == "win32":  # Windows: lascio alla finestra già aperta il diritto di venire in primo piano
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_uint32(0xFFFFFFFF).value)
        except Exception:  # noqa: BLE001
            pass
    sock.write(payload(paths))
    sock.flush()
    sock.waitForBytesWritten(timeout)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout)
    return True


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
