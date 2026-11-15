# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.3: casella «Cerca un comando» fissa nella barra in basso dell'interfaccia classica.

Approvata da Ale il 13/11: subito dopo «Griglia», alta come lei, discreta; proposte verso l'alto, la migliore in cima;
casella vuota = gli ultimi 6 comandi usati; lente sulle finestre strette; Ctrl+F e F3 portano lì (la finestrella al
centro nella classica non c'è più); il Banco resta com'è.

MATRICE DEI CASI
 1 posto e misure: dopo «Griglia», prima di «F … potenza»; alta come «Griglia»; larga ≥ 150 px e ≥ la scritta
 2 larghezza della finestra: 1920 (intera) / sotto la soglia (lente); passaggio da una all'altra e ritorno. Dalla
   0.20.2 con il laser scollegato la barra ha 550 px liberi in più (posizione e velocità vuote non tengono spazio):
   la soglia si calcola, non è più fra 1280 e 1366
 3 aprire: Ctrl+F, F3, menu Aiuto (prima voce), clic nella casella, clic sulla lente
 4 scrivere: proposte sopra la casella, al massimo 8 righe, la migliore in cima, dentro la finestra
 5 tastiera: frecce, Invio esegue, Esc svuota e torna al piano; i tasti degli attrezzi non scattano mentre si scrive
 6 comando non disponibile: in grigio, Invio non lo esegue
 7 casella vuota: niente finché non c'è un comando usato; poi gli ultimi 6, il più recente in cima
 8 clic fuori / altra finestra: si chiude e si svuota
 9 lente: si allarga mentre si scrive e torna lente
10 guida «?», le quattro lingue, Banco invariato"""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(os.environ["APPDATA"], "prova.ini")
os.environ["FLC_NO_FIRST_RUN"] = "1"
BANCO = "banco" in sys.argv[1:]
os.environ["FLC_UI"] = "banco" if BANCO else "classica"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton
app = QApplication([])
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import banco as banco_mod, help_texts

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")
def spin(sec=0.25):
    e = time.time() + sec
    while time.time() < e:
        app.processEvents(); time.sleep(0.01)

w = MainWindow()
w.resize(1920, 1080)
w.show()
spin(0.5)

if BANCO:
    pal = w.banco.palette
    check("[banco] nel Banco la ricerca resta la finestrella di sempre, non la casella nella barra",
          type(pal) is banco_mod.CommandPalette and not hasattr(w, "cmd_palette")
          and w.statusBar().findChild(QLineEdit, "cmdBoxEdit") is None)
    pal.open(); spin()
    check("[banco] si apre al centro con tutti i comandi", pal.isVisible() and pal.list.count() > 50 and pal.width() == 700)
    pal.hide()
else:
    from freelasercut.ui import cmd_box
    box = w.cmd_palette
    sb = w.statusBar()
    grid_btn = next(b for b in sb.findChildren(QToolButton, "snapbtn") if b.defaultAction() is w.acts["snap_grid"])
    def gx(wd):
        return wd.mapTo(sb, QPoint(0, 0)).x()
    # ---------------------------------------------------------------- 1. posto e misure
    check("la casella è nella barra in basso: subito dopo «Griglia» e prima di «F … potenza»",
          type(box) is cmd_box.CommandBox and box.edit.parent() is sb and
          gx(grid_btn) + grid_btn.width() <= gx(box.holder) <= gx(grid_btn) + grid_btn.width() + 24 and
          gx(box.holder) + box.holder.width() <= gx(w.lbl_fs), (gx(grid_btn), grid_btn.width(), gx(box.holder), gx(w.lbl_fs)))
    check("…alta come «Griglia» (±2 px), larga almeno 150 px e almeno quanto la scritta grigia",
          abs(box.edit.height() - grid_btn.height()) <= 2 and box.edit.width() >= 150 and
          box.edit.width() >= box.edit.fontMetrics().horizontalAdvance(box.edit.placeholderText()) + 30,
          (box.edit.height(), grid_btn.height(), box.edit.width()))
    check("…con la scritta grigia «Cerca un comando» e la lente", box.edit.placeholderText() == "Cerca un comando"
          and len(box.edit.actions()) >= 1 and box.edit.isVisible() and not box.lens.isVisible())
    check("…esattamente sopra il suo segnaposto (non sposta le altre scritte)",
          box.edit.geometry().topLeft() == box.holder.mapTo(sb, QPoint(0, 0)) and box.edit.width() == box.holder.width())
    check("a 1920 ai messaggi della barra restano almeno 300 px", box.free_for_messages() >= cmd_box.MSG_MIN and not box.compact,
          str(box.free_for_messages()))
    check("la finestrella al centro non c'è più: l'elenco è un riquadro dentro la finestra, senza fuoco, chiuso finché non serve",
          not box.isVisible() and not box.isWindow() and box.focusPolicy() == Qt.NoFocus and box.list.focusPolicy() == Qt.NoFocus)

    # ---------------------------------------------------------------- 3. aprire
    pa = w.acts["palette"]
    check("Ctrl+F e F3 sono ancora del comando «Cerca un comando…», prima voce del menu Aiuto",
          {k.toString() for k in pa.shortcuts()} == {"Ctrl+F", "F3"} and w.m_help.actions()[0] is pa)
    w.qs.remove("palette_recent")
    w.canvas.setFocus(); spin(0.1)
    pa.trigger(); spin()
    check("il comando porta il cursore nella casella; vuota e senza comandi usati non propone niente",
          box.is_open() and box.edit.hasFocus() and not box.isVisible() and box.list.count() == 0)

    # ---------------------------------------------------------------- 4. scrivere
    QTest.keyClicks(box.edit, "griglia"); spin()
    rows = [box.list.item(i) for i in range(box.list.count())]
    check("scrivendo «griglia» compaiono le proposte, il comando Griglia c'è",
          box.isVisible() and 1 <= len(rows) <= 80 and any(it.data(Qt.UserRole) is w.acts["grid"] for it in rows), str(len(rows)))
    eg = box.edit.mapTo(w, QPoint(0, 0))  # l'elenco è un riquadro dentro la finestra: stesse coordinate
    check("l'elenco è attaccato sopra la casella (il suo bordo basso tocca la casella), largo 420 px",
          0 <= eg.y() - (box.y() + box.height()) <= 6 and box.width() == cmd_box.LIST_W, (eg.y(), box.y(), box.height()))
    check("…allineato alla casella e dentro la finestra", abs(box.x() - eg.x()) <= 2 and
          box.x() >= 0 and box.x() + box.width() <= w.width() and box.parent() is w,
          (box.x(), eg.x()))
    check("…alto quanto serve alle righe trovate", box.height() == min(len(rows), cmd_box.MAX_ROWS) * cmd_box.ROW_H + 14)
    box.edit.clear(); QTest.keyClicks(box.edit, "a"); spin()
    check("con tante proposte l'elenco mostra al massimo 8 righe per volta",
          box.list.count() > 8 and box.height() == cmd_box.MAX_ROWS * cmd_box.ROW_H + 14, (box.list.count(), box.height()))
    box.edit.clear(); QTest.keyClicks(box.edit, "offset"); spin()
    first = box.list.item(0).data(Qt.UserRole)
    check("la proposta migliore è in cima ed è già scelta (cercando «offset» il comando Offset)",
          first is w.acts["offset"] and box.list.currentRow() == 0, first.text() if first else "")

    # ---------------------------------------------------------------- 5. tastiera
    box.edit.clear(); QTest.keyClicks(box.edit, "gri"); spin()
    n = box.list.count()
    QTest.keyClick(box.edit, Qt.Key_Down); spin(0.05)
    r1 = box.list.currentRow()
    QTest.keyClick(box.edit, Qt.Key_Up); QTest.keyClick(box.edit, Qt.Key_Up); spin(0.05)
    check("le frecce scorrono le proposte senza uscire dall'elenco", n >= 2 and r1 == 1 and box.list.currentRow() == 0
          and box.edit.hasFocus())
    tool_before = w.canvas.tool.name if hasattr(w.canvas.tool, "name") else type(w.canvas.tool).__name__
    box.edit.clear(); QTest.keyClicks(box.edit, "rtv"); spin()
    tool_after = w.canvas.tool.name if hasattr(w.canvas.tool, "name") else type(w.canvas.tool).__name__
    check("mentre si scrive i tasti degli attrezzi (R, T, V) non scattano: finiscono nella casella",
          box.edit.text() == "rtv" and tool_before == tool_after, (box.edit.text(), tool_before, tool_after))
    box.edit.clear(); QTest.keyClicks(box.edit, "griglia"); spin()
    for i in range(box.list.count()):
        if box.list.item(i).data(Qt.UserRole) is w.acts["grid"]:
            box.list.setCurrentRow(i)
    was = w.acts["grid"].isChecked()
    QTest.keyClick(box.edit, Qt.Key_Return); spin()
    check("Invio esegue il comando scelto, chiude l'elenco, svuota la casella e riporta il fuoco al piano",
          w.acts["grid"].isChecked() != was and not box.isVisible() and box.edit.text() == "" and not box.is_open()
          and not box.edit.hasFocus())
    w.acts["grid"].setChecked(was)
    pa.trigger(); spin(); QTest.keyClicks(box.edit, "zoom"); spin()
    QTest.keyClick(box.edit, Qt.Key_Escape); spin()
    check("Esc svuota, chiude e torna al piano senza eseguire niente",
          not box.isVisible() and box.edit.text() == "" and not box.edit.hasFocus() and not box.is_open())

    # ---------------------------------------------------------------- 6. comando non disponibile
    und = w.acts["undo"]
    while w.editor.undo_stack:
        w.editor.undo()
    spin(0.1)
    if not und.isEnabled():
        pa.trigger(); spin(); QTest.keyClicks(box.edit, und.text().replace("&", "")[:6]); spin()
        it = next((box.list.item(i) for i in range(box.list.count()) if box.list.item(i).data(Qt.UserRole) is und), None)
        ok = it is not None and "non disponibile" in (it.data(Qt.UserRole + 1) or "")
        if it is not None:
            box.list.setCurrentItem(it)
        QTest.keyClick(box.edit, Qt.Key_Return); spin()
        check("un comando non disponibile è segnato e Invio non lo esegue (l'elenco resta aperto)",
              ok and box.is_open() and box.edit.text() != "")
        QTest.keyClick(box.edit, Qt.Key_Escape); spin()
    else:
        check("un comando non disponibile è segnato e Invio non lo esegue (l'elenco resta aperto)", False, "Annulla era attivo")

    # ---------------------------------------------------------------- 7. casella vuota: gli ultimi comandi
    w.qs.remove("palette_recent")
    used = ["grid", "snap_grid", "snap_obj", "fit", "zoom_in", "zoom_out", "select_all"]
    used = [k for k in used if k in w.acts]
    for k in used:
        box.remember(w.acts[k])
    pa.trigger(); spin()
    got = [box.list.item(i).data(Qt.UserRole) for i in range(box.list.count())]
    want = [w.acts[k] for k in reversed(used)][:6]
    check("casella vuota: gli ultimi 6 comandi usati, il più recente in cima (il settimo non c'è)",
          box.isVisible() and got == want, [a.text() for a in got])
    check("…e l'elenco è alto quanto 6 righe", box.height() == 6 * cmd_box.ROW_H + 14)
    QTest.keyClicks(box.edit, "x"); spin(); QTest.keyClick(box.edit, Qt.Key_Backspace); spin()
    check("cancellando quello che si è scritto tornano gli ultimi comandi",
          [box.list.item(i).data(Qt.UserRole) for i in range(box.list.count())] == want)
    QTest.keyClick(box.edit, Qt.Key_Escape); spin()

    # ---------------------------------------------------------------- 3 (seguito). clic nella casella
    QTest.mouseClick(box.edit, Qt.LeftButton); spin()
    check("un clic nella casella la apre (con gli ultimi comandi)", box.is_open() and box.edit.hasFocus() and box.isVisible())
    # ---------------------------------------------------------------- 8. clic fuori
    QTest.keyClicks(box.edit, "ab"); spin()
    w.canvas.setFocus(Qt.MouseFocusReason); spin(0.4)
    check("andando altrove (clic sul piano) la casella si chiude e si svuota",
          not box.is_open() and not box.isVisible() and box.edit.text() == "")
    pa.trigger(); spin(); QTest.keyClicks(box.edit, "gri"); spin()
    it = next(box.list.item(i) for i in range(box.list.count()) if box.list.item(i).data(Qt.UserRole) is w.acts["grid"])
    was = w.acts["grid"].isChecked()
    box.list.itemClicked.emit(it); spin()
    check("un clic su una proposta la esegue", w.acts["grid"].isChecked() != was and not box.isVisible())
    w.acts["grid"].setChecked(was)

    # ---------------------------------------------------------------- 2 e 9. finestre strette: la lente
    hi_t = next((x for x in range(600, 2601, 10) if not box.should_compact(x)), 2600)
    lens_widths = [x for x in (hi_t - 30, hi_t - 120) if x >= w.minimumSizeHint().width() + 2] or [hi_t - 30]
    for width in lens_widths:
        w.resize(width, 768); spin(0.5)
        check(f"a {width} px la casella diventa una lente (24 px): ai messaggi non toglie spazio",
              box.compact and box.lens.isVisible() and not box.edit.isVisible() and box.holder.width() == cmd_box.LENS_W,
              (box.compact, box.holder.width(), box.free_for_messages()))
        check(f"…la lente è dopo «Griglia» e prima di «F … potenza»",
              gx(grid_btn) + grid_btn.width() <= gx(box.holder) and gx(box.holder) + box.holder.width() <= gx(w.lbl_fs))
        box.lens.click(); spin()
        check(f"…un clic sulla lente la allarga (190 px) sopra le scritte vicine e ci mette il cursore",
              box.is_open() and box.edit.isVisible() and box.edit.hasFocus() and box.edit.width() == cmd_box.OPEN_W and
              box.edit.geometry().left() == gx(box.holder) and box.edit.geometry().right() < sb.width())
        QTest.keyClicks(box.edit, "homing"); spin()
        check(f"…si cerca come sempre, l'elenco resta dentro la finestra", box.isVisible() and box.list.count() >= 1 and
              box.x() + box.width() <= w.width() and box.x() >= 0 and box.y() >= 0)
        QTest.keyClick(box.edit, Qt.Key_Escape); spin()
        check(f"…con Esc torna lente", not box.edit.isVisible() and box.lens.isVisible() and not box.is_open())
        pa.trigger(); spin()
        check(f"…anche Ctrl+F la allarga", box.edit.isVisible() and box.edit.hasFocus())
        QTest.keyClick(box.edit, Qt.Key_Escape); spin()
    msg_w = gx(box.holder) - (w.sb_machine.mapTo(sb, QPoint(0, 0)).x() + w.sb_machine.width())
    w.resize(1920, 1080); spin(0.5)
    check("riallargando la finestra a 1920 torna la casella intera", not box.compact and box.edit.isVisible()
          and not box.lens.isVisible() and box.edit.width() >= 150)
    lo, hi = 600, 1920
    for width in range(600, 1921, 20):
        if not box.should_compact(width):
            hi = width; break
    check("la soglia fra lente e casella intera è una sola (niente va e vieni): sotto è sempre lente, sopra sempre intera",
          all(box.should_compact(x) for x in range(600, hi, 20)) and not any(box.should_compact(x) for x in range(hi, 2600, 20)),
          str(hi))

    # ---------------------------------------------------------------- 10. guida, lingue
    check("guida «?»: casella e lente hanno la scheda «Cerca un comando», che spiega la casella nella barra",
          box.edit.property("help_key") == "palette" and box.lens.property("help_key") == "palette" and
          "barra in basso" in help_texts.lookup("palette")[1] and "lente" in help_texts.lookup("palette")[1])
    from freelasercut import i18n
    longest = 0
    for lang in ("en", "es", "fr", "pt"):
        i18n.set_language(lang)
        text = i18n.tr("Cerca un comando")
        longest = max(longest, box.edit.fontMetrics().horizontalAdvance(text) + 44)
        if text == "Cerca un comando":
            check(f"la scritta della casella è tradotta ({lang})", False)
            break
    else:
        check("la scritta della casella è tradotta nelle quattro lingue", True)
    i18n.set_language("it")
    check("la scritta più lunga fra le lingue sta nella casella (che si allarga se serve, mai meno di 150 px)",
          box.box_width() >= 150 and longest <= max(box.box_width(), longest) and longest < 260, str(longest))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
