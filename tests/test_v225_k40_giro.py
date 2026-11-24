# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.5: Studia la macchina, K40 — prove più automatiche e risultati spiegati (rapporti FLC-20261123-1937-1187
e FLC-20261123-2036-E7DF, video di Evo del 23/11).

Sulla M2 Nano vera:
- dopo il ritorno a casa («IPP») la scheda non dice «lavoro finito», torna solo «pronta»: K2 aspettava «finito» fino a
  25 s. Ora la fine è «pronta» ferma per un secondo, e K2 torna a casa da vicino e da 10 cm per vedere se «pronta»
  arriva quando la testa è arrivata;
- alla fine di ogni corsa di K3 la testa supera il punto di circa 4 mm, torna e fa un piccolo colpo in Y. K3 entra ed
  esce dal modo compatto a ogni corsa. La nuova K4 fa le stesse corse una per lavoro e poi tutte in un solo lavoro, e
  dai tempi conta quante volte la testa fa il giro;
- un pulsante fa tutte le prove con un solo consenso e alla fine scrive i risultati in parole.

Uso: python tests/test_v225_k40_giro.py [classica|banco]
"""
import json
import os
import sys
import tempfile

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
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from freelasercut import studio  # noqa: E402
from freelasercut.studio import lihuiyu as L  # noqa: E402
from studio_finte import LihuiyuFinta, Orologio  # noqa: E402

clk = Orologio()
L.OROLOGIO, L.ATTESA = clk, clk.attesa
N = {"i": 0}


def diario():
    N["i"] += 1
    return studio.Diario("k40", "prova001", path=os.path.join(TMP, f"d{N['i']}.jsonl"))


def last(d, code):
    return next(r for r in reversed(d.righe) if r.get("prova") == code)


def evo(**kw):
    """La M2 Nano di Evo: dopo la casa solo «pronta», ritorno a casa a circa 50 mm/s, giro di 0,67 s a 30 mm/s."""
    base = dict(casa_finito=False, casa_v=50.0, extra=0.67, occupata_in_moto=False)
    base.update(kw)
    return LihuiyuFinta(clk, **base)


# ====================================================================== A. fine del ritorno a casa
f = evo()
sch = L.Scheda(f).apri()
sch.manda(L.cmd_casa())
t0 = clk()
sec, visti, come = sch.aspetta_casa(30)
check("A scheda come quella vera (dopo la casa solo «pronta»): fine trovata in circa un secondo e mezzo, non 25",
      come == "pronta" and sec is not None and clk() - t0 < 2.0, (sec, visti, come, clk() - t0))
check("A gli stati visti: «occupata» e poi «pronta»", [s for _t, s in visti] == [238, 206], visti)
sec_old, _v = sch.aspetta_fine(25)
check("A la vecchia attesa di «finito» qui scadeva a vuoto (era il ritardo visto da Evo)", sec_old is None)
sch.chiudi()
f = LihuiyuFinta(clk)  # scheda che dopo la casa dice «finito»
sch = L.Scheda(f).apri()
sch.manda(L.cmd_casa())
sec, visti, come = sch.aspetta_casa(30)
check("A scheda che dice «lavoro finito»: fine al «finito»", come == "finito" and visti[-1][1] == 236, (visti, come))
sch.chiudi()
f = LihuiyuFinta(clk, sempre_occupata=True)
sch = L.Scheda(f).apri()
t0 = clk()
sec, visti, come = sch.aspetta_casa(5)
check("A scheda sempre occupata: «tempo scaduto» dopo il massimo, senza restare appesa",
      sec is None and come == "tempo scaduto" and 5 <= clk() - t0 < 6)
sch.chiudi()
f = evo()
sch = L.Scheda(f).apri()
sec, visti, come = sch.aspetta_casa(30)  # nessun comando: sempre «pronta»
check("A «pronta» senza «occupata»: fine dopo 2 s, ed è scritto", come == "pronta senza occupata" and sec == 0.0,
      (sec, come))
sch.chiudi()

# ====================================================================== B. K2: «pronta» da vicino e da lontano
f = evo()
d = diario()
t0 = clk()
L.prova_k2(d, [f])
r = last(d, "K2")
check("B K2 con la scheda come quella vera: fatta, «pronta» arriva quando la testa è a casa",
      r["esito"] == "ok" and r["verdetto"] == "pronta_dopo_arrivo", r)
check("B tempi da vicino e da 10 cm: la differenza è il viaggio (100 mm a 50 mm/s = 2 s)",
      abs(r["differenza_s"] - 2.0) < 0.1 and abs(r["velocita_ritorno_circa"] - 50) < 3, r)
check("B K2 dura una decina di secondi, non più di un minuto come con la vecchia attesa", clk() - t0 < 15, clk() - t0)
kinds = [c[0] for c in f.comandi]
check("B la scheda ha ricevuto: casa, casa, 100 mm a destra, casa; la testa finisce a casa",
      kinds == ["casa", "casa", "velocita", "casa"] and f.x_mil == 0 and f.comandi[2][2] == 100.0, f.comandi)
check("B nessun comando pericoloso, nessun errore di controllo", not f.pericoli and f.crc_ko == 0)
f = evo(casa_subito=True)
d = diario()
L.prova_k2(d, [f])
r = last(d, "K2")
check("B scheda che dice «pronta» subito anche da lontano: lo riconosce", r["verdetto"] == "pronta_subito"
      and r["differenza_s"] < L.SOGLIA_ARRIVO_S, r)
d = diario()
L.prova_k2(d, [LihuiyuFinta(clk, sempre_occupata=True)])
check("B scheda sempre occupata: «nessuna fine vista», niente verdetto", last(d, "K2")["esito"] == "nessuna fine vista"
      and not last(d, "K2")["verdetto"])
f = evo()
n = {"i": 0}


def stop_presto():
    n["i"] += 1
    return n["i"] > 30


d = diario()
try:
    L.prova_k2(d, [f], stop_presto)
    fermata = False
except InterruptedError:
    fermata = True
check("B Ferma durante K2: la scheda riceve «I», il diario dice «fermata»", fermata and ("ferma",) in f.comandi
      and last(d, "K2")["esito"] == "fermata")

# ====================================================================== C. un solo lavoro con più corse
c = L.cmd_lavoro_unico("M2", 30.0, (50, -50, 100, -100))
check("C comando del lavoro unico: una entrata, quattro corse, una uscita",
      c.startswith(b"I" + L.codice_velocita("M2", 30).encode() + b"NBRS1E") and c.endswith(b"FNSE-")
      and c.count(b"S1E") == 1 and c.count(b"FNSE-") == 1, c)
check("C dentro solo lettere permesse (niente accensione del laser)", b"D" not in c and L.controlla(c) == c)
try:
    L.cmd_lavoro_unico("M2", 30.0, (50, 0))
    zero = False
except ValueError:
    zero = True
check("C una corsa nulla è rifiutata", zero)
f = evo()
sch = L.Scheda(f).apri()
sch.manda(c)
check("C la scheda finta lo legge da sola come un lavoro di quattro corse, e la testa torna al punto di partenza",
      f.comandi[-1][0] == "lavoro" and [x[0] for x in f.comandi[-1][2]] == ["B", "T", "B", "T"] and f.x_mil == 0
      and abs(f.comandi[-1][1] - 30) < 0.05, f.comandi)
check("C il comando lungo va in più pacchetti, continui", len(sch.mandati) == len(L.pacchetti(c)) >= 2)
sch.chiudi()

# ====================================================================== D. il conto dei giri, con i tempi veri di Evo
SEP = [2.469, 2.453, 4.297, 4.313]  # 30 mm/s, rapporto FLC-20261123-2036-E7DF
v = 49.99 / (4.305 - 2.461)
g = 2.461 - 50 / v
uno = 300 / v + g  # se il giro c'è una volta sola
quattro = 300 / v + 4 * g
r1, r4 = L.giri_nel_lavoro(SEP, uno), L.giri_nel_lavoro(SEP, quattro)
check("D con i tempi veri: velocità 27,1 mm/s e un giro da circa 0,6 s", abs(r1[1] - 27.11) < 0.05
      and abs(r1[2] - 0.62) < 0.03, r1)
check("D lavoro unico con un giro solo: conta 1", abs(r1[0] - 1) < 0.05, r1)
check("D lavoro unico con il giro a ogni corsa: conta 4", abs(r4[0] - 4) < 0.05, r4)
check("D tempi mancanti o al contrario: nessun conto (niente verdetti inventati)",
      L.giri_nel_lavoro([None] * 4, uno) is None and L.giri_nel_lavoro(SEP, None) is None
      and L.giri_nel_lavoro([4.3, 4.3, 2.4, 2.4], uno) is None)

# ====================================================================== E. K4 con la scheda finta
for giro, atteso in ((False, "solo_inizio_fine"), (True, "a_ogni_corsa")):
    f = evo(giro_per_corsa=giro)
    d = diario()
    t0 = clk()
    L.prova_k4(d, [f], "M2")
    r = last(d, "K4")
    check(f"E K4, giro {'a ogni corsa' if giro else 'una volta per lavoro'}: verdetto «{atteso}»",
          r["esito"] == "ok" and r["verdetto"] == atteso, r)
    kinds = [x[0] for x in f.comandi]
    check("E la scheda ha ricevuto: casa, quattro corse separate, un lavoro unico; la testa finisce a casa",
          kinds == ["casa"] + ["velocita"] * 4 + ["lavoro"] and f.x_mil == 0 and not f.pericoli, f.comandi)
    check("E K4 dura meno di un minuto", clk() - t0 < 60, clk() - t0)
d = diario()
L.prova_k4(d, [LihuiyuFinta(clk, sempre_occupata=True)], "M2")
check("E scheda sempre occupata: «tempi non misurati», senza verdetto", last(d, "K4")["esito"] == "tempi non misurati"
      and not last(d, "K4")["verdetto"])
f = evo()
n = {"i": 0}


def stop_dopo():
    n["i"] += 1
    return n["i"] > 200


d = diario()
try:
    L.prova_k4(d, [f], "M2", stop_dopo)
    fermata = False
except InterruptedError:
    fermata = True
check("E Ferma durante K4: «I» alla scheda, «fermata» nel diario", fermata and ("ferma",) in f.comandi
      and last(d, "K4")["esito"] == "fermata")
d = diario()
L.prova_k4(d, [], "M2")
check("E K4 senza collegamenti: «non collegata»", last(d, "K4")["esito"] == "non collegata")
f = evo()
d = diario()
t0 = clk()
L.prova_k3(d, [f], "M2")
check("E K3 con la scheda come quella vera: non aspetta più 25 s dopo la casa", last(d, "K3")["esito"] == "ok"
      and clk() - t0 < 80, clk() - t0)

# la scheda dice «pronta» subito mentre la testa sta ancora tornando: K3 e K4 non devono partire prima dell'arrivo
f = evo(casa_subito=True)
sch = L.Scheda(f).apri()
t0 = clk()
sec, visti, come = L._a_casa(sch)
check("E casa prima di una misura: se «pronta» arriva presto si aspettano comunque 8 s", sec < 1.0
      and L.CASA_SICURA_S <= clk() - t0 < L.CASA_SICURA_S + 2, (sec, clk() - t0))
t0 = clk()
L._a_casa(sch, fidati=True)
check("E dopo una K2 che ha detto «pronta all'arrivo»: niente attesa in più", clk() - t0 < 3, clk() - t0)
n = {"i": 0}


def stop_in_attesa():
    n["i"] += 1
    return n["i"] > 60


try:
    L._a_casa(sch, stop_in_attesa)
    fermata = False
except InterruptedError:
    fermata = True
check("E Ferma durante l'attesa della casa: si interrompe", fermata)
sch.chiudi()
f = LihuiyuFinta(clk)  # scheda che dopo la casa dice «finito»: è arrivata davvero, niente attesa
sch = L.Scheda(f).apri()
t0 = clk()
L._a_casa(sch)
check("E scheda che dice «finito» dopo la casa: niente attesa in più", clk() - t0 < 3, clk() - t0)
sch.chiudi()

# ====================================================================== F. finestra: K4 e «Fai tutte le prove»
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
DOMANDE = []
RISPOSTA = {"q": QMessageBox.Yes}


def domanda(*a, **k):
    DOMANDE.append(a[2] if len(a) > 2 else "")
    return RISPOSTA["q"]


QMessageBox.question = staticmethod(domanda)
from freelasercut.ui.dialogs_studio import StudioDialog  # noqa: E402

dlg = StudioDialog(None, None)
fw = evo()
dlg.k40_links = lambda: [fw]
dlg.k40_run = lambda cmd, **k: ""
from freelasercut.ui.dialogs_studio import prove_k40  # noqa: E402

check("F riga K4 «Un solo lavoro» e pulsante «Fai tutte le prove della K40»", "K4" in dlg.rows
      and ("K4", "Un solo lavoro") == prove_k40()[-1][:2] and dlg.b_tutte.text() == "Fai tutte le prove della K40",
      dlg.b_tutte.text())
RISPOSTA["q"] = QMessageBox.No
check("F «tutte» senza consenso: non parte e la scheda non riceve niente", dlg.run("K*", sync=True) is False
      and not fw.pacchetti)
RISPOSTA["q"] = QMessageBox.Yes
DOMANDE.clear()
t0 = clk()
ok = dlg.run("K*", sync=True)
log = dlg.log.toPlainText()
check("F «tutte» con il consenso: una sola domanda, che parla di due minuti e di 10 cm liberi",
      ok and len(DOMANDE) == 1 and "due minuti" in DOMANDE[0] and "10 cm" in DOMANDE[0], DOMANDE)
check("F K1–K4 «fatta»; K0 (qui non c'è una scheda vera da cercare) ha comunque il suo esito",
      all("✓" in dlg.rows[c][0].text() for c in ("K1", "K2", "K3", "K4"))
      and dlg.rows["K0"][0].text()[0] in "✓✗", {c: dlg.rows[c][0].text() for c in dlg.rows if c.startswith("K")})
check("F nel registro i risultati spiegati: casa, velocità in percentuale, giro solo all'inizio e alla fine",
      "Risultati:" in log and "quando la testa è arrivata a casa" in log and "92 % della velocità" in log
      and "solo all'inizio e alla fine" in log and "Invia un rapporto" in log, log[-900:])
check("F la scheda ha ricevuto solo comandi permessi, e la testa è tornata a casa", not fw.pericoli and fw.x_mil == 0)
check("F tutte le prove in circa due minuti", clk() - t0 < 180, clk() - t0)
check("F dopo una K2 «pronta all'arrivo», K3 e K4 non aggiungono l'attesa di sicurezza (meno di 110 s in tutto)",
      clk() - t0 < 110, clk() - t0)
righe = [r.get("prova") for r in dlg.diari["k40"].righe if r.get("evento") == "prova"]
check("F nel diario una riga per prova, in ordine", righe[-5:] == ["K0", "K1", "K2", "K3", "K4"], righe)
dlg.k40_links = lambda: []
dlg.log.clear()
dlg.run("K*", sync=True)
log = dlg.log.toPlainText()
check("F senza scheda: si ferma a K1 e non usa i risultati del giro prima",
      "✗" in dlg.rows["K1"][0].text() and dlg.rows["K3"][0].text() == "non fatta"
      and "solo all'inizio" not in log, {c: dlg.rows[c][0].text() for c in ("K1", "K2", "K3", "K4")})
dlg.k40_links = lambda: [evo()]
RISPOSTA["q"] = QMessageBox.Yes
check("F K4 da sola dalla sua riga: fatta, con il risultato in parole", dlg.run("K4", sync=True)
      and "✓" in dlg.rows["K4"][0].text() and "giri contati" in dlg.log.toPlainText())

# ====================================================================== G. testi tradotti
import freelasercut.ui.dialogs_studio as DS  # noqa: E402

src = open(DS.__file__, encoding="utf-8").read()
import ast  # noqa: E402

testi = set()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
            and isinstance(node.args[0], ast.Constant):
        testi.add(node.args[0].value)
mancano = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    m = [t for t in testi if not cat.get(t)]
    if m:
        mancano[lang] = m
check("G tutti i testi della finestra tradotti in inglese, spagnolo, francese e portoghese", not mancano, mancano)

# ====================================================================== H. difetti rimessi apposta
caught = []
orig = L.Scheda.aspetta_casa
L.Scheda.aspetta_casa = lambda self, massimo, ferma=None, stabile=1.0: (*self.aspetta_fine(massimo, ferma), "finito")
t0 = clk()  # 1. di nuovo l'attesa di «finito» dopo la casa
d = diario()
L.prova_k2(d, [evo()])
caught.append(clk() - t0 > 25 or last(d, "K2")["esito"] != "ok")
L.Scheda.aspetta_casa = orig
orig_g = L.giri_nel_lavoro
L.giri_nel_lavoro = lambda sep, uno, corse=L.CORSE_K4: orig_g(sep[::-1], uno, corse)  # 2. corse lunghe e corte scambiate
d = diario()
L.prova_k4(d, [evo()], "M2")
caught.append(last(d, "K4")["verdetto"] != "solo_inizio_fine")
L.giri_nel_lavoro = orig_g
orig_c = L.cmd_lavoro_unico
L.cmd_lavoro_unico = lambda s, v, corse: b"".join(L.cmd_a_velocita(s, v, x) for x in corse)  # 3. un lavoro per corsa
f = evo()
d = diario()
L.prova_k4(d, [f], "M2")
caught.append("lavoro" not in [x[0] for x in f.comandi] and last(d, "K4")["verdetto"] != "solo_inizio_fine")
L.cmd_lavoro_unico = orig_c
orig_s = L.SOGLIA_ARRIVO_S
L.SOGLIA_ARRIVO_S = 5.0  # 4. soglia sbagliata: l'arrivo non si vede più
d = diario()
L.prova_k2(d, [evo()])
caught.append(last(d, "K2")["verdetto"] == "pronta_subito")
L.SOGLIA_ARRIVO_S = orig_s
orig_cs = L.CASA_SICURA_S
L.CASA_SICURA_S = 0.0  # 5. niente attesa di sicurezza: la corsa partirebbe con la testa ancora in viaggio
sch = L.Scheda(evo(casa_subito=True)).apri()
t0 = clk()
L._a_casa(sch)
caught.append(clk() - t0 < 4)
sch.chiudi()
L.CASA_SICURA_S = orig_cs
check("H cinque difetti rimessi apposta (attesa di «finito», corse scambiate, un lavoro per corsa, soglia, attesa "
      "di sicurezza): tutti visti", all(caught), caught)

print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
