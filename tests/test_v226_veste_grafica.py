# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6: nuova veste grafica (logo «metallo e neon» di Ale, 24/11/2026).

- il logo è un'immagine, non più un disegno: icona .ico con una misura per ogni uso e gli angoli trasparenti, PNG per
  Linux e Mac, un .svg che contiene l'immagine per i punti che chiedono un .svg (pagina del telefono, sito);
- schermata di avvio: logo nuovo con la scritta, colori blu notte e arancio (via il viola), motto nella lingua del
  programma, schermata almeno 4 secondi, e a incisione finita i nomi scorrono piano a righe alternate.

Uso: python tests/test_v226_veste_grafica.py [classica|banco]
"""
import json
import os
import shutil
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

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from freelasercut import i18n, splash  # noqa: E402
from freelasercut.ui import style  # noqa: E402

ASSETS = os.path.join(ROOT, "freelasercut", "assets")
DOCS = os.path.join(ROOT, "docs")
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def arr(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


def alpha_png(path):
    return np.array(Image.open(path).convert("RGBA"))


def is_logo(a):
    """Il logo nuovo: riquadro con gli angoli trasparenti, fondo blu scuro, la C arancio in basso al centro."""
    h, w = a.shape[:2]
    corners = max(a[0, 0, 3], a[0, w - 1, 3], a[h - 1, 0, 3], a[h - 1, w - 1, 3])
    mid = a[h // 2, w // 2]
    low = a[int(h * 0.70):int(h * 0.90), int(w * 0.30):int(w * 0.70), :3].astype(int)
    orange = ((low[..., 0] > 170) & (low[..., 0] > low[..., 2] + 60)).mean()
    return corners <= 8 and mid[3] == 255 and orange > 0.04


# ====================================================================== A. i file del logo
print("--- A. i file")
ico = Image.open(os.path.join(ASSETS, "logo.ico"))
sizes = sorted(s[0] for s in ico.info["sizes"])
check("A l'icona .ico ha una misura per ogni uso, da 16 a 256", sizes == [16, 20, 24, 32, 40, 48, 64, 128, 256], sizes)
ok = True
for s in sizes:
    f = Image.open(os.path.join(ASSETS, "logo.ico"))
    f.size = (s, s)
    f.load()
    a = np.array(f.convert("RGBA"))
    ok = ok and a.shape[0] == s and a[0, 0, 3] <= 8 and a[s - 1, s - 1, 3] <= 8 and a[s // 2, s // 2, 3] == 255
check("A a ogni misura gli angoli sono trasparenti (niente riquadro blu attorno) e il centro è pieno", ok)
png = alpha_png(os.path.join(ASSETS, "logo.png"))
check("A logo.png (Linux, Mac, telefono): 256 pixel, è il logo nuovo", png.shape[:2] == (256, 256) and is_logo(png))
big = alpha_png(os.path.join(DOCS, "logo", "logo_1024.png"))
check("A docs/logo/logo_1024.png (Store, sito): 1024 pixel, è il logo nuovo", big.shape[:2] == (1024, 1024) and is_logo(big))
small = alpha_png(os.path.join(DOCS, "logo", "logo_256.png"))
check("A docs/logo/logo_256.png per le pagine del sito: leggero (meno di 200 KB)", is_logo(small)
      and os.path.getsize(os.path.join(DOCS, "logo", "logo_256.png")) < 200_000)
for name in ("logo.svg",):
    for folder in (ASSETS, os.path.join(DOCS, "logo")):
        path = os.path.join(folder, name)
        r = QSvgRenderer(path)
        img = QImage(96, 96, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        r.render(p, QRectF(0, 0, 96, 96))
        p.end()
        head = open(path, encoding="utf-8").read(400)
        check(f"A {os.path.relpath(path, ROOT)}: un .svg valido con dentro il logo nuovo (per chi chiede un .svg)",
              r.isValid() and is_logo(arr(img)) and "<svg" in head and os.path.getsize(path) < 120_000)
word = Image.open(os.path.join(ASSETS, "logo_scritta.png"))
wa = np.array(word.convert("RGBA"))
check("A logo_scritta.png: fondo trasparente, largo abbastanza per gli schermi fitti (486 punti × 2 o più)",
      word.width >= 972 and wa[2, word.width // 2, 3] == 0 and wa[..., 3].max() == 255 and 2.9 < word.width / word.height < 3.5,
      word.size)
for n in ("chiaro", "scuro"):
    d = Image.open(os.path.join(DOCS, "logo", f"logo_scritta_{n}.png"))
    check(f"A docs/logo/logo_scritta_{n}.png (README, sito): logo nuovo con la scritta, fondo trasparente",
          d.mode == "RGBA" and d.width >= 1000 and 2.9 < d.width / d.height < 3.5 and np.array(d)[2, d.width // 2, 3] == 0, d.size)
page = open(os.path.join(DOCS, "index.html"), encoding="utf-8").read()
refs = [x for x in ("logo/logo.svg", "logo/logo_256.png") if x in page]
check("A la pagina del sito usa i file che esistono, e per le immagini quello leggero",
      len(refs) == 2 and all(os.path.exists(os.path.join(DOCS, x)) for x in refs) and "logo/logo_1024.png" not in page)
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("A il README mostra il logo con la scritta", "docs/logo/logo_scritta_chiaro.png" in readme)
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8", errors="replace").read()
check("A gli installatori prendono ancora questi file (stessi nomi: .ico per Windows, .png per Linux e Mac, 1024 per lo Store)",
      "assets\\logo.ico" in nsi
      and '"assets", "logo.png"' in open(os.path.join(ROOT, "build", "prepara_appimage.py"), encoding="utf-8").read()
      and '"assets", "logo.png"' in open(os.path.join(ROOT, "build", "prepara_mac.py"), encoding="utf-8").read()
      and '"logo_1024.png"' in open(os.path.join(ROOT, "build", "prepara_msix.py"), encoding="utf-8").read())

# ====================================================================== B. l'icona del programma
print("--- B. icona del programma")
icon = style.app_icon()
check("B l'icona del programma ha tutte le misure", sorted(s.width() for s in icon.availableSizes()) == sizes)
same = True
for s in (16, 24, 32):
    f = Image.open(os.path.join(ASSETS, "logo.ico"))
    f.size = (s, s)
    f.load()
    want, got = np.array(f.convert("RGBA")).astype(int), arr(icon.pixmap(s, s).toImage()).astype(int)
    full = want[..., 3] == 255
    same = same and got.shape == want.shape and np.abs(got[full] - want[full]).max() <= 2
check("B a 16, 24 e 32 pixel Qt prende l'immagine di quella misura (quella ritoccata), non una rimpicciolita", same)
real_assets = style.ASSETS
try:
    style.ASSETS = tempfile.mkdtemp()
    shutil.copy(os.path.join(ASSETS, "logo.png"), style.ASSETS)
    alt = style.app_icon()
    check("B se il .ico non c'è resta l'immagine PNG (mai un'icona vuota)", not alt.isNull() and is_logo(arr(alt.pixmap(64, 64).toImage())))
finally:
    style.ASSETS = real_assets
src_mw = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
src_bc = open(os.path.join(ROOT, "freelasercut", "ui", "banco.py"), encoding="utf-8").read()
check("B finestra, programma e barra del Banco usano l'icona nuova (nessuno legge più il vecchio disegno)",
      src_mw.count("style.app_icon()") == 2 and "style.app_icon().pixmap(26, 26)" in src_bc
      and '"logo.svg"' not in src_mw and '"logo.svg"' not in src_bc)
from freelasercut.ui import main_window as mw  # noqa: E402

win = mw.MainWindow()
wi = win.windowIcon()
check("B la finestra vera ha l'icona nuova", not wi.isNull() and is_logo(arr(wi.pixmap(48, 48).toImage())))
if os.environ["FLC_UI"] == "banco":
    from PySide6.QtWidgets import QLabel

    logos = [w for w in win.findChildren(QLabel) if w.pixmap() is not None and not w.pixmap().isNull()
             and w.pixmap().width() in (26, 52) and w.parent() is not None and w.parent().objectName() == "bcTop"]
    check("B Banco: nella barra in alto c'è il logo nuovo", len(logos) == 1 and is_logo(arr(logos[0].pixmap().toImage())),
          len(logos))

# ====================================================================== C. schermata di avvio: aspetto
print("--- C. schermata di avvio")
W, H = splash.W, splash.H
i18n.set_language("it")
fin = arr(splash.render(splash.ENGRAVE_S, dpr=1.0))
bg = arr(splash._pixmap(1.0).toImage())
check("C fondo blu notte senza viola: in ogni punto il blu supera il rosso",
      (bg[20:280:13, 20:540:17, 2].astype(int) > bg[20:280:13, 20:540:17, 0].astype(int) + 15).all())
rect = splash.logo_rect((1458, 457))
check("C il logo con la scritta è largo 486, centrato, sopra la fascia in basso",
      abs(rect.width() - 486) < 0.01 and abs(rect.center().x() - W / 2) < 0.01 and rect.bottom() < splash.BAND_TOP - 30)
icon_zone = fin[int(rect.top()):int(rect.bottom()), int(rect.left()):int(rect.left() + 0.30 * rect.width())]
check("C nella schermata c'è il logo nuovo (la C arancio accesa sotto la testa)",
      ((icon_zone[..., 0] > 200) & (icon_zone[..., 2] < 90)).sum() > 300)
beam = fin[250:252, :, :3].astype(int)
check("C il raggio in basso va dal blu all'arancio",
      beam[0, 200, 2] > beam[0, 200, 0] + 80 and beam[0, 470, 0] > beam[0, 470, 2] + 80,
      (beam[0, 200].tolist(), beam[0, 470].tolist()))
x0 = rect.left() + splash.LOGO_WORD[0] * rect.width()
room = (splash.LOGO_WORD[1] - splash.LOGO_WORD[0]) * rect.width()
my, mh = int(rect.top() + splash.MOTTO_Y * rect.height()), 18
mottos, fits, views = {}, {}, {}
for lang in ("it", "en", "es", "fr", "pt"):
    i18n.set_language(lang)
    mottos[lang] = splash.motto_text()
    f, w = splash.motto_font(mottos[lang], room)
    fits[lang] = (round(w), f.pixelSize())
    views[lang] = arr(splash._foreground(1.0).toImage())[my:my + mh, int(x0):int(x0 + room)]
i18n.set_language("it")
check("C il motto è nella lingua del programma, tutto maiuscolo, in cinque lingue diverse",
      len(set(mottos.values())) == 5 and all(m == m.upper() and len(m) > 20 for m in mottos.values())
      and mottos["it"] == "SOFTWARE LIBERO PER INCISIONE LASER" and "LASER" in mottos["en"], mottos)
check("C in ogni lingua il motto sta sotto la scritta senza uscire (le traduzioni lunghe si stringono, mai sotto 8 pixel)",
      all(w <= room and px >= 8 for w, px in fits.values()), (fits, round(room)))
check("C il motto si vede (chiaro sul fondo) ed è disegnato diverso lingua per lingua",
      all((v[..., 3] > 120).sum() > 150 for v in views.values()) and not np.array_equal(views["it"], views["en"]))
check("C un motto lunghissimo si rimpicciolisce fino al minimo e non di più",
      splash.motto_font("X" * 200, room)[0].pixelSize() == 8 and splash.motto_font("CIAO", room)[0].pixelSize() == splash.MOTTO_PX)
real = splash.ASSETS
try:
    splash.ASSETS = tempfile.mkdtemp()
    shutil.copy(os.path.join(ASSETS, "logo_scritta.svg"), splash.ASSETS)
    old = arr(splash._foreground(1.0).toImage())
    check("C se l'immagine nuova manca la schermata disegna il logo di prima (mai vuota)",
          (old[40:150, 60:500, 3] > 0).sum() > 5000)
finally:
    splash.ASSETS = real
band = slice(int(splash.BAND_TOP), H)
check("C la fascia in basso (messaggio, autore, versione) resta libera dai nomi",
      np.array_equal(arr(splash.render(0.0))[band], arr(splash.render(30.0))[band]))

# ====================================================================== D. i nomi che scorrono
print("--- D. scorrimento dei nomi")
E = splash.ENGRAVE_S
check("D la schermata resta almeno 4 secondi (Ale, 24/11)", splash.MIN_SHOW_S == 4.0)
check("D finché si incide non scorre niente", splash.scroll_distance(0) == 0 and splash.scroll_distance(E) == 0
      and splash.scroll_distance(E - 1) == 0)
d1, d2 = splash.scroll_distance(E + splash.SCROLL_EASE_S - 1e-6), splash.scroll_distance(E + splash.SCROLL_EASE_S + 1e-6)
check("D parte dolcemente: nessuno scatto alla fine dell'avvio e, da lì, 9 pixel al secondo",
      abs(d1 - d2) < 1e-4 and abs((splash.scroll_distance(E + 10) - splash.scroll_distance(E + 9)) - splash.SCROLL_PX_S) < 1e-9
      and splash.SCROLL_PX_S == 9.0 and splash.scroll_distance(E + 0.1) < 0.1)
mono = [splash.scroll_distance(E + k * 0.05) for k in range(200)]
check("D non torna mai indietro", all(b >= a for a, b in zip(mono, mono[1:])))
check("D righe alternate: la prima verso destra, la seconda verso sinistra, e così via",
      splash.row_shift(0, 5.0) == 5.0 and splash.row_shift(1, 5.0) == splash.SCROLL_PERIOD - 5.0
      and splash.row_shift(2, 5.0) == 5.0 and splash.row_shift(3, 5.0) == splash.SCROLL_PERIOD - 5.0)
check("D lo spostamento resta sempre dentro un giro (uscita da un bordo, la riga rientra dall'altro)",
      all(0 <= splash.row_shift(i, d) < splash.SCROLL_PERIOD for i in range(12) for d in (0.0, 1.0, 541.9, 542.0, 9999.5)))
t_giro = E + splash.SCROLL_EASE_S / 2 + splash.SCROLL_PERIOD / splash.SCROLL_PX_S  # qui le righe hanno fatto un giro esatto
a_fin, a_giro = arr(splash.render(E)), arr(splash.render(t_giro))
diff = np.abs(a_fin.astype(int) - a_giro.astype(int))
check("D dopo un giro intero la schermata è di nuovo quella appena incisa (nessun nome perso per strada)",
      abs(splash.scroll_distance(t_giro) - splash.SCROLL_PERIOD) < 1e-6 and diff.max() <= 3, int(diff.max()))
# a metà giro: senza il rientro dall'altro bordo mancherebbe mezza riga
T_MEZZO = E + splash.SCROLL_EASE_S / 2 + 0.5 * splash.SCROLL_PERIOD / splash.SCROLL_PX_S
a_mov = arr(splash.render(T_MEZZO))
rows = splash.name_rows()


def ink(a, r, x0, x1):
    """Quanto «inchiostro» dei nomi c'è nella riga r fra x0 e x1 (differenza dal fondo senza nomi)."""
    base = arr(splash.render(0.0))
    y0, y1 = int(r.top), int(r.bottom)
    return int(np.abs(a[y0:y1, x0:x1, :3].astype(int) - base[y0:y1, x0:x1, :3].astype(int)).sum())


check("D mentre scorrono i nomi sono cambiati di posto ma ci sono tutti (stesso inchiostro, entro il 12%)",
      not np.array_equal(a_fin, a_mov)
      and all(abs(ink(a_mov, r, 0, W) - ink(a_fin, r, 0, W)) <= 0.12 * ink(a_fin, r, 0, W) + 400
              for r in rows if r.bottom < rect.top() or r.top > rect.bottom()),
      [(ink(a_fin, r, 0, W), ink(a_mov, r, 0, W)) for r in rows])
side = int(splash.SIDE)
# prima dello scorrimento i margini sono vuoti; poi i nomi li attraversano (entrano ed escono dai bordi)
check("D i nomi arrivano fino ai bordi della schermata (prima c'era il margine vuoto)",
      sum(ink(a_fin, r, 2, side - 2) for r in rows) == 0 and sum(ink(a_mov, r, 2, side - 2) for r in rows) > 0)
low = splash.Splash(splash._pixmap(1.0), min_show=0.0, clock=lambda: T_MEZZO)
low._t0 = 0.0
low._final = True
img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
img.fill(Qt.transparent)
p = QPainter(img)
p.drawPixmap(0, 0, splash._pixmap(1.0))
low.drawContents(p)
p.end()
check("D sui PC lenti (stato finale) i nomi restano fermi, tutti incisi", np.array_equal(arr(img), a_fin))
low.deleteLater()


class Clock:
    def __init__(self, t=0.0, step=0.0):
        self.t, self.step = t, step

    def __call__(self):
        self.t += self.step
        return self.t


ck = Clock(E + 1.0)
sp = splash.Splash(splash._pixmap(1.0), min_show=0.0, clock=ck)
sp._t0 = 0.0
sp.show()
app.processEvents()
sp._last = -1.0
first = sp.pulse()
n0 = sp.frames
ck.t += splash.SCROLL_FRAME_S / 2
soon = sp.pulse()
ck.t += splash.SCROLL_FRAME_S
later = sp.pulse()
check("D a incisione finita la schermata continua a ridisegnarsi, ma al massimo 25 volte al secondo",
      first and not soon and later and sp.frames == n0 + 1 and splash.SCROLL_FRAME_S == 1 / 25)
sp._final = True
ck.t += 1.0
check("D …e sui PC lenti non si ridisegna più (non rallenta il caricamento)", sp.pulse() is False and sp.frames == n0 + 1)
sp.hide()
sp.deleteLater()
ck2 = Clock(0.0, 0.02)
sp2 = splash.Splash(splash._pixmap(1.0), min_show=splash.MIN_SHOW_S, clock=ck2)
sp2._t0 = 0.0
sp2.show()
app.processEvents()
sp2.wait_min()
check("D sui PC veloci l'attesa arriva a 4 secondi e intanto la schermata si ridisegna (incisione e poi scorrimento)",
      4.0 <= ck2.t < 4.6 and sp2.frames > 20, (round(ck2.t, 2), sp2.frames))
sp2.hide()
sp2.deleteLater()
hl = splash.Splash(splash._pixmap(1.0))
check("D nelle prove (senza schermo) l'attesa resta zero", hl.min_show == 0.0)
hl.deleteLater()

# ====================================================================== E. traduzioni
print("--- E. traduzioni")
KEY = "SOFTWARE LIBERO PER INCISIONE LASER"
tr_ok = True
for lang in ("en", "es", "fr", "pt"):
    d = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    tr_ok = tr_ok and d.get(KEY) and d[KEY] != KEY and d[KEY] == d[KEY].upper()
check("E il motto è nei quattro cataloghi", tr_ok)
win.close()

# ====================================================================== F. incisione fluida durante il caricamento
print("--- F. il caricamento fa battere la schermata di avvio (Ale, 24/11: un tentennamento a tre quarti dell'incisione)")
import time  # noqa: E402

from freelasercut import heartbeat  # noqa: E402

check("F senza schermata di avvio il battito non fa niente", heartbeat.hook is None and heartbeat.beat() is None)
spf = splash.Splash(splash._pixmap(1.0), min_show=0.0)
spf.install_pulse()
check("F schermata aperta: il battito è il suo ridisegno", heartbeat.hook == spf.pulse)
spf.remove_pulse()
check("F schermata chiusa: il battito si stacca", heartbeat.hook is None)
beats = []
heartbeat.hook = lambda: beats.append(time.perf_counter())
t0 = time.perf_counter()
win_f = mw.build_main_window()
t1 = time.perf_counter()
heartbeat.hook = None
gaps = [b - a for a, b in zip([t0] + beats, beats + [t1])]
check("F costruendo la finestra principale il battito arriva centinaia di volte (prima: mai, la schermata restava "
      "ferma)", len(beats) >= 300, len(beats))
check("F …e mai un vuoto lungo fra un battito e l'altro (qui meno di 0,2 s; la soglia è larga per i PC lenti)", max(gaps) < 2.0,
      round(max(gaps), 3))
heartbeat.hook = lambda: (_ for _ in ()).throw(RuntimeError("battito rotto"))
check("F un battito che dà errore non ferma il caricamento", heartbeat.beat() is None)
heartbeat.hook = None
win_f.close()

print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
