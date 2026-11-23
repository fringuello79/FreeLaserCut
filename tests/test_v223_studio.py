# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.3: «Studia la macchina» (funzione in prova, dietro il codice delle funzioni in prova).

Prove guidate su una K40 con la scheda M2 Nano e su un laser con la scheda Ruida, per raccogliere dati veri dai tester:
si fanno in qualsiasi ordine, anche solo alcune, anche da persone diverse; ogni risultato si scrive subito nel diario ed
entra nel rapporto per l'assistenza. Il laser non si accende mai. Qui tutto si prova con schede finte
(tests/studio_finte.py) che decodificano da sole quello che ricevono, più difetti rimessi apposta per vedere che le
prove se ne accorgono.

Uso: python tests/test_v223_studio.py [classica|banco]
"""
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
ANSWER = {"q": QMessageBox.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER["q"])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import admin, diag, studio  # noqa: E402
from freelasercut.studio import lihuiyu as L  # noqa: E402
from freelasercut.studio import ruida as R  # noqa: E402
from studio_finte import LihuiyuFinta, Orologio, RuidaFinta, SerialeFinta  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


def spin(sec=0.05):
    import time

    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.005)


def refused(fn, *a):
    try:
        fn(*a)
        return False
    except studio.SicurezzaError:
        return True


clk = Orologio()
L.OROLOGIO, L.ATTESA = clk, clk.attesa


def last(d, code):
    return next(r for r in reversed(d.righe) if r.get("prova") == code)


# ====================================================================== A. linguaggio della M2 Nano
check("A CRC uguale a quello calcolato con la tabella (valore di controllo di «123456789»: A1)",
      L.crc8(b"123456789") == 0xA1)
p = L.pacchetto32(b"IPP")
check("A pacchetto: 0x00, comandi, F fino a 30, CRC", len(p) == 32 and p[0] == 0 and p[1:4] == b"IPP"
      and p[4:31] == b"F" * 27 and p[31] == L.crc8(p[1:31]))
w = L.sul_cavo(p)
check("A sul cavo: 0xA6 ogni 31 byte di dati (34 byte)", len(w) == 34 and w[0] == 0xA6 and w[32] == 0xA6 and w[33] == p[31])
check("A distanze in lettere", [L.distanza(x) for x in (1, 25, 26, 51, 52, 255, 3937)]
      == ["a", "y", "|a", "|z", "052", "z", "z" * 15 + "112"])
REG = {("M2", 10): "CV1151921011002219", ("M2", 30): "CV1952352031000086", ("M1", 25): "CV1872311026000123",
       ("M", 50): "CV2112442", ("B2", 30): "CV1721972031000172", ("A", 30): "CV2460832"}


def near_code(a, b):
    """Uguali, o con la sola correzione diagonale (ultime 6 cifre) che differisce di 1: la tolleranza dello studio."""
    if a == b:
        return True
    return len(a) == len(b) == 18 and a[:12] == b[:12] and abs(int(a[12:]) - int(b[12:])) <= 1


got = {k: L.codice_velocita(*k) for k in REG}
check("A codici di velocità come quelli registrati dal programma originale (6 casi, tolleranza dello studio)",
      all(near_code(got[k], v) for k, v in REG.items()), got)
c = L.cmd_a_velocita("M2", 10, 100)
check("A spostamento a velocità: I, codice, NBRS1E, B + distanza, FNSE-",
      re.fullmatch(rb"ICV\d{16}NBRS1EBz{15}112FNSE-", c) is not None and near_code(c[1:19].decode(), REG[("M2", 10)]), c)
check("A spostamento a sinistra con T", L.cmd_a_velocita("M2", 30, -50).split(b"NBRS1E")[1].startswith(b"T"))
check("A spostamento veloce: I … S1P", L.cmd_passo_veloce(10, -5) == b"IL197Bz139S1P", L.cmd_passo_veloce(10, -5))
bad = 0
for args in (("M2", 0.1), ("M2", 500), ("Z9", 10)):
    try:
        L.codice_velocita(*args)
    except ValueError:
        bad += 1
check("A velocità fuori misura o scheda sconosciuta: errore, niente codice", bad == 3)

# ====================================================================== B. il laser non si accende mai
check("B K40: D (accensione), W (potenza), A (comandi AT e seriale), U, minuscole strane: rifiutati",
      all(refused(L.controlla, x) for x in (b"ID", b"IBaD", b"CV123W", b"AT1", b"A1234", b"IUS1P", b"I\n", b"I\x00")))
check("B K40: i comandi dello studio passano", all(L.controlla(x) for x in (
    L.cmd_casa(), L.cmd_ferma(), L.cmd_passo_veloce(3, 4), L.cmd_a_velocita("M2", 10, 50), L.cmd_a_velocita("B", 30, -50))))
rnd = random.Random(7)
alphabet = bytes(range(32, 127))
viol = 0
for _ in range(400):
    s = bytes(rnd.choice(alphabet) for _ in range(rnd.randint(1, 40)))
    ok = not refused(L.controlla, s)
    if ok and (b"D" in s or b"W" in s or b"A" in s):
        viol += 1
check("B K40: 400 sequenze a caso: nessuna con D, W o A passa il controllo", viol == 0)
src = open(os.path.join(ROOT, "freelasercut", "studio", "lihuiyu.py"), encoding="utf-8").read()
code_lines = [ln.split("#")[0] for ln in src.splitlines() if not ln.strip().startswith(("#", '"', "'"))]
check("B K40: nel codice nessuna stringa di byte con D o W (accensione e potenza non esistono)",
      not any(re.search(rb'b"[^"]*[DW][^"]*"'.decode(), ln) for ln in code_lines))
for bad_cmd in (b"\xA8" + bytes(10), b"\xA9\x00\x00\x00\x00", b"\xC6\x01\x3F\x7F", b"\xC9\x02" + bytes(5), b"\xD8\x00",
                b"\xDA\x01\x00\x26" + bytes(10), b"\xD9\x10\x03" + bytes(10), b"\xD9\x10\x02" + b"\x80" + bytes(9),
                b"\xDA\x00\x05\x80", b"\xD7", b"\xCE\xCE"):
    if not refused(R.controlla, bad_cmd):
        check("B Ruida: comando non permesso passato", False, bad_cmd.hex())
check("B Ruida: taglio, potenza, velocità, avvio lavoro, scrittura in memoria, rapido con la luce, fine file: rifiutati",
      all(refused(R.controlla, x) for x in (b"\xA8" + bytes(10), b"\xC6\x01\x3F\x7F", b"\xD8\x00", b"\xDA\x01\x00\x26",
                                           b"\xD9\x10\x03" + bytes(10), b"\xD7")))
check("B Ruida: i quattro comandi dello studio passano", all(R.controlla(x) for x in (
    R.cmd_saluto(), R.cmd_leggi(0x057E), R.cmd_rapido(10, 20), R.cmd_stop())))
nbad = 0
for a in (0x0080, 0x8000, -1, 0x05FF):
    try:
        R.cmd_leggi(a)
    except ValueError:
        nbad += 1
check("B Ruida: indirizzo non valido (byte da 0x80 in su): errore prima di mandare", nbad == 4)
cross = {R.districa(R.rimescola(0xCE, a), b) for a in R.CHIAVI for b in R.CHIAVI if a != b}
check("B Ruida: il saluto con la chiave sbagliata per la scheda è 0x57, 0x66 o 0xFF (niente di pericoloso)",
      cross == {0x57, 0x66, 0xFF}, sorted(map(hex, cross)))
danger = {R.districa(R.rimescola(0x00, 0x11), 0x38), R.districa(R.rimescola(0x00, 0x38), 0x11)}
check("B Ruida: la lettura con chiavi 0x11/0x38 scambiate diventerebbe un taglio (0xA8): per questo non si fa",
      danger == {0xA8})

# ====================================================================== C. Ruida: rimescolamento e numeri
check("C rimescolamento e ritorno per tutti i 256 byte con le tre chiavi",
      all(R.districa(R.rimescola(b, k), k) == b for b in range(256) for k in R.CHIAVI))
check("C conferma 0xCC sul filo con la chiave 0x88: 0xC6", R.rimescola(0xCC, 0x88) == 0xC6)
bu = R.busta_udp(b"\xCE")
check("C busta UDP: somma dei byte rimescolati, il più alto prima", bu[2:] == bytes([R.rimescola(0xCE)])
      and ((bu[0] << 8) | bu[1]) == sum(bu[2:]))
check("C numeri a 7 bit: andata e ritorno, anche negativi", all(
    R.da_numero(R.numero(v), True) == v for v in (0, 1, 127, 128, 600000, -1, -12345, 2 ** 33)))
check("C risposta alla lettura decodificata", R.leggi_risposta(b"\xDA\x01\x00\x26" + R.numero(600000) + R.numero(0),
                                                            0x0026)["valore"] == 600000)
check("C risposta di un altro indirizzo o troppo corta: ignorata",
      R.leggi_risposta(b"\xDA\x01\x00\x36" + R.numero(5) + R.numero(0), 0x0026) is None
      and R.leggi_risposta(b"\xDA\x01\x00", 0x26) is None)

# ====================================================================== D. K40 con la scheda finta, in qualsiasi ordine
d = studio.Diario("k40", "prova001")
f = LihuiyuFinta(clk)
check("D K3 per prima (senza K1 né K2): da sola va a casa e misura", L.prova_k3(d, [f], "M2") is not None)
k3 = last(d, "K3")
vv = k3["velocita_vera"]
check("D velocità vera misurata come quella della scheda (92 % di quella chiesta, entro l'1 %)",
      abs(vv["10.0"] - 9.2) < 0.092 and abs(vv["30.0"] - 27.6) < 0.276, vv)
check("D otto spostamenti, tutti con la loro durata", len(k3["misure"]) == 8 and all(m["secondi"] for m in k3["misure"]))
kinds = [c[0] for c in f.comandi]
check("D la scheda ha ricevuto: casa, poi solo spostamenti a velocità, avanti e indietro (torna dov'era)",
      kinds[0] == "casa" and kinds[1:] == ["velocita"] * 8 and f.x_mil == 0, f.comandi)
check("D la scheda finta ha decodificato da sola le velocità chieste (10 e 30 mm/s)",
      sorted({round(c[1], 1) for c in f.comandi if c[0] == "velocita"}) == [10.0, 30.0], f.comandi)
check("D nessun pacchetto pericoloso, nessun errore di CRC", not f.pericoli and f.crc_ko == 0)
check("D K1 dopo K3: stato «lavoro finito»", L.prova_k1(d, [f]) == [236])
check("D K2: casa, con gli stati nel tempo", L.prova_k2(d, [f])[1][-1][1] == 236 and last(d, "K2")["esito"] == "ok")
f2 = LihuiyuFinta(clk, crc_sbagliati=2)
L.prova_k2(d, [f2])
check("D errori di controllo: il pacchetto si rimanda e si contano", last(d, "K2")["errori_crc"] == 2 and f2.crc_ko == 2
      and ("casa",) in f2.comandi)
L.prova_k1(d, [LihuiyuFinta(clk, muta=True)])
check("D scheda che non risponde allo stato: «risposte strane», niente blocchi", last(d, "K1")["esito"] == "risposte strane")
L.prova_k3(d, [LihuiyuFinta(clk, sempre_occupata=True)], "M2")
check("D scheda sempre occupata: K3 finisce lo stesso (tempi non misurati), senza restare appesa",
      last(d, "K3")["esito"] == "tempi non misurati")
L.prova_k2(d, [LihuiyuFinta(clk, non_si_apre=True), f])
check("D primo collegamento che non si apre: si prova il successivo e si scrive perché",
      last(d, "K2")["esito"] == "ok" and "occupata" in last(d, "K2")["errori_prima"][0])
L.prova_k1(d, [])
check("D nessun collegamento (per esempio senza driver): «non collegata» nel diario", last(d, "K1")["esito"] == "non collegata")
ff = LihuiyuFinta(clk)
n = {"i": 0}


def stop_after():
    n["i"] += 1
    return n["i"] > 40


try:
    L.prova_k3(d, [ff], "M2", stop_after)
    stopped = False
except InterruptedError:
    stopped = True
check("D Ferma durante K3: si interrompe, la scheda riceve «I», il diario dice «fermata»",
      stopped and ("ferma",) in ff.comandi and last(d, "K3")["esito"] == "fermata")
k0 = L.prova_k0(d, run=lambda cmd, **k: "")
check("D K0 su questo computer: non trova niente e lo scrive, senza errori", last(d, "K0")["prova"] == "K0"
      and "trovata" in k0)
pnp = L._pnp_windows(lambda cmd, **k: "USB\\VID_1A86&PID_5512\\5&2C3F1&0&3|USB|USB-EPP/I2C... CH341A|OK\n"
                                       "USB\\VID_1A86&PID_7523\\6&ABC|Ports|USB-SERIAL CH340 (COM7)|OK")
check("D Windows: dei dispositivi si tengono VID, PID, classe e stato (niente numero di serie né posizione)",
      pnp[0]["pid"] == "5512" and "5&2C3F1" not in json.dumps(pnp), pnp)
mac = L._usb_mac(lambda cmd, **k: '  "idVendor" = 6790\n  "idProduct" = 21778\n  "idVendor" = 1452\n  "idProduct" = 1\n')
check("D Mac: la scheda si riconosce dall'elenco dell'USB", mac == [{"vid": "1a86", "pid": "5512"}], mac)

# ====================================================================== E. Ruida con la scheda finta, in qualsiasi ordine
dr = studio.Diario("ruida", "prova001", extra={"rete": studio.maschera_ip("192.168.7.33")})
rf = RuidaFinta(0x88)
link = R.Rete("127.0.0.1", porta=rf.porta, ascolto=0, attesa=0.3)
v = R.prova_r2(dr, link)  # R2 per prima: cerca da sola la chiave
r2 = last(dr, "R2")
check("E R2 per prima: trova da sola la chiave e legge tutto", r2["chiave"] == "88" and r2["letti"] == 9, r2.get("letti"))
check("E modello della scheda, misure del piano, posizione", r2["modello"] == "RDC6442S" and r2["piano_x_mm"] == 600.0
      and r2["piano_y_mm"] == 400.0 and r2["pos_x_mm"] == 120.0 and r2["pos_y_mm"] == 80.0 and len(r2["impronta"]) == 10)
check("E R3: 10 mm e ritorno, senza luce, arrivata e tornata", R.prova_r3(dr, link, 0x88) is not None
      and last(dr, "R3")["esito"] == "ok")
check("E dopo R3 la testa è dov'era", abs(rf.mem[0x0421] - 120000) < 50, rf.mem[0x0421])
mv = [c for c in rf.ricevuti if c[:2] == b"\xD9\x10"]
check("E i due spostamenti sono rapidi senza luce (opzione 02)", len(mv) == 2 and all(c[2] == 2 for c in mv))
R.prova_r4(dr, R.Rete("127.0.0.1", porta=rf.porta, ascolto=0, attesa=0.05), 0x88)
check("E R4: lettura estesa, con i valori letti e quanti senza risposta", last(dr, "R4")["letti"]
      and last(dr, "R4")["totale"] == 128 + 96 + 128)
check("E la scheda finta non ha mai ricevuto comandi pericolosi", not rf.pericoli)
rf.chiudi()
r38 = RuidaFinta(0x38)
link = R.Rete("127.0.0.1", porta=r38.porta, ascolto=0, attesa=0.25)
check("E scheda con la chiave 0x38: R1 la trova alla terza", R.prova_r1(dr, link) == 0x38
      and [t["chiave"] for t in last(dr, "R1")["tentativi"]] == ["88", "11", "38"])
check("E con le chiavi sbagliate la scheda ha visto solo un byte innocuo, e nessuna lettura",
      [c for c in r38.ricevuti if c[:1] == b"\xDA"] == [] and {x[1] for x in r38.estranei} <= {b"\xff", b"f", b"W"}
      and not r38.pericoli, r38.estranei)
R.prova_r2(dr, link, 0x38)
check("E R2 con la chiave trovata: letto tutto", last(dr, "R2")["letti"] == 9)
r38.chiudi()
muta = RuidaFinta(0x88, muta=True)
link = R.Rete("127.0.0.1", porta=muta.porta, ascolto=0, attesa=0.1)
check("E scheda che non risponde: R1 «nessuna conferma»", R.prova_r1(dr, link) is None
      and last(dr, "R1")["esito"] == "nessuna conferma")
R.prova_r3(dr, link, 0x88)
check("E R3 senza posizione letta: non si muove", "non mi muovo" in last(dr, "R3")["esito"]
      and not [c for c in muta.ricevuti if c[:2] == b"\xD9\x10"])
muta.chiudi()
import socket  # noqa: E402

busy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
busy.bind(("", 0))
R.prova_r1(dr, R.Rete("127.0.0.1", porta=9, ascolto=busy.getsockname()[1]))
busy.close()
check("E porta delle risposte occupata (un altro programma del laser aperto): «non collegata» con il motivo",
      last(dr, "R1")["esito"] == "non collegata" and "occupata" in last(dr, "R1")["errore"])
usb = RuidaFinta(0x88, rete=False)
ulink = R.Usb(apri_seriale=lambda: SerialeFinta(usb), attesa=0.1)
R.prova_r2(dr, ulink)
check("E USB (niente conferme): R2 legge con la chiave 0x88 senza saluto", last(dr, "R2")["letti"] == 9
      and last(dr, "R2")["collegamento"] == "usb" and not any(c == b"\xCE" for c in usb.ricevuti))
check("E USB: niente somma davanti ai pacchetti", usb.ricevuti and usb.ricevuti[0][:2] == b"\xDA\x00")
usb2 = RuidaFinta(0x38, rete=False)
R.prova_r2(dr, R.Usb(apri_seriale=lambda: SerialeFinta(usb2), attesa=0.05))
check("E USB con un'altra chiave: nessuna risposta, e la scheda non ha visto niente di pericoloso",
      last(dr, "R2")["esito"] == "nessuna risposta" and not usb2.pericoli, [c.hex() for c in usb2.pericoli])

# ====================================================================== F. diario e rapporto
txt = open(dr.path, encoding="utf-8").read()
recs = [json.loads(x) for x in txt.splitlines()]
check("F diario: una riga JSON per evento, scritta subito", len(recs) == len(dr.righe) and recs[0]["evento"] == "inizio")
check("F diario: versione, sistema, macchina, tester in ogni riga", recs[0]["flc"] and recs[0]["studio"] == studio.VERSIONE
      and all(r["tester"] == "prova001" and r["macchina"] == "ruida" for r in recs))
check("F indirizzo di rete nascosto", "192.168.x.x" in txt and "192.168.7.33" not in txt)
check("F maschera: indirizzi strani diventano «?»", studio.maschera_ip("pippo") == "?" and studio.maschera_ip("") == "?")
check("F scritta sulla scheda ripulita", studio.pulisci_etichetta("6C6879-LASER-M2:9 <b>/x\\") == "6C6879-LASER-M2:9 b/x")
home = os.path.expanduser("~")
check("F nel diario niente percorsi della cartella utente", home not in txt and home not in open(d.path).read())
z = os.path.join(TMP, "rapporto.zip")
names = diag.make_report(z)
inz = [n for n in names if n.startswith("studio-macchina/")]
check("F il rapporto per l'assistenza contiene i diari", len(inz) >= 2 and all(n.endswith(".jsonl") for n in inz), names)
with zipfile.ZipFile(z) as zz:
    body = zz.read(inz[-1]).decode("utf-8")
check("F nel rapporto i diari sono leggibili", all(json.loads(x) for x in body.splitlines()))
from PySide6.QtCore import QSettings  # noqa: E402

qs = QSettings(os.path.join(TMP, "t.ini"), QSettings.IniFormat)
t1 = studio.tester_id(qs)
check("F numero del tester: a caso, 8 cifre, sempre lo stesso su questo computer",
      re.fullmatch(r"[0-9a-f]{8}", t1) and studio.tester_id(qs) == t1)
check("F impronta: stessa macchina stessa impronta, macchina diversa impronta diversa",
      studio.impronta(1, 2) == studio.impronta(1, 2) != studio.impronta(1, 3))

# ====================================================================== G. difetti rimessi apposta: le prove se ne accorgono
caught = []
orig = L.controlla
L.controlla = lambda x: bytes(x)  # 1. niente controllo
fg = LihuiyuFinta(clk)
sch = L.Scheda(fg).apri()
try:
    sch.manda(b"IDBzS1P")
except Exception:  # noqa: BLE001
    pass
caught.append(bool(fg.pericoli))
L.controlla = orig
orig_crc = L.crc8
L.crc8 = lambda data: (orig_crc(data) + 1) & 0xFF  # 2. CRC sbagliato
fg = LihuiyuFinta(clk)
L.prova_k2(studio.Diario("k40", "guasto", path=os.path.join(TMP, "g.jsonl")), [fg])
caught.append(fg.crc_ko > 0 and ("casa",) not in fg.comandi and "errore" in open(os.path.join(TMP, "g.jsonl")).read())
L.crc8 = orig_crc
orig_pend = L._FAM_M
L._FAM_M = ((60416.0, 60416.0, 59904.0, 59392.0), -11148.0)  # 3. retta delle velocità sbagliata
caught.append(not near_code(L.codice_velocita("M2", 10), REG[("M2", 10)]))
L._FAM_M = orig_pend
orig_sw = R.rimescola
R.rimescola = lambda b, chiave=0x88: orig_sw(b, chiave ^ 0x01)  # 4. rimescolamento sbagliato
rg = RuidaFinta(0x88)
caught.append(R.prova_r1(studio.Diario("ruida", "g", path=os.path.join(TMP, "g2.jsonl")),
                         R.Rete("127.0.0.1", porta=rg.porta, ascolto=0, attesa=0.1), [0x88]) is None)
rg.chiudi()
R.rimescola = orig_sw
orig_mask = studio.maschera_ip
studio.maschera_ip = lambda ip: ip  # 5. indirizzo non mascherato
dg = studio.Diario("ruida", "g", path=os.path.join(TMP, "g3.jsonl"), extra={"rete": studio.maschera_ip("10.1.2.3")})
caught.append("10.1.2.3" in open(dg.path).read())
studio.maschera_ip = orig_mask
orig_ctl = R.controlla
R.controlla = lambda c: bytes(c)  # 6. Ruida senza controllo
rg = RuidaFinta(0x88)
sr = R.Scheda(R.Rete("127.0.0.1", porta=rg.porta, ascolto=0, attesa=0.1)).apri()
sr.manda(b"\xA8" + bytes(10))
import time as _t  # noqa: E402

_t.sleep(0.2)
caught.append(bool(rg.pericoli))
sr.chiudi()
rg.chiudi()
R.controlla = orig_ctl
check("G sei difetti rimessi apposta (niente controllo K40, CRC, retta, rimescolamento, IP in chiaro, niente controllo "
      "Ruida): tutti visti", all(caught) and len(caught) == 6, caught)

# ====================================================================== H. finestra
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.show()
spin(0.2)
check("H senza codice: la voce è nascosta e la finestra non si apre", not win.acts["study_machine"].isVisible()
      and win.study_machine_dialog() is None)
pal = getattr(getattr(win, "banco", None), "palette", None)
if pal is not None:
    check("H Banco: senza codice la ricerca dei comandi non la trova",
          win.acts["study_machine"] not in (pal.collect(), [a for a, _p in pal.entries])[1])
check("H con il codice compare in Strumenti", win.admin_dialog(code="prova") is True
      and win.acts["study_machine"].isVisible() and "study_machine" in win.TOOLS_MENU)
if pal is not None:
    check("H Banco: con il codice la ricerca la trova",
          win.acts["study_machine"] in (pal.collect(), [a for a, _p in pal.entries])[1])
check("H scheda nella guida «?»", help_texts.lookup("study_machine") is not None
      and "non si accende mai" in help_texts.lookup("study_machine")[1])
dlg = win.study_machine_dialog()
spin()
check("H la finestra si apre una volta sola, con le due schede e otto prove", dlg is not None
      and win.study_machine_dialog() is dlg and dlg.tabs.count() == 2 and len(dlg.rows) == 8)
check("H avviso in testa: il laser non si accende mai", "non si accende" in dlg.banner.text())
fw = LihuiyuFinta(clk)
dlg.k40_links = lambda: [fw]
dlg.k40_board.setCurrentIndex(dlg.k40_board.findData("M2"))
dlg.k40_label.setText("6C6879-LASER-M2:9")
ANSWER["q"] = QMessageBox.No
check("H K2 senza consenso: non parte e la scheda non riceve niente", dlg.run("K2", sync=True) is False and not fw.pacchetti)
ANSWER["q"] = QMessageBox.Yes
check("H K2 con il consenso: fatta", dlg.run("K2", sync=True) and "✓" in dlg.rows["K2"][0].text())
check("H K1 (sola lettura) senza domanda: fatta", dlg.run("K1", sync=True) and "✓" in dlg.rows["K1"][0].text())
dlg.run("K3", sync=True)
check("H K3: velocità misurate scritte nel registro della finestra", "✓" in dlg.rows["K3"][0].text()
      and "mm/s" in dlg.log.toPlainText())
kd = dlg.diari["k40"]
check("H diario della K40 con la scheda scelta e la scritta", kd.righe[0]["scheda_scelta"] == "M2"
      and kd.righe[0]["scritta"] == "6C6879-LASER-M2:9")
dlg.tabs.setCurrentIndex(1)
dlg.ruida_ip.setText("")
check("H Ruida in rete senza indirizzo: non parte", dlg.run("R1", sync=True) is False)
rw = RuidaFinta(0x11)
dlg.ruida_link = lambda: R.Rete("127.0.0.1", porta=rw.porta, ascolto=0, attesa=0.2)
dlg.ruida_ip.setText("192.168.5.77")
dlg.run("R2", sync=True)
dlg.run("R1", sync=True)
check("H Ruida: R2 prima di R1, poi R1: tutte e due fatte, chiave 11", "✓" in dlg.rows["R2"][0].text()
      and "✓" in dlg.rows["R1"][0].text() and dlg.chiave_ruida == 0x11)
check("H R3 con il consenso: fatta", dlg.run("R3", sync=True) and "✓" in dlg.rows["R3"][0].text())
check("H nessun comando pericoloso arrivato alla Ruida finta", not rw.pericoli)
rw.chiudi()
rd = open(dlg.diari["ruida"].path, encoding="utf-8").read()
check("H nel diario della Ruida l'indirizzo è nascosto", "192.168.x.x" in rd and "192.168.5.77" not in rd)
fb = LihuiyuFinta(clk)
dlg.k40_links = lambda: [fb]
dlg.run("K2")
for _ in range(200):
    spin(0.01)
    if not dlg.busy():
        break
spin(0.1)
check("H prova in sottofondo: finisce e aggiorna la riga", not dlg.busy() and "✓" in dlg.rows["K2"][0].text())
opened = []
win.acts["send_report"].triggered.disconnect()
win.acts["send_report"].triggered.connect(lambda *_: opened.append(1))
dlg.b_report.click()
check("H «Invia un rapporto all'assistenza» apre il rapporto di sempre", opened == [1])
dlg.close()
spin()

# ====================================================================== I. testi
new_src = "".join(open(os.path.join(ROOT, *p), encoding="utf-8").read() for p in (
    ("freelasercut", "ui", "dialogs_studio.py"),))
mw = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
ht = open(os.path.join(ROOT, "freelasercut", "ui", "help_texts.py"), encoding="utf-8").read()


def tr_strings(text):
    out = []
    for m in re.finditer(r'tr\(((?:\s*"(?:[^"\\]|\\.)*")+)', text):
        out.append("".join(json.loads(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1))))
    return out


texts = set(tr_strings(new_src))
for blob in (mw, ht):
    for s in tr_strings(blob):
        if "tudia la macchina" in s or "M2 Nano" in s or "scheda Ruida" in s:
            texts.add(s)
missing = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [t for t in texts if not cat.get(t)]
    if miss:
        missing[lang] = miss[:3]
check(f"I tutti i {len(texts)} testi nuovi tradotti in inglese, spagnolo, francese e portoghese", not missing and len(texts) > 40,
      missing)
check("I nei testi pubblici niente nomi di programmi commerciali", not re.search(
    r"LightBurn|LaserDRW|RDWorks|xTool|K40 Whisperer|MeerK40t", " ".join(texts), re.I))

win.close()
spin()
print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
