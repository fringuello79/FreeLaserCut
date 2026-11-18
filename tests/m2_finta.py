# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""M2 finta per le prove del collegamento (core/xtool_m2_link.py): risponde come la xTool M2 vista con la M2
virtuale (freeburn/xtool-m2-virtuale.md), su 127.0.0.1 e su una porta libera. Solo per le prove: non comanda niente.

Opzioni per mettere alla prova il collegamento: abbinamento con il pulsante (406 finché non si «preme»), finestre
del file senza CRC (come fa la macchina vera secondo la comunità), notifiche come lista o come oggetto, file rovinato
(MD5 sbagliato), macchina occupata, testa diversa.
"""
import asyncio
import base64
import hashlib
import json
import os
import ssl
import struct
import subprocess
import tempfile
import threading
import urllib.parse

from freelasercut.core.xtool_m2_link import T_FILE, T_JSON, Unpacker, crc16, envelope  # noqa: F401

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def make_cert(folder):
    cert, key = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
    if not os.path.exists(cert):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                        "-days", "2", "-subj", "/CN=m2-finta"], check=True, capture_output=True)
    return cert, key


class _WS:
    def __init__(self, r, w):
        self.r, self.w, self.closed = r, w, False

    async def send(self, data, op=2):
        if self.closed:
            return
        n = len(data)
        head = bytes([0x80 | op, n]) if n < 126 else (bytes([0x80 | op, 126]) + struct.pack(">H", n) if n < 65536
                                                      else bytes([0x80 | op, 127]) + struct.pack(">Q", n))
        try:
            self.w.write(head + data)
            await self.w.drain()
        except (ConnectionError, OSError):
            self.closed = True

    async def recv(self):
        parts = []
        while True:
            try:
                h = await self.r.readexactly(2)
                n = h[1] & 0x7F
                if n == 126:
                    n = struct.unpack(">H", await self.r.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", await self.r.readexactly(8))[0]
                k = await self.r.readexactly(4) if h[1] & 0x80 else None
                d = bytearray(await self.r.readexactly(n))
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                return None
            if k:
                for i in range(n):
                    d[i] ^= k[i % 4]
            if (h[0] & 0x0F) == 8:
                return None
            parts.append(bytes(d))
            if h[0] & 0x80:
                return b"".join(parts)


class M2Finta:
    def __init__(self, head="LASER_BLUE_10W", maker="TO", pairing=False, crc_on_request=True, list_events=True,
                 corrupt=False, busy=False, direction="vertical", token="gettone-finto-123", auto_start=False,
                 job_seconds=0.3):
        self.head, self.maker, self.pairing = head, maker, pairing
        self.crc_on_request, self.list_events, self.corrupt, self.busy = crc_on_request, list_events, corrupt, busy
        self.direction, self.token, self.auto_start, self.job_seconds = direction, token, auto_start, job_seconds
        self.pressed = False
        self.requests = []  # (url, method, params, data, ha sessionToken)
        self.files = []  # (nome, byte, md5 ok)
        self.params = None
        self.mode = "Idle"
        self.task = ""
        self.instr, self.files_ws = [], {}
        self.transfers = {}
        self.loop = None
        self.port = None
        self._tasks = set()
        self.closed_by_peer = False

    # --- avvio in un filo ----------------------------------------------------------------------
    def start(self):
        folder = os.path.join(tempfile.gettempdir(), "flc-m2-finta")
        os.makedirs(folder, exist_ok=True)
        cert, key = make_cert(folder)
        ready = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            srv = self.loop.run_until_complete(asyncio.start_server(self.conn, "127.0.0.1", 0, ssl=ctx,
                                                                    limit=2 ** 24))
            self.port = srv.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(10)
        return self

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def run(self, coro, timeout=10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def press(self):
        """Il pulsante della macchina."""
        return self.run(self._press())

    def spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # --- protocollo ---------------------------------------------------------------------------
    async def send_json(self, ws, obj):
        await ws.send(envelope(json.dumps(obj).encode(), T_JSON))

    async def notify(self, url, data):
        ev = dict(data)
        ev["name"] = url
        payload = [ev] if self.list_events else data
        for ws in list(self.instr):
            await self.send_json(ws, {"type": "request", "method": "NOTIFY", "url": url, "data": payload})

    async def set_mode(self, mode):
        self.mode = mode
        await self.notify("/v1/platform/device/state", {"mode": mode, "taskId": self.task})

    async def process(self, action):
        await self.notify("/v1/platform/device/process", {"content": {"action": action, "taskId": self.task}})

    async def _press(self):
        if self.pairing and not self.pressed:
            self.pressed = True
            return
        if self.mode == "WorkReady":
            self.spawn(self.job())
        elif self.mode == "WorkPlay":
            await self.set_mode("WorkPause")
            await self.process("pause")
        elif self.mode == "WorkPause":
            await self.set_mode("WorkPlay")
            await self.process("resume")

    async def job(self):
        await self.set_mode("WorkPlay")
        await self.process("start")
        t = 0.0
        while t < self.job_seconds:
            await asyncio.sleep(0.05)
            if self.mode == "Idle":  # annullato
                return
            if self.mode != "WorkPause":
                t += 0.05
        await self.process("finish")
        await self.set_mode("finish")
        await self.set_mode("Idle")

    def answer(self, url, method, params, data, has_session):
        if url == "/v1/user/parity":
            if self.pairing and data.get("token") != self.token:
                return 406, {}
            return 0, {"token": self.token if self.pairing else "", "sessionToken": "sessione-finta"}
        if url == "/v1/user/auth-status":
            if self.pairing and not self.pressed:
                return 406, {}
            return 0, {"token": self.token, "sessionToken": "sessione-finta"}
        if url == "/v1/platform/device/machine-info":
            return 0, {"deviceCode": "JS002", "sn": "FINTA0001", "firmware": {"version": "V40.141.099"}}
        if url == "/v1/project/laser-head/info":
            return 0, {"type": self.head, "manufacture": self.maker, "direction": self.direction}
        if url == "/v1/project/running/status":
            return 0, {"state": "WorkPlay" if self.busy else self.mode, "motion_status": 0, "homing_status": 0}
        if url == "/v1/platform/device/state/sync":
            return 0, {"curMode": {"mode": self.mode, "taskId": self.task}}
        if url == "/v1/project/peripheral/lid":
            return 0, {"state": "on"}
        return 0, {}

    async def on_instr(self, ws, msg):
        url, method = msg.get("url", ""), msg.get("method", "")
        params, data, tid = msg.get("params") or {}, msg.get("data") or {}, msg.get("transactionId")
        if url != "/v1/user/ping":
            self.requests.append((url, method, params, data, bool(msg.get("sessionToken"))))
        if tid is None:
            return
        code, risp = self.answer(url, method, params, data, bool(msg.get("sessionToken")))
        if url == "/v1/filetransfer/upload":
            ch = int(data["channel"])
            self.transfers[ch] = {"name": data["filename"], "size": int(data["filesize"]), "md5": data["digestdata"],
                                  "buf": bytearray(int(data["filesize"])), "got": 0, "end": 0}
            risp = {"packetsize": int(data.get("packetsize") or 65536)}
        await self.send_json(ws, {"type": "response", "code": code, "transactionId": tid, "data": risp, "msg": "ok"})
        if url == "/v1/filetransfer/upload":
            self.spawn(self.ask_window(int(data["channel"])))
        elif url == "/v1/project/process/parameter":
            self.params = dict(data)
            self.task = str(data.get("taskID") or "")
            await self.set_mode("WorkReady")
            await self.process("ready")
            if self.auto_start:
                self.spawn(self._press())
        elif url == "/v1/project/device/control":
            a = str(params.get("action", "")).upper()
            if a == "START" and self.mode == "WorkReady":
                self.spawn(self.job())
            elif a == "PAUSE" and self.mode == "WorkPlay":
                await self.set_mode("WorkPause")
                await self.process("pause")
            elif a == "RESUME" and self.mode == "WorkPause":
                await self.set_mode("WorkPlay")
                await self.process("resume")
            elif a == "CANCEL":
                await self.process("cancel")
                await self.set_mode("Idle")
        elif url == "/v1/project/control/absolute-move":
            await self.notify("/v1/project/device/move/finish", {"info": {"code": 0}})

    async def ask_window(self, ch):
        t = self.transfers[ch]
        for _ in range(100):
            ws = next(iter(self.files_ws.values()), None)
            if ws:
                break
            await asyncio.sleep(0.05)
        size = min(5 * 1024 * 1024, t["size"] - t["got"])
        t["end"] = t["got"] + size
        pkt = bytes([1, ch]) + t["got"].to_bytes(5, "big") + size.to_bytes(3, "big")
        await ws.send(envelope(pkt, T_FILE, with_crc=self.crc_on_request))

    async def on_file(self, ws, kind, payload):
        if kind == T_FILE and payload == b"\x02":
            await ws.send(envelope(b"\x82", T_FILE))
            return
        if kind == T_FILE and payload[:1] == bytes([129]):
            ch, off, chunk = payload[1], int.from_bytes(payload[2:7], "big"), payload[7:]
            t = self.transfers.get(ch)
            if t is None:
                return
            t["buf"][off:off + len(chunk)] = chunk
            t["got"] = max(t["got"], off + len(chunk))
            if t["got"] >= t["size"]:
                ok = hashlib.md5(bytes(t["buf"])).hexdigest() == t["md5"] and not self.corrupt
                self.files.append((t["name"], bytes(t["buf"]), ok))
                del self.transfers[ch]
                await ws.send(envelope(json.dumps({"type": "request", "method": "NOTIFY",
                                                   "url": "/v1/filetransfer/finish",
                                                   "data": {"code": 0 if ok else -1, "channel": ch}}).encode(),
                                       T_JSON))
            elif t["got"] >= t["end"]:
                await self.ask_window(ch)

    async def conn(self, r, w):
        head = await r.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        path = lines[0].split(" ")[1]
        key = [x.split(":", 1)[1].strip() for x in lines[1:] if x.lower().startswith("sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        w.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
        await w.drain()
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        fn, sess = q.get("function", ["instruction"])[0], q.get("id", ["?"])[0]
        ws = _WS(r, w)
        if fn == "instruction":
            self.instr.append(ws)
        else:
            self.files_ws[sess] = ws
        up = Unpacker()
        try:
            while True:
                m = await ws.recv()
                if m is None:
                    break
                for kind, payload in up.feed(m):
                    if fn == "instruction" and kind == T_JSON:
                        self.spawn(self.on_instr(ws, json.loads(payload)))
                    elif fn != "instruction":
                        await self.on_file(ws, kind, payload)
        finally:
            ws.closed = True
            if ws in self.instr:
                self.instr.remove(ws)
            w.close()

    def drop_all(self):
        """La macchina chiude il collegamento (spenta, Wi-Fi perso)."""
        async def go():
            for ws in list(self.instr) + list(self.files_ws.values()):
                ws.w.close()
        self.run(go())
