# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""MakerHub dentro FreeLaserCut (0.18.10, per ora fra le funzioni in prova).

MakerHub (maker-hub.it) è un servizio esterno, di altri: qui c'è solo il collegamento.
1 i suoi generatori (per esempio «Scatola a incastri») si aprono nel browser, sul loro sito;
2 «FreeLaserCut Live»: un disegno preparato sul loro sito arriva sul piano di lavoro. Il programma si collega una
  volta con un codice di 6 caratteri, poi è sempre lui a chiedere a MakerHub se c'è un lavoro (nessuna porta aperta).

Il protocollo («FreeLaserCut Live», versione 1) e il client di esempio da cui questo modulo deriva li ha scritti e
forniti MakerHub, con il permesso di usarli in FreeLaserCut.

Scelte di FreeLaserCut, più strette dell'esempio:
- non si manda il nome del computer né quello del progetto aperto; modello e area della macchina solo se l'utente lo
  chiede; nessuna immagine del piano;
- nessuna chiamata di rete finché l'utente non collega MakerHub o non chiede di aggiornare l'elenco;
- gli indirizzi che si aprono nel browser devono essere https e di maker-hub.it;
- un lavoro non può mai avviare il laser, e prima di arrivare sul piano l'utente lo conferma.

Questo modulo non usa Qt per la rete e non tocca la finestra: la parte a schermo è in ui/dialogs_makerhub.py.
"""
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .i18n import tr

PROTOCOL = 1
SERVER = "https://app.maker-hub.it/ponte"
SITE = "https://maker-hub.it/"
DOMAIN = "maker-hub.it"
FORMATS = ("svg", "dxf")
MAX_DATA = 4 * 1024 * 1024  # il disegno di un lavoro, in byte
MAX_REPLY = 6 * 1024 * 1024  # una risposta del server
WAIT_S = 25  # quanto il server tiene aperta la richiesta quando non c'è niente

KEY_TOKEN = "makerhub_token"
KEY_TOOLS = "makerhub_tools"  # l'ultimo elenco letto da MakerHub (JSON)
KEY_MACHINE = "makerhub_send_machine"

# L'elenco di partenza: quello documentato nel protocollo. Il resto arriva da MakerHub quando l'utente lo chiede.
BUILTIN_TOOLS = [{
    "id": "scatola", "name": "Scatola a incastri",
    "description": "Misure esterne o interne, coperchio, gioco: i pezzi escono già compensati per il kerf.",
    "url": "https://app.maker-hub.it/?pagina=laser&scheda=scatola&da=freelasercut", "send": True}]

WORK_MODES = {"taglio": "line", "incisione": "fill"}
COLOR_TOL2 = 3 * 48 ** 2  # quanto un colore del disegno può scostarsi da quello dichiarato (somma dei quadrati RGB)


class BridgeError(Exception):
    """Errore con un messaggio da mostrare all'utente. code = stato HTTP, se c'è."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def clean(text, limit=80):
    """Un testo arrivato da fuori, pronto per essere mostrato: una riga, niente caratteri di controllo, niente
    parentesi angolari (le finestre di Qt le leggerebbero come HTML), lunghezza limitata."""
    s = "".join(ch if ch.isprintable() else " " for ch in str(text if text is not None else ""))
    s = re.sub(r"\s+", " ", s).strip().replace("<", "‹").replace(">", "›")
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def safe_url(url):
    """L'indirizzo, se è https e di maker-hub.it; altrimenti None (un elenco sbagliato non porta l'utente altrove)."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or not (host == DOMAIN or host.endswith("." + DOMAIN)):
        return None
    return u.geturl()


def parse_tools(data):
    """L'elenco di MakerHub (GET …/flc/strumenti) -> [{id, name, description, url, send}], solo le voci per tutti e
    con un indirizzo valido."""
    out, seen = [], set()
    items = data.get("strumenti") if isinstance(data, dict) else None
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get("per_tutti") is False:
            continue  # «in prova» sul loro sito: non si mostra
        url, name = safe_url(it.get("url")), clean(it.get("nome"), 60)
        tid = clean(it.get("id"), 40) or name
        if not url or not name or tid in seen:
            continue
        seen.add(tid)
        out.append({"id": tid, "name": name, "description": clean(it.get("descrizione"), 200), "url": url,
                    "send": it.get("manda_a_freelasercut") is True})
        if len(out) >= 30:
            break
    return out


def saved_tools(qs):
    """L'elenco da mostrare: l'ultimo letto da MakerHub, se c'è ed è ancora valido; altrimenti quello di partenza."""
    try:
        raw = json.loads(qs.value(KEY_TOOLS) or "null")
    except (TypeError, ValueError):
        raw = None
    tools = []
    for t in raw if isinstance(raw, list) else []:
        if isinstance(t, dict) and safe_url(t.get("url")) and clean(t.get("name"), 60):
            tools.append({"id": clean(t.get("id"), 40), "name": clean(t.get("name"), 60),
                          "description": clean(t.get("description"), 200), "url": safe_url(t.get("url")),
                          "send": t.get("send") is True})
    return tools or [dict(t) for t in BUILTIN_TOOLS]


def _local(host):
    return host in ("127.0.0.1", "localhost", "::1")


class Bridge:
    """Il collegamento con MakerHub. Tutte le chiamate bloccano: vanno fatte in un filo secondario."""

    def __init__(self, token=None, server=None, timeout=40):
        self.server = (server or SERVER).rstrip("/")
        self.token = token or None
        self.timeout = timeout
        u = urllib.parse.urlsplit(self.server)
        if u.scheme != "https" and not (u.scheme == "http" and _local(u.hostname or "")):
            raise BridgeError(tr("L'indirizzo di MakerHub deve essere https"))

    # ------------------------------------------------------------------ rete
    def _open(self, req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(MAX_REPLY + 1)
        except urllib.error.HTTPError as exc:
            msg = ""
            try:
                msg = json.loads(exc.read(20000).decode("utf-8")).get("errore") or ""
            except (ValueError, AttributeError, OSError):
                pass
            raise BridgeError(clean(msg, 200) or tr("MakerHub ha risposto con l'errore {0}", exc.code), exc.code)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise BridgeError(tr("MakerHub non è raggiungibile: {0}", clean(getattr(exc, "reason", exc), 120)))
        if len(body) > MAX_REPLY:
            raise BridgeError(tr("La risposta di MakerHub è troppo grande"))
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BridgeError(tr("La risposta di MakerHub non si legge"))
        if not isinstance(data, dict):
            raise BridgeError(tr("La risposta di MakerHub non si legge"))
        return data

    def _headers(self):
        return {"Content-Type": "application/json", "User-Agent": f"FreeLaserCut/{__version__} MakerHubLive/{PROTOCOL}"}

    def _post(self, path, data, timeout=None):
        req = urllib.request.Request(self.server + path, data=json.dumps(data).encode("utf-8"), method="POST",
                                     headers=self._headers())
        return self._open(req, timeout or self.timeout)

    # ------------------------------------------------------------------ elenco dei generatori
    def tools(self):
        req = urllib.request.Request(self.server + "/flc/strumenti", headers={"User-Agent": self._headers()["User-Agent"]})
        return parse_tools(self._open(req, 15))

    # ------------------------------------------------------------------ collegamento
    @staticmethod
    def normalize_code(code):
        return re.sub(r"[\s-]", "", str(code or "")).upper()

    def pair(self, code):
        """Scambia il codice (6 caratteri, scritto dall'utente) con il token permanente. -> il token."""
        code = self.normalize_code(code)
        if not re.fullmatch(r"[A-Z0-9]{4,12}", code):
            raise BridgeError(tr("Il codice è fatto di 6 lettere e numeri: copialo da MakerHub"))
        try:
            r = self._post("/abbina", {"codice": code, "computer": "", "versione": __version__, "app": "freelasercut"})
        except BridgeError as exc:
            if exc.code == 403:
                raise BridgeError(tr("Codice sbagliato o scaduto: generane un altro su MakerHub (vale 10 minuti)"), 403)
            if exc.code == 429:
                raise BridgeError(tr("Troppi tentativi: riprova fra 10 minuti"), 429)
            raise
        token = r.get("token")
        if not isinstance(token, str) or not 8 <= len(token) <= 512 or not token.isprintable():
            raise BridgeError(tr("La risposta di MakerHub non si legge"))
        self.token = token
        return token

    # ------------------------------------------------------------------ lavori
    def wait(self, seconds=WAIT_S):
        """I lavori in arrivo: [{id, title, op, problems}], di solito nessuno. Blocca fino a `seconds` secondi."""
        if not self.token:
            raise BridgeError(tr("FreeLaserCut non è collegato a MakerHub"))
        r = self._post("/attesa", {"token": self.token, "documento": "", "versione": __version__, "attesa": seconds,
                                   "massimo": 1}, timeout=seconds + 15)
        jobs = []
        cmds = r.get("comandi")
        for cmd in cmds if isinstance(cmds, list) else []:
            if not isinstance(cmd, dict) or isinstance(cmd.get("id"), bool) or not isinstance(cmd.get("id"), int):
                continue
            ops = cmd.get("operazioni")
            for op in (ops if isinstance(ops, list) and ops else [{}])[:1]:  # un disegno per lavoro
                jobs.append({"id": cmd["id"], "title": clean(cmd.get("titolo"), 80), "op": op, "problems": validate(op)})
        return jobs

    def result(self, job_id, ok, message="", state=None):
        return self._post("/esito", {"token": self.token, "id": int(job_id), "ok": bool(ok),
                                     "messaggio": str(message)[:1000], "stato": state or {}})


def machine_state(profile=None):
    """Quello che FreeLaserCut dice di sé a MakerHub insieme all'esito: sempre la versione; modello e area di lavoro
    solo se l'utente l'ha chiesto (profile non None)."""
    st = {"programma": f"FreeLaserCut {__version__}"}
    if profile is not None:
        st["macchina"] = clean(getattr(profile, "model", "") or getattr(profile, "name", ""), 60)
        st["area_mm"] = [round(float(profile.bed_x), 1), round(float(profile.bed_y), 1)]
    return st


# ============================================================================ controlli su un lavoro
_BAD_SVG = re.compile(r"<\s*script|javascript:|<\s*foreignObject|<!ENTITY|<!DOCTYPE[^>]*\[", re.I)
# href: solo riferimenti interni (#id). Così restano fuori i file, gli indirizzi e anche le immagini incorporate.
_OUTSIDE = re.compile(r"""href\s*=\s*["']\s*(?!#)""", re.I)


def _color(text):
    m = re.fullmatch(r"#([0-9A-Fa-f]{6})", str(text or "").strip())
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else None


def _number(v, lo, hi):
    """Un numero vero dentro [lo, hi] (i valori fuori vengono portati al limite); None se non è un numero."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return min(max(float(v), lo), hi)


def validate(op):
    """I controlli PRIMA di importare un lavoro. -> lista di problemi (vuota = va bene)."""
    if not isinstance(op, dict) or op.get("op") != "lavoro":
        return [tr("non è un lavoro")]
    bad = []
    if op.get("protocollo") != PROTOCOL:
        bad.append(tr("protocollo {0} non supportato (questo FreeLaserCut conosce il {1})",
                      clean(op.get("protocollo"), 12), PROTOCOL))
    if op.get("avvia_il_laser"):
        bad.append(tr("un lavoro di MakerHub non può avviare il laser"))
    fmt = op.get("formato")
    if fmt not in FORMATS:
        bad.append(tr("formato non previsto"))
    data = op.get("dati")
    if not isinstance(data, str) or not data.strip():
        bad.append(tr("disegno vuoto"))
    elif len(data.encode("utf-8", "replace")) > MAX_DATA:
        bad.append(tr("disegno troppo grande"))
    elif fmt == "svg" and (_BAD_SVG.search(data) or _OUTSIDE.search(data)):
        bad.append(tr("il disegno contiene script, immagini o riferimenti a file esterni"))
    name = op.get("file")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name) or ".." in name:
        bad.append(tr("nome del file non valido"))
    elif fmt in FORMATS and not name.lower().endswith("." + fmt):
        bad.append(tr("nome del file non valido"))
    unit = op.get("unita")
    if unit not in (None, "mm"):
        bad.append(tr("unità di misura non prevista"))
    levels = op.get("livelli")
    if levels is not None and not isinstance(levels, list):
        bad.append(tr("livelli non validi"))
    return bad


# ============================================================================ dal lavoro alle forme
class Plan:
    """Un lavoro letto ma non ancora messo nel progetto: le forme (già sui livelli scelti), le impostazioni da dare
    a quei livelli, le note per l'utente."""

    def __init__(self):
        self.shapes = []
        self.layers = []  # [(indice, modo, {speed, power_max, passes}, compensato)]
        self.notes = []
        self.other = None  # livello degli oggetti con un colore non previsto
        self.other_count = 0
        self.size = (0.0, 0.0)
        self.title = self.material = ""
        self.thickness = None
        self.kerf = 0.0

    def apply_layers(self, doc):
        """Dà ai livelli scelti modo e valori di partenza. Sono livelli che nessuna forma usava: il lavoro già fatto
        non cambia. Ordine di lavoro: dopo quello che c'è già sul piano, prima le incisioni e per ultimi i tagli
        (un pezzo tagliato può muoversi o cadere: va inciso prima)."""
        mine = {ly[0] for ly in self.layers} | ({self.other} if self.other is not None else set())
        top = max([c.priority for c in doc.used_layers() if c.index not in mine] + [0])
        if self.other is not None:
            doc.layer(self.other).priority = top + 1
        for idx, mode, values, compensated in self.layers:
            cs = doc.layer(idx)
            cs.mode = mode
            cs.output = True
            cs.priority = top + (2 if mode == "line" else 1)
            for k, v in values.items():
                setattr(cs, k, v)
            if compensated and mode == "line":
                cs.kerf = 0.0  # i pezzi sono già cresciuti di mezzo taglio: niente seconda compensazione
        if self.other is not None:
            doc.layer(self.other).mode = "line"


def plan_job(op, doc):
    """Legge il disegno di un lavoro valido. -> Plan. Non cambia il progetto (i livelli si impostano dopo la conferma).
    Solleva ValueError con un messaggio per l'utente se il disegno non si legge o è vuoto."""
    from .core import io_formats, ops

    plan = Plan()
    plan.title = clean(op.get("titolo"), 80)
    plan.material = clean(op.get("materiale"), 60)
    plan.thickness = _number(op.get("spessore_mm"), 0.0, 1000.0)
    plan.kerf = _number(op.get("kerf_compensato_mm"), 0.0, 5.0) or 0.0
    used = {leaf.layer for s in doc.all_shapes() for leaf, _ in s.leaves()}
    n_layers = len(io_formats.LAYER_COLORS)

    def free(prefer):
        for i in list(range(prefer, n_layers)) + list(range(prefer)):
            if i not in used:
                used.add(i)
                return i
        return None

    entries = []  # [(rgb, indice del livello)]
    levels = op.get("livelli")
    for lv in levels if isinstance(levels, list) else []:
        if not isinstance(lv, dict):
            continue
        rgb, mode = _color(lv.get("colore")), WORK_MODES.get(lv.get("lavoro"))
        if rgb is None or mode is None or any(rgb == e[0] for e in entries):
            continue
        idx = free(io_formats.nearest_layer(rgb))
        if idx is None:
            break  # tutti i livelli sono già usati: il disegno arriva con i colori più vicini, senza impostazioni
        values = {}
        power = _number(lv.get("potenza_pct"), 0.0, 100.0)
        speed = _number(lv.get("velocita_mm_min"), 10.0, 60000.0)
        passes = _number(lv.get("passate"), 1, 20)
        if power is not None:
            values["power_max"] = power
        if speed is not None:
            values["speed"] = speed
        if passes is not None:
            values["passes"] = int(round(passes))
        entries.append((rgb, idx))
        plan.layers.append((idx, mode, values, plan.kerf > 0))

    def layer_of(rgb):
        if not entries:
            return io_formats.nearest_layer(rgb)  # nessun livello dichiarato: come un import normale
        if rgb is not None:
            d, idx = min((sum((a - b) ** 2 for a, b in zip(rgb, e[0])), e[1]) for e in entries)
            if d <= COLOR_TOL2:
                return idx
        if plan.other is None:
            plan.other = free(1)
            if plan.other is None:
                plan.other = entries[0][1]
        plan.other_count += 1
        return plan.other

    data = op["dati"]
    try:
        if op["formato"] == "svg":
            shapes = io_formats.import_svg(data.encode("utf-8"), doc, layer_of=layer_of)
        else:
            with tempfile.TemporaryDirectory(prefix="flc_makerhub_") as tmp:
                path = os.path.join(tmp, "disegno.dxf")
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(data)
                shapes = io_formats.import_dxf(path, doc, layer_of=layer_of)
    except Exception as exc:  # noqa: BLE001 — qualunque file rovinato: un messaggio, mai un blocco
        raise ValueError(tr("il disegno non si legge: {0}", clean(exc, 160)))
    if not shapes:
        raise ValueError(tr("il disegno è vuoto"))
    b = ops.union_bounds(shapes)
    if not all(math.isfinite(v) for v in (b.width(), b.height())) or b.width() > 20000 or b.height() > 20000:
        raise ValueError(tr("il disegno ha misure non credibili"))
    plan.shapes = shapes
    plan.size = (b.width(), b.height())
    drawn = {leaf.layer for s in shapes for leaf, _ in s.leaves()}
    plan.layers = [ly for ly in plan.layers if ly[0] in drawn]  # un livello dichiarato ma senza linee non si tocca
    if plan.other is not None and plan.other not in drawn:
        plan.other = None
    if plan.kerf > 0:
        plan.notes.append(tr("Il taglio è già compensato da MakerHub ({0:g} mm): sui livelli di taglio di questo "
                             "disegno la compensazione di FreeLaserCut è a zero, lasciala così.", plan.kerf))
    if any(v for _i, _m, v, _c in plan.layers):
        plan.notes.append(tr("Potenza e velocità sono i valori di partenza proposti da MakerHub: controllali sui "
                             "livelli, e se hai dubbi fai prima un test materiale."))
    if plan.other_count:
        plan.notes.append(tr("{0} oggetti hanno un colore che MakerHub non ha dichiarato: sono sul livello {1}, "
                             "controlla che cosa devono fare.", plan.other_count, doc.layer(plan.other).label()))
    for raw in (op.get("note") if isinstance(op.get("note"), list) else [])[:5]:
        note = clean(raw, 240)
        if note and "kerf" not in note.lower():  # del kerf parla già la nota qui sopra, con i nomi di FreeLaserCut
            plan.notes.append(tr("MakerHub: {0}", note))
    return plan
