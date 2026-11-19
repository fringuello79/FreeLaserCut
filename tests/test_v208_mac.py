# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.8 (anteprima): versione per macOS. Le prove vere sono sui Mac di GitHub (mac.yml: costruzione del pacchetto,
avvio con la finestra vera, server per Claude); qui, su qualsiasi sistema, i pezzi scritti apposta per il Mac:
- pacchetto (build/prepara_mac.py): Info.plist con nome, identificativo, versione, macOS minimo e i due permessi
  (camera e rete locale) senza i quali macOS chiude il programma o non gli lascia vedere i laser in Wi-Fi; avvio
  isolato (-I), senza scrivere nel pacchetto firmato (-B, cache di numba fuori); numba tolto solo per i Mac Intel;
  OpenCV senza la sua copia di Qt; LEGGIMI del primo avvio («Apri comunque»);
- permesso della camera chiesto con Qt dal filo della finestra (OpenCV dal suo filo non può): concesso, negato, da
  chiedere (la ricerca aspetta la risposta e riparte da sola), e niente di tutto questo fuori dal Mac;
- avviso di errore all'avvio con osascript, con virgolette e barre nel testo;
- prova di avvio: sui Mac Intel numba manca e non è un errore; altrove sì.
Uso: python tests/test_v208_mac.py
"""
import os
import plistlib
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "build"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


print("--- pacchetto")
import prepara_installer  # noqa: E402
import prepara_mac as pm  # noqa: E402

info = pm.info_plist("9.8.7")
check("Info.plist: nome, eseguibile, identificativo e versione", info["CFBundleName"] == "FreeLaserCut"
      and info["CFBundleExecutable"] == "FreeLaserCut" and info["CFBundleIdentifier"].startswith("io.github.fringuello79")
      and info["CFBundleShortVersionString"] == "9.8.7" and info["CFBundlePackageType"] == "APPL")
check("Info.plist: permessi di camera e rete locale con la loro spiegazione",
      len(info.get("NSCameraUsageDescription", "")) > 20 and len(info.get("NSLocalNetworkUsageDescription", "")) > 20)
check("Info.plist: macOS 13 o più recente (come Qt 6.12), schermi Retina, progetti .flcut",
      info["LSMinimumSystemVersion"] == "13.0" and info["NSHighResolutionCapable"] is True
      and info["CFBundleDocumentTypes"][0]["CFBundleTypeExtensions"] == ["flcut"])
check("Info.plist: niente App Nap (con la finestra coperta il lavoro al laser non rallenta)",
      info.get("LSAppNapIsDisabled") is True)
check("Info.plist: si scrive come file plist valido", plistlib.loads(plistlib.dumps(info)) == info)
L = pm.LAUNCHER
check("avvio: Python isolato (-I), senza scrivere .pyc nel pacchetto (-B), dalla copia in Contents/MacOS",
      L.startswith("#!/bin/sh") and '"$HERE/FreeLaserCut-python"' in L and L.count("-I -B -m") == 2
      and 'exec "$PY" -I -B -m freelasercut "$@"' in L)
check("avvio: «--mcp-server» avvia il server per Claude", '"$1" = "--mcp-server"' in L
      and "-m freelasercut.mcp_server" in L)
check("avvio: la cache di numba fuori dal pacchetto firmato", "NUMBA_CACHE_DIR" in L and "Library/Caches" in L)
check("librerie: le stesse versioni dell'installatore Windows, OpenCV senza la sua copia di Qt",
      len(pm.MAC_PACKAGES) == len(prepara_installer.PACKAGES)
      and any(p.startswith("opencv-python-headless==") for p in pm.MAC_PACKAGES)
      and not any(p.startswith("opencv-python==") for p in pm.MAC_PACKAGES))
check("numba tolto solo per i Mac Intel (non esiste più per loro)", pm.NO_INTEL == ("numba==",)
      and any(p.startswith("numba==") for p in pm.MAC_PACKAGES))
check("Python per Mac: stessa versione e stessa uscita dell'installatore Windows",
      pm.PY_MINOR == ".".join(prepara_installer.PY_VERSION.split(".")[:2]) and set(pm.ARCH_PBS) == {"arm64", "x86_64"})
check("LEGGIMI: primo avvio con «Apri comunque», in italiano e in inglese, porte USB e permessi",
      "Apri comunque" in pm.LEGGIMI and "Open Anyway" in pm.LEGGIMI and "/dev/cu." in pm.LEGGIMI
      and "Consenti" in pm.LEGGIMI)
check("niente icona senza gli strumenti di macOS: lo dice e va avanti", pm.make_icns("/non/esiste.png", "/tmp/x.icns")
      is False)

print("--- permesso della camera")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut import camera  # noqa: E402

check("fuori dal Mac non si chiede niente", sys.platform == "darwin" or camera.mac_camera_permission() == "n/a")
import PySide6.QtCore as QC  # noqa: E402


class FakeApp:
    def __init__(self, status):
        self.status = status
        self.asked = []

    def checkPermission(self, perm):
        return self.status

    def requestPermission(self, perm, ctx, fn):
        self.asked.append((type(perm).__name__, ctx is self))
        self.fn = fn


import plistlib  # noqa: E402

tmp_app = tempfile.mkdtemp()
macos_dir = os.path.join(tmp_app, "FreeLaserCut.app", "Contents", "MacOS")
os.makedirs(macos_dir)
exe = os.path.join(macos_dir, "FreeLaserCut-python")
open(exe, "w").close()
plist = os.path.join(tmp_app, "FreeLaserCut.app", "Contents", "Info.plist")
with open(plist, "wb") as fh:
    plistlib.dump({"CFBundleName": "FreeLaserCut", "NSCameraUsageDescription": "camera"}, fh)
check("dentro FreeLaserCut.app con la frase della camera: il permesso si chiede", camera.mac_app_bundle(exe))
with open(plist, "wb") as fh:
    plistlib.dump({"CFBundleName": "FreeLaserCut"}, fh)
check("…senza la frase nell'Info.plist: no (macOS non saprebbe cosa dire)", not camera.mac_app_bundle(exe))
check("programma dai sorgenti o prove (python fuori da un .app): no", not camera.mac_app_bundle(sys.executable)
      or ".app" in os.path.realpath(sys.executable))
check("cartella che non c'è: no, senza errori", not camera.mac_app_bundle("/non/esiste/X.app/Contents/MacOS/x"))

# 0.20.8: QMediaDevices su macOS solo dal filo della finestra (fuori, errore di memoria sul Mac di GitHub)
import threading  # noqa: E402
import types  # noqa: E402

calls = []


class FakeDev:
    def __init__(self, n):
        self.n = n

    def description(self):
        return self.n


class FakeQMD:
    @staticmethod
    def videoInputs():
        calls.append(threading.current_thread() is threading.main_thread())
        return [FakeDev("FaceTime HD Camera"), FakeDev("Falcon camera")]


real_mm = sys.modules.get("PySide6.QtMultimedia")
real_plat0 = sys.platform
try:
    sys.modules["PySide6.QtMultimedia"] = types.SimpleNamespace(QMediaDevices=FakeQMD)
    sys.platform = "darwin"
    got = camera.usb_camera_names()
    check("Mac, filo della finestra: i nomi delle camere si leggono", got == {0: "FaceTime HD Camera", 1: "Falcon camera"}
          and calls == [True], (got, calls))
    calls.clear()
    out = {}
    th = threading.Thread(target=lambda: out.update(r=camera.usb_camera_names()))
    th.start()
    th.join(10)
    check("Mac, altro filo: QMediaDevices non si tocca (niente chiusura), nessun nome", out.get("r") == {} and calls == [],
          (out, calls))
    sys.platform = "linux"
    calls.clear()
    out = {}
    th = threading.Thread(target=lambda: out.update(r=camera.usb_camera_names()))
    th.start()
    th.join(10)
    check("Linux, altro filo: come prima", len(out.get("r") or {}) == 2 and calls == [False], (out, calls))
finally:
    sys.platform = real_plat0
    if real_mm is not None:
        sys.modules["PySide6.QtMultimedia"] = real_mm
    else:
        sys.modules.pop("PySide6.QtMultimedia", None)
src_panel = open(os.path.join(os.path.dirname(camera.__file__), "camera_panel.py"), encoding="utf-8").read()
check("pannello Camera: su Mac i nomi si leggono prima di partire con la ricerca e il filo usa quelli",
      src_panel.index('mac_names = camera_mod.usb_camera_names() if sys.platform == "darwin" else None')
      < src_panel.index("def work():")
      and "names = mac_names if mac_names is not None else camera_mod.usb_camera_names()" in src_panel)

real_platform, real_instance = sys.platform, QC.QCoreApplication.instance
real_bundle = camera.mac_app_bundle
PS = QC.Qt.PermissionStatus
try:
    sys.platform = "darwin"
    camera.mac_app_bundle = lambda executable=None: False
    check("Mac fuori dal pacchetto .app: non si chiede niente, si prova come sempre",
          camera.mac_camera_permission() == "n/a")
    camera.mac_app_bundle = lambda executable=None: True
    fa = FakeApp(PS.Granted)
    QC.QCoreApplication.instance = staticmethod(lambda: fa)
    check("Mac, permesso già dato: si cerca subito", camera.mac_camera_permission() == "granted" and not fa.asked)
    fa.status = PS.Denied
    check("Mac, permesso negato: lo dice (nessuna domanda)", camera.mac_camera_permission() == "denied" and not fa.asked)
    fa.status = PS.Undetermined
    got = []
    r = camera.mac_camera_permission(lambda ok: got.append(ok))
    check("Mac, prima volta: macOS chiede, con il permesso della camera e il programma come contesto",
          r == "asked" and fa.asked == [("QCameraPermission", True)] and not got)
    fa.status = PS.Granted
    fa.fn(None)
    check("…risposta «Consenti»: si riparte da soli", got == [True])
    fa.status = PS.Denied
    fa.fn(None)
    check("…risposta «Non consentire»: lo si sa", got == [True, False])
    check("la richiesta di OpenCV dal suo filo resta spenta sul Mac (la variabile si mette prima di aprire le camere)",
          "OPENCV_AVFOUNDATION_SKIP_AUTH" in open(camera.__file__, encoding="utf-8").read()
          and 'if sys.platform == "darwin":\n' in open(camera.__file__, encoding="utf-8").read())
finally:
    sys.platform = real_platform
    QC.QCoreApplication.instance = real_instance
    camera.mac_app_bundle = real_bundle

print("--- avviso di errore all'avvio e prova di avvio")
from freelasercut import startup_guard  # noqa: E402

cmd = startup_guard.mac_dialog('Errore "grave" in C:\\cartella')
check("avviso con osascript: virgolette e barre del testo protette",
      cmd[:2] == ["osascript", "-e"] and cmd[2] == 'display alert "FreeLaserCut" message "Errore \\"grave\\" in '
      'C:\\\\cartella" as critical', cmd)
src = open(os.path.join(ROOT, "freelasercut", "startup_guard.py"), encoding="utf-8").read()
check("l'avviso del Mac si usa solo sul Mac", 'if sys.platform == "darwin":' in src and "cmd = mac_dialog(text)" in src)
st = open(os.path.join(ROOT, "freelasercut", "selftest.py"), encoding="utf-8").read()
check("prova di avvio: numba può mancare solo sui Mac Intel",
      'mod == "numba" and sys.platform == "darwin" and platform.machine() == "x86_64"' in st)
wf = open(os.path.join(ROOT, ".github", "workflows", "mac.yml"), encoding="utf-8").read()
check("su GitHub: Apple Silicon e Intel, prova di avvio Cocoa, server per Claude, .dmg da scaricare",
      "macos-15" in wf and "macos-15-intel" in wf and "piattaforma Qt cocoa" in wf and "--mcp-server" in wf
      and "upload-artifact" in wf)

# 0.20.8: hdiutil «Resource busy» sui Mac di GitHub (il .dmg Intel della 0.20.7 non era uscito): si riprova
codes, waits = iter([1, 1, 0]), []
check(".dmg: hdiutil che non riesce si riprova (qui al terzo tentativo), aspettando sempre di più",
      pm.make_dmg(["hdiutil"], run=lambda c: next(codes), sleep=waits.append) == 3 and waits == [15.0, 30.0])
try:
    pm.make_dmg(["hdiutil"], tries=2, run=lambda c: 1, sleep=lambda s: None)
    gave_up = False
except subprocess.CalledProcessError:
    gave_up = True
check("…e dopo l'ultimo tentativo si ferma con l'errore", gave_up)
from freelasercut import __codename__, __version__, display_version, splash as _splash  # noqa: E402

check("0.20.8: la schermata di avvio e la barra del titolo mostrano il nome della versione («0.20.VI»), "
      "il numero resta per gli aggiornamenti", display_version() == __codename__ == "0.20.VI" and __version__[0].isdigit()
      and "display_version()" in open(_splash.__file__, encoding="utf-8").read())

ok = sum(results)
print(f"\n{ok}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
