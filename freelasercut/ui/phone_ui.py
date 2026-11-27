# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Controllo dal telefono: accende la pagina per il telefono, mostra il codice QR e la mini guida."""
import io
import math
import time

import cv2
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import phone
from ..camera import PHONE_CAMERA, SIM_CAMERA
from ..i18n import tr
from ..theme import css


class PhoneControl(QObject):
    """Ponte fra il server (thread suo) e l'interfaccia: i comandi arrivano come segnali nel thread principale."""
    pause_requested = Signal()
    stop_requested = Signal()
    photo_received = Signal(bytes)
    plate_received = Signal(bytes)  # 0.19.0: la foto del piano di lavoro
    step_requested = Signal(float, float, float)  # 0.22.5: freccia dal telefono (dx, dy, passo in mm)
    joy_requested = Signal(float, float)  # 0.22.5: joystick dal telefono (x, y fra -1 e 1; 0, 0 = fermo)
    halt_requested = Signal()  # 0.22.5: «■» dal telefono: ferma la testa
    glow_requested = Signal(bool)  # 0.23.4: Lucciola accesa / spenta dal telefono
    changed = Signal()

    STEPS = (0.1, 1.0, 10.0, 50.0)
    JOY_TIMEOUT_MS = 600  # senza notizie dal telefono per più di così (rete persa, pagina chiusa) il joystick si ferma
    # 0.23.4: la pagina chiede lo stato ogni secondo. Se per più di così non arriva niente (pagina chiusa, rete persa,
    # schermo spento) la Lucciola accesa dal telefono si spegne
    GLOW_SILENCE_S = 2.5

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctl = win.ctl
        self.server = None
        self.snapshot = {"title": tr("Avvio…")}
        self.job_t0 = None
        self.ctl.job_progress.connect(self._progress)
        self.pause_requested.connect(self._do_pause)
        self.stop_requested.connect(self._do_stop)
        self.photo_received.connect(self._do_photo)
        self.plate_received.connect(self._do_plate)
        self.step_requested.connect(self._do_step)
        self.joy_requested.connect(self._do_joy)
        self.halt_requested.connect(lambda: self._do_halt(cancel=True))
        self.glow_requested.connect(self._do_glow)
        self._glow_perm = False  # 0.23.4: «Lucciola dal telefono»: spenta di partenza e mai ricordata (solo la sessione)
        self.glow_watch = QTimer(self)
        self.glow_watch.setInterval(250)
        self.glow_watch.timeout.connect(self._glow_watchdog)
        self.joy = None  # JoyJog tutto suo (creato alla prima richiesta)
        self._plan = None  # frecce: (x, y, fine prevista) dell'ultimo spostamento mandato, finché la testa non è ferma
        self._hold_until = 0.0  # dopo «■» la posizione letta è vecchia per un attimo: le frecce aspettano
        self.joy_watch = QTimer(self)
        self.joy_watch.setSingleShot(True)
        self.joy_watch.setInterval(self.JOY_TIMEOUT_MS)
        self.joy_watch.timeout.connect(lambda: self._do_halt(tr("Joystick fermato: il telefono non risponde")))
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)

    # ---------------------------------------------------------------- acceso / spento
    @property
    def running(self):
        return self.server is not None and self.server.running

    def start(self):
        if self.running:
            return True
        self.server = phone.PhoneServer(lambda: self.snapshot, self._frame, self._pause, self._stop, self._photo,
                                        token=self.server.token if self.server else None, plate=self._plate,
                                        move=self._move)
        self.server.start()
        self.refresh()
        self.timer.start()
        self.changed.emit()
        return True

    def stop(self):
        self._phone_glow_off("Lucciola spenta: controllo dal telefono spento")
        if self.server is not None:
            self.server.close()
        self.timer.stop()
        self.joy_watch.stop()
        if self.joy is not None and self.joy.active:
            self.joy.stop()
        self.changed.emit()

    # ---------------------------------------------------------------- 0.22.5: muovere la testa dal telefono
    def move_enabled(self):
        """Permesso sul PC (Controllo dal telefono → «Permetti di muovere la testa dal telefono»). Spento di partenza."""
        qs = getattr(self.win, "qs", None)
        return bool(qs is not None and str(qs.value("phone_move", "false")).lower() in ("true", "1"))

    def set_move_enabled(self, on):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("phone_move", bool(on))
        if not on and self.joy is not None and self.joy.active:
            self._do_halt()
        if not on:  # 0.23.4: la Lucciola dal telefono vive solo insieme ai movimenti dal telefono
            self.set_glow_enabled(False)
        self.refresh()
        self.changed.emit()

    # ---------------------------------------------------------------- 0.23.4: la Lucciola dal telefono
    def _laser(self):
        return getattr(self.win, "laser", None)

    def glow_enabled(self):
        """Permesso sul PC, solo per questa sessione: spento di partenza, si spegne con i movimenti dal telefono."""
        return bool(self._glow_perm and self.move_enabled())

    def set_glow_enabled(self, on):
        self._glow_perm = bool(on) and self.move_enabled()
        if not self._glow_perm:
            self._phone_glow_off("Lucciola spenta: non è più permessa dal telefono")
        self.refresh()
        self.changed.emit()

    def phone_glow_on(self):
        lz = self._laser()
        return bool(lz is not None and getattr(lz, "_glow_on", False) and getattr(lz, "glow_owner", None) == "phone")

    def glow_check(self):
        """-> (si può accendere la Lucciola dal telefono?, perché no). Solo nel thread principale."""
        ctl, lz = self.ctl, self._laser()
        st = str(ctl.last_status.get("state", "") or "")
        if lz is None:
            return False, tr("Macchina non pronta")
        if not self.glow_enabled():
            return False, tr("La Lucciola dal telefono è spenta: si permette sul PC, in Controllo dal telefono.")
        if not ctl.connected:
            return False, tr("Macchina non connessa")
        if getattr(lz, "_power_knob", False):
            return False, tr("Su questa macchina la Lucciola non c'è: la potenza si regola con la manopola.")
        if ctl.job_active or getattr(ctl, "checking", False):
            return False, tr("Durante un lavoro la Lucciola non si accende.")
        if st.split(":")[0] in ("Alarm", "Door", "Hold", "Sleep"):
            return False, tr("Macchina non pronta: sbloccala o aspetta dal PC ({0}).", st)
        if getattr(lz, "_glow_on", False):
            if self.phone_glow_on():
                return True, ""
            return False, tr("La Lucciola è accesa dal PC: si spegne da lì.")
        if getattr(ctl, "fire_active", False):
            return False, tr("Sul PC è acceso il Puntino: spegnilo prima.")
        if not lz.glow_warned:
            return False, tr("La prima volta, in ogni sessione, la Lucciola si accende dal PC: lì c'è l'avviso da leggere.")
        return True, ""

    def _phone_glow_off(self, reason=""):
        """Spegne la Lucciola solo se l'ha accesa il telefono. Quella accesa dal PC resta com'è."""
        self.glow_watch.stop()
        if self.phone_glow_on():
            self._laser().glow_stop()
            if reason:
                self._log(reason)
            return True
        return False

    def _glow_watchdog(self):
        if not self.phone_glow_on():
            self.glow_watch.stop()
            return
        seen = list(getattr(self.server, "last_seen", {}).values()) if self.server is not None else []
        if not self.running or not seen or time.time() - max(seen) > self.GLOW_SILENCE_S:
            self._phone_glow_off("Lucciola spenta: il telefono non risponde")
            self.refresh()

    def move_check(self):
        """-> (si può muovere?, perché no). Solo nel thread principale."""
        ctl = self.ctl
        st = str(ctl.last_status.get("state", "") or "")
        if not self.move_enabled():
            return False, tr("Muovere la testa dal telefono è spento: si accende sul PC, in Controllo dal telefono.")
        if not ctl.connected:
            return False, tr("Macchina non connessa")
        if ctl.job_active:
            return False, tr("Durante un lavoro la testa non si muove dal telefono.")
        if getattr(ctl, "fire_active", False) and not (self.phone_glow_on() and self.glow_enabled()):
            # Puntino o Lucciola accesi dal PC: il raggio c'è, anche se debole. Dal telefono non lo si porta in giro.
            # 0.23.4: la Lucciola accesa dal telefono sì (serve proprio a vedere dove punta mentre si sistema il pezzo)
            return False, tr("Sul PC è acceso il Puntino o la Lucciola: spegnilo per muovere la testa dal telefono.")
        if getattr(ctl, "checking", False) or st.split(":")[0] in ("Alarm", "Door", "Hold", "Sleep"):
            return False, tr("Macchina non pronta: sbloccala o aspetta dal PC ({0}).", st)
        return True, ""

    def new_code(self):
        if self.server is not None:
            self.server.new_token()
        self.changed.emit()

    def urls(self):
        return self.server.urls() if self.running else []

    # ---------------------------------------------------------------- stato (thread principale)
    def _progress(self, done, total):
        if done == 0 or self.job_t0 is None:
            self.job_t0 = time.time()

    def paused(self):
        lp = getattr(self.win, "laser", None)
        b = getattr(lp, "b_pause", None)
        return bool(b is not None and b.isChecked()) or str(self.ctl.last_status.get("state", "")).startswith("Hold")

    def refresh(self):
        ctl = self.ctl
        st = str(ctl.last_status.get("state", "") or "")
        active = bool(ctl.job_active)
        done, total = int(getattr(ctl, "_job_done", 0)), int(getattr(ctl, "_job_total", 0))
        fire = getattr(getattr(self.win, "fire", None), "state", "")
        paused = active and self.paused()
        alarm = fire == "allarme" or st.startswith("Alarm")
        if fire == "allarme":
            title = tr("Guardia fiamme: lavoro fermato")
        elif not ctl.connected:
            title = tr("Macchina non connessa")
        elif active:
            title = tr("In pausa") if paused else tr("Lavoro in corso")
        elif st.startswith("Alarm"):
            title = tr("Allarme della macchina")
        else:
            title = tr("Pronta")
        src = getattr(getattr(self.win, "camera", None), "src", None)
        cam = src is not None and getattr(src, "index", None) not in (SIM_CAMERA, PHONE_CAMERA)
        elapsed = time.time() - self.job_t0 if active and self.job_t0 else 0.0
        left = elapsed * (total - done) / done if active and done > 20 and total else None
        detail = tr("Stato della scheda: {0}", st) if ctl.connected and st else ""
        if active and fire == "attiva":
            detail += ("  ·  " if detail else "") + tr("guardia fiamme attiva")
        move_ok, move_note = self.move_check()
        head = None
        try:
            hp = self.win.canvas.head_pos()
            head = [round(float(hp.x()), 2), round(float(hp.y()), 2)] if hp is not None and ctl.connected else None
        except Exception:  # noqa: BLE001
            head = None
        if move_ok and head is None:
            move_ok, move_note = False, tr("Posizione della testa non ancora nota: aspetta un attimo o fai l'homing")
        if not move_ok and self.joy is not None and self.joy.active:
            self._do_halt(tr("Joystick fermato: la macchina non è più pronta"))
        glow_ok, glow_note = self.glow_check()
        lz = self._laser()
        glow = {"perm": self.glow_enabled(), "ok": glow_ok, "note": glow_note,
                "on": bool(lz is not None and getattr(lz, "_glow_on", False)), "mine": self.phone_glow_on(),
                "left": round(lz.glow_seconds_left()) if lz is not None and self.phone_glow_on() else 0}
        self.snapshot = {"title": title, "detail": detail, "state": st, "connected": bool(ctl.connected),
                         "job_active": active, "paused": paused, "done": done if active else 0,
                         "total": total if active else 0, "elapsed": elapsed, "left": left, "alarm": alarm,
                         "camera": bool(cam), "fire": fire or "", "move_ok": move_ok, "move_note": move_note,
                         "pos": head, "glow": glow}

    # ---------------------------------------------------------------- chiamate dal thread del server
    def _frame(self):
        src = getattr(getattr(self.win, "camera", None), "src", None)
        if src is None or getattr(src, "index", None) in (SIM_CAMERA, PHONE_CAMERA):
            return None  # la foto mandata dal telefono non è una telecamera da guardare dal telefono
        f = src.get(after=0, timeout=0.5)
        if f is None:
            return None
        h, w = f.shape[:2]
        if w > 800:
            f = cv2.resize(f, (800, int(h * 800 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    def _pause(self):
        s = self.snapshot
        if not s.get("job_active"):
            return False, tr("Nessun lavoro in corso.")
        if s.get("paused"):
            return True, tr("Il lavoro è già in pausa. Per riprendere usa il PC.")
        self.pause_requested.emit()
        return True, tr("Pausa richiesta.")

    def _stop(self):
        if not self.snapshot.get("job_active"):
            return False, tr("Nessun lavoro in corso.")
        self.stop_requested.emit()
        return True, tr("Lavoro fermato, laser spento.")

    def _move(self, kind, data):
        """Dal thread del server: controlla la richiesta e la passa al thread principale. Laser mai acceso."""
        s = self.snapshot
        if kind == "lucciola":  # 0.23.4
            on = data.get("on") if isinstance(data, dict) else None
            if on is False:  # spegnere si può sempre (spegne solo quella accesa dal telefono)
                self.glow_requested.emit(False)
                return True, tr("Lucciola spenta.")
            g = s.get("glow") or {}
            if on is not True:
                return False, tr("Richiesta non valida")
            if not g.get("ok"):
                return False, g.get("note") or tr("Macchina non pronta")
            self.glow_requested.emit(True)
            return True, ""
        if kind == "ferma":
            if not self.move_enabled():  # funzione spenta sul PC: dal telefono non parte nessun comando, nemmeno questo
                return False, s.get("move_note") or tr("Macchina non pronta")
            self.halt_requested.emit()
            return True, tr("Testa ferma.")
        if not s.get("move_ok"):
            return False, s.get("move_note") or tr("Macchina non pronta")
        try:
            if kind == "passo":
                dx, dy = int(data.get("dx", 0)), int(data.get("dy", 0))
                step = float(data.get("step", 10))
                if dx not in (-1, 0, 1) or dy not in (-1, 0, 1) or (dx == 0 and dy == 0) or step not in self.STEPS:
                    raise ValueError
                self.step_requested.emit(float(dx), float(dy), step)
                return True, ""
            if kind == "joystick":
                x, y = float(data.get("x", 0)), float(data.get("y", 0))
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise ValueError
                self.joy_requested.emit(max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))
                return True, ""
        except (TypeError, ValueError, AttributeError, OverflowError):
            pass
        return False, tr("Richiesta non valida")

    def _photo(self, data):
        self.photo_received.emit(bytes(data))
        return tr("Foto arrivata sul PC: il risultato è nel Test materiale.")

    def _plate(self, data):
        self.plate_received.emit(bytes(data))
        return tr("Foto arrivata sul PC: lì indica i 4 angoli dell'area di lavoro.")

    # ---------------------------------------------------------------- esecuzione (thread principale)
    def _do_pause(self):
        if self.ctl.job_active and not self.paused():
            b = getattr(getattr(self.win, "laser", None), "b_pause", None)
            if b is not None:
                b.setChecked(True)
            else:
                self.ctl.feed_hold()
            self._log("pausa dal telefono")

    def _do_stop(self):
        self._phone_glow_off("Lucciola spenta dal telefono (Stop)")
        if self.ctl.job_active:
            self.ctl.stop_job()
            self._log("stop dal telefono")
            self.win.statusBar().showMessage(tr("Lavoro fermato dal telefono"), 15000)

    def _feed(self):
        try:
            return float(self.win.move.feed.value())
        except Exception:  # noqa: BLE001
            return 3000.0

    def _do_step(self, dx, dy, step):
        ok, _why = self.move_check()  # di nuovo qui: fra la richiesta e adesso può essere partito un lavoro
        if not ok:
            return
        # dentro il piano, come il joystick: su una macchina senza limiti software più tocchi da 50 mm non devono
        # portare la testa contro il telaio
        from .jogpad import JoyJog, reach_box

        try:
            hp = self.win.canvas.head_pos()
            x0, y0, x1, y1 = reach_box(self.ctl, self.win.profile)
        except Exception:  # noqa: BLE001
            hp = None
        if hp is None:
            return
        m = JoyJog.MARGIN
        now = time.monotonic()
        if now < self._hold_until:
            return
        hx, hy = float(hp.x()), float(hp.y())
        if self._plan is not None and now < self._plan[2] + JoyJog.SETTLE + JoyJog.POS_SLACK:
            # la posizione letta dalla scheda arriva in ritardo (ogni 0,2 s): con più tocchi di fila si parte da dove
            # la testa sta andando, non da dove risultava, se no la somma dei tocchi supererebbe il bordo
            hx, hy = self._plan[0], self._plan[1]
        mx = min(hx + dx * step, max(hx, x1 - m)) if dx > 0 else max(hx + dx * step, min(hx, x0 + m)) if dx < 0 else hx
        my = min(hy + dy * step, max(hy, y1 - m)) if dy > 0 else max(hy + dy * step, min(hy, y0 + m)) if dy < 0 else hy
        if abs(mx - hx) < 0.005 and abs(my - hy) < 0.005:
            self._log("freccia dal telefono: la testa è già al bordo del piano")
            return
        feed = max(self._feed(), 1.0)
        self.ctl.jog(mx - hx, my - hy, feed)
        start = max(now, self._plan[2]) if self._plan is not None else now
        self._plan = (mx, my, start + math.hypot(mx - hx, my - hy) / (feed / 60.0))
        self._log(f"freccia dal telefono ({dx:+.0f}, {dy:+.0f}) × {step:g} mm")

    def _do_joy(self, x, y):
        ok, _why = self.move_check()
        if not ok or (abs(x) < 1e-3 and abs(y) < 1e-3):
            self._do_halt()
            return
        if self.joy is None:
            from .jogpad import JoyJog

            self.joy = JoyJog(self.ctl, lambda: self.win.profile, self.win.canvas.head_pos, self._feed, self)
        if not self.joy.active:
            if not self.joy.start():
                return
            self._log("joystick dal telefono")
        self.joy.set_vector(x, y)
        self.joy_watch.start()

    def _do_halt(self, reason="", cancel=False):
        """Ferma il joystick del telefono. cancel=True (solo «■» premuto sul telefono, con la funzione accesa): ferma
        anche lo spostamento di una freccia ancora in corso."""
        self.joy_watch.stop()
        fermato = False
        if self.joy is not None and self.joy.active:
            self.joy.stop(reason)
            fermato = True
        elif cancel and self.move_enabled() and self.ctl.connected and not self.ctl.job_active:
            self.ctl.jog_cancel()
            fermato = True
        if fermato:
            self._plan = None  # la testa si è fermata a metà strada: si riparte dalla posizione vera, appena arriva
            self._hold_until = time.monotonic() + 0.6
        if reason:
            self._log(reason)
        if cancel:  # 0.23.4: «■» dal telefono spegne anche la Lucciola accesa dal telefono
            self._phone_glow_off("Lucciola spenta dal telefono («■»)")

    def _do_glow(self, on):
        """Thread principale. Accende (dopo un nuovo controllo: fra la richiesta e adesso può essere cambiato tutto) o
        spegne la Lucciola dal telefono, con la potenza scelta sul PC e tutti i suoi limiti (LaserPanel)."""
        lz = self._laser()
        if not on:
            if self._phone_glow_off("Lucciola spenta dal telefono"):
                self.refresh()
            return
        ok, why = self.glow_check()
        if not ok or lz is None or self.phone_glow_on():
            if why:
                self._log("Lucciola dal telefono non accesa: " + why)
            return
        if lz.glow_start_on(from_phone=True):
            self._log("Lucciola accesa dal telefono")
            self.glow_watch.start()
        self.refresh()

    def _do_photo(self, data):
        self._log(f"foto del test dal telefono ({len(data) // 1024} kB)")
        self.win.photo_from_phone(data)

    def _do_plate(self, data):
        self._log(f"foto del piano dal telefono ({len(data) // 1024} kB)")
        self.win.plate_from_phone(data)

    def _log(self, text):
        log = getattr(self.win, "comm_log", None)
        if log is not None:
            log.add("#", text)


def qr_pixmap(text, scale=6):
    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3, dark="#000000", light="#FFFFFF")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm


def guide_html():
    return tr(
        "<b>Come si usa</b><ol>"
        "<li>Il telefono deve essere collegato allo <b>stesso Wi-Fi</b> del PC (non con i dati mobili).</li>"
        "<li>Spunta <i>Attiva il controllo dal telefono</i>. La prima volta Windows può chiedere se consentire "
        "l'accesso alla rete a FreeLaserCut (Python): scegli <b>Reti private</b> e premi Consenti.</li>"
        "<li>Inquadra il codice QR con la fotocamera del telefono e apri il link. Puoi aggiungere la pagina alla "
        "schermata Home per ritrovarla.</li>"
        "<li>Dal telefono vedi l'avanzamento e la camera, puoi mettere in <b>pausa</b> o <b>fermare</b> il lavoro "
        "e inviare la <b>foto del test materiale</b>. Avviare o riprendere si fa solo dal PC, davanti alla macchina.</li>"
        "</ol>"
        "<p>Il collegamento resta dentro la rete di casa e si spegne quando chiudi FreeLaserCut. Il codice "
        "nell'indirizzo è casuale: se l'hai dato a qualcuno, premi <i>Cambia codice</i> e il vecchio link smette di "
        "funzionare. Se il telefono non apre la pagina: controlla il Wi-Fi, che la rete sia impostata come "
        "<i>privata</i> in Windows e che il firewall non blocchi FreeLaserCut.</p>") + tr(
        "<p><b>Foto del piano di lavoro</b> (0.19.0): dal telefono puoi anche fotografare il piano dall'alto e "
        "mandare la foto. Sul PC indichi i 4 angoli dell'area di lavoro e la foto finisce sotto il piano, per "
        "posizionare i pezzi (pannello Camera, voce «Foto del piano dal telefono»).</p>") + tr(
        "<p><b>Muovere la testa</b> (0.22.5): se spunti <i>Permetti di muovere la testa dal telefono</i>, sulla pagina "
        "compaiono le frecce (un passo per tocco: 0,1, 1, 10 o 50 mm) e un joystick (la testa si muove finché lo "
        "tieni). Il laser resta sempre spento, durante un lavoro non funziona, e se il telefono perde la rete la "
        "testa si ferma da sola. Usalo solo se vedi la macchina.</p>") + tr(  # con Puntino o Lucciola del PC non si muove
        "<p><b>Lucciola dal telefono</b> (0.23.4): con <i>Permetti di accendere la Lucciola dal telefono</i> sulla "
        "pagina compare il pulsante per accenderla e spegnerla, con la potenza scelta sul PC. La prima volta in ogni "
        "sessione va accesa dal PC. Accesa dal telefono, la testa si può muovere per vedere dove punta. Si spegne "
        "da sola dopo 5 minuti senza movimenti, se chiudi la pagina o il telefono perde la rete, con «■» e quando "
        "parte un lavoro. Il permesso non resta: va rispuntato a ogni avvio.</p>")


class PhoneDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle(tr("Controllo dal telefono"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        self.chk = QCheckBox(tr("Attiva il controllo dal telefono (fino alla chiusura di FreeLaserCut)"))
        self.chk.setChecked(ctrl.running)
        self.chk.toggled.connect(self._toggle)
        v.addWidget(self.chk)
        self.chk_move = QCheckBox(tr("Permetti di muovere la testa dal telefono (frecce e joystick, laser spento)"))
        self.chk_move.setToolTip(tr("Solo con la macchina ferma e senza lavori. Chi tiene il telefono deve vedere la "
                                    "macchina: la testa si muove davvero."))
        self.chk_move.setChecked(ctrl.move_enabled())
        self.chk_move.toggled.connect(ctrl.set_move_enabled)
        v.addWidget(self.chk_move)
        # 0.23.4: Lucciola dal telefono. Solo con i movimenti permessi, mai ricordata: si rispunta a ogni avvio
        self.chk_glow = QCheckBox(tr("Permetti di accendere la Lucciola dal telefono (solo fino alla chiusura)"))
        self.chk_glow.setToolTip(tr(
            "Il pulsante Lucciola compare sulla pagina del telefono. Stessa potenza e stessi limiti del PC; la prima "
            "volta in ogni sessione va accesa dal PC, per leggere l'avviso. Si spegne da sola dopo 5 minuti senza "
            "movimenti, se il telefono perde la rete o chiude la pagina, e quando parte un lavoro. Chi tiene il "
            "telefono deve vedere la macchina e portare gli occhiali protettivi."))
        self.chk_glow.setStyleSheet("QCheckBox { margin-left: 18px; }")
        self.chk_glow.setChecked(ctrl.glow_enabled())
        self.chk_glow.toggled.connect(ctrl.set_glow_enabled)
        v.addWidget(self.chk_glow)
        h = QHBoxLayout()
        self.qr = QLabel()
        self.qr.setFixedSize(230, 230)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setStyleSheet(css("background:#0B0F17; border:1px solid #2A3550; border-radius:8px;"))
        h.addWidget(self.qr)
        right = QVBoxLayout()
        self.url = QLabel()
        self.url.setWordWrap(True)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.url)
        self.b_copy = QPushButton(tr("Copia l'indirizzo"))
        self.b_copy.clicked.connect(self._copy)
        self.b_code = QPushButton(tr("Cambia codice"))
        self.b_code.setToolTip(tr("Il vecchio indirizzo smette di funzionare"))
        self.b_code.clicked.connect(self._new_code)
        right.addWidget(self.b_copy)
        right.addWidget(self.b_code)
        self.seen = QLabel()
        self.seen.setWordWrap(True)
        right.addWidget(self.seen)
        right.addStretch(1)
        h.addLayout(right, 1)
        v.addLayout(h)
        g = QLabel(guide_html())
        g.setWordWrap(True)
        g.setTextFormat(Qt.RichText)
        v.addWidget(g)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        ctrl.changed.connect(self.update_view)
        self.t = QTimer(self)
        self.t.timeout.connect(self._seen)
        self.t.start(1000)
        self.update_view()

    def _toggle(self, on):
        if on:
            try:
                self.ctrl.start()
            except OSError as ex:
                self.chk.blockSignals(True)
                self.chk.setChecked(False)
                self.chk.blockSignals(False)
                QMessageBox.warning(self, tr("Controllo dal telefono"), tr("Non riesco ad aprire la pagina: {0}", ex))
        else:
            self.ctrl.stop()
        self.update_view()

    def _copy(self):
        u = self.ctrl.urls()
        if u:
            QGuiApplication.clipboard().setText(u[0])

    def _new_code(self):
        self.ctrl.new_code()

    def update_view(self):
        if hasattr(self, "chk_glow"):  # 0.23.4: la Lucciola dal telefono segue i movimenti dal telefono
            self.chk_glow.setEnabled(self.ctrl.move_enabled())
            if self.chk_glow.isChecked() != self.ctrl.glow_enabled():
                self.chk_glow.blockSignals(True)
                self.chk_glow.setChecked(self.ctrl.glow_enabled())
                self.chk_glow.blockSignals(False)
        urls = self.ctrl.urls()
        on = bool(urls)
        self.b_copy.setEnabled(on)
        self.b_code.setEnabled(on)
        if on:
            self.qr.setPixmap(qr_pixmap(urls[0]).scaled(220, 220, Qt.KeepAspectRatio, Qt.FastTransformation))
            txt = tr("Indirizzo per il telefono:") + f"<br><b>{urls[0]}</b>"
            if len(urls) > 1:
                txt += "<br><small>" + tr("Altri indirizzi di questo PC:") + "<br>" + "<br>".join(urls[1:]) + "</small>"
            self.url.setText(txt)
        else:
            self.qr.clear()
            self.qr.setText(tr("Spento"))
            self.url.setText(tr("Spunta la casella qui sopra per accendere la pagina per il telefono."))
        self._seen()

    def _seen(self):
        srv = self.ctrl.server
        if not self.ctrl.running or srv is None or not srv.last_seen:
            self.seen.setText("")
            return
        t = max(srv.last_seen.values())
        self.seen.setText(tr("Telefoni collegati: {0} · ultimo contatto {1}", len(srv.last_seen),
                             time.strftime("%H:%M:%S", time.localtime(t))))
