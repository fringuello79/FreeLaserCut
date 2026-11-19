# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (Ale, 19/11/2026): più laser configurati insieme, ognuno con il suo nome, scelti da una tendina.

Ogni laser è un profilo macchina salvato in `profiles/<nome>.json` (come fino alla 0.20.8): il nome del profilo è
il nome del laser e decide il file. Qui ci sono le operazioni sull'elenco, senza interfaccia, così si provano da sole:
elenco, nome nuovo (Rinomina), laser nuovo (da un modello del catalogo o copia di quello in uso), tolto dall'elenco,
porta usata l'ultima volta da ciascun laser.

Invarianti:
- due laser non hanno mai lo stesso file: il controllo è sul file, senza badare a maiuscole e simboli
  («B1 garage» e «b1_GARAGE» finiscono nello stesso file su Windows, quindi sono lo stesso nome);
- rinominando, il file nuovo si scrive PRIMA di togliere quello vecchio: un errore lascia il laser com'era;
- un nome vuoto, solo spazi, più lungo di NAME_MAX o già usato da un altro laser non si accetta, e si dice perché.
"""
import copy
import os
import re

from .i18n import tr
from .profile import MachineProfile, config_dir

NAME_MAX = 60
PORT_KEY = "laser_port/"  # + nome del file del profilo, in minuscolo: porta usata l'ultima volta da quel laser


def profiles_dir():
    return os.path.join(config_dir(), "profiles")


def _same_path(a, b):
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)).lower() == os.path.normcase(os.path.abspath(b)).lower()


def path_for(name):
    """Il file in cui va il laser con questo nome."""
    return MachineProfile(name=str(name)).path()


def saved():
    """[(nome da mostrare, percorso)] dei laser salvati, in ordine di nome. I file rovinati non entrano.
    Due file con lo stesso nome dentro (copiati a mano) restano distinti: al secondo si aggiunge il nome del file."""
    import glob

    rows = []
    for path in glob.glob(os.path.join(profiles_dir(), "*.json")):
        try:
            name = MachineProfile.load(path).name
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        rows.append((str(name or os.path.splitext(os.path.basename(path))[0]), path))
    rows.sort(key=lambda r: (r[0].lower(), r[1].lower()))
    out, seen = [], set()
    for name, path in rows:
        label = name
        if name.lower() in seen:
            label = f"{name} ({os.path.basename(path)})"
        seen.add(name.lower())
        out.append((label, path))
    return out


def clean_name(name):
    """Spazi tolti ai lati e quelli doppi ridotti a uno."""
    return re.sub(r"\s+", " ", str(name or "")).strip()


def name_problem(name, own_path=None):
    """Perché questo nome non va bene per un laser (testo da mostrare), o None se va bene.
    own_path: il file del laser che si sta rinominando (il suo nome attuale non è «già usato»)."""
    name = clean_name(name)
    if not name:
        return tr("Scrivi un nome per il laser.")
    if len(name) > NAME_MAX:
        return tr("Il nome è troppo lungo: al massimo {0} caratteri.", NAME_MAX)
    if not re.search(r"[A-Za-z0-9]", name):
        return tr("Il nome deve avere almeno una lettera o una cifra.")
    target = path_for(name)
    if _same_path(target, own_path):
        return None
    if os.path.exists(target) or any(_same_path(target, p) for _n, p in saved()):
        return tr("C'è già un laser che si chiama così (o quasi): scegli un altro nome.")
    return None


def unique_name(base):
    """«base», o «base 2», «base 3»… il primo nome libero."""
    base = clean_name(base)[:NAME_MAX - 3].strip() or tr("Laser")
    if name_problem(base) is None:
        return base
    for i in range(2, 1000):
        cand = f"{base} {i}"
        if name_problem(cand) is None:
            return cand
    return base


def rename(profile, new_name):
    """Dà un nome nuovo al laser e sposta il suo file. -> (percorso nuovo, percorso vecchio).
    ValueError con il motivo se il nome non va bene; OSError se il file non si scrive (il laser resta com'era)."""
    old_path = profile.path()
    old_name = profile.name
    new_name = clean_name(new_name)
    why = name_problem(new_name, own_path=old_path)
    if why:
        raise ValueError(why)
    profile.name = new_name
    try:
        new_path = profile.save()
    except OSError:
        profile.name = old_name
        raise
    if os.path.exists(old_path):
        try:
            same = os.path.samefile(old_path, new_path)
        except OSError:
            same = _same_path(old_path, new_path)
        if not same:
            try:
                os.remove(old_path)
            except OSError:
                pass  # il vecchio resta nell'elenco: meglio un doppione che un laser perso
    return new_path, old_path


def create(new_name, model=None, like=None):
    """Un laser nuovo. model: un modello del catalogo (valori di targa); like: un profilo da copiare (un secondo
    laser uguale a quello in uso, con impostazioni lette e assi già provati). -> il profilo salvato.
    ValueError se il nome non va bene."""
    new_name = clean_name(new_name)
    why = name_problem(new_name)
    if why:
        raise ValueError(why)
    if like is not None:
        p = copy.deepcopy(like)
        if hasattr(p, "bed_fixed"):
            p.bed_fixed = None
    else:
        from . import machines

        p = machines.preset_profile(model) if model else MachineProfile()
    p.name = new_name
    p.save()
    return p


def remove(path, qs=None):
    """Toglie un laser dall'elenco (cancella il suo file). -> True se è stato tolto."""
    if not path or not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    if qs is not None:
        qs.remove(_port_key(path))
    return True


def _port_key(path):
    return PORT_KEY + os.path.splitext(os.path.basename(str(path)))[0].lower()


def remember_port(qs, profile, port):
    if qs is not None and port:
        qs.setValue(_port_key(profile.path()), str(port))


def port_for(qs, profile):
    """La porta con cui questo laser è stato collegato l'ultima volta, o ""."""
    if qs is None:
        return ""
    return str(qs.value(_port_key(profile.path()), "") or "")


def move_port(qs, old_path, new_path):
    """Dopo «Rinomina»: la porta ricordata segue il laser."""
    if qs is None or _port_key(old_path) == _port_key(new_path):
        return
    v = qs.value(_port_key(old_path), "")
    if v:
        qs.setValue(_port_key(new_path), v)
    qs.remove(_port_key(old_path))
