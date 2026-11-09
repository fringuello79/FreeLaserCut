# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Cache di numba per l'AppImage (0.18.0).

Le funzioni compilate con numba (``@njit(cache=True)``: diffusione dell'errore, vettorizzazione) si salvano su disco
per non ricompilarle a ogni avvio. Accanto al codice non si può (l'AppImage è in sola lettura), e la cartella che
numba userebbe al suo posto (~/.cache/numba) dipende dal percorso completo del file sorgente: nell'AppImage quel
percorso cambia a ogni avvio (/tmp/.mount_XXXX), quindi numba ricompilerebbe sempre e lascerebbe una cartella nuova
ogni volta. Qui la cartella dipende solo dalla versione di FreeLaserCut e dal percorso *dentro* l'AppImage.

numba usa questa classe solo se ``NUMBA_CACHE_LOCATOR_CLASSES`` la indica (lo fa ``linux.startup`` nell'AppImage);
questo modulo si importa solo quando numba la cerca."""
import hashlib
import os

from numba.core.caching import UserWideCacheLocator

from . import __version__
from .linux import NUMBA_PREFIX as PREFIX


def relative_dir(py_file, appdir=None):
    """Cartella del file sorgente relativa ad APPDIR (con / come separatore), o None se il file è fuori."""
    appdir = appdir or os.environ.get("APPDIR")
    if not appdir:
        return None
    root = os.path.realpath(appdir)
    d = os.path.dirname(os.path.realpath(py_file))
    if not (d == root or d.startswith(root.rstrip(os.sep) + os.sep)):
        return None
    return os.path.relpath(d, root).replace(os.sep, "/")


def subpath(py_file, appdir=None, version=__version__):
    rel = relative_dir(py_file, appdir)
    if rel is None:
        return None
    digest = hashlib.sha1(f"{version}:{rel}".encode()).hexdigest()[:16]
    return f"{PREFIX}{version}-{os.path.basename(rel)}_{digest}"


class AppImageCacheLocator(UserWideCacheLocator):
    """Come la cache utente di numba, ma con una cartella che non cambia da un avvio all'altro."""

    @classmethod
    def get_suitable_cache_subpath(cls, py_file):
        return subpath(py_file) or super().get_suitable_cache_subpath(py_file)

    @classmethod
    def from_function(cls, py_func, py_file):
        if relative_dir(py_file) is None:
            return None  # file fuori dall'AppImage: decidono gli altri modi di numba
        return super().from_function(py_func, py_file)
