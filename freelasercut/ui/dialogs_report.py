# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto → Invia un rapporto all'assistenza (0.17.7).

La persona racconta cosa è successo; FreeLaserCut prepara il rapporto (.zip con le informazioni tecniche, niente
progetti né foto) e, solo dopo il consenso all'informativa privacy, lo manda al progetto oppure apre il programma di
posta con il messaggio già scritto. Si può sempre vedere prima cosa contiene e salvarlo come file."""
import os
import sys
import threading
import time
import zipfile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from .. import diag, support
from ..profile import config_dir
from freelasercut.i18n import tr  # noqa: E402


class _Done(QObject):
    done = Signal(bool, str)


def _grab_png(win):
    """Immagine della finestra principale (PNG), presa prima che si apra questa finestra."""
    try:
        pix = win.grab()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pix.save(buf, "PNG")
        return bytes(ba)
    except Exception:  # noqa: BLE001
        return None


class ReportDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle(tr("Invia un rapporto all'assistenza"))
        self.setMinimumWidth(620)
        self.code = diag.new_code()
        self.shot = _grab_png(win)
        self.zip_path = None
        self._sig = _Done()
        self._sig.done.connect(self._sent)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Racconta cosa è successo: il rapporto arriva al progetto FreeLaserCut con le informazioni "
                          "tecniche che servono per capire il problema e correggerlo. Più è preciso, più è facile."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.subject = QLineEdit()
        self.subject.setPlaceholderText(tr("in poche parole, per esempio «il laser si ferma a metà della foto»"))
        f.addRow(tr("Oggetto"), self.subject)
        self.doing = self._box(tr("per esempio: ho aperto la foto, Prepara foto, Schizzo, poi Avvia"))
        f.addRow(tr("Cosa stavi facendo"), self.doing)
        self.expected = self._box(tr("cosa doveva succedere"))
        f.addRow(tr("Cosa ti aspettavi"), self.expected)
        self.happened = self._box(tr("cosa è successo invece (messaggi, comportamento della macchina)"))
        f.addRow(tr("Cosa è successo"), self.happened)
        self.freq = QComboBox()
        for t in (tr("sempre"), tr("a volte"), tr("una volta sola"), tr("non so")):
            self.freq.addItem(t)
        f.addRow(tr("Succede"), self.freq)
        self.contact = QLineEdit()
        self.contact.setPlaceholderText(tr("facoltativa: solo se vuoi una risposta"))
        f.addRow(tr("La tua email"), self.contact)
        v.addLayout(f)
        self.with_shot = QCheckBox(tr("Aggiungi un'immagine della finestra di FreeLaserCut (si vede il disegno aperto)"))
        self.with_shot.setEnabled(self.shot is not None)
        v.addWidget(self.with_shot)
        self.with_photo = QCheckBox(tr("Aggiungi le impostazioni di Prepara foto della foto selezionata (senza la foto)"))
        self.with_photo.setChecked(True)
        v.addWidget(self.with_photo)
        priv = QLabel(tr(
            "<b>Privacy.</b> Il rapporto contiene: la tua descrizione, versione di FreeLaserCut e di Windows, profilo "
            "e impostazioni della macchina, registro della comunicazione con la scheda, porte USB, l'ultimo lavoro "
            "(impostazioni e righe di G-code, non il disegno) ed eventuali errori. Il nome della tua cartella utente "
            "viene tolto. Niente progetti né foto, salvo l'immagine della finestra se la scegli. Serve solo a "
            "trovare e correggere i problemi di FreeLaserCut (anche con strumenti di intelligenza artificiale), resta "
            "nell'account Google del progetto e si cancella dopo 12 mesi. Puoi chiederne la cancellazione con il "
            "codice <b>{0}</b>. <a href='{1}'>Informativa completa</a>", self.code, support.PRIVACY_URL))
        priv.setWordWrap(True)
        priv.setTextFormat(Qt.RichText)
        priv.setOpenExternalLinks(True)
        priv.setObjectName("muted")
        v.addWidget(priv)
        self.consent = QCheckBox(tr("Ho letto l'informativa e acconsento all'invio del rapporto"))
        self.consent.toggled.connect(self._update)
        v.addWidget(self.consent)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        b = QHBoxLayout()
        self.b_show = QPushButton(tr("Mostra il contenuto"))
        self.b_show.clicked.connect(self.show_content)
        self.b_save = QPushButton(tr("Salva il file…"))
        self.b_save.clicked.connect(self.save_file)
        self.b_mail = QPushButton(tr("Invia per email…"))
        self.b_mail.setToolTip(tr("Apre il tuo programma di posta con il messaggio per {0} già scritto; il file del "
                                  "rapporto lo trascini tu nella mail", support.SUPPORT_EMAIL))
        self.b_mail.clicked.connect(self.send_mail)
        self.b_send = QPushButton(tr("Invia"))
        self.b_send.setObjectName("primary")
        self.b_send.setToolTip(tr("Manda il rapporto al progetto FreeLaserCut via Internet, senza programmi di posta"))
        self.b_send.clicked.connect(self.send)
        self.b_send.setVisible(support.can_send())
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.reject)
        for w in (self.b_show, self.b_save):
            b.addWidget(w)
        b.addStretch(1)
        for w in (self.b_mail, self.b_send, close):
            b.addWidget(w)
        v.addLayout(b)
        self._update()

    @staticmethod
    def _box(placeholder):
        t = QPlainTextEdit()
        t.setPlaceholderText(placeholder)
        t.setFixedHeight(58)
        return t

    def _update(self, *_):
        on = self.consent.isChecked()
        self.b_send.setEnabled(on)
        self.b_mail.setEnabled(on)

    def user(self):
        return {"oggetto": self.subject.text().strip(), "facevi": self.doing.toPlainText().strip(),
                "aspettavi": self.expected.toPlainText().strip(), "successo": self.happened.toPlainText().strip(),
                "frequenza": self.freq.currentText()}

    # ---------------------------------------------------------------- il rapporto
    def build(self, path=None):
        if path is None:
            d = os.path.join(config_dir(), "rapporti")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{self.code}.zip")
        diag.make_report(path, self.win, getattr(self.win, "comm_log", None), user=self.user(),
                         screenshot=self.shot if self.with_shot.isChecked() else None, code=self.code,
                         photo=self.with_photo.isChecked())
        self.zip_path = path
        return path

    def summary(self):
        return diag.summary_text(self.user(), self.code, self.win)

    def show_content(self):
        path = self.build()
        parts = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.endswith(".png"):
                    parts.append(f"===== {n}\n" + tr("(immagine della finestra)"))
                else:
                    parts.append(f"===== {n}\n" + z.read(n).decode("utf-8", errors="replace"))
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Contenuto del rapporto {0}", self.code))
        lay = QVBoxLayout(dlg)
        t = QPlainTextEdit("\n\n".join(parts))
        t.setReadOnly(True)
        lay.addWidget(t)
        dlg.resize(820, 620)
        dlg.exec()

    def save_file(self):
        base = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva il rapporto"), os.path.join(base, f"{self.code}.zip"),
                                              tr("Archivio zip (*.zip)"))
        if not path:
            return None
        self.build(path)
        self.status.setText(tr("Rapporto salvato: {0}", path))
        return path

    def send_mail(self):
        """Programma di posta con il messaggio già scritto; la cartella con il rapporto si apre accanto."""
        base = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
        path = self.build(os.path.join(base, f"{self.code}.zip"))
        QDesktopServices.openUrl(QUrl(support.mailto(self.code, self.user(), self.summary())))
        if sys.platform == "win32":
            import subprocess

            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])  # noqa: S603,S607
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        self.status.setText(tr("Si è aperta la mail per {0}: trascina dentro il file {1} (è sul Desktop, la cartella "
                               "è aperta) e premi Invia.", support.SUPPORT_EMAIL, os.path.basename(path)))
        return path

    def send(self):
        if not self.consent.isChecked() or not support.can_send():
            return
        path = self.build()
        summary = self.summary()
        user, contact = self.user(), self.contact.text().strip()
        self.b_send.setEnabled(False)
        self.status.setText(tr("Invio in corso…"))

        def work():
            ok, info = support.send(path, self.code, user, contact, summary)
            self._sig.done.emit(ok, info)
        threading.Thread(target=work, daemon=True).start()

    def _sent(self, ok, info):
        self._update()
        if ok:
            self.status.setText(tr("<b>Rapporto inviato.</b> Codice {0}. Grazie!", info))
            self.result_code = info
            QMessageBox.information(self, tr("Rapporto inviato"),
                                    tr("Rapporto inviato, grazie!\nCodice: {0}\n\nSe hai scritto la tua email ti "
                                       "risponderemo lì.", info))
            self.accept()
        else:
            self.status.setText(tr("Invio non riuscito ({0}). Puoi usare «Invia per email…» o salvare il file.", info))
