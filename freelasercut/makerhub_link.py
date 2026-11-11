# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Collegamento MakerHub → FreeLaserCut (0.18.14, fra le funzioni in prova): il disegno fatto sul loro sito arriva
sul piano di lavoro senza scaricarlo e importarlo a mano.

Come funziona. Gli strumenti di MakerHub (Dima Lab, Forma Lab, Hinge Lab, Split Lab) hanno il pulsante «Manda a
FreeLaserCut». Il pulsante apre una finestrella del browser su http://127.0.0.1:47821/flc/ponte: è una pagina servita
da FreeLaserCut stesso, sul computer dell'utente. La finestrella dice «pronto» alla pagina che l'ha aperta, riceve da
lei il file (postMessage del browser), lo consegna qui e si chiude. Non è una chiamata di rete verso l'esterno:
FreeLaserCut non chiama MakerHub e MakerHub non chiama FreeLaserCut; tutto passa dal browser dell'utente, sul suo
computer.

Perché una finestrella e non una chiamata diretta dalla pagina: da Chrome 142 una pagina pubblica che chiama il
computer locale fa comparire una richiesta di permesso, e dentro un riquadro (iframe) viene bloccata. L'apertura di
una finestra no (provato con Chromium 153 simulando un sito pubblico).

Sicurezza:
- si ascolta solo su 127.0.0.1 (mai sulla rete), e solo dopo che l'utente l'ha chiesto dal menu;
- nessuna intestazione CORS: nessun sito può leggere le risposte; l'intestazione Host deve essere la nostra (contro
  il «DNS rebinding»);
- chi manda il disegno lo dice il browser (event.origin, che una pagina non può falsificare): si accettano solo
  https://maker-hub.it e i suoi sottodomini, più le pagine servite da questo stesso computer (prove);
- la consegna vale solo con il gettone usa-e-getta scritto nella finestrella, che le altre pagine non possono leggere;
- limiti su dimensioni e numero dei file; degli ZIP si leggono solo gli SVG, senza scrivere niente su disco;
- il laser non parte mai: arriva un disegno sul piano, annullabile come ogni altra modifica.
"""
import base64
import binascii
import io
import json
import re
import secrets
import time
import urllib.parse
import zipfile
from collections import namedtuple

from .i18n import language, tr

PORT = 47821
PROTOCOL = 1
BRIDGE_PATH = "/flc/ponte"
IMPORT_PATH = "/flc/importa"
DOMAIN = "maker-hub.it"

MAX_HEAD = 16 * 1024  # intestazioni di una richiesta
MAX_BODY = 48 * 1024 * 1024  # corpo di una consegna (i file viaggiano in base64)
MAX_FILES = 64  # file in una consegna
MAX_ENTRIES = 400  # voci dentro uno ZIP
MAX_UNPACKED = 96 * 1024 * 1024  # peso totale dei disegni, una volta aperti gli ZIP
MAX_DRAWINGS = 200  # disegni in una consegna
TOKEN_LIFE = 600  # secondi di vita di un gettone
MAX_TOKENS = 32
IDLE_MS = 20000  # una connessione che non manda niente viene chiusa
CLOSE_MS = 1600  # dopo quanto si chiude la finestrella, a consegna fatta

Request = namedtuple("Request", "method path headers body")
Drawing = namedtuple("Drawing", "name data sheet")  # sheet: numero del foglio (piano-N.svg) oppure None
Arrival = namedtuple("Arrival", "tool origin kind drawings skipped")


class HttpError(Exception):
    def __init__(self, code, text=""):
        super().__init__(text or str(code))
        self.code = code
        self.text = text


class BadPayload(Exception):
    """La consegna non è valida; il testo è quello da mostrare a chi l'ha mandata."""


# ============================================================================ chi può mandare
def origin_kind(origin, allow_file=False):
    """Che cosa c'è dietro un'origine dichiarata dal browser: "makerhub" (https://maker-hub.it e sottodomini), "local"
    (una pagina servita da questo computer), "file" (un file aperto dal disco: origine «null», solo se allow_file),
    altrimenti None: non si accetta."""
    o = str(origin or "").strip()
    if o == "null":
        return "file" if allow_file else None
    try:
        u = urllib.parse.urlsplit(o)
        host = (u.hostname or "").lower()
        u.port  # un numero di porta non valido fa eccezione qui
    except ValueError:
        return None
    if u.username or u.password or u.path not in ("", "/") or u.query or u.fragment or not host:
        return None
    if u.scheme == "https" and (host == DOMAIN or host.endswith("." + DOMAIN)):
        return "makerhub"
    if u.scheme == "http" and (host in ("localhost", "127.0.0.1", "::1")):
        return "local"
    return None


# ============================================================================ HTTP, il minimo che serve
def parse_request(buf, max_body=MAX_BODY):
    """Una richiesta HTTP dai byte arrivati finora. -> Request, oppure None se ne mancano ancora.
    Solleva HttpError se non è una richiesta che si possa servire."""
    end = buf.find(b"\r\n\r\n")
    if end < 0:
        if len(buf) > MAX_HEAD:
            raise HttpError(431)
        return None
    if end > MAX_HEAD:
        raise HttpError(431)
    try:
        lines = bytes(buf[:end]).decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise HttpError(400) from None
    m = re.fullmatch(r"([A-Z]{3,7}) (/[\x21-\x7e]*) HTTP/1\.[01]", lines[0])
    if not m:
        raise HttpError(400)
    headers = {}
    for line in lines[1:]:
        k, sep, v = line.partition(":")
        k = k.strip().lower()
        if not sep or not k or k in headers and k in ("host", "content-length", "origin", "x-flc-token"):
            raise HttpError(400)
        headers[k] = v.strip()
    if "transfer-encoding" in headers:
        raise HttpError(411)
    n = headers.get("content-length", "0")
    if not n.isdigit() or len(n) > 12:
        raise HttpError(400)
    n = int(n)
    if n > max_body:
        raise HttpError(413)
    if len(buf) - end - 4 < n:
        return None
    return Request(m.group(1), urllib.parse.urlsplit(m.group(2)).path, headers, bytes(buf[end + 4:end + 4 + n]))


_REASONS = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
            405: "Method Not Allowed", 411: "Length Required", 413: "Payload Too Large",
            431: "Request Header Fields Too Large", 503: "Service Unavailable"}


def response(code, body=b"", ctype="text/plain; charset=utf-8", extra=()):
    """I byte di una risposta. Niente CORS (nessun sito deve poterla leggere) e niente cache."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    head = [f"HTTP/1.1 {code} {_REASONS.get(code, 'Error')}", f"Content-Type: {ctype}", f"Content-Length: {len(body)}",
            "Connection: close", "Cache-Control: no-store", "X-Content-Type-Options: nosniff",
            "Referrer-Policy: no-referrer", "Cross-Origin-Resource-Policy: same-origin", *extra]
    return ("\r\n".join(head) + "\r\n\r\n").encode("ascii") + body


def json_response(code, ok, message):
    return response(code, json.dumps({"ok": bool(ok), "messaggio": str(message)}, ensure_ascii=False),
                    "application/json; charset=utf-8")


# ============================================================================ che cosa è arrivato
def _clean_name(name, fallback="disegno"):
    """Solo il nome del file, senza cartelle né caratteri strani (non si scrive mai su disco: serve per i messaggi)."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*').strip(" .")
    return base[:80] or fallback


def _clean_tool(name):
    t = " ".join("".join(c for c in str(name or "") if c.isprintable() and c not in "<>&\"'`{}\\").split())
    return t[:40] or "MakerHub"


def _looks_svg(data):
    return b"<svg" in data[:4096].lower() and b"<!ENTITY" not in data  # niente «entità» XML: non servono a un disegno


_IMAGE = re.compile(rb"<image\b[^>]*>", re.I)
_EMBEDDED = re.compile(rb"href\s*=\s*[\"']\s*data:image/", re.I)


def safe_svg(data):
    """Lo stesso SVG senza le immagini che puntano a un file o a un indirizzo (restano quelle scritte dentro il file):
    un disegno arrivato da un sito non deve far aprire al programma file del computer."""
    return _IMAGE.sub(lambda m: m.group(0) if _EMBEDDED.search(m.group(0)) else b"", data)


def _sheet_no(name):
    m = re.fullmatch(r"piano[-_ ]?(\d{1,4})\.svg", name.lower())
    return int(m.group(1)) if m else None


def _reference_only(name):
    """La mappa di montaggio è un disegno da guardare, non da tagliare (lo dicono gli strumenti stessi)."""
    return name.lower().startswith(("mappa", "montaggio", "assembly", "anteprima"))


def unpack(files):
    """I disegni dentro una consegna: [(nome, byte)] -> (disegni, saltati). Gli ZIP vengono aperti (in memoria);
    restano gli SVG da tagliare, in ordine: prima i fogli piano-1.svg, piano-2.svg…, poi gli altri pezzi."""
    drawings, skipped, weight = [], [], 0

    def take(name, data):
        nonlocal weight
        if not name.lower().endswith(".svg") or _reference_only(name) or not _looks_svg(data):
            skipped.append(name)
            return
        weight += len(data)
        if weight > MAX_UNPACKED or len(drawings) >= MAX_DRAWINGS:
            raise BadPayload(tr("Il file è troppo grande per essere mandato così: scaricalo dal sito e importalo con "
                                "File → Importa."))
        drawings.append(Drawing(name, safe_svg(data), _sheet_no(name)))

    for name, data in files:
        name = _clean_name(name)
        if data[:4] == b"PK\x03\x04" or name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    infos = [i for i in z.infolist() if not i.is_dir()]
                    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                        raise BadPayload(tr("Il file è troppo grande per essere mandato così: scaricalo dal sito e "
                                            "importalo con File → Importa."))
                    for i in infos:
                        inner = _clean_name(i.filename)
                        if not inner.lower().endswith(".svg") or _reference_only(inner):
                            skipped.append(inner)
                            continue
                        take(inner, z.read(i))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, ValueError):
                raise BadPayload(tr("Non riesco ad aprire il file arrivato ({0}).", name)) from None
        else:
            take(name, data)
    sheets = sorted((d for d in drawings if d.sheet is not None), key=lambda d: d.sheet)
    return sheets + [d for d in drawings if d.sheet is None], skipped


def read_payload(body, allow_file=False):
    """La consegna della finestrella (JSON) -> Arrival. Solleva BadPayload con il testo da mostrare."""
    try:
        d = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BadPayload(tr("Il disegno arrivato non è leggibile.")) from None
    if not isinstance(d, dict) or not isinstance(d.get("file"), list) or not 1 <= len(d["file"]) <= MAX_FILES:
        raise BadPayload(tr("Il disegno arrivato non è leggibile."))
    origin = d.get("origine")
    kind = origin_kind(origin, allow_file) if isinstance(origin, str) else None
    if kind is None:
        raise PermissionError(tr("Questo sito non può mandare disegni a FreeLaserCut."))
    files = []
    for f in d["file"]:
        if not isinstance(f, dict):
            raise BadPayload(tr("Il disegno arrivato non è leggibile."))
        if isinstance(f.get("testo"), str):
            data = f["testo"].encode("utf-8")
        elif isinstance(f.get("b64"), str):
            try:
                data = base64.b64decode(f["b64"], validate=True)
            except (binascii.Error, ValueError):
                raise BadPayload(tr("Il disegno arrivato non è leggibile.")) from None
        else:
            raise BadPayload(tr("Il disegno arrivato non è leggibile."))
        files.append((f.get("nome"), data))
    drawings, skipped = unpack(files)
    if not drawings:
        raise BadPayload(tr("Nel file arrivato non c'è nessun disegno da tagliare."))
    return Arrival(_clean_tool(d.get("strumento")), origin, kind, drawings, skipped)


# ============================================================================ la finestrella
def _texts():
    return {
        "attesa": tr("Aspetto il disegno da MakerHub…"),
        "consegno": tr("Porto il disegno in FreeLaserCut…"),
        "fatto": tr("Fatto: il disegno è in FreeLaserCut."),
        "errore": tr("Non sono riuscito a portare il disegno in FreeLaserCut."),
        "niente": tr("Non è arrivato nessun disegno. Puoi chiudere questa finestra."),
        "solo": tr("Questa finestra serve a ricevere i disegni dagli strumenti di MakerHub. Puoi chiuderla."),
        "chiudi": tr("Questa finestra si chiude da sola."),
    }


_BRIDGE_JS = r"""(function(){'use strict';
var C=__CONFIG__,op=window.opener,m=document.getElementById('m'),n=document.getElementById('n'),done=false,from=null;
function say(t,k,note){m.textContent=t;n.textContent=note||'';document.body.className=k||''}
function tell(o){try{op.postMessage(o,from&&from!=='null'?from:'*')}catch(e){}}
if(!op){say(C.t.solo,'fermo');return}
function b64(buf){var u=new Uint8Array(buf),s='',i=0;for(;i<u.length;i+=0x8000)s+=String.fromCharCode.apply(null,u.subarray(i,i+0x8000));return btoa(s)}
function pack(f){var d=f&&f.dati,nome=String(f&&f.nome||'');
 if(typeof d==='string')return Promise.resolve({nome:nome,testo:d});
 if(typeof Blob!=='undefined'&&d instanceof Blob)return d.arrayBuffer().then(function(b){return{nome:nome,b64:b64(b)}});
 if(d instanceof ArrayBuffer)return Promise.resolve({nome:nome,b64:b64(d)});
 if(d&&d.buffer instanceof ArrayBuffer)return Promise.resolve({nome:nome,b64:b64(d.buffer.slice(d.byteOffset,d.byteOffset+d.byteLength))});
 return Promise.reject(new Error('dati'))}
window.addEventListener('message',function(e){
 if(done||e.source!==op)return;var d=e.data;
 if(!d||d.flc!=='disegno'||!Array.isArray(d.file))return;
 done=true;from=e.origin;say(C.t.consegno,'');
 Promise.all(d.file.slice(0,C.max).map(pack)).then(function(files){
  return fetch(C.importa,{method:'POST',headers:{'Content-Type':'application/json','X-FLC-Token':C.token},
   body:JSON.stringify({v:C.v,origine:from,strumento:String(d.strumento||''),file:files})})
 }).then(function(r){return r.json()}).then(function(j){
  var ok=!!(j&&j.ok),msg=String(j&&j.messaggio||'');
  say(msg||(ok?C.t.fatto:C.t.errore),ok?'ok':'errore',ok?C.t.chiudi:'');
  tell({flc:'fatto',v:C.v,ok:ok,messaggio:msg});
  if(ok)setTimeout(function(){window.close()},C.chiudi)
 }).catch(function(){say(C.t.errore,'errore');tell({flc:'fatto',v:C.v,ok:false,messaggio:C.t.errore})})
});
op.postMessage({flc:'pronto',v:C.v,app:'FreeLaserCut',versione:C.versione},'*');
setTimeout(function(){if(!done)say(C.t.niente,'fermo')},120000);
})();"""

_BRIDGE_HTML = """<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FreeLaserCut</title>
<style nonce="__NONCE__">
:root{color-scheme:light dark}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f4f3ef;color:#1d2a26;
font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:360px;padding:22px 26px;text-align:center}
h1{font-size:15px;letter-spacing:.08em;text-transform:uppercase;margin:0 0 14px;color:#5b6b65}
#i{width:38px;height:38px;margin:0 auto 14px;border-radius:50%;border:3px solid #c9d3cf;border-top-color:#2f6f5b;
animation:g 1s linear infinite}
p{margin:0 0 6px}#n{font-size:13px;color:#6b7a75}
.ok #i{animation:none;border-color:#2f8f62;background:#2f8f62}
.errore #i{animation:none;border-color:#c0492f;background:#c0492f}
.fermo #i{display:none}
@keyframes g{to{transform:rotate(360deg)}}
@media(prefers-color-scheme:dark){body{background:#1c211f;color:#e8ecea}h1,#n{color:#9fb0aa}#i{border-color:#3a4642;
border-top-color:#63c3a1}}
</style></head>
<body><main><h1>FreeLaserCut</h1><div id="i"></div><p id="m">__WAIT__</p><p id="n"></p></main>
<script nonce="__NONCE__">__SCRIPT__</script></body></html>
"""


def bridge_html(token, nonce, version):
    cfg = {"v": PROTOCOL, "token": token, "importa": IMPORT_PATH, "versione": version, "max": MAX_FILES,
           "chiudi": CLOSE_MS, "t": _texts()}
    js = _BRIDGE_JS.replace("__CONFIG__", json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c"))
    wait = _texts()["attesa"].replace("&", "&amp;").replace("<", "&lt;")
    return (_BRIDGE_HTML.replace("__LANG__", language()).replace("__WAIT__", wait)
            .replace("__SCRIPT__", js).replace("__NONCE__", nonce))


# ============================================================================ il ricevitore
class Core:
    """La logica del ricevitore, senza rete: una richiesta già letta -> i byte della risposta.
    deliver(Arrival) -> (riuscito, messaggio) è la funzione che porta il disegno nel programma."""

    def __init__(self, deliver, port=None, version="", allow_file=lambda: False, clock=time.monotonic):
        self.deliver = deliver
        self.port = port or PORT
        self.version = version
        self.allow_file = allow_file
        self.clock = clock
        self.tokens = {}  # gettone -> scadenza

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def new_token(self):
        now = self.clock()
        for t in [t for t, exp in self.tokens.items() if exp <= now]:
            del self.tokens[t]
        while len(self.tokens) >= MAX_TOKENS:
            del self.tokens[next(iter(self.tokens))]  # il più vecchio
        token = secrets.token_urlsafe(24)
        self.tokens[token] = now + TOKEN_LIFE
        return token

    def spend(self, token):
        """Il gettone vale una volta sola, ed entro la scadenza."""
        exp = self.tokens.pop(str(token or ""), None)
        return exp is not None and exp > self.clock()

    def handle(self, req):
        if req.headers.get("host", "").lower() != f"127.0.0.1:{self.port}":
            return response(403)  # un altro nome che punta qui (DNS rebinding) o una richiesta costruita a mano
        if req.path == BRIDGE_PATH:
            if req.method != "GET":
                return response(405, extra=("Allow: GET",))
            nonce = secrets.token_urlsafe(16)
            csp = ("Content-Security-Policy: default-src 'none'; script-src 'nonce-{0}'; style-src 'nonce-{0}'; "
                   "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'").format(nonce)
            return response(200, bridge_html(self.new_token(), nonce, self.version), "text/html; charset=utf-8",
                            (csp, "X-Frame-Options: DENY"))
        if req.path == IMPORT_PATH:
            if req.method != "POST":
                return response(405, extra=("Allow: POST",))
            # la consegna la fa solo la nostra finestrella: stessa origine, con il gettone che solo lei conosce
            if (req.headers.get("origin") != self.origin
                    or req.headers.get("sec-fetch-site", "same-origin") != "same-origin"
                    or not req.headers.get("content-type", "").lower().startswith("application/json")
                    or not self.spend(req.headers.get("x-flc-token"))):
                return json_response(403, False, tr("Questo sito non può mandare disegni a FreeLaserCut."))
            try:
                arrival = read_payload(req.body, bool(self.allow_file()))
            except PermissionError as exc:
                return json_response(403, False, exc)
            except BadPayload as exc:
                return json_response(400, False, exc)
            try:
                ok, message = self.deliver(arrival)
            except Exception as exc:  # noqa: BLE001 — al browser va comunque una risposta
                ok, message = False, tr("Non sono riuscito a portare il disegno in FreeLaserCut.") + f" ({exc})"
            return json_response(200, ok, message)
        return response(404)


class Receiver:
    """Il ricevitore vero: un QTcpServer su 127.0.0.1, nel filo principale (niente fili, niente attese)."""

    def __init__(self, deliver, version="", allow_file=lambda: False, port=None):
        from PySide6.QtNetwork import QTcpServer

        self.core = Core(deliver, port, version, allow_file)
        self.server = QTcpServer()
        self.server.newConnection.connect(self._new)
        self.socks = {}  # connessione -> byte arrivati finora (None: risposta già data)

    @property
    def port(self):
        return self.core.port

    def running(self):
        return self.server.isListening()

    def start(self):
        """-> True se ora è in ascolto (False: la porta è occupata da un altro programma)."""
        from PySide6.QtNetwork import QHostAddress

        if self.server.isListening():
            return True
        return bool(self.server.listen(QHostAddress(QHostAddress.LocalHost), self.core.port))

    def stop(self):
        self.server.close()
        for s in list(self.socks):
            s.abort()  # fa partire «disconnected», che la toglie dall'elenco
        self.socks.clear()
        self.core.tokens.clear()

    # ------------------------------------------------------------ connessioni
    def _new(self):
        from PySide6.QtCore import QTimer

        while self.server.hasPendingConnections():
            s = self.server.nextPendingConnection()
            self.socks[s] = bytearray()
            s.readyRead.connect(lambda s=s: self._read(s))
            s.disconnected.connect(lambda s=s: self._gone(s))
            t = QTimer(s)  # chi non finisce di parlare non resta appeso; il timer muore con la connessione
            t.setSingleShot(True)
            t.timeout.connect(lambda s=s: self._idle(s))
            t.start(IDLE_MS)

    def _idle(self, s):
        if s in self.socks:
            s.abort()

    def _gone(self, s):
        if self.socks.pop(s, 0) != 0:
            s.deleteLater()

    def _read(self, s):
        buf = self.socks.get(s)
        if buf is None:  # risposta già data (o connessione già chiusa): il resto non interessa
            s.readAll()
            return
        buf += bytes(s.readAll())
        try:
            req = parse_request(buf)
        except HttpError as exc:
            self._reply(s, response(exc.code))
            return
        if req is None:
            return
        self.socks[s] = None
        try:
            out = self.core.handle(req)
        except Exception:  # noqa: BLE001
            out = response(503)
        self._reply(s, out)

    def _reply(self, s, data):
        if s not in self.socks:  # chiusa mentre il disegno entrava nel programma
            return
        self.socks[s] = None
        s.write(data)
        s.flush()
        s.disconnectFromHost()
