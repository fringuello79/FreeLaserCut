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


real_platform, real_instance = sys.platform, QC.QCoreApplication.instance
PS = QC.Qt.PermissionStatus
try:
    sys.platform = "darwin"
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
          "OPENCV_AVFOUNDATION_SKIP_AUTH" in open(camera.__file__, encoding="utf-8").read())
finally:
    sys.platform = real_platform
    QC.QCoreApplication.instance = real_instance

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

ok = sum(results)
print(f"\n{ok}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
