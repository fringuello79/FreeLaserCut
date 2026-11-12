# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0: un tentativo per i due utenti con Windows 10 a 64 bit a cui il programma non parte.

Ipotesi (da confermare con i loro registri): dalla 2.4 NumPy dà per scontate le istruzioni «x86-64-v2» (SSSE3,
SSE4.1, SSE4.2); sui processori di prima (Intel Core 2, AMD Phenom II / Athlon II: PC che spesso hanno ancora Windows
10) «import numpy» fa chiudere il programma di colpo. Rimedio: l'installatore porta anche una NumPy di prima (2.3) in
una cartella a parte, e all'avvio la si mette davanti SOLO su quei processori. Sui PC normali non cambia niente.

Il dato: (istruzioni del processore, cartella delle librerie compatibili presente o no, forzatura) →
librerie compatibili attive / non attive / mancanti, e una riga nei registri che lo dice.

Casi: lettura delle istruzioni (Linux, Windows, processore sconosciuto); processore vecchio / moderno / sconosciuto;
con e senza cartella; forzature; ordine nell'avvio (prima di qualsiasi libreria, anche con --self-test); riga
nell'intestazione dei registri di un avvio vero; installatore e prova su GitHub; le librerie fissate vanno d'accordo.
Non provato qui: un processore davvero senza SSE4.2, e Windows.
"""
import os
import re
import subprocess
import sys
import tempfile
import types

TMP = tempfile.mkdtemp(prefix="flc_cpu_")
os.environ["APPDATA"] = os.path.join(TMP, "dati")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "dati")
os.environ["FLC_NO_DIALOGS"] = "1"
os.makedirs(os.environ["APPDATA"])
for k in ("FLC_CPU_COMPAT", "FLC_PROVA_CPU", "FLC_PROVA_COMPAT"):
    os.environ.pop(k, None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "build"))
from freelasercut import startup_guard as g  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


MODERN = "sse3 ssse3 sse4_1 sse4_2 avx avx2"
PHENOM = "flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm 3dnowext 3dnow constant_tsc rep_good nopl nonstop_tsc cpuid extd_apicid pni monitor cx16 popcnt lahf_lm cmp_legacy svm extapic cr8_legacy abm sse4a misalignsse 3dnowprefetch\n"
HASWELL = "processor\t: 0\nflags\t\t: fpu sse sse2 pni pclmulqdq ssse3 fma cx16 sse4_1 sse4_2 movbe popcnt aes xsave avx f16c rdrand avx2 bmi2\n"
CORE2 = "flags\t\t: fpu sse sse2 pni ssse3 cx16 lahf_lm\n"

# ================================================================== lettura delle istruzioni
check("Linux: da /proc/cpuinfo di un AMD Phenom II si legge solo SSE3 (mancano SSSE3, SSE4.1, SSE4.2)",
      g.cpuinfo_features(PHENOM) == {"sse3"}, g.cpuinfo_features(PHENOM))
check("…di un Intel Core 2: SSE3 e SSSE3; di un processore del 2013: tutto fino ad AVX2",
      g.cpuinfo_features(CORE2) == {"sse3", "ssse3"} and g.cpuinfo_features(HASWELL) == {"sse3", "ssse3", "sse4_1", "sse4_2", "avx", "avx2"})
check("…processore non x86 (nessuna riga «flags»): non si sa", g.cpuinfo_features("Features\t: fp asimd\n") is None)
check("processore vecchio = manca almeno una fra SSSE3, SSE4.1, SSE4.2; se non si sa, non lo si tratta da vecchio",
      g.old_cpu({"sse3"}) and g.old_cpu({"sse3", "ssse3"}) and g.old_cpu({"sse3", "ssse3", "sse4_1"})
      and not g.old_cpu(set(MODERN.split())) and not g.old_cpu({"ssse3", "sse4_1", "sse4_2"}) and not g.old_cpu(None))
asked = []
fake_ct = types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=types.SimpleNamespace(
    IsProcessorFeaturePresent=lambda code: (asked.append(code), code in (13, 36))[1])))
real_ct, real_sys = sys.modules.get("ctypes"), g.sys
sys.modules["ctypes"] = fake_ct
g.sys = types.SimpleNamespace(platform="win32", prefix=sys.prefix, executable=sys.executable, modules=sys.modules)
g._state.pop("cpu", None)
feats = g.cpu_features()
g.sys = real_sys
if real_ct is not None:
    sys.modules["ctypes"] = real_ct
check("Windows: le istruzioni si chiedono al sistema (IsProcessorFeaturePresent), senza caricare niente di pesante",
      feats == {"sse3", "ssse3"} and set(asked) == {13, 36, 37, 38, 39, 40, 41}, (feats, asked))
g._state.pop("cpu", None)
real = g.cpu_features()
check("su questa macchina la lettura vera funziona (un insieme di nomi, oppure «non si sa»)",
      real is None or (isinstance(real, set) and real <= {"sse3", "ssse3", "sse4_1", "sse4_2", "avx", "avx2", "avx512f"}), real)

# ================================================================== quando si attivano
COMPAT = os.path.join(TMP, "site-compat")
os.makedirs(os.path.join(COMPAT, "numpy"))
with open(os.path.join(COMPAT, "numpy", "__init__.py"), "w") as fh:
    fh.write('__version__ = "2.3.5-compatibile"\n')
PROBE = ("import sys; sys.path.insert(0, sys.argv[1]); from freelasercut import startup_guard as g; r = g.compat_libs(); "
         "import numpy; print(r, numpy.__version__, g._state.get('compat'), '|', g.cpu_line())")


def probe(cpu=None, compat=COMPAT, force=None):
    env = dict(os.environ)
    for k, v in (("FLC_PROVA_CPU", cpu), ("FLC_PROVA_COMPAT", compat), ("FLC_CPU_COMPAT", force)):
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run([sys.executable, "-c", PROBE, ROOT], capture_output=True, text=True, env=env, timeout=120)
    return (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1]


out = probe("sse3")
check("processore vecchio + cartella presente: le librerie compatibili vanno davanti (si carica la NumPy di prima)",
      out.startswith("True 2.3.5-compatibile attive"), out)
check("…e la riga per i registri lo dice: istruzioni trovate, quelle che mancano, librerie compatibili attive",
      "Istruzioni del processore: sse3 (mancano: ssse3 sse4_1 sse4_2" in out and "librerie compatibili: attive" in out, out)
out = probe(MODERN)
check("processore moderno: non cambia niente (NumPy di sempre), anche se la cartella c'è",
      out.startswith("False ") and "compatibile" not in out.split("|")[0] and "mancano" not in out
      and "librerie compatibili" not in out and "avx2" in out, out)
out = probe("sse3", compat=os.path.join(TMP, "non-esiste"))
check("processore vecchio ma cartella assente (programma non installato con l'installatore): niente da mettere davanti, "
      "e i registri dicono «mancanti»", out.startswith("False ") and "librerie compatibili: mancanti" in out, out)
out = probe(MODERN, force="1")
check("FLC_CPU_COMPAT=1 le forza anche su un processore moderno (serve alle prove e all'assistenza)",
      out.startswith("True 2.3.5-compatibile attive"), out)
out = probe("sse3", force="0")
check("FLC_CPU_COMPAT=0 le vieta anche su un processore vecchio", out.startswith("False ") and "2.3.5-compatibile" not in out, out)
out = probe("sse3 ssse3 sse4_1")
check("manca solo SSE4.2: è ancora un processore vecchio", out.startswith("True 2.3.5-compatibile"), out)
g._state.pop("cpu", None)
os.environ["FLC_PROVA_CPU"] = MODERN
before = list(sys.path)
check("in questo processo, con un processore moderno: il percorso delle librerie resta identico",
      g.compat_libs() is False and sys.path == before and g._state.get("compat") == "")
os.environ.pop("FLC_PROVA_CPU")

# ================================================================== nell'avvio vero
main_src = open(os.path.join(ROOT, "freelasercut", "__main__.py"), encoding="utf-8").read()
body = main_src.split("def boot():")[1]
check("all'avvio è la prima cosa: prima della prova di avvio (--self-test), della guardia e di qualsiasi libreria",
      body.index("guard.compat_libs()") < body.index("--self-test") < body.index("guard.install()") < body.index("from PySide6")
      and "import numpy" not in main_src and "PySide6" not in main_src.split("def boot():")[0])
BROKEN = os.path.join(TMP, "compat-rotta")
os.makedirs(os.path.join(BROKEN, "numpy"))
with open(os.path.join(BROKEN, "numpy", "__init__.py"), "w") as fh:
    fh.write('raise ImportError("NumPy compatibile finta: caricata proprio lei")\n')
data = os.path.join(TMP, "avvio")
os.makedirs(data)
env = dict(os.environ, APPDATA=data, XDG_CONFIG_HOME=data, FLC_SETTINGS_INI=os.path.join(data, "p.ini"), QT_QPA_PLATFORM="offscreen",
           FLC_NO_FIRST_RUN="1", FLC_NO_UPDATE="1", FLC_MULTI="1", FLC_NO_DIALOGS="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
           FLC_PROVA_CPU="sse3", FLC_PROVA_COMPAT=BROKEN)
r = subprocess.run([sys.executable, "-m", "freelasercut"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=120)
log = ""
try:
    log = open(os.path.join(data, "FreeLaserCut", "flc.log"), encoding="utf-8").read()
except OSError:
    pass
check("avvio vero su un processore vecchio (finto): si carica davvero la NumPy della cartella compatibile",
      r.returncode != 0 and "NumPy compatibile finta: caricata proprio lei" in log, (r.returncode, log[-400:]))
check("…e l'intestazione dell'errore riporta il processore e le librerie compatibili attive",
      "Istruzioni del processore: sse3 (mancano: ssse3 sse4_1 sse4_2" in log and "librerie compatibili: attive" in log, log[-500:])
data2 = os.path.join(TMP, "avvio2")
os.makedirs(data2)
env2 = dict(env, APPDATA=data2, XDG_CONFIG_HOME=data2, FLC_SETTINGS_INI=os.path.join(data2, "p.ini"), FLC_PROVA_CPU=MODERN,
            FLC_PROVA_GUASTO="esci")
r2 = subprocess.run([sys.executable, "-m", "freelasercut"], cwd=ROOT, env=env2, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120)
crash = ""
try:
    crash = open(os.path.join(data2, "FreeLaserCut", "flc_crash.log"), encoding="utf-8").read()
except OSError:
    pass
check("avvio vero su un processore moderno, con la stessa cartella rotta lì accanto: parte normalmente (non la tocca)",
      r2.returncode == 0 and "FLC: avvio finito, finestra aperta" in r2.stdout, (r2.returncode, (r2.stdout + r2.stderr)[-300:]))
check("…e nel registro dei crash c'è comunque la riga con le istruzioni del processore (serve a capire i prossimi casi)",
      "Istruzioni del processore: sse3 ssse3 sse4_1 sse4_2 avx avx2" in crash and "mancano" not in crash, crash[-300:])
st = subprocess.run([sys.executable, "-c",
                     "import sys; sys.argv = ['x', '--self-test']; import freelasercut.selftest as s; "
                     "s.run = lambda: print('PROVA', __import__('numpy').__version__); import freelasercut.__main__ as m; m.boot()"],
                    cwd=ROOT, capture_output=True, text=True, timeout=120,
                    env=dict(os.environ, FLC_PROVA_CPU="sse3", FLC_PROVA_COMPAT=COMPAT))
check("anche la prova di avvio (--self-test) usa le librerie compatibili quando servono", "PROVA 2.3.5-compatibile" in st.stdout,
      (st.stdout, st.stderr[-200:]))
self_src = open(os.path.join(ROOT, "freelasercut", "selftest.py"), encoding="utf-8").read()
check("la prova di avvio stampa la riga del processore", "startup_guard.cpu_line()" in self_src)

# ================================================================== installatore e prova su GitHub
import prepara_installer as pi  # noqa: E402

pins = dict(p.split("==") for p in pi.COMPAT_PACKAGES)
main_pins = dict(p.split("==") for p in pi.PACKAGES)
ver = tuple(int(x) for x in pins["numpy"].split(".")[:2])
check("l'installatore porta una NumPy di prima della 2.4 (l'ultima senza l'obbligo di x86-64-v2), diversa da quella di tutti",
      list(pins) == ["numpy"] and (2, 0) <= ver < (2, 4) and tuple(int(x) for x in main_pins["numpy"].split(".")[:2]) >= (2, 4), pins)
try:
    import importlib.metadata as md

    need = [r for r in (md.distribution("numba").requires or []) if r.lower().startswith("numpy")]
    lo = re.search(r">=\s*([\d.]+)", need[0])
    hi = re.search(r"<\s*([\d.]+)", need[0])
    fits = (not lo or tuple(int(x) for x in lo.group(1).split(".")[:2]) <= ver) and (
        not hi or ver < tuple(int(x) for x in hi.group(1).split(".")[:2]))
    check("…e va d'accordo con la numba installata (che vuole «" + need[0] + "»)", fits and md.version("numba") == main_pins["numba"],
          (need, md.version("numba")))
except Exception as ex:  # noqa: BLE001 — numba non installata qui: il controllo si fa dove c'è
    check("(numba non installata in questo ambiente: controllo saltato)", True, repr(ex))
src = open(pi.__file__, encoding="utf-8").read()
part = src[src.index('step("Librerie compatibili'):]
part = part[:part.index("pyside = ")]
check("…e se non si riesce a scaricarla, l'installatore per tutti si costruisce lo stesso",
      "except (subprocess.CalledProcessError, OSError)" in part and "shutil.rmtree(compat, ignore_errors=True)" in part)
check("…in una cartella a parte (python\\Lib\\site-compat), senza trascinarsi altre librerie",
      '"Lib", "site-compat"' in part and '"--no-deps"' in part and "*COMPAT_PACKAGES" in part and '"win_amd64"' in part
      and "site-packages" not in part, part[:200])
check("…e il programma la cerca proprio lì", os.path.join("Lib", "site-compat") in
      open(os.path.join(ROOT, "freelasercut", "startup_guard.py"), encoding="utf-8").read().replace('", "', os.sep).replace('"', "")
      or '"Lib", "site-compat"' in open(os.path.join(ROOT, "freelasercut", "startup_guard.py"), encoding="utf-8").read())
yml = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
step = yml[yml.index("- name: Librerie compatibili per i processori più vecchi"):]
step = step[:step.index("- name: Errore d'avvio messo apposta")]
check("su GitHub, con il programma installato su Windows: le librerie compatibili vengono forzate e il programma deve aprirsi",
      'FLC_CPU_COMPAT: "1"' in step and "--self-test" in step and "site-compat\\numpy" in step and "numpy 2\\.3\\." in step
      and "ESITO: tutto a posto" in step and "librerie compatibili: attive" in step, step[:200])
check("…senza poter fermare la pubblicazione per tutti (riguarda solo i PC vecchi)", "continue-on-error: true" in step)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code_)
