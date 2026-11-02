# Novità di FreeLaserCut

## 0.10.3 — 02/11/2026
Dalle note di chi lo usa:
- **Suggerimenti dei comandi senza scatti:** passando su un comando, il suggerimento compariva, spariva un attimo e ricompariva intero (era la dissolvenza di Windows, che sui PC lenti si vede bene). Ora compare subito intero, dopo 350 ms invece di 700; anche menu e tendine si aprono senza animazioni.
- **Ottimizza lo spazio (nesting)** nella barra principale della finestra classica, accanto ai comandi per allineare e distribuire.
- **Piano più reattivo**, soprattutto sui PC lenti, con lo stesso identico aspetto:
  - griglia e righelli non si ricalcolano più a ogni movimento del mouse, ma solo quando cambiano zoom, vista o dimensioni;
  - i contorni delle forme (in particolare dei testi) si calcolano una volta per modifica, non a ogni ridisegno;
  - passando col mouse con lo strumento Selezione si aggiornano solo i righelli: su un piano con una foto e dieci testi, da circa 18 ms a meno di 4 ms per movimento.
- Nuova prova automatica `tests/test_v103.py`: il piano deve restare identico, pixel per pixel, al disegno da zero in ogni situazione.

## 0.10.2 — 02/11/2026
Dalle segnalazioni di chi lo usa:
- **Corretto:** chiusa la finestra *Anteprima*, la foto restava coperta dall'arancione del percorso finché non la si spostava. Ora il percorso sparisce alla chiusura (resta solo durante un lavoro in corso).
- **Zoom in *Prepara foto***: sull'anteprima *Come verrà incisa* si ingrandisce con la rotella, con i pulsanti − / + / *Tutta la foto* o con un doppio clic, e ci si sposta trascinando.
  - Ingrandendo, la zona visibile si ricalcola con i **punti veri** alla risoluzione del livello, e i punti restano netti: così si confrontano bene i metodi di incisione (Jarvis, Floyd–Steinberg, Stucki, mezzetinte…).
  - Lo zoom resta cambiando metodo o regolazioni, e funziona anche nella scheda *Linee e riempimento*.
- Nuova prova automatica `tests/test_v102.py` (27 controlli).

## 0.10.1 — 01/11/2026
Avvio più robusto, dalle segnalazioni di chi lo ha provato:
- **Corretto:** se qualcosa andava storto all'avvio, il messaggio d'errore poteva restare nascosto dietro la schermata con il logo, che rimaneva sempre in primo piano. Ora la schermata d'avvio si chiude prima di ogni messaggio d'errore e non sta più sopra le altre finestre; se la finestra principale non si apre, FreeLaserCut mostra l'errore, lo scrive in `flc.log` ed esce in modo pulito.
- **Istanza unica:** aprire FreeLaserCut quando è già aperto porta in primo piano la finestra esistente (anche se era ridotta a icona) invece di aprirne un'altra copia. Un progetto aperto con doppio clic arriva nella finestra già aperta.
- **Scelta dell'interfaccia** al primo avvio: il doppio clic su una scheda vale come *Inizia*; il pulsante dice quale interfaccia parte (*Inizia con Banco* / *Inizia con Classica*) ed è più evidente.
- **Installatore:**
  - controlla se FreeLaserCut è aperto, sia quando installa sia quando disinstalla, e chiede di chiuderlo;
  - messaggi chiari se i file della versione precedente non si possono togliere o scrivere (programma aperto, antivirus);
  - la pagina della cartella spiega dove si installa e perché non va scelto «Programmi»; se la cartella scelta non è scrivibile lo dice subito.
- Nuovo collegamento **FreeLaserCut (diagnostica)** nel menu Start: avvia il programma con una console che resta aperta e mostra gli eventuali errori.
- Nuova prova automatica `tests/test_v101.py` (30 controlli).

## 0.10.0 — 01/11/2026
- **Prepara foto** (*Strumenti → Prepara foto…*, Ctrl+Alt+F, oppure il pulsante nel pannello Proprietà di un'immagine):
  - ritaglio trascinando sull'anteprima, rotazione e specchio;
  - **sfondo rimosso** in automatico (con tolleranza regolabile), riduzione del rumore, livelli automatici, contrasto locale, nitidezza;
  - maschera a ovale o a rettangolo arrotondato, con bordo sfumato;
  - **materiali pronti** (legno chiaro e scuro, ardesia, cuoio, carta, alluminio anodizzato, scala di grigi) che impostano retinatura, DPI, negativo, luminosità e contrasto;
  - anteprima di come verrà l'incisione, con i punti della retinatura;
  - **Prova foto**: 4 tasselli da 30 mm della parte centrale con retinature diverse, accanto alla foto, per scegliere sul materiale vero;
  - la foto originale resta nel progetto: si può riaprire *Prepara foto* e cambiare tutto.
- **Foto → linee e riempimento** (scheda *Linee e riempimento* di Prepara foto): la foto diventa vettoriale e si adatta da sola ai suoi toni:
  - da 1 a 4 fasce di tono in riempimento, ognuna su un livello con potenza crescente dalla più chiara alla più scura;
  - in più, a scelta, il contorno delle zone scure e le linee dei dettagli (bordi netti della foto);
  - dettaglio regolabile, anteprima prima di confermare.
- **Corretto (issue #2):** con una foto grande l'anteprima e la preparazione del lavoro duravano decine di secondi e FreeLaserCut sembrava bloccato. Ora:
  - il G-code si legge una volta sola e l'anteprima si prepara circa 4 volte più in fretta e si disegna sul piano oltre 20 volte più in fretta;
  - le anteprime con moltissimi punti si disegnano come immagine e il piano resta fluido;
  - una foto senza dimensioni reali si importa larga 100 mm invece che alla misura in pixel;
  - prima di preparare un lavoro con oltre 5 milioni di punti, FreeLaserCut chiede conferma e suggerisce di ridurre i DPI.
- Nuova prova automatica `tests/test_v10.py` (velocità, anteprime, Prepara foto, salvataggio, annulla); il G-code di linee e riempimenti è identico alla 0.9.

## 0.9.2 — 01/11/2026
- **Corretto (sicurezza):** il lavoro risultava finito appena la scheda aveva ricevuto l'ultima riga, mentre eseguiva ancora gli ultimi movimenti dal suo buffer: per qualche secondo il laser tagliava con *Stop* e *Pausa* già spenti. Ora il lavoro finisce solo quando la macchina è davvero ferma; se nel frattempo scatta un allarme, il lavoro risulta interrotto.
- **Corretto:** dopo un lavoro, eliminando le forme restava sul piano la traccia arancione del laser. Ora la traccia e l'anteprima si cancellano a ogni modifica del disegno.
- Nuova prova automatica del flusso completo sul simulatore (`tests/test_v091.py`): connessione, homing, verifica, lavoro, fine a testa ferma, eliminazione e annulla, in Classica e nel Banco.

## 0.9.1 — 01/11/2026
- **Corretto:** con la macchina connessa la pastiglia di stato accanto a *Connetti* si allargava a ogni aggiornamento (più volte al secondo) e trascinava con sé il pannello Laser: i pulsanti *Avvia*, *Contorno* e *Anteprima* finivano fuori dalla finestra.

## 0.9.0 — 31/10/2026
- **Codici QR e a barre** (*Strumenti → Codice QR o a barre…*, Ctrl+Alt+Q):
  - tipi: QR, Code 128, EAN-13, EAN-8, UPC-A e Code 39;
  - come forme vettoriali pulite da incidere in riempimento: FreeLaserCut sceglie da solo un livello in riempimento;
  - opzioni: zona di rispetto, correzione d'errore del QR, numero leggibile sotto le barre, versione **in negativo** per i materiali che il laser schiarisce;
  - con le variabili (`{n}`, `{data}`, colonne CSV) ogni copia di una serie ha il suo codice;
  - restano modificabili (pannello Proprietà → *Modifica codice…*).
- **Testo su tracciato** (*Strumenti → Testo su tracciato…*, Ctrl+Alt+T):
  - seleziona un testo e una linea o una forma: il testo ne segue la curva;
  - si regolano posizione, allineamento, distanza dalla curva e verso;
  - il testo resta modificabile.
- **Rotativo** (*Laser → Rotativo…*) per bicchieri, borracce e cilindri, a rulli o a mandrino:
  - FreeLaserCut scala l'asse Y e corregge la velocità sulla superficie;
  - c'è la prova "un giro" per la taratura;
  - il contorno segue il rotativo;
  - quando è attivo, un avviso resta nella barra di stato.
- **Nesting su più pannelli**: i pezzi che non entrano continuano su altri pannelli uguali, affiancati, ognuno col suo contorno e il suo numero sul livello T1.
- **Linee di taglio comuni**:
  - nel nesting i pezzi vengono accostati e i lati in comune si tagliano una volta sola;
  - il nuovo comando *Disponi → Unisci le linee di taglio comuni* fa lo stesso su qualsiasi selezione, per esempio una serie a griglia con distanza 0.
- **Firma dell'installatore e Microsoft Store** (preparazione):
  - firma facoltativa nell'installatore NSIS;
  - workflow GitHub Actions che costruisce l'installatore dal codice pubblico (richiesto da SignPath Foundation);
  - pacchetto MSIX per il Microsoft Store (`build/prepara_msix.py`);
  - guida in `build/FIRMA-E-STORE.md`.
- Pannello Laser: l'etichetta "Disconnesso" non si taglia più.

## 0.8.0 — 31/10/2026
- **Ottimizza lo spazio (nesting)** — *Disponi → Ottimizza lo spazio*, **Alt+N**, nel Banco anche dalla barra contestuale e dal menu radiale. Sistema pezzi e gruppi sul materiale sprecandone il meno possibile:
  - usa la **sagoma vera** di ogni pezzo, non il rettangolo che lo contiene, e lo ruota se lo permetti (nessuna rotazione, solo 180°, 90°, 45° o 15°);
  - il materiale può essere il piano intero, un rettangolo su misura o **qualsiasi contorno disegnato sul livello T1**, anche un avanzo irregolare;
  - si scelgono distanza tra i pezzi e margine dal bordo. Le forme ferme sul piano vengono evitate, e un'incisione resta dentro il suo contorno di taglio anche senza raggruppare;
  - alla fine mostra il materiale usato e la resa in %; i pezzi che non entrano restano al loro posto, selezionati. Si annulla con Ctrl+Z.
- **Modelli di laser pronti**: Longer, Ortur, xTool, Atomstack, Sculpfun, Creality Falcon, Two Trees, Comgrow e qualsiasi laser GRBL generico. Si sceglie al primo avvio o da *Laser → Riconosci la macchina*, anche senza la macchina collegata; collegandola, i valori veri si rileggono dalla scheda.
- Il riconoscimento automatico associa anche gli altri produttori al modello giusto, usando l'area di lavoro letta dalla scheda.
- Pagina web del progetto in `docs/index.html` (GitHub Pages), con download, guida rapida e macchine supportate.

## 0.7.0 — 31/10/2026
- **Nuova interfaccia «Banco»** (predefinita): il piano di lavoro occupa tutto lo schermo e i comandi stanno dove servono.
  - **Strati a sinistra** come schede, nell'ordine di lavoro: clic per aprirne una e regolare modalità, velocità, potenza, passate, incisione e aria senza aprire finestre (Ctrl+Z annulla).
  - **«Dal disegno al pezzo»** a destra: disegno → strati e materiale → controllo → posizionamento, con lo stato di ogni passo. L'avvio richiede le due conferme di sicurezza e si **tiene premuto** un secondo.
  - **Isola degli strumenti** in basso, **barra contestuale** (misure, allinea, combina, serie…) accanto alla selezione.
  - **Ricerca di tutti i comandi** (Ctrl+F o F3): scrivi una parola, anche senza accenti, e premi Invio.
  - **Menu radiale** col tasto destro sul piano: 8 comandi su ciò che hai sotto il cursore.
  - **Cabina** durante l'incisione: tempo rimanente, ora di fine, velocità/potenza ±10% al volo, aria, Pausa e Stop grandi e sempre nello stesso posto; il disegno è bloccato finché il laser lavora.
  - **Officina** (Ctrl+Shift+W): laser, movimento, camera, macchina, console e tabella dei livelli in un cassetto; **con un secondo monitor si sposta da sola sull'altro schermo** (disattivabile).
- L'interfaccia di prima resta disponibile come **Classica**. Al primo avvio si sceglie quale usare; si cambia quando vuoi da **Impostazioni → Interfaccia** (nel Banco: pulsante ⚙ in alto a destra).
- Nuovo menu **Impostazioni**: interfaccia, lingua, Officina sul secondo monitor, opzioni di vista.
- Corretto: in inglese, spagnolo, francese e portoghese il comando *Annulla* (Ctrl+Z) compariva come "Cancel / Cancelar / Annuler".

## 0.6.0 — 31/10/2026
- **Interfaccia in 5 lingue**: English, Italiano, Español, Français, Português. Al primo avvio si usa la lingua di Windows (inglese se non è tra queste); si cambia da **Visualizza → Lingua / Language** e vale dal riavvio, che il programma propone subito.
- Anche i pulsanti standard delle finestre (OK, Annulla, Salva…) seguono la lingua scelta.
- Donazioni tramite **GitHub Sponsors** o **PayPal** (collegamento PayPal.Me): nel programma e nel repository non compare più nessun indirizzo email.
- La guida "?" dei comandi per ora resta in italiano.

## 0.5.2 — 31/10/2026
- Schermata d'avvio con il logo mentre il programma si carica ("Avvio in corso…", "Preparo il motore delle immagini…", "Apro il piano di lavoro…").
- Pulsante **♥ Sostieni FreeLaserCut** in alto a destra, nella barra dei menu.

## 0.5.1 — 31/10/2026
- Nuovo nome: **FreeLaserCut (FLC)**, prima *Freeburn*. Nuovo logo.
- Al primo avvio profili, materiali, calibrazione della camera e preferenze di Freeburn vengono copiati in FreeLaserCut.
- I progetti si salvano come `.flcut`; i vecchi `.fbrn` si aprono ancora.
- Avviso di sicurezza al primo avvio su un PC nuovo.
- Aiuto → Sostieni FreeLaserCut: contributo volontario allo sviluppo.
- Installatore per Windows con tutto incluso, senza permessi da amministratore.
- Licenza GNU GPL 3.0 o successiva.

## 0.5.0
- Barra numerica compatta, livelli modificabili direttamente in tabella, guida "?" su ogni comando, riconoscimento automatico della macchina e del driver USB, anteprima adattiva.

## 0.4
- Apertura dei progetti LightBurn (`.lbrn2`, `.lbrn`), galleria di 22 forme parametriche, collegamento a Claude, calibrazione della camera con bersagli incisi.

## 0.3
- Libreria materiali per il Longer B1 40W, test materiale, vettorizzazione delle immagini, testo variabile (date, numerazione, CSV) e testo curvo.

## 0.2
- Editor completo, livelli Linea / Riempimento / Immagine, verifica del G-code, pausa su errore, ripresa del lavoro, regolazioni durante il lavoro, anteprima.

## 0.1
- Connessione e invio dei lavori ai controller GRBL, simulatore del B1, profilo macchina letto dalla scheda, calibrazione della camera.
