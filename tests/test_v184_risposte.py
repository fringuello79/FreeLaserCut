# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.4, dal rapporto FLC-20261110-1624-6EFE (Creality Falcon A1 10W, firmware CV40, ESP32-S3 con USB
nativo, [OPT:VcHL,127,65536]): la scheda ogni tanto non manda un «ok».
- verifica: alla fine mancava 1 risposta su 13483 → «la scheda ha smesso di rispondere», sempre, e il lavoro non
  partiva mai; il messaggio prometteva una «comunicazione più prudente» che era già quella in uso;
- lavoro: inciso tutto, ma 2 conferme mancanti → «il lavoro non avanza» e niente fine lavoro.
Ora poche risposte perse alla fine (al massimo LOST_OK_MAX), a macchina ferma e muta, chiudono normalmente verifica e
lavoro con un avviso; con molte risposte perse resta l'errore, con un messaggio onesto."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.grbl import GrblController, SIM_PORT, RX_BUFFER, LOST_OK_MAX  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info)


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


FALCON_INFO = ("[VER:1.1f.20220810:]\r\n[OPT:VcHL,127,65536]\r\n"
               "[software versions: CV40-MASTER-Release V1.0.6 20250306-1455]\r\nID:D0CF13189978\r\n")
# come il test materiale del rapporto: G55, aria, righe di raster, fine con M9 e G54
JOB = (["G90 G21", "M5 S0", "G10 L2 P2 X0 Y0", "G55", "M8", "M4 S0"]
       + [f"G1 X{10 + (i % 20)} Y{10 + (i // 20) * 0.1:.1f} S{250 if i % 2 else 0} F7500" for i in range(240)]
       + ["M5 S0", "M9", "G0 X0 Y0", "G54"])
N = len(JOB)

c = GrblController()
c.connect_port(SIM_PORT)
c.sim.speedup = 50
until(lambda: c.board_settings)
c.sim.info_text = FALCON_INFO
c.request_info()
until(lambda: any("CV40" in l for l in c.board_info))
check("Falcon A1 ([OPT:VcHL,127,65536], non nota): buffer prudente da 127 byte",
      not c.trusted_buffer and c.rx_buffer == RX_BUFFER, c.rx_buffer)
until(lambda: c.last_status.get("state") == "Idle")

done, fin, msgs = [], [], []
c.check_finished.connect(lambda r: done.append(r))
c.job_finished.connect(lambda ok, m: fin.append((ok, m)))
c.message.connect(lambda m: msgs.append(m))


def run_check(lose_rel=(), timeout=15):
    """lose_rel: righe del lavoro (da 1) di cui si perde l'«ok»; l'«ok» n. 1 è quello di $C."""
    done.clear()
    until(lambda: not c.busy and c.last_status.get("state") == "Idle", 8)
    base = c.sim._oks
    c.sim.lose_ok_at = {base + 1 + k for k in lose_rel}
    t0 = time.time()
    c.check_job(JOB)
    until(lambda: done, timeout)
    until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle", 8)
    c.sim.lose_ok_at = set()
    return (done[-1] if done else "nessun esito"), time.time() - t0


def run_job(lose_rel=(), lines=JOB, timeout=20):
    fin.clear()
    until(lambda: not c.busy and c.last_status.get("state") == "Idle", 8)
    base = c.sim._oks
    c.sim.lose_ok_at = {base + k for k in lose_rel}
    t0 = time.time()
    c.stream_job(lines)
    until(lambda: fin, timeout)
    c.sim.lose_ok_at = set()
    return (fin[-1] if fin else None), time.time() - t0


# ================================================================== verifica
pos0 = list(c.sim.pos)
r, dt = run_check()
check("verifica normale: nessun errore, nessuna risposta persa", r == [] and c.lost_replies == 0, (r, c.lost_replies))

r, dt = run_check([N])  # come nel rapporto: l'ultima riga (G54) senza risposta
check("verifica con l'ultima risposta persa (rapporto Falcon): finisce senza errori", r == [], r)
check("…in pochi secondi, senza aspettare i 6 s del blocco", dt < 5.5, f"{dt:.1f} s")
check("…conta 1 risposta persa e lo dice", c.lost_replies == 1 and any("risposte perse" in m for m in msgs), msgs[-1:])
check("…la scheda esce dalla modalità di prova e la testa non si è mossa",
      not c.sim.check_mode and c.sim.pos == pos0 and not c.check_stalled, (c.sim.check_mode, c.sim.pos))

r, dt = run_check([N - 2, N])  # M9 e G54
check("verifica con 2 risposte perse alla fine (M9, G54): finisce senza errori", r == [] and c.lost_replies == 2,
      (r, c.lost_replies))

r, dt = run_check([40, 130])  # risposte perse in mezzo: il buffer si stringe un po', le righe partono tutte
check("verifica con 2 risposte perse in mezzo: finisce senza errori", r == [] and c.lost_replies == 2,
      (r, c.lost_replies))

r, dt = run_check(range(N - LOST_OK_MAX, N + 1))  # una più del massimo
check(f"verifica con {LOST_OK_MAX + 1} risposte perse: resta l'errore «la scheda ha smesso di rispondere»",
      isinstance(r, list) and any(e[2] == "NO_RISPOSTA" for e in r), r[-1:] if isinstance(r, list) else r)
txt = next((e[3] for e in r if e[2] == "NO_RISPOSTA"), "") if isinstance(r, list) else ""
check("…buffer già prudente: il messaggio non promette più una comunicazione «più prudente»",
      "più prudente" not in txt and "USB" in txt and "prima di partire" in txt, txt)
check("…la scheda esce dalla modalità di prova", not c.sim.check_mode and c.last_status.get("state") == "Idle")

c.sim.drop_check_after = 60  # come prima (Acmer S1): dopo 60 righe la scheda non risponde più
r, dt = run_check()
c.sim.drop_check_after = None
check("verifica con le risposte che smettono a metà: errore come prima",
      isinstance(r, list) and any(e[2] == "NO_RISPOSTA" for e in r) and c.check_stalled, r[-1:] if isinstance(r, list) else r)
c.check_stalled = False

# ================================================================== lavoro
c.homed = True
f, dt = run_job()
check("lavoro normale: completato, nessuna risposta persa", f and f[0] and c.lost_replies == 0, f)

f, dt = run_job([N - 2, N])  # come nel rapporto: incisione finita, 2 conferme mancanti
check("lavoro con le ultime 2 risposte perse (rapporto Falcon): completato", f and f[0] is True, f)
check("…il messaggio dice che le conferme mancanti sono risposte perse", f and "risposte perse" in f[1], f)
check("…tutte le righe risultano confermate (nessuna ripresa da proporre)",
      c.job_acked == N and not c.job_active and not c.busy, (c.job_acked, N))
check("…la macchina ha davvero finito (testa a X0 Y0 come l'ultimo G0)",
      abs(c.sim.pos[0]) < 0.01 and abs(c.sim.pos[1]) < 0.01, c.sim.pos)

f, dt = run_job(range(N - LOST_OK_MAX, N + 1), timeout=8)
check(f"lavoro con {LOST_OK_MAX + 1} risposte perse: non si dichiara finito da solo",
      f is None and c.job_active, f)
c.stop_job()
until(lambda: not c.job_active and fin, 5)
until(lambda: c.last_status.get("state") in ("Idle", "Alarm"), 5)
until(lambda: False, 1.0)  # il riavvio della scheda dopo lo stop arriva ancora qui, non nella prova dopo
if c.last_status.get("state") == "Alarm":
    c.unlock()
    until(lambda: c.last_status.get("state") == "Idle", 5)

DWELL = JOB[:-1] + ["G4 P0.1", "G54"]
f, dt = run_job([len(DWELL) - 1], lines=DWELL, timeout=8)
check("risposta persa su una pausa G4: non si dichiara finito da solo (la pausa potrebbe essere in corso)",
      f is None and c.job_active, f)
c.stop_job()
until(lambda: not c.job_active, 5)

c.disconnect_port()

# ================================================================== traduzioni
import json  # noqa: E402

keys = ["La scheda non ha risposto alle ultime {0} righe della verifica (risposte perse, succede con alcune schede "
        "con l'USB nativo): le considero controllate.",
        "La scheda ha smesso di rispondere durante la verifica ({0} righe senza risposta). Prova a scollegare e "
        "ricollegare il cavo USB; se succede ancora, togli la spunta «Verifica il G-code con la scheda prima di "
        "partire» e manda un rapporto all'assistenza.",
        "Lavoro completato: {0} righe (la scheda non ha confermato le ultime {1}: risposte perse, la macchina ha "
        "finito)"]
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k for k in keys if not loc.get(k)]
    check(f"traduzioni {lang}: i 3 messaggi nuovi ci sono", not miss and all("{0}" in loc[k] for k in keys), miss)

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
