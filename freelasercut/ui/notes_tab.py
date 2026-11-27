# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Note del progetto (0.23.5, chiesto da Costanzo; idea della linguetta di Ale, 27/11/2026).

Una linguetta «Note» attaccata all'angolo in basso a destra del piano disegnato, speculare alle linguette dei piani
(in alto a sinistra): segue zoom e spostamenti e, se l'angolo esce dalla vista, resta sul bordo. Un clic apre un
foglietto sopra l'angolo del piano dove si scrive testo libero; un altro clic (o Esc) lo chiude. «Note ●» quando c'è
scritto qualcosa; passando il mouse si leggono le prime righe.

Non disturba il resto: niente voci di menu né scorciatoie nuove, niente sopra i pannelli del Banco (si ferma prima),
nascosta nella vista d'insieme dei piani. Il testo sta nel documento (`Document.notes`, chiave «notes» del file, solo
se c'è) e si salva con il progetto; scriverlo segna il progetto come modificato. La nota non va mai nei rapporti né
sul telefono e la Galleria la toglie prima di pubblicare (galleria.progetto_ripulito)."""
import html

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout

from freelasercut.i18n import tr  # noqa: E402
from freelasercut import fontscale  # noqa: E402

from ..core.document import NOTES_MAX

PANEL_W, PANEL_H = 320, 220
PREVIEW_LINES = 3


class NotesTab(QObject):
    """La linguetta e il suo foglietto, figli del viewport della tela (come le linguette dei piani)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        cv = win.canvas
        vp = cv.viewport()
        self.btn = QToolButton(vp)
        self.btn.setObjectName("notesTab")
        self.btn.setCheckable(True)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFocusPolicy(Qt.NoFocus)
        self.btn.setProperty("help_key", "project_notes")
        self.btn.toggled.connect(self._toggled)
        self.panel = QFrame(vp)
        self.panel.setObjectName("notesPanel")
        self.panel.setProperty("help_key", "project_notes")
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)
        self.title = QLabel(tr("Note del progetto"))
        self.title.setObjectName("notesTitle")
        lay.addWidget(self.title)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("notesEdit")
        self.edit.setProperty("help_key", "project_notes")
        self.edit.setPlaceholderText(tr("Scrivi qui le note di questo progetto: materiale, impostazioni, per chi è… "
                                        "Si salvano con il progetto e non vengono mai incise."))
        self.edit.setTabChangesFocus(True)
        # foglietto di grandezza fissa: il testo va a capo da solo e, quando è lungo, scorre in verticale
        self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.textChanged.connect(self._edited)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit, 1)
        self.panel.hide()
        self._doc = None
        self._style_key = None
        self._loading = False
        vp.installEventFilter(self)  # il viewport cambia grandezza: la linguetta resta al suo posto
        cv.view_changed.connect(self.place)
        win.editor.changed.connect(self.sync)
        self.sync()
        self.btn.show()

    # ---------------------------------------------------------- documento
    def text(self):
        return getattr(self.win.editor.doc, "notes", "") or ""

    def sync(self):
        """Un altro documento (nuovo, aperto, recuperato): il foglietto mostra la sua nota."""
        doc = self.win.editor.doc
        if doc is self._doc:
            return
        self._doc = doc
        self._loading = True
        try:
            self.edit.setPlainText(self.text())
        finally:
            self._loading = False
        self._label()

    def _edited(self):
        if self._loading:
            return
        t = self.edit.toPlainText()
        if len(t) > NOTES_MAX:  # un limite largo, per non gonfiare il file
            t = t[:NOTES_MAX]
            self._loading = True
            try:
                self.edit.setPlainText(t)
                self.edit.moveCursor(QTextCursor.MoveOperation.End)
            finally:
                self._loading = False
        doc = self.win.editor.doc
        if t == (getattr(doc, "notes", "") or ""):
            return
        doc.notes = t
        self.win.editor.dirty = True
        if hasattr(self.win, "_update_title"):
            self.win._update_title()
        self._label()

    def _label(self):
        t = self.text().strip()
        self.btn.setText(tr("Note ●") if t else tr("Note"))
        tip = "<b>" + html.escape(tr("Note del progetto")) + "</b><br>" + html.escape(
            tr("Clic per aprirle o chiuderle. Si salvano con il progetto e non vengono mai incise."))
        if t:
            righe = t.splitlines()
            anteprima = "\n".join(r[:80] for r in righe[:PREVIEW_LINES]) + ("\n…" if len(righe) > PREVIEW_LINES else "")
            tip += "<hr>" + html.escape(anteprima).replace("\n", "<br>")
        self.btn.setToolTip(tip)
        self.place()  # «Note ●» è più larga di «Note»: si riallinea all'angolo del piano

    # ---------------------------------------------------------- apri e chiudi
    def _toggled(self, on):
        self.panel.setVisible(on)
        if on:
            self.place()
            self.panel.raise_()
            self.edit.setFocus(Qt.OtherFocusReason)
            self.edit.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self.win.canvas.setFocus(Qt.OtherFocusReason)

    def close(self):
        self.btn.setChecked(False)

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and e.key() == Qt.Key_Escape:
            if e.type() == QEvent.ShortcutOverride:  # Esc è del foglietto, non delle scorciatoie della finestra
                e.accept()
                return True
            self.close()
            return True
        if obj is self.win.canvas.viewport() and e.type() == QEvent.Resize:
            self.place()
        return False

    # ---------------------------------------------------------- aspetto e posizione
    def _restyle(self):
        cv = self.win.canvas
        light = cv.light_bed
        if self._style_key == light:
            return
        self._style_key = light
        from .canvas import BED_DARK, BED_LIGHT
        from .plates import TAB_TEXT

        pal = BED_LIGHT if light else BED_DARK
        idle = "rgba(255,255,255,210)" if light else "rgba(255,255,255,30)"
        hover = "rgba(255,255,255,235)" if light else "rgba(255,255,255,45)"
        cur, other = TAB_TEXT[light]
        paper = "#FFFBEA" if light else "#2A2F3A"
        ink = "#1F2430" if light else "#E6EAF2"
        bar, bar_hover = ("rgba(31,36,48,70)", "rgba(31,36,48,130)") if light else ("rgba(230,234,242,70)",
                                                                                    "rgba(230,234,242,130)")
        # la linguetta è la gemella di quelle dei piani, girata: attaccata sotto il bordo, angoli tondi in basso
        self.btn.setStyleSheet(fontscale.css(f"""
QToolButton#notesTab {{ background: {idle}; border: 1px solid {pal["grid_major"]}; border-top: none;
    border-bottom-left-radius: 5px; border-bottom-right-radius: 5px; padding: 1px 10px 2px 10px;
    font-size: 9pt; font-weight: 600; color: {other}; }}
QToolButton#notesTab:hover {{ background: {hover}; color: {cur}; }}
QToolButton#notesTab:checked {{ background: {pal["bed"]}; border-color: {pal["edge"]}; color: {cur};
    font-weight: 700; }}
"""))
        self.panel.setStyleSheet(fontscale.css(f"""
QFrame#notesPanel {{ background: {paper}; border: 1px solid {pal["edge"]}; border-radius: 6px; }}
QLabel#notesTitle {{ color: {ink}; font-size: 9pt; font-weight: 700; background: transparent; }}
QPlainTextEdit#notesEdit {{ background: transparent; color: {ink}; border: none; font-size: 10pt; }}
QPlainTextEdit#notesEdit QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; border: none; }}
QPlainTextEdit#notesEdit QScrollBar::handle:vertical {{ background: {bar}; border-radius: 4px; min-height: 28px; }}
QPlainTextEdit#notesEdit QScrollBar::handle:vertical:hover {{ background: {bar_hover}; }}
QPlainTextEdit#notesEdit QScrollBar::add-line:vertical, QPlainTextEdit#notesEdit QScrollBar::sub-line:vertical {{
    height: 0; border: none; background: transparent; }}
QPlainTextEdit#notesEdit QScrollBar::add-page:vertical, QPlainTextEdit#notesEdit QScrollBar::sub-page:vertical {{
    background: transparent; }}
"""))

    def _limits(self):
        """(sinistra, alto, destra, basso) dove la linguetta e il foglietto possono stare, in coordinate del viewport:
        mai sotto i righelli, mai sopra i pannelli del Banco."""
        from .canvas import RULER

        cv = self.win.canvas
        vp = cv.viewport()
        left, top, right, bottom = RULER + 4, RULER + 2, vp.width() - 4, vp.height() - 4
        bc = getattr(self.win, "banco", None)
        if bc is not None:
            ins = getattr(cv, "fit_insets", (0, 0, 0, 0))
            right = vp.width() - ins[2] - 4
            if not bc.locked() and bc.rail.isVisible():
                left = max(left, ins[0])
            off = vp.mapTo(cv, vp.rect().topLeft())
            for w in (getattr(bc, "island", None), getattr(bc, "view_box", None),
                      getattr(getattr(bc, "cockpit", None), "bottom", None)):
                if w is not None and w.isVisible() and w.parent() is cv:
                    bottom = min(bottom, w.y() - off.y() - 6)
        return left, top, max(left + 60, right), max(top + 30, bottom)

    def place(self):
        cv = self.win.canvas
        ov = getattr(self.win, "plate_overview", None)
        hide = ov is not None and ov.isVisible()  # la vista d'insieme copre tutto il piano
        self.btn.setVisible(not hide)
        if hide:
            self.panel.hide()
            return
        self.panel.setVisible(self.btn.isChecked())
        self._restyle()
        self.btn.adjustSize()
        left, top, right, bottom = self._limits()
        corner = cv.to_view(QPointF(cv.bed_x, 0.0))  # angolo in basso a destra del piano
        w, h = self.btn.width(), self.btn.height()
        x = min(max(left, round(corner.x()) - w), right - w)
        y = min(max(top, round(corner.y()) - 1), bottom - h)
        self.btn.move(x, y)
        self.btn.raise_()
        if self.panel.isVisible():
            pw = min(PANEL_W, max(160, right - left))
            ph = min(PANEL_H, max(100, bottom - top - h - 4))
            self.panel.resize(pw, ph)
            px = min(max(left, x + w - pw), right - pw)
            py = y - ph - 2
            if py < top:  # non c'è posto sopra: sotto la linguetta, o dove ci sta
                py = min(max(top, y + h + 2), bottom - ph)
            self.panel.move(px, py)
            self.panel.raise_()
