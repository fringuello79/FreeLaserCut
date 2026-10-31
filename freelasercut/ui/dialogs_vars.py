# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Numerazione e CSV per il testo variabile."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..core import variables
from . import style
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402


class VariablesDialog(QDialog):
    def __init__(self, texts=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Testo variabile"))
        self.resize(640, 560)
        st = variables.STATE
        v = QVBoxLayout(self)
        help_ = QLabel(tr("Nel testo usa <b>{N}</b> per il numero di serie (<b>{N:3}</b> = 001), <b>{DATA}</b>, "
                       "<b>{ANNO}</b>, <b>{ORA}</b>, oppure il nome di una colonna del CSV tra graffe, "
                       "per esempio <b>{Nome}</b>. Le copie di una serie a griglia o circolare si numerano da sole."))
        help_.setWordWrap(True)
        v.addWidget(help_)
        v.addWidget(section(tr("Numero di serie")))
        f = QFormLayout()
        self.serial = QSpinBox()
        self.serial.setRange(-999999, 99999999)
        self.serial.setValue(int(st["serial"]))
        self.step = QSpinBox()
        self.step.setRange(-1000, 1000)
        self.step.setValue(int(st["step"]))
        self.pad = QSpinBox()
        self.pad.setRange(0, 12)
        self.pad.setValue(int(st["pad"]))
        self.pad.setSpecialValueText("libere")
        self.auto = QCheckBox(tr("Avanza da solo alla fine di ogni lavoro riuscito"))
        self.auto.setChecked(bool(st["auto"]))
        f.addRow(tr("Prossimo numero"), self.serial)
        f.addRow(tr("Incremento"), self.step)
        f.addRow(tr("Cifre minime"), self.pad)
        f.addRow("", self.auto)
        v.addLayout(f)
        v.addWidget(section(tr("Dati da file CSV")))
        cr = QHBoxLayout()
        self.csv_lab = QLabel("")
        self.csv_lab.setObjectName("muted")
        b_load = QPushButton(style.icon("open"), tr("Carica CSV…"))
        b_load.clicked.connect(self._load)
        b_clear = QPushButton(tr("Rimuovi"))
        b_clear.clicked.connect(self._clear)
        cr.addWidget(self.csv_lab, 1)
        cr.addWidget(b_load)
        cr.addWidget(b_clear)
        v.addLayout(cr)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        self.row_lab = QLabel("")
        v.addWidget(self.row_lab)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setObjectName("muted")
        v.addWidget(self.preview)
        self.texts = list(texts)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Applica"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._rows = list(st.get("rows") or [])
        self._csv = st.get("csv", "")
        for w in (self.serial, self.step, self.pad):
            w.valueChanged.connect(self._update_preview)
        self.table.currentCellChanged.connect(lambda *_: self._update_preview())
        self._fill(int(st.get("row", 0)))

    def _fill(self, current=0):
        rows = self._rows
        cols = list(rows[0].keys()) if rows else []
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            for j, c in enumerate(cols):
                self.table.setItem(i, j, QTableWidgetItem(str(r.get(c, ""))))
        if rows:
            self.table.selectRow(min(current, len(rows) - 1))
        self.csv_lab.setText(tr("{0} · {1} righe · colonne: {2}", os.path.basename(self._csv), len(rows), ', '.join(cols))
                             if rows else tr("Nessun file: carica un CSV (anche esportato da Excel) per nomi, date, codici…"))
        self._update_preview()

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Carica CSV"), os.path.dirname(self._csv) if self._csv else "",
                                              tr("CSV (*.csv *.txt);;Tutti i file (*)"))
        if not path:
            return
        backup = dict(variables.STATE)
        try:
            variables.load_csv(path)
        except (OSError, UnicodeDecodeError, ValueError) as ex:
            QMessageBox.warning(self, "CSV", tr("Non riesco a leggere il file:\n{0}", ex))
            return
        self._rows, self._csv = list(variables.STATE["rows"]), path
        variables.STATE.update(backup)  # si applica solo con "Applica"
        self._fill(0)

    def _clear(self):
        self._rows, self._csv = [], ""
        self._fill(0)

    def state(self):
        row = max(0, self.table.currentRow()) if self._rows else 0
        return {"serial": self.serial.value(), "step": self.step.value(), "pad": self.pad.value(),
                "auto": self.auto.isChecked(), "csv": self._csv, "rows": self._rows, "row": row}

    def _update_preview(self):
        st = self.state()
        if self._rows:
            self.row_lab.setText(tr("Riga corrente: {0} di {1} (clic su una riga per cambiarla)", st['row'] + 1, len(self._rows)))
        else:
            self.row_lab.setText("")
        if not self.texts:
            self.preview.setText(tr("Nessun testo variabile nel progetto."))
            return
        shown = []
        for t in self.texts[:6]:
            shown.append("«" + variables.expand(t.text, t.var_offset, st).replace("\n", " ⏎ ") + "»")
        more = f" … e altri {len(self.texts) - 6}" if len(self.texts) > 6 else ""
        self.preview.setText(tr("Anteprima: ") + "  ".join(shown) + more)

    def apply(self):
        variables.STATE.update(self.state())
        variables.changed()
