# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.16: le prove automatiche su GitHub girano una volta sola per versione e quattro suite insieme.

Che cosa cambia:
- `.github/workflows/prove.yml`: il push di un tag non fa più ripartire le prove (è lo stesso codice del push sul
  ramo); la pubblicazione degli installatori resta sul tag, com'era;
- `tests/run_tests.py`: con `FLC_PROVE_INSIEME=4` (o `--insieme 4`) le suite girano quattro alla volta e vengono
  riportate nell'ordine di sempre. Una suite che fallisce mentre gira insieme ad altre viene riprovata da sola e conta
  la seconda volta. Senza la variabile tutto resta com'era: una suite alla volta.

Casi: quante insieme (variabile, argomento, valori senza senso); una alla volta = subito e in ordine; insieme = in
coda, poi tutte, non più di N alla volta, riportate in ordine anche se finiscono in disordine; fallita insieme e
riuscita da sola; fallita due volte; interrotta senza righe KO; tempo scaduto; preferenze separate per ogni suite;
il file delle prove di GitHub; l'elenco delle suite (ognuna esiste, tutte prima del riepilogo).
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import run_tests as rt  # noqa: E402  (non fa partire niente: le prove stanno sotto «if __name__ == "__main__"»)

checks = []


def check(name, cond, info=""):
    checks.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


# ------------------------------------------------------------------ quante insieme
pf = rt.parallel_from
check("senza dire niente: una suite alla volta, come sempre", pf([], {}) == 1 and rt.PARALLEL == 1)
check("FLC_PROVE_INSIEME=4: quattro insieme", pf([], {"FLC_PROVE_INSIEME": "4"}) == 4)
check("«--insieme 3» vale più della variabile", pf(["x", "--insieme", "3"], {"FLC_PROVE_INSIEME": "8"}) == 3)
check("valori senza senso: uno; zero o negativi: uno; troppi: sedici al massimo",
      [pf([], {"FLC_PROVE_INSIEME": v}) for v in ("molte", "", "0", "-3", "99")] == [1, 1, 1, 1, 16]
      and pf(["--insieme"], {}) == 1 and pf(["--insieme", "x"], {}) == 1)


# ------------------------------------------------------------------ una finta macchina delle prove
class Fake:
    """Al posto dei processi veri: ogni suite dura quanto le si dice e riesce o no secondo il copione."""

    def __init__(self, script):
        self.script = script  # nome -> (durata, [esito della 1ª volta, della 2ª…]); esito: "ok", "ko", "crash"
        self.calls = []  # (nome, quante giravano in quel momento, compresa lei)
        self.running = 0
        self.peak = 0
        self.lock = threading.Lock()

    def __call__(self, name, args):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            n = sum(1 for c in self.calls if c[0] == name)
            self.calls.append((name, self.running))
        dur, outcomes = self.script[name]
        time.sleep(dur)
        with self.lock:
            self.running -= 1
        what = outcomes[min(n, len(outcomes) - 1)]
        if what == "ok":
            return 0, f"OK  {name} primo\nOK  {name} secondo\n", ""
        if what == "ko":
            return 1, f"OK  {name} primo\nKO  {name} secondo\n", ""
        return -11, "", "Segmentation fault"


def run(fake, names, parallel):
    """Mette in fila le suite come fa il file delle prove e raccoglie quello che viene stampato e contato."""
    del rt.results[:], rt._queue[:]
    rt.PARALLEL = parallel
    real = rt._run_one
    rt._run_one = fake
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            for n in names:
                rt.run_suite(n, f"Etichetta {n}")
            before = len(fake.calls)
            rt.flush(fake)
    finally:
        rt._run_one = real
        rt.PARALLEL = 1
    return buf.getvalue(), list(rt.results), before


names = [f"s{i}" for i in range(10)]
# ------------------------------------------------------------------ una alla volta
f = Fake({n: (0.01, ["ok"]) for n in names})
out, res, before = run(f, names, 1)
check("una alla volta: ogni suite parte subito, in ordine, mai due insieme, niente in coda",
      before == 10 and [c[0] for c in f.calls] == names and f.peak == 1 and not rt._queue, (before, f.peak))
check("…tutte riportate e contate (2 controlli per suite)", len(res) == 20 and all(ok for _n, ok in res)
      and [l for l in out.splitlines() if l.startswith("Etichetta")] == [f"Etichetta {n}" for n in names])

# ------------------------------------------------------------------ insieme
f = Fake({n: (0.25 - 0.02 * i, ["ok"]) for i, n in enumerate(names)})  # le ultime finiscono prima
t0 = time.time()
out, res, before = run(f, names, 4)
took = time.time() - t0
check("insieme: finché non si arriva in fondo non parte niente (restano in coda), poi girano tutte",
      before == 0 and sorted(c[0] for c in f.calls) == sorted(names) and not rt._queue, before)
check("…quattro alla volta, non di più e non una sola", f.peak == 4, f.peak)
check("…riportate nell'ordine di sempre anche se finiscono in disordine",
      [l for l in out.splitlines() if l.startswith("Etichetta")] == [f"Etichetta {n}" for n in names]
      and len(res) == 20 and all(ok for _n, ok in res), out[-300:])
check("…e ci mettono meno che una alla volta", took < 0.8 * sum(0.25 - 0.02 * i for i in range(10)), took)
check("…mentre girano si vede l'avanzamento ([1/10] … [10/10])", "[1/10]" in out and "[10/10]" in out)

# ------------------------------------------------------------------ fallita insieme, riuscita da sola
script = {n: (0.05, ["ok"]) for n in names}
script["s3"] = (0.05, ["ko", "ok"])
script["s7"] = (0.05, ["crash", "ok"])
f = Fake(script)
out, res, before = run(f, names, 4)
again = [c for c in f.calls if c[0] in ("s3", "s7")]
check("una suite che fallisce insieme alle altre viene riprovata, una volta, e da sola",
      [c[0] for c in f.calls].count("s3") == 2 and [c[0] for c in f.calls].count("s7") == 2
      and all(c[1] == 1 for c in f.calls[10:]) and len(f.calls) == 12, f.calls[10:])
check("…se da sola riesce conta come riuscita, e il rapporto lo dice",
      all(ok for _n, ok in res) and len(res) == 20 and out.count("riprovata da sola: riuscita") == 2
      and "Etichetta s3  [fallita insieme alle altre" in out, [r for r in res if not r[1]])

# ------------------------------------------------------------------ fallita due volte
script = {n: (0.03, ["ok"]) for n in names}
script["s2"] = (0.03, ["ko"])
script["s5"] = (0.03, ["crash"])
f = Fake(script)
out, res, before = run(f, names, 4)
bad = [n for n, ok in res if not ok]
check("una suite rotta resta rossa anche dopo il secondo tentativo, con il suo controllo fallito",
      "KO  s2 secondo" in bad and out.count("riprovata da sola: fallita di nuovo") == 2, bad)
check("…e una che si interrompe senza dire perché viene contata come fallita, con il codice e l'errore",
      "s5" in bad and "la suite si è interrotta (codice -11)" in out and "Segmentation fault" in out and len(bad) == 2, bad)
check("…le altre non ne risentono", sum(1 for _n, ok in res if ok) == 8 * 2 + 1, len(res))
f = Fake({"sola": (0.01, ["ko"])})
out, res, before = run(f, ["sola"], 1)
check("una alla volta non c'è nessun secondo tentativo: com'era prima", len(f.calls) == 1 and [ok for _n, ok in res] == [True, False])
del rt.results[:]
with contextlib.redirect_stdout(io.StringIO()):
    rt.flush()
check("niente in coda: non succede niente", not rt.results)

# ------------------------------------------------------------------ i processi veri
d = tempfile.mkdtemp()
good = os.path.join(d, "buona.py")
with open(good, "w", encoding="utf-8") as fh:
    fh.write('import os, sys\nprint("OK  misure 10 × 20 →", sys.argv[1:])\nprint("INI", os.environ["FLC_SETTINGS_INI"])\n'
             'print("QT", os.environ["QT_QPA_PLATFORM"])\n')
rc, out, err = rt._run_one(good, ("banco",))
rc2, out2, err2 = rt._run_one(good, ())
ini = [l for l in (out + out2).splitlines() if l.startswith("INI")]
check("una suite vera: gira in un processo suo, con i suoi argomenti, senza finestre e con i caratteri giusti",
      rc == 0 and "OK  misure 10 × 20 → ['banco']" in out and "QT offscreen" in out, (rc, out, err))
check("…ogni suite ha le sue preferenze, mai quelle di un'altra (né quelle di chi lancia le prove)",
      len(ini) == 2 and ini[0] != ini[1] and os.environ["FLC_SETTINGS_INI"] not in ini[0], ini)
real_run = subprocess.run


def slow(*a, **k):
    raise subprocess.TimeoutExpired(a[0], k.get("timeout"), output="OK  primo\n")


subprocess.run = slow
try:
    rc, out, err = rt._run_one(good, ())
finally:
    subprocess.run = real_run
check("una suite che non finisce più viene fermata e contata come fallita, senza far cadere tutte le prove",
      rc == 124 and "OK  primo" in out and "tempo scaduto" in err and rt._failed(rc, out), (rc, out, err))

# ------------------------------------------------------------------ il file di GitHub e l'elenco delle suite
yml = src(".github", "workflows", "prove.yml")
push = yml[yml.index("on:"):yml.index("permissions:")]
check("su GitHub le prove partono dal push sui rami e non più anche dal push dei tag",
      re.search(r"push:\s*\n\s+branches: \[\"\*\*\"\]", push) and "tags" not in push.replace("un tag", ""), push)
check("…restano le proposte di modifica e l'avvio a mano, e i documenti continuano a non farle partire",
      "pull_request:" in push and "workflow_dispatch:" in push and push.count('paths-ignore: ["docs/**", "**.md"]') == 2)
check("…quattro suite insieme, sempre su Windows e su Linux, con lo stesso comando",
      'FLC_PROVE_INSIEME: "4"' in yml and "windows-latest" in yml and "ubuntu-24.04" in yml
      and "run: python tests/run_tests.py" in yml)
inst = src(".github", "workflows", "installatore.yml")
check("gli installatori si costruiscono ancora dal tag, com'era, e non dipendono dalle prove lunghe",
      re.search(r"push:\s*\n\s+tags: \[\"v\*\"\]", inst) and "run_tests.py" not in inst)
code = src("tests", "run_tests.py")
main = code[code.index('if __name__ == "__main__":'):]
suites = re.findall(r'run_suite\("([^"]+)"', main)
check("ogni suite dell'elenco esiste, nessuna è scritta due volte con gli stessi argomenti",
      len(suites) > 100 and all(os.path.exists(os.path.join(HERE, s)) for s in set(suites))
      and len(re.findall(r'run_suite\("[^"]+",\s*"(?:[^"\\]|\\.)*"(?:,\s*"[a-z]+")?\)', main))
      == len(set(re.findall(r'run_suite\("([^"]+)",\s*"(?:[^"\\]|\\.)*"((?:,\s*"[a-z]+")?)\)', main))),
      [s for s in set(suites) if not os.path.exists(os.path.join(HERE, s))])
check("le suite in coda vengono eseguite prima del riepilogo, dopo l'ultima dell'elenco",
      main.count("    flush()\n") == 1 and main.rindex("run_suite(") < main.index("    flush()\n") < main.index("ko = [n for n, ok in results")
      and "PARALLEL = parallel_from(sys.argv, os.environ)" in main[:200])

code_ = 0 if all(checks) else 1
print(f"\n{sum(checks)}/{len(checks)} superati")
sys.exit(code_)
