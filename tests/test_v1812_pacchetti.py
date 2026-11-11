# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versioni 0.18.12 e 0.18.13: la costruzione su GitHub non resta appesa agli archivi dei pacchetti.

L'11/11/2026 le Release 0.18.11 e 0.18.12 non sono uscite: dalle macchine di GitHub non si raggiungevano gli archivi
di Ubuntu (prima lo specchio azure.archive.ubuntu.com, poi anche archive.ubuntu.com) e i lavori che installano
pacchetti di sistema restavano fermi anche 40 minuti prima di fallire.
- `build/apt_install.sh`: toglie lo specchio di Azure se non si risolve, controlla che un archivio risponda PRIMA di
  chiamare apt e, se nessuno risponde, rinuncia subito;
- `build/nsis_senza_apt.sh`: prende NSIS (serve per l'installatore di Windows) da altri specchi, e lo installa solo
  se l'impronta SHA-256 è quella dei pacchetti ufficiali di Ubuntu.

Casi provati (con finti apt-get, getent, curl e dpkg: non si installa niente e non si usa la rete):
1 tutto bene; 2 specchio di Azure che non si risolve; 3 nessun archivio raggiungibile: uscita 75 senza chiamare apt;
4 un fallimento passeggero; 5 fallisce sempre: due tentativi; 6 nessun pacchetto; 7 elenco con il solo Azure;
8 NSIS: file con l'impronta sbagliata scartati su tutti gli specchi, niente installazione; 9 specchi che non
  rispondono; 10 makensis c'è già: non fa niente; 11 impronte e versione scritte nello script;
12 i due file di GitHub usano gli script nei passi giusti.
L'installazione vera di NSIS dai pacchetti (scaricamento, impronta giusta, dpkg, compilazione di un installatore di
prova) è stata fatta a mano l'11/11/2026 su Ubuntu 24.04: qui non si può, perché userebbe la rete.
Le simulazioni girano dove c'è bash su Linux (come le macchine di GitHub); altrove restano i controlli sui file.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APT = os.path.join(ROOT, "build", "apt_install.sh")
NSIS = os.path.join(ROOT, "build", "nsis_senza_apt.sh")
SHA_COMMON = "49471b9debdee4751ebb4caf6b705cc4c678eebfaecefbe56362258893f85859"  # indice ufficiale noble/universe
SHA_NSIS = "9e061bef1a8b611aeb2ea76d9a3bd7722b960ca1a9dff8e38d2ab51e5a8f5e5b"
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


apt_src = open(APT, encoding="utf-8", newline="").read()
nsis_src = open(NSIS, encoding="utf-8", newline="").read()
check("i due script ci sono, con i fine riga di Linux", all(s.startswith("#!/usr/bin/env bash\n") and "\r" not in s
                                                            for s in (apt_src, nsis_src)))
ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
check("i file .sh restano con i fine riga di Linux anche scaricati su Windows", "*.sh text eol=lf" in ga)
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
pv = open(os.path.join(ROOT, ".github", "workflows", "prove.yml"), encoding="utf-8").read()
host_apt = [ln.strip() for ln in (wf + pv).splitlines() if "sudo apt-get" in ln]
check("nei lavori di GitHub nessun passo installa più pacchetti senza lo script", not host_apt, host_apt)
check("lo usano: NSIS, librerie dell'AppImage, prova su Linux, prove automatiche",
      wf.count("bash build/apt_install.sh ") == 2 and wf.count("bash repo/build/apt_install.sh ") == 1
      and pv.count("bash build/apt_install.sh ") == 1 and "apt_install.sh libxcb-cursor0" in wf
      and "apt_install.sh xvfb" in wf)
check("NSIS ha la seconda strada: se apt non va, i pacchetti dagli specchi (così Windows esce lo stesso)",
      "run: bash build/apt_install.sh nsis || bash build/nsis_senza_apt.sh" in wf)
m = re.search(r"  prova-linux:.*?(?=\n  [a-z-]+:\n)", wf, re.S)
check("nella prova dell'AppImage lo script arriva in una cartella a parte, senza i sorgenti del programma accanto",
      m is not None and "path: repo" in m.group(0) and "sparse-checkout: build" in m.group(0)
      and m.group(0).index("actions/checkout") < m.group(0).index("actions/download-artifact"))
rel = re.search(r"\n  release:.*?(?=\n  [a-z-]+:\n|\Z)", wf, re.S)
check("la Release dipende solo dalla prova su Windows: se Linux non riesce esce lo stesso",
      rel is not None and "needs.prova-windows.result == 'success'" in rel.group(0) and "!cancelled()" in rel.group(0)
      and "prova-linux.result" not in rel.group(0).split("steps:")[0].replace("needs: [", ""))
check("NSIS: versione e impronte dei due pacchetti ufficiali scritte nello script; si installa solo dopo il controllo",
      'VERSIONE="3.09-4ubuntu1"' in nsis_src and SHA_COMMON in nsis_src and SHA_NSIS in nsis_src
      and "sha256sum -c" in nsis_src and nsis_src.index("sha256sum -c") < nsis_src.index("dpkg -i"))
urls = re.search(r'SPECCHI="\$\{NSIS_MIRRORS:-([^}]*)\}"', nsis_src)
check("NSIS: tutti gli specchi sono in https, e non stanno tutti sulla rete di Ubuntu",
      urls is not None and all(u.startswith("https://") for u in urls.group(1).split())
      and sum("ubuntu.com" not in u for u in urls.group(1).split()) >= 4, urls and urls.group(1))

if sys.platform.startswith("linux") and shutil.which("bash"):
    tmp = tempfile.mkdtemp()
    os.mkdir(os.path.join(tmp, "bin"))
    shims = {
        "apt-get": ('echo "apt-get $*" >> "$LOGF"\n'
                    'if [ "${FAIL_AZURE:-0}" = 1 ] && grep -q azure.archive.ubuntu.com "$APT_MIRRORS_FILE"; then exit 100; fi\n'
                    'for a in "$@"; do if [ "$a" = install ]; then n=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); '
                    'echo $n > "$CNT"; [ "$n" -le "${FAIL_N:-0}" ] && exit 100; fi; done\nexit 0\n'),
        "getent": '[ "${AZURE_DNS:-1}" = 1 ] && exit 0 || exit 2\n',
        # curl finto: con «-o /dev/null» è il controllo che un archivio risponda (REACH); altrimenti scarica un file
        # (DL=0: lo specchio non risponde; DL=1: arriva un file, ma non è quello di Ubuntu)
        "curl": ('echo "curl $*" >> "$LOGF"\nout=""; prev=""\nfor a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
                 'if [ "$out" = /dev/null ]; then [ "${REACH:-1}" = 1 ] && exit 0 || exit 7; fi\n'
                 '[ "${DL:-0}" = 1 ] || exit 7\necho "non sono il pacchetto di Ubuntu" > "$out"\nexit 0\n'),
        "dpkg": 'echo "dpkg $*" >> "$LOGF"\nexit 0\n',
    }
    for name, body in shims.items():
        with open(os.path.join(tmp, "bin", name), "w", newline="\n") as f:
            f.write("#!/usr/bin/env bash\n" + body)
        os.chmod(os.path.join(tmp, "bin", name), 0o755)
    THREE = ("http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\n"
             "https://security.ubuntu.com/ubuntu/\tpriority:3\n")

    def run(script=APT, args=("nsis", "xvfb"), mirrors=THREE, extra_path=None, **env):
        mf, log, cnt = (os.path.join(tmp, n) for n in ("m.txt", "log", "cnt"))
        open(mf, "w", newline="\n").write(mirrors)
        for p in (log, cnt):
            if os.path.exists(p):
                os.remove(p)
        path = os.pathsep.join(([extra_path] if extra_path else []) + [os.path.join(tmp, "bin"), os.environ["PATH"]])
        e = dict(os.environ, PATH=path, LOGF=log, CNT=cnt, APT_MIRRORS_FILE=mf, APT_RETRY_WAIT="0", APT_SUDO="",
                 NSIS_SUDO="", NSIS_DIR=os.path.join(tmp, "w"), **{k: str(v) for k, v in env.items()})
        os.makedirs(e["NSIS_DIR"], exist_ok=True)
        r = subprocess.run(["bash", script, *args], capture_output=True, text=True, env=e, timeout=60)
        calls = open(log).read().splitlines() if os.path.exists(log) else []
        return r.returncode, calls, open(mf).read(), r.stdout + r.stderr

    def apts(calls):
        return [c for c in calls if c.startswith("apt-get")]

    rc, calls, mir, out = run()
    check("tutto bene: un aggiornamento e un'installazione, con i pacchetti chiesti; l'elenco degli specchi non cambia",
          rc == 0 and len(apts(calls)) == 2 and apts(calls)[1].endswith("install -y nsis xvfb") and mir == THREE, (rc, calls))
    rc, calls, mir, out = run(AZURE_DNS=0, FAIL_AZURE=1)
    check("lo specchio di Azure non si risolve: tolto prima di provare, e il primo tentativo riesce",
          rc == 0 and len(apts(calls)) == 2 and "azure" not in mir and mir.count("http") == 2 and "::warning::" in out,
          (rc, calls, mir))
    rc, calls, mir, out = run(AZURE_DNS=0, REACH=0)
    check("nessun archivio risponde: tre controlli, poi rinuncia subito (uscita 75) senza chiamare apt, e dice che è la rete",
          rc == 75 and not apts(calls) and sum(c.startswith("curl") for c in calls) == 3 and "::error::" in out
          and "guasto di rete" in out, (rc, calls, out[-200:]))
    rc, calls, mir, out = run(AZURE_DNS=1, REACH=0)
    check("…anche quando il nome di Azure si risolve ma nessuno risponde", rc == 75 and not apts(calls), (rc, calls))
    rc, calls, mir, out = run(FAIL_N=1)
    check("un fallimento passeggero di apt: riprova e riesce", rc == 0 and sum("install" in c for c in apts(calls)) == 2, (rc, calls))
    rc, calls, mir, out = run(FAIL_N=99)
    check("apt fallisce sempre: due tentativi, poi esce con errore e lo dice",
          rc == 1 and sum("install" in c for c in apts(calls)) == 2 and "::error::" in out, (rc, len(calls), out[-200:]))
    rc, calls, mir, out = run(args=())
    check("senza pacchetti: errore d'uso, niente apt", rc == 2 and not calls, (rc, calls))
    only = "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n"
    rc, calls, mir, out = run(mirrors=only, AZURE_DNS=0, REACH=0)
    check("un elenco con il solo specchio di Azure non viene svuotato", mir == only and rc == 75, (rc, mir))
    check("ogni chiamata ad apt ha un tempo massimo (niente lavori fermi per decine di minuti)",
          apt_src.count('timeout "$LIMITE" $SUDO apt-get') == 2 and "Acquire::https::Timeout=20" in apt_src)

    two = "https://uno.example/ubuntu https://due.example/ubuntu"
    rc, calls, mir, out = run(script=NSIS, args=(), NSIS_FORZA=1, NSIS_MIRRORS=two, DL=1)
    check("NSIS: un file che non ha l'impronta di Ubuntu viene scartato su ogni specchio, e non si installa niente",
          rc == 1 and sum(c.startswith("curl") for c in calls) == 2 and not [c for c in calls if c.startswith("dpkg")]
          and out.count("impronta diversa") == 2 and not os.listdir(os.path.join(tmp, "w")), (rc, calls, out[-300:]))
    rc, calls, mir, out = run(script=NSIS, args=(), NSIS_FORZA=1, NSIS_MIRRORS=two, DL=0)
    check("NSIS: nessuno specchio risponde: errore chiaro, niente installazione",
          rc == 1 and not [c for c in calls if c.startswith("dpkg")] and "::error::" in out, (rc, calls))
    have = os.path.join(tmp, "have")
    os.mkdir(have)
    with open(os.path.join(have, "makensis"), "w", newline="\n") as f:
        f.write('#!/usr/bin/env bash\necho v3.09-finto\n')
    os.chmod(os.path.join(have, "makensis"), 0o755)
    rc, calls, mir, out = run(script=NSIS, args=(), NSIS_MIRRORS=two, DL=1, extra_path=have)
    check("NSIS: se makensis c'è già non scarica e non installa niente", rc == 0 and not calls and "c'è già" in out, (rc, calls))
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("     (simulazioni saltate: servono bash e Linux, come sulle macchine di GitHub)")

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
