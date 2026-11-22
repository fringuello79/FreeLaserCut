# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.0: la Galleria dei lavori condivisi (freelasercut/galleria.py, ui/dialogs_galleria.py).

Il servizio vero non si tocca: le prove parlano con un servizio finto su 127.0.0.1 (tests/galleria_finta.py), che
registra tutto quello che riceve. Una prova per ogni riga della tabella dei casi (freeburn/galleria.md):
controlli sui testi e sul modulo, pacchetto ripulito, che cosa parte davvero, risposte ostili del servizio,
file scaricati ostili, finestre (Classica e Banco).

Uso: python tests/test_v220_galleria.py [classica|banco]
"""
import io
import json
import os
import socket
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="flc_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(TMP, "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_MODULI"] = "1"
os.environ["FLC_LANG"] = "it"
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"

from galleria_finta import Finta  # noqa: E402

finta = Finta()
os.environ["FLC_GALLERIA_URL"] = finta.url

from PIL import Image  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from freelasercut import admin, galleria as G  # noqa: E402
from freelasercut.core.document import Document, EllipseShape, RectShape  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def codice(fn, *a, **k):
    try:
        fn(*a, **k)
    except G.Errore as exc:
        return exc.codice
    return None


app = QApplication([])
from freelasercut.ui import dialogs_galleria as DG, help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


def spin(cond=None, secondi=15.0):
    fine = time.time() + secondi
    while time.time() < fine:
        app.processEvents()
        if cond is None or cond():
            return True
        time.sleep(0.01)
    return False


def zip_di(voci, metodo=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", metodo) as z:
        for nome, dati in voci:
            z.writestr(nome, dati)
    return b.getvalue()


def png(w=40, h=30, colore=(200, 30, 30)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), colore).save(b, "PNG")
    return b.getvalue()


BUONO = json.dumps({"format": "freelasercut", "version": 1, "name": "x", "shapes": [{"kind": "rect"}], "layers": {}})

# ====================================================================== testi e modulo
print("--- testi e modulo")
check("testi normali accettati", all(G.controlla_testo(t) is None for t in (
    "Portachiavi con il nome, 3 mm", "Città di L'Aquila 2026", "Scatola 200 x 150", "")))
check("link, email, telefono, parole vietate, lettere ripetute, tutto maiuscolo: rifiutati col loro motivo",
      [G.controlla_testo(t) for t in ("vai su www.sito.com", "scrivi a mario@posta.it", "chiama +39 333 1234567",
                                      "porno gratis", "Bellooooooooo", "SCATOLA BELLISSIMA GRANDE")]
      == ["link", "mail", "telefono", "parole", "ripetuto", "maiuscolo"])
BASE = {"titolo": "Scatola di Natale", "descrizione": "Incastri da 3 mm", "categoria": "scatole", "materiale": "Tiglio",
        "spessore_mm": 3.0, "laser_famiglia": "Longer B1 40W", "potenza_w": 40.0, "tipo": "entrambi", "tempo_s": 900,
        "licenza": "cc-by-4.0", "autore_nome": "Ale", "regole_accettate": True, "opera_mia": True}
s = G.controlla_scheda(BASE)
check("modulo giusto: scheda pronta, con la versione del programma e senza campi in più",
      s["titolo"] == "Scatola di Natale" and s["spessore_mm"] == 3.0 and s["versione_flc"] and s["tempo_s"] == 900
      and set(s) <= {"titolo", "descrizione", "categoria", "materiale", "spessore_mm", "laser_famiglia", "potenza_w",
                     "tipo", "larghezza_mm", "altezza_mm", "tempo_s", "licenza", "autore_nome", "versione_flc",
                     "regole_accettate", "opera_mia"}, sorted(s))
check("spessore e potenza a zero = non indicati", G.controlla_scheda({**BASE, "spessore_mm": 0, "potenza_w": 0})["potenza_w"] is None)
check("titolo corto o lungo, materiale mancante, descrizione lunga: ognuno col suo messaggio",
      [codice(G.controlla_scheda, {**BASE, **x}) for x in ({"titolo": "ab"}, {"titolo": "x" * 81}, {"materiale": ""},
                                                          {"descrizione": "x " * 400})]
      == ["titolo", "titolo", "materiale", "descrizione"])
check("categoria, licenza o numeri fuori dai limiti: rifiutati",
      [codice(G.controlla_scheda, {**BASE, **x}) for x in ({"categoria": "armi"}, {"licenza": "mia"}, {"tipo": ""},
                                                          {"spessore_mm": 500}, {"potenza_w": float("nan")})] == ["campo"] * 5)
check("le due caselle sono obbligatorie", [codice(G.controlla_scheda, {**BASE, **x}) for x in (
    {"regole_accettate": False}, {"opera_mia": False})] == ["caselle", "caselle"])
check("testo non ammesso nel titolo o nel nome: detto prima di mandare",
      codice(G.controlla_scheda, {**BASE, "titolo": "Visita www.sito.com"}) == "testo_link"
      and codice(G.controlla_scheda, {**BASE, "autore_nome": "a@b.it"}) == "testo_mail")
check("ogni errore ha una frase per la persona, mai il codice nudo",
      all(len(G.testo_errore(c)) > 15 for c in ("rete", "risposta", "vuoto", "grande", "foto", "titolo", "doppione", "limite",
                                                "troppe", "non_trovato", "proprio", "chiave", "file", "indirizzo", "boh")))
check("0.22.0: chi descrive il lavoro come esplicito o per adulti è fermato già qui (la prova del portachiavi)",
      [G.controlla_testo(t) for t in ("Portachiavi con contenuto esplicito", "Explicit keychain", "Llavero erótico",
                                      "Porte-clés sexy")] == ["parole"] * 4)
check("…ma «legno nudo», «hard maple» e «sesto senso» passano",
      all(G.controlla_testo(t) is None for t in ("Tagliere in legno nudo", "Hard maple 6 mm", "Sesto senso")))
check("otto regole, brevi", len(G.regole()) == 8 and all(20 < len(r) < 320 for r in G.regole()))

# ====================================================================== indirizzo del servizio
print("--- indirizzo")
vero = os.environ.pop("FLC_GALLERIA_URL")
check("indirizzo di serie: https", G.base() == (G.BASE_URL, False) and G.BASE_URL.startswith("https://"))
os.environ["FLC_GALLERIA_URL"] = "http://galleria.esempio.it/v1"
check("http fuori da 127.0.0.1: non ci si collega", codice(G.base) == "indirizzo" and codice(G.elenco) == "indirizzo")
os.environ["FLC_GALLERIA_URL"] = "ftp://127.0.0.1/v1"
check("altri protocolli: no", codice(G.base) == "indirizzo")
os.environ["FLC_GALLERIA_URL"] = vero
check("http verso 127.0.0.1: solo per le prove", G.base() == (vero, True))

# ====================================================================== finestra e comandi
print("--- comandi")
w = MainWindow()
qs = w.qs
acts = w.m_file.actions()
a1, a2 = w.acts.get("gallery_share"), w.acts.get("gallery_open")
check("i due comandi sono nel menu File subito dopo «Salva con nome»",
      a1 in acts and a2 in acts and acts.index(a1) == acts.index(w.acts["save_as"]) + 1 and acts.index(a2) == acts.index(a1) + 1)
check("0.22.0: si vedono per tutti, senza sbloccare niente", a1.isVisible() and a2.isVisible() and not admin.unlocked(qs))
admin.set_unlocked(qs, True)
w._apply_admin()
admin.set_unlocked(qs, False)
w._apply_admin()
check("…e restano anche dopo aver tolto le funzioni in prova", a1.isVisible() and a2.isVisible())
check("schede d'aiuto dei due comandi", all(help_texts.lookup(k) for k in ("gallery_share", "gallery_open")))
finta.richieste.clear()
check("progetto vuoto: «Condividi» lo dice e non apre il modulo", w.gallery_share() is None and "vuoto" in w.ultimo_avviso
      and not finta.richieste, getattr(w, "ultimo_avviso", ""))

# ====================================================================== installazione
print("--- installazione")
i1 = G.installazione(qs)
check("numero dell'installazione: 32 cifre a caso, lo stesso alla seconda richiesta",
      len(i1) == 32 and int(i1, 16) >= 0 and G.installazione(qs) == i1)
i2 = G.azzera_installazione(qs)
check("si può azzerare: ne nasce uno nuovo", i2 != i1 and G.installazione(qs) == i2)

# ====================================================================== pacchetto
print("--- pacchetto")
SEGRETO = os.path.join(TMP, "CARTELLA-SEGRETA-di-Mario", "progetto-RISERVATO.flcut")
os.makedirs(os.path.dirname(SEGRETO))
r = RectShape(80, 50, layer=1)
r.set_transform(QTransform.fromTranslate(20, 30))
e = EllipseShape(40, 40, layer=2) if EllipseShape.__init__.__code__.co_argcount >= 3 else EllipseShape()
e.set_transform(QTransform.fromTranslate(120, 40))
w.editor.add([r, e], "prova")
doc = w.editor.doc
doc.layer(2).mode = "fill"
doc.save(SEGRETO)
doc.name = "progetto-RISERVATO"
r.name = "C:\\Users\\Mario\\Desktop\\logo-RISERVATO-cliente.svg" if hasattr(r, "name") else None
prima_path, prima_nome, sporco = doc.path, doc.name, w.editor.dirty
dati, meta, imp = G.progetto_ripulito(doc, "Scatola di Natale")
check("il progetto aperto resta com'era: stesso file, stesso nome", doc.path == prima_path and doc.name == prima_nome
      and w.editor.dirty == sporco)
check("nel file che parte il nome è il titolo scritto nel modulo", meta["name"] == "Scatola di Natale" and "current" not in meta)
check("niente percorsi né nomi di cartelle nel file che parte",
      b"CARTELLA-SEGRETA" not in dati and "CARTELLA-SEGRETA" not in json.dumps(meta) and "Users" not in json.dumps(meta)
      and "progetto-RISERVATO" not in json.dumps(meta), json.dumps(meta)[:120])
check("il file che parte è un progetto valido e si riapre con le sue forme",
      G.controlla_progetto(dati)["format"] == "freelasercut" and len(G.controlla_progetto(dati)["shapes"]) == 2)
check("nessun file temporaneo lasciato in giro", not [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("flc-galleria-")])
nomi = {"shapes": [{"name": "C:\\Users\\Mario\\Desktop\\cliente-SEGRETO\\logo.svg", "children": [{"name": "/home/mario/segreto/pezzo.dxf"}]},
                   {"name": "Cerchio grande"}]}
G._ripulisci(nomi)
check("nomi degli oggetti che sono percorsi: resta solo il nome del file; i nomi normali restano",
      [nomi["shapes"][0]["name"], nomi["shapes"][0]["children"][0]["name"], nomi["shapes"][1]["name"]] == ["logo.svg", "pezzo.dxf", "Cerchio grande"], nomi)
doc.plates[0].name = "D:\\Lavori\\cliente-SEGRETO\\piano uno"
_d, _m, _i = G.progetto_ripulito(doc, "Scatola di Natale")
check("nome del piano che è un percorso: nel file che parte resta solo l'ultima parte",
      _m["plates"][0]["name"] == "piano uno" and b"cliente-SEGRETO" not in _d and doc.plates[0].name.startswith("D:"), _m.get("plates"))
doc.plates[0].name = ""
_, _, imp2 = G.progetto_ripulito(doc, "Un altro titolo")
r.w = 81.0
_, _, imp3 = G.progetto_ripulito(doc, "Scatola di Natale")
r.w = 80.0
check("impronta: la stessa cambiando solo il titolo, diversa cambiando il disegno", imp == imp2 and imp != imp3 and len(imp) == 64)

FOTO = os.path.join(TMP, "foto-pezzo.jpg")
im = Image.new("RGB", (3000, 2000), (120, 90, 40))
ex = im.getexif()
ex[0x0112] = 6  # girata di 90°
ex[0x010F] = "MarcaDelTelefonoSegreta"
ex[0x8825] = {1: "N", 2: (41.0, 59.0, 0.0)}  # posizione GPS
im.save(FOTO, "JPEG", exif=ex, quality=90)
grande, piccola = G.foto_pronta(FOTO)
fg = Image.open(io.BytesIO(grande))
check("foto del pezzo: girata nel verso giusto, ridotta a 1600 pixel, entro 1 MB",
      fg.size == (1067, 1600) and len(grande) <= G.MAX_FOTO and grande[:3] == b"\xff\xd8\xff", f"{fg.size} {len(grande)}")
check("foto senza dati EXIF: niente posizione, niente marca del telefono",
      not dict(fg.getexif()) and b"MarcaDelTelefonoSegreta" not in grande and b"MarcaDelTelefonoSegreta" not in piccola)
check("miniatura entro 120 KB", len(piccola) <= G.MAX_MINI and max(Image.open(io.BytesIO(piccola)).size) == 512)
NONFOTO = os.path.join(TMP, "finta.jpg")
open(NONFOTO, "w").write("non sono una foto")
check("file che non è una foto: detto con chiarezza", codice(G.foto_pronta, NONFOTO) == "foto" and codice(G.foto_pronta, NONFOTO + "x") == "foto")
p = G.prepara(doc, "Scatola di Natale", [FOTO])
ap = Image.open(io.BytesIO(p.anteprima))
check("pacchetto: anteprima PNG stretta sul disegno (lato lungo 800), miniatura JPEG, una foto, misure in mm",
      p.anteprima[:4] == b"\x89PNG" and max(ap.size) == 800 and len(p.anteprima) <= G.MAX_ANTEPRIMA and p.mini[:3] == b"\xff\xd8\xff"
      and len(p.mini) <= G.MAX_MINI and len(p.foto) == 1 and abs(p.larghezza_mm - 140) < 1 and abs(p.altezza_mm - 50) < 1 and p.forme == 2,
      f"{ap.size} {p.larghezza_mm}×{p.altezza_mm}")
px = ap.convert("RGB")
bianchi = sum(1 for x in range(0, ap.width, 7) for y in range(0, ap.height, 7) if px.getpixel((x, y)) == (255, 255, 255))
tot = len(range(0, ap.width, 7)) * len(range(0, ap.height, 7))
check("anteprima: fondo bianco con il disegno sopra (il livello a riempimento è pieno)", 0.3 < bianchi / tot < 0.97, f"{bianchi}/{tot}")
check("parti da mandare: progetto, anteprima, mini, foto1, foto1mini", list(p.parti()) == ["progetto", "anteprima", "mini", "foto1", "foto1mini"])
check("progetto vuoto: non si prepara niente", codice(G.prepara, Document(), "Vuoto") == "vuoto")
vecchio = G.MAX_PROGETTO
G.MAX_PROGETTO = 200
check("progetto oltre il massimo: detto prima di mandare", codice(G.prepara, doc, "Scatola di Natale") == "grande")
G.MAX_PROGETTO = vecchio

# ====================================================================== controllo dei file
print("--- controllo dei file .flcut")
check("progetto buono, con un'immagine", G.controlla_progetto(zip_di([("project.json", BUONO), ("images/a1b2.png", png())]), immagini=True)["shapes"])
cattivi = {
    "non è uno ZIP": b"ciao" * 20,
    "manca project.json": zip_di([("images/a.png", png())]),
    "file in più": zip_di([("project.json", BUONO), ("leggimi.txt", "x")]),
    "percorso che esce dalla cartella": zip_di([("project.json", BUONO), ("../../autorun.bat", "x")]),
    "programma dentro": zip_di([("project.json", BUONO), ("images/virus.exe", "MZ")]),
    "file gonfiato apposta": zip_di([("project.json", BUONO), ("images/bomba.png", b"\0" * 3_000_000)]),
    "JSON rovinato": zip_di([("project.json", "{ non json")]),
    "JSON di un altro programma": zip_di([("project.json", json.dumps({"format": "altro", "shapes": []}))]),
    "forme che non sono un elenco": zip_di([("project.json", json.dumps({"format": "freelasercut", "shapes": "x"}))]),
}
check("file ostili: tutti rifiutati", all(codice(G.controlla_progetto, b) == "file" for b in cattivi.values()),
      [k for k, b in cattivi.items() if codice(G.controlla_progetto, b) != "file"])
finto_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (30000).to_bytes(4, "big") + (30000).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"\0" * 20
check("immagine enorme (900 milioni di punti) o che non è un PNG: rifiutata nei file che arrivano da fuori",
      codice(G.controlla_progetto, zip_di([("project.json", BUONO), ("images/a.png", finto_png)], zipfile.ZIP_STORED), immagini=True) == "file"
      and codice(G.controlla_progetto, zip_di([("project.json", BUONO), ("images/a.png", b"GIF89a" + b"x" * 40)], zipfile.ZIP_STORED), immagini=True) == "file")
medio = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (7000).to_bytes(4, "big") + (7000).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"\0" * 20
check("una sola immagine da 49 milioni di punti: già troppo (il limite è 40)",
      codice(G.controlla_progetto, zip_di([("project.json", BUONO), ("images/a.png", medio)], zipfile.ZIP_STORED), immagini=True) == "file")
cif = bytearray(zip_di([("project.json", BUONO)], zipfile.ZIP_STORED))
cif[6] |= 1
cif[cif.rfind(b"PK\x01\x02") + 8] |= 1
check("file cifrato: rifiutato", codice(G.controlla_progetto, bytes(cif)) == "file")

# ====================================================================== condivisione
print("--- condivisione")
finta.richieste.clear()
passi = []
esito = G.condividi(qs, BASE, p, avanzamento=lambda i, n: passi.append((i, n)))
ident = esito["id"]
check("condivisione completa: pubblico", esito["stato"] == "pubblico" and finta.lavori[ident]["stato"] == "pubblico", esito)
check("ordine delle richieste: scheda, i 5 file, chiusura",
      [(m, pth.split("/")[2]) for m, pth, _h, _b in finta.richieste] == [("POST", "condividi")] + [("PUT", "carica")] * 5 + [("POST", "concludi")])
check("avanzamento da 0 alla fine, senza tornare indietro", passi[0] == (0, 7) and passi[-1] == (7, 7) and [x[0] for x in passi] == sorted(x[0] for x in passi))
scheda_mandata = json.loads(finta.richieste[0][3])
check("nella scheda mandata solo i campi previsti", set(scheda_mandata) == {
    "titolo", "descrizione", "categoria", "materiale", "spessore_mm", "laser_famiglia", "potenza_w", "tipo", "larghezza_mm",
    "altezza_mm", "tempo_s", "licenza", "autore_nome", "versione_flc", "regole_accettate", "opera_mia", "impronta", "foto_n"},
    sorted(scheda_mandata))
tutto = b"".join(pth.encode() + json.dumps(h).encode() + b for _m, pth, h, b in finta.richieste)
utente = os.path.basename(os.path.expanduser("~"))
proibiti = [x for x in ("CARTELLA-SEGRETA", "progetto-RISERVATO", "RISERVATO-cliente", "MarcaDelTelefonoSegreta", socket.gethostname(),
                        utente if len(utente) > 4 else "", w.profile.name if w.profile.name != w.profile.model else "",
                        str(w.ctl.port or ""), TMP)
            if x and len(x) >= 4 and x.encode() in tutto]  # due lettere («vm») si trovano per caso dentro i PNG
check("in tutto quello che è partito: nessun percorso, nome di file, nome del computer, dell'utente, della porta", not proibiti, proibiti)
h0 = finta.richieste[0][2]
check("intestazioni: solo programma, versione e numero dell'installazione",
      h0.get("x-flc-installazione") == G.installazione(qs) and h0.get("user-agent", "").startswith("FreeLaserCut/")
      and not [k for k in h0 if k in ("cookie", "authorization", "from", "referer")], sorted(h0))
check("il file arrivato al servizio è quello ripulito", finta.lavori[ident]["parti"]["progetto"] == p.progetto
      and json.loads(zipfile.ZipFile(io.BytesIO(finta.lavori[ident]["parti"]["progetto"])).read("project.json"))["name"] == "Scatola di Natale")
check("la chiave dell'autore resta su questo computer, in «I miei lavori»",
      G.chiave_di(ident) == finta.lavori[ident]["chiave"] and G.miei()[0]["titolo"] == "Scatola di Natale")
check("lo stesso progetto una seconda volta: «è già nella Galleria»", codice(G.condividi, qs, BASE, p) == "doppione")

r.w = 82.0
p2 = G.prepara(doc, "Scatola rifiutata")
finta.ia = "no:adult"
es2 = G.condividi(qs, {**BASE, "titolo": "Scatola rifiutata"}, p2)
check("immagini non accettate dal controllo automatico: non pubblicato, niente in «I miei lavori», frase chiara",
      es2["stato"] == "rifiutato" and G.chiave_di(es2["id"]) is None and "adulti" in G.testo_stato("rifiutato", es2["motivo"]), es2)
r.w = 83.0
p3 = G.prepara(doc, "Scatola in attesa")
finta.ia = "attesa"
es3 = G.condividi(qs, {**BASE, "titolo": "Scatola in attesa"}, p3)
check("controllo automatico che non risponde: in attesa, ricordato, non nell'elenco pubblico",
      es3["stato"] == "attesa" and G.chiave_di(es3["id"]) and es3["id"] not in [l["id"] for l in G.elenco()["lavori"]]
      and "un'ora" in G.testo_stato("attesa"))
finta.ia = "ok"
r.w = 84.0
p4 = G.prepara(doc, "Scatola quattro")
finta.guasto = "carica_rifiuta"
check("un file rifiutato a metà invio: errore chiaro, e non resta un lavoro a metà",
      codice(G.condividi, qs, {**BASE, "titolo": "Scatola quattro"}, p4) == "file_grande"
      and not [m for m in G.miei() if m["titolo"] == "Scatola quattro"]
      and [l["stato"] for l in finta.lavori.values() if l["titolo"] == "Scatola quattro"] == ["tolto"])
finta.guasto = "risposta_condividi"
r.w = 85.0
check("risposta sbagliata alla scheda: non si manda nessun file",
      codice(G.condividi, qs, {**BASE, "titolo": "Scatola cinque"}, G.prepara(doc, "Scatola cinque")) == "risposta"
      and finta.richieste[-1][1].endswith("/condividi"))
finta.guasto = None
finta.limite = 0
r.w = 86.0
check("limite del giorno: detto con la sua frase", codice(G.condividi, qs, {**BASE, "titolo": "Scatola sei"}, G.prepara(doc, "Scatola sei")) == "limite")
finta.limite = 50
r.w = 80.0

# ====================================================================== risposte ostili
print("--- risposte del servizio")
finta.guasto = "non_json"
check("risposta che non è JSON (pagina di un proxy): «risposta non valida»", codice(G.elenco) == "risposta")
finta.guasto = "enorme"
t0 = time.time()
check("risposta enorme (40 MB): scartata…", codice(G.elenco) == "risposta")
spin(lambda: finta.interrotte > 0, 3)
check("…e letta solo fino al limite: il resto non viene nemmeno scaricato", finta.interrotte == 1 and time.time() - t0 < 8, finta.interrotte)
finta.guasto = "errore_500"
check("errore del servizio senza spiegazione: frase generica", codice(G.elenco) == "interno")
finta.guasto = "elenco_ostile"
ost = G.elenco()["lavori"]
check("elenco con righe ostili: restano solo quelle con un identificativo valido", [l["id"] for l in ost] == ["ostile0001"])
o = ost[0]
check("campi ostili ridotti a tipi e limiti giusti",
      len(o["titolo"]) == 80 and o["descrizione"] == "" and o["categoria"] == "altro" and o["tipo"] == "entrambi"
      and o["materiale"] == "" and o["stelle_media"] is None and o["stelle_n"] == 0 and o["fatti_n"] == 0
      and o["licenza"] == "cc-by-4.0" and "\n" not in o["autore_nome"] and o["potenza_w"] is None and o["foto_n"] == 0, o)
finta.guasto = None
check("identificativi strani non partono nemmeno", codice(G.lavoro, "../admin") == "non_trovato" and codice(G.scarica, "x" * 11) == "non_trovato")
finta.guasto = ("anteprima", b"GIF89a" + b"0" * 50)
check("anteprima che non è un PNG: scartata", codice(G.anteprima, ident) == "risposta")
finta.guasto = ("file", cattivi["programma dentro"])
check("progetto scaricato ostile: non arriva al programma", codice(G.scarica, ident) == "file")
finta.guasto = None
check("progetto scaricato buono: gli stessi byte mandati", G.scarica(ident) == p.progetto)
os.environ["FLC_GALLERIA_URL"] = "http://127.0.0.1:9/v1"
t0 = time.time()
check("servizio che non risponde: «controlla la connessione», senza bloccare a lungo", codice(G.elenco) == "rete" and time.time() - t0 < 10)
os.environ["FLC_GALLERIA_URL"] = finta.url

# ====================================================================== voti, fatti, segnalazioni
print("--- community")


class Altro:  # un'altra installazione
    def __init__(self, n):
        self.v = "%032x" % n

    def value(self, _k):
        return self.v

    def setValue(self, _k, v):
        self.v = v


check("non si vota il proprio lavoro", codice(G.voto, qs, ident, 5) == "proprio")
v = G.voto(Altro(1), ident, 5)
v = G.voto(Altro(1), ident, 3)
v = G.voto(Altro(2), ident, 4)
check("stelle: un voto per installazione, si può cambiare", v["stelle_n"] == 2 and v["stelle_media"] == 3.5, v)
check("stelle fuori da 1–5: non partono", codice(G.voto, Altro(3), ident, 6) == "campo" and codice(G.voto, Altro(3), ident, 0) == "campo")
G.fatto(Altro(1), ident)
check("«L'ho fatto anch'io»: contato una volta", G.fatto(Altro(1), ident)["fatti_n"] == 1)
check("motivo di segnalazione sconosciuto: non parte", codice(G.segnala, Altro(1), ident, "antipatico") == "campo")
check("segnalazione «copiato»: registrata, il lavoro resta", G.segnala(Altro(1), ident, "copiato") and G.lavoro(ident)["id"] == ident)

# ====================================================================== finestra «Condividi»
print("--- finestra Condividi")
finta.richieste.clear()
dlg = w.gallery_share()
check("modulo: titolo dal nome del progetto, tipo indovinato dai livelli, laser dal catalogo, licenza CC BY",
      dlg is not None and dlg.titolo.text() == "progetto-RISERVATO" and dlg.tipo.currentData() == "entrambi"
      and dlg.laser.text() == w.profile.model and dlg.licenza.currentData() == "cc-by-4.0" and dlg.categoria.currentData() == "altro",
      (dlg.titolo.text(), dlg.tipo.currentData(), dlg.laser.text()))
check("anteprima disegnata e misure scritte", dlg.vista.pixmap() is not None and not dlg.vista.pixmap().isNull() and "140" in dlg.misure.text(), dlg.misure.text())
check("le due caselle partono vuote", not dlg.c_mia.isChecked() and not dlg.c_regole.isChecked())
dlg.condividi()
check("senza le caselle e senza materiale: messaggio, niente parte", dlg.esito == ("errore", "materiale") and not finta.richieste, dlg.esito)
dlg.materiale.setText("Compensato di pioppo")
dlg.titolo.setText("Scrivimi a mario@posta.it")
dlg.c_mia.setChecked(True)
dlg.c_regole.setChecked(True)
dlg.condividi()
check("email nel titolo: fermata qui, niente parte", dlg.esito == ("errore", "testo_mail") and not finta.richieste and "email" in dlg.stato.text())
dlg.titolo.setText("Cornice con ovale")
dlg.autore.setText("Ale di prova")
dlg.spessore.setValue(4.0)
dlg.metti_foto([FOTO])
r.w = 90.0
dlg.condividi()
check("durante l'invio i comandi sono fermi", dlg.in_corso and not dlg.b_ok.isEnabled())
spin(lambda: dlg.esito is not None)
check("condivisione dalla finestra: pubblico, finestra chiusa, frase di conferma",
      dlg.esito and dlg.esito[0] == "pubblico" and dlg.result() == QDialog.DialogCode.Accepted and "Galleria" in dlg.ultimo_avviso, dlg.esito)
nuovo = finta.lavori[dlg.esito[1]]
check("al servizio è arrivato quello scritto nel modulo, con la foto",
      nuovo["titolo"] == "Cornice con ovale" and nuovo["materiale"] == "Compensato di pioppo" and nuovo["spessore_mm"] == 4.0
      and nuovo["autore_nome"] == "Ale di prova" and nuovo["foto_n"] == 1 and nuovo["tipo"] == "entrambi" and "foto1" in nuovo["parti"])
check("il nome pubblico è ricordato per la prossima volta", qs.value(G.KEY_NOME) == "Ale di prova")
w.profile.model, modello_vero = "Il laser di Mario in garage", w.profile.model
nome_prima, w.profile.name = w.profile.name, "Laser della cantina"
check("un laser col nome dato dalla persona non viene proposto nel modulo", DG.laser_del_profilo(w.profile)[0] == "")
w.profile.name = nome_prima
w.profile.model = "Longer B1 40W del garage di Mario"
check("0.22.0: profilo rinominato che contiene un modello del catalogo: si propone solo il modello",
      DG.laser_del_profilo(w.profile)[0] == "Longer B1 40W", DG.laser_del_profilo(w.profile))
w.profile.model, nome_vero = "", w.profile.name
w.profile.name = "Longer B1 20W / 30W"
check("…anche quando il modello è nel nome del profilo", DG.laser_del_profilo(w.profile)[0] == "Longer B1 20W / 30W")
w.profile.model, w.profile.name = modello_vero, nome_vero
finta.ia = "no:violence"
r.w = 91.0
dlg = w.gallery_share()
dlg.titolo.setText("Cornice rifiutata")
dlg.materiale.setText("Pioppo")
dlg.c_mia.setChecked(True)
dlg.c_regole.setChecked(True)
dlg.condividi()
spin(lambda: dlg.esito is not None)
check("lavoro non accettato: la finestra resta aperta con il motivo", dlg.esito[0] == "rifiutato" and dlg.result() != QDialog.DialogCode.Accepted
      and "violenza" in dlg.stato.text() and dlg.b_ok.isEnabled(), dlg.stato.text())
dlg.reject()
finta.ia = "ok"
r.w = 92.0
dlg = w.gallery_share()
dlg.titolo.setText("Cornice chiusa a metà")
dlg.materiale.setText("Pioppo")
dlg.c_mia.setChecked(True)
dlg.c_regole.setChecked(True)
dlg.condividi()
dlg.reject()
spin(lambda: DG.bg.pending() == 0, 10)
meta_ = [l for l in finta.lavori.values() if l["titolo"] == "Cornice chiusa a metà"]
check("finestra chiusa durante l'invio: l'invio si ferma, niente viene pubblicato né resta in «I miei lavori»",
      dlg.esito is None and w.acts["save"].isEnabled() and all(l["stato"] in ("tolto", "caricamento") for l in meta_)
      and not [m for m in G.miei() if m["titolo"] == "Cornice chiusa a metà"], [(l["id"], l["stato"]) for l in meta_])
r.w = 80.0

# ====================================================================== finestra «Galleria»
print("--- finestra Galleria")
for _i, (cat, tit) in enumerate((("giochi", "Puzzle del drago"), ("insegne", "<b>Targa</b> <img src=x>"))):
    r.w = 100.0 + _i
    G.condividi(Altro(50 + _i), {**BASE, "titolo": tit, "categoria": cat, "tipo": "taglio", "autore_nome": "Altra persona",
                                 "laser_famiglia": "Sculpfun S30", "potenza_w": 10}, G.prepara(doc, tit))
r.w = 80.0
for _m in [m for m in G.miei() if m["titolo"] in ("Puzzle del drago", "<b>Targa</b> <img src=x>")]:
    G.dimentica_mio(_m["id"])  # nella prova sono «di altri»: su questo computer non c'è la loro chiave
altrui = next(l["id"] for l in finta.lavori.values() if l["titolo"] == "Puzzle del drago")
html_id = next(l["id"] for l in finta.lavori.values() if l["titolo"].startswith("<b>"))
gd = w.gallery_open()
spin(lambda: gd.lista.count() >= 3 and gd.in_corso == 0)
ids = [gd.lista.item(i).data(0x0100) for i in range(gd.lista.count())]
check("elenco caricato con i lavori pubblici (non quelli in attesa o rifiutati)",
      altrui in ids and ident in ids and es3["id"] not in ids and es2["id"] not in ids, ids)
check("le miniature arrivano dopo, senza fermare la finestra", altrui in gd._pix and not gd.lista.item(ids.index(altrui)).icon().isNull())
gd.lista.setCurrentRow(ids.index(altrui))
check("scheda a destra: titolo, autore, materiale, laser dell'autore, licenza",
      gd.t_titolo.text() == "Puzzle del drago" and "Altra persona" in gd.t_dati.text() and "Tiglio 3 mm" in gd.t_dati.text()
      and "Sculpfun S30 10 W" in gd.t_dati.text() and "CC BY 4.0" in gd.t_dati.text() and gd.b_apri.isEnabled(), gd.t_dati.text())
gd.lista.setCurrentRow(ids.index(html_id))
from PySide6.QtCore import Qt  # noqa: E402

check("testi degli altri mostrati come testo semplice (l'HTML resta scritto, non viene eseguito)",
      gd.t_titolo.textFormat() == Qt.PlainText and gd.t_dati.textFormat() == Qt.PlainText and gd.t_descr.textFormat() == Qt.PlainText
      and gd.t_titolo.text().startswith("<b>Targa</b>"))
gd.lista.setCurrentRow(ids.index(altrui))
gd.vota(4)
spin(lambda: gd.in_corso == 0)
check("voto dalla finestra: registrato e riga aggiornata", finta.lavori[altrui]["voti"].get(G.installazione(qs)) == 4
      and "★ 4.0 (1)" in gd.lista.item(ids.index(altrui)).text(), gd.lista.item(ids.index(altrui)).text())
gd.ho_fatto()
spin(lambda: gd.in_corso == 0)
check("«L'ho fatto anch'io» dalla finestra", len(finta.lavori[altrui]["fatti"]) == 1 and "fatto da 1" in gd.lista.item(ids.index(altrui)).text())
gd.lista.setCurrentRow(ids.index(ident))
check("su un lavoro mio: niente voto né segnalazione, c'è «Togli dalla Galleria»",
      not gd.b_stelle[0].isEnabled() and not gd.b_segnala.isEnabled() and not gd.b_togli.isHidden())
gd.categoria.setCurrentIndex(gd.categoria.findData("giochi"))
spin(lambda: gd.in_corso == 0)
check("filtro per categoria", [gd.lista.item(i).data(0x0100) for i in range(gd.lista.count())] == [altrui])
gd.categoria.setCurrentIndex(0)
gd.cerca.setText("drago")
gd.carica()
spin(lambda: gd.in_corso == 0)
check("ricerca per parola", [gd.lista.item(i).data(0x0100) for i in range(gd.lista.count())] == [altrui])
gd.cerca.setText("")

# apertura come progetto nuovo
w.editor.dirty = False
gd.carica()
spin(lambda: gd.in_corso == 0 and gd.lista.count() >= 3)
ids = [gd.lista.item(i).data(0x0100) for i in range(gd.lista.count())]
gd.lista.setCurrentRow(ids.index(altrui))
finta.guasto = ("file", cattivi["file in più"])
doc_prima = w.editor.doc
gd.apri()
spin(lambda: gd.in_corso == 0)
check("progetto ostile: non si apre, il progetto di prima resta, la finestra lo dice",
      w.editor.doc is doc_prima and gd.aperto is None and "non lo apro" in gd.ultimo_avviso, gd.ultimo_avviso)
finta.guasto = None
gd.apri()
spin(lambda: gd.aperto is not None)
nd = w.editor.doc
check("«Apri come progetto nuovo»: forme e livelli dell'autore, senza file, da salvare con nome",
      gd.aperto == altrui and nd is not doc_prima and len(nd.shapes) == 2 and nd.path is None and w.editor.dirty
      and nd.name == "Puzzle del drago" and nd.layer(2).mode == "fill" and abs(nd.shapes[0].w - 100.0) < 1e-6,
      (len(nd.shapes), nd.path, nd.name))
check("avviso sul piano: parametri di un altro laser, da controllare",
      "Altra persona" in w.galleria_avviso and "Sculpfun S30 10 W" in w.galleria_avviso and "Controllale" in w.galleria_avviso
      and w.banner.isVisibleTo(w), w.galleria_avviso)
check("il progetto di prima sul disco non è stato toccato", Document.load(SEGRETO).shapes[0].w == 80.0)
finta.lavori[html_id]["autore_nome"] = "<i>furbo</i>"
DG.apri_nel_programma(w, G.scarica(html_id), G.lavoro(html_id))
check("nome dell'autore con HTML: nell'avviso resta testo", "&lt;i&gt;furbo&lt;/i&gt;" in w.galleria_avviso)
w.editor.dirty = False

# i miei lavori
gd = w.gallery_open()
gd.schede.setCurrentIndex(1)
spin(lambda: gd.in_corso == 0 and gd.lista.count() >= 2)
mie = {gd.lista.item(i).data(0x0100): gd.lista.item(i).text() for i in range(gd.lista.count())}
check("«I miei lavori»: quelli condivisi da qui, con lo stato (pubblico, in attesa)",
      ident in mie and es3["id"] in mie and "in attesa" in mie[es3["id"]] and altrui not in mie, mie)
spin(lambda: es3["id"] in gd._pix, 5)
check("0.22.0: anche il lavoro in attesa ha la sua miniatura (chiesta con la chiave dell'autore)",
      es3["id"] in gd._pix and not gd.lista.item(list(mie).index(es3["id"])).icon().isNull()
      and any(pth.endswith("/anteprima/" + es3["id"]) and h.get("x-flc-chiave") == G.chiave_di(es3["id"])
              for _m, pth, h, _b in finta.richieste))
check("…e nell'elenco di tutti la chiave non parte mai",
      not any("/anteprima/" in pth and h.get("x-flc-chiave") and not pth.endswith(tuple(m["id"] for m in G.miei()))
              for _m, pth, h, _b in finta.richieste))
sb = gd.schede
check("0.22.0: le due schede in cima sono pulsanti larghi, quella scelta piena",
      sb.expanding() and "QTabBar::tab:selected" in sb.styleSheet() and "padding" in sb.styleSheet())
gd.lista.setCurrentRow(list(mie).index(ident))
gd.risposta_prova = False
gd.togli()
spin(lambda: gd.in_corso == 0)
check("«Togli» chiede conferma: con «No» resta", finta.lavori[ident]["stato"] == "pubblico" and G.chiave_di(ident))
gd.risposta_prova = True
gd.togli()
spin(lambda: gd.in_corso == 0 and finta.lavori[ident]["stato"] == "tolto")
spin(lambda: gd.in_corso == 0)
check("«Togli» con «Sì»: tolto dal servizio e da «I miei lavori»",
      finta.lavori[ident]["stato"] == "tolto" and G.chiave_di(ident) is None
      and ident not in [gd.lista.item(i).data(0x0100) for i in range(gd.lista.count())])
finta.lavori[es3["id"]]["stato"] = "tolto"
gd.carica()
spin(lambda: gd.in_corso == 0)
check("lavoro che il servizio non ha più: sparisce anche da «I miei lavori»", G.chiave_di(es3["id"]) is None)
check("togliere un lavoro non mio: non si può", codice(G.togli, altrui) == "chiave")
gd.reject()

# servizio spento
os.environ["FLC_GALLERIA_URL"] = "http://127.0.0.1:9/v1"
gd = w.gallery_open()
spin(lambda: gd.in_corso == 0)
check("Galleria senza rete: la finestra si apre e lo dice, niente errori", gd.lista.count() == 0 and "connessione" in gd.stato.text(), gd.stato.text())
gd.reject()
gd = w.gallery_open()
gd.reject()
spin(lambda: DG.bg.pending() == 0, 10)
check("finestra chiusa mentre carica: nessun errore", True)
os.environ["FLC_GALLERIA_URL"] = finta.url

larga = io.BytesIO()
Image.new("1", (DG.MAX_LATO_IMMAGINE + 1, 4)).save(larga, "PNG")


class _Spia:  # si accorge se un'immagine troppo grande viene decodificata prima del controllo
    viste = 0

    @staticmethod
    def fromData(*a):
        _Spia.viste += 1
        return _QImageVera.fromData(*a)


_QImageVera, DG.QImage = DG.QImage, _Spia
check("immagine vera ma più larga del massimo: scartata senza nemmeno decodificarla",
      DG.immagine_sicura(larga.getvalue(), "PNG") is None and _Spia.viste == 0, _Spia.viste)
DG.QImage = _QImageVera
check("immagini ricevute: aperte solo se piccole e del tipo giusto",
      DG.immagine_sicura(png(), "PNG") is not None and DG.immagine_sicura(finto_png, "PNG") is None
      and DG.immagine_sicura(b"GIF89a" + b"x" * 30, "PNG") is None and DG.immagine_sicura(b"", "PNG") is None)

# ====================================================================== testi pubblici della 0.22.0
print("--- testi pubblici")


def leggi(*parti):
    return open(os.path.join(ROOT, *parti), encoding="utf-8").read()


readme, changelog, sito, priv = leggi("README.md"), leggi("CHANGELOG.md"), leggi("docs", "index.html"), leggi("docs", "privacy.html")
from freelasercut import __version__  # noqa: E402

check("versione 0.22.0, in cima al CHANGELOG e nel README", __version__ == "0.22.0" and changelog.split("\n## ")[1].startswith("0.22.0")
      and "**Versione 0.22.0**" in readme)
check("CHANGELOG, README e sito parlano della Galleria con i due comandi del menu File",
      all("Condividi nella Galleria" in t and "Galleria FreeLaserCut" in t for t in (changelog, readme, sito))
      and "Share to the Gallery" in sito)
check("informativa privacy: sezione della Galleria in inglese e italiano, con che cosa parte e che cosa no",
      'id="gallery"' in priv and 'id="galleria"' in priv and "EXIF" in priv and "No account" in priv and "Niente account" in priv
      and "Never" in priv and "Mai" in priv and "Workers AI" in priv and "22 November 2026" in priv)
check("…e il sito e il README la collegano", "privacy.html#gallery" in sito and "privacy.html#galleria" in sito and "privacy.html" in readme)
mac = leggi("build", "prepara_mac.py")
check("Mac: minimo 14.4 nel .dmg, nel sito e nel README", 'MIN_MACOS = "14.4"' in mac and "macOS 14.4+" in sito
      and "14.4 Sonoma" in sito and "macOS 14.4" in readme and "macOS 13" not in readme and "13 Ventura" not in sito)
check("nei testi nuovi nessun nome di altri programmi", not any(x in t for t in (changelog.split("\n## ")[1], priv)
                                                                for x in ("Light" + "Burn", "xTool" + " Studio")))

finta.chiudi()
w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
