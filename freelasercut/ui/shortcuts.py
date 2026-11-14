# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto → Scorciatoie da tastiera (0.19.5): l'elenco ordinato, una scorciatoia per riga, il tasto in grassetto.

sections() -> [(titolo, [(tasti, cosa fa, azione o None), ...]), ...]. «azione» è il nome dell'azione della finestra
principale che ha davvero quella scorciatoia: una prova controlla che i due coincidano.
"""
import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QTextBrowser, QVBoxLayout

from ..theme import C
from freelasercut.i18n import tr  # noqa: E402


def sections():
    sh = tr("Maiusc")
    return [
        (tr("Strumenti"), [
            ("V", tr("Selezione"), None), ("N", tr("Modifica nodi"), None), ("L", tr("Linee e curve"), None),
            ("H", tr("Mano libera"), None),
            ("R", tr("Rettangolo"), None), ("E", tr("Ellisse"), None), ("P", tr("Poligono"), None),
            ("S", tr("Stella"), None), ("F", tr("Galleria forme"), None), ("T", tr("Testo"), None),
            ("M", tr("Misura"), None), ("Q", tr("Posiziona laser"), None),
            ("Ctrl+Alt+N", tr("Forma con misure esatte"), "exact_shape"),
            ("Esc", tr("Torna allo strumento Selezione"), None),
            ("F9", tr("Aggancio agli oggetti sì/no"), "snap_obj"),
            (sh + "+F9", tr("Aggancio alla griglia sì/no"), "snap_grid"),
            (tr("Alt (tenuto premuto)"), tr("Sospende l'aggancio"), None),
        ]),
        (tr("Sulla tela"), [
            (tr("Rotella"), tr("Zoom"), None),
            (tr("Spazio + trascina, o tasto centrale"), tr("Sposta la vista"), None),
            ("Ctrl+0", tr("Adatta al piano"), "fit"),
            (tr("Frecce"), tr("Sposta gli oggetti selezionati di 1 mm"), None),
            (sh + tr("+frecce"), tr("Sposta di 10 mm"), None),
            (tr("Ctrl+frecce"), tr("Sposta di 0,1 mm"), None),
            (tr("{0} mentre trascini", sh), tr("Proporzioni, angoli a 15°, un asse solo"), None),
            (tr("Ctrl mentre trascini"), tr("Dal centro"), None),
            (tr("Alt mentre trascini"), tr("Niente aggancio"), None),
            (tr("Trascina da sinistra a destra"), tr("Seleziona ciò che è tutto dentro"), None),
            (tr("Trascina da destra a sinistra"), tr("Seleziona anche ciò che tocca"), None),
        ]),
        (tr("Muovere la testa (laser collegato)"), [
            (tr("Frecce, senza niente selezionato"), tr("Jog della testa del passo scelto nella scheda Movimento"), None),
            (tr("Movimento → Continuo"), tr("Tieni premuta una freccia: la testa si muove finché la rilasci"), None),
            (tr("Movimento → Joystick"), tr("Tieni premuto e trascina: la testa va dove punta la manopola, più veloce "
                                            "più la allontani dal centro; rilascia per fermarla"), None),
            (tr("Esc sul joystick"), tr("Ferma il joystick"), None),
            (tr("Doppio clic con «Posiziona laser» (Q)"), tr("Porta la testa in quel punto"), None),
        ]),
        (tr("Nodi"), [
            (tr("Clic su un nodo"), tr("Seleziona quel nodo"), None),
            (tr("Ctrl+clic o {0}+clic", sh), tr("Aggiunge o toglie un nodo dalla selezione"), None),
            (tr("Trascina sul vuoto"), tr("Seleziona i nodi dentro il rettangolo"), None),
            ("Ctrl+A", tr("Tutti i nodi"), None),
            (tr("Doppio clic su un segmento"), tr("Nuovo nodo"), None),
            (tr("D o Canc"), tr("Elimina i nodi selezionati"), None),
            ("C", tr("Angolo"), None), ("S", tr("Morbido"), None), ("B", tr("Spezza"), None),
            ("I", tr("Inserisce un nodo sul segmento sotto il mouse"), None),
            ("M", tr("Nodo nel punto medio del segmento"), None), ("L", tr("Raddrizza il segmento"), None),
            ("A", tr("Arrotonda lo spigolo (raccordo)"), None),
            ("J", tr("Unisce due estremi selezionati in un punto solo, a metà strada"), None),
            (sh + "+J", tr("Collega due estremi selezionati con un tratto dritto"), None),
            ("Esc", tr("Toglie la selezione dei nodi (di nuovo: torna a Selezione)"), None),
            (tr("Disponi → Allinea / Distribuisci"), tr("Con dei nodi scelti, agiscono sui nodi"), None),
            (tr("Trascina un segmento dritto"), tr("Lo curva"), None),
            (tr("Rilascia un estremo su un altro"), tr("Li unisce"), None),
        ]),
        (tr("Modifica"), [
            ("Ctrl+Z", tr("Annulla"), "undo"), ("Ctrl+Y", tr("Ripeti"), "redo"),
            ("Ctrl+D", tr("Duplica"), "duplicate"), ("Ctrl+G", tr("Raggruppa"), "group"),
            ("Ctrl+U", tr("Separa"), "ungroup"), ("Ctrl+W", tr("Salda"), "weld"),
            ("Alt+O", tr("Offset"), "offset"), ("Ctrl+Alt+S", tr("Semplifica tracciati"), "simplify"),
            ("Alt+A", tr("Serie a griglia"), "grid_array"),
            ("Alt+B", tr("Scomponi"), "break"), ("Alt+J", tr("Unisci estremi"), "join"),
            (". ,", tr("Ruota di 90°"), None), ("Alt+T", tr("Vettorizza l'immagine selezionata"), "trace"),
        ]),
        (tr("Disponi"), [
            ("Alt+N", tr("Ottimizza lo spazio (nesting): i pezzi si sistemano sul materiale con il minimo spreco"), "nest"),
        ]),
        (tr("Piani di lavoro"), [
            (tr("Ctrl+PagSu / Ctrl+PagGiù"), tr("Piano precedente / successivo"), "plate_prev"),
            (tr("Ctrl+{0}+N", sh), tr("Nuovo piano di lavoro"), "plate_new"),
            (tr("Ctrl+{0}+O", sh), tr("Vista d'insieme dei piani"), None),
            (tr("Doppio clic su una linguetta"), tr("Rinomina il piano"), None),
            (tr("Tasto destro su una linguetta"), tr("Sposta qui la selezione, duplica, elimina"), None),
        ]),
        (tr("Materiali e livelli"), [
            ("Ctrl+M", tr("Libreria materiali (applica al livello selezionato)"), "materials"),
            (tr("Laser → Test materiale"), tr("Griglia di prova di velocità e potenza sul tuo materiale"), None),
            (tr("Doppio clic nella tabella dei livelli"), tr("Modifica nome, modalità, velocità, potenza o passate"), None),
            (tr("Tasto destro su un livello"), tr("Altre opzioni"), None),
        ]),
        (tr("Laser"), [
            (tr("Ctrl+Invio"), tr("Avvia il lavoro"), "start"), (tr("Ctrl+Spazio"), tr("Pausa / riprendi"), "pause"),
            (tr("Ctrl+Pausa o {0}+Esc", sh), tr("Stop"), "stop"), (tr("Ctrl+{0}+F", sh), tr("Contorno"), "frame"),
            (tr("Ctrl+{0}+K", sh), tr("Verifica il lavoro"), "verify"), ("Alt+P", tr("Anteprima"), "preview"),
            (tr("Laser → Riconosci la macchina"), tr("Porte USB, driver e profilo adattato alla scheda collegata"), None),
        ]),
        (tr("Anteprima del lavoro"), [
            (tr("Rotella"), tr("Zoom verso il cursore"), None), (tr("Trascina"), tr("Sposta"), None),
            (tr("Doppio clic o 0"), tr("Adatta alla finestra"), None),
        ]),
        (tr("Interfaccia Banco"), [
            (tr("Ctrl+F o F3"), tr("Cerca un comando"), None),
            (tr("Ctrl+{0}+W", sh), tr("Apre o chiude l'Officina"), None),
            (tr("Tasto destro sul piano"), tr("Menu radiale"), None),
            (tr("Durante l'incisione"), tr("Pausa e Stop restano sempre nello stesso posto, in basso al centro"), None),
        ]),
        (tr("Guida"), [
            ("F1", tr("Questo elenco"), "shortcuts"),
            (tr("{0}+F1, o il pulsante ? in alto a destra", sh), tr("Passa il mouse su un comando per leggerne "
                                                                    "descrizione e opzioni; Esc esce"), None),
        ]),
    ]


def to_html(query=""):
    """Le sezioni in HTML: una scorciatoia per riga, il tasto in grassetto. query: mostra solo le righe che la
    contengono (nel tasto o nella descrizione), senza distinguere maiuscole e minuscole."""
    q = (query or "").strip().lower()
    out = []
    n = 0
    for title, rows in sections():
        keep = [(k, d) for k, d, _a in rows if not q or q in k.lower() or q in d.lower() or q in title.lower()]
        if not keep:
            continue
        out.append(f"<h3 style='margin:14px 0 4px 0; color:{C['accent_hi']};'>{html.escape(title)}</h3>"
                   "<table cellspacing='0' cellpadding='3' width='100%'>")
        for k, d in keep:
            n += 1
            out.append(f"<tr><td width='38%' valign='top'><b>{html.escape(k)}</b></td>"
                       f"<td valign='top'>{html.escape(d)}</td></tr>")
        out.append("</table>")
    if not n:
        out.append(f"<p>{html.escape(tr('Nessuna scorciatoia contiene «{0}».', query))}</p>")
    return "".join(out), n


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Scorciatoie da tastiera"))
        self.resize(640, 640)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Cerca")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("un tasto o un comando, per esempio «nodi» o «Ctrl+Z»"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        v.addLayout(top)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        v.addWidget(self.view, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        bb.accepted.connect(self.close)
        v.addWidget(bb)
        self.count = 0
        self.refresh()
        self.search.setFocus(Qt.OtherFocusReason)

    def refresh(self, *_):
        text, self.count = to_html(self.search.text())
        self.view.setHtml(text)
