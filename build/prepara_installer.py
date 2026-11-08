# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Prepara la cartella build/stage per l'installatore Windows di FreeLaserCut.

Uso (da Windows, Linux o macOS, con Python 3.10 o più recente e internet):

    python build/prepara_installer.py
    makensis -DVER=<versione> build/installer.nsi   (NSIS 3: https://nsis.sourceforge.io)

Il risultato è build/FreeLaserCut-<versione>-Setup.exe. Lo script:
1. scarica Python per Windows (python-build-standalone) e lo estrae in build/stage/python;
2. installa le librerie per Windows (ruote ufficiali da PyPI) dentro quel Python;
3. toglie gli strumenti di sviluppo che il programma non usa;
4. copia il programma in build/stage/app, più licenze e README.
"""
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
STAGE = os.path.join(BUILD, "stage")
CACHE = os.path.join(BUILD, "cache")

PY_RELEASE = "20261026"
PY_VERSION = "3.14.10"
PY_URL = (f"https://github.com/astral-sh/python-build-standalone/releases/download/{PY_RELEASE}/"
          f"cpython-{PY_VERSION}+{PY_RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")

PACKAGES = [
    "PySide6-Essentials==6.12.0",
    "numpy==2.5.4",
    "pyserial==3.5",
    "pillow==13.0.0",
    "opencv-python==5.0.0.93",
    "pyclipper==1.4.0",
    "segno==1.6.6",
    "python-barcode==0.16.1",
    "svgelements==1.9.6",
    "ezdxf==1.4.5",
    "Hershey-Fonts==2.1.0",
    "numba==0.68.1",
]

# cartelle che il programma non usa (strumenti per sviluppatori, Tk, file di sviluppo)
TRIM_PYTHON = ["tcl", "include", "libs"]
TRIM_SITE = ["bin", "share", "test", "tests"]
TRIM_PYSIDE = ["qml", "metatypes", "typesystems", "include", "glue"]


def step(msg):
    print(f"\n== {msg}", flush=True)


def version():
    with open(os.path.join(ROOT, "freelasercut", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)


def scarica(url, dest, tentativi=6):
    """Scarica con qualche nuovo tentativo: un 504 momentaneo di GitHub non deve far fallire l'installatore."""
    import time

    for n in range(1, tentativi + 1):
        print("scarico", url, f"(tentativo {n})" if n > 1 else "")
        try:
            urllib.request.urlretrieve(url, dest + ".part")
            os.replace(dest + ".part", dest)
            return
        except OSError as exc:  # HTTPError e URLError sono OSError
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            if n == tentativi:
                raise
            pausa = min(10 * 2 ** (n - 1), 60)
            print("  non riuscito:", exc, f"— riprovo tra {pausa} s")
            time.sleep(pausa)


def main():
    ver = version()
    step(f"FreeLaserCut {ver}: preparo {STAGE}")
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(CACHE, exist_ok=True)

    step("Python per Windows")
    archive = os.path.join(CACHE, os.path.basename(PY_URL).replace("+", "_"))
    if not os.path.exists(archive):
        scarica(PY_URL, archive)
    with tarfile.open(archive) as tf:
        tf.extractall(STAGE, filter="data") if sys.version_info >= (3, 12) else tf.extractall(STAGE)
    py = os.path.join(STAGE, "python")
    for d in TRIM_PYTHON:
        shutil.rmtree(os.path.join(py, d), ignore_errors=True)

    step("Librerie (ruote per Windows, Python 3.14)")
    site = os.path.join(py, "Lib", "site-packages")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", site,
                           "--platform", "win_amd64", "--python-version", "3.14", "--implementation", "cp",
                           "--abi", "cp314", "--only-binary=:all:", "--upgrade", *PACKAGES])
    for d in TRIM_SITE:
        shutil.rmtree(os.path.join(site, d), ignore_errors=True)
    pyside = os.path.join(site, "PySide6")
    for d in TRIM_PYSIDE:
        shutil.rmtree(os.path.join(pyside, d), ignore_errors=True)
    for name in os.listdir(pyside):
        if name.lower().endswith(".exe"):
            os.remove(os.path.join(pyside, name))
    # la cartella app\ entra nel percorso di Python da sola: il programma parte da qualsiasi cartella
    with open(os.path.join(site, "freelasercut_app.pth"), "w", encoding="utf-8") as fh:
        fh.write("../../../app\n")

    step("Programma, licenze, README")
    shutil.copytree(os.path.join(ROOT, "freelasercut"), os.path.join(STAGE, "app", "freelasercut"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("LICENSE", "README.md", "LICENZE-TERZE-PARTI.md", "CHANGELOG.md"):
        shutil.copy2(os.path.join(ROOT, f), STAGE)
    shutil.copytree(os.path.join(ROOT, "licenze-terze-parti"), os.path.join(STAGE, "licenze-terze-parti"))

    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(STAGE) for f in fs)
    step(f"Pronto: {size / 1e6:.0f} MB in {STAGE}")
    print(f"Ora: makensis -DVER={ver} build{os.sep}installer.nsi")


if __name__ == "__main__":
    main()
