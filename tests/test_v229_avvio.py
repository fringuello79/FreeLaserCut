# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.9: schermata d'avvio fluida (Ale, 25/11/2026: «l'animazione iniziale del laser che incide i nomi è
ancora scattosa»).

Fino alla 0.22.8 la schermata si ridisegnava solo fra un modulo e l'altro: le librerie che si caricano in un pezzo solo
(OpenCV, la libreria di numba) la tenevano ferma per centinaia di millisecondi. Ora splash.Splash.preload le carica in
un thread a parte e intanto ridisegna a 60 fotogrammi al secondo.

Casi: con un caricamento finto di un secondo che tiene fermo il thread (come una DLL) la schermata si ridisegna di
continuo, senza buchi lunghi; con un caricamento fatto di tanti pezzi in Python (come numpy) anche; un errore nel
caricamento non esce e non lascia il thread vivo; a schermata nascosta o su un PC lento il caricamento si fa come
prima, nel thread principale; __main__ chiama preload prima della finestra, con numpy, OpenCV e numba; le librerie si
caricano davvero da un thread a parte. Difetti rimessi apposta: il caricamento nel thread principale (come nella
0.22.8) fa un buco lungo quanto il caricamento; preload senza ridisegni non ridisegna.
"""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from freelasercut import splash as SP  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name + (f"  {info}" if info and not cond else ""))


class Watch(SP.Splash):
    """La schermata vera, che si segna quando si ridisegna."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.stamps = []

    def drawContents(self, p):
        self.stamps.append(time.perf_counter())
        super().drawContents(p)

    def worst_gap(self, a, b):
        st = [t for t in self.stamps if a <= t <= b]
        if len(st) < 2:
            return b - a
        st = [a] + st + [b]
        return max(y - x for x, y in zip(st, st[1:]))


def fresh():
    s = Watch(SP._pixmap(), min_show=0.0)
    s.show()
    app.processEvents()
    s.stamps.clear()
    return s


def dll_like():
    time.sleep(1.0)  # come il caricamento di una DLL: il thread è fermo ma Python è libero


def python_like():
    end = time.perf_counter() + 0.8
    x = 0
    while time.perf_counter() < end:  # come gli import fatti in Python: lavoro continuo, Python occupato
        for i in range(2000):
            x += i * i
    return x


print("Schermata d'avvio fluida mentre si caricano le librerie")
s = fresh()
a = time.perf_counter()
spent = s.preload(dll_like)
b = time.perf_counter()
gap = s.worst_gap(a, b)
check("caricamento lungo un secondo (come una DLL): la schermata si ridisegna di continuo, nessun buco oltre 60 ms",
      len(s.stamps) >= 30 and gap < 0.06 and 0.95 < spent < 1.6, (len(s.stamps), round(gap, 3), round(spent, 2)))
s.close()

s = fresh()
a = time.perf_counter()
s.preload(python_like)
b = time.perf_counter()
gap = s.worst_gap(a, b)
check("caricamento fatto in Python (come numpy): anche qui ridisegni continui, nessun buco oltre 80 ms",
      len(s.stamps) >= 20 and gap < 0.08, (len(s.stamps), round(gap, 3)))
s.close()

s = fresh()
before = {t.name for t in threading.enumerate()}


def boom():
    raise ImportError("libreria rotta (prova)")


try:
    s.preload(boom)
    ok = True
except Exception:  # noqa: BLE001
    ok = False
time.sleep(0.05)
check("un errore nel caricamento non esce da preload (lo mostra poi l'import vero) e il thread non resta vivo",
      ok and "flc-librerie" not in {t.name for t in threading.enumerate()})
s.close()

calls = []
s = fresh()
s.hide()
s.preload(lambda: calls.append(threading.get_ident()))
check("a schermata nascosta il caricamento si fa come prima, nel thread principale",
      calls == [threading.get_ident()], calls)
s.close()

calls.clear()
s = fresh()
s._final = True
s.stamps.clear()
s.preload(lambda: calls.append(threading.get_ident()))
check("PC lento (stato finale): niente thread né ridisegni, come prima",
      calls == [threading.get_ident()] and not s.stamps, (calls, len(s.stamps)))
s.close()

calls.clear()
s = fresh()
s.preload(lambda: calls.append(threading.get_ident()))
check("con la schermata visibile il caricamento va in un thread a parte", calls and calls[0] != threading.get_ident(), calls)
s.close()

src = open(os.path.join(ROOT, "freelasercut", "__main__.py"), encoding="utf-8").read()
i_pre, i_win = src.find("splash.preload(_heavy_libs)"), src.find("from .ui.main_window import main")
check("__main__: preload delle librerie dopo la schermata e prima della finestra principale",
      0 < src.find("show_splash()") < i_pre < i_win, (i_pre, i_win))
from freelasercut import __main__ as M  # noqa: E402

body = M._heavy_libs.__code__.co_names
check("…con numpy, OpenCV e numba (nessuna crea oggetti di Qt)",
      {"numpy", "cv2", "numba"} <= set(body) and not any("PySide" in n or "freelasercut" in n for n in body), body)
err = []


def real():
    try:
        M._heavy_libs()
    except Exception as e:  # noqa: BLE001
        err.append(repr(e))


th = threading.Thread(target=real)
th.start()
th.join(120)
check("le librerie vere si caricano da un thread a parte senza errori", not th.is_alive() and not err
      and "numpy" in sys.modules and "cv2" in sys.modules, err)
check("dopo il caricamento il cambio di thread di Python torna quello di prima",
      abs(sys.getswitchinterval() - 0.005) < 1e-9, sys.getswitchinterval())
check("costanti: 60 fotogrammi al secondo durante il caricamento, il passo di sempre fuori",
      abs(SP.PRELOAD_FRAME_S - 1 / 60) < 1e-9 and abs(SP.FRAME_S - 1 / 40) < 1e-9)

print("Difetti rimessi apposta")
s = fresh()
a = time.perf_counter()
dll_like()  # come nella 0.22.8: caricamento nel thread principale
s.pulse()
b = time.perf_counter()
check("difetto 1 (caricamento nel thread principale, come nella 0.22.8): la prova se ne accorge (buco lungo)",
      s.worst_gap(a, b) > 0.5, round(s.worst_gap(a, b), 3))
s.close()

orig = SP.Splash.pulse
SP.Splash.pulse = lambda self: False
s = fresh()
a = time.perf_counter()
s.preload(lambda: time.sleep(0.4))
b = time.perf_counter()
SP.Splash.pulse = orig
check("difetto 2 (preload senza ridisegni): la prova se ne accorge", s.worst_gap(a, b) > 0.3, round(s.worst_gap(a, b), 3))
s.close()

ok = sum(results)
print(f"{ok}/{len(results)} prove superate")
sys.exit(0 if ok == len(results) else 1)
