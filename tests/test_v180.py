# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.0: versione per Linux (AppImage), costruita e pubblicata insieme a quella per Windows.

Una prova per ogni riga della matrice dei casi (documento di progetto «versione-linux»): aggiornamento da AppImage,
riavvio e server per Claude dal file .AppImage, permesso della porta USB, diagnostica, menu delle applicazioni,
avviso «il collaudo su Linux lo fa chi installa», certificati HTTPS, X11 su Wayland, sito, workflow e pacchetto.
Gira anche su Windows: le parti di Linux si provano simulando l'ambiente (linux.is_linux, APPIMAGE, APPDIR)."""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import xml.dom.minidom
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
for k in ("APPIMAGE", "APPDIR", "FLC_UPDATE_MODE"):
    os.environ.pop(k, None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QMessageBox, QPushButton

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
INFOS, WARNS = [], []
QMessageBox.information = staticmethod(lambda *a, **k: (INFOS.append(a[2] if len(a) > 2 else ""), QMessageBox.Ok)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: (WARNS.append(a[2] if len(a) > 2 else ""), QMessageBox.Ok)[1])
BOXES = []
QMessageBox.exec = lambda self: BOXES.append(self) or 0

import freelasercut
from freelasercut import diag, i18n, linux, updater

ON_LINUX = sys.platform.startswith("linux")
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""))


class patch:
    """Sostituisce un attributo per la durata di un blocco with."""
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)

    def __exit__(self, *a):
        setattr(self.obj, self.name, self.old)


check("versione 0.18.0 o successiva", updater.parse_version(freelasercut.__version__) >= (0, 18, 0),
      freelasercut.__version__)

# ================================================================== AppImage finta: file + cartella montata
TMP = tempfile.mkdtemp(prefix="flc-v180-")
APPDIR = os.path.join(TMP, "mount", "squashfs-root")
FAKE_EXE = os.path.join(APPDIR, "usr", "python", "bin", "python3")
os.makedirs(os.path.dirname(FAKE_EXE))
open(FAKE_EXE, "w").close()
HOME_APPS = os.path.join(TMP, "Applicazioni con spazi")
os.makedirs(HOME_APPS)
APPIMAGE = os.path.join(HOME_APPS, "FreeLaserCut-0.18.0-x86_64.AppImage")
with open(APPIMAGE, "wb") as fh:
    fh.write(b"vecchia appimage")
os.chmod(APPIMAGE, 0o755)
ENV = {"APPIMAGE": APPIMAGE, "APPDIR": APPDIR, "ARGV0": "x", "OWD": TMP, "PATH": os.environ.get("PATH", ""),
       "HOME": os.path.expanduser("~")}
yes = lambda: True  # noqa: E731
no = lambda: False  # noqa: E731

# ------------------------------------------------------------------ A. che copia è
with patch(linux, "is_linux", yes):
    check("AppImage riconosciuta: APPIMAGE esiste e Python gira dentro APPDIR",
          linux.appimage_path(ENV, FAKE_EXE) == APPIMAGE)
    check("non è AppImage se Python gira fuori dalla cartella montata (variabile rimasta da un altro programma)",
          linux.appimage_path(ENV, sys.executable) is None)
    check("non è AppImage se il file APPIMAGE non c'è più",
          linux.appimage_path(dict(ENV, APPIMAGE=APPIMAGE + ".tolto"), FAKE_EXE) is None)
    check("non è AppImage senza APPDIR", linux.appimage_path({"APPIMAGE": APPIMAGE}, FAKE_EXE) is None)
    check("cartella simile ma diversa (…/squashfs-root2) non conta",
          linux.appimage_path(dict(ENV, APPDIR=APPDIR[:-1]), FAKE_EXE) is None)
with patch(linux, "is_linux", no):
    check("su Windows APPIMAGE non conta mai", linux.appimage_path(ENV, FAKE_EXE) is None)

saved_env = dict(os.environ)
os.environ.update({"APPIMAGE": APPIMAGE, "APPDIR": APPDIR})
with patch(linux, "is_linux", yes), patch(updater, "install_dir", lambda *a: None):
    check("modo di aggiornamento: «appimage» dall'AppImage", updater.mode(FAKE_EXE) == "appimage")
    check("modo di aggiornamento: «manual» dal codice sorgente", updater.mode(sys.executable) in ("manual", "store"))
    check("file da scaricare: AppImage su Linux, installatore su Windows",
          updater.asset_kind("appimage") == "appimage" and updater.asset_kind("installer") == "setup"
          and updater.asset_kind("manual") == "setup")
os.environ.clear()
os.environ.update(saved_env)
os.environ["FLC_UPDATE_MODE"] = "appimage"
check("FLC_UPDATE_MODE=appimage accettato (prove)", updater.mode() == "appimage")
os.environ.pop("FLC_UPDATE_MODE")

# ------------------------------------------------------------------ A. Release con i due file
P = updater.DOWNLOAD_PREFIX


def api(tag="v0.99.0", setup=True, appimage=True, sums=True, extra=()):
    v = tag.lstrip("v")
    assets = list(extra)
    if setup:
        assets.append({"name": f"FreeLaserCut-{v}-Setup.exe", "browser_download_url": P + f"{tag}/FreeLaserCut-{v}-Setup.exe", "size": 10})
    if appimage:
        assets.append({"name": f"FreeLaserCut-{v}-x86_64.AppImage",
                       "browser_download_url": P + f"{tag}/FreeLaserCut-{v}-x86_64.AppImage", "size": 20})
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": P + f"{tag}/SHA256SUMS.txt", "size": 1})
    return {"tag_name": tag, "name": "x", "body": "", "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
            "assets": assets}


r = updater.parse_release(api())
check("Release con installatore e AppImage: Windows prende l'installatore",
      r.asset("setup")[1] == "FreeLaserCut-0.99.0-Setup.exe" and r.setup_name == "FreeLaserCut-0.99.0-Setup.exe")
check("…e Linux prende l'AppImage", r.asset("appimage") == (P + "v0.99.0/FreeLaserCut-0.99.0-x86_64.AppImage",
                                                          "FreeLaserCut-0.99.0-x86_64.AppImage", 20))
r = updater.parse_release(api(appimage=False))
check("Release senza AppImage (la parte Linux non è passata): Windows non cambia, Linux non ha il file",
      r.setup_url and r.asset("appimage") == (None, None, 0))
try:
    updater.download(r, kind="appimage")
    msg = ""
except updater.UpdateError as exc:
    msg = str(exc)
check("…e su Linux lo dice chiaramente (manca la versione per Linux)", "Linux" in msg and "AppImage" in msg, msg)
r = updater.parse_release(api(appimage=False, extra=[
    {"name": "FreeLaserCut-0.98.0-x86_64.AppImage", "browser_download_url": P + "v0.99.0/FreeLaserCut-0.98.0-x86_64.AppImage"},
    {"name": "FreeLaserCut-0.99.0-x86_64.AppImage", "browser_download_url": "https://altrove.example/FreeLaserCut-0.99.0-x86_64.AppImage"}]))
check("AppImage con numero diverso o da un altro sito: ignorata", r.appimage_url is None)
r = updater.parse_release(api(setup=False))
check("Release con la sola AppImage: per Windows manca l'installatore", r.setup_url is None and r.appimage_url)

# ------------------------------------------------------------------ A. scaricamento vero (server locale)
PAYLOAD = os.urandom(300_000)
NAME = "FreeLaserCut-0.99.0-x86_64.AppImage"
FILES = {}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = FILES.get(self.path.rsplit("/", 1)[-1])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}/dl"


def rel_local(sha=None):
    FILES[NAME] = PAYLOAD
    FILES["FreeLaserCut-0.99.0-Setup.exe"] = b"setup"
    FILES["SHA256SUMS.txt"] = (f"{hashlib.sha256(b'setup').hexdigest()}  FreeLaserCut-0.99.0-Setup.exe\n"
                               f"{sha or hashlib.sha256(PAYLOAD).hexdigest()}  {NAME}\n").encode()
    return updater.Release("0.99.0", "v0.99.0", "x", "", "", f"{BASE}/FreeLaserCut-0.99.0-Setup.exe",
                           "FreeLaserCut-0.99.0-Setup.exe", 5, f"{BASE}/SHA256SUMS.txt",
                           (f"{BASE}/{NAME}", NAME, len(PAYLOAD)))


dest = tempfile.mkdtemp()
got = updater.download(rel_local(), dest_dir=dest, kind="appimage")
check("AppImage scaricata e controllata con lo SHA256SUMS.txt comune a Windows e Linux",
      os.path.basename(got) == NAME and open(got, "rb").read() == PAYLOAD)
got_w = updater.download(rel_local(), dest_dir=dest, kind="setup")
check("dallo stesso SHA256SUMS.txt anche l'installatore per Windows", open(got_w, "rb").read() == b"setup")
os.remove(got)
try:
    updater.download(rel_local(sha="0" * 64), dest_dir=dest, kind="appimage")
    msg = ""
except updater.UpdateError as exc:
    msg = str(exc)
left = os.listdir(dest)
check("SHA-256 diverso: AppImage cancellata (né il file né il .part), errore chiaro", "SHA-256" in msg
      and NAME not in left and NAME + ".part" not in left, f"{msg} {left}")

# ------------------------------------------------------------------ A. sostituzione del file
new = os.path.join(tempfile.mkdtemp(), NAME)
with open(new, "wb") as fh:
    fh.write(PAYLOAD)
real = updater.apply_appimage(new, APPIMAGE)
check("la nuova AppImage prende il posto di quella vecchia nello stesso percorso",
      real == os.path.realpath(APPIMAGE) and open(APPIMAGE, "rb").read() == PAYLOAD)
check("…il file scaricato non resta in giro e non restano file temporanei",
      not os.path.exists(new) and sorted(os.listdir(HOME_APPS)) == [os.path.basename(APPIMAGE)])
if os.name == "posix":
    check("…ed è eseguibile", os.stat(APPIMAGE).st_mode & stat.S_IXUSR != 0)
    link = os.path.join(TMP, "FreeLaserCut.AppImage")
    os.symlink(APPIMAGE, link)
    with open(new, "wb") as fh:
        fh.write(b"versione via collegamento")
    updater.apply_appimage(new, link)
    check("con un collegamento simbolico si sostituisce il file vero e il collegamento resta",
          os.path.islink(link) and open(APPIMAGE, "rb").read() == b"versione via collegamento")
    with open(APPIMAGE, "wb") as fh:
        fh.write(PAYLOAD)
    if not IS_ROOT:
        ro = os.path.join(TMP, "sola-lettura")
        os.makedirs(ro)
        ro_app = os.path.join(ro, NAME)
        open(ro_app, "wb").write(b"vecchia")
        os.chmod(ro, 0o555)
        open(new, "wb").write(b"nuova")
        try:
            updater.apply_appimage(new, ro_app)
            msg = ""
        except updater.UpdateError as exc:
            msg = str(exc)
        check("cartella non scrivibile: errore chiaro, il file vecchio resta com'era, quello nuovo pure",
              msg and open(ro_app, "rb").read() == b"vecchia" and os.path.exists(new), msg)
        check("…e la finestra lo sa prima di scaricare (folder_writable)", not linux.folder_writable(ro_app)
              and linux.folder_writable(APPIMAGE))
        os.chmod(ro, 0o755)

calls = []
updater.relaunch_appimage(APPIMAGE, popen=lambda cmd, **kw: calls.append((cmd, kw)))
check("riapertura dal file .AppImage, senza le variabili della copia che si chiude",
      calls and calls[0][0] == [APPIMAGE] and "APPDIR" not in calls[0][1]["env"]
      and "APPIMAGE" not in calls[0][1]["env"] and calls[0][1]["start_new_session"])

# ------------------------------------------------------------------ B/C. riavvio e Claude dall'AppImage
with patch(linux, "is_linux", yes):
    cmd, env = linux.relaunch_command(("--x",), ENV, FAKE_EXE)
    check("riavvio da AppImage: si riparte dal file, non da Python nella cartella montata",
          cmd == [APPIMAGE, "--x"] and "APPDIR" not in env and "OWD" not in env and env["PATH"] == ENV["PATH"])
    cmd, env = linux.relaunch_command((), {}, sys.executable)
    check("riavvio dal codice sorgente: python -m freelasercut come prima", cmd == [sys.executable, "-m", "freelasercut"]
          and env is None)
    check("server per Claude da AppImage: il file .AppImage con --mcp-server",
          linux.mcp_command(ENV, FAKE_EXE) == {"command": APPIMAGE, "args": ["--mcp-server"]})
    check("server per Claude dal codice sorgente: niente (si usa Python)", linux.mcp_command({}, sys.executable) is None)

from freelasercut.ui import dialogs_claude  # noqa: E402

with patch(linux, "mcp_command", lambda *a, **k: {"command": APPIMAGE, "args": ["--mcp-server"]}):
    e = dialogs_claude.server_entry()
    line = dialogs_claude.claude_code_command()
check("configurazione di Claude da AppImage: comando = file .AppImage, senza PYTHONPATH",
      e == {"command": APPIMAGE, "args": ["--mcp-server"]})
check("riga per Claude Code da AppImage (percorso tra virgolette, anche con gli spazi)",
      line == f'claude mcp add freelasercut -- "{APPIMAGE}" --mcp-server', line)
with patch(linux, "mcp_command", lambda *a, **k: None):
    e = dialogs_claude.server_entry()
    line = dialogs_claude.claude_code_command()
check("configurazione di Claude dal codice sorgente come prima (python -m freelasercut.mcp_server)",
      e["args"] == ["-m", "freelasercut.mcp_server"] and "PYTHONPATH" in e["env"] and "-m freelasercut.mcp_server" in line)

from freelasercut import mcp_server  # noqa: E402

launched = []
with patch(linux, "appimage_path", lambda *a, **k: APPIMAGE), patch(linux, "is_linux", yes), \
        patch(mcp_server.subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw))):
    os.environ.update({"APPIMAGE": APPIMAGE, "APPDIR": APPDIR})
    mcp_server._launch()
    os.environ.pop("APPIMAGE")
    os.environ.pop("APPDIR")
check("Claude apre FreeLaserCut dal file .AppImage (non da Python nella cartella montata)",
      launched and launched[0][0] == [APPIMAGE] and "APPDIR" not in launched[0][1]["env"])

# ------------------------------------------------------------------ D. porta USB
with patch(linux, "is_linux", yes):
    h = linux.serial_hint("/dev/ttyUSB0", PermissionError(13, "Permission denied: '/dev/ttyUSB0'"))
    check("porta senza permesso: spiegazione con il gruppo e il comando", "dialout" in h and "sudo usermod -aG" in h, h)
    check("errore di pyserial con [Errno 13] nel testo riconosciuto",
          linux.serial_hint("/dev/ttyACM0", OSError("could not open port /dev/ttyACM0: [Errno 13] Permission denied")))
    check("porta che non c'è (errore diverso): nessuna spiegazione dei permessi",
          linux.serial_hint("/dev/ttyUSB9", FileNotFoundError(2, "No such file")) == "")
    check("Wi-Fi e simulatore: nessuna spiegazione", linux.serial_hint("tcp://192.168.1.110:8080", PermissionError()) == ""
          and linux.serial_hint("SIM", PermissionError()) == "")
    with patch(linux, "tty_group", lambda d: "uucp"):
        check("gruppo letto dalla porta (Arch: uucp)", linux.permission_command("/dev/ttyUSB0") == (
            "sudo usermod -aG uucp $USER", "uucp"))
    with patch(linux, "tty_group", lambda d: "root"):
        check("porta del solo amministratore: si propone dialout", linux.permission_command("/dev/ttyUSB0")[1] == "dialout")
with patch(linux, "is_linux", no):
    check("su Windows nessuna spiegazione Linux", linux.serial_hint("COM3", PermissionError(13, "Accesso negato")) == "")

from freelasercut import grbl, machines  # noqa: E402


class _NoSerial:
    @staticmethod
    def Serial(*a, **k):
        raise PermissionError(13, "Permission denied: '/dev/ttyUSB0'")


msgs = []
ctl = grbl.GrblController()
ctl.connection_changed.connect(lambda ok, m: msgs.append(m))
with patch(linux, "is_linux", yes), patch(grbl, "serial", _NoSerial):
    ok = ctl.connect_port("/dev/ttyUSB0")
app.processEvents()
check("Connetti su una porta senza permesso: non si connette e spiega cosa fare",
      not ok and msgs and "Permission denied" in msgs[-1] and "usermod" in msgs[-1], msgs[-1:] and msgs[-1][:200])
log = []
with patch(linux, "is_linux", yes):
    machines.probe("/dev/ttyUSB0", log=log.append, opener=lambda p, b: _NoSerial.Serial())
check("Riconosci la macchina su una porta senza permesso: la spiegazione è nel registro",
      any("usermod" in x for x in log), log)

# ------------------------------------------------------------------ F. diagnostica
osr = os.path.join(TMP, "os-release")
with open(osr, "w", encoding="utf-8") as fh:
    fh.write('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nID=ubuntu\n')
check("distribuzione letta da /etc/os-release", linux.distro(osr) == "Ubuntu 24.04.1 LTS")
check("os-release mancante: «?»", linux.distro(osr + ".no") == "?")
with patch(linux, "is_linux", yes), patch(linux, "tty_report", lambda: ["/dev/ttyUSB0: gruppo dialout · accesso NO"]), \
        patch(linux, "distro", lambda *a: "Fedora Linux 41"):
    lines = linux.system_lines({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME", **ENV})
check("righe Linux del rapporto: distribuzione, sessione, AppImage, porte",
      "Distribuzione: Fedora Linux 41" in lines and "Sessione: wayland · desktop GNOME" in lines
      and any(x.startswith("Porte USB: /dev/ttyUSB0: gruppo dialout") for x in lines), lines)
with patch(linux, "appimage_path", lambda *a, **k: APPIMAGE):
    check("rapporto: avvio «AppImage (Linux)»", diag.launch_kind("/tmp/x/python3") == "AppImage (Linux)")
check("rapporto: Store e installatore come prima", diag.launch_kind(r"C:\Program Files\WindowsApps\FLC\python.exe")
      .endswith("Microsoft Store"))
info = diag.system_info()
if ON_LINUX:
    check("su Linux il rapporto contiene distribuzione, sessione e porte", "Distribuzione:" in info and "Sessione:" in info
          and "Porte USB: " in info, info)
else:
    check("su Windows il rapporto non ha le righe di Linux", "Distribuzione:" not in info)
check("nessun nome della cartella utente nel rapporto", os.path.expanduser("~") not in info or os.path.expanduser("~") in ("/", "~"))

# ------------------------------------------------------------------ G. menu delle applicazioni
for p in ("/home/ale/Applicazioni/FreeLaserCut.AppImage", '/home/a b/"strano" $HOME `x` \\ 100%/FLC.AppImage'):
    q = linux.desktop_quote(p)
    check(f"riga Exec: percorso protetto e reversibile ({p[:30]}…)", linux.desktop_unquote(q) == p and q.startswith('"'),
          q)
DATA = os.path.join(TMP, "xdg-data")
ran = []
with patch(linux.shutil, "which", lambda name: "/usr/bin/" + name):
    files = linux.install_desktop(APPIMAGE, os.path.join(ROOT, "freelasercut", "assets", "logo.png"),
                                  env={"XDG_DATA_HOME": DATA}, run=lambda cmd, **kw: ran.append(cmd))
paths = linux.desktop_paths({"XDG_DATA_HOME": DATA})
desk = open(paths["desktop"], encoding="utf-8").read()
check("file .desktop nella cartella dell'utente, con Exec, icona e tipo dei progetti",
      f"Exec={linux.desktop_quote(APPIMAGE)} %F" in desk and "Icon=freelasercut" in desk
      and "MimeType=application/x-freelasercut;" in desk and "Terminal=false" in desk and desk.startswith("[Desktop Entry]"))
check("icona e tipo MIME scritti", os.path.getsize(paths["icon"]) > 1000 and
      xml.dom.minidom.parse(paths["mime"]).getElementsByTagName("glob")[0].getAttribute("pattern") == "*.flcut")
if os.name == "posix":
    check("file .desktop eseguibile (GNOME e Xfce lo chiedono)", os.stat(paths["desktop"]).st_mode & stat.S_IXUSR)
check("database del menu e dei tipi aggiornati, .flcut associato a FreeLaserCut",
      [c[0] for c in ran] == ["update-mime-database", "update-desktop-database", "xdg-mime"]
      and ran[2][1:] == ["default", "freelasercut.desktop", "application/x-freelasercut"], ran)
check("voce del menu riconosciuta per questo file, non per un altro",
      linux.desktop_installed_for(APPIMAGE, {"XDG_DATA_HOME": DATA})
      and not linux.desktop_installed_for(APPIMAGE + "2", {"XDG_DATA_HOME": DATA}))
with patch(linux.shutil, "which", lambda name: None):
    files2 = linux.install_desktop(APPIMAGE, os.path.join(ROOT, "freelasercut", "assets", "logo.png"),
                                   env={"XDG_DATA_HOME": DATA}, run=lambda cmd, **kw: 1 / 0)
check("si può rifare (stessi file) e funziona anche senza update-desktop-database", files2 == files)

# ------------------------------------------------------------------ I/J. certificati e X11 su Wayland
cert = os.path.join(TMP, "ca.pem")
open(cert, "w").write("x")
with patch(linux, "is_linux", yes):
    e = {}
    check("certificati: senza quelli di Python si usa il file del sistema",
          linux.ssl_fallback(e, (cert + ".no", cert), default_cafile="/non/esiste") == cert and e["SSL_CERT_FILE"] == cert)
    check("certificati: SSL_CERT_FILE già impostato non si tocca", linux.ssl_fallback({"SSL_CERT_FILE": "a"}, (cert,), "") is None)
    check("certificati: se Python li trova non si fa niente", linux.ssl_fallback({}, (cert,), default_cafile=cert) is None)
    check("certificati: nessun file trovato, nessun cambiamento", linux.ssl_fallback({}, (cert + ".no",), "") is None)
    e = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    check("Wayland con XWayland: X11 (xcb)", linux.prefer_xcb(e) and e["QT_QPA_PLATFORM"] == "xcb")
    linux.after_qapp(None, e)
    check("…e dopo QApplication la variabile sparisce (non passa ai programmi aperti)", "QT_QPA_PLATFORM" not in e
          and "FLC_XCB_SET" not in e)
    e = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"}
    check("scelta della persona (QT_QPA_PLATFORM) rispettata", not linux.prefer_xcb(e) and e["QT_QPA_PLATFORM"] == "wayland")
    linux.after_qapp(None, e)
    check("…e non viene tolta", e.get("QT_QPA_PLATFORM") == "wayland")
    check("Wayland senza XWayland: si resta su Wayland", not linux.prefer_xcb({"XDG_SESSION_TYPE": "wayland"}))
    check("FLC_WAYLAND=1: si resta su Wayland", not linux.prefer_xcb({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0",
                                                                      "FLC_WAYLAND": "1"}))
    check("sessione X11: niente da cambiare", not linux.prefer_xcb({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}))
with patch(linux, "is_linux", no):
    e = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
    check("su Windows niente di tutto questo", not linux.prefer_xcb(e) and linux.ssl_fallback(e, (cert,), "") is None)

# ------------------------------------------------------------------ cache di numba nell'AppImage
from freelasercut import numba_cache  # noqa: E402

m1, m2 = os.path.join(TMP, ".mount_AbC123"), os.path.join(TMP, ".mount_XyZ789")
f1 = os.path.join(m1, "usr", "app", "freelasercut", "core", "imaging.py")
f2 = os.path.join(m2, "usr", "app", "freelasercut", "core", "imaging.py")
s1, s2 = numba_cache.subpath(f1, m1), numba_cache.subpath(f2, m2)
check("cache di numba: stessa cartella anche se il punto di montaggio cambia a ogni avvio",
      s1 == s2 and s1.startswith(f"flc-{freelasercut.__version__}-core_"), f"{s1} {s2}")
check("…diversa per un'altra versione e per un altro file",
      numba_cache.subpath(f1, m1, "9.9.9") != s1 and numba_cache.subpath(os.path.join(m1, "usr", "app", "x.py"), m1) != s1)
check("…e fuori dall'AppImage decide numba come prima", numba_cache.subpath("/home/a/freelasercut/core/imaging.py", m1) is None)
root = os.path.join(TMP, "numba-cache")
for n in (f"flc-0.17.0-core_aa", f"flc-{freelasercut.__version__}-core_bb", "imaging_cc", f"flc-{freelasercut.__version__}1-x"):
    os.makedirs(os.path.join(root, n))
removed = linux.numba_cleanup(root)
check("cache delle versioni vecchie tolta, quella attuale e quelle di altri programmi restano",
      removed == 2 and sorted(os.listdir(root)) == sorted([f"flc-{freelasercut.__version__}-core_bb", "imaging_cc"]),
      os.listdir(root))
with patch(linux, "is_linux", yes):
    e = dict(ENV, XDG_CACHE_HOME=os.path.join(TMP, "xdgcache"))
    check("nell'AppImage numba usa questa cache", linux.numba_setup(e, FAKE_EXE) and
          e["NUMBA_CACHE_LOCATOR_CLASSES"].startswith("freelasercut.numba_cache.AppImageCacheLocator"))
    check("…ma non se la persona ha scelto da sé (NUMBA_CACHE_DIR)", not linux.numba_setup(dict(ENV, NUMBA_CACHE_DIR="/x"), FAKE_EXE))
    check("…e non fuori dall'AppImage", not linux.numba_setup({}, sys.executable))
if ON_LINUX:
    code = r"""
import os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import mod
mod.f(3.0)
print("HITS", mod.f.stats.cache_hits, "MISSES", len(mod.f.stats.cache_misses))
"""
    hits = []
    cache_home = os.path.join(TMP, "cache-home")
    for mnt in (m1, m2):  # due «avvii» dell'AppImage, montata in due cartelle diverse
        pkg = os.path.join(mnt, "usr", "app")
        os.makedirs(pkg, exist_ok=True)
        with open(os.path.join(pkg, "mod.py"), "w", encoding="utf-8") as fh:
            fh.write("from numba import njit\n@njit(cache=True)\ndef f(x):\n    return x * 2.0\n")
        os.utime(os.path.join(pkg, "mod.py"), (1_700_000_000, 1_700_000_000))
        env_n = dict(os.environ, APPDIR=mnt, XDG_CACHE_HOME=cache_home, NUMBA_CACHE_LOCATOR_CLASSES=linux.NUMBA_LOCATORS)
        r = subprocess.run([sys.executable, "-c", code, ROOT, pkg], env=env_n, capture_output=True, text=True, timeout=300)
        hits.append(r.stdout.strip() or r.stderr[-500:])
    check("numba vero: al secondo avvio, montato altrove, la funzione si carica dalla cache senza ricompilare",
          hits[1].startswith("HITS") and "HITS 0" not in hits[1] and os.listdir(os.path.join(cache_home, "numba"))[0]
          .startswith("flc-"), hits)

# ================================================================== finestra principale
os.environ["FLC_UPDATE_MODE"] = "appimage"
from freelasercut.ui import dialogs_machine, update_ui  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
app.processEvents()
check("aggiornamento giornaliero proposto anche nell'AppImage", w.updates.mode == "appimage"
      and w.acts["update_auto"].isVisible())
check("Aiuto → «FreeLaserCut per Linux: collaudo e segnalazioni» solo su Linux",
      w.acts["linux_info"].isVisible() == ON_LINUX and w.acts["linux_info"].text().startswith("FreeLaserCut per Linux"))
from freelasercut.ui import help_texts  # noqa: E402

check("le voci nuove hanno la scheda della guida «?»", help_texts.lookup("linux_info") and help_texts.lookup("linux_desktop"))

# ---- avviso: il collaudo su Linux lo fa chi installa, con il rapporto dal menu Aiuto
with patch(linux, "is_linux", no):
    check("avviso: mai su Windows", w.linux_notice(force=True) is None)
with patch(linux, "is_linux", yes):
    check("avviso: non durante le prove senza finestre (offscreen), salvo richiesta da Aiuto", w.linux_notice() is None)
    with patch(linux, "appimage_path", lambda *a, **k: APPIMAGE), \
            patch(linux, "desktop_installed_for", lambda *a, **k: False):
        box = w.linux_notice_dialog()
    text = box.text()
    check("avviso: dice che è lo stesso programma, con le stesse prove automatiche",
          "stesso programma" in text and "stesse prove automatiche" in text)
    check("avviso: dice che lo sviluppo e le prove con laser e camera veri sono su Windows e perché su Linux no",
          "si fanno su Windows" in text and "distribuzioni, desktop e configurazioni sono troppi" in text)
    check("avviso: il collaudo su Linux lo fa chi installa, sul proprio computer",
          "il collaudo su Linux lo fa chi installa il programma, sul proprio computer" in text)
    check("avviso: come segnalare (Aiuto → Invia un rapporto all'assistenza) e cosa c'è già nel rapporto",
          "Aiuto → Invia un rapporto all'assistenza" in text and "distribuzione" in text)
    check("avviso: propone il menu delle applicazioni (spuntato) se non c'è ancora",
          box.desktop_check is not None and box.desktop_check.isChecked())
    with patch(linux, "appimage_path", lambda *a, **k: None):
        check("avviso dal codice sorgente: niente proposta del menu", w.linux_notice_dialog().desktop_check is None)
    added, reports = [], []
    with patch(linux, "appimage_path", lambda *a, **k: APPIMAGE), \
            patch(linux, "desktop_installed_for", lambda *a, **k: False), \
            patch(w, "linux_add_to_menu", lambda *a, **k: added.append(k)), \
            patch(w, "send_report_dialog", lambda *a: reports.append(1)), \
            patch(QMessageBox, "clickedButton", lambda self: self.report_btn):
        w.qs.setValue("linux_notice_seen", False)
        b = w.linux_notice(force=True)
        app.processEvents()
    check("avviso: segnato come letto, menu aggiunto, «Invia un rapporto…» apre il rapporto",
          w.qs.value("linux_notice_seen") in (True, "true") and added == [{"quiet": True}] and reports == [1])
    w.qs.setValue("linux_notice_seen", True)
    os.environ.pop("FLC_NO_FIRST_RUN")
    check("avviso letto: al prossimo avvio non ricompare", w.linux_notice() is None)
    os.environ["FLC_NO_FIRST_RUN"] = "1"
for lang, words in (("en", ("testing on Linux is done by the people who install the program", "Help → Send a report to support")),
                    ("es", ("las pruebas en Linux las hace quien instala el programa", "Ayuda → Enviar un informe al soporte")),
                    ("fr", ("les essais sous Linux sont faits par ceux qui installent le programme", "Aide → Envoyer un rapport à l'assistance")),
                    ("pt", ("os testes no Linux são feitos por quem instala o programa", "Ajuda → Enviar um relatório ao suporte"))):
    i18n.set_language(lang)
    with patch(linux, "is_linux", yes):
        t = w.linux_notice_dialog().text()
    check(f"avviso tradotto ({lang}) con il nome giusto del menu del rapporto", all(x in t for x in words), t[:300])
i18n.set_language("it")
cat_en = json.load(open(os.path.join(ROOT, "freelasercut", "locale", "en.json"), encoding="utf-8"))
check("in inglese il nome del comando del rapporto è quello del menu",
      cat_en.get("Invia un rapporto all'assistenza…", "").startswith("Send a report to support"),
      cat_en.get("Invia un rapporto all'assistenza…"))

# ---- Aiuto → Aggiungi al menu
with patch(linux, "appimage_path", lambda *a, **k: APPIMAGE), patch(linux, "install_desktop", lambda a, i: ["f1", "f2"]):
    INFOS.clear()
    res = w.linux_add_to_menu()
check("Aiuto → Aggiungi al menu: scrive i file e lo dice", res == ["f1", "f2"] and INFOS and "f1" in INFOS[-1])
with patch(linux, "appimage_path", lambda *a, **k: None):
    check("dal codice sorgente la voce non fa niente", w.linux_add_to_menu() is None)

# ---- Informazioni
captured = []
with patch(QMessageBox, "about", staticmethod(lambda p, t, x: captured.append(x))):
    w.show_about()
check("Informazioni: su Linux ricorda chi collauda e come segnalare", ("Versione per Linux" in captured[-1]) == ON_LINUX)

# ---- E. Riconosci la macchina su Linux
for flag in (True, False):
    with patch(dialogs_machine, "_LINUX", flag):
        dlg = dialogs_machine.MachineWizard(w)
        names = [b.text() for b in dlg.findChildren(QPushButton)]
        head = dlg.table.horizontalHeaderItem(3).text()
        if flag:
            check("Riconosci la macchina su Linux: «Permesso della porta USB…» al posto dei driver di Windows",
                  "Permesso della porta USB…" in names and "Installa driver dal PC…" not in names
                  and "Gestione dispositivi" not in names and head == "Descrizione del sistema", names)
            BOXES.clear()
            with patch(linux, "permission_command", lambda d=None: ("sudo usermod -aG dialout $USER", "dialout")):
                cmd = dlg.linux_permission()
            check("…che spiega passo per passo e offre di copiare il comando",
                  cmd == "sudo usermod -aG dialout $USER" and BOXES and "usermod" in BOXES[-1].text()
                  and "Invia un rapporto all'assistenza" in BOXES[-1].text())
        else:
            check("su Windows restano i pulsanti dei driver", "Installa driver dal PC…" in names and
                  "Permesso della porta USB…" not in names and head == "Descrizione di Windows", names)
        dlg.close()

# ---- A. aggiornamento dalla finestra
um = w.updates
d = um.release_dialog(updater.parse_release(api()))
labels = " ".join(x.text() for x in d.findChildren(QLabel))
buttons = [b.text() for b in d.findChildren(QDialogButtonBox)[0].buttons()]
check("finestra delle novità nell'AppImage: «Scarica e installa» e spiegazione della sostituzione del file",
      "Scarica e installa" in buttons and "AppImage" in labels and "stesso file, stessa cartella" in labels, labels)
WARNS.clear()
BOXES.clear()
started = []
with patch(updater, "appimage_target", lambda: os.path.join(TMP, "sola", NAME)), \
        patch(linux, "folder_writable", lambda p: False), \
        patch(threading, "Thread", lambda *a, **k: started.append(1)):
    ok = um.install(updater.parse_release(api()))
check("cartella dell'AppImage non scrivibile: lo dice prima di scaricare e non scarica",
      ok is False and not started and BOXES and "Non posso scrivere" in BOXES[-1].text())
kinds = []


def fake_download(rel, **kw):
    kinds.append(kw.get("kind"))
    raise updater.UpdateError("prova")


with patch(updater, "appimage_target", lambda: APPIMAGE), patch(linux, "folder_writable", lambda p: True), \
        patch(updater, "download", fake_download):
    um.install(updater.parse_release(api()))
    for _ in range(200):
        app.processEvents()
        if kinds and um._dlg is None:
            break
check("nell'AppImage si scarica l'AppImage, non l'installatore per Windows", kinds == ["appimage"], kinds)
done = []
lst = type("L", (), {"close": lambda self: done.append("listener")})()
app._flc_single = lst
with patch(updater, "apply_appimage", lambda p: (done.append(("apply", p)), APPIMAGE)[1]), \
        patch(updater, "relaunch_appimage", lambda t: done.append(("relaunch", t))):
    w._update_installer = os.path.join(dest, NAME)
    res = update_ui.run_installer_on_exit(w)
check("alla chiusura: sostituisce l'AppImage, smette di ascoltare (istanza unica), la riapre",
      res and done == [("apply", os.path.join(dest, NAME)), "listener", ("relaunch", APPIMAGE)], done)
done.clear()
with patch(updater, "apply_appimage", lambda p: (_ for _ in ()).throw(updater.UpdateError("cartella piena"))), \
        patch(updater, "relaunch_appimage", lambda t: done.append("relaunch")):
    WARNS.clear()
    w._update_installer = os.path.join(dest, NAME)
    res = update_ui.run_installer_on_exit(w)
check("sostituzione non riuscita: lo dice e non riapre una copia a metà", not res and not done and WARNS)
app._flc_single = None

# ---- A. Release uscita senza AppImage: per Linux non è un aggiornamento
banners = []
with patch(w, "show_banner", lambda *a, **k: banners.append(a)):
    INFOS.clear()
    um._on_checked(updater.parse_release(api(appimage=False)), None, False)
    um._on_checked(updater.parse_release(api(appimage=False)), None, True)
check("Release senza AppImage: nessun avviso automatico nell'AppImage (non c'è niente da installare)", not banners)
check("…e chi cerca a mano legge che per Linux arriverà con la prossima versione",
      INFOS and "solo per Windows" in INFOS[-1] and "prossima versione" in INFOS[-1], INFOS[-1:])
with patch(w, "show_banner", lambda *a, **k: banners.append(a)):
    um._on_checked(updater.parse_release(api()), None, False)
check("Release con AppImage: l'avviso dell'aggiornamento compare", banners)

# ---- B. riavvio (lingua, interfaccia) dall'AppImage
popen = []
with patch(linux, "relaunch_command", lambda *a, **k: ([APPIMAGE], {"PATH": "/usr/bin"})), \
        patch(subprocess, "Popen", lambda cmd, **kw: popen.append((cmd, kw))):
    w._restart = True
    w._confirm_discard = lambda: True
    w.editor.dirty = False
    w.qs.setValue("autosave_pending", False)
    w.close()
check("riavvio dall'AppImage (lingua, interfaccia): riparte il file .AppImage",
      popen and popen[0][0] == [APPIMAGE] and popen[0][1]["env"] == {"PATH": "/usr/bin"}, popen)
os.environ.pop("FLC_UPDATE_MODE")

def readme_text():
    return open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()


# ================================================================== K/L. sito, workflow, pacchetto
html = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
check("sito: pulsante di download per Linux che legge l'AppImage dall'ultima Release",
      'id="dl-linux"' in html and "x86_64\\.appimage$" in html)
check("sito: spiegato in italiano e in inglese chi collauda la versione per Linux e come segnalare",
      "il collaudo su Linux lo fa chi lo installa" in html and "Aiuto → Invia un rapporto all'assistenza" in html
      and "testing on Linux is done by the people who install it" in html and "Help → Send a report to support" in html)
check("sito: il pulsante per Windows cerca sempre e solo l'installatore",
      "/^freelasercut-[\\d.]+-setup\\.exe$/i" in html)
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
check("GitHub: AppImage costruita su Ubuntu 22.04 e provata davvero (X11, server per Claude, aggiornamento)",
      "build-linux:" in wf and "runs-on: ubuntu-22.04" in wf and "prova-linux:" in wf and "--self-test" in wf
      and "piattaforma Qt xcb" in wf and "--mcp-server" in wf and "aggiornamento: appimage" in wf)
check("GitHub: prova anche su Debian, Ubuntu 22.04, Fedora e Arch, senza fermare la Release",
      all(x in wf for x in ("debian:12", "ubuntu:22.04", "fedora:", "archlinux:")) and "continue-on-error: true" in wf)
check("GitHub: la Release non esce se il lavoro viene annullato", "!cancelled()" in wf and "always()" not in wf)
check("GitHub: la Release esce sempre se Windows passa; l'AppImage solo se la sua prova è riuscita",
      "needs.prova-windows.result == 'success'" in wf and "needs.prova-linux.result == 'success'" in wf
      and "cat dist-linux/SHA256SUMS-linux.txt >> dist/SHA256SUMS.txt" in wf and "FILES+=(dist/FreeLaserCut-*-x86_64.AppImage)" in wf)
check("GitHub: le note della Release spiegano chi collauda la versione per Linux",
      "il collaudo su Linux lo fa chi lo installa" in wf and "Aiuto → Invia un rapporto all'assistenza" in wf)
sys.path.insert(0, os.path.join(ROOT, "build"))
import prepara_appimage  # noqa: E402
import prepara_installer  # noqa: E402

src_app = open(prepara_appimage.__file__, encoding="utf-8").read()
check("AppImage con lo stesso Python e le stesse librerie dell'installatore, presi dallo stesso posto (OpenCV senza il suo Qt)",
      re.search(r"^from prepara_installer import .*\bPACKAGES\b.*\bPY_RELEASE\b.*\bPY_VERSION\b", src_app, re.M)
      and "PY_VERSION =" not in src_app and "PY_RELEASE =" not in src_app
      and [p.split("==")[1] for p in prepara_appimage.LINUX_PACKAGES] == [p.split("==")[1] for p in prepara_installer.PACKAGES]
      and any(p.startswith("opencv-python-headless==") for p in prepara_appimage.LINUX_PACKAGES)
      and not any(p.startswith("opencv-python==") for p in prepara_appimage.LINUX_PACKAGES))
check("nome del file costruito = quello che cerca l'aggiornamento",
      updater._APPIMAGE_RE.match(f"FreeLaserCut-{freelasercut.__version__}-x86_64.AppImage")
      and 'f"FreeLaserCut-{ver}-x86_64.AppImage"' in open(prepara_appimage.__file__, encoding="utf-8").read())
check("AppRun: server per Claude con --mcp-server, Python isolato (-I: niente cartella corrente né PYTHONPATH)",
      '"$1" = "--mcp-server"' in prepara_appimage.APPRUN and "-I -m freelasercut.mcp_server" in prepara_appimage.APPRUN
      and "-I -m freelasercut " in prepara_appimage.APPRUN and " -s " not in prepara_appimage.APPRUN)
check("prova veloce della costruzione: il programma deve venire dall'AppDir, non dal repository",
      '"-I", "-c"' in src_app and "cwd=APPDIR" in src_app and "il programma non viene dall'AppDir" in src_app)
check("glibc controllata: niente che chieda più di 2.34 (Ubuntu 22.04, Debian 12, Fedora 35, come promesso)",
      prepara_appimage.GLIBC_MAX == (2, 34) and prepara_appimage.PLATFORMS[0] == "manylinux_2_34_x86_64"
      and "manylinux_2_35_x86_64" not in prepara_appimage.PLATFORMS and "glibc 2.34" in readme_text())
gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
check("file costruiti fuori dal repository (.gitignore)", "build/AppDir/" in gi and "build/*.AppImage" in gi)
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("README: installazione su Linux, permesso dialout e chi collauda",
      "## Installazione (Linux)" in readme and "dialout" in readme and "il collaudo su Linux lo fa chi installa" in readme)
ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
check("CHANGELOG: 0.18.0 con la versione per Linux e il collaudo da parte di chi la installa",
      re.search(r"^## 0\.18\.0\b", ch, re.M) and "il collaudo su Linux lo fa chi" in ch.split("## 0.17.17")[0])

# ================================================================== M. prova di avvio (--self-test)
fresh = tempfile.mkdtemp(prefix="flc-utente-")
ini = os.path.join(fresh, "preferenze.ini")
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
           APPDATA=os.path.join(fresh, "appdata"), XDG_CONFIG_HOME=os.path.join(fresh, "config"), FLC_SETTINGS_INI=ini)
env.pop("FLC_UPDATE_MODE", None)
r = subprocess.run([sys.executable, "-m", "freelasercut", "--self-test"], cwd=ROOT, env=env, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=300)
check("--self-test: finestra aperta, librerie caricate, esito positivo, codice 0",
      r.returncode == 0 and "finestra principale: ok" in r.stdout and "ESITO: tutto a posto" in r.stdout,
      (r.stdout + r.stderr)[-1500:])
check("--self-test: non tocca dati e preferenze della persona (tutto in una cartella temporanea sua)",
      os.listdir(fresh) == [] and "aggiornamento: manual" in r.stdout, f"{os.listdir(fresh)} {r.stdout[-300:]}")

srv.shutdown()
w.editor.dirty = False
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
