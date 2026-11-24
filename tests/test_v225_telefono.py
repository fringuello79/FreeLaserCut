# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.5: dal telefono si muove la testa (frecce e joystick) e la pagina ha un aspetto nuovo, sempre leggero.

Regole: si muove solo se sul PC è permesso (casella nella finestra Controllo dal telefono, spenta di partenza), con
la macchina connessa e ferma, senza lavori. Il laser non si accende mai. Il joystick si ferma da solo se il telefono
smette di mandare notizie (rete persa, pagina chiusa), quando lo lasci e con «■».

Uso: python tests/test_v225_telefono.py [classica|banco]
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

from freelasercut import phone  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


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
orig_rt = w.ctl.realtime
w.ctl.realtime = lambda b, *a, **k: (sent.append(("rt", b)), orig_rt(b, *a, **k))[1]
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected and w.ctl.last_status.get("state") == "Idle")
w.ctl.sim.speedup = 1
pd = w.phone_dialog()
pd.chk.setChecked(True)
base = f"http://127.0.0.1:{w.phone.server.port}/{w.phone.server.token}/"


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
    return out.get("r")


def state():
    w.phone.refresh()
    return json.loads(get("stato"))


def jogs():
    return [x for x in sent if isinstance(x, str) and x.startswith("$J=")]


# ====================================================================== A. la pagina
page = get("").decode("utf-8")
check("A pagina: sezione «Muovi la testa» con frecce, passi e joystick, laser spento scritto",
      "Muovi la testa" in page and 'data-d="0,1"' in page and 'data-s="50"' in page and 'id="joy"' in page
      and "laser spento" in page)
check("A aspetto: comandi in rilievo (ombre e pressione) e luce di stato, senza file esterni",
      "box-shadow" in page and "translateY(3px)" in page and 'id="led"' in page and "http" not in re.sub(
          r"(https?://)?(www\.)?w3\.org", "", page.split("<script>")[0]))
check("A pagina leggera (meno di 30 kB) e senza segnaposto", len(page.encode()) < 30000 and "{{" not in page
      and "[[" not in page, len(page))
check("A ancora nessun comando per avviare o riprendere", "avvia" not in page.lower().replace("avviarlo", "")
      and "riprendi" not in page.lower())
check("A pagina: i pulsanti di prima ci sono tutti (pausa, stop, camera, foto)",
      all(f'id="{i}"' in page for i in ("pause", "stop", "camb", "ph", "pl")))

# ====================================================================== B. permesso spento: non si muove
st = state()
check("B di partenza muovere dal telefono è spento, e lo stato dice perché", not st["move_ok"]
      and "spento" in st["move_note"] and not w.phone.move_enabled(), st.get("move_note"))
n0 = len(jogs())
code, r = post("muovi", {"dx": 1, "dy": 0, "step": 10})
spin(0.2)
check("B freccia con il permesso spento: rifiutata, nessun movimento", code == 200 and not r["ok"] and len(jogs()) == n0, r)

# ====================================================================== C. permesso acceso
pd.chk_move.setChecked(True)
check("C la casella si ricorda", w.phone.move_enabled() and str(w.qs.value("phone_move")).lower() in ("true", "1"))
until(lambda: state()["move_ok"], 5)
st = state()
check("C macchina ferma e connessa: si può muovere, con la posizione della testa", st["move_ok"] and st["pos"] is not None, st)
n0 = len(jogs())
code, r = post("muovi", {"dx": 1, "dy": 0, "step": 10})
until(lambda: len(jogs()) > n0, 3)
check("C freccia → destra 10 mm, nessuna accensione del laser", r["ok"] and jogs()[-1].startswith("$J=G91 G21 X10.000")
      and "M3" not in jogs()[-1] and "S" not in jogs()[-1].split("F")[0], jogs()[-1:])
code, r = post("muovi", {"dx": 0, "dy": 1, "step": 0.1})
until(lambda: "Y0.100" in (jogs()[-1] if jogs() else ""), 3)
check("C freccia su 0,1 mm", "Y0.100" in jogs()[-1], jogs()[-1:])
bad = [post("muovi", b)[1] for b in ({"dx": 5, "dy": 0, "step": 10}, {"dx": 1, "dy": 0, "step": 1000},
                                     {"dx": 0, "dy": 0, "step": 10}, {"dx": "x"})]
check("C richieste strane (passo di 1 m, direzione 5, niente direzione): rifiutate", all(not b["ok"] for b in bad), bad)
code, _ = post("muovi", ["non", "un", "oggetto"])
check("C corpo non valido: rifiutato senza errori del programma", code == 400)

# joystick
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
n0 = len(jogs())
for _ in range(5):
    post("joystick", {"x": 1, "y": 0})
    spin(0.12)
check("C joystick a destra: la testa si muove (pezzetti di jog)", len(jogs()) > n0 and w.phone.joy is not None
      and w.phone.joy.active, len(jogs()) - n0)
post("joystick", {"x": 0, "y": 0})
spin(0.1)
check("C joystick lasciato: si ferma (comando di arresto del jog)", not w.phone.joy.active and ("rt", 0x85) in sent)
post("joystick", {"x": 0, "y": 1})
spin(0.1)
active = w.phone.joy.active
sent.clear()
spin(1.0)  # il telefono non manda più niente (rete persa)
check("C telefono muto per più di 0,6 s: il joystick si ferma da solo", active and not w.phone.joy.active
      and ("rt", 0x85) in sent)
post("joystick", {"x": -1, "y": 0})
spin(0.1)
code, r = post("ferma-testa", {})
spin(0.1)
check("C «■» ferma la testa", r["ok"] and not w.phone.joy.active)
code, r = post("joystick", {"x": "nan", "y": 0})
check("C joystick con valori non numerici: rifiutato", not r["ok"])
big = [w.phone._move("passo", {"dx": 1e999, "dy": 0, "step": 10}), w.phone._move("passo", {"dx": 1, "dy": 0, "step": 10 ** 400}),
       w.phone._move("joystick", {"x": 10 ** 400, "y": 0})]
check("C numeri enormi o infiniti: rifiutati senza errori del programma", all(not b[0] for b in big), big)
import http.client  # noqa: E402


def raw_post(path, headers):
    out = {}

    def run():
        c = http.client.HTTPConnection("127.0.0.1", w.phone.server.port, timeout=5)
        c.putrequest("POST", f"/{w.phone.server.token}/{path}", skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders()
        out["s"] = c.getresponse().status
        c.close()
    t = threading.Thread(target=run)
    t.start()
    until(lambda: not t.is_alive(), 10)
    return out.get("s")


check("C lunghezza della richiesta negativa o non numerica: 400, niente letture senza fine",
      raw_post("muovi", {"X-FLC": "1", "Content-Length": "-5"}) == 400
      and raw_post("stop", {"X-FLC": "1", "Content-Length": "abc"}) == 400)

# frecce dentro il piano
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
w.phone.refresh()
hp = w.canvas.head_pos()
from freelasercut.ui.jogpad import reach_box  # noqa: E402

bx0, by0, bx1, by1 = reach_box(w.ctl, w.profile)
n0 = len(jogs())
for _ in range(3):
    w.phone._do_step(-1.0, 0.0, 50.0)  # tre tocchi di fila verso il bordo sinistro, senza aspettare
spin(0.2)
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
spin(0.5)
import re as _re  # noqa: E402

lefts = [float(_re.search(r"X(-?[\d.]+)", j).group(1)) for j in jogs()[n0:] if "X" in j]
hp2 = w.canvas.head_pos()
check("C frecce: tre tocchi da 50 mm verso il bordo non portano la testa fuori dal piano",
      hp2.x() >= bx0 + 0.4 and abs(sum(lefts)) <= max(hp.x() - bx0, 0) + 0.01, (hp.x(), hp2.x(), lefts, bx0))

# Puntino o Lucciola accesi dal PC: dal telefono non si muove
w.ctl.fire_active = True
st = state()
n0 = len(jogs())
r1 = post("muovi", {"dx": 1, "dy": 0, "step": 10})[1]
r2 = post("joystick", {"x": 1, "y": 0})[1]
spin(0.2)
check("C Puntino o Lucciola accesi sul PC: frecce e joystick rifiutati, e lo dice", not st["move_ok"]
      and "Lucciola" in st["move_note"] and not r1["ok"] and not r2["ok"] and len(jogs()) == n0, st.get("move_note"))
w.ctl.fire_active = False
until(lambda: state()["move_ok"], 5)

# ====================================================================== D. durante un lavoro: mai
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
job = ["G90", "M4 S0"] + [f"G1 X{10 + (i % 2) * 30} Y{10 + i * 0.2:.1f} F600 S0" for i in range(200)]
w.ctl.stream_job(job)
until(lambda: w.ctl.job_active, 5)
st = state()
check("D lavoro in corso: muovere dal telefono è spento e lo dice", not st["move_ok"] and "lavoro" in st["move_note"], st)
n0 = len(jogs())
r1 = post("muovi", {"dx": 1, "dy": 0, "step": 10})[1]
r2 = post("joystick", {"x": 1, "y": 0})[1]
spin(0.3)
check("D frecce e joystick rifiutati durante il lavoro, nessun jog mandato", not r1["ok"] and not r2["ok"]
      and len(jogs()) == n0)
w.ctl.stop_job()
until(lambda: not w.ctl.job_active, 10)

# ====================================================================== E. spento il permesso, spenta la pagina
pd.chk_move.setChecked(False)
st = state()
check("E tolta la casella: di nuovo spento", not st["move_ok"] and not w.phone.move_enabled())
sent.clear()
code, r = post("ferma-testa", {})
spin(0.2)
check("E con la funzione spenta nemmeno «■» manda qualcosa alla macchina", not r["ok"] and ("rt", 0x85) not in sent, sent)
check("E senza la funzione nel server (move=None): 404", phone.PhoneServer(lambda: {}, None, None, None, None).move is None)

# ====================================================================== F. testi tradotti
import ast  # noqa: E402

testi = set()
for f in ("freelasercut/phone.py", "freelasercut/ui/phone_ui.py"):
    for node in ast.walk(ast.parse(open(os.path.join(ROOT, f), encoding="utf-8").read())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
                and isinstance(node.args[0], ast.Constant):
            testi.add(node.args[0].value)
mancano = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    m = [t for t in testi if not cat.get(t)]
    if m:
        mancano[lang] = m
check("F testi del telefono tradotti in inglese, spagnolo, francese e portoghese", not mancano, mancano)

# ====================================================================== G. difetti rimessi apposta
caught = []
orig_check = w.phone.move_check
w.phone.move_check = lambda: (True, "")  # 1. nessun controllo: si muoverebbe anche durante un lavoro
w.ctl.stream_job(job)
until(lambda: w.ctl.job_active, 5)
w.phone.refresh()
caught.append(w.phone.snapshot["move_ok"] is True)
w.phone.move_check = orig_check
w.ctl.stop_job()
until(lambda: not w.ctl.job_active, 10)
w.phone.JOY_TIMEOUT_MS = 10 ** 6
w.phone.joy_watch.setInterval(10 ** 6)  # 2. niente sorveglianza: il joystick non si fermerebbe
pd.chk_move.setChecked(True)
until(lambda: state()["move_ok"], 5)
post("joystick", {"x": 0, "y": 1})
spin(1.0)
caught.append(w.phone.joy is not None and w.phone.joy.active)
w.phone._do_halt()
w.phone.joy_watch.setInterval(600)
caught.append(not phone.PAGE.count("joyEnd") < 3)  # 3. la pagina senza l'arresto al rilascio (contato sopra)
import freelasercut.ui.jogpad as _jp  # noqa: E402

orig_rb = _jp.reach_box
_jp.reach_box = lambda ctl, prof: (-1e6, -1e6, 1e6, 1e6)  # 4. frecce senza il limite del piano
until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
spin(0.9)  # passata l'attesa dopo l'arresto del joystick
sent.clear()
w.phone._do_step(-1.0, 0.0, 50.0)
spin(0.2)
caught.append(any(isinstance(x, str) and "X-50.000" in x for x in sent))
w.phone._do_halt(cancel=True)
_jp.reach_box = orig_rb
check("G difetti rimessi apposta (controlli tolti, sorveglianza tolta, frecce senza limite): visti", all(caught), caught)

pd.chk.setChecked(False)
w.close()
print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
