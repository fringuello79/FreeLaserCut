# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Collegamento via Wi-Fi: indirizzo della scheda del laser sulla rete di casa (telnet, di solito porta 23)."""
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout)

from .. import netport
from freelasercut.i18n import tr  # noqa: E402


def guide_html():
    return tr(
        "<b>Laser con il Wi-Fi</b> che accettano il G-code dalla rete (per esempio le schede FluidNC, grblHAL o "
        "ESP3D, o l'AlgoLaser Delta): il laser e il PC devono essere sulla stessa rete. L'indirizzo della scheda si legge "
        "sul display del laser, nella sua app o nella pagina del router (per esempio <i>192.168.1.50</i>); "
        "su FluidNC va bene anche il nome, per esempio <i>fluidnc.local</i>. La porta è quasi sempre <b>23</b> (sulle schede Makerbase MKS DLC32 di solito <b>8080</b>).<br>"
        "Se la tua macchina si collega solo con l'app del produttore, usa il cavo USB.")


class NetDialog(QDialog):
    tested = Signal(bool, str)

    def __init__(self, qs, parent=None):
        super().__init__(parent)
        self.qs = qs
        self.port = None
        self.setWindowTitle(tr("Collegamento via Wi-Fi"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        g = QLabel(guide_html())
        g.setWordWrap(True)
        g.setTextFormat(Qt.RichText)
        v.addWidget(g)
        f = QFormLayout()
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.1.50")
        self.num = QSpinBox()
        self.num.setRange(1, 65535)
        self.num.setValue(self.suggested_port(parent))
        f.addRow(tr("Indirizzo della scheda"), self.host)
        f.addRow(tr("Porta"), self.num)
        v.addLayout(f)
        # 0.18.17: per mettere in rete la scheda c'è la procedura guidata (la stessa di Impostazioni)
        self.b_wizard = QPushButton(tr("Configura il Wi-Fi della scheda…"))
        self.b_wizard.setToolTip(tr("Se il laser non è ancora nella rete di casa: procedura guidata, con il cavo USB o "
                                    "senza"))
        self.b_wizard.clicked.connect(self._wizard)
        self.b_wizard.setVisible(hasattr(parent, "wifi_wizard"))
        v.addWidget(self.b_wizard)
        h = QHBoxLayout()
        self.b_test = QPushButton(tr("Prova il collegamento"))
        self.b_test.clicked.connect(self.test)
        h.addWidget(self.b_test)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        h.addWidget(self.result, 1)
        v.addLayout(h)
        v.addWidget(QLabel(tr("Indirizzi usati")))
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.itemClicked.connect(self._pick)
        v.addWidget(self.list)
        self.b_forget = QPushButton(tr("Dimentica l'indirizzo scelto"))
        self.b_forget.clicked.connect(self._forget)
        v.addWidget(self.b_forget)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Usa questo indirizzo"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.tested.connect(self._show_test)
        self._fill()

    @staticmethod
    def suggested_port(main):
        """8080 per le schede Makerbase e Longer (l'ultima scheda vista), 23 per le altre."""
        from .. import wifi_setup

        ctl = getattr(main, "ctl", None)
        info = list(getattr(ctl, "board_info", None) or [])
        name = getattr(getattr(main, "profile", None), "name", "") or ""
        if wifi_setup.is_mks_like(info) or any(t in name.upper() for t in ("LONGER", "MKS", "DLC32")):
            return 8080
        return netport.DEFAULT_PORT

    def _wizard(self):
        self.wizard_port = self.parent().wifi_wizard()
        if self.wizard_port:
            self.port = self.wizard_port
            self.accept()
        else:
            self._fill()

    def _fill(self):
        self.list.clear()
        for p in netport.saved(self.qs):
            it = QListWidgetItem(netport.label(p, self.qs))
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
        self.b_forget.setEnabled(self.list.count() > 0)

    def _pick(self, it):
        a = netport.parse_address(it.data(Qt.UserRole))
        if a:
            self.host.setText(a[0])
            self.num.setValue(a[1])

    def _forget(self):
        it = self.list.currentItem()
        if it is not None:
            netport.forget(self.qs, it.data(Qt.UserRole))
            self._fill()

    def address(self):
        a = netport.parse_address(f"{self.host.text().strip()}:{self.num.value()}")
        return netport.make_port(*a) if a else None

    def test(self):
        port = self.address()
        if not port:
            self.result.setText(tr("Indirizzo non valido."))
            return None
        self.b_test.setEnabled(False)
        self.result.setText(tr("Provo…"))

        def work():
            try:
                s = netport.NetSerial.from_port(port, connect_timeout=4.0)
                s.write(b"\r\n$I\n")
                got = b""
                for _ in range(30):
                    got += s.readline()
                    if b"ok" in got or b"error" in got:
                        break
                s.close()
                txt = got.decode(errors="replace")
                ok = "ok" in txt or "[VER" in txt or "Grbl" in txt or "FluidNC" in txt
                ver = next((l.strip() for l in txt.splitlines() if l.strip().startswith("[VER")), "")
                self.tested.emit(ok, ver)
            except OSError as ex:
                self.tested.emit(False, str(ex))
        from . import bg

        bg.run(work, self)
        return port

    def _show_test(self, ok, info):
        self.b_test.setEnabled(True)
        if ok:
            self.result.setText(tr("La scheda risponde. {0}", info))
        else:
            self.result.setText(tr("Nessuna risposta GRBL: {0}", info or tr("controlla indirizzo, porta e Wi-Fi.")))

    def _ok(self):
        port = self.address()
        if not port:
            self.result.setText(tr("Indirizzo non valido."))
            return
        netport.remember(self.qs, port)
        self.port = port
        self.accept()
