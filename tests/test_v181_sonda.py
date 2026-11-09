# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.1 (da un utente con laser CO2 e scheda MKS DLC32): sonda dell'autofocus letta al contrario.

Con la sonda spostata sull'ingresso «Probe» (IO22) l'autofocus funzionava solo dopo aver cambiato a mano $6 da 0
a 1. Ora la finestra «Asse Z e autofocus» ha il pulsante «Inverti il segnale della sonda» e, se la sonda risulta
toccata per più di qualche secondo, spiega le due cause possibili. FreeLaserCut scrive $6 solo dopo il clic e la
conferma, poi rilegge $$ per controllare.

Matrice dei casi (una prova per riga):
- lettura di $6: 0, 1, «1.000», chiave testo, assente, valore strano, nessuna impostazione;
- simulatore: sonda normale e «normalmente chiusa», con $6=0 e $6=1; nessuna sonda (ingresso libero); sonda sul
  finecorsa Z (come prima, non cambia con $6);
- autofocus: sonda NC con $6=0 rifiutato con il consiglio; dopo l'inversione riuscito alla quota giusta;
- finestra: testo del pulsante, scollegato, scheda senza $6, avviso solo dopo STUCK_S, sì / no alla conferma,
  rilettura che conferma, rilettura che non conferma, nessuna rilettura (timeout), doppia inversione = come prima,
  in allarme sì, durante l'autofocus no, chiusura della finestra a scrittura in corso;
- Classica e Banco (argomento della riga di comando).
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
ANSWER = [QMessageBox.Yes]
ASKED = []


def _question(*a, **k):
    ASKED.append(a[2] if len(a) > 2 else "")
    return ANSWER[0]


QMessageBox.question = staticmethod(_question)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import autofocus as af  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


def wait(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# ------------------------------------------------------------------ lettura di $6
check("$6 letto: 0 → si scrive 1, 1 → si scrive 0",
      (af.invert_now({6: "0"}), af.invert_target({6: "0"}), af.invert_now({6: "1"}), af.invert_target({6: "1"}))
      == (0, 1, 1, 0))
check("$6 con i decimali o con la chiave in testo", af.invert_now({6: "1.000"}) == 1 and af.invert_now({"6": "0"}) == 0)
check("scheda senza $6, valore strano o nessuna impostazione: None (il pulsante resta spento)",
      (af.invert_now({}), af.invert_now({6: "2"}), af.invert_now({6: "abc"}), af.invert_now(None),
       af.invert_target({5: "1"})) == (None, None, None, None, None))
check("allarme 4 (sonda già toccata): cita $6 e il pulsante", "$6" in af.explain_alarm(4)
      and "Inverti il segnale della sonda" in af.explain_alarm(4))

# ------------------------------------------------------------------ simulatore
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
c = w.ctl
res = []
c.autofocus_done.connect(lambda ok, m, z: res.append((ok, m, z)))
c.connect_port(SIM_PORT)
check("simulatore collegato", until(lambda: c.last_status.get("state") == "Idle" and 6 in c.board_settings),
      c.last_status)
sim = c.sim
pins = lambda: c.last_status.get("pins")  # noqa: E731

check("nessuna sonda, $6=0: l'ingresso libero risulta toccato (come il B1 vero)", until(lambda: pins() == "P", 3), pins())
sim.settings[6] = "1"
check("nessuna sonda, $6=1: risulta libero", until(lambda: pins() is None, 3), pins())
sim.settings[6] = "0"
sim.surface_z = -20.0
check("sonda normale, $6=0, a riposo: libera", until(lambda: pins() is None, 3), pins())
sim.pos[2] = -20.0
check("sonda normale, $6=0, appoggiata: toccata", until(lambda: pins() == "P", 3), pins())
sim.pos[2] = 0.0
sim.probe_nc = True
check("sonda normalmente chiusa, $6=0, a riposo: la scheda la vede TOCCATA", until(lambda: pins() == "P", 3), pins())
res.clear()
check("…l'autofocus non parte e consiglia di invertire $6",
      c.autofocus(8, 30, 200, 40) is False and res and "$6" in res[-1][1], res)
sim.settings[6] = "1"
check("sonda normalmente chiusa, $6=1, a riposo: libera", until(lambda: pins() is None, 3), pins())
res.clear()
check("…l'autofocus parte", c.autofocus(8, 30, 200, 40) is True)
until(lambda: res)
check("…tocca il materiale a -20 e si ferma 8 mm sopra (come Giuseppe dopo $6=1)",
      res and res[-1][0] and abs(res[-1][2] + 20) < 1e-6 and abs(sim.pos[2] + 12) < 1e-6, (res, sim.pos))
until(lambda: not c.busy and c.last_status.get("state") == "Idle", 3)
sim.pos[2] = -20.0
check("sonda normalmente chiusa, $6=1, appoggiata: toccata", until(lambda: pins() == "P", 3), pins())
sim.pos[2] = 0.0
sim.probe_nc = False
sim.probe_wiring = "zlimit"
sim.pos[2] = -20.0
check("sonda sul finecorsa Z: resta un finecorsa anche con $6=1 (P non compare)", until(lambda: pins() == "Z", 3), pins())
sim.pos[2] = 0.0
sim.probe_wiring = "probe"

# ------------------------------------------------------------------ finestra
from freelasercut.ui.dialogs_autofocus import AutofocusDialog  # noqa: E402

sim.settings[6] = "0"
sim.surface_z = -20.0
sim.probe_nc = True  # di nuovo come Giuseppe prima della modifica
c.request_settings()
until(lambda: c.board_settings.get(6) == "0" and pins() == "P", 3)
af.STUCK_S = 0.6  # più breve per la prova (di partenza 3 s)
dlg = AutofocusDialog(w)
dlg.show()
wait(0.2)
check("pulsante con il valore attuale e quello nuovo: «$6: 0 → 1»", "$6: 0 → 1" in dlg.b_invert.text()
      and dlg.b_invert.isEnabled(), dlg.b_invert.text())
check("sonda toccata da poco: ancora nessun avviso in evidenza", not dlg.stuck() and "#E8590C" not in
      dlg.inv_hint.styleSheet())
check("dopo STUCK_S secondi di «TOCCATA»: avviso con le due cause (segnale al contrario, sonda non collegata)",
      until(lambda: dlg.stuck() and "#E8590C" in dlg.inv_hint.styleSheet(), 3)
      and "normalmente chiuse" in dlg.inv_hint.text() and "non è collegata" in dlg.inv_hint.text(), dlg.inv_hint.text())

ANSWER[0] = QMessageBox.No
ASKED.clear()
dlg.b_invert.click()
wait(0.8)
check("conferma con «No»: niente scritto sulla scheda", ASKED and sim.settings[6] == "0" and dlg._inv_wait is None,
      (ASKED, sim.settings[6]))
check("…il testo della conferma dice valore nuovo, valore attuale e la copia delle impostazioni",
      ASKED and "$6=1" in ASKED[-1] and "$6=0" in ASKED[-1] and "copia" in ASKED[-1], ASKED)

ANSWER[0] = QMessageBox.Yes
dlg.b_invert.click()
check("durante la scrittura il pulsante è spento (niente doppio clic)", not dlg.b_invert.isEnabled())
check("con «Sì»: $6=1 scritto e riletto, la finestra lo conferma", until(lambda: "Fatto" in dlg.result.text(), 5)
      and sim.settings[6] == "1" and c.board_settings.get(6) == "1", (dlg.result.text(), sim.settings[6]))
check("…la sonda ora risulta libera e l'avviso torna normale", until(lambda: pins() is None, 3)
      and until(lambda: "#E8590C" not in dlg.inv_hint.styleSheet(), 3) and not dlg.stuck())
check("…il pulsante ora propone il ritorno: «$6: 1 → 0»", until(lambda: "$6: 1 → 0" in dlg.b_invert.text()
                                                              and dlg.b_invert.isEnabled(), 3), dlg.b_invert.text())
dlg.b_invert.click()
check("seconda inversione: di nuovo $6=0, come all'inizio", until(lambda: c.board_settings.get(6) == "0"
                                                                   and "Fatto" in dlg.result.text(), 5)
      and sim.settings[6] == "0", sim.settings[6])
check("…e la sonda NC torna a risultare toccata", until(lambda: pins() == "P", 3), pins())

# la scheda non accetta il valore (rilettura con il valore di prima)
orig_write = c.write_setting
c.write_setting = lambda n, v: None
until(lambda: dlg.b_invert.isEnabled(), 3)
dlg.b_invert.click()
check("la scheda non accetta la modifica: lo dice, con il valore che ha davvero", until(
    lambda: "non ha accettato" in dlg.result.text(), 5) and "$6=0" in dlg.result.text(), dlg.result.text())
check("…e il pulsante torna attivo", until(lambda: dlg.b_invert.isEnabled(), 3))

# nessuna rilettura entro 5 s
orig_req = c.request_settings
c.request_settings = lambda: None
dlg.b_invert.click()
check("nessuna rilettura entro 5 s: messaggio e pulsante di nuovo attivo", until(
    lambda: "rileggere" in dlg.result.text() and dlg.b_invert.isEnabled(), 8), dlg.result.text())
c.write_setting, c.request_settings = orig_write, orig_req

# in allarme si può (GRBL accetta i $ anche in allarme), durante l'autofocus no
c.request_settings()
until(lambda: c.board_settings.get(6) == "0", 3)
sim.state = "Alarm"
check("macchina in allarme: il pulsante resta attivo", until(lambda: c.last_status.get("state") == "Alarm"
                                                             and dlg.b_invert.isEnabled(), 3), c.last_status)
c.unlock()
until(lambda: c.last_status.get("state") == "Idle", 3)
sim.settings[6] = "1"
c.request_settings()
until(lambda: c.board_settings.get(6) == "1" and pins() is None, 3)
c._af = {"z": None}  # autofocus in corso (il simulatore lo finirebbe prima del controllo)
dlg._state()
check("durante l'autofocus il pulsante è spento", c.autofocusing and not dlg.b_invert.isEnabled())
c._af = None
dlg._state()
check("…finito l'autofocus torna attivo", dlg.b_invert.isEnabled())
sim.surface_z = -20.0
sim.pos[2] = 0.0

# scheda senza $6 (per esempio FluidNC)
c.board_settings.pop(6, None)
dlg._state()
check("scheda senza $6: pulsante spento con la spiegazione (FluidNC)", not dlg.b_invert.isEnabled()
      and "FluidNC" in dlg.b_invert.toolTip(), dlg.b_invert.toolTip())
c.request_settings()
until(lambda: 6 in c.board_settings, 3)

# chiusura con la scrittura in corso: niente errori dopo
dlg.b_invert.click()
dlg.close()
wait(5.5)
check("finestra chiusa a scrittura in corso: nessun errore alla rilettura né al timeout", True)

c.disconnect_port()
until(lambda: not c.connected, 3)
dlg2 = AutofocusDialog(w)
check("scollegato: pulsante spento e nessun avviso", not dlg2.b_invert.isEnabled() and not dlg2.stuck())
dlg2.done(0)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
