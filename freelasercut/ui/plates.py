# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Piani di lavoro: le linguette «Piano 1 · Piano 2 · +» attaccate in alto a sinistra al piano disegnato sulla tela.

Ogni piano è un lavoro a sé nello stesso progetto, con la stessa macchina e gli stessi livelli. Mentre il laser
incide un piano si può preparare il successivo: il piano in incisione ha ▶ e l'avanzamento sulla sua scheda e i
suoi oggetti restano visibili in grigio come riferimento."""
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QTransform
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QMenu, QMessageBox, QTabBar, QToolButton, QWidget

from freelasercut.i18n import tr  # noqa: E402

from ..core.document import ImageShape

JOB_COLOR = "#E8792B"


class _Tabs(QTabBar):
    def wheelEvent(self, e):  # la rotella sopra le linguette fa lo zoom della tela, non cambia piano per sbaglio
        e.ignore()


class PlateBar(QWidget):
    """Le linguette dei piani, attaccate in alto a sinistra al bordo del piano disegnato sulla tela (seguono zoom e
    spostamenti; se il bordo esce dalla vista restano in alto)."""

    def __init__(self, win):
        super().__init__(win.canvas.viewport())
        self.win = win
        self.setObjectName("plateBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.tabs = _Tabs()
        self.tabs.setObjectName("plateTabs")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)  # solo se le linguette non ci stanno
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setFocusPolicy(Qt.NoFocus)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(lambda pt: self.tab_menu(self.tabs.tabAt(pt), self.tabs.mapToGlobal(pt)))
        self.tabs.tabBarDoubleClicked.connect(lambda i: self.rename(i) if i >= 0 else self.new_plate())
        self.tabs.currentChanged.connect(self._picked)
        self.tabs.setToolTip(tr("Piani di lavoro del progetto: clic per passare a un altro piano (Ctrl+PagSu / "
                                "Ctrl+PagGiù), doppio clic per rinominarlo, tasto destro per le altre azioni"))
        self.add_btn = QToolButton()
        self.add_btn.setObjectName("plateAdd")
        self.add_btn.setText("+")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setToolTip(tr("Nuovo piano di lavoro: un altro lavoro nello stesso progetto, con la stessa macchina "
                                   "e gli stessi livelli. Puoi prepararlo mentre il laser incide un altro piano."))
        self.add_btn.clicked.connect(self.new_plate)
        self.ghosts = QToolButton()
        self.ghosts.setObjectName("plateGhosts")
        self.ghosts.setCheckable(True)
        self.ghosts.setCursor(Qt.PointingHandCursor)
        self.ghosts.setToolTip(tr("Mostra gli altri piani: i loro oggetti in grigio, come riferimento (non si "
                                  "selezionano e non vengono incisi con questo piano)"))
        self.ghosts.setChecked(win.canvas.show_ghosts)
        self.ghosts.toggled.connect(self._ghosts_toggled)
        self.overview = QToolButton()
        self.overview.setObjectName("plateOverviewBtn")
        self.overview.setCheckable(True)
        self.overview.setCursor(Qt.PointingHandCursor)
        self.overview.setToolTip(tr("Vista d'insieme: tutti i piani affiancati, in ordine. Clic su un piano per "
                                    "modificarlo (Ctrl+Maiusc+O)"))
        self.overview.toggled.connect(self._overview_toggled)
        lay.addWidget(self.tabs, 0, Qt.AlignBottom)
        lay.addWidget(self.add_btn, 0, Qt.AlignBottom)
        lay.addWidget(self.ghosts, 0, Qt.AlignBottom)
        lay.addWidget(self.overview, 0, Qt.AlignBottom)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._ncount = None
        self._style_key = None
        win.editor.plates_changed.connect(self.rebuild)
        win.editor.changed.connect(self._counts)
        win.canvas.view_changed.connect(self.place)
        self.rebuild()
        self.show()

    # ---------------------------------------------------------- aspetto e posizione
    def _restyle(self):
        cv = self.win.canvas
        light = cv.light_bed
        if self._style_key == light:
            return
        self._style_key = light
        from .canvas import BED_DARK, BED_LIGHT

        pal = BED_LIGHT if light else BED_DARK
        idle = "rgba(255,255,255,210)" if light else "rgba(255,255,255,30)"
        hover = "rgba(255,255,255,220)" if light else "rgba(255,255,255,40)"
        btn = "#5B6578" if light else "#AEB8CB"
        self.setStyleSheet(f"""
QWidget#plateBar {{ background: transparent; }}
QTabBar#plateTabs {{ background: transparent; }}
QTabBar#plateTabs::tab {{ background: {idle}; border: 1px solid {pal["grid_major"]}; border-bottom: none;
    border-top-left-radius: 5px; border-top-right-radius: 5px; padding: 1px 10px 2px 10px; margin-right: 2px;
    font-size: 9pt; font-weight: 600; min-width: 0; }}
QTabBar#plateTabs::tab:selected {{ background: {pal["bed"]}; border-color: {pal["edge"]}; font-weight: 700; }}
QTabBar#plateTabs::tab:hover:!selected {{ background: {hover}; }}
QToolButton#plateAdd, QToolButton#plateGhosts, QToolButton#plateOverviewBtn {{ background: transparent; border: none;
    color: {btn}; font-size: 11pt; font-weight: 700; padding: 0 4px 1px 4px; border-radius: 4px; }}
QToolButton#plateAdd:hover, QToolButton#plateGhosts:hover, QToolButton#plateOverviewBtn:hover {{ background: {hover}; }}
QToolButton#plateGhosts:checked, QToolButton#plateOverviewBtn:checked {{ background: rgba(47,125,246,45); }}
""")
        from . import style

        on = "#2F7DF6" if light else "#8DB8FF"  # acceso: blu, come il bordo del piano attivo nella vista d'insieme
        self.ghosts.setIcon(style.icon("layers", btn, 14, active=on))
        self.overview.setIcon(style.icon("pages", btn, 14, active=on))
        self.refresh()

    def place(self):
        """In alto a sinistra sul bordo del piano, come una linguetta; mai sotto i righelli né fuori dalla vista."""
        from .canvas import RULER

        cv = self.win.canvas
        self._restyle()
        vp = cv.viewport()
        corner = cv.to_view(QPointF(0.0, cv.bed_y))
        ov = getattr(self.win, "plate_overview", None)
        if ov is not None and ov.isVisible():  # vista d'insieme: le linguette in alto a sinistra
            corner = QPointF(ov._area().left(), RULER + 2 + self.height())
        # nel Banco ci sono i pannelli sopra la tela, a sinistra e a destra: le linguette non ci vanno sotto
        ins = getattr(cv, "fit_insets", (0, 0, 0, 0)) if getattr(self.win, "banco", None) else (0, 0, 0, 0)
        left = max(RULER + 4, ins[0] if not self.win.banco.locked() and self.win.banco.rail.isVisible() else 0) \
            if getattr(self.win, "banco", None) else RULER + 4
        x0 = max(left, round(corner.x()))
        right = vp.width() - ins[2] - 4
        extra = self.add_btn.sizeHint().width() + 6 + sum(b.sizeHint().width() + 2 for b in (self.ghosts, self.overview)
                                                           if b.isVisible())
        room = max(120, right - x0 - extra)  # tante linguette: compaiono le frecce invece di uscire dalla vista
        self.tabs.setMaximumWidth(room)
        self.tabs.adjustSize()
        self.adjustSize()
        x = min(x0, max(left, right - self.width()))
        y = min(max(RULER + 2, round(corner.y()) - self.height() + 1), max(RULER + 2, vp.height() - self.height() - 4))
        self.move(x, y)
        self.raise_()

    # ---------------------------------------------------------- stato
    def _job_index(self):
        uid = getattr(self.win, "_job_plate", None)
        if uid is None or not self.win.ctl.job_active:
            return None
        return self.win.editor.doc.plate_index(uid)

    def _progress(self):
        ctl = self.win.ctl
        n = len(getattr(ctl, "job_lines", None) or [])
        return 100.0 * getattr(ctl, "job_acked", 0) / n if n else 0.0

    def tab_text(self, i):
        name = self.win.editor.doc.plate_name(i)
        if i == self._job_index():
            return tr("▶ {0} · {1:.0f}%", name, self._progress())
        return name

    def rebuild(self):
        doc = self.win.editor.doc
        tb = self.tabs
        tb.blockSignals(True)
        while tb.count() > len(doc.plates):
            tb.removeTab(tb.count() - 1)
        while tb.count() < len(doc.plates):
            tb.addTab("")
        tb.setCurrentIndex(doc.current)
        tb.blockSignals(False)
        self.ghosts.setVisible(len(doc.plates) > 1)
        self.overview.setVisible(len(doc.plates) > 1 or self.overview.isChecked())
        self._ncount = None
        self.refresh()

    def _counts(self):
        """Il numero di oggetti nei suggerimenti delle schede (solo se è cambiato)."""
        doc = self.win.editor.doc
        n = (self._job_index(),) + tuple(len(p.shapes) for p in doc.plates)
        if n == self._ncount:
            return
        self._ncount = n
        job = n[0]
        for i, k in enumerate(n[1:]):
            if i < self.tabs.count() and i != job:
                self.tabs.setTabToolTip(i, tr("{0}: {1} oggetti", doc.plate_name(i), k))

    def refresh(self):
        doc = self.win.editor.doc
        job = self._job_index()
        light = self.win.canvas.light_bed
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, self.tab_text(i))
            if i == job:
                col = JOB_COLOR
            elif i == doc.current:  # 0.17.7: scritte più scure (prima si leggevano a malapena)
                col = "#0B1220" if light else "#FFFFFF"
            else:
                col = "#2E3A4F" if light else "#D6DEEC"
            self.tabs.setTabTextColor(i, QColor(col))
        self._counts()
        if job is not None:
            self.tabs.setTabToolTip(job, tr("«{0}» è in incisione: {1:.0f}%. Intanto puoi preparare un altro piano.",
                                            doc.plate_name(job), self._progress()))
        elif self._timer.isActive():
            self._timer.stop()
            self._ncount = None
            self._counts()
        self.place()

    def job_started(self):
        self._timer.start()
        self.refresh()

    # ---------------------------------------------------------- azioni
    def _picked(self, i):
        ed = self.win.editor
        if i < 0 or i == ed.doc.current:
            return
        ed.commit()  # un testo a metà resta sul suo piano
        if not ed.set_plate(i):
            self.rebuild()
            return
        job = self._job_index()
        if job is not None and job != i:
            self.win.statusBar().showMessage(tr("Ora lavori su «{0}». Il laser continua a incidere «{1}».",
                                                ed.doc.plate_name(i), ed.doc.plate_name(job)), 6000)

    def step(self, delta):
        doc = self.win.editor.doc
        if len(doc.plates) > 1:
            self.win.editor.set_plate((doc.current + delta) % len(doc.plates))

    def _ghosts_toggled(self, on):
        self.win.canvas.set_ghosts(on)
        self.win.qs.setValue("plates/ghosts", bool(on))
        act = self.win.acts.get("plate_ghosts") if hasattr(self.win, "acts") else None
        if act is not None and act.isChecked() != bool(on):
            act.setChecked(bool(on))

    def _overview_toggled(self, on):
        ov = getattr(self.win, "plate_overview", None)
        if ov is None:
            return
        ov.open() if on else ov.close_view()

    def overview_changed(self, on):
        """La vista d'insieme si è aperta o chiusa (anche con Esc o con un clic su un piano)."""
        for w in (self.overview, self.win.acts.get("plate_overview") if hasattr(self.win, "acts") else None):
            if w is not None and w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)
        self.overview.setVisible(len(self.win.editor.doc.plates) > 1 or on)
        if hasattr(self.win, "_plates_menu_state"):
            self.win._plates_menu_state()
        self.place()

    def new_plate(self):
        self.win.editor.add_plate()

    def rename(self, i=None):
        ed = self.win.editor
        i = ed.doc.current if i is None or i is False else i
        if not 0 <= i < len(ed.doc.plates):
            return
        name, ok = QInputDialog.getText(self.win, tr("Rinomina il piano"), tr("Nome del piano di lavoro:"),
                                        text=ed.doc.plate_name(i))
        if ok:
            ed.rename_plate(i, name)

    def duplicate(self, i=None):
        ed = self.win.editor
        i = ed.doc.current if i is None or i is False else i
        if 0 <= i < len(ed.doc.plates):
            ed.duplicate_plate(i)

    def delete(self, i=None):
        ed = self.win.editor
        doc = ed.doc
        i = doc.current if i is None or i is False else i
        if not 0 <= i < len(doc.plates) or len(doc.plates) < 2:
            return False
        if i == self._job_index():
            QMessageBox.information(self.win, tr("Elimina il piano"),
                                    tr("«{0}» è in incisione: lo puoi eliminare quando il lavoro è finito.",
                                       doc.plate_name(i)))
            return False
        n = len(doc.plates[i].shapes)
        if n:
            r = QMessageBox.question(self.win, tr("Elimina il piano"),
                                     tr("Eliminare «{0}» con i suoi {1} oggetti?\nNon si può annullare.",
                                        doc.plate_name(i), n))
            if r != QMessageBox.Yes:
                return False
        return ed.remove_plate(i)

    def move_menu(self, menu):
        """Riempie il menu «Sposta su un altro piano» (le voci cambiano con i piani)."""
        menu.clear()
        ed = self.win.editor
        doc = ed.doc
        sel = bool(ed.selection)
        for i in range(len(doc.plates)):
            if i == doc.current:
                continue
            a = menu.addAction(doc.plate_name(i))
            a.setEnabled(sel)
            a.triggered.connect(lambda _=False, i=i: ed.move_to_plate(ed.selection, i))
        if len(doc.plates) > 1:
            menu.addSeparator()
        a = menu.addAction(tr("Su un piano nuovo"))
        a.setEnabled(sel)
        a.triggered.connect(self.move_to_new)

    def move_to_new(self):
        ed = self.win.editor
        sel = list(ed.selection)
        if not sel:
            return
        i = ed.doc.add_plate()
        ed.dirty = True
        ed.plates_changed.emit()
        ed.move_to_plate(sel, i)
        ed.set_plate(i)

    def tab_menu(self, i, gpos):
        ed = self.win.editor
        doc = ed.doc
        m = QMenu(self)
        m.setAttribute(Qt.WA_DeleteOnClose)
        if i >= 0:
            if i != doc.current:
                n = len(ed.selection)
                a = m.addAction(tr("Sposta qui gli oggetti selezionati ({0})", n))
                a.setEnabled(n > 0)
                a.triggered.connect(lambda: ed.move_to_plate(ed.selection, i))
                m.addSeparator()
            m.addAction(tr("Rinomina…"), lambda: self.rename(i))
            m.addAction(tr("Duplica il piano"), lambda: self.duplicate(i))
            a = m.addAction(tr("Elimina il piano…"), lambda: self.delete(i))
            a.setEnabled(len(doc.plates) > 1)
            m.addSeparator()
        m.addAction(tr("Nuovo piano di lavoro"), self.new_plate)
        m.popup(gpos)
        return m


# tasti che restano attivi con la vista d'insieme aperta (gli altri, che modificano i disegni, no: lì non si vede
# cosa farebbero). Laser, salvataggio, ricerca e cambio di piano funzionano sempre.
OVERVIEW_KEYS = {"Esc", "0", "Home", "Ctrl+Shift+O", "Ctrl+PgUp", "Ctrl+PgDown", "Ctrl+Shift+N", "Ctrl+S", "Ctrl+Shift+S",
                 "Ctrl+O", "Ctrl+N", "Ctrl+Q", "F1", "Shift+F1", "Ctrl+F", "F3", "Ctrl+Shift+W", "Ctrl+Return",
                 "Ctrl+Enter", "Ctrl+Space", "Ctrl+Pause", "Ctrl+Shift+F", "Ctrl+Shift+K", "Alt+P"}


class _SwallowClicks(QObject):
    """Dopo un clic che chiude la vista d'insieme, il secondo clic di un doppio clic non arriva alla tela
    (selezionerebbe o modificherebbe quello che c'è sotto il mouse)."""

    def __init__(self, target, ms):
        super().__init__(target)
        self.target = target
        target.installEventFilter(self)
        QTimer.singleShot(ms, self, self.done)

    def eventFilter(self, obj, e):
        return e.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease)

    def done(self):
        self.target.removeEventFilter(self)
        self.deleteLater()


class PlateOverview(QWidget):
    """Vista d'insieme: tutti i piani di lavoro in fila, nell'ordine (1, 2, 3…), ognuno con il suo piano, il nome e
    l'avanzamento se è in incisione. Si guarda e basta: rotella = zoom, trascina = sposta, clic su un piano = si torna
    a modificare quello. Esc o di nuovo il pulsante per uscire."""

    GAP = 0.12  # spazio fra i piani, rispetto alla loro larghezza
    COLS = 4  # oltre, si va a capo

    def __init__(self, win):
        super().__init__(win.canvas.viewport())
        self.win = win
        self.setObjectName("plateOverview")
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # copre tutto: la tela sotto non si ridisegna
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        self._k = None  # px per mm (None = adatta alla vista)
        self._off = QPointF(0, 0)
        self._drag = None
        self._hover = None
        self._pix = {}  # uid del piano -> (chiave, immagine del piano già disegnata)
        self._timer = QTimer(self)
        self._timer.setInterval(500)  # durante l'incisione: avanzamento, testa e traccia
        self._timer.timeout.connect(self._tick)
        self._layout_key = None
        self._job_state = None
        win.editor.changed.connect(self.update)
        win.editor.plates_changed.connect(self.update)
        win.ctl.job_finished.connect(lambda *_: self.update())  # niente ▶ rimasto dopo la fine o lo Stop
        win.canvas.view_changed.connect(self._fit_size)
        self.hide()

    # ---------------------------------------------------------- geometria
    def _grid(self):
        doc = self.win.editor.doc
        n = max(1, len(doc.plates))
        cols = max(1, min(n, self.COLS))
        rows = (n + cols - 1) // cols
        return n, cols, rows

    LABEL = 30  # px sopra ogni piano per il nome

    def _gaps(self):
        cv = self.win.canvas
        return max(cv.bed_x, 1e-3) * self.GAP, max(cv.bed_y, 1e-3) * self.GAP

    def _area(self):
        """Parte della vista libera (nel Banco i pannelli coprono i lati)."""
        from .canvas import RULER

        cv = self.win.canvas
        bc = getattr(self.win, "banco", None)
        ins = getattr(cv, "fit_insets", (0, 0, 0, 0)) if bc else (0, 0, 0, 0)
        bottom = self.height() - max(ins[3], 30)
        if bc is not None and bc.cockpit_on and bc.cockpit.bottom.isVisible():  # Pausa/Stop durante l'incisione
            bottom = min(bottom, bc.cockpit.bottom.y() - cv.viewport().y() - 30)
        top = RULER + 30
        cb = bc.cockpit.top if bc is not None and bc.cockpit_on else None
        if cb is not None and cb.isVisible():  # la scritta «Incisione in corso»
            top = max(top, cb.geometry().bottom() - cv.viewport().y() + 8)
        return QRectF(RULER + ins[0] + 10, top, max(100, self.width() - RULER - ins[0] - ins[2] - 20),
                      max(100, bottom - top))

    def fit(self):
        n, cols, rows = self._grid()
        cv = self.win.canvas
        gx, gy = self._gaps()
        a = self._area()
        bx, by = max(cv.bed_x, 1e-3), max(cv.bed_y, 1e-3)
        self._k = max(0.02, min(a.width() / (cols * bx + (cols - 1) * gx),
                                max(20.0, a.height() - rows * self.LABEL) / (rows * by + (rows - 1) * gy)))
        self._layout_key = self._lay_key()
        tw = (cols * cv.bed_x + (cols - 1) * gx) * self._k
        th = (rows * cv.bed_y + (rows - 1) * gy) * self._k + rows * self.LABEL
        self._off = QPointF(a.left() + (a.width() - tw) / 2, a.top() + max(0.0, (a.height() - th) / 2))
        self.update()

    def plate_rect(self, i):
        """Rettangolo del piano i nella vista (px)."""
        _, cols, _ = self._grid()
        cv = self.win.canvas
        gx, gy = self._gaps()
        k = self._k
        x = self._off.x() + (i % cols) * (cv.bed_x + gx) * k
        y = self._off.y() + (i // cols) * ((cv.bed_y + gy) * k + self.LABEL) + self.LABEL
        return QRectF(x, y, cv.bed_x * k, cv.bed_y * k)

    def plate_at(self, pt):
        for i in range(len(self.win.editor.doc.plates)):
            if self.plate_rect(i).adjusted(-4, -30, 4, 4).contains(pt):
                return i
        return None

    # ---------------------------------------------------------- apri / chiudi
    def open(self):
        self.win.editor.commit()
        self.win.editor.clear_selection()  # niente tasti (Canc…) su oggetti che qui non si vedono selezionati
        self._fit_size()
        self.fit()
        self.show()
        self.raise_()
        self.win.plate_bar.raise_()
        self.setFocus()
        self._timer.start()
        self.win.plate_bar.overview_changed(True)

    def close_view(self):
        if not self.isVisible():
            return
        self._timer.stop()
        self.hide()
        self._pix.clear()  # le immagini dei piani servono solo mentre è aperta: memoria liberata
        self.win.canvas.setFocus()
        self.win.plate_bar.overview_changed(False)

    def _fit_size(self):
        vp = self.win.canvas.viewport()
        if self.size() != vp.size():
            self.setGeometry(vp.rect())
            if self.isVisible():
                self.fit()

    def _tick(self):
        bar = self.win.plate_bar
        st = (bar._job_index(), round(bar._progress()))
        if st != self._job_state or self.win.ctl.job_active or self.win.ctl.checking:
            self._job_state = st
            self.update()

    def _lay_key(self):
        cv = self.win.canvas
        return (len(self.win.editor.doc.plates), id(self.win.editor.doc), cv.bed_x, cv.bed_y)

    # ---------------------------------------------------------- mouse e tasti
    def wheelEvent(self, e):
        f = 1.15 ** (e.angleDelta().y() / 120)
        k = max(0.02, min(self._k * f, 60.0))
        p = e.position()
        self._off = p - (p - self._off) * (k / self._k)
        self._k = k
        self.update()

    def mousePressEvent(self, e):
        self._drag = (e.position(), QPointF(self._off), False)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons():
            p0, off0, _ = self._drag
            d = e.position() - p0
            if abs(d.x()) + abs(d.y()) > 4:
                self._drag = (p0, off0, True)
                self._off = off0 + d
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
            return
        h = self.plate_at(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.PointingHandCursor if h is not None else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        moved = self._drag is not None and self._drag[2]
        self._drag = None
        self.setCursor(Qt.PointingHandCursor if self._hover is not None else Qt.ArrowCursor)
        if moved or e.button() != Qt.LeftButton:
            return
        i = self.plate_at(e.position())
        if i is not None:
            self._open_plate(i)

    def _open_plate(self, i):
        from PySide6.QtWidgets import QApplication

        self.win.editor.set_plate(i)
        self.close_view()
        _SwallowClicks(self.win.canvas.viewport(), QApplication.doubleClickInterval() + 50)

    def mouseDoubleClickEvent(self, e):
        i = self.plate_at(e.position())
        if i is None:
            self.fit()  # doppio clic sul vuoto: di nuovo tutti in vista
        elif self.isVisible():
            self._open_plate(i)

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride:
            from PySide6.QtGui import QKeySequence

            seq = QKeySequence(e.keyCombination()).toString(QKeySequence.PortableText)
            if seq not in OVERVIEW_KEYS and seq not in self._safe_keys():
                e.accept()  # il tasto resta qui (e non fa niente): niente Canc, Ctrl+V, Ctrl+Z… su ciò che non si vede
                return True
        return super().event(e)

    SAFE_ACTS = ("start", "pause", "stop", "frame", "verify", "preview", "save", "save_as", "open", "new", "quit",
                 "plate_overview", "plate_next", "plate_prev", "plate_new", "shortcuts", "help_mode")

    def _safe_keys(self):
        """Le scorciatoie vere dei comandi che restano attivi (Avvia, Pausa, Stop… come sono impostate)."""
        from PySide6.QtGui import QKeySequence

        acts = getattr(self.win, "acts", {})
        return {k.toString(QKeySequence.PortableText) for n in self.SAFE_ACTS if n in acts for k in acts[n].shortcuts()}

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_view()
        elif e.key() in (Qt.Key_0, Qt.Key_Home):
            self.fit()
        e.accept()  # gli altri tasti non arrivano alla tela che sta sotto

    # ---------------------------------------------------------- disegno
    BIG = 60000  # oltre questi punti si disegna senza smussatura (resta veloce anche con foto vettorializzate)

    def _plate_pixmap(self, plate, r):
        """Il piano con i suoi oggetti, disegnato una volta e poi riusato: spostando la vista o aggiornando
        l'avanzamento del lavoro non si ridisegnano tutti gli oggetti."""
        from PySide6.QtGui import QPainter, QPixmap

        from .canvas import BED_DARK, BED_LIGHT, cpen, layer_color

        cv = self.win.canvas
        doc = self.win.editor.doc
        dpr = self.devicePixelRatioF()
        w, h = max(1, round(r.width() * dpr)), max(1, round(r.height() * dpr))
        shapes = [s for s in plate.shapes if not s.hidden]
        key = (w, h, dpr, cv.light_bed, cv.bed_x, cv.bed_y, tuple((id(s), id(s.path())) for s in shapes),
               tuple(sorted((k, c.show, c.mode, c.output, c.negative, c.fill_grouping) for k, c in doc.layers.items())))
        ck, pix = self._pix.get(plate.uid, (None, None))
        if ck == key:
            return pix
        pal = BED_LIGHT if cv.light_bed else BED_DARK
        pix = QPixmap(w, h)
        pix.setDevicePixelRatio(dpr)
        pix.fill(QColor(pal["bed"]))
        q = QPainter(pix)
        q.setRenderHint(QPainter.Antialiasing, sum(s.path().elementCount() for s in shapes) <= self.BIG)
        k = r.width() / cv.bed_x
        tf = QTransform(k, 0, 0, -k, 0, r.height())
        q.setTransform(tf)
        from . import fill_preview

        # 0.18.1: zona riempita per livello intero, come il G-code (prima ogni forma da sola)
        entries = [(leaf, ltf.map(leaf.local_path())) for s in shapes for leaf, ltf in s.leaves()
                   if not isinstance(leaf, ImageShape)]
        q.setPen(Qt.NoPen)
        for idx, fpath in fill_preview.regions(entries, doc.layers):
            fcs = doc.layers.get(idx)
            fc = QColor(layer_color(idx))
            fc.setAlpha(70 if (fcs is None or fcs.output) else 30)
            q.setBrush(fc)
            q.drawPath(fpath)
        for s in shapes:
            for leaf, ltf in s.leaves():
                cs = doc.layers.get(leaf.layer)
                if leaf.hidden or (cs is not None and not cs.show):
                    continue
                col = layer_color(leaf.layer)
                if isinstance(leaf, ImageShape):
                    img = cv.image_preview(leaf, cs)
                    if img is not None:
                        q.save()
                        q.setTransform(QTransform(1, 0, 0, -1, 0, leaf.h) * ltf * tf)
                        q.setRenderHint(QPainter.SmoothPixmapTransform, True)
                        q.drawImage(QRectF(0, 0, leaf.w, leaf.h), img)
                        q.restore()
                    continue
                path = ltf.map(leaf.local_path())
                q.setBrush(Qt.NoBrush)
                q.setPen(cpen(col, 1.0, Qt.DashLine if leaf.layer >= 30 else Qt.SolidLine,
                              255 if (cs is None or cs.output) else 110))
                q.drawPath(path)
        q.end()
        self._pix[plate.uid] = (key, pix)
        return pix

    def paintEvent(self, _):
        from PySide6.QtGui import QFont, QPainter, QPen

        from .canvas import BED_DARK, BED_LIGHT, cpen

        win, cv = self.win, self.win.canvas
        doc = win.editor.doc
        if self._k is None or self._layout_key != self._lay_key():  # piani aggiunti o tolti, altro progetto
            self.fit()
        alive = {pl.uid for pl in doc.plates}
        for uid in [u for u in self._pix if u not in alive]:
            del self._pix[uid]
        pal = BED_LIGHT if cv.light_bed else BED_DARK
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(pal["out"]))
        job = win.plate_bar._job_index()
        head = cv.head_pos()
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, min(13.0, 11.0 * self._k * cv.bed_x / 300)))
        for i, plate in enumerate(doc.plates):
            r = self.plate_rect(i)
            if not r.intersects(QRectF(self.rect())):
                continue
            cur, hov = i == doc.current, i == self._hover
            p.drawPixmap(r.topLeft(), self._plate_pixmap(plate, r))
            edge = QColor(JOB_COLOR) if i == job else QColor("#2F7DF6") if cur else QColor(pal["edge"])
            p.setPen(cpen(edge, 2.2 if (cur or i == job or hov) else 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            # nome sopra il piano (come la linguetta)
            name = doc.plate_name(i)
            if i == job:
                name = tr("▶ {0} · {1:.0f}%", name, win.plate_bar._progress())
            f.setBold(cur)
            p.setFont(f)
            p.setPen(QColor(JOB_COLOR) if i == job else QColor("#1F2633" if cv.light_bed else "#EEF2F8"))
            p.drawText(QRectF(r.left(), r.top() - 28, r.width(), 26), Qt.AlignLeft | Qt.AlignBottom,
                       f"{i + 1}.  {name}   ·   " + tr("{0} oggetti", len(plate.shapes)))
            if i == job:  # dove sta passando il laser
                p.save()
                p.setClipRect(r.adjusted(-2, -2, 2, 2))
                p.setTransform(QTransform(self._k, 0, 0, -self._k, r.left(), r.bottom()))
                trail = getattr(cv, "_trail_path", None)
                if trail is not None and not trail.isEmpty():
                    p.setRenderHint(QPainter.Antialiasing, trail.elementCount() <= self.BIG)
                    p.setPen(cpen(JOB_COLOR, 1.6, Qt.SolidLine, 200))
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(QTransform.fromScale(1, -1).map(trail))
                if head is not None:
                    p.setRenderHint(QPainter.Antialiasing, True)
                    p.setPen(QPen(QColor(JOB_COLOR), 0))
                    p.setBrush(QColor(JOB_COLOR))
                    rr = 5 / self._k
                    p.drawEllipse(head, rr, rr)
                p.restore()
            if hov and not cur:
                p.fillRect(r, QColor(47, 125, 246, 18))
        # in basso: come si usa
        p.setPen(QColor("#5B6578" if cv.light_bed else "#AEB8CB"))
        f2 = QFont(self.font())
        f2.setPointSizeF(9)
        p.setFont(f2)
        a = self._area()
        p.drawText(QRectF(a.left(), a.bottom() + 4, a.width(), 20), Qt.AlignCenter,
                   tr("Vista d'insieme · clic su un piano per modificarlo · rotella zoom · trascina per spostare · "
                      "doppio clic sul vuoto: tutti in vista · Esc esce"))
        p.end()
