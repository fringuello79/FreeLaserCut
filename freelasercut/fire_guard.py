# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Guardia fiamme: durante un lavoro guarda le immagini della camera e riconosce una fiammata.

Una fiamma, per la camera, è una zona di pixel molto luminosi, caldi (dal rosso al giallo) e saturi, più grande
del puntino del laser e della brace che si vede normalmente dove il laser incide. Nei primi fotogrammi del lavoro
si misura quanto "caldo" c'è di solito (luci, brace normale); l'allarme scatta solo se la zona calda supera
nettamente quel livello per alcuni fotogrammi di fila, così un riflesso o una scintilla isolata non fermano il lavoro.

È un aiuto in più, non sostituisce la sorveglianza: la camera deve vedere il piano e la stanza deve essere
abbastanza illuminata. Nessuna parte di questo modulo usa Qt: si prova da sola con immagini sintetiche.
"""
import collections
import statistics

import cv2
import numpy as np

# sensibilità: frazione minima dell'immagine (rimpicciolita a 320 px) occupata dalla zona calda
LEVELS = {"alta": 0.0015, "media": 0.004, "bassa": 0.010}
WIDTH = 320
LEARN = 6  # fotogrammi iniziali per imparare il livello "normale"


def hot_mask(frame_bgr):
    """Maschera dei pixel "da fiamma" dell'immagine rimpicciolita a WIDTH px di larghezza.

    Una fiamma vista dalla camera ha un bordo caldo (rosso, arancio, giallo) e spesso un cuore quasi bianco, perché
    la camera è abbagliata. Il bordo caldo conta sempre; le zone molto chiare contano solo se toccano un bordo caldo:
    così una lampada bianca o un foglio illuminato da soli non sembrano fiamme."""
    h, w = frame_bgr.shape[:2]
    if w != WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (WIDTH, max(1, int(round(h * WIDTH / w)))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    warm_hue = (hh <= 35) | (hh >= 165)  # rosso, arancio, giallo (OpenCV: 0..180)
    rim = warm_hue & (ss >= 90) & (vv >= 150)
    rim = cv2.morphologyEx(rim.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    bright = ((vv >= 230) & (ss <= 120)).astype(np.uint8)
    out = rim.copy()
    if bright.any() and rim.any():
        n, lab = cv2.connectedComponents(bright, connectivity=8)
        near = cv2.dilate(rim, np.ones((5, 5), np.uint8)) > 0
        keep = np.unique(lab[near & (bright > 0)])
        keep = keep[keep > 0]
        if keep.size:
            out |= np.isin(lab, keep).astype(np.uint8)
    m = out * 255
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def hot_fraction(frame_bgr):
    m = hot_mask(frame_bgr)
    return float(np.count_nonzero(m)) / m.size


class FlameDetector:
    def __init__(self, sensitivity="media", frames=3):
        self.sensitivity = sensitivity if sensitivity in LEVELS else "media"
        self.frames = max(1, int(frames))
        self.reset()

    def reset(self):
        self.base = collections.deque(maxlen=LEARN)
        self.streak = 0
        self.last = {"fraction": 0.0, "threshold": LEVELS[self.sensitivity], "streak": 0, "alarm": False,
                     "learning": True}

    def threshold(self):
        level = LEVELS[self.sensitivity]
        if not self.base:
            return level
        base = statistics.median(self.base)
        return max(level, base * 1.5 + level)  # sopra il normale di almeno una «fiamma minima»

    def update(self, frame_bgr):
        m = hot_mask(frame_bgr)
        frac = float(np.count_nonzero(m)) / m.size
        learning = len(self.base) < LEARN
        if learning:
            # all'inizio del lavoro imparo il livello normale (ma una fiamma già grande scatta lo stesso)
            if frac < LEVELS[self.sensitivity] * 4:
                self.base.append(frac)
        thr = self.threshold()
        self.streak = self.streak + 1 if frac > thr else 0
        self.last = {"fraction": frac, "threshold": thr, "streak": self.streak, "alarm": self.streak >= self.frames,
                     "learning": learning}
        return self.last
