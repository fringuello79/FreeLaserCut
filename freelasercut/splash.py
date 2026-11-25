# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Schermata d'avvio: compare subito, mentre si caricano le librerie pesanti (numpy, OpenCV, numba).

0.20.5: dietro al logo i nomi di chi ha aiutato FreeLaserCut (freelasercut/thanks.py), «incisi» riga per riga da un
puntino di luce, come fa il laser. Deciso da Ale il 16/11/2026: a ogni avvio, preceduti da «Grazie a», e sui PC
veloci la schermata resta almeno 3 secondi. I nomi sono sempre nell'ordine dell'elenco (finito, si ricomincia) e le
righe hanno grandezze diverse, alternate (Ale, 16/11 alle 23:10): lo stesso nome, quando ricompare, ha un'altra
grandezza. In ogni riga solo nomi interi, distribuiti da un bordo all'altro.

Come funziona, perché non si blocchi e non blocchi niente:
- il disegno dipende solo dal TEMPO trascorso dall'apertura, non da un timer: mentre si caricano le librerie il
  programma è occupato e un timer non girerebbe. La schermata si ridisegna a ogni messaggio (say) e ogni volta che
  Python carica un modulo (un «cercatore» in sys.meta_path che non trova mai niente e fa solo ridisegnare: sono
  centinaia di occasioni durante l'avvio). Se fra due occasioni passa molto tempo, l'incisione semplicemente è più
  avanti; se il PC è lento, quando arriva il momento si vede già lo stato finale;
- l'incisione dura circa 3 secondi (ogni riga 1,6 s, righe sfalsate di 0,17 s); se il caricamento dura di più la
  schermata resta con i nomi già incisi;
- 0.22.6: finita l'incisione i nomi scorrono piano, una riga verso destra e quella sotto verso sinistra (Ale, 24/11).
  Non si ridisegna nessun testo: si copiano spostate le stesse immagini delle righe, e quello che esce da un bordo
  rientra dall'altro. Anche lo scorrimento dipende solo dal tempo. Sui PC lenti (stato finale) i nomi restano fermi;
- l'attesa minima (wait_min) si fa solo a finestra principale già costruita: non tocca i messaggi d'errore dell'avvio
  né la scelta dell'interfaccia al primo avvio. Senza schermo (prove automatiche, piattaforme offscreen e minimal)
  non c'è attesa.
"""
import os
import sys
import threading
import time

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSplashScreen

from . import __author__, display_version, heartbeat, thanks
from freelasercut.i18n import tr  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
W, H = 560, 300

# ---- trama dei nomi
SIDE = 22.0  # margine ai lati
BAND_TOP = 249.0  # da qui in giù c'è la fascia in basso: la trama (alone compreso) si ferma prima
TOP0 = 9.0  # la prima riga
LEADING = 1.12  # altezza di una riga = grandezza del carattere × questo
ROWS = 12  # 0.20.7 (Ale, 19/11): nomi più piccoli e più fitti, come una trama (prima 9 righe da 15-30 pixel)
# Le grandezze delle righe (pixel del carattere): irregolari e alternate, una grande dopo una piccola. Quanti nomi
# mettere in ogni riga e con che grandezza lo decide thanks.plan_rows a ogni avvio, perché dipende dall'elenco e dal
# carattere del sistema: ogni riga ha almeno due nomi (va sempre da un bordo all'altro), i nomi restano nell'ordine
# dell'elenco e uno stesso nome, quando ricompare, ha una grandezza diversa. La prima riga non è delle più grandi:
# deve starci «Grazie a».
SIZE_MIN, SIZE_MAX = 12, 22
FIRST_MAX = 18
# 0.20.7: i nomi di una riga ne occupano almeno questa parte (il resto sono gli spazi fra loro). Se con il carattere
# del sistema non si trova, si prova con la successiva; 0 = senza questa richiesta (come fino alla 0.20.6)
FILLS = (0.94, 0.88, 0.80, 0)
COUNTS = (2, 3, 4, 5, 6, 7, 8, 9)  # quanti nomi può avere una riga (le ripetizioni vanno bene: l'elenco ricomincia)
SIZE_DIFF = 1  # due grandezze dello stesso nome sono sempre diverse (di solito di 3-4 pixel o più)
WEIGHTS = (600, 400, 300, 600, 600, 300, 600, 400, 300)  # peso del carattere riga per riga
FONT_FAMILY = "Segoe UI"


def row_alpha(px):
    """Opacità dei nomi già incisi: più la riga è grande, più è tenue."""
    return 0.10 if px >= 19 else 0.13 if px >= 15 else 0.17


COLD_RGB = (150, 180, 255)  # i nomi già incisi: appena visibili
STRIP_PAD = 8.0  # margine sopra e sotto ogni riga nella sua immagine (alone del testo caldo)
HOT = "#FFC58A"  # il testo appena inciso, ancora caldo
GLOW = (255, 138, 61)  # alone arancio del testo caldo e del puntino
TRAIL = 140.0  # quanti pixel dietro al puntino restano caldi
DOT = 6.0
ROW_S = 1.6  # una riga si scopre da sinistra a destra in questo tempo
STAGGER_S = 0.115  # ogni riga parte dopo la precedente (12 righe: tutto in circa 3 secondi, come prima)
COOL_S = 0.12  # il caldo in fondo alla riga si spegne in questo tempo
ENGRAVE_S = ROW_S + STAGGER_S * (ROWS - 1) + COOL_S  # tutta l'incisione: circa 3,1 secondi
MIN_SHOW_S = 4.0  # sui PC veloci la schermata resta almeno così (Ale: 3 s dal 16/11, 4 s dal 24/11 per lo scorrimento)
FRAME_S = 1 / 40  # non più di 40 ridisegni al secondo
# 0.22.9 (Ale, 25/11: «l'animazione iniziale è ancora scattosa»): mentre le librerie pesanti si caricano in un thread a
# parte (Splash.preload) il thread dell'interfaccia è libero e ridisegna a 60 fotogrammi al secondo
PRELOAD_FRAME_S = 1 / 60
PRELOAD_SWITCH_S = 0.0005  # cambio di thread di Python durante il caricamento (vedi Splash.preload)
# 0.22.6: scorrimento dei nomi a incisione finita
SCROLL_PX_S = 9.0  # pixel al secondo: piano
SCROLL_EASE_S = 1.2  # parte dolcemente in questo tempo
SCROLL_GAP = 26.0  # spazio fra la fine di una riga e il suo ricominciare
SCROLL_PERIOD = (W - 2 * SIDE) + SCROLL_GAP  # dopo tanti pixel la riga è di nuovo uguale a se stessa
SCROLL_FRAME_S = 1 / 25  # durante lo scorrimento bastano 25 ridisegni al secondo: il caricamento non deve rallentare
# 0.22.6: nuova veste grafica (logo «metallo e neon»): il logo con la scritta è un'immagine, il motto lo scrive il
# programma nella sua lingua
LOGO_W, LOGO_TOP = 486.0, 34.0  # larghezza e posizione del logo con la scritta
LOGO_WORD = (0.317, 1.0)  # dove sta la scritta dentro l'immagine (da sinistra, in parti della larghezza)
MOTTO_Y = 0.80  # il motto: sotto la riga luminosa della scritta (in parti dell'altezza dell'immagine)
MOTTO_PX, MOTTO_SPACING = 11, 2.6
SLOW_FRAME_S = 0.15  # un ridisegno più lento di così, due volte: PC troppo lento, si passa allo stato finale
ORANGE = "#FF8A3D"  # 0.20.0: il numero di versione in risalto, con l'arancio della fine del raggio


def headless():
    """Senza schermo vero (prove automatiche): niente attese."""
    return QGuiApplication.platformName() in ("offscreen", "minimal") or bool(os.environ.get("FLC_NO_SPLASH_WAIT"))


def name_font(px=19, weight=600):
    f = QFont(FONT_FAMILY)
    f.setPixelSize(int(px))
    f.setWeight(QFont.Weight(int(weight)))
    return f


class Row:
    """Una riga della trama: dove sta, com'è scritta e i suoi pezzi [(testo, x dal margine sinistro, larghezza)]."""

    def __init__(self, top, px, weight, alpha, items):
        self.top, self.px, self.weight, self.alpha, self.items = float(top), int(px), int(weight), float(alpha), items
        self.h = px * LEADING
        self.alone = False  # un nome solo perché con il successivo non ci stava nemmeno alla grandezza più piccola

    @property
    def bottom(self):
        return self.top + self.h

    def names(self):
        return [t.split("\u00a0")[-1] for t, _x, _w in self.items if t != "·"]

    def font(self):
        return name_font(self.px, self.weight)


def name_rows(names=None, lead=None, stretch=1.0):
    """Le 9 righe della trama (Row), dall'alto: nomi nell'ordine dell'elenco (finito, si ricomincia), righe di
    grandezze irregolari e alternate, lo stesso nome mai due volte di seguito con la stessa grandezza. In ogni riga
    almeno due nomi interi, da un bordo all'altro. La prima comincia con «Grazie a» nella lingua del programma.
    stretch: per le prove, allarga o stringe le larghezze misurate (altri sistemi hanno altri caratteri)."""
    names = [n for n in (thanks.NAMES if names is None else names) if n and n.strip()]
    lead = tr("Grazie a") if lead is None else lead
    width = W - 2 * SIDE
    fms, cache, fits = {}, {}, {}

    def measure(px, weight):
        fm = fms.get((px, weight))
        if fm is None:
            fm = fms[(px, weight)] = QFontMetricsF(name_font(px, weight))

        def m(text):
            key = (px, weight, text)
            if key not in cache:
                cache[key] = fm.horizontalAdvance(text) * stretch
            return cache[key]
        return m

    def gap(px):
        return max(5.0, px * 0.4)

    def fit(r, pos, k):
        """La grandezza più grande a cui k nomi dalla posizione pos stanno nella riga r (0 = nemmeno la minima)."""
        weight = WEIGHTS[r % len(WEIGHTS)]
        key = (weight, pos % len(names), k, r == 0)
        if key not in fits:
            best = 0
            for px in range(SIZE_MIN, SIZE_MAX + 1):
                if thanks.row_width(names, pos, k, measure(px, weight), lead if r == 0 else "", gap(px)) > width:
                    break
                best = px
            fits[key] = best
        return fits[key]

    def dense(fill):
        def ok(r, pos, k, px):
            """0.20.7: la riga è piena almeno per «fill»: niente grandi spazi fra un nome e l'altro."""
            weight = WEIGHTS[r % len(WEIGHTS)]
            return thanks.row_width(names, pos, k, measure(px, weight), lead if r == 0 else "", gap(px)) >= fill * width
        return ok

    room = int((BAND_TOP - 5.0 - TOP0) / LEADING)  # somma massima delle grandezze che sta sopra la fascia in basso
    plan = None
    # con caratteri molto larghi o strani una trama così fitta può non esserci: si allenta. Prima conta che le righe
    # siano piene (la richiesta di Ale), poi che due righe vicine abbiano grandezze ben diverse (PASSES, dentro
    # plan_rows: da 4 pixel di differenza in giù)
    for fill in FILLS:
        plan = thanks.plan_rows(len(names), ROWS, fit, SIZE_MIN, SIZE_MAX, room, FIRST_MAX, counts=COUNTS,
                                ok=dense(fill) if fill else None, fallback=not fill)
        if plan:
            break
    sizes = [px for _k, px in plan]
    items = thanks.place_rows(names, plan, [measure(px, WEIGHTS[r % len(WEIGHTS)]) for r, px in enumerate(sizes)],
                              width, lead=lead)
    spare = max(0.0, (BAND_TOP - 5.0 - TOP0) - sum(sizes) * LEADING) / max(1, ROWS - 1)  # lo spazio che avanza, fra le righe
    rows, top = [], TOP0
    pos = 0
    for r, (px, it) in enumerate(zip(sizes, items)):
        rows.append(Row(top, px, WEIGHTS[r % len(WEIGHTS)], row_alpha(px), it))
        rows[-1].alone = bool(names) and len(names) > 1 and plan[r][0] == 1 and fit(r, pos, 2) < SIZE_MIN
        pos += plan[r][0]
        top += px * LEADING + spare
    return rows


def repeats_same_size(rows, min_diff=SIZE_DIFF):
    """Quante volte un nome ricompare con la grandezza dell'ultima volta (0 = mai)."""
    return thanks.same_size_repeats([r.items for r in rows], [r.px for r in rows], min_diff=min_diff)


def row_progress(t, i):
    """Quanto è incisa la riga i dopo t secondi: 0 = non ancora, 1 = tutta."""
    return min(1.0, max(0.0, (t - i * STAGGER_S) / ROW_S))


def scroll_distance(t):
    """0.22.6: di quanti pixel hanno scorso le righe dopo t secondi dall'apertura (0 finché l'incisione non è finita).
    Partenza dolce: nei primi SCROLL_EASE_S la velocità cresce da 0 a SCROLL_PX_S."""
    u = t - ENGRAVE_S
    if u <= 0:
        return 0.0
    return SCROLL_PX_S * (u * u / (2 * SCROLL_EASE_S) if u < SCROLL_EASE_S else u - SCROLL_EASE_S / 2)


def row_shift(i, dist):
    """Spostamento della riga i (0 = la prima): le pari verso destra, le dispari verso sinistra. Sempre fra 0 e
    SCROLL_PERIOD: uscita da un bordo, la riga rientra dall'altro."""
    return (dist if i % 2 == 0 else -dist) % SCROLL_PERIOD


def _dpr():
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def _blank(dpr):
    pm = QPixmap(int(W * dpr), int(H * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    return pm


def _card_path():
    card = QPainterPath()
    card.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 18, 18)
    return card


def _pixmap(dpr=None):
    """Il fondo della schermata: il cartoncino blu con il bordo. Logo, raggio e versione stanno in _foreground,
    che si disegna SOPRA la trama dei nomi."""
    pm = _blank(dpr or _dpr())
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    card = _card_path()
    bg = QLinearGradient(0, 0, W, H)
    bg.setColorAt(0.0, QColor("#0B2259"))  # 0.22.6: blu notte, senza il viola
    bg.setColorAt(0.5, QColor("#040C28"))
    bg.setColorAt(1.0, QColor("#0A1338"))
    p.fillPath(card, bg)
    edge = QLinearGradient(0, 0, W, H)  # bordo: blu in alto a sinistra, arancio in basso a destra, come il logo
    edge.setColorAt(0.0, QColor(41, 170, 255, 170))
    edge.setColorAt(0.6, QColor(41, 120, 255, 90))
    edge.setColorAt(1.0, QColor(255, 138, 30, 170))
    p.setPen(QPen(edge, 1.3))
    p.drawPath(card)
    p.end()
    return pm


def _foreground(dpr=None):
    """Sopra la trama: il logo, il «raggio» in basso, l'autore e il numero di versione."""
    pm = _blank(dpr or _dpr())
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if not _draw_logo(p, pm.devicePixelRatio()):
        r = QSvgRenderer(os.path.join(ASSETS, "logo_scritta.svg"))  # il logo di prima, se l'immagine nuova manca
        if r.isValid():
            vb = r.viewBoxF()
            w = 470.0
            h = w * vb.height() / max(vb.width(), 1)
            r.render(p, QRectF((W - w) / 2, 40, w, h))
    # "raggio" in basso: una linea che sfuma dal blu all'arancio
    beam = QLinearGradient(60, 0, W - 60, 0)
    beam.setColorAt(0.0, QColor(41, 170, 255, 0))
    beam.setColorAt(0.3, QColor("#29AAFF"))
    beam.setColorAt(0.62, QColor("#2E7CF6"))
    beam.setColorAt(0.86, QColor("#FF8A1E"))
    beam.setColorAt(1.0, QColor(255, 138, 30, 0))
    p.fillRect(QRectF(60, 250, W - 120, 2), beam)
    _version_badge(p)
    p.end()
    return pm


def logo_rect(size):
    """Dove va il logo con la scritta: largo LOGO_W, centrato, con le proporzioni dell'immagine (size = (l, a))."""
    w, h = size
    return QRectF((W - LOGO_W) / 2, LOGO_TOP, LOGO_W, LOGO_W * h / max(w, 1))


def motto_font(text, room, family=FONT_FAMILY):
    """Il carattere del motto: maiuscolo spaziato. Le traduzioni più lunghe stringono prima gli spazi fra le lettere
    e poi rimpiccioliscono, finché il motto sta in `room` pixel. -> (QFont, larghezza)"""
    f = QFont(family)
    f.setWeight(QFont.DemiBold)
    width = 0.0
    for px, sp in ((MOTTO_PX, MOTTO_SPACING), (MOTTO_PX, 1.8), (MOTTO_PX, 1.0), (10, 1.0), (10, 0.4), (9, 0.4), (8, 0.2)):
        f.setPixelSize(px)
        f.setLetterSpacing(QFont.AbsoluteSpacing, sp)
        width = QFontMetricsF(f).horizontalAdvance(text) - sp  # dopo l'ultima lettera lo spazio non conta
        if width <= room:
            break
    return f, width


def motto_text():
    return tr("SOFTWARE LIBERO PER INCISIONE LASER")


def _draw_logo(p, dpr=1.0):
    """0.22.6: il logo nuovo con la scritta (immagine con il fondo trasparente) e sotto il motto, nella lingua del
    programma. -> False se l'immagine non c'è o non si legge (allora si disegna il logo di prima)."""
    reader = QImageReader(os.path.join(ASSETS, "logo_scritta.png"))
    size = reader.size()
    if not size.isValid():
        return False
    rect = logo_rect((size.width(), size.height()))
    # si legge già della misura che serve: niente immagine grande in memoria e un solo rimpicciolimento, fatto bene
    want_w = min(size.width(), int(round(rect.width() * dpr)))
    reader.setScaledSize(size.scaled(want_w, 10 ** 6, Qt.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return False
    p.drawImage(rect, img)
    x0, x1 = rect.left() + LOGO_WORD[0] * rect.width(), rect.left() + LOGO_WORD[1] * rect.width()
    text = motto_text()
    f, _w = motto_font(text, x1 - x0)
    p.setFont(f)
    p.setPen(QColor("#DCE8FF"))
    p.drawText(QRectF(x0, rect.top() + MOTTO_Y * rect.height(), x1 - x0, 18), Qt.AlignHCenter | Qt.AlignVCenter, text)
    return True


def _strip(dpr, h):
    pm = QPixmap(int(W * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    return pm


def _draw_row(p, row, color):
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(row.font())
    p.setPen(color)
    for text, x, w in row.items:
        p.drawText(QRectF(SIDE + x, STRIP_PAD, w + 2, row.h), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextDontClip, text)


def _row_strips(row, dpr=None):
    """Due immagini della riga, larghe come la schermata: fredda (i nomi già incisi) e calda (appena incisi, con
    l'alone arancio). A ogni ridisegno se ne copiano solo dei pezzi: nessun testo viene ridisegnato."""
    dpr = dpr or _dpr()
    h = row.h + 2 * STRIP_PAD
    cold = _strip(dpr, h)
    p = QPainter(cold)
    _draw_row(p, row, QColor(*COLD_RGB, int(round(row.alpha * 255))))
    p.end()
    glow = _strip(dpr, h)
    p = QPainter(glow)
    _draw_row(p, row, QColor(*GLOW, 235))
    p.end()
    # alone: l'immagine del testo rimpicciolita e riallargata con interpolazione (una sfocatura che costa poco)
    img = glow.toImage()
    small = img.scaled(max(1, img.width() // 5), max(1, img.height() // 5), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation)
    blur = small.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blur.setDevicePixelRatio(dpr)
    hot = _strip(dpr, h)
    p = QPainter(hot)
    p.drawImage(0, 0, blur)
    p.drawImage(0, 0, blur)  # due volte: alone più deciso
    _draw_row(p, row, QColor(HOT))
    p.end()
    return cold, hot


class _Pulse:
    """Un «cercatore» di moduli che non trova mai niente: serve solo a far ridisegnare la schermata d'avvio ogni
    volta che Python carica un modulo (vedi Splash.pulse)."""

    def __init__(self, splash):
        self.splash = splash

    def find_spec(self, name, path=None, target=None):
        s = self.splash
        if s is not None:
            try:
                s.pulse()
            except Exception:  # noqa: BLE001 — la schermata non deve mai fermare il caricamento
                self.splash = None
        return None

    def invalidate_caches(self):
        return None


class Splash(QSplashScreen):
    def __init__(self, pixmap, names=None, min_show=None, clock=time.monotonic):
        # niente WindowStaysOnTopHint: coprirebbe la scelta dell'interfaccia e i messaggi d'errore
        super().__init__(pixmap)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._msg = tr("Avvio in corso…")
        self._clock = clock
        self._t0 = clock()
        self._last = -1.0
        self._tid = threading.get_ident()
        self._busy = False
        self._slow = 0
        self._final = False  # PC troppo lento per l'animazione: si disegna lo stato finale
        self._hook = None
        self.frames = 0  # ridisegni fatti (per le prove e per il rapporto)
        self.min_show = (0.0 if headless() else MIN_SHOW_S) if min_show is None else float(min_show)
        dpr = pixmap.devicePixelRatio() or 1.0
        try:
            self.rows = name_rows(names)
            self._strips = [_row_strips(r, dpr) for r in self.rows]
        except Exception:  # noqa: BLE001 — senza i nomi la schermata resta quella di sempre
            self.rows, self._strips = [], []
        try:
            self._fg = _foreground(dpr)
        except Exception:  # noqa: BLE001
            self._fg = None

    # ---- tempo
    def elapsed(self):
        return 1e9 if self._final else self._clock() - self._t0

    def engraved(self):
        """L'incisione dei nomi è finita?"""
        return self.elapsed() >= ENGRAVE_S

    # ---- ridisegno durante il caricamento
    def install_pulse(self):
        if self._hook is None:
            self._hook = _Pulse(self)
            sys.meta_path.insert(0, self._hook)
            heartbeat.hook = self.pulse  # 0.22.6: anche la costruzione della finestra fa battere la schermata

    def remove_pulse(self):
        h, self._hook = self._hook, None
        if h is not None:
            heartbeat.hook = None
            h.splash = None
            try:
                sys.meta_path.remove(h)
            except ValueError:
                pass

    def pulse(self):
        """Ridisegna, se è passato abbastanza dall'ultima volta. Solo dal thread dell'interfaccia, mai dentro un
        altro ridisegno, mai a schermata nascosta. 0.22.6: a incisione finita si continua, più piano (i nomi
        scorrono); niente più solo sui PC lenti, dove la schermata è già nello stato finale e resta ferma.
        -> True se ha ridisegnato."""
        if self._busy or threading.get_ident() != self._tid:
            return False
        now = self._clock()
        done = self._last >= 0 and self._last - self._t0 > ENGRAVE_S  # l'ultimo ridisegno era già a incisione finita
        if now - self._last < (SCROLL_FRAME_S if done else FRAME_S) or (done and self._final):
            return False
        if not self.isVisible():
            return False
        self._busy = True
        try:
            self.repaint()
        finally:
            self._busy = False
        return True

    def preload(self, fn):
        """0.22.9: chiama fn (gli import delle librerie pesanti: numpy, OpenCV, numba) in un thread a parte e intanto
        ridisegna la schermata a PRELOAD_FRAME_S. Fino alla 0.22.8 la schermata si ridisegnava solo fra un modulo e
        l'altro: OpenCV e la libreria di numba si caricano in un pezzo solo (su Windows anche mezzo secondo, con
        l'antivirus), e l'incisione andava a scatti. Il caricamento delle librerie (le DLL) lascia libero Python, quindi
        qui si ridisegna davvero mentre si caricano.
        Un errore in fn non esce da qui: l'import vero, subito dopo nel thread principale, lo ripete e lo mostra con
        la guardia d'avvio come sempre. A schermata nascosta, su un PC lento (stato finale) o fuori dal thread
        dell'interfaccia fn si chiama qui, come prima. -> secondi passati."""
        start = self._clock()
        if not self.isVisible() or self._final or threading.get_ident() != self._tid:
            try:
                fn()
            except Exception:  # noqa: BLE001 — lo ripete e lo mostra l'import nel thread principale
                pass
            return self._clock() - start
        done = threading.Event()

        def work():
            try:
                fn()
            except BaseException:  # noqa: BLE001 — come sopra
                pass
            finally:
                done.set()

        # Ogni chiamata a Qt lascia libero Python e poi lo deve riprendere: con il thread che carica in Python (numpy)
        # di solito si aspetta fino a 5 ms ogni volta, e un ridisegno ne fa decine. Durante il caricamento il cambio è
        # più svelto (0,5 ms), poi torna quello di prima.
        switch = sys.getswitchinterval()
        sys.setswitchinterval(min(switch, PRELOAD_SWITCH_S))
        try:
            threading.Thread(target=work, name="flc-librerie", daemon=True).start()
            flags = QEventLoop.ExcludeUserInputEvents | QEventLoop.ExcludeSocketNotifiers
            while not done.is_set():
                if self.isVisible() and not self._final and self._clock() - self._last >= PRELOAD_FRAME_S:
                    self._last = -1.0  # pulse() userebbe il passo più lento: qui il thread dell'interfaccia è libero
                    self.pulse()
                QGuiApplication.processEvents(flags)
                done.wait(0.004)
        finally:
            sys.setswitchinterval(switch)
        return self._clock() - start

    def say(self, text):
        self._msg = text
        if not self._busy:
            self._busy = True
            try:
                self.repaint()
            finally:
                self._busy = False
        QGuiApplication.processEvents()

    def wait_min(self):
        """Sui PC veloci: tiene la schermata finché non sono passati min_show secondi dall'apertura, con l'incisione
        (e poi lo scorrimento dei nomi) che va avanti. Da chiamare a finestra principale già costruita, prima di mostrarla. Senza schermo, a
        schermata nascosta o con il tempo già passato non aspetta. -> secondi aspettati."""
        start = self._clock()
        # l'attesa arriva almeno alla fine dell'incisione (3,1 s), così la schermata non sparisce a metà dell'ultima riga
        until = max(self.min_show, ENGRAVE_S) if self.min_show > 0 else 0.0
        while self.isVisible() and not self._final and self._clock() - self._t0 < until:
            self._last = -1.0
            self.pulse()
            QGuiApplication.processEvents(QEventLoop.ExcludeUserInputEvents, 10)
            time.sleep(0.012)
        return self._clock() - start

    def finish(self, win):
        self.remove_pulse()
        super().finish(win)

    def closeEvent(self, e):
        self.remove_pulse()
        super().closeEvent(e)

    # ---- disegno
    def _piece(self, p, pm, x, w, y):
        """Copia sulla schermata, all'altezza y, la parte da x a x + w dell'immagine di una riga."""
        if w <= 0:
            return
        d = pm.devicePixelRatio()
        h = pm.height() / d
        p.drawPixmap(QRectF(x, y, w, h), pm, QRectF(x * d, 0, w * d, pm.height()))

    def paint_names(self, p, t):
        """La trama dei nomi com'è dopo t secondi dall'apertura."""
        if not self._strips or not self.rows:
            return
        p.save()
        p.setClipPath(_card_path())
        # la fascia in basso (raggio, messaggio, versione) resta sempre libera: nemmeno l'alone ci arriva
        p.setClipRect(QRectF(0, 0, W, BAND_TOP), Qt.IntersectClip)
        dist = 0.0 if self._final else scroll_distance(t)  # 0.22.6: PC lento = nomi fermi
        for i, (row, (cold, hot_pm)) in enumerate(zip(self.rows, self._strips)):
            f = row_progress(t, i)
            if f <= 0 or not row.items:
                continue
            y = row.top - STRIP_PAD
            if dist > 0:  # incisione finita: la riga intera, spostata; tre copie perché rientri dall'altro bordo
                dx = row_shift(i, dist)
                h = cold.height() / cold.devicePixelRatio()
                for k in (-1, 0, 1):
                    p.drawPixmap(QRectF(dx + k * SCROLL_PERIOD, y, W, h), cold, QRectF(cold.rect()))
                continue
            x = f * W  # il fronte dell'incisione, da un bordo all'altro della schermata
            self._piece(p, cold, 0.0, x, y)
            done = t - i * STAGGER_S - ROW_S  # da quanto la riga è finita (negativo: in corso)
            heat = 1.0 if done <= 0 else max(0.0, 1.0 - done / COOL_S)
            if heat > 0:  # il tratto appena inciso: caldo vicino al puntino, via via più freddo dietro
                steps = 14
                sw = TRAIL / steps
                for k in range(steps):
                    x0 = x - TRAIL + k * sw
                    if x0 + sw <= 0:
                        continue
                    p.setOpacity(heat * (k + 1) / steps)
                    self._piece(p, hot_pm, max(0.0, x0), sw - max(0.0, -x0), y)
                p.setOpacity(1.0)
            if 0 < f < 1:  # il puntino del laser sul fronte
                c = QPointF(x, row.top + row.h / 2)
                g = QRadialGradient(c, 13)
                g.setColorAt(0.0, QColor(*GLOW, 230))
                g.setColorAt(0.35, QColor(*GLOW, 120))
                g.setColorAt(1.0, QColor(*GLOW, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(c, 13, 13)
                p.setBrush(QColor("#FFF4E0"))
                p.drawEllipse(c, DOT / 2, DOT / 2)
        p.restore()

    def drawContents(self, p):
        was, self._busy = self._busy, True  # un modulo caricato mentre si disegna non deve far ridisegnare
        t_paint = time.perf_counter()
        try:
            self._last = self._clock()
            self.frames += 1
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            try:
                self.paint_names(p, self.elapsed())
            except Exception:  # noqa: BLE001 — senza i nomi, ma la schermata c'è
                self._strips = []
            if self._fg is not None:
                p.drawPixmap(0, 0, self._fg)
            f = QFont("Segoe UI")
            f.setPixelSize(13)
            p.setFont(f)
            p.setPen(QColor("#C9D5F5"))
            p.drawText(QRectF(24, 262, 300, 22), Qt.AlignLeft | Qt.AlignVCenter, self._msg)
        finally:
            self._busy = was
        if time.perf_counter() - t_paint > SLOW_FRAME_S:
            self._slow += 1
            if self._slow >= 2:
                self._final = True
        elif self._slow:
            self._slow = 0


def _version_badge(p):
    """In basso a destra: l'autore in grigio e il numero di versione in arancio, dentro una pastiglia sottile."""
    num = QFont("Segoe UI")
    num.setPixelSize(14)
    num.setWeight(QFont.DemiBold)
    num.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
    p.setFont(num)
    text = "v" + display_version()  # 0.20.8: il nome della versione («0.20.VI»), se c'è
    tw = p.fontMetrics().horizontalAdvance(text)
    pill = QRectF(W - 24 - (tw + 22), 262, tw + 22, 22)
    path = QPainterPath()
    path.addRoundedRect(pill, 11, 11)
    o = QColor(ORANGE)
    p.fillPath(path, QColor(o.red(), o.green(), o.blue(), 28))
    p.setPen(QPen(QColor(o.red(), o.green(), o.blue(), 120), 1.0))
    p.drawPath(path)
    p.setPen(o)
    p.drawText(pill, Qt.AlignCenter, text)
    small = QFont("Segoe UI")
    small.setPixelSize(12)
    p.setFont(small)
    p.setPen(QColor("#8C9CC4"))
    p.drawText(QRectF(0, 262, pill.left() - 10, 22), Qt.AlignRight | Qt.AlignVCenter, __author__)
    return pill


def render(t, names=None, msg=None, dpr=1.0):
    """La schermata com'è dopo t secondi, in un'immagine (per le prove e per vederla senza avviare il programma)."""
    img = QImage(int(W * dpr), int(H * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.transparent)
    base = _pixmap(dpr)
    s = Splash(base, names=names, min_show=0.0, clock=lambda: t)
    s._t0 = 0.0
    if msg is not None:
        s._msg = msg
    p = QPainter(img)
    p.drawPixmap(0, 0, base)
    s.drawContents(p)
    p.end()
    s.deleteLater()
    return img


def show_splash():
    s = Splash(_pixmap())
    s.show()
    s.raise_()
    s.install_pulse()
    QGuiApplication.processEvents()
    return s
