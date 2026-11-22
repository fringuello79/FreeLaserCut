# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.0 (Ale, 21-22/11/2026): la Galleria, cioè i lavori che gli utenti condividono, da sfogliare dal programma.

Questo modulo parla con il servizio della Galleria (repository FreeLaserCut-galleria, su Cloudflare) e prepara il
pacchetto da condividere. Niente finestre: le due finestre sono in ui/dialogs_galleria.py.

Che cosa parte dal computer, e solo quando la persona preme «Condividi»:
- il progetto RIPULITO (project.json + immagini): il nome del progetto diventa il titolo scritto nel modulo; nel file
  non ci sono percorsi, nomi dei file originali, nome del PC né della porta;
- l'anteprima disegnata qui, le foto scelte dalla persona (ridotte e senza dati EXIF: niente posizione GPS);
- i dati del modulo, così come si vedono nella finestra;
- un numero a caso che distingue questa installazione (per un voto a testa e per i limiti): nessun account, nessuna email.

Regole di sicurezza per quello che ARRIVA dalla Galleria (è scritto da altri):
- solo https (http solo verso 127.0.0.1, per le prove);
- ogni risposta ha una grandezza massima; un progetto scaricato si controlla prima di aprirlo (solo project.json e
  images/*.png, niente file gonfiati apposta, immagini non enormi);
- i testi degli altri si mostrano sempre come testo semplice (lo fa l'interfaccia).
"""
import hashlib
import io
import json
import os
import re
import struct
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field

from . import __version__
from .i18n import tr
from .profile import config_dir

BASE_URL = "https://flc-galleria.freelasercut.workers.dev/v1"
REGOLE_VERSIONE = 1
KEY_INST = "galleria/installazione"
KEY_NOME = "galleria/nome_pubblico"

CATEGORIE = ("insegne", "scatole", "portachiavi", "decorazioni", "giochi", "casa", "utensili", "foto", "test", "altro")
TIPI = ("taglio", "incisione", "entrambi")
LICENZE = ("cc-by-4.0", "cc-by-nc-4.0", "cc0")
MOTIVI = ("non_funziona", "non_adatto", "copiato", "spam")
ORDINI = ("voti", "fatti", "nuovi")

# gli stessi limiti del servizio (FreeLaserCut-galleria, src/controlli.ts): controllati qui prima di mandare
MAX_PROGETTO = 10 * 1024 * 1024
MAX_ANTEPRIMA = 1024 * 1024
MAX_MINI = 120 * 1024
MAX_FOTO = 1024 * 1024
MAX_FOTO_N = 3
MAX_ZIP_VOCI = 500
MAX_ZIP_ESPANSO = 200 * 1024 * 1024
MAX_ZIP_RAPPORTO = 300
MAX_PIXEL_IMMAGINE = 40_000_000  # una sola immagine dentro un progetto scaricato
MAX_PIXEL_TOTALI = 120_000_000
MAX_JSON = 512 * 1024
PAGINA = 24


def nomi_categorie():
    return {"insegne": tr("Insegne e targhe"), "scatole": tr("Scatole e contenitori"),
            "portachiavi": tr("Portachiavi e gadget"), "decorazioni": tr("Decorazioni e Natale"),
            "giochi": tr("Giochi e puzzle"), "casa": tr("Casa e cucina"), "utensili": tr("Utensili e maschere"),
            "foto": tr("Foto e ritratti"), "test": tr("Test dei materiali"), "altro": tr("Altro")}


def nomi_tipi():
    return {"taglio": tr("Taglio"), "incisione": tr("Incisione"), "entrambi": tr("Taglio e incisione")}


def nomi_licenze():
    return {"cc-by-4.0": tr("CC BY 4.0: si può usare e modificare, citando l'autore"),
            "cc-by-nc-4.0": tr("CC BY-NC 4.0: come sopra, ma non per vendere"),
            "cc0": tr("CC0: senza condizioni")}


def nomi_motivi():
    return {"non_funziona": tr("Non funziona o è finto"), "non_adatto": tr("Contenuto non adatto"),
            "copiato": tr("Copiato da altri"), "spam": tr("Pubblicità o spam")}


def nomi_ordini():
    return {"voti": tr("Più votati"), "fatti": tr("Più fatti"), "nuovi": tr("Nuovi")}


def regole():
    """Le regole della Galleria, da accettare a ogni condivisione. Testo breve: da rivedere con l'avvocato prima
    di aprire la Galleria a tutti (cambiando il testo si alza REGOLE_VERSIONE)."""
    return [
        tr("Condividi solo lavori fatti da te, o che hai il diritto di condividere. Niente marchi, personaggi o "
           "disegni di altri senza il loro permesso."),
        tr("Niente contenuti offensivi, violenti, per adulti o illegali. Niente pubblicità, link, indirizzi email o "
           "numeri di telefono."),
        tr("Il lavoro diventa pubblico: chiunque può vederlo, scaricarlo e usarlo secondo la licenza che scegli."),
        tr("I controlli sono automatici. Chi guarda può segnalare un lavoro: i lavori segnalati vengono nascosti, e "
           "possono essere tolti senza preavviso."),
        tr("Puoi togliere i tuoi lavori quando vuoi, da «I miei lavori», dallo stesso computer da cui li hai "
           "condivisi."),
        tr("Potenza e velocità sono quelle del laser dell'autore: chi scarica un lavoro le controlla sul proprio "
           "laser prima di incidere. I lavori sono offerti senza garanzie: chi li usa lo fa a proprio rischio."),
        tr("Che cosa viene mandato: il progetto ripulito, l'anteprima, le foto che scegli e i dati di questo modulo. "
           "Nessun account e nessuna email: un numero a caso distingue questa installazione per i voti e i limiti."),
        tr("Per chiedere di togliere un contenuto: il pulsante «Segnala», oppure freelasercut@gmail.com."),
    ]


# ====================================================================== errori
class Errore(Exception):
    """Un rifiuto con il suo codice (quello del servizio, o uno di qui) e il testo da mostrare alla persona."""

    def __init__(self, codice, messaggio=None, stato=0, dati=None):
        self.codice, self.stato, self.dati = str(codice), int(stato or 0), dati or {}
        super().__init__(messaggio or testo_errore(self.codice))


def testo_errore(codice):
    c = str(codice)
    if c in ("testo_link", "testo_mail", "testo_telefono"):
        return tr("Nei testi non si possono mettere link, indirizzi email o numeri di telefono.")
    if c == "testo_parole":
        return tr("Nei testi ci sono parole non ammesse.")
    if c in ("testo_ripetuto", "testo_maiuscolo"):
        return tr("Scrivi i testi in modo normale: niente tutto maiuscolo e niente lettere ripetute.")
    return {
        "rete": tr("La Galleria non risponde: controlla la connessione a Internet e riprova."),
        "risposta": tr("La risposta della Galleria non è valida. Riprova più tardi."),
        "vuoto": tr("Il progetto è vuoto: disegna o importa qualcosa prima di condividerlo."),
        "grande": tr("Il progetto è troppo grande per la Galleria (al massimo 10 MB). Rimpicciolisci o togli le foto."),
        "file_grande": tr("Il progetto è troppo grande per la Galleria (al massimo 10 MB). Rimpicciolisci o togli le foto."),
        "foto": tr("Non riesco a leggere una delle foto scelte."),
        "titolo": tr("Scrivi un titolo fra 3 e 80 caratteri."),
        "materiale": tr("Scrivi il materiale (per esempio «Compensato di betulla»)."),
        "descrizione": tr("La descrizione è troppo lunga (al massimo 600 caratteri)."),
        "caselle": tr("Per condividere bisogna spuntare le due caselle in fondo."),
        "regole": tr("Per condividere bisogna spuntare le due caselle in fondo."),
        "opera_mia": tr("Per condividere bisogna spuntare le due caselle in fondo."),
        "campo": tr("La Galleria non ha accettato i dati del modulo."),
        "doppione": tr("Questo progetto è già nella Galleria."),
        "limite": tr("Hai raggiunto il limite di oggi. Riprova domani."),
        "troppe": tr("Troppe richieste: riprova fra un minuto."),
        "non_trovato": tr("Questo lavoro non è più nella Galleria."),
        "proprio": tr("È un tuo lavoro: non puoi votarlo."),
        "chiave": tr("Questo lavoro si può cambiare solo dal computer da cui è stato condiviso."),
        "installazione": tr("Questa installazione non è stata riconosciuta dalla Galleria."),
        "file": tr("Il file ricevuto dalla Galleria non è un progetto valido: non lo apro."),
        "indirizzo": tr("L'indirizzo della Galleria non è sicuro: non mi collego."),
    }.get(c, tr("La Galleria ha avuto un problema. Riprova più tardi."))


def testo_stato(stato, motivo=""):
    """La frase da mostrare dopo una condivisione, secondo lo stato deciso dal servizio."""
    m = str(motivo or "")
    m = m[3:] if m.startswith("ia:") else m
    if stato == "pubblico":
        return tr("Fatto: il lavoro è nella Galleria.")
    if stato == "attesa":
        return tr("Il lavoro è arrivato. Il controllo automatico delle immagini non ha risposto: verrà riprovato "
                  "entro un'ora, poi il lavoro comparirà nella Galleria.")
    if stato == "rifiutato":
        perche = {"adult": tr("contenuto per adulti"), "violence": tr("violenza"), "hate": tr("odio o offese"),
                  "weapon": tr("armi"), "drugs": tr("droghe"), "spam": tr("pubblicità o spam")}.get(m, m)
        return tr("Il controllo automatico non ha accettato le immagini del lavoro ({0}). Il lavoro non è stato "
                  "pubblicato.", perche)
    if stato == "nascosto":
        return tr("Il controllo automatico non è sicuro che sia un lavoro per il laser: resta nascosto finché non "
                  "viene guardato.")
    return tr("Il lavoro è arrivato alla Galleria.")


# ====================================================================== controlli sui testi (come il servizio)
_VIETATE = ("viagra", "cialis", "casino", "scommesse", "bitcoin", "crypto", "forex", "escort", "onlyfans",
            "telegram.me", "porn", "porno", "xxx", "nsfw", "hentai", "cazzo", "puttana", "troia", "vaffanculo",
            "fuck", "shit", "bitch", "puta", "mierda", "joder", "putain", "merde", "salope", "caralho", "porra",
            # 0.22.0: chi descrive il proprio lavoro come esplicito o per adulti (non «nudo»: legno nudo; non «hard»)
            "esplicito", "esplicita", "espliciti", "esplicite", "explicit", "explicito", "explicita", "explicite",
            "sex", "sexy", "sesso", "sexo", "sexe", "erotico", "erotica", "erotic", "erotique", "nudes", "dildo", "penis",
            "vagina")
_RE_MAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
_RE_LINK = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|it|ru|cn|xyz|shop|top|info|biz|me|ly)\b", re.I)
_RE_TEL = re.compile(r"\+?\d[\d .\-()]{7,}\d")


def controlla_testo(s):
    """None se il testo va bene, altrimenti il motivo (lo stesso nome usato dal servizio: «testo_<motivo>»)."""
    s = str(s or "")
    if not s:
        return None
    if _RE_MAIL.search(s):
        return "mail"
    if _RE_LINK.search(s):
        return "link"
    if _RE_TEL.search(s) and sum(c.isdigit() for c in s) >= 9:
        return "telefono"
    piano = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    parole = re.split(r"[^a-z0-9.]+", piano)
    if any(p in parole for p in _VIETATE):
        return "parole"
    if re.search(r"(.)\1{7,}", s):
        return "ripetuto"
    lettere = [c for c in s if c.isalpha()]
    if len(lettere) > 12 and sum(c.isupper() for c in lettere) / len(lettere) > 0.8:
        return "maiuscolo"
    return None


def _pulito(v, massimo):
    s = unicodedata.normalize("NFC", str(v or ""))
    s = "".join(c for c in s if c in "\n\t" or ord(c) >= 32 and ord(c) != 127).strip()
    return s[:massimo] if massimo else s


def controlla_scheda(s):
    """Controlla il modulo come farà il servizio e ritorna la scheda pronta da mandare. Solleva Errore."""
    out = {
        "titolo": _pulito(s.get("titolo"), 0), "descrizione": _pulito(s.get("descrizione"), 0),
        "categoria": s.get("categoria"), "materiale": _pulito(s.get("materiale"), 0),
        "laser_famiglia": _pulito(s.get("laser_famiglia"), 80), "tipo": s.get("tipo"),
        "licenza": s.get("licenza"), "autore_nome": _pulito(s.get("autore_nome"), 40),
        "versione_flc": __version__, "regole_accettate": bool(s.get("regole_accettate")),
        "opera_mia": bool(s.get("opera_mia")),
    }
    if not 3 <= len(out["titolo"]) <= 80:
        raise Errore("titolo")
    if not 2 <= len(out["materiale"]) <= 60:
        raise Errore("materiale")
    if len(out["descrizione"]) > 600:
        raise Errore("descrizione")
    if out["categoria"] not in CATEGORIE or out["tipo"] not in TIPI or out["licenza"] not in LICENZE:
        raise Errore("campo")
    for campo, lo, hi in (("spessore_mm", 0, 100), ("potenza_w", 0, 500), ("larghezza_mm", 0, 3000),
                          ("altezza_mm", 0, 3000), ("tempo_s", 0, 7 * 24 * 3600)):
        v = s.get(campo)
        if v in (None, "", 0, 0.0):
            out[campo] = None
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise Errore("campo") from None
        if not (v == v and lo <= v <= hi):  # v == v: non è NaN
            raise Errore("campo")
        out[campo] = round(v) if campo == "tempo_s" else round(v, 2)
    for campo in ("titolo", "descrizione", "materiale", "autore_nome", "laser_famiglia"):
        m = controlla_testo(out[campo])
        if m:
            raise Errore("testo_" + m)
    if not (out["regole_accettate"] and out["opera_mia"]):
        raise Errore("caselle")
    return out


# ====================================================================== installazione e lavori propri
def installazione(qs):
    """Il numero a caso di questa installazione (32 cifre esadecimali), creato la prima volta che serve."""
    v = str(qs.value(KEY_INST) or "")
    if not re.fullmatch(r"[0-9a-f]{32}", v):
        v = uuid.uuid4().hex
        qs.setValue(KEY_INST, v)
    return v


def azzera_installazione(qs):
    qs.remove(KEY_INST)
    return installazione(qs)


def _file_miei():
    return os.path.join(config_dir(), "galleria-miei.json")


def miei():
    """I lavori condivisi da questo computer: [{id, chiave, titolo, data}], i più recenti per primi."""
    try:
        with open(_file_miei(), encoding="utf-8") as fh:
            dati = json.load(fh)
    except (OSError, ValueError):
        return []
    return [d for d in dati if isinstance(d, dict) and re.fullmatch(r"[a-z0-9]{10}", str(d.get("id", "")))
            and isinstance(d.get("chiave"), str)] if isinstance(dati, list) else []


def _scrivi_miei(elenco):
    path = _file_miei()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(elenco, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ricorda_mio(ident, chiave, titolo, data):
    _scrivi_miei([{"id": ident, "chiave": chiave, "titolo": titolo, "data": data}] + [m for m in miei() if m["id"] != ident])


def dimentica_mio(ident):
    _scrivi_miei([m for m in miei() if m["id"] != ident])


def chiave_di(ident):
    return next((m["chiave"] for m in miei() if m["id"] == ident), None)


# ====================================================================== rete
def base():
    """L'indirizzo del servizio. Per le prove si cambia con FLC_GALLERIA_URL; fuori da 127.0.0.1 vale solo https."""
    url = (os.environ.get("FLC_GALLERIA_URL") or BASE_URL).rstrip("/")
    u = urllib.parse.urlsplit(url)
    locale = u.hostname in ("127.0.0.1", "localhost")
    if not (u.scheme == "https" or (u.scheme == "http" and locale)):
        raise Errore("indirizzo")
    return url, locale


def _apri(req, timeout, locale):
    if locale:  # prove: mai attraverso un proxy
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (solo https: lo controlla base())


def chiama(metodo, percorso, dati=None, corpo=None, inst=None, chiave=None, limite=MAX_JSON, binario=False, timeout=25):
    """Una richiesta al servizio. Ritorna il JSON (o i byte, con binario=True). Solleva Errore con il codice del
    servizio; «rete» se non si arriva, «risposta» se arriva qualcosa che non si capisce o troppo grande."""
    url, locale = base()
    h = {"User-Agent": f"FreeLaserCut/{__version__}", "X-FLC-Versione": __version__, "Accept": "application/json"}
    if inst:
        h["X-FLC-Installazione"] = inst
    if chiave:
        h["X-FLC-Chiave"] = chiave
    body = None
    if dati is not None:
        body = json.dumps(dati).encode("utf-8")
        h["Content-Type"] = "application/json"
    elif corpo is not None:
        body = bytes(corpo)
        h["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url + percorso, data=body, method=metodo, headers=h)
    try:
        with _apri(req, timeout, locale) as r:
            raw = r.read(limite + 1)
    except urllib.error.HTTPError as exc:
        try:
            info = json.loads(exc.read(MAX_JSON).decode("utf-8", "replace"))
            codice = str(info.get("errore") or "")
        except Exception:  # noqa: BLE001  risposta d'errore non JSON (proxy, pagina del fornitore)
            info, codice = {}, ""
        raise Errore(codice or "interno", stato=exc.code, dati=info if isinstance(info, dict) else {}) from None
    except Errore:
        raise
    except Exception:  # noqa: BLE001  rete assente, tempo scaduto, certificato, nome non trovato
        raise Errore("rete") from None
    if len(raw) > limite:
        raise Errore("risposta")
    if binario:
        return raw
    try:
        out = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Errore("risposta") from None
    if not isinstance(out, (dict, list)):
        raise Errore("risposta")
    return out


def _id_valido(ident):
    if not re.fullmatch(r"[a-z0-9]{10}", str(ident or "")):
        raise Errore("non_trovato")
    return str(ident)


def _testo(v, massimo):
    return _pulito(v, massimo) if isinstance(v, str) else ""


def _numero(v, lo=0.0, hi=1e9):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and lo <= v <= hi else None


def lavoro_pulito(d):
    """Una scheda arrivata dal servizio, ridotta ai campi conosciuti e ai tipi giusti (è scritta da altri)."""
    if not isinstance(d, dict):
        raise Errore("risposta")
    ident = d.get("id")
    if not re.fullmatch(r"[a-z0-9]{10}", str(ident or "")):
        raise Errore("risposta")
    n = lambda k, hi=1e9: _numero(d.get(k), 0, hi)  # noqa: E731
    return {
        "id": ident, "titolo": _testo(d.get("titolo"), 80).replace("\n", " "), "descrizione": _testo(d.get("descrizione"), 600),
        "categoria": d.get("categoria") if d.get("categoria") in CATEGORIE else "altro",
        "materiale": _testo(d.get("materiale"), 60).replace("\n", " "), "spessore_mm": n("spessore_mm", 100),
        "laser_famiglia": _testo(d.get("laser_famiglia"), 80).replace("\n", " "), "potenza_w": n("potenza_w", 500),
        "tipo": d.get("tipo") if d.get("tipo") in TIPI else "entrambi",
        "larghezza_mm": n("larghezza_mm", 3000), "altezza_mm": n("altezza_mm", 3000), "tempo_s": n("tempo_s", 7 * 24 * 3600),
        "licenza": d.get("licenza") if d.get("licenza") in LICENZE else "cc-by-4.0",
        "autore_nome": _testo(d.get("autore_nome"), 40).replace("\n", " "),
        "foto_n": int(n("foto_n", MAX_FOTO_N) or 0), "nuovo": d.get("nuovo") is True,
        "stelle_media": n("stelle_media", 5), "stelle_n": int(n("stelle_n") or 0), "fatti_n": int(n("fatti_n") or 0),
        "scaricati_n": int(n("scaricati_n") or 0),
        "stato": d.get("stato") if d.get("stato") in ("caricamento", "attesa", "pubblico", "nascosto", "rifiutato") else "",
        "motivo": _testo(d.get("motivo"), 60),
    }


def elenco(ordine="voti", categoria="", tipo="", cerca="", pagina=0):
    q = {"ordine": ordine if ordine in ORDINI else "voti", "pagina": max(0, int(pagina))}
    if categoria in CATEGORIE:
        q["categoria"] = categoria
    if tipo in TIPI:
        q["tipo"] = tipo
    if cerca:
        q["cerca"] = _pulito(cerca, 40)
    r = chiama("GET", "/elenco?" + urllib.parse.urlencode(q))
    righe = r.get("lavori") if isinstance(r, dict) else None
    if not isinstance(righe, list):
        raise Errore("risposta")
    out = []
    for d in righe[:PAGINA]:
        try:
            out.append(lavoro_pulito(d))
        except Errore:
            continue  # una riga rovinata non ferma l'elenco
    return {"lavori": out, "altre": r.get("altre") is True, "pagina": q["pagina"]}


def lavoro(ident, chiave=None):
    return lavoro_pulito(chiama("GET", "/lavoro/" + _id_valido(ident), chiave=chiave))


def anteprima(ident, chiave=None):
    """PNG dell'anteprima. Con la chiave dell'autore arriva anche quella di un lavoro non ancora pubblico (0.22.0)."""
    b = chiama("GET", "/anteprima/" + _id_valido(ident), chiave=chiave, limite=MAX_ANTEPRIMA, binario=True)
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Errore("risposta")
    return b


def foto(ident, n):
    b = chiama("GET", f"/foto/{_id_valido(ident)}/{int(n)}", limite=MAX_FOTO, binario=True)
    if not b.startswith(b"\xff\xd8\xff"):
        raise Errore("risposta")
    return b


def scarica(ident):
    """Il progetto di un lavoro, già controllato (vedi controlla_progetto). Solleva Errore("file") se non va."""
    b = chiama("GET", "/file/" + _id_valido(ident), limite=MAX_PROGETTO, binario=True, timeout=90)
    controlla_progetto(b, immagini=True)
    return b


def voto(qs, ident, stelle):
    if int(stelle) not in (1, 2, 3, 4, 5):
        raise Errore("campo")
    return lavoro_pulito(chiama("POST", "/voto", {"id": _id_valido(ident), "stelle": int(stelle)}, inst=installazione(qs)))


def fatto(qs, ident):
    return lavoro_pulito(chiama("POST", "/fatto", {"id": _id_valido(ident)}, inst=installazione(qs)))


def segnala(qs, ident, motivo):
    if motivo not in MOTIVI:
        raise Errore("campo")
    chiama("POST", "/segnala", {"id": _id_valido(ident), "motivo": motivo}, inst=installazione(qs))
    return True


def togli(ident):
    """Toglie dalla Galleria un lavoro condiviso da questo computer."""
    chiave = chiave_di(ident)
    if not chiave:
        raise Errore("chiave")
    try:
        chiama("POST", "/togli/" + _id_valido(ident), {}, chiave=chiave)
    except Errore as exc:
        if exc.codice != "non_trovato":  # già tolto (o scaduto): qui si dimentica lo stesso
            raise
    dimentica_mio(ident)
    return True


# ====================================================================== controllo di un file .flcut
def controlla_progetto(b, immagini=False):
    """Controlla un .flcut prima di mandarlo o di aprirlo: ZIP con solo project.json e images/<nome>.png, niente
    file cifrati o gonfiati apposta, project.json che è un progetto di FreeLaserCut. Con immagini=True (file che
    arriva da fuori) anche: ogni immagine è un PNG di grandezza ragionevole. Ritorna il dizionario del progetto."""
    try:
        if len(b) < 22 or len(b) > MAX_PROGETTO or b[:4] != b"PK\x03\x04":
            raise Errore("file")
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            voci = z.infolist()
            if not voci or len(voci) > MAX_ZIP_VOCI:
                raise Errore("file")
            espanso, progetto, pixel = 0, None, 0
            for v in voci:
                if v.flag_bits & 1 or v.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise Errore("file")
                if v.filename != "project.json" and not re.fullmatch(r"images/[A-Za-z0-9_-]{1,64}\.png", v.filename):
                    raise Errore("file")
                if v.compress_size > 0 and v.file_size / v.compress_size > MAX_ZIP_RAPPORTO:
                    raise Errore("file")
                espanso += v.file_size
                if espanso > MAX_ZIP_ESPANSO:
                    raise Errore("file")
                if v.filename == "project.json":
                    if v.file_size > 64 * 1024 * 1024:
                        raise Errore("file")
                    progetto = v
                elif immagini:
                    with z.open(v) as fh:
                        testa = fh.read(24)
                    if len(testa) < 24 or testa[:8] != b"\x89PNG\r\n\x1a\n" or testa[12:16] != b"IHDR":
                        raise Errore("file")
                    w, h = struct.unpack(">II", testa[16:24])
                    if w == 0 or h == 0 or w * h > MAX_PIXEL_IMMAGINE:
                        raise Errore("file")
                    pixel += w * h
                    if pixel > MAX_PIXEL_TOTALI:
                        raise Errore("file")
            if progetto is None:
                raise Errore("file")
            meta = json.loads(z.read(progetto).decode("utf-8"))
    except Errore:
        raise
    except Exception:  # noqa: BLE001  ZIP rovinato, JSON rovinato, testo non UTF-8
        raise Errore("file") from None
    if not isinstance(meta, dict) or meta.get("format") != "freelasercut" or not isinstance(meta.get("shapes"), list) \
            or not isinstance(meta.get("layers", {}), dict):
        raise Errore("file")
    return meta


def _forme(meta):
    n = len(meta.get("shapes") or [])
    for p in (meta.get("plates") or [])[1:]:
        if isinstance(p, dict):
            n += len(p.get("shapes") or [])
    return n


# ====================================================================== preparazione del pacchetto
@dataclass
class Pacchetto:
    progetto: bytes
    impronta: str
    anteprima: bytes
    mini: bytes
    foto: list = field(default_factory=list)  # [(jpeg, mini)]
    larghezza_mm: float = 0.0
    altezza_mm: float = 0.0
    forme: int = 0

    def parti(self):
        out = {"progetto": self.progetto, "anteprima": self.anteprima, "mini": self.mini}
        for i, (grande, piccola) in enumerate(self.foto, 1):
            out[f"foto{i}"] = grande
            out[f"foto{i}mini"] = piccola
        return out


_RE_PERCORSO = re.compile(r"[\\/]")


def _nome_senza_percorso(v):
    """Un nome dentro il progetto: se sembra un percorso («C:\\Users\\…\\logo.svg») resta solo l'ultima parte."""
    if isinstance(v, str) and _RE_PERCORSO.search(v):
        return _RE_PERCORSO.split(v.rstrip("\\/"))[-1][:80]
    return v


def _ripulisci(nodo):
    if isinstance(nodo, dict):
        for k, v in list(nodo.items()):
            if k == "name":
                nodo[k] = _nome_senza_percorso(v)
            else:
                _ripulisci(v)
    elif isinstance(nodo, list):
        for v in nodo:
            _ripulisci(v)


def progetto_ripulito(doc, titolo):
    """(byte del .flcut da condividere, dizionario del progetto, impronta). Il documento aperto non cambia:
    resta con il suo nome e il suo file."""
    vecchio = doc.path
    fd, tmp = tempfile.mkstemp(prefix="flc-galleria-", suffix=".flcut")
    os.close(fd)
    try:
        try:
            doc.save(tmp)
        finally:
            doc.path = vecchio  # save() si segna il file come quello del progetto: qui non deve
        with zipfile.ZipFile(tmp) as z:
            meta = json.loads(z.read("project.json").decode("utf-8"))
            immagini = {n: z.read(n) for n in sorted(z.namelist()) if n.startswith("images/") and n.endswith(".png")}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    meta["name"] = str(titolo)
    meta.pop("current", None)
    _ripulisci(meta.get("shapes"))
    _ripulisci(meta.get("plates"))
    for lay in (meta.get("layers") or {}).values():
        if isinstance(lay, dict) and "name" in lay:
            lay["name"] = _nome_senza_percorso(lay["name"])
    h = hashlib.sha256()
    h.update(json.dumps({k: meta.get(k) for k in ("shapes", "layers", "plates", "variables", "guides")},
                        sort_keys=True, ensure_ascii=True).encode("ascii"))
    for nome, dati in immagini.items():
        h.update(nome.encode("ascii", "replace"))
        h.update(hashlib.sha256(dati).digest())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(meta, indent=1))
        for nome, dati in immagini.items():
            z.writestr(nome, dati)
    return buf.getvalue(), meta, h.hexdigest()


def _forme_da_disegnare(doc):
    vis = [s for s in doc.shapes if not s.hidden]
    if vis:
        return vis
    for p in doc.plates:
        vis = [s for s in p.shapes if not s.hidden]
        if vis:
            return vis
    return []


def disegna_anteprima(doc, lato=800):
    """PNG del disegno su fondo bianco, stretto attorno alle forme (del piano attivo, o del primo che ne ha).
    Ritorna (byte PNG, larghezza in mm, altezza in mm)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform

    from .core import ops
    from .core.document import LAYER_COLORS, ImageShape

    forme = _forme_da_disegnare(doc)
    if not forme:
        raise Errore("vuoto")
    b = ops.union_bounds(forme)
    w_mm, h_mm = max(b.width(), 0.01), max(b.height(), 0.01)
    bordo = max(w_mm, h_mm) * 0.04 + 0.5
    rect = QRectF(b).adjusted(-bordo, -bordo, bordo, bordo)
    k = lato / max(rect.width(), rect.height())
    w, h = max(8, int(round(rect.width() * k))), max(8, int(round(rect.height() * k)))
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.setRenderHint(QPainter.SmoothPixmapTransform)
    vista = QTransform.fromTranslate(-rect.left(), -rect.bottom()) * QTransform.fromScale(k, -k)
    for s in forme:
        for leaf, tf in s.leaves():
            if leaf.hidden:
                continue
            if isinstance(leaf, ImageShape):
                pil = doc.images.get(leaf.image_id)
                if pil is None:
                    continue
                from PIL.ImageQt import ImageQt

                from .core import photo_clip

                pil = photo_clip.clipped_image(pil, leaf)
                pil.thumbnail((1600, 1600))
                qi = QImage(ImageQt(pil.convert("RGBA")))
                q.save()
                q.setTransform(QTransform.fromScale(1, -1) * QTransform.fromTranslate(0, leaf.h) * tf * vista)
                q.drawImage(QRectF(0, 0, leaf.w, leaf.h), qi)
                q.restore()
                continue
            colore = QColor(LAYER_COLORS[leaf.layer % 30] if leaf.layer < 30 else "#888888")
            q.save()
            q.setTransform(vista)
            pen = QPen(colore)
            pen.setCosmetic(True)
            pen.setWidthF(1.5)
            q.setPen(pen)
            path = tf.map(leaf.local_path())
            if doc.layer(leaf.layer).mode in ("fill", "offset_fill"):
                pieno = QColor(colore)
                pieno.setAlpha(110)
                q.fillPath(path, pieno)
            q.drawPath(path)
            q.restore()
    q.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba), w_mm, h_mm


def _jpeg(pil, lato, massimo):
    """JPEG di al massimo `lato` pixel e `massimo` byte, senza dati EXIF (niente posizione, niente modello)."""
    im = pil.convert("RGB")
    im.thumbnail((lato, lato))
    for lato_ora in (im.size[0], int(im.size[0] * 0.75), int(im.size[0] * 0.5), int(im.size[0] * 0.35)):
        prova = im if lato_ora == im.size[0] else im.resize((max(8, lato_ora), max(8, int(im.size[1] * lato_ora / im.size[0]))))
        for q in (85, 75, 62, 50):
            out = io.BytesIO()
            prova.save(out, "JPEG", quality=q, optimize=True)
            if out.tell() <= massimo:
                return out.getvalue()
    raise Errore("foto")


def _png_entro(png, massimo):
    """L'anteprima PNG entro la grandezza massima: se serve, rimpicciolita."""
    if len(png) <= massimo:
        return png
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    for lato in (640, 480, 360, 240):
        p = im.copy()
        p.thumbnail((lato, lato))
        out = io.BytesIO()
        p.save(out, "PNG", optimize=True)
        if out.tell() <= massimo:
            return out.getvalue()
    out = io.BytesIO()
    p.quantize(64).save(out, "PNG", optimize=True)
    if out.tell() > massimo:
        raise Errore("grande")
    return out.getvalue()


def foto_pronta(path):
    """Una foto scelta dalla persona → (JPEG da 1600 pixel, miniatura), girata nel verso giusto e senza EXIF."""
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im) or im
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                fondo = Image.new("RGB", im.size, "#FFFFFF")
                fondo.paste(im, mask=im.split()[-1])
                im = fondo
            return _jpeg(im, 1600, MAX_FOTO), _jpeg(im, 512, MAX_MINI)
    except Errore:
        raise
    except Exception:  # noqa: BLE001  file che non è un'immagine, rovinato, troppo grande per Pillow
        raise Errore("foto") from None


def prepara(doc, titolo, foto_paths=()):
    """Tutto quello che serve per condividere il progetto aperto. Non manda niente. Solleva Errore."""
    from PIL import Image

    if not [s for s in doc.all_shapes() if not s.hidden]:
        raise Errore("vuoto")
    progetto, meta, impronta = progetto_ripulito(doc, titolo)
    if len(progetto) > MAX_PROGETTO:
        raise Errore("grande")
    controlla_progetto(progetto)  # il file che parte si riapre ed è un progetto valido
    if _forme(meta) == 0:
        raise Errore("vuoto")
    png, w_mm, h_mm = disegna_anteprima(doc)
    png = _png_entro(png, MAX_ANTEPRIMA)
    mini = _jpeg(Image.open(io.BytesIO(png)), 512, MAX_MINI)
    foto_ = [foto_pronta(p) for p in list(foto_paths)[:MAX_FOTO_N]]
    return Pacchetto(progetto, impronta, png, mini, foto_, round(w_mm, 1), round(h_mm, 1), _forme(meta))


# ====================================================================== condivisione
def condividi(qs, scheda, pacchetto, avanzamento=None, adesso=None, annulla=None):
    """Manda il lavoro: scheda, poi i file uno alla volta, poi la chiusura (con il controllo automatico).
    Ritorna {"id", "stato", "motivo"}. La chiave dell'autore si salva appena il servizio la dà.
    annulla(): se diventa vero (finestra chiusa a metà) l'invio si ferma prima del passo successivo. Un invio
    fermato o fallito a metà non lascia niente: si chiede al servizio di toglierlo e qui lo si dimentica."""
    import time

    s = controlla_scheda(scheda)
    s.update({"impronta": pacchetto.impronta, "foto_n": len(pacchetto.foto),
              "larghezza_mm": s.get("larghezza_mm") or pacchetto.larghezza_mm or None,
              "altezza_mm": s.get("altezza_mm") or pacchetto.altezza_mm or None})
    parti = pacchetto.parti()
    passi = len(parti) + 2

    def passo(i):
        if annulla is not None and annulla():
            raise Errore("annullato", tr("Invio annullato."))
        if avanzamento:
            avanzamento(i, passi)

    passo(0)
    r = chiama("POST", "/condividi", s, inst=installazione(qs))
    ident, chiave, attese = r.get("id"), r.get("chiave_autore"), r.get("carica")
    if not re.fullmatch(r"[a-z0-9]{10}", str(ident or "")) or not isinstance(chiave, str) or len(chiave) < 20 \
            or not isinstance(attese, list) or sorted(attese) != sorted(parti):
        raise Errore("risposta")
    ricorda_mio(ident, chiave, s["titolo"], time.strftime("%Y-%m-%d", time.localtime(adesso)))
    try:
        for i, parte in enumerate(attese, 1):
            passo(i)
            chiama("PUT", f"/carica/{ident}/{parte}", corpo=parti[parte], chiave=chiave, timeout=120)
        passo(passi - 1)
        fine = chiama("POST", f"/concludi/{ident}", {}, chiave=chiave, timeout=90)
    except Errore:
        try:
            chiama("POST", f"/togli/{ident}", {}, chiave=chiave, timeout=15)
        except Errore:
            pass  # il servizio cancella da solo, dopo un giorno, gli invii non finiti
        dimentica_mio(ident)
        raise
    stato = fine.get("stato") if fine.get("stato") in ("pubblico", "attesa", "rifiutato", "nascosto") else "attesa"
    if stato == "rifiutato":
        dimentica_mio(ident)  # non c'è niente da togliere: il servizio lo cancella da solo
    if avanzamento:
        avanzamento(passi, passi)
    return {"id": ident, "stato": stato, "motivo": _testo(fine.get("motivo"), 60)}
