# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.2: dal messaggio di rinosp su GitHub (Mac: passato all'interfaccia Banco, il programma si chiudeva a
ogni avvio e non si poteva più entrare, nemmeno per mandare un rapporto).

Rete di sicurezza: ogni avvio vero nel Banco lascia un segno (banco-avvio.txt) che si toglie quando la finestra è
aperta da qualche secondo o alla chiusura normale. Se all'avvio dopo il segno c'è ancora, per quella volta si parte in
Classica con una fascia che lo dice; alla seconda volta di seguito la scelta salvata diventa Classica.
In più: la prova d'avvio di GitHub apre anche il Banco con la finestra vera, e sul Mac «Officina sul secondo monitor»
parte spenta."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
LABEL = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ.pop("FLC_UI", None)  # la rete vale solo quando l'interfaccia viene dalla scelta salvata
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)

from freelasercut.ui import banco  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{LABEL}] " + name, info if not cond else "", flush=True)


def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


qs = banco.settings()
MARK = banco._guard_path()


def mark():
    return open(MARK, encoding="utf-8").read().strip() if os.path.exists(MARK) else None


def start():
    """Un avvio vero, visto dalla rete: -> (motivo, interfaccia usata)."""
    reason = banco.guard_start()
    return reason, banco.ui_mode()


def crash():
    """Il programma muore prima che il Banco sia confermato: resta il segno, la memoria del processo si perde."""
    banco._guard.update(forced=None, open=False, reason=None)


# ================================================================ 1. Classica: la rete non fa niente
banco.save_mode("classica")
check("scelta Classica: nessun segno, nessun motivo, si parte in Classica", start() == (None, "classica") and mark() is None)
banco._guard_write(1, False)
start()
check("scelta Classica con un segno vecchio in giro: il segno si toglie", mark() is None)

# ================================================================ 2. Banco che funziona
banco.save_mode("banco")
check("scelta Banco, primo avvio: si prova il Banco e resta il segno «1»", start() == (None, "banco") and mark() == "1",
      mark())
banco.guard_ok()
check("finestra aperta da qualche secondo (o chiusura normale): il segno si toglie", mark() is None)
banco.guard_ok()
check("conferma data due volte: nessun errore", mark() is None)
for _ in range(3):
    start()
    banco.guard_ok()
check("tanti avvii buoni di seguito: sempre Banco, mai un segno rimasto", start() == (None, "banco") and mark() == "1")
banco.guard_ok()

# ================================================================ 3. Banco che non si apre
start()
crash()
check("il Banco muore all'avvio: il segno «1» resta", mark() == "1")
check("avvio dopo: Classica per questa volta, con il motivo «una»; la scelta salvata resta Banco",
      start() == ("una", "classica") and qs.value("ui_mode") == "banco" and mark() == "1 classica", (mark(), qs.value("ui_mode")))
check("…e nel processo l'interfaccia è Classica dappertutto (menu, finestre)", banco.ui_mode(qs) == "classica"
      and not banco.needs_choice(qs))
crash()
check("avvio dopo, senza fare niente: si riprova il Banco (segno «2»)", start() == (None, "banco") and mark() == "2", mark())
crash()
check("muore di nuovo: all'avvio dopo la scelta salvata diventa Classica (motivo «due») e il segno si toglie",
      start() == ("due", "classica") and qs.value("ui_mode") == "classica" and mark() is None, (mark(), qs.value("ui_mode")))
crash()
check("da lì in poi: Classica normale, senza motivo", start() == (None, "classica") and mark() is None)

# un avvio buono in mezzo azzera il conto
banco.save_mode("banco")
start()
crash()
start()  # Classica per una volta
crash()
start()  # riprova
banco.guard_ok()
check("fallito, poi riuscito: il conto riparte da zero", mark() is None and start() == (None, "banco") and mark() == "1")
banco.guard_ok()

# ================================================================ 4. interfaccia imposta da fuori e segno che non si scrive
banco.save_mode("banco")
banco._guard_write(1, False)
os.environ["FLC_UI"] = "banco"
check("FLC_UI=banco (assistenza, prove): la rete non interviene anche con un segno rimasto",
      start() == (None, "banco") and mark() == "1")
os.environ["FLC_UI"] = "classica"
check("FLC_UI=classica (il comando dato a chi non riesce a entrare): Classica senza toccare il segno",
      start() == (None, "classica") and mark() == "1" and qs.value("ui_mode") == "banco")
os.environ.pop("FLC_UI")
banco.guard_clear()
real_path = banco._guard_path
banco._guard_path = lambda: os.path.join(tempfile.gettempdir(), "cartella-che-non-esiste-flc", "x", "segno.txt")
check("segno che non si può scrivere: si parte nel Banco lo stesso, senza errori", start() == (None, "banco"))
banco.guard_ok()
banco._guard_path = real_path
for junk in ("", "abc", "-3", "7 classica extra"):
    with open(MARK, "w", encoding="utf-8") as fh:
        fh.write(junk)
    f, fb = banco.guard_read()
    results.append(isinstance(f, int) and f >= 0)
check("segno rovinato: letto senza errori", all(results[-4:]))
banco.guard_clear()

# ================================================================ 5. la fascia e i suoi pulsanti
banco.save_mode("banco")
start()
crash()
reason = banco.guard_start()
w = MainWindow()
check("dopo un avvio fallito la finestra nasce in Classica (niente Banco)", reason == "una" and w.ui_mode == "classica"
      and w.banco is None)
w.banco_fallback_banner(reason)
labels = [b.text() for b in w.banner.findChildren(QPushButton)]
text = " ".join(lab.text() for lab in w.banner.findChildren(type(w.banner_label))) if hasattr(w, "banner_label") else ""
check("fascia «per questa volta usa la Classica» con Manda un rapporto, Riprova il Banco, Resta in Classica",
      w.banner.isVisibleTo(w) and w.banco_fallback == "una"
      and all(any(t in lab for lab in labels) for t in ("Manda un rapporto", "Riprova il Banco", "Resta in Classica")), labels)
w.keep_classic()
check("«Resta in Classica»: scelta salvata Classica, segno tolto, fascia chiusa", qs.value("ui_mode") == "classica"
      and mark() is None and not w.banner.isVisibleTo(w))
w.banco_fallback_banner("due")
labels = [b.text() for b in w.banner.findChildren(QPushButton) if b.isVisibleTo(w.banner)]
check("fascia dopo due volte: senza «Resta in Classica» (lo è già)", w.banco_fallback == "due"
      and any("Riprova il Banco" in lab for lab in labels) and not any("Resta in Classica" in lab for lab in labels), labels)
closed = []
w.close = lambda: closed.append(1) or True
w.retry_banco()
check("«Riprova il Banco»: scelta salvata Banco, il prossimo avvio prova il Banco, il programma si riavvia",
      qs.value("ui_mode") == "banco" and mark() == "1 classica" and closed == [1] and w._restart is True)
crash()
check("…e l'avvio dopo prova davvero il Banco", start() == (None, "banco") and mark() == "2")
crash()
check("…se non va, torna la Classica per sempre", start() == ("due", "classica") and qs.value("ui_mode") == "classica")
crash()
del w.close
w.editor.dirty = False

# ================================================================ 6. Banco vero: la chiusura normale toglie il segno
banco.save_mode("banco")
check("avvio nel Banco", start() == (None, "banco") and mark() == "1")
wb = MainWindow()
check("la finestra nasce nel Banco", wb.ui_mode == "banco" and wb.banco is not None)
check("il pulsante Impostazioni conserva il menu dopo la costruzione del Banco",
      wb.banco.gear.menu() is wb.m_settings and bool(wb.m_settings.actions()))
check("il sottomenu Grandezza dei caratteri resta accessibile", bool(wb.m_font.actions()))
wb.editor.dirty = False
wb.banco.shutdown()
check("chiusura normale del Banco: il segno si toglie", mark() is None)

# ================================================================ 7. secondo monitor: sul Mac parte spento
qs.remove("officina_second_screen")
real = sys.platform
try:
    sys.platform = "darwin"
    mac_default = banco.second_screen_on(qs)
    qs.setValue("officina_second_screen", True)
    mac_on = banco.second_screen_on(qs)
    qs.remove("officina_second_screen")
    sys.platform = "win32"
    win_default = banco.second_screen_on(qs)
    sys.platform = "linux"
    lin_default = banco.second_screen_on(qs)
    qs.setValue("officina_second_screen", False)
    lin_off = banco.second_screen_on(qs)
finally:
    sys.platform = real
    qs.remove("officina_second_screen")
check("«Officina sul secondo monitor»: sul Mac parte spenta, su Windows e Linux accesa come prima",
      mac_default is False and win_default is True and lin_default is True, (mac_default, win_default, lin_default))
check("…e la scelta di chi usa il programma vale sempre", mac_on is True and lin_off is False)
src_b, src_m = read("freelasercut", "ui", "banco.py"), read("freelasercut", "ui", "main_window.py")
check("il Banco e il menu Impostazioni leggono la stessa regola", "if not second_screen_on(win.qs):" in src_b
      and "sec.setChecked(second_screen_on(self.qs))" in src_m and src_b.count('"officina_second_screen"') == 1)

# ================================================================ 8. l'avvio vero e la prova di GitHub
i_start, i_build = src_m.index("    banco_reason = _banco.guard_start()"), src_m.index("win = build_main_window()")
i_show, i_ok = src_m.index("    win.show()\n    startup_guard.done()"), src_m.index("QTimer.singleShot(_banco.GUARD_OK_MS, _banco.guard_ok)")
check("main(): la rete si accende prima di costruire la finestra e la conferma parte dopo averla mostrata",
      i_start < i_build < i_show < i_ok and "win.banco_fallback_banner(banco_reason)" in src_m
      and 2000 <= banco.GUARD_OK_MS <= 30000)
check("costruire una finestra nelle prove non accende la rete", "guard_start" not in src_m.split("def main(")[0]
      .split("class MainWindow")[1])
st = read("freelasercut", "selftest.py")
check("prova d'avvio: nel Banco apre l'Officina, la fa diventare finestra e la rimette cassetto",
      "off.to_window(" in st and "off.to_drawer()" in st and "interfaccia Banco: ok" in st and "faulthandler.enable()" in st)
yml = read(".github", "workflows", "installatore.yml")
NAMES_CI = ("Prova di avvio nel Banco (finestra vera, Cocoa)", "Prova di avvio nel Banco (X11)")
if "FLC_UI: banco" in yml:
    check("GitHub: prova d'avvio anche nel Banco su Mac (Cocoa) e Linux (X11), senza fermare la pubblicazione",
          yml.count("FLC_UI: banco") == 2 and all(n in yml for n in NAMES_CI)
          and yml.count('grep -q "interfaccia Banco: ok" selftest-banco.txt') == 2
          and all("continue-on-error: true" in yml.split(n)[1].split("- name:")[0] for n in NAMES_CI))
else:  # il file del flusso lo mette a mano chi pubblica: finché non c'è, la prova nel Banco su GitHub non gira
    print("  --  nel flusso di GitHub la prova d'avvio nel Banco non c'è ancora (installatore.yml da aggiornare)")

banco.save_mode("classica")
banco.guard_clear()
ok = sum(results)
print(f"\n{ok}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
