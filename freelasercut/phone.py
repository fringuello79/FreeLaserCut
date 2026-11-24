# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Controllo dal telefono: una piccola pagina web servita da FreeLaserCut sulla rete di casa.

Dal telefono (stesso Wi-Fi del PC) si vede l'avanzamento del lavoro e la camera, si può mettere in pausa
o fermare il lavoro e inviare la foto del test materiale per la taratura. Dal telefono NON si può avviare né
riprendere un lavoro: per partire bisogna essere davanti alla macchina.
0.22.5: si può anche muovere la testa (frecce o joystick, laser sempre spento), solo se sul PC è permesso e la
macchina è ferma, senza lavori.

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

    def __init__(self, state, frame, pause, stop, photo, port=PORT, token=None, host="0.0.0.0", plate=None, move=None):
        self.state, self.frame, self.pause, self.stop_job, self.photo = state, frame, pause, stop, photo
        self.plate = plate  # 0.19.0: plate(bytes) → messaggio; la foto del piano di lavoro fatta con il telefono
        self.move = move  # 0.22.5: move(tipo, dati) → (ok, messaggio); tipo «passo», «joystick» o «ferma»
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


def _asset(name):
    """Logo di FreeLaserCut per la pagina del telefono (intestazione e icona della schermata Home)."""
    import os

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


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
            elif r in ("logo.svg", "logo.png"):
                data = _asset(r)
                if data:
                    self._send(200, data, "image/svg+xml" if r.endswith(".svg") else "image/png",
                               {"Cache-Control": "max-age=86400"})
                else:
                    self._send(404, "non trovato", "text/plain; charset=utf-8")
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
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:  # 0.22.5: lunghezza storta: niente letture senza fine
                self._send(400, {"ok": False, "msg": tr("Richiesta non valida")})
                return
            if r in ("pausa", "stop"):
                if n:
                    self.rfile.read(min(n, 4096))
                ok, msg = (srv.pause if r == "pausa" else srv.stop_job)()
                self._send(200, {"ok": bool(ok), "msg": msg})
            elif r in ("muovi", "joystick", "ferma-testa"):
                if srv.move is None:
                    self._send(404, {"ok": False, "msg": "non trovato"})
                    return
                if n > 1024:
                    self._send(413, {"ok": False, "msg": tr("Richiesta non valida")})
                    return
                try:
                    data = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
                    if not isinstance(data, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError, RecursionError):
                    self._send(400, {"ok": False, "msg": tr("Richiesta non valida")})
                    return
                kind = {"muovi": "passo", "joystick": "joystick", "ferma-testa": "ferma"}[r]
                ok, msg = srv.move(kind, data)
                self._send(200, {"ok": bool(ok), "msg": msg})
            elif r in ("foto-test", "foto-piano"):
                if r == "foto-piano" and srv.plate is None:
                    self._send(404, {"ok": False, "msg": "non trovato"})
                    return
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
                msg = srv.photo(data) if r == "foto-test" else srv.plate(data)
                self._send(200, {"ok": True, "msg": msg})
            else:
                self._send(404, {"ok": False, "msg": "non trovato"})

    return H


PAGE = r"""<!doctype html>
<html lang="{{LANG}}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#070C17">
<title>FreeLaserCut · [[telefono]]</title>
<link rel="icon" href="logo.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="logo.png">
<style>
:root{--bg:#070C17;--bg2:#0C1322;--card:rgba(20,29,48,.78);--hi:rgba(255,255,255,.06);--line:rgba(110,150,230,.18);
--tx:#E6EBF5;--mu:#8C98B0;--ac:#2E7CF6;--ac2:#5FA8FF;--glow:rgba(46,124,246,.45);--warn:#F5A524;--bad:#E5484D;--ok:#2FB171;
--key1:#1B2640;--key2:#111A2D;--keytx:#E6EBF5}
@media (prefers-color-scheme: light){:root{--bg:#E9EDF4;--bg2:#F4F6FA;--card:rgba(255,255,255,.86);--hi:rgba(255,255,255,.9);
--line:rgba(46,124,246,.18);--tx:#1A2233;--mu:#5C6880;--glow:rgba(46,124,246,.25);--key1:#FFFFFF;--key2:#E3E8F1;--keytx:#1A2233}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;color:var(--tx);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:14px 14px 30px;
min-height:100vh;background:radial-gradient(120% 60% at 50% -10%,rgba(46,124,246,.22),transparent 60%),
linear-gradient(rgba(110,150,230,.05) 1px,transparent 1px) 0 0/100% 28px,var(--bg)}
h1{font-size:18px;margin:2px 2px 12px;display:flex;justify-content:space-between;align-items:center;letter-spacing:.3px}
h1 .brand{display:flex;align-items:center;gap:10px}
h1 img{width:32px;height:32px;border-radius:9px;box-shadow:0 0 14px var(--glow)}
h1 small{font-weight:500;color:var(--mu);font-size:12px;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px;margin:0 0 12px;
box-shadow:inset 0 1px 0 var(--hi),0 10px 30px rgba(0,0,0,.28);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.ctitle{display:flex;justify-content:space-between;align-items:center;font-weight:700;margin-bottom:10px;
text-transform:uppercase;font-size:12px;letter-spacing:1.4px;color:var(--mu)}
.state{font-size:23px;font-weight:800;display:flex;align-items:center;gap:10px}
.led{width:11px;height:11px;border-radius:50%;background:var(--mu);box-shadow:0 0 0 3px rgba(140,152,176,.15)}
.led.run{background:var(--ok);box-shadow:0 0 12px var(--ok)}.led.hold{background:var(--warn);box-shadow:0 0 12px var(--warn)}
.led.bad{background:var(--bad);box-shadow:0 0 12px var(--bad)}.led.ready{background:var(--ac2);box-shadow:0 0 12px var(--ac)}
.mu{color:var(--mu);font-size:14px}
.bar{height:10px;border-radius:6px;background:rgba(110,150,230,.14);overflow:hidden;margin:12px 0 6px}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--ac),var(--ac2));box-shadow:0 0 12px var(--glow);
transition:width .4s}
.row{display:flex;gap:10px}.row button{flex:1}
button,.key{font:inherit;font-weight:700;border:0;border-radius:14px;padding:15px 10px;color:var(--keytx);min-height:54px;
background:linear-gradient(180deg,var(--key1),var(--key2));border:1px solid var(--line);
box-shadow:inset 0 1px 0 var(--hi),0 4px 0 rgba(0,0,0,.35),0 8px 18px rgba(0,0,0,.25);
transition:transform .06s,box-shadow .06s;touch-action:manipulation;user-select:none;-webkit-user-select:none}
button:active:not(:disabled),.key.on{transform:translateY(3px);box-shadow:inset 0 2px 6px rgba(0,0,0,.45),0 1px 0 rgba(0,0,0,.35)}
button:disabled{opacity:.35}
#pause{background:linear-gradient(180deg,#FFBE45,#E0901A);color:#1A0E05;border-color:#FFC45C}
#stop{background:linear-gradient(180deg,#F0646A,#C93338);color:#fff;border-color:#F07A7F}
.alarm{border-color:var(--bad)!important;box-shadow:0 0 0 1px var(--bad),0 0 24px rgba(229,72,77,.35)!important}
.live{font-size:12px;font-weight:800;color:var(--mu)}.live.on{color:var(--bad);text-shadow:0 0 8px var(--bad)}
#camwrap{position:relative;display:none}
#cam{width:100%;border-radius:12px;background:#000;display:block;box-shadow:0 0 0 1px var(--line)}
#camts{position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;padding:2px 7px;border-radius:6px}
#camwrap.full{position:fixed;inset:0;z-index:9;background:#000;display:flex;align-items:center;justify-content:center;border-radius:0}
#camwrap.full #cam{border-radius:0;max-height:100%;object-fit:contain}
#msg,#mvmsg{min-height:1.4em;margin-top:8px;font-size:14px}
label.file{display:block;text-align:center;border:1px dashed var(--line);border-radius:14px;padding:14px;cursor:pointer;font-weight:700;
background:linear-gradient(180deg,var(--key1),var(--key2));box-shadow:inset 0 1px 0 var(--hi)}
input[type=file]{display:none}
.seg{display:flex;background:rgba(110,150,230,.10);border-radius:12px;padding:4px;gap:4px;margin-bottom:12px}
.seg button{flex:1;min-height:38px;padding:8px;border-radius:9px;box-shadow:none;background:transparent;border-color:transparent;color:var(--mu)}
.seg button.on{background:linear-gradient(180deg,var(--ac2),var(--ac));color:#fff;box-shadow:0 0 14px var(--glow)}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;max-width:300px;margin:0 auto}
.pad button{min-height:70px;font-size:26px}
.pad .halt{color:var(--bad);font-size:22px}
.steps{display:flex;gap:6px;justify-content:center;margin:12px 0 2px}
.steps button{min-height:38px;padding:6px 10px;font-size:14px;border-radius:20px;flex:0 0 auto}
.steps button.on{background:linear-gradient(180deg,var(--ac2),var(--ac));color:#fff;box-shadow:0 0 12px var(--glow)}
#joy{position:relative;width:230px;height:230px;margin:6px auto 4px;border-radius:50%;touch-action:none;
background:radial-gradient(circle,rgba(46,124,246,.10) 0 30%,transparent 31%),
repeating-radial-gradient(circle,transparent 0 37px,rgba(110,150,230,.16) 38px 39px),linear-gradient(180deg,var(--key2),var(--key1));
border:1px solid var(--line);box-shadow:inset 0 6px 18px rgba(0,0,0,.45),0 0 0 6px rgba(110,150,230,.06)}
#knob{position:absolute;left:50%;top:50%;width:84px;height:84px;margin:-42px 0 0 -42px;border-radius:50%;
background:radial-gradient(circle at 35% 30%,var(--ac2),var(--ac) 60%,#1B4FA8);box-shadow:0 8px 18px rgba(0,0,0,.45),0 0 18px var(--glow),
inset 0 2px 0 rgba(255,255,255,.35)}
#pos{font-variant-numeric:tabular-nums;text-align:center;margin-top:8px}
.hide{display:none}
</style></head><body>
<h1><span class="brand"><img src="logo.svg" alt="">FreeLaserCut</span> <small>v{{VER}}</small></h1>
<div class="card" id="st">
  <div class="state"><span class="led" id="led"></span><span id="state">…</span></div>
  <div class="mu" id="sub"></div>
  <div class="bar"><i id="prog"></i></div>
  <div class="mu" id="pct"></div>
</div>
<div class="card">
  <div class="row"><button id="pause" disabled>[[Pausa]]</button><button id="stop" disabled>[[Stop]]</button></div>
  <div class="mu" style="margin-top:8px">[[Da qui puoi fermare il lavoro, non avviarlo: per partire o riprendere serve essere davanti alla macchina.]]</div>
  <div id="msg"></div>
</div>
<div class="card" id="mv">
  <div class="ctitle"><span>[[Muovi la testa]]</span><span class="mu" id="mvlaser">[[laser spento]]</span></div>
  <div class="seg"><button id="t_ar" class="on">[[Frecce]]</button><button id="t_joy">[[Joystick]]</button></div>
  <div id="arrows">
    <div class="pad">
      <span></span><button class="key" data-d="0,1">▲</button><span></span>
      <button class="key" data-d="-1,0">◀</button><button class="key halt" id="halt">■</button><button class="key" data-d="1,0">▶</button>
      <span></span><button class="key" data-d="0,-1">▼</button><span></span>
    </div>
    <div class="steps" id="steps"><button data-s="0.1">0,1</button><button data-s="1">1</button><button data-s="10" class="on">10</button><button data-s="50">50 mm</button></div>
  </div>
  <div id="joywrap" class="hide"><div id="joy"><div id="knob"></div></div></div>
  <div class="mu" id="pos"></div>
  <div id="mvmsg" class="mu"></div>
</div>
<div class="card">
  <div class="ctitle"><span>[[Controllo attività]]</span><span id="live" class="live">● LIVE</span></div>
  <div id="camwrap"><img id="cam" alt=""><div id="camts"></div></div>
  <div class="mu" id="camnote"></div>
  <div class="mu" id="firenote"></div>
  <div class="row" style="margin-top:8px"><button id="camb">[[Mostra la camera]]</button></div>
</div>
<div class="card">
  <label class="file" for="ph">📷 [[Invia la foto del test materiale]]</label>
  <input id="ph" type="file" accept="image/*" capture="environment">
  <div class="mu" style="margin-top:8px">[[Foto dall'alto, con tutto il test e i quattro quadratini agli angoli, luce uniforme e senza riflessi. Arriva nel Test materiale sul PC.]]</div>
  <div id="phmsg" class="mu"></div>
</div>
<div class="card">
  <label class="file" for="pl">📷 [[Foto del piano di lavoro]]</label>
  <input id="pl" type="file" accept="image/*" capture="environment">
  <div class="mu" style="margin-top:8px">[[Foto dall'alto, con tutta l'area di lavoro dentro. Sul PC indicherai i 4 angoli dell'area e la foto finirà sotto il piano, per posizionare i pezzi.]]</div>
  <div id="plmsg" class="mu"></div>
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
function buzz(){ try{ navigator.vibrate && navigator.vibrate(12); }catch(e){} }
async function tick(){
  try{
    const s = await (await fetch(base + 'stato', {cache:'no-store'})).json(); last = s;
    $('state').textContent = s.title || s.state || '—';
    $('sub').textContent = s.detail || '';
    $('firenote').textContent = s.job_active && s.fire === 'attiva' ? T.fireon : '';
    const p = s.total ? 100*s.done/s.total : 0;
    $('prog').style.width = p.toFixed(1)+'%';
    $('pct').textContent = s.job_active ? (p.toFixed(0)+' %  ·  '+T.elapsed+' '+fmt(s.elapsed)+(s.left!=null?'  ·  '+T.left+' '+fmt(s.left):'')) : '';
    $('pause').disabled = !(s.job_active && !s.paused);
    $('pause').textContent = s.paused ? T.paused : T.pause;
    $('stop').disabled = !s.job_active;
    $('st').classList.toggle('alarm', !!s.alarm);
    $('led').className = 'led ' + (s.alarm ? 'bad' : s.paused ? 'hold' : s.job_active ? 'run' : s.connected ? 'ready' : '');
    moveState(s);
  }catch(e){ $('state').textContent = T.offline; $('sub').textContent = T.offline2; $('led').className = 'led bad'; moveState(null); }
}
$('pause').onclick = async () => { buzz(); const r = await post('pausa'); $('msg').textContent = r.msg || ''; tick(); };
$('stop').onclick = async () => { buzz(); if(!confirm(T.confirm)) return; const r = await post('stop'); $('msg').textContent = r.msg || ''; tick(); };
// muovere la testa: frecce (un passo per tocco) o joystick (movimento continuo finché tieni premuto), laser spento
let step = 10, moveOk = false;
function moveState(s){
  moveOk = !!(s && s.move_ok);
  document.querySelectorAll('#mv .key').forEach(b => b.disabled = !moveOk);
  $('joy').style.opacity = moveOk ? 1 : .35;
  if(!moveOk && joyOn) joyEnd();
  $('pos').textContent = s && s.pos ? 'X ' + s.pos[0].toFixed(1) + '   Y ' + s.pos[1].toFixed(1) + ' mm' : '';
  if(!moveOk) $('mvmsg').textContent = (s && s.move_note) || T.offline;
  else if($('mvmsg').dataset.keep !== '1') $('mvmsg').textContent = '';
}
function say(r){ $('mvmsg').textContent = (r && r.msg) || ''; $('mvmsg').dataset.keep = r && !r.ok ? '1' : ''; }
document.querySelectorAll('#mv .key[data-d]').forEach(b => b.onclick = async () => {
  if(!moveOk) return; buzz(); const [dx,dy] = b.dataset.d.split(',').map(Number);
  say(await post('muovi', JSON.stringify({dx, dy, step}), 'application/json'));
});
$('halt').onclick = async () => { buzz(); say(await post('ferma-testa', '{}', 'application/json')); };
document.querySelectorAll('#steps button').forEach(b => b.onclick = () => {
  step = Number(b.dataset.s); document.querySelectorAll('#steps button').forEach(x => x.classList.toggle('on', x === b)); buzz(); });
function tab(joy){ $('t_ar').classList.toggle('on', !joy); $('t_joy').classList.toggle('on', joy);
  $('arrows').classList.toggle('hide', joy); $('joywrap').classList.toggle('hide', !joy); }
$('t_ar').onclick = () => { tab(false); if(joyOn) joyEnd(); };
$('t_joy').onclick = () => tab(true);
let joyOn = false, jx = 0, jy = 0, joyTimer = null;
function joySend(){ if(!joyOn) return; post('joystick', JSON.stringify({x: jx, y: jy}), 'application/json').then(r => { if(r && !r.ok) { say(r); joyEnd(); } }).catch(()=>{}); }
function joyAt(e){
  const r = $('joy').getBoundingClientRect(), R = r.width / 2 - 42;
  let x = (e.clientX - r.left - r.width/2) / R, y = (e.clientY - r.top - r.height/2) / R;
  const m = Math.hypot(x, y); if(m > 1){ x /= m; y /= m; }
  jx = +x.toFixed(3); jy = +(-y).toFixed(3);
  $('knob').style.transform = 'translate(' + (x*R) + 'px,' + (y*R) + 'px)';
}
function joyEnd(){
  if(!joyOn) return; joyOn = false; clearInterval(joyTimer); jx = jy = 0;
  $('knob').style.transform = ''; post('joystick', JSON.stringify({x: 0, y: 0}), 'application/json').catch(()=>{});
}
$('joy').addEventListener('pointerdown', e => { if(!moveOk) return; e.preventDefault(); $('joy').setPointerCapture(e.pointerId);
  joyOn = true; buzz(); joyAt(e); joySend(); clearInterval(joyTimer); joyTimer = setInterval(joySend, 150); });
$('joy').addEventListener('pointermove', e => { if(joyOn) joyAt(e); });
['pointerup','pointercancel','lostpointercapture'].forEach(n => $('joy').addEventListener(n, joyEnd));
document.addEventListener('visibilitychange', () => { if(document.hidden) joyEnd(); });
// controllo attività: la camera si accende da sola durante il lavoro (se il PC ha una camera), un tocco = schermo intero
let userCam = null, camLast = 0, camBusy = false;
function wantCam(){ return userCam !== null ? userCam : !!(last && last.job_active && last.camera); }
function camShow(on){ $('camwrap').style.display = on ? 'block' : 'none'; $('camb').textContent = on ? T.hidecam : T.showcam;
  $('live').classList.toggle('on', on); if(!on) $('camwrap').classList.remove('full'); }
function cam(){
  clearTimeout(camTimer);
  if(!wantCam()){ camShow(false); camTimer = setTimeout(cam, 1000); return; }
  if(last && !last.camera){ camShow(false); $('camnote').textContent = T.nocam; camTimer = setTimeout(cam, 2000); return; }
  if(camBusy){ camTimer = setTimeout(cam, 300); return; }
  camBusy = true; $('cam').src = base + 'foto.jpg?t=' + Date.now();
}
$('cam').onload = () => { camBusy = false; camLast = Date.now(); camShow(true); $('camnote').textContent = '';
  $('camts').textContent = new Date().toLocaleTimeString(); camTimer = setTimeout(cam, 700); };
$('cam').onerror = () => { camBusy = false; $('camnote').textContent = T.nocam; camShow(false); camTimer = setTimeout(cam, 2000); };
$('cam').onclick = () => $('camwrap').classList.toggle('full');
$('camb').onclick = () => { userCam = !wantCam(); cam(); };
setInterval(() => { if(wantCam() && camLast && Date.now() - camLast > 5000) $('camnote').textContent = T.stale; }, 1000);
async function shrink(file){
  try{
    const bmp = await createImageBitmap(file); const k = Math.min(1, 2400/Math.max(bmp.width,bmp.height));
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width*k); c.height = Math.round(bmp.height*k);
    c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);
    return await new Promise(r => c.toBlob(r,'image/jpeg',0.92));
  }catch(e){ return file; }
}
function sender(input, where, out){
  $(input).onchange = async e => {
    const f = e.target.files[0]; if(!f) return;
    $(out).textContent = T.sending;
    try{ const b = await shrink(f); const r = await post(where, b, 'image/jpeg'); $(out).textContent = r.msg || T.sent; }
    catch(err){ $(out).textContent = T.failed + err; }
    e.target.value = '';
  };
}
sender('ph', 'foto-test', 'phmsg'); sender('pl', 'foto-piano', 'plmsg');
tick(); setInterval(tick, 1000); cam();
</script></body></html>
"""


def _js_strings():
    return {"elapsed": tr("trascorso"), "left": tr("mancano circa"), "paused": tr("In pausa"), "pause": tr("Pausa"),
            "offline": tr("PC non raggiungibile"),
            "offline2": tr("FreeLaserCut è chiuso o il controllo dal telefono è spento."),
            "confirm": tr("Fermare il lavoro? Non si potrà riprendere da qui."), "nocam": tr("Nessuna camera sul PC"),
            "stale": tr("La camera non manda immagini nuove da qualche secondo."),
            "fireon": tr("Guardia fiamme attiva: la camera sorveglia il lavoro."),
            "hidecam": tr("Nascondi la camera"), "showcam": tr("Mostra la camera"), "sending": tr("Invio in corso…"),
            "sent": tr("Inviata."), "failed": tr("Invio non riuscito:")}


def _html_strings():
    """Testi fissi della pagina (qui scritti per intero così finiscono nelle traduzioni)."""
    return {"telefono": tr("telefono"), "Pausa": tr("Pausa"), "Stop": tr("Stop"),
            "Mostra la camera": tr("Mostra la camera"), "Controllo attività": tr("Controllo attività"),
            "Muovi la testa": tr("Muovi la testa"), "laser spento": tr("laser spento"), "Frecce": tr("Frecce"),
            "Joystick": tr("Joystick"),
            "Invia la foto del test materiale": tr("Invia la foto del test materiale"),
            "Foto del piano di lavoro": tr("Foto del piano di lavoro"),
            "Foto dall'alto, con tutta l'area di lavoro dentro. Sul PC indicherai i 4 angoli dell'area e la foto "
            "finirà sotto il piano, per posizionare i pezzi.":
                tr("Foto dall'alto, con tutta l'area di lavoro dentro. Sul PC indicherai i 4 angoli dell'area e la foto "
                   "finirà sotto il piano, per posizionare i pezzi."),
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
