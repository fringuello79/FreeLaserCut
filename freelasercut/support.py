# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Invio del rapporto per l'assistenza (0.17.7). Nessuna parte di questo modulo usa Qt.

Il rapporto parte SOLO quando la persona preme «Invia» nella finestra Aiuto → Invia un rapporto all'assistenza,
dopo aver dato il consenso (informativa privacy). Va al ricevitore del progetto (un'app web di Google Apps Script
sull'account del progetto, tools/rapporti/Codice.gs): FreeLaserCut ne conosce solo l'indirizzo pubblico, nessuna
password. In alternativa si apre il programma di posta con il messaggio già scritto."""
import base64
import json
import urllib.parse
import urllib.request

from . import __version__

SUPPORT_EMAIL = "freelasercut@gmail.com"
# indirizzo dell'app web che riceve i rapporti (finisce con /exec); vuoto = solo email e file
# ricevitore del progetto (tools/rapporti/Codice.gs), app web pubblica: nessuna password
SUPPORT_URL = "https://script.google.com/macros/s/AKfycbwHXQ_g8x61Sx2EMIOmR1U4QC3Tmtz_mz6YQTKnXa9NGzfSaxjM1f-54olE3T1ughuD/exec"
PRIVACY_URL = "https://fringuello79.github.io/FreeLaserCut/privacy.html"
MAX_BYTES = 9 * 1024 * 1024  # il ricevitore accetta fino a 10 MB


def can_send(url=None):
    return bool((url if url is not None else SUPPORT_URL).strip())


def payload(zip_bytes, code, user=None, contact="", summary=""):
    u = user or {}
    desc = ("Cosa stavi facendo:\n{0}\n\nCosa ti aspettavi:\n{1}\n\nCosa è successo:\n{2}\n\nSuccede: {3}").format(
        u.get("facevi", ""), u.get("aspettavi", ""), u.get("successo", ""), u.get("frequenza", ""))
    return {"app": "FreeLaserCut", "versione": __version__, "codice": code, "oggetto": u.get("oggetto", ""),
            "descrizione": desc, "contatto": contact or "", "riassunto": summary[:30000],
            "zip": base64.b64encode(zip_bytes).decode("ascii")}


def send(zip_path, code, user=None, contact="", summary="", url=None, timeout=60, opener=None):
    """Manda il rapporto. Ritorna (True, codice) oppure (False, motivo)."""
    url = (url if url is not None else SUPPORT_URL).strip()
    if not url:
        return False, "nessun indirizzo di invio"
    if not url.startswith("https://"):
        return False, "indirizzo non sicuro"
    with open(zip_path, "rb") as fh:
        data = fh.read()
    if len(data) > MAX_BYTES:
        return False, "rapporto troppo grande"
    body = json.dumps(payload(data, code, user, contact, summary)).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "text/plain;charset=utf-8",
                                          "User-Agent": f"FreeLaserCut/{__version__}"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001  rete assente, proxy, errore del server
        return False, str(exc)[:200]
    try:
        res = json.loads(txt)
    except ValueError:
        return False, "risposta non valida"
    if res.get("ok"):
        return True, str(res.get("codice") or code)
    return False, str(res.get("errore") or "errore del ricevitore")[:200]


def mailto(code, user=None, summary=""):
    """Indirizzo «mailto:» con destinatario, oggetto e testo già scritti (l'allegato lo aggiunge la persona)."""
    u = user or {}
    subject = f"[FLC rapporto] {__version__} · {code}" + (f" · {u.get('oggetto')}" if u.get("oggetto") else "")
    body = ("Ciao, ti mando il rapporto per l'assistenza (il file .zip allegato: trascinalo qui).\n\n"
            f"Codice: {code}\n\nCosa stavo facendo:\n{u.get('facevi', '')}\n\nCosa mi aspettavo:\n"
            f"{u.get('aspettavi', '')}\n\nCosa è successo:\n{u.get('successo', '')}\n\nSuccede: {u.get('frequenza', '')}\n")
    if summary:
        body += "\n— riassunto tecnico —\n" + summary[:1500]
    q = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{SUPPORT_EMAIL}?{q}"
