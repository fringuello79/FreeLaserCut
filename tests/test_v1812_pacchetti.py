# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.12: la costruzione su GitHub non si ferma più per lo specchio dei pacchetti.

L'11/11/2026 la Release 0.18.11 non è uscita: azure.archive.ubuntu.com, lo specchio che le macchine di GitHub usano
per primo, non si risolveva («Temporary failure resolving»), e i lavori che installano pacchetti di sistema sono
falliti due volte. `build/apt_install.sh` toglie quello specchio quando non risponde e riprova.

Casi provati (con finti apt-get e getent: non si installa niente e non si usa la rete):
1 tutto bene: un giro solo, l'elenco degli specchi non cambia;
2 lo specchio non si risolve: tolto PRIMA del primo tentativo, che riesce;
3 lo specchio si risolve ma apt fallisce: tolto dopo il primo tentativo, il secondo riesce;
4 fallimenti passeggeri: riprova fino a riuscire; 5 fallisce sempre: quattro tentativi, poi errore;
6 nessun pacchetto: errore d'uso; 7 l'elenco con il solo specchio di Azure non viene svuotato;
8 i due file di GitHub usano lo script in tutti i passi che installano pacchetti sulla macchina.
Le simulazioni girano dove c'è bash su Linux (come le macchine di GitHub); altrove restano i controlli sui file.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "build", "apt_install.sh")
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


src = open(SCRIPT, encoding="utf-8", newline="").read()
check("lo script c'è, con i fine riga di Linux", src.startswith("#!/usr/bin/env bash\n") and "\r" not in src)
ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
check("i file .sh restano con i fine riga di Linux anche scaricati su Windows", "*.sh text eol=lf" in ga)
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
pv = open(os.path.join(ROOT, ".github", "workflows", "prove.yml"), encoding="utf-8").read()
host_apt = [ln.strip() for ln in (wf + pv).splitlines() if "sudo apt-get" in ln]
check("nei lavori di GitHub nessun passo installa più pacchetti senza lo script", not host_apt, host_apt)
check("lo usano: NSIS, librerie dell'AppImage, prova su Linux, prove automatiche",
      wf.count("bash build/apt_install.sh ") == 2 and wf.count("bash repo/build/apt_install.sh ") == 1
      and pv.count("bash build/apt_install.sh ") == 1 and "apt_install.sh nsis" in wf
      and "apt_install.sh libxcb-cursor0" in wf and "apt_install.sh xvfb" in wf)
m = re.search(r"  prova-linux:.*?(?=\n  [a-z-]+:\n)", wf, re.S)
check("nella prova dell'AppImage lo script arriva in una cartella a parte, senza i sorgenti del programma accanto",
      m is not None and "path: repo" in m.group(0) and "sparse-checkout: build" in m.group(0)
      and m.group(0).index("actions/checkout") < m.group(0).index("actions/download-artifact"))

if sys.platform.startswith("linux") and shutil.which("bash"):
    tmp = tempfile.mkdtemp()
    os.mkdir(os.path.join(tmp, "bin"))
    with open(os.path.join(tmp, "bin", "apt-get"), "w", newline="\n") as f:
        f.write('#!/usr/bin/env bash\necho "apt-get $*" >> "$LOGF"\n'
                'if [ "${FAIL_AZURE:-0}" = 1 ] && grep -q azure.archive.ubuntu.com "$APT_MIRRORS_FILE"; then exit 100; fi\n'
                'for a in "$@"; do if [ "$a" = install ]; then n=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); '
                'echo $n > "$CNT"; [ "$n" -le "${FAIL_N:-0}" ] && exit 100; fi; done\nexit 0\n')
    with open(os.path.join(tmp, "bin", "getent"), "w", newline="\n") as f:
        f.write('#!/usr/bin/env bash\n[ "${AZURE_DNS:-1}" = 1 ] && exit 0 || exit 2\n')
    for n in ("apt-get", "getent"):
        os.chmod(os.path.join(tmp, "bin", n), 0o755)
    THREE = ("http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\n"
             "https://security.ubuntu.com/ubuntu/\tpriority:3\n")

    def run(args=("nsis", "xvfb"), mirrors=THREE, **env):
        mf, log, cnt = (os.path.join(tmp, n) for n in ("m.txt", "log", "cnt"))
        open(mf, "w", newline="\n").write(mirrors)
        for p in (log, cnt):
            if os.path.exists(p):
                os.remove(p)
        e = dict(os.environ, PATH=os.path.join(tmp, "bin") + os.pathsep + os.environ["PATH"], LOGF=log, CNT=cnt,
                 APT_MIRRORS_FILE=mf, APT_RETRY_WAIT="0", APT_SUDO="", **{k: str(v) for k, v in env.items()})
        r = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=e, timeout=60)
        calls = open(log).read().splitlines() if os.path.exists(log) else []
        return r.returncode, calls, open(mf).read(), r.stdout + r.stderr

    rc, calls, mir, out = run()
    check("tutto bene: un aggiornamento e un'installazione, con i pacchetti chiesti; l'elenco degli specchi non cambia",
          rc == 0 and len(calls) == 2 and calls[1].endswith("install -y nsis xvfb") and mir == THREE, (rc, calls))
    rc, calls, mir, out = run(AZURE_DNS=0, FAIL_AZURE=1)
    check("lo specchio di Azure non si risolve: tolto prima di provare, e il primo tentativo riesce",
          rc == 0 and len(calls) == 2 and "azure" not in mir and mir.count("http") == 2 and "::warning::" in out, (rc, calls, mir))
    rc, calls, mir, out = run(AZURE_DNS=1, FAIL_AZURE=1)
    check("lo specchio si risolve ma non serve i pacchetti: tolto dopo il primo tentativo, il secondo riesce",
          rc == 0 and len(calls) == 3 and "azure" not in mir, (rc, calls))
    rc, calls, mir, out = run(FAIL_N=2)
    check("due fallimenti passeggeri: riprova e alla terza riesce", rc == 0 and sum("install" in c for c in calls) == 3, (rc, calls))
    rc, calls, mir, out = run(FAIL_N=99)
    check("fallisce sempre: quattro tentativi, poi esce con errore e lo dice",
          rc == 1 and sum("install" in c for c in calls) == 4 and "::error::" in out, (rc, len(calls), out[-200:]))
    rc, calls, mir, out = run(args=())
    check("senza pacchetti: errore d'uso, niente apt", rc == 2 and not calls, (rc, calls))
    only = "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n"
    rc, calls, mir, out = run(mirrors=only, AZURE_DNS=0, FAIL_N=99)
    check("un elenco con il solo specchio di Azure non viene svuotato", mir == only and rc == 1, (rc, mir))
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("     (simulazioni saltate: servono bash e Linux, come sulle macchine di GitHub)")

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
