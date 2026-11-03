# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Unità di misura della velocità: FreeLaserCut lavora sempre in mm/min (come GRBL e il G-code); qui si sceglie solo
come mostrarla e scriverla (Impostazioni → Unità di misura). I campi mostrano l'unità scelta ma il valore resta in
mm/min, così progetti, profili e libreria non cambiano."""
import os

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

UNITS = ("mm/min", "mm/s")
_unit = None


def speed_unit():
    global _unit
    if _unit is None:
        u = os.environ.get("FLC_SPEED_UNIT") or _saved()
        _unit = u if u in UNITS else "mm/min"
    return _unit


def _saved():
    try:
        from PySide6.QtCore import QSettings

        return str(QSettings("FreeLaserCut", "FreeLaserCut").value("unit_speed", "mm/min"))
    except Exception:  # noqa: BLE001
        return "mm/min"


def set_speed_unit(u):
    """Cambia l'unità (vale per le finestre aperte da ora in poi)."""
    global _unit
    _unit = u if u in UNITS else "mm/min"


def per_s():
    return speed_unit() == "mm/s"


def to_shown(v_mm_min):
    return v_mm_min / 60.0 if per_s() else v_mm_min


def from_shown(v):
    return v * 60.0 if per_s() else v


def suffix():
    return " " + speed_unit()


def fmt(v_mm_min, unit=True):
    """1000 → «1000 mm/min» oppure «16,7 mm/s» (una cifra decimale in mm/s)."""
    if per_s():
        txt = f"{v_mm_min / 60.0:.1f}".rstrip("0").rstrip(".")
    else:
        txt = f"{v_mm_min:g}"
    return f"{txt} {speed_unit()}" if unit else txt


def other(v_mm_min):
    """La stessa velocità nell'altra unità (per i suggerimenti)."""
    return f"{v_mm_min:g} mm/min" if per_s() else f"{v_mm_min / 60.0:.1f} mm/s"


class SpeedSpin(QDoubleSpinBox):
    """Campo della velocità: value() e setValue() in mm/min, sullo schermo nell'unità scelta."""

    def __init__(self, lo=1.0, hi=36000.0, val=1000.0, step_mm_min=100.0, show_suffix=True, parent=None):
        super().__init__(parent)
        self.setDecimals(0)  # dentro: mm/min interi
        self.setRange(lo, hi)
        self.setSingleStep(60.0 if per_s() and step_mm_min >= 60 else step_mm_min)
        self.setValue(val)
        if show_suffix:
            self.setSuffix(suffix())
        self.setKeyboardTracking(False)

    def textFromValue(self, v):
        return fmt(v, unit=False)

    def valueFromText(self, text):
        t = text.replace(self.suffix(), "").strip().replace(",", ".")
        try:
            return from_shown(float(t))
        except ValueError:
            return self.value()

    def validate(self, text, pos):
        from PySide6.QtGui import QValidator

        t = text.replace(self.suffix(), "").strip().replace(",", ".")
        if t == "" or t == ".":
            return QValidator.Intermediate, text, pos
        try:
            float(t)
            return QValidator.Acceptable, text, pos
        except ValueError:
            return QValidator.Invalid, text, pos


class SpeedIntSpin(QSpinBox):
    """Come SpeedSpin, per i campi interi (Banco)."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def textFromValue(self, v):
        return fmt(v, unit=False)

    def valueFromText(self, text):
        t = text.replace(self.suffix(), "").strip().replace(",", ".")
        try:
            return int(round(from_shown(float(t))))
        except ValueError:
            return self.value()

    def validate(self, text, pos):
        from PySide6.QtGui import QValidator

        t = text.replace(self.suffix(), "").strip().replace(",", ".")
        if t in ("", "."):
            return QValidator.Intermediate, text, pos
        try:
            float(t)
            return QValidator.Acceptable, text, pos
        except ValueError:
            return QValidator.Invalid, text, pos
