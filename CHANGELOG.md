# Novità di FreeLaserCut

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
