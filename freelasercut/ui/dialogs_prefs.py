# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Preferenze (0.19.2): tutte le regolazioni «da fare una volta» in una finestra sola, con la ricerca.

Le regolazioni erano sparse fra il menu Impostazioni, il menu Laser, il menu Aiuto e le spunte del pannello Laser.
Questa finestra non ne crea di nuove e non ne sposta nessuna: è una seconda porta sulle stesse. Ogni riga è lo
specchio di un comando o di una spunta che esiste già, quindi:

- menu, pannelli e Preferenze dicono sempre la stessa cosa (cambiando di qua cambia anche di là);
- vale per tutte e due le interfacce: nella Classica si apre da Impostazioni → Preferenze…, nel Banco dalla ⚙;
- un comando aggiunto ai menu si aggiunge qui con una riga.

Le scelte che valgono dal riavvio (interfaccia, aspetto, lingua, unità) chiudono prima questa finestra e poi fanno
la loro domanda «Riavviare adesso?», come dal menu.
"""
import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .widgets import section


def _norm(s):
    """Per la ricerca: minuscole, senza accenti e senza trattini («wifi» trova «Wi-Fi»)."""
    s = unicodedata.normalize("NFKD", str(s).replace("&", "").replace("-", "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _plain(text):
    return str(text).replace("&&", "\x00").replace("&", "").replace("\x00", "&")


class PreferencesDialog(QDialog):
    def __init__(self, win, start_section=None):
        super().__init__(win)
        self.win = win
        self.setObjectName("prefsDialog")
        self.setWindowTitle(tr("Preferenze"))
        self.resize(640, 620)
        self.setMinimumSize(420, 320)
        self._rows = []  # (sezione, widget della riga, testo per la ricerca)
        self._sections = {}  # chiave → (titolo, [widget delle righe])
        v = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setObjectName("prefsSearch")
        self.search.setPlaceholderText(tr("Cerca una regolazione…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        v.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.body = QVBoxLayout(host)
        self.body.setContentsMargins(4, 4, 10, 4)
        self.body.setSpacing(4)
        self.scroll.setWidget(host)
        v.addWidget(self.scroll, 1)
        self.empty = QLabel(tr("Nessuna regolazione con queste parole."))
        self.empty.setObjectName("muted")
        self.empty.hide()
        v.addWidget(self.empty)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)
        self._build()
        self.body.addStretch(1)
        if start_section in self._sections:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self._sections[start_section][0], 0, 0))
        self.search.setFocus()

    # ------------------------------------------------------------------ contenuto
    def _build(self):
        w = self.win
        a = w.acts
        lp = getattr(w, "laser", None)

        self._section("machine", tr("Macchina"))
        for k in ("setup_wizard", "wifi_wizard", "identify", "serial_speed", "scan_offset", "autofocus", "board_backup",
                  "profile_export", "profile_import"):
            self._button("machine", a.get(k))
        for name in ("inv_x", "inv_y"):
            self._mirror("machine", getattr(lp, name, None))

        self._section("job", tr("Lavoro"))
        for name in ("finish_origin", "optimize", "verify_first"):
            self._mirror("job", getattr(lp, name, None))
        for name in ("a_frame_laser", "a_frame_repeat"):
            self._check("job", getattr(lp, name, None))

        self._section("ui", tr("Interfaccia"))
        self._radios("ui", tr("Interfaccia"), list(getattr(w, "ui_actions", {}).values()))
        self._check("ui", getattr(w, "act_second_screen", None))
        self._radios("ui", tr("Aspetto"), list(getattr(w, "theme_actions", {}).values()))
        self._radios("ui", tr("Colore principale"), list(getattr(w, "accent_actions", {}).values()))
        lang = getattr(w, "m_language", None)
        if lang is not None:
            self._radios("ui", _plain(lang.title()), [x for x in lang.actions() if not x.isSeparator()])
        self._radios("ui", tr("Unità di misura"), list(getattr(w, "unit_actions", {}).values()))
        self._radios("ui", tr("Livello di aiuto"), [a[k] for k in ("help_beginner", "help_normal", "help_expert") if k in a],
                     restart=False)
        for k in ("light_bed", "grid", "snap_obj", "snap_grid", "dither_prev"):
            self._check("ui", a.get(k))
        self._button("ui", a.get("admin_code"))

        self._section("updates", tr("Aggiornamenti"))
        for k in ("update_auto", "update_preview"):
            self._check("updates", a.get(k))
        self._button("updates", a.get("updates"))

    # ------------------------------------------------------------------ mattoni
    def _section(self, key, title):
        lab = section(title)
        self.body.addSpacing(6)
        self.body.addWidget(lab)
        self._sections[key] = (lab, [])

    def _add(self, key, widget, text, tip=""):
        if tip:
            widget.setToolTip(tip)
        self.body.addWidget(widget)
        self._sections[key][1].append(widget)
        self._rows.append((key, widget, _norm(text + " " + tip + " " + self._sections[key][0].text())))

    @staticmethod
    def _tip(action):
        tip = action.statusTip() or ""
        return tip if tip and tip != action.text() else ""

    def _later(self, action):
        """Comandi che aprono un'altra finestra o chiedono di riavviare: prima si chiude questa."""
        self.accept()
        QTimer.singleShot(0, action.trigger)

    def _button(self, key, action):
        if action is None or not action.isVisible():
            return
        b = QPushButton(_plain(action.text()))
        b.setObjectName("prefsButton")
        b.setIcon(action.icon())
        b.setEnabled(action.isEnabled())
        b.setStyleSheet("text-align: left; padding: 5px 10px;")
        b.clicked.connect(lambda: self._later(action))
        self._add(key, b, action.text(), self._tip(action))

    def _check(self, key, action):
        """Spunta specchio di un comando con la spunta (QAction): cambia l'uno, cambia l'altro."""
        if action is None or not action.isVisible() or not action.isCheckable():
            return
        c = QCheckBox(_plain(action.text()))
        c.setChecked(action.isChecked())
        c.setEnabled(action.isEnabled())
        c.clicked.connect(lambda _on: action.trigger())
        action.toggled.connect(c.setChecked)
        self.finished.connect(lambda *_: self._drop(action.toggled, c.setChecked))
        self._add(key, c, action.text(), self._tip(action))

    def _mirror(self, key, box):
        """Spunta specchio di una spunta di un pannello (QCheckBox)."""
        if box is None:
            return
        c = QCheckBox(_plain(box.text()))
        c.setChecked(box.isChecked())
        c.setEnabled(box.isEnabled())
        c.clicked.connect(lambda on: box.setChecked(bool(on)))
        box.toggled.connect(c.setChecked)
        self.finished.connect(lambda *_: self._drop(box.toggled, c.setChecked))
        self._add(key, c, box.text(), box.toolTip())

    @staticmethod
    def _drop(signal, slot):
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _radios(self, key, title, actions, restart=True):
        """Una scelta fra più voci (un gruppo di comandi con il pallino)."""
        actions = [x for x in actions if x is not None and x.isVisible()]
        if len(actions) < 2:
            return
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        lab = QLabel(title)
        lab.setMinimumWidth(130)
        h.addWidget(lab, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        text = title
        for act in actions:
            r = QRadioButton(_plain(act.text()))
            r.setChecked(act.isChecked())
            r.setIcon(act.icon())
            r.setAutoExclusive(True)
            if restart:
                r.clicked.connect(lambda _on, x=act: self._later(x))
            else:
                r.clicked.connect(lambda _on, x=act: x.trigger())
            col.addWidget(r)
            text += " " + act.text()
        h.addLayout(col, 1)
        self._add(key, row, text)

    # ------------------------------------------------------------------ ricerca
    def filter(self, text):
        words = _norm(text).split()
        shown = 0
        per_section = {k: 0 for k in self._sections}
        for key, widget, hay in self._rows:
            ok = all(w in hay for w in words)
            widget.setVisible(ok)
            per_section[key] += ok
            shown += ok
        for key, (lab, _rows) in self._sections.items():
            lab.setVisible(per_section[key] > 0)
        self.empty.setVisible(shown == 0)
        return shown

    def rows(self, key=None):
        """Per le prove: [(sezione, widget)] delle righe, tutte o di una sezione."""
        return [(k, w) for k, w, _h in self._rows if key is None or k == key]
