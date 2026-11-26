# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Rotativo: accessorio a rulli o a mandrino collegato al posto del motore dell'asse Y o, dalla 0.22.6, del
motore della Z (macchine con un interruttore che passa il driver della Z dal piano al rotativo)."""
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)

from ..core import gcode
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, dec=2, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


def _board_float(ctl, n, default):
    try:
        return float(ctl.board_settings.get(n, default))
    except (TypeError, ValueError):
        return default


def ask(parent, title, text, buttons):
    """Domanda con i pulsanti scritti per esteso: ritorna l'indice del pulsante premuto (-1 se chiusa)."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.RichText)
    box.setText(text)
    bs = [box.addButton(b, QMessageBox.AcceptRole if i == 0 else QMessageBox.RejectRole) for i, b in enumerate(buttons)]
    box.setDefaultButton(bs[-1])  # di partenza la risposta prudente
    box.exec()
    c = box.clickedButton()
    return bs.index(c) if c in bs else -1


class RotaryDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        qs = main.qs
        self.setWindowTitle(tr("Rotativo"))
        self.setMinimumWidth(500)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Per incidere bicchieri, borracce, bottiglie e cilindri: il rotativo si collega al posto del "
                          "motore dell'asse Y e gira l'oggetto. Disegna come su un foglio: l'altezza del disegno è la "
                          "parte di circonferenza da incidere. FreeLaserCut scala da solo l'asse Y e la velocità."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.on = QCheckBox(tr("Rotativo attivo"))
        self.on.setChecked(qs.value("rotary_on", "false") in (True, "true"))
        v.addWidget(self.on)
        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem(tr("A rulli (l'oggetto appoggia su due rulli)"), "roller")
        self.kind.addItem(tr("A mandrino (l'oggetto è stretto nelle griffe)"), "chuck")
        self.kind.setCurrentIndex(max(0, self.kind.findData(qs.value("rotary_kind", "roller"))))
        f.addRow(tr("Tipo"), self.kind)
        # 0.22.6 (giuseppegrassano77-coder): rotativo sul motore della Z, con l'interruttore della macchina
        self.axis = QComboBox()
        self.axis.addItem(tr("Y (al posto del motore dell'asse Y)"), "Y")
        self.axis.addItem(tr("Z (al posto del motore del piano, con l'interruttore della macchina)"), "Z")
        z_ok = bool(getattr(main.profile, "z_motor", False))
        self.axis.setCurrentIndex(1 if z_ok and str(qs.value("rotary_axis", "Y")) == "Z" else 0)
        if not z_ok:
            self.axis.model().item(1).setEnabled(False)
            self.axis.setToolTip(tr("Sulla Z solo con l'asse Z motorizzato (Laser → profilo)"))
        f.addRow(tr("Collegato al posto di"), self.axis)
        self._was = (self.on.isChecked(), self.axis.currentData())
        self.mm_rev = _spin(1, 10000, float(qs.value("rotary_mm_rev", 100.0)))
        self.mm_rev.setToolTip(tr("Quanti mm di asse Y deve comandare la scheda perché il rullo (o il mandrino) "
                                  "faccia un giro completo. Si trova con la prova qui sotto."))
        test = QPushButton(tr("Prova: un giro"))
        test.setToolTip(tr("Muove l'asse Y del valore indicato: il rullo (o il mandrino) deve fare esattamente un giro"))
        test.clicked.connect(self.test_rev)
        row = QHBoxLayout()
        row.addWidget(self.mm_rev, 1)
        row.addWidget(test)
        self.rev_label = QLabel(tr("Asse Y per un giro"))
        f.addRow(self.rev_label, row)
        self.roller = _spin(1, 500, float(qs.value("rotary_roller_d", 25.0)))
        f.addRow(tr("Diametro del rullo"), self.roller)
        self.obj = _spin(1, 1000, float(qs.value("rotary_object_d", 70.0)))
        self.obj.setToolTip(tr("Misuralo col calibro nel punto da incidere"))
        f.addRow(tr("Diametro dell'oggetto"), self.obj)
        # 0.23.3 (Ale): motore del rotativo montato al contrario. Solo nel programma: sulla scheda non si scrive niente
        self.invert = QCheckBox(tr("Inverti il senso di rotazione"))
        self.invert.setToolTip(tr("Spunta se l'incisione esce specchiata (motore del rotativo montato al contrario). "
                                  "Prova prima su carta."))
        self.invert.setChecked(qs.value("rotary_invert", "false") in (True, "true"))
        f.addRow("", self.invert)
        v.addLayout(f)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        v.addWidget(self.info)
        warn = QLabel(tr("Prima di incidere: metti a fuoco sul punto più alto dell'oggetto, in «Partenza» scegli la "
                         "posizione attuale della testa e fai il contorno. Spegni il rotativo quando torni al piano normale."))
        warn.setWordWrap(True)
        v.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.mm_rev, self.roller, self.obj):
            w.valueChanged.connect(self.update_info)
        self.kind.currentIndexChanged.connect(self.update_info)
        self.axis.currentIndexChanged.connect(self.update_info)
        self.on.toggled.connect(self.update_info)
        self.invert.toggled.connect(self.update_info)
        self.update_info()

    def settings(self):
        return {"kind": self.kind.currentData(), "mm_per_rev": self.mm_rev.value(), "roller_d": self.roller.value(),
                "object_d": self.obj.value(), "axis": self.axis.currentData(), "invert": self.invert.isChecked()}

    def update_info(self, *_):
        roller = self.kind.currentData() == "roller"
        self.roller.setEnabled(roller)
        k = gcode.rotary_scale(self.settings())
        circ = math.pi * self.obj.value()
        ax = self.axis.currentData()
        self.rev_label.setText(tr("Asse Z per un giro") if ax == "Z" else tr("Asse Y per un giro"))
        txt = tr("Circonferenza dell'oggetto: {0:.1f} mm (altezza massima del disegno che fa il giro "
                 "completo) · asse {2} × {1:.4f}", circ, abs(k), ax)
        if self.invert.isChecked():
            txt += " · " + tr("senso di rotazione invertito")
        if ax == "Z":
            txt += "<br>" + tr("Sulla Z: partenza dalla posizione della testa; autofocus e frecce della Z spenti; l'asse "
                               "Y resta libero per centrare la testa sull'oggetto. Prima di incidere serve «Prova: un "
                               "giro» con la macchina collegata.")
        self.info.setText(txt)

    def test_rev(self):
        ctl = self.main.ctl
        if not ctl.connected or ctl.job_active:
            self.info.setText(tr("Connetti la macchina per la prova."))
            return
        if self.axis.currentData() == "Z":
            self.test_rev_z()
            return
        # 0.19.3: il rotativo è sull'asse Y della macchina; ctl.jog ragiona sul piano come si vede
        ctl.jog(*self.main.profile.plane_delta(0.0, self.mm_rev.value()), 1500)

    def test_rev_z(self):
        """0.22.6: prima un movimento piccolo e lento: se si muove il piano invece del mandrino lo si vede subito e ci
        si ferma. Poi il giro intero. La prova vale per questa connessione e per le impostazioni della scheda di
        adesso ($102, i passi della Z): se cambiano, si rifà."""
        ctl, main = self.main.ctl, self.main
        if ctl.last_status.get("state") not in ("Idle", None):
            self.info.setText(tr("La macchina non è ferma: aspetta, poi riprova."))
            return
        if hasattr(main, "_reread_settings"):  # i passi della Z di adesso, letti dalla scheda
            self.info.setText(tr("Leggo le impostazioni della scheda…"))
            main._reread_settings(self._test_rev_z, fail=self.info.setText)
        else:
            self._test_rev_z()

    def _test_rev_z(self):
        ctl, main = self.main.ctl, self.main
        z_rate = _board_float(ctl, 112, 300.0)
        ctl.jog_z(2.0, min(100.0, z_rate), force=True)
        ans = ask(self, tr("Rotativo sulla Z"),
                  tr("Ho mosso la Z di poco, piano piano.<br><br><b>Si è mosso il rotativo</b> (l'oggetto ha girato "
                     "appena)?<br><br>Se invece si è mosso il piano, l'interruttore della macchina è ancora sul piano: "
                     "rispondi No, spostalo su «Rotary» e rifai la prova."),
                  (tr("Sì, ha girato il rotativo"), tr("No, si è mosso il piano")))
        if ans != 0:
            main.rotary_z_tested = False
            self.info.setText(tr("Prova fermata: sposta l'interruttore su «Rotary» e rifai la prova."))
            return
        ctl.jog_z(self.mm_rev.value(), min(1500.0, z_rate), force=True)
        main.rotary_z_tested = True
        z102 = ctl.board_settings.get(102)
        if z102 is not None:
            main.qs.setValue("rotary_z_102", str(z102))  # i passi della Z con cui è stata fatta la prova
        self.info.setText(tr("Il rotativo deve fare esattamente un giro. Se non torna al punto di partenza, cambia "
                             "«Asse Z per un giro» e rifai la prova."))

    def accept(self):
        qs = self.main.qs
        s = self.settings()
        now = (self.on.isChecked(), s["axis"])
        if now[0] and now[1] == "Z" and self._was != now:
            ans = ask(self, tr("Rotativo sulla Z"),
                      tr("Il rotativo è collegato al posto del motore della Z (interruttore su «Rotary»)?<br>Il piano "
                         "non deve muoversi: se l'interruttore resta sul piano, il lavoro lo muoverebbe su e giù."),
                      (tr("Sì, è sul rotativo"), tr("Annulla")))
            if ans != 0:
                return
        elif self._was == (True, "Z") and now != self._was:
            QMessageBox.information(self, tr("Rotativo sulla Z"),
                                    tr("Rimetti l'interruttore della macchina sul piano: con l'interruttore su «Rotary» "
                                       "l'autofocus farebbe girare il mandrino fino all'allarme."))
        qs.setValue("rotary_axis", s["axis"])
        qs.setValue("rotary_on", self.on.isChecked())
        qs.setValue("rotary_kind", s["kind"])
        qs.setValue("rotary_mm_rev", s["mm_per_rev"])
        qs.setValue("rotary_roller_d", s["roller_d"])
        qs.setValue("rotary_object_d", s["object_d"])
        qs.setValue("rotary_invert", bool(s["invert"]))
        super().accept()
