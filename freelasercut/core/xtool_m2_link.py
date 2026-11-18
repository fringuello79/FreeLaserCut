# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7, sperimentale (funzioni in prova): collegamento diretto con la xTool M2.

Rifà la stessa sequenza che xTool Studio usa con la macchina, vista in chiaro con la M2 virtuale (vedi
freeburn/xtool-m2-virtuale.md) e descritta dalla comunità (ha-xtool, licenza MIT):
- collegamento cifrato (WebSocket TLS) sulla porta 28900, canali «instruction» (richieste JSON) e «file_stream»;
- abbinamento: la prima richiesta è /v1/user/parity come «ospite»; se la macchina risponde 406 chiede di premere il
  suo pulsante (consenso di chi ha la macchina, non un aggiramento) e poi dà un gettone che si conserva;
- invio del lavoro: il file G-code della M2 sul canale dei file, poi i parametri del lavoro; la macchina si mette in
  attesa e il lavoro parte SOLO con il pulsante sulla macchina (o con «Avvia» da qui);
- pausa, ripresa, annullamento, stato, coperchio.

Nessun dato di account: si presenta come ospite. Niente G-code «grezzo» ai controllori (il servizio di diagnostica
salta i controlli della macchina: non si usa). Solo libreria standard. Il lavoro gira in un filo a parte con il suo
ciclo asyncio; chi usa la classe chiama metodi bloccanti (con un limite di tempo) e riceve gli eventi da `on_event`,
chiamato dal filo del collegamento: chi ha una finestra li passa al filo dell'interfaccia (coda + timer).
"""
import asyncio
import base64
import datetime
import hashlib
import json
import os
import ssl
import struct
import threading
import time
import urllib.request
import uuid

PORT = 28900
HTTP_PORT = 8080
USER_ID = "mk-guest"  # sessione da ospite, come xTool Studio senza account
USER_KEY = "bWFrZWJsb2NrLXh0b29s"  # chiave fissa della prima richiesta (base64 di «makeblock-xtool»)
PING_ID = 65510  # il battito usa sempre questo numero di richiesta
TXN_WRAP = 65500
PAIR_TIMEOUT = 60.0  # secondi per premere il pulsante
REQ_TIMEOUT = 10.0
PACKET = 1024 * 1024  # dimensione dei pacchetti del file (come xTool Studio)
T_JSON, T_FILE = 4, 33
FILE_REQUEST, FILE_DATA = 1, 129

# tipo della testa dichiarato dalla macchina -> potenza del modulo (W); l'infrarosso e la testa a inchiostro non
# sono previsti dal lavoro di FreeLaserCut
HEAD_WATTS = {"LASER_BLUE_10W": 10, "LASER_BLUE_20W": 20, "LASER_BLUE_40W": 40}
WORKHEAD = {10: "BLUE_10W", 20: "BLUE_20W", 40: "BLUE_40W"}
IDLE_STATES = ("idle", "p_idle", "finish", "p_finish")


class M2Error(Exception):
    """Errore del collegamento o risposta negativa della macchina (testo già da mostrare)."""

    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code


class PairingNeeded(M2Error):
    pass


# ------------------------------------------------------------------------------------------- busta BA BE
def crc16(data):
    """CRC-16/ARC (polinomio 0xA001 riflesso, partenza 0)."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def envelope(payload, kind, with_crc=True):
    n = len(payload)
    head = b"\xba\xbe" + n.to_bytes(3, "big") + bytes([(kind & 0x7F) | (0 if with_crc else 0x80)])
    head += (crc16(payload) if with_crc else 0).to_bytes(2, "big")
    return head + crc16(head).to_bytes(2, "big") + payload


class Unpacker:
    """Ricompone le buste anche spezzate o unite; scarta i byte rovinati riallineandosi alla firma BA BE."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out, i, b = [], 0, self.buf
        while i + 10 <= len(b):
            if b[i] != 0xBA or b[i + 1] != 0xBE:
                i += 1
                continue
            n = int.from_bytes(b[i + 2:i + 5], "big")
            if crc16(b[i:i + 8]) != int.from_bytes(b[i + 8:i + 10], "big"):
                i += 1
                continue
            if i + 10 + n > len(b):
                break
            kind = b[i + 5]
            payload = bytes(b[i + 10:i + 10 + n])
            if not kind & 0x80 and crc16(payload) != int.from_bytes(b[i + 6:i + 8], "big"):
                i += 1
                continue
            out.append((kind & 0x7F, payload))
            i += 10 + n
        del self.buf[:i]
        return out


def file_data(channel, offset, chunk):
    return bytes([FILE_DATA, channel & 0xFF]) + int(offset).to_bytes(5, "big") + chunk


def parse_file_request(payload):
    """-> (canale, scostamento, dimensione della finestra) o None."""
    if len(payload) >= 10 and payload[0] == FILE_REQUEST:
        return payload[1], int.from_bytes(payload[2:7], "big"), int.from_bytes(payload[7:10], "big")
    return None


def events_of(msg):
    """Una notifica della macchina -> lista di (url, campi). `data` può essere una lista di eventi con `name` (come
    li legge xTool Studio) oppure un oggetto solo."""
    url = msg.get("url", "")
    data = msg.get("data")
    items = data if isinstance(data, list) else [data if isinstance(data, dict) else {}]
    return [(str((it or {}).get("name") or url), it or {}) for it in items]


def mode_of(fields):
    """Modo della macchina da una notifica di stato o da state/sync."""
    cur = fields.get("curMode")
    if isinstance(cur, dict) and cur.get("mode"):
        return str(cur["mode"])
    return str(fields.get("mode") or fields.get("state") or "")


def action_of(fields):
    c = fields.get("content")
    if isinstance(c, dict):
        return str(c.get("action") or "").lower()
    return str(fields.get("action") or "").lower()


def is_idle(mode):
    return str(mode).strip().lower() in IDLE_STATES


def head_watts(info):
    return HEAD_WATTS.get(str((info or {}).get("type") or "").upper())


def head_maker(info):
    m = str((info or {}).get("manufacture") or "").upper()
    return m if m in ("TO", "COS") else None


def firmware_of(info):
    fw = (info or {}).get("firmware")
    if isinstance(fw, dict):
        return str(fw.get("version") or fw.get("package_version") or "")
    return str(fw or "")


def is_m2_version(text):
    """Versione del firmware del tipo NN.141.NNN (141 = M2 per xTool Studio)."""
    parts = str(text or "").lstrip("vV").split(".")
    return len(parts) >= 3 and parts[1] == "141"


def check_head(info, want_w=None, want_maker=None):
    """Controlla la testa montata contro la configurazione. -> (watt, costruttore) da usare; M2Error se non va.
    want_w / want_maker None = automatico (quello che dice la macchina)."""
    info = info or {}
    typ = str(info.get("type") or "")
    w = head_watts(info)
    if w is None:
        if typ.upper().startswith("LASER_RED"):
            raise M2Error("Sulla M2 è montato il modulo a infrarosso: FreeLaserCut per ora prepara il lavoro solo per "
                          "i moduli blu da 10, 20 e 40 W.")
        if typ:
            raise M2Error(f"Sulla M2 è montata una testa che FreeLaserCut non conosce ({typ}): il lavoro non parte.")
        if want_w is None:
            raise M2Error("La M2 non dice quale modulo è montato: scegli il modulo nella configurazione.")
        w = int(want_w)
    elif want_w is not None and int(want_w) != w:
        raise M2Error(f"Nella configurazione c'è il modulo da {int(want_w)} W, ma sulla M2 è montato quello da {w} W: "
                      "correggi la configurazione (o scegli «Automatico») prima di inviare.")
    direction = str(info.get("direction") or "vertical").lower()
    if direction not in ("vertical", "0"):
        raise M2Error("La M2 dice che la testa non è montata in verticale (supporto orizzontale): il lavoro non parte.")
    maker = head_maker(info)
    if want_maker is not None:
        if maker is not None and maker != want_maker:
            raise M2Error(f"Nella configurazione il modulo è «{want_maker}», ma la M2 dice «{maker}»: correggi la "
                          "configurazione (o scegli «Automatico»).")
        maker = want_maker
    return w, maker or "TO"


# ------------------------------------------------------------------------------------ WebSocket (client)
class _WS:
    """WebSocket minimo lato client (messaggi binari mascherati, ping/pong, chiusura)."""

    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.closed = False

    @classmethod
    async def open(cls, host, port, path, ssl_ctx, timeout):
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx, server_hostname=None if ssl_ctx is None else host,
                                    limit=2 ** 24), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        writer.write(req.encode())
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        first = head.split(b"\r\n", 1)[0]
        if b" 101" not in first:
            writer.close()
            raise M2Error(f"La M2 ha rifiutato il collegamento ({first.decode('latin-1', 'replace')})")
        return cls(reader, writer)

    async def send(self, data, opcode=2):
        if self.closed:
            raise ConnectionError("chiuso")
        n = len(data)
        if n < 126:
            head = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
        else:
            head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        body = bytearray(data)
        if n:
            m = (mask * (n // 4 + 1))[:n]
            body = bytes(a ^ b for a, b in zip(body, m)) if n < 4096 else _xor(bytes(body), m)
        self.w.write(head + mask + bytes(body))
        await self.w.drain()

    async def recv(self):
        """-> dati di un messaggio intero (binario o testo), None se chiuso."""
        parts = []
        while True:
            try:
                h = await self.r.readexactly(2)
                n = h[1] & 0x7F
                if n == 126:
                    n = struct.unpack(">H", await self.r.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", await self.r.readexactly(8))[0]
                mask = await self.r.readexactly(4) if h[1] & 0x80 else None
                data = await self.r.readexactly(n)
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                self.closed = True
                return None
            if mask:
                data = _xor(data, (mask * (n // 4 + 1))[:n])
            op = h[0] & 0x0F
            if op == 8:
                self.closed = True
                return None
            if op == 9:
                try:
                    await self.send(data, 10)
                except (ConnectionError, OSError):
                    pass
                continue
            if op == 10:
                continue
            parts.append(data)
            if h[0] & 0x80:
                return b"".join(parts)

    def close(self):
        self.closed = True
        try:
            self.w.close()
        except (OSError, RuntimeError):
            pass


def _xor(data, mask):
    a = int.from_bytes(data, "little")
    b = int.from_bytes(mask, "little")
    return (a ^ b).to_bytes(len(data), "little")


def _ssl_context():
    """La M2 ha un certificato autofirmato: si cifra senza verificarlo (lo fa anche xTool Studio)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def probe_version(host, port=HTTP_PORT, timeout=3.0):
    """Riconoscimento come fa xTool Studio con «Connessione IP»: GET /system?action=version. -> testo o ""."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/system?action=version", timeout=timeout) as r:
            data = json.loads(r.read(4096).decode("utf-8", "replace") or "{}")
        return str(data.get("version") or "")
    except (OSError, ValueError):
        return ""


# --------------------------------------------------------------------------------------- il collegamento
class M2Link:
    """Collegamento con una xTool M2. Metodi bloccanti (dal filo dell'interfaccia o da un altro filo).
    on_event(nome, dati): «pairing» (premi il pulsante), «paired» (gettone nuovo), «state» (modo), «process»
    (azione del lavoro: ready/start/pause/resume/cancel/finish), «upload» (frazione 0–1), «alarm», «closed»."""

    def __init__(self, host, token="", port=PORT, on_event=None, timezone=None, pair_timeout=PAIR_TIMEOUT):
        self.host = str(host).strip()
        self.port = int(port)
        self.token = str(token or "")
        self.session_token = ""
        self.on_event = on_event
        self.timezone = timezone or _local_tz()
        self.pair_timeout = float(pair_timeout)
        self.session = str(uuid.uuid4())
        self.info = {}
        self.head = {}
        self.mode = ""
        self.task_id = ""
        self.connected = False
        self._loop = None
        self._thread = None
        self._ws = None
        self._fws = None
        self._txn = 0
        self._pending = {}
        self._uploads = {}
        self._tasks = set()
        self._waiters = []

    # --- filo e ciclo ----------------------------------------------------------------------------
    def _start_loop(self):
        if self._loop is not None:
            return
        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()
            self._loop.close()

        self._thread = threading.Thread(target=run, name="xtool-m2", daemon=True)
        self._thread.start()
        ready.wait(5)

    def _call(self, coro, timeout):
        self._start_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout)
        except TimeoutError:  # concurrent.futures.TimeoutError è TimeoutError da Python 3.11
            fut.cancel()
            raise M2Error("La M2 non risponde (tempo scaduto).") from None

    def _emit(self, name, data=None):
        if self.on_event is not None:
            try:
                self.on_event(name, data)
            except Exception:  # noqa: BLE001 - un errore della finestra non deve fermare il collegamento
                pass

    def _spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    # --- API pubblica ----------------------------------------------------------------------------
    def connect(self, timeout=None):
        """Collega e abbina. Se la macchina chiede il pulsante manda l'evento «pairing» e aspetta fino a
        pair_timeout secondi. -> dizionario con machine-info e laser-head/info."""
        t = (timeout or (REQ_TIMEOUT * 3)) + self.pair_timeout
        return self._call(self._connect(), t)

    def close(self):
        if self._loop is None:
            return
        try:
            self._call(self._close("chiuso da FreeLaserCut"), 5)
            self._call(self._cancel_tasks(), 5)
        except M2Error:
            pass
        loop = self._loop
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(3)
        self._loop = None

    def request(self, url, method="GET", params=None, data=None, timeout=REQ_TIMEOUT):
        return self._call(self._request(url, method, params, data, timeout), timeout + 2)

    def refresh(self):
        """Stato della macchina: -> (modo, stato del coperchio)."""
        return self._call(self._refresh(), REQ_TIMEOUT * 3)

    def send_job(self, data, laser_w, thickness=0.0, filename="gcode.txt", smoke_fan=3, timeout=600):
        """Carica il lavoro e i suoi parametri: la macchina si mette in attesa del pulsante. -> taskID."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self._call(self._send_job(bytes(data), int(laser_w), float(thickness), filename, int(smoke_fan)),
                          timeout)

    def control(self, action):
        """START, PAUSE, RESUME o CANCEL."""
        action = str(action).upper()
        if action not in ("START", "PAUSE", "RESUME", "CANCEL"):
            raise ValueError(action)
        return self.request("/v1/project/device/control", "POST", params={"action": action})

    # --- dentro il ciclo -------------------------------------------------------------------------
    async def _connect(self):
        if self.connected:
            return {"machine": self.info, "head": self.head}
        ctx = _ssl_context()
        q = f"/websocket?id={self.session}&function="
        try:
            self._ws = await _WS.open(self.host, self.port, q + "instruction", ctx, REQ_TIMEOUT)
        except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
            raise M2Error(f"Non riesco a collegarmi alla M2 su {self.host}: {e}") from None
        self._spawn(self._read_loop(self._ws, "instruction"))
        result = await self._parity()
        self._apply_parity(result)
        self.connected = True
        self._spawn(self._heartbeat())
        try:
            self._fws = await _WS.open(self.host, self.port, q + "file_stream", ctx, REQ_TIMEOUT)
            self._spawn(self._read_loop(self._fws, "file_stream"))
        except (OSError, asyncio.TimeoutError, ssl.SSLError) as e:
            await self._close("canale dei file non aperto")
            raise M2Error(f"La M2 non apre il canale dei file: {e}") from None
        self.info = await self._request("/v1/platform/device/machine-info")
        self.head = await self._request("/v1/project/laser-head/info")
        try:
            sync = await self._request("/v1/platform/device/state/sync", "POST")
            self.mode = mode_of(sync or {})
        except M2Error:
            pass
        return {"machine": self.info, "head": self.head}

    async def _parity(self):
        data = {"userID": USER_ID, "userKey": USER_KEY, "timezone": self.timezone, "token": self.token}
        try:
            return await self._request("/v1/user/parity", "GET", data=data, first=True)
        except M2Error as e:
            if e.code != 406:
                await self._close("abbinamento rifiutato")
                raise
        self._emit("pairing", self.pair_timeout)
        end = time.monotonic() + self.pair_timeout
        while time.monotonic() < end:
            await asyncio.sleep(1.0)
            try:
                return await self._request("/v1/user/auth-status", "GET", first=True, timeout=20)
            except M2Error as e:
                if e.code in (503, 409, 410):
                    await self._close("abbinamento bloccato")
                    raise PairingNeeded("La M2 ha bloccato l'abbinamento (codice {0}). Riprova fra poco.".format(
                        e.code), e.code) from None
                if e.code is None:  # tempo scaduto o collegamento chiuso
                    await self._close("abbinamento non riuscito")
                    raise PairingNeeded("Abbinamento non riuscito: la M2 non risponde.") from None
        await self._close("pulsante non premuto")
        raise PairingNeeded("Il pulsante della M2 non è stato premuto in tempo: riprova e premilo quando richiesto.")

    def _apply_parity(self, result):
        result = result if isinstance(result, dict) else {}
        tok = result.get("token")
        if isinstance(tok, str) and tok and tok != self.token:
            self.token = tok
            self._emit("paired", tok)
        st = result.get("sessionToken")
        self.session_token = st if isinstance(st, str) else ""

    async def _request(self, url, method="GET", params=None, data=None, timeout=REQ_TIMEOUT, first=False):
        if self._ws is None or self._ws.closed:
            raise M2Error("La M2 non è collegata.")
        self._txn = self._txn + 1 if self._txn + 1 < TXN_WRAP else 1
        tid = self._txn
        msg = {"type": "request", "method": method.upper(), "url": url, "params": params or {}, "data": data or {},
               "timestamp": int(time.time() * 1000), "transactionId": tid}
        if self.session_token and not first:
            msg["sessionToken"] = self.session_token
        fut = asyncio.get_running_loop().create_future()
        self._pending[tid] = fut
        try:
            await self._ws.send(envelope(json.dumps(msg, separators=(",", ":")).encode(), T_JSON))
            resp = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise M2Error(f"La M2 non risponde a {url}.") from None
        except (ConnectionError, OSError):
            raise M2Error("Collegamento con la M2 interrotto.") from None
        finally:
            self._pending.pop(tid, None)
        code = resp.get("code", 0)
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = -1
        if code != 0:
            raise M2Error(f"La M2 ha risposto {code} a {url}: {resp.get('msg') or resp.get('message') or ''}".strip(),
                          code)
        return resp.get("data") if resp.get("data") is not None else {}

    async def _heartbeat(self):
        while self.connected and self._ws is not None and not self._ws.closed:
            await asyncio.sleep(3.0)
            msg = {"type": "request", "method": "GET", "url": "/v1/user/ping", "params": {}, "data": {},
                   "timestamp": int(time.time() * 1000), "transactionId": PING_ID}
            try:
                await self._ws.send(envelope(json.dumps(msg, separators=(",", ":")).encode(), T_JSON))
            except (ConnectionError, OSError):
                break
            if self._fws is not None and not self._fws.closed:
                try:
                    await self._fws.send(envelope(b"\x02", T_FILE))
                except (ConnectionError, OSError):
                    pass

    async def _read_loop(self, ws, channel):
        up = Unpacker()
        while True:
            m = await ws.recv()
            if m is None:
                break
            for kind, payload in up.feed(m):
                if kind == T_JSON:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except ValueError:
                        continue
                    self._on_json(msg, channel)
                elif kind == T_FILE and channel == "file_stream":
                    req = parse_file_request(payload)
                    if req is not None:
                        self._spawn(self._serve_window(*req))
        if channel == "instruction" and self.connected:
            await self._close("la M2 ha chiuso il collegamento")

    def _on_json(self, msg, channel):
        tid = msg.get("transactionId")
        if tid is None and isinstance(msg.get("data"), dict):
            tid = msg["data"].get("transactionId")
        if msg.get("type") == "response" and tid is not None:
            if tid == PING_ID:
                return
            fut = self._pending.get(tid)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        for name, fields in events_of(msg):
            self._on_event(name, fields)

    def _on_event(self, name, fields):
        if name.endswith("/filetransfer/finish"):
            ch = fields.get("channel")
            up = self._uploads.get(int(ch)) if isinstance(ch, (int, str)) and str(ch).isdigit() else None
            if up is not None and not up["done"].done():
                up["done"].set_result(int(fields.get("code", 0) or 0))
            return
        if name.endswith("/device/state"):
            self.mode = mode_of(fields) or self.mode
            tid = fields.get("taskId") or (fields.get("curMode") or {}).get("taskId")
            if tid:
                self.task_id = str(tid)
            self._emit("state", self.mode)
        elif name.endswith("/device/process"):
            self._emit("process", action_of(fields))
        elif "alarm" in name:
            self._emit("alarm", fields)
        for w in list(self._waiters):
            if not w[1].done() and w[0](name, fields):
                w[1].set_result(fields)

    async def _wait_event(self, test, timeout):
        fut = asyncio.get_running_loop().create_future()
        item = (test, fut)
        self._waiters.append(item)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._waiters.remove(item)

    async def _refresh(self):
        st = await self._request("/v1/project/running/status")
        mode = mode_of(st or {})
        try:
            lid = await self._request("/v1/project/peripheral/lid")
        except M2Error:
            lid = {}
        return mode, str((lid or {}).get("state") or "")

    async def _serve_window(self, channel, offset, size):
        up = self._uploads.get(channel)
        if up is None or self._fws is None:
            return
        data, end = up["data"], min(len(up["data"]), offset + size)
        pos = offset
        while pos < end:
            chunk = data[pos:min(end, pos + up["packet"])]
            await self._fws.send(envelope(file_data(channel, pos, chunk), T_FILE))
            pos += len(chunk)
            up["sent"] = max(up["sent"], pos)
            self._emit("upload", up["sent"] / max(1, len(data)))

    async def _upload(self, data, filename):
        ch = 50 + (len(self._uploads) % 150)
        md5 = hashlib.md5(data).hexdigest()
        loop = asyncio.get_running_loop()
        self._uploads[ch] = {"data": data, "packet": PACKET, "sent": 0, "done": loop.create_future()}
        try:
            r = await self._request("/v1/filetransfer/upload", "PUT", data={
                "filetype": 1, "filename": filename, "filesize": len(data), "digesttype": 1, "digestdata": md5,
                "channel": ch, "packetsize": PACKET})
            pk = (r or {}).get("packetsize")
            if isinstance(pk, int) and 0 < pk < PACKET:
                self._uploads[ch]["packet"] = pk
            code = await asyncio.wait_for(self._uploads[ch]["done"], max(30.0, len(data) / 200000.0))
        except asyncio.TimeoutError:
            raise M2Error("Il file del lavoro non è arrivato alla M2 (tempo scaduto).") from None
        finally:
            self._uploads.pop(ch, None)
        if code != 0:
            raise M2Error(f"La M2 ha scartato il file del lavoro (codice {code}).", code)
        return md5

    async def _send_job(self, data, laser_w, thickness, filename, smoke_fan):
        if not self.connected:
            raise M2Error("La M2 non è collegata.")
        if laser_w not in WORKHEAD:
            raise M2Error("Modulo laser non previsto.")
        head = await self._request("/v1/project/laser-head/info")
        self.head = head or {}
        check_head(self.head, laser_w)
        st = await self._request("/v1/project/running/status")
        mode = mode_of(st or {})
        if mode and not is_idle(mode):
            raise M2Error(f"La M2 è occupata ({mode}): aspetta che finisca o annulla il lavoro in corso.")
        try:
            await self._request("/v1/project/calibration/gyro", "POST")  # verso della testa, come xTool Studio
        except M2Error:
            pass
        await self._request("/v1/project/peripheral/lid")
        moved = self._spawn(self._wait_event(lambda n, f: n.endswith("/move/finish"), 30))
        try:
            await self._request("/v1/project/control/absolute-move", "POST",
                                data={"coor": {"x": 0, "y": 0, "z": 0}, "speed": 18000})
            await moved
        except (M2Error, asyncio.TimeoutError):
            moved.cancel()
        await self._upload(data, filename)
        task = str(uuid.uuid4())
        ready = self._spawn(self._wait_event(lambda n, f: n.endswith("/device/process") and action_of(f) == "ready"
                                             or n.endswith("/device/state") and mode_of(f).lower() in
                                             ("workready", "p_ready", "p_offline_ready_work"), 20))
        await self._request("/v1/project/process/parameter", "PUT", data={
            "taskID": task, "filetype": "TXT", "filename": filename, "mode": "MOTOR", "type": "PROCESS",
            "workhead": WORKHEAD[laser_w], "processMode": "PLANE", "thickness": round(thickness, 2),
            "smokeFanSpeed": smoke_fan})
        self.task_id = task
        try:
            await ready
        except asyncio.TimeoutError:
            raise M2Error("La M2 ha ricevuto il lavoro ma non si è messa in attesa del pulsante.") from None
        return task

    async def _cancel_tasks(self):
        tasks = [t for t in self._tasks if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _close(self, reason):
        was = self.connected
        self.connected = False
        for ws in (self._ws, self._fws):
            if ws is not None:
                ws.close()
        self._ws = self._fws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError(reason))
        self._pending.clear()
        if was:
            self._emit("closed", reason)


def _local_tz():
    try:
        tz = datetime.datetime.now().astimezone().tzinfo
        name = getattr(tz, "key", None) or str(tz or "")
        return name if "/" in name else "Europe/Rome"
    except (ValueError, OSError):
        return "Europe/Rome"
