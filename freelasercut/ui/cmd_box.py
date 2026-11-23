# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Casella «Cerca un comando» fissa nella barra in basso dell'interfaccia classica (0.19.3).

Voluta e approvata da Ale il 13/11: discreta, alta come il pulsante «Griglia», subito dopo di lui; le proposte si
aprono verso l'alto con il comando migliore in cima (come la ricerca di Windows). Con la casella vuota: gli ultimi
comandi usati. Sulle finestre strette resta solo una lente, che si allarga sopra le scritte vicine finché si scrive.
Ctrl+F e F3 portano qui: nella classica la finestrella al centro non c'è più (nel Banco resta com'è).

Il motore è lo stesso della finestrella (banco.CommandPalette): stessi comandi letti dai menu, stesso ordine,
stessi «usati di recente». Qui cambia solo dove stanno la casella e l'elenco.
"""
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import QLineEdit, QToolButton, QWidget

from freelasercut.i18n import tr  # noqa: E402
from freelasercut import fontscale  # noqa: E402
from ..theme import C
from . import style
from .banco import PALETTE_QSS, CommandPalette

BOX_W = 150  # larghezza della casella quando c'è posto (cresce se la scritta nella lingua scelta è più lunga)
LENS_W = 24  # sulle finestre strette: solo la lente
OPEN_W = 190  # la lente che si allarga mentre si scrive
MSG_MIN = 300  # ai messaggi della barra devono restare almeno questi pixel, altrimenti la casella diventa lente
LIST_W = 420
ROW_H = 34
MAX_ROWS = 8
RECENT_ROWS = 6


class CommandBox(CommandPalette):
    """Il motore della ricerca, con la casella nella barra di stato e l'elenco che si apre sopra di lei."""

    def __init__(self, win):
        super().__init__(win)
        sb = win.statusBar()
        self.sb = sb
        # l'elenco: non una finestra a parte ma un riquadro dentro la finestra principale, sopra tutto il resto.
        # Così non prende mai il fuoco (si continua a scrivere nella casella), non cambia la finestra attiva e sta
        # dove lo si mette anche sui sistemi che non lasciano posizionare le finestre (Wayland)
        self.setParent(win)
        self.setWindowFlags(Qt.Widget)
        self.hide()
        self.setFocusPolicy(Qt.NoFocus)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(PALETTE_QSS)
        self.layout().setContentsMargins(6, 6, 6, 6)
        self.layout().removeWidget(self.edit)
        self.hint.hide()
        # il segnaposto nella barra (tiene il posto) e la casella vera, figlia della barra, messa sopra di lui
        self.holder = QWidget()
        self.holder.setObjectName("cmdBoxHolder")
        self.holder.setProperty("help_key", "palette")
        self.lens = QToolButton(self.holder)
        self.lens.setObjectName("snapbtn")
        self.lens.setIcon(style.icon("search", size=14))
        self.lens.setIconSize(QSize(14, 14))
        self.lens.setToolTip(tr("Cerca un comando (Ctrl+F)"))
        self.lens.setCursor(Qt.PointingHandCursor)
        self.lens.setProperty("help_key", "palette")
        self.lens.clicked.connect(self.open)
        self.lens.hide()
        self.edit.setParent(sb)
        self.edit.setObjectName("cmdBoxEdit")
        self.edit.setPlaceholderText(tr("Cerca un comando"))
        self.edit.setClearButtonEnabled(False)
        self.edit.addAction(style.icon("search", color=C["muted"], size=13), QLineEdit.LeadingPosition)
        self.edit.setProperty("help_key", "palette")
        self.edit.setToolTip(tr("Scrivi una parola e trovi il comando, in qualsiasi menu sia (Ctrl+F)"))
        # discreta finché non serve: fondo della barra e bordo leggero, come il pulsante «Griglia»; quando ci si
        # scrive diventa un campo bianco come tutti gli altri campi del programma
        self.edit.setStyleSheet(fontscale.css(
            f"QLineEdit#cmdBoxEdit {{ font-size: 8.5pt; padding: 1px 4px; border-radius: 6px; background: transparent; "
            f"color: {C['text']}; border: 1px solid {C['border']}; }}"
            f"QLineEdit#cmdBoxEdit:hover {{ border-color: {C['accent_hi']}; }}"
            f"QLineEdit#cmdBoxEdit:focus {{ background: #FFFFFF; color: #0E1526; border: 1px solid {C['accent']}; }}"))
        self.compact = False
        self._opened = False
        self._height = 21
        sb.installEventFilter(self)
        self.holder.installEventFilter(self)
        win.installEventFilter(self)
        QTimer.singleShot(0, self.relayout)

    # ------------------------------------------------------------------ misure
    def box_width(self):
        """Larga quanto serve alla scritta grigia nella lingua scelta (mai meno di BOX_W)."""
        fm = self.edit.fontMetrics()
        return max(BOX_W, fm.horizontalAdvance(self.edit.placeholderText()) + 44)

    def free_for_messages(self, total=None):
        """Pixel che resterebbero ai messaggi della barra con la casella intera."""
        sb = self.sb
        total = sb.width() if total is None else total
        fixed = 0
        for w in sb.children():
            if not isinstance(w, QWidget) or w in (self.holder, self.edit) or w.parent() is not sb:
                continue
            if w.isHidden() or w.inherits("QSizeGrip"):
                continue
            hint = w.sizeHint().width() if not w.maximumWidth() < 16777215 else w.maximumWidth()
            fixed += max(hint, w.minimumWidth()) + 6
        return total - fixed - self.box_width() - 6

    def should_compact(self, total=None):
        return self.free_for_messages(total) < MSG_MIN

    def relayout(self):
        """Mette la casella al suo posto: intera, oppure lente (finestre strette)."""
        ref = next((b for b in self.sb.findChildren(QToolButton, "snapbtn") if b is not self.lens), None)
        self._height = max(19, ref.sizeHint().height() if ref is not None else 21)
        self.compact = self.should_compact()
        self.holder.setFixedSize(LENS_W if self.compact else self.box_width(), self._height)
        self.lens.setGeometry(0, 0, LENS_W, self._height)
        self.lens.setVisible(self.compact)
        QTimer.singleShot(0, self._place_edit)

    def _place_edit(self):
        if self.compact and not self._opened:
            self.edit.hide()
            return
        top_left = self.holder.mapTo(self.sb, QPoint(0, 0))
        w = OPEN_W if self.compact else self.holder.width()
        x = min(top_left.x(), max(0, self.sb.width() - w - 4))
        self.edit.setGeometry(x, top_left.y(), w, self._height)
        self.edit.show()
        self.edit.raise_()
        if self.isVisible():
            self._place_list()

    def _place_list(self):
        rows = min(self.list.count(), MAX_ROWS)
        if not rows:
            self.hide()
            return
        h = rows * ROW_H + 14
        self.resize(LIST_W, h)
        g = self.edit.mapTo(self.win, QPoint(0, 0))  # coordinate della finestra principale
        x = max(2, min(g.x(), self.win.width() - LIST_W - 2))  # attaccato alla casella, ma dentro la finestra
        y = max(2, g.y() - h - 3)
        self.move(x, y)

    # ------------------------------------------------------------------ aprire, filtrare, chiudere
    def open(self):
        """Ctrl+F, F3, il menu Aiuto, un clic sulla lente: il cursore va nella casella e compaiono gli ultimi comandi."""
        self.collect()
        self._opened = True
        self._place_edit()
        self.edit.setFocus(Qt.ShortcutFocusReason)
        self.edit.selectAll()
        self._filter(self.edit.text())

    def _filter(self, text):
        if not self._opened:
            return
        if not self.entries:
            self.collect()
        super()._filter(text)
        if not text.strip():  # casella vuota: solo gli ultimi comandi usati (i più recenti in cima)
            recent = self.recent()
            keep = []
            for i in range(self.list.count()):
                a = self.list.item(i).data(Qt.UserRole)
                if self.key_of(a) in recent:
                    keep.append(i)
            for i in range(self.list.count() - 1, -1, -1):
                if i not in keep[:RECENT_ROWS]:
                    self.list.takeItem(i)
            if self.list.count():
                self.list.setCurrentRow(0)
        self._show_list()

    def _show_list(self):
        if not self.list.count() or not self._opened:
            self.hide()
            return
        self._place_list()
        if not self.isVisible():
            self.show()
        self.raise_()

    def close_box(self, clear=True, refocus=True):
        """Esc, un clic fuori, un comando eseguito: l'elenco sparisce, la casella si svuota e torna com'era."""
        self._opened = False
        self.hide()
        if clear:
            self.edit.blockSignals(True)
            self.edit.clear()
            self.edit.blockSignals(False)
        if refocus and self.edit.hasFocus():
            self.win.canvas.setFocus(Qt.OtherFocusReason)
        self._place_edit()

    def is_open(self):
        return self._opened

    def _run(self, it):
        a = it.data(Qt.UserRole) if it is not None else None
        if a is None or not a.isEnabled():
            return
        self.remember(a)
        self.close_box()
        QTimer.singleShot(0, a.trigger)

    # ------------------------------------------------------------------ tasti e finestra
    def eventFilter(self, obj, e):
        t = e.type()
        if obj is self.edit:
            if t == QEvent.KeyPress:
                k = e.key()
                if k in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
                    r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                    self.list.setCurrentRow(max(0, min(r, self.list.count() - 1)))
                    return True
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    self._run(self.list.currentItem())
                    return True
                if k == Qt.Key_Escape:
                    self.close_box()
                    return True
                return False
            if t == QEvent.FocusIn and not self._opened:
                QTimer.singleShot(0, self.open)  # un clic nella casella
                return False
            if t == QEvent.FocusOut:
                # un clic su una riga dell'elenco non toglie il fuoco (l'elenco non lo prende): qui si è andati altrove
                QTimer.singleShot(120, self._focus_lost)
                return False
            return False
        if obj is self.sb and t in (QEvent.Resize, QEvent.LayoutRequest):
            QTimer.singleShot(0, self._after_resize)
        elif obj is self.holder and t in (QEvent.Move, QEvent.Show):
            QTimer.singleShot(0, self._place_edit)
        elif obj is self.win and t in (QEvent.Resize, QEvent.WindowDeactivate, QEvent.WindowStateChange):
            if t == QEvent.WindowDeactivate:
                QTimer.singleShot(150, self._focus_lost)
            elif self.isVisible():
                QTimer.singleShot(0, self._place_list)
        return False

    def _after_resize(self):
        want = self.should_compact()
        if want != self.compact:
            self.relayout()
        else:
            self._place_edit()

    def _focus_lost(self):
        if self._opened and not self.edit.hasFocus():
            self.close_box(clear=True, refocus=False)
