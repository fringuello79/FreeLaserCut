# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (Ale, 19/11/2026): tendina «Laser» in cima al pannello Laser (Classica e Officina del Banco) per passare da
un laser configurato all'altro, con il menu ⋯ per dare un nome al laser, aggiungerne uno e toglierlo dall'elenco.
La logica sta in `freelasercut/lasers.py`; qui solo i controlli e le finestre."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import lasers
from freelasercut.i18n import tr  # noqa: E402


class LaserPicker(QWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setObjectName("laserpick")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(6, 4, 6, 0)
        hl.setSpacing(4)
        lab = QLabel(tr("Laser"))
        lab.setObjectName("muted")
        hl.addWidget(lab)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(80)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(8)
        self.combo.view().setTextElideMode(Qt.ElideNone)
        self.combo.view().setMinimumWidth(240)
        self.combo.setProperty("help_key", "laser_pick")
        self.combo.activated.connect(self._chosen)
        hl.addWidget(self.combo, 1)
        self.btn = QToolButton()
        self.btn.setText("⋯")
        self.btn.setToolTip(tr("Nome del laser, nuovo laser, togli dall'elenco"))
        self.btn.setPopupMode(QToolButton.InstantPopup)
        self.btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        m = QMenu(self.btn)
        self.a_rename = m.addAction(tr("Dai un nome a questo laser…"), lambda: win.rename_laser())
        self.a_add = m.addAction(tr("Aggiungi un laser…"), lambda: win.add_laser())
        m.addSeparator()
        self.a_remove = m.addAction(tr("Togli questo laser dall'elenco…"), lambda: win.remove_laser())
        self.btn.setMenu(m)
        hl.addWidget(self.btn)
        self.refill()

    def refill(self):
        """L'elenco dei laser salvati, con quello in uso scelto. Il laser in uso c'è sempre, anche se non è ancora
        salvato (la prima volta, con il Longer B1 di partenza)."""
        win = self.win
        cur = win.profile.path()
        self.combo.blockSignals(True)
        self.combo.clear()
        sel = -1
        for label, path in lasers.saved():
            self.combo.addItem(label, path)
            if lasers._same_path(path, cur):
                sel = self.combo.count() - 1
        if sel < 0:
            self.combo.insertItem(0, win.profile.name, "")
            sel = 0
        self.combo.setCurrentIndex(sel)
        self.combo.blockSignals(False)
        self.update_state()

    def update_state(self):
        """Con il laser collegato non si cambia laser (prima si disconnette): il nome invece si può cambiare."""
        ctl = self.win.ctl
        busy = bool(ctl.connected)
        self.combo.setEnabled(not busy and self.combo.count() > 1)
        self.a_add.setEnabled(not busy)
        self.a_remove.setEnabled(not busy and self.combo.count() > 1)
        if busy:
            tip = tr("Laser in uso: «{0}». Per passare a un altro laser disconnetti prima questo.", self.win.profile.name)
        elif self.combo.count() > 1:
            tip = tr("Laser in uso: «{0}». Scegli un altro laser configurato per passare a quello.", self.win.profile.name)
        else:
            tip = tr("Laser in uso: «{0}». Con ⋯ → «Aggiungi un laser…» ne configuri un altro e passi dall'uno "
                     "all'altro da qui.", self.win.profile.name)
        self.combo.setToolTip(tip)

    def _chosen(self, i):
        path = self.combo.itemData(i)
        if path and not lasers._same_path(path, self.win.profile.path()):
            self.win.switch_laser(path)
        else:
            self.refill()


class AddLaserDialog(QDialog):
    """Nome del laser nuovo e da dove partire: copia del laser in uso o un modello del catalogo."""

    def __init__(self, win):
        super().__init__(win)
        from .. import machines

        self.setWindowTitle(tr("Aggiungi un laser"))
        v = QVBoxLayout(self)
        intro = QLabel(tr("Ogni laser ha il suo nome, la sua area, le sue impostazioni e la porta con cui si collega. "
                          "Poi passi dall'uno all'altro dalla tendina «Laser»."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.start = QComboBox()
        self.start.addItem(tr("Copia di «{0}» (stesse impostazioni)", win.profile.name), "")
        for n in machines.catalog_names():
            self.start.addItem(n, n)
        self.start.currentIndexChanged.connect(self._suggest)
        f.addRow(tr("Parti da"), self.start)
        self.name = QLineEdit()
        self.name.setMaxLength(lasers.NAME_MAX)
        self.name.setPlaceholderText(tr("es. B1 del garage, Falcon dell'ufficio"))
        self.name.textChanged.connect(self._check)
        f.addRow(tr("Nome"), self.name)
        v.addLayout(f)
        self.why = QLabel()
        self.why.setObjectName("muted")
        self.why.setWordWrap(True)
        v.addWidget(self.why)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        self.win = win
        self._suggest()

    def _suggest(self, *_):
        model = self.start.currentData()
        self.name.setText(lasers.unique_name(model or self.win.profile.name))
        self.name.selectAll()

    def _check(self, *_):
        why = lasers.name_problem(self.name.text())
        self.why.setText(why or "")
        self.ok.setEnabled(why is None)

    def values(self):
        return lasers.clean_name(self.name.text()), self.start.currentData() or None


def ask_name(win, title, label, text):
    """Finestrella per il nome, che non si chiude con un nome sbagliato. -> nome o None."""
    from PySide6.QtWidgets import QInputDialog

    while True:
        name, ok = QInputDialog.getText(win, title, label, QLineEdit.Normal, text)
        if not ok:
            return None
        why = lasers.name_problem(name, own_path=win.profile.path())
        if why is None:
            return lasers.clean_name(name)
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(win, title, why)
        text = name

