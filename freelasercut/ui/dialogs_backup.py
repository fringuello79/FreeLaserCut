# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Copie delle impostazioni della scheda: elenco, nuova copia, confronto e ripristino."""
import os
import shutil
import time

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHeaderView,
                               QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import board_backup as bb
from freelasercut.i18n import tr  # noqa: E402


class BoardBackupDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.ctl = win.ctl
        self.setWindowTitle(tr("Copie delle impostazioni della scheda"))
        self.setMinimumSize(640, 420)
        v = QVBoxLayout(self)
        intro = QLabel(tr(
            "FreeLaserCut salva da solo una copia di tutte le impostazioni della scheda ($$) quando si collega (se "
            "sono cambiate) e prima di modificarne una. Se qualcosa va storto, o la scheda si azzera, scegli una copia "
            "e premi «Ripristina»: vengono rimandati alla scheda solo i valori diversi."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Data"), tr("Motivo"), tr("Scheda"), tr("Valori")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        v.addWidget(self.table, 1)
        g = QGridLayout()
        self.b_now = QPushButton(tr("Salva una copia adesso"))
        self.b_now.clicked.connect(self.save_now)
        self.b_restore = QPushButton(tr("Confronta e ripristina…"))
        self.b_restore.setObjectName("primary")
        self.b_restore.clicked.connect(self.restore)
        self.b_import = QPushButton(tr("Aggiungi un file…"))
        self.b_import.clicked.connect(self.import_file)
        self.b_export = QPushButton(tr("Esporta la copia…"))
        self.b_export.clicked.connect(self.export_file)
        self.b_folder = QPushButton(tr("Apri la cartella"))
        self.b_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(bb.backup_dir())))
        for i, b in enumerate((self.b_now, self.b_restore, self.b_import, self.b_export, self.b_folder)):
            g.addWidget(b, i // 3, i % 3)
        v.addLayout(g)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self.ctl.connection_changed.connect(lambda *_: self._buttons())
        self.table.itemSelectionChanged.connect(self._buttons)
        self.fill()

    # ---------------------------------------------------------------- elenco
    def fill(self, select=None):
        self.items = bb.list_backups()
        self.table.setRowCount(0)
        row = 0
        for i, (p, m) in enumerate(self.items):
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = (m["date"] or time.strftime("%Y-%m-%d %H:%M", time.localtime(m["mtime"])), m["reason"] or "—",
                    m["ver"] or "—", str(m["count"]))
            for c, t in enumerate(vals):
                it = QTableWidgetItem(t)
                it.setData(Qt.UserRole, p)
                self.table.setItem(r, c, it)
            if select and p == select:
                row = r
        if self.items:
            self.table.selectRow(row)
        self._buttons()

    def current(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.items):
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _buttons(self):
        on = self.ctl.connected
        self.b_now.setEnabled(on)
        self.b_restore.setEnabled(on and self.current() is not None and not self.ctl.job_active)
        self.b_export.setEnabled(self.current() is not None)

    # ---------------------------------------------------------------- azioni
    def save_now(self):
        """Rilegge $$ dalla scheda e salva (anche se uguale all'ultima copia non ne fa un doppione)."""
        def got(data):
            try:
                self.ctl.settings_ready.disconnect(got)
            except (RuntimeError, TypeError):
                pass
            path = bb.save(data, self.ctl.board_info, tr("copia a mano"), self.ctl.port or "")
            self.fill(path)
            self.status.setText(tr("Copia salvata: {0}", os.path.basename(path)) if path else
                                tr("La scheda non ha mandato le impostazioni."))
        self.ctl.settings_ready.connect(got)
        self.ctl.request_settings()
        self.status.setText(tr("Leggo le impostazioni dalla scheda…"))

    def restore(self):
        path = self.current()
        if path is None or not self.ctl.connected:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            saved = bb.parse(fh.read())
        changes = bb.diff(self.ctl.board_settings, saved)
        skipped = bb.not_restored(saved)
        note = (tr("Non rimando {0}: non è un'area di lavoro credibile.", ", ".join(f"${n}={v}" for n, v in skipped))
                if skipped else "")
        if not changes:
            QMessageBox.information(self, tr("Ripristino"), (note + "\n\n" if note else "")
                                    + tr("La scheda ha già tutti i valori di questa copia."))
            return []
        txt = "\n".join(f"${n}: {a} → {b}" for n, a, b in changes[:25])
        if len(changes) > 25:
            txt += "\n…"
        if note:
            txt += "\n\n" + note
        if QMessageBox.question(self, tr("Ripristino"), tr("Rimando alla scheda {0} valori:\n\n{1}\n\nProcedo?",
                                                           len(changes), txt)) != QMessageBox.Yes:
            return None
        lines = bb.restore_lines(self.ctl.board_settings, saved)
        for line in lines:
            self.ctl.send_line(line)
        self.ctl.request_settings()
        self.status.setText(tr("Ripristinati {0} valori. Alcune schede vanno riavviate per usarli.", len(lines)))
        QTimer.singleShot(1500, lambda: self.fill(path))
        return lines

    def import_file(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("Copia delle impostazioni"), "", tr("Testo (*.txt);;Tutti i file (*)"))
        if not p:
            return
        with open(p, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        n = bb.parse(txt)
        if not n:
            QMessageBox.warning(self, tr("Copia delle impostazioni"), tr("Nel file non ci sono righe «$numero=valore»."))
            return
        dest = os.path.join(bb.backup_dir(), time.strftime("importata-%Y%m%d-%H%M%S.txt"))
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt if txt.startswith(bb.HEADER) else bb.to_text(n, (), tr("importata da {0}", os.path.basename(p))))
        self.fill(dest)

    def export_file(self):
        src = self.current()
        if src is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, tr("Esporta la copia"), os.path.basename(src), tr("Testo (*.txt)"))
        if p:
            shutil.copyfile(src, p)
