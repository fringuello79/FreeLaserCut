# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.4: aggiornamento dal programma (Release di GitHub).
Tutto in locale: un piccolo server HTTP fa la parte di GitHub, l'installatore non viene avviato davvero."""
import sys, os, time, tempfile, json, hashlib, threading, http.server, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ["FLC_UPDATE_MODE"] = "installer"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox, QLabel
app = QApplication([])
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), QMessageBox.Yes)[1])
infos = []
QMessageBox.information = staticmethod(lambda *a, **k: (infos.append(a[2] if len(a) > 2 else ""), QMessageBox.Ok)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
boxes = []
QMessageBox.exec = lambda self: boxes.append(self.text()) or 0
from freelasercut import updater, __version__

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

# ------------------------------------------------------------------ versioni
check("versioni: 0.10.10 è più nuova di 0.10.9 (confronto numerico, non di testo)", updater.is_newer("v0.10.10", "0.10.9"))
check("versioni: stessa versione o più vecchia non è un aggiornamento",
      not updater.is_newer("0.10.4", "0.10.4") and not updater.is_newer("v0.9.9", "0.10.4") and not updater.is_newer("1.0", "1.0.0"))
check("versioni: 1.0 > 0.10.4, tag senza numeri ignorati", updater.is_newer("v1.0", "0.10.4") and not updater.is_newer("ultima", "0.1"))

# ------------------------------------------------------------------ che copia è
tmp = tempfile.mkdtemp()
inst = os.path.join(tmp, "Programs", "FreeLaserCut")
os.makedirs(os.path.join(inst, "python"))
exe = os.path.join(inst, "python", "pythonw.exe")
open(exe, "w").close()
check("senza disinstallatore non è una copia installata", updater.install_dir(exe) is None)
open(os.path.join(inst, updater.UNINSTALLER), "w").close()
check("copia installata riconosciuta (python\\pythonw.exe accanto al disinstallatore)", updater.install_dir(exe) == inst)
os.environ.pop("FLC_UPDATE_MODE")
check("copia del Microsoft Store (WindowsApps) → si aggiorna dallo Store",
      updater.mode(r"C:\Program Files\WindowsApps\FreeLaserCut_0.10.4.0_x64\python\pythonw.exe".replace("\\", os.sep)) == "store")
check("codice sorgente → aggiornamento manuale", updater.mode(sys.executable) in ("manual", "store") and
      (sys.platform == "win32" or updater.mode(exe) == "manual"))
os.environ["FLC_UPDATE_MODE"] = "installer"

# ------------------------------------------------------------------ Release di GitHub
P = updater.DOWNLOAD_PREFIX
def api(tag="v0.99.0", setup=True, sums=True, extra=()):
    assets = list(extra)
    if setup:
        assets.append({"name": f"FreeLaserCut-{tag.lstrip('v')}-Setup.exe", "browser_download_url": P + f"{tag}/FreeLaserCut-{tag.lstrip('v')}-Setup.exe", "size": 10})
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": P + f"{tag}/SHA256SUMS.txt", "size": 90})
    return {"tag_name": tag, "name": f"FreeLaserCut {tag}", "body": "## Novità\n- **aggiornamento** dal programma",
            "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}", "draft": False, "prerelease": False, "assets": assets}
r = updater.parse_release(api())
check("Release letta: versione, installatore, SHA256SUMS e note", r and r.version == "0.99.0" and r.setup_name == "FreeLaserCut-0.99.0-Setup.exe"
      and r.sums_url.endswith("SHA256SUMS.txt") and "aggiornamento" in r.notes, repr(r))
evil = {"name": "FreeLaserCut-0.99.0-Setup.exe", "browser_download_url": "https://example.com/FreeLaserCut-0.99.0-Setup.exe", "size": 1}
r = updater.parse_release(api(setup=False, extra=[evil]))
check("un installatore che non sta nella Release di github.com/fringuello79 viene ignorato", r is not None and r.setup_url is None)
r = updater.parse_release(api(extra=[{"name": "FreeLaserCut-0.98.0-Setup.exe", "browser_download_url": P + "x/FreeLaserCut-0.98.0-Setup.exe"}], setup=False))
check("installatore di un'altra versione ignorato", r is not None and r.setup_url is None)
check("bozze e versioni di prova ignorate", updater.parse_release({**api(), "draft": True}) is None
      and updater.parse_release({**api(), "prerelease": True}) is None)
sha = "a" * 64
check("SHA256SUMS: formato di sha256sum (anche «*nome» e maiuscole)",
      updater.expected_sha(f"{sha}  FreeLaserCut-0.99.0-Setup.exe\n", "freelasercut-0.99.0-setup.exe") == sha
      and updater.expected_sha(f"{'B' * 64} *build/FreeLaserCut-0.99.0-Setup.exe", "FreeLaserCut-0.99.0-Setup.exe") == "b" * 64
      and updater.expected_sha("niente", "x.exe") is None)
cmd = updater.installer_command(r"C:\Temp\FreeLaserCut-0.99.0-Setup.exe", r"C:\Users\Ale Rossi\AppData\Local\Programs\FreeLaserCut")
check("riga di comando dell'installatore: /AGGIORNA e /D= per ultimo, senza virgolette anche con gli spazi",
      cmd.startswith('"C:\\Temp\\FreeLaserCut-0.99.0-Setup.exe" /AGGIORNA /D=') and cmd.endswith("Ale Rossi\\AppData\\Local\\Programs\\FreeLaserCut")
      and '"/D=' not in cmd, cmd)

# ------------------------------------------------------------------ server locale al posto di GitHub
PAYLOAD = os.urandom(300_000)
FILES = {}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = FILES.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        try:
            for i in range(0, len(body), 65536):
                self.wfile.write(body[i:i + 65536])
        except (BrokenPipeError, ConnectionResetError):
            pass  # scaricamento annullato dal programma: normale
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
good_sha = hashlib.sha256(PAYLOAD).hexdigest()
FILES["/setup.exe"] = PAYLOAD
FILES["/sums"] = f"{good_sha}  FreeLaserCut-0.99.0-Setup.exe\n".encode()
FILES["/badsums"] = f"{'0' * 64}  FreeLaserCut-0.99.0-Setup.exe\n".encode()
def rel(sums="/sums"):
    return updater.Release("0.99.0", "v0.99.0", "FreeLaserCut 0.99.0", "## Novità\n- prova", f"https://github.com/{updater.REPO}/releases",
                           BASE + "/setup.exe", "FreeLaserCut-0.99.0-Setup.exe", len(PAYLOAD), BASE + sums if sums else None)
dest = tempfile.mkdtemp()
prog = []
path = updater.download(rel(), dest, progress=lambda d, t: prog.append((d, t)))
check("scaricamento: file completo, SHA-256 giusto, avanzamento fino in fondo", open(path, "rb").read() == PAYLOAD and prog
      and prog[-1] == (len(PAYLOAD), len(PAYLOAD)), f"{len(prog)} passi")
def err(fn):
    try:
        fn(); return None
    except updater.UpdateError as e:
        return str(e)
dest = tempfile.mkdtemp()
e1 = err(lambda: updater.download(rel("/badsums"), dest))
check("SHA-256 diverso: rifiutato e cancellato", e1 and "SHA-256" in e1 and not os.path.exists(os.path.join(dest, "FreeLaserCut-0.99.0-Setup.exe"))
      and not os.path.exists(os.path.join(dest, "FreeLaserCut-0.99.0-Setup.exe.part")), str(e1))
e2 = err(lambda: updater.download(rel(None), dest))
check("senza SHA256SUMS.txt non scarica", e2 and "SHA256SUMS" in e2, str(e2))
e3 = err(lambda: updater.download(rel(), dest, cancelled=lambda: True))
check("annullato: nessun file a metà", e3 and "annullato" in e3 and not os.listdir(dest), f"{e3} {os.listdir(dest)}")
e4 = err(lambda: updater.download(types.SimpleNamespace(**{**vars(rel()), "setup_size": len(PAYLOAD) + 5}), dest))
check("dimensione diversa da quella della Release: scaricamento incompleto", e4 and "incompleto" in e4, str(e4))
FILES["/api"] = json.dumps(api("v0.99.0")).encode()
check("lettura dell'ultima Release dall'API", updater.fetch_latest(5, BASE + "/api").version == "0.99.0")
e5 = err(lambda: updater.fetch_latest(5, BASE + "/nessuna"))
check("nessuna Release pubblicata: messaggio chiaro", e5 and "nessuna versione" in e5, str(e5))
e6 = err(lambda: updater.fetch_latest(2, "http://127.0.0.1:1/api"))
check("senza rete: messaggio chiaro", e6 and "connessione" in e6, str(e6))

# ------------------------------------------------------------------ interfaccia
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import update_ui
w = MainWindow()
w.show()
um = w.updates
help_menu = [m for m in w.menuBar().actions() if m.menu() and w.acts["about"] in m.menu().actions()][0].menu()
check("Aiuto → Cerca aggiornamenti… e Controlla gli aggiornamenti ogni giorno", w.acts["updates"] in help_menu.actions()
      and w.acts["update_auto"] in help_menu.actions() and w.acts["update_auto"].isVisible())
check("di partenza non controlla niente (permesso non ancora dato)", not um.enabled() and not w.acts["update_auto"].isChecked()
      and w.qs.value("update_check") is None)
um.startup()
check("in prova (senza schermo) all'avvio non chiede e non si collega", w.qs.value("update_check") is None and not um.busy)
w.acts["update_auto"].trigger()
check("attivato dal menu: preferenza salvata", um.enabled() and w.qs.value("update_check") == "true")
um.set_enabled(False)
check("disattivato: anche la spunta del menu si toglie", not um.enabled() and not w.acts["update_auto"].isChecked())
w.qs.setValue("update_last", time.time())
check("controllo automatico al massimo una volta al giorno", not um.due())
w.qs.setValue("update_last", time.time() - 25 * 3600)
check("dopo un giorno si controlla di nuovo", um.due())

newer = updater.Release("0.99.0", "v0.99.0", "FreeLaserCut 0.99.0", "## Novità\n- prova", f"https://github.com/{updater.REPO}/releases",
                        BASE + "/setup.exe", "FreeLaserCut-0.99.0-Setup.exe", len(PAYLOAD), BASE + "/sums")
um._on_checked(newer, None, False)
btns = [w.banner_buttons.itemAt(i).widget().text() for i in range(w.banner_buttons.count())]
check("versione nuova trovata in automatico: avviso in alto con tre scelte", w.banner.isVisible() and "0.99.0" in w.banner_text.text()
      and len(btns) == 3, str(btns))
um.skip(newer)
w.banner.hide()
um._on_checked(newer, None, False)
check("«Salta questa versione»: per la 0.99.0 non avvisa più", not w.banner.isVisible() and w.qs.value("update_skip") == "0.99.0")
infos.clear()
um._on_checked(updater.Release(__version__, "v" + __version__, "", "", "", None, None, 0, None), None, True)
check("Cerca aggiornamenti con l'ultima versione già installata: lo dice", infos and "ultima versione" in infos[-1], str(infos[-1:]))
boxes.clear()
um._on_checked(None, "Non riesco a collegarmi a GitHub (prova).", True)
check("Cerca aggiornamenti senza rete: messaggio d'errore", boxes and "GitHub" in boxes[-1])
um.busy = False
FILES["/api"] = json.dumps(api("v0.99.0")).encode()
real_fetch = updater.fetch_latest
updater.fetch_latest = lambda timeout=10.0, url=None: real_fetch(timeout, BASE + "/api")
seen = []
um.checked.connect(lambda r, e, m: seen.append((r, e, m)))
um.release_dialog = (lambda orig: (lambda r: (seen.append("dialog"), types.SimpleNamespace(exec=lambda: 0, choice=None))[1]))(um.release_dialog)
um.check(manual=True)
check("Cerca aggiornamenti… in sottofondo: trova la 0.99.0 e mostra le novità",
      until(lambda: "dialog" in seen and any(isinstance(x, tuple) for x in seen))  # 0.18.1: i due segnali possono
      and next(x for x in seen if isinstance(x, tuple))[0].version == "0.99.0", str(seen[:2]))  # arrivare in due giri
updater.fetch_latest = real_fetch
del um.release_dialog

d = um.release_dialog(newer)
labels = [b.text() for b in d.findChildren(QDialogButtonBox)[0].buttons()]
check("finestra delle novità (copia installata): Scarica e installa", any("Scarica e installa" in t for t in labels), str(labels))
um.mode = "store"
d = um.release_dialog(newer)
labels = [b.text() for b in d.findChildren(QDialogButtonBox)[0].buttons()]
txt = " ".join(l.text() for l in d.findChildren(QLabel))
check("copia del Microsoft Store: niente scaricamento, dice di aggiornare dallo Store", not any("Scarica" in t for t in labels)
      and "Microsoft Store" in txt, str(labels))
infos.clear()
check("copia dello Store: «Cerca aggiornamenti…» non si collega a GitHub", um.check(manual=True) is False and not um.busy
      and infos and "Microsoft Store" in infos[-1])
um.mode = "manual"
d = um.release_dialog(newer)
labels = [b.text() for b in d.findChildren(QDialogButtonBox)[0].buttons()]
check("copia dal codice sorgente: rimanda al sito", any("sito" in t for t in labels) and not any("Scarica" in t for t in labels), str(labels))
um.mode = "installer"

w.ctl._check = {"total": 1, "done": 0, "errors": [], "exiting": False}
infos.clear()
check("durante una verifica (o un lavoro) non aggiorna", um.install(newer) is False and infos and "in corso" in infos[-1])
w.ctl._check = None

launched = []
real_launch = updater.launch_installer
updater.launch_installer = lambda p, d=None: launched.append((p, d))
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
asked.clear()
um.release = newer
check("Scarica e installa: parte lo scaricamento", um.install(newer) is True)
check("scaricato e controllato, chiede conferma, FreeLaserCut si chiude e parte l'installatore",
      until(lambda: launched, 15) and asked and "Installo adesso" in asked[-1] and not w.isVisible()
      and launched[0][0].endswith("FreeLaserCut-0.99.0-Setup.exe") and open(launched[0][0], "rb").read() == PAYLOAD,
      f"{launched} visibile={w.isVisible()}")
updater.launch_installer = real_launch

# chiusura annullata (lavoro non salvato): l'installatore non parte
w2 = MainWindow()
w2.show()
w2._confirm_discard = lambda: False
launched2 = []
updater.launch_installer = lambda p, d=None: launched2.append(p)
ok = w2.updates.ready(launched[0][0])
check("se la chiusura viene annullata non parte niente e si può riprovare", ok is False and not launched2 and w2.isVisible()
      and w2._update_installer is None)
updater.launch_installer = real_launch
w2._confirm_discard = lambda: True
w2.editor.dirty = False
w2.qs.setValue("autosave_pending", False)
w2.close()

# ------------------------------------------------------------------ installatore e pubblicazione
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8").read()
check("installatore: riconosce /AGGIORNA", '${GetOptions} $R9 "/AGGIORNA" $R8' in nsi and "Var Aggiorna" in nsi)
check("installatore: in aggiornamento salta benvenuto, licenza, cartella e fine", nsi.count("MUI_PAGE_CUSTOMFUNCTION_PRE SaltaSeAggiorna") == 4)
check("installatore: aspetta fino a 30 s che FreeLaserCut si chiuda, poi chiede", "IntCmp $R2 60 flc_chiedi" in nsi and "Sleep 500" in nsi)
check("installatore: a fine aggiornamento si chiude e riapre FreeLaserCut", "SetAutoClose true" in nsi and
      "Function .onInstSuccess" in nsi and "Exec '\"$INSTDIR\\python\\pythonw.exe\" -m freelasercut'" in nsi)
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
check("GitHub: il tag vX.Y.Z crea la Release con installatore e SHA256SUMS.txt, dopo la prova su Windows",
      "gh release create" in wf and "SHA256SUMS.txt" in wf and "needs: [build, prova-windows" in wf
      and "needs.prova-windows.result == 'success'" in wf and "contents: write" in wf)  # 0.18.0: più Linux
check("GitHub: il tag deve corrispondere alla versione del programma", 'GITHUB_REF_NAME" != "v$ver"' in wf)
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
