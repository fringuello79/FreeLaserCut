# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Collega FreeLaserCut a Claude: aggiunge il server MCP "freelasercut" alla configurazione dell'app Claude per desktop."""
import glob
import json
import os
import shutil
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout

from . import style
from freelasercut.i18n import tr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def python_exe():
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            exe = cand
    return exe


def server_entry():
    from .. import linux

    app = linux.mcp_command()  # AppImage: la cartella del programma cambia a ogni avvio, il file .AppImage no
    if app:
        return app
    return {"command": python_exe(), "args": ["-m", "freelasercut.mcp_server"], "env": {"PYTHONPATH": ROOT}}


def claude_code_command():
    """Riga per collegare FreeLaserCut a Claude Code (anche su Linux, dove l'app Claude per desktop non c'è)."""
    e = server_entry()
    if "env" in e:
        return f'claude mcp add freelasercut -e PYTHONPATH="{ROOT}" -- "{e["command"]}" -m freelasercut.mcp_server'
    return f'claude mcp add freelasercut -- "{e["command"]}" ' + " ".join(e["args"])


def config_paths():
    """Dove l'app Claude per desktop tiene claude_desktop_config.json (installazione classica o da Microsoft Store)."""
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(os.path.join(appdata, "Claude", "claude_desktop_config.json"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for d in glob.glob(os.path.join(local, "Packages", "*Claude*", "LocalCache", "Roaming", "Claude")):
            out.append(os.path.join(d, "claude_desktop_config.json"))
    if sys.platform == "darwin":
        out.append(os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"))
    if sys.platform.startswith("linux"):  # versioni dell'app Claude per Linux non ufficiali usano questa cartella
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        out.append(os.path.join(base, "Claude", "claude_desktop_config.json"))
    return out


def install():
    """Aggiunge (o aggiorna) la voce "freelasercut" senza toccare le altre. Ritorna i file scritti."""
    written = []
    paths = config_paths()
    existing = [p for p in paths if os.path.isdir(os.path.dirname(p))]
    for path in existing or paths[:1]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cfg = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                txt = fh.read().strip()
            cfg = json.loads(txt) if txt else {}
            shutil.copy2(path, path + time.strftime(".%Y%m%d-%H%M%S.bak"))
        cfg.setdefault("mcpServers", {})["freelasercut"] = server_entry()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
        written.append(path)
    return written


MCPB_MAIN = """# Avvio del server MCP di FreeLaserCut (estensione per l'app Claude)
import os, sys
root = os.environ.get("FLC_ROOT", "")
if root and root not in sys.path:
    sys.path.insert(0, root)
from freelasercut.mcp_server import main
main()
"""


def build_mcpb(out_path):
    """Estensione per l'app Claude (.mcpb): doppio clic e Installa. Contiene i percorsi di questo PC."""
    import zipfile

    from .. import __version__
    from ..mcp_server import TOOLS

    manifest = {
        "manifest_version": "0.2",
        "name": "freelasercut",
        "display_name": "FreeLaserCut",
        "version": __version__,
        "description": tr("Disegna e prepara i lavori di incisione e taglio laser in FreeLaserCut (Longer B1 40W)."),
        "author": {"name": "fringuello79"},
        "server": {
            "type": "python",
            "entry_point": "server/main.py",
            "mcp_config": {"command": python_exe(), "args": ["${__dirname}/server/main.py"],
                           "env": {"FLC_ROOT": ROOT, "PYTHONPATH": ROOT}},
        },
        "tools": [{"name": n, "description": d[:200]} for n, _, d, _ in TOOLS],
        "license": "GPL-3.0-or-later",
    }
    icon = os.path.join(ROOT, "freelasercut", "assets", "logo.png")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(icon):
            manifest["icon"] = "icon.png"
            z.write(icon, "icon.png")
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("server/main.py", MCPB_MAIN)
    return out_path


class ClaudeDialog(QDialog):
    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Collega a Claude"))
        self.resize(640, 520)
        v = QVBoxLayout(self)
        txt = QLabel(
            tr("<b>Detta a Claude cosa disegnare.</b> Collegato con MCP, Claude può creare forme e testi, "
            "importare file, impostare livelli e materiali, vedere il disegno e preparare il lavoro. "
            "Per esempio: <i>«fammi una medaglia da 60 mm con scritto SRM 2026 curvo in alto e il taglio sul "
            "bordo, tiglio 3 mm»</i>.<br><br>"
            "Il laser non parte mai da solo: quando Claude chiede di avviare compare la solita conferma sullo "
            "schermo e sei tu a premere Avvia.<br><br>"
            "1. Premi <b>Configura Claude per desktop</b>: aggiungo «freelasercut» alla configurazione dell'app Claude "
            "(il file originale viene salvato come copia .bak).<br>"
            "2. <b>Chiudi e riapri l'app Claude</b> (anche dall'icona vicino all'orologio).<br>"
            "3. In una chat scrivi cosa vuoi fare in FreeLaserCut. Se FreeLaserCut è chiuso, Claude lo apre."))
        txt.setWordWrap(True)
        txt.setTextFormat(Qt.RichText)
        v.addWidget(txt)
        state = QLabel(tr("FreeLaserCut accetta i comandi sulla porta locale {0} (solo da questo PC).", port) if port
                       else tr("⚠ Il server locale non è partito: riavvia FreeLaserCut."))
        state.setObjectName("muted")
        v.addWidget(state)
        self.cfg = QPlainTextEdit(json.dumps({"mcpServers": {"freelasercut": server_entry()}}, indent=2))
        self.cfg.setReadOnly(True)
        self.cfg.setFont(style.mono_font(9))
        v.addWidget(QLabel(tr("Voce di configurazione (per Claude per desktop o altri programmi MCP):")))
        v.addWidget(self.cfg, 1)
        import html as _html

        cli = QLabel(tr("Claude Code:  <code>{0}</code>", _html.escape(claude_code_command())))
        cli.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cli.setWordWrap(True)
        v.addWidget(cli)
        h = QHBoxLayout()
        b_inst = QPushButton(style.icon("connect", "#FFFFFF"), tr("Configura Claude per desktop"))
        b_inst.setObjectName("primary")
        b_inst.clicked.connect(self._install)
        b_ext = QPushButton(style.icon("export"), tr("Installa come estensione…"))
        b_ext.setToolTip(tr("Crea FreeLaserCut.mcpb e lo apre: l'app Claude chiede di installarlo (Impostazioni → Estensioni)"))
        b_ext.clicked.connect(self._extension)
        b_copy = QPushButton(style.icon("copy"), tr("Copia la configurazione"))
        b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.cfg.toPlainText()))
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.accept)
        if sys.platform.startswith("linux"):  # su Linux l'app Claude per desktop ufficiale non c'è: resta Claude Code
            b_ext.setVisible(False)
            note = QLabel(tr("Su Linux l'app Claude per desktop non è disponibile ufficialmente: usa Claude Code con la "
                             "riga qui sopra, oppure un altro programma che supporta MCP con la voce di configurazione."))
            note.setWordWrap(True)
            note.setObjectName("muted")
            v.addWidget(note)
        h.addWidget(b_inst)
        h.addWidget(b_ext)
        h.addWidget(b_copy)
        h.addStretch(1)
        h.addWidget(b_close)
        v.addLayout(h)

    def _extension(self):
        out = os.path.join(os.path.dirname(ROOT), "FreeLaserCut.mcpb")
        try:
            build_mcpb(out)
        except OSError as ex:
            QMessageBox.warning(self, tr("Estensione"), tr("Non riesco a creare l'estensione:\n{0}", ex))
            return
        try:
            if os.name == "nt":
                os.startfile(out)  # l'app Claude la riconosce e chiede di installarla
        except OSError:
            pass
        QMessageBox.information(self, tr("Estensione per Claude"), tr("Creata: {0}\n\nSe l'app Claude non si apre da sola: Impostazioni → Estensioni → Impostazioni avanzate → Installa estensione, e scegli questo file.", out))

    def _install(self):
        try:
            files = install()
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, tr("Collega a Claude"), tr("Non riesco a scrivere la configurazione:\n{0}\n\nPuoi copiarla e incollarla a mano in Claude → Impostazioni → Sviluppatore.", ex))
            return
        QMessageBox.information(self, tr("Collega a Claude"), tr("Fatto. Configurazione aggiornata in:\n")
                                + "\n".join(files) + tr("\n\nOra chiudi del tutto l'app Claude e riaprila."))
