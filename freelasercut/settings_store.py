# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Dove stanno le preferenze del programma.

Di solito nel posto normale del sistema (su Windows il registro, su Linux ~/.config). Con la variabile d'ambiente
FLC_SETTINGS_INI in un file .ini a parte: lo usano le prove automatiche, così ogni prova parte da preferenze pulite
anche su Windows, dove il registro è in comune fra tutte."""
import os


def app_settings():
    from PySide6.QtCore import QSettings

    ini = os.environ.get("FLC_SETTINGS_INI")
    if ini:
        return QSettings(ini, QSettings.IniFormat)
    return QSettings("FreeLaserCut", "FreeLaserCut")
