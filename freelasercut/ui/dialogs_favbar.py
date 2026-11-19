# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Visualizza → Personalizza la barra… (0.20.7): i comandi che usi di più nella barra in alto, dopo quelli di sempre.

A sinistra tutti i comandi che si possono aggiungere (con una casella per cercarli), a destra quelli nella barra,
nell'ordine in cui compaiono. Doppio clic o «Aggiungi» / «Togli»; «Su» e «Giù» cambiano l'ordine.
La scelta si salva nelle impostazioni (chiave «fav_bar») e vale anche ai prossimi avvii.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from freelasercut.i18n import tr  # noqa: E402


def plain(text):
    """Il nome di un comando senza «&» e senza i puntini finali."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").rstrip("…").rstrip(".").strip()


class FavBarDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("Personalizza la barra"))
        v = QVBoxLayout(self)
        intro = QLabel(tr("Scegli i comandi che usi di più: compaiono nella barra in alto, dopo quelli di sempre, "
                          "nell'ordine che vedi a destra. Al massimo {0}.", win.FAV_MAX))
        intro.setWordWrap(True)
        v.addWidget(intro)
        grid = QGridLayout()
        v.addLayout(grid, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Cerca un comando…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        grid.addWidget(QLabel(tr("Comandi")), 0, 0)
        grid.addWidget(QLabel(tr("Nella barra")), 0, 2)
        grid.addWidget(self.search, 1, 0)
        self.all = QListWidget()
        self.chosen = QListWidget()
        for lw in (self.all, self.chosen):
            lw.setMinimumWidth(260)
            lw.setMinimumHeight(320)
        grid.addWidget(self.all, 2, 0)
        grid.addWidget(self.chosen, 1, 2, 2, 1)
        mid = QVBoxLayout()
        mid.addStretch(1)
        self.b_add = QPushButton(tr("Aggiungi →"))
        self.b_del = QPushButton(tr("← Togli"))
        mid.addWidget(self.b_add)
        mid.addWidget(self.b_del)
        mid.addStretch(1)
        grid.addLayout(mid, 2, 1)
        side = QHBoxLayout()
        self.b_up = QPushButton(tr("Su"))
        self.b_down = QPushButton(tr("Giù"))
        self.b_clear = QPushButton(tr("Svuota"))
        for b in (self.b_up, self.b_down, self.b_clear):
            side.addWidget(b)
        side.addStretch(1)
        grid.addLayout(side, 3, 2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.b_add.clicked.connect(lambda: self.add())
        self.b_del.clicked.connect(lambda: self.remove())
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down.clicked.connect(lambda: self.move(1))
        self.b_clear.clicked.connect(lambda: self.set_keys([]))
        self.all.itemDoubleClicked.connect(lambda *_: self.add())
        self.chosen.itemDoubleClicked.connect(lambda *_: self.remove())
        self.all.currentRowChanged.connect(self._update)
        self.chosen.currentRowChanged.connect(self._update)
        self.set_keys(win.fav_bar_keys())

    # ------------------------------------------------------------------ elenchi
    def _item(self, key):
        act = self.win.acts[key]
        it = QListWidgetItem(act.icon(), plain(act.text()))
        it.setData(Qt.UserRole, key)
        it.setToolTip(act.toolTip())
        return it

    def keys(self):
        """I comandi nella barra, in ordine."""
        return [self.chosen.item(i).data(Qt.UserRole) for i in range(self.chosen.count())]

    def set_keys(self, keys):
        keys = self.win.clean_fav_keys(keys)
        self.chosen.clear()
        for k in keys:
            self.chosen.addItem(self._item(k))
        self.all.clear()
        rest = [k for k in self.win.fav_candidates() if k not in keys]
        for k in sorted(rest, key=lambda k: plain(self.win.acts[k].text()).lower()):
            self.all.addItem(self._item(k))
        self._filter(self.search.text())
        self._update()

    def _filter(self, text):
        t = text.strip().lower()
        for i in range(self.all.count()):
            it = self.all.item(i)
            it.setHidden(bool(t) and t not in it.text().lower() and t not in (it.toolTip() or "").lower())

    def _update(self, *_):
        full = self.chosen.count() >= self.win.FAV_MAX
        cur = self.all.currentItem()
        self.b_add.setEnabled(cur is not None and not cur.isHidden() and not full)
        row = self.chosen.currentRow()
        self.b_del.setEnabled(row >= 0)
        self.b_up.setEnabled(row > 0)
        self.b_down.setEnabled(0 <= row < self.chosen.count() - 1)
        self.b_clear.setEnabled(self.chosen.count() > 0)

    def add(self, key=None):
        """Aggiunge in fondo il comando scelto a sinistra (o quello dato). -> True se l'ha aggiunto."""
        if self.chosen.count() >= self.win.FAV_MAX:
            return False
        if key is None:
            cur = self.all.currentItem()
            if cur is None or cur.isHidden():
                return False
            key = cur.data(Qt.UserRole)
        if key in self.keys() or key not in self.win.fav_candidates():
            return False
        self.set_keys(self.keys() + [key])
        self.chosen.setCurrentRow(self.chosen.count() - 1)
        return True

    def remove(self):
        row = self.chosen.currentRow()
        if row < 0:
            return False
        keys = self.keys()
        del keys[row]
        self.set_keys(keys)
        self.chosen.setCurrentRow(min(row, self.chosen.count() - 1))
        return True

    def move(self, step):
        row = self.chosen.currentRow()
        new = row + step
        if row < 0 or not 0 <= new < self.chosen.count():
            return False
        keys = self.keys()
        keys[row], keys[new] = keys[new], keys[row]
        self.set_keys(keys)
        self.chosen.setCurrentRow(new)
        return True

    def accept(self):
        self.win.set_fav_bar(self.keys())
        super().accept()
