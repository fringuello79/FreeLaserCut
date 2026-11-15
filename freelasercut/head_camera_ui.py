# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: camera della testa nell'interfaccia.

- HeadCameraCard: il riquadro «Camera della testa» nel pannello Camera (scelta della telecamera, stato, pulsanti).
  Tiene la telecamera aperta e il modello (head_camera.HeadModel) e fa i comandi: laser sul centro camera, camera
  sul laser, camera o laser in un punto del piano, origine dal centro camera, tavola da due angoli, foto a mosaico.
- HeadCameraWindow: la vista dal vivo con mirino, righello in mm e disegno sovrapposto; un clic sul video porta lì
  il centro della camera.
Tutti i conti passano dal modello (P = L + O + M · (p − c)); le destinazioni restano dentro il piano."""
import math
import time

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from . import camera as camera_mod
from . import head_camera as hc
from . import head_grid as hg
from .camera import CameraSource
from .i18n import tr
from .theme import C, css

CAM_COLOR = "#2ED3B7"  # centro della camera della testa: verde acqua (la testa è azzurra, il punto di partenza magenta)
BOARD_COLOR = "#F5B83D"


def to_qimage(bgr):
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy()


# ======================================================================= riquadro nel pannello Camera
class HeadCameraCard(QWidget):
    changed = Signal()

    def __init__(self, panel):
        super().__init__()
        from .app import card, muted

        self.panel = panel
        self.ctl = panel.ctl
        self.win = panel.win
        self.src = None
        self.model = hc.HeadModel.load()
        self.model_ok = self.model is not None  # False se la risoluzione della camera aperta è diversa
        self.model_why = ""  # perché il modello non vale con la camera aperta
        self.window = None
        self.cal = None
        self.job = None  # foto a mosaico in corso
        self.check = None  # 0.20.2: «Controlla la calibrazione» in corso
        if self.model is not None:
            self.model.set_thickness(self.thickness() if self.model.moves_with_head is False else None)
        self.board = [None, None]  # angoli A e B della tavola (mm sul piano)
        self.last_msg = ""
        self.mark = None  # (u, v) del puntino durante la calibrazione
        self.waiting_click = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        box, bl = card(tr("Camera della testa"))
        self.combo = QComboBox()
        self.combo.setIconSize(QSize(96, 54))
        self.combo.setMinimumHeight(40)
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        self.combo.activated.connect(self._chosen)
        self.combo.setToolTip(tr("Quale delle telecamere collegate è fissata alla testa del laser. Puoi scegliere anche "
                                 "quella che ora è la camera del piano: passa alla testa."))
        # 0.20.3 (Ale, 15/11): la telecamera della testa si sceglie sempre, fra tutte quelle collegate; ⟳ le cerca di
        # nuovo anche da qui (prima il pulsante era solo nella scheda Camera)
        crow = QHBoxLayout()
        crow.addWidget(self.combo, 1)
        self.btn_search = QToolButton()
        self.btn_search.setText("⟳")
        self.btn_search.setToolTip(tr("Cerca di nuovo le telecamere USB"))
        self.btn_search.clicked.connect(lambda: self.panel.search(manual=True))
        crow.addWidget(self.btn_search)
        bl.addLayout(crow)
        self.state = muted("")
        bl.addWidget(self.state)
        self.note = muted("")  # che cosa manca per fare quello che hai chiesto (prima il pulsante era solo spento)
        self.note.hide()
        bl.addWidget(self.note)
        self.bed_line = muted("")
        bl.addWidget(self.bed_line)
        row = QHBoxLayout()
        self.btn_view = QPushButton(tr("Vista della testa…"))
        self.btn_view.setToolTip(tr("Video della camera della testa con mirino e righello: un clic sul video porta lì "
                                    "il centro della camera"))
        self.btn_view.clicked.connect(self.open_window)
        self.btn_cal = QPushButton(tr("Calibra…"))
        self.btn_cal.setToolTip(tr("Calibrazione completa, una volta per tutte: incide una griglia di puntini su un "
                                   "cartone di circa 15 × 10 cm e misura lente, inclinazione, scala e distanza fra "
                                   "laser e camera"))
        self.btn_cal.clicked.connect(lambda: self.open_window(calibrate=True))
        row.addWidget(self.btn_view, 1)
        row.addWidget(self.btn_cal)
        bl.addLayout(row)
        lay.addWidget(box)
        self.update_state()

    # ---------------------------------------------------------------- scelta della telecamera
    def choice(self):
        qs = getattr(self.win, "qs", None)
        v = qs.value("head_camera_choice") if qs is not None else None
        if v in (None, ""):
            return None
        if str(v) == "none":
            return "none"
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def saved_name(self):
        qs = getattr(self.win, "qs", None)
        return str(qs.value("head_camera_name", "") or "") if qs is not None else ""

    def index(self):
        """Indice della telecamera USB aperta come camera della testa, o None."""
        src = self.src
        return src.index if src is not None and isinstance(getattr(src, "index", None), int) else None

    def wanted(self):
        """0.20.3: la telecamera che la persona ha scelto per la testa (indice), anche se non è ancora aperta: quella
        salvata, ritrovata per nome se il numero è cambiato. None = nessuna."""
        if self.index() is not None:
            return self.index()
        ch = self.choice()
        name = self.saved_name()
        if name:  # 0.20.0: il numero può cambiare (altra porta USB): la ritrovo per nome, se il sistema lo dice
            for i, n in camera_mod.NAMES.items():
                if n == name and camera_mod.name_valid(i, (camera_mod.LAST_PROBE.get(i) or {}).get("mode")):
                    ch = i
                    break
        return ch if isinstance(ch, int) else None

    def release(self, forget=True):
        """0.20.3: la telecamera della testa passa a un altro compito (scelta come camera del piano): si chiude qui."""
        self.close_src()
        qs = getattr(self.win, "qs", None)
        if forget and qs is not None:
            qs.setValue("head_camera_choice", "none")
            qs.setValue("head_camera_name", "")
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self.update_state()
        self.changed.emit()

    def mark_bed_camera(self):
        """Nell'elenco della testa la camera del piano si riconosce, e si può scegliere (passa alla testa)."""
        bed = self.panel.bed_index()
        tag = "  ·  " + tr("ora camera del piano")
        for i in range(self.combo.count()):
            data, text = self.combo.itemData(i), self.combo.itemText(i)
            if not isinstance(data, int):
                continue
            if data == bed and not text.endswith(tag):
                self.combo.setItemText(i, text + tag)
            elif data != bed and text.endswith(tag):
                self.combo.setItemText(i, text[:-len(tag)])

    def set_cameras(self, cams, bed_index):
        """Elenco delle telecamere dopo una ricerca (le stesse del pannello). 0.20.3: si possono scegliere tutte,
        anche quella che ora è la camera del piano (che passa alla testa)."""
        usb = [c for c in cams if isinstance(c[0], int) and c[0] >= 0]
        if self.index() is not None and all(c[0] != self.index() for c in usb):
            frame = self.src.get(after=0, timeout=0.3)
            if frame is not None:
                h, w = frame.shape[:2]
                usb.append((self.index(), camera_mod.camera_label(self.index(), w, h, False, self.src.mode), (w, h),
                            cv2.resize(frame, (160, 90))))
            else:
                usb.append((self.index(), tr("Camera {0}", self.index()), None, None))
        usb.sort(key=lambda c: c[0])
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        for idx, label, _size, thumb, *_ in usb:
            if thumb is not None:
                self.combo.addItem(QIcon(QPixmap.fromImage(to_qimage(thumb))), label, idx)
            else:
                self.combo.addItem(label, idx)
        self.combo.blockSignals(False)
        self.mark_bed_camera()
        want = self.wanted()
        if want is not None and want == bed_index:
            want = None  # aperta come camera del piano: la stessa telecamera non si apre due volte (da sola)
        i = self.combo.findData(want) if want is not None else 0
        self.combo.setCurrentIndex(max(i, 0))
        if want is not None and i > 0 and self.index() != want:
            self._open(want)
        self.update_state()

    def _chosen(self, _i):
        idx = self.combo.currentData()
        qs = getattr(self.win, "qs", None)
        self._note("")
        if idx is not None and idx == self.panel.bed_index():
            # 0.20.3: era la camera del piano: la persona dice che è quella della testa, quindi passa alla testa
            # (prima la scelta veniva rifiutata, e con una telecamera sola quella della testa non si poteva scegliere)
            self.panel.release_bed()
        elif idx is not None and self.panel.choice() == idx and qs is not None:
            qs.setValue("camera_choice", "none")  # scelta salvata per il piano ma non aperta: non deve riprendersela
        if qs is not None:
            qs.setValue("head_camera_choice", "none" if idx is None else int(idx))
        if idx is None:
            self.close_src()
            self.panel.mark_head_camera()
        else:
            self._open(idx)
            if qs is not None and self.src is not None:
                self.panel.mark_head_camera()
                name = camera_mod.NAMES.get(idx, "")
                qs.setValue("head_camera_name", name if camera_mod.name_valid(idx, self.src.mode) else "")
        self.mark_bed_camera()
        self.update_state()
        self.changed.emit()

    def _note(self, text):
        """Riga gialla nel riquadro: che cosa manca (camera non scelta, laser non connesso…). Vuota = nascosta."""
        self.note.setText(text or "")
        self.note.setVisible(bool(text))

    def _open(self, idx):
        if self.index() == idx:
            return True
        self.close_src()
        try:
            self.src = CameraSource(idx, size=hc.HEAD_SIZE, prefer="dshow-mjpg")
        except Exception as exc:  # noqa: BLE001
            self.src = None
            self.last_msg = tr("Non riesco ad aprire la camera della testa: {0}", exc)
            self.update_state()
            return False
        self._check_model_size()
        return True

    def set_source(self, src):
        """Una sorgente già pronta (prove automatiche: camera simulata)."""
        self.close_src()
        self.src = src
        self._check_model_size()
        self.update_state()

    def _check_model_size(self):
        size = tuple(getattr(self.src, "size", (0, 0)) or (0, 0))
        if self.src is not None and not size[0]:
            f = self.src.get(after=0, timeout=2.0)
            size = (f.shape[1], f.shape[0]) if f is not None else size
        self.model_ok = self.model is not None and (not size[0] or tuple(self.model.frame_size) == size)
        self.model_why = "" if self.model_ok or self.model is None else tr("La risoluzione della camera è cambiata: "
                                                                            "ricalibra.")
        # 0.20.2: stessa risoluzione ma modo di lettura diverso (su Windows può tagliare l'immagine in un altro modo)
        mode = str(getattr(self.src, "mode", "") or "")
        if self.model_ok and self.model.camera_mode and mode and mode != self.model.camera_mode:
            self.model_ok = False
            self.model_why = tr("La camera ora si legge in un altro modo ({0}, la calibrazione è stata fatta con {1}): "
                                "l'immagine può essere tagliata diversamente. Ricalibra.", mode, self.model.camera_mode)

    def close_src(self):
        if self.cal is not None:
            self.cal.cancel()
        if self.src is not None:
            self.src.close()
        self.src = None

    # ---------------------------------------------------------------- stato
    def ready(self):
        """Calibrata e utilizzabile per i comandi che muovono la testa."""
        return self.model is not None and self.model_ok

    def busy(self):
        return self.cal is not None or self.job is not None or self.check is not None

    def update_state(self):
        busy = self.busy()
        if self.src is None and self.model is None:
            txt, col = tr("Fissata alla testa, guarda il piano da vicino: sceglila qui sopra e calibrala."), ""
        elif self.src is None:
            txt, col = tr("Calibrata, ma nessuna camera della testa aperta: sceglila qui sopra."), C["warn"]
        elif self.model is None:
            txt, col = tr("Camera pronta, non ancora calibrata: premi «Calibra…»."), C["warn"]
        elif not self.model_ok:
            txt, col = self.model_why or tr("La risoluzione della camera è cambiata: ricalibra."), C["warn"]
        elif self.model.method != "grid":
            txt, col = tr("✓ Calibrata il {0} col puntino (0.20.0)  ·  {1}  ·  per la precisione completa rifai la "
                          "calibrazione", self.model.created, self.model.describe()), C["success"]
        else:
            txt, col = tr("✓ Calibrata il {0}  ·  {1}", self.model.created, self.model.describe()), C["success"]
        if self.src is not None and getattr(self.src, "autofocus", "") == "on":
            txt += "\n" + tr("Attenzione: questa camera ha la messa a fuoco automatica e non si lascia spegnere: se "
                             "l'immagine cambia scala da sola la calibrazione non tiene.")
        if self.last_msg and self.src is None:
            txt, col = self.last_msg, C["warn"]
        self.state.setText(txt)
        self.state.setStyleSheet(f"color:{col};" if col else "")
        self.btn_view.setEnabled(self.src is not None)
        # 0.20.3: «Calibra» si può sempre premere (anche con una calibrazione già fatta): se manca qualcosa lo dice,
        # invece di restare spento senza spiegare perché
        self.btn_cal.setEnabled(not busy)
        self.btn_cal.setText(tr("Calibra di nuovo…") if self.model is not None else tr("Calibra…"))
        bed = self.panel.bed_index() if hasattr(self.panel, "combo") else None
        bed_txt = self.panel.combo.currentText().split("  ·  ")[0] if bed is not None else tr("nessuna")
        self.bed_line.setText(tr("Camera del piano (guarda dall'alto): {0}. Si sceglie nella scheda Camera.", bed_txt))
        line = getattr(self.panel, "_head_line", None)
        if line is not None:
            line()
        if self.window is not None:
            self.window.update_state()
        self.update_marker()

    # ---------------------------------------------------------------- testa e segni sul piano
    def head(self):
        return hc.head_on_bed(self.ctl, self.win.profile) if self.ctl.connected else None

    def update_marker(self, head=None):
        bed = getattr(self.win, "bed", None)
        if bed is None or not hasattr(bed, "set_cam_center"):
            return
        head = head if head is not None else self.head()
        if self.ready() and self.src is not None and head is not None:
            x, y = self.model.center(head)
            bed.set_cam_center(float(x), float(y))
        else:
            bed.set_cam_center(None, None)

    # ---------------------------------------------------------------- comandi che muovono la testa
    def _can_move(self, need_model=True):
        if getattr(self.panel, "autocam", None) is not None:
            return tr("Attendi la fine della calibrazione AutoCam")
        if not self.ctl.connected:
            return tr("Connetti la macchina per muovere la testa")
        if self.ctl.job_active or self.ctl.checking:
            return tr("C'è un lavoro in corso")
        if self.busy():
            return tr("Attendi la fine della calibrazione o della foto")
        if need_model and not self.ready():
            return tr("Calibra prima la camera della testa")
        if self.head() is None:
            return tr("Posizione della testa sconosciuta")
        return None

    def _say(self, text, ms=6000):
        try:
            self.win.statusBar().showMessage(text, ms)
        except Exception:  # noqa: BLE001
            pass
        self._note(text if self.cal is None else "")  # 0.20.3: si legge anche nel riquadro (Impostazioni)
        if self.window is not None:
            self.window.info.setText(text)
        return text

    def _go(self, target, what):
        """La testa (il laser) in target, dentro il piano. -> (x, y) raggiunto o None."""
        p = self.win.profile
        tx, ty = hc.clamp_to_bed(p, *target)
        mx, my = p.to_machine(tx, ty)
        self.ctl.goto_machine(mx, my, 3000)
        miss = math.hypot(tx - target[0], ty - target[1])
        if miss > 0.05:
            self._say(tr("{0}: fin lì la testa non arriva, si ferma al bordo (mancano {1:.1f} mm)", what, miss), 9000)
        else:
            self._say(tr("{0}: X {1:.2f}  Y {2:.2f} mm", what, tx, ty))
        return (tx, ty)

    def laser_to_camera(self):
        """Il laser va dove ora c'è il centro della camera (mirino)."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.center(self.head()), tr("Laser sul centro della camera"))

    def camera_to_laser(self):
        """La camera va a guardare il punto dove ora c'è il laser."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.head_for_camera(self.head()), tr("Camera sul punto del laser"))

    def camera_to(self, x, y):
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.head_for_camera((x, y)), tr("Camera qui"))

    def laser_to(self, x, y):
        why = self._can_move(need_model=False)
        if why:
            return self._say(why) and None
        return self._go((x, y), tr("Laser qui"))

    def camera_to_pixel(self, u, v):
        """Clic sul video: quel punto va sotto il mirino."""
        head = self.head()
        if not self.ready() or head is None:
            return self._say(self._can_move() or tr("Calibra prima la camera della testa")) and None
        P = self.model.img_to_bed(head, [(u, v)])[0]
        return self.camera_to(*P)

    def origin_from_camera(self):
        """L'origine utente (X0 Y0) dove ora c'è il centro della camera: G10 L20 con lo scostamento in coordinate
        macchina (vale con assi invertiti e piano ruotato)."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        dmx, dmy = self.win.profile.to_machine_delta(*self.model.offset)
        line = f"G10 L20 P1 X{-dmx:.3f} Y{-dmy:.3f}"
        self.ctl.send_line(line)
        c = self.model.center(self.head())
        self._say(tr("Origine utente (X0 Y0) sul centro della camera: X {0:.2f}  Y {1:.2f} mm sul piano", c[0], c[1]))
        return line

    # ---------------------------------------------------------------- tavola da due angoli (fase 2)
    def take_corner(self, which, auto=True, frame=None):
        """Angolo della tavola (0 = A, 1 = B) dal centro della camera, oppure dall'angolo trovato vicino al mirino.
        -> (x, y) sul piano o None."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        head = self.head()
        P = self.model.center(head)
        note = tr("dal mirino")
        if auto:
            frame = frame if frame is not None else (self.src.get(after=time.time(), timeout=2.0) if self.src else None)
            if frame is not None:
                found, why_not = hc.find_corner(frame, self.model.c, radius=int(min(self.model.frame_size) * 0.3))
                if found is not None:
                    P = self.model.img_to_bed(head, [found])[0]
                    note = tr("angolo trovato nell'immagine")
                else:
                    note = tr("dal mirino ({0})", why_not)
        self.board[which] = (float(P[0]), float(P[1]))
        self._show_board()
        self._say(tr("Angolo {0} della tavola: X {1:.2f}  Y {2:.2f} mm, {3}", "AB"[which], P[0], P[1], note), 9000)
        return self.board[which]

    def board_angle(self):
        if self.board[0] is None or self.board[1] is None:
            return None
        return hc.board_angle(*self.board)

    def _show_board(self):
        bed = getattr(self.win, "bed", None)
        if bed is not None and hasattr(bed, "set_board"):
            bed.set_board(self.board[0], self.board[1])
        if self.window is not None:
            self.window.update_state()

    def clear_board(self):
        self.board = [None, None]
        self._show_board()

    def align_selection(self, margin=0.0):
        """Ruota la selezione come il lato A→B della tavola e la appoggia in A (+ margine). Un solo Annulla."""
        ang = self.board_angle()
        ed = self.win.editor
        if ang is None:
            return self._say(tr("Prendi prima i due angoli della tavola (A e B, sullo stesso lato)")) and None
        sel = ed.editable()
        if not sel:
            return self._say(tr("Seleziona prima il disegno da mettere sulla tavola")) and None
        from .core import ops

        b = ops.union_bounds(sel)
        A = hc.align_affine((b.left(), b.top(), b.right(), b.bottom()), self.board[0], ang, margin)
        tf = QTransform(A[0, 0], A[1, 0], A[0, 1], A[1, 1], A[0, 2], A[1, 2])
        ed.transform(tf, tr("Allinea alla tavola"), shapes=sel)
        self._say(tr("Disegno appoggiato sulla tavola: ruotato di {0:.2f}°, angolo in A + {1:g} mm", ang, margin))
        return A

    # ---------------------------------------------------------------- calibrazione
    def calibrate(self, power=None, ask=True, guess=None, moves=None, cal_thickness=None):
        """0.20.2: calibrazione completa (griglia di puntini, head_grid.HeadGridCalibration). Prima la finestrella
        (dove è la camera, se sale e scende con il laser, potenza del puntino di prova), poi la testa in un punto da
        cui la camera potrà fotografare la griglia, poi il lavoro vero. ask=False: valori dati (prove, comandi)."""
        if not self.ctl.connected:  # 0.20.3: detto chiaro (il pulsante ora si può sempre premere)
            return self._say(tr("Per calibrare connetti il laser: la calibrazione incide una griglia di puntini su un "
                                "cartone."), 10000) and None
        why = self._can_move(need_model=False)
        if why:
            return self._say(why) and None
        if not self.ctl.homed:
            if ask and QMessageBox.question(self, tr("Camera della testa"),
                                            tr("Prima serve l'homing. Faccio l'homing adesso?")) == QMessageBox.Yes:
                self.ctl.home()
            return None
        if self.ctl.last_status.get("state") == "Alarm":
            return self._say(tr("La macchina è in allarme: sblocca o fai l'homing prima.")) and None
        qs = getattr(self.win, "qs", None)
        if power is None:
            try:
                power = float(qs.value("head_camera_power", hc.DEFAULT_POWER)) if qs is not None else hc.DEFAULT_POWER
            except (TypeError, ValueError):
                power = hc.DEFAULT_POWER
        if moves is None:
            moves = self.moves_answer()
        if cal_thickness is None:
            try:
                cal_thickness = float(qs.value("head_camera_card_mm", 3.0)) if qs is not None else 3.0
            except (TypeError, ValueError):
                cal_thickness = 3.0
        if ask:
            dlg = HeadCalDialog(self, power)
            if dlg.exec() != QDialog.Accepted:
                return None
            power, guess = dlg.power.value(), dlg.pad.guess()
            moves, cal_thickness = dlg.moves(), dlg.card_mm.value()
        if qs is not None:
            qs.setValue("head_camera_power", float(power))
            qs.setValue("head_camera_moves", {True: "yes", False: "no", None: "unknown"}[moves])
            qs.setValue("head_camera_card_mm", float(cal_thickness))
        p = self.win.profile
        start, why = hc.calibration_start(self.head(), guess, (p.bed_x, p.bed_y), margin=hc.START_MARGIN + 60)
        if start is None:
            return self._say(tr("Calibrazione impossibile: {0}", why), 12000) and None
        head = self.head()
        if math.hypot(start[0] - head[0], start[1] - head[1]) > 0.5:
            # la camera da qui non arriverebbe a fotografare la griglia: la testa va prima nel punto giusto
            self._go(start, tr("Centro del cartone della calibrazione"))
            end = time.time() + 60
            while time.time() < end:
                QApplication.processEvents()
                h = self.head()
                if h is not None and math.hypot(h[0] - start[0], h[1] - start[1]) < 0.05 \
                        and self.ctl.last_status.get("state") == "Idle":
                    break
                time.sleep(0.02)
            if ask and QMessageBox.question(
                    self, tr("Calibrazione completa"),
                    tr("Ho spostato la testa in X {0:.0f}  Y {1:.0f} mm: da qui la camera riesce a fotografare tutta "
                       "la griglia.\n\nMetti il cartone (circa 15 × 10 cm) centrato sotto l'ugello, a fuoco. "
                       "Inizio?", start[0], start[1])) != QMessageBox.Yes:
                return None
        name = camera_mod.NAMES.get(self.index(), "") if self.index() is not None else ""
        old = self.model if self.ready() else None
        self.cal = hg.HeadGridCalibration(self.ctl, self.src, self.win.profile, power, name, self.index(), guess=guess,
                                          moves=moves, old_model=old, cal_thickness=cal_thickness)
        self.cal.progress.connect(self._cal_progress)
        self.cal.need_confirm.connect(self._cal_confirm)
        self.cal.need_click.connect(self._cal_need_click)
        self.cal.need_height.connect(self._cal_need_height)
        self.cal.need_choice.connect(self._cal_need_choice)
        self.cal.mark_seen.connect(self._cal_mark)
        self.cal.finished.connect(self._cal_finished)
        self.mark = None
        self.waiting_click = False
        self.update_state()
        self.cal.start()
        return self.cal

    def moves_answer(self):
        """Risposta salvata a «la camera sale e scende con il laser?»: True, False o None (non so)."""
        qs = getattr(self.win, "qs", None)
        v = str(qs.value("head_camera_moves", "yes") or "yes") if qs is not None else "yes"
        return {"yes": True, "no": False}.get(v)

    def _cal_need_height(self, text):
        """Camera che forse non sale con il laser: la persona solleva il cartone e scrive di quanto."""
        cal = self.cal
        dlg = HeightDialog(self.window or self, text)
        ok = dlg.exec() == QDialog.Accepted
        if cal is None:
            return
        cal.height_answer(dlg.mm.value() if ok else None)

    def _cal_need_choice(self, text):
        cal = self.cal
        ans = QMessageBox.question(self.window or self, tr("Calibrazione completa"), text,
                                   QMessageBox.Yes | QMessageBox.No)
        if cal is not None:
            cal.choose(ans == QMessageBox.Yes)

    # ---------------------------------------------------------------- 0.20.2: spessore, controllo, foto
    def thickness(self):
        qs = getattr(self.win, "qs", None)
        try:
            return float(qs.value("head_camera_thickness", 0.0)) if qs is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def set_thickness(self, mm):
        """Spessore del materiale (camere che non salgono con il laser): vale per tutti i comandi."""
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("head_camera_thickness", float(mm))
        if self.model is not None:
            got = self.model.set_thickness(float(mm) if self.model.moves_with_head is False else None)
            if got is not None and abs(got - float(mm)) > 1e-6:
                self._say(tr("Spessore fuori misura per questa camera: uso {0:.1f} mm", got))
        self.update_marker()
        return mm

    def check_calibration(self, dot=False, ask=True):
        """«Controlla la calibrazione» (10 s, laser spento); dot=True: anche con un puntino inciso su uno scarto."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        if dot and ask and QMessageBox.question(
                self.window or self, tr("Controlla con un puntino"),
                tr("Incido un puntino qui, dove è ora il laser, e lo guardo con la camera.\n\nSotto l'ugello c'è cartone o "
                   "legno da scarto, a fuoco? Occhiali indossati?")) != QMessageBox.Yes:
            return None
        self.check = hg.HeadCheckJob(self.ctl, self.src, self.win.profile, self.model, dot=dot)
        self.check.progress.connect(self._cal_progress)
        self.check.finished.connect(self._check_finished)
        self.update_state()
        self.check.start()
        return self.check

    def _check_finished(self, res, msg):
        self.check = None
        self.last_check = res
        self._say(msg, 15000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    def align_bed_photo(self):
        """Parte 2: la foto della camera del piano allineata con la camera della testa (laser spento)."""
        why = self._can_move() or self.panel.can_align()
        if why:
            return self._say(why) and None
        park = (self.panel.saved or {}).get("park")
        park = tuple(float(v) for v in park) if isinstance(park, (list, tuple)) and len(park) == 2 else None
        self.align_job = hg.BedAlignJob(self.ctl, self.src, self.win.profile, self.model, self.panel.src,
                                        self.panel.model, park)
        self.job = self.align_job  # occupa la testa come la foto a mosaico
        self.align_job.progress.connect(self._cal_progress)
        self.align_job.finished.connect(self._align_finished)
        self.update_state()
        self.align_job.start()
        return self.align_job

    def _align_finished(self, corr, msg):
        self.job = None
        if corr is not None:
            self.panel.set_align(corr)
        self._say(msg, 15000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    def has_mosaic(self):
        return getattr(self.panel, "mosaic", None) is not None

    def clear_mosaic(self):
        """Leone (15/11): la foto a mosaico si toglie dal piano quando non serve più."""
        if hasattr(self.panel, "clear_mosaic"):
            self.panel.clear_mosaic()
        self._say(tr("Foto a mosaico tolta dal piano"))
        self.update_state()

    def cancel(self):
        if self.cal is not None:
            self.cal.cancel()
        if self.job is not None:
            self.job.cancel()
        if self.check is not None:
            self.check.cancel()

    def _cal_progress(self, i, total, text):
        if self.window is not None:
            self.window.progress(i, total, text)

    def _cal_need_click(self, text):
        self.waiting_click = True
        self._say(text, 60000)
        if self.window is not None:
            self.window.ask_click(text)

    def _cal_mark(self, p):
        self.mark = tuple(p)

    def _cal_confirm(self, p):
        """Il puntino trovato da solo: la persona lo guarda cerchiato nel video e dice se è lui."""
        self.mark = tuple(p)
        if self.window is not None:
            self.window.tick()
        cal = self.cal
        ans = QMessageBox.question(
            self.window or self, tr("Camera della testa"),
            tr("Guarda il video della camera della testa: il cerchio verde è sul puntino appena inciso?\n\n"
               "Sì: continuo da solo.\nNo: sposti tu la testa con le frecce (scheda Movimento) finché vedi il "
               "puntino, poi ci fai clic sopra nel video."),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if cal is None:
            return
        if ans == QMessageBox.Cancel:
            cal.cancel()
        else:
            cal.confirm(ans == QMessageBox.Yes)

    def click_on_video(self, u, v):
        """Clic sul video: durante la calibrazione è il puntino; altrimenti il centro camera va lì."""
        if self.cal is not None and self.waiting_click:
            self.waiting_click = False
            self.cal.click(u, v)
            return "mark"
        if self.busy():
            return None
        self.camera_to_pixel(u, v)
        return "move"

    def _cal_finished(self, model, msg):
        self.cal = None
        self.waiting_click = False
        if model is not None:
            model.set_thickness(self.thickness() if model.moves_with_head is False else None)
            model.save()
            self.model, self.model_ok, self.model_why = model, True, ""
        self.last_msg = ""
        self._say(msg.split("\n")[0], 12000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    # ---------------------------------------------------------------- foto del piano a mosaico (fase 3)
    def mosaic_zone(self, which):
        """Zona da fotografare: "bed" tutto il piano, "selection" attorno alla selezione (+10 mm), "board" la tavola
        presa con i due angoli. -> (x0, y0, x1, y1) o None."""
        p = self.win.profile
        if which == "selection":
            ed = self.win.editor
            if not ed.selection:
                return None
            b = ed.selection_bounds()
            z = (b.left() - 10, b.top() - 10, b.right() + 10, b.bottom() + 10)
        elif which == "board":
            if self.board[0] is None or self.board[1] is None:
                return None
            xs = [self.board[0][0], self.board[1][0]]
            ys = [self.board[0][1], self.board[1][1]]
            d = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
            z = (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + max(10.0, d * 0.6))
        else:
            z = (0.0, 0.0, float(p.bed_x), float(p.bed_y))
        z = (max(0.0, z[0]), max(0.0, z[1]), min(float(p.bed_x), z[2]), min(float(p.bed_y), z[3]))
        return z if z[2] - z[0] > 1 and z[3] - z[1] > 1 else None

    def take_mosaic(self, which="bed"):
        why = self._can_move()
        if why:
            return self._say(why) and None
        zone = self.mosaic_zone(which)
        if zone is None:
            return self._say(tr("Niente da fotografare: seleziona un disegno o prendi gli angoli della tavola")) and None
        self.job = hc.HeadMosaicJob(self.ctl, self.src, self.win.profile, self.model, zone)
        self._mosaic_ppm = self.job.ppm
        self.job.progress.connect(self._cal_progress)
        self.job.finished.connect(self._mosaic_finished)
        self.update_state()
        self.job.start()
        return self.job

    def _mosaic_finished(self, img, msg):
        self.job = None
        if img is not None:
            self.panel.show_mosaic(img, self._mosaic_ppm)
        self._say(msg, 12000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    # ---------------------------------------------------------------- finestra
    def open_window(self, calibrate=False):
        if self.src is None:
            # 0.20.3: prima qui non succedeva niente (e il pulsante era spento): ora dice che cosa fare
            n = self.combo.count() - 1
            self._say(tr("Scegli prima qui sopra quale telecamera è quella della testa.") if n > 0 else
                      tr("Nessuna telecamera trovata: collegala alla USB e premi ⟳, poi sceglila qui sopra."), 10000)
            return None
        if self.window is None:
            self.window = HeadCameraWindow(self)
        self.window.show()
        self.window.raise_()
        self.window.update_state()
        if calibrate:
            self.window.start_calibration()
        return self.window

    def shutdown(self):
        self.cancel()
        if self.window is not None:
            self.window.close()
        self.close_src()


# ======================================================================= dove è la camera
class WherePad(QWidget):
    """Dove è montata la camera rispetto al laser, come si vedono sul piano dello schermo: una croce di frecce (al
    centro «non lo so») e la distanza in cm. Ne viene lo scostamento indicativo da cui parte la ricerca del puntino."""

    changed = Signal()
    OPPOSITE = {"r": "l", "l": "r", "u": "d", "d": "u", "ur": "dl", "dl": "ur", "ul": "dr", "dr": "ul"}

    def __init__(self, qs=None):
        super().__init__()
        from .app import muted

        self.qs = qs
        self.direction = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(muted(tr("Dove hai montato la camera rispetto al laser? Guarda il piano sullo schermo e scegli "
                               "la freccia dalla parte della camera (al centro: non lo so).")))
        row = QHBoxLayout()
        pad = QGridLayout()
        pad.setSpacing(2)
        self.buttons = {}
        arrows = {"ul": "↖", "u": "↑", "ur": "↗", "l": "←", "": "●", "r": "→", "dl": "↙", "d": "↓", "dr": "↘"}
        self.names = {"ul": tr("in alto a sinistra"), "u": tr("in alto"), "ur": tr("in alto a destra"),
                      "l": tr("a sinistra"), "": tr("non lo so"), "r": tr("a destra"), "dl": tr("in basso a sinistra"),
                      "d": tr("in basso"), "dr": tr("in basso a destra")}
        for k, (r_, c_) in {"ul": (0, 0), "u": (0, 1), "ur": (0, 2), "l": (1, 0), "": (1, 1), "r": (1, 2),
                            "dl": (2, 0), "d": (2, 1), "dr": (2, 2)}.items():
            b_ = QPushButton(arrows[k])
            b_.setCheckable(True)
            b_.setFixedSize(34, 30)
            b_.setToolTip(tr("La camera è {0} rispetto al laser, come li vedi sul piano dello schermo", self.names[k])
                          if k else tr("Non so dov'è la camera"))
            b_.clicked.connect(lambda _=False, k=k: self.set_direction(k))
            pad.addWidget(b_, r_, c_)
            self.buttons[k] = b_
        row.addLayout(pad)
        col = QVBoxLayout()
        drow = QHBoxLayout()
        drow.addWidget(muted(tr("a circa")))
        self.cm = QDoubleSpinBox()
        self.cm.setRange(0.0, 25.0)
        self.cm.setDecimals(1)
        self.cm.setSingleStep(0.5)
        self.cm.setSuffix(" cm")
        self.cm.setValue(6.0)
        self.cm.valueChanged.connect(lambda *_: self._update())
        drow.addWidget(self.cm)
        drow.addStretch(1)
        col.addLayout(drow)
        self.text = muted("")
        col.addWidget(self.text)
        row.addLayout(col, 1)
        lay.addLayout(row)
        try:
            d_, cm_ = str(qs.value("head_camera_where", "") or "").split(";")
            if d_ in hc.DIRECTIONS:
                self.cm.setValue(float(cm_))
                self.direction = d_
        except (ValueError, AttributeError):
            pass
        self.set_direction(self.direction, save=False)

    def set_direction(self, k, save=True):
        self.direction = k if k in hc.DIRECTIONS else ""
        for key, b_ in self.buttons.items():
            b_.setChecked(key == self.direction)
        self.cm.setEnabled(bool(self.direction))
        self._update(save)

    def _update(self, save=True):
        if not self.direction:
            self.text.setText(tr("Non lo sai: il puntino lo cerco tutto intorno, partendo dal laser."))
        else:
            self.text.setText(tr("La camera è {0} rispetto al laser, a circa {1:g} cm: il puntino che incide il laser "
                                 "starà {2} rispetto alla camera, e lo cerco lì.", self.names[self.direction],
                                 self.cm.value(), self.names[self.OPPOSITE[self.direction]]))
        if save and self.qs is not None:
            self.qs.setValue("head_camera_where", f"{self.direction};{self.cm.value():g}" if self.direction else "")
        self.changed.emit()

    def guess(self):
        """Scostamento indicativo laser → centro camera (mm), o None se non si sa."""
        return hc.guess_from_direction(self.direction, self.cm.value())


class HeadCalDialog(QDialog):
    """Prima della calibrazione completa: dove è la camera, se sale e scende con il laser, potenza del puntino di prova
    e dove si mette il cartone (un punto da cui la camera potrà fotografare tutta la griglia)."""

    def __init__(self, card_, power=hc.DEFAULT_POWER):
        super().__init__(card_.window or card_.win)
        from .app import muted

        self.card = card_
        self.setWindowTitle(tr("Calibrazione completa della camera della testa"))
        lay = QVBoxLayout(self)
        qs = getattr(card_.win, "qs", None)
        self.pad = WherePad(qs)
        lay.addWidget(self.pad)
        # 0.20.2 (revisione A1): la sola domanda nuova; il resto si misura
        lay.addWidget(muted(tr("La camera sale e scende con il laser quando lo metti a fuoco?")))
        mrow = QHBoxLayout()
        self.moves_btns = {}
        for key, txt, tip in (("yes", tr("Sì"), tr("È fissata al modulo del laser (come un supporto sulla testa): la "
                                                    "distanza dal materiale resta sempre quella del fuoco")),
                              ("no", tr("No"), tr("È fissata al carrello o al telaio: con materiali più alti li vede "
                                                  "più da vicino. Alla fine ti chiedo di sollevare il cartone di uno "
                                                  "spessore noto")),
                              ("unknown", tr("Non so"), tr("Lo misuro io: alla fine ti chiedo di sollevare il cartone "
                                                           "di uno spessore noto e di rimettere a fuoco"))):
            b_ = QPushButton(txt)
            b_.setCheckable(True)
            b_.setToolTip(tip)
            b_.clicked.connect(lambda _=False, k=key: self.set_moves(k))
            mrow.addWidget(b_)
            self.moves_btns[key] = b_
        mrow.addStretch(1)
        lay.addLayout(mrow)
        self.card_row = QWidget()
        crl = QHBoxLayout(self.card_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.addWidget(muted(tr("Spessore del cartone della calibrazione")))
        self.card_mm = QDoubleSpinBox()
        self.card_mm.setRange(0.0, 30.0)
        self.card_mm.setDecimals(1)
        self.card_mm.setSuffix(" mm")
        try:
            self.card_mm.setValue(float(qs.value("head_camera_card_mm", 3.0)) if qs is not None else 3.0)
        except (TypeError, ValueError):
            self.card_mm.setValue(3.0)
        crl.addWidget(self.card_mm)
        crl.addStretch(1)
        lay.addWidget(self.card_row)
        prow = QHBoxLayout()
        prow.addWidget(muted(tr("Potenza del puntino di prova")))
        self.power = QDoubleSpinBox()
        self.power.setRange(1.0, 100.0)
        self.power.setDecimals(0)
        self.power.setSuffix(" %")
        self.power.setValue(float(power))
        self.power.setToolTip(tr("Se il puntino si vede poco ne incido un altro più forte (al massimo il triplo, mai "
                                 "oltre l'80%); se si allarga troppo la griglia si incide più delicata"))
        prow.addWidget(self.power)
        prow.addStretch(1)
        lay.addLayout(prow)
        self.where = QLabel()
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        if card_.win.profile.rot():
            lay.addWidget(muted(tr("Il piano è mostrato ruotato: per le frecce guarda lo schermo, non la macchina.")))
        note = tr("Serve una sola cosa: un cartone (o compensato sottile) chiaro e piatto di circa 15 × 10 cm, centrato "
                  "sotto l'ugello e a fuoco. FreeLaserCut incide un puntino di prova, controlla la luce e che il cartone "
                  "copra la zona, poi incide una griglia di puntini (1–2 minuti) e la fotografa in più punti "
                  "dell'immagine. In tutto 3–5 minuti; alla fine dice quanto è precisa.\n•  occhiali protettivi per "
                  "450 nm indossati, aspirazione accesa\n•  una luce sopra il piano (con il coperchio chiuso la "
                  "camera vede poco)")
        if getattr(card_.src, "autofocus", "") == "on":
            note += "\n" + tr("•  questa camera ha la messa a fuoco automatica e non si lascia spegnere: la "
                              "calibrazione controlla che l'immagine resti ferma")
        lay.addWidget(muted(note))
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(tr("Inizia"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.pad.changed.connect(self._update)
        v = card_.moves_answer()
        self.set_moves({True: "yes", False: "no", None: "unknown"}[v])
        self._update()

    def set_moves(self, key):
        self._moves = key if key in self.moves_btns else "yes"
        for k, b_ in self.moves_btns.items():
            b_.setChecked(k == self._moves)
        self.card_row.setVisible(self._moves != "yes")

    def moves(self):
        return {"yes": True, "no": False}.get(self._moves)

    def start(self):
        p = self.card.win.profile
        return hc.calibration_start(self.card.head(), self.pad.guess(), (p.bed_x, p.bed_y),
                                    margin=hc.START_MARGIN + 60)

    def _update(self):
        start, why = self.start()
        head = self.card.head()
        ok = start is not None
        if not ok:
            self.where.setText(tr("Calibrazione impossibile: {0}", why))
            self.where.setStyleSheet(f"color:{C['danger']};")
        elif head is not None and math.hypot(start[0] - head[0], start[1] - head[1]) > 0.5:
            self.where.setText(tr("Il cartone va in X {0:.0f}  Y {1:.0f} mm: da dove è ora la testa la camera non "
                                  "riuscirebbe a fotografare tutta la griglia, quindi la testa ci va prima (poi metti lì "
                                  "il cartone).", start[0], start[1]))
            self.where.setStyleSheet(f"color:{C['warn']};")
        else:
            self.where.setText(tr("Il cartone va qui, centrato sotto l'ugello (X {0:.0f}  Y {1:.0f} mm).", *start))
            self.where.setStyleSheet("")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)


class HeightDialog(QDialog):
    """Seconda altezza (camere che forse non salgono con il laser): di quanto è stato sollevato il cartone."""

    def __init__(self, parent, text):
        super().__init__(parent)
        from .app import muted

        self.setWindowTitle(tr("Calibrazione completa"))
        lay = QVBoxLayout(self)
        lay.addWidget(muted(text))
        row = QHBoxLayout()
        row.addWidget(muted(tr("Cartone sollevato di")))
        self.mm = QDoubleSpinBox()
        self.mm.setRange(1.5, 30.0)
        self.mm.setDecimals(1)
        self.mm.setSingleStep(0.5)
        self.mm.setValue(4.0)
        self.mm.setSuffix(" mm")
        row.addWidget(self.mm)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Fatto, misura"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Salta"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ======================================================================= vista dal vivo
# 0.20.2 (richieste di Leone, 15/11): la vista si raddrizza da sola dopo la calibrazione (in alto = verso il fondo del
# piano, a destra = X+, come sul piano e come le frecce), si può capovolgere o ruotare a mano e si ingrandisce con la
# rotella. Tutti i conti (clic, disegno sovrapposto, mirino, puntino) passano da to_img / at, una sola trasformazione.
DIHEDRAL = [np.array(m, float) for m in ([[1, 0], [0, 1]], [[0, -1], [1, 0]], [[-1, 0], [0, -1]], [[0, 1], [-1, 0]],
                                         [[-1, 0], [0, 1]], [[1, 0], [0, -1]], [[0, 1], [1, 0]], [[0, -1], [-1, 0]])]


def auto_orientation(M):
    """La rotazione di 90° in 90° (con specchio se serve) che porta l'immagine come il piano visto dall'alto:
    a destra X+, in alto Y+. M: mm sul piano per pixel dell'immagine (colonne = +u, +v). -> matrice 2×2 intera."""
    best, score = DIHEDRAL[0], -1e9
    for D in DIHEDRAL:
        J = np.asarray(M, float) @ np.linalg.inv(D)
        a = J[:, 0] / max(np.hypot(*J[:, 0]), 1e-12)
        b = J[:, 1] / max(np.hypot(*J[:, 1]), 1e-12)
        s = a[0] - b[1]
        if s > score + 1e-9:
            best, score = D, s
    return best


class HeadView(QWidget):
    clicked = Signal(float, float)  # pixel dell'immagine (vera, non girata)

    ZOOM_MAX = 12.0

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 270)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(False)
        self.frame = None
        self.img = None
        self.model = None
        self.head = None
        self.marks = []
        self.board = []
        self.shapes = []  # [[(u, v), ...], ...] disegno sovrapposto, già in pixel dell'immagine vera
        self.ask = False
        self.auto = True  # raddrizza da sola (serve la calibrazione)
        self.manual = np.eye(2)  # capovolgi / ruota a mano, dopo quella automatica
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._drag = None
        self._press = None

    # ---- orientamento
    def orientation(self):
        D = np.eye(2)
        if self.auto and self.model is not None:
            D = auto_orientation(self.model.M)
        return self.manual @ D

    def flip(self, which):
        """"h" capovolge in orizzontale, "v" in verticale, "r" ruota di 90° in senso orario (sullo schermo)."""
        F = {"h": np.array([[-1, 0], [0, 1]], float), "v": np.array([[1, 0], [0, -1]], float),
             "r": np.array([[0, -1], [1, 0]], float)}[which]
        self.manual = F @ self.manual
        self.update()

    def set_manual(self, text):
        try:
            v = [float(x) for x in str(text).split(",")]
            M = np.array(v, float).reshape(2, 2)
            if any(np.allclose(M, D) for D in DIHEDRAL):
                self.manual = M
        except (ValueError, TypeError):
            pass

    def manual_text(self):
        return ",".join(f"{v:g}" for v in self.manual.ravel())

    # ---- geometria della vista
    def set_frame(self, frame):
        self.frame = frame
        self.img = to_qimage(frame) if frame is not None else None
        self.update()

    def _geom(self):
        """(centro dell'immagine sullo schermo, pixel di schermo per pixel d'immagine, D) o None."""
        if self.img is None:
            return None
        D = self.orientation()
        w, h = self.img.width(), self.img.height()
        dw, dh = abs(D[0, 0] * w + D[0, 1] * h), abs(D[1, 0] * w + D[1, 1] * h)
        k = min(self.width() / max(dw, 1), self.height() / max(dh, 1)) * self.zoom
        ctr = QPointF(self.width() / 2, self.height() / 2) + self.pan
        return ctr, k, D

    def _rect(self):
        g = self._geom()
        if g is None:
            return QRectF()
        ctr, k, D = g
        w, h = self.img.width(), self.img.height()
        dw, dh = abs(D[0, 0] * w + D[0, 1] * h) * k, abs(D[1, 0] * w + D[1, 1] * h) * k
        return QRectF(ctr.x() - dw / 2, ctr.y() - dh / 2, dw, dh)

    def at(self, u, v):
        """Pixel dell'immagine → punto dello schermo."""
        ctr, k, D = self._geom()
        d = D @ np.array([u - self.img.width() / 2, v - self.img.height() / 2])
        return QPointF(ctr.x() + d[0] * k, ctr.y() + d[1] * k)

    def to_img(self, pos):
        """Punto dello schermo → pixel dell'immagine vera (None fuori dall'immagine)."""
        g = self._geom()
        if g is None:
            return None
        ctr, k, D = g
        d = np.linalg.inv(D) @ np.array([(pos.x() - ctr.x()) / k, (pos.y() - ctr.y()) / k])
        u, v = d[0] + self.img.width() / 2, d[1] + self.img.height() / 2
        if not (0 <= u <= self.img.width() and 0 <= v <= self.img.height()):
            return None
        return (float(u), float(v))

    def fit(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()

    # ---- mouse
    def wheelEvent(self, e):
        if self.img is None:
            return
        steps = e.angleDelta().y() / 120.0
        old = self.zoom
        self.zoom = float(min(max(self.zoom * 1.18 ** steps, 1.0), self.ZOOM_MAX))
        if self.zoom == 1.0:
            self.pan = QPointF(0, 0)
        else:  # il punto sotto il cursore resta fermo
            pos = e.position()
            ctr = QPointF(self.width() / 2, self.height() / 2) + self.pan
            r = self.zoom / old
            new_ctr = pos - (pos - ctr) * r
            self.pan = new_ctr - QPointF(self.width() / 2, self.height() / 2)
        self.update()

    def mousePressEvent(self, e):
        if e.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag = (e.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton:
            self._press = e.position()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            start, pan0 = self._drag
            self.pan = pan0 + (e.position() - start)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None and e.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag = None
            self.setCursor(Qt.CrossCursor)
            return
        if e.button() == Qt.LeftButton and self._press is not None:
            moved = (e.position() - self._press).manhattanLength()
            self._press = None
            p = self.to_img(e.position())
            if p is not None and moved <= 6:
                self.clicked.emit(float(p[0]), float(p[1]))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.fit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#080D18"))
        if self.img is None:
            p.setPen(QColor(C["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Nessuna immagine dalla camera della testa"))
            return
        ctr, k, D = self._geom()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.save()
        p.translate(ctr)
        p.scale(k, k)
        p.setTransform(QTransform(D[0, 0], D[1, 0], D[0, 1], D[1, 1], 0, 0) * p.transform())
        p.drawImage(QPointF(-self.img.width() / 2, -self.img.height() / 2), self.img)
        p.restore()
        p.setRenderHint(QPainter.Antialiasing)
        at = self.at

        # disegno sovrapposto
        if self.shapes:
            p.setPen(QPen(QColor(255, 120, 60, 220), 1.4))
            for poly in self.shapes:
                for a, b in zip(poly, poly[1:]):
                    if all(math.isfinite(v) for v in (*a, *b)):  # NaN = fuori da quello che la lente può vedere
                        p.drawLine(at(*a), at(*b))
        # tavola
        if self.board:
            p.setPen(QPen(QColor(BOARD_COLOR), 2))
            for (u, v), name in self.board:
                if not (math.isfinite(u) and math.isfinite(v)):
                    continue
                p.drawEllipse(at(u, v), 7, 7)
                p.drawText(at(u, v) + QPointF(9, -9), name)
        for u, v in self.marks:
            p.setPen(QPen(QColor(60, 220, 60), 2))
            p.drawEllipse(at(u, v), 10, 10)
        # mirino: al centro dell'immagine vera
        c0 = at(self.img.width() / 2, self.img.height() / 2)
        cx, cy = c0.x(), c0.y()
        col = QColor(CAM_COLOR)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawLine(QPointF(cx + dx * 8, cy + dy * 8), QPointF(cx + dx * 40, cy + dy * 40))
        p.setPen(QPen(col, 1.5))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawLine(QPointF(cx + dx * 8, cy + dy * 8), QPointF(cx + dx * 40, cy + dy * 40))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        # righello: 10 mm (o 5 / 2 / 1 mm se la vista è piccola), con lo zoom
        if self.model is not None:
            mmpx = self.model.mm_per_px()
            for mm in (10.0, 5.0, 2.0, 1.0, 0.5):
                if mm / mmpx * k < self.width() * 0.3:
                    break
            L = mm / mmpx * k
            x0, y0 = 16, self.height() - 18
            p.setPen(QPen(QColor(0, 0, 0, 170), 5))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + L, y0))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + L, y0))
            for t_ in (0.0, L):
                p.drawLine(QPointF(x0 + t_, y0 - 5), QPointF(x0 + t_, y0 + 5))
            p.drawText(QPointF(x0 + L + 8, y0 + 5), f"{mm:g} mm")
        if self.zoom > 1.001:
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(0, 6, self.width() - 10, 20), Qt.AlignRight,
                       tr("zoom ×{0:.1f} · doppio clic: tutta l'immagine", self.zoom))
        if self.ask:
            p.setPen(QColor(C["warn"]))
            p.drawText(QRectF(0, 6, self.width(), 22), Qt.AlignHCenter, tr("Fai clic sul puntino inciso"))


class HeadCameraWindow(QDialog):
    def __init__(self, card_):
        super().__init__(card_.win)
        from .app import card, muted

        self.card = card_
        self.setWindowTitle(tr("Camera della testa"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(820, 760)
        lay = QVBoxLayout(self)
        self.view = HeadView()
        self.view.clicked.connect(self._clicked)
        qs = getattr(card_.win, "qs", None)
        if qs is not None:
            self.view.auto = str(qs.value("head_view_auto", "1")) != "0"
            self.view.set_manual(qs.value("head_view_manual", ""))
        lay.addWidget(self.view, 1)
        # 0.20.2: orientamento della vista (discreto, sotto il video)
        vr = QHBoxLayout()
        vr.setSpacing(4)
        self.chk_upright = QCheckBox(tr("Raddrizza da sola"))
        self.chk_upright.setChecked(self.view.auto)
        self.chk_upright.setToolTip(tr("Dopo la calibrazione la vista si gira come il piano sullo schermo: in alto il "
                                       "fondo della macchina, a destra X+. Così le frecce muovono la testa nel verso "
                                       "che vedi."))
        self.chk_upright.toggled.connect(self._set_upright)
        vr.addWidget(self.chk_upright)
        self.view_btns = {}
        for key, txt, tip in (("h", "↔", tr("Capovolgi in orizzontale")), ("v", "↕", tr("Capovolgi in verticale")),
                              ("r", "⟳", tr("Ruota di 90°"))):
            b_ = QPushButton(txt)
            b_.setFixedWidth(34)
            b_.setToolTip(tip)
            b_.clicked.connect(lambda _=False, k=key: self._flip(k))
            vr.addWidget(b_)
            self.view_btns[key] = b_
        b_fit = QPushButton(tr("Adatta"))
        b_fit.setToolTip(tr("Tutta l'immagine (anche con un doppio clic sul video). La rotella ingrandisce, il tasto "
                            "centrale o destro trascinato sposta la vista."))
        b_fit.clicked.connect(self.view.fit)
        vr.addWidget(b_fit)
        vr.addStretch(1)
        lay.addLayout(vr)
        self.info = muted("")
        lay.addWidget(self.info)

        # comandi della testa
        mc, ml = card(tr("Laser e camera"))
        g = QGridLayout()
        self.b_laser = QPushButton(tr("Laser sul centro camera"))
        self.b_laser.setToolTip(tr("Il laser va dove ora c'è il mirino della camera"))
        self.b_laser.clicked.connect(card_.laser_to_camera)
        self.b_cam = QPushButton(tr("Camera sul punto del laser"))
        self.b_cam.setToolTip(tr("La testa si sposta perché il mirino guardi il punto dove ora c'è il laser"))
        self.b_cam.clicked.connect(card_.camera_to_laser)
        self.b_origin = QPushButton(tr("Origine qui (centro camera)"))
        self.b_origin.setToolTip(tr("Il punto sotto il mirino diventa l'origine utente (X0 Y0): per riprendere un "
                                    "lavoro dallo stesso punto"))
        self.b_origin.clicked.connect(card_.origin_from_camera)
        self.chk_design = QCheckBox(tr("Mostra il disegno sul video"))
        self.chk_design.setChecked(True)
        g.addWidget(self.b_laser, 0, 0)
        g.addWidget(self.b_cam, 0, 1)
        g.addWidget(self.b_origin, 0, 2)
        g.addWidget(self.chk_design, 1, 0, 1, 3)
        ml.addLayout(g)
        ml.addWidget(muted(tr("Un clic sul video porta lì il centro della camera. Sul piano il quadratino verde acqua "
                              "è il punto sotto il mirino.")))
        lay.addWidget(mc)

        # calibrazione
        kc, kl = card(tr("Calibrazione"))
        row = QHBoxLayout()
        self.b_cal = QPushButton(tr("◎  Calibrazione completa…"))
        self.b_cal.setObjectName("primary")
        self.b_cal.setToolTip(tr("Una volta per tutte: incide una griglia di puntini su un cartone di circa 15 × 10 cm "
                                 "e misura lente, inclinazione, scala e distanza fra laser e camera"))
        self.b_cal.clicked.connect(self.start_calibration)
        self.b_check = QPushButton(tr("Controlla"))
        self.b_check.setToolTip(tr("In 10 secondi, a laser spento: la testa si sposta di misure note e l'immagine deve "
                                   "spostarsi come previsto (camera urtata, supporto allentato?)"))
        self.b_check.clicked.connect(lambda: card_.check_calibration())
        self.b_check_dot = QPushButton(tr("Con un puntino"))
        self.b_check_dot.setToolTip(tr("Controlla anche la distanza fra laser e camera: incide un puntino su uno scarto e "
                                       "guarda se la camera lo vede dove se lo aspetta (circa 20 secondi)"))
        self.b_check_dot.clicked.connect(lambda: card_.check_calibration(dot=True))
        self.b_stop = QPushButton(tr("Annulla"))
        self.b_stop.setObjectName("danger")
        self.b_stop.clicked.connect(card_.cancel)
        self.b_stop.hide()
        row.addWidget(self.b_cal, 1)
        row.addWidget(self.b_check)
        row.addWidget(self.b_check_dot)
        row.addWidget(self.b_stop)
        kl.addLayout(row)
        # 0.20.2: spessore del materiale, solo per le camere che non salgono e scendono con il laser
        self.th_row = QWidget()
        thl = QHBoxLayout(self.th_row)
        thl.setContentsMargins(0, 0, 0, 0)
        thl.addWidget(muted(tr("Spessore del materiale")))
        self.thick = QDoubleSpinBox()
        self.thick.setRange(0.0, 80.0)
        self.thick.setDecimals(1)
        self.thick.setSingleStep(0.5)
        self.thick.setSuffix(" mm")
        self.thick.setToolTip(tr("La camera non sale e scende con il laser: con un materiale più alto vede il piano più "
                                 "da vicino. Scrivi lo spessore e FreeLaserCut corregge le posizioni."))
        self.thick.setValue(card_.thickness())
        self.thick.valueChanged.connect(card_.set_thickness)
        thl.addWidget(self.thick)
        thl.addStretch(1)
        kl.addWidget(self.th_row)
        self.bar = QProgressBar()
        self.bar.hide()
        kl.addWidget(self.bar)
        self.cal_text = muted("")
        kl.addWidget(self.cal_text)
        lay.addWidget(kc)

        # tavola (fase 2)
        tc, tl = card(tr("Tavola da due angoli"))
        tl.addWidget(muted(tr("Porta il mirino su un angolo della tavola (A), poi su un altro angolo dello stesso lato "
                              "(B): FreeLaserCut sa dov'è e quanto è storta, e ci appoggia il disegno.")))
        r2 = QHBoxLayout()
        self.b_a = QPushButton(tr("Angolo A qui"))
        self.b_a.clicked.connect(lambda: card_.take_corner(0, self.chk_auto.isChecked()))
        self.b_b = QPushButton(tr("Angolo B qui"))
        self.b_b.clicked.connect(lambda: card_.take_corner(1, self.chk_auto.isChecked()))
        self.chk_auto = QCheckBox(tr("Cerca l'angolo vicino al mirino"))
        self.chk_auto.setChecked(True)
        self.chk_auto.setToolTip(tr("FreeLaserCut cerca nell'immagine i due bordi della tavola e prende il punto in cui "
                                    "si incontrano; se non li trova usa il mirino"))
        r2.addWidget(self.b_a)
        r2.addWidget(self.b_b)
        r2.addWidget(self.chk_auto, 1)
        tl.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(muted(tr("Margine")))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 200.0)
        self.margin.setDecimals(1)
        self.margin.setSuffix(" mm")
        self.margin.setValue(5.0)
        r3.addWidget(self.margin)
        self.b_align = QPushButton(tr("Appoggia la selezione sulla tavola"))
        self.b_align.clicked.connect(lambda: card_.align_selection(self.margin.value()))
        self.b_clear = QPushButton(tr("Togli la tavola"))
        self.b_clear.clicked.connect(card_.clear_board)
        r3.addWidget(self.b_align, 1)
        r3.addWidget(self.b_clear)
        tl.addLayout(r3)
        self.board_text = muted("")
        tl.addWidget(self.board_text)
        lay.addWidget(tc)

        # foto a mosaico (fase 3)
        pc, pl = card(tr("Foto del piano con la camera della testa"))
        r4 = QHBoxLayout()
        self.zone = QComboBox()
        self.zone.addItem(tr("Tutto il piano"), "bed")
        self.zone.addItem(tr("Attorno alla selezione"), "selection")
        self.zone.addItem(tr("La tavola"), "board")
        r4.addWidget(self.zone, 1)
        self.b_mosaic = QPushButton(tr("Fai la foto a mosaico"))
        self.b_mosaic.setToolTip(tr("La testa passa sopra la zona a laser spento e la camera fa una foto in ogni punto: "
                                    "le foto, unite, vanno sotto il piano in scala 1:1"))
        self.b_mosaic.clicked.connect(lambda: card_.take_mosaic(self.zone.currentData()))
        r4.addWidget(self.b_mosaic)
        self.b_unmosaic = QPushButton(tr("Togli la foto dal piano"))
        self.b_unmosaic.setToolTip(tr("Toglie da sotto il piano la foto a mosaico (si può rifare quando vuoi)"))
        self.b_unmosaic.clicked.connect(card_.clear_mosaic)
        r4.addWidget(self.b_unmosaic)
        pl.addLayout(r4)
        self.b_align_bed = QPushButton(tr("Allinea la foto della camera del piano"))
        self.b_align_bed.setToolTip(tr("Con il materiale sul piano: la camera della testa guarda alcuni punti e corregge "
                                       "la foto della camera in alto (lente, spessore del materiale, coperchio "
                                       "spostato). Circa 30 secondi, laser spento."))
        self.b_align_bed.clicked.connect(card_.align_bed_photo)
        pl.addWidget(self.b_align_bed)
        lay.addWidget(pc)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(120)
        self.update_state()

    # ---- stato
    def update_state(self):
        cd = self.card
        busy = cd.busy()
        ok = cd.ready() and cd.ctl.connected and not busy
        for b in (self.b_laser, self.b_cam, self.b_origin, self.b_a, self.b_b, self.b_mosaic, self.b_check,
                  self.b_check_dot):
            b.setEnabled(ok)
        self.b_unmosaic.setEnabled(cd.has_mosaic())
        self.b_align_bed.setVisible(cd.panel.can_align() is None)
        self.b_align_bed.setEnabled(ok)
        self.th_row.setVisible(cd.model is not None and cd.model.moves_with_head is False)
        self.b_align.setEnabled(cd.board_angle() is not None and not busy)
        self.b_clear.setEnabled(cd.board[0] is not None or cd.board[1] is not None)
        if not ok and not busy:  # 0.20.3: perché i comandi qui sopra sono spenti (prima non lo diceva)
            self.info.setText(tr("Connetti il laser per usare i comandi della camera della testa.")
                              if not cd.ctl.connected else
                              (cd.model_why or tr("Calibra la camera della testa per usare questi comandi.")
                               if not cd.ready() else self.info.text()))
        self.b_cal.setEnabled(not busy)  # 0.20.3: sempre possibile rifarla; se manca qualcosa lo dice
        self.b_cal.setText(tr("◎  Rifai la calibrazione completa…") if cd.model is not None
                           else tr("◎  Calibrazione completa…"))
        self.b_stop.setVisible(busy)
        if not busy:
            self.bar.hide()
            self.view.ask = False
        ang = cd.board_angle()
        parts = []
        for i, c in enumerate(cd.board):
            if c is not None:
                parts.append(tr("{0}: X {1:.1f} Y {2:.1f}", "AB"[i], c[0], c[1]))
        if ang is not None:
            parts.append(tr("lato A→B a {0:.2f}°", ang))
        self.board_text.setText("  ·  ".join(parts) if parts else tr("Nessun angolo preso"))
        if cd.model is None and not self.cal_text.text():
            self.cal_text.setText(tr("Non ancora calibrata."))
        elif cd.model is not None and not busy and not self.cal_text.text():
            self.cal_text.setText(cd.model.describe() + ("" if cd.model.method == "grid" else "\n" + tr(
                "Calibrata col puntino (versione 0.20.0): funziona, ma la calibrazione completa è più precisa ai bordi "
                "dell'immagine e nella foto a mosaico.")))

    def progress(self, i, total, text):
        self.bar.show()
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(i)
        self.cal_text.setText(text)
        self.update_state()

    def ask_click(self, text):
        self.view.ask = True
        self.cal_text.setText(text)
        self.view.update()

    def show_result(self, msg):
        self.view.ask = False
        self.cal_text.setText(msg)
        self.update_state()

    def start_calibration(self):
        return self.card.calibrate()

    def _set_upright(self, on):
        self.view.auto = bool(on)
        qs = getattr(self.card.win, "qs", None)
        if qs is not None:
            qs.setValue("head_view_auto", "1" if on else "0")
        self.view.update()

    def _flip(self, key):
        self.view.flip(key)
        qs = getattr(self.card.win, "qs", None)
        if qs is not None:
            qs.setValue("head_view_manual", self.view.manual_text())

    def _clicked(self, u, v):
        if self.card.click_on_video(u, v) == "mark":
            self.view.ask = False

    # ---- video
    def tick(self):
        cd = self.card
        if cd.src is None or not self.isVisible():
            return
        frame = cd.src.get(after=0, timeout=0.02)
        if frame is None:
            return
        head = cd.head()
        self.view.model = cd.model if cd.ready() else None
        self.view.marks = [cd.mark] if cd.mark is not None and cd.cal is not None else []
        self.view.board = []
        self.view.shapes = []
        if cd.ready() and head is not None:
            m = cd.model
            for i, c in enumerate(cd.board):
                if c is not None:
                    u, v = m.bed_to_img(head, [c])[0]
                    self.view.board.append(((u, v), "AB"[i]))
            if self.chk_design.isChecked():
                self.view.shapes = self._design(m, head)
            c = m.center(head)
            self.info.setText(tr("Centro camera: X {0:.2f}  Y {1:.2f} mm  ·  laser: X {2:.2f}  Y {3:.2f} mm",
                                 c[0], c[1], head[0], head[1]))
        self.view.set_frame(frame)

    def _design(self, m, head):
        """Il disegno (forme visibili vicino alla zona inquadrata) in pixel della camera."""
        doc = self.card.win.editor.doc
        vw, vh = m.view_mm()
        cx, cy = m.center(head)
        R = math.hypot(vw, vh) / 2 + 2
        out = []
        n = 0
        for s in doc.shapes:
            if getattr(s, "hidden", False):
                continue
            b = s.bounds()
            if b.right() < cx - R or b.left() > cx + R or b.bottom() < cy - R or b.top() > cy + R:
                continue
            for poly in s.path().toSubpathPolygons():
                pts = np.array([(q.x(), q.y()) for q in poly], float)
                if len(pts) < 2:
                    continue
                out.append([tuple(q) for q in m.bed_to_img(head, pts)])
                n += len(pts)
                if n > 20000:
                    return out
        return out

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)

    def showEvent(self, e):
        self.timer.start(120)
        super().showEvent(e)
