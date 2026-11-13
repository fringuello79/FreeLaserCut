# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aggiornamento dal programma.

Legge l'ultima Release pubblicata su GitHub (fringuello79/FreeLaserCut), scarica l'installatore per Windows,
controlla lo SHA-256 con il file SHA256SUMS.txt della stessa Release e lo avvia con /AGGIORNA: l'installatore
aspetta che FreeLaserCut sia chiuso, salta le pagine già viste, installa nella stessa cartella e lo riapre.

Si collega a internet solo se la persona lo ha permesso (o se lo chiede con Aiuto → Cerca aggiornamenti) e
non manda nessun dato: una sola richiesta a api.github.com per sapere qual è l'ultima versione.
La copia del Microsoft Store si aggiorna dallo Store; chi usa il codice sorgente aggiorna con git.

Su Linux (0.18.0) la copia distribuita è un'AppImage: si scarica la nuova AppImage della stessa Release, si
controlla allo stesso modo e, alla chiusura, prende il posto del file vecchio (stesso percorso), poi si riapre.
"""
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

from . import __version__
from .i18n import tr

REPO = "fringuello79/FreeLaserCut"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
# 0.19.2: canale «anteprima». Le versioni pubblicate su GitHub come pre-release (tag vX.Y.Z-pre) non sono «latest»:
# chi non ha chiesto le anteprime continua a ricevere solo le versioni stabili, come prima; chi le ha chieste
# riceve la versione con il numero più alto fra le ultime pubblicate, stabili o in anteprima.
API_RECENT = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
SITE = "https://fringuello79.github.io/FreeLaserCut/"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
CHECK_EVERY = 24 * 3600  # controllo automatico: al massimo una volta al giorno
UNINSTALLER = "Disinstalla FreeLaserCut.exe"
_SETUP_RE = re.compile(r"(?i)^freelasercut-(\d+(?:\.\d+)*)-setup\.exe$")
_APPIMAGE_RE = re.compile(r"(?i)^freelasercut-(\d+(?:\.\d+)*)-x86_64\.appimage$")
_SUMS_RE = re.compile(r"(?i)^sha256sums(\.txt)?$")
MAX_SETUP_BYTES = 400 * 1024 * 1024


class UpdateError(Exception):
    """Problema leggibile da mostrare alla persona (rete, file, firma)."""


# ------------------------------------------------------------------ versioni
def parse_version(text):
    """«v0.10.4», «0.10.4» → (0, 10, 4). Testo senza numeri → ()."""
    m = re.search(r"\d+(?:\.\d+)*", str(text or ""))
    return tuple(int(x) for x in m.group(0).split(".")) if m else ()


def is_newer(remote, local=__version__):
    r, l = parse_version(remote), parse_version(local)
    if not r:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


# ------------------------------------------------------------------ che copia è questa
def install_dir(executable=None):
    """Cartella dell'installazione fatta con l'installatore (…\\FreeLaserCut, con python\\ e app\\ dentro), o None."""
    exe = executable or sys.executable
    py = os.path.dirname(os.path.abspath(exe))
    if os.path.basename(py).lower() != "python":
        return None
    root = os.path.dirname(py)
    return root if os.path.isfile(os.path.join(root, UNINSTALLER)) else None


def mode(executable=None):
    """«installer»: si aggiorna da qui (Windows); «appimage»: si aggiorna da qui (Linux); «store»: dal Microsoft
    Store; «manual»: codice sorgente o altro sistema."""
    forced = os.environ.get("FLC_UPDATE_MODE")
    if forced in ("installer", "appimage", "store", "manual"):
        return forced
    exe = os.path.abspath(executable or sys.executable).lower()
    here = os.path.abspath(__file__).lower()
    if "windowsapps" in exe or "windowsapps" in here:
        return "store"
    if sys.platform == "win32" and install_dir(executable):
        return "installer"
    from . import linux

    if linux.appimage_path(executable=executable):
        return "appimage"
    return "manual"


def asset_kind(m=None):
    """Quale file della Release serve a questa copia: «setup» (Windows) o «appimage» (Linux)."""
    return "appimage" if (m or mode()) == "appimage" else "setup"


# ------------------------------------------------------------------ Release di GitHub
class Release:
    def __init__(self, version, tag, name, notes, page, setup_url, setup_name, setup_size, sums_url,
                 appimage=None):
        self.version = version
        self.tag = tag
        self.name = name
        self.notes = notes
        self.page = page
        self.setup_url = setup_url
        self.setup_name = setup_name
        self.setup_size = setup_size
        self.sums_url = sums_url
        self.appimage_url, self.appimage_name, self.appimage_size = appimage or (None, None, 0)
        self.prerelease = False  # True per una versione in anteprima (vedi parse_release)

    def asset(self, kind="setup"):
        """(indirizzo, nome, dimensione) del file per Windows («setup») o per Linux («appimage»)."""
        if kind == "appimage":
            return self.appimage_url, self.appimage_name, self.appimage_size
        return self.setup_url, self.setup_name, self.setup_size

    def __repr__(self):
        return f"Release({self.version!r}, {self.setup_name!r}, {self.appimage_name!r})"


def _asset(rel, kind):
    """Come Release.asset, ma letto dagli attributi: funziona anche con oggetti simili (prove, versioni vecchie)."""
    if not rel:
        return None, None, 0
    if kind == "appimage":
        return (getattr(rel, "appimage_url", None), getattr(rel, "appimage_name", None),
                getattr(rel, "appimage_size", 0) or 0)
    return rel.setup_url, rel.setup_name, rel.setup_size or 0


def parse_release(data, allow_pre=False):
    """Dalla risposta di api.github.com/…/releases/latest. None se non è una versione utilizzabile.
    Le bozze mai; le versioni in anteprima (pre-release) solo con allow_pre."""
    if not isinstance(data, dict) or data.get("draft") or (data.get("prerelease") and not allow_pre):
        return None
    tag = str(data.get("tag_name") or "")
    ver = ".".join(str(x) for x in parse_version(tag))
    if not ver:
        return None
    setup = sums = appimage = None
    for a in data.get("assets") or []:
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if not url.startswith(DOWNLOAD_PREFIX):
            continue  # solo file di questa Release, da github.com
        m = _SETUP_RE.match(name)
        mi = _APPIMAGE_RE.match(name)
        if m and parse_version(m.group(1)) == parse_version(ver):
            setup = (url, name, int(a.get("size") or 0))
        elif mi and parse_version(mi.group(1)) == parse_version(ver):
            appimage = (url, name, int(a.get("size") or 0))
        elif _SUMS_RE.match(name):
            sums = url
    page = str(data.get("html_url") or RELEASES_PAGE)
    if not page.startswith(f"https://github.com/{REPO}/"):
        page = RELEASES_PAGE
    rel = Release(ver, tag, str(data.get("name") or tag), str(data.get("body") or ""), page,
                  setup[0] if setup else None, setup[1] if setup else None, setup[2] if setup else 0, sums, appimage)
    rel.prerelease = bool(data.get("prerelease"))
    return rel


def newest(items, allow_pre=True):
    """Dall'elenco di api.github.com/…/releases: la versione utilizzabile con il numero più alto (None se non c'è).
    A parità di numero vince quella stabile."""
    best = None
    for data in items if isinstance(items, list) else []:
        rel = parse_release(data, allow_pre)
        if rel is None:
            continue
        key = (parse_version(rel.version), not rel.prerelease)
        if best is None or key > best[0]:
            best = (key, rel)
    return best[1] if best else None


def _request(url, timeout, accept="application/octet-stream"):
    req = urllib.request.Request(url, headers={"User-Agent": f"FreeLaserCut/{__version__}", "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (solo https verso GitHub)


RETRIES = 3          # tentativi per ogni file: GitHub a volte risponde 502/503/504 per qualche secondo
RETRY_WAIT = (2, 5)  # secondi di attesa tra un tentativo e l'altro


def _transient(exc):
    """Errore di rete passeggero, per cui vale la pena riprovare (server occupato, collegamento caduto)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _retrying(fn, cancelled=None, wait=None):
    """Esegue fn() riprovando gli errori passeggeri (RETRIES volte in tutto)."""
    import time

    for n in range(RETRIES):
        try:
            return fn()
        except UpdateError:
            raise
        except OSError as exc:
            if n == RETRIES - 1 or not _transient(exc) or (cancelled is not None and cancelled()):
                raise
            (wait or time.sleep)(RETRY_WAIT[min(n, len(RETRY_WAIT) - 1)])


def _net_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return UpdateError(tr("Su GitHub non c'è ancora nessuna versione pubblicata."))
        if exc.code == 403:
            return UpdateError(tr("GitHub ha rifiutato la richiesta (troppe richieste in poco tempo): riprova più tardi."))
        if exc.code >= 500:
            return UpdateError(tr("GitHub in questo momento non risponde (errore {0}): riprova tra qualche minuto, "
                                  "oppure scarica l'installatore dal sito.", exc.code))
        return UpdateError(tr("GitHub ha risposto con l'errore {0}.", exc.code))
    reason = getattr(exc, "reason", exc)
    return UpdateError(tr("Non riesco a collegarmi a GitHub ({0}). Controlla la connessione a internet.", reason))


def fetch_latest(timeout=10.0, url=None, preview=False):
    """Ultima Release pubblicata (o None se non ce n'è una utilizzabile). Errori di rete → UpdateError.
    preview=True: conta anche le versioni in anteprima (si legge l'elenco delle ultime, non «latest»)."""
    url = url or (API_RECENT if preview else API_LATEST)
    try:
        with _request(url, timeout, "application/vnd.github+json") as r:
            data = json.loads(r.read(4_000_000 if preview else 2_000_000).decode("utf-8"))
    except urllib.error.URLError as exc:
        raise _net_error(exc) from exc
    except (OSError, ValueError) as exc:
        raise UpdateError(tr("Risposta di GitHub non valida ({0}).", exc)) from exc
    return newest(data) if preview else parse_release(data)


def expected_sha(sums_text, name):
    """Riga «<sha256>  <nome file>» (formato di sha256sum) per il file cercato."""
    for line in sums_text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and os.path.basename(m.group(2)).lower() == name.lower():
            return m.group(1).lower()
    return None


def download_dir():
    d = os.path.join(tempfile.gettempdir(), "FreeLaserCut-aggiornamento")
    os.makedirs(d, exist_ok=True)
    return d


def download(rel, dest_dir=None, progress=None, cancelled=None, timeout=30.0, wait=None, kind="setup"):
    """Scarica l'installatore (kind «setup») o l'AppImage (kind «appimage») della Release e ne controlla dimensione
    e SHA-256. Ritorna il percorso del file. progress(fatti, totali) viene chiamata durante lo scaricamento;
    cancelled() → True interrompe."""
    url, name, size = _asset(rel, kind)
    if not url:
        if kind == "appimage":
            raise UpdateError(tr("In questa versione su GitHub manca la versione per Linux (AppImage): arriverà con "
                                 "la prossima versione."))
        raise UpdateError(tr("In questa versione su GitHub manca l'installatore per Windows."))
    if not rel.sums_url:
        raise UpdateError(tr("In questa versione su GitHub manca il file SHA256SUMS.txt: senza non posso controllare "
                          "che l'installatore sia integro."))

    def get_sums():
        with _request(rel.sums_url, timeout) as r:
            return r.read(200_000).decode("utf-8", "replace")

    try:
        sums = _retrying(get_sums, cancelled, wait)
    except urllib.error.URLError as exc:
        raise _net_error(exc) from exc
    except OSError as exc:
        raise UpdateError(tr("Non riesco a scaricare SHA256SUMS.txt ({0}).", exc)) from exc
    want = expected_sha(sums, name)
    if not want:
        raise UpdateError(tr("SHA256SUMS.txt non contiene {0}: non posso controllare l'installatore.", name))
    dest_dir = dest_dir or download_dir()
    final = os.path.join(dest_dir, name)
    part = final + ".part"
    state = {}

    def get_setup():
        state["h"] = h = hashlib.sha256()
        state["done"] = done = 0
        with _request(url, timeout) as r, open(part, "wb") as fh:
            total = int(r.headers.get("Content-Length") or size or 0)
            if total > MAX_SETUP_BYTES:
                raise UpdateError(tr("L'installatore su GitHub è troppo grande: non lo scarico."))
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError(tr("Scaricamento annullato."))
                try:
                    chunk = r.read(256 * 1024)
                except http.client.HTTPException as exc:  # collegamento caduto a metà (IncompleteRead…)
                    raise ConnectionError(str(exc) or type(exc).__name__) from exc
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                state["done"] = done
                if done > MAX_SETUP_BYTES:
                    raise UpdateError(tr("L'installatore su GitHub è troppo grande: non lo scarico."))
                if progress is not None:
                    progress(done, total)
        if total and done < total:  # il server ha chiuso prima della fine: si ricomincia
            raise ConnectionError(f"scaricati {done} byte su {total}")

    try:
        _retrying(get_setup, cancelled, wait)
    except urllib.error.URLError as exc:
        _remove(part)
        raise _net_error(exc) from exc
    except UpdateError:
        _remove(part)
        raise
    except OSError as exc:
        _remove(part)
        raise UpdateError(tr("Scaricamento non riuscito ({0}).", exc)) from exc
    h, done = state["h"], state["done"]
    if size and done != size:
        _remove(part)
        raise UpdateError(tr("Scaricamento incompleto: riprova."))
    if h.hexdigest() != want:
        _remove(part)
        raise UpdateError(tr("L'installatore scaricato non corrisponde allo SHA-256 pubblicato: l'ho cancellato. "
                          "Riprova più tardi o scaricalo dal sito."))
    _remove(final)
    os.replace(part, final)
    return final


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def installer_command(path, target_dir=None):
    """Riga di comando dell'installatore in modalità aggiornamento. /D= (cartella) va per ultimo e senza
    virgolette, anche con gli spazi: è la regola di NSIS."""
    cmd = f'"{path}" /AGGIORNA'
    if target_dir:
        cmd += f" /D={os.path.normpath(target_dir)}"
    return cmd


def launch_installer(path, target_dir=None):
    """Avvia l'installatore in modalità aggiornamento, staccato da FreeLaserCut (che intanto si chiude).
    L'installatore aspetta che FreeLaserCut sia chiuso, installa nella stessa cartella e lo riapre."""
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(installer_command(path, target_dir), creationflags=flags, close_fds=True,
                                cwd=os.path.dirname(path))
    args = [path, "/AGGIORNA"] + ([f"/D={target_dir}"] if target_dir else [])
    return subprocess.Popen(args, close_fds=True, start_new_session=True, cwd=os.path.dirname(path))


# ------------------------------------------------------------------ Linux: AppImage
def appimage_target():
    """Il file .AppImage da sostituire (quello da cui gira questa copia), o None."""
    from . import linux

    return linux.appimage_path()


def apply_appimage(path, target=None):
    """Alla chiusura di FreeLaserCut: la nuova AppImage (già scaricata e controllata) prende il posto di quella
    vecchia, nello stesso percorso, così menu e collegamenti restano validi. Ritorna il percorso del file."""
    from . import linux

    target = target or appimage_target()
    if not target:
        raise UpdateError(tr("Non trovo il file AppImage di FreeLaserCut da aggiornare."))
    try:
        real = linux.replace_appimage(path, target)
    except OSError as exc:
        raise UpdateError(tr("Non riesco a sostituire {0} ({1}): la nuova versione resta in {2}.",
                             target, exc, path)) from exc
    _remove(path)
    return real


def relaunch_appimage(target, popen=None):
    """Riapre FreeLaserCut dal file AppImage (nuovo processo, staccato da questo che si sta chiudendo)."""
    from . import linux

    popen = popen or subprocess.Popen
    return popen([target], env=linux.clean_env(), start_new_session=True, close_fds=True,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 cwd=os.path.expanduser("~"))


# ------------------------------------------------------------------ in sottofondo (per l'interfaccia)
def check_async(callback, timeout=10.0, preview=False):
    """Controlla in un thread; callback(release|None, errore|None) viene chiamata dal thread:
    l'interfaccia la riporta nel thread principale con un segnale Qt."""
    def run():
        try:
            rel = fetch_latest(timeout, preview=preview) if preview else fetch_latest(timeout)
        except UpdateError as exc:
            callback(None, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            callback(None, tr("Controllo non riuscito ({0}).", exc))
            return
        callback(rel, None)
    t = threading.Thread(target=run, daemon=True, name="flc-aggiornamenti")
    t.start()
    return t
