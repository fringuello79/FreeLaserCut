# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5: macro, pulsanti personali nella scheda Movimento (idea di Mauro D., issue #25, 27/11/2026).

Mauro: «sulla iKier c'è un pulsante fisico che esegue tutta la procedura di autofocus; da LightBurn una macro con un
pezzetto di codice GRBL ottiene lo stesso risultato: macro anche su FLC?». Ora nella scheda Movimento (nel Banco:
Officina) c'è la sezione «Macro»: «Macro…» apre la finestra dove si scrivono nome e righe; ogni macro diventa un
pulsante che manda quelle righe alla scheda, come la Console.

Casi: lettura delle righe (commenti, righe vuote, troppo lunghe, troppe, caratteri strani); riconoscimento di laser
acceso (M3/M4, non M30/M5/G3) e impostazioni della scheda; M5 aggiunto in fondo solo se serve; preferenza salvata,
rovinata, troppe macro; finestra (nuova, nome, comandi, ordine, elimina, nome vuoto e errori che bloccano il
salvataggio); pulsanti spenti senza laser; con il simulatore: macro semplice mandata, conferma chiesta per il laser
(rifiutata = niente alla scheda; accettata = M5 alla fine), macchina non pronta, K40; larghezza del pannello con 12
macro dai nomi lunghi. Difetti rimessi apposta: M5 non aggiunto; macro che parte con la macchina non pronta.

Uso: python tests/test_v235_macro.py [classica|banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
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

from freelasercut import macros as M  # noqa: E402
from freelasercut.grbl import K40_PORT, SIM_PORT  # noqa: E402
from freelasercut.i18n import LANGUAGES, SOURCE  # noqa: E402
from freelasercut.ui import macro_ui  # noqa: E402


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def spin(sec):
    until(lambda: False, sec)


print("--- A. righe, rischi, M5")
lines, err = M.parse("; autofocus iKier\nG91 (relativo)\n\n  G0 Z5  \nG90 ; di nuovo assoluto\n")
check("commenti «;» e «(…)» e righe vuote tolti", lines == ["G91", "G0 Z5", "G90"] and not err, (lines, err))
check("nessun comando: errore", M.parse(" ; solo un commento\n\n")[1] != [])
check("riga troppo lunga: errore con il numero di riga", any("2" in e for e in M.parse("M8\nG0 X" + "1" * 200)[1]))
check("troppe righe: errore", M.parse("\n".join(["M8"] * (M.MAX_LINES + 1)))[1] != [])
check("caratteri strani (accenti, tabulazioni, controllo): errore", M.parse("G0 X10°")[1] != []
      and M.parse("G0\tX1")[1] != [] and M.parse("M3\x18")[1] != [])
check("M3, M4, m03 e «G1 X5 M3 S100» accendono il laser", all("laser" in M.risks([x]) for x in
                                                             ("M3", "M4 S200", "m03", "G1 X5 M3 S100", "M3S500")))
check("M30, M5, G3, M8, M35 non accendono il laser", not any(M.risks([x]) for x in
                                                            ("M30", "M5", "G3 X1 Y1 I1", "M8", "M35", "G0 X3.4")))
check("$110=5000, $RST=*, $N0= cambiano le impostazioni; $$, $H, $X, $J= no",
      all("settings" in M.risks([x]) for x in ("$110=5000", "$RST=*", "$N0=G21", "$32 = 1"))
      and not any(M.risks([x]) for x in ("$$", "$H", "$X", "$J=G91 X1 F100", "$I", "$G")))
check("M5 aggiunto se il laser resta acceso", M.with_laser_off(["M3 S10", "G1 X5 F100"]) == ["M3 S10", "G1 X5 F100", "M5"])
check("M5 non aggiunto se c'è già o se il laser non si accende",
      M.with_laser_off(["M3 S10", "G1 X5", "M5"]) == ["M3 S10", "G1 X5", "M5"] and M.with_laser_off(["M8"]) == ["M8"])

print("--- B. preferenza")
from PySide6.QtCore import QSettings  # noqa: E402

qs = QSettings(os.path.join(tempfile.mkdtemp(), "m.ini"), QSettings.IniFormat)
check("senza preferenza: nessuna macro", M.load(qs) == [])
qs.setValue(M.KEY, "{rotto")
check("preferenza rovinata: nessuna macro, niente errori", M.load(qs) == [])
qs.setValue(M.KEY, '[{"name": "  Aria   su ", "code": "M8"}, {"name": "", "code": "M9"}, 5, {"name": "x"}]')
check("voci strane scartate, nome ripulito", M.load(qs) == [{"name": "Aria su", "code": "M8"}], M.load(qs))
M.save(qs, [{"name": f"M{i}", "code": "M8"} for i in range(20)])
check(f"al massimo {M.MAX_MACROS} macro", len(M.load(qs)) == M.MAX_MACROS)

print("--- C. stato della macchina (finta)")


class FakeCtl:
    def __init__(self, **kw):
        self.connected, self.port, self.job_active, self._check, self.autofocusing, self.busy = (
            True, "COM3", False, None, False, False)
        self.last_status = {"state": "Idle"}
        self.sent = []
        self.__dict__.update(kw)

    def send_line(self, line, tag=None):
        self.sent.append(line)


check("pronta: può partire", M.why_not(FakeCtl()) is None)
cases = {"scollegata": FakeCtl(connected=False), "K40": FakeCtl(port=K40_PORT), "lavoro": FakeCtl(job_active=True),
         "autofocus": FakeCtl(autofocusing=True), "righe in coda": FakeCtl(busy=True),
         "allarme": FakeCtl(last_status={"state": "Alarm"}), "in movimento": FakeCtl(last_status={"state": "Jog"}),
         "stato sconosciuto": FakeCtl(last_status={})}
bad = [k for k, c in cases.items() if not M.why_not(c)]
check("non parte: scollegata, K40, lavoro, autofocus, righe in coda, allarme, in movimento, stato sconosciuto", not bad, bad)
check("con la K40 il motivo lo dice", "K40" in M.why_not(cases["K40"]))

print("--- D. finestra")
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w._confirm_discard = lambda: True
w.resize(1400, 900)
w.show()
app.processEvents()
mp = w.move
box = mp.macros
check("nella scheda Movimento c'è la sezione Macro con «Macro…» e la frase per chi non ne ha", box.b_edit.text() == "Macro…"
      and not box.empty.isHidden() and box.grid_w.isHidden() and "autofocus" in box.empty.text())
w0 = mp.sizeHint().width()
dlg = macro_ui.MacroDialog([], box)
check("finestra vuota: campi spenti, «Nuova» acceso", not dlg.name.isEnabled() and not dlg.code.isEnabled()
      and dlg.b_new.isEnabled())
dlg.add()
check("«Nuova»: macro con un nome di partenza, campi accesi", dlg.items[0]["name"] == "Macro 1" and dlg.name.isEnabled()
      and dlg.list.count() == 1)
dlg.name.setText("")
dlg.name.textEdited.emit("")
dlg.code.setPlainText("M8")
dlg.accept()
check("nome vuoto: non si salva", dlg.result() != 1 and not dlg.result_macros and "nome" in dlg.note.text(),
      dlg.note.text())
dlg.name.setText("Aria")
dlg.name.textEdited.emit("Aria")
dlg.add()
dlg.name.setText("Laser su")
dlg.name.textEdited.emit("Laser su")
dlg.code.setPlainText("M3 S10\nG1 X1 F100")
check("la nota dice che accende il laser e che chiederà conferma", "conferma" in dlg.note.text(), dlg.note.text())
dlg.add()
dlg.name.setText("Rotta")
dlg.name.textEdited.emit("Rotta")
dlg.code.setPlainText("G0 X" + "9" * 200)
dlg.accept()
check("comandi sbagliati: non si salva e la nota lo dice", not dlg.result_macros and "Rotta" in dlg.note.text())
dlg.remove()
check("«Elimina» toglie la macro scelta", [m["name"] for m in dlg.items] == ["Aria", "Laser su"])
dlg.move(-1)
check("▲ sposta su", [m["name"] for m in dlg.items] == ["Laser su", "Aria"] and dlg.cur == 0)
dlg.accept()
check("salvate nell'ordine scelto", dlg.result_macros == [{"name": "Laser su", "code": "M3 S10\nG1 X1 F100"},
                                                        {"name": "Aria", "code": "M8"}], dlg.result_macros)
M.save(w.qs, dlg.result_macros + [{"name": "Impostazione", "code": "$110=5000"}])
box.reload()
app.processEvents()
check("dopo il salvataggio: un pulsante per macro, la frase sparisce", [b.full for b in box.buttons]
      == ["Laser su", "Aria", "Impostazione"] and box.empty.isHidden() and not box.grid_w.isHidden())
check("senza laser i pulsanti sono spenti", not any(b.isEnabled() for b in box.buttons))
check("anche chiamata a mano, senza laser la macro non parte e lo dice", not box.run(1) and "Collega" in box.last_msg)

print("--- E. con il simulatore")
ctl = w.ctl
ctl.connect_port(SIM_PORT)
ctl.sim.speedup = 50
until(lambda: ctl.board_settings and ctl.last_status.get("state") == "Idle")
spin(0.3)
check("collegato: pulsanti accesi", all(b.isEnabled() for b in box.buttons))
sent = []
ctl.line_sent.connect(lambda l: sent.append(l))
asked = []
answer = [False]
macro_ui.confirm = lambda parent, name, risk: (asked.append((name, sorted(risk))), answer[0])[1]
box.buttons[1].click()
until(lambda: "M8" in sent, 3)
check("«Aria»: M8 alla scheda, senza conferma", "M8" in sent and not asked, (sent, asked))
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 3)
sent.clear()
box.buttons[0].click()
spin(0.4)
check("«Laser su»: conferma chiesta; rifiutata, alla scheda non arriva niente",
      asked == [("Laser su", ["laser"])] and not sent, (asked, sent))
answer[0] = True
box.buttons[0].click()
until(lambda: {"M3 S10", "G1 X1 F100", "M5"} <= set(sent), 5)
# l'ordine della lista «sent» non conta: line_sent arriva da due fili; conta l'ordine in cui le righe sono messe in coda
check("accettata: le righe e poi M5 alla fine, tutte arrivate alla scheda",
      box.last_sent == ["M3 S10", "G1 X1 F100", "M5"] and {"M3 S10", "G1 X1 F100", "M5"} <= set(sent), (box.last_sent, sent))
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 5)
asked.clear()
answer[0] = False
box.buttons[2].click()
spin(0.3)
check("«$110=5000»: conferma per le impostazioni della scheda", asked == [("Impostazione", ["settings"])], asked)
ctl.last_status["state"] = "Alarm"
sent.clear()
ok = box.run(1)
check("macchina in allarme: non parte e lo dice", not ok and not sent and "allarme" in box.last_msg, box.last_msg)

print("--- F. larghezza")
M.save(w.qs, [{"name": "Macro lunghissima n. %d" % i, "code": "M8"} for i in range(M.MAX_MACROS)])
box.reload()
if UI == "classica":
    w.docks["move"].show()
    w.docks["move"].raise_()
app.processEvents()
w1 = mp.sizeHint().width()
check("finestra classica: i pulsanti si vedono (la prova dei nomi accorciati vale davvero)",
      UI != "classica" or all(b.isVisible() for b in box.buttons))
check("12 macro dai nomi lunghi: il pannello non si allarga (nomi accorciati, nome intero nel suggerimento)",
      w1 <= max(w0, 330) + 4 and all((not b.isVisible()) or (b.text().endswith("…") and b.full.startswith(b.text()[:-1])) for b in box.buttons)
      and "lunghissima n. 0" in box.buttons[0].toolTip(), (w0, w1))
import json  # noqa: E402

missing = []
for lang in [l for l in LANGUAGES if l != SOURCE]:
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8"))
    for key in ("Macro", "Macro…", "Collega prima il laser.", "Vuoi mandarla?", "Comandi (G-code o GRBL)",
                "Con la K40 le macro non si possono usare: la sua scheda non capisce il G-code."):
        if key not in cat:
            missing.append((lang, key))
check("traduzioni: i testi nuovi ci sono in tutte le lingue del programma", not missing, missing[:5])

print("--- G. difetti rimessi apposta (stesse prove di sopra, con la macro vera e una scheda finta)")
real_off, real_why = M.with_laser_off, M.why_not
M.save(w.qs, [{"name": "Laser su", "code": "M3 S10\nG1 X1 F100"}, {"name": "Aria", "code": "M8"}])
box.reload()
real_ctl = box.ctl
answer[0] = True
box.ctl = FakeCtl()
box.run(0)
check("senza difetti: con la scheda finta la macro del laser finisce con M5", box.ctl.sent[-1:] == ["M5"], box.ctl.sent)
M.with_laser_off = lambda lines: list(lines)
box.ctl = FakeCtl()
box.run(0)
check("difetto 1 (M5 non aggiunto): la prova se ne accorge", box.ctl.sent[-1:] != ["M5"], box.ctl.sent)
M.with_laser_off = real_off
M.why_not = lambda c: None if c.connected else "x"
box.ctl = FakeCtl(last_status={"state": "Alarm"})
box.run(1)
check("difetto 2 (parte con la macchina in allarme): la prova se ne accorge", box.ctl.sent == ["M8"], box.ctl.sent)
M.why_not = real_why
box.ctl = FakeCtl(last_status={"state": "Alarm"})
check("senza difetti: in allarme non parte", not box.run(1) and box.ctl.sent == [])
box.ctl = real_ctl

ctl.disconnect_port()
spin(0.2)
print(f"{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
