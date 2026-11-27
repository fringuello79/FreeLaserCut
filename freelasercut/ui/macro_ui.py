# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Macro (0.23.5, idea di Mauro D.): i pulsanti personali nella scheda Movimento (anche nell'Officina del Banco) e
la finestra per scriverli. Controlli e regole in freelasercut/macros.py."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import macros as M
from ..i18n import tr

COLS = 3


class MacroButton(QPushButton):
    """Pulsante che non allarga mai il pannello: il nome si accorcia con «…» se non ci sta (intero nel suggerimento)."""

    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.full = name
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(40)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        room = max(10, self.width() - 16)
        self.setText(self.fontMetrics().elidedText(self.full, Qt.ElideRight, room))


def confirm(parent, name, risk):
    """Conferma ogni volta per le macro che accendono il laser o cambiano le impostazioni della scheda."""
    if os.environ.get("FLC_NO_DIALOGS"):
        return True
    parts = []
    if "laser" in risk:
        parts.append(tr("<b>accende il laser</b> (M3 o M4): occhiali protettivi per tutti i presenti e niente di "
                        "infiammabile sotto la testa. Se la macro non lo rispegne, FreeLaserCut aggiunge M5 alla "
                        "fine."))
    if "settings" in risk:
        parts.append(tr("<b>cambia le impostazioni della scheda</b>: prima della modifica FreeLaserCut ne salva "
                        "una copia (Laser → Copie delle impostazioni della scheda)."))
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("Macro «{0}»", name))
    box.setTextFormat(Qt.RichText)
    box.setText(tr("La macro «{0}»:", name) + "<br>• " + "<br>• ".join(parts) + "<br><br>" + tr("Vuoi mandarla?"))
    yes = box.addButton(tr("Manda"), QMessageBox.AcceptRole)
    box.addButton(tr("Annulla"), QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is yes


class MacroBox(QWidget):
    """Griglia di pulsanti (uno per macro) + «Macro…» per scriverle."""

    def __init__(self, ctl, settings, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.qs = settings
        self.last_msg = ""
        self.last_sent = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        v.addWidget(self.grid_w)
        self.empty = QLabel(tr("Nessuna macro: con «Macro…» crei pulsanti tuoi con poche righe di G-code (per "
                               "esempio l'autofocus della tua macchina o l'aria)."))
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        v.addWidget(self.empty)
        self.b_edit = QPushButton(tr("Macro…"))
        self.b_edit.setToolTip(tr("Crea, modifica e ordina i pulsanti delle macro"))
        self.b_edit.clicked.connect(self.edit)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.b_edit)
        h.addStretch(1)
        v.addLayout(h)
        self.buttons = []
        self.connected = False
        self.reload()

    def reload(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.buttons = []
        self.items = M.load(self.qs)
        for i, m in enumerate(self.items):
            name = m["name"]
            b = MacroButton(name)
            lines, _err = M.parse(m["code"])
            b.setToolTip(tr("Macro «{0}»", name) + "\n" + "\n".join(lines[:8]) + ("\n…" if len(lines) > 8 else ""))
            b.clicked.connect(lambda _=False, k=i: self.run(k))
            self.grid.addWidget(b, i // COLS, i % COLS)
            self.buttons.append(b)
        self.grid_w.setVisible(bool(self.items))
        self.empty.setVisible(not self.items)
        self.set_connected(self.connected)

    def set_connected(self, ok):
        self.connected = bool(ok)
        for b in self.buttons:
            b.setEnabled(self.connected)

    def _say(self, text):
        self.last_msg = text
        if not os.environ.get("FLC_NO_DIALOGS"):
            QMessageBox.information(self, tr("Macro"), text)

    def run(self, k):
        """Clic su un pulsante: controlli, conferma se serve, poi le righe alla scheda."""
        self.last_sent = []
        if not 0 <= k < len(self.items):
            return False
        m = self.items[k]
        lines, errors = M.parse(m["code"])
        if errors:
            self._say(tr("La macro «{0}» ha un errore: {1}", m["name"], "; ".join(errors)))
            return False
        why = M.why_not(self.ctl)
        if why:
            self._say(why)
            return False
        risk = M.risks(lines)
        if risk and not confirm(self, m["name"], risk):
            self.last_msg = tr("Macro annullata.")
            return False
        self.last_sent = M.run(self.ctl, lines)
        self.last_msg = ""
        return True

    def edit(self):
        dlg = MacroDialog(M.load(self.qs), self)
        if dlg.exec() == QDialog.Accepted:
            M.save(self.qs, dlg.result_macros)
            self.reload()


class MacroDialog(QDialog):
    """Elenco delle macro a sinistra, nome e comandi a destra."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Macro"))
        self.items = [dict(m) for m in items]
        self.result_macros = []
        self.cur = -1
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Ogni macro è un pulsante nella scheda Movimento che manda alla scheda le righe scritte qui, "
                          "una per riga, come nella Console. Parte solo con la macchina ferma e pronta. I commenti "
                          "dopo «;» o fra parentesi sono ignorati."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(150)
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        bl = QHBoxLayout()
        self.b_new = QPushButton(tr("Nuova"))
        self.b_new.clicked.connect(self.add)
        self.b_del = QPushButton(tr("Elimina"))
        self.b_del.clicked.connect(self.remove)
        self.b_up = QPushButton("▲")
        self.b_up.setToolTip(tr("Sposta su"))
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down = QPushButton("▼")
        self.b_down.setToolTip(tr("Sposta giù"))
        self.b_down.clicked.connect(lambda: self.move(+1))
        for b in (self.b_new, self.b_del, self.b_up, self.b_down):
            bl.addWidget(b)
        left.addLayout(bl)
        body.addLayout(left)
        right = QVBoxLayout()
        right.addWidget(QLabel(tr("Nome del pulsante")))
        self.name = QLineEdit()
        self.name.setMaxLength(M.MAX_NAME)
        self.name.textEdited.connect(self._store)
        right.addWidget(self.name)
        right.addWidget(QLabel(tr("Comandi (G-code o GRBL)")))
        self.code = QPlainTextEdit()
        self.code.setPlaceholderText(tr("Per esempio, aria accesa:\nM8\n\noppure testa al parcheggio:\nG90\nG0 X0 Y0"))
        self.code.setMinimumSize(300, 200)
        self.code.textChanged.connect(self._store)
        right.addWidget(self.code, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        right.addWidget(self.note)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        self._fill()
        if self.items:
            self.list.setCurrentRow(0)
        else:
            self._select(-1)

    def _fill(self):
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.items:
            self.list.addItem(m["name"] or tr("(senza nome)"))
        self.list.blockSignals(False)

    def _select(self, r):
        self.cur = r
        ok = 0 <= r < len(self.items)
        for w in (self.name, self.code, self.b_del, self.b_up, self.b_down):
            w.setEnabled(ok)
        self.b_new.setEnabled(len(self.items) < M.MAX_MACROS)
        self.name.blockSignals(True)
        self.code.blockSignals(True)
        self.name.setText(self.items[r]["name"] if ok else "")
        self.code.setPlainText(self.items[r]["code"] if ok else "")
        self.name.blockSignals(False)
        self.code.blockSignals(False)
        self._update_note()

    def _store(self, *_):
        r = self.cur
        if not 0 <= r < len(self.items):
            return
        self.items[r]["name"] = self.name.text()
        self.items[r]["code"] = self.code.toPlainText()
        it = self.list.item(r)
        if it is not None:
            it.setText(M.clean_name(self.name.text()) or tr("(senza nome)"))
        self._update_note()

    def _update_note(self):
        r = self.cur
        if not 0 <= r < len(self.items):
            self.note.setText(tr("Al massimo {0} macro.", M.MAX_MACROS))
            return
        lines, errors = M.parse(self.items[r]["code"])
        if errors:
            self.note.setText(tr("Da sistemare: {0}", "; ".join(errors)))
            return
        risk = M.risks(lines)
        msg = [tr("Righe da mandare: {0}.", len(lines))]
        if "laser" in risk:
            msg.append(tr("Accende il laser: chiederà conferma ogni volta."))
        if "settings" in risk:
            msg.append(tr("Cambia le impostazioni della scheda: chiederà conferma ogni volta."))
        self.note.setText(" ".join(msg))

    def add(self):
        if len(self.items) >= M.MAX_MACROS:
            return
        self.items.append({"name": tr("Macro {0}", len(self.items) + 1), "code": ""})
        self._fill()
        self.list.setCurrentRow(len(self.items) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def remove(self):
        r = self.cur
        if 0 <= r < len(self.items):
            del self.items[r]
            self._fill()
            self.list.setCurrentRow(min(r, len(self.items) - 1))
            if not self.items:
                self._select(-1)

    def move(self, d):
        r = self.cur
        j = r + d
        if 0 <= r < len(self.items) and 0 <= j < len(self.items):
            self.items[r], self.items[j] = self.items[j], self.items[r]
            self._fill()
            self.list.setCurrentRow(j)

    def problems(self):
        """Elenco dei problemi che impediscono di salvare (nome vuoto, comandi sbagliati)."""
        out = []
        for i, m in enumerate(self.items, 1):
            name = M.clean_name(m["name"])
            if not name:
                out.append(tr("la macro {0} non ha un nome", i))
                continue
            _lines, errors = M.parse(m["code"])
            for e in errors:
                out.append(f"«{name}»: {e}")
        return out

    def accept(self):
        probs = self.problems()
        if probs:
            self.note.setText(tr("Da sistemare: {0}", "; ".join(probs[:3])))
            if not os.environ.get("FLC_NO_DIALOGS"):
                QMessageBox.warning(self, tr("Macro"), tr("Prima di salvare sistema:") + "\n• " + "\n• ".join(probs[:8]))
            return
        self.result_macros = [{"name": M.clean_name(m["name"]), "code": m["code"]} for m in self.items]
        super().accept()
