# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aggiornamento dal programma, parte visibile: permesso al primo avvio, controllo una volta al giorno,
Aiuto → Cerca aggiornamenti…, finestra con le novità, scaricamento con avanzamento e installazione."""
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressDialog,
                               QTextBrowser, QVBoxLayout)

from .. import __version__, updater
from ..i18n import tr

MAX_NOTES = 20_000


class UpdateManager(QObject):
    checked = Signal(object, object, bool)  # Release|None, errore|None, chiesto a mano?
    progress = Signal(int, int)
    downloaded = Signal(object, object)  # percorso|None, errore|None

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.qs = win.qs
        self.mode = updater.mode()
        self.busy = False
        self.release = None
        self._cancel = False
        self._dlg = None
        self.checked.connect(self._on_checked)
        self.progress.connect(self._on_progress)
        self.downloaded.connect(self._on_downloaded)

    # ---------------------------------------------------------------- preferenze
    def enabled(self):
        return self.qs.value("update_check") in (True, "true")

    def set_enabled(self, on):
        self.qs.setValue("update_check", "true" if on else "false")
        a = self.win.acts.get("update_auto") if hasattr(self.win, "acts") else None
        if a is not None and a.isChecked() != bool(on):
            a.blockSignals(True)
            a.setChecked(bool(on))
            a.blockSignals(False)
        if on and self.due():
            self.check(manual=False)

    def due(self):
        try:
            last = float(self.qs.value("update_last", 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        return time.time() - last >= updater.CHECK_EVERY or last > time.time() + 60

    # ---------------------------------------------------------------- all'avvio
    def startup(self):
        """Pochi secondi dopo l'avvio: alla prima volta chiede il permesso, poi controlla al massimo una volta al giorno.
        Solo nella copia installata con l'installatore (lo Store e git si aggiornano da sé)."""
        if os.environ.get("FLC_NO_UPDATE") or QGuiApplication.platformName() in ("offscreen", "minimal"):
            return
        if self.mode != "installer":
            return
        if self.qs.value("update_check") is None:
            if QApplication.activeModalWidget() is not None or not self.win.isVisible():
                QTimer.singleShot(5000, self.startup)  # c'è già un'altra finestra aperta: chiedo dopo
                return
            self.ask_permission()
        if self.enabled() and self.due():
            self.check(manual=False)

    def ask_permission(self):
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("Aggiornamenti"))
        box.setTextFormat(Qt.RichText)
        box.setText(tr("<b>Vuoi che FreeLaserCut controlli da solo se c'è una versione nuova?</b><br><br>"
                       "Una volta al giorno, all'avvio, chiede a GitHub qual è l'ultima versione pubblicata. "
                       "Non invia nessun dato tuo e non scarica niente senza chiedertelo.<br><br>"
                       "Puoi cambiare idea quando vuoi da <i>Aiuto → Controlla gli aggiornamenti ogni giorno</i>; "
                       "<i>Aiuto → Cerca aggiornamenti…</i> funziona sempre."))
        yes = box.addButton(tr("Sì, controlla ogni giorno"), QMessageBox.YesRole)
        box.addButton(tr("No, grazie"), QMessageBox.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        self.set_enabled(box.clickedButton() is yes)

    # ---------------------------------------------------------------- controllo
    def check(self, manual=True):
        if self.mode == "store":  # la copia dello Store non si collega a GitHub: la aggiorna lo Store
            if manual:
                QMessageBox.information(self.win, tr("Aggiornamenti"), tr(
                    "Questa copia di FreeLaserCut viene dal Microsoft Store: l'aggiornamento arriva dallo Store."))
            return False
        if self.busy:
            return False
        self.busy = True
        if manual:
            self.win.statusBar().showMessage(tr("Cerco aggiornamenti su GitHub…"), 4000)
        updater.check_async(lambda rel, err: self.checked.emit(rel, err, manual))
        return True

    def _on_checked(self, rel, err, manual):
        self.busy = False
        if err:
            if manual:
                self._error(tr("Controllo degli aggiornamenti"), err)
            return
        self.qs.setValue("update_last", time.time())
        if rel is None or not updater.is_newer(rel.version):
            if manual:
                QMessageBox.information(self.win, tr("Aggiornamenti"),
                                        tr("Hai già l'ultima versione di FreeLaserCut ({0}).", __version__))
            return
        self.release = rel
        if manual:
            self.show_release(rel)
            return
        if str(self.qs.value("update_skip", "")) == rel.version:
            return
        w = self.win
        if w.banner.isVisible() and getattr(w, "_banner_kind", "") == "alarm":
            w.statusBar().showMessage(tr("È disponibile FreeLaserCut {0}: Aiuto → Cerca aggiornamenti…", rel.version), 15000)
            return
        w.show_banner(tr("È disponibile FreeLaserCut {0} (hai la {1}).", rel.version, __version__), "info",
                      [(tr("Novità e aggiornamento"), lambda: self.show_release(rel)),
                       (tr("Salta questa versione"), lambda: self.skip(rel)),
                       (tr("Più tardi"), w.banner.hide)])

    def skip(self, rel):
        self.qs.setValue("update_skip", rel.version)
        self.win.banner.hide()

    # ---------------------------------------------------------------- finestra delle novità
    def release_dialog(self, rel):
        d = QDialog(self.win)
        d.setWindowTitle(tr("Aggiornamento disponibile"))
        d.setMinimumSize(560, 420)
        v = QVBoxLayout(d)
        head = QLabel(tr("<b>È disponibile FreeLaserCut {0}</b> (hai la {1}).", rel.version, __version__))
        head.setTextFormat(Qt.RichText)
        v.addWidget(head)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes[:MAX_NOTES] or tr("Nessuna nota per questa versione."))
        v.addWidget(notes, 1)
        bb = QDialogButtonBox()
        d.choice = None
        if self.mode == "installer":
            info = QLabel(tr("FreeLaserCut scarica l'installatore da GitHub, ne controlla l'impronta SHA-256, si chiude "
                             "e si riapre da solo a installazione finita. Progetti, profili e materiali restano."))
            go = bb.addButton(tr("Scarica e installa"), QDialogButtonBox.AcceptRole)
            go.setDefault(True)
            go.clicked.connect(lambda: (setattr(d, "choice", "install"), d.accept()))
        elif self.mode == "store":
            info = QLabel(tr("Questa copia di FreeLaserCut viene dal Microsoft Store: l'aggiornamento arriva dallo Store."))
        else:
            info = QLabel(tr("Questa copia non è stata installata con l'installatore per Windows: scarica la nuova "
                             "versione dal sito (oppure aggiorna con git)."))
            site = bb.addButton(tr("Apri il sito"), QDialogButtonBox.ActionRole)
            site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updater.SITE)))
        info.setWordWrap(True)
        v.addWidget(info)
        page = bb.addButton(tr("Pagina della versione"), QDialogButtonBox.ActionRole)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.page)))
        bb.addButton(tr("Chiudi"), QDialogButtonBox.RejectRole).clicked.connect(d.reject)
        v.addWidget(bb)
        return d

    def show_release(self, rel):
        d = self.release_dialog(rel)
        d.exec()
        if d.choice == "install":
            self.win.banner.hide()
            self.install(rel)

    # ---------------------------------------------------------------- scaricamento e installazione
    def install(self, rel):
        ctl = self.win.ctl
        if ctl.job_active or ctl.checking:
            QMessageBox.information(self.win, tr("Aggiornamento"),
                                    tr("C'è un lavoro (o una verifica) in corso: aggiorna quando la macchina ha finito."))
            return False
        self._cancel = False
        dlg = QProgressDialog(tr("Scarico FreeLaserCut {0}…", rel.version), tr("Annulla"), 0, 0, self.win)
        dlg.setWindowTitle(tr("Aggiornamento"))
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(lambda: setattr(self, "_cancel", True))
        dlg.show()
        self._dlg = dlg

        def run():
            try:
                path = updater.download(rel, progress=lambda done, total: self.progress.emit(done // 1024, total // 1024),
                                        cancelled=lambda: self._cancel)
            except updater.UpdateError as exc:
                self.downloaded.emit(None, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                self.downloaded.emit(None, tr("Scaricamento non riuscito ({0}).", exc))
                return
            self.downloaded.emit(path, None)
        threading.Thread(target=run, daemon=True, name="flc-scarica-aggiornamento").start()
        return True

    def _on_progress(self, done_kb, total_kb):
        dlg = self._dlg  # setValue può far girare gli eventi: intanto lo scaricamento può finire
        if dlg is None:
            return
        if total_kb > 0:
            dlg.setLabelText(tr("Scarico FreeLaserCut {0}… {1:.1f} di {2:.1f} MB", self.release.version if self.release
                                      else "", done_kb / 1024, total_kb / 1024))
            dlg.setMaximum(total_kb)
            dlg.setValue(min(done_kb, total_kb))

    def _on_downloaded(self, path, err):
        if self._dlg is not None:
            self._dlg.close()
            self._dlg = None
        if err:
            if not self._cancel:
                self._error(tr("Aggiornamento"), err)
            return
        QTimer.singleShot(0, lambda: self.ready(path))  # fuori dal gestore dell'avanzamento

    def ready(self, path):
        ver = self.release.version if self.release else ""
        r = QMessageBox.question(self.win, tr("Aggiornamento pronto"), tr(
            "FreeLaserCut {0} è scaricato e controllato.\n\nPer installarlo FreeLaserCut si chiude (ti chiede di salvare "
            "se serve) e si riapre da solo a installazione finita, di solito in meno di un minuto.\n\nInstallo adesso?", ver))
        if r != QMessageBox.Yes:
            self.win.statusBar().showMessage(tr("Aggiornamento rimandato: l'installatore resta in {0}", path), 10000)
            return False
        self.win._update_installer = path
        self.win.close()
        if self.win.isVisible():  # chiusura annullata (lavoro non salvato, lavoro in corso…)
            self.win._update_installer = None
            return False
        return True

    def _error(self, title, msg):
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(msg)
        site = box.addButton(tr("Apri il sito"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is site:
            QDesktopServices.openUrl(QUrl(updater.SITE))


def run_installer_on_exit(win):
    """Chiamata da closeEvent dopo la chiusura accettata: avvia l'installatore scaricato (se c'è)."""
    path = getattr(win, "_update_installer", None)
    if not path:
        return False
    win._update_installer = None
    try:
        updater.launch_installer(path, updater.install_dir())
    except OSError:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))  # almeno la cartella con l'installatore
        return False
    return True
