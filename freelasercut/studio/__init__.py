# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Studia la macchina (0.22.3, funzione in prova): raccoglie dati veri dalle macchine di chi prova FreeLaserCut, per
imparare a usare le schede che il programma ancora non sa guidare (K40 con la scheda M2 Nano e laser con la scheda
Ruida).

Regole che valgono per tutto il pacchetto:
- il laser non si accende mai: i comandi che lo accendono non esistono qui, e ogni byte passa da un controllo che
  rifiuta tutto quello che non è nell'elenco dei comandi permessi (lihuiyu.controlla, ruida.controlla);
- prima si legge; ci si muove solo con il consenso della persona, a laser spento, per pochi centimetri;
- ogni prova è indipendente: si fanno tutte o solo alcune, in qualsiasi ordine, anche da persone diverse;
- ogni risultato si scrive subito su disco (diario), così resta anche se il programma si chiude a metà, ed entra da
  solo nel rapporto per l'assistenza;
- nel diario ci sono solo dati della macchina: niente nomi di file, percorsi, disegni, nome del computer, porte;
  l'indirizzo di rete si scrive mascherato.

I protocolli sono stati studiati sulla documentazione e sul codice di altri progetti liberi (vedi
RICONOSCIMENTI-TECNICI.md) e riscritti da capo.
"""
import hashlib
import json
import os
import platform
import re
import secrets
import sys
import time

VERSIONE = 1  # versione del formato del diario: cambia se cambiano i campi
CARTELLA = "studio-macchina"
TENERE = 30  # file del diario che entrano nel rapporto (i più recenti)


class SicurezzaError(RuntimeError):
    """Un comando non permesso stava per partire verso la scheda: non è partito."""


def cartella():
    from ..profile import config_dir

    d = os.path.join(config_dir(), CARTELLA)
    os.makedirs(d, exist_ok=True)
    return d


def tester_id(qs=None):
    """Numero a caso, uguale per tutte le prove fatte da questo computer: serve solo a mettere insieme i rapporti di
    una stessa persona. Non dice niente di chi è."""
    if qs is not None:
        v = qs.value("studio/tester")
        if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{8}", v):
            return v
    v = secrets.token_hex(4)
    if qs is not None:
        qs.setValue("studio/tester", v)
    return v


def impronta(*valori):
    """Impronta corta di valori letti dalla macchina: la stessa macchina dà la stessa impronta, senza scrivere in
    chiaro numeri che potrebbero identificarla."""
    h = hashlib.sha256(json.dumps(valori, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return h[:10]


def maschera_ip(ip):
    """192.168.1.50 -> «192.168.x.x»; tutto quello che non è un indirizzo IPv4 diventa «?»."""
    m = re.fullmatch(r"\s*(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\s*", str(ip or ""))
    return f"{m.group(1)}.{m.group(2)}.x.x" if m else "?"


def pulisci_etichetta(text, n=40):
    """Il modello scritto a mano (per esempio «6C6879-LASER-M2:9» o «RDC6445G»): solo lettere, cifre e - : . / spazio."""
    return re.sub(r"[^A-Za-z0-9\-:./ ]", "", str(text or ""))[:n].strip()


def sistema():
    return {"sistema": platform.system(), "versione_sistema": platform.release(), "architettura": platform.machine(),
            "python": sys.version.split()[0]}


def esadecimale(data):
    return bytes(data or b"").hex(" ")


class Diario:
    """Un file .jsonl per sessione di prove: una riga per evento, scritta e svuotata su disco subito."""

    def __init__(self, macchina, tester="", path=None, extra=None):
        from .. import __version__

        self.macchina = macchina
        self.tester = tester
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = path or os.path.join(cartella(), f"{stamp}-{macchina}-{secrets.token_hex(2)}.jsonl")
        self.righe = []
        self.scrivi("inizio", flc=__version__, studio=VERSIONE, **sistema(), **(extra or {}))

    def scrivi(self, evento, **dati):
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "macchina": self.macchina, "tester": self.tester,
               "evento": evento, **dati}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        self.righe.append(rec)
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
        except OSError:
            pass  # senza disco il diario resta in memoria: la finestra lo mostra comunque
        return rec

    def risultato(self, prova, esito, **dati):
        return self.scrivi("prova", prova=prova, esito=esito, **dati)


def file_per_rapporto(n=TENERE):
    """[(nome nel rapporto, testo)] dei diari più recenti."""
    try:
        d = cartella()
        names = sorted(f for f in os.listdir(d) if f.endswith(".jsonl"))[-n:]
    except OSError:
        return []
    out = []
    for f in names:
        try:
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                out.append((f"{CARTELLA}/{f}", fh.read()[-300_000:]))
        except OSError:
            continue
    return out
