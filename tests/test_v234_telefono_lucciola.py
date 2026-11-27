# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.4 (richiesta di Ale del 26/11): dal Controllo dal telefono si accende e si spegne la Lucciola.

Regole (con tutti i limiti della Lucciola del PC: tetto di potenza dai watt, 5 minuti senza movimenti, spenta da
lavoro, verifica, allarme, porta, cavo staccato):
- permesso sul PC a parte, spento di partenza, valido solo per la sessione e solo con i movimenti dal telefono;
- la prima volta in ogni sessione si accende dal PC (l'avviso lo deve leggere chi è davanti alla macchina);
- stessa potenza scelta sul PC, mai oltre il tetto; niente sulla K40; niente con il Puntino o la Lucciola del PC;
- spegnere dal telefono si può sempre, ma spegne solo quella accesa dal telefono;
- si spegne se il telefono tace per più di 2,5 s (pagina chiusa, rete persa), con «■», togliendo i permessi o
  spegnendo il controllo dal telefono;
- accesa dal telefono, la testa si può muovere dal telefono (serve a vedere dove punta). Il Puntino del PC blocca.

Uso: python tests/test_v234_telefono_lucciola.py [classica|banco]
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

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
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Yes))

from freelasercut import grbl  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import panels_machine  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

warned = []
panels_machine.confirm_glow = lambda *a, **k: (warned.append(1), True)[1]  # l'avviso del PC: «accetto»


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def spin(t):
    until(lambda: False, t)


w = MainWindow()
w.show()
until(lambda: True, 0.2)
sent = []
orig_send = w.ctl.send_line
w.ctl.send_line = lambda line, *a, **k: (sent.append(line), orig_send(line, *a, **k))[1]
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected and w.ctl.last_status.get("state") == "Idle")
w.ctl.sim.speedup = 1
lz = w.laser
pd = w.phone_dialog()
pd.chk.setChecked(True)
pc = w.phone
base = f"http://127.0.0.1:{pc.server.port}/{pc.server.token}/"


def get(path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.read()


def post(path, body):
    out = {}

    def run():
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"X-FLC": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                out["r"] = (r.status, json.loads(r.read()))
        except urllib.error.HTTPError as ex:
            out["r"] = (ex.code, {})
    t = threading.Thread(target=run)
    t.start()
    until(lambda: not t.is_alive(), 10)
    spin(0.1)  # il comando arriva al thread principale con un segnale
    return out.get("r")


def state():
    pc.refresh()
    return json.loads(get("stato"))


def fires():
    return [x for x in sent if isinstance(x, str) and (x.startswith("M3") or x.startswith("M5"))]


def m3_values():
    out = []
    for x in sent:
        m = re.match(r"M3 S([\d.]+)", x) if isinstance(x, str) else None
        if m:
            out.append(float(m.group(1)))
    return out


def alive_until(fn, t=3.0):
    """Aspetta come until, ma con il telefono che intanto chiede lo stato (come la pagina vera): così la Lucciola
    non si spegne per il silenzio del telefono e si vede se a spegnerla è proprio il comando provato."""
    e = time.time() + t
    while time.time() < e and not fn():
        state()
        spin(0.2)
    return fn()


def phone_on():
    pc.refresh()  # come la pagina vera: lo stato si aggiorna ogni mezzo secondo e il tocco arriva dopo
    return post("lucciola", {"on": True})


def reset():
    """Lucciola spenta dappertutto, permessi come prima."""
    if lz._glow_on:
        lz.glow_stop()
    if w.ctl.fire_active:
        w.ctl.fire(False)
    spin(0.1)


# ====================================================================== A. la pagina
page = get("").decode("utf-8")
check("A pagina: pulsante Lucciola nella sezione dei movimenti, nascosto finché non è permesso",
      'id="glowrow" class="hide"' in page and 'id="glow"' in page and "Accendi la Lucciola" in page)
check("A pagina: spegnimento quando la pagina va in secondo piano", "visibilitychange" in page
      and "'lucciola', '{\"on\":false}'" in page)
check("A pagina ancora leggera e senza comandi per avviare o riprendere", len(page.encode()) < 30000
      and "avvia" not in page.lower().replace("avviarlo", "") and "riprendi" not in page.lower(), len(page))

# ====================================================================== B. permessi
st = state()
check("B di partenza: Lucciola dal telefono non permessa, pulsante nascosto", not st["glow"]["perm"]
      and not st["glow"]["ok"] and not pc.glow_enabled())
n0 = len(fires())
code, r = phone_on()
check("B senza permesso: rifiutata, nessun M3", code == 200 and not r["ok"] and len(fires()) == n0
      and "permette sul PC" in r["msg"], r)
pc.set_glow_enabled(True)
check("B senza i movimenti dal telefono il permesso della Lucciola non si accende", not pc.glow_enabled()
      and not pd.chk_glow.isEnabled())
pd.chk_move.setChecked(True)
check("B movimenti permessi: la casella della Lucciola si può spuntare", pd.chk_glow.isEnabled()
      and not pd.chk_glow.isChecked())
pd.chk_glow.setChecked(True)
check("B permesso dato dalla casella", pc.glow_enabled())
check("B il permesso non si salva nelle preferenze (vale solo per la sessione)",
      not any("glow" in k and "phone" in k for k in w.qs.allKeys()), [k for k in w.qs.allKeys() if "phone" in k])

# ====================================================================== C. prima volta solo dal PC
n0 = len(fires())
st = state()
code, r = phone_on()
check("C avviso non ancora accettato sul PC: rifiutata, nessun M3, il telefono dice perché",
      not r["ok"] and len(fires()) == n0 and "dal PC" in r["msg"] and not st["glow"]["ok"], r)
check("C …e nessun avviso aperto per conto del telefono", not warned)
check("C anche chiamata direttamente, l'accensione «dal telefono» senza avviso accettato non parte",
      lz.glow_start_on(from_phone=True) is False and not lz._glow_on and not w.ctl.fire_active and not warned)
lz.glow_start_on()  # dal PC: avviso accettato
spin(0.2)
check("C dal PC: accesa, avviso accettato una volta", lz._glow_on and lz.glow_owner == "pc" and warned == [1])
st = state()
check("C Lucciola del PC: il telefono la vede accesa ma non sua, non la può accendere", st["glow"]["on"]
      and not st["glow"]["mine"] and not st["glow"]["ok"] and "dal PC" in st["glow"]["note"], st["glow"])
code, r = post("lucciola", {"on": False})
check("C «spegni» dal telefono non spegne quella del PC", lz._glow_on and w.ctl.fire_active)
check("C con la Lucciola del PC le frecce del telefono restano bloccate", not state()["move_ok"])
lz.glow_stop()
spin(0.2)

# ====================================================================== D. accesa dal telefono
sent.clear()
code, r = phone_on()
until(lambda: lz._glow_on, 3)
st = state()
cap = lz.glow_cap
check("D accesa dal telefono: laser acceso, del telefono, senza un altro avviso", r["ok"] and lz._glow_on
      and lz.glow_owner == "phone" and w.ctl.fire_active and warned == [1], (r, lz.glow_owner))
check("D potenza: quella scelta sul PC, mai oltre il tetto del laser", m3_values()
      and all(v <= cap / 100.0 * lz.s_max + 1e-6 for v in m3_values())
      and abs(m3_values()[-1] - min(lz.glow_pct.value(), cap) / 100.0 * lz.s_max) < 0.06, (m3_values(), cap))
check("D sul telefono: accesa e sua, con il tempo che manca", st["glow"]["on"] and st["glow"]["mine"]
      and 0 < st["glow"]["left"] <= grbl.GLOW_S, st["glow"])
check("D sul PC il pulsante della Lucciola è acceso (si può spegnere da lì)", lz.b_glow.isChecked())
check("D il testo della pagina dice 5 minuti come il programma", grbl.GLOW_S == 300.0)
n0 = len(fires())
phone_on()
check("D seconda accensione: nessun M3 in più", len([x for x in fires()[n0:] if x.startswith("M3")]) == 0)

# ====================================================================== E. muovere con la Lucciola del telefono
until(lambda: state()["move_ok"], 5)
check("E Lucciola del telefono: le frecce del telefono funzionano", state()["move_ok"])
lz._glow_deadline = time.time() + 60  # come se fosse accesa da 4 minuti
n0 = len(sent)
code, r = post("muovi", {"dx": 1, "dy": 0, "step": 10})
until(lambda: any(isinstance(x, str) and x.startswith("$J=") for x in sent[n0:]), 3)
until(lambda: lz.glow_seconds_left() > 200, 5)
check("E freccia: la testa si muove e la Lucciola resta accesa", r["ok"] and lz._glow_on and w.ctl.fire_active)
check("E il movimento fa ripartire i 5 minuti", lz.glow_seconds_left() > 200, lz.glow_seconds_left())

# ====================================================================== F. spegnere dal telefono
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
code, r = post("lucciola", {"on": False})
until(lambda: not lz._glow_on, 3)
check("F spenta dal telefono: M5, laser spento, pulsante del PC spento", r["ok"] and not lz._glow_on
      and not w.ctl.fire_active and fires()[-1].startswith("M5") and not lz.b_glow.isChecked())
check("F richieste strane: rifiutate", not post("lucciola", {"on": "sì"})[1]["ok"]
      and post("lucciola", ["x"])[0] == 400)

# ====================================================================== G. il telefono tace
phone_on()
until(lambda: lz._glow_on, 3)
on_before = lz._glow_on
t0 = time.time()
until(lambda: not lz._glow_on, 6)  # nessuna richiesta dal telefono
dt = time.time() - t0
check("G telefono muto: spenta da sola fra 2,5 e 4 s", on_before and not lz._glow_on and not w.ctl.fire_active
      and 2.0 <= dt <= 4.0, round(dt, 2))
phone_on()
until(lambda: lz._glow_on, 3)
ok_alive = True
for _ in range(8):  # il telefono chiede lo stato ogni secondo, come la pagina vera
    state()
    spin(0.6)
    ok_alive = ok_alive and lz._glow_on
check("G telefono che risponde: resta accesa", ok_alive)

# ====================================================================== H. «■», permessi, controllo spento
phone_on()
alive_until(lambda: lz._glow_on, 3)
code, r = post("ferma-testa", {})
alive_until(lambda: not lz._glow_on, 1.5)
check("H «■» dal telefono: spenta (subito, con il telefono che risponde)", not lz._glow_on and not w.ctl.fire_active)
phone_on()
until(lambda: lz._glow_on, 3)
pd.chk_glow.setChecked(False)
spin(0.1)
check("H tolto il permesso della Lucciola: spenta", not lz._glow_on and not w.ctl.fire_active)
pd.chk_glow.setChecked(True)
phone_on()
until(lambda: lz._glow_on, 3)
pd.chk_move.setChecked(False)
spin(0.1)
check("H tolto il permesso dei movimenti: spenta, e anche il permesso della Lucciola",
      not lz._glow_on and not pc.glow_enabled() and not pd.chk_glow.isChecked() and not pd.chk_glow.isEnabled())
pd.chk_move.setChecked(True)
pd.chk_glow.setChecked(True)
phone_on()
until(lambda: lz._glow_on, 3)
pd.chk.setChecked(False)
check("H controllo dal telefono spento: spenta subito", not lz._glow_on and not w.ctl.fire_active)
pd.chk.setChecked(True)
base = f"http://127.0.0.1:{pc.server.port}/{pc.server.token}/"

# ====================================================================== I. condizioni della macchina
reset()
w.ctl.fire(True, 1.0)  # Puntino dal PC
spin(0.1)
code, r = phone_on()
check("I Puntino acceso dal PC: rifiutata", not r["ok"] and "Puntino" in r["msg"] and not lz._glow_on, r)
check("I …e le frecce del telefono restano bloccate", not state()["move_ok"])
reset()
lz.set_power_knob(True)
code, r = phone_on()
check("I K40 (potenza dalla manopola): rifiutata", not r["ok"] and "manopola" in r["msg"] and not lz._glow_on, r)
lz.set_power_knob(False)
w.ctl.last_status["state"] = "Alarm"
code, r = phone_on()
check("I allarme: rifiutata", not r["ok"] and not lz._glow_on, r)
w.ctl.last_status["state"] = "Idle"
phone_on()
until(lambda: lz._glow_on, 3)
job = ["G90", "M4 S0"] + [f"G1 X{10 + (i % 2) * 30} Y{10 + i * 0.2:.1f} F600 S0" for i in range(200)]
w.ctl.stream_job(job)
until(lambda: w.ctl.job_active, 5)
until(lambda: not lz._glow_on, 3)
check("I parte un lavoro dal PC: Lucciola del telefono spenta", w.ctl.job_active and not lz._glow_on)
code, r = phone_on()
check("I durante il lavoro: rifiutata", not r["ok"] and not lz._glow_on, r)
w.ctl.stop_job()
until(lambda: not w.ctl.job_active, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
phone_on()
until(lambda: lz._glow_on, 3)
w.ctl.disconnect_port()
until(lambda: not w.ctl.connected, 5)
spin(0.6)
check("I macchina scollegata: spenta", not lz._glow_on)

# ====================================================================== L. la finestra
check("L casella nella finestra, con il suggerimento sui limiti", "Lucciola" in pd.chk_glow.text()
      and "5 minuti" in pd.chk_glow.toolTip() and "occhiali" in pd.chk_glow.toolTip())

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} prove superate")
sys.stdout.flush()
pc.stop()
from _uscita import esci  # noqa: E402

esci(code)
