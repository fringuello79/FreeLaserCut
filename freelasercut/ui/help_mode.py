# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Guida contestuale "Che cos'è?": pulsante "?" sulla barra (o Maiusc+F1).

Con la guida attiva:
- passando il mouse su un comando, un campo, una colonna o una voce di menu compare una scheda con la
  descrizione, la scorciatoia, le opzioni (per menu e tendine) e il valore attuale;
- i clic NON eseguono i comandi: puoi esplorare tutto senza paura. Si possono comunque aprire i menu
  della barra e cambiare scheda nei pannelli, per leggere le voci che contengono;
- Esc, Maiusc+F1 o di nuovo "?" per uscire.

Le descrizioni vengono da help_texts.HELP (chiave nella proprietà "help_key" di azioni e controlli);
per tutto il resto la scheda si compone dal suggerimento del controllo e dalle sue opzioni.
"""
import html

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
    QFormLayout, QFrame, QHeaderView, QLabel, QLineEdit, QMenu, QMenuBar, QRadioButton, QScrollBar, QTabBar,
    QToolButton, QVBoxLayout, QWidget,
)

from ..theme import C
from . import help_texts
from freelasercut.i18n import tr  # noqa: E402

_MOUSE = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick)


def _clean(text):
    return (text or "").replace("&&", "\x00").replace("&", "").replace("\x00", "&").strip()


class HelpCard(QFrame):
    """Scheda flottante che segue il mouse (non intercetta i clic)."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setObjectName("helpcard")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setFixedWidth(340)
        v.addWidget(self.label)

    def show_text(self, html_text, near):
        self.label.setText(html_text)
        self.adjustSize()
        scr = QGuiApplication.screenAt(near) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x, y = near.x() + 18, near.y() + 20
        if x + self.width() > g.right():
            x = near.x() - self.width() - 12
        if y + self.height() > g.bottom():
            y = near.y() - self.height() - 12
        self.move(max(g.left(), x), max(g.top(), y))
        self.show()
        self.raise_()


class HelpMode(QObject):
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.card = HelpCard()
        self._timer = QTimer(self)
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._poll)
        self._last = None
        QApplication.instance().installEventFilter(self)  # per Maiusc+F1 anche dentro le finestre di dialogo

    # ------------------------------------------------------------------ attivazione
    def set_active(self, on):
        on = bool(on)
        if on == self.active:
            return
        self.active = on
        if on:
            QApplication.setOverrideCursor(QCursor(Qt.WhatsThisCursor))
            self._last = None
            self._timer.start()
            self._poll()
        else:
            self._timer.stop()
            self.card.hide()
            QApplication.restoreOverrideCursor()
        self.toggled.emit(on)

    def toggle(self):
        self.set_active(not self.active)

    # ------------------------------------------------------------------ eventi
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.KeyPress:
            if ev.key() == Qt.Key_F1 and ev.modifiers() & Qt.ShiftModifier:
                self.toggle()
                return True
            if self.active and ev.key() == Qt.Key_Escape:
                self.set_active(False)
                return True
            return False
        if not self.active or not isinstance(obj, QWidget):
            return False
        if t == QEvent.ToolTip:
            return True  # in modalità guida la scheda sostituisce i suggerimenti normali
        if t in _MOUSE:
            if self._passthrough(obj, ev):
                return False
            if t == QEvent.MouseButtonPress:
                self._last = None
                self._poll()  # aggiorna subito la scheda sul punto cliccato
            return True  # in modalità guida i clic non eseguono i comandi
        if t in (QEvent.ContextMenu, QEvent.Wheel) and not isinstance(obj, (QMenu, QScrollBar)):
            return t == QEvent.ContextMenu
        return False

    def _passthrough(self, obj, ev):
        """Clic che lasciamo passare anche in modalità guida."""
        w = obj
        while w is not None:
            if w.property("help_toggle"):
                return True  # il pulsante "?" stesso
            w = w.parentWidget()
        if isinstance(obj, (QMenuBar, QTabBar, QScrollBar)):
            return True  # aprire i menu e cambiare scheda per leggerne il contenuto
        if isinstance(obj, QMenu):
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
            a = obj.actionAt(pos)
            if a is None or a.menu() is not None or a.property("help_key") == "help_mode":
                return True
        return False

    # ------------------------------------------------------------------ descrizione
    def _poll(self):
        pos = QCursor.pos()
        w = QApplication.widgetAt(pos)
        if w is not None and w.window() is self.card:
            # il mouse è finito sotto la scheda: la nascondo per vedere cosa c'è davvero lì sotto
            self.card.hide()
            w = QApplication.widgetAt(pos)
        if w is None or w.window() is self.card:
            return
        key = (id(w), pos.x() // 6, pos.y() // 6)
        if key == self._last:
            return
        self._last = key
        info = self.describe(w, pos)
        if info is None:
            self.card.hide()
            return
        self.card.show_text(self._html(*info), pos)

    def describe(self, w, gpos):
        """(titolo, descrizione, opzioni, scorciatoia, valore) per il controllo sotto il mouse."""
        # voci di menu
        if isinstance(w, QMenu):
            a = w.actionAt(w.mapFromGlobal(gpos))
            return self._action(a) if a is not None and not a.isSeparator() else None
        if isinstance(w, QMenuBar):
            a = w.actionAt(w.mapFromGlobal(gpos))
            if a is None or a.menu() is None:
                return None
            opts = [(_clean(x.text()), x.statusTip() or "") for x in a.menu().actions() if not x.isSeparator()]
            return (f"Menu {_clean(a.text())}", tr("Clic per aprirlo; passa sulle voci per leggerne la descrizione."),
                    opts, "", "")
        # celle e intestazioni di tabelle, liste, tendine aperte
        view = w.parentWidget() if w.parentWidget() is not None and isinstance(w.parentWidget(), QAbstractItemView) else None
        if isinstance(w, QHeaderView) or isinstance(view, QHeaderView):
            hv = w if isinstance(w, QHeaderView) else view
            return self._header(hv, gpos)
        if view is not None:
            r = self._item_view(view, gpos)
            if r is not None:
                return r
        # pulsanti delle barre: descrivi l'azione
        x = w
        while x is not None:
            if isinstance(x, QToolButton) and x.defaultAction() is not None:
                return self._action(x.defaultAction(), x)
            key = x.property("help_key")
            if key or x.toolTip() or x.whatsThis() or isinstance(x, (QAbstractButton, QComboBox, QAbstractSpinBox,
                                                                       QLineEdit, QAbstractSlider)):
                return self._widget(x, key)
            if x.isWindow():
                break
            x = x.parentWidget()
        return None

    def _action(self, a, button=None):
        key = a.property("help_key")
        entry = help_texts.lookup(key)
        title = entry[0] if entry else _clean(a.text())
        body = entry[1] if entry else (a.statusTip() or (a.toolTip() if a.toolTip() != _clean(a.text()) else ""))
        opts = list(entry[2]) if entry and entry[2] else []
        menu = a.menu() or (button.menu() if button is not None else None)
        if menu is not None and not opts:
            opts = [(_clean(x.text()), x.statusTip() or "") for x in menu.actions() if not x.isSeparator()]
        sc = a.shortcut().toString(QKeySequence.NativeText)
        val = ""
        if a.isCheckable():
            val = tr("attivo") if a.isChecked() else tr("non attivo")
        if not a.isEnabled():
            val = (val + " · " if val else "") + tr("non disponibile adesso")
        return title, body or tr("Comando."), opts, sc, val

    def _widget(self, w, key):
        entry = help_texts.lookup(key)
        title = entry[0] if entry else ""
        body = entry[1] if entry else ""
        opts = list(entry[2]) if entry and entry[2] else []
        tip = w.whatsThis() or w.toolTip()
        if not title:
            title = self._form_label(w) or _clean(getattr(w, "text", lambda: "")() if isinstance(w, QAbstractButton) else "")
        if not body:
            body = tip
        val = ""
        if isinstance(w, QComboBox):
            if not opts:
                for i in range(min(w.count(), 30)):
                    d = w.itemData(i, Qt.ToolTipRole)
                    opts.append((w.itemText(i), d if isinstance(d, str) else ""))
            val = w.currentText()
            title = title or tr("Menu a tendina")
        elif isinstance(w, QAbstractSpinBox):
            if not hasattr(w, "minimum"):
                return title or tr("Campo"), body or "", opts, "", w.text()
            lo, hi = w.minimum(), w.maximum()
            suf = w.suffix() if hasattr(w, "suffix") else ""
            dec = w.decimals() if hasattr(w, "decimals") else 0
            fmt = (lambda v: f"{v:.{dec}f}".rstrip("0").rstrip(".") if dec else f"{v:g}")
            rng = tr("Valori da {0} a {1}{2}", fmt(lo), fmt(hi), suf)
            body = f"{body}<br>{rng}." if body else rng + "."
            val = w.text()
        elif isinstance(w, (QCheckBox, QRadioButton)):
            title = title or _clean(w.text())
            val = tr("attivo") if w.isChecked() else tr("non attivo")
        elif isinstance(w, QAbstractButton) and w.isCheckable():
            val = tr("attivo") if w.isChecked() else tr("non attivo")
        elif isinstance(w, QLineEdit):
            val = w.text()
        elif isinstance(w, QAbstractSlider):
            val = str(w.value())
        if not title and not body:
            return None
        if not w.isEnabled():
            val = (val + " · " if val else "") + tr("non disponibile adesso")
        return title or tr("Controllo"), body or "", opts, "", val

    def _form_label(self, w):
        """Etichetta di un campo dentro un modulo (QFormLayout)."""
        p = w.parentWidget()
        if p is None or p.layout() is None:
            return ""
        stack = [p.layout()]
        while stack:
            lay = stack.pop()
            if isinstance(lay, QFormLayout):
                lab = lay.labelForField(w)
                if isinstance(lab, QLabel) and lab.text():
                    return _clean(lab.text())
            for i in range(lay.count()):
                it = lay.itemAt(i)
                if it is not None and it.layout() is not None:
                    stack.append(it.layout())
        return ""

    def _header(self, hv, gpos):
        sec = hv.logicalIndexAt(hv.mapFromGlobal(gpos))
        if sec < 0:
            return None
        owner = hv.parentWidget()
        key = owner.property("help_key") if owner is not None else None
        entry = help_texts.lookup(f"{key}:col:{sec}") if key else None
        if entry is None and key == "layers:table":
            entry = help_texts.lookup(f"layers:col:{sec}")
        model = hv.model()
        text = str(model.headerData(sec, hv.orientation()) or "") if model else ""
        tip = model.headerData(sec, hv.orientation(), Qt.ToolTipRole) if model else ""
        if entry:
            return entry[0], entry[1], list(entry[2] or []), "", ""
        return (f"Colonna «{text}»", tip if isinstance(tip, str) else "", [], "", "") if text else None

    def _item_view(self, view, gpos):
        idx = view.indexAt(view.viewport().mapFromGlobal(gpos))
        key = view.property("help_key")
        # tendina aperta: descrivi la singola voce
        combo = view.parentWidget()
        while combo is not None and not isinstance(combo, QComboBox) and not combo.isWindow():
            combo = combo.parentWidget()
        if isinstance(combo, QComboBox) or (view.window() is not None and view.window().windowType() == Qt.Popup):
            if not idx.isValid():
                return None
            tip = idx.data(Qt.ToolTipRole)
            return str(idx.data() or ""), tip if isinstance(tip, str) else tr("Voce del menu a tendina."), [], "", ""
        if key == "layers:table" and idx.isValid():
            e = help_texts.lookup(f"layers:col:{idx.column()}")
            if e:
                return e[0], e[1], list(e[2] or []), "", str(idx.data() or "")
        if key:
            e = help_texts.lookup(key)
            if e:
                return e[0], e[1], list(e[2] or []), "", ""
        return None

    @staticmethod
    def _html(title, body, opts, shortcut, value):
        muted = C["muted"]
        h = f"<div style='font-weight:700; font-size:9.5pt'>{html.escape(title)}"
        if shortcut:
            h += f" <span style='color:{muted}; font-weight:400'>· {html.escape(shortcut)}</span>"
        h += "</div>"
        if body:
            h += f"<div style='margin-top:3px'>{body if '<br>' in body else html.escape(body)}</div>"
        if opts:
            h += "<div style='margin-top:5px; font-weight:600'>Opzioni</div><ul style='margin:2px 0 0 -18px'>"
            for name, desc in opts[:24]:
                h += f"<li><b>{html.escape(name)}</b>" + (f" — {html.escape(desc)}" if desc else "") + "</li>"
            h += "</ul>"
        if value:
            h += f"<div style='margin-top:4px; color:{muted}'>Adesso: {html.escape(value)}</div>"
        h += tr("<div style='margin-top:6px; color:{0}; font-size:7.5pt'>Guida attiva · Esc per uscire</div>", muted)
        return h
