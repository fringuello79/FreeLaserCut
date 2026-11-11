# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""MakerHub in FreeLaserCut (0.18.10, per ora fra le funzioni in prova): il menu, la finestra «Collega MakerHub»,
l'ascolto in secondo piano e l'arrivo di un disegno sul piano di lavoro.

La rete e i controlli sui lavori sono in ../makerhub.py. Qui valgono tre regole:
- niente di tutto questo esiste finché le funzioni in prova non sono sbloccate;
- l'ascolto parte solo se l'utente ha collegato MakerHub, e si vede (voce del menu, finestra, barra di stato);
- un disegno arriva sul piano solo dopo la conferma, e il laser non parte mai da qui.
"""
import json
import os
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QTransform
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .. import admin
from .. import makerhub as mh
from ..core import ops
from ..i18n import tr
from . import bg
from .style import ASSETS

NAME = "MakerHub"  # il nome è loro: non si traduce
_LOGO = os.path.join(ASSETS, "makerhub.png")


def logo_icon():
    return QIcon(_LOGO)


def open_url(url):
    """Apre nel browser un indirizzo di MakerHub (solo https e solo maker-hub.it). -> True se l'ha aperto."""
    url = mh.safe_url(url)
    if not url:
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))


# ============================================================================ ascolto
class Listener(QObject):
    """Chiede a MakerHub se c'è un disegno, in un filo secondario. I lavori arrivano uno alla volta con il segnale
    `job`: il filo aspetta la risposta della finestra (answer) e poi manda l'esito a MakerHub."""

    MIN_CYCLE = 2.0  # secondi fra due richieste a vuoto: se MakerHub rispondesse subito, non lo si tempesta

    job = Signal(dict)
    status = Signal(str, str)  # "wait" | "on" | "error" | "expired", testo per l'utente
    refused = Signal(str, str)  # titolo, motivo: un lavoro scartato dai controlli

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        self._gen = 0
        self._wake = threading.Event()
        self._cond = threading.Condition()
        self._answers = {}
        self._done = {}  # lavori già trattati in questa sessione: se MakerHub li rimanda, non si chiede due volte

    def running(self):
        return self.bridge is not None

    def start(self, token):
        self.stop()
        self.bridge = mh.Bridge(token)
        self._gen += 1
        self._wake = threading.Event()
        self.status.emit("wait", tr("Mi collego a MakerHub…"))
        gen, bridge, wake = self._gen, self.bridge, self._wake
        bg.run(lambda: self._loop(gen, bridge, wake), self, name="makerhub")

    def stop(self):
        if self.bridge is None:
            return
        self._gen += 1
        self.bridge = None
        self._wake.set()
        with self._cond:
            self._cond.notify_all()

    def answer(self, job_id, ok, message, state):
        """Dal filo della finestra: com'è andata con il lavoro job_id."""
        with self._cond:
            self._answers[job_id] = (bool(ok), str(message), state)
            self._cond.notify_all()

    def _loop(self, gen, bridge, wake):
        pause = 2.0
        while gen == self._gen:
            t0 = time.monotonic()
            try:
                jobs = bridge.wait()
            except Exception as exc:  # noqa: BLE001 — la rete può fare di tutto: il filo non deve morire in silenzio
                if gen != self._gen:
                    return
                if getattr(exc, "code", None) == 401:
                    self.status.emit("expired", tr("MakerHub non riconosce più questo FreeLaserCut: collegalo di nuovo "
                                                   "con un codice nuovo"))
                    return
                self.status.emit("error", str(exc) if isinstance(exc, mh.BridgeError)
                                 else tr("MakerHub non è raggiungibile: {0}", mh.clean(exc, 120)))
                wake.wait(pause)
                pause = min(pause * 2, 60.0)
                continue
            if gen != self._gen:
                return
            pause = 2.0
            self.status.emit("on", tr("Collegato a MakerHub: i disegni che mandi dal sito arrivano qui"))
            for j in jobs:
                if j["problems"]:
                    ok, msg, state = False, tr("lavoro rifiutato: {0}", "; ".join(j["problems"])), mh.machine_state()
                    self.refused.emit(j["title"], "; ".join(j["problems"]))
                elif j["id"] in self._done:
                    ok, msg, state = self._done[j["id"]]
                else:
                    self.job.emit(j)
                    with self._cond:
                        self._cond.wait_for(lambda: j["id"] in self._answers or gen != self._gen)
                        if gen != self._gen:
                            return
                        ok, msg, state = self._answers.pop(j["id"])
                    self._done[j["id"]] = (ok, msg, state)
                try:
                    bridge.result(j["id"], ok, msg, state)
                except Exception:  # noqa: BLE001 — l'esito è una cortesia: se non parte, MakerHub rimanda il lavoro
                    pass
            if not jobs:
                wake.wait(max(0.0, self.MIN_CYCLE - (time.monotonic() - t0)))


# ============================================================================ il pezzo di finestra principale
class Hub(QObject):
    """Tutto MakerHub per la finestra principale: menu, ascolto, finestra, arrivo dei disegni."""

    changed = Signal()  # stato o elenco cambiati: la finestra «Collega MakerHub» si aggiorna
    _back = Signal(str, object)  # il risultato di un filo secondario, portato nel filo della finestra
    finished = Signal(str, bool, str)  # un'operazione in secondo piano è finita: "pair" | "tools", riuscita, messaggio

    def __init__(self, win, menubar):
        super().__init__(win)
        self.win = win
        self.qs = win.qs
        self.state, self.text = "off", ""
        self.dialog = None
        self.listener = Listener(self)
        self.listener.job.connect(self.receive)
        self.listener.status.connect(self._on_status)
        self.listener.refused.connect(self._on_refused)
        self._back.connect(self._on_back)
        self.menu = menubar.addMenu(NAME)
        self.refresh_menu()

    # ------------------------------------------------------------------ menu
    def tools(self):
        return mh.saved_tools(self.qs)

    def refresh_menu(self):
        m = self.menu
        m.clear()  # distrugge le voci dei generatori (sono sue); la voce «Collega» è della finestra e resta
        self.tool_actions = []
        for t in self.tools():
            a = m.addAction(logo_icon(), t["name"])
            a.setStatusTip(tr("{0} Si apre sul sito di MakerHub, nel browser.", t["description"]).strip())
            a.setToolTip(a.statusTip())
            a.triggered.connect(lambda _=False, url=t["url"]: self.open_tool(url))
            self.tool_actions.append(a)
        m.addSeparator()
        m.addAction(self.win.acts["makerhub"])
        self._show(admin.unlocked(self.qs))

    def _show(self, on):
        self.menu.menuAction().setVisible(on)
        for a in self.menu.actions():
            a.setVisible(on)
        self.win.acts["makerhub"].setVisible(on)

    def open_tool(self, url):
        if not admin.unlocked(self.qs):
            return False
        ok = open_url(url)
        if ok:
            self.win.statusBar().showMessage(tr("Ho aperto MakerHub nel browser"), 5000)
        return ok

    # ------------------------------------------------------------------ funzioni in prova: tutto o niente
    def apply_admin(self):
        on = admin.unlocked(self.qs)
        self._show(on)
        if on:
            token = self.token()
            if token and not self.listener.running():
                self.listener.start(token)
        else:
            self.listener.stop()
            self._set_state("off", "")
            if self.dialog is not None:
                self.dialog.close()
        self._label()

    # ------------------------------------------------------------------ collegamento
    def token(self):
        t = self.qs.value(mh.KEY_TOKEN)
        return t if isinstance(t, str) and t else None

    def paired(self):
        return self.token() is not None

    def pair(self, code):
        """Collega questo FreeLaserCut con il codice scritto dall'utente. Blocca (rete). -> (riuscito, messaggio)."""
        if not admin.unlocked(self.qs):
            return False, tr("MakerHub è ancora fra le funzioni in prova")
        return self._net_pair(code)

    @staticmethod
    def _net_pair(code):
        try:
            return True, mh.Bridge().pair(code)
        except mh.BridgeError as exc:
            return False, str(exc)

    def _paired(self, token):
        self.qs.setValue(mh.KEY_TOKEN, token)
        self.qs.sync()
        self.listener.start(token)
        self._label()
        self.changed.emit()

    def unpair(self):
        """Scollega: da qui in poi nessuna chiamata a MakerHub. (Sul loro sito l'utente può togliere il computer.)"""
        self.listener.stop()
        self.qs.remove(mh.KEY_TOKEN)
        self.qs.sync()
        self._set_state("off", "")
        self._label()

    @staticmethod
    def refresh_tools():
        """Rilegge l'elenco dei generatori da MakerHub. Blocca (rete). -> (riuscito, messaggio | elenco)."""
        try:
            tools = mh.Bridge().tools()
        except mh.BridgeError as exc:
            return False, str(exc)
        if not tools:
            return False, tr("MakerHub ha risposto con un elenco vuoto: tengo quello che c'era")
        return True, tools

    def start_async(self, what, *args):
        """pair / tools in un filo secondario; alla fine arriva il segnale finished(what, riuscito, messaggio)."""
        if not admin.unlocked(self.qs):
            return
        work = {"pair": self._net_pair, "tools": self.refresh_tools}[what]  # nel filo secondario solo la rete
        bg.run(lambda: self._back.emit(what, work(*args)), self, name="makerhub-" + what)

    def _on_back(self, what, result):
        ok, value = result
        msg = "" if ok else str(value)
        if ok and what == "pair":
            self._paired(value)
            msg = tr("Collegato a MakerHub")
        elif ok and what == "tools":
            self.qs.setValue(mh.KEY_TOOLS, json.dumps(value))
            self.refresh_menu()
            msg = tr("Elenco aggiornato: {0} strumenti", len(value))
            self.changed.emit()
        self.finished.emit(what, bool(ok), msg)

    # ------------------------------------------------------------------ stato
    def _set_state(self, state, text):
        if (state, text) == (self.state, self.text):
            return False
        self.state, self.text = state, text
        self.changed.emit()
        return True

    def _label(self):
        a = self.win.acts["makerhub"]
        a.setText(tr("MakerHub collegato (in prova)…") if self.listener.running() else tr("Collega MakerHub (in prova)…"))

    def _on_status(self, state, text):
        if not self.listener.running() and state != "expired":
            return  # un messaggio in ritardo di un ascolto già fermato
        was = self.state
        if state == "expired":
            self.listener.stop()
            self.qs.remove(mh.KEY_TOKEN)
            self.qs.sync()
            self._label()
        if self._set_state(state, text) and (state in ("error", "expired") or (state == "on" and was != "on")):
            self.win.statusBar().showMessage(f"{NAME}: {text}", 8000)

    def _on_refused(self, title, why):
        self.win.statusBar().showMessage(tr("MakerHub ha mandato «{0}», ma non l'ho aperto: {1}", title or "?", why), 15000)

    # ------------------------------------------------------------------ arriva un disegno
    def state_for_makerhub(self):
        send = self.qs.value(mh.KEY_MACHINE) in (True, "true")
        return mh.machine_state(self.win.profile if send else None)

    def receive(self, job):
        """Un lavoro valido arrivato da MakerHub: conferma, poi sul piano di lavoro. Il laser non parte mai da qui.
        -> (riuscito, messaggio) che torna a MakerHub."""
        win, jid = self.win, job["id"]

        def done(ok, msg):
            self.listener.answer(jid, ok, msg, self.state_for_makerhub())
            return ok, msg

        if not admin.unlocked(self.qs):
            return done(False, tr("MakerHub non è attivo in questo FreeLaserCut"))
        doc = win.editor.doc
        try:
            plan = mh.plan_job(job["op"], doc)
        except ValueError as exc:
            QMessageBox.warning(win, NAME, tr("MakerHub ha mandato «{0}», ma {1}.", job["title"] or "?", exc))
            return done(False, str(exc))
        title = job["title"] or plan.title or tr("un disegno")
        w, h = plan.size
        lines = [tr("MakerHub ti ha mandato «{0}»: {1:g} × {2:g} mm.", title, round(w, 1), round(h, 1))]
        if plan.material:
            lines.append(tr("Materiale: {0}", plan.material) + (f", {plan.thickness:g} mm" if plan.thickness else ""))
        bed = (win.profile.bed_x, win.profile.bed_y)
        too_big = w > bed[0] + 0.01 or h > bed[1] + 0.01
        if too_big:
            lines.append(tr("È più grande del piano di lavoro ({0:g} × {1:g} mm): arriva lo stesso, con le sue misure.",
                            bed[0], bed[1]))
        lines.append(tr("Lo metto sul piano di lavoro? Il laser non parte: lo avvii tu, dopo aver controllato."))
        if win.isMinimized():
            win.showNormal()
        QApplication.alert(win)
        if QMessageBox.question(win, NAME, "\n\n".join(lines)) != QMessageBox.Yes:
            return done(False, tr("l'utente non l'ha voluto aprire"))
        b = ops.union_bounds(plan.shapes)
        ops.transform_all(plan.shapes, QTransform.fromTranslate(bed[0] / 2 - b.center().x(), bed[1] / 2 - b.center().y()))
        plan.apply_layers(doc)
        win.editor.add(plan.shapes, tr("Importa da MakerHub"))
        win.statusBar().showMessage(tr("«{0}» è sul piano di lavoro: controlla i livelli prima di avviare", title), 10000)
        if plan.notes:
            QMessageBox.information(win, NAME, "\n\n".join(plan.notes))
        return done(True, tr("aperto sul piano di lavoro") + (tr(" (più grande del piano)") if too_big else ""))

    # ------------------------------------------------------------------ finestra
    def open_dialog(self):
        if not admin.unlocked(self.qs):
            return None
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return self.dialog
        dlg = MakerHubDialog(self, self.win)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda *_: setattr(self, "dialog", None))
        self.dialog = dlg
        dlg.show()
        return dlg


class MakerHubDialog(QDialog):
    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setWindowTitle(NAME)
        self.setWindowIcon(logo_icon())
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        head = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(QPixmap(_LOGO).scaled(QSize(64, 64), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(pic, 0, Qt.AlignTop)
        intro = QLabel(tr("<b>MakerHub</b>, il laboratorio digitale del maker.<br>È un servizio esterno, di "
                          "maker-hub.it: i suoi strumenti si aprono nel browser, sul loro sito, e per usarli serve "
                          "un account lì."))
        intro.setWordWrap(True)
        head.addWidget(intro, 1)
        lay.addLayout(head)

        box = QGroupBox(tr("Strumenti di MakerHub"))
        v = QVBoxLayout(box)
        self.list = QListWidget()
        self.list.setIconSize(QSize(22, 22))
        self.list.setWordWrap(True)
        self.list.setResizeMode(QListWidget.Adjust)  # le righe vanno a capo sulla larghezza della finestra…
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # …quindi niente barra orizzontale
        self.list.setMaximumHeight(150)
        self.list.itemDoubleClicked.connect(lambda *_: self.open_selected())
        v.addWidget(self.list)
        row = QHBoxLayout()
        self.b_open = QPushButton(tr("Apri nel browser"))
        self.b_open.setObjectName("primary")
        self.b_open.clicked.connect(self.open_selected)
        self.b_site = QPushButton(tr("Sito di MakerHub"))
        self.b_site.clicked.connect(lambda: open_url(mh.SITE))
        self.b_refresh = QPushButton(tr("Aggiorna l'elenco"))
        self.b_refresh.setToolTip(tr("Chiede a MakerHub l'elenco aggiornato dei suoi strumenti"))
        self.b_refresh.clicked.connect(lambda: self._run("tools"))
        row.addWidget(self.b_open)
        row.addWidget(self.b_site)
        row.addStretch(1)
        row.addWidget(self.b_refresh)
        v.addLayout(row)
        lay.addWidget(box)

        box = QGroupBox(tr("Ricevi i disegni in FreeLaserCut"))
        v = QVBoxLayout(box)
        self.how = QLabel()
        self.how.setWordWrap(True)
        v.addWidget(self.how)
        row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText(tr("Codice di 6 caratteri"))
        self.code.setMaxLength(16)
        self.code.returnPressed.connect(self.pair)
        self.b_pair = QPushButton(tr("Collega"))
        self.b_pair.setObjectName("primary")
        self.b_pair.clicked.connect(self.pair)
        self.b_unpair = QPushButton(tr("Scollega"))
        self.b_unpair.clicked.connect(self.unpair)
        row.addWidget(self.code, 1)
        row.addWidget(self.b_pair)
        row.addWidget(self.b_unpair)
        v.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.machine = QCheckBox(tr("Di' a MakerHub che macchina uso (modello e area di lavoro)"))
        self.machine.setToolTip(tr("Serve a MakerHub per proporre i parametri giusti. Spento: non viene mandato."))
        self.machine.setChecked(hub.qs.value(mh.KEY_MACHINE) in (True, "true"))
        self.machine.toggled.connect(lambda on: hub.qs.setValue(mh.KEY_MACHINE, bool(on)))
        v.addWidget(self.machine)
        lay.addWidget(box)

        note = QLabel(tr("FreeLaserCut contatta MakerHub solo se lo colleghi tu o se chiedi l'elenco aggiornato. "
                         "Manda la sua versione e l'esito di ogni disegno ricevuto; non manda il nome del computer "
                         "né quello del progetto. Come ogni sito, MakerHub vede l'indirizzo di rete da cui ti colleghi."))
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.close)
        row.addWidget(b_close)
        lay.addLayout(row)

        hub.changed.connect(self.refresh)
        hub.finished.connect(self._finished)
        self._busy = None
        self._note = ""
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        hub = self.hub
        keep = self.list.currentRow()
        self.list.clear()
        for t in hub.tools():
            it = QListWidgetItem(logo_icon(), t["name"] + (" — " + t["description"] if t["description"] else ""))
            it.setData(Qt.UserRole, t["url"])
            self.list.addItem(it)
        self.list.setCurrentRow(keep if 0 <= keep < self.list.count() else 0)
        paired = hub.paired()
        self.how.setText(tr("Collegato. Sul sito di MakerHub prepara il disegno e premi «Manda a FreeLaserCut»: "
                            "arriva qui, ti chiedo conferma e lo metto sul piano. Il laser non parte mai da solo.")
                         if paired else
                         tr("1. Su MakerHub apri «FreeLaserCut Live» e premi «Genera il codice».\n"
                            "2. Scrivi qui il codice (vale 10 minuti) e premi Collega. Si fa una volta sola."))
        self.code.setVisible(not paired)
        self.b_pair.setVisible(not paired)
        self.b_unpair.setVisible(paired)
        busy = self._busy is not None
        self.b_pair.setEnabled(not busy)
        self.b_refresh.setEnabled(not busy)
        self.code.setEnabled(not busy)
        text = {"pair": tr("Mi collego a MakerHub…"), "tools": tr("Chiedo l'elenco a MakerHub…")}.get(self._busy)
        self.status.setText(text or self._note or hub.text)
        self.status.setVisible(bool(self.status.text()))

    def open_selected(self):
        it = self.list.currentItem()
        return self.hub.open_tool(it.data(Qt.UserRole)) if it is not None else False

    def _run(self, what, *args):
        if self._busy is not None:
            return
        self._busy, self._note = what, ""
        self.refresh()
        self.hub.start_async(what, *args)

    def pair(self):
        code = mh.Bridge.normalize_code(self.code.text())
        if not code:
            self._note = tr("Scrivi il codice che vedi su MakerHub")
            return self.refresh()
        self._run("pair", code)

    def unpair(self):
        self.hub.unpair()
        self._note = tr("Scollegato: FreeLaserCut non contatta più MakerHub. Sul loro sito puoi togliere questo "
                        "computer dall'elenco.")
        self.refresh()

    def _finished(self, what, ok, msg):
        if self._busy == what:
            self._busy = None
        self._note = "" if (ok and what == "pair") else msg
        if ok and what == "pair":
            self.code.clear()
        self.refresh()
