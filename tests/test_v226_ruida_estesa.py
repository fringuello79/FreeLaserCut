# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6: «Studia la macchina», Ruida — la lettura estesa (R4) legge anche le impostazioni note che stanno
fuori dalle zone (velocità e accelerazioni di lavoro, ritorno a casa, ritardi, contatori).

Il punto delicato: il numero di un'impostazione e i due byte che vanno sul cavo non sono la stessa cosa (sul cavo ogni
byte porta 7 bit). Qui si controlla la conversione su tutti i numeri possibili e su quelli già verificati dalle fonti,
che R4 mandi solo letture, e che i valori della scheda finta tornino nel diario con l'indirizzo giusto.

Uso: python tests/test_v226_ruida_estesa.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freelasercut import studio  # noqa: E402
from freelasercut.studio import ruida as R  # noqa: E402
from studio_finte import RuidaFinta, SerialeFinta  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def last(d, prova):
    return next(r for r in reversed(d.righe) if r.get("prova") == prova)


# ====================================================================== A. numero dell'impostazione <-> byte sul cavo
print("--- A. conversione")
ok = True
for n in range(0x4000):
    c = R.sul_cavo(n)
    ok = ok and (c >> 8) < 0x80 and (c & 0xFF) < 0x80 and R.numero_impostazione(c) == n
check("A andata e ritorno su tutti i 16384 numeri, con i due byte sempre sotto 0x80", ok)
# coppie verificate: quelle che lo studio leggeva già (R2) e che le fonti chiamano con il loro numero
noti = {0x026: 0x0026, 0x036: 0x0036, 0x200: 0x0400, 0x205: 0x0405, 0x221: 0x0421, 0x231: 0x0431, 0x241: 0x0441,
        0x251: 0x0451, 0x2FE: 0x057E, 0x07F: 0x007F, 0x080: 0x0100, 0x0C8: 0x0148, 0x100: 0x0200, 0x1B2: 0x0332}
check("A le coppie conosciute tornano (0x2FE = 05 7E, 0x221 = 04 21, 0x0C8 = 01 48…)",
      all(R.sul_cavo(n) == c for n, c in noti.items()), {hex(n): hex(R.sul_cavo(n)) for n in noti})
check("A gli indirizzi di R2 sono quelli di prima", R.MEMORIA["scheda"] == R.sul_cavo(0x2FE)
      and R.MEMORIA["x"] == R.sul_cavo(0x221) and R.MEMORIA["stato"] == R.sul_cavo(0x200))
for bad in (-1, 0x4000, 0x10000):
    try:
        R.sul_cavo(bad)
        r = False
    except ValueError:
        r = True
    check(f"A numero fuori misura rifiutato ({bad})", r)
try:
    R.numero_impostazione(0x0080)
    r = False
except ValueError:
    r = True
check("A un indirizzo con un byte da 0x80 in su non è un indirizzo", r)

# ====================================================================== B. l'elenco
print("--- B. elenco delle impostazioni fuori dalle zone")
zona = {a for lo, hi in R.ZONE_ESTESE for a in range(lo, hi)}
fuori = [R.sul_cavo(n) for n in R.IMPOSTAZIONI_NOTE]
check("B nessun doppione e in ordine", list(R.IMPOSTAZIONI_NOTE) == sorted(set(R.IMPOSTAZIONI_NOTE)))
check("B nessuna è già dentro una zona (non si legge due volte)", not zona & set(fuori))
check("B ci sono il ritorno a casa (0x0C8), le impostazioni di lavoro (0x100-0x1B2) e i contatori (0x313…)",
      {0x0C8, 0x0C9, 0x100, 0x10A, 0x125, 0x135, 0x1B2, 0x313, 0x340} <= set(R.IMPOSTAZIONI_NOTE))
check("B sono tante quante dice la raccolta (178)", len(R.IMPOSTAZIONI_NOTE) == 178, len(R.IMPOSTAZIONI_NOTE))
soli_letture = True
for a in fuori:
    c = R.controlla(R.cmd_leggi(a))
    soli_letture = soli_letture and c[:2] == b"\xDA\x00" and len(c) == 4
check("B ognuna diventa una lettura di 4 byte (DA 00 + indirizzo) e passa il controllo di sicurezza", soli_letture)

# ====================================================================== C. R4 in rete con la scheda finta
print("--- C. R4 in rete")
rf = RuidaFinta(0x88)
VALORI = {0x0C8: 20000, 0x0C9: 21000, 0x100: 7, 0x10A: 3000000, 0x135: 2500000, 0x1B2: 12, 0x313: 5000, 0x5C0: 99}
for n, v in VALORI.items():
    rf.mem[R.sul_cavo(n)] = v
d = studio.Diario("ruida", "prova226", extra={"rete": studio.maschera_ip("192.168.7.33")})
letti = R.prova_r4(d, R.Rete("127.0.0.1", porta=rf.porta, ascolto=0, attesa=0.05), 0x88)
r4 = last(d, "R4")
attesi = 128 + 96 + 128 + len(R.IMPOSTAZIONI_NOTE)
check("C totale = le tre zone più le impostazioni fuori zona", r4["totale"] == attesi and r4["fuori_zona"] == 178,
      (r4["totale"], r4.get("fuori_zona")))
check("C i valori fuori zona arrivano nel diario con l'indirizzo come sul cavo",
      all(r4["letti"].get("%04X" % R.sul_cavo(n), [None])[0] == v for n, v in VALORI.items()),
      {hex(n): r4["letti"].get("%04X" % R.sul_cavo(n)) for n in VALORI})
check("C dal diario si risale al numero dell'impostazione",
      {R.numero_impostazione(int(k, 16)) for k in r4["letti"]} >= set(VALORI))
check("C quelli che la scheda non conosce sono contati come senza risposta",
      r4["senza_risposta"] == attesi - len(r4["letti"]) and r4["senza_risposta"] > 0)
check("C i valori delle zone ci sono ancora (modello della scheda, piano)",
      r4["letti"]["057E"][0] == 0x65106510 and r4["letti"]["0026"][0] == 600000)
lette = [c for c in rf.ricevuti]
check("C alla scheda sono arrivate solo letture, una per indirizzo", len(lette) == attesi
      and all(len(c) == 4 and c[:2] == b"\xDA\x00" for c in lette) and len(set(lette)) == attesi, len(lette))
check("C nessun comando pericoloso e nessun pacchetto storto", not rf.pericoli and not rf.estranei)
check("C la funzione restituisce gli stessi valori", letti == r4["letti"])
rf.chiudi()

# ====================================================================== D. R4 su USB (niente conferme) e fermata a metà
print("--- D. USB e Ferma")
ru = RuidaFinta(0x88, rete=False)
ru.mem[R.sul_cavo(0x0C8)] = 20000
du = studio.Diario("ruida", "prova226", extra={})
usb = R.Usb(porta="finta", apri_seriale=lambda *a, **k: SerialeFinta(ru), attesa=0.02)
R.prova_r4(du, usb, 0x88)
u4 = last(du, "R4")
check("D su USB: stesso totale, valore fuori zona letto, solo letture", u4["totale"] == attesi
      and u4["letti"].get("0148", [None])[0] == 20000 and not ru.pericoli
      and all(c[:2] == b"\xDA\x00" for c in ru.ricevuti), (u4["totale"], u4["letti"].get("0148")))
rs = RuidaFinta(0x88, rete=False)
ds = studio.Diario("ruida", "prova226", extra={})
n = {"i": 0}


def ferma():
    n["i"] += 1
    return n["i"] > 20


R.prova_r4(ds, R.Usb(porta="finta", apri_seriale=lambda *a, **k: SerialeFinta(rs), attesa=0.02), 0x88, ferma)
check("D Ferma a metà: si ferma subito e scrive quello che ha letto", len(rs.ricevuti) == 20
      and last(ds, "R4")["totale"] == attesi, len(rs.ricevuti))

print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
