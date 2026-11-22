# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Costruisce la versione per macOS di FreeLaserCut (anteprima): build/FreeLaserCut-<versione>-macOS-<arch>.dmg.

Uso (su un Mac, con Python 3.10 o più recente e internet; sulle macchine Mac di GitHub lo fa mac.yml):

    python build/prepara_mac.py [--arch arm64|x86_64]

Stesso schema della versione per Linux (prepara_appimage.py), stesso Python e stesse librerie:
1. scarica Python per macOS (python-build-standalone, stessa versione dell'installatore Windows);
2. installa le librerie con quel Python (ruote ufficiali da PyPI; OpenCV «headless», senza una sua copia di Qt);
3. copia il programma fra le librerie e compila i .pyc;
4. scrive FreeLaserCut.app: Info.plist (con i permessi per camera e rete locale, senza i quali macOS chiude il
   programma o non gli lascia vedere i laser in Wi-Fi), avvio, icona;
5. firma «ad hoc» tutto il pacchetto (sui Mac con Apple Silicon un programma senza nessuna firma non parte) e lo
   mette in un .dmg con il collegamento ad Applicazioni.

Senza un certificato Apple Developer il programma NON è notarizzato: al primo avvio macOS lo blocca e va aperto da
Impostazioni di Sistema → Privacy e sicurezza → «Apri comunque» (lo spiega il LEGGIMI nel .dmg).
"""
import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
sys.path.insert(0, BUILD)
from prepara_installer import CACHE, PACKAGES, PY_RELEASE, PY_VERSION, TRIM_PYGAME, TRIM_PYSIDE, TRIM_SITE, scarica, step, version  # noqa: E402

PY_MINOR = ".".join(PY_VERSION.split(".")[:2])  # 3.14
ARCH_PBS = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}
# OpenCV senza la sua copia di Qt e senza finestre sue (come su Linux): la camera la legge lo stesso
MAC_PACKAGES = [p.replace("opencv-python==", "opencv-python-headless==") for p in PACKAGES]
# numba non esiste più per i Mac Intel (dalla 0.63 solo Apple Silicon): lì il programma usa le stesse funzioni in
# Python puro (più lente su foto grandi e vettorizzazione), come quando numba manca
NO_INTEL = ("numba==",)
TRIM_STDLIB = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data"]
PYSIDE_TOOLS = ["scripts", "assistant", "designer", "linguist", "lrelease", "lupdate", "qmlformat", "qmllint", "qmlls", "rcc",
                "uic", "balsam", "balsamui", "svgtoqml", "qsb", "Assistant.app", "Designer.app", "Linguist.app"]
BUNDLE_ID = "io.github.fringuello79.freelasercut"
MIN_MACOS = "14.4"  # 0.22.0: le librerie di Qt 6.12 (PySide6) sono costruite per macOS 14.4 (Sonoma): sul 13 il programma si apriva e si chiudeva (mail di Michele, 21/11)

# Avvio: il programma gira con una copia di Python dentro Contents/MacOS, così macOS lo vede come «FreeLaserCut»
# (nome nella barra dei menu e nel Dock, icona) e non come «python3». -I: Python isolato, niente PYTHONPATH o librerie
# personali al posto di quelle del pacchetto. «--mcp-server» avvia il server per Claude invece della finestra.
LAUNCHER = r"""#!/bin/sh
# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/FreeLaserCut-python"
# la cache di numba fuori dal pacchetto (firmato: non va cambiato dopo)
export NUMBA_CACHE_DIR="$HOME/Library/Caches/FreeLaserCut/numba"
if [ "$1" = "--mcp-server" ]; then
    shift
    exec "$PY" -I -B -m freelasercut.mcp_server "$@"
fi
exec "$PY" -I -B -m freelasercut "$@"
"""

LEGGIMI = """FreeLaserCut per macOS — ANTEPRIMA
=================================

Installazione: trascina FreeLaserCut nella cartella Applicazioni.

Primo avvio (una volta sola). FreeLaserCut è gratuito e non ha un certificato Apple a pagamento, quindi macOS lo
blocca la prima volta:
1. apri FreeLaserCut: macOS dice che non può verificarlo; premi «Fine» (non «Sposta nel cestino»);
2. apri Impostazioni di Sistema → Privacy e sicurezza, scorri in basso e premi «Apri comunque» accanto a FreeLaserCut;
3. conferma con «Apri» (e la password del Mac se la chiede).
Dalle volte successive si apre normalmente.

È un'anteprima: le prove automatiche girano su Mac veri, ma nessuno l'ha ancora usata con un laser e una camera
veri su macOS. Se qualcosa non va: Aiuto → Invia un rapporto all'assistenza.

Laser con il cavo USB: la porta si chiama di solito /dev/cu.usbserial-… o /dev/cu.wchusbserial-…
Alla prima apertura della camera, e del collegamento a un laser in Wi-Fi, macOS chiede il permesso: rispondi «Consenti».

-------------------------------------------------------------------------------------------------------------------
FreeLaserCut for macOS — PREVIEW. Drag FreeLaserCut to Applications. The first time macOS blocks it (no paid Apple
certificate): close the message, open System Settings → Privacy & Security and press «Open Anyway».
"""


def info_plist(ver):
    return {
        "CFBundleName": "FreeLaserCut",
        "CFBundleDisplayName": "FreeLaserCut",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "FreeLaserCut",
        "CFBundleIconFile": "FreeLaserCut.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": ver,
        "CFBundleVersion": ver,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en", "it", "es", "fr", "pt"],
        "LSMinimumSystemVersion": MIN_MACOS,
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHumanReadableCopyright": "© 2026 fringuello79 — GPL-3.0-or-later",
        # senza queste due frasi macOS chiude il programma alla prima camera / non lascia vedere i laser in rete
        "NSCameraUsageDescription": "FreeLaserCut uses the camera to show the laser bed and to place your designs "
                                    "on the material.",
        "NSLocalNetworkUsageDescription": "FreeLaserCut connects to laser engravers on your local network (Wi-Fi).",
        # macOS 14 e successivi: anche l'iPhone come camera (Continuità), senza l'avviso nel registro
        "NSCameraUseContinuityCameraDeviceType": True,
        # 0.20.8: niente App Nap. Con la finestra coperta o ridotta a icona macOS rallenta i programmi «in pausa»:
        # durante un lavoro le righe al laser devono continuare ad arrivare in tempo
        "LSAppNapIsDisabled": True,
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "FreeLaserCut project",
            "CFBundleTypeExtensions": ["flcut"],
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Owner",
        }],
    }


def make_icns(png, dest):
    """Icona .icns dal logo PNG con gli strumenti di macOS (sips, iconutil). -> True se riuscita."""
    if not shutil.which("sips") or not shutil.which("iconutil") or not os.path.exists(png):
        return False
    iconset = dest[:-5] + ".iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(["sips", "-z", str(px), str(px), png, "--out", os.path.join(iconset, name)],
                           check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", dest], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", choices=sorted(ARCH_PBS), default="arm64" if platform.machine() == "arm64" else "x86_64")
    ap.add_argument("--no-dmg", action="store_true", help="solo FreeLaserCut.app (prove)")
    args = ap.parse_args()
    ver = version()
    out_dir = os.path.join(BUILD, "mac")
    app = os.path.join(out_dir, "FreeLaserCut.app")
    contents = os.path.join(app, "Contents")
    res = os.path.join(contents, "Resources")
    step(f"FreeLaserCut {ver} per macOS ({args.arch}): preparo {app}")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(os.path.join(contents, "MacOS"))
    os.makedirs(res)
    os.makedirs(CACHE, exist_ok=True)

    step("Python per macOS")
    url = (f"https://github.com/astral-sh/python-build-standalone/releases/download/{PY_RELEASE}/"
           f"cpython-{PY_VERSION}+{PY_RELEASE}-{ARCH_PBS[args.arch]}-install_only_stripped.tar.gz")
    archive = os.path.join(CACHE, os.path.basename(url).replace("+", "_"))
    if not os.path.exists(archive):
        scarica(url, archive)
    with tarfile.open(archive) as tf:
        tf.extractall(res, filter="data") if sys.version_info >= (3, 12) else tf.extractall(res)
    py_dir = os.path.join(res, "python")
    py = os.path.join(py_dir, "bin", f"python{PY_MINOR}")
    stdlib = os.path.join(py_dir, "lib", f"python{PY_MINOR}")
    for d in TRIM_STDLIB:
        shutil.rmtree(os.path.join(stdlib, d), ignore_errors=True)

    step("Librerie (ruote per macOS)")
    if platform.machine() != args.arch:
        raise SystemExit(f"Questo Mac è {platform.machine()}: per {args.arch} serve un Mac {args.arch} (pip usa il "
                         "Python del pacchetto, che deve poter girare qui).")
    site = os.path.join(stdlib, "site-packages")
    pkgs = [p for p in MAC_PACKAGES if not (args.arch == "x86_64" and p.startswith(NO_INTEL))]
    subprocess.check_call([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
                           "--only-binary=:all:", "--upgrade", *pkgs])
    for d in TRIM_SITE:
        shutil.rmtree(os.path.join(site, d), ignore_errors=True)
    for d in TRIM_PYGAME:
        shutil.rmtree(os.path.join(site, "pygame", d), ignore_errors=True)
    pyside = os.path.join(site, "PySide6")
    for d in TRIM_PYSIDE + PYSIDE_TOOLS:
        p = os.path.join(pyside, d)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.remove(p) if os.path.exists(p) else None)
    # Qt per Mac arriva «universale» (Apple Silicon e Intel insieme): si tiene solo il processore di questo pacchetto,
    # quasi metà del peso
    if shutil.which("lipo"):
        thin = 0
        for d, _dirs, files in os.walk(site):
            for f in files:
                path = os.path.join(d, f)
                if os.path.islink(path):
                    continue
                r = subprocess.run(["lipo", "-archs", path], capture_output=True, text=True)
                archs = r.stdout.split() if r.returncode == 0 else []
                if len(archs) > 1 and args.arch in archs:
                    subprocess.check_call(["lipo", path, "-thin", args.arch, "-output", path])
                    thin += 1
        print(f"librerie ridotte al solo {args.arch}: {thin}")
    # pip non serve al programma (e non deve cambiare il pacchetto firmato)
    for name in os.listdir(site):
        if name == "pip" or name.startswith("pip-"):
            shutil.rmtree(os.path.join(site, name), ignore_errors=True)

    step("Programma, licenze, README")
    # il programma va fra le librerie: Python lo trova anche isolato (-I) e anche dalla copia in Contents/MacOS, che
    # vede la libreria standard attraverso il collegamento Contents/lib (un .pth relativo lì sbaglierebbe cartella)
    app_dir = os.path.join(site, "freelasercut")
    shutil.copytree(os.path.join(ROOT, "freelasercut"), app_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("LICENSE", "README.md", "LICENZE-TERZE-PARTI.md", "CHANGELOG.md"):
        shutil.copy2(os.path.join(ROOT, f), res)
    shutil.copytree(os.path.join(ROOT, "licenze-terze-parti"), os.path.join(res, "licenze-terze-parti"))
    # .pyc compilati ora: il pacchetto firmato non va più cambiato (Python non deve scriverli dopo)
    subprocess.check_call([py, "-m", "compileall", "-q", "-j", "0", app_dir])  # il programma: deve riuscire tutto
    # le librerie: qualche file di modello non è Python vero (si compila quello che si può, come fa pip)
    subprocess.call([py, "-m", "compileall", "-q", "-j", "0", stdlib], stdout=subprocess.DEVNULL)

    step("FreeLaserCut.app")
    macos = os.path.join(contents, "MacOS")
    shutil.copy2(py, os.path.join(macos, "FreeLaserCut-python"))
    # Python cerca la sua libreria standard in ../lib accanto all'eseguibile: Contents/lib -> Resources/python/lib
    os.symlink("Resources/python/lib", os.path.join(contents, "lib"))
    launcher = os.path.join(macos, "FreeLaserCut")
    with open(launcher, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(LAUNCHER)
    os.chmod(launcher, 0o755)
    with open(os.path.join(contents, "Info.plist"), "wb") as fh:
        plistlib.dump(info_plist(ver), fh)
    with open(os.path.join(contents, "PkgInfo"), "w", encoding="ascii") as fh:
        fh.write("APPL????")
    logo = os.path.join(ROOT, "freelasercut", "assets", "logo.png")
    if not make_icns(logo, os.path.join(res, "FreeLaserCut.icns")):
        print("ATTENZIONE: icona .icns non creata (servono sips e iconutil di macOS)")

    if shutil.which("codesign"):
        step("Firma ad hoc (nessun certificato Apple: il programma non è notarizzato)")
        subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", app])
        subprocess.check_call(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    else:
        print("ATTENZIONE: codesign non trovato (non sei su un Mac): pacchetto non firmato")

    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(app) for f in fs
               if not os.path.islink(os.path.join(d, f)))
    step(f"FreeLaserCut.app pronto: {size / 1e6:.0f} MB")
    if args.no_dmg:
        return
    step("Immagine disco .dmg")
    stage = os.path.join(out_dir, "dmg")
    os.makedirs(stage)
    shutil.move(app, os.path.join(stage, "FreeLaserCut.app"))
    os.symlink("/Applications", os.path.join(stage, "Applicazioni"))
    with open(os.path.join(stage, "LEGGIMI - primo avvio.txt"), "w", encoding="utf-8") as fh:
        fh.write(LEGGIMI)
    dmg = os.path.join(BUILD, f"FreeLaserCut-{ver}-macOS-{args.arch}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    make_dmg(["hdiutil", "create", "-volname", f"FreeLaserCut {ver}", "-srcfolder", stage, "-ov", "-format", "UDZO",
              dmg])
    shutil.move(os.path.join(stage, "FreeLaserCut.app"), app)  # resta anche fuori, per la prova di avvio
    step(f"Pronto: {dmg}")


def make_dmg(cmd, tries=5, wait=15.0, run=subprocess.call, sleep=None):
    """0.20.8: hdiutil sui Mac di GitHub a volte risponde «create failed - Resource busy» (con la 0.20.7 il .dmg per
    Intel non è uscito per questo): si riprova qualche volta, aspettando un po' fra un tentativo e l'altro."""
    import time

    sleep = sleep or time.sleep
    for i in range(1, tries + 1):
        code = run(cmd)
        if code == 0:
            return i
        print(f"hdiutil non è riuscito (codice {code}), tentativo {i} di {tries}", flush=True)
        if i < tries:
            sleep(wait * i)
    raise subprocess.CalledProcessError(code, cmd)


if __name__ == "__main__":
    main()
