# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Velocità della porta seriale (baud), scelta a mano.

Di solito non serve: le schede GRBL usano 115200 e «Riconosci la macchina» prova da solo le velocità più
comuni. Questa finestra è per chi sa che la sua scheda usa un'altra velocità: si sceglie (o si scrive) il
valore, si prova sulla porta senza cambiare niente e solo con OK si salva nel profilo della macchina.
Si apre da Laser → Velocità della porta seriale…, con il tasto destro su Connetti, o dall'avviso che compare
quando la scheda collegata non risponde.
"""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from .. import machines, netport
from ..grbl import SIM_PORT
from ..theme import C
from freelasercut.i18n import tr  # noqa: E402

STANDARD = 115200
COMMON = (115200, 250000, 230400, 921600, 500000, 57600, 38400, 19200, 9600)
LIMITS = (1200, 2000000)


class _Sig(QObject):
    done = Signal(object)


def parse_baud(text):
    """Testo scritto dalla persona → velocità valida o None."""
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    if not digits:
        return None
    b = int(digits)
    return b if LIMITS[0] <= b <= LIMITS[1] else None


class SerialSpeedDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent if parent is not None else win)
        self.win = win
        self.profile = win.profile
        self.result_text = ""
        self.setWindowTitle(tr("Velocità della porta seriale"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Di solito non serve toccarla: le schede GRBL usano <b>115200</b> baud e <i>Laser → Riconosci "
                          "la macchina…</i> prova da solo le velocità più comuni e salva quella giusta. Sceglila qui "
                          "solo se sai che la tua scheda ne usa un'altra (lo dice il manuale o il produttore)."))
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        v.addWidget(intro)
        f = QFormLayout()
        self.port = QComboBox()
        src = getattr(win, "port_combo", None)
        if src is not None:
            for i in range(src.count()):
                self.port.addItem(src.itemText(i), src.itemData(i))
            self.port.setCurrentIndex(src.currentIndex())
        f.addRow(tr("Porta"), self.port)
        self.speed = QComboBox()
        self.speed.setEditable(True)
        self.speed.setInsertPolicy(QComboBox.NoInsert)
        for b in COMMON:
            self.speed.addItem(str(b))
        self.speed.lineEdit().setValidator(QIntValidator(1, LIMITS[1], self))
        self.speed.setCurrentText(str(int(self.profile.baud)))
        self.speed.setToolTip(tr("Scegli dall'elenco o scrivi il valore (da 1200 a 2000000 baud)"))
        f.addRow(tr("Velocità (baud)"), self.speed)
        v.addLayout(f)
        row = QHBoxLayout()
        self.b_test = QPushButton(tr("Prova questa velocità"))
        self.b_test.setToolTip(tr("Apre la porta a questa velocità e chiede alla scheda chi è ($I), senza muovere niente "
                                  "e senza cambiare il profilo"))
        self.b_std = QPushButton(tr("Rimetti 115200"))
        row.addWidget(self.b_test)
        row.addWidget(self.b_std)
        row.addStretch(1)
        v.addLayout(row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        v.addWidget(self.result)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.b_ok = bb.button(QDialogButtonBox.Ok)
        self.b_ok.setText(tr("Salva nel profilo"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.b_test.clicked.connect(self.test)
        self.b_std.clicked.connect(lambda: self.speed.setCurrentText(str(STANDARD)))
        self.speed.currentTextChanged.connect(self._sync)
        self.port.currentIndexChanged.connect(self._sync)
        self._sig = _Sig(self)
        self._sig.done.connect(self._tested)
        self._sync()

    # ---------------------------------------------------------------- stato
    def value(self):
        return parse_baud(self.speed.currentText())

    def _connected(self):
        ctl = getattr(self.win, "ctl", None)
        return bool(ctl is not None and ctl.connected)

    def _sync(self, *_):
        b = self.value()
        port = self.port.currentData()
        net = bool(port) and (netport.is_net(port) or port == SIM_PORT)
        self.b_ok.setEnabled(b is not None)
        self.b_test.setEnabled(b is not None and bool(port) and not self._connected())
        notes = []
        if b is None:
            notes.append(tr("Scrivi un numero da 1200 a 2000000."))
        if net:
            notes.append(tr("In Wi-Fi o con il simulatore la velocità non conta: vale solo per le porte USB / seriali."))
        if self._connected():
            notes.append(tr("Il laser è connesso: per provare una velocità disconnettilo. Se la salvi, vale dalla "
                            "prossima connessione."))
        self.note.setText(" ".join(notes))
        self.note.setVisible(bool(notes))

    # ---------------------------------------------------------------- prova
    def test(self, wait=False):
        b, port = self.value(), self.port.currentData()
        if b is None or not port or self._connected():
            return None
        self.b_test.setEnabled(False)
        self.result.setText(tr("Provo {0} a {1} baud…", port, b))
        opener = None
        if port == SIM_PORT:
            from ..sim import SimSerial

            opener = lambda _p, _b: SimSerial()  # noqa: E731

        def work():
            try:
                r = machines.probe(port, bauds=(b,), opener=opener)
            except Exception:  # noqa: BLE001
                r = None
            self._sig.done.emit((b, port, r))
        if wait:  # per le prove automatiche
            work()
            return self.result_text
        threading.Thread(target=work, daemon=True).start()
        return None

    def _tested(self, payload):
        b, port, r = payload
        self._sync()
        if r:
            who = next((l for l in r.get("banner", []) if "grbl" in l.lower()), "") or \
                next((l for l in r.get("info", []) if l.startswith("[VER")), "") or tr("scheda GRBL")
            self.result_text = tr("<span style='color:{0}'>✓ La scheda risponde a {1} baud</span> ({2}). Premi «Salva nel "
                                  "profilo» e poi Connetti.", C["success"], b, who)
        else:
            self.result_text = tr("<span style='color:{0}'>Nessuna risposta a {1} baud su {2}.</span> Prova un'altra "
                                  "velocità o <i>Riconosci la macchina</i>; controlla anche che il laser sia acceso, il "
                                  "driver USB e che nessun altro programma usi la porta.", C["warn"], b, port)
        self.result.setText(self.result_text)

    # ---------------------------------------------------------------- salva
    def accept(self):
        b = self.value()
        if b is None:
            return
        if b != int(self.profile.baud):
            self.profile.baud = b
            try:
                self.profile.save()
            except OSError as ex:
                QMessageBox.warning(self, self.windowTitle(), tr("Non riesco a salvare: {0}", ex))
                return
        sb = getattr(self.win, "statusBar", None)
        if callable(sb):
            sb().showMessage(tr("Velocità della porta seriale: {0} baud (profilo «{1}»)", b, self.profile.name), 8000)
        super().accept()
