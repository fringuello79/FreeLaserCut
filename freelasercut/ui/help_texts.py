# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Testi della guida contestuale (pulsante "?" / Maiusc+F1).

Ogni voce: chiave -> (titolo, descrizione, [(opzione, spiegazione), ...]).
Le chiavi sono le stesse delle azioni della finestra principale (es. "frame", "offset"), "tool:<nome>"
per gli strumenti, e prefissi per i controlli dei pannelli ("num:", "layers:", "cs:", "mode:" ...).
Un controllo senza voce qui viene descritto lo stesso, partendo dal suo suggerimento e dalle sue opzioni.
Nessuna dipendenza da Qt: il modulo si può verificare anche senza interfaccia.
"""
from freelasercut.i18n import tr  # noqa: E402

MODE_HELP = [
    (tr("Linea"), tr("il laser segue il contorno delle forme: tagli e incisioni a filo")),
    (tr("Riempimento"), tr("righe parallele riempiono l'interno delle forme chiuse: scritte e loghi pieni")),
    (tr("Riempimento offset"), tr("riempie con contorni concentrici che seguono la forma: bordi più puliti, meno salti")),
    (tr("Immagine"), tr("incisione di foto e bitmap pixel per pixel, con il metodo di retinatura scelto")),
]

DITHER_HELP = [
    (tr("Scala di grigi"), tr("la potenza varia per ogni pixel fra minima e massima: ottima sui laser a diodo")),
    (tr("Soglia"), tr("solo bianco o nero: per loghi e disegni al tratto")),
    ("Floyd–Steinberg", tr("diffusione dell'errore, morbida e senza trame")),
    (tr("Jarvis"), tr("diffusione su un'area più ampia: di solito la migliore per le foto")),
    (tr("Stucki"), tr("simile a Jarvis, un po' più nitida")),
    (tr("Atkinson"), tr("mantiene i dettagli, schiarisce le ombre")),
    (tr("Ordinato (Bayer)"), tr("trama regolare: utile per tarare la correzione del punto")),
    (tr("Mezzetinte (retino)"), tr("punti che crescono con lo scuro, effetto giornale")),
]

HELP = {
    # ------------------------------------------------------------------ file
    "new": (tr("Nuovo progetto"), tr("Chiude il progetto aperto (chiede se salvarlo) e ne apre uno vuoto."), None),
    "open": (tr("Apri"), tr("Apre un progetto FreeLaserCut (.flcut, anche i vecchi .fbrn di Freeburn) o LightBurn (.lbrn2, .lbrn) con forme, livelli e impostazioni."), None),
    "save": (tr("Salva"), tr("Salva il progetto. La prima volta chiede nome e cartella."), None),
    "save_as": (tr("Salva con nome"), tr("Salva una copia del progetto con un altro nome."), None),
    "import": (tr("Importa"), tr("Aggiunge al progetto aperto disegni e immagini: SVG, DXF, PNG, JPG, BMP e progetti LightBurn. "
               "Puoi anche trascinare i file sulla tela."), None),
    "export": (tr("Esporta SVG"), tr("Salva il disegno come SVG, da aprire in Inkscape, Illustrator o altri programmi."), None),
    "save_gcode": (tr("Salva G-code"), tr("Scrive il lavoro in un file G-code (.gcode/.nc) da eseguire dopo o su un'altra macchina."), None),
    "run_file": (tr("Esegui un file G-code"), tr("Invia alla macchina un file G-code già pronto, con anteprima e verifica."), None),
    "quit": (tr("Esci"), tr("Chiude FreeLaserCut. Se c'è un lavoro in corso chiede conferma."), None),
    # ------------------------------------------------------------------ modifica
    "undo": (tr("Annulla"), tr("Torna indietro di un'azione. La cronologia è illimitata; il menu mostra il nome dell'azione."), None),
    "redo": (tr("Ripeti"), tr("Rifà l'azione appena annullata."), None),
    "cut": (tr("Taglia"), tr("Sposta la selezione negli appunti."), None),
    "copy": (tr("Copia"), tr("Copia la selezione negli appunti."), None),
    "paste": (tr("Incolla"), tr("Incolla gli appunti dove si trova il cursore sulla tela."), None),
    "paste_in_place": (tr("Incolla sul posto"), tr("Incolla gli appunti alle stesse coordinate dell'originale."), None),
    "duplicate": (tr("Duplica"), tr("Crea una copia della selezione sovrapposta all'originale."), None),
    "delete": (tr("Elimina"), tr("Cancella le forme selezionate (si annulla con Ctrl+Z)."), None),
    "select_all": (tr("Seleziona tutto"), tr("Seleziona tutte le forme non bloccate."), None),
    "invert_sel": (tr("Inverti selezione"), tr("Seleziona ciò che non era selezionato e viceversa."), None),
    "sel_open": (tr("Seleziona forme aperte"), tr("Trova i tracciati non chiusi."), None),
    "sel_open_fill": (tr("Forme aperte sui riempimenti"), tr("Trova i tracciati aperti sui livelli Riempimento: è il motivo più "
                      "comune di un riempimento che non incide nulla."), None),
    "sel_contained": (tr("Aggiungi le forme contenute"), tr("Aggiunge alla selezione le forme che stanno dentro quella selezionata."), None),
    "to_path": (tr("Converti in tracciato"), tr("Trasforma testi, rettangoli, ellissi e forme parametriche in tracciati liberi, "
                "modificabili nodo per nodo. I parametri (testo, raggio, lati) si perdono."), None),
    "trace": (tr("Vettorizza immagine"), tr("Trasforma una foto o un disegno in tracciati."),
              [(tr("Contorno"), tr("i bordi delle zone scure diventano forme chiuse")),
               (tr("Linea centrale"), tr("scritte a mano e disegni al tratto diventano una linea sola"))]),
    "close_paths": (tr("Chiudi tracciati"), tr("Chiude i tracciati i cui estremi sono vicini, entro la tolleranza scelta."), None),
    "join": (tr("Unisci estremi"), tr("Unisce in un solo tracciato i segmenti che si toccano."), None),
    "break": (tr("Scomponi"), tr("Divide un tracciato nelle sue parti separate."), None),
    "reverse": (tr("Inverti direzione di taglio"), tr("Il laser percorrerà la forma nel verso opposto."), None),
    "duplicates": (tr("Elimina duplicati"), tr("Cancella le forme identiche sovrapposte, che il laser brucerebbe due volte."), None),
    "offset": (tr("Offset forme"), tr("Crea un contorno parallelo a distanza fissa."),
               [(tr("Fuori / Dentro / Entrambi"), tr("da che lato nasce il nuovo contorno")),
                ("Angoli vivi, tondi o smussati", tr("come vengono raccordati gli spigoli"))]),
    "lock": (tr("Blocca"), tr("Le forme bloccate non si spostano né si modificano per sbaglio."), None),
    "unlock": (tr("Sblocca"), tr("Rende di nuovo modificabili le forme bloccate."), None),
    # ------------------------------------------------------------------ disponi
    "group": (tr("Raggruppa"), tr("Unisce la selezione in un gruppo che si sposta come un oggetto solo."), None),
    "ungroup": (tr("Separa"), tr("Scioglie il gruppo selezionato (un livello di annidamento per volta)."), None),
    "weld": (tr("Salda"), tr("Fonde forme sovrapposte in un unico contorno: niente linee interne bruciate due volte."), None),
    "union": (tr("Unione"), tr("Somma due forme chiuse in una."), None),
    "difference": (tr("Differenza"), tr("Toglie dalla prima forma selezionata la seconda."), None),
    "intersection": (tr("Intersezione"), tr("Tiene solo la parte comune alle due forme."), None),
    "xor": (tr("Esclusione"), tr("Tiene le parti non comuni alle due forme."), None),
    "flip_h": (tr("Rifletti orizzontalmente"), tr("Specchia la selezione destra-sinistra."), None),
    "flip_v": (tr("Rifletti verticalmente"), tr("Specchia la selezione sopra-sotto."), None),
    "rot_cw": ("Ruota 90° orario", tr("Ruota la selezione di 90° in senso orario."), None),
    "rot_ccw": ("Ruota 90° antiorario", tr("Ruota la selezione di 90° in senso antiorario."), None),
    "align_left": (tr("Allinea a sinistra"), tr("Allinea i bordi sinistri all'ultima forma selezionata (o a quella bloccata)."), None),
    "align_right": (tr("Allinea a destra"), tr("Allinea i bordi destri all'ultima forma selezionata."), None),
    "align_top": (tr("Allinea in alto"), tr("Allinea i bordi superiori all'ultima forma selezionata."), None),
    "align_bottom": (tr("Allinea in basso"), tr("Allinea i bordi inferiori all'ultima forma selezionata."), None),
    "align_hcenter": (tr("Centra in orizzontale"), tr("Allinea i centri sulla stessa verticale."), None),
    "align_vcenter": (tr("Centra in verticale"), tr("Allinea i centri sulla stessa orizzontale."), None),
    "align_center": (tr("Centra i centri"), tr("Sovrappone i centri delle forme selezionate."), None),
    "dist_h": (tr("Distribuisci in orizzontale"), tr("Spazi uguali fra le forme, da sinistra a destra."), None),
    "dist_v": (tr("Distribuisci in verticale"), tr("Spazi uguali fra le forme, dal basso in alto."), None),
    "dist_hc": (tr("Distribuisci centri orizzontali"), tr("Centri a distanza uguale in orizzontale."), None),
    "dist_vc": (tr("Distribuisci centri verticali"), tr("Centri a distanza uguale in verticale."), None),
    "same_w": (tr("Stessa larghezza"), tr("Dà a tutte la larghezza dell'ultima forma selezionata."), None),
    "same_h": (tr("Stessa altezza"), tr("Dà a tutte l'altezza dell'ultima forma selezionata."), None),
    "nest": (tr("Ottimizza lo spazio (nesting)"), tr("Sistema i pezzi sul materiale con il minimo spreco, usando la loro sagoma "
             "vera. Materiale: piano intero, rettangolo su misura o un contorno disegnato sul livello T1 (anche un avanzo "
             "irregolare). Si scelgono distanza tra i pezzi, margine e rotazioni; le forme che si toccano restano unite."),
             [(tr("Distanza tra i pezzi"), tr("almeno lo spessore del taglio")), (tr("Rotazioni"), tr("nessuna con venature o foto"))]),
    "grid_array": (tr("Serie a griglia"), tr("Copie in righe e colonne, con spaziatura, sfalsamento e numerazione automatica "
                   "dei testi variabili."), None),
    "circ_array": (tr("Serie circolare"), "Copie disposte in cerchio, ruotate o no.", None),
    "along_path": (tr("Copia lungo un tracciato"), tr("Ripete la forma lungo un tracciato (prima la forma, poi il tracciato)."), None),
    "front": (tr("Porta in primo piano"), tr("Cambia solo l'ordine di disegno sulla tela, non l'ordine di taglio."), None),
    "back": (tr("Porta in fondo"), tr("Cambia solo l'ordine di disegno sulla tela, non l'ordine di taglio."), None),
    # ------------------------------------------------------------------ vista
    "zoom_in": (tr("Ingrandisci"), tr("Ingrandisce la tela. Anche con la rotella del mouse, verso il cursore."), None),
    "zoom_out": (tr("Riduci"), tr("Rimpicciolisce la tela."), None),
    "fit": (tr("Adatta al piano"), tr("Mostra tutto il piano di lavoro."), None),
    "fit_sel": (tr("Adatta alla selezione"), tr("Ingrandisce sulla selezione."), None),
    "filled": (tr("Vista riempita"), tr("Mostra i riempimenti pieni invece del solo contorno."), None),
    "grid": (tr("Griglia"), tr("Mostra o nasconde la griglia del piano."), None),
    "snap_grid": (tr("Aggancia alla griglia"), tr("Mentre disegni o sposti, i punti si attaccano alla griglia. Alt lo sospende."), None),
    "snap_obj": (tr("Aggancia agli oggetti"), tr("I punti si attaccano a nodi, centri e punti medi delle altre forme."), None),
    "light_bed": (tr("Piano chiaro"), tr("Sfondo del piano chiaro o scuro."), None),
    "dither_prev": (tr("Mostra il dithering"), tr("Sulla tela le immagini appaiono già retinate come verranno incise."), None),
    # ------------------------------------------------------------------ laser
    "connect": (tr("Connetti / disconnetti"), tr("Collega FreeLaserCut al laser sulla porta scelta. Una porta USB la può usare un "
                "solo programma per volta: chiudi LightBurn o LaserGRBL."), None),
    "home": (tr("Homing"), tr("La testa va ai finecorsa e azzera la posizione: piano, testa e camera usano le stesse coordinate."), None),
    "unlock_m": ("Sblocca macchina ($X)", tr("Toglie l'allarme senza homing. Usalo solo se sai dove si trova la testa."), None),
    "frame": (tr("Contorno"), tr("La testa percorre il perimetro del lavoro, per vedere dove inciderà."),
              [(tr("Con il puntino"), tr("laser a potenza minima: vedi la traccia sul materiale (predefinito)")),
               (tr("Stretto"), tr("segue la sagoma esterna invece del rettangolo")),
               (tr("A laser spento"), "solo movimento")]),
    "verify": (tr("Verifica il lavoro"), tr("Fa controllare il G-code alla scheda in modalità di prova ($C), senza muovere nulla."), None),
    "start": (tr("Avvia il lavoro"), tr("Controlli preliminari, riepilogo, verifica nella scheda e poi partenza."), None),
    "pause": (tr("Pausa / riprendi"), tr("Ferma la testa a metà lavoro e la fa ripartire dallo stesso punto."), None),
    "stop": (tr("Stop"), tr("Interrompe il lavoro e spegne il laser. Non si può riprendere (serve un nuovo avvio)."), None),
    "preview": (tr("Anteprima"), tr("Simulazione del lavoro con tempo stimato, percorsi colorati per potenza e resa realistica "
                "sul materiale. Rotella = zoom, trascina = sposta."), None),
    "exact_shape": (tr("Forma con misure esatte"), tr("Crea rettangolo, cerchio, poligono o forma della galleria con larghezza, "
                    "altezza e centro precisi."), None),
    "variables": (tr("Testo variabile"), tr("Numeri di serie, data e ora, campi da un file CSV dentro i testi."), None),
    "materials": (tr("Libreria materiali"), tr("Valori pronti per il Longer B1 40W (incisioni e tagli) più le tue voci: "
                  "scegli il materiale e applicalo al livello."), None),
    "material_test": (tr("Test materiale"), tr("Incide una griglia potenza × velocità con le etichette per trovare i valori giusti."), None),
    "identify": (tr("Riconosci la macchina"), tr("Elenca le porte USB con il chip e il driver, interroga la scheda ($I, $$), "
                 "riconosce firmware, area di lavoro e buffer e prepara il profilo giusto. Da qui puoi anche installare "
                 "un driver USB che hai sul PC."), None),
    "help_mode": (tr("Che cos'è?"), tr("Attiva la guida: passa il mouse su un comando, un campo o un menu per leggerne la "
                  "descrizione e le opzioni. I clic non eseguono nulla. Esc o di nuovo \"?\" per uscire."), None),
    "shortcuts": (tr("Scorciatoie da tastiera"), tr("Elenco completo dei tasti rapidi."), None),
    "about": (tr("Informazioni"), tr("Versione di FreeLaserCut, autore e licenze."), None),
    "support": (tr("Sostieni FreeLaserCut"), tr("Mostra come contribuire allo sviluppo con una donazione volontaria "
                "tramite GitHub Sponsors o PayPal. Il programma resta completo e gratuito: la donazione non sblocca niente."), None),
    "claude": (tr("Collega a Claude"), tr("Installa l'estensione per Claude: potrai chiedere in chat di disegnare, impostare "
               "livelli e preparare lavori."), None),
    # ------------------------------------------------------------------ strumenti
    "tool:select": (tr("Selezione (V)"), tr("Clic per scegliere una forma, trascina per selezionare un'area."),
                    [(tr("Da sinistra a destra"), tr("prende solo ciò che è tutto dentro")),
                     (tr("Da destra a sinistra"), tr("prende anche ciò che tocca")),
                     (tr("Maiusc / Ctrl"), "aggiunge / alterna")]),
    "tool:nodes": (tr("Modifica nodi (N)"), tr("Sposta nodi e maniglie delle curve."),
                   [("D", "elimina nodo"), ("C / S", "angolo / morbido"), ("B", "spezza"), ("L", "raddrizza"),
                    ("M", tr("nodo nel punto medio"))]),
    "tool:line": (tr("Linee e curve (L)"), tr("Ogni clic aggiunge un nodo; clic e trascina crea una curva. Clic sul primo "
                  "nodo per chiudere, tasto destro o Esc per finire."), None),
    "tool:rect": (tr("Rettangolo (R)"), tr("Trascina per disegnare. Maiusc = quadrato, Ctrl = dal centro. Raggio degli angoli "
                  "nelle Proprietà."), None),
    "tool:ellipse": (tr("Ellisse e cerchio (E)"), tr("Maiusc = cerchio, Ctrl = dal centro."), None),
    "tool:polygon": (tr("Poligono (P)"), tr("Poligono regolare; il numero di lati si cambia nelle Proprietà."), None),
    "tool:star": (tr("Stella (S)"), tr("Punte, rapporto fra i raggi e curvatura nelle Proprietà."), None),
    "tool:special": (tr("Galleria forme (F)"), tr("22 forme parametriche: frecce, cuore, scudo, medaglia, ingranaggio, "
                     "targa, etichetta e altre, modificabili anche dopo."), None),
    "tool:text": (tr("Testo (T)"), tr("Clic sulla tela e scrivi. Font di Windows e font a linea singola, testo curvo e variabili."), None),
    "tool:measure": (tr("Misura (M)"), tr("Passa sopra una forma per leggerne le misure, trascina per misurare una distanza."), None),
    "tool:position": (tr("Posiziona laser (Q)"), tr("Clic sulla tela: la testa va in quel punto. Serve l'homing."), None),
    "canvas": (tr("Tela"), tr("Il piano di lavoro in scala reale. Rotella = zoom verso il cursore, tasto centrale o barra "
               "spaziatrice + trascina = sposta la vista. Il comportamento del clic dipende dallo strumento attivo."), None),
    # ------------------------------------------------------------------ barra numerica
    "num:anchor": (tr("Punto di riferimento"), tr("Quale punto della selezione usano X, Y, la scala e la rotazione: "
                   "uno dei 4 angoli, il centro di un lato o il centro."), None),
    "num:x": (tr("X (mm)"), tr("Posizione orizzontale del punto di riferimento. Accetta calcoli e unità: 120/3, 2in, 5cm, +10."), None),
    "num:y": (tr("Y (mm)"), tr("Posizione verticale del punto di riferimento. Accetta calcoli e unità."), None),
    "num:w": (tr("Larghezza (mm)"), tr("Larghezza della selezione. Con il lucchetto chiuso anche l'altezza cambia in proporzione. "
              "Accetta calcoli: *2 raddoppia, /3 divide."), None),
    "num:h": (tr("Altezza (mm)"), tr("Altezza della selezione. Con il lucchetto chiuso anche la larghezza cambia in proporzione."), None),
    "num:lock": (tr("Blocca proporzioni"), tr("Chiuso: larghezza e altezza cambiano insieme. Aperto: si cambiano separatamente."), None),
    "num:rot": (tr("Rotazione (gradi)"), tr("Angolo della forma intorno al punto di riferimento. Positivo = antiorario."), None),
    "num:layer": (tr("Livello della selezione"), tr("Sposta le forme selezionate su un altro livello colore (e quindi su altre "
                  "impostazioni di taglio). Senza selezione sceglie il livello dei nuovi disegni."),
                  [("C00…C29", tr("livelli incisi, ognuno con le sue impostazioni")),
                   ("T1", "livello strumenti: guide e contorni mai incisi")]),
    "num:center": (tr("Centra sul piano"), tr("Porta la selezione al centro del piano di lavoro."), None),
    # ------------------------------------------------------------------ livelli
    "layers:table": (tr("Livelli"), tr("Un livello per ogni colore usato nel disegno, nell'ordine in cui vengono lavorati "
                     "(dall'alto in basso). Doppio clic su una cella per modificarla, tasto destro per il menu."),
                     [(tr("Livello"), tr("nome (doppio clic per rinominare)")),
                      (tr("Modalità"), "Linea, Riempimento, Riempimento offset, Immagine"),
                      ("mm/min", "velocità"), (tr("Pot. %"), "potenza massima"), ("×", "passate"),
                      (tr("Inc."), tr("se tolto il livello non viene inciso")), (tr("Vis."), tr("visibile sulla tela")),
                      (tr("Aria"), "air assist acceso")]),
    "layers:col:0": (tr("Nome del livello"), tr("Doppio clic per rinominare. Vuoto = nome automatico C00…C29."), None),
    "layers:col:1": (tr("Modalità"), tr("Come il laser lavora le forme del livello."), MODE_HELP),
    "layers:col:2": (tr("Velocità (mm/min)"), tr("Avanzamento della testa mentre il laser è acceso. 6000 mm/min = 100 mm/s."), None),
    "layers:col:3": (tr("Potenza massima (%)"), tr("Percentuale della potenza del laser. Con M4 (predefinito) si riduce da sola "
                     "in curva e in accelerazione."), None),
    "layers:col:4": (tr("Passate"), tr("Quante volte il livello viene ripetuto: per tagliare spessori maggiori."), None),
    "layers:col:5": (tr("Incidi"), tr("Spunta tolta = il livello resta nel progetto ma non viene inciso né mostrato in anteprima."), None),
    "layers:col:6": (tr("Visibile"), tr("Mostra o nasconde le forme del livello sulla tela. Non cambia cosa viene inciso."), None),
    "layers:col:7": (tr("Aria"), tr("Accende l'air assist durante questo livello (consigliato per i tagli)."), None),
    "layers:up": (tr("Sposta su"), tr("Il livello viene lavorato prima."), None),
    "layers:down": (tr("Sposta giù"), tr("Il livello viene lavorato dopo."), None),
    "layers:select": (tr("Seleziona le forme"), tr("Seleziona sulla tela tutte le forme del livello."), None),
    "layers:settings": (tr("Tutte le impostazioni"), tr("Apre l'editor completo del livello: kerf, ponticelli, interlinea, "
                        "angolo, overscan, metodo immagine e altro."), None),
    "layers:sort": (tr("Tagli per ultimi"), tr("Ordina i livelli: prima incisioni e riempimenti, per ultime le linee di taglio, "
                    "così i pezzi non cadono prima di essere incisi."), None),
    # ------------------------------------------------------------------ impostazioni di taglio
    "cs:mode": (tr("Modalità"), tr("Come il laser lavora le forme del livello."), MODE_HELP),
    "cs:speed": (tr("Velocità"), tr("In mm/min (accanto vedi l'equivalente in mm/s). Più veloce = più chiaro."), None),
    "cs:power_max": (tr("Potenza massima"), tr("Percentuale della potenza del laser usata per le parti più scure o per il taglio."), None),
    "cs:power_min": (tr("Potenza minima"), tr("Nelle immagini in scala di grigi è la potenza dei bianchi; altrimenti di solito 0."), None),
    "cs:passes": (tr("Passate"), tr("Quante volte ripetere il livello."), None),
    "cs:interval": (tr("Interlinea"), tr("Distanza fra le righe di un riempimento o di un'immagine. Ideale: righe che si "
                    "toccano appena (circa lo spot del laser, 0,08–0,1 mm sul B1 40W)."), None),
    "cs:dither": (tr("Metodo immagine"), tr("Come i grigi della foto diventano punti incisi."), DITHER_HELP),
}


def lookup(key):
    """(titolo, descrizione, opzioni) oppure None."""
    return HELP.get(key) if key else None
