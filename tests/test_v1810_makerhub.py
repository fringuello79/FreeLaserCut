# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.10: MakerHub dentro FreeLaserCut (funzione in prova, dietro il codice amministratore).

MakerHub è un servizio esterno (maker-hub.it). Qui si prova il lato di FreeLaserCut contro un MakerHub FINTO, in
ascolto su questo computer: nessuna chiamata esce davvero.

Casi provati:
1 indirizzi: solo https e solo maker-hub.it (niente sosia, niente utente@, niente http);
2 elenco dei generatori: voci «in prova» nascoste, indirizzi sbagliati scartati, testi ripuliti;
3 controlli su un lavoro: protocollo, formato, vuoto, troppo grande, nome del file, avvio del laser, script,
  immagini, riferimenti esterni, unità;
4 rete: codice giusto, sbagliato, troppi tentativi, server spento; niente nome del computer né del progetto;
5 dal lavoro alle forme: misure vere, livelli liberi, valori di partenza (anche assurdi o mancanti), kerf già
  compensato, colori non dichiarati, nessun livello dichiarato, DXF, disegno rovinato; il progetto non cambia
  finché non si conferma;
6 finestra: nascosto senza codice e nessuna chiamata di rete; menu, ricerca del Banco, browser; elenco aggiornato
  solo a richiesta; collegamento; arrivo di un disegno con conferma, rifiuto, lavoro non valido, lavoro rimandato,
  macchina dichiarata solo a richiesta, annulla; collegamento scaduto; scollega; di nuovo nascosto; rapporto per
  l'assistenza senza il token; traduzioni.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)  # il MakerHub finto è su questo computer: mai passare da un proxy
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
asked, told = [], []
answer = [QMessageBox.Yes]


def _question(*a, **k):
    asked.append(a[2] if len(a) > 2 else "")
    return answer[0]


def _tell(*a, **k):
    told.append(a[2] if len(a) > 2 else "")
    return QMessageBox.Ok


QMessageBox.question = staticmethod(_question)
QMessageBox.information = staticmethod(_tell)
QMessageBox.warning = staticmethod(_tell)

from freelasercut import __version__, admin  # noqa: E402
from freelasercut import makerhub as mh  # noqa: E402
from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# ================================================================== il MakerHub finto
class Fake:
    def __init__(self):
        self.requests = []  # (metodo, percorso, corpo)
        self.queue = []  # lavori da consegnare
        self.results = []  # esiti ricevuti
        self.tokens = {"tok-buono-1234567890"}
        self.tools = {"protocollo": 1, "servizio": "MakerHub", "strumenti": []}
        self.lock = threading.Lock()
        self.new = threading.Event()

    def count(self, path=None):
        with self.lock:
            return sum(1 for _m, p, _b in self.requests if path is None or p == path)

    def last(self, path):
        with self.lock:
            return [b for _m, p, b in self.requests if p == path][-1]


fake = Fake()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with fake.lock:
            fake.requests.append(("GET", self.path, None))
        if self.path == "/ponte/flc/strumenti":
            return self._send(200, fake.tools)
        self._send(404, {"errore": "non trovato"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw.decode("utf-8"))
        with fake.lock:
            fake.requests.append(("POST", self.path, body))
            fake.agent = self.headers.get("User-Agent")
        if self.path == "/ponte/abbina":
            if body.get("codice") == "AB3K9Q":
                return self._send(200, {"ok": True, "token": "tok-buono-1234567890"})
            if body.get("codice") == "TROPPI":
                return self._send(429, {"errore": "troppi tentativi"})
            return self._send(403, {"errore": "codice sbagliato"})
        if body.get("token") not in fake.tokens:
            return self._send(401, {"errore": "token non valido"})
        if self.path == "/ponte/attesa":
            end = time.time() + 0.25  # il vero MakerHub aspetta fino a 25 secondi: qui un quarto di secondo
            while time.time() < end:
                with fake.lock:
                    if fake.queue:
                        return self._send(200, {"ok": True, "comandi": [fake.queue.pop(0)]})
                fake.new.wait(0.02)
                fake.new.clear()
            return self._send(200, {"ok": True, "comandi": []})
        if self.path == "/ponte/esito":
            with fake.lock:
                fake.results.append(body)
            return self._send(200, {"ok": True})
        self._send(404, {"errore": "non trovato"})


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
REAL_SERVER = mh.SERVER
mh.SERVER = f"http://127.0.0.1:{httpd.server_address[1]}/ponte"

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="70mm" viewBox="0 0 100 70">'
       '<rect x="0" y="0" width="100" height="70" fill="none" stroke="#FF0000"/>'
       '<circle cx="50" cy="35" r="10" fill="#000000"/></svg>')


def job_op(**over):
    op = {"op": "lavoro", "protocollo": 1, "titolo": "Scatola 100x70x50", "file": "scatola_100x70x50.svg",
          "formato": "svg", "unita": "mm", "dati": SVG, "materiale": "Compensato di pioppo", "spessore_mm": 3.0,
          "kerf_compensato_mm": 0.15,
          "livelli": [{"colore": "#FF0000", "lavoro": "taglio", "potenza_pct": 80, "velocita_mm_min": 300, "passate": 2},
                      {"colore": "#000000", "lavoro": "incisione", "potenza_pct": None, "velocita_mm_min": None,
                       "passate": None}],
          "origine": "MakerHub", "note": ["Il kerf è già compensato: non applicare un'altra compensazione."],
          "avvia_il_laser": False}
    op.update(over)
    return op


def push(jid, title="Scatola 100×70×50", **over):
    with fake.lock:
        fake.queue.append({"id": jid, "titolo": title, "operazioni": [job_op(**over)]})
    fake.new.set()


def leaf_layers(shapes):
    return sorted({leaf.layer for s in shapes for leaf, _ in s.leaves()})


# ================================================================== 1. indirizzi
check("indirizzi: https di maker-hub.it e dei suoi sottodomini",
      mh.safe_url("https://app.maker-hub.it/?pagina=laser&scheda=scatola&da=freelasercut")
      and mh.safe_url("https://maker-hub.it/") and mh.safe_url(mh.SITE) and mh.safe_url(REAL_SERVER))
check("…mai http, mai un altro sito, mai un sosia, mai utente@",
      not any(mh.safe_url(u) for u in (
          "http://app.maker-hub.it/", "https://example.com/", "https://maker-hub.it.example.com/",
          "https://finto-maker-hub.it/", "https://maker-hub.it@example.com/", "https://utente:x@maker-hub.it/",
          "javascript:alert(1)", "file:///C:/Windows/win.ini", "", None, "https://[::1")))
check("l'elenco di partenza ha solo indirizzi buoni, con il segno che arrivi da FreeLaserCut",
      all(mh.safe_url(t["url"]) == t["url"] and "da=freelasercut" in t["url"] for t in mh.BUILTIN_TOOLS))

# ================================================================== 2. elenco dei generatori
raw = {"protocollo": 1, "servizio": "MakerHub", "strumenti": [
    {"id": "scatola", "icona": "📦", "nome": "Scatola a incastri", "descrizione": "Pezzi già compensati.",
     "url": "https://app.maker-hub.it/?pagina=laser&scheda=scatola&da=freelasercut", "manda_a_freelasercut": True,
     "per_tutti": True},
    {"id": "prova", "nome": "Ancora in prova", "url": "https://app.maker-hub.it/?x=1", "per_tutti": False},
    {"id": "altrove", "nome": "Porta altrove", "url": "https://example.com/", "per_tutti": True},
    {"id": "scatola", "nome": "Doppione", "url": "https://app.maker-hub.it/?x=2", "per_tutti": True},
    {"id": "html", "nome": "<img src=x onerror=1>Ingranaggi", "descrizione": "riga\nuno " + "x" * 400,
     "url": "https://app.maker-hub.it/?pagina=laser&scheda=ingranaggi", "per_tutti": True},
    "non una voce", {"id": "senza nome", "url": "https://app.maker-hub.it/"}]}
tools = mh.parse_tools(raw)
check("elenco: restano le voci per tutti con un indirizzo buono, senza doppioni",
      [t["id"] for t in tools] == ["scatola", "html"] and tools[0]["send"] is True and tools[1]["send"] is False, tools)
check("…i testi arrivano ripuliti: una riga, niente parentesi angolari, lunghezza limitata",
      "<" not in tools[1]["name"] and "\n" not in tools[1]["description"] and len(tools[1]["description"]) <= 200, tools[1])
check("…una risposta che non è un elenco dà un elenco vuoto, senza errori",
      mh.parse_tools(None) == [] and mh.parse_tools({"strumenti": "no"}) == [] and mh.parse_tools([1, 2]) == [])

# ================================================================== 3. controlli su un lavoro
check("lavoro del protocollo: nessun problema", mh.validate(job_op()) == [], mh.validate(job_op()))
bad_jobs = {
    "protocollo diverso": job_op(protocollo=2),
    "formato non previsto": job_op(formato="pdf", file="x.pdf"),
    "disegno vuoto": job_op(dati="  "),
    "disegno troppo grande": job_op(dati="<svg>" + "x" * (4 * 1024 * 1024) + "</svg>"),
    "nome del file con un percorso": job_op(file="../../avvio.svg"),
    "nome del file con un'altra estensione": job_op(file="scatola.exe"),
    "avvio del laser": job_op(avvia_il_laser=True),
    "script nell'SVG": job_op(dati=SVG.replace("<rect", "<script>1</script><rect")),
    "entità XML": job_op(dati='<!DOCTYPE svg [<!ENTITY a "aaaa">]>' + SVG),
    "immagine": job_op(dati=SVG.replace("<rect", '<image href="data:image/png;base64,AAAA" width="5" height="5"/><rect')),
    "riferimento a un file": job_op(dati=SVG.replace("<rect", '<use xlink:href="file:///C:/x.svg#a"/><rect')),
    "unità diversa dai millimetri": job_op(unita="in"),
    "livelli che non sono un elenco": job_op(livelli="rosso"),
    "non è un lavoro": {"op": "esegui", "comando": "format c:"},
    "non è nemmeno un oggetto": "ciao",
}
kept = [k for k, op in bad_jobs.items() if not mh.validate(op)]
check(f"lavori da rifiutare ({len(bad_jobs)} tipi): tutti rifiutati", not kept, kept)
check("un riferimento interno (#id) è permesso",
      mh.validate(job_op(dati=SVG.replace("<rect", '<use href="#a"/><rect'))) == [])

# ================================================================== 4. rete
try:
    mh.Bridge(server="http://example.com/ponte")
    refused = False
except mh.BridgeError:
    refused = True
check("il collegamento vero è https; in chiaro solo verso questo computer (per le prove)",
      refused and REAL_SERVER.startswith("https://") and mh.Bridge(server=REAL_SERVER) is not None)
b = mh.Bridge()
tok = b.pair(" ab3-k9q ")
sent = fake.last("/ponte/abbina")
check("codice giusto (scritto con spazi, trattino e minuscole): arriva il token", tok == "tok-buono-1234567890"
      and sent["codice"] == "AB3K9Q", sent)
check("…a MakerHub vanno solo codice, versione e nome del programma: niente nome del computer",
      sent == {"codice": "AB3K9Q", "computer": "", "versione": __version__, "app": "freelasercut"}
      and fake.agent == f"FreeLaserCut/{__version__} MakerHubLive/1", (sent, fake.agent))
msgs = {}
for code in ("ZZZZZZ", "TROPPI", "!!", ""):
    try:
        mh.Bridge().pair(code)
        msgs[code] = None
    except mh.BridgeError as exc:
        msgs[code] = (exc.code, str(exc))
check("codice sbagliato o scaduto: messaggio chiaro, nessun token", msgs["ZZZZZZ"] and msgs["ZZZZZZ"][0] == 403
      and "10 minuti" in msgs["ZZZZZZ"][1], msgs)
check("troppi tentativi: lo dice", msgs["TROPPI"] and msgs["TROPPI"][0] == 429 and "riprova" in msgs["TROPPI"][1].lower(), msgs)
n = fake.count("/ponte/abbina")
check("codice che non può essere un codice: fermato prima di chiamare MakerHub", msgs["!!"] and msgs[""]
      and msgs["!!"][0] is None and n == 3, (msgs, n))
dead = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = dead.server_address[1]
dead.server_close()
try:
    mh.Bridge(server=f"http://127.0.0.1:{port}/ponte", timeout=3).pair("AB3K9Q")
    err = None
except mh.BridgeError as exc:
    err = str(exc)
check("MakerHub spento o senza rete: un messaggio, non un errore del programma", err and "raggiungibile" in err, err)
jobs = b.wait(1)
sent = fake.last("/ponte/attesa")
check("attesa senza lavori: elenco vuoto; non si manda il nome del progetto", jobs == [] and sent["documento"] == ""
      and set(sent) == {"token", "documento", "versione", "attesa", "massimo"}, sent)
push(1)
jobs = b.wait(1)
check("attesa con un lavoro: arriva con titolo e controlli fatti", len(jobs) == 1 and jobs[0]["id"] == 1
      and jobs[0]["problems"] == [] and jobs[0]["op"]["formato"] == "svg", jobs)
try:
    mh.Bridge(token="tok-vecchio").wait(1)
    code = None
except mh.BridgeError as exc:
    code = exc.code
check("token non più valido: MakerHub risponde 401 e FreeLaserCut lo riconosce", code == 401, code)
check("di sé FreeLaserCut dice solo la versione; modello e area solo con il profilo",
      mh.machine_state() == {"programma": f"FreeLaserCut {__version__}"}
      and mh.machine_state(MachineProfile()) == {"programma": f"FreeLaserCut {__version__}",
                                                 "macchina": MachineProfile().model,
                                                 "area_mm": [MachineProfile().bed_x, MachineProfile().bed_y]})

# ================================================================== 5. dal lavoro alle forme
doc = Document()
before = json.dumps({i: cs.to_dict() for i, cs in doc.layers.items()}, sort_keys=True)
plan = mh.plan_job(job_op(), doc)
check("misure vere: 100 × 70 mm restano 100 × 70 mm", abs(plan.size[0] - 100) < 0.01 and abs(plan.size[1] - 70) < 0.01, plan.size)
check("leggere il lavoro non cambia il progetto (né forme né livelli) finché non si conferma",
      not doc.all_shapes() and json.dumps({i: cs.to_dict() for i, cs in doc.layers.items()}, sort_keys=True) == before)
cut = [ly for ly in plan.layers if ly[1] == "line"]
fill = [ly for ly in plan.layers if ly[1] == "fill"]
check("rosso = taglio su un livello, nero = incisione su un altro",
      len(cut) == 1 and len(fill) == 1 and cut[0][0] != fill[0][0]
      and leaf_layers(plan.shapes) == sorted([cut[0][0], fill[0][0]]), plan.layers)
check("valori di partenza del taglio: quelli di MakerHub; dove mancano non si tocca niente",
      cut[0][2] == {"power_max": 80.0, "speed": 300.0, "passes": 2} and fill[0][2] == {}, plan.layers)
doc.layer(cut[0][0]).kerf = 0.2
speed0, power0 = doc.layer(fill[0][0]).speed, doc.layer(fill[0][0]).power_max
plan.apply_layers(doc)
cs = doc.layer(cut[0][0])
check("dopo la conferma: livello di taglio in Linea con 80% · 300 mm/min · 2 passate",
      (cs.mode, cs.power_max, cs.speed, cs.passes) == ("line", 80.0, 300.0, 2), cs)
check("kerf già compensato da MakerHub: la compensazione di FreeLaserCut va a zero, e lo dice",
      cs.kerf == 0.0 and any("compensat" in n_ for n_ in plan.notes), (cs.kerf, plan.notes))
fs = doc.layer(fill[0][0])
check("livello di incisione in Riempimento, con la sua velocità e la sua potenza di prima",
      fs.mode == "fill" and (fs.speed, fs.power_max) == (speed0, power0), fs)

doc = Document()
doc.add(RectShape(10, 10, layer=0))
doc.add(RectShape(10, 10, layer=io_formats.nearest_layer((255, 0, 0))))
doc.layer(0).mode = "image"
plan = mh.plan_job(job_op(), doc)
plan.apply_layers(doc)
check("i livelli già usati dal progetto non vengono toccati: il disegno va su livelli liberi",
      not set(leaf_layers(plan.shapes)) & {0, io_formats.nearest_layer((255, 0, 0))} and doc.layer(0).mode == "image",
      leaf_layers(plan.shapes))

doc = Document()
doc.add(RectShape(10, 10, layer=7))
doc.layer(7).priority = 4
swapped = job_op(livelli=[{"colore": "#000000", "lavoro": "taglio"}, {"colore": "#FF0000", "lavoro": "incisione"}])
plan = mh.plan_job(swapped, doc)
plan.apply_layers(doc)
for s_ in plan.shapes:
    doc.add(s_)
order = [(c.index, c.mode) for c in doc.used_layers()]
check("ordine di lavoro: dopo quello che c'era, prima l'incisione e per ultimo il taglio (anche se il suo livello viene prima)",
      [m for _i, m in order] == ["line", "fill", "line"] and order[0][0] == 7 and order[2][0] < order[1][0], order)

doc = Document()
odd = job_op(livelli=[{"colore": "#FF0000", "lavoro": "taglio", "potenza_pct": 250, "velocita_mm_min": -5, "passate": 0},
                      {"colore": "#000000", "lavoro": "incisione", "potenza_pct": "80", "velocita_mm_min": True,
                       "passate": float("nan")}])
plan = mh.plan_job(odd, doc)
vals = {ly[1]: ly[2] for ly in plan.layers}
check("valori assurdi: portati nei limiti (100%, 10 mm/min, 1 passata); quelli che non sono numeri ignorati",
      vals["line"] == {"power_max": 100.0, "speed": 10.0, "passes": 1} and vals["fill"] == {}, vals)

doc = Document()
doc.layer(io_formats.nearest_layer((255, 0, 0))).kerf = 0.2
plan = mh.plan_job(job_op(kerf_compensato_mm=0), doc)
plan.apply_layers(doc)
check("senza kerf compensato la compensazione dell'utente resta, e non c'è la nota",
      doc.layer([ly for ly in plan.layers if ly[1] == "line"][0][0]).kerf == 0.2
      and not any("compensat" in n_ for n_ in plan.notes), plan.notes)

doc = Document()
blue = SVG.replace("</svg>", '<path d="M10 10 L20 20" stroke="#0000FF" fill="none"/></svg>')
plan = mh.plan_job(job_op(dati=blue), doc)
check("un colore che MakerHub non ha dichiarato: su un livello a parte, con l'avviso",
      plan.other is not None and plan.other not in [ly[0] for ly in plan.layers] and plan.other_count == 1
      and plan.other in leaf_layers(plan.shapes) and any("colore" in n_ for n_ in plan.notes), (plan.other, plan.notes))

doc = Document()
plan = mh.plan_job(job_op(livelli=[]), doc)
normal = io_formats.import_svg(SVG.encode(), Document())
check("nessun livello dichiarato: arriva come un import normale, senza toccare le impostazioni",
      plan.layers == [] and leaf_layers(plan.shapes) == leaf_layers(normal), (plan.layers, leaf_layers(plan.shapes)))

import ezdxf  # noqa: E402

dwg = ezdxf.new("R2010")
dwg.header["$INSUNITS"] = 4
msp = dwg.modelspace()
msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], close=True, dxfattribs={"color": 1})
msp.add_circle((30, 20), 5, dxfattribs={"color": 7})
dwg.layers.add("TAGLIO", color=1)
msp.add_line((0, 0), (60, 40), dxfattribs={"layer": "TAGLIO"})
dxf_path = os.path.join(tempfile.mkdtemp(), "p.dxf")
dwg.saveas(dxf_path)
dxf_text = open(dxf_path, encoding="utf-8").read()
doc = Document()
plan = mh.plan_job(job_op(formato="dxf", file="scatola.dxf", dati=dxf_text), doc)
cut_i = [ly[0] for ly in plan.layers if ly[1] == "line"][0]
on_cut = sum(1 for s in plan.shapes for leaf, _ in s.leaves() if leaf.layer == cut_i)
check("DXF: 60 × 40 mm; il rosso a numero e il rosso «come il livello» vanno sul taglio, il nero sull'incisione",
      abs(plan.size[0] - 60) < 0.01 and abs(plan.size[1] - 40) < 0.01 and on_cut == 2 and plan.other is None,
      (plan.size, on_cut, plan.other))
check("…e un DXF aperto dal menu File continua ad arrivare come prima",
      leaf_layers(io_formats.import_dxf(dxf_path, Document())) == [0])
errs = []
for data in ("<svg><rect", '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm"></svg>', "non è un disegno"):
    try:
        mh.plan_job(job_op(dati=data), Document())
        errs.append(None)
    except ValueError as exc:
        errs.append(str(exc))
check("disegno rovinato o vuoto: un messaggio per l'utente, mai un blocco", all(errs), errs)

# ================================================================== 6. finestra
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
from freelasercut.ui import dialogs_makerhub as ui  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

ui.Listener.MIN_CYCLE = 0.05  # il MakerHub finto risponde in un quarto di secondo: qui non serve aspettare
opened = []
ui.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
calls0 = fake.count()
w = MainWindow()
w.resize(1400, 900)
hub = w.makerhub
w.qs.setValue(mh.KEY_TOKEN, "tok-buono-1234567890")  # un token rimasto da prima, ma con le funzioni in prova nascoste
w._apply_admin()
pal = getattr(getattr(w, "banco", None), "palette", None)
check("senza codice: niente menu MakerHub, la finestra non si apre, un generatore non si apre",
      not hub.menu.menuAction().isVisible() and not w.acts["makerhub"].isVisible() and w.makerhub_dialog() is None
      and hub.open_tool(mh.BUILTIN_TOOLS[0]["url"]) is False and not opened)
if pal is not None:
    found = (pal.collect(), [a_ for a_, _p in pal.entries])[1]
    check("Banco: senza codice la ricerca dei comandi non trova MakerHub",
          w.acts["makerhub"] not in found and not any(a_ in found for a_ in hub.tool_actions))
time.sleep(0.6)
app.processEvents()
check("senza codice nessuna chiamata a MakerHub, nemmeno con un token salvato", fake.count() == calls0
      and not hub.listener.running(), fake.count() - calls0)
w.qs.remove(mh.KEY_TOKEN)
check("con il codice: compare il menu MakerHub con i suoi generatori e «Collega MakerHub»",
      w.admin_dialog(code="prova") is True and hub.menu.menuAction().isVisible() and w.acts["makerhub"].isVisible()
      and [a_.text() for a_ in hub.tool_actions] == ["Scatola a incastri"]
      and w.acts["makerhub"] in hub.menu.actions())
check("ogni voce ha il logo di MakerHub", not hub.tool_actions[0].icon().isNull() and not w.acts["makerhub"].icon().isNull()
      and not ui.logo_icon().pixmap(20, 20).isNull())
if pal is not None:
    found = (pal.collect(), [a_ for a_, _p in pal.entries])[1]
    check("Banco: con il codice la ricerca dei comandi trova il generatore e il collegamento",
          w.acts["makerhub"] in found and hub.tool_actions[0] in found)
hub.tool_actions[0].trigger()
check("un clic sul generatore apre nel browser la pagina di MakerHub, con il segno che arrivi da FreeLaserCut",
      opened == ["https://app.maker-hub.it/?pagina=laser&scheda=scatola&da=freelasercut"], opened)
w.qs.setValue(mh.KEY_TOOLS, json.dumps([{"id": "x", "name": "Finto", "url": "https://example.com/"}]))
hub.refresh_menu()
check("un elenco salvato con un indirizzo di un altro sito non viene usato: resta quello di partenza",
      [a_.text() for a_ in hub.tool_actions] == ["Scatola a incastri"])
w.qs.remove(mh.KEY_TOOLS)
time.sleep(0.4)
app.processEvents()
check("fin qui (avvio, sblocco, menu, browser) nessuna chiamata a MakerHub", fake.count() == calls0, fake.count() - calls0)

dlg = w.makerhub_dialog()
check("la finestra si apre, una seconda richiesta riporta la stessa; da scollegato chiede il codice",
      dlg is not None and w.makerhub_dialog() is dlg and not dlg.code.isHidden() and dlg.b_unpair.isHidden()
      and dlg.list.count() == 1)
time.sleep(0.5)
app.processEvents()
check("aprire la finestra non chiama MakerHub", fake.count() == calls0 and dlg._busy is None, fake.count() - calls0)
fake.tools = raw
dlg.b_refresh.click()
check("«Aggiorna l'elenco»: una sola chiamata, e il menu e la finestra mostrano i generatori nuovi",
      until(lambda: dlg._busy is None and len(hub.tool_actions) == 2, 8)
      and fake.count("/ponte/flc/strumenti") == 1 and dlg.list.count() == 2
      and [a_.text() for a_ in hub.tool_actions][0] == "Scatola a incastri"
      and "<" not in hub.tool_actions[1].text(), [a_.text() for a_ in hub.tool_actions])
fake.tools = {"strumenti": []}
dlg.b_refresh.click()
check("MakerHub risponde con un elenco vuoto: resta quello di prima, e lo dice",
      until(lambda: dlg._busy is None and "vuoto" in dlg.status.text(), 8) and len(hub.tool_actions) == 2, dlg.status.text())
dlg.list.setCurrentRow(1)
dlg.b_open.click()
check("«Apri nel browser» apre il generatore scelto", opened[-1] == "https://app.maker-hub.it/?pagina=laser&scheda=ingranaggi", opened)

dlg.code.setText("zzzzzz")
dlg.b_pair.click()
check("codice sbagliato nella finestra: lo dice e resta scollegato",
      until(lambda: dlg._busy is None and "10 minuti" in dlg.status.text(), 8) and not hub.paired()
      and not hub.listener.running(), dlg.status.text())
dlg.code.setText("ab3 k9q")
dlg.b_pair.click()
check("codice giusto: collegato, il token è nelle preferenze, l'ascolto parte e si vede",
      until(lambda: hub.paired() and hub.state == "on", 8) and hub.listener.running()
      and w.qs.value(mh.KEY_TOKEN) == "tok-buono-1234567890" and dlg.code.isHidden() and not dlg.b_unpair.isHidden()
      and "collegato" in w.acts["makerhub"].text().lower() and "Collegato" in dlg.status.text(),
      (hub.state, hub.text, w.acts["makerhub"].text()))
check("i fili di MakerHub non tengono aperto il programma alla chiusura",
      all(t.daemon for t in threading.enumerate() if t.name.startswith("makerhub")))

# ---- arriva un disegno
ed = w.editor
bed = (w.profile.bed_x, w.profile.bed_y)
del asked[:], told[:], fake.results[:]
depth0 = len(ed.undo_stack) if hasattr(ed, "undo_stack") else None
push(11)
until(lambda: len(fake.results) == 1, 8)
shapes = list(ed.doc.shapes)
bb = None
for s in shapes:
    bb = s.bounds() if bb is None else bb.united(s.bounds())
check("un disegno mandato dal sito: FreeLaserCut chiede conferma con titolo, misure e materiale",
      len(asked) == 1 and "Scatola 100×70×50" in asked[0] and "100 × 70 mm" in asked[0] and "pioppo" in asked[0]
      and "non parte" in asked[0], asked)
check("…poi è sul piano, al centro, con le misure vere",
      shapes and abs(bb.width() - 100) < 0.01 and abs(bb.height() - 70) < 0.01
      and abs(bb.center().x() - bed[0] / 2) < 0.01 and abs(bb.center().y() - bed[1] / 2) < 0.01, bb)
modes = sorted(ed.doc.layer(i).mode for i in leaf_layers(shapes))
check("…taglio e incisione sui loro livelli, e le note su kerf e parametri",
      modes == ["fill", "line"] and len(told) == 1 and "compensat" in told[0] and "valori di partenza" in told[0], (modes, told))
r = fake.results[0]
check("…a MakerHub torna l'esito, con la sola versione di FreeLaserCut",
      r["id"] == 11 and r["ok"] is True and r["stato"] == {"programma": f"FreeLaserCut {__version__}"}, r)
check("il laser non parte e la macchina non viene toccata", not w.ctl.job_active and not w.ctl.connected)
ed.undo()
check("un solo Annulla toglie tutto il disegno arrivato", not ed.doc.shapes)

del asked[:], told[:], fake.results[:]
answer[0] = QMessageBox.No
push(12)
until(lambda: len(fake.results) == 1, 8)
check("alla conferma si risponde No: sul piano non arriva niente, e MakerHub lo sa",
      len(asked) == 1 and not ed.doc.shapes and fake.results[0]["ok"] is False
      and "non l'ha voluto" in fake.results[0]["messaggio"], fake.results)
answer[0] = QMessageBox.Yes

del asked[:], told[:], fake.results[:]
push(13, avvia_il_laser=True)
until(lambda: len(fake.results) == 1, 8)
check("un lavoro che vorrebbe avviare il laser: scartato senza chiedere, niente sul piano, esito negativo",
      not asked and not ed.doc.shapes and fake.results[0]["ok"] is False and "laser" in fake.results[0]["messaggio"]
      and not w.ctl.job_active, fake.results)

del asked[:], told[:], fake.results[:]
push(14, "<img src=x onerror=alert(1)>Scatola", dati="<svg><rect")
until(lambda: len(fake.results) == 1, 8)
check("disegno rovinato: avviso (senza HTML nel titolo), niente sul piano, esito negativo",
      not asked and len(told) == 1 and "<" not in told[0] and not ed.doc.shapes and fake.results[0]["ok"] is False,
      (told, fake.results))

del asked[:], told[:], fake.results[:]
w.qs.setValue(mh.KEY_MACHINE, True)
big = SVG.replace('width="100mm" height="70mm" viewBox="0 0 100 70"', 'width="2000mm" height="1400mm" viewBox="0 0 100 70"')
push(15, dati=big)
until(lambda: len(fake.results) == 1, 8)
r = fake.results[0]
check("più grande del piano: lo dice prima, arriva con le sue misure e MakerHub lo sa",
      len(asked) == 1 and "più grande del piano" in asked[0] and r["ok"] is True and "più grande" in r["messaggio"]
      and abs(max(s.bounds().width() for s in ed.doc.shapes) - 2000) < 0.5, (asked, r))
check("con «Di' a MakerHub che macchina uso»: nell'esito ci sono modello e area di lavoro",
      r["stato"].get("macchina") == w.profile.model and r["stato"].get("area_mm") == [bed[0], bed[1]], r["stato"])
w.qs.setValue(mh.KEY_MACHINE, False)
n_shapes = len(ed.doc.shapes)
del asked[:], told[:], fake.results[:]
push(15, dati=big)  # MakerHub rimanda lo stesso lavoro (per esempio l'esito non gli era arrivato)
until(lambda: len(fake.results) == 1, 8)
check("lo stesso lavoro rimandato da MakerHub: non si chiede due volte e non arriva un doppione",
      not asked and len(ed.doc.shapes) == n_shapes and fake.results[0]["id"] == 15 and fake.results[0]["ok"] is True,
      (asked, fake.results))

# ---- rapporto per l'assistenza
from freelasercut import diag  # noqa: E402

rep = os.path.join(tempfile.mkdtemp(), "rapporto.zip")
diag.make_report(rep, w, None)
blob = b"".join(zipfile.ZipFile(rep).read(n_) for n_ in zipfile.ZipFile(rep).namelist())
check("nel rapporto per l'assistenza il token di MakerHub non c'è", os.path.getsize(rep) > 500
      and b"tok-buono" not in blob and b"makerhub_token" not in blob)

# ---- collegamento scaduto, scollega, di nuovo nascosto
fake.tokens.clear()
check("MakerHub non riconosce più il token: FreeLaserCut lo butta, smette di chiamare e lo dice",
      until(lambda: hub.state == "expired", 8) and not hub.paired() and not hub.listener.running()
      and "codice nuovo" in hub.text and "collegato" not in w.acts["makerhub"].text().lower()
      and not dlg.code.isHidden(), (hub.state, hub.text))
time.sleep(0.5)
app.processEvents()
n = fake.count()
time.sleep(0.8)
app.processEvents()
check("…e da lì in poi nessuna chiamata", fake.count() == n, fake.count() - n)
fake.tokens.add("tok-buono-1234567890")
ok, token = hub.pair("AB3K9Q")
hub._paired(token)
until(lambda: hub.state == "on", 8)
dlg.b_unpair.click()
check("«Scollega»: il token sparisce dalle preferenze, l'ascolto si ferma e la finestra chiede di nuovo il codice",
      not hub.paired() and w.qs.value(mh.KEY_TOKEN) is None and not hub.listener.running() and not dlg.code.isHidden()
      and "Scollegato" in dlg.status.text(), dlg.status.text())
time.sleep(0.6)
app.processEvents()
n = fake.count()
push(16)
time.sleep(0.8)
app.processEvents()
check("…e un disegno mandato dopo non arriva, né partono altre chiamate", fake.count() == n and not asked[1:] and len(ed.doc.shapes) == n_shapes)
with fake.lock:
    del fake.queue[:]
ok, token = hub.pair("AB3K9Q")
hub._paired(token)
until(lambda: hub.state == "on", 8)
answer[0] = QMessageBox.Yes
check("nascondendo di nuovo le funzioni in prova: menu e finestra spariscono e l'ascolto si ferma",
      w.admin_dialog() is False and not hub.menu.menuAction().isVisible() and not w.acts["makerhub"].isVisible()
      and not hub.listener.running() and until(lambda: hub.dialog is None, 3) and w.makerhub_dialog() is None)
check("…ma il collegamento resta salvato: sbloccando di nuovo riparte da solo",
      hub.paired() and w.admin_dialog(code="prova") is True and until(lambda: hub.state == "on", 8)
      and hub.listener.running())
hub.unpair()

# ================================================================== traduzioni
srcs = [open(os.path.join(ROOT, "freelasercut", *p), encoding="utf-8").read()
        for p in (("makerhub.py",), ("ui", "dialogs_makerhub.py"))]
keys = set()
for src in srcs:
    for m in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        keys.add("".join(json.loads(p_) for p_ in re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1))))
check("testi da tradurre trovati nei due file di MakerHub", len(keys) > 50, len(keys))
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    brand = [k for k in keys if "MakerHub" in k and "MakerHub" not in (loc.get(k) or "MakerHub")]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto e il nome MakerHub intatto",
          not miss and not bad and not brand, (miss[:3], bad[:3], brand[:3]))

httpd.shutdown()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
