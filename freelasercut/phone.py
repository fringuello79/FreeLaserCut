# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Controllo dal telefono: una piccola pagina web servita da FreeLaserCut sulla rete di casa.

Dal telefono (stesso Wi-Fi del PC) si vede l'avanzamento del lavoro e la camera, si può mettere in pausa
o fermare il lavoro e inviare la foto del test materiale per la taratura. Dal telefono NON si può avviare né
riprendere un lavoro: per partire bisogna essere davanti alla macchina.

Sicurezza: è spento di partenza e si accende solo per la sessione in corso; l'indirizzo contiene un codice
casuale (chi non ce l'ha riceve «non trovato»); risponde solo a indirizzi della rete locale; i comandi
richiedono un'intestazione che una pagina di un altro sito non può aggiungere. Niente esce dalla rete di casa.
Nessuna parte di questo modulo usa Qt: le funzioni passate dall'interfaccia vengono chiamate dal thread del server.
"""
import ipaddress
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .i18n import language, tr

PORT = 8766
MAX_PHOTO = 25 * 1024 * 1024
HEADER = "X-FLC"


def new_token():
    return secrets.token_urlsafe(9)


def local_ips():
    """Indirizzi IPv4 della rete locale di questo PC, il più probabile per primo."""
    ips = []
    try:  # nessun pacchetto parte: serve solo a sapere quale scheda di rete userebbe il PC
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    good = [ip for ip in ips if _is_local(ip) and not ip.startswith("127.")]
    return good or ["127.0.0.1"]


def _is_local(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local


class PhoneServer:
    """state() → dict; frame() → bytes JPEG o None; pause(), stop() → (ok, messaggio); photo(bytes) → messaggio."""

    def __init__(self, state, frame, pause, stop, photo, port=PORT, token=None, host="0.0.0.0"):
        self.state, self.frame, self.pause, self.stop_job, self.photo = state, frame, pause, stop, photo
        self.token = token or new_token()
        self.want_port = port
        self.host = host
        self.httpd = None
        self.thread = None
        self.last_seen = {}  # ip → ora dell'ultima richiesta valida

    @property
    def running(self):
        return self.httpd is not None

    @property
    def port(self):
        return self.httpd.server_address[1] if self.httpd else None

    def urls(self):
        return [f"http://{ip}:{self.port}/{self.token}/" for ip in local_ips()] if self.httpd else []

    def start(self):
        if self.httpd:
            return self.port
        handler = _make_handler(self)
        err = None
        for p in range(self.want_port, self.want_port + 20):
            try:
                self.httpd = ThreadingHTTPServer((self.host, p), handler)
                break
            except OSError as ex:
                err = ex
        if not self.httpd:
            raise OSError(f"nessuna porta libera tra {self.want_port} e {self.want_port + 19}: {err}")
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True,
                                       name="flc-telefono")
        self.thread.start()
        return self.port

    def close(self):
        h, self.httpd = self.httpd, None
        if h:
            h.shutdown()
            h.server_close()

    def new_token(self):
        self.token = new_token()
        return self.token


def _make_handler(srv):
    import time

    class H(BaseHTTPRequestHandler):
        server_version = "FreeLaserCut"
        sys_version = ""

        def log_message(self, *a):  # niente sul terminale
            pass

        def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _route(self):
            if not _is_local(self.client_address[0]):
                self._send(403, {"ok": False, "msg": "solo dalla rete locale"})
                return None
            parts = self.path.split("?", 1)[0].strip("/").split("/")
            if not parts or not secrets.compare_digest(parts[0], srv.token):
                self._send(404, "non trovato", "text/plain; charset=utf-8")
                return None
            srv.last_seen[self.client_address[0]] = time.time()
            return "/".join(parts[1:])

        def do_GET(self):
            r = self._route()
            if r is None:
                return
            if r == "":
                self._send(200, render_page(), "text/html; charset=utf-8",
                           {"Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; "
                                                       "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                                       "connect-src 'self'"})
            elif r == "stato":
                try:
                    self._send(200, dict(srv.state() or {}))
                except Exception as ex:  # noqa: BLE001
                    self._send(500, {"ok": False, "msg": str(ex)})
            elif r == "foto.jpg":
                data = srv.frame() if srv.frame else None
                if data:
                    self._send(200, data, "image/jpeg")
                else:
                    self._send(404, "nessuna camera", "text/plain; charset=utf-8")
            else:
                self._send(404, "non trovato", "text/plain; charset=utf-8")

        def do_POST(self):
            r = self._route()
            if r is None:
                return
            if self.headers.get(HEADER) != "1":
                self._send(403, {"ok": False, "msg": "richiesta non valida"})
                return
            n = int(self.headers.get("Content-Length") or 0)
            if r in ("pausa", "stop"):
                if n:
                    self.rfile.read(min(n, 4096))
                ok, msg = (srv.pause if r == "pausa" else srv.stop_job)()
                self._send(200, {"ok": bool(ok), "msg": msg})
            elif r == "foto-test":
                if n <= 0 or n > MAX_PHOTO:
                    self._send(413, {"ok": False, "msg": "foto troppo grande o vuota"})
                    return
                data = b""
                while len(data) < n:
                    chunk = self.rfile.read(min(1 << 16, n - len(data)))
                    if not chunk:
                        break
                    data += chunk
                if len(data) != n:
                    self._send(400, {"ok": False, "msg": "foto incompleta"})
                    return
                msg = srv.photo(data)
                self._send(200, {"ok": True, "msg": msg})
            else:
                self._send(404, {"ok": False, "msg": "non trovato"})

    return H


PAGE = r"""<!doctype html>
<html lang="{{LANG}}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0C1322">
<title>FreeLaserCut · [[telefono]]</title>
<style>
:root{--bg:#0C1322;--card:#141D30;--line:#24304A;--tx:#E6EBF5;--mu:#8C98B0;--ac:#2E7CF6;--warn:#F5A524;--bad:#E5484D;--ok:#2FB171}
@media (prefers-color-scheme: light){:root{--bg:#F2F4F8;--card:#FFFFFF;--line:#D8DEE9;--tx:#1A2233;--mu:#5C6880}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:14px 16px 28px}
h1{font-size:18px;margin:0 0 10px;display:flex;justify-content:space-between;align-items:center}
h1 small{font-weight:400;color:var(--mu);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:0 0 12px}
.state{font-size:22px;font-weight:700}.mu{color:var(--mu);font-size:14px}
.bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden;margin:10px 0 6px}
.bar i{display:block;height:100%;width:0;background:var(--ac);transition:width .4s}
.row{display:flex;gap:10px}.row button{flex:1}
button{font:inherit;font-weight:700;border:0;border-radius:12px;padding:16px 10px;color:#fff;background:var(--ac);min-height:56px}
button:disabled{opacity:.35}
#pause{background:var(--warn);color:#1A0E05}#stop{background:var(--bad)}
#cam{width:100%;border-radius:10px;display:none;background:#000;margin-top:8px}
.alarm{background:#3A1418;border-color:var(--bad);color:#FFD7DA}
#msg{min-height:1.4em;margin-top:8px;font-size:14px}
label.file{display:block;text-align:center;border:1px dashed var(--line);border-radius:12px;padding:14px;cursor:pointer;font-weight:700}
input[type=file]{display:none}
</style></head><body>
<h1>FreeLaserCut <small>v{{VER}}</small></h1>
<div class="card" id="st">
  <div class="state" id="state">…</div>
  <div class="mu" id="sub"></div>
  <div class="bar"><i id="prog"></i></div>
  <div class="mu" id="pct"></div>
</div>
<div class="card">
  <div class="row"><button id="pause" disabled>[[Pausa]]</button><button id="stop" disabled>[[Stop]]</button></div>
  <div class="mu" style="margin-top:8px">[[Da qui puoi fermare il lavoro, non avviarlo: per partire o riprendere serve essere davanti alla macchina.]]</div>
  <div id="msg"></div>
</div>
<div class="card">
  <div class="row"><button id="camb" style="background:var(--line);color:var(--tx)">[[Mostra la camera]]</button></div>
  <img id="cam" alt="">
</div>
<div class="card">
  <label class="file" for="ph">📷 [[Invia la foto del test materiale]]</label>
  <input id="ph" type="file" accept="image/*" capture="environment">
  <div class="mu" style="margin-top:8px">[[Foto dall'alto, con tutto il test e i quattro quadratini agli angoli, luce uniforme e senza riflessi. Arriva nel Test materiale sul PC.]]</div>
  <div id="phmsg" class="mu"></div>
</div>
<script>
const T = {{T}};
const base = location.pathname.endsWith('/') ? location.pathname : location.pathname + '/';
const $ = id => document.getElementById(id);
let camOn = false, camTimer = null, last = null;
function fmt(s){s=Math.max(0,Math.round(s||0));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')}
async function post(what, body, type){
  const r = await fetch(base + what, {method:'POST', headers:{'X-FLC':'1','Content-Type':type||'text/plain'}, body: body||''});
  return r.json();
}
async function tick(){
  try{
    const s = await (await fetch(base + 'stato', {cache:'no-store'})).json(); last = s;
    $('state').textContent = s.title || s.state || '—';
    $('sub').textContent = s.detail || '';
    const p = s.total ? 100*s.done/s.total : 0;
    $('prog').style.width = p.toFixed(1)+'%';
    $('pct').textContent = s.job_active ? (p.toFixed(0)+' %  ·  '+T.elapsed+' '+fmt(s.elapsed)+(s.left!=null?'  ·  '+T.left+' '+fmt(s.left):'')) : '';
    $('pause').disabled = !(s.job_active && !s.paused);
    $('pause').textContent = s.paused ? T.paused : T.pause;
    $('stop').disabled = !s.job_active;
    $('st').classList.toggle('alarm', !!s.alarm);
  }catch(e){ $('state').textContent = T.offline; $('sub').textContent = T.offline2; }
}
$('pause').onclick = async () => { const r = await post('pausa'); $('msg').textContent = r.msg || ''; tick(); };
$('stop').onclick = async () => { if(!confirm(T.confirm)) return; const r = await post('stop'); $('msg').textContent = r.msg || ''; tick(); };
function cam(){ $('cam').src = base + 'foto.jpg?t=' + Date.now(); }
$('cam').onerror = () => { if(camOn){ $('cam').style.display='none'; $('camb').textContent=T.nocam; } };
$('cam').onload = () => { if(camOn){ $('cam').style.display='block'; camTimer = setTimeout(cam, 1000); } };
$('camb').onclick = () => { camOn = !camOn; clearTimeout(camTimer); $('camb').textContent = camOn ? T.hidecam : T.showcam; if(camOn) cam(); else $('cam').style.display='none'; };
async function shrink(file){
  try{
    const bmp = await createImageBitmap(file); const k = Math.min(1, 2400/Math.max(bmp.width,bmp.height));
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width*k); c.height = Math.round(bmp.height*k);
    c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);
    return await new Promise(r => c.toBlob(r,'image/jpeg',0.92));
  }catch(e){ return file; }
}
$('ph').onchange = async e => {
  const f = e.target.files[0]; if(!f) return;
  $('phmsg').textContent = T.sending;
  try{ const b = await shrink(f); const r = await post('foto-test', b, 'image/jpeg'); $('phmsg').textContent = r.msg || T.sent; }
  catch(err){ $('phmsg').textContent = T.failed + err; }
  e.target.value = '';
};
tick(); setInterval(tick, 1000);
</script></body></html>
"""


def _js_strings():
    return {"elapsed": tr("trascorso"), "left": tr("mancano circa"), "paused": tr("In pausa"), "pause": tr("Pausa"),
            "offline": tr("PC non raggiungibile"),
            "offline2": tr("FreeLaserCut è chiuso o il controllo dal telefono è spento."),
            "confirm": tr("Fermare il lavoro? Non si potrà riprendere da qui."), "nocam": tr("Nessuna camera sul PC"),
            "hidecam": tr("Nascondi la camera"), "showcam": tr("Mostra la camera"), "sending": tr("Invio in corso…"),
            "sent": tr("Inviata."), "failed": tr("Invio non riuscito:")}


def _html_strings():
    """Testi fissi della pagina (qui scritti per intero così finiscono nelle traduzioni)."""
    return {"telefono": tr("telefono"), "Pausa": tr("Pausa"), "Stop": tr("Stop"),
            "Mostra la camera": tr("Mostra la camera"),
            "Invia la foto del test materiale": tr("Invia la foto del test materiale"),
            "Da qui puoi fermare il lavoro, non avviarlo: per partire o riprendere serve essere davanti alla macchina.":
                tr("Da qui puoi fermare il lavoro, non avviarlo: per partire o riprendere serve essere davanti alla macchina."),
            "Foto dall'alto, con tutto il test e i quattro quadratini agli angoli, luce uniforme e senza riflessi. "
            "Arriva nel Test materiale sul PC.":
                tr("Foto dall'alto, con tutto il test e i quattro quadratini agli angoli, luce uniforme e senza "
                   "riflessi. Arriva nel Test materiale sul PC.")}


def render_page():
    import html
    import re

    h = _html_strings()
    page = re.sub(r"\[\[(.+?)\]\]", lambda m: html.escape(h.get(m.group(1), m.group(1)), quote=True), PAGE)
    js = json.dumps(_js_strings(), ensure_ascii=False).replace("</", "<\\/")
    return page.replace("{{VER}}", __version__).replace("{{T}}", js).replace("{{LANG}}", language())
