# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Correzione della scansione avanti e indietro: la tabella velocità → sfasamento del profilo
e la prova da incidere per trovarla. Il dialogo resta aperto: Anteprima / Contorno / Avvia passano dalla
finestra principale, come il test materiale."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core import scan_test
from ..theme import C
from . import style
from .dialogs_materials import _dspin, _mmss
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402
from .. import units


def shown_speeds(text):
    """Velocità scritte nell'unità scelta → mm/min."""
    if not units.per_s():
        return parse_speeds(text)
    vals = parse_speeds(text, lo=0.1)
    return sorted({round(units.from_shown(v), 1) for v in vals})[:10]


def parse_speeds(text, lo=10):
    """«3000, 6000 10000» → [3000.0, 6000.0, 10000.0] (valori positivi, al massimo 10)."""
    out = []
    for tok in text.replace(";", " ").replace(",", " ").split():
        try:
            v = float(tok.replace("k", "000").replace("K", "000"))
        except ValueError:
            continue
        if lo <= v <= 100000 and v not in out:
            out.append(v)
    return sorted(out)[:10]


class ScanOffsetDialog(QDialog):
    action = Signal(str, object)  # ("preview"|"frame"|"start"|"save", GcodeJob)
    saved = Signal()

    def __init__(self, profile, head_bed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Correzione della scansione avanti e indietro"))
        self.profile = profile
        self.head_bed = head_bed
        self.job = None
        h = QHBoxLayout(self)
        left = QVBoxLayout()
        h.addLayout(left, 1)
        intro = QLabel(tr("Incidendo avanti e indietro, le righe di andata e quelle di ritorno possono non finire nello "
                          "stesso punto: i bordi verticali vengono «a pettine» e le scritte piccole sfocate. "
                          "FreeLaserCut sposta ogni riga di metà dello sfasamento indicato qui, solo nei livelli con "
                          "la scansione bidirezionale."))
        intro.setWordWrap(True)
        left.addWidget(intro)
        left.addWidget(section(tr("Valori del profilo «{0}»", profile.name)))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("Velocità ({0})", units.speed_unit()), tr("Sfasamento (mm)")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        left.addWidget(self.table, 1)
        tb = QHBoxLayout()
        self.b_add = QPushButton(tr("Aggiungi riga"))
        self.b_del = QPushButton(tr("Togli riga"))
        self.b_save = QPushButton(style.icon("save"), tr("Salva nel profilo"))
        self.b_save.setObjectName("primary")
        self.b_add.clicked.connect(lambda: self._add_row(0.0, 0.0))
        self.b_del.clicked.connect(self._del_row)
        self.b_save.clicked.connect(self.save)
        tb.addWidget(self.b_add)
        tb.addWidget(self.b_del)
        tb.addStretch(1)
        tb.addWidget(self.b_save)
        left.addLayout(tb)
        self.note = QLabel(tr("Fra due righe il valore si interpola; oltre l'ultima cresce in proporzione alla velocità. "
                              "Tabella vuota = nessuna correzione."))
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{C['muted']};")
        left.addWidget(self.note)
        for s, d in sorted(profile.scan_offsets or []):
            self._add_row(s, d)

        right = QVBoxLayout()
        h.addLayout(right, 1)
        right.addWidget(section(tr("Prova da incidere")))
        f = QFormLayout()
        self.speeds = QLineEdit(", ".join(units.fmt(v, unit=False) for v in (3000, 6000, 10000)))
        self.speeds.setToolTip(tr("Una riga di rettangoli per ogni velocità ({0}), separate da virgole", units.speed_unit()))
        self.off_max = _dspin(0.02, 2.0, 0.30, 2, 0.05, " mm")
        self.off_step = _dspin(0.01, 0.5, 0.05, 2, 0.01, " mm")
        self.power = _dspin(1, 100, 30, 0, 5, " %")
        self.interval = _dspin(0.05, 1.0, 0.15, 2, 0.05, " mm")
        self.x0 = _dspin(0, 2000, 20, 1, 5, " mm")
        self.y0 = _dspin(0, 2000, 20, 1, 5, " mm")
        orow = QHBoxLayout()
        orow.addWidget(QLabel(tr("da 0 a")))
        orow.addWidget(self.off_max)
        orow.addWidget(QLabel(tr("passo")))
        orow.addWidget(self.off_step)
        posr = QHBoxLayout()
        posr.addWidget(QLabel("X"))
        posr.addWidget(self.x0)
        posr.addWidget(QLabel("Y"))
        posr.addWidget(self.y0)
        self.b_head = QPushButton(style.icon("position"), "")
        self.b_head.setToolTip(tr("Metti la prova dove si trova ora la testa"))
        self.b_head.setEnabled(head_bed is not None)
        self.b_head.clicked.connect(self._at_head)
        posr.addWidget(self.b_head)
        self.labels = QCheckBox(tr("Etichette (velocità e correzione)"))
        self.labels.setChecked(True)
        f.addRow(tr("Velocità"), self.speeds)
        f.addRow(tr("Correzioni"), orow)
        f.addRow(tr("Potenza"), self.power)
        f.addRow(tr("Interlinea"), self.interval)
        f.addRow(tr("Angolo in basso a sinistra"), posr)
        f.addRow("", self.labels)
        right.addLayout(f)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        right.addWidget(self.info)
        btn = QGridLayout()
        self.b_prev = QPushButton(style.icon("preview"), tr("Anteprima"))
        self.b_frame = QPushButton(style.icon("frame"), tr("Contorno"))
        self.b_gcode = QPushButton(style.icon("gcode"), tr("Salva G-code"))
        self.b_start = QPushButton(style.icon("play"), tr("Avvia la prova"))
        self.b_start.setObjectName("primary")
        for i, (b, k) in enumerate(((self.b_prev, "preview"), (self.b_frame, "frame"), (self.b_gcode, "save"),
                                    (self.b_start, "start"))):
            b.clicked.connect(lambda _=False, k=k: self.action.emit(k, self.build()))
            btn.addWidget(b, i // 2, i % 2)
        right.addLayout(btn)
        right.addWidget(section(tr("Dopo la prova: in ogni riga, quale rettangolo ha i bordi più dritti?")))
        self.pick_box = QFormLayout()
        right.addLayout(self.pick_box)
        self.b_use = QPushButton(tr("Usa questi valori nella tabella"))
        self.b_use.clicked.connect(self.use_picks)
        right.addWidget(self.b_use)
        right.addStretch(1)
        self.picks = []
        for wdg in (self.off_max, self.off_step, self.power, self.interval, self.x0, self.y0):
            wdg.valueChanged.connect(self._changed)
        self.speeds.textChanged.connect(self._changed)
        self.labels.toggled.connect(self._changed)
        self.resize(900, 520)
        self._changed()

    # ---------------------------------------------------------------- tabella
    def _add_row(self, s, d):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(units.fmt(float(s), unit=False)))
        self.table.setItem(r, 1, QTableWidgetItem(f"{float(d):g}"))

    def _del_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True) or \
            ([self.table.rowCount() - 1] if self.table.rowCount() else [])
        for r in rows:
            self.table.removeRow(r)

    def values(self):
        """Righe valide della tabella, ordinate per velocità (una sola riga per velocità)."""
        out = {}
        for r in range(self.table.rowCount()):
            try:
                s = round(units.from_shown(float(self.table.item(r, 0).text().replace(",", "."))), 1)
                d = float(self.table.item(r, 1).text().replace(",", "."))
            except (AttributeError, ValueError):
                continue
            if s > 0 and -5 <= d <= 5:
                out[s] = d
        return [[s, out[s]] for s in sorted(out)]

    def save(self):
        self.profile.scan_offsets = self.values()
        try:
            self.profile.save()
        except OSError:
            pass
        self.table.setRowCount(0)
        for s, d in self.profile.scan_offsets:
            self._add_row(s, d)
        self.info.setText(tr("<b>Salvato nel profilo.</b> Vale dai prossimi lavori con la scansione bidirezionale."))
        self.saved.emit()

    # ---------------------------------------------------------------- prova
    def _at_head(self):
        if self.head_bed is not None:
            self.x0.setValue(max(0.0, self.head_bed[0]))
            self.y0.setValue(max(0.0, self.head_bed[1]))

    def spec(self):
        return scan_test.ScanTestSpec(speeds=shown_speeds(self.speeds.text()) or [6000.0], off_max=self.off_max.value(),
                                      off_step=self.off_step.value(), power=self.power.value(),
                                      interval=self.interval.value(), x0=self.x0.value(), y0=self.y0.value(),
                                      labels=self.labels.isChecked())

    def build(self):
        if self.job is None:
            self.job = scan_test.build(self.spec(), self.profile)
        return self.job

    def _changed(self, *_):
        self.job = None
        s = self.spec()
        offs = s.offsets()
        # una scelta per ogni velocità
        while self.pick_box.rowCount():
            self.pick_box.removeRow(0)
        self.picks = []
        current = dict((float(a), float(b)) for a, b in self.values())
        for sp in s.speeds:
            cb = QComboBox()
            cb.addItem("—", None)
            for d in offs:
                cb.addItem(f"{d:g} mm", d)
            same = [i for i, d in enumerate(offs) if sp in current and abs(d - current[sp]) < 1e-6]
            if same:  # solo se il valore attuale è proprio una delle correzioni provate
                cb.setCurrentIndex(same[0] + 1)
            self.pick_box.addRow(units.fmt(sp), cb)
            self.picks.append((sp, cb))
        try:
            job = self.build()
        except Exception as ex:  # noqa: BLE001 — mostra l'errore invece di chiudere
            self.info.setText(tr("Errore: {0}", ex))
            return
        w, hgt = scan_test.size(s)
        txt = tr("<b>{0:.0f} × {1:.0f} mm</b> · {2} velocità × {3} correzioni · tempo stimato <b>{4}</b>",
                 w, hgt, len(s.speeds), len(offs), _mmss(job.seconds))
        if job.warnings:
            txt += "<br><span style='color:%s'>⚠ %s</span>" % (C.get("warn", "#F5A524"), job.warnings[0])
        self.info.setText(txt)
        self.b_start.setEnabled(not job.warnings)

    def use_picks(self):
        cur = dict((float(a), float(b)) for a, b in self.values())
        n = 0
        for sp, cb in self.picks:
            d = cb.currentData()
            if d is not None:
                cur[sp] = float(d)
                n += 1
        self.table.setRowCount(0)
        for s in sorted(cur):
            self._add_row(s, cur[s])
        self.info.setText(tr("{0} valori messi nella tabella: premi «Salva nel profilo» per usarli.", n) if n else
                          tr("Scegli prima, per ogni velocità, il rettangolo con i bordi più dritti."))
