# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.14: MakerHub nel menu Strumenti (funzione in prova) e il collegamento sito → FreeLaserCut.

MakerHub (maker-hub.it) è un servizio esterno. Strumenti → MakerHub apre nel browser il loro sito, dove stanno Dima
Lab, Forma Lab, Hinge Lab e Split Lab; il pulsante «Manda a FreeLaserCut» di quegli strumenti apre una finestrella su
http://127.0.0.1:47821/flc/ponte (servita da FreeLaserCut), che riceve il file dalla pagina e lo consegna qui.
In questa prova il browser non c'è: l'apertura è sostituita da un finto e la finestrella da un cliente che fa le
stesse due richieste. La prova con Chromium vero e i quattro programmi veri è fuori dalla suite (documento
«aggiornamento-0.18.14»).

Il dato: una consegna = chi manda (origine dichiarata dal browser) + nome dello strumento + uno o più file (SVG, o
ZIP di SVG) → uno o più disegni, ognuno «foglio N» (piano-N.svg) oppure «pezzo».

Casi provati:
1 strumenti e indirizzi: i quattro strumenti, indirizzo https di maker-hub.it, niente rete in makerhub.py;
2 icona (come nella 0.18.11);
3 chi può mandare: maker-hub.it e sottodomini in https, pagine di questo computer, file dal disco solo se sbloccato;
4 richieste: incomplete, a pezzi, sbagliate, troppo grandi; risposte senza CORS;
5 file arrivati: SVG, ZIP con fogli, ZIP con pezzi, mappa di montaggio, file non di disegno, ZIP rovinato o enorme,
  immagini che puntano a file del computer, nomi con cartelle;
6 consegna: Host sbagliato, gettone assente, usato due volte, scaduto, origine della richiesta sbagliata, sito non
  ammesso, dati rovinati; la finestrella (gettone, niente script esterni, controlla chi le parla);
7 ricevitore vero: ascolta solo su 127.0.0.1, risponde a richieste a pezzi, si spegne, porta occupata;
8 finestra: nascosta senza codice; menu Strumenti → MakerHub con logo, quattro strumenti e «Ricevi qui i disegni»;
  clic = browser + ascolto + istruzioni; spunta tolta = niente ascolto; ripresa all'avvio; chiusura;
9 disegni sul piano: uno solo, più fogli (piani di lavoro), piano già occupato, pezzi affiancati, mappa, scritte,
  troppo grande, illeggibile, programma occupato, annulla, laser mai toccato;
10 lo script per il sito: stessa porta e stesse parole della finestrella, nessuna chiamata di rete;
11 testi: schede d'aiuto e traduzioni.
"""
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
boxes = []
QMessageBox.question = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(a) or QMessageBox.Ok)
opened = []
browser = [True]  # False = il sistema non riesce ad aprire il browser
QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or browser[0])

from freelasercut import __version__, admin, theme  # noqa: E402
from freelasercut import makerhub as mh  # noqa: E402
from freelasercut import makerhub_link as link  # noqa: E402
from freelasercut.core import ops  # noqa: E402
from freelasercut.ui import help_texts, style  # noqa: E402

REAL_PORT = link.PORT
_probe = socket.socket()
_probe.bind(("127.0.0.1", 0))
link.PORT = PORT = _probe.getsockname()[1]  # la prova usa una porta libera qualsiasi: può girare accanto a un FreeLaserCut
_probe.close()                              # aperto, o a un'altra copia della prova
results = []
SITE = "https://app.maker-hub.it/?da=freelasercut"  # l'indirizzo è uno solo: gli strumenti si scelgono nel loro menu


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def svg(w=100, h=70, extra="", color="#ff0000"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">'
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="none" stroke="{color}"/>{extra}</svg>').encode()


def zipped(files, compress=zipfile.ZIP_STORED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as z:
        for name, data in files:
            z.writestr(name, data)
    return buf.getvalue()


# ================================================================== 1. strumenti e indirizzi
check("gli strumenti sono i quattro di MakerHub, con il loro nome",
      [t.name for t in mh.TOOLS] == ["Dima Lab", "Forma Lab", "Hinge Lab", "Split Lab"]
      and [t.key for t in mh.TOOLS] == ["dima", "forma", "hinge", "split"] and all(t.what for t in mh.TOOLS))
check("ogni strumento apre il sito di MakerHub, in https, con il segno che arrivi da FreeLaserCut",
      all(t.url == SITE and mh.safe_url(t.url) == SITE for t in mh.TOOLS), [t.url for t in mh.TOOLS])
check("si aprono solo indirizzi https di maker-hub.it: mai http, un altro sito, un sosia, utente@",
      mh.safe_url("https://maker-hub.it/") and not any(mh.safe_url(u) for u in (
          "http://app.maker-hub.it/", "https://example.com/", "https://maker-hub.it.example.com/",
          "https://finto-maker-hub.it/", "https://maker-hub.it@example.com/", "https://utente:x@maker-hub.it/",
          "javascript:alert(1)", "file:///C:/Windows/win.ini", "", None, "https://[::1")))
real = mh.TOOLS
mh.TOOLS = (mh.Tool("dima", "Dima Lab", "https://example.com/dima", "x"),)
check("se l'indirizzo di uno strumento non fosse di MakerHub il browser non verrebbe aperto",
      mh.open_tool("dima") is False and not opened, opened)
mh.TOOLS = real
check("uno strumento che non esiste non apre niente", mh.open_tool("scatola") is False and mh.tool("scatola") is None and not opened)
code = src("freelasercut", "makerhub.py")
check("makerhub.py non fa rete e non avvia fili: apre soltanto la pagina",
      not re.search(r"urllib\.request|urlopen|http\.client|socket|requests|threading|QNetwork|QTcpServer", code))
code_link = src("freelasercut", "makerhub_link.py")
check("il ricevitore non chiama nessuno e non usa fili: solo un QTcpServer, e non scrive file",
      "QTcpServer" in code_link and not re.search(
          r"urllib\.request|urlopen|http\.client|requests|threading|QNetworkAccessManager|\bopen\(|extractall|\.extract\(", code_link))
check("della 0.18.10 non è tornato niente: nessun codice di collegamento, nessuna chiamata al loro server",
      not os.path.exists(os.path.join(ROOT, "freelasercut", "ui", "dialogs_makerhub.py"))
      and not re.search(r"makerhub_token|plan_job|maker-hub\.it/ponte|Bearer", code + code_link + src("freelasercut", "ui", "main_window.py")))

# ================================================================== 2. icona
ic = mh.icon()
ref = style.icon("puzzle")
sizes = sorted(s.width() for s in ic.availableSizes())
check("icona: c'è, a più risoluzioni, e nella misura base è grande come quelle degli altri strumenti",
      not ic.isNull() and sizes == sorted(s.width() for s in ref.availableSizes()) + [60] and sizes[0] == 20
      and ic.actualSize(QSize(16, 16)) == ref.actualSize(QSize(16, 16))
      and ic.actualSize(QSize(20, 20)) == ref.actualSize(QSize(20, 20)), (sizes, [s.width() for s in ref.availableSizes()]))
img = ic.pixmap(QSize(40, 40)).toImage()
mid = img.pixelColor(20, 4)  # nella fascia arancione sopra il chip
corner = img.pixelColor(0, 0)
round_ = img.pixelColor(4, 4)  # dentro il riquadro, ma nello spicchio tolto dall'angolo tondo
check("il logo è a colori (arancione MakerHub), con gli angoli tondi e trasparenti e il segno bianco dentro",
      mid.red() > 200 and 60 < mid.green() < 130 and mid.blue() < 60 and mid.alpha() == 255 and corner.alpha() == 0
      and round_.alpha() < 60 and any(img.pixelColor(x, 20).lightness() > 230 for x in range(8, 32)),
      (mid.getRgb(), corner.getRgb(), round_.getRgb()))
inked = [x for x in range(40) if img.pixelColor(x, 20).alpha() > 128]
ref_img = ref.pixmap(QSize(40, 40)).toImage()
ref_ink = [x for x in range(40) for y in range(40) if ref_img.pixelColor(x, y).alpha() > 128]
check("il riquadro occupa la casella come i disegni delle altre icone (un po' di margine, non tutta)",
      2 <= inked[0] <= 4 and 35 <= inked[-1] <= 37 and abs((inked[-1] - inked[0]) - (max(ref_ink) - min(ref_ink))) <= 5,
      (inked[0], inked[-1], min(ref_ink), max(ref_ink)))


def lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b_):
    la, lb = sorted((lum(a), lum(b_)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


orange = mid.getRgb()[:3]
worst = min(contrast(orange, rgb(t[k])) for t in (theme.DARK, theme.LIGHT) for k in ("panel", "panel2"))
check("l'arancione si stacca dal fondo dei menu sia nel tema scuro sia in quello chiaro (contrasto ≥ 3)",
      worst >= 3.0, round(worst, 2))
off = ic.pixmap(QSize(40, 40), QIcon.Mode.Disabled).toImage().pixelColor(20, 4)
check("spenta (voce non disponibile) è grigia e attenuata, come le altre",
      abs(off.red() - off.green()) < 12 and abs(off.green() - off.blue()) < 12 and 40 < off.alpha() < 200, off.getRgb())

# ================================================================== 3. chi può mandare
ok_origins = {"https://maker-hub.it": "makerhub", "https://app.maker-hub.it": "makerhub", "https://a.b.maker-hub.it:8443": "makerhub",
              "HTTPS://APP.MAKER-HUB.IT": "makerhub", "http://localhost:8000": "local", "http://127.0.0.1": "local",
              "http://[::1]:5500": "local"}
check("accettati: maker-hub.it e sottodomini in https, e le pagine servite da questo computer",
      all(link.origin_kind(o) == k for o, k in ok_origins.items()), {o: link.origin_kind(o) for o in ok_origins})
bad_origins = ["http://app.maker-hub.it", "https://maker-hub.it.example.com", "https://finto-maker-hub.it", "https://example.com",
               "https://utente@maker-hub.it", "https://maker-hub.it/percorso", "https://maker-hub.it?x=1", "https://maker-hub.it:99999",
               "http://127.0.0.1.example.com", "http://192.168.1.10", "https://localhost", "file://", "null", "", None, 5,
               "javascript:alert(1)", "https://", "maker-hub.it", "https://[::1"]
check("rifiutati: http, altri siti, sosia, indirizzi con utente o percorso, la rete di casa, i file dal disco",
      not [o for o in bad_origins if link.origin_kind(o) is not None], [o for o in bad_origins if link.origin_kind(o) is not None])
check("un file aperto dal disco (origine «null») vale solo se lo si chiede espressamente",
      link.origin_kind("null", allow_file=True) == "file" and link.origin_kind("null") is None
      and link.origin_kind("https://example.com", allow_file=True) is None)

# ================================================================== 4. richieste
GET = f"GET /flc/ponte HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nAccept: */*\r\n\r\n".encode()
r = link.parse_request(GET)
check("una richiesta intera si legge: metodo, percorso, intestazioni",
      r and (r.method, r.path, r.headers["host"], r.body) == ("GET", "/flc/ponte", f"127.0.0.1:{PORT}", b""), r)
check("finché non è arrivata tutta si aspetta (anche a metà intestazioni o a metà corpo)",
      link.parse_request(GET[:20]) is None and link.parse_request(b"") is None
      and link.parse_request(b"POST /flc/importa HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\n12345") is None)
r = link.parse_request(bytearray(b"POST /flc/importa?x=1 HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\n12345ABC"))
check("il corpo è lungo quanto dichiarato, non di più; il percorso è senza la parte dopo «?»",
      r and r.body == b"12345" and r.path == "/flc/importa" and isinstance(r.body, bytes), r)


def refused(raw, **k):
    try:
        link.parse_request(raw, **k)
    except link.HttpError as exc:
        return exc.code
    return None


check("richieste non valide: riga sbagliata 400, intestazione senza «:» 400, lunghezza non numerica 400, Host doppio 400",
      [refused(b"CIAO\r\n\r\n"), refused(b"GET /x HTTP/1.1\r\nsenza due punti\r\n\r\n"),
       refused(b"POST /x HTTP/1.1\r\nContent-Length: dieci\r\n\r\n"), refused(b"GET /x HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n"),
       refused(b"GET http://altro/ HTTP/1.1\r\n\r\n"), refused("GET /è HTTP/1.1\r\n\r\n".encode())] == [400] * 6)
check("troppo grandi: intestazioni 431, corpo 413 (senza aspettare che arrivi), corpo «a pezzi» 411",
      [refused(b"GET /x HTTP/1.1\r\n" + b"A: " + b"x" * 20000), refused(b"GET /x HTTP/1.1\r\nA: " + b"x" * 20000 + b"\r\n\r\n"),
       refused(b"POST /x HTTP/1.1\r\nContent-Length: 999999999\r\n\r\n"),
       refused(b"POST /x HTTP/1.1\r\nContent-Length: 50\r\n\r\n", max_body=10),
       refused(b"POST /x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n")] == [431, 431, 413, 413, 411])
resp = link.response(200, "ciào", extra=("X-Prova: 1",))
head, _, body = resp.partition(b"\r\n\r\n")
check("le risposte: lunghezza giusta, mai in cache, niente CORS (nessun sito le può leggere), connessione chiusa",
      head.startswith(b"HTTP/1.1 200 OK") and b"Content-Length: 5" in head and body == "ciào".encode() and b"no-store" in head
      and b"nosniff" in head and b"Connection: close" in head and b"X-Prova: 1" in head
      and b"access-control" not in head.lower(), head)
check("in tutto il ricevitore non c'è nessuna intestazione CORS", "access-control" not in code_link.lower())

# ================================================================== 5. file arrivati
d, sk = link.unpack([("dima-400x300.svg", svg(400, 300))])
check("un SVG solo: un disegno, non è un «foglio»", len(d) == 1 and d[0].name == "dima-400x300.svg" and d[0].sheet is None and not sk)
split = zipped([("piano-2.svg", svg(120, 80)), ("mappa-montaggio.svg", svg(800, 500)), ("piano-10.svg", svg(30, 30)),
                ("piano-1.svg", svg(60, 40)), ("impostazioni.json", b"{}"), ("LEGGIMI.txt", b"ciao")])
d, sk = link.unpack([("split-lab.zip", split)])
check("uno ZIP di fogli: piano-1, piano-2, piano-10 nell'ordine dei numeri (non dell'alfabeto)",
      [(x.name, x.sheet) for x in d] == [("piano-1.svg", 1), ("piano-2.svg", 2), ("piano-10.svg", 10)], d and [(x.name, x.sheet) for x in d])
check("…la mappa di montaggio e i file che non sono disegni restano fuori (e si sa quali)",
      sorted(sk) == ["LEGGIMI.txt", "impostazioni.json", "mappa-montaggio.svg"], sk)
hinge = zipped([("retro.svg", svg(160, 117)), ("fascia-living-hinge.svg", svg(436, 60)), ("base.svg", svg(160, 117)),
                ("rinforzo-giunzione.svg", svg(12, 56)), ("mappa-montaggio.svg", svg(165, 117)), ("LEGGIMI.txt", b"x")],
               zipfile.ZIP_DEFLATED)
d, sk = link.unpack([("hinge-lab-progetto.zip", hinge)])
check("uno ZIP di pezzi (anche compresso): quattro pezzi, nessun foglio",
      [x.name for x in d] == ["retro.svg", "fascia-living-hinge.svg", "base.svg", "rinforzo-giunzione.svg"]
      and all(x.sheet is None for x in d) and "mappa-montaggio.svg" in sk)
d, sk = link.unpack([("uno.zip", zipped([("sotto/cartella/piano-1.svg", svg()), ("..\\..\\fuori.svg", svg())]))])
check("i nomi dentro lo ZIP perdono le cartelle (niente «../»): non si scrive niente su disco in ogni caso",
      [x.name for x in d] == ["piano-1.svg", "fuori.svg"], [x.name for x in d])
d, sk = link.unpack([("foto.png", b"\x89PNG..."), ("note.svg", b"non sono un disegno"), ("bomba.svg", b'<!DOCTYPE x [<!ENTITY a "aaaa">]><svg/>')])
check("file che non sono disegni, finti SVG e SVG con «entità» XML: scartati", not d and len(sk) == 3, (d, sk))


def rejected(files):
    try:
        link.unpack(files)
    except link.BadPayload as exc:
        return str(exc)
    return None


check("ZIP rovinato: rifiutato con un messaggio, senza errori",
      "Non riesco ad aprire" in (rejected([("x.zip", b"PK\x03\x04" + b"rovinato" * 20)]) or "")
      and "Non riesco ad aprire" in (rejected([("x.zip", split[:len(split) // 2])]) or ""))
old_max = link.MAX_ENTRIES, link.MAX_UNPACKED
link.MAX_ENTRIES = 3
too_many = rejected([("x.zip", split)])
link.MAX_ENTRIES, link.MAX_UNPACKED = old_max[0], 1000
too_heavy = rejected([("x.zip", zipped([("piano-1.svg", svg(extra="<!--" + "x" * 5000 + "-->"))], zipfile.ZIP_DEFLATED))])
too_heavy2 = rejected([("a.svg", svg(extra="<!--" + "x" * 600 + "-->")), ("b.svg", svg(extra="<!--" + "x" * 600 + "-->"))])
link.MAX_ENTRIES, link.MAX_UNPACKED = old_max
check("ZIP con troppi file, o che aperto pesa troppo (anche se compresso pesa poco), o troppi disegni pesanti: rifiutati",
      all("troppo grande" in (t or "") for t in (too_many, too_heavy, too_heavy2)), (too_many, too_heavy, too_heavy2))
reads = []
real_read = zipfile.ZipFile.read
zipfile.ZipFile.read = lambda self, *a_, **k_: reads.append(1) or real_read(self, *a_, **k_)
link.MAX_UNPACKED = 1000
bomb = rejected([("x.zip", zipped([("piano-1.svg", svg(extra="<!--" + "x" * 200000 + "-->"))], zipfile.ZIP_DEFLATED))])
link.MAX_UNPACKED = old_max[1]
zipfile.ZipFile.read = real_read
check("…e uno ZIP che dichiara un contenuto enorme viene rifiutato senza nemmeno aprirne i file", "troppo grande" in (bomb or "") and not reads, (bomb, reads))
img = svg(extra='<image href="file:///C:/Users/x/segreto.png" width="5" height="5"/><image xlink:href="https://example.com/a.png"/>'
                '<image width="2" height="2" href="data:image/png;base64,AAAA"/>')
clean = link.unpack([("a.svg", img)])[0][0].data
check("le immagini che puntano a un file del computer o a un indirizzo vengono tolte; quelle scritte dentro il file restano",
      b"segreto" not in clean and b"example.com" not in clean and b"data:image/png" in clean and clean.count(b"<image") == 1, clean)


def payload(files, origin="https://app.maker-hub.it", tool="Dima Lab", **more):
    out = []
    for name, data in files:
        out.append({"nome": name, "testo": data.decode()} if name.endswith(".svg") and more.get("text", True)
                   else {"nome": name, "b64": base64.b64encode(data).decode()})
    d_ = {"v": 1, "origine": origin, "strumento": tool, "file": out}
    d_.update({k: v for k, v in more.items() if k != "text"})
    return json.dumps(d_).encode()


a = link.read_payload(payload([("dima.svg", svg())]))
check("una consegna buona: strumento, origine, tipo di origine, disegni",
      (a.tool, a.origin, a.kind, len(a.drawings), a.skipped) == ("Dima Lab", "https://app.maker-hub.it", "makerhub", 1, []), a)
a = link.read_payload(payload([("split-lab.zip", split)], tool="Split Lab"))
check("una consegna con uno ZIP (in base64): i fogli ci sono tutti", [x.sheet for x in a.drawings] == [1, 2, 10])
a = link.read_payload(payload([("d.svg", svg())], tool='  <b>Dima\n Lab</b> "x" ' + "y" * 80))
check("il nome dello strumento viene ripulito e accorciato (finisce nei nomi dei piani e nei messaggi)",
      "<" not in a.tool and '"' not in a.tool and "\n" not in a.tool and len(a.tool) <= 40 and a.tool.startswith("bDima Lab"), a.tool)


def payload_error(body, **k):
    try:
        link.read_payload(body, **k)
    except link.BadPayload as exc:
        return "dati", str(exc)
    except PermissionError as exc:
        return "permesso", str(exc)
    return None


check("consegne rovinate: non JSON, senza file, file senza contenuto, base64 sbagliato, troppi file → «non è leggibile»",
      all((payload_error(b_) or ("", ""))[0] == "dati" for b_ in (
          b"ciao", b"\xff\xfe", b"[]", b'{"origine":"https://maker-hub.it","file":[]}', b'{"origine":"https://maker-hub.it","file":"x"}',
          b'{"origine":"https://maker-hub.it","file":[{"nome":"a.svg"}]}', b'{"origine":"https://maker-hub.it","file":[5]}',
          b'{"origine":"https://maker-hub.it","file":[{"nome":"a.zip","b64":"***"}]}',
          payload([("a.svg", svg())] * (link.MAX_FILES + 1)))))
check("consegna senza niente da tagliare (solo la mappa e le note): lo dice",
      "nessun disegno" in (payload_error(payload([("x.zip", zipped([("mappa-montaggio.svg", svg()), ("LEGGIMI.txt", b"x")]))])) or ("", ""))[1])
check("consegna da un sito non ammesso, o senza origine: rifiutata per permesso, prima ancora di guardare i file",
      [(payload_error(payload([("a.svg", svg())], origin=o)) or ("",))[0] for o in ("https://example.com", "null", "", "http://app.maker-hub.it")]
      == ["permesso"] * 4 and (payload_error(payload([("a.svg", svg())], origine=None)) or ("",))[0] == "permesso")
check("…da un file aperto dal disco: solo se concesso",
      link.read_payload(payload([("a.svg", svg())], origin="null"), allow_file=True).kind == "file")

# ================================================================== 6. consegna
got = []
now = [1000.0]
allow = [False]
core = link.Core(lambda arr: got.append(arr) or (True, "fatto!"), version="9.9.9",
                 allow_file=lambda: allow[0], clock=lambda: now[0])
HOST = {"host": f"127.0.0.1:{PORT}"}


def ask(method, path, headers=None, body=b""):
    out = core.handle(link.Request(method, path, dict(HOST, **(headers or {})), body))
    head_, _, body_ = out.partition(b"\r\n\r\n")
    return int(head_.split()[1]), head_.decode("latin-1"), body_


def token_of(page):
    return re.search(r'"token": "([^"]+)"', page.decode()).group(1)


def post(tok, body=None, **headers):
    h = {"origin": f"http://127.0.0.1:{PORT}", "content-type": "application/json", "sec-fetch-site": "same-origin"}
    if tok is not None:
        h["x-flc-token"] = tok
    h.update({k.replace("_", "-"): v for k, v in headers.items()})
    h = {k: v for k, v in h.items() if v is not None}
    st, hd, bd = ask("POST", "/flc/importa", h, body if body is not None else payload([("a.svg", svg())]))
    return st, json.loads(bd) if bd.startswith(b"{") else bd


st, hd, page = ask("GET", "/flc/ponte")
nonce = re.search(r"script-src 'nonce-([^']+)'", hd)
check("la finestrella: pagina HTML con le sue regole (solo il suo script, niente riquadri, niente cache, niente CORS)",
      st == 200 and "text/html" in hd and nonce and f'<script nonce="{nonce.group(1)}">'.encode() in page
      and "default-src 'none'" in hd and "frame-ancestors 'none'" in hd and "connect-src 'self'" in hd
      and "no-store" in hd and "access-control" not in hd.lower() and "cross-origin-opener-policy" not in hd.lower(), hd)
text = page.decode()
check("…non carica niente da fuori: nessuno script, foglio di stile o immagine esterni",
      not re.search(r'(src|href)\s*=\s*["\']', text) and "http://" not in text.replace("http://www.w3.org", "") and "https://" not in text)
check("…dice «pronto» a chi l'ha aperta, accetta il disegno solo da lei, consegna con il gettone e avvisa quando ha fatto",
      "flc:'pronto'" in text and "e.source!==op" in text and "d.flc!=='disegno'" in text and "'X-FLC-Token':C.token" in text
      and "flc:'fatto'" in text and "origine:from" in text and "from=e.origin" in text)
check("…e porta la versione del programma e i testi nella lingua dell'interfaccia",
      '"versione": "9.9.9"' in text and "Aspetto il disegno da MakerHub" in text and "</script><" not in text.split("<script")[1].split("</script>")[0])
tok = token_of(page)
check("ogni apertura ha un gettone diverso, lungo e non indovinabile",
      len(tok) >= 30 and token_of(ask("GET", "/flc/ponte")[2]) != tok)
st, j = post(tok)
check("consegna buona: arriva al programma e la risposta dice com'è andata",
      st == 200 and j == {"ok": True, "messaggio": "fatto!"} and len(got) == 1 and got[0].tool == "Dima Lab", (st, j))
st, j = post(tok)
check("lo stesso gettone non vale due volte", st == 403 and j["ok"] is False and len(got) == 1, (st, j))
for name, kw in (("senza gettone", {"tok": None}), ("con un gettone inventato", {"tok": "x" * 32}),
                 ("da un'altra origine (una pagina che prova a consegnare da sola)", {"origin": "https://app.maker-hub.it"}),
                 ("senza origine (un modulo, un programma)", {"origin": None}), ("con origine «null»", {"origin": "null"}),
                 ("segnata dal browser come «altro sito»", {"sec_fetch_site": "cross-site"}),
                 ("non in JSON (un modulo web)", {"content_type": "text/plain"})):
    fresh = token_of(ask("GET", "/flc/ponte")[2])
    kw = dict(kw)
    st, j = post(kw.pop("tok", fresh), **kw)
    check(f"consegna {name}: rifiutata, e al programma non arriva niente", st == 403 and len(got) == 1, (st, j))
fresh = token_of(ask("GET", "/flc/ponte")[2])
now[0] += link.TOKEN_LIFE + 1
st, j = post(fresh)
check("un gettone scaduto non vale più", st == 403 and len(got) == 1, (st, j))
first = token_of(ask("GET", "/flc/ponte")[2])
for _ in range(link.MAX_TOKENS + 5):
    last = token_of(ask("GET", "/flc/ponte")[2])
check("i gettoni in attesa non crescono senza fine: i più vecchi decadono, l'ultimo vale",
      len(core.tokens) <= link.MAX_TOKENS and post(first)[0] == 403 and post(last)[0] == 200 and len(got) == 2)
st, j = post(token_of(ask("GET", "/flc/ponte")[2]), payload([("a.svg", svg())], origin="https://example.com"))
check("consegna dalla finestrella ma per conto di un sito non ammesso: rifiutata con il motivo",
      st == 403 and "non può mandare" in j["messaggio"] and len(got) == 2, (st, j))
st, j = post(token_of(ask("GET", "/flc/ponte")[2]), payload([("a.svg", svg())], origin="null"))
allow[0] = True
st2, j2 = post(token_of(ask("GET", "/flc/ponte")[2]), payload([("a.svg", svg())], origin="null"))
check("file aperti dal disco: rifiutati, accettati solo quando il programma lo concede",
      st == 403 and st2 == 200 and len(got) == 3 and got[-1].kind == "file", (st, st2))
st, j = post(token_of(ask("GET", "/flc/ponte")[2]), b"{rovinato")
check("consegna con dati rovinati: 400 con il motivo", st == 400 and "leggibile" in j["messaggio"] and len(got) == 3, (st, j))
core.deliver = lambda arr: 1 / 0
st, j = post(token_of(ask("GET", "/flc/ponte")[2]))
check("se il programma inciampa mentre importa, la finestrella riceve comunque una risposta chiara",
      st == 200 and j["ok"] is False and "Non sono riuscito" in j["messaggio"], (st, j))
core.deliver = lambda arr: got.append(arr) or (True, "ok")
check("Host diverso dal nostro (un nome che punta a questo computer, «DNS rebinding»): 403 su tutto",
      [core.handle(link.Request(m, p, {"host": h}, b"")).split()[1] for m, p, h in (
          ("GET", "/flc/ponte", f"evil.example:{PORT}"), ("GET", "/flc/ponte", f"localhost:{PORT}"), ("GET", "/flc/ponte", "127.0.0.1"),
          ("GET", "/flc/ponte", f"127.0.0.1:{PORT + 1}"), ("POST", "/flc/importa", "evil.example"), ("GET", "/", ""))] == [b"403"] * 6)
check("tutto il resto: 404; metodi sbagliati: 405",
      [ask(m, p)[0] for m, p in (("GET", "/"), ("GET", "/favicon.ico"), ("GET", "/flc"), ("GET", "/flc/ponte/x"), ("POST", "/flc/ponte"),
                                 ("GET", "/flc/importa"), ("PUT", "/flc/importa"), ("OPTIONS", "/flc/importa"))]
      == [404, 404, 404, 404, 405, 405, 405, 405])

# ================================================================== 7. ricevitore vero
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()


def talk(parts, port=PORT, pause=0.0, close_early=False):
    """Manda i byte (anche a pezzi) e legge la risposta, da un filo a parte, mentre il programma gira."""
    out = {}

    def work():
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            for part in parts:
                s.sendall(part)
                time.sleep(pause)
            data = b""
            if not close_early:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            s.close()
            out["data"] = data
        except OSError as exc:
            out["error"] = exc

    t = threading.Thread(target=work, name="prova-cliente")
    t.start()
    end = time.time() + 15
    while t.is_alive() and time.time() < end:
        app.processEvents()
        time.sleep(0.003)
    t.join(1)
    for _ in range(5):
        app.processEvents()
    return out


def deliver(files, tool="Dima Lab", origin="https://app.maker-hub.it", port=PORT):
    """Quello che fa la finestrella: prende la pagina (e il gettone), poi consegna. -> (stato, risposta)"""
    page_ = talk([f"GET /flc/ponte HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode()], port)
    if "data" not in page_:
        return None, page_.get("error")
    tok_ = token_of(page_["data"].partition(b"\r\n\r\n")[2])
    body_ = payload(files, origin=origin, tool=tool)
    head_ = (f"POST /flc/importa HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
             f"Content-Type: application/json\r\nSec-Fetch-Site: same-origin\r\nX-FLC-Token: {tok_}\r\n"
             f"Content-Length: {len(body_)}\r\n\r\n").encode()
    out = talk([head_ + body_], port)
    if "data" not in out:
        return None, out.get("error")
    h_, _, b_ = out["data"].partition(b"\r\n\r\n")
    return int(h_.split()[1]), json.loads(b_)


seen = []
rx = link.Receiver(lambda arr: seen.append(arr) or (True, "arrivato"), "1.2.3")
check("appena creato il ricevitore non ascolta", not rx.running() and "error" in talk([GET]))
check("acceso, ascolta sulla sua porta e solo su questo computer (127.0.0.1), mai sulla rete",
      rx.start() and rx.running() and rx.port == PORT and rx.server.serverAddress().toString() == "127.0.0.1"
      and rx.server.serverPort() == PORT, rx.server.serverAddress().toString())
out = talk([GET])
check("risponde alla finestrella e chiude la connessione", out.get("data", b"").startswith(b"HTTP/1.1 200") and b"FreeLaserCut" in out["data"], out)
out = talk([GET[:10], GET[10:25], GET[25:]], pause=0.05)
check("una richiesta che arriva a pezzi viene ricomposta", out.get("data", b"").startswith(b"HTTP/1.1 200"), out)
st, j = deliver([("dima.svg", svg())])
check("una consegna vera, via rete locale: arriva", st == 200 and j["ok"] and len(seen) == 1 and seen[0].drawings[0].name == "dima.svg", (st, j))
big = [("grande.svg", svg(extra="<!--" + "x" * 3_000_000 + "-->"))]
st, j = deliver(big)
check("un disegno di 3 MB arriva intero", st == 200 and len(seen) == 2 and len(seen[1].drawings[0].data) > 3_000_000, (st, j))
out = talk([b"CIAO\r\n\r\n"])
check("una richiesta senza senso riceve 400 e basta", out.get("data", b"").startswith(b"HTTP/1.1 400"), out)
out = talk([f"POST /flc/importa HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nContent-Length: 999999999999\r\n\r\n".encode()])
check("chi dichiara un corpo enorme riceve subito 413", out.get("data", b"").startswith(b"HTTP/1.1 413"), out)
talk([f"POST /flc/importa HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nContent-Length: 500\r\n\r\nmeta".encode()], close_early=True)
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
check("chi chiude a metà non lascia niente appeso, e il ricevitore continua a rispondere",
      not rx.socks and talk([GET]).get("data", b"").startswith(b"HTTP/1.1 200"), rx.socks)
other = link.Receiver(lambda arr: (True, ""), "x")
check("la porta è una sola: un secondo ricevitore non parte e lo dice", other.start() is False and not other.running())
rx.stop()
check("spento, non risponde più e non tiene gettoni", not rx.running() and "error" in talk([GET]) and not rx.core.tokens)
check("…e si può riaccendere", rx.start() and talk([GET]).get("data", b"").startswith(b"HTTP/1.1 200"))
rx.stop()

# ================================================================== 8. finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

threads0 = {t.name for t in threading.enumerate()}
w = MainWindow()
w.resize(1400, 900)
ed = w.editor
BX, BY = w.profile.bed_x, w.profile.bed_y
names = ["makerhub_dima", "makerhub_forma", "makerhub_hinge", "makerhub_split", "makerhub_receive"]
pal = getattr(getattr(w, "banco", None), "palette", None)


def searchable():
    pal.collect()
    return [a_ for a_, _p in pal.entries]


check("senza codice: il menu MakerHub è nascosto, le sue voci pure, e non aprono né ascoltano niente",
      not w.m_makerhub.menuAction().isVisible() and not any(w.acts[n].isVisible() for n in names)
      and w.makerhub_open("dima") is False and w.makerhub_receive(True) is False and not opened
      and (w.mh_link is None or not w.mh_link.running()) and "error" in talk([GET]))
if pal is not None:
    check("Banco: senza codice la ricerca dei comandi non trova nessuna voce di MakerHub", not [n for n in names if w.acts[n] in searchable()])
tops = [a_.text().replace("&", "") for a_ in w.menuBar().actions()]
check("in alto non c'è un menu MakerHub, e la vecchia voce «Scatola a incastri» non c'è più",
      "MakerHub" not in tops and "makerhub_box" not in w.acts and not hasattr(w, "makerhub_box"), tops)
check("con il codice il menu compare, con tutte le sue voci", w.admin_dialog(code="prova") is True
      and w.m_makerhub.menuAction().isVisible() and all(w.acts[n].isVisible() for n in names)
      and w.acts["relief"].isVisible() and w.acts["print_cut"].isVisible())
tools = [m.menu() for m in w.menuBar().actions() if m.menu() is not None and w.acts["puzzle"] in m.menu().actions()]
acts = tools[0].actions() if tools else []
sub = w.m_makerhub.menuAction()
check("sta nel menu Strumenti, dopo Stampa e taglia e prima delle voci per le foto",
      len(tools) == 1 and sub in acts and acts.index(sub) == acts.index(w.acts["print_cut"]) + 1
      and acts.index(sub) < acts.index(w.acts["photo"]), [a_.text() for a_ in acts][-12:])
check("si chiama «MakerHub» e ha il loro logo arancione", sub.text() == "MakerHub" and not sub.icon().isNull()
      and sub.icon().pixmap(QSize(40, 40)).toImage().pixelColor(20, 4).red() > 200)
inside = [a_ for a_ in w.m_makerhub.actions()]
check("dentro: Dima Lab, Forma Lab, Hinge Lab, Split Lab con a che cosa servono, una riga, «Ricevi qui i disegni» con la spunta",
      [a_.text().split(" – ")[0] for a_ in inside[:4]] == ["Dima Lab", "Forma Lab", "Hinge Lab", "Split Lab"]
      and all(" – " in a_.text() for a_ in inside[:4]) and inside[4].isSeparator() and inside[5] is w.acts["makerhub_receive"]
      and inside[5].isCheckable() and not inside[5].isChecked() and len(inside) == 6, [a_.text() for a_ in inside])
if pal is not None:
    check("Banco: con il codice la ricerca dei comandi trova le cinque voci", all(w.acts[n] in searchable() for n in names))
del opened[:], boxes[:]
dialogs0 = len(w.findChildren(QDialog))
w.acts["makerhub_hinge"].trigger()
msg = w.statusBar().currentMessage()
check("un clic su uno strumento apre nel browser, una volta, il sito di MakerHub", opened == [SITE], opened)
check("…accende l'ascolto (la spunta compare) e lo ricorda", w.mh_link is not None and w.mh_link.running() and w.acts["makerhub_receive"].isChecked()
      and w.qs.value("makerhub/used") in (True, "true") and talk([GET]).get("data", b"").startswith(b"HTTP/1.1 200"))
check("…e la barra in basso dice che cosa fare: scegliere Hinge Lab nel loro menu e premere «Manda a FreeLaserCut»",
      "Hinge Lab" in msg and "menu a sinistra" in msg and "Manda a FreeLaserCut" in msg, msg)
check("…senza finestre né domande, e senza fili in più", not boxes and len(w.findChildren(QDialog)) == dialogs0
      and not [t.name for t in threading.enumerate() if t.name not in threads0 and ("makerhub" in t.name.lower() or "http" in t.name.lower())])
st, j = deliver([("a.svg", svg())], origin="https://example.com")
check("un sito che non è MakerHub non riesce a mandare niente", st == 403 and not ed.doc.shapes and w.mh_last is None, (st, j))
browser[0] = False
del opened[:]
ok = w.makerhub_open("dima")
msg = w.statusBar().currentMessage()
check("se il browser non si apre lo dice, con l'indirizzo da copiare", ok is False and opened == [SITE] and SITE in msg, msg)
browser[0] = True
check("togliendo la spunta l'ascolto si spegne davvero, e resta spento",
      w.makerhub_receive(False) is False and not w.mh_link.running() and "error" in talk([GET])
      and not w.acts["makerhub_receive"].isChecked() and w.qs.value("makerhub/receive") in (False, "false"))
del opened[:]
w.acts["makerhub_split"].trigger()
msg = w.statusBar().currentMessage()
check("con la spunta tolta, aprire uno strumento non riaccende l'ascolto: la barra dice di scaricare e usare File → Importa",
      opened == [SITE] and not w.mh_link.running() and "Split Lab" in msg and "File → Importa" in msg and "Manda a" not in msg, msg)
w.acts["makerhub_receive"].trigger()
check("rimettendo la spunta l'ascolto riparte, e la barra spiega che si ascolta solo questo computer",
      w.mh_link.running() and w.acts["makerhub_receive"].isChecked() and w.qs.value("makerhub/receive") in (True, "true")
      and "solo questo computer" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
w._makerhub_stop()
blocker = socket.socket()
if sys.platform != "win32":  # Linux: la porta appena lasciata libera si può riprendere subito (su Windows lo è già)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
blocker.bind(("127.0.0.1", PORT))
blocker.listen(1)
del opened[:]
ok = w.makerhub_open("forma")
msg = w.statusBar().currentMessage()
check("porta occupata da un altro programma: lo strumento si apre lo stesso, la spunta resta tolta",
      ok is True and opened == [SITE] and not w.mh_link.running() and not w.acts["makerhub_receive"].isChecked(), msg)
w._makerhub_start()
check("…e il programma dice che la porta è occupata e come fare (File → Importa)",
      str(PORT) in w.statusBar().currentMessage() and "File → Importa" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
blocker.close()
w._makerhub_resume()
check("all'avvio, chi ha già usato gli strumenti e ha lasciato la spunta ritrova l'ascolto acceso", w.mh_link.running())
w._makerhub_stop()
w.qs.setValue("makerhub/receive", False)
w._makerhub_resume()
off1 = w.mh_link.running()
w.qs.setValue("makerhub/receive", True)
w.qs.setValue("makerhub/used", False)
w._makerhub_resume()
check("…chi ha tolto la spunta, o non li ha mai usati, no", not off1 and not w.mh_link.running())
w.qs.setValue("makerhub/used", True)
w._makerhub_start()

# ================================================================== 9. disegni sul piano


def plates():
    out = []
    for i, p in enumerate(ed.doc.plates):
        b = ops.union_bounds(p.shapes) if p.shapes else None
        out.append((ed.doc.plate_name(i), len(p.shapes), round(b.width(), 1) if b else 0, round(b.height(), 1) if b else 0))
    return out


def fresh():
    ed.dirty = False
    w.file_new()
    w.mh_last = None


def boxes_of(shapes):
    return [(s.bounds().left(), s.bounds().top(), s.bounds().right(), s.bounds().bottom()) for s in shapes]


undo0 = len(ed.undo_stack)
st, j = deliver([("dima-100x70.svg", svg(100, 70))])
b = ops.union_bounds(ed.doc.shapes)
check("un disegno solo: arriva sul piano attivo, a misura vera, al centro del piano, selezionato",
      st == 200 and j["ok"] and plates() == [("Piano 1", 1, 100.0, 70.0)] and abs(b.center().x() - BX / 2) < 0.01
      and abs(b.center().y() - BY / 2) < 0.01 and ed.selection == ed.doc.shapes, (st, j, plates()))
check("…è una sola azione, e la barra in basso dice da dove arriva",
      len(ed.undo_stack) == undo0 + 1 and ed.undo_label() == "Importa da MakerHub" and "MakerHub (Dima Lab)" in w.statusBar().currentMessage(),
      (ed.undo_label(), w.statusBar().currentMessage()))
check("…il browser riceve la conferma", "il disegno è in FreeLaserCut" in j["messaggio"], j)
ed.undo()
check("un Annulla lo toglie", not ed.doc.shapes)
fresh()
st, j = deliver([("forma-lab-box.zip", zipped([("piano-1.svg", svg(355, 233)), ("montaggio.txt", b"x"), ("progetto.json", b"{}")]))], "Forma Lab")
check("uno ZIP con un foglio solo: come un disegno solo, senza piani nuovi né nomi cambiati",
      plates() == [("Piano 1", 1, 355.0, 233.0)] and "Forma Lab" in w.statusBar().currentMessage(), plates())
fresh()
st, j = deliver([("split-lab.zip", split)], "Split Lab")
msg = w.statusBar().currentMessage()
check("uno ZIP con tre fogli: tre piani di lavoro con il nome dello strumento e il numero del foglio, nell'ordine",
      plates() == [("Split Lab 1", 1, 60.0, 40.0), ("Split Lab 2", 1, 120.0, 80.0), ("Split Lab 10", 1, 30.0, 30.0)], plates())
check("…si resta sul primo foglio, con il suo disegno selezionato, e ogni foglio è al centro del suo piano",
      ed.doc.current == 0 and ed.selection == ed.doc.shapes
      and all(abs(ops.union_bounds(p.shapes).center().x() - BX / 2) < 0.01 for p in ed.doc.plates), ed.doc.current)
check("…la barra dice quanti fogli e che la mappa di montaggio non è da tagliare",
      "3 fogli" in msg and "Split Lab" in msg and "mappa di montaggio" in msg.lower(), msg)
fresh()
from freelasercut.core.document import RectShape  # noqa: E402

mine = RectShape(10, 10, layer=1)
ed.add([mine], "prova")
st, j = deliver([("split-lab.zip", zipped([("piano-1.svg", svg(60, 40)), ("piano-2.svg", svg(120, 80))]))], "Split Lab")
check("se il piano attivo ha già un disegno non viene toccato: i fogli vanno tutti su piani nuovi",
      plates()[0][:2] == ("Piano 1", 1) and [p[0] for p in plates()[1:]] == ["Split Lab 1", "Split Lab 2"]
      and ed.doc.plates[0].shapes == [mine] and ed.doc.current == 1, (plates(), ed.doc.current))
fresh()
st, j = deliver([("hinge-lab-progetto.zip", hinge)], "Hinge Lab")
bx = boxes_of(ed.doc.shapes)
check("uno ZIP di pezzi: tutti sullo stesso piano, uno accanto all'altro, senza sovrapporsi, e la mappa resta fuori",
      plates()[0][:2] == ("Piano 1", 4) and len(ed.doc.plates) == 1
      and not any(a_[0] < c[2] and c[0] < a_[2] and a_[1] < c[3] and c[1] < a_[3] for i, a_ in enumerate(bx) for c in bx[:i])
      and "mappa di montaggio" in w.statusBar().currentMessage().lower(), (plates(), bx))
u = ops.union_bounds(ed.doc.shapes)
check("…l'insieme è al centro del piano e, se il piano è più stretto della fila, i pezzi vanno a capo",
      abs(u.center().x() - BX / 2) < 0.01 and abs(u.center().y() - BY / 2) < 0.01
      and (u.width() <= max(BX, 436.0) + 0.01), (u.width(), BX))
check("…e si tolgono tutti con un solo Annulla", (ed.undo(), len(ed.doc.shapes))[1] == 0)
fresh()
st, j = deliver([("larghi.zip", zipped([(f"p{i}.svg", svg(BX * 0.6, 30 + i)) for i in range(3)]))], "Hinge Lab")
ys = sorted(round(s.bounds().top(), 1) for s in ed.doc.shapes)
check("tre pezzi larghi più di mezzo piano: uno per riga, staccati di 5 mm", len(set(ys)) == 3 and ys[1] - ys[0] >= 30 + 4.9, ys)
fresh()
st, j = deliver([("scritta.svg", svg(extra='<text x="5" y="20">Ciao</text><text x="5" y="40">Mondo</text>'))], "Forma Lab")
check("un disegno con scritte non convertite: il resto arriva e la barra dice che le scritte no",
      plates() == [("Piano 1", 1, 100.0, 70.0)] and "scritte" in w.statusBar().currentMessage().lower(), w.statusBar().currentMessage())
fresh()
st, j = deliver([("enorme.svg", svg(BX + 300, 50))])
check("un disegno più grande del piano arriva lo stesso, e la barra lo dice",
      plates()[0][1] == 1 and "più grande del piano" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
fresh()
st, j = deliver([("rotto.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0'), ("vuoto.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')])
check("un disegno illeggibile o vuoto: niente sul piano, e al browser arriva il motivo con il nome del file",
      st == 200 and j["ok"] is False and "rotto.svg" in j["messaggio"] and not ed.doc.shapes and w.mh_last is None, (st, j))
st, j = deliver([("misto.zip", zipped([("a.svg", svg(50, 50)), ("rotto.svg", b"<svg"), ("b.svg", svg(40, 40))]))])
check("uno buono e uno rotto nello stesso ZIP: i buoni arrivano", j["ok"] and plates()[0][1] == 2, (j, plates()))
fresh()
ed.begin("trascinamento a metà")
st, j = deliver([("dima.svg", svg())])
check("a metà di un'altra azione (o con una finestra aperta) il disegno aspetta, e al browser lo si dice",
      st == 200 and j["ok"] and "occupato" in j["messaggio"] and not ed.doc.shapes and w.mh_last is None, (st, j))
ed.cancel()
end = time.time() + 3
while w.mh_last is None and time.time() < end:
    app.processEvents()
    time.sleep(0.02)
check("…ed entra da solo appena il programma è libero", plates() == [("Piano 1", 1, 100.0, 70.0)] and w.mh_last is not None, plates())
fresh()
dlg = QDialog(w)
dlg.setModal(True)
dlg.show()
app.processEvents()
st, j = deliver([("dima.svg", svg())])
waited = not ed.doc.shapes and "occupato" in j["messaggio"]
dlg.close()
end = time.time() + 3
while w.mh_last is None and time.time() < end:
    app.processEvents()
    time.sleep(0.02)
check("lo stesso con una finestra di dialogo aperta", waited and len(ed.doc.shapes) == 1, (waited, plates()))
fresh()
st, j = deliver([("da-disco.svg", svg())], origin="null")
check("con le funzioni in prova sbloccate si accettano anche gli strumenti aperti dal disco (le prove di Ale)", st == 200 and len(ed.doc.shapes) == 1, (st, j))
check("in tutto questo il laser e la macchina non sono stati toccati", not w.ctl.job_active and not w.ctl.connected and not boxes)
fresh()
arr = link.read_payload(payload([("a.svg", svg())]))
check("nascondendo di nuovo le funzioni in prova: menu nascosto, ascolto spento, niente si apre né si riceve",
      w.admin_dialog() is False and not w.m_makerhub.menuAction().isVisible() and not any(w.acts[n].isVisible() for n in names)
      and not w.mh_link.running() and "error" in talk([GET]) and w.makerhub_open("dima") is False
      and w._makerhub_arrived(arr)[0] is False and not ed.doc.shapes)
w.admin_dialog(code="prova")
w._makerhub_start()
ed.dirty = False
w.qs.setValue("autosave_pending", False)
from PySide6.QtGui import QCloseEvent  # noqa: E402

link_ = w.mh_link
w.closeEvent(QCloseEvent())
check("chiudendo il programma l'ascolto si spegne", not link_.running() and "error" in talk([GET]))

# ================================================================== 10. lo script per il sito
js = src("tools", "makerhub", "freelasercut-link.js")
check("lo script per le pagine di MakerHub usa la stessa porta e lo stesso indirizzo della finestrella",
      "'47821'" in js and REAL_PORT == 47821 and "'/flc/ponte'" in js and link.BRIDGE_PATH == "/flc/ponte"
      and "'http://127.0.0.1:' + PORT" in js)
check("…le stesse parole («pronto», «disegno», «fatto») e la stessa versione del dialogo",
      all(f"'{k}'" in js and f"'{k}'" in link._BRIDGE_JS for k in ("pronto", "disegno", "fatto"))
      and "var PROTOCOL = 1;" in js and link.PROTOCOL == 1)
check("…non fa nessuna chiamata di rete: apre solo la finestrella (niente fetch, XMLHttpRequest, WebSocket, immagini-spia)",
      not re.search(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|new Image|EventSource|\.src\s*=", js) and js.count("window.open(") == 1)
check("…manda il disegno solo alla finestrella di FreeLaserCut (mai «a chiunque») e ascolta solo lei",
      re.search(r"postMessage\(\{ flc: 'disegno'.*?\}, FLC\)", js, re.S) and "'*'" not in js
      and "e.origin !== FLC" in js and "e.source !== j.win" in js)
check("…lascia stare i pulsanti di prima, non usa cookie né memoria del browser, e ha la sua licenza libera in testa",
      "localStorage" not in js and "document.cookie" not in js and "licenza MIT" in js.split("*/")[0]
      and "nativeClick.apply(this, arguments)" in js)
kit = [f for _d, _s, fs in os.walk(os.path.join(ROOT, "tools", "makerhub")) for f in fs]
check("nel repository c'è solo il nostro script con le istruzioni: i programmi di MakerHub no", sorted(kit) == ["LEGGIMI.md", "freelasercut-link.js"], kit)

# ================================================================== 11. testi
for n in names:
    h = help_texts.lookup(n)
    check(f"scheda d'aiuto di {n}: c'è, dice che MakerHub è esterno e come arriva il disegno",
          h is not None and "(in prova)" in h[0] and ("esterno" in h[1] or n == "makerhub_receive")
          and "Manda a FreeLaserCut" in h[1], h)
check("la scheda d'aiuto della vecchia voce non c'è più", help_texts.lookup("makerhub_box") is None)
keys = set()
for text in (code, code_link, src("freelasercut", "ui", "main_window.py"), src("freelasercut", "ui", "help_texts.py")):
    for m in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', text):
        parts = re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1))
        try:
            k = "".join(json.loads(p_) for p_ in parts)
        except ValueError:
            continue
        if "MakerHub" in k or text in (code, code_link):  # i due file di MakerHub per intero; degli altri, i testi che lo nominano
            keys.add(k)
keys |= {"Ricevi qui i disegni", "Non riesco a leggere il disegno arrivato ({0}).",
         "FreeLaserCut è occupato: il disegno entrerà appena chiudi la finestra aperta nel programma.",
         "La mappa di montaggio non è da tagliare: resta sul sito.",
         "Le scritte non sono arrivate: sul sito vanno convertite in tracciati."}
check("testi da tradurre trovati", len(keys) == 41 and all(t.what in keys for t in real), len(keys))
menu_names = {"en": "File → Import", "es": "Archivo → Importar", "fr": "Fichier → Importer", "pt": "Arquivo → Importar"}
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    brand = [k for k in keys if ("MakerHub" in k and "MakerHub" not in (loc.get(k) or "MakerHub"))
             or ("Manda a FreeLaserCut" in k and "Manda a FreeLaserCut" not in (loc.get(k) or "Manda a FreeLaserCut"))]
    tips = [loc.get(k) or "" for k in keys if "File → Importa" in k]
    check(f"traduzioni {lang}: tutti i testi, con MakerHub e il nome del pulsante «Manda a FreeLaserCut» intatti (sul sito è scritto "
          f"così) e il menu File → Importa chiamato come in quella lingua",
          not miss and not bad and not brand and tips and all(menu_names[lang] in t for t in tips), (miss[:3], bad[:3], brand[:3]))
    old = [k for k in loc if re.search(r"Scatola a incastri|scatole a incastri|Collega MakerHub|FreeLaserCut Live|Genera il codice", k)]
    check(f"traduzioni {lang}: i testi della vecchia voce non ci sono più", not old, old[:3])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
