# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione per Linux (0.18.0): tutto quello che su Linux va fatto in modo diverso da Windows.

- La copia distribuita è un'AppImage: un solo file. Il programma gira da una cartella temporanea montata dal file
  (``APPDIR``), che sparisce quando FreeLaserCut si chiude: per riavviarlo, aggiornarlo o farlo aprire da Claude si
  usa sempre il file ``APPIMAGE``, mai ``sys.executable``.
- La porta USB del laser (``/dev/ttyUSB0``, ``/dev/ttyACM0``) si apre solo se l'utente è nel gruppo della porta
  (``dialout`` su Debian/Ubuntu/Fedora, ``uucp`` su Arch): i driver dei chip CH340/CP210x sono già nel sistema.
- Menu delle applicazioni e associazione dei progetti ``.flcut``: file .desktop e tipo MIME nella cartella
  dell'utente (niente permessi da amministratore).
- Su Wayland, se c'è XWayland, Qt usa X11 (xcb): finestre e secondo monitor si comportano come su Windows.

Le funzioni qui sono senza Qt (salvo dove indicato) e si provano con tests/test_v180.py anche su Windows.
"""
import errno
import os
import shutil
import subprocess
import sys

APP_ID = "freelasercut"                       # nome del file .desktop e dell'icona
MIME_TYPE = "application/x-freelasercut"      # progetti .flcut
RUNTIME_VARS = ("APPDIR", "APPIMAGE", "ARGV0", "OWD")  # messe dal runtime dell'AppImage
NUMBA_PREFIX = "flc-"                          # cartelle della cache di numba dell'AppImage (numba_cache.py)
NUMBA_LOCATORS = "freelasercut.numba_cache.AppImageCacheLocator,InTreeCacheLocator,UserWideCacheLocator"
CERT_FILES = (                                # certificati del sistema, per HTTPS (aggiornamenti, rapporti)
    "/etc/ssl/certs/ca-certificates.crt",      # Debian, Ubuntu, Mint, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",        # Fedora, RHEL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/ssl/ca-bundle.pem",                  # openSUSE
    "/etc/ssl/cert.pem",                       # Alpine, Arch, Void
)


def is_linux():
    return sys.platform.startswith("linux")


# ------------------------------------------------------------------ AppImage
def appimage_path(env=None, executable=None):
    """Percorso del file .AppImage da cui gira questa copia, o None (codice sorgente, Windows…).
    Vale solo se Python gira davvero da dentro la cartella montata dell'AppImage: una variabile APPIMAGE
    rimasta nell'ambiente di un altro programma non basta."""
    env = os.environ if env is None else env
    if not is_linux():
        return None
    path, appdir = env.get("APPIMAGE"), env.get("APPDIR")
    if not path or not appdir or not os.path.isfile(path):
        return None
    exe = os.path.realpath(executable or sys.executable)
    root = os.path.realpath(appdir)
    if not (exe == root or exe.startswith(root.rstrip(os.sep) + os.sep)):
        return None
    return path


def clean_env(env=None):
    """Ambiente per avviare un altro programma (o una nuova AppImage) senza le variabili di questa AppImage."""
    out = dict(os.environ if env is None else env)
    for k in RUNTIME_VARS:
        out.pop(k, None)
    return out


def relaunch_command(args=(), env=None, executable=None):
    """(comando, ambiente) per avviare FreeLaserCut di nuovo: riavvio, aggiornamento, avvio da Claude.
    Ambiente None = quello di adesso."""
    app = appimage_path(env, executable)
    if app:
        return [app, *args], clean_env(env)
    return [executable or sys.executable, "-m", "freelasercut", *args], None


def mcp_command(env=None, executable=None):
    """Comando del server MCP per Claude, o None se non gira da AppImage (allora si usa Python)."""
    app = appimage_path(env, executable)
    return {"command": app, "args": ["--mcp-server"]} if app else None


def replace_appimage(new_file, target):
    """Mette la nuova AppImage al posto di quella vecchia, nello stesso percorso (i collegamenti restano validi).
    Il file vecchio può essere in uso: su Linux la copia che gira continua a leggere il suo, e al prossimo avvio
    parte quello nuovo. Se target è un collegamento simbolico si sostituisce il file a cui punta."""
    real = os.path.realpath(target)
    folder = os.path.dirname(real)
    tmp = os.path.join(folder, f".{os.path.basename(real)}.nuova")
    if os.path.abspath(new_file) != os.path.abspath(tmp):
        shutil.copyfile(new_file, tmp)
    try:
        mode = os.stat(real).st_mode & 0o777 if os.path.exists(real) else 0o755
        os.chmod(tmp, mode | 0o755)
        os.replace(tmp, real)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return real


def folder_writable(path):
    folder = os.path.dirname(os.path.realpath(path))
    return os.path.isdir(folder) and os.access(folder, os.W_OK | os.X_OK)


# ------------------------------------------------------------------ avvio
def prefer_xcb(env=None):
    """Prima di creare QApplication. Su Wayland con XWayland disponibile sceglie X11 (xcb), salvo che la persona
    abbia scelto da sé con QT_QPA_PLATFORM (o FLC_WAYLAND=1). Ritorna True se ha impostato xcb: allora, creata
    l'applicazione, after_qapp() toglie la variabile, perché non passi ai programmi aperti da FreeLaserCut."""
    env = os.environ if env is None else env
    if not is_linux() or env.get("QT_QPA_PLATFORM") or env.get("FLC_WAYLAND") == "1":
        return False
    wayland = env.get("XDG_SESSION_TYPE") == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    if not wayland or not env.get("DISPLAY"):
        return False
    env["QT_QPA_PLATFORM"] = "xcb"
    env["FLC_XCB_SET"] = "1"
    return True


def after_qapp(app=None, env=None):
    """Dopo QApplication: nome del file .desktop (icona giusta nella barra e su Wayland) e pulizia dell'ambiente."""
    env = os.environ if env is None else env
    if env.pop("FLC_XCB_SET", None):
        env.pop("QT_QPA_PLATFORM", None)
    if app is not None and is_linux():
        try:
            app.setDesktopFileName(APP_ID)
        except Exception:  # noqa: BLE001
            pass


def ssl_fallback(env=None, candidates=CERT_FILES, default_cafile=None):
    """Python dell'AppImage cerca i certificati dove li tiene Debian: su altre distribuzioni indico il file giusto.
    Serve a scaricare gli aggiornamenti e a inviare i rapporti all'assistenza. Ritorna il file scelto o None."""
    env = os.environ if env is None else env
    if not is_linux() or env.get("SSL_CERT_FILE") or env.get("SSL_CERT_DIR"):
        return None
    if default_cafile is None:
        import ssl

        default_cafile = ssl.get_default_verify_paths().cafile or ""
    if default_cafile and os.path.isfile(default_cafile):
        return None
    for c in candidates:
        if os.path.isfile(c):
            env["SSL_CERT_FILE"] = c
            return c
    return None


def numba_cache_root(env=None):
    env = os.environ if env is None else env
    base = env.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "numba")


def numba_cleanup(root, version=None):
    """Toglie le cache di numba delle versioni precedenti dell'AppImage (una cartella per versione)."""
    if version is None:
        from . import __version__ as version
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if name.startswith(NUMBA_PREFIX) and not name.startswith(f"{NUMBA_PREFIX}{version}-"):
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
            removed += 1
    return removed


def numba_setup(env=None, executable=None):
    """Nell'AppImage: cache di numba in una cartella che non cambia a ogni avvio (vedi numba_cache.py).
    Va fatto prima che numba venga importato. Ritorna True se l'ha impostata."""
    env = os.environ if env is None else env
    if not appimage_path(env, executable) or env.get("NUMBA_CACHE_LOCATOR_CLASSES") or env.get("NUMBA_CACHE_DIR"):
        return False
    env["NUMBA_CACHE_LOCATOR_CLASSES"] = NUMBA_LOCATORS
    numba_cleanup(numba_cache_root(env))
    return True


def startup(env=None):
    """Tutto quello che va fatto su Linux prima di creare QApplication (e prima di importare numba)."""
    if not is_linux():
        return
    ssl_fallback(env)
    prefer_xcb(env)
    numba_setup(env)


# ------------------------------------------------------------------ porta USB
def tty_group(device):
    """Gruppo che può aprire la porta (dialout, uucp…), o None."""
    try:
        import grp

        return grp.getgrgid(os.stat(device).st_gid).gr_name
    except (OSError, KeyError, ImportError):
        return None


def permission_command(device=None):
    group = (tty_group(device) if device else None) or "dialout"
    if group == "root":  # porta che solo l'amministratore può aprire: il gruppo giusto non si deduce
        group = "dialout"
    return f"sudo usermod -aG {group} $USER", group


def is_permission_error(exc):
    if isinstance(exc, PermissionError):
        return True
    if getattr(exc, "errno", None) == errno.EACCES:
        return True
    text = str(exc)
    return "Permission denied" in text or "[Errno 13]" in text


def serial_hint(port, exc, tr=None):
    """Spiegazione da aggiungere all'errore di apertura della porta, oppure "" (non è un problema di permessi)."""
    if not is_linux() or not port or not str(port).startswith("/dev/") or not is_permission_error(exc):
        return ""
    tr = tr or _tr
    cmd, group = permission_command(port)
    return tr("Su Linux la porta USB si apre solo se il tuo utente è nel gruppo «{0}». Apri un terminale, scrivi "
              "{1} e premi Invio (chiede la tua password), poi esci dalla sessione e rientra (o riavvia il "
              "computer). Serve una volta sola.", group, cmd)


def tty_report():
    """Righe per il rapporto all'assistenza: porte seriali, gruppo e se questo utente le può aprire."""
    import glob

    out = []
    for dev in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")):
        ok = os.access(dev, os.R_OK | os.W_OK)
        out.append(f"{dev}: gruppo {tty_group(dev) or '?'} · accesso {'sì' if ok else 'NO'}")
    return out or ["nessuna (/dev/ttyUSB*, /dev/ttyACM*)"]


def distro(path="/etc/os-release"):
    try:
        with open(path, encoding="utf-8") as fh:
            vals = dict(line.rstrip("\n").split("=", 1) for line in fh if "=" in line)
    except OSError:
        return "?"
    name = vals.get("PRETTY_NAME") or vals.get("NAME") or "?"
    return name.strip().strip('"')


def system_lines(env=None):
    """Righe sulla parte Linux per il rapporto (senza nome utente né cartelle personali)."""
    env = os.environ if env is None else env
    lines = [f"Distribuzione: {distro()}",
             f"Sessione: {env.get('XDG_SESSION_TYPE') or '?'} · desktop {env.get('XDG_CURRENT_DESKTOP') or '?'}",
             f"Avvio da AppImage: {'sì' if appimage_path(env) else 'no'}"]
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is not None:
            lines.append(f"Qt: piattaforma {QGuiApplication.platformName()}")
    except Exception:  # noqa: BLE001
        pass
    lines += [f"Porte USB: {x}" for x in tty_report()]
    return lines


# ------------------------------------------------------------------ menu delle applicazioni
def data_home(env=None):
    env = os.environ if env is None else env
    return env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def desktop_quote(path):
    """Un argomento della riga Exec di un file .desktop, come lo vuole la specifica freedesktop: tra virgolette,
    con \\ davanti a " ` $ \\, poi ogni \\ raddoppiato (regola generale dei valori di testo) e % raddoppiato."""
    for ch in ("\\", '"', "`", "$"):
        path = path.replace(ch, "\\" + ch)
    return f'"{path}"'.replace("\\", "\\\\").replace("%", "%%")


def desktop_unquote(value):
    """Il contrario di desktop_quote (per le prove e per riconoscere una voce già scritta)."""
    v = value.replace("%%", "%").replace("\\\\", "\\")
    if not (v.startswith('"') and v.endswith('"')):
        return v
    out, i, body = [], 0, v[1:-1]
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            i += 1
        out.append(body[i])
        i += 1
    return "".join(out)


def desktop_entry(appimage, tr=None):
    tr = tr or _tr
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=FreeLaserCut",
        f"Comment={tr('Incisione e taglio laser per macchine GRBL')}",
        f"Exec={desktop_quote(appimage)} %F",
        f"TryExec={appimage.replace(chr(92), chr(92) * 2)}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Graphics;Engineering;",
        f"MimeType={MIME_TYPE};",
        "StartupWMClass=FreeLaserCut",
        "X-FreeLaserCut-AppImage=true",
        "",
    ])


MIME_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="{MIME_TYPE}">
    <comment>FreeLaserCut project</comment>
    <comment xml:lang="it">Progetto FreeLaserCut</comment>
    <icon name="{APP_ID}"/>
    <glob pattern="*.flcut"/>
  </mime-type>
</mime-info>
"""


def desktop_paths(env=None):
    base = data_home(env)
    return {"desktop": os.path.join(base, "applications", f"{APP_ID}.desktop"),
            "icon": os.path.join(base, "icons", "hicolor", "256x256", "apps", f"{APP_ID}.png"),
            "mime": os.path.join(base, "mime", "packages", f"{APP_ID}.xml")}


def install_desktop(appimage, icon_png, env=None, tr=None, run=subprocess.run):
    """Aggiunge FreeLaserCut al menu delle applicazioni e gli associa i progetti .flcut (solo per questo utente).
    Si può rifare quante volte si vuole: i file vengono riscritti. Ritorna i file scritti."""
    p = desktop_paths(env)
    for f in p.values():
        os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(p["desktop"], "w", encoding="utf-8") as fh:
        fh.write(desktop_entry(appimage, tr))
    os.chmod(p["desktop"], 0o755)  # alcuni desktop (GNOME, Xfce) avviano solo i .desktop eseguibili
    shutil.copyfile(icon_png, p["icon"])
    with open(p["mime"], "w", encoding="utf-8") as fh:
        fh.write(MIME_XML)
    base = data_home(env)
    for cmd in (["update-mime-database", os.path.join(base, "mime")],
                ["update-desktop-database", os.path.join(base, "applications")],
                ["xdg-mime", "default", f"{APP_ID}.desktop", MIME_TYPE]):
        if shutil.which(cmd[0]):
            try:
                run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, env=clean_env(), check=False)
            except (OSError, subprocess.SubprocessError):
                pass
    return list(p.values())


def desktop_installed_for(appimage, env=None):
    """True se il menu delle applicazioni ha già FreeLaserCut che punta a questo file."""
    try:
        with open(desktop_paths(env)["desktop"], encoding="utf-8") as fh:
            return f"Exec={desktop_quote(appimage)} " in fh.read()
    except OSError:
        return False


def _tr(text, *args):
    from .i18n import tr

    return tr(text, *args)
