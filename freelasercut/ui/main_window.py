# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Finestra principale di FreeLaserCut 0.2: editor completo + controllo macchina."""
import html
import os
import re
import sys
import time

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence, QTransform
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStatusBar, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__, gcode_preview
from ..core import gcode, geom, io_formats, materials, ops, resume, variables
from ..core.document import Document, ImageShape
from ..grbl import SIM_PORT, GrblController, list_serial_ports
from ..grbl_codes import STATE_COLORS
from ..profile import MachineProfile, config_dir, migrate_qsettings
from ..theme import C, QSS, css, tc
from . import style
from .canvas import Canvas
from .dialogs_materials import MaterialLibraryDialog, MaterialTestDialog
from .dialogs import CheckResultDialog, CircularArrayDialog, GridArrayDialog, OffsetDialog, PreviewDialog
from .editor import Editor
from .help_mode import HelpMode
from .panels_design import LayersPanel, NumericBar, PaletteBar, PropertiesPanel
from .panels_machine import LaserPanel, MovePanel
from .dialogs_setup import corner_name
from freelasercut.i18n import tr  # noqa: E402
from .. import units

ASSETS = style.ASSETS
STATE_IT = {"Idle": tr("Pronta"), "Run": tr("In lavoro"), "Jog": "Jog", "Hold": tr("In pausa"), "Door": tr("Porta aperta"),
            "Home": tr("Homing"), "Alarm": tr("Allarme"), "Check": tr("Verifica"), "Sleep": tr("Riposo"), "Disconnesso": tr("Disconnessa")}
FILE_FILTER = tr("Progetto FreeLaserCut (*.flcut)")
OPEN_FILTER = (tr("Tutti i progetti (*.flcut *.fbrn *.lbrn2 *.lbrn)") + ";;"
               + tr("Progetto FreeLaserCut (*.flcut *.fbrn)") + ";;" + tr("Progetti .lbrn2 e .lbrn (*.lbrn2 *.lbrn)"))
IMPORT_FILTER = (tr("Tutti i formati supportati (*.svg *.dxf *.lbrn2 *.lbrn *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp)")
                 + ";;SVG (*.svg);;DXF (*.dxf);;" + tr("Immagini (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp)"))



BIG_PHOTO_DOTS = 5_000_000  # oltre: chiede conferma prima di preparare il lavoro (tempo, memoria)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.qs = migrate_qsettings()
        self.ctl = GrblController()
        from .. import diag

        # registro della comunicazione con la scheda: si salva da solo quando qualcosa va storto
        self.comm_log = diag.CommLog(self.ctl, self)
        self.comm_log.on_stall = self._job_stalled
        from .update_ui import UpdateManager

        self.updates = UpdateManager(self)  # aggiornamento dal programma (Release di GitHub)
        self._update_installer = None
        self.profile = self._load_active_profile()
        self.editor = Editor(Document())
        self.canvas = Canvas(self.editor, (self.profile.bed_x, self.profile.bed_y))
        self.bed = self.canvas  # compatibilità con il pannello Camera
        self.job = None
        self.job_preview = None
        self.job_preview_off = None
        self._pending_start = None
        self._interrupted = None  # (righe, riga raggiunta) per la ripresa
        self.setWindowTitle(tr("FreeLaserCut"))
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "logo.svg")))
        self.setDockNestingEnabled(True)
        scr = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else None
        if scr is not None:  # mai più grande dello schermo (barra in basso e tavolozza resterebbero nascoste)
            self.resize(min(1600, scr.width() - 40), min(980, scr.height() - 60))
            self.move(scr.left() + 20, scr.top() + 10)
        else:
            self.resize(1600, 980)

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.banner = self._build_banner()
        cv.addWidget(self.banner)
        cv.addWidget(self.canvas, 1)
        self.setCentralWidget(central)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_docks()
        from .fire_ui import FireGuard

        self.fire = FireGuard(self, self.qs)  # guardia fiamme (spenta di partenza)
        self._sync_axes()
        from .phone_ui import PhoneControl

        self.phone = PhoneControl(self)  # controllo dal telefono (spento di partenza, solo per la sessione)
        self._build_statusbar()
        self._wire()
        self.refresh_ports()
        self.on_connection(False, "")
        self._update_title()
        if self.qs.value("auto_connect", "true") in (True, "true"):
            QTimer.singleShot(900, self._auto_connect)
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.autosave)
        self._autosave.start(90_000)
        QTimer.singleShot(400, self._offer_recovery)
        QTimer.singleShot(200, self._first_run_notice)
        QTimer.singleShot(2200, self._offer_setup)
        QTimer.singleShot(4000, self.updates.startup)
        try:  # comandi da Claude (MCP): solo da questo PC
            from ..remote import RemoteServer

            self.remote = RemoteServer(self)
        except Exception:  # noqa: BLE001
            self.remote = None
        geom = self.qs.value("win_geom")
        if geom is not None:
            try:
                self.restoreGeometry(geom)  # posizione, misure ed eventuale "a tutto schermo" dell'ultima volta
            except TypeError:
                pass
        self._default_state = self.saveState(5)  # disposizione iniziale, per "Ripristina la disposizione"
        state = self.qs.value("win_state_v5")
        if state is not None:
            try:
                self.restoreState(state, 5)
                for d in self.docks.values():
                    if not d.isVisible():
                        d.show()
            except TypeError:
                pass
        from .banco import ui_mode

        self.ui_mode = ui_mode(self.qs)
        self.banco = None
        if self.ui_mode == "banco":  # interfaccia «Banco»: stessa logica, disposizione diversa
            from .banco import Banco

            self.banco = Banco(self)
        self.update_rotary_state()
        from . import cmd_labels

        cmd_labels.label_actions(self)
        # scritte e spiegazioni dei segni del piano: niente con la modalità esperto né durante il lavoro
        self.canvas.hints_allowed = lambda: not self.expert_mode() and not (self.ctl.job_active or self.ctl.checking)
        self.set_help_level(self.help_level(), quiet=True)

    # ================================================================ azioni
    def _a(self, text, slot=None, shortcut=None, icon=None, tip=None, checkable=False):
        a = QAction(text, self)
        if icon:
            a.setIcon(style.icon(icon))
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut])])
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(f"{text}  ({a.shortcut().toString()})" if shortcut else text)
        a.setCheckable(checkable)
        if slot is not None:
            a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self):
        e, c = self.editor, self.canvas
        A = self._a
        self.acts = {
            "new": A(tr("Nuovo"), self.file_new, "Ctrl+N", "new"),
            "open": A(tr("Apri…"), self.file_open, "Ctrl+O", "open"),
            "save": A(tr("Salva"), self.file_save, "Ctrl+S", "save"),
            "save_as": A(tr("Salva con nome…"), self.file_save_as, "Ctrl+Shift+S"),
            "import": A(tr("Importa…"), self.file_import, "Ctrl+I", "import", "SVG, DXF, PNG, JPG, BMP…"),
            "export": A(tr("Esporta SVG…"), self.file_export, "Ctrl+Shift+E", "export"),
            "save_gcode": A(tr("Salva G-code…"), self.save_gcode, "Ctrl+Shift+G", "gcode"),
            "run_file": A(tr("Esegui un file G-code…"), self.run_gcode_file, None, "open"),
            "quit": A(tr("Esci"), self.close, "Ctrl+Q"),
            "undo": A(tr("Annulla {0}", "").strip(), e.undo, "Ctrl+Z", "undo"),
            "redo": A(tr("Ripeti"), e.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "redo"),
            "cut": A(tr("Taglia"), e.cut, "Ctrl+X", "cut"),
            "copy": A(tr("Copia"), e.copy, "Ctrl+C", "copy"),
            "paste": A(tr("Incolla"), lambda: e.paste(at=self.canvas.cursor_bed), "Ctrl+V", "paste"),
            "paste_in_place": A(tr("Incolla sul posto"), lambda: e.paste(in_place=True), "Ctrl+Shift+V"),
            "duplicate": A(tr("Duplica"), e.duplicate, "Ctrl+D", "duplicate"),
            "delete": A(tr("Elimina"), e.delete, None, "delete"),
            "select_all": A(tr("Seleziona tutto"), e.select_all, "Ctrl+A", "select_all"),
            "invert_sel": A(tr("Inverti selezione"), e.invert_selection, "Ctrl+Shift+I", "invert_sel"),
            "sel_open": A(tr("Seleziona forme aperte"), e.select_open, None, "open_shapes"),
            "sel_open_fill": A(tr("Seleziona forme aperte sui riempimenti"), lambda: e.select_open(True)),
            "sel_contained": A(tr("Aggiungi le forme contenute"), e.select_contained),
            "to_path": A(tr("Converti in tracciato"), e.convert_to_path, "Ctrl+Shift+C", "to_path"),
            "trace": A(tr("Vettorizza immagine…"), self.trace_dialog, "Alt+T", "trace",
                       tr("Trasforma una foto o un disegno in tracciati (contorno o linea centrale)")),
            "photo": A(tr("Prepara foto…"), self.photo_dialog, "Ctrl+Alt+F", "photo_prep",
                       tr("Ritaglio, regolazioni, sfondo, forma e metodo di incisione con l'anteprima dei punti veri; "
                          "oppure la foto diventa linee e riempimenti")),
            "close_paths": A(tr("Chiudi tracciati…"), self.close_paths_dialog, None, "close_path"),
            "join": A(tr("Unisci estremi"), e.auto_join, "Alt+J", "join"),
            "break": A(tr("Scomponi"), e.break_apart, "Alt+B", "break"),
            "reverse": A(tr("Inverti direzione di taglio"), e.reverse),
            "duplicates": A(tr("Elimina duplicati"), e.delete_duplicates, "Alt+D", "duplicates"),
            "offset": A(tr("Offset forme…"), self.offset_dialog, "Alt+O", "offset"),
            "lock": A(tr("Blocca"), lambda: e.lock(True), "Ctrl+L", "lock"),
            "unlock": A(tr("Sblocca"), lambda: e.lock(False), "Ctrl+Shift+L", "unlock"),
            "group": A(tr("Raggruppa"), e.group, "Ctrl+G", "group"),
            "ungroup": A(tr("Separa"), e.ungroup, "Ctrl+U", "ungroup"),
            "weld": A(tr("Salda"), e.weld, "Ctrl+W", "weld"),
            "union": A(tr("Unione"), lambda: e.boolean("union"), None, "union"),
            "difference": A(tr("Differenza (la prima meno la seconda)"), lambda: e.boolean("difference"), None, "subtract"),
            "intersection": A(tr("Intersezione"), lambda: e.boolean("intersection"), None, "intersect"),
            "xor": A(tr("Esclusione"), lambda: e.boolean("xor"), None, "exclude"),
            "flip_h": A(tr("Rifletti orizzontalmente"), lambda: e.flip(True), "Ctrl+Shift+H", "flip_h"),
            "flip_v": A(tr("Rifletti verticalmente"), lambda: e.flip(False), "Ctrl+Alt+V", "flip_v"),
            "rot_cw": A(tr("Ruota di 90° in senso orario"), lambda: e.rotate(-90), ".", "rot_cw"),
            "rot_ccw": A(tr("Ruota di 90° in senso antiorario"), lambda: e.rotate(90), ",", "rot_ccw"),
            "align_left": A(tr("Allinea a sinistra"), lambda: e.align("left"), "Alt+Left", "align_left"),
            "align_right": A(tr("Allinea a destra"), lambda: e.align("right"), "Alt+Right", "align_right"),
            "align_top": A(tr("Allinea in alto"), lambda: e.align("top"), "Alt+Up", "align_top"),
            "align_bottom": A(tr("Allinea in basso"), lambda: e.align("bottom"), "Alt+Down", "align_bottom"),
            "align_hcenter": A(tr("Centra in orizzontale"), lambda: e.align("hcenter"), None, "align_hcenter"),
            "align_vcenter": A(tr("Centra in verticale"), lambda: e.align("vcenter"), None, "align_vcenter"),
            "align_center": A(tr("Centra i centri"), lambda: e.align("center"), "Alt+C"),
            "dist_h": A(tr("Distribuisci spazi orizzontali"), lambda: e.distribute("h", "gap"), None, "dist_h"),
            "dist_v": A(tr("Distribuisci spazi verticali"), lambda: e.distribute("v", "gap"), None, "dist_v"),
            "dist_hc": A(tr("Distribuisci centri orizzontali"), lambda: e.distribute("h", "center")),
            "dist_vc": A(tr("Distribuisci centri verticali"), lambda: e.distribute("v", "center")),
            "same_w": A(tr("Stessa larghezza dell'ultima selezionata"), lambda: e.same_size("w")),
            "same_h": A(tr("Stessa altezza dell'ultima selezionata"), lambda: e.same_size("h")),
            "grid_array": A(tr("Serie a griglia…"), self.grid_array_dialog, "Alt+A", "grid_array"),
            "circ_array": A(tr("Serie circolare…"), self.circ_array_dialog, None, "circ_array"),
            "along_path": A(tr("Copia lungo un tracciato…"), self.along_path_dialog),
            "nest": A(tr("Ottimizza lo spazio (nesting)…"), self.nest_dialog, "Alt+N", "nest",
                      tr("Sistema i pezzi sul materiale sprecandone il meno possibile")),
            "common_lines": A(tr("Unisci le linee di taglio comuni"), self.common_lines_cmd, None, "common_lines",
                              tr("I lati che due pezzi hanno in comune si tagliano una volta sola")),
            "front": A(tr("Porta in primo piano"), lambda: e.order("front"), "Ctrl+Shift+Up", "front"),
            "back": A(tr("Porta in fondo"), lambda: e.order("back"), "Ctrl+Shift+Down", "back"),
            "zoom_in": A(tr("Ingrandisci"), lambda: c.zoom_by(1.25), ["Ctrl++", "Ctrl+="], "zoom_in"),
            "zoom_out": A(tr("Riduci"), lambda: c.zoom_by(0.8), "Ctrl+-", "zoom_out"),
            "fit": A(tr("Adatta al piano"), c.fit_bed, "Ctrl+0", "fit"),
            "fit_sel": A(tr("Adatta alla selezione"), c.fit_selection, "Ctrl+Shift+0"),
            "filled": A(tr("Vista riempita"), self._toggle_filled, "Alt+W", checkable=True),
            "grid": A(tr("Griglia"), self._toggle_grid, "Ctrl+'", "grid", checkable=True),
            "snap_grid": A(tr("Aggancia alla griglia"), lambda x: self._set_snap("snap_grid", x), "Shift+F9", "grid",
                           checkable=True),
            "snap_obj": A(tr("Aggancia agli oggetti"), lambda x: self._set_snap("snap_objects", x), "F9", "magnet",
                          checkable=True),
            "light_bed": A(tr("Piano chiaro"), self._toggle_light_bed, None, checkable=True),
            "dither_prev": A(tr("Mostra il dithering delle immagini"), self._toggle_dither, checkable=True),
            "connect": A(tr("Connetti / disconnetti la macchina"), lambda: self.toggle_connection(), "Ctrl+K", "connect"),
            "home": A(tr("Homing"), self.ctl.home, "Ctrl+H", "home"),
            "unlock_m": A(tr("Sblocca macchina ($X)"), self.ctl.unlock, None, "unlock"),
            "frame": A(tr("Contorno"), lambda: self.frame_job("box"), "Ctrl+Shift+F", "frame"),
            "verify": A(tr("Verifica il lavoro"), self.verify_job, "Ctrl+Shift+K", "verify"),
            "start": A(tr("Avvia il lavoro"), self.start_job, "Ctrl+Return", "play"),
            "pause": A(tr("Pausa / riprendi"), self._toggle_pause, "Ctrl+Space", "pause"),
            "stop": A(tr("Stop"), self.ctl.stop_job, "Ctrl+Break", "stop"),
            "preview": A(tr("Anteprima…"), self.preview_job, "Alt+P", "preview"),
            "exact_shape": A(tr("Crea forma con misure esatte…"), self.exact_shape_dialog, "Ctrl+Alt+N", "ruler_add",
                             tr("Rettangolo, cerchio, poligono o forma della galleria con larghezza, altezza e posizione precise")),
            "code": A(tr("Codice QR o a barre…"), self.code_dialog, "Ctrl+Alt+Q", "qr",
                      tr("QR, Code 128, EAN-13, EAN-8, UPC-A, Code 39, anche con numeri di serie")),
            "puzzle": A(tr("Puzzle da foto…"), self.puzzle_dialog, None, "puzzle",
                        tr("La foto selezionata (o una da scegliere) diventa un puzzle: incastri sempre diversi, anche "
                           "a forma di cuore, cerchio o di una forma tua; prima si incide la foto, poi si tagliano i pezzi")),
            "text_path": A(tr("Testo su tracciato…"), self.text_path_dialog, "Ctrl+Alt+T", "text_path",
                           tr("Seleziona un testo e una linea o forma: il testo ne segue la curva")),
            "variables": A(tr("Testo variabile…"), self.variables_dialog, None, "variable",
                           tr("Numeri di serie, data e campi da CSV nei testi")),
            "materials": A(tr("Libreria materiali…"), self.material_library, "Ctrl+M", "library"),
            "material_test": A(tr("Test materiale…"), self.material_test, None, "grid",
                               tr("Griglia potenza × velocità per trovare i valori giusti di un materiale")),
            "scan_offset": A(tr("Correzione della scansione avanti e indietro…"), self.scan_offset_dialog, None, None,
                             tr("Allinea le righe incise andando e tornando: bordi dritti e scritte nitide nei "
                                "riempimenti e nelle foto")),
            "phone": A(tr("Controllo dal telefono…"), self.phone_dialog, None, "smartphone",
                       tr("Dal telefono sulla rete di casa: avanzamento, camera, pausa, stop e foto del test")),
            "board_backup": A(tr("Copie delle impostazioni della scheda…"), self.board_backup_dialog, None, None,
                              tr("Copie automatiche dei parametri della scheda ($$): confronto e ripristino in un clic")),
            "fire_guard": A(tr("Guardia fiamme…"), self.fire_guard_dialog, None, "fire",
                            tr("Durante il lavoro guarda la camera: se vede una fiamma ferma tutto e spegne il laser")),
            "rotary": A(tr("Rotativo (bicchieri, cilindri)…"), self.rotary_dialog, None, "rotary",
                        tr("Accessorio rotativo a rulli o a mandrino al posto dell'asse Y"), checkable=True),
            "identify": A(tr("Riconosci la macchina…"), self.identify_machine, None, "usb",
                          tr("Porte USB, chip e driver, lettura della scheda e profilo adattato in automatico")),
            "profile_export": A(tr("Esporta il profilo della macchina…"), self.export_profile, None, None,
                                tr("Salva il profilo attivo in un file .flcprofile da condividere con chi ha la stessa "
                                   "macchina")),
            "profile_import": A(tr("Importa un profilo macchina…"), self.import_profile, None, None,
                                tr("Apre un profilo .flcprofile condiviso da un altro utente: i valori vengono controllati "
                                   "e il profilo è segnato «dalla comunità»")),
            "youtube": A(tr("Video tutorial su YouTube"), self.open_youtube, None, None,
                         tr("Apre il canale YouTube di FreeLaserCut con i video tutorial")),
            "help_mode": A(tr("Che cos'è?"), None, None, "help",
                           tr("Guida: passa il mouse su un comando per leggerne descrizione e opzioni (Maiusc+F1)"),
                           checkable=True),
            "shortcuts": A(tr("Scorciatoie da tastiera"), self.show_shortcuts, "F1"),
            "about": A(tr("Informazioni su FreeLaserCut"), self.show_about),
            "report": A(tr("Crea rapporto per l'assistenza…"), self.make_support_report, None, None,
                        tr("Un file .zip con versione, sistema, profilo della macchina, registro errori e registro "
                           "della comunicazione con la scheda, da allegare a una segnalazione. Niente progetti né dati personali.")),
            "updates": A(tr("Cerca aggiornamenti…"), lambda: self.updates.check(manual=True), None, None,
                         tr("Controlla su GitHub se c'è una versione più nuova di FreeLaserCut e, se vuoi, la scarica "
                            "e la installa: FreeLaserCut si chiude e si riapre da solo.")),
            "help_beginner": A(tr("Principiante: nomi sotto i comandi e spiegazioni"),
                               lambda: self.set_help_level("principiante"), None, None,
                               tr("Sotto ogni icona un nome corto, scritte accanto ai segni del piano, spiegazioni "
                                  "passando sui segni e suggerimenti"), checkable=True),
            "help_normal": A(tr("Normale: spiegazioni passando sui segni"), lambda: self.set_help_level("normale"), None,
                             None, tr("Solo icone; spiegazioni passando sui segni del piano e suggerimenti come «Fai "
                                      "l'homing»"), checkable=True),
            "help_expert": A(tr("Esperto: meno scritte d'aiuto"), lambda: self.set_help_level("esperto"), None, None,
                             tr("Niente nomi, spiegazioni dei segni e suggerimenti. Gli avvisi di sicurezza restano "
                                "sempre."), checkable=True),
            "setup_wizard": A(tr("Configurazione guidata della macchina…"), self.setup_wizard, None, None,
                              tr("Poche domande: il modello, l'angolo dello 0 della macchina e la prova delle frecce. "
                                 "Si può rifare quando vuoi.")),
            "update_auto": A(tr("Controlla gli aggiornamenti ogni giorno"), lambda on: self.updates.set_enabled(on), None, None,
                             tr("All'avvio, al massimo una volta al giorno, FreeLaserCut chiede a GitHub qual è l'ultima "
                                "versione. Non invia dati tuoi e non scarica niente senza chiedere."), checkable=True),
            "support": A(tr("Sostieni FreeLaserCut…"), self.show_support, None, None,
                         tr("Contributo volontario allo sviluppo (GitHub Sponsors o PayPal)")),
            "claude": A(tr("Collega a Claude (MCP)…"), self.claude_dialog, None, "connect",
                        tr("Detta a Claude cosa disegnare e preparare in FreeLaserCut")),
        }
        for k in ("filled", "grid"):
            self.acts[k].setChecked(True)
        on = lambda key, d: self.qs.value(key, d) in (True, "true")  # noqa: E731
        self.acts["light_bed"].setChecked(on("light_bed", True))
        c.light_bed = self.acts["light_bed"].isChecked()
        self.acts["snap_obj"].setChecked(on("snap_objects", True))
        self.acts["snap_grid"].setChecked(on("snap_grid", False))
        c.snap_objects = self.acts["snap_obj"].isChecked()
        c.snap_grid = self.acts["snap_grid"].isChecked()
        self.tool_actions = {}
        grp = QActionGroup(self)
        for name, label, icon, key in (("select", tr("Selezione"), "select", "V"), ("nodes", tr("Modifica nodi"), "nodes", "N"),
                                       ("line", tr("Linee e curve"), "line", "L"), ("rect", tr("Rettangolo"), "rect", "R"),
                                       ("ellipse", tr("Ellisse e cerchio"), "ellipse", "E"),
                                       ("polygon", tr("Poligono"), "polygon", "P"), ("star", tr("Stella"), "star", "S"),
                                       ("special", "Forme: frecce, cuore, scudo, medaglia, ingranaggio…", "shapes", "F"),
                                       ("text", tr("Testo"), "text", "T"), ("measure", tr("Misura"), "measure", "M"),
                                       ("position", tr("Posiziona laser (clic = la testa va lì)"), "position", "Q")):
            a = QAction(style.icon(icon), label, self)
            a.setShortcut(QKeySequence(key))
            a.setToolTip(f"{label}  ({key})")
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, n=name: self.canvas.set_tool(n))
            grp.addAction(a)
            self.addAction(a)
            self.tool_actions[name] = a
        self.tool_actions["select"].setChecked(True)
        # guida contestuale: ogni comando sa qual è la sua scheda descrittiva
        for k, act in self.acts.items():
            act.setProperty("help_key", k)
        for n, act in self.tool_actions.items():
            act.setProperty("help_key", f"tool:{n}")
        self.canvas.setProperty("help_key", "canvas")
        self.help = HelpMode(self)
        self.acts["help_mode"].setToolTip(tr("Che cos'è?  (Maiusc+F1) — passa il mouse su un comando per leggerne la "
                                          "descrizione e le opzioni"))
        self.acts["help_mode"].toggled.connect(self.help.set_active)
        self.help.toggled.connect(lambda on: self.acts["help_mode"].setChecked(on))

    def _build_menus(self):
        mb = self.menuBar()
        a = self.acts
        # in alto a destra, sempre visibile: contributo volontario allo sviluppo
        a["support"].setIcon(style.icon("heart", color="#E5484D", active="#E5484D"))
        a["support"].setIconText(tr("Sostieni FreeLaserCut"))
        sb = QToolButton()
        sb.setObjectName("supportbtn")
        sb.setDefaultAction(a["support"])
        sb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        sb.setIconSize(QSize(14, 14))
        sb.setCursor(Qt.PointingHandCursor)
        sb.setToolTip(tr("Sostieni FreeLaserCut: contributo volontario allo sviluppo"))
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 1, 6, 1)
        cl.addWidget(sb)
        mb.setNativeMenuBar(False)  # l'angolo con il pulsante esiste solo nella barra dei menu di Qt
        mb.setCornerWidget(corner, Qt.TopRightCorner)
        self.support_button = sb
        self._support_corner = corner  # PySide non ne prende la proprietà: senza riferimento verrebbe distrutto

        def menu(title, keys):
            m = mb.addMenu(title)
            for k in keys:
                if k == "-":
                    m.addSeparator()
                elif isinstance(k, tuple):
                    sub = m.addMenu(k[0])
                    for kk in k[1]:
                        if kk == "-":
                            sub.addSeparator()
                        elif callable(kk):
                            kk(sub)
                        else:
                            sub.addAction(a[kk])
                else:
                    m.addAction(a[k])
            return m

        self.m_file = menu(tr("&File"), ["new", "open", "-", "save", "save_as", "-", "import", "export", "-", "save_gcode",
                                     "run_file", "-", "quit"])
        self.m_recent = QMenu(tr("File recenti"), self)
        self.m_file.insertMenu(a["save"], self.m_recent)
        self.m_file.insertSeparator(a["save"])
        self._refresh_recent()
        menu(tr("&Modifica"), ["undo", "redo", "-", "cut", "copy", "paste", "paste_in_place", "duplicate", "delete", "-",
                           "select_all", "invert_sel", (tr("Seleziona speciale"), ["sel_open", "sel_open_fill", "sel_contained"]),
                           "-", "to_path", "trace", "close_paths", "join", "break", "reverse", "duplicates", "offset", "-",
                           "lock", "unlock"])

        def anchors_move(sub):
            for i, n in enumerate(gcode.ANCHOR_NAMES):
                act = sub.addAction(n.capitalize())
                act.triggered.connect(lambda _=False, i=i: self.editor.move_to(i, QRectF(0, 0, self.profile.bed_x, self.profile.bed_y)))

        def anchors_head(sub):
            for i, n in enumerate(gcode.ANCHOR_NAMES):
                act = sub.addAction(n.capitalize())
                act.triggered.connect(lambda _=False, i=i: self.head_to_selection(i))

        menu(tr("&Disponi"), ["group", "ungroup", "-", "weld", (tr("Operazioni booleane"), ["union", "difference", "intersection", "xor"]),
                          "-", "flip_h", "flip_v", "rot_cw", "rot_ccw", "-",
                          (tr("Allinea"), ["align_left", "align_hcenter", "align_right", "-", "align_top", "align_vcenter",
                                       "align_bottom", "-", "align_center"]),
                          (tr("Distribuisci"), ["dist_h", "dist_v", "dist_hc", "dist_vc"]),
                          (tr("Stessa misura"), ["same_w", "same_h"]),
                          (tr("Sposta sul piano"), [anchors_move]), (tr("Porta la testa sulla selezione"), [anchors_head]), "-",
                          "grid_array", "circ_array", "along_path", "-", "nest", "common_lines", "-", "front", "back"])
        m = mb.addMenu(tr("&Strumenti"))
        for name in ("select", "nodes", "line", "rect", "ellipse", "polygon", "star", "special", "text", "measure",
                     "position"):
            m.addAction(self.tool_actions[name])
        m.addSeparator()
        m.addAction(a["exact_shape"])
        m.addAction(a["code"])
        m.addAction(a["text_path"])
        m.addAction(a["puzzle"])
        m.addSeparator()
        m.addAction(a["variables"])
        m.addAction(a["photo"])
        m.addAction(a["trace"])
        menu(tr("&Laser"), ["connect", "identify", "profile_export", "profile_import", "-", "home", "unlock_m", "-", "frame", "verify", "preview", "-", "start", "pause", "stop", "-",
                        "materials", "material_test", "scan_offset", "-", "board_backup", "fire_guard", "phone", "rotary", "-", "save_gcode", "run_file"])
        self.m_view = menu(tr("&Visualizza"), ["zoom_in", "zoom_out", "fit", "fit_sel", "-", "filled", "grid", "light_bed",
                                           "snap_grid", "snap_obj", "dither_prev"])
        self.m_view.addSeparator()
        self.m_panels = self.m_view.addMenu(tr("Pannelli"))
        self.m_view.addAction(tr("Ripristina la disposizione dei pannelli"), lambda: self.reset_layout())
        self.m_view.addSeparator()
        self._build_language_menu(self.m_view)
        self._build_settings_menu(mb)
        hm = menu(tr("&Aiuto"), ["help_mode", "-", "youtube", "claude", "-", "shortcuts", "about", "report", "-", "updates", "update_auto",
                                 "-", "support"])
        hm.insertMenu(hm.actions()[1], self.m_help_level)  # lo stesso sottomenu di Impostazioni: un solo pallino
        self.acts["update_auto"].setChecked(self.updates.enabled())
        self.acts["update_auto"].setVisible(self.updates.mode == "installer")  # Store e git si aggiornano da sé

    def _build_settings_menu(self, mb):
        """Impostazioni: interfaccia (Banco / Classica), secondo monitor, lingua, vista."""
        from .banco import ui_mode

        m = mb.addMenu(tr("&Impostazioni"))
        self.m_settings = m
        m.addAction(self.acts["setup_wizard"])
        m.addSeparator()
        sub = m.addMenu(tr("Interfaccia"))
        grp = QActionGroup(self)
        grp.setExclusive(True)
        cur = ui_mode(self.qs)
        self.ui_actions = {}
        for code, label in (("banco", tr("Banco (piano a tutto schermo)")), ("classica", tr("Classica (menu e pannelli)"))):
            act = sub.addAction(label)
            act.setCheckable(True)
            act.setChecked(code == cur)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.choose_interface(c))
            self.ui_actions[code] = act
        sec = m.addAction(tr("Officina sul secondo monitor, se c'è"))
        sec.setCheckable(True)
        sec.setChecked(self.qs.value("officina_second_screen", "true") in (True, "true"))
        sec.toggled.connect(self._toggle_second_screen)
        self.act_second_screen = sec
        self._build_look_menu(m)
        self._build_units_menu(m)
        # Livello di aiuto: tre voci, una sola attiva (anche nel menu Aiuto; nel Banco il menu Aiuto non c'è)
        sub = m.addMenu(tr("Livello di aiuto"))
        self.m_help_level = sub
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for k in ("help_beginner", "help_normal", "help_expert"):
            grp.addAction(self.acts[k])
            sub.addAction(self.acts[k])
        m.addSeparator()
        m.addMenu(self.m_language)  # lo stesso sottomenu di Visualizza: una sola lista di lingue
        m.addSeparator()
        for k in ("light_bed", "snap_obj", "snap_grid", "dither_prev"):
            m.addAction(self.acts[k])

    def _build_look_menu(self, parent):
        """Impostazioni → Aspetto: tema scuro / chiaro / come Windows e colore principale (vale dal riavvio)."""
        from PySide6.QtGui import QPixmap

        from .. import theme

        sub = parent.addMenu(tr("Aspetto"))
        self.m_look = sub
        self.theme_actions, self.accent_actions = {}, {}
        cur_t = str(self.qs.value("ui_theme", theme.THEME))
        cur_a = str(self.qs.value("ui_accent", theme.ACCENT))
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for code, label in (("scuro", tr("Tema scuro")), ("chiaro", tr("Tema chiaro")),
                            ("sistema", tr("Come Windows (chiaro o scuro)"))):
            act = sub.addAction(label)
            act.setCheckable(True)
            act.setChecked(code == cur_t)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.choose_look(theme=c))
            self.theme_actions[code] = act
        sub.addSeparator()
        sub.addSection(tr("Colore principale"))
        grp2 = QActionGroup(self)
        grp2.setExclusive(True)
        names = {"blu": tr("Blu"), "verde": tr("Verde"), "viola": tr("Viola"), "arancio": tr("Arancio"), "rosa": tr("Rosa")}
        for code, cols in theme.ACCENTS.items():
            pm = QPixmap(14, 14)
            pm.fill(QColor(cols[0]))
            act = sub.addAction(QIcon(pm), names.get(code, code))
            act.setCheckable(True)
            act.setChecked(code == cur_a)
            grp2.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.choose_look(accent=c))
            self.accent_actions[code] = act

    def _build_units_menu(self, parent):
        """Impostazioni → Unità di misura: velocità in mm/min (come GRBL) o in mm/s."""
        sub = parent.addMenu(tr("Unità di misura"))
        self.m_units = sub
        self.unit_actions = {}
        grp = QActionGroup(self)
        grp.setExclusive(True)
        cur = units.speed_unit()
        for code, label in (("mm/min", tr("Velocità in mm/min (millimetri al minuto)")),
                            ("mm/s", tr("Velocità in mm/s (millimetri al secondo)"))):
            act = sub.addAction(label)
            act.setCheckable(True)
            act.setChecked(code == cur)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.choose_units(c))
            self.unit_actions[code] = act
        sub.addSeparator()
        note = sub.addAction(tr("Le misure di lunghezza sono in mm (nei campi puoi scrivere anche 2in o 5cm)"))
        note.setEnabled(False)

    def choose_units(self, code):
        """Salva l'unità della velocità; i campi la usano dal prossimo avvio (propone di riavviare subito)."""
        if code not in units.UNITS:
            return False
        self.qs.setValue("unit_speed", code)
        self.qs.sync()
        if code == units.speed_unit():
            return False
        r = QMessageBox.question(self, tr("Unità di misura"), tr(
            "Le velocità saranno mostrate in {0} dal prossimo avvio di FreeLaserCut (progetti, profili e libreria "
            "non cambiano). Riavviare adesso?", code))
        if r == QMessageBox.Yes:
            self._restart = True
            if not self.close():
                self._restart = False
        return True

    def choose_look(self, theme=None, accent=None):
        """Salva tema e/o colore principale; si vedono dal prossimo avvio (propone di riavviare subito)."""
        from .. import theme as th

        if theme is not None:
            self.qs.setValue("ui_theme", theme)
        if accent is not None:
            self.qs.setValue("ui_accent", accent)
        self.qs.sync()
        if (str(self.qs.value("ui_theme", th.THEME)), str(self.qs.value("ui_accent", th.ACCENT))) == (th.THEME, th.ACCENT):
            return False  # è già quello in uso
        r = QMessageBox.question(self, tr("Aspetto"), tr("Il nuovo aspetto sarà usato dal prossimo avvio di FreeLaserCut. "
                                                         "Riavviare adesso?"))
        if r == QMessageBox.Yes:
            self._restart = True
            if not self.close():
                self._restart = False
        return True

    def _toggle_second_screen(self, on):
        self.qs.setValue("officina_second_screen", bool(on))
        if getattr(self, "banco", None) is not None:
            self.banco.check_screens()

    def choose_interface(self, code):
        from .banco import save_mode

        save_mode(code, self.qs)
        if code == getattr(self, "ui_mode", code):  # è già quella in uso
            return
        r = QMessageBox.question(self, tr("Interfaccia"), tr("La nuova interfaccia sarà usata dal prossimo avvio di "
                                                              "FreeLaserCut. Riavviare adesso?"))
        if r == QMessageBox.Yes:
            self._restart = True
            if not self.close():
                self._restart = False

    def _build_toolbars(self):
        a = self.acts
        tb = QToolBar(tr("Principale"))
        tb.setObjectName("main")
        tb.setIconSize(QSize(18, 18))
        tb.setMovable(False)
        for k in ("new", "open", "save", "-", "import", "-", "undo", "redo", "-", "cut", "copy", "paste", "delete",
                  "-", "group", "ungroup", "weld", "union", "difference", "intersection", "-", "flip_h", "flip_v",
                  "rot_ccw", "rot_cw", "-", "align_left", "align_hcenter", "align_right", "align_top", "align_vcenter",
                  "align_bottom", "dist_h", "dist_v", "nest", "-", "offset", "grid_array", "circ_array", "-", "zoom_in",
                  "zoom_out", "fit", "-", "preview", "-", "trace", "exact_shape", "code", "materials", "material_test"):
            if k == "-":
                tb.addSeparator()
            else:
                tb.addAction(a[k])
        # a destra, nello spazio libero: riconoscimento macchina e guida "?"
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(a["identify"])
        tb.addAction(a["help_mode"])
        hb = tb.widgetForAction(a["help_mode"])
        hb.setObjectName("helpbtn")
        hb.setProperty("help_toggle", True)
        self.addToolBar(Qt.TopToolBarArea, tb)
        # connessione: sempre visibile in cima al pannello Laser (e nella barra di stato)
        self.port_combo = QComboBox()
        self.port_combo.setToolTip(tr("Porta USB della macchina (★ = probabilmente il laser)"))
        rb = QToolButton()
        rb.setIcon(style.icon("refresh"))
        rb.setToolTip(tr("Cerca di nuovo le porte USB"))
        rb.clicked.connect(self.refresh_ports)
        self.btn_refresh = rb
        wb = QToolButton()
        wb.setIcon(style.icon("wifi"))
        wb.setToolTip(tr("Collega un laser via Wi-Fi (FluidNC, grblHAL, ESP3D)"))
        wb.clicked.connect(self.net_dialog)
        self.btn_wifi = wb
        self.btn_connect = QPushButton(tr("Connetti"))
        self.btn_connect.setObjectName("primary")
        self.btn_connect.setIcon(style.icon("connect", "#FFFFFF"))
        self.btn_connect.setToolTip(tr("Collega FreeLaserCut al laser (Ctrl+K)"))
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.setFixedHeight(20)
        self.pill.setMinimumWidth(64)
        self.pill.setAlignment(Qt.AlignCenter)
        self.addToolBarBreak()
        self.numeric = NumericBar(self.editor, self.canvas)
        self.addToolBar(Qt.TopToolBarArea, self.numeric)
        tools = QToolBar(tr("Strumenti"))
        tools.setObjectName("tools")
        tools.setOrientation(Qt.Vertical)
        tools.setIconSize(QSize(20, 20))
        tools.setMovable(False)
        for name in ("select", "nodes", "-", "line", "rect", "ellipse", "polygon", "star", "special", "text", "-",
                     "measure", "position"):
            if name == "-":
                tools.addSeparator()
            else:
                tools.addAction(self.tool_actions[name])
        self.addToolBar(Qt.LeftToolBarArea, tools)
        self.palette = PaletteBar(self.editor)
        self.addToolBar(Qt.BottomToolBarArea, self.palette)

    def _dock(self, title, widget, area=Qt.RightDockWidgetArea, name=None):
        d = QDockWidget(title, self)
        d.setObjectName(name or title)
        from .widgets import shrinkable

        shrinkable(widget)
        if not isinstance(widget, QScrollArea):  # se lo spazio non basta il pannello scorre, non si schiaccia
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sa.setWidget(widget)
            widget = sa
        d.setWidget(widget)
        # niente "X": i pannelli non si perdono più (si scelgono dalle schede o da Visualizza → Pannelli)
        d.setFeatures(QDockWidget.NoDockWidgetFeatures)
        d.setTitleBarWidget(QWidget())  # il titolo è già sulla scheda: niente barra doppia
        d.setMinimumWidth(300)
        icons = {"dock_layers": "layers", "dock_props": "settings", "dock_laser": "laser", "dock_move": "move",
                 "dock_camera": "camera", "dock_machine": "machine", "dock_console": "console"}
        act = QAction(style.icon(icons.get(name, "settings")), title, self)
        act.triggered.connect(lambda _=False, d=d: self.show_panel(d))
        self.m_panels.addAction(act)
        return d

    def show_panel(self, d):
        d.show()
        d.raise_()
        d.widget().setFocus()

    def reset_layout(self):
        """Torna alla disposizione iniziale dei pannelli (quella registrata all'avvio)."""
        if getattr(self, "_default_state", None) is not None:
            for d in self.docks.values():
                d.setFloating(False)
                d.show()
            self.restoreState(self._default_state, 5)
            self.docks["layers"].raise_()
            self.docks["laser"].raise_()
            QTimer.singleShot(0, self._clean_tabbars)
            h = max(self.height() - 160, 600)
            QTimer.singleShot(50, lambda: (self.resizeDocks([self.docks["layers"], self.docks["laser"]],
                                                             [int(h * 0.55), int(h * 0.45)], Qt.Vertical),
                                           self.resizeDocks([self.docks["layers"]],
                                                            [max(420, min(480, self.width() // 3))], Qt.Horizontal)))

    def _build_docks(self):
        from ..app import ConsolePanel, MachinePanel
        from ..camera_panel import CameraPanel

        self.layers = LayersPanel(self.editor, lambda: self.profile)
        self.props = PropertiesPanel(self.editor, self.canvas)
        self.laser = LaserPanel(self.ctl, self.qs)
        # punto di riferimento (9 pallini) e tipo di partenza: l'anteprima sul piano si sposta subito
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(150)
        self._place_timer.timeout.connect(self._placement_changed)
        self.laser.anchor.changed.connect(lambda *_: self._place_timer.start())
        self.laser.start_from.currentIndexChanged.connect(lambda *_: self._place_timer.start())
        self.laser.b_goto_anchor.clicked.connect(self.goto_anchor)
        self.laser.inv_x.toggled.connect(lambda on: self.set_axis_inverted("x", on))
        self.laser.inv_y.toggled.connect(lambda on: self.set_axis_inverted("y", on))
        self.move = MovePanel(self.ctl, self.qs, lambda: self.profile, self.canvas.head_pos)
        self.machine = MachinePanel(self.ctl, self.profile, self.on_profile)
        self.camera = CameraPanel(self.ctl, self)
        self.console = ConsolePanel(self.ctl)
        d1 = self._dock(tr("Livelli"), self.layers, name="dock_layers")
        d2 = self._dock(tr("Proprietà"), self.props, name="dock_props")
        d3 = self._dock(tr("Laser"), self.laser, name="dock_laser")
        d4 = self._dock(tr("Movimento"), self.move, name="dock_move")
        d5 = self._dock(tr("Camera"), self.camera, name="dock_camera")
        d6 = self._dock(tr("Macchina"), self.machine, name="dock_machine")
        d7 = self._dock(tr("Console"), self.console, name="dock_console")
        # due gruppi a destra: progettazione (sopra) e macchina (sotto)
        from PySide6.QtWidgets import QTabWidget

        self.setTabPosition(Qt.RightDockWidgetArea, QTabWidget.North)
        self.addDockWidget(Qt.RightDockWidgetArea, d1, Qt.Vertical)
        self.addDockWidget(Qt.RightDockWidgetArea, d3, Qt.Vertical)
        self.tabifyDockWidget(d1, d2)
        prev = d3
        for d in (d4, d5, d6, d7):  # ognuno sull'ultimo aggiunto: evita la barra intermedia di Qt
            self.tabifyDockWidget(prev, d)
            prev = d
        d1.raise_()
        d3.raise_()
        self.resizeDocks([d1, d3], [420, 520], Qt.Vertical)
        self.resizeDocks([d1], [430], Qt.Horizontal)
        self.docks = {"layers": d1, "props": d2, "laser": d3, "move": d4, "camera": d5, "machine": d6, "console": d7}
        conn = QFrame()
        conn.setObjectName("connbar")
        hl = QHBoxLayout(conn)
        hl.setContentsMargins(6, 4, 6, 4)
        hl.setSpacing(4)
        hl.addWidget(self.port_combo, 1)
        hl.addWidget(self.btn_refresh)
        hl.addWidget(self.btn_wifi)
        ib = QToolButton()
        ib.setDefaultAction(self.acts["identify"])
        hl.addWidget(ib)
        hl.addWidget(self.btn_connect)
        hl.addWidget(self.pill)
        self.laser.layout().insertWidget(0, conn)
        QTimer.singleShot(0, self._clean_tabbars)
        QTimer.singleShot(250, self._balance_docks)

    def _clean_tabbars(self):
        """Nasconde eventuali barre di schede rimaste orfane (difetto noto di Qt con tabifyDockWidget)."""
        from PySide6.QtWidgets import QTabBar

        groups = []
        for d in self.docks.values():
            g = {d.windowTitle()} | {x.windowTitle() for x in self.tabifiedDockWidgets(d)}
            if g not in groups:
                groups.append(g)
        for tb in self.findChildren(QTabBar):
            if tb.parent() is self and tb.isVisible():
                tabs = {tb.tabText(i) for i in range(tb.count())}
                if tabs and tabs not in groups:
                    tb.hide()

    def _balance_docks(self):
        if getattr(self, "banco", None) is not None:  # nel Banco i pannelli stanno nell'Officina
            return
        if self.qs.value("win_state_v5") is None:
            h = max(self.height() - 160, 600)
            self.resizeDocks([self.docks["layers"], self.docks["laser"]], [int(h * 0.58), int(h * 0.42)], Qt.Vertical)
            self.resizeDocks([self.docks["layers"]], [max(420, min(480, self.width() // 3))], Qt.Horizontal)

    def _build_banner(self):
        f = QFrame()
        f.setObjectName("alarm")
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 8, 14, 8)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        h.addWidget(self.banner_text, 1)
        self.banner_buttons = QHBoxLayout()
        h.addLayout(self.banner_buttons)
        x = QToolButton()
        x.setIcon(style.icon("x"))
        x.clicked.connect(self._dismiss_banner)
        h.addWidget(x)
        f.hide()
        self._banner_kind = None
        self._alarm_dismissed = False
        return f

    def show_banner(self, text, kind="alarm", buttons=(), hint=False):
        """hint=True: solo un suggerimento (es. «Fai l'homing»), che la modalità esperto non mostra."""
        if hint and self.expert_mode():
            return
        self._banner_hint = hint
        self._banner_kind = kind
        col = {"alarm": (C["danger"], "#3A1418", "#FFD9DA"), "info": (C["accent"], "#10264D", "#D6E6FF"),
               "warn": (C["warn"], "#3A2A0A", "#FFE8B8")}[kind]
        col = tuple(tc(x) for x in col)
        self.banner.setStyleSheet(f"QFrame#alarm {{ background:{col[1]}; border-bottom:1px solid {col[0]}; }}")
        self.banner_text.setStyleSheet(f"color:{col[2]}; font-weight:600;")
        self.banner_text.setText(text)
        while self.banner_buttons.count():
            w = self.banner_buttons.takeAt(0).widget()
            if w:
                w.setParent(None)
        for label, fn in buttons:
            b = QPushButton(label)
            b.clicked.connect(fn)
            self.banner_buttons.addWidget(b)
        self.banner.show()

    def _dismiss_banner(self):
        if self._banner_kind == "alarm":
            self._alarm_dismissed = True
        self.banner.hide()

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        from PySide6.QtGui import QFontMetrics

        mono = f"font-family: '{style.MONO_FONT}', Consolas, monospace; font-size: 8.5pt;"
        fm = QFontMetrics(style.mono_font(8.5))

        def fixed(sample):  # larghezza fissa: i numeri che cambiano non spostano il resto della barra
            lab = QLabel("")
            lab.setStyleSheet(mono)
            lab.setFixedWidth(fm.horizontalAdvance(sample) + 14)
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lab

        self.lbl_cursor = fixed(tr("X -0000.00  Y -0000.00 mm"))
        self.lbl_cursor.setText("X —  Y —")
        self.lbl_zoom = fixed("00000%")
        self.lbl_head = fixed("testa -000.00, -000.00  ·  lavoro -000.00, -000.00")
        self.lbl_fs = fixed("F 00000 mm/min · potenza 000%")
        self.lbl_fs.setObjectName("muted")
        self.sb_machine = QPushButton(tr("○  Laser non connesso"))
        self.sb_machine.setFlat(True)
        self.sb_machine.setCursor(Qt.PointingHandCursor)
        self.sb_machine.setToolTip(tr("Clic: connetti / disconnetti il laser"))
        self.sb_machine.clicked.connect(lambda: self.toggle_connection())
        sb.addWidget(self.sb_machine)
        self.sb_rotary = QPushButton(tr("⟳ Rotativo attivo"))
        self.sb_rotary.setFlat(True)
        self.sb_rotary.setCursor(Qt.PointingHandCursor)
        self.sb_rotary.setStyleSheet(css("color:#FFB347; font-weight:700;"))
        self.sb_rotary.setToolTip(tr("L'asse Y comanda il rotativo. Clic per le impostazioni"))
        self.sb_rotary.clicked.connect(self.rotary_dialog)
        sb.addWidget(self.sb_rotary)
        self.sb_rotary.setVisible(self.rotary_settings() is not None)
        snaps = QWidget()
        sl = QHBoxLayout(snaps)
        sl.setContentsMargins(0, 0, 8, 0)
        sl.setSpacing(4)
        for key, text in (("snap_obj", tr("Aggancio oggetti")), ("snap_grid", tr("Griglia"))):
            b = QToolButton()
            b.setDefaultAction(self.acts[key])
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setObjectName("snapbtn")
            b.setIconSize(QSize(14, 14))
            sl.addWidget(b)
        sb.addPermanentWidget(snaps)
        for w in (self.lbl_fs, self.lbl_head, self.lbl_cursor, self.lbl_zoom):
            sb.addPermanentWidget(w)

    def _wire(self):
        e, c, ctl = self.editor, self.canvas, self.ctl
        c.cursor_moved.connect(lambda x, y: self.lbl_cursor.setText(tr("X {0:8.2f}  Y {1:8.2f} mm", x, y)))
        c.zoom_changed.connect(lambda k: self.lbl_zoom.setText(f"{k / 3.78 * 100:5.0f}%"))
        c.status.connect(lambda t: self.statusBar().showMessage(t, 4000))
        c.tool_changed.connect(lambda n: self.tool_actions[n].setChecked(True))
        c.tool_changed.connect(self._tool_changed)
        c.edit_text.connect(self._edit_text)
        c.goto_requested.connect(self.goto_bed)
        c.jog_requested.connect(lambda dx, dy: ctl.jog(dx * self.move.step(), dy * self.move.step(), self.move.feed.value()))
        e.message.connect(lambda t: self.statusBar().showMessage(t, 5000))
        e.history_changed.connect(self._update_title)
        e.history_changed.connect(self._update_undo)
        e.selection_changed.connect(self._update_sel_actions)
        e.changed.connect(self._doc_changed)
        self.move.goto_bed.connect(self.goto_bed)
        self.laser.start_requested.connect(self.start_job)
        self.layers.material_requested.connect(self.material_library)
        self.props.trace_requested.connect(self.trace_dialog)
        self.props.photo_requested.connect(self.photo_dialog)
        self.props.variables_requested.connect(self.variables_dialog)
        variables.on_change(self._vars_changed)
        self.laser.verify_requested.connect(self.verify_job)
        self.laser.frame_requested.connect(self.frame_job)
        self.laser.preview_requested.connect(self.preview_job)
        self.laser.save_requested.connect(self.save_gcode)
        self.laser.run_file_requested.connect(self.run_gcode_file)
        ctl.connection_changed.connect(self.on_connection)
        ctl.status_changed.connect(self.on_status)
        ctl.alarm_raised.connect(lambda code, t: self.show_banner(f"⚠  Allarme {code}: {t}", "alarm",
                                                                  [(tr("Sblocca"), ctl.unlock), (tr("Homing"), ctl.home)]))
        ctl.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        ctl.homed_changed.connect(self.on_homed)
        ctl.settings_ready.connect(self._auto_identify)
        ctl.check_finished.connect(self._check_done)
        ctl.job_error.connect(self._job_error)
        ctl.job_finished.connect(self._job_finished)
        # offset G54 della scheda: serve ai test (materiale, scansione) sulle schede senza G55
        ctl.status_changed.connect(lambda _st: setattr(self.profile, "wcs_offset", self.ctl.wco))
        self._update_undo()
        self._update_sel_actions()

    # ================================================================ titolo / stato documento
    def _update_title(self):
        d = self.editor.doc
        name = os.path.basename(d.path) if d.path else d.name
        self.setWindowTitle(tr("{0}{1} — FreeLaserCut {2}", '● ' if self.editor.dirty else '', name, __version__))

    def _update_undo(self):
        e = self.editor
        self.acts["undo"].setEnabled(bool(e.undo_stack))
        self.acts["redo"].setEnabled(bool(e.redo_stack))
        self.acts["undo"].setText(tr("Annulla {0}", e.undo_label()).strip())
        self.acts["redo"].setText(tr("Ripeti {0}", e.redo_label()).strip())

    def _update_sel_actions(self):
        n = len(self.editor.selection)
        for k in ("cut", "copy", "duplicate", "delete", "to_path", "break", "reverse", "offset", "flip_h", "flip_v",
                  "rot_cw", "rot_ccw", "grid_array", "circ_array", "front", "back", "lock", "unlock", "close_paths", "join"):
            self.acts[k].setEnabled(n >= 1)
        for k in ("group", "align_left", "align_right", "align_top", "align_bottom", "align_hcenter", "align_vcenter",
                  "align_center", "same_w", "same_h", "along_path"):
            self.acts[k].setEnabled(n >= 2)
        for k in ("union", "difference", "intersection", "xor"):
            self.acts[k].setEnabled(n == 2)
        for k in ("dist_h", "dist_v", "dist_hc", "dist_vc"):
            self.acts[k].setEnabled(n >= 3)
        self.acts["weld"].setEnabled(n >= 1)
        self.acts["trace"].setEnabled(n == 1 and isinstance(self.editor.selection[0], ImageShape))
        self.acts["photo"].setEnabled(n == 1 and isinstance(self.editor.selection[0], ImageShape))

    def _doc_changed(self):
        self._update_title()
        self.job = None  # il lavoro va rigenerato
        self._big_photo_ok = False
        if not (self.ctl.job_active or self.ctl.checking):
            self.canvas.clear_preview()
            self.canvas.clear_trail()  # la traccia del lavoro finito non corrisponde più al disegno

    def _tool_changed(self, name):
        if not self.editor.selection:
            self.props.rebuild()
        if name == "special":
            self.docks["props"].show()
            self.docks["props"].raise_()

    def _edit_text(self, shape):
        self.docks["props"].show()
        self.docks["props"].raise_()
        QTimer.singleShot(0, self.props.focus_text)

    def _set_snap(self, attr, on):
        setattr(self.canvas, attr, on)
        self.qs.setValue(attr, on)
        self.statusBar().showMessage((tr("Aggancio agli oggetti ") if attr == "snap_objects" else tr("Aggancio alla griglia "))
                                     + (tr("attivo") if on else tr("disattivato")) + tr("  (Alt lo sospende mentre trascini)"), 3000)

    def _toggle_light_bed(self, on):
        self.canvas.light_bed = on
        self.qs.setValue("light_bed", on)
        self.canvas.resetCachedContent()
        self.canvas.viewport().update()

    def _toggle_filled(self, on):
        self.canvas.filled_view = on
        self.canvas.sync()

    def _toggle_grid(self, on):
        self.canvas.show_grid = on
        self.canvas.viewport().update()

    def _toggle_dither(self, on):
        self.canvas.dither_preview = on
        self.canvas.sync()

    # ================================================================ file
    def _confirm_discard(self):
        if not self.editor.dirty or not self.editor.doc.shapes:
            return True
        r = QMessageBox.question(self, tr("Modifiche non salvate"), tr("Il progetto ha modifiche non salvate. Salvarle?"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def file_new(self):
        if self._confirm_discard():
            variables.from_dict(None)
            self.editor.set_document(Document())
            self._update_title()

    def file_open(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Apri progetto"), self.qs.value("last_dir", os.path.expanduser("~")),
                                                  OPEN_FILTER + ";;" + tr("Tutti i file (*)"))
        if not path:
            return
        warnings = None
        try:
            if path.lower().endswith((".lbrn2", ".lbrn")):
                from ..core import lbrn

                doc, warnings = lbrn.load(path)
            else:
                doc = Document.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Apri progetto"), tr("Impossibile aprire il file:\n{0}", exc))
            return
        self.qs.setValue("last_dir", os.path.dirname(path))
        self.editor.set_document(doc)
        self._add_recent(path)
        self._update_title()
        self.canvas.fit_bed()
        if warnings is not None:  # progetto .lbrn2/.lbrn: si salva come nuovo progetto FreeLaserCut
            n = len(doc.used_layers())
            msg = (tr("Progetto aperto: {0} oggetti, {1} livelli con le loro impostazioni (velocità convertite da mm/s a mm/min). Salvandolo diventa un progetto FreeLaserCut.", len(doc.shapes), n))
            if warnings:
                msg += tr("  Avvisi: ") + "; ".join(sorted(set(warnings)))
            self.statusBar().showMessage(msg, 15000)
            self.editor.doc.path = None
            self.editor.dirty = True
            self._update_title()

    def file_save(self):
        d = self.editor.doc
        if not d.path:
            return self.file_save_as()
        try:
            d.save(d.path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Salva"), tr("Impossibile salvare:\n{0}", exc))
            return False
        self.editor.dirty = False
        self._update_title()
        self.statusBar().showMessage(tr("Salvato: {0}", d.path), 4000)
        return True

    def file_save_as(self):
        start = os.path.join(self.qs.value("last_dir", os.path.expanduser("~")), (self.editor.doc.name or "progetto") + ".flcut")
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva progetto"), start, FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".flcut"):
            path = (path[:-5] if path.lower().endswith(".fbrn") else path) + ".flcut"
        self.qs.setValue("last_dir", os.path.dirname(path))
        self.editor.doc.path = path
        self.editor.doc.name = os.path.splitext(os.path.basename(path))[0]
        ok = self.file_save()
        if ok:
            self._add_recent(path)
        return ok

    def _add_recent(self, path):
        rec = [p for p in (self.qs.value("recent", []) or []) if p != path]
        rec.insert(0, path)
        self.qs.setValue("recent", rec[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        self.m_recent.clear()
        rec = self.qs.value("recent", []) or []
        if isinstance(rec, str):
            rec = [rec]
        for p in rec:
            if os.path.exists(p):
                a = self.m_recent.addAction(os.path.basename(p))
                a.setToolTip(p)
                a.triggered.connect(lambda _=False, p=p: self.file_open(p))
        self.m_recent.setEnabled(bool(self.m_recent.actions()))

    def file_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Importa"), self.qs.value("import_dir", os.path.expanduser("~")),
                                                IMPORT_FILTER)
        if paths:
            self.qs.setValue("import_dir", os.path.dirname(paths[0]))
            self.import_files(paths)

    def import_files(self, paths, at=None):
        doc = self.editor.doc
        added = []
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in (".flcut", ".fbrn"):
                self.file_open(p)
                return
            if ext in (".lbrn2", ".lbrn"):
                if not doc.shapes:
                    self.file_open(p)
                    return
                from ..core import lbrn

                try:
                    shapes = lbrn.import_shapes(p, doc)
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.warning(self, tr("Importa"), tr("Non riesco a importare {0}:\n{1}", os.path.basename(p), exc))
                    continue
                self.editor.add(shapes, tr("Importa progetto .lbrn2"))  # posizioni originali, come nel progetto
                continue
            if ext in (".gcode", ".nc", ".gc", ".ngc"):
                self.run_gcode_file(p)
                return
            try:
                shapes = io_formats.import_file(p, doc, max_size=(self.profile.bed_x * 0.8, self.profile.bed_y * 0.8),
                                                photo_mm=io_formats.PHOTO_MM)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, tr("Importa"), tr("Non riesco a importare {0}:\n{1}", os.path.basename(p), exc))
                continue
            added += shapes
        if not added:
            return
        b = ops.union_bounds(added)
        target = at if at is not None else QPointF(self.profile.bed_x / 2, self.profile.bed_y / 2)
        from PySide6.QtGui import QTransform

        ops.transform_all(added, QTransform.fromTranslate(target.x() - b.center().x(), target.y() - b.center().y()))
        self.editor.add(added, tr("Importa"))
        for s in added:
            for leaf, _ in s.leaves():
                if isinstance(leaf, ImageShape):
                    doc.layer(leaf.layer).mode = "image"
        self.statusBar().showMessage(tr("Importati {0} oggetti", len(added)), 4000)

    def file_export(self):
        shapes = self.editor.selection or self.editor.doc.shapes
        if not shapes:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Esporta SVG"), os.path.join(self.qs.value("last_dir", os.path.expanduser("~")),
                                                                            "disegno.svg"), tr("SVG (*.svg)"))
        if path:
            io_formats.export_svg(shapes, self.editor.doc, path)
            self.statusBar().showMessage(tr("Esportato: {0}", path), 4000)

    def autosave(self):
        if not self.editor.dirty or not self.editor.doc.shapes:
            return
        try:
            d = self.editor.doc
            path0, name0 = d.path, d.name
            d.save(os.path.join(config_dir(), "autosave.flcut"))
            d.path, d.name = path0, name0
            self.qs.setValue("autosave_pending", True)
        except Exception:  # noqa: BLE001
            pass

    def _offer_recovery(self):
        p = os.path.join(config_dir(), "autosave.flcut")
        if self.qs.value("autosave_pending", False) in (True, "true") and os.path.exists(p):
            r = QMessageBox.question(self, tr("Ripristino"), tr("FreeLaserCut non è stato chiuso correttamente l'ultima volta.\n"
                                     "Vuoi recuperare il progetto salvato in automatico?"))
            self.qs.setValue("autosave_pending", False)
            if r == QMessageBox.Yes:
                doc = Document.load(p)
                doc.path = None
                doc.name = tr("Progetto recuperato")
                self.editor.set_document(doc)
                self.editor.dirty = True
                self._update_title()

    # ================================================================ dialoghi di modifica
    def offset_dialog(self):
        if not self.editor.selection:
            return
        dlg = OffsetDialog(self)
        if dlg.exec() == QDialog.Accepted:
            d, direction, corner, keep, outer = dlg.values()
            self.editor.offset(d, direction, corner, keep, outer)

    def grid_array_dialog(self):
        if not self.editor.selection:
            return
        b = self.editor.selection_bounds()
        dlg = GridArrayDialog((b.width(), b.height()), self)
        if dlg.exec() == QDialog.Accepted:
            cols, rows, dx, dy, mode, shift, mirror, group = dlg.values()
            self.editor.grid_array(cols, rows, dx, dy, mode, shift, mirror, group)

    def circ_array_dialog(self):
        if not self.editor.selection:
            return
        b = self.editor.selection_bounds()
        dlg = CircularArrayDialog((b.center().x(), b.top() - 30), self)
        if dlg.exec() == QDialog.Accepted:
            count, center, start, end, rot, group = dlg.values()
            self.editor.circular_array(count, center, start, end, rot, group)

    def common_lines_cmd(self, *_):
        """Le linee di taglio sovrapposte fra pezzi a contatto (es. serie a griglia con distanza 0) diventano una."""
        from ..core import geom, nesting
        from ..core.document import ImageShape, PathShape, TextShape

        doc = self.editor.doc
        line_layers = {cs.index for cs in doc.used_layers() if cs.mode == "line"}
        sel = [s for s in self.editor.editable() if not isinstance(s, (TextShape, ImageShape)) and s.layer in line_layers]
        if len(sel) < 2:
            QMessageBox.information(self, tr("Linee di taglio comuni"), tr("Seleziona almeno due forme a contatto su un "
                                    "livello in modalità Linea (per esempio una serie a griglia con distanza 0)."))
            return 0.0
        total = {"saved": 0.0}
        new_shapes = []

        def do():
            for layer in sorted({s.layer for s in sel}):
                cut = [s for s in sel if s.layer == layer]
                merged, saved = nesting.merge_common_lines([p for s in cut for p in geom.flatten(s.path(), 0.01)])
                if saved <= 0.01:
                    continue
                total["saved"] += saved
                doc.remove(cut)
                ps = PathShape(geom.polys_to_path(merged), layer=layer)
                doc.add(ps)
                new_shapes.append(ps)
            self.editor.selection = list(new_shapes)
        self.editor.run(tr("Unisci le linee di taglio comuni"), do)
        self.editor.selection_changed.emit()
        if total["saved"] > 0.01:
            self.statusBar().showMessage(tr("Linee comuni unite: {0:.0f} mm di taglio in meno", total["saved"]), 8000)
        else:
            self.statusBar().showMessage(tr("Nessun lato in comune fra le forme selezionate"), 6000)
        return total["saved"]

    def nest_dialog(self):
        from .dialogs_nest import NestDialog

        NestDialog(self).exec()

    def along_path_dialog(self):
        n, ok = QInputDialog.getInt(self, tr("Copia lungo un tracciato"), tr("Numero di copie:"), 10, 1, 1000)
        if ok:
            self.editor.copy_along_path(n, True)

    def _free_layers(self, n):
        """n livelli colorati liberi (nessuna forma sopra), dal più basso."""
        used = {cs.index for cs in self.editor.doc.used_layers()}
        free = [i for i in range(1, 30) if i not in used]
        return free[:n]

    def _unmirror_photo(self, img):
        """Foto con uno specchio nella trasformazione (es. da un progetto .lbrn2 aperto con una versione precedente):
        sposta lo specchio nei pixel, così «Prepara foto» la mostra come appare sul piano. Sul piano non cambia nulla."""
        import uuid

        from ..core.document import bake_mirror

        doc = self.editor.doc
        if img.source_id or img.tf.determinant() >= 0 or doc.images.get(img.image_id) is None:
            return
        pix, tf = bake_mirror(doc.images[img.image_id], img.w, img.h, img.tf)
        nid = uuid.uuid4().hex[:12]

        def do():
            doc.images[nid] = pix
            img.image_id = nid
            img.set_transform(tf)
            img.invalidate()

        self.editor.run(tr("Raddrizza la foto"), do)

    def photo_dialog(self):
        """«Prepara foto»: elaborazione della foto, oppure conversione in linee e riempimenti, oppure prova foto."""
        import math
        import uuid

        from ..core import photo as photomod
        from ..core.document import DITHER_LABELS, PathShape
        from .dialogs_photo import PhotoDialog

        sel = self.editor.selection
        if len(sel) != 1 or not isinstance(sel[0], ImageShape):
            self.statusBar().showMessage(tr("Seleziona una foto (immagine) da preparare"), 4000)
            return
        img, doc = sel[0], self.editor.doc
        self._unmirror_photo(img)
        src_id = img.source_id or img.image_id
        original = doc.images.get(src_id)
        if original is None:
            return
        t = img.tf
        sx = math.hypot(t.m11(), t.m12()) or 1.0
        sy = math.hypot(t.m21(), t.m22()) or 1.0
        cs = doc.layer(img.layer)
        dlg = PhotoDialog(img, original, cs, (img.w * sx, img.h * sy), self)
        if dlg.exec() != QDialog.Accepted:
            return
        st, adj, lay, mode = dlg.settings(), dlg.adjust(), dlg.layer_values(), dlg.mode()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            proc = original if st.is_identity() else photomod.process(original, st)
            w_mm, h_mm = dlg.target_size(proc)
            center = t.map(QPointF(img.w / 2, img.h / 2))
            # orientamento della foto sul piano senza la scala (per mettere i nuovi oggetti al suo posto)
            rot = QTransform(t.m11() / sx, t.m12() / sx, t.m21() / sy, t.m22() / sy, 0, 0)

            def place(w, h, cx=center.x(), cy=center.y()):
                return QTransform.fromTranslate(-w / 2, -h / 2) * rot * QTransform.fromTranslate(cx, cy)

            if mode == "image":
                new_id = src_id if st.is_identity() else uuid.uuid4().hex[:12]
                doc.images[new_id] = proc if new_id != src_id else original

                def do():
                    img.image_id = new_id
                    img.source_id = None if new_id == src_id else src_id
                    img.photo = None if st.is_identity() else st.to_dict()
                    img.brightness, img.contrast, img.gamma = adj["brightness"], adj["contrast"], adj["gamma"]
                    img.w, img.h = w_mm / sx, h_mm / sy
                    img.invalidate()
                    c2 = img.tf.map(QPointF(img.w / 2, img.h / 2))
                    img.set_transform(img.tf * QTransform.fromTranslate(center.x() - c2.x(), center.y() - c2.y()))
                    c = doc.layer(img.layer)
                    c.mode = "image"
                    c.dither, c.dpi, c.negative = lay["dither"], lay["dpi"], lay["negative"]
                self.editor.run(tr("Prepara foto"), do)
                self.editor.select([img])
                self.statusBar().showMessage(tr("Foto preparata: {0:.1f} × {1:.1f} mm, {2}", w_mm, h_mm,
                                                DITHER_LABELS[lay["dither"]]), 6000)
            elif mode == "vector":
                p = dlg.vector_params()
                r = photomod.to_vectors(proc, w_mm, h_mm, tones=p["tones"], detail=p["detail"], smooth=p["smooth"],
                                        outlines=p["outlines"], edges=p["edges"], min_size_mm=p["min_size_mm"], **adj)
                parts = [("fill", path, dark) for path, dark in r["fills"]]
                if r["outline"] is not None:
                    parts.append(("outline", r["outline"], 1.0))
                if r["edges"] is not None:
                    parts.append(("edges", r["edges"], 1.0))
                if not parts:
                    self.statusBar().showMessage(tr("Nessuna forma trovata: prova a cambiare dettaglio o contrasto"), 5000)
                    return
                free = self._free_layers(len(parts))
                if len(free) < len(parts):
                    QMessageBox.warning(self, tr("Prepara foto"), tr("Servono {0} livelli liberi: liberane qualcuno e riprova.",
                                                                     len(parts)))
                    return
                tf = place(w_mm, h_mm)
                n_fill = len(r["fills"])
                shapes = []
                self.editor.begin(tr("Foto in linee e riempimenti"))
                for k, ((kind, path, dark), li) in enumerate(zip(parts, free)):
                    c = doc.layer(li)
                    if kind == "fill":
                        c.mode = "fill"
                        c.speed = cs.speed
                        c.power_max = round(max(cs.power_max, 1.0) * (0.4 + 0.6 * (k + 1) / max(n_fill, 1)), 1)
                        c.name = tr("Foto tono {0}", k + 1)
                    else:
                        c.mode = "line"
                        c.name = tr("Foto contorno") if kind == "outline" else tr("Foto dettagli")
                    ps = PathShape(path, li)
                    ps.set_transform(tf)
                    shapes.append(ps)
                if p["keep"]:
                    self.editor.add(shapes, tr("Foto in linee e riempimenti"))
                else:
                    self.editor.replace([img], shapes, tr("Foto in linee e riempimenti"))
                self.editor.commit()
                self.statusBar().showMessage(tr("Creati {0} oggetti su {0} livelli: controlla velocità e potenza dei livelli "
                                                "nuovi prima di incidere", len(shapes)), 8000)
            else:  # prova foto: 4 metodi a confronto sulla zona centrale
                methods = [lay["dither"]] + [m for m in ("jarvis", "stucki", "floyd", "grayscale", "halftone")
                                             if m != lay["dither"]]
                methods = methods[:4]
                free = self._free_layers(len(methods))
                if len(free) < len(methods):
                    QMessageBox.warning(self, tr("Prepara foto"), tr("Servono {0} livelli liberi: liberane qualcuno e riprova.",
                                                                     len(methods)))
                    return
                side = min(30.0, w_mm, h_mm)
                ppm = proc.width / max(w_mm, 1e-6)
                half = side * ppm / 2
                cx, cy = proc.width / 2, proc.height / 2
                tile = proc.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
                tid = uuid.uuid4().hex[:12]
                doc.images[tid] = tile
                b = img.bounds()
                x0, y0 = b.right() + 10.0, b.bottom() - side
                if x0 + 4 * (side + 5) > self.profile.bed_x:  # a destra non ci sta: sotto la foto
                    x0, y0 = b.left(), b.top() - side - 10.0
                tiles = []
                self.editor.begin(tr("Prova foto"))
                for k, (m, li) in enumerate(zip(methods, free)):
                    c = doc.layer(li)
                    for f_ in ("speed", "power_max", "power_min", "passes", "air", "dpi", "negative", "dot_correction",
                               "halftone_cell", "halftone_angle", "bidirectional", "overscan", "image_start"):
                        setattr(c, f_, getattr(cs, f_))
                    c.mode, c.dither, c.dpi, c.negative = "image", m, lay["dpi"], lay["negative"]
                    c.name = DITHER_LABELS[m]
                    s = ImageShape(tid, side, side, layer=li)
                    s.brightness, s.contrast, s.gamma = adj["brightness"], adj["contrast"], adj["gamma"]
                    s.set_transform(QTransform.fromTranslate(x0 + k * (side + 5.0), y0))
                    tiles.append(s)
                self.editor.add(tiles, tr("Prova foto"))
                self.editor.commit()
                self.statusBar().showMessage(tr("Prova foto: da sinistra {0}. Incidila e scegli il metodo migliore.",
                                                ", ".join(DITHER_LABELS[m] for m in methods)), 10000)
        finally:
            QApplication.restoreOverrideCursor()

    def trace_dialog(self):
        sel = self.editor.selection
        if len(sel) != 1 or not isinstance(sel[0], ImageShape):
            self.statusBar().showMessage(tr("Seleziona un'immagine da vettorizzare"), 4000)
            return
        img = sel[0]
        pil = self.editor.doc.images.get(img.image_id)
        if pil is None:
            return
        from .dialogs_trace import TraceDialog
        from ..core.document import PathShape

        cur = self.layers._current_cs()
        dlg = TraceDialog(img, pil, cur.index if cur is not None and cur.mode != "image" else 1, self)
        if dlg.exec() != QDialog.Accepted:
            return
        path, layer, keep = dlg.values()
        if path is None or path.isEmpty():
            self.statusBar().showMessage(tr("Nessun tracciato trovato: prova a cambiare la soglia"), 5000)
            return
        ps = PathShape(path, layer)
        ps.set_transform(img.tf)
        if keep:
            self.editor.add(ps, tr("Vettorizza immagine"))
        else:
            self.editor.replace([img], [ps], "Vettorizza immagine")

    def exact_shape_dialog(self, *_):
        from .dialogs_shapes import ExactShapeDialog

        head = self.canvas.head_pos()
        c = (head.x(), head.y()) if head is not None else (self.profile.bed_x / 2, self.profile.bed_y / 2)
        dlg = ExactShapeDialog(c, self.editor.current_layer, self)
        if dlg.exec() == QDialog.Accepted:
            s = dlg.shape()
            self.editor.add([s], f"Crea {s.describe().lower()}")

    def _fill_layer(self):
        """Livello adatto ai codici (riempimento): quello attuale se va bene, altrimenti uno già in riempimento,
        altrimenti il primo colore libero (che verrà messo in riempimento). -> (indice, da_impostare)"""
        doc, cur = self.editor.doc, self.editor.current_layer
        if cur != 30 and doc.layer(cur).mode in ("fill", "offset_fill"):
            return cur, False
        for cs in doc.used_layers():
            if cs.index != 30 and cs.mode == "fill" and cs.output:
                return cs.index, False
        used = {cs.index for cs in doc.used_layers()}
        for i in range(1, 30):
            if i not in used:
                return i, True
        return cur, False

    def code_dialog(self, *_):
        from ..core.document import CodeShape
        from .dialogs_code import CodeDialog

        sel = self.editor.selection
        shape = sel[0] if len(sel) == 1 and isinstance(sel[0], CodeShape) else None
        dlg = CodeDialog(self, shape)
        if dlg.exec() != QDialog.Accepted:
            return None
        v = dlg.values()
        if shape is not None:
            c = shape.bounds().center()
            self.editor.modify(shape, tr("Modifica codice"), **v)
            return shape
        idx, set_fill = self._fill_layer()
        if set_fill:
            self.editor.run(tr("Livello in riempimento"), lambda: setattr(self.editor.doc.layer(idx), "mode", "fill"))
        s = CodeShape(layer=idx, **v)
        b = s.bounds()
        vp = self.canvas.viewport().rect().center()
        c = self.canvas.to_bed(QPointF(vp))
        if not (0 <= c.x() <= self.profile.bed_x and 0 <= c.y() <= self.profile.bed_y):
            c = QPointF(self.profile.bed_x / 2, self.profile.bed_y / 2)
        s.apply(QTransform.fromTranslate(c.x() - b.center().x(), c.y() - b.center().y()))
        self.editor.add([s], tr("Crea codice"))
        return s

    def puzzle_dialog(self, *_):
        from .dialogs_puzzle import run_puzzle

        return run_puzzle(self)

    def text_path_dialog(self, *_):
        from .dialogs_textpath import run_text_path

        return run_text_path(self)

    def close_paths_dialog(self):
        tol, ok = QInputDialog.getDouble(self, tr("Chiudi tracciati"), tr("Chiudi se gli estremi distano al massimo (mm):"), 0.5, 0.01, 50, 2)
        if ok:
            self.editor.close_paths(tol)

    # ================================================================ connessione
    def refresh_ports(self):
        last = self.qs.value("port", "")
        self.port_combo.clear()
        best = None
        from .. import machines

        from .. import netport

        ports = [(p.device, p.label(), p.likely) for p in machines.describe_ports()]
        ports += [(p, netport.label(p), False) for p in netport.saved(self.qs)]  # laser in Wi-Fi già usati
        ports.append((SIM_PORT, tr("Simulatore (senza macchina)"), False))
        for dev, label, likely in ports:
            self.port_combo.addItem(("★  " if likely else "") + label, dev)
            if dev == last:
                best = self.port_combo.count() - 1
            elif likely and best is None:
                best = self.port_combo.count() - 1
        if best is not None:
            self.port_combo.setCurrentIndex(best)

    def board_backup_dialog(self, *_):
        from .dialogs_backup import BoardBackupDialog

        dlg = BoardBackupDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        return dlg

    def net_dialog(self, *_):
        """Laser via Wi-Fi: indirizzo della scheda, prova del collegamento, indirizzi ricordati."""
        from .dialogs_net import NetDialog

        dlg = NetDialog(self.qs, self)
        if dlg.exec() and dlg.port:
            self.refresh_ports()
            i = self.port_combo.findData(dlg.port)
            if i >= 0:
                self.port_combo.setCurrentIndex(i)
            return dlg.port
        return None

    def _auto_connect(self):
        """All'avvio si collega da solo alla porta usata l'ultima volta (se c'è ancora)."""
        if self.ctl.connected:
            return
        last = self.qs.value("port", "")
        if last and self.port_combo.findData(last) >= 0 and last != SIM_PORT:
            self.port_combo.setCurrentIndex(self.port_combo.findData(last))
            self.statusBar().showMessage(tr("Mi collego al laser su {0}…", last), 4000)
            self.toggle_connection(quiet=True)

    def toggle_connection(self, quiet=False):
        if self.ctl.connected:
            if self.ctl.job_active:
                if QMessageBox.question(self, tr("Lavoro in corso"), tr("C'è un lavoro in corso. Fermarlo e disconnettere?")) != QMessageBox.Yes:
                    return
                self.ctl.stop_job()
            self.ctl.disconnect_port()
            return
        port = self.port_combo.currentData()
        if not port:
            return
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText(tr("Connessione…"))
        QApplication.processEvents()
        self._quiet_connect = quiet
        if self.ctl.connect_port(port, self.profile.baud):
            self.qs.setValue("port", port)
        self.btn_connect.setEnabled(True)

    def on_connection(self, ok, msg):
        if not ok and self.ctl.job_active is False and self.ctl.job_lines and 0 < self.ctl.job_acked < len(self.ctl.job_lines):
            self._interrupted = (list(self.ctl.job_lines), self.ctl.job_acked)
        self.btn_connect.setText(tr("Disconnetti") if ok else tr("Connetti"))
        self.btn_connect.setObjectName("danger" if ok else "primary")
        self.btn_connect.setIcon(style.icon("disconnect" if ok else "connect", "#FFFFFF"))
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self.port_combo.setEnabled(not ok)
        self.btn_refresh.setEnabled(not ok)
        self.btn_wifi.setEnabled(not ok)
        self.laser.set_connected(ok)
        self.move.set_connected(ok)
        self.machine.set_connected(ok)
        self.machine.refresh_profile()
        self.console.set_connected(ok)
        self.camera.update_state()
        for k in ("home", "unlock_m", "frame", "verify", "start", "pause", "stop"):
            self.acts[k].setEnabled(ok)
        if not ok:
            self.set_pill("Disconnesso")
            self.canvas.hide_head()
            self.lbl_head.setText("")
            self.lbl_fs.setText("")
            if msg and msg.startswith(("Impossibile", "Connessione persa", "Errore")) and not getattr(self, "_quiet_connect", False):
                QMessageBox.warning(self, tr("Connessione"), msg + tr("\n\nControlla il cavo USB, che la macchina sia accesa "
                                    "e che nessun altro programma usi la porta."))
        else:
            self._quiet_connect = False
            self.set_pill("Idle")
            self.statusBar().showMessage(msg, 4000)
            QTimer.singleShot(2500, self._after_connect)

    def _after_connect(self):
        if not self.ctl.connected:
            return
        if self._interrupted:
            lines, at = self._interrupted
            self.show_banner(tr("Un lavoro si è interrotto alla riga {0} di {1}. Fai l'homing, poi puoi riprenderlo da dove si era fermato.", at, len(lines)), "warn", [(tr("Homing"), self.ctl.home), (tr("Riprendi"), self.resume_job),
                                                                 (tr("Scarta"), self._drop_interrupted)])
        elif not self.ctl.homed and not self.banner.isVisible():
            if not self.profile.homing:
                # senza finecorsa lo 0 è dove sta la testa all'accensione: lo ricordo, con l'angolo giusto
                self.show_banner(tr("Questa macchina non ha l'homing: conta le posizioni da dove si trova la testa quando "
                                    "la accendi. Prima di accenderla porta la testa nell'angolo dello 0 ({0}).",
                                    corner_name(self.profile.corner_now())), "info",
                                 [(tr("Configurazione guidata"), self.setup_wizard), (tr("Ok"), self.banner.hide)], hint=True)
            else:
                self.show_banner(tr("Fai l'homing: così testa, piano di lavoro e camera usano le stesse coordinate."), "info",
                                 [(tr("Homing"), self.ctl.home)], hint=True)

    def set_pill(self, state):
        if state == getattr(self, "_pill_state", None):  # lo stato arriva più volte al secondo: niente da rifare
            return
        self._pill_state = state
        color = STATE_COLORS.get(state, "#4E5C7A")
        text = STATE_IT.get(state, state)
        self.pill.setText(text)
        self.pill.setStyleSheet(f"background:{color}; border-radius:9px; padding:1px 8px; font-weight:600; font-size:8pt; color:white;")
        self.pill.ensurePolished()
        # larghezza dal testo, non da sizeHint(): sizeHint() tiene conto della larghezza minima già impostata
        # e a ogni stato la pastiglia (con tutto il pannello Laser) si allargava di qualche pixel
        self.pill.setMinimumWidth(max(64, self.pill.fontMetrics().horizontalAdvance(text) + 24))
        if hasattr(self, "sb_machine"):
            self.sb_machine.setText(("●  " + STATE_IT.get(state, state)) if state != "Disconnesso" else tr("○  Laser non connesso"))
            self.sb_machine.setStyleSheet(f"color:{color if state != 'Disconnesso' else C['muted']}; font-weight:600;")

    def on_status(self, st):
        state = st.get("state", "")
        self.set_pill(state)
        m = st.get("MPos", [0, 0, 0])
        w = st.get("WPos", [0, 0, 0])
        bx, by = self.profile.to_bed(m[0], m[1])
        self.canvas.set_head(bx, by, state, st.get("power", 0))
        ah = getattr(self, "_anchor_head", None)
        if ah is not None and state == "Idle" and abs(ah[0] - bx) + abs(ah[1] - by) > 0.05 and \
                not (self.ctl.job_active or self.ctl.checking) and self.job_preview is not None:
            # partenza dalla testa: il lavoro segue la testa. Sposto anteprima e rombo (niente da ricalcolare:
            # all'avvio il lavoro si rifà comunque dalla posizione vera)
            dx, dy = bx - ah[0], by - ah[1]
            ox, oy = self.job_preview_off or (0.0, 0.0)
            self.job_preview_off = (ox + dx, oy + dy)
            self.canvas.set_preview_offset(self.job_preview_off)
            self._anchor_head = (bx, by)
            self.canvas.set_anchor_marker(bx, by, tr("partenza: sulla testa"))
        self.lbl_head.setText(tr("testa {0:7.2f}, {1:7.2f}  ·  lavoro {2:.2f}, {3:.2f}", bx, by, w[0], w[1]))
        pw = st.get("power", 0) / max(self.profile.s_max, 1) * 100
        self.lbl_fs.setText(tr("F {0} · potenza {1:.0f}%", units.fmt(st.get('feed', 0) or 0), pw))
        if state == "Alarm" and (not self.banner.isVisible() or self._banner_kind == "info") and not self._alarm_dismissed:
            self.show_banner(tr("⚠  La macchina è bloccata (allarme): fai l'homing oppure sblocca."), "alarm",
                             [(tr("Sblocca"), self.ctl.unlock), (tr("Homing"), self.ctl.home)])
        elif state != "Alarm":
            self._alarm_dismissed = False
            if self._banner_kind == "alarm" and self.banner.isVisible() and state in ("Idle", "Run", "Jog"):
                self.banner.hide()

    def on_homed(self, homed, negative):
        if homed:
            p = self.profile
            if p.negative_space != negative:
                p.negative_space = negative
                # angolo dello 0 detto nella configurazione guidata: ora che so se le coordinate sono negative,
                # ricalcolo il verso degli assi NON provati con le frecce (quelli provati restano)
                if p.recompute_untested_axes():
                    self._sync_axes()
                try:
                    p.save()
                except OSError:
                    pass
            if self._banner_kind == "info":
                self.banner.hide()
            self.machine.refresh_profile()
            self.statusBar().showMessage(tr("Homing completato: piano e macchina allineati"), 5000)
        self.camera.update_state()

    def _load_active_profile(self):
        """Il profilo scelto l'ultima volta (Riconosci la macchina), altrimenti il Longer B1 40W."""
        path = self.qs.value("profile_path", "")
        if path and os.path.exists(path):
            try:
                return MachineProfile.load(path)
            except (OSError, ValueError, TypeError):
                pass
        return MachineProfile.load_default()

    def set_active_profile(self, p):
        self.qs.setValue("profile_path", p.path())
        self.on_profile(p)
        self.machine.profile = p
        self.machine.refresh_profile()
        self.statusBar().showMessage(tr("Profilo macchina: {0}", p.name), 5000)

    def identify_machine(self, *_):
        from .dialogs_machine import MachineWizard

        MachineWizard(self).exec()

    def _auto_identify(self, settings):
        """Dopo ogni lettura di $$: se la scheda collegata non corrisponde al profilo attivo, lo dice e propone
        il riconoscimento (una sola volta per firmware)."""
        from .. import machines

        port = next((p for p in machines.describe_ports() if p.device == self.ctl.port), None)
        ident = machines.identify((), self.machine.info, settings, port, self.profile.baud)
        if not ident.vendor and not ident.family:
            return
        same = (ident.model and ident.model == self.profile.model) or (
            ident.vendor and ident.vendor.lower() in self.profile.name.lower())
        bx, by = ident.bed
        size_ok = not (bx and by) or (abs(bx - self.profile.bed_x) < 5 and abs(by - self.profile.bed_y) < 5)
        if same and size_ok:
            return
        tag = f"{ident.vendor_fw}|{ident.version}|{bx:g}x{by:g}"
        if self.qs.value("ident_dismissed", "") == tag or self.banner.isVisible():
            return
        self.show_banner(tr("Collegata: {0} ({1}). Il profilo attivo è «{2}».", ident.name(), ident.summary(), self.profile.name),
                         "info", [(tr("Riconosci e adatta"), self.identify_machine),
                                  (tr("Ignora"), lambda: (self.qs.setValue("ident_dismissed", tag), self.banner.hide()))])

    def on_profile(self, p):
        self.profile = p
        self.laser.s_max = p.s_max
        self._sync_axes()
        if (self.canvas.bed_x, self.canvas.bed_y) != (p.bed_x, p.bed_y):
            self.canvas.set_bed(p.bed_x, p.bed_y)

    def _placement_changed(self):
        """Partenza o punto di riferimento cambiati: rifà l'anteprima, così sul piano si vede dove inciderà."""
        if self.ctl.job_active or self.ctl.checking or getattr(self, "_job_is_external", False):
            return
        if not self.editor.doc.shapes:
            return
        mode = self.laser.start_from.currentData()
        if mode == "current" and self.canvas.head_pos() is None:
            self.statusBar().showMessage(tr("Partenza dalla posizione della testa: connetti la macchina per vedere "
                                            "dove inciderà"), 5000)
            return
        if self._photo_dots() > BIG_PHOTO_DOTS and not getattr(self, "_big_photo_ok", False):
            return  # foto enorme: l'anteprima la chiede la persona (Anteprima), non la faccio da sola
        self.build_job()
        names = [tr("in basso a sinistra"), tr("in basso al centro"), tr("in basso a destra"), tr("al centro a sinistra"),
                 tr("al centro"), tr("al centro a destra"), tr("in alto a sinistra"), tr("in alto al centro"),
                 tr("in alto a destra")]
        if mode != "absolute":
            where = tr("sulla testa") if mode == "current" else tr("sull'origine utente")
            self.statusBar().showMessage(tr("Il punto {0} del lavoro va {1}: l'anteprima mostra dove inciderà",
                                            names[self.laser.anchor.value], where), 6000)

    def _sync_axes(self):
        """Spunte «Inverti l'asse X/Y» del pannello Laser ↔ profilo della macchina, e verso dei jog."""
        p = self.profile
        self.ctl.axis_sign = p.axis_sign()
        lp = getattr(self, "laser", None)
        if lp is None or not hasattr(lp, "inv_x"):
            return
        for w, val in ((lp.inv_x, p.invert_x), (lp.inv_y, p.invert_y)):
            w.blockSignals(True)
            w.setChecked(bool(val))
            w.blockSignals(False)

    def set_axis_inverted(self, axis, on):
        """Spunta «Inverti l'asse»: si salva nel profilo della macchina e rifà l'anteprima del lavoro."""
        if self.ctl.job_active or self.ctl.checking:
            self._sync_axes()
            return
        setattr(self.profile, "invert_x" if axis == "x" else "invert_y", bool(on))
        # scelta a mano: quell'asse è deciso, l'homing non lo ricalcola più
        if axis == "x":
            self.profile.tested_x = True
        else:
            self.profile.tested_y = True
        self.profile.axes_tested = self.profile.tested_x and self.profile.tested_y
        try:
            self.profile.save()
        except OSError:
            pass
        self._sync_axes()
        self.statusBar().showMessage(tr("Asse {0} {1}: vale da subito per jog, posizione della testa e lavori",
                                        axis.upper(), tr("invertito") if on else tr("normale")), 6000)
        if self.job is not None and not getattr(self, "_job_is_external", False):
            self.build_job()

    def work_origin_on_bed(self):
        wx, wy = self.ctl.wco
        return self.profile.to_bed(wx, wy)

    def design_bounds(self):
        """Ingombro del disegno che verrà inciso (solo la selezione se «Solo gli oggetti selezionati»)."""
        from .editor import TOOL_LAYER

        if self.laser.only_sel.isChecked() and self.editor.selection:
            shapes = list(self.editor.selection)
        else:
            shapes = list(self.editor.doc.shapes)
        shapes = [s for s in shapes if not s.hidden and getattr(s, "layer", 0) != TOOL_LAYER
                  and self.editor.doc.layer(s.layer).output]
        return self.editor.doc.bounds(shapes) if shapes else None

    def goto_anchor(self, *_):
        """Porta la testa (laser spento) sul punto del disegno scelto con i 9 pallini, com'è disegnato sul piano."""
        b = self.design_bounds()
        if b is None or b.isNull():
            self.statusBar().showMessage(tr("Non c'è niente da incidere: disegna o importa qualcosa"), 5000)
            return None
        names = [tr("in basso a sinistra"), tr("in basso al centro"), tr("in basso a destra"), tr("al centro a sinistra"),
                 tr("al centro"), tr("al centro a destra"), tr("in alto a sinistra"), tr("in alto al centro"),
                 tr("in alto a destra")]
        a = self.laser.anchor.value
        if self.laser.start_from.currentData() == "origin":
            # con «Origine utente» il punto scelto del lavoro cade sull'origine, non dove il disegno è disegnato:
            # la testa va lì, dove inciderà davvero (lo stesso posto del rombo magenta)
            ox, oy = self.work_origin_on_bed()
            x = min(max(ox, 0.0), self.profile.bed_x)
            y = min(max(oy, 0.0), self.profile.bed_y)
            if not self.ctl.connected:
                self.statusBar().showMessage(tr("Connetti la macchina per muovere la testa"), 3000)
                return (x, y)
            self.goto_bed(x, y)
            self.statusBar().showMessage(tr("La testa va sull'origine utente: lì cade il punto {0} del lavoro "
                                            "({1:.1f}, {2:.1f} mm)", names[a], x, y), 8000)
            return (x, y)
        p = geom.rect_anchor(b, a)
        x = min(max(p.x(), 0.0), self.profile.bed_x)
        y = min(max(p.y(), 0.0), self.profile.bed_y)
        if not self.ctl.connected:
            self.statusBar().showMessage(tr("Connetti la macchina per muovere la testa"), 3000)
            return (x, y)
        self.goto_bed(x, y)
        msg = tr("La testa va sul punto {0} del disegno ({1:.1f}, {2:.1f} mm)", names[a], x, y)
        if (x, y) != (p.x(), p.y()):
            msg += " · " + tr("il punto era fuori dal piano: mi fermo al bordo")
        self.statusBar().showMessage(msg, 8000)
        return (x, y)

    def goto_bed(self, x, y):
        if not self.ctl.connected:
            self.statusBar().showMessage(tr("Connetti la macchina per muovere la testa"), 3000)
            return
        if self.ctl.job_active or self.ctl.checking:
            return
        x = min(max(x, 0.0), self.profile.bed_x)
        y = min(max(y, 0.0), self.profile.bed_y)
        mx, my = self.profile.to_machine(x, y)
        self.ctl.goto_machine(mx, my, max(self.move.feed.value(), 3000))

    def head_to_selection(self, anchor):
        b = self.editor.selection_bounds()
        if b.isNull():
            return
        p = geom.rect_anchor(b, anchor)
        self.goto_bed(p.x(), p.y())

    # ================================================================ lavoro
    def job_options(self):
        lp = self.laser
        mode = lp.start_from.currentData()
        head = self.canvas.head_pos()
        opts = gcode.JobOptions(start_from=mode, anchor=lp.anchor.value,
                                current_pos=(head.x(), head.y()) if head is not None else (0.0, 0.0),
                                work_origin=self.work_origin_on_bed(), laser_cmd="M4",
                                no_g55=bool(getattr(self.profile, "no_g55", False)), g54_offset=self.ctl.wco,
                                finish="origin" if lp.finish_origin.isChecked() else "stay",
                                optimize=lp.optimize.isChecked(), inner_first=lp.optimize.isChecked(),
                                only_ids={s.id for s in self.editor.selection} if lp.only_sel.isChecked() else None,
                                name=self.editor.doc.name, rotary=self.rotary_settings())
        return opts

    def rotary_settings(self):
        """Impostazioni del rotativo (None se spento): restano nelle preferenze, non nel progetto."""
        qs = self.qs
        if qs.value("rotary_on", "false") not in (True, "true"):
            return None
        return {"kind": qs.value("rotary_kind", "roller"), "mm_per_rev": float(qs.value("rotary_mm_rev", 100.0)),
                "roller_d": float(qs.value("rotary_roller_d", 25.0)), "object_d": float(qs.value("rotary_object_d", 70.0))}

    def rotary_dialog(self, *_):
        from .dialogs_rotary import RotaryDialog

        RotaryDialog(self).exec()
        self.update_rotary_state()

    def update_rotary_state(self):
        r = self.rotary_settings()
        if hasattr(self, "sb_rotary"):
            self.sb_rotary.setVisible(r is not None)
        a = self.acts.get("rotary")
        if a is not None:
            a.setChecked(r is not None)
        if getattr(self, "banco", None) is not None:
            self.banco.flow.refresh()

    def build_job(self, show=True):
        """Genera il G-code; se show mostra l'anteprima sul piano e il riepilogo."""
        opts = self.job_options()
        if opts.start_from == "current" and self.canvas.head_pos() is None:
            QMessageBox.information(self, tr("Posizione attuale"), tr("Per partire dalla posizione attuale la macchina deve "
                                    "essere connessa (FreeLaserCut deve sapere dov'è la testa)."))
            return None
        dots = self._photo_dots()
        if dots > BIG_PHOTO_DOTS and not getattr(self, "_big_photo_ok", False):
            r = QMessageBox.question(self, tr("Foto molto grande"), tr(
                "Le foto da incidere sono {0:.1f} milioni di punti: preparare il lavoro richiede tempo e molta memoria, "
                "e l'incisione dura ore.\n\nDi solito conviene rimpicciolire la foto o abbassare la risoluzione "
                "(punti per pollice) nel livello. Preparare comunque il lavoro?", dots / 1e6))
            if r != QMessageBox.Yes:
                return None
            self._big_photo_ok = True  # fino alla prossima modifica del disegno
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            job = gcode.generate(self.editor.doc, self.profile, opts)
            if opts.rotary:  # anteprima: il disegno com'è sul piano, non l'asse Y scalato del rotativo
                from dataclasses import replace as _dc_replace

                flat = gcode.generate(self.editor.doc, self.profile, _dc_replace(opts, rotary=None))
                pv, pv_off = flat.preview, flat.out_to_bed  # spostamento della SUA anteprima (con Y invertito cambia)
            else:
                pv = job.preview if job.preview is not None else gcode_preview.parse(job.lines, profile=self.profile)
                pv_off = job.out_to_bed
        finally:
            QApplication.restoreOverrideCursor()
        self.job, self.job_preview, self.job_preview_off = job, pv, pv_off
        if show:
            self.canvas.set_preview(pv, pv_off)
            self.laser.show_job(job, self.profile)
            self._update_anchor_marker(opts)
        return job

    def anchor_point(self, opts=None):
        """Dove finisce sul piano il punto scelto con i 9 pallini: sul disegno (assolute), sulla testa o sull'origine."""
        opts = opts or self.job_options()
        if opts.start_from == "current":
            return opts.current_pos
        if opts.start_from == "origin":
            return tuple(opts.work_origin)
        b = self.design_bounds()
        if b is None or b.isNull():
            return None
        p = geom.rect_anchor(b, self.laser.anchor.value)
        return (p.x(), p.y())

    def _update_anchor_marker(self, opts=None):
        pt = self.anchor_point(opts)
        if pt is None:
            self.canvas.set_anchor_marker(None, None)
            return
        mode = (opts or self.job_options()).start_from
        label = {"current": tr("partenza: sulla testa"), "origin": tr("partenza: origine utente")}.get(
            mode, tr("punto scelto del disegno"))
        self.canvas.set_anchor_marker(pt[0], pt[1], label)
        # partenza dalla testa: se poi la testa si sposta (frecce, «Porta la testa qui»), anteprima e rombo la seguono
        self._anchor_head = tuple(pt) if mode == "current" else None

    def _photo_dots(self):
        """Punti che il laser farà sulle foto (livelli Immagine con uscita attiva)."""
        doc = self.editor.doc
        n = 0.0
        for s in doc.shapes:
            if s.hidden:
                continue
            for leaf, tf in s.leaves():
                if not isinstance(leaf, ImageShape) or leaf.hidden:
                    continue
                cs = doc.layer(leaf.layer)
                if cs.mode != "image" or not cs.output:
                    continue
                step = 25.4 / max(cs.dpi, 10.0)
                r = tf.map(leaf.local_path()).boundingRect()
                n += (r.width() / step) * (r.height() / step)
        return n

    def preflight(self, job):
        """Controlli prima di partire. Ritorna (bloccanti, avvisi)."""
        block, warn = [], []
        st = self.ctl.last_status.get("state")
        if not self.ctl.connected:
            block.append(tr("La macchina non è connessa."))
        if st == "Alarm":
            block.append(tr("La macchina è in allarme: sblocca o fai l'homing."))
        elif st in ("Run", "Jog", "Hold", "Door", "Home") and self.ctl.connected:
            block.append(tr("La macchina non è ferma (contorno, spostamento o pausa in corso): aspetta che si fermi, poi "
                            "riprova."))
        if job is None or not job.lines or job.bounds is None:
            block.append(tr("Il lavoro è vuoto: nessuna forma su livelli con uscita attiva."))
        else:
            for w in job.warnings:
                (block if "esce dall'area" in w else warn).append(w)
            lim = self._soft_limit_problem(job)
            if lim and not any("esce dall'area" in w for w in job.warnings):
                block.append(lim)
        if job is not None and self.laser.start_from.currentData() == "absolute" and not self.ctl.homed and self.profile.homing:
            warn.append(tr("Non hai fatto l'homing in questa sessione: la posizione sul piano potrebbe non corrispondere."))
        if not self.profile.laser_mode:
            warn.append(tr("La modalità laser della scheda è disattivata ($32=0): attivala nella scheda Macchina."))
        return block, warn

    def _soft_limit_problem(self, job):
        """Con i limiti software attivi ($20=1) la scheda accetta solo la corsa $130×$131 letta da lei:
        se il lavoro ci esce, GRBL va in allarme 2. Ritorna il messaggio, oppure None."""
        lim = self.ctl.soft_limits() if self.ctl.connected else None
        if lim is None or job is None:
            return None
        tx, ty = lim
        box = None
        pv = getattr(job, "preview", None)
        segs = getattr(pv, "segs", None)
        if segs is not None and len(segs):
            ox, oy = job.out_to_bed
            xs = (float(min(segs[:, 0].min(), segs[:, 2].min())) + ox, float(max(segs[:, 0].max(), segs[:, 2].max())) + ox)
            ys = (float(min(segs[:, 1].min(), segs[:, 3].min())) + oy, float(max(segs[:, 1].max(), segs[:, 3].max())) + oy)
            box = (xs[0], ys[0], xs[1], ys[1])
        elif job.motion_bounds is not None:
            m = job.motion_bounds
            box = (m.left(), m.top(), m.right(), m.bottom())
        if box is None:
            return None
        neg = self.profile.negative_space
        if neg is None:
            neg = self.ctl.negative_space
        # angoli del lavoro (coordinate del piano) → coordinate macchina, con assi invertiti e coordinate negative
        prof = self.profile
        if prof.negative_space is None and neg is not None:
            import copy

            prof = copy.copy(prof)
            prof.negative_space = neg
        corners = [prof.to_machine(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
        y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
        lo, hi = (0.0, 0.0), (tx, ty)
        if neg:  # coordinate macchina negative: la scheda accetta -$130..0
            lo, hi = (-tx, -ty), (0.0, 0.0)
        eps = 0.01
        if x0 < lo[0] - eps or y0 < lo[1] - eps or x1 > hi[0] + eps or y1 > hi[1] + eps:
            return tr("La scheda ha i limiti software attivi ($20=1) e accetta solo {0:g} × {1:g} mm ($130/$131): "
                      "il lavoro ne esce e la macchina andrebbe in allarme. Sposta il disegno o l'origine.", tx, ty)
        return None

    def start_job(self, job=None):
        if self.ctl.job_active or self.ctl.checking:
            return
        if not isinstance(job, gcode.GcodeJob):
            self._job_is_external = False
        job = job if isinstance(job, gcode.GcodeJob) else self.build_job()
        if job is None:
            return
        block, warn = self.preflight(job)
        if block:
            QMessageBox.warning(self, tr("Non posso avviare il lavoro"), "\n".join("• " + b for b in block))
            return
        b = job.bounds
        txt = (f"<b>Tempo stimato {_hms(job.seconds)}</b> · {b.width():.1f} × {b.height():.1f} mm · {len(job.lines)} righe<br><br>"
               + ("".join(f"⚠ {w}<br>" for w in warn) + "<br>" if warn else "")
               + tr("Prima di partire:<br>• occhiali protettivi per 450 nm indossati da chi è vicino<br>"
                 "• materiale fissato e a fuoco (lente 50 mm)<br>• air assist e aspirazione fumi attivi<br>"
                 "• non lasciare la macchina incustodita"))
        box = QMessageBox(self)
        box.setWindowTitle(tr("Avvio del lavoro"))
        box.setTextFormat(Qt.RichText)
        box.setText(txt)
        verify = self.laser.verify_first.isChecked() and len(job.lines) <= 40000
        go = box.addButton(tr("Verifica e avvia") if verify else tr("Avvia"), QMessageBox.AcceptRole)
        box.addButton(tr("Annulla"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        if verify:
            self._pending_start = job
            self.laser.start_progress("check")
            if not self.ctl.check_job(job.lines):  # macchina non ferma, riga troppo lunga…: lo dice la barra di stato
                self._pending_start = None
                self.laser.update_running()
        else:
            self._run(job.lines)

    def _run(self, lines):
        self.canvas.clear_trail()
        self.laser.start_progress("job")
        self.ctl.stream_job(lines)
        self.laser.update_running()

    def verify_job(self):
        if not self.ctl.connected or self.ctl.job_active:
            return
        job = self.build_job()
        if job is None or not job.lines:
            return
        self._pending_start = None
        self.laser.start_progress("check")
        if not self.ctl.check_job(job.lines):
            self.laser.update_running()

    def _check_done(self, errors):
        self.laser.update_running()
        job = self._pending_start
        self._pending_start = None
        if errors and self.ctl.no_g55 and not getattr(self.profile, "no_g55", False):
            # la scheda non conosce G55 (firmware Acmer e altri): da ora il sistema «assoluto» si fa in G54
            self.profile.no_g55 = True
            try:
                self.profile.save()
            except OSError:
                pass
            rest = [e for e in errors if not (e[2] == 20 and str(e[1]).strip().upper() == "G55")]
            if not rest and not getattr(self, "_job_is_external", False):
                self.statusBar().showMessage(tr("La scheda non conosce G55: rifaccio il lavoro senza e lo verifico di nuovo"),
                                             8000)
                QTimer.singleShot(1500, lambda: self._reverify(job is not None))
                return
        if errors and any(e[2] == "NO_RISPOSTA" for e in errors):
            self.statusBar().showMessage(tr("La scheda ha smesso di rispondere durante la verifica"), 10000)
        if errors is None:  # Stop, Disconnetti o reset della scheda a metà verifica
            self.laser.eta.setText(tr("Verifica interrotta"))
            self.statusBar().showMessage(tr("Verifica interrotta: il lavoro non è stato avviato"), 6000)
            return
        if job is not None and not errors:
            self.statusBar().showMessage(tr("Verifica superata: avvio il lavoro"), 4000)
            QTimer.singleShot(1200, lambda: self._run(job.lines))  # la scheda ha appena fatto il reset del check mode
            return
        n = len(self.job.lines) if self.job else 0
        self.laser.eta.setText(tr("Verifica superata") if not errors else tr("Verifica: {0} errori", len(errors)))
        CheckResultDialog(errors, n, self).exec()

    def _reverify(self, then_start):
        """Rifà il lavoro (per esempio senza G55) e lo fa verificare di nuovo alla scheda."""
        job = self.build_job()
        if job is None or not job.lines or not self.ctl.connected:
            return
        self._pending_start = job if then_start else None
        self.laser.start_progress("check")
        if not self.ctl.check_job(job.lines):
            self._pending_start = None
            self.laser.update_running()

    def _job_error(self, index, line, code, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr("Lavoro in pausa"))
        box.setText(tr("<b>La scheda ha rifiutato la riga {0}</b>: <code>{1}</code><br>error:{2} — {3}<br><br>Il lavoro è stato messo in pausa per sicurezza.", index + 1, line, code, text))
        stop = box.addButton(tr("Ferma il lavoro"), QMessageBox.RejectRole)
        box.addButton(tr("Continua comunque"), QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is stop:
            self.ctl.stop_job()
        else:
            self.ctl.resume()

    def _job_finished(self, ok, msg):
        self.laser.update_running()
        if ok:
            self._interrupted = None
            self.statusBar().showMessage(msg, 8000)
            QApplication.beep()
            self._advance_variables()
        elif self.ctl.job_lines and 0 < self.ctl.job_acked < len(self.ctl.job_lines):
            self._interrupted = (list(self.ctl.job_lines), self.ctl.job_acked)

    def resume_job(self):
        if not self._interrupted or not self.ctl.connected:
            return
        lines, at = self._interrupted
        ok, why = resume.can_resume(lines, at)
        if not ok:
            QMessageBox.information(self, tr("Ripresa"), why)
            return
        if not self.ctl.homed:
            QMessageBox.information(self, tr("Ripresa"), tr("Prima fai l'homing: serve a ritrovare la posizione esatta della testa."))
            return
        back = max(0, min(at, 40))  # rifà qualche riga per sicurezza (sovrapposizione minima)
        r = QMessageBox.question(self, tr("Ripresa del lavoro"), tr("Riprendo dalla riga {0} di {1}.\nIl materiale NON deve essere stato spostato. Procedo?", at - back + 1, len(lines)))
        if r != QMessageBox.Yes:
            return
        prog = resume.resume_program(lines, at, back)
        self.banner.hide()
        self._interrupted = None
        self._run(prog)

    def _drop_interrupted(self):
        self._interrupted = None
        self.banner.hide()

    def _toggle_pause(self):
        self.laser.b_pause.toggle()

    def frame_job(self, kind="box", job=None):
        if not self.ctl.connected or self.ctl.job_active:
            return
        if isinstance(job, gcode.GcodeJob):
            self.show_external_job(job)
        else:
            job = self.build_job()
        if job is None or job.bounds is None:
            return
        pv = self.job_preview
        ox, oy = self._preview_offset(job)
        if kind.startswith("hull"):
            import cv2
            import numpy as np

            b = pv.segs[pv.segs[:, 5] > 0] if pv is not None and len(pv.segs) else np.zeros((0, 7))
            pts = np.concatenate([b[:, 0:2], b[:, 2:4]]).astype(np.float32) + np.float32([ox, oy])
            if len(pts) < 3:
                return
            hull = cv2.convexHull(pts).reshape(-1, 2)
            bed_pts = [(float(x), float(y)) for x, y in hull] + [(float(hull[0][0]), float(hull[0][1]))]
        else:
            b = job.bounds
            bed_pts = [(b.left(), b.top()), (b.right(), b.top()), (b.right(), b.bottom()), (b.left(), b.bottom()),
                       (b.left(), b.top())]
        bed_pts = [(min(max(x, 0.0), self.profile.bed_x), min(max(y, 0.0), self.profile.bed_y)) for x, y in bed_pts]
        bed_pts = bed_pts + bed_pts[1:] * (self.laser.frame_repeats() - 1)
        mpts = [self.profile.to_machine(x, y) for x, y in bed_pts]
        if getattr(job, "rotary_k", 1.0) != 1.0:  # rotativo: il contorno gira l'oggetto come farà il lavoro
            _, ry = self.profile.to_machine(*job.rotary_ref)
            mpts = [(mx, ry + (my - ry) * job.rotary_k) for mx, my in mpts]
        laser = self.laser.fire_pct.value() if kind.endswith("_laser") else 0.0
        self.ctl.frame_path(mpts, max(self.move.feed.value(), 3000), laser, self.profile.s_max)
        self.statusBar().showMessage(tr("Contorno con il puntino al %g%%: Stop per interrompere") % laser if laser
                                     else tr("Contorno a laser spento"), 5000)

    def preview_job(self, job=None):
        job = job if isinstance(job, gcode.GcodeJob) else self.build_job()
        if job is None or not job.lines:
            return
        if job is self.job and self.job_preview is not None:
            pv = self.job_preview  # già letta da build_job (per il rotativo è il disegno com'è sul piano)
        else:
            pv = job.preview if job.preview is not None else gcode_preview.parse(job.lines, profile=self.profile)
        ox, oy = self._preview_offset(job) if job is self.job else job.out_to_bed
        pv = gcode_preview.shifted(pv, ox, oy)  # anteprima in coordinate piano; l'originale resta per il piano
        PreviewDialog(pv, job, self.profile, (self.profile.bed_x, self.profile.bed_y), self).exec()
        # chiusa l'anteprima, il percorso arancione non resta sopra il disegno (con una foto la copriva tutta);
        # riappare quando si avvia il lavoro
        if not (self.ctl.job_active or self.ctl.checking):
            self.canvas.clear_preview()

    def save_gcode(self, job=None, name=None):
        job = job if isinstance(job, gcode.GcodeJob) else self.build_job()
        if job is None or not job.lines:
            return
        start = os.path.join(self.qs.value("gcode_dir", os.path.expanduser("~")), (name or self.editor.doc.name or "lavoro") + ".gcode")
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva G-code"), start, tr("G-code (*.gcode *.nc)"))
        if not path:
            return
        self.qs.setValue("gcode_dir", os.path.dirname(path))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(job.lines) + "\n")
        self.statusBar().showMessage(tr("G-code salvato: {0} ({1} righe, ~{2})", path, len(job.lines), _hms(job.seconds)), 6000)

    def run_gcode_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Esegui file G-code"), self.qs.value("gcode_dir", os.path.expanduser("~")),
                                                  tr("G-code (*.gcode *.nc *.gc *.ngc *.txt);;Tutti i file (*)"))
        if not path:
            return
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        pv = gcode_preview.parse(lines, profile=self.profile)
        gcode.flip_preview(pv, self.profile.invert_x, self.profile.invert_y)  # assi invertiti: piano = origine - uscita
        off = self.work_origin_on_bed()
        self.canvas.set_preview(pv, off)
        if not self.ctl.connected:
            self.statusBar().showMessage(tr("Anteprima di {0}: connetti la macchina per eseguirlo", os.path.basename(path)), 6000)
            return
        r = QMessageBox.question(self, tr("Esegui file G-code"), tr("{0}\n{1} righe · tempo stimato {2}\n\nOcchiali indossati, materiale fissato e a fuoco?\nAvvio?", os.path.basename(path), len(lines), _hms(pv.seconds)))
        if r == QMessageBox.Yes:
            self._run(lines)

    def show_external_job(self, job):
        """Un lavoro generato fuori dal documento (test materiale): anteprima sul piano e riepilogo."""
        pv = job.preview if job.preview is not None else gcode_preview.parse(job.lines, profile=self.profile)
        self.job, self.job_preview, self.job_preview_off = job, pv, job.out_to_bed
        self.canvas.set_preview(pv, job.out_to_bed)
        self.laser.show_job(job, self.profile)
        return pv

    def _preview_offset(self, job):
        """Spostamento dell'anteprima salvata (con il rotativo è quella del disegno piatto, che ha il suo)."""
        if job is self.job and getattr(self, "job_preview_off", None) is not None:
            return self.job_preview_off
        return job.out_to_bed

    # ================================================================ testo variabile
    def _variable_texts(self, output_only=False):
        out = []
        for s in self.editor.doc.shapes:
            cs = self.editor.doc.layers.get(s.layer)
            if output_only and (s.hidden or cs is None or not cs.output):
                continue
            out.extend(ops.variable_texts(s))
        return out

    def _vars_changed(self):
        for t in self._variable_texts():
            t.invalidate()
        for s in self.editor.doc.shapes:
            if any(True for _ in ops.variable_texts(s)):
                s.invalidate()
        self.editor.preview_changed()

    def _advance_variables(self):
        if not variables.STATE.get("auto") or getattr(self, "_job_is_external", False):
            return
        texts = self._variable_texts(output_only=True)
        if not texts:
            return
        copies = max(t.var_offset for t in texts) + 1
        variables.advance(copies)
        self.statusBar().showMessage(tr("Testo variabile: prossimo numero {0}", variables.STATE['serial'])
                                     + (tr(", riga CSV {0}", variables.STATE['row'] + 1) if variables.STATE.get("rows") else ""),
                                     10000)

    def variables_dialog(self, *_):
        from .dialogs_vars import VariablesDialog

        dlg = VariablesDialog(self._variable_texts(), self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()

    # ================================================================ materiali
    def material_library(self, *_):
        cs = self.layers._current_cs()
        dlg = MaterialLibraryDialog(cs, self)
        dlg.apply_requested.connect(lambda m: self.apply_material(cs, m))
        dlg.test_requested.connect(lambda m: QTimer.singleShot(0, lambda: self.material_test(m)))
        dlg.exec()

    def apply_material(self, cs, m):
        if cs is None:
            return
        self.editor.run(f"Materiale: {m.name}", materials.apply_to_layer, m, cs)
        msg = f"{cs.label()}: {m.summary()}"
        if m.defocus:
            msg += tr(" — ricordati di abbassare il fuoco di {0:g} mm", m.defocus)
        self.statusBar().showMessage(msg, 10000)

    def material_test(self, seed=None):
        if getattr(self, "_mt_dlg", None) is not None:
            self._mt_dlg.raise_()
            self._mt_dlg.activateWindow()
            if isinstance(seed, materials.Material):
                self._mt_dlg.seed(seed)
            return self._mt_dlg
        head = self.canvas.head_pos()
        dlg = MaterialTestDialog(self.profile, (head.x(), head.y()) if head is not None else None,
                                 seed if isinstance(seed, materials.Material) else None, self)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)

        dlg.action.connect(lambda kind, job: self._test_job_action(kind, job, "test-materiale"))
        dlg.destroyed.connect(lambda *_: setattr(self, "_mt_dlg", None))
        self._mt_dlg = dlg
        dlg.show()
        return dlg

    def _test_job_action(self, kind, job, name):
        """Anteprima / contorno / salva / avvia di un lavoro di prova (test materiale, prova della scansione)."""
        if kind == "preview":
            self.preview_job(job)
        elif kind == "frame":
            if not self.ctl.connected:
                self.show_external_job(job)
                self.statusBar().showMessage(tr("Connetti la macchina per il contorno: intanto il test è mostrato sul piano"), 5000)
            else:
                self.frame_job("box", job)
        elif kind == "save":
            self.save_gcode(job, name)
        elif kind == "start":
            self.show_external_job(job)
            self._job_is_external = True
            self.start_job(job)

    def scan_offset_dialog(self, *_):
        """Laser → Correzione della scansione avanti e indietro (tabella del profilo e prova da incidere)."""
        if getattr(self, "_so_dlg", None) is not None:
            self._so_dlg.raise_()
            self._so_dlg.activateWindow()
            return self._so_dlg
        from .dialogs_scan import ScanOffsetDialog

        head = self.canvas.head_pos()
        dlg = ScanOffsetDialog(self.profile, (head.x(), head.y()) if head is not None else None, self)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.action.connect(lambda kind, job: self._test_job_action(kind, job, "prova-scansione"))
        dlg.saved.connect(lambda: self.statusBar().showMessage(
            tr("Correzione della scansione salvata nel profilo «{0}»", self.profile.name), 5000))
        dlg.destroyed.connect(lambda *_: setattr(self, "_so_dlg", None))
        self._so_dlg = dlg
        dlg.show()
        return dlg

    HELP_LEVELS = ("principiante", "normale", "esperto")

    def help_level(self):
        """Impostazioni → Livello di aiuto. Chi aggiorna dalla 0.12: nomi accesi → principiante, esperto → esperto."""
        v = self.qs.value("help_level", "")
        if v in self.HELP_LEVELS:
            return v
        if self.qs.value("expert_mode", False) in (True, "true", "1", 1):
            return "esperto"
        if self.qs.value("cmd_labels", False) in (True, "true", "1", 1):
            return "principiante"
        return "normale"

    def set_help_level(self, level, quiet=False):
        """principiante: nomi sotto i comandi e accanto ai segni, spiegazioni, suggerimenti;
        normale: spiegazioni e suggerimenti; esperto: nessuno dei tre. Gli avvisi di sicurezza restano sempre."""
        from . import cmd_labels

        level = level if level in self.HELP_LEVELS else "normale"
        self.qs.setValue("help_level", level)
        for k, lv in (("help_beginner", "principiante"), ("help_normal", "normale"), ("help_expert", "esperto")):
            if self.acts[k].isChecked() != (lv == level):
                self.acts[k].setChecked(lv == level)
        names = level == "principiante"
        if names or getattr(self, "_names_applied", False):
            cmd_labels.apply(self, names)
        self._names_applied = names
        self.canvas.set_marker_labels(names)
        self.canvas.hide_marker_hint()
        if level == "esperto" and getattr(self, "_banner_hint", False) and self.banner.isVisible():
            self.banner.hide()
        if not quiet:
            self.statusBar().showMessage({
                "principiante": tr("Livello di aiuto: principiante (nomi sotto i comandi e spiegazioni)"),
                "normale": tr("Livello di aiuto: normale (spiegazioni passando sui segni)"),
                "esperto": tr("Livello di aiuto: esperto (meno scritte; gli avvisi di sicurezza restano)")}[level], 5000)

    def expert_mode(self):
        return self.help_level() == "esperto"

    def setup_wizard(self, *_, first=False):
        """Impostazioni → Configurazione guidata della macchina (anche al primo avvio)."""
        from .dialogs_setup import SetupWizard

        dlg = SetupWizard(self, first=first)
        self._setup_dlg = dlg
        res = dlg.exec()
        self._setup_dlg = None
        return res

    def phone_dialog(self, *_):
        """Laser → Controllo dal telefono (acceso/spento, codice QR, mini guida)."""
        if getattr(self, "_ph_dlg", None) is not None:
            self._ph_dlg.raise_()
            return self._ph_dlg
        from .phone_ui import PhoneDialog

        dlg = PhoneDialog(self.phone, self)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda *_: setattr(self, "_ph_dlg", None))
        self._ph_dlg = dlg
        dlg.show()
        return dlg

    def photo_from_phone(self, data):
        """Foto del test materiale arrivata dal telefono: apre il Test materiale e la legge."""
        from .dialogs_testphoto import decode_image

        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        dlg = self.material_test()
        if dlg is None:
            return None
        dlg.raise_()
        return dlg.analyze_image(decode_image(data))

    def fire_guard_dialog(self, *_):
        """Laser → Guardia fiamme (attivazione, sensibilità e prova dal vivo con la camera)."""
        if getattr(self, "_fg_dlg", None) is not None:
            self._fg_dlg.raise_()
            return self._fg_dlg
        from .fire_ui import FireGuardDialog

        dlg = FireGuardDialog(self.fire, self)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda *_: setattr(self, "_fg_dlg", None))
        self._fg_dlg = dlg
        dlg.show()
        return dlg

    # ================================================================ aiuto
    def claude_dialog(self, *_):
        from .dialogs_claude import ClaudeDialog

        ClaudeDialog(self.remote.port if self.remote else None, self).exec()

    def _first_run_notice(self):
        """Una volta sola, su un PC nuovo: le regole di base per usare un laser in sicurezza."""
        from ..profile import FIRST_RUN_FLAG

        flag = os.path.join(config_dir(), FIRST_RUN_FLAG)
        if os.path.exists(flag) or os.environ.get("FLC_NO_FIRST_RUN") \
                or QGuiApplication.platformName() in ("offscreen", "minimal"):
            return
        QMessageBox.warning(
            self, tr("Sicurezza laser"),
            tr("<b>FreeLaserCut comanda un laser: usalo in sicurezza.</b><ul>"
            "<li>Indossa sempre gli occhiali di protezione adatti alla lunghezza d'onda del tuo laser "
            "(per i diodi blu 445–455 nm), anche chi ti sta vicino.</li>"
            "<li>Non lasciare mai la macchina accesa senza sorveglianza: il materiale può prendere fuoco. "
            "Tieni a portata di mano un estintore adatto.</li>"
            "<li>Lavora in un ambiente aerato o con aspirazione: i fumi di legno, cartone e plastiche sono nocivi. "
            "Non incidere PVC, vinile o materiali che contengono cloro.</li>"
            "<li>Prima di ogni lavoro controlla il contorno, la messa a fuoco e che il piano sia sgombro.</li></ul>"
            "Il programma è fornito così com'è, senza garanzie: la responsabilità dell'uso della macchina è tua."))
        try:
            with open(flag, "w", encoding="utf-8") as fh:
                fh.write("avviso letto\n")
        except OSError:
            pass
        if not self.qs.value("setup_wizard_done", False) in (True, "true", "1", 1):
            self.qs.setValue("setup_wizard_offered", True)
            self.setup_wizard(first=True)

    def _offer_setup(self):
        """Chi aggiorna da una versione precedente: una volta sola propongo la configurazione guidata."""
        if self.qs.value("setup_wizard_done", False) in (True, "true", "1", 1) or \
                self.qs.value("setup_wizard_offered", False) in (True, "true", "1", 1) or self.banner.isVisible():
            return
        if os.environ.get("FLC_NO_FIRST_RUN") or QGuiApplication.platformName() in ("offscreen", "minimal"):
            return
        from ..profile import FIRST_RUN_FLAG

        # PC nuovo: ci pensa il primo avvio (avviso di sicurezza, poi la configurazione). Questo timer scatta anche
        # mentre l'avviso è aperto, e la striscia «Novità» resterebbe sotto la configurazione appena fatta.
        if not os.path.exists(os.path.join(config_dir(), FIRST_RUN_FLAG)) or getattr(self, "_setup_dlg", None):
            return
        self.qs.setValue("setup_wizard_offered", True)
        self.show_banner(tr("Novità: la configurazione guidata della macchina. Poche domande (modello, angolo dello 0, "
                            "prova delle frecce) perché testa e lavoro compaiano nel punto giusto del piano."), "info",
                         [(tr("Apri"), lambda: (self.banner.hide(), self.setup_wizard())),
                          (tr("Più tardi"), self.banner.hide)], hint=True)

    def make_support_report(self, path=None):
        """Aiuto → Crea rapporto per l'assistenza: un .zip da allegare a una segnalazione."""
        from .. import diag

        if not path:
            base = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(base):
                base = os.path.expanduser("~")
            start = os.path.join(base, time.strftime("FreeLaserCut-rapporto-%Y%m%d-%H%M.zip"))
            path, _ = QFileDialog.getSaveFileName(self, tr("Crea rapporto per l'assistenza"), start, tr("Archivio zip (*.zip)"))
        if not path:
            return None
        try:
            names = diag.make_report(path, self, self.comm_log)
        except OSError as ex:
            QMessageBox.warning(self, tr("Crea rapporto per l'assistenza"), tr("Non riesco a creare il file:\n{0}", ex))
            return None
        box = QMessageBox(self)
        box.setWindowTitle(tr("Rapporto creato"))
        box.setIcon(QMessageBox.Information)
        box.setText(tr("<b>Rapporto pronto</b><br>{0}", html.escape(path)))
        box.setInformativeText(tr("Allegalo a una segnalazione su GitHub (Issues) o mandalo a chi ti aiuta. "
                                  "Contiene: {0}.\nNiente progetti, immagini o dati personali.", ", ".join(names)))
        open_b = box.addButton(tr("Apri la cartella"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_b:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        return path

    def _job_stalled(self, msg, path):
        """Il lavoro non avanza e la macchina è ferma: lo dico e salvo il registro (resta tutto com'è)."""
        self.statusBar().showMessage(tr("Il lavoro sembra fermo ({0}). Registro salvato: per farti aiutare usa "
                                        "Aiuto → Crea rapporto per l'assistenza.", msg), 20000)

    YOUTUBE = "https://www.youtube.com/@FreeLaserCut"

    def open_youtube(self, *_):
        """Aiuto → Video tutorial su YouTube (si apre nel browser)."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self.YOUTUBE))

    def export_profile(self, *_, path=None):
        """Laser → Esporta il profilo della macchina (file .flcprofile)."""
        from .. import profile_share

        if not path:
            start = os.path.join(os.path.expanduser("~"), re.sub(r"[^\w\- ]+", "_", self.profile.name).strip() +
                                 profile_share.EXT)
            path, _ = QFileDialog.getSaveFileName(self, tr("Esporta il profilo della macchina"), start,
                                                  tr("Profilo FreeLaserCut (*{0})", profile_share.EXT))
        if not path:
            return None
        if not path.lower().endswith(profile_share.EXT):
            path += profile_share.EXT
        try:
            profile_share.export_profile(self.profile, path)
        except OSError as ex:
            QMessageBox.warning(self, tr("Esporta il profilo della macchina"), tr("Non riesco a salvare il file:\n{0}", ex))
            return None
        self.statusBar().showMessage(tr("Profilo «{0}» esportato: {1}", self.profile.name, path), 8000)
        return path

    def import_profile(self, *_, path=None):
        """Laser → Importa un profilo macchina: controllato, segnato «dalla comunità», assi da provare."""
        from .. import profile_share

        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Importa un profilo macchina"), os.path.expanduser("~"),
                                                  tr("Profilo FreeLaserCut (*{0})", profile_share.EXT))
        if not path:
            return None
        try:
            p = profile_share.read_profile(path)
        except ValueError as ex:
            QMessageBox.warning(self, tr("Importa un profilo macchina"), tr("Profilo non importato: {0}", ex))
            return None
        base, n = p.name, 2
        while os.path.exists(p.path()):  # non sovrascrivo un profilo che c'è già
            p.name = f"{base} ({n})"
            n += 1
        try:
            os.makedirs(os.path.dirname(p.path()), exist_ok=True)
            p.save()
        except OSError as ex:
            QMessageBox.warning(self, tr("Importa un profilo macchina"), tr("Non riesco a salvare il profilo:\n{0}", ex))
            return None
        r = QMessageBox.question(self, tr("Importa un profilo macchina"), tr(
            "Profilo «{0}» importato ({1:g} × {2:g} mm, {3}).\n\nViene da un altro utente: prima di incidere controlla "
            "area di lavoro e potenza e fai la prova delle frecce (Impostazioni → Configurazione guidata).\n\n"
            "Usarlo adesso?", p.name, p.bed_x, p.bed_y, profile_share.COMMUNITY))
        if r == QMessageBox.Yes:
            self.set_active_profile(p)
        return p

    def show_support(self):
        from .dialogs_support import SupportDialog

        SupportDialog(self).exec()

    def show_shortcuts(self):
        QMessageBox.information(self, tr("Scorciatoie da tastiera"), SHORTCUTS)

    def show_about(self):
        QMessageBox.about(self, tr("FreeLaserCut"), tr("<h3>FreeLaserCut (FLC) {0}</h3>Software libero di incisione laser per macchine GRBL, con profilo nativo per il Longer B1 40W.<br>Di fringuello79 · licenza GNU GPL 3.0 o successiva · nessuna garanzia.<br>Ti è utile? Puoi sostenerne lo sviluppo da <i>Aiuto → Sostieni FreeLaserCut</i>.<br><br>Caratteri Inter e JetBrains Mono (SIL OFL) · icone Lucide (ISC) · font a linea singola Hershey.", __version__))

    def _build_language_menu(self, parent):
        """Visualizza → Lingua: la scelta vale dal riavvio (il titolo resta riconoscibile anche in inglese)."""
        from .. import i18n

        title = tr("Lingua") if i18n.language() == "en" else tr("Lingua") + " / Language"
        sub = parent.addMenu(title)
        self.m_language = sub
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for code, name in i18n.LANGUAGES.items():
            act = sub.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == i18n.language())
            grp.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.choose_language(c))

    def choose_language(self, code):
        from .. import i18n

        i18n.save_language(code)
        if code == i18n.language():
            return
        r = QMessageBox.question(self, tr("Lingua"), tr("La nuova lingua sarà usata dal prossimo avvio di FreeLaserCut. "
                                                         "Riavviare adesso?"))
        if r == QMessageBox.Yes:
            self._restart = True
            if not self.close():
                self._restart = False

    def closeEvent(self, e):
        if self.ctl.job_active:
            if QMessageBox.question(self, tr("Lavoro in corso"), tr("C'è un lavoro in corso. Fermarlo e uscire?")) != QMessageBox.Yes:
                e.ignore()
                return
            self.ctl.stop_job()
        if not self._confirm_discard():
            e.ignore()
            return
        if getattr(self, "phone", None) is not None:
            self.phone.stop()
        if getattr(self, "banco", None) is None:
            self.qs.setValue("win_state_v5", self.saveState(5))
        else:
            self.banco.shutdown()
        self.qs.setValue("win_geom", self.saveGeometry())
        self.qs.setValue("autosave_pending", False)
        self.camera.shutdown()
        self.ctl.disconnect_port()
        if self.remote is not None:
            from .. import remote

            remote.stop(self.remote)
        super().closeEvent(e)
        if e.isAccepted():
            from .update_ui import run_installer_on_exit

            run_installer_on_exit(self)  # aggiornamento scaricato: l'installatore parte ora che FreeLaserCut si chiude
        if getattr(self, "_restart", False):
            from PySide6.QtCore import QProcess

            lst = getattr(QApplication.instance(), "_flc_single", None)
            if lst is not None:  # smetto di ascoltare: la nuova copia non deve trovare «già aperto» questa che si chiude
                lst.close()

            QProcess.startDetached(sys.executable, ["-m", "freelasercut"])


def _hms(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


SHORTCUTS = tr("""STRUMENTI
V selezione · N nodi · L linee/curve · R rettangolo · E ellisse · P poligono · S stella · F forme (galleria) · T testo
M misura · Q posiziona laser · Ctrl+Alt+N forma con misure esatte · Esc torna alla selezione
F9 aggancio agli oggetti sì/no · Maiusc+F9 aggancio alla griglia · Alt (tenuto premuto) lo sospende

SULLA TELA
Rotella zoom · Spazio+trascina o tasto centrale: sposta la vista · Ctrl+0 adatta al piano
Frecce: sposta di 1 mm (Maiusc 10, Ctrl 0,1) · senza selezione: jog della testa
Maiusc: proporzioni / angoli a 15° / asse · Ctrl: dal centro · Alt: niente aggancio
Trascina da sinistra a destra: seleziona ciò che è dentro · da destra a sinistra: anche ciò che tocca

NODI
Doppio clic su un segmento: nuovo nodo · D elimina · C angolo · S morbido · B spezza · I inserisci · M punto medio · L raddrizza
Trascina un segmento dritto per curvarlo · rilascia un estremo su un altro per unirli

MODIFICA
Ctrl+Z / Ctrl+Y annulla/ripeti · Ctrl+D duplica · Ctrl+G raggruppa · Ctrl+U separa · Ctrl+W salda
Alt+O offset · Alt+A serie a griglia · Alt+B scomponi · Alt+J unisci estremi · . , ruota di 90°
Alt+T vettorizza l'immagine selezionata

MATERIALI
Ctrl+M libreria materiali (applica al livello selezionato) · Laser → Test materiale

LIVELLI
Doppio clic su nome, modalità, velocità, potenza o passate per modificarli nella tabella · tasto destro: altre opzioni

GUIDA
Maiusc+F1 (o il pulsante ? in alto a destra): passa il mouse su un comando per leggerne descrizione e opzioni · Esc esce

LASER
Ctrl+Invio avvia · Ctrl+Spazio pausa · Ctrl+Pausa stop · Ctrl+Maiusc+F contorno · Ctrl+Maiusc+K verifica · Alt+P anteprima
Laser → Riconosci la macchina: porte USB, driver e profilo adattato alla scheda collegata

ANTEPRIMA
Rotella zoom verso il cursore · trascina per spostare · doppio clic o 0 adatta alla finestra""") + "\n\n" + tr("""DISPONI
Alt+N ottimizza lo spazio (nesting): i pezzi si sistemano sul materiale con il minimo spreco""") + "\n\n" + tr("""INTERFACCIA BANCO
Ctrl+F o F3 cerca un comando · Ctrl+Maiusc+W apre/chiude l'Officina · tasto destro sul piano: menu radiale
Durante l'incisione: Pausa e Stop restano sempre nello stesso posto, in basso al centro""")


def main(app=None, splash=None):
    from ..app import _install_crash_log

    _install_crash_log()

    def say(text):
        if splash is not None:
            try:
                splash.say(text)
            except Exception:  # noqa: BLE001
                pass

    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fringuello79.FreeLaserCut")
            except Exception:  # noqa: BLE001
                pass
        app = QApplication(sys.argv)
    app.setApplicationName("FreeLaserCut")
    app.setStyle("Fusion")
    style.fast_ui(app)  # suggerimenti pronti e senza scatti, niente animazioni dei menu
    style.load_fonts()
    app.setFont(style.ui_font(9))
    app.setStyleSheet(QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)
    app.setWindowIcon(QIcon(os.path.join(ASSETS, "logo.svg")))
    say(tr("Preparo il motore delle immagini…"))
    try:
        from ..core import imaging

        imaging.warmup()
    except Exception:  # noqa: BLE001
        pass
    from .banco import ChoiceDialog, needs_choice

    if needs_choice(migrate_qsettings()) and QGuiApplication.platformName() not in ("offscreen", "minimal"):
        if splash is not None:
            splash.hide()
        ChoiceDialog().exec()
        if splash is not None:
            splash.show()
    say(tr("Apro il piano di lavoro…"))
    try:
        win = MainWindow()
    except Exception:  # noqa: BLE001 — prima chiudo lo splash, poi registro e mostro l'errore, poi esco
        if splash is not None:
            try:
                splash.close()
            except RuntimeError:
                pass
        sys.excepthook(*sys.exc_info())
        sys.exit(1)
    win.show()
    if splash is not None:
        splash.finish(win)
    listener = getattr(app, "_flc_single", None)
    if listener is not None:  # istanza unica: d'ora in poi un secondo avvio porta qui
        listener.attach(win)
    open_paths(win, sys.argv[1:])
    sys.exit(app.exec())


def open_paths(win, paths):
    """Apre i file passati all'avvio (o da un secondo avvio): progetti con Apri, il resto con Importa."""
    for p in paths:
        if os.path.exists(p):
            win.import_files([p]) if not p.lower().endswith((".flcut", ".fbrn")) else win.file_open(p)
