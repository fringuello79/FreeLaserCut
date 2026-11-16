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
)


def endless(names=NAMES):
    """I nomi uno dopo l'altro, senza fine, per riempire la trama della schermata di avvio: sempre nell'ordine
    dell'elenco, e finito l'elenco si ricomincia dal primo (Ale, 16/11 sera: «nomi ordinati come all'inizio»)."""
    names = [n for n in names if n and n.strip()]
    while names:
        yield from names


def same_size_repeats(rows, sizes, sep="·", min_diff=1):
    """Quante volte un nome ricompare con la STESSA grandezza dell'ultima volta (deve essere zero: lo stesso nome,
    se ripetuto, ha grandezze diverse). rows: da layout_rows; sizes: la grandezza di ogni riga; due grandezze sono
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


def row_count(names, pos, measure, width, lead="", gap=9.0, sep="·"):
    """Quanti nomi interi entrano in una riga larga `width` partendo dal nome numero `pos` dell'elenco ripetuto
    (almeno uno: un nome più largo della riga resta da solo). Stessa regola di layout_rows."""
    n = len(names)
    if n == 0:
        return 0
    sep_w = measure(sep)
    used, k = 0.0, 0
    while k < n:  # in una riga lo stesso nome non compare due volte
        name = names[(pos + k) % n]
        w = measure(f"{lead}\u00a0\u00a0\u00a0{name}" if (k == 0 and lead) else name)
        need = w if k == 0 else used + gap + sep_w + gap + w
        if k and need > width:
            break
        used, k = need, k + 1
    return k


def plan_sizes(names, rows, sizes, count, total_max, first_max, min_diff=4, step=5, limit=4000):
    """Sceglie la grandezza di ogni riga della trama (Ale, 16/11: grandezze irregolari, alternate, e lo stesso nome
    quando ricompare ha una grandezza diversa), con i nomi sempre nell'ordine dell'elenco.
    sizes: le grandezze possibili; count(riga, posizione nell'elenco, grandezza) -> quanti nomi entrano nella riga;
    total_max: somma massima delle grandezze (lo spazio in altezza); first_max: grandezza massima della prima riga
    (deve starci «Grazie a»); min_diff: quanto devono distare due grandezze dello stesso nome; step: quanto devono
    distare due righe vicine. Cerca in ordine, preferendo grande dopo piccola e piccola dopo grande, e si ferma alla
    prima disposizione che riempie lo spazio senza righe con un nome solo; se non c'è, tiene la migliore trovata.
    -> elenco delle grandezze, una per riga (None se non esiste nessuna disposizione valida)."""
    names = list(names)
    n = len(names)
    small, big = sorted(sizes), sorted(sizes, reverse=True)
    lo = small[0]
    best = [None, None]
    nodes = [0]

    def rec(r, pos, chosen, last, total, singles):
        if r == rows:
            score = (singles, total_max - total)
            if best[0] is None or score < best[0]:
                best[0], best[1] = score, list(chosen)
            return singles == 0 and total_max - total <= 2 * lo // 3
        order = small if (chosen and chosen[-1] > (lo + big[0]) / 2) else big
        for px in order:
            if r == 0 and px > first_max:
                continue
            if chosen and abs(px - chosen[-1]) < step:
                continue
            if total + px + (rows - r - 1) * lo > total_max:
                continue
            nodes[0] += 1
            if nodes[0] > limit:
                return True
            k = count(r, pos, px)
            row = [names[(pos + j) % n] for j in range(k)] if n else []
            if any(abs(last.get(nm, -10 ** 6) - px) < min_diff for nm in row):
                continue
            new_last = dict(last)
            new_last.update((nm, px) for nm in row)
            chosen.append(px)
            stop = rec(r + 1, pos + k, chosen, new_last, total + px, singles + (k == 1))
            chosen.pop()
            if stop:
                return True
        return False

    rec(0, 0, [], {}, 0, 0)
    return best[1]


def layout_rows(seq, measure, width, rows, lead="", gap=9.0, sep="·"):
    """Dispone i nomi su `rows` righe larghe `width`: in ogni riga solo nomi interi, separati da «·», distribuiti da
    un bordo all'altro; i nomi proseguono di seguito nelle righe sotto. La prima riga comincia con `lead` («Grazie
    a») seguito da tre spazi e dal primo nome, come un pezzo solo.
    seq: iteratore di nomi (endless()); measure(testo) -> larghezza; gap: spazio minimo attorno a «·».
    Righe di grandezza diversa: measure e gap possono essere elenchi, uno per riga.
    -> [[(testo, x, larghezza), …], …] con x dal bordo sinistro della riga (i «·» sono pezzi come i nomi)."""
    measures = list(measure) if isinstance(measure, (list, tuple)) else [measure] * rows
    gaps = list(gap) if isinstance(gap, (list, tuple)) else [gap] * rows
    out, pending = [], None
    for r in range(rows):
        measure, gap = measures[r], gaps[r]
        sep_w = measure(sep)
        items, used = [], 0.0
        while True:
            if pending is None:
                try:
                    pending = next(seq)
                except StopIteration:
                    break
            text = f"{lead}\u00a0\u00a0\u00a0{pending}" if (r == 0 and not items and lead) else pending
            w = measure(text)
            need = w if not items else used + gap + sep_w + gap + w
            if items and need > width:
                break
            items.append((text, w))
            used = need
            pending = None
        if not items:
            out.append([])
            continue
        n = len(items)
        total = sum(w for _, w in items) + (n - 1) * sep_w
        space = (width - total) / (2 * (n - 1)) if n > 1 else 0.0
        row, x = [], 0.0
        for i, (text, w) in enumerate(items):
            if i:
                row.append((sep, x + space, sep_w))
                x += space + sep_w + space
            row.append((text, x, w))
            x += w
        out.append(row)
    return out
