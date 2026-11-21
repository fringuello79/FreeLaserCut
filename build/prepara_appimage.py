# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Costruisce la versione per Linux di FreeLaserCut: build/FreeLaserCut-<versione>-x86_64.AppImage.

Uso (su Linux x86_64, con Python 3.10 o più recente e internet):

    python build/prepara_appimage.py

Lo stesso programma dell'installatore per Windows, con lo stesso Python e le stesse librerie:
1. scarica Python per Linux (python-build-standalone, stessa versione dell'installatore) in AppDir/usr/python;
2. installa le librerie per Linux (ruote ufficiali da PyPI; OpenCV nella versione «headless», che non porta un suo
   Qt in conflitto con PySide6);
3. aggiunge le poche librerie xcb che Qt 6 vuole e che molte distribuzioni non installano (xcb-cursor…) e
   libgthread (0.20.5: openSUSE non la installa), poi controlla che Qt non chieda al sistema niente di imprevisto;
4. copia il programma, compila i .pyc (l'AppImage è in sola lettura) e scrive AppRun, il file .desktop e l'icona;
5. impacchetta tutto con appimagetool.

Le prove: tests/test_v180.py (codice) e il workflow installatore.yml (avvio dell'AppImage su Ubuntu con X11 vero).
"""
import glob
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
sys.path.insert(0, BUILD)
from prepara_installer import CACHE, PACKAGES, PY_RELEASE, PY_VERSION, TRIM_PYGAME, TRIM_PYSIDE, scarica, step, version  # noqa: E402

APPDIR = os.path.join(BUILD, "AppDir")
PY_URL = (f"https://github.com/astral-sh/python-build-standalone/releases/download/{PY_RELEASE}/"
          f"cpython-{PY_VERSION}+{PY_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz")
APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
PY_MINOR = ".".join(PY_VERSION.split(".")[:2])  # 3.14

# su Linux: OpenCV senza la sua copia di Qt (stessa versione e stessa licenza Apache 2.0)
LINUX_PACKAGES = [p.replace("opencv-python==", "opencv-python-headless==") for p in PACKAGES]
# PySide6 6.12 per Linux è «manylinux_2_34»: serve glibc 2.34 o più recente (Ubuntu 22.04, Debian 12, Fedora 35,
# Linux Mint 21 e successive). Si costruisce su Ubuntu 22.04 e nessun file può chiedere di più.
GLIBC_MAX = (2, 34)
PLATFORMS = [f"manylinux_2_{n}_x86_64" for n in range(GLIBC_MAX[1], 16, -1)] + [
    "manylinux2014_x86_64", "manylinux_2_5_x86_64", "manylinux1_x86_64", "linux_x86_64"]

# librerie che il plugin xcb di Qt 6 richiede e che spesso mancano (Ubuntu, Debian e Fedora non le mettono sempre):
# si copiano accanto alle librerie di Qt, che le trovano da sole ($ORIGIN). Licenza MIT/X11.
# 0.18.1: anche le estensioni di libxcb (randr, render, shape, shm, sync, xfixes, xkb): sul primo Ubuntu di prova di
# GitHub mancava libxcb-xkb e Qt non partiva («xcb-cursor0 is needed», messaggio di Qt che non dice quale manca).
# 0.20.5: libxkbcommon-x11 usa strutture interne di libxkbcommon e deve venire dalla stessa versione: con la x11 di
# Ubuntu 22.04 (1.4) e la libxkbcommon di sistema (Arch, 1.13) il programma andava in crash (SEGV in
# xkb_state_update_mask) alla prima pressione di un tasto/avvio. Si mettono nell'AppImage entrambe.
# Resta del sistema solo libxcb.so.1 (con libX11), come fanno gli strumenti AppImage.
XCB_EXTRA = ["libxcb-cursor.so.0", "libxcb-icccm.so.4", "libxcb-image.so.0", "libxcb-keysyms.so.1",
             "libxcb-render-util.so.0", "libxcb-util.so.1", "libxkbcommon-x11.so.0",
             "libxkbcommon.so.0",  # 0.20.5: sempre in coppia con libxkbcommon-x11 (stessa versione, vedi sotto)
             "libxcb-randr.so.0", "libxcb-render.so.0", "libxcb-shape.so.0", "libxcb-shm.so.0", "libxcb-sync.so.1",
             "libxcb-xfixes.so.0", "libxcb-xkb.so.1"]
# 0.20.5 (rapporto del 14/11 da openSUSE Leap 16: «ImportError: libgthread-2.0.so.0: cannot open shared object
# file» al caricamento di Qt, il programma non partiva). Le librerie di Qt (Core, Gui, XcbQpa) chiedono
# libgthread-2.0.so.0: Ubuntu, Debian, Fedora e Arch la danno insieme a glib, openSUSE la tiene in un pacchetto a
# parte (libgthread-2_0-0) che di serie non c'è. È una libreria minuscola e vuota da anni (g_thread_init non fa più
# niente): si mette accanto alle librerie di Qt e si appoggia alla libglib-2.0 del sistema. Licenza LGPL-2.1+.
GLIB_EXTRA = ["libgthread-2.0.so.0"]
# Le librerie del SISTEMA che Qt e le librerie aggiunte qui sopra possono chiedere: quelle che ogni distribuzione con
# un desktop installa (glibc, libstdc++, glib, zlib, X11, OpenGL, caratteri, D-Bus). Se una versione nuova di Qt ne
# chiede un'altra la costruzione si ferma (system_libs, più sotto): così ce ne accorgiamo noi, prima di chi installa.
# Una libreria nuova va messa nell'AppImage (come XCB_EXTRA e GLIB_EXTRA) oppure, se c'è davvero dappertutto, qui.
SYSTEM_OK = {
    "ld-linux-x86-64.so.2", "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",  # glibc
    "libresolv.so.2",                                                                               # glibc (rete)
    "libgcc_s.so.1", "libstdc++.so.6",                                                              # GCC
    "libglib-2.0.so.0", "libz.so.1", "libzstd.so.1",                                                # base
    "libX11.so.6", "libX11-xcb.so.1", "libxcb.so.1",                                                # X11
    "libEGL.so.1", "libGL.so.1",                                                                    # OpenGL
    "libfontconfig.so.1", "libfreetype.so.6",                                                       # caratteri
    "libdbus-1.so.3",                                                                               # D-Bus
    # solo QtNetwork (finestra unica e collegamento con MakerHub; se mancano il programma parte lo stesso)
    "libgssapi_krb5.so.2", "libbrotlidec.so.1", "libbrotlicommon.so.1",
}
# I moduli di Qt che il programma carica (QtMultimedia no: serve solo per i nomi delle telecamere, dentro un try)
QT_MODULES = ["Core", "Gui", "Widgets", "DBus", "Svg", "Network", "OpenGL", "OpenGLWidgets", "XcbQpa"]
LIB_DIRS = ["/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib/x86_64-linux-gnu"]
if os.environ.get("FLC_XCB_DIR"):  # costruzione su un sistema più nuovo: librerie prese da Ubuntu 22.04 a parte
    LIB_DIRS.insert(0, os.environ["FLC_XCB_DIR"])

TRIM_STDLIB = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data"]
PYSIDE_TOOLS = ["assistant", "designer", "linguist", "lrelease", "lupdate", "qmlformat", "qmllint", "qmlls", "rcc",
                "uic", "balsam", "balsamui", "svgtoqml", "qsb"]

APPRUN = r"""#!/bin/sh
# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
# Avvio dell'AppImage. «--mcp-server» avvia il server per Claude invece della finestra.
# -I: Python isolato, niente cartella corrente, PYTHONPATH o librerie personali al posto di quelle dell'AppImage.
HERE="$(dirname "$(readlink -f "$0")")"
PY="$HERE/usr/python/bin/python3"
if [ "$1" = "--mcp-server" ]; then
    shift
    exec "$PY" -I -m freelasercut.mcp_server "$@"
fi
exec "$PY" -I -m freelasercut "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=FreeLaserCut
Comment=Laser engraving and cutting for GRBL machines
Comment[it]=Incisione e taglio laser per macchine GRBL
Exec=AppRun %F
Icon=freelasercut
Terminal=false
Categories=Graphics;Engineering;
MimeType=application/x-freelasercut;
StartupWMClass=FreeLaserCut
"""


def find_lib(name):
    for d in LIB_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return os.path.realpath(p)
    return None


def xcb_outside(plugin, appdir):
    """Librerie xcb (tranne libxcb.so.1) che il plugin di Qt trova fuori dall'AppImage: devono essere zero."""
    out = subprocess.run(["ldd", plugin], capture_output=True, text=True).stdout
    bad = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith(("libxcb", "libxkbcommon")) or parts[0] == "libxcb.so.1":
            continue
        where = parts[2] if len(parts) > 2 and parts[1] == "=>" else "?"
        if not os.path.realpath(where).startswith(os.path.realpath(appdir) + os.sep):
            bad.append(f"{parts[0]} ({where})")
    return bad


def elf_needed(path):
    """Le librerie che un file ELF a 64 bit chiede (voci DT_NEEDED), lette dal file senza strumenti esterni.
    [] se non è un file ELF a 64 bit o non ha librerie dinamiche."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    if data[:4] != b"\x7fELF" or len(data) < 64 or data[4] != 2 or data[5] != 1:  # ELF64, little endian
        return []
    try:
        phoff, = struct.unpack_from("<Q", data, 0x20)
        phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
        loads, dyn = [], None
        for i in range(phnum):
            p_type, _fl, p_offset, p_vaddr, _pa, p_filesz, _mem, _al = struct.unpack_from("<IIQQQQQQ", data,
                                                                                         phoff + i * phentsize)
            if p_type == 1:  # PT_LOAD
                loads.append((p_vaddr, p_offset, p_filesz))
            elif p_type == 2:  # PT_DYNAMIC
                dyn = (p_offset, p_filesz)
        if dyn is None:
            return []
        names, strtab = [], None
        for off in range(dyn[0], dyn[0] + dyn[1], 16):
            tag, val = struct.unpack_from("<qQ", data, off)
            if tag == 0:
                break
            if tag == 1:  # DT_NEEDED
                names.append(val)
            elif tag == 5:  # DT_STRTAB
                strtab = val
        if strtab is None:
            return []
        base = next((o + strtab - v for v, o, size in loads if v <= strtab < v + size), None)
        if base is None:
            return []
        return [data[base + n:data.index(b"\0", base + n)].decode("utf-8", "replace") for n in names]
    except (struct.error, ValueError, OverflowError, IndexError, MemoryError):  # file rovinato
        return []


def system_libs(roots, inside):
    """Le librerie che i file `roots`, e a catena quelle che loro chiedono, vanno a prendere FUORI dall'AppImage.
    inside: le cartelle dell'AppImage dove Qt cerca le sue librerie (Qt/lib: hanno tutte RUNPATH=$ORIGIN).
    -> {nome della libreria di sistema: nome del file che la chiede}."""
    index = {}
    for d in inside:
        for f in sorted(os.listdir(d)):
            index.setdefault(f, os.path.join(d, f))
    seen, todo, outside = set(), list(roots), {}
    while todo:
        p = todo.pop()
        real = os.path.realpath(p)
        if real in seen:
            continue
        seen.add(real)
        for name in elf_needed(real):
            if name in index:
                todo.append(index[name])
            else:
                outside.setdefault(name, os.path.basename(p))
    return outside


def qt_roots(pyside):
    """I file di Qt da cui parte il controllo: le librerie dei moduli usati e il plugin xcb."""
    qt_lib = os.path.join(pyside, "Qt", "lib")
    roots = [os.path.join(qt_lib, f"libQt6{m}.so.6") for m in QT_MODULES]
    roots.append(os.path.join(pyside, "Qt", "plugins", "platforms", "libqxcb.so"))
    return [r for r in roots if os.path.exists(r)]


def unexpected_system_libs(pyside):
    """Le librerie di sistema chieste da Qt che non sono fra quelle previste (SYSTEM_OK): devono essere zero.
    -> ["libreria (chiesta da file)", …]"""
    out = system_libs(qt_roots(pyside), [os.path.join(pyside, "Qt", "lib")])
    return [f"{name} (chiesta da {who})" for name, who in sorted(out.items()) if name not in SYSTEM_OK]


def glibc_needed(folder):
    """La versione di glibc più alta richiesta dai file ELF della cartella (dai simboli GLIBC_x.y)."""
    pat = re.compile(rb"GLIBC_(2\.\d+)")
    worst, who = (2, 0), "-"
    for d, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(d, f)
            if os.path.islink(p) or not (f.endswith(".so") or ".so." in f or os.access(p, os.X_OK)):
                continue
            try:
                with open(p, "rb") as fh:
                    if fh.read(4) != b"\x7fELF":
                        continue
                    data = fh.read()
            except OSError:
                continue
            for m in set(pat.findall(data)):
                v = tuple(int(x) for x in m.decode().split("."))
                if v > worst:
                    worst, who = v, os.path.relpath(p, folder)
    return worst, who


def main():
    if not sys.platform.startswith("linux"):
        sys.exit("La versione per Linux si costruisce su Linux (anche su GitHub: workflow installatore.yml).")
    ver = version()
    step(f"FreeLaserCut {ver}: preparo {APPDIR}")
    shutil.rmtree(APPDIR, ignore_errors=True)
    os.makedirs(CACHE, exist_ok=True)
    usr = os.path.join(APPDIR, "usr")
    os.makedirs(usr)

    step(f"Python {PY_VERSION} per Linux")
    archive = os.path.join(CACHE, os.path.basename(PY_URL).replace("+", "_"))
    if not os.path.exists(archive):
        scarica(PY_URL, archive)
    with tarfile.open(archive) as tf:
        tf.extractall(usr, filter="data") if sys.version_info >= (3, 12) else tf.extractall(usr)
    py_home = os.path.join(usr, "python")
    py = os.path.join(py_home, "bin", "python3")
    lib = os.path.join(py_home, "lib", f"python{PY_MINOR}")
    for d in TRIM_STDLIB:
        shutil.rmtree(os.path.join(lib, d), ignore_errors=True)
    for d in ("include", "share"):
        shutil.rmtree(os.path.join(py_home, d), ignore_errors=True)
    for f in glob.glob(os.path.join(py_home, "lib", "libtcl*")) + glob.glob(os.path.join(py_home, "lib", "libtk*")):
        os.remove(f)
    for d in sum((glob.glob(os.path.join(py_home, "lib", x)) for x in ("tcl*", "tk*", "itcl*", "thread*")), []):
        shutil.rmtree(d, ignore_errors=True)

    step(f"Librerie (ruote per Linux, Python {PY_MINOR})")
    site = os.path.join(lib, "site-packages")
    plat = [a for p in PLATFORMS for a in ("--platform", p)]
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", site,
                           *plat, "--python-version", PY_MINOR, "--implementation", "cp",
                           "--abi", "cp" + PY_MINOR.replace(".", ""), "--only-binary=:all:", "--upgrade",
                           *LINUX_PACKAGES])
    for d in ("bin", "share", "test", "tests"):
        shutil.rmtree(os.path.join(site, d), ignore_errors=True)
    for d in TRIM_PYGAME:
        shutil.rmtree(os.path.join(site, "pygame", d), ignore_errors=True)
    pyside = os.path.join(site, "PySide6")
    for d in TRIM_PYSIDE + ["scripts"]:  # scripts: strumenti di pubblicazione di Qt (Android, Nuitka…), non servono
        shutil.rmtree(os.path.join(pyside, d), ignore_errors=True)
    for name in PYSIDE_TOOLS:
        p = os.path.join(pyside, name)
        if os.path.isfile(p):
            os.remove(p)
    # la cartella usr/app entra nel percorso di Python da sola
    with open(os.path.join(site, "freelasercut_app.pth"), "w", encoding="utf-8") as fh:
        fh.write("../../../../app\n")

    step("Librerie xcb e libgthread per Qt")
    qt_lib = os.path.join(pyside, "Qt", "lib")
    missing = []
    for name in XCB_EXTRA + GLIB_EXTRA:
        src = find_lib(name)
        if src is None:
            missing.append(name)
            continue
        shutil.copy2(src, os.path.join(qt_lib, name))
        print("  +", name)
    if missing:
        sys.exit("librerie xcb non trovate (o libgthread) sul sistema di costruzione: " + ", ".join(missing))
    outside = xcb_outside(os.path.join(pyside, "Qt", "plugins", "platforms", "libqxcb.so"), APPDIR)
    if outside:
        sys.exit("il plugin xcb di Qt prende ancora dal sistema: " + ", ".join(outside))
    print("  il plugin xcb usa solo libxcb.so.1 del sistema; le altre librerie xcb sono nell'AppImage")

    step("Librerie che Qt prende dal sistema")
    if len(qt_roots(pyside)) < len(QT_MODULES) + 1:
        sys.exit("mancano librerie di Qt nell'AppDir: " + ", ".join(
            m for m in QT_MODULES if not os.path.exists(os.path.join(qt_lib, f"libQt6{m}.so.6"))))
    extra = unexpected_system_libs(pyside)
    if extra:
        sys.exit("Qt chiede al sistema librerie non previste: " + ", ".join(extra) + ".\nSu una distribuzione che non "
                 "le installa di serie il programma non partirebbe (successo con libgthread su openSUSE). Vanno "
                 "messe nell'AppImage (XCB_EXTRA, GLIB_EXTRA) oppure, se ci sono davvero dappertutto, in SYSTEM_OK.")
    print("  solo librerie di base (glibc, libstdc++, glib, zlib, X11, OpenGL, caratteri, D-Bus)")

    step("Programma, licenze, README")
    app = os.path.join(usr, "app")
    shutil.copytree(os.path.join(ROOT, "freelasercut"), os.path.join(app, "freelasercut"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    doc = os.path.join(usr, "share", "doc", "freelasercut")
    os.makedirs(doc)
    for f in ("LICENSE", "README.md", "LICENZE-TERZE-PARTI.md", "CHANGELOG.md"):
        shutil.copy2(os.path.join(ROOT, f), doc)
    shutil.copytree(os.path.join(ROOT, "licenze-terze-parti"), os.path.join(doc, "licenze-terze-parti"))

    step("Compilo i .pyc (l'AppImage è in sola lettura: senza, ogni avvio ricompilerebbe tutto)")
    subprocess.check_call([py, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash", app])
    # librerie: qualche file di modello non è Python vero e non si compila; basta un avviso
    if subprocess.call([py, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash", site, lib],
                       stdout=subprocess.DEVNULL):
        print("  avviso: alcuni file delle librerie non si compilano (modelli, non usati dal programma)")

    step("AppRun, .desktop, icona")
    apprun = os.path.join(APPDIR, "AppRun")
    with open(apprun, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(APPRUN)
    os.chmod(apprun, 0o755)
    with open(os.path.join(APPDIR, "freelasercut.desktop"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(DESKTOP)
    icon = os.path.join(ROOT, "freelasercut", "assets", "logo.png")
    shutil.copy2(icon, os.path.join(APPDIR, "freelasercut.png"))
    icons = os.path.join(usr, "share", "icons", "hicolor", "256x256", "apps")
    os.makedirs(icons)
    shutil.copy2(icon, os.path.join(icons, "freelasercut.png"))
    os.symlink("freelasercut.png", os.path.join(APPDIR, ".DirIcon"))

    step("Prova veloce del Python impacchettato")
    out = subprocess.check_output([py, "-I", "-c", "import freelasercut, numpy, cv2, PySide6, serial, numba;"
                                   "print(freelasercut.__version__, freelasercut.__file__)"], text=True, cwd=APPDIR).strip()
    if not out.split(" ", 1)[-1].startswith(os.path.join(app, "freelasercut")):
        sys.exit(f"il programma non viene dall'AppDir: {out!r}")
    out = out.split(" ", 1)[0]
    if out != ver:
        sys.exit(f"versione sbagliata nell'AppDir: {out!r} invece di {ver!r}")
    print("  ok,", out)

    step(f"Controllo glibc (al massimo {GLIBC_MAX[0]}.{GLIBC_MAX[1]})")
    worst, who = glibc_needed(APPDIR)
    print(f"  serve glibc {worst[0]}.{worst[1]} ({who})")
    if worst > GLIBC_MAX:
        sys.exit(f"{who} chiede glibc {worst[0]}.{worst[1]}: l'AppImage non partirebbe sulle distribuzioni previste")

    step("AppImage")
    tool = os.path.join(CACHE, "appimagetool-x86_64.AppImage")
    if not os.path.exists(tool):
        scarica(APPIMAGETOOL_URL, tool)
    os.chmod(tool, os.stat(tool).st_mode | stat.S_IXUSR)
    target = os.path.join(BUILD, f"FreeLaserCut-{ver}-x86_64.AppImage")
    if os.path.exists(target):
        os.remove(target)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")  # funziona anche senza FUSE (server, container)
    subprocess.check_call([tool, "--no-appstream", APPDIR, target], env=env)
    size = os.path.getsize(target)
    step(f"Pronto: {target} ({size / 1e6:.0f} MB)")
    if not re.match(r"^FreeLaserCut-\d+(\.\d+)*-x86_64\.AppImage$", os.path.basename(target)):
        sys.exit("nome del file diverso da quello che cerca l'aggiornamento")


if __name__ == "__main__":
    main()
