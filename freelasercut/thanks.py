# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Ringraziamenti (0.20.5): l'elenco di chi ha aiutato FreeLaserCut a migliorare.

È l'UNICO posto in cui stanno i nomi. Lo usano la schermata di avvio (i nomi «incisi» dietro al logo), la targa
in Aiuto → Ringraziamenti, e una prova automatica controlla che README e sito riportino gli stessi nomi.
Solo i nomi, senza scrivere per che cosa. Si aggiunge un nome solo con il consenso della persona: chi vuole comparire
lo scrive nel campo «Nome per i ringraziamenti» del rapporto all'assistenza.
Nessuna dipendenza da Qt: la schermata di avvio lo importa prima delle librerie pesanti.
"""
NAMES = (
    "Stefano Modena",
    "MakerHub",
    "leone2805",
    "Evoluzione2",
    "rinosp",
    "Brenda-IT",
    "giorgiobattisti56-wq",
    "giuseppegrassano77-coder",
    "OrsoLaser",
    "Roberto C.",
    "SpikeTheDragon40k",
    "Deborah",
    "Paolo1968",  # 0.20.6: rapporto del 18/11
    "DolomiticHunter",  # 0.20.6: rapporto del 18/11
    "Mauro C.",  # 0.20.9: donazione (Ale, 19/11)
    "Gianni",  # 0.20.9: rapporto del 19/11
    "marcello",  # 0.20.9: rapporto del 19/11
    "Sengir",  # 0.21.1: rapporti sul Falcon A1 (Ale, 19/11)
    "Daniel Z.",  # 0.21.2: rapporti e spinta sui social (Ale, 20/11)
    "solboricua",  # 0.21.2: rapporto E698 dal Mac M1 (20/11)
    "universalecinema-boop",  # 0.22.2: GitHub (Ale, 22/11)
    "Paul H.",  # 0.22.2: chiesto da Ale (22/11 sera)
    "Michele S.",  # 0.22.4: richiesta della grandezza dei caratteri (Ale, 23/11)
    "LaserJack",  # 0.22.4: rapporto del 23/11 (Atomstack X30 Pro)
)
# 0.22.2 (Ale, 22/11): i co-sviluppatori. L'UNICO posto in cui stanno; li mostrano Aiuto → Informazioni, la targa dei
# ringraziamenti, il README e il sito (una prova controlla che siano gli stessi). Restano anche nell'elenco qui sopra.
CODEV = ("Evoluzione2", "Stefano Modena")


def codev_text(joiner=" e "):
    """«Evoluzione2 e Stefano Modena»: i co-sviluppatori in una riga (joiner: la congiunzione nella lingua giusta)."""
    names = [n for n in CODEV if n and n.strip()]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + joiner + names[-1] if names else ""


def endless(names=NAMES):
    """I nomi uno dopo l'altro, senza fine, per riempire la trama della schermata di avvio: sempre nell'ordine
    dell'elenco, e finito l'elenco si ricomincia dal primo (Ale, 16/11 sera: «nomi ordinati come all'inizio»)."""
    names = [n for n in names if n and n.strip()]
    while names:
        yield from names


def same_size_repeats(rows, sizes, sep="·", min_diff=1):
    """Quante volte un nome ricompare con la STESSA grandezza dell'ultima volta (deve essere zero: lo stesso nome,
    se ripetuto, ha grandezze diverse). rows: da place_rows; sizes: la grandezza di ogni riga; due grandezze sono
    «diverse» se distano almeno min_diff."""
    last, bad = {}, 0
    for row, size in zip(rows, sizes):
        for text, _x, _w in row:
            if text == sep:
                continue
            name = text.split("\u00a0")[-1]
            if name in last and abs(last[name] - size) < min_diff:
                bad += 1
            last[name] = size
    return bad


def row_width(names, pos, k, measure, lead="", gap=9.0, sep="·"):
    """Larghezza minima di una riga con k nomi interi a partire dal nome numero `pos` dell'elenco ripetuto
    (con «Grazie a» davanti al primo se c'è `lead`): nomi, «·» e lo spazio minimo attorno a ogni «·»."""
    n = len(names)
    w = 0.0
    for j in range(k):
        name = names[(pos + j) % n]
        w += measure(f"{lead}\u00a0\u00a0\u00a0{name}" if (j == 0 and lead) else name)
    return w + (k - 1) * (measure(sep) + 2 * gap)


# Le passate della ricerca in plan_rows, dalla più esigente alla meno: (quanto devono distare le grandezze di uno
# stesso nome quando ricompare, quanto devono distare due righe vicine, quanto spazio può restare vuoto in fondo)
PASSES = ((4, 4, 8), (4, 3, 16), (3, 3, 28), (3, 2, 44), (2, 2, 70), (2, 1, 10 ** 6), (2, 0, 10 ** 6), (1, 0, 10 ** 6))


def plan_rows(n, rows, fit, size_min, size_max, total_max, first_max, counts=(2, 3, 4, 5), limit=8000, ok=None,
              fallback=True, passes=PASSES):
    """Decide, riga per riga, QUANTI nomi mettere e con che GRANDEZZA (Ale, 16/11: grandezze irregolari, alternate,
    lo stesso nome quando ricompare ha una grandezza diversa, nomi sempre nell'ordine dell'elenco).
    Ogni riga ha almeno due nomi, così va sempre da un bordo all'altro; la sua grandezza è al massimo quella a cui
    quei nomi ci stanno ancora (fit), quindi le righe con pochi nomi corti vengono grandi e quelle con tanti nomi
    piccole. Quanti nomi stanno in una riga dipende dal carattere del sistema: per questo si decide a ogni avvio.
    Un nome resta da solo in una riga soltanto se lui e il successivo, insieme, non ci stanno nemmeno alla grandezza
    più piccola (nomi molto lunghi con un carattere molto largo).
    n: quanti nomi ha l'elenco; fit(riga, posizione, k) -> la grandezza più grande a cui k nomi dalla posizione data
    stanno nella riga (0 se non ci stanno nemmeno alla più piccola); total_max: somma massima delle grandezze (lo
    spazio in altezza); first_max: grandezza massima della prima riga.
    Cerca in ordine, alternando righe grandi e piccole, con le richieste di PASSES via via meno esigenti; se
    nemmeno l'ultima riesce (non dovrebbe succedere), due nomi per riga alla grandezza che ci sta.
    ok(riga, posizione, k, grandezza) (0.20.7, facoltativo): False se la riga così resta troppo vuota (trama fitta,
    senza grandi spazi fra i nomi); vale per le righe con almeno due nomi. fallback=False: None invece dell'ultima
    risorsa, così chi chiama può riprovare con richieste meno severe.
    -> [(quanti nomi, grandezza), …], una voce per riga."""
    if n <= 0:
        return [(0, size_min)] * rows
    counts = [k for k in counts if k <= n] or [min(n, 1)]
    mid = (size_min + size_max) / 2

    def top_size(r, pos, k):
        px = min(size_max, fit(r, pos, k))
        if k == 1:
            px = max(px, size_min)  # un nome da solo si mette comunque, alla più piccola se non ci sta
        return min(px, first_max) if r == 0 else px

    def alone(r, pos):
        """Il nome in questa posizione deve stare da solo: con il successivo non ci sta nemmeno alla più piccola."""
        return n > 1 and counts[0] > 1 and top_size(r, pos, counts[0]) < size_min

    def search(min_diff, step, slack_max):
        nodes = [0]
        found = []

        def rec(r, pos, chosen, last, total):
            if r == rows:
                if total_max - total <= slack_max:
                    found[:] = chosen
                    return True
                return False
            prev = chosen[-1][1] if chosen else None
            order = counts if (prev is None or prev < mid) else list(reversed(counts))  # dopo una piccola, una grande
            if alone(r, pos):
                order = [1]
            for k in order:
                top = top_size(r, pos, k)
                for px in range(top, size_min - 1, -2):  # la più grande che ci sta, poi via via più piccola
                    if prev is not None and abs(px - prev) < step:
                        continue
                    left = rows - r - 1
                    if total + px + left * size_min > total_max or total + px + left * size_max < total_max - slack_max:
                        continue
                    nodes[0] += 1
                    if nodes[0] > limit:
                        return True
                    if ok is not None and k > 1 and not ok(r, pos, k, px):
                        continue
                    idx = [(pos + j) % n for j in range(k)]
                    if any(abs(last.get(i, -10 ** 6) - px) < min_diff for i in idx):
                        continue
                    new_last = dict(last)
                    new_last.update((i, px) for i in idx)
                    chosen.append((k, px))
                    stop = rec(r + 1, pos + k, chosen, new_last, total + px)
                    chosen.pop()
                    if stop:
                        return True
            return False

        rec(0, 0, [], {}, 0)
        return list(found) or None

    for min_diff, step, slack in passes:
        got = search(min_diff, step, slack)
        if got:
            return got
    if not fallback:
        return None
    out, pos = [], 0  # ultima risorsa: due nomi per riga (uno, se nemmeno due ci stanno), alla grandezza che ci sta
    for r in range(rows):
        k = 1 if alone(r, pos) else next((k for k in counts if top_size(r, pos, k) >= size_min), 1)
        out.append((k, max(size_min, min(top_size(r, pos, k), total_max // rows))))
        pos += k
    return out


def place_rows(names, plan, measures, width, lead="", gaps=9.0, sep="·"):
    """Dispone i nomi secondo il piano di plan_rows: nella riga r i suoi k nomi, di seguito, distribuiti da un bordo
    all'altro con un «·» fra l'uno e l'altro; la prima comincia con `lead` («Grazie a»), tre spazi e il primo nome,
    come un pezzo solo. measures: una funzione testo -> larghezza per ogni riga.
    -> [[(testo, x dal bordo sinistro della riga, larghezza), …], …] (i «·» sono pezzi come i nomi)."""
    names = list(names)
    n = len(names)
    out, pos = [], 0
    for r, (k, _px) in enumerate(plan):
        measure = measures[r]
        if not n or k <= 0:
            out.append([])
            continue
        texts = [names[(pos + j) % n] for j in range(k)]
        pos += k
        if r == 0 and lead:
            texts[0] = f"{lead}\u00a0\u00a0\u00a0{texts[0]}"
        ws = [measure(t) for t in texts]
        sep_w = measure(sep)
        space = (width - sum(ws) - (k - 1) * sep_w) / (2 * (k - 1)) if k > 1 else 0.0
        row, x = [], 0.0
        for i, (t, w) in enumerate(zip(texts, ws)):
            if i:
                row.append((sep, x + space, sep_w))
                x += space + sep_w + space
            row.append((t, x, w))
            x += w
        out.append(row)
    return out
