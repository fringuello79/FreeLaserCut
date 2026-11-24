# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Studia la macchina (0.22.3, funzione in prova, sbloccabile con il codice amministratore).

Due schede, K40 (scheda M2 Nano) e Ruida, con le loro prove. Ogni prova si fa da sola, in qualsiasi ordine, anche solo
alcune: il risultato si scrive subito nel diario (studio-macchina/ nella cartella delle impostazioni) ed entra da solo
nel rapporto per l'assistenza. Le prove che muovono la testa chiedono prima il consenso. Il laser non si accende mai.
"""
import re
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import studio
from ..studio import lihuiyu, ruida
from freelasercut.i18n import tr  # noqa: E402


def prove_k40():
    """(codice, titolo, descrizione) delle prove della K40."""
    return [
        ("K0", tr("Trova la scheda"), tr("Guarda se la scheda è collegata e con quale driver. Non le manda niente.")),
        ("K1", tr("Stato della scheda"), tr("Chiede lo stato alla scheda per due secondi. La testa non si muove.")),
        ("K2", tr("Ritorno a casa"), tr("La testa va a casa, poi 10 cm a destra e di nuovo a casa, a laser spento, "
                                       "per vedere quando la scheda dice «pronta». Chiede il consenso.")),
        ("K3", tr("Velocità vera"), tr("Da casa, 50 e 100 mm verso destra e ritorno, a 10 e a 30 mm/s, a laser spento, "
                                      "col cronometro (circa un minuto). Chiede il consenso.")),
        ("K4", tr("Un solo lavoro"), tr("Le stesse corse a 30 mm/s, prima una per volta e poi tutte di fila in un solo "
                                       "lavoro, a laser spento (circa mezzo minuto). Dice se il piccolo giro a fine "
                                       "corsa c'è solo all'inizio e alla fine del lavoro. Chiede il consenso.")),
    ]


TUTTE_K40 = ("K0", "K1", "K2", "K3", "K4")


def prove_ruida():
    return [
        ("R1", tr("Saluto e chiave"), tr("Saluta la scheda con le tre chiavi conosciute e guarda quale risponde. "
                                         "La testa non si muove.")),
        ("R2", tr("Memoria della scheda"), tr("Legge modello della scheda, misure del piano, stato e posizione della "
                                              "testa. Solo lettura.")),
        ("R3", tr("Piccolo spostamento"), tr("La testa si sposta di 10 mm e torna, senza luce e a laser spento, "
                                             "leggendo la posizione. Chiede il consenso.")),
        ("R4", tr("Lettura estesa"), tr("Legge le zone di memoria con le impostazioni della macchina (circa un minuto). "
                                        "Solo lettura.")),
    ]


def consenso_testo(codice):
    prima = tr("Prima di continuare:\n•  chiudi il programma che è venuto con la macchina (e ogni altro programma "
               "del laser)\n•  spegni il laser dal pannello (interruttore del laser o chiave del tubo)\n•  togli gli "
               "oggetti dal piano e tieni a portata il pulsante di emergenza\n\n")
    return {
        "K2": prima + tr("La testa andrà nell'angolo dei finecorsa, poi 10 cm a destra e di nuovo nell'angolo, a "
                         "laser spento. Servono 10 cm liberi a destra di casa. Procedo?"),
        "K3": prima + tr("La testa andrà a casa e poi si sposterà verso destra di 50 e di 100 mm e tornerà, a 10 e a "
                         "30 mm/s, a laser spento. Servono 10 cm liberi a destra di casa. Procedo?"),
        "K4": prima + tr("La testa andrà a casa e poi si sposterà verso destra di 50 e di 100 mm e tornerà, a 30 mm/s, "
                         "a laser spento. Servono 10 cm liberi a destra di casa. Procedo?"),
        "K*": prima + tr("Farò una dopo l'altra tutte le prove della K40 (circa due minuti). La testa andrà a casa e "
                         "si sposterà verso destra fino a 10 cm e tornerà, a laser spento. Servono 10 cm liberi a "
                         "destra di casa. Puoi fermare tutto con «Ferma». Procedo?"),
        "R3": prima + tr("La testa si sposterà di 10 mm lungo X e tornerà dov'era, senza luce e a laser spento. "
                         "Procedo?"),
    }[codice]


ESITI_OK = ("ok", "fatto (senza «finito»)")


class _Ponte(QObject):
    riga = Signal(str)
    fine = Signal(str, str, str)  # codice, esito, eccezione


class StudioDialog(QDialog):
    def __init__(self, parent=None, qs=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Studia la macchina (in prova)"))
        self.qs = qs
        self.tester = studio.tester_id(qs)
        self.diari = {}
        self.chiave_ruida = None
        self._stop = threading.Event()
        self._thread = None
        self.k40_links = lihuiyu.collegamenti  # funzioni sostituibili nelle prove automatiche
        self.ruida_link = self._ruida_link
        self.k40_run = None
        self._ponte = _Ponte()
        self._ponte.riga.connect(self._log, Qt.QueuedConnection)
        self._ponte.fine.connect(self._finita, Qt.QueuedConnection)

        v = QVBoxLayout(self)
        self.banner = QLabel(tr(
            "Raccoglie dati veri dalla tua macchina, per insegnare a FreeLaserCut a usarla. <b>Il laser non si accende "
            "mai.</b> Fai le prove che vuoi, nell'ordine che vuoi: ogni risultato si salva subito. Alla fine premi "
            "«Invia un rapporto all'assistenza». Nel rapporto ci sono solo dati della macchina, niente disegni né "
            "nomi di file; l'indirizzo di rete è nascosto."))
        self.banner.setWordWrap(True)
        v.addWidget(self.banner)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self.rows = {}
        self.tabs.addTab(self._page_k40(), tr("K40 (scheda M2 Nano)"))
        self.tabs.addTab(self._page_ruida(), tr("Ruida"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        v.addWidget(self.log)
        h = QHBoxLayout()
        self.b_stop = QPushButton(tr("Ferma"))
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.ferma)
        self.b_report = QPushButton(tr("Invia un rapporto all'assistenza…"))
        self.b_report.clicked.connect(self._report)
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.close)
        h.addWidget(self.b_stop)
        h.addStretch(1)
        h.addWidget(self.b_report)
        h.addWidget(b_close)
        v.addLayout(h)
        self.resize(720, 640)

    # ------------------------------------------------------------ pagine
    def _rows(self, grid, prove):
        for i, (code, title, desc) in enumerate(prove):
            lab = QLabel(f"<b>{code} · {title}</b><br>{desc}")
            lab.setWordWrap(True)
            st = QLabel(tr("da fare"))
            b = QPushButton(tr("Fai la prova"))
            b.clicked.connect(lambda _=False, c=code: self.run(c))
            grid.addWidget(lab, i, 0)
            grid.addWidget(st, i, 1)
            grid.addWidget(b, i, 2)
            grid.setColumnStretch(0, 1)
            self.rows[code] = (st, b)

    def _page_k40(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.k40_board = QComboBox()
        self.k40_board.addItem(tr("Non so (provo come M2)"), "?")
        for b in lihuiyu.SCHEDE:
            self.k40_board.addItem(b, b)
        if self.qs is not None:
            i = self.k40_board.findData(self.qs.value("studio/k40_scheda", "?"))
            self.k40_board.setCurrentIndex(max(i, 0))
        f.addRow(tr("Modello della scheda:"), self.k40_board)
        self.k40_label = QLineEdit()
        self.k40_label.setMaxLength(40)
        self.k40_label.setPlaceholderText(tr("come è scritto sulla scheda, per esempio 6C6879-LASER-M2:9"))
        f.addRow(tr("Scritta sulla scheda:"), self.k40_label)
        v.addLayout(f)
        h = QHBoxLayout()
        self.b_tutte = QPushButton(tr("Fai tutte le prove della K40"))
        self.b_tutte.setToolTip(tr("K0, K1, K2, K3 e K4 una dopo l'altra, con un solo consenso (circa due minuti). "
                                   "Alla fine trovi nel registro qui sotto i risultati spiegati."))
        self.b_tutte.clicked.connect(lambda: self.run("K*"))
        h.addWidget(self.b_tutte)
        h.addStretch(1)
        v.addLayout(h)
        g = QGridLayout()
        self._rows(g, prove_k40())
        v.addLayout(g)
        v.addStretch(1)
        return w

    def _page_ruida(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.ruida_conn = QComboBox()
        self.ruida_conn.addItem(tr("Rete (cavo o Wi-Fi)"), "rete")
        self.ruida_conn.addItem(tr("USB"), "usb")
        f.addRow(tr("Collegamento:"), self.ruida_conn)
        self.ruida_ip = QLineEdit(str(self.qs.value("studio/ruida_ip", "") if self.qs is not None else ""))
        self.ruida_ip.setPlaceholderText(tr("indirizzo scritto sul pannello della macchina, per esempio 192.168.1.100"))
        f.addRow(tr("Indirizzo di rete:"), self.ruida_ip)
        self.ruida_model = QLineEdit()
        self.ruida_model.setMaxLength(40)
        self.ruida_model.setPlaceholderText(tr("modello scritto sul pannello, per esempio RDC6445G"))
        f.addRow(tr("Modello del pannello:"), self.ruida_model)
        self.ruida_conn.currentIndexChanged.connect(lambda *_: self.ruida_ip.setEnabled(self.ruida_conn.currentData() == "rete"))
        v.addLayout(f)
        g = QGridLayout()
        self._rows(g, prove_ruida())
        v.addLayout(g)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ collegamenti e diario
    def _ruida_link(self):
        if self.ruida_conn.currentData() == "usb":
            return ruida.Usb()
        ip = self.ruida_ip.text().strip()
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip) or any(int(p) > 255 for p in ip.split(".")):
            raise ValueError(tr("Scrivi l'indirizzo di rete della macchina (quattro numeri separati da punti)."))
        if self.qs is not None:
            self.qs.setValue("studio/ruida_ip", ip)
        return ruida.Rete(ip)

    def scheda_k40(self):
        b = self.k40_board.currentData()
        if self.qs is not None:
            self.qs.setValue("studio/k40_scheda", b)
        return "M2" if b == "?" else b

    def diario(self, macchina):
        d = self.diari.get(macchina)
        if d is None:
            extra = {}
            if macchina == "k40":
                extra = {"scheda_scelta": self.k40_board.currentData(),
                         "scritta": studio.pulisci_etichetta(self.k40_label.text())}
            else:
                extra = {"collegamento": self.ruida_conn.currentData(),
                         "rete": studio.maschera_ip(self.ruida_ip.text()) if self.ruida_conn.currentData() == "rete" else "",
                         "pannello": studio.pulisci_etichetta(self.ruida_model.text())}
            d = self.diari[macchina] = studio.Diario(macchina, self.tester, extra=extra)
        return d

    # ------------------------------------------------------------ prove
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def run(self, code, sync=False):
        """Fa una prova. -> False se non è partita (già in corso, consenso negato, dati mancanti)."""
        if self.busy():
            return False
        if code in lihuiyu.MUOVE | ruida.MUOVE | {"K*"}:
            if QMessageBox.question(self, tr("Studia la macchina"), consenso_testo(code)) != QMessageBox.Yes:
                self._log(tr("{0}: non fatta (nessun consenso).", code))
                return False
        try:
            job = self._job(code)
        except ValueError as ex:
            QMessageBox.warning(self, tr("Studia la macchina"), str(ex))
            return False
        self._stop.clear()
        self._set_running(code, True)
        self._log(tr("Tutte le prove della K40: comincio.") if code == "K*" else tr("{0}: comincio.", code))
        if sync:
            self._work(code, job)
            return True
        self._thread = threading.Thread(target=self._work, args=(code, job), daemon=True)
        self._thread.start()
        return True

    def _job(self, code):
        stop = self._stop.is_set
        if code.startswith("K"):
            d = self.diario("k40")
            d.scrivi("scelte", scheda_scelta=self.k40_board.currentData(),
                     scritta=studio.pulisci_etichetta(self.k40_label.text()))
            if code == "K0":
                return lambda: lihuiyu.prova_k0(d, self.k40_run)
            links = self.k40_links()
            scheda = self.scheda_k40()
            def fidati():  # K2 fatta in questo diario ha detto che «pronta» arriva quando la testa è a casa
                r = next((x for x in reversed(d.righe) if x.get("prova") == "K2"), {})
                return r.get("verdetto") == "pronta_dopo_arrivo"

            uno = {"K1": lambda: lihuiyu.prova_k1(d, links),
                   "K2": lambda: lihuiyu.prova_k2(d, links, stop, scheda),
                   "K3": lambda: lihuiyu.prova_k3(d, links, scheda, stop, fidati_di_pronta=fidati()),
                   "K4": lambda: lihuiyu.prova_k4(d, links, scheda, stop, fidati_di_pronta=fidati())}
            if code != "K*":
                return uno[code]
            self._da_riga = len(d.righe)  # i risultati di questo giro, non quelli di prima

            def tutte():  # 0.22.5: una dopo l'altra; si ferma alla prima che non trova la scheda o se premi Ferma
                lihuiyu.prova_k0(d, self.k40_run)
                for c in TUTTE_K40[1:]:
                    if stop():
                        raise InterruptedError
                    self._ponte_riga(tr("{0}: comincio.", c))
                    uno[c]()
                    r = next((x for x in reversed(d.righe) if x.get("prova") == c), {})
                    if r.get("esito") not in ESITI_OK:
                        break
            return tutte
        link = self.ruida_link()
        d = self.diario("ruida")
        d.scrivi("scelte", collegamento=link.nome, pannello=studio.pulisci_etichetta(self.ruida_model.text()),
                 rete=studio.maschera_ip(getattr(link, "ip", "")) if link.nome == "rete" else "")
        if code == "R1":
            def r1():
                k = ruida.prova_r1(d, link)
                if k is not None:
                    self.chiave_ruida = k
                return k
            return r1
        if code == "R2":
            return lambda: ruida.prova_r2(d, link, self.chiave_ruida)
        if code == "R3":
            def r3():
                if self.chiave_ruida is None and link.somma:
                    self.chiave_ruida = ruida.prova_r1(d, link)
                return ruida.prova_r3(d, link, self.chiave_ruida, stop)
            return r3
        return lambda: ruida.prova_r4(d, link, self.chiave_ruida, stop)

    def _work(self, code, job):
        exc = ""
        try:
            job()
        except InterruptedError:
            exc = "fermata"
        except Exception as ex:  # noqa: BLE001
            exc = f"{type(ex).__name__}: {ex}"
            macchina = "k40" if code.startswith("K") else "ruida"
            if macchina in self.diari:
                self.diari[macchina].risultato(code, "errore", errore=exc)
        d = self.diari.get("k40" if code.startswith("K") else "ruida")
        cerca = TUTTE_K40[-1] if code == "K*" else code
        last = next((r for r in reversed(d.righe) if r.get("prova") == cerca), None) if d else None
        esito = (last or {}).get("esito", "errore")
        if threading.current_thread() is threading.main_thread():
            self._finita(code, esito, exc)
        else:
            try:
                self._ponte.fine.emit(code, esito, exc)
            except RuntimeError:  # finestra già chiusa: il risultato è comunque nel diario
                pass

    def _ponte_riga(self, testo):
        if threading.current_thread() is threading.main_thread():
            self._log(testo)
        else:
            try:
                self._ponte.riga.emit(testo)
            except RuntimeError:
                pass

    def _finita(self, code, esito, exc):
        if code == "K*":
            return self._finite_tutte(exc)
        self._set_running(code, False)
        st, _b = self.rows[code]
        if exc == "fermata":
            st.setText(tr("fermata"))
            self._log(tr("{0}: fermata.", code))
        elif esito in ESITI_OK:
            st.setText("✓ " + tr("fatta"))
            self._log(tr("{0}: fatta, risultato salvato.", code) + self._riassunto(code))
        else:
            st.setText("✗ " + tr("non riuscita"))
            self._log(tr("{0}: non riuscita ({1}). Il risultato è salvato comunque: anche questo serve.", code,
                         exc or esito) + self._riassunto(code))
        self._thread = None

    def _finite_tutte(self, exc):
        """Dopo «Fai tutte le prove»: ogni riga col suo stato e, nel registro, i risultati spiegati in parole."""
        self._set_running("K*", False)
        d = self.diari.get("k40")
        righe = d.righe[getattr(self, "_da_riga", 0):] if d else []
        spiegati = []
        for c in TUTTE_K40:
            st, _b = self.rows[c]
            r = next((x for x in reversed(righe) if x.get("prova") == c), None)
            if r is None:
                st.setText(tr("fermata") if exc == "fermata" else tr("non fatta"))
                continue
            ok = r.get("esito") in ESITI_OK
            st.setText(("✓ " + tr("fatta")) if ok else ("✗ " + tr("non riuscita")))
            spiegati.append(f"{c}: " + (tr("fatta.") if ok else tr("non riuscita ({0}).", r.get("esito", ""))) +
                            self._riassunto(c))
        if exc == "fermata":
            spiegati.append(tr("Prove fermate."))
        elif exc:
            spiegati.append(tr("Errore: {0}", exc))
        self._log(tr("Risultati:") + "\n" + "\n".join(spiegati) + "\n" +
                  tr("Ora premi «Invia un rapporto all'assistenza»: dentro ci sono tutti i dati."))
        self._thread = None

    def _riassunto(self, code):
        d = self.diari.get("k40" if code.startswith("K") else "ruida")
        r = next((x for x in reversed(d.righe) if x.get("prova") == code), {}) if d else {}
        if code == "K0":
            return " " + tr("Scheda trovata.") if r.get("trovata") else ""
        if code == "K1" and r.get("nomi"):
            return " " + tr("Stato: {0}.", ", ".join(r["nomi"]))
        if code == "K2" and r.get("verdetto") == "pronta_dopo_arrivo":
            return " " + tr("La scheda dice «pronta» quando la testa è arrivata a casa (da 10 cm: {0} s in più).",
                            str(r.get("differenza_s", "")).replace(".", ","))
        if code == "K2" and r.get("verdetto") == "pronta_subito":
            return " " + tr("La scheda dice «pronta» subito, anche se la testa è ancora per strada: FreeLaserCut "
                            "dovrà aspettare un tempo fisso dopo il ritorno a casa.")
        if code == "K3" and r.get("velocita_vera"):
            testo = " " + tr("Velocità misurate: {0}.", ", ".join(
                f"{k} → {v} mm/s" for k, v in r["velocita_vera"].items()))
            if r.get("rapporto"):
                medio = sum(r["rapporto"].values()) / len(r["rapporto"])
                testo += " " + tr("La testa va al {0} % della velocità chiesta.", f"{medio * 100:.0f}")
            return testo
        if code == "K4" and r.get("verdetto"):
            giri = str(r.get("giri", "")).replace(".", ",")
            return " " + {
                "solo_inizio_fine": tr("Il giro a fine corsa c'è solo all'inizio e alla fine del lavoro (giri contati: "
                                       "{0}). Bene: nei tagli veri non sposta il pezzo.", giri),
                "a_ogni_corsa": tr("Il giro a fine corsa c'è a ogni cambio di verso anche dentro un solo lavoro (giri "
                                   "contati: {0}). Va studiato prima di tagliare.", giri),
                "non_chiaro": tr("Dai tempi non si capisce se il giro c'è solo all'inizio e alla fine (giri contati: "
                                 "{0}). Conviene rifare la prova.", giri),
            }.get(r["verdetto"], "")
        if code.startswith("K") and r.get("motivo"):
            testo = {
                "libusb_senza_pyusb": tr("La scheda c'è e ha il driver libusb-win32 (quello che si installa con "
                                         "Zadig), ma per parlarle FreeLaserCut ha bisogno della libreria pyusb, che "
                                         "su questo computer manca. Nessun comando è partito."),
                "nessun_driver": tr("La scheda c'è, ma non ha un driver con cui FreeLaserCut sappia parlarle. "
                                    "Nessun comando è partito."),
                "senza_pyusb": tr("Su questo sistema per parlare con la scheda serve la libreria pyusb, che manca. "
                                  "Nessun comando è partito."),
                "non_vista": tr("La scheda non si vede: è accesa e collegata con il cavo USB?"),
            }.get(r["motivo"], "")
            return (" " + testo) if testo else ""
        if code == "R1" and r.get("chiave"):
            return " " + tr("Chiave: {0}.", r["chiave"])
        if code == "R2" and r.get("letti"):
            return " " + tr("Valori letti: {0}.", r["letti"])
        return ""

    def _set_running(self, code, on):
        self.b_stop.setEnabled(on)
        self.b_tutte.setEnabled(not on)
        for c, (st, b) in self.rows.items():
            b.setEnabled(not on)
        if on:
            for c in (TUTTE_K40 if code == "K*" else (code,)):
                self.rows[c][0].setText(tr("in corso…"))

    def ferma(self):
        self._stop.set()
        self._log(tr("Fermo appena possibile…"))

    def _log(self, text):
        self.log.appendPlainText(text)

    def _report(self):
        win = self.parent()
        act = getattr(win, "acts", {}).get("send_report") if win is not None else None
        if act is not None:
            act.trigger()

    def closeEvent(self, ev):
        if self.busy():
            self._stop.set()
            self._thread.join(5)
        super().closeEvent(ev)
