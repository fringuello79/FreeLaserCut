# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.0: le due finestre della Galleria (File → «Condividi nella Galleria…» e «Galleria FreeLaserCut…»).

Tutto quello che parla con il servizio sta in freelasercut/galleria.py e gira in un filo a parte: la finestra non si
ferma mai ad aspettare la rete. I testi che arrivano dalla Galleria sono scritti da altri: qui si mostrano sempre
come testo semplice (mai come HTML) e le immagini si aprono solo se hanno una grandezza ragionevole.
"""
import html
import os
import struct
import tempfile

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QTabBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import galleria
from ..i18n import tr
from . import bg
from freelasercut import fontscale  # noqa: E402

MAX_LATO_IMMAGINE = 2400  # un'immagine arrivata dalla Galleria più grande di così non si apre


# ====================================================================== attrezzi
class _Compito(QObject):
    finito = Signal(object, object)  # (risultato, galleria.Errore oppure None)
    passo = Signal(object, object)


def avvia(finestra, lavoro, quando, passo=None):
    """lavoro(compito) gira in un filo a parte; quando(risultato, errore) arriva nel filo della finestra."""
    c = _Compito(finestra)
    c.finito.connect(quando)
    if passo is not None:
        c.passo.connect(passo)

    def filo():
        try:
            r, e = lavoro(c), None
        except galleria.Errore as exc:
            r, e = None, exc
        except Exception:  # noqa: BLE001  un errore qui non deve chiudere il programma
            r, e = None, galleria.Errore("interno")
        try:
            c.finito.emit(r, e)
        except RuntimeError:
            pass  # la finestra è stata chiusa nel frattempo

    bg.run(filo, finestra, c, name="flc-galleria")
    return c


def avviso(finestra, testo, titolo=None):
    """Un messaggio alla persona. Nelle prove automatiche resta in `finestra.ultimo_avviso` e non ferma niente."""
    finestra.ultimo_avviso = testo
    if not os.environ.get("FLC_NO_DIALOGS"):
        QMessageBox.information(finestra, titolo or tr("Galleria FreeLaserCut"), testo)


def chiedi(finestra, testo, titolo=None):
    if os.environ.get("FLC_NO_DIALOGS"):
        return getattr(finestra, "risposta_prova", True)
    return QMessageBox.question(finestra, titolo or tr("Galleria FreeLaserCut"), testo) == QMessageBox.Yes


def _semplice(lab, a_capo=True):
    lab.setTextFormat(Qt.PlainText)
    lab.setWordWrap(a_capo)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def immagine_sicura(dati, formato):
    """QImage da byte arrivati dalla Galleria, oppure None: controlla tipo e grandezza PRIMA di decodificare."""
    try:
        if formato == "PNG":
            if dati[:8] != b"\x89PNG\r\n\x1a\n" or dati[12:16] != b"IHDR":
                return None
            w, h = struct.unpack(">II", dati[16:24])
            if not (0 < w <= MAX_LATO_IMMAGINE and 0 < h <= MAX_LATO_IMMAGINE):
                return None
        elif dati[:3] != b"\xff\xd8\xff":
            return None
        img = QImage.fromData(bytes(dati), formato)
    except Exception:  # noqa: BLE001
        return None
    if img.isNull() or img.width() > MAX_LATO_IMMAGINE or img.height() > MAX_LATO_IMMAGINE:
        return None
    return img


def _durata(s):
    s = int(s or 0)
    if s <= 0:
        return ""
    h, m = divmod((s + 30) // 60, 60)
    return tr("{0} h {1} min", h, m) if h else tr("{0} min", max(1, m))


def _stelle(d):
    if not d.get("stelle_n"):
        return tr("senza voti")
    return "★ {0:.1f} ({1})".format(d.get("stelle_media") or 0.0, d["stelle_n"])


def tipo_del_progetto(doc):
    """Taglio, incisione o tutti e due, indovinato dai livelli usati (la persona lo può cambiare)."""
    modi = {cs.mode for cs in doc.used_layers() if cs.output}
    pieni = modi & {"fill", "offset_fill", "image"}
    if pieni and "line" in modi:
        return "entrambi"
    return "incisione" if pieni else "taglio"


def laser_del_profilo(profile):
    """(modello, watt) da proporre nel modulo: il modello solo se è una voce del catalogo (un nome dato dalla
    persona al suo laser non parte mai da solo), i watt dal primo numero della potenza ottica."""
    import re

    from .. import machines

    nomi = [n for n in machines.catalog_names() if n != machines.GENERIC]
    modello = profile.model if profile.model in nomi else ""
    if not modello:  # 0.22.0: profilo rinominato («Longer B1 40W garage»): si propone solo la voce del catalogo
        testo = f"{profile.model} {profile.name}".lower()
        dentro = [n for n in nomi if n.lower() in testo]
        modello = max(dentro, key=len) if dentro else ""
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(getattr(profile, "optical_power", "") or ""))
    try:
        watt = float(m.group(1).replace(",", ".")) if m else 0.0
    except ValueError:
        watt = 0.0
    return modello, (watt if 0 < watt <= 500 else 0.0)


def tempo_stimato(win):
    """Secondi del lavoro com'è adesso, oppure None (niente domande e niente finestre: se non si può, pazienza)."""
    try:
        from ..core import gcode
        from .main_window import BIG_PHOTO_DOTS

        if win._photo_dots() > BIG_PHOTO_DOTS:
            return None
        job = gcode.generate(win.editor.doc, win.profile, win.job_options())
        return int(job.seconds) if job.seconds and job.seconds > 0 else None
    except Exception:  # noqa: BLE001
        return None


# ====================================================================== condividi
class ShareDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win, self.doc = win, win.editor.doc
        self.setWindowTitle(tr("Condividi nella Galleria"))
        self.setMinimumWidth(760)
        self.ultimo_avviso, self.esito, self.in_corso, self.foto_scelte = "", None, False, []
        self._chiusa = False
        riga = QHBoxLayout(self)

        # --- a sinistra: anteprima e foto
        sx = QVBoxLayout()
        self.vista = QLabel()
        self.vista.setFixedSize(300, 300)
        self.vista.setAlignment(Qt.AlignCenter)
        self.vista.setStyleSheet("background:#FFFFFF; border:1px solid #8892A6;")
        sx.addWidget(self.vista)
        self.misure = QLabel()
        self.misure.setObjectName("muted")
        sx.addWidget(self.misure)
        self.b_foto = QPushButton(tr("Aggiungi una foto del pezzo finito…"))
        self.b_foto.clicked.connect(self.scegli_foto)
        sx.addWidget(self.b_foto)
        self.l_foto = QLabel()
        self.l_foto.setObjectName("muted")
        _semplice(self.l_foto)
        sx.addWidget(self.l_foto)
        self.b_via_foto = QPushButton(tr("Togli le foto"))
        self.b_via_foto.clicked.connect(lambda: self.metti_foto([]))
        sx.addWidget(self.b_via_foto)
        sx.addStretch(1)
        riga.addLayout(sx)

        # --- a destra: il modulo
        dx = QVBoxLayout()
        f = QFormLayout()
        self.titolo = QLineEdit()
        self.titolo.setMaxLength(80)
        nome = str(self.doc.name or "").strip()
        if nome and nome != tr("Senza titolo"):
            self.titolo.setText(os.path.splitext(os.path.basename(nome))[0][:80])
        f.addRow(tr("Titolo"), self.titolo)
        self.categoria = QComboBox()
        for k, v in galleria.nomi_categorie().items():
            self.categoria.addItem(v, k)
        self.categoria.setCurrentIndex(self.categoria.findData("altro"))
        f.addRow(tr("Categoria"), self.categoria)
        self.materiale = QLineEdit()
        self.materiale.setMaxLength(60)
        self.materiale.setPlaceholderText(tr("per esempio: Compensato di betulla"))
        f.addRow(tr("Materiale"), self.materiale)
        self.spessore = QDoubleSpinBox()
        self.spessore.setRange(0, 100)
        self.spessore.setDecimals(1)
        self.spessore.setSuffix(" mm")
        self.spessore.setSpecialValueText(tr("non indicato"))
        f.addRow(tr("Spessore"), self.spessore)
        self.tipo = QComboBox()
        for k, v in galleria.nomi_tipi().items():
            self.tipo.addItem(v, k)
        self.tipo.setCurrentIndex(self.tipo.findData(tipo_del_progetto(self.doc)))
        f.addRow(tr("Lavorazione"), self.tipo)
        modello, watt = laser_del_profilo(win.profile)
        self.laser = QLineEdit(modello)
        self.laser.setMaxLength(80)
        f.addRow(tr("Laser"), self.laser)
        self.potenza = QDoubleSpinBox()
        self.potenza.setRange(0, 500)
        self.potenza.setDecimals(1)
        self.potenza.setSuffix(" W")
        self.potenza.setSpecialValueText(tr("non indicato"))
        self.potenza.setValue(watt)
        f.addRow(tr("Potenza del laser"), self.potenza)
        self.descrizione = QPlainTextEdit()
        self.descrizione.setFixedHeight(70)
        self.descrizione.setPlaceholderText(tr("Due righe: che cos'è, consigli per farlo bene"))
        f.addRow(tr("Descrizione"), self.descrizione)
        self.licenza = QComboBox()
        for k, v in galleria.nomi_licenze().items():
            self.licenza.addItem(v, k)
        f.addRow(tr("Licenza"), self.licenza)
        self.autore = QLineEdit(str(win.qs.value(galleria.KEY_NOME) or ""))
        self.autore.setMaxLength(40)
        self.autore.setPlaceholderText(tr("facoltativo: il nome che si vedrà nella Galleria"))
        f.addRow(tr("Nome pubblico"), self.autore)
        dx.addLayout(f)
        self.c_mia = QCheckBox(tr("È opera mia, oppure ho il diritto di condividerla"))
        dx.addWidget(self.c_mia)
        r = QHBoxLayout()
        self.c_regole = QCheckBox(tr("Ho letto e accetto le regole della Galleria"))
        r.addWidget(self.c_regole)
        b = QPushButton(tr("Leggi le regole"))
        b.clicked.connect(self.mostra_regole)
        r.addWidget(b)
        r.addStretch(1)
        dx.addLayout(r)
        nota = QLabel(tr("Parte solo quello che vedi qui: il progetto ripulito, l'anteprima, le foto che scegli e questi "
                         "dati. Mai percorsi, nomi dei file, nome del computer o della porta."))
        nota.setObjectName("muted")
        nota.setWordWrap(True)
        dx.addWidget(nota)
        self.barra = QProgressBar()
        self.barra.setVisible(False)
        dx.addWidget(self.barra)
        self.stato = QLabel()
        _semplice(self.stato)
        dx.addWidget(self.stato)
        r = QHBoxLayout()
        r.addStretch(1)
        self.b_annulla = QPushButton(tr("Annulla"))
        self.b_annulla.clicked.connect(self.reject)
        r.addWidget(self.b_annulla)
        self.b_ok = QPushButton(tr("Condividi"))
        self.b_ok.setObjectName("primary")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self.condividi)
        r.addWidget(self.b_ok)
        dx.addLayout(r)
        riga.addLayout(dx, 1)
        self.metti_foto([])
        self._anteprima()
        self.tempo = tempo_stimato(win)

    # ------------------------------------------------------------------
    def _anteprima(self):
        try:
            png, w, h = galleria.disegna_anteprima(self.doc, 600)
        except galleria.Errore:
            return
        img = immagine_sicura(png, "PNG")
        if img is not None:
            self.vista.setPixmap(QPixmap.fromImage(img).scaled(296, 296, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.misure.setText(tr("Misure del lavoro: {0:.0f} × {1:.0f} mm", w, h))

    def metti_foto(self, percorsi):
        self.foto_scelte = [p for p in percorsi if p][:galleria.MAX_FOTO_N]
        self.l_foto.setText("\n".join(os.path.basename(p) for p in self.foto_scelte)
                            or tr("Nessuna foto: si vedrà solo l'anteprima del disegno."))
        self.b_via_foto.setVisible(bool(self.foto_scelte))
        self.b_foto.setEnabled(len(self.foto_scelte) < galleria.MAX_FOTO_N)

    def scegli_foto(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Foto del pezzo finito"), self.win.qs.value("last_dir", os.path.expanduser("~")),
                                                tr("Immagini (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp)"))
        if paths:
            self.metti_foto(self.foto_scelte + list(paths))

    def mostra_regole(self):
        testo = "\n\n".join(f"{i}. {r}" for i, r in enumerate(galleria.regole(), 1))
        avviso(self, testo, tr("Regole della Galleria"))

    def scheda(self):
        return {"titolo": self.titolo.text(), "descrizione": self.descrizione.toPlainText(),
                "categoria": self.categoria.currentData(), "materiale": self.materiale.text(),
                "spessore_mm": self.spessore.value(), "laser_famiglia": self.laser.text(),
                "potenza_w": self.potenza.value(), "tipo": self.tipo.currentData(), "tempo_s": self.tempo,
                "licenza": self.licenza.currentData(), "autore_nome": self.autore.text(),
                "regole_accettate": self.c_regole.isChecked(), "opera_mia": self.c_mia.isChecked()}

    def _occupata(self, si):
        self.in_corso = si
        for w in (self.b_ok, self.b_foto, self.b_via_foto, self.titolo, self.categoria, self.materiale, self.spessore,
                  self.tipo, self.laser, self.potenza, self.descrizione, self.licenza, self.autore, self.c_mia, self.c_regole):
            w.setEnabled(not si)
        self.barra.setVisible(si)
        if not si:
            self.b_foto.setEnabled(len(self.foto_scelte) < galleria.MAX_FOTO_N)

    def condividi(self):
        """Controlla il modulo, prepara il pacchetto (qui, nel filo della finestra) e lo manda (in un filo a parte)."""
        if self.in_corso:
            return
        self.esito = None
        try:
            scheda = galleria.controlla_scheda(self.scheda())
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                pacchetto = galleria.prepara(self.doc, scheda["titolo"], self.foto_scelte)
            finally:
                QApplication.restoreOverrideCursor()
        except galleria.Errore as exc:
            self.esito = ("errore", exc.codice)
            self.stato.setText(str(exc))
            avviso(self, str(exc), tr("Condividi nella Galleria"))
            return
        self.win.qs.setValue(galleria.KEY_NOME, scheda["autore_nome"])
        self._occupata(True)
        self.stato.setText(tr("Invio alla Galleria…"))
        qs = self.win.qs
        inst = galleria.installazione(qs)  # creato qui, nel filo della finestra: il filo a parte non tocca le impostazioni

        class _Qs:  # il filo a parte legge solo questo valore
            def value(self, _k):
                return inst

            def setValue(self, *_a):
                pass

        avvia(self, lambda c: galleria.condividi(_Qs(), scheda, pacchetto, avanzamento=lambda i, n: c.passo.emit(i, n),
                                                  annulla=lambda: self._chiusa),
              self._finita, self._passo)

    def _passo(self, i, n):
        self.barra.setRange(0, int(n))
        self.barra.setValue(int(i))

    def _finita(self, r, errore):
        if self._chiusa:
            return
        self._occupata(False)
        if errore is not None:
            self.esito = ("errore", errore.codice)
            self.stato.setText(str(errore))
            avviso(self, str(errore), tr("Condividi nella Galleria"))
            return
        self.esito = (r["stato"], r["id"])
        testo = galleria.testo_stato(r["stato"], r.get("motivo"))
        self.stato.setText(testo)
        avviso(self, testo, tr("Condividi nella Galleria"))
        if r["stato"] != "rifiutato":
            self.accept()

    def done(self, r):
        self._chiusa = True
        super().done(r)


# ====================================================================== apertura di un lavoro scaricato
def apri_nel_programma(win, dati, scheda):
    """Apre come PROGETTO NUOVO (senza file) un lavoro scaricato e già controllato. -> True se aperto."""
    from ..core.document import Document

    fd, tmp = tempfile.mkstemp(prefix="flc-galleria-", suffix=".flcut")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(dati)
        doc = Document.load(tmp)
    except Exception:  # noqa: BLE001  file che il controllo ha lasciato passare ma che non si apre
        avviso(win, galleria.testo_errore("file"))
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if not doc.all_shapes():
        avviso(win, galleria.testo_errore("file"))
        return False
    doc.path = None
    doc.name = scheda.get("titolo") or tr("Senza titolo")
    win.editor.set_document(doc)
    win.editor.dirty = True
    win._update_title()
    win.canvas.fit_bed()
    di = html.escape(scheda.get("autore_nome") or tr("un altro utente"))
    laser = " ".join(x for x in (scheda.get("laser_famiglia") or "",
                                 "{0:g} W".format(scheda["potenza_w"]) if scheda.get("potenza_w") else "") if x)
    testo = tr("Lavoro della Galleria, di {0}: potenza e velocità sono quelle del suo laser{1}. "
               "Controllale sul tuo prima di incidere.", di, f" ({html.escape(laser)})" if laser else "")
    win.galleria_avviso = testo
    win.show_banner(testo, "warn", [(tr("Ho capito"), win.banner.hide)])
    return True


# ====================================================================== sfoglia
class GalleryDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle(tr("Galleria FreeLaserCut"))
        self.resize(1040, 680)
        self.ultimo_avviso, self.lavori, self.scelto, self.pagina, self.altre = "", {}, None, 0, False
        self.in_corso, self._giro, self._chiusa, self.aperto = 0, 0, False, None
        self._pix = {}
        v = QVBoxLayout(self)
        self.schede = QTabBar()
        self.schede.addTab(tr("Tutti i lavori"))
        self.schede.addTab(tr("I miei lavori"))
        # 0.22.0: alla prima prova «I miei lavori» non si vedeva: due pulsanti larghi, quello scelto pieno
        self.schede.setExpanding(True)
        self.schede.setDrawBase(False)
        self.schede.setCursor(Qt.PointingHandCursor)
        self.schede.setStyleSheet(fontscale.css(
            "QTabBar::tab { padding: 9px 18px; margin: 0 3px; font-size: 11pt; font-weight: 600; border-radius: 6px;"
            " border: 1px solid #5A6478; }"
            "QTabBar::tab:selected { background: #2F9E64; color: #FFFFFF; border-color: #2F9E64; }"
            "QTabBar::tab:!selected:hover { border-color: #2F9E64; }"))
        self.schede.currentChanged.connect(lambda *_: self.carica())
        v.addWidget(self.schede)
        r = QHBoxLayout()
        self.cerca = QLineEdit()
        self.cerca.setPlaceholderText(tr("Cerca nei titoli e nelle descrizioni"))
        self.cerca.setMaxLength(40)
        self.cerca.returnPressed.connect(self.carica)
        r.addWidget(self.cerca, 1)
        self.categoria = QComboBox()
        self.categoria.addItem(tr("Tutte le categorie"), "")
        for k, t in galleria.nomi_categorie().items():
            self.categoria.addItem(t, k)
        r.addWidget(self.categoria)
        self.tipo = QComboBox()
        self.tipo.addItem(tr("Taglio o incisione"), "")
        for k, t in galleria.nomi_tipi().items():
            self.tipo.addItem(t, k)
        r.addWidget(self.tipo)
        self.ordine = QComboBox()
        for k, t in galleria.nomi_ordini().items():
            self.ordine.addItem(t, k)
        r.addWidget(self.ordine)
        for c in (self.categoria, self.tipo, self.ordine):
            c.currentIndexChanged.connect(lambda *_: self.carica())
        self.b_aggiorna = QPushButton(tr("Aggiorna"))
        self.b_aggiorna.clicked.connect(lambda: self.carica())
        r.addWidget(self.b_aggiorna)
        self.filtri = (self.cerca, self.categoria, self.tipo, self.ordine)
        v.addLayout(r)

        centro = QHBoxLayout()
        self.lista = QListWidget()
        self.lista.setViewMode(QListWidget.IconMode)
        self.lista.setIconSize(QSize(170, 170))
        self.lista.setGridSize(QSize(196, 232))
        self.lista.setResizeMode(QListWidget.Adjust)
        self.lista.setMovement(QListWidget.Static)
        self.lista.setWordWrap(True)
        self.lista.setTextElideMode(Qt.ElideRight)
        self.lista.currentItemChanged.connect(lambda cur, _old: self.mostra(cur.data(Qt.UserRole) if cur else None))
        self.lista.itemDoubleClicked.connect(lambda *_: self.apri())
        centro.addWidget(self.lista, 1)

        pan = QWidget()
        pan.setFixedWidth(360)
        d = QVBoxLayout(pan)
        self.grande = QLabel()
        self.grande.setFixedSize(340, 300)
        self.grande.setAlignment(Qt.AlignCenter)
        self.grande.setStyleSheet("background:#FFFFFF; border:1px solid #8892A6;")
        d.addWidget(self.grande)
        self.t_titolo = _semplice(QLabel())
        self.t_titolo.setStyleSheet(fontscale.css("font-size: 12pt; font-weight: 600;"))
        d.addWidget(self.t_titolo)
        self.t_dati = _semplice(QLabel())
        d.addWidget(self.t_dati)
        self.t_descr = _semplice(QLabel())
        scorri = QScrollArea()
        scorri.setWidgetResizable(True)
        scorri.setWidget(self.t_descr)
        self.t_descr.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        d.addWidget(scorri, 1)
        r = QHBoxLayout()
        r.addWidget(QLabel(tr("Il tuo voto:")))
        self.b_stelle = []
        for n in range(1, 6):
            b = QToolButton()
            b.setText("★")
            b.setToolTip(tr("{0} stelle", n))
            b.clicked.connect(lambda _c=False, k=n: self.vota(k))
            r.addWidget(b)
            self.b_stelle.append(b)
        r.addStretch(1)
        d.addLayout(r)
        r = QHBoxLayout()
        self.b_fatto = QPushButton(tr("L'ho fatto anch'io"))
        self.b_fatto.clicked.connect(self.ho_fatto)
        r.addWidget(self.b_fatto)
        self.b_segnala = QPushButton(tr("Segnala…"))
        m = QMenu(self.b_segnala)
        for k, t in galleria.nomi_motivi().items():
            m.addAction(t, lambda kk=k: self.segnala(kk))
        self.b_segnala.setMenu(m)
        r.addWidget(self.b_segnala)
        d.addLayout(r)
        self.b_togli = QPushButton(tr("Togli dalla Galleria"))
        self.b_togli.clicked.connect(self.togli)
        d.addWidget(self.b_togli)
        self.b_apri = QPushButton(tr("Apri come progetto nuovo"))
        self.b_apri.setObjectName("primary")
        self.b_apri.clicked.connect(self.apri)
        d.addWidget(self.b_apri)
        centro.addWidget(pan)
        v.addLayout(centro, 1)

        r = QHBoxLayout()
        self.stato = _semplice(QLabel(), a_capo=False)
        r.addWidget(self.stato, 1)
        self.b_altri = QPushButton(tr("Altri lavori"))
        self.b_altri.clicked.connect(lambda: self.carica(self.pagina + 1))
        r.addWidget(self.b_altri)
        b = QPushButton(tr("Chiudi"))
        b.clicked.connect(self.reject)
        r.addWidget(b)
        v.addLayout(r)
        self.mostra(None)
        self.carica()

    # ------------------------------------------------------------------ elenco
    def miei(self):
        return self.schede.currentIndex() == 1

    def carica(self, pagina=0):
        self._giro += 1
        giro, miei = self._giro, self.miei()
        for w in self.filtri:
            w.setEnabled(not miei)
        if pagina == 0:
            self.lista.clear()
            self.lavori = {}
            self.mostra(None)
        self.b_altri.setVisible(False)
        self.stato.setText(tr("Carico la Galleria…"))
        self.in_corso += 1
        if miei:
            salvati = galleria.miei()

            def lavoro(_c):
                out = []
                for m in salvati:
                    try:
                        out.append(galleria.lavoro(m["id"], chiave=m["chiave"]))
                    except galleria.Errore as exc:
                        if exc.codice != "non_trovato":
                            raise
                        out.append({"id": m["id"], "titolo": m.get("titolo") or "", "stato": "tolto"})
                return {"lavori": out, "altre": False, "pagina": 0}
        else:
            q = dict(ordine=self.ordine.currentData(), categoria=self.categoria.currentData(),
                     tipo=self.tipo.currentData(), cerca=self.cerca.text().strip(), pagina=pagina)

            def lavoro(_c):
                return galleria.elenco(**q)
        avvia(self, lavoro, lambda r, e: self._elenco(giro, r, e))

    def _elenco(self, giro, r, errore):
        self.in_corso -= 1
        if self._chiusa or giro != self._giro:
            return
        if errore is not None:
            self.stato.setText(str(errore))
            return
        self.pagina, self.altre = r["pagina"], r["altre"]
        da_caricare = []
        for d in r["lavori"]:
            if d.get("stato") == "tolto":
                galleria.dimentica_mio(d["id"])  # non c'è più: sparisce anche da «I miei lavori»
                continue
            self.lavori[d["id"]] = d
            it = QListWidgetItem(self._riga(d))
            it.setData(Qt.UserRole, d["id"])
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lista.addItem(it)
            if d["id"] in self._pix:
                it.setIcon(QIcon(self._pix[d["id"]]))
            elif d.get("stato") in ("", "pubblico") or (self.miei() and d.get("stato") in ("attesa", "nascosto")):
                da_caricare.append(d["id"])
        self.b_altri.setVisible(self.altre)
        n = self.lista.count()
        self.stato.setText(tr("{0} lavori", n) if n else (tr("Non hai ancora condiviso lavori da questo computer.") if self.miei()
                                                          else tr("Nessun lavoro trovato.")))
        if da_caricare:
            self.in_corso += 1

            def lavoro(c):
                for ident in da_caricare:
                    if self._chiusa or giro != self._giro:
                        break
                    try:  # i miei lavori non ancora pubblici: con la mia chiave (0.22.0)
                        c.passo.emit(ident, galleria.anteprima(ident, galleria.chiave_di(ident) if self.miei() else None))
                    except galleria.Errore:
                        continue
                return True

            def fine(_r, _e):
                self.in_corso -= 1
            avvia(self, lavoro, fine, self._miniatura)

    def _riga(self, d):
        stato = {"attesa": tr("in attesa del controllo"), "nascosto": tr("nascosto"), "rifiutato": tr("non accettato"),
                 "caricamento": tr("invio non finito")}.get(d.get("stato") or "")
        if stato:
            return f"{d['titolo']}\n{stato}"
        sotto = _stelle(d) + (" · " + tr("fatto da {0}", d["fatti_n"]) if d.get("fatti_n") else "")
        return ("● " if d.get("nuovo") else "") + f"{d['titolo']}\n{sotto}"

    def _miniatura(self, ident, dati):
        if self._chiusa:
            return
        img = immagine_sicura(dati, "PNG")
        if img is None:
            return
        self._pix[ident] = QPixmap.fromImage(img)
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            if it.data(Qt.UserRole) == ident:
                it.setIcon(QIcon(self._pix[ident]))
        if self.scelto == ident:
            self.mostra(ident)

    def _aggiorna_riga(self, d):
        self.lavori[d["id"]] = {**self.lavori.get(d["id"], {}), **d}
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            if it.data(Qt.UserRole) == d["id"]:
                it.setText(self._riga(self.lavori[d["id"]]))
        if self.scelto == d["id"]:
            self.mostra(d["id"])

    # ------------------------------------------------------------------ scheda a destra
    def mostra(self, ident):
        self.scelto = ident if ident in self.lavori else None
        d = self.lavori.get(self.scelto)
        mio = bool(d) and galleria.chiave_di(d["id"]) is not None
        pubblico = bool(d) and d.get("stato") in ("", "pubblico")
        for b in self.b_stelle + [self.b_fatto, self.b_segnala]:
            b.setEnabled(pubblico and not mio)
        self.b_apri.setEnabled(pubblico)
        self.b_togli.setVisible(mio)
        if not d:
            self.grande.clear()
            self.t_titolo.setText(tr("Scegli un lavoro dall'elenco"))
            self.t_dati.setText("")
            self.t_descr.setText("")
            return
        pix = self._pix.get(d["id"])
        if pix is not None:
            self.grande.setPixmap(pix.scaled(336, 296, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.grande.clear()
        self.t_titolo.setText(d["titolo"])
        righe = []
        if d.get("autore_nome"):
            righe.append(tr("di {0}", d["autore_nome"]))
        righe.append(galleria.nomi_categorie().get(d.get("categoria"), "") + " · " + galleria.nomi_tipi().get(d.get("tipo"), ""))
        mat = d.get("materiale") or ""
        if d.get("spessore_mm"):
            mat += " {0:g} mm".format(d["spessore_mm"])
        if mat:
            righe.append(tr("Materiale: {0}", mat))
        laser = " ".join(x for x in (d.get("laser_famiglia") or "", "{0:g} W".format(d["potenza_w"]) if d.get("potenza_w") else "") if x)
        if laser:
            righe.append(tr("Laser dell'autore: {0}", laser))
        if d.get("larghezza_mm") and d.get("altezza_mm"):
            righe.append(tr("Misure: {0:.0f} × {1:.0f} mm", d["larghezza_mm"], d["altezza_mm"]))
        if _durata(d.get("tempo_s")):
            righe.append(tr("Tempo stimato dall'autore: {0}", _durata(d["tempo_s"])))
        righe.append(_stelle(d) + " · " + tr("fatto da {0}", d.get("fatti_n") or 0) + " · " + tr("scaricato {0} volte", d.get("scaricati_n") or 0))
        righe.append(tr("Licenza: {0}", galleria.nomi_licenze().get(d.get("licenza"), "").split(":")[0]))
        if d.get("stato") not in ("", "pubblico"):
            righe.append(self._riga(d).split("\n")[-1])
        self.t_dati.setText("\n".join(r for r in righe if r.strip(" ·")))
        self.t_descr.setText(d.get("descrizione") or "")

    # ------------------------------------------------------------------ azioni
    def _azione(self, lavoro, dopo):
        ident = self.scelto
        if not ident:
            return
        self.in_corso += 1

        def fine(r, errore):
            self.in_corso -= 1
            if self._chiusa:
                return
            if errore is not None:
                if errore.codice == "non_trovato":
                    self.carica()
                avviso(self, str(errore))
                return
            dopo(ident, r)
        avvia(self, lambda _c: lavoro(ident), fine)

    def _inst(self):
        inst = galleria.installazione(self.win.qs)

        class _Qs:
            def value(self, _k):
                return inst

            def setValue(self, *_a):
                pass
        return _Qs()

    def vota(self, stelle):
        qs = self._inst()
        self._azione(lambda i: galleria.voto(qs, i, stelle),
                     lambda _i, r: (self._aggiorna_riga(r), self.stato.setText(tr("Voto registrato: {0} stelle", stelle))))

    def ho_fatto(self):
        qs = self._inst()
        self._azione(lambda i: galleria.fatto(qs, i),
                     lambda _i, r: (self._aggiorna_riga(r), self.stato.setText(tr("Grazie: segnato come fatto."))))

    def segnala(self, motivo):
        qs = self._inst()
        self._azione(lambda i: galleria.segnala(qs, i, motivo),
                     lambda _i, _r: avviso(self, tr("Grazie: la segnalazione è arrivata.")))

    def togli(self):
        if not self.scelto or not chiedi(self, tr("Togliere questo lavoro dalla Galleria? Non si può annullare.")):
            return
        self._azione(lambda i: galleria.togli(i), lambda _i, _r: self.carica())

    def apri(self):
        d = self.lavori.get(self.scelto)
        if not d or d.get("stato") not in ("", "pubblico") or not self.win._confirm_discard():
            return
        self.stato.setText(tr("Scarico il lavoro…"))

        def dopo(_i, dati):
            if apri_nel_programma(self.win, dati, d):
                self.aperto = d["id"]
                self.accept()
        self._azione(lambda i: galleria.scarica(i), dopo)

    def done(self, r):
        self._chiusa = True
        super().done(r)
