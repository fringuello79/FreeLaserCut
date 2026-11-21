# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: lettura dei controller di gioco (joystick fisico per muovere la testa: Logitech G13 in modalità joystick,
pad Xbox e PlayStation, joystick USB, Arduino che si presenta come joystick).

Qt 6 non ha più un modulo per i gamepad: si usa SDL attraverso pygame-ce (LGPL 2.1), caricato solo quando serve.
Se pygame-ce non c'è o non parte, `backend()` dice perché e la funzione resta spenta: il programma lavora come prima.

Qui solo la lettura (nomi, assi, pulsanti). Le regole di sicurezza stanno in `ui/joystick_fisico.py`.
"""
import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Device:
    name: str
    guid: str = ""
    index: int = 0
    axes: int = 0
    buttons: int = 0

    def key(self):
        """Identificativo per ricordarlo: nome e GUID di SDL insieme (due G13 uguali hanno lo stesso)."""
        return f"{self.name}|{self.guid}"


@dataclass
class Reading:
    axes: list = field(default_factory=list)  # da -1 a 1; asse 1 positivo verso il basso (come SDL)
    buttons: list = field(default_factory=list)  # bool
    t: float = 0.0  # time.monotonic() della lettura


class GamepadError(Exception):
    pass


class PygameBackend:
    """SDL con pygame-ce. Il video di SDL è quello finto («dummy»): nessuna finestra, nessun disturbo a Qt. Gli eventi
    dei controller arrivano anche quando SDL non ha una finestra in primo piano: se FreeLaserCut è in primo piano lo
    decide `ui/joystick_fisico.py`, che altrimenti ignora la levetta."""

    name = "SDL (pygame-ce)"

    def __init__(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        try:
            import pygame  # noqa: F401 - pesante: solo qui, solo quando serve
        except Exception as ex:  # noqa: BLE001 - ImportError, DLL mancanti, librerie di sistema
            raise GamepadError(f"pygame-ce non disponibile ({type(ex).__name__}: {ex})") from ex
        self.pg = pygame
        self._lock = threading.Lock()
        try:
            pygame.display.init()
            pygame.joystick.init()
        except Exception as ex:  # noqa: BLE001
            raise GamepadError(f"SDL non parte ({ex})") from ex
        self._open = {}

    def version(self):
        try:
            return f"pygame-ce {self.pg.version.ver} · SDL {'.'.join(str(v) for v in self.pg.get_sdl_version())}"
        except Exception:  # noqa: BLE001
            return "pygame-ce"

    def devices(self):
        with self._lock:
            pg = self.pg
            try:
                pg.event.pump()
                # SDL vede i controller collegati dopo l'avvio solo rifacendo l'elenco
                pg.joystick.quit()
                pg.joystick.init()
                self._open.clear()
                out = []
                for i in range(pg.joystick.get_count()):
                    j = pg.joystick.Joystick(i)
                    out.append(Device(str(j.get_name() or f"Joystick {i + 1}"), str(j.get_guid() or ""), i,
                                      int(j.get_numaxes()), int(j.get_numbuttons())))
                return out
            except Exception as ex:  # noqa: BLE001
                raise GamepadError(f"elenco dei controller non letto ({ex})") from ex

    def read(self, dev):
        with self._lock:
            pg = self.pg
            try:
                pg.event.pump()
                j = self._open.get(dev.index)
                if j is None:
                    j = pg.joystick.Joystick(dev.index)
                    self._open[dev.index] = j
                if str(j.get_guid() or "") != dev.guid or str(j.get_name() or "") != dev.name:
                    raise GamepadError("il controller non è più quello scelto")
                return Reading([float(j.get_axis(k)) for k in range(j.get_numaxes())],
                               [bool(j.get_button(k)) for k in range(j.get_numbuttons())], time.monotonic())
            except GamepadError:
                raise
            except Exception as ex:  # noqa: BLE001 - scollegato, errore di SDL
                raise GamepadError(f"controller non leggibile ({ex})") from ex


class FakeBackend:
    """Controller finti per le prove: `devices` si cambia a mano, `state[key] = Reading`, `fail = True` simula un
    controller che non risponde, `frozen = True` uno che ridà sempre la stessa lettura vecchia."""

    name = "finto"

    def __init__(self, devices=()):
        self.devs = list(devices)
        self.state = {}
        self.fail = False
        self.frozen = False
        self._last = {}

    def version(self):
        return "finto"

    def devices(self):
        if self.fail:
            raise GamepadError("finto: non risponde")
        return list(self.devs)

    def set(self, dev, x=0.0, y=0.0, buttons=()):
        n = max(dev.buttons, 1)
        self.state[dev.key()] = ([float(x), float(y)] + [0.0] * max(0, dev.axes - 2), [k in buttons for k in range(n)])

    def read(self, dev):
        if self.fail or dev.key() not in {d.key() for d in self.devs}:
            raise GamepadError("finto: scollegato")
        if self.frozen and dev.key() in self._last:
            return self._last[dev.key()]
        axes, buttons = self.state.get(dev.key(), ([0.0] * max(dev.axes, 2), [False] * max(dev.buttons, 1)))
        r = Reading(list(axes), list(buttons), time.monotonic())
        self._last[dev.key()] = r
        return r


_BACKEND = None
_ERROR = ""


def backend():
    """Il lettore dei controller, o None (e il motivo in `error()`). Si prova una volta sola per avvio."""
    global _BACKEND, _ERROR
    if _BACKEND is None and not _ERROR:
        if os.environ.get("FLC_NO_GAMEPAD") == "1":
            _ERROR = "spento (FLC_NO_GAMEPAD=1)"
            return None
        try:
            _BACKEND = PygameBackend()
        except GamepadError as ex:
            _ERROR = str(ex)
    return _BACKEND


def error():
    return _ERROR


def set_backend(b, err=""):
    """Per le prove: mette un lettore (anche None, con il motivo)."""
    global _BACKEND, _ERROR
    _BACKEND, _ERROR = b, ("" if b is not None else (err or "nessun lettore"))
