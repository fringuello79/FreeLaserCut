# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Servizio finto della Galleria per le prove (stesse regole essenziali di FreeLaserCut-galleria, in piccolo).

Gira su 127.0.0.1 in un filo a parte e tiene tutto in memoria. Registra ogni richiesta ricevuta (`richieste`), così le
prove possono guardare che cosa è partito davvero dal programma. `guasto` fa rispondere male apposta.
"""
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Finta:
    def __init__(self):
        self.lavori = {}      # id -> dict (scheda + stato, chiave, parti, voti…)
        self.richieste = []   # [(metodo, percorso, intestazioni, corpo)]
        self.ia = "ok"        # ok | no:<motivo> | attesa | nascondi
        self.guasto = None    # vedi _guasto()
        self.interrotte = 0   # risposte che il programma ha smesso di leggere a metà
        self.limite = 5
        self._n = 0
        self._per_inst = {}
        finta = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _manda(self, stato, corpo, tipo="application/json"):
                if isinstance(corpo, (dict, list)):
                    corpo = json.dumps(corpo).encode("utf-8")
                self.send_response(stato)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                try:
                    self.wfile.write(corpo)
                except (BrokenPipeError, ConnectionResetError):
                    finta.interrotte += 1  # il programma ha smesso di leggere (risposta troppo grande): è quello che deve fare

            def _tutto(self, metodo):
                n = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(n) if n else b""
                finta.richieste.append((metodo, self.path, {k.lower(): v for k, v in self.headers.items()}, corpo))
                try:
                    stato, out, tipo = finta.rispondi(metodo, self.path, self.headers, corpo)
                except Exception as exc:  # noqa: BLE001
                    stato, out, tipo = 500, {"errore": "interno", "messaggio": str(exc)}, "application/json"
                self._manda(stato, out, tipo)

            def do_GET(self):
                self._tutto("GET")

            def do_POST(self):
                self._tutto("POST")

            def do_PUT(self):
                self._tutto("PUT")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        self.filo = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.filo.start()

    def chiudi(self):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------
    def _pubblico(self, l, con_stato=False):
        out = {k: l.get(k) for k in ("id", "titolo", "descrizione", "categoria", "materiale", "spessore_mm",
                                     "laser_famiglia", "potenza_w", "tipo", "larghezza_mm", "altezza_mm", "tempo_s",
                                     "licenza", "autore_nome", "versione_flc", "foto_n")}
        voti = list(l["voti"].values())
        out.update({"pubblicato": 1, "nuovo": True, "stelle_media": round(sum(voti) / len(voti), 1) if voti else None,
                    "stelle_n": len(voti), "fatti_n": len(l["fatti"]), "scaricati_n": l["scaricati"]})
        if con_stato:
            out.update({"stato": l["stato"], "motivo": l["motivo"]})
        return out

    def _parti(self, l):
        p = ["progetto", "anteprima", "mini"]
        for i in range(1, l["foto_n"] + 1):
            p += [f"foto{i}", f"foto{i}mini"]
        return p

    def rispondi(self, metodo, percorso, h, corpo):
        J = "application/json"
        u = urllib.parse.urlsplit(percorso)
        p = u.path.strip("/").split("/")[1:]
        q = dict(urllib.parse.parse_qsl(u.query))
        g = self.guasto
        if g == "non_json":
            return 200, b"<html>pagina di un proxy</html>", "text/html"
        if g == "enorme":
            return 200, b"[" + b"1," * 20_000_000 + b"1]", J  # 40 MB: molto più di quanto il programma deve leggere
        if g == "errore_500":
            return 500, b"errore", "text/plain"
        a = p[0] if p else ""
        b = p[1] if len(p) > 1 else ""
        c = p[2] if len(p) > 2 else ""
        inst = h.get("X-FLC-Installazione") or ""
        chiave = h.get("X-FLC-Chiave") or ""
        dati = None
        if metodo == "POST":
            try:
                dati = json.loads(corpo.decode("utf-8")) if corpo else {}
            except ValueError:
                return 400, {"errore": "json", "messaggio": "richiesta non valida"}, J
        if metodo == "GET" and a == "elenco":
            if g == "elenco_ostile":
                return 200, {"pagina": 0, "altre": False, "lavori": [
                    {"id": "../../etc", "titolo": "id non valido"},
                    {"id": "ostile0001", "titolo": "<b>grassetto</b><img src=x onerror=1>" + "A" * 500, "descrizione": 12,
                     "categoria": "armi", "tipo": 7, "materiale": ["x"], "stelle_media": "cinque", "stelle_n": -3,
                     "fatti_n": 1e99, "licenza": "tutta mia", "autore_nome": "x\ny", "potenza_w": True, "foto_n": 99},
                    "non è un dizionario"]}, J
            righe = [l for l in self.lavori.values() if l["stato"] == "pubblico"]
            if q.get("categoria"):
                righe = [l for l in righe if l["categoria"] == q["categoria"]]
            if q.get("tipo"):
                righe = [l for l in righe if l["tipo"] == q["tipo"]]
            if q.get("cerca"):
                righe = [l for l in righe if q["cerca"].lower() in (l["titolo"] + " " + l["descrizione"]).lower()]
            ordine = q.get("ordine", "voti")
            if ordine == "fatti":
                righe.sort(key=lambda l: -len(l["fatti"]))
            elif ordine == "voti":
                righe.sort(key=lambda l: -(sum(l["voti"].values()) / len(l["voti"]) if l["voti"] else 0))
            else:
                righe.sort(key=lambda l: -l["n"])
            pag = int(q.get("pagina", 0))
            fetta = righe[pag * 24:pag * 24 + 25]
            return 200, {"pagina": pag, "altre": len(fetta) > 24, "lavori": [self._pubblico(l) for l in fetta[:24]]}, J
        if metodo == "POST" and a == "condividi":
            if not re.fullmatch(r"[0-9a-f-]{32,64}", inst):
                return 401, {"errore": "installazione", "messaggio": "installazione non riconosciuta"}, J
            if dati.get("regole_accettate") is not True:
                return 400, {"errore": "regole", "messaggio": "regole"}, J
            if dati.get("opera_mia") is not True:
                return 400, {"errore": "opera_mia", "messaggio": "opera mia"}, J
            if not re.fullmatch(r"[0-9a-f]{64}", str(dati.get("impronta", ""))):
                return 400, {"errore": "campo", "messaggio": "impronta"}, J
            for l in self.lavori.values():
                if l["impronta"] == dati["impronta"] and l["stato"] in ("attesa", "pubblico", "nascosto"):
                    return 409, {"errore": "doppione", "messaggio": "già nella Galleria", "id": l["id"]}, J
            self._per_inst[inst] = self._per_inst.get(inst, 0) + 1
            if self._per_inst[inst] > self.limite:
                return 429, {"errore": "limite", "messaggio": "limite di oggi"}, J
            self._n += 1
            ident = "lavoro%04d" % self._n
            l = dict(dati)
            l.update({"id": ident, "n": self._n, "chiave": "chiave-autore-%020d" % self._n, "stato": "caricamento",
                      "motivo": "", "parti": {}, "voti": {}, "fatti": set(), "segnalazioni": {}, "scaricati": 0,
                      "inst": inst, "foto_n": int(dati.get("foto_n") or 0)})
            self.lavori[ident] = l
            if g == "risposta_condividi":
                return 201, {"id": "x", "chiave_autore": "y", "carica": []}, J
            return 201, {"id": ident, "chiave_autore": l["chiave"], "carica": self._parti(l)}, J
        l = self.lavori.get(b) if a not in ("voto", "fatto", "segnala") else self.lavori.get(str((dati or {}).get("id")))
        if a == "admin":
            return 403, {"errore": "admin", "messaggio": "non autorizzato"}, J
        if l is None or l["stato"] == "tolto":
            return 404, {"errore": "non_trovato", "messaggio": "lavoro non trovato"}, J
        if metodo == "PUT" and a == "carica":
            if chiave != l["chiave"]:
                return 403, {"errore": "chiave", "messaggio": "chiave sbagliata"}, J
            if c not in self._parti(l):
                return 400, {"errore": "parte", "messaggio": "parte sconosciuta"}, J
            if g == "carica_rifiuta" and c == "anteprima":
                return 413, {"errore": "file_grande", "messaggio": "file troppo grande"}, J
            l["parti"][c] = corpo
            return 200, {"ok": True, "parte": c}, J
        if metodo == "POST" and a == "concludi":
            if chiave != l["chiave"]:
                return 403, {"errore": "chiave", "messaggio": "chiave sbagliata"}, J
            mancano = [x for x in self._parti(l) if x not in l["parti"]]
            if mancano:
                return 400, {"errore": "mancano", "messaggio": "mancano dei file", "mancano": mancano}, J
            if self.ia == "ok":
                l["stato"] = "pubblico"
            elif self.ia.startswith("no:"):
                l["stato"], l["motivo"] = "rifiutato", "ia:" + self.ia[3:]
            elif self.ia == "nascondi":
                l["stato"], l["motivo"] = "nascosto", "ia:not_laser"
            else:
                l["stato"], l["motivo"] = "attesa", "ia:IA non disponibile"
            return 200, {"id": l["id"], "stato": l["stato"], "motivo": l["motivo"]}, J
        if metodo == "GET" and a == "lavoro":
            if l["stato"] == "pubblico":
                return 200, self._pubblico(l), J
            if chiave == l["chiave"]:
                return 200, self._pubblico(l, True), J
            return 404, {"errore": "non_trovato", "messaggio": "lavoro non trovato"}, J
        if metodo == "GET" and a in ("file", "anteprima", "foto"):
            mio = a == "anteprima" and l["stato"] in ("attesa", "nascosto") and chiave and chiave == l["chiave"]
            if l["stato"] != "pubblico" and not mio:  # come il servizio vero (0.22.0): l'autore vede la sua anteprima
                return 404, {"errore": "non_trovato", "messaggio": "lavoro non trovato"}, J
            if a == "file":
                l["scaricati"] += 1
                if isinstance(g, tuple) and g[0] == "file":
                    return 200, g[1], "application/zip"
                return 200, l["parti"]["progetto"], "application/zip"
            if a == "anteprima":
                if isinstance(g, tuple) and g[0] == "anteprima":
                    return 200, g[1], "image/png"
                return 200, l["parti"]["anteprima"], "image/png"
            return 200, l["parti"].get("foto" + c, b""), "image/jpeg"
        if metodo == "POST" and a in ("voto", "fatto", "segnala"):
            if not re.fullmatch(r"[0-9a-f-]{32,64}", inst):
                return 401, {"errore": "installazione", "messaggio": "installazione non riconosciuta"}, J
            if l["stato"] != "pubblico":
                return 404, {"errore": "non_trovato", "messaggio": "lavoro non trovato"}, J
            if a == "segnala":
                l["segnalazioni"][inst] = dati.get("motivo")
                if len(l["segnalazioni"]) >= 3 or dati.get("motivo") == "non_adatto":
                    l["stato"], l["motivo"] = "nascosto", "segnalato:" + str(dati.get("motivo"))
                return 200, {"ok": True}, J
            if l["inst"] == inst:
                return 403, {"errore": "proprio", "messaggio": "è un tuo lavoro"}, J
            if a == "voto":
                l["voti"][inst] = int(dati.get("stelle"))
            else:
                l["fatti"].add(inst)
            return 200, self._pubblico(l), J
        if metodo == "POST" and a == "togli":
            if chiave != l["chiave"]:
                return 403, {"errore": "chiave", "messaggio": "chiave sbagliata"}, J
            l["stato"], l["parti"] = "tolto", {}
            return 200, {"ok": True}, J
        return 404, {"errore": "non_trovato", "messaggio": "indirizzo sconosciuto"}, J
