# Prove automatiche di FreeLaserCut, per area

Generato da `tests/run_tests.py` (non modificare a mano): ogni suite sta nell'area della sua descrizione.
Suite: 264. Lancio completo: `python tests/run_tests.py`; una sola: `python tests/<file> [banco]`.

## Wi-Fi, rete e telefono (18)

- `test_v110.py`: Guardia fiamme, taratura da foto del test, controllo dal telefono
- `test_v120.py`: Laser in Wi-Fi, copie delle impostazioni della scheda, 39 modelli pronti
- `test_v181_camera.py`: Telecamera del Falcon A1 (USB, mai nera) e telecamere di rete
- `test_v1817_wifi.py`: Collegamento Wi-Fi del laser: procedura guidata, famiglie di schede, privacy della password
- `test_v1817_wifi.py` (Banco): Collegamento Wi-Fi del laser nell'interfaccia Banco
- `test_v190_telecamera.py`: Telecamera senza calibrazione e foto del piano dal telefono
- `test_v190_telecamera.py` (Banco): Telecamera senza calibrazione e foto dal telefono nell'interfaccia Banco
- `test_v190_wifi_registro.py`: Wi-Fi guidato: il registro viene salvato a fine procedura
- `test_v191_wifi.py`: Wi-Fi sul vero: telecamere lontane dalla porta del laser, scheda con «$wifi»
- `test_v191_wifi.py` (Banco): Wi-Fi sul vero nell'interfaccia Banco
- `test_v192_wifi.py`: Wi-Fi delle Longer: interruttore «$50», messaggi e attesa della scheda vera
- `test_v192_wifi.py` (Banco): Wi-Fi delle Longer nell'interfaccia Banco
- `test_v205_scatti_wifi.py`: PC lenti: misure della selezione, istantanee per Annulla e punti dell'aggancio senza fermare la finestra, scatti dei trascinamenti nel rapporto; Wi-Fi delle Makerbase: «Il laser non trova la rete»
- `test_v205_scatti_wifi.py` (Banco): PC lenti e Wi-Fi delle Makerbase nell'interfaccia Banco
- `test_v206_rapporti.py`: Rapporti del 18/11: punto di riferimento che resta dopo il riavvio, scritte del test materiali con potenza e velocità scelte e numeri arrotondati, invio prudente in Wi-Fi, schede che interrompono le risposte lunghe, lente molto grandangolare della camera della testa, tasto destro su una foto
- `test_v208_mac.py`: Versione per macOS (anteprima): pacchetto con permessi di camera e rete locale, avvio isolato, numba solo su Apple Silicon, permesso della camera chiesto dal filo della finestra, avviso di errore all'avvio
- `test_v209_rapporti.py`: Rapporti del 19/11: Wi-Fi con WPA2/WPA3 insieme e router recenti, rete propria del laser; porte CH341 su Linux e porta scritta a mano; camera della testa ferma senza homing; Prepara foto con una forma che ritaglia la foto come dalla pagina principale
- `test_v209_rapporti.py` (Banco): Wi-Fi dei router recenti, porte a mano e homing della camera della testa nell'interfaccia Banco

## Telecamera e guardia fiamme (15)

- `test_v107.py`: Telecamera: la scelta si ricorda, «Nessuna» non accende la webcam
- `test_v111.py`: Fiamma con il cuore bianco, nomi sotto i comandi
- `test_v175.py`: Calibrazione della camera con i punti messi a mano sui dischi incisi
- `test_v175.py` (Banco): Punti a mano della camera nell'interfaccia Banco
- `test_v181_camera.py` (Banco): Telecamere del Falcon A1 nell'interfaccia Banco
- `test_v200_camera_testa.py`: Camera della testa: calibrazione col puntino inciso, laser e camera dove vuoi, origine dalla camera, tavola da due angoli, foto del piano a mosaico, telecamere cercate di nuovo
- `test_v200_camera_testa.py` (Banco): Camera della testa nell'interfaccia Banco
- `test_v203_telecamere.py`: Telecamera della testa e del piano: si scelgono sempre (quella già usata passa di qua), «Calibra» sempre possibile, calibrazione nuova mai scartata senza chiedere
- `test_v203_telecamere.py` (Banco): Scelta delle telecamere e calibrazione sempre possibile nell'interfaccia Banco
- `test_v205_richieste.py`: Angoli del rettangolo raccordati verso l'interno, riga dei Livelli che segue il livello assegnato, anteprima dell'offset sul piano, opzioni dello strumento Forme subito; finestra della camera della testa ridimensionabile, pulsante dello sfondo del piano; Linux: libgthread nell'AppImage e libreria mancante detta all'avvio; ringraziamenti sulla schermata di avvio, in Aiuto e nel rapporto
- `test_v205_richieste.py` (Banco): Angoli verso l'interno, Livelli, offset, Forme, camera della testa, sfondo del piano e ringraziamenti nell'interfaccia Banco
- `test_v212_calibrazione.py`: Calibrazione della camera con la scheda che si riavvia da sola (rapporti E933 e 44A1): riavvii chiesti e no, homing tolto, la calibrazione si ferma con il messaggio e senza altri movimenti, inizio e fine nel registro, passaggio al cartone spiegato
- `test_v201_lentezza.py`: Telecamera USB a riposo quando nessuno la guarda, rallentamenti nel registro e nel rapporto
- `test_v202_camera_testa.py`: Calibrazione completa della camera della testa (griglia incisa, lente, inclinazione, verifica onesta), mosaico preciso, camera del piano aiutata, vista raddrizzata e zoom, crocetta dal centro camera
- `test_v202_camera_testa.py` (Banco): Calibrazione completa e vista della testa nell'interfaccia Banco

## Nesting e piani di lavoro (15)

- `test_v08.py`: Ottimizza lo spazio (nesting) e modelli di laser pronti
- `test_v09.py`: QR e codici a barre, testo su tracciato, rotativo, più pannelli e linee comuni
- `test_v103.py`: Suggerimenti pronti, nesting nella barra, piano più reattivo e identico
- `test_v150.py`: Piani di lavoro: più lavori in un progetto, si prepara il prossimo mentre il laser incide
- `test_v150.py` (Banco): Piani di lavoro nell'interfaccia Banco
- `test_v183_selezione.py`: Selezione: un clic sceglie un oggetto solo; nesting senza selezione finale
- `test_v183_selezione.py` (Banco): Selezione e nesting nell'interfaccia Banco
- `test_v1816_nesting_manuale.py`: Nesting manuale: area disegnata sul piano, laser sui punti, T1 mai inciso
- `test_v1816_nesting_manuale.py` (Banco): Nesting manuale nell'interfaccia Banco
- `test_v1817_nesting_manuale.py`: Nesting manuale: solo i pezzi selezionati, forme sotto ignorate, contorno che sparisce
- `test_v1817_nesting_manuale.py` (Banco): Nesting manuale (correzioni) nell'interfaccia Banco
- `test_v190_nesting_finestra.py`: Nesting manuale in una finestra sola, homing dalla spunta del laser
- `test_v190_nesting_finestra.py` (Banco): Nesting manuale in una finestra sola nell'interfaccia Banco
- `test_v195_varie.py`: Nesting manuale che sporge dai pannelli, elenco delle scorciatoie, Sculpfun E1 dalla scheda e tabella Sculpfun, Riconosci → Applica che tiene angolo e assi
- `test_v195_varie.py` (Banco): Nesting manuale e scorciatoie nell'interfaccia Banco

## Materiali (5)

- `test_v03.py`: Materiali, test materiale, vettorizzazione, testo variabile e curvo
- `test_v160.py`: Materiali imparati: la curva del tuo legno dalle foto dei test, toni e anteprima
- `test_v160.py` (Banco): Materiali imparati nell'interfaccia Banco
- `test_v192_analisi.py`: Scorciatoie valide, ordine dei tagli, preparazione del lavoro con Annulla, materiali per potenza, Preferenze, ricerca comandi, anteprime
- `test_v212_catalogo.py`: Catalogo: VEVOR A7 5W (come l'Atomstack A5 Pro) e Sculpfun iCube Ultra Dual 12W e 1.2W IR (area prudente 135 × 135, dichiarata 150 × 135, famiglia nel riconoscimento, nota sul raggio a 1064 nm, accelerazione 500, tabella dei materiali Sculpfun con interlinea 0,05), traduzioni

## Foto e immagini (29)

- `test_v10.py`: Foto veloci, Prepara foto, foto in linee e riempimento, prova foto
- `test_v102.py`: Anteprima che non copre la foto, zoom a punti veri in Prepara foto
- `test_v108.py`: Progetti .lbrn2: foto non più specchiate, testi al loro posto
- `test_v125.py`: Foto dei progetti .lbrn2 uguali in «Prepara foto», maniglie incomplete
- `test_v132.py`: Foto e disegni su livelli separati, formati delle immagini
- `test_v133.py`: Effetti per le foto (matita, china, linee, puntinismo…)
- `test_v135.py`: Ritratto a matita, partenza delle immagini, retino spiegato, Longer Ray5 10W e 20W
- `test_v136.py`: Puzzle da foto, installatore che chiude il collegamento con Claude
- `test_v140.py`: Schizzo del soggetto (sfondo tolto), Scultura 3D da modello a strati e a incastro
- `test_v170.py`: Schizzo del soggetto: tratto a matita nuovo, aiuti (riquadro, tieni, togli)
- `test_v170.py` (Banco): Schizzo del soggetto nell'interfaccia Banco
- `test_v172.py`: Area di lavoro non credibile, foto troppo fitte per la porta, override, Mecpow X3S
- `test_v172.py` (Banco): Area non credibile, foto fitte e override nell'interfaccia Banco
- `test_v176.py`: Pennelli precisi dello Schizzo del soggetto, velo rosso; il simulatore non tocca il profilo
- `test_v190_mezzetinte.py`: Mezzetinte: dimensione del punto e misure collegate
- `test_v203_soggetto.py`: Schizzo del soggetto: ricerca automatica che si spegne, il soggetto parte vuoto e resta solo quello dipinto con Tieni
- `test_v203_soggetto.py` (Banco): Schizzo del soggetto che parte da vuoto nell'interfaccia Banco
- `test_v203_ritaglio.py`: Foto ritagliata a forma: cuore, stella, nuvola, cerchio ed esagono in Prepara foto, ritaglio con una forma del disegno, foto ruotata in negativo che non incide fuori
- `test_v203_ritaglio.py` (Banco): Foto ritagliata a forma nell'interfaccia Banco
- `test_v206_richieste.py`: Foto ritagliata con una forma: misure, maniglie, Allinea e aggancio del lavoro sulla sola parte che si vede, Contorno da tagliare; Prepara foto: forma sull'originale e riquadro del ritaglio che si sposta e si allarga; ingranaggio a evolvente con modulo, angolo di pressione, gioco, foro e alleggerimenti; precisazione dei ringraziamenti
- `test_v206_richieste.py` (Banco): Foto ritagliata, Contorno da tagliare, Prepara foto, ingranaggio e ringraziamenti nell'interfaccia Banco
- `test_v211_foto.py`: Prepara foto anche sulla foto ritagliata con una forma: menu in alto, tasto destro e pannello Proprietà
- `test_v211_foto.py` (Banco): Prepara foto sulla foto ritagliata nell'interfaccia Banco
- `test_v212_velocita.py`: Velocità costante a laser spento (riempimenti e immagini) e «Spostamenti a vuoto più lenti» (macchina): righe intere a velocità di lavoro senza G0, salti fra le forme e fra i livelli che restano, G-code identico alla 0.21.1 con le caselle spente, tetto alla velocità della scheda, Contorno, stima del tempo, file vecchi
- `test_v220_galleria.py`: Galleria dei lavori condivisi (in prova): comandi nel menu File, modulo, progetto ripulito e che cosa parte davvero, foto senza EXIF, risposte e file ostili, voti, segnalazioni, «I miei lavori», apertura come progetto nuovo
- `test_v221_vuoti.py`: Vuoti nelle righe di foto e riempimenti: salto veloce solo se resta lungo dopo le rincorse, mai all'indietro (foto con l'effetto Matita)
- `test_v221_vuoti.py` (Banco): Vuoti nelle righe di foto e riempimenti nell'interfaccia Banco
- `test_v223_png_trasparenti.py`: Immagini con lo sfondo trasparente: sulla tela si vede solo la parte piena, il clic sul trasparente prende quello che c'è sotto, il trasparente non si incide mai (negativo, luminosità, contrasto); stesso G-code di prima senza trasparenza
- `test_v223_png_trasparenti.py` (Banco): Immagini con lo sfondo trasparente nell'interfaccia Banco

## Lavoro e G-code (42)

- `test_gcode.py`: Generatore G-code (eseguito sul simulatore)
- `test_controller.py`: Controller: verifica, errori, override, ripresa, fire
- `test_v05.py`: Barra numerica, livelli in tabella, guida ?, riconoscimento macchina, anteprima
- `test_v091.py`: Flusso completo sul simulatore: pannello Laser stabile, fine lavoro a testa ferma, piano pulito
- `test_v104_verifica.py`: Verifica: allarme dei limiti software, Stop/reset/Disconnetti, corsa letta dalla scheda
- `test_v105.py`: Correzione della scansione avanti e indietro, prova da incidere, Acmer S1
- `test_v121.py`: Scheda rimasta in prova, verifica senza risposte, schede senza G55
- `test_v123.py`: Anteprima che segue il punto di riferimento, puntino fino al 20%
- `test_v134.py`: Profili macchina da condividere, YouTube, 8 modelli nuovi verificati
- `test_v141.py`: Anteprima 3D con la scheda grafica, con l'anteprima semplice di riserva
- `test_v181_anteprima.py`: Anteprima del Riempimento per livello intero, come il G-code
- `test_v181_anteprima.py` (Banco): Anteprima del Riempimento nell'interfaccia Banco
- `test_v184_risposte.py`: Risposte perse alla fine di verifica e lavoro (Creality Falcon A1)
- `test_v185_stampa_taglia.py`: Stampa e taglia (in prova): crocette, PDF in misure vere, allineamento al foglio
- `test_v185_stampa_taglia.py` (Banco): Stampa e taglia nell'interfaccia Banco
- `test_v185_aria.py`: Comando dell'air assist a scelta: M8, M7 o nessuno
- `test_v185_aria.py` (Banco): Comando dell'air assist nell'interfaccia Banco
- `test_v192_g55.py`: Scheda che su G55 tace o risponde con un errore, in verifica e nel lavoro: lavoro fermato e rifatto senza
- `test_v196_varie.py`: DXF con valori vuoti, freccette nei campi della barra, vista di ogni piano, G-code CRLF
- `test_v201_aria.py`: Air assist delle schede MKS DLC32 (M7) e scelta dell'aria che resta rifacendo il profilo
- `test_v201_aria.py` (Banco): Air assist delle MKS DLC32 nell'interfaccia Banco
- `test_v203_testo.py`: Testo: anteprima del carattere sul testo vero scorrendo l'elenco, spaziatura delle lettere senza salti e delle righe
- `test_v203_testo.py` (Banco): Testo: anteprima del carattere e spaziature nell'interfaccia Banco
- `test_v203_misure.py`: Barra delle misure: caselle X, Y, L, A, R e rotazione larghe quanto serve al numero (la prima cifra non esce più tagliata)
- `test_v207_svg_grigi.py`: SVG con contorno e riempimento separati da soli; riempimenti in toni di grigio con la potenza dal grigio di ogni forma (nero = massima, bianco = non si incide), forme sopra che coprono quelle sotto, fori vuoti; loghi neri, colori e file di prima come prima; anteprima dei toni; salvataggio; traduzioni
- `test_v207_scia.py`: Scia dell'incisione sul piano: si spegne dal menu Visualizza (ricordato), ridisegno al massimo 4 volte al secondo, nascosta con l'anteprima del lavoro guardando un altro piano senza gli altri piani
- `test_v207_piano.py`: G-code «del piano» di un programma esterno adattato al laser del profilo (watt, velocità massima, assi, G55, fuori dal piano), solo con le funzioni in prova; il collegamento diretto con la M2 non c'è
- `test_v207_piano.py` (Banco): G-code «del piano» nell'interfaccia Banco
- `test_v206_cook.py`: Free Laser Cook (in prova): conto dell'energia e delle passate, G-code a testa alzata con pausa per girare, righe della griglia, firma e giro dell'aroma sul legno; ricette incluse, salvate, esportate e importate; finestra dietro il codice con le accortezze da spuntare
- `test_v210_tastiera.py`: La testa con la tastiera: Alt+Maiusc+frecce, passi Alt+1…5, Z, origine, anche con oggetti selezionati e in Stampa e taglia (Ctrl+1, Ctrl+2); niente durante il lavoro; tasti tutti diversi
- `test_v210_disegno.py`: Linea tratteggiata, Ritaglia con la forma e al piano, rampa dei riempimenti (timbri), Z che scende a ogni passata, Separa sui tracciati con più figure e Scomponi sui gruppi
- `test_v210_disegno.py` (Banco): Tratteggio, ritaglio, rampa, Z per passata, Separa e Scomponi nell'interfaccia Banco
- `test_v210_ripresa.py`: Lavoro in corso salvato sul disco e ripreso dopo la riapertura del programma, Scarta, file rovinati; Parti da qui nell'anteprima
- `test_v211_grigio.py`: Grigio delle forme scelto nel pannello Proprietà: riga Grigio, tono e potenza, più forme insieme, gruppi, Annulla, G-code e salvataggio
- `test_v212_lucciola.py`: Finestre chiuse che restavano attaccate ai segnali (rapporti 75E8 e ABFC): Lucciola dopo Stampa e taglia, copie della scheda dopo un cambio di collegamento, nessuna lambda sui segnali di controllore, scheda Laser e finestra principale
- `test_v212_lucciola_tasto.py`: Lucciola dalla tastiera (Alt+Maiusc+L): come il pulsante, tetto di potenza, niente raggio senza macchina, in lavoro o in allarme, Stop che la spegne davvero anche nel programma, con Stampa e taglia davanti
- `test_v202_pausa.py`: Pausa prima di un livello: G-code con M0, invio diretto che si ferma e riprende, Annulla durante la pausa
- `test_v220_aria.py`: Configurazione guidata della macchina, passo dell'aria: due prove a laser spento (M8 e M7), aria che si spegne sempre, casi in cui la prova non si fa, scelta salvata nel profilo
- `test_v220_aria.py` (Banco): Configurazione guidata della macchina, passo dell'aria nell'interfaccia Banco
- `test_v221_import.py`: DXF con i colori numerati e del layer (il taglio rosso non si perde); SVG senza unità a 72, 90 o 96 dpi (Illustrator)
- `test_v222_contorno.py`: Contorno con la partenza dalla posizione della testa: finito il giro la testa torna da dove è partita e il lavoro non si sposta (9 pallini, laser spento e puntino, rettangolo e convesso)
- `test_v222_contorno.py` (Banco): Contorno con la partenza dalla testa nell'interfaccia Banco

## Macchina, connessione e profili (56)

- `test_v104.py`: Rapporto per l'assistenza, registro della comunicazione, installatore
- `test_v122.py`: Assi invertibili, velocità in mm/s, MKS DLC32
- `test_v124.py`: Porta la testa sul punto scelto del disegno
- `test_v130.py`: Segni del piano spiegati, modalità esperto, configurazione guidata della macchina
- `test_v142.py`: Scultura 3D: niente blocchi con i modelli scomodi, avvisi, Annulla, sistemazione veloce
- `test_v161.py`: Velocità della porta seriale a mano, avviso se la scheda non risponde
- `test_v161.py` (Banco): Velocità della porta seriale nell'interfaccia Banco
- `test_v162.py`: Homing interrotto da un allarme non valido, messaggio dell'allarme, codice QR davanti
- `test_v162.py` (Banco): Homing interrotto e codice QR nell'interfaccia Banco
- `test_v163.py`: Scheda muta dopo la connessione: reset morbido automatico, una volta sola
- `test_v173.py`: ESP32 muto dopo la connessione: riavvio dalle linee DTR/RTS; strumento Misura leggibile
- `test_v177.py`: Invia un rapporto all'assistenza: rapporto più completo, consenso, invio ed email
- `test_v177.py` (Banco): Rapporto all'assistenza nell'interfaccia Banco
- `test_v1712.py`: Pennello veloce, zoom sull'originale e autofocus con sonda
- `test_v1712.py` (Banco): Pennello, zoom e autofocus nell'interfaccia Banco
- `test_v1714.py`: Acmer P3 nel catalogo e profili dei produttori (.lbdev)
- `test_sculpfun_c1.py`: Sculpfun C1 3W e 6W nel catalogo
- `test_v180.py`: Versione per Linux: AppImage, aggiornamento, porta USB, menu, avviso sul collaudo
- `test_v181_sonda.py`: Autofocus: segnale della sonda al contrario ($6)
- `test_v181_sonda.py` (Banco): Autofocus: sonda al contrario nell'interfaccia Banco
- `test_v183_gerber.py`: Circuiti stampati: importazione dei file Gerber e dei fori Excellon
- `test_v186_menu.py`: Menu del tasto destro sul piano (interfaccia classica)
- `test_v187_lucciola.py`: Lucciola: laser acceso al minimo, potenza limitata, spegnimento da solo
- `test_v187_lucciola.py` (Banco): Lucciola nell'interfaccia Banco
- `test_v1812_ray5_40w.py`: Longer Ray5 40W nel catalogo
- `test_v1815_g55.py`: Scheda che rifiuta G55 con un altro errore e poi tace (OMTech K40)
- `test_v1815_g55.py` (Banco): Scheda che rifiuta G55 nell'interfaccia Banco
- `test_v1816_swift.py`: Atomstack Swift 7W e 12W nel catalogo; 460800 baud fra le velocità provate
- `test_v1816_cnc3018.py`: CNC 3018 con il laser al posto del mandrino (Genmitsu 3018-PRO) nel catalogo
- `test_v192_g55.py` (Banco): Scheda senza G55 nell'interfaccia Banco
- `test_v192_acmer_p2.py`: Acmer P2 da 10, 20 e 33 W nel catalogo dei modelli: dati ufficiali, riconoscimento della scheda
- `test_v193_piano.py`: Piano mostrato ruotato di 90°, angolo dell'homing: «casa» a fine lavoro, angolo scelto nella configurazione guidata, file in coordinate macchina
- `test_v193_piano.py` (Banco): Piano ruotato e angolo dell'homing nell'interfaccia Banco
- `test_v193_cerca.py`: Ricerca comandi: casella «Cerca un comando» nella barra in basso della classica
- `test_v194_sculpfun_e1.py`: Sculpfun E1 nel catalogo: 12 W, Pro 21 W e modulo infrarosso, riconoscimento dall'area di lavoro
- `test_v195_movimento.py`: Scheda Movimento: Puntino e Lucciola al centro delle frecce, joystick virtuale sul simulatore
- `test_v195_movimento.py` (Banco): Puntino, Lucciola e joystick nell'interfaccia Banco
- `test_v200_nomi.py`: Nome del progetto dal file importato e file di provenienza delle forme
- `test_v207_svg_vuoti.py`: SVG con tracciati senza disegno (<path/> senza «d», come nei file di xTool Creative Space): il resto del file si importa; SVG sani byte per byte identici; attributi con «>» o apostrofi non rovinati; da file e .svgz; rettangoli e cerchi con trasformazioni speculari al posto giusto
- `test_v209_laser.py`: Più laser configurati, ognuno con il suo nome: tendina nel pannello Laser, nome, laser nuovo da un modello o copia, tolto dall'elenco, porta ricordata per ogni laser, profilo e piano che cambiano
- `test_v210_tastiera.py` (Banco): La testa con la tastiera nell'interfaccia Banco
- `test_v211_joystick.py`: Joystick pronto e fedele: pezzetti al ritmo del tempo vero, la testa gira subito anche con code da 15, 63 e 127 posti, velocità vera, bordo, rilascio, simulatore con i jog in coda come le schede vere
- `test_v211_falcon.py`: Angolo dello 0 e assi che non si contraddicono più (Falcon A1 del rapporto 2E95): avviso con correzione, configurazione guidata, catalogo, prova delle frecce dall'angolo dell'homing, simulatore; freccia «Continuo» mai muta al bordo
- `test_v211_falcon.py` (Banco): Angolo dello 0, assi e freccia «Continuo» nell'interfaccia Banco
- `test_v212_moduli.py`: Moduli aggiuntivi: cartella dei dati, modulo.json, versione adatta, errori che restano del modulo (importazione, registrazione, comando), niente comandi a metà né al posto di quelli del programma, traduzioni, riga nel rapporto, spenti nello Store; nessun comando né file per macchine non GRBL nel programma
- `test_v212_lucciola.py` (Banco): Finestre chiuse attaccate ai segnali nell'interfaccia Banco
- `test_v212_lucciola_tasto.py` (Banco): Lucciola dalla tastiera nell'interfaccia Banco
- `test_v212_joystick_fisico.py`: Joystick fisico (G13, pad, joystick USB) con un controller finto: zona morta e taratura del centro, si arma solo dal centro, programma in secondo piano e finestre aperte, guardiano e scollegamento, homing obbligatorio, tetto della «Velocità jog» e mai oltre 6000, nessun comando del laser, lavoro e allarme, un solo padrone fra schermo, tastiera e levetta, verso, pressione lunga per Homing e X0 Y0, controller ricordato, da riaccendere a ogni avvio, libreria che manca
- `test_v212_continuo.py`: «Continuo» e joystick quando il piano del profilo è più grande della corsa della scheda (rapporto 3802): bordo vero con coordinate positive e negative, assi invertiti e piano ruotato, nessun error:15, rifiuto spiegato sotto le frecce con «Usa le misure della macchina», avviso al collegamento, simulatore con la corsa del profilo
- `test_v201_nomi.py`: Il nome del progetto dato dall'importazione segue i file che restano sul piano
- `test_v201_carverall_jl9.py`: Carverall JL9 (X1 Pro) 20W nel catalogo: dati ufficiali, riconoscimento dall'area di lavoro
- `test_v221_import.py` (Banco): DXF e SVG importati nell'interfaccia Banco
- `test_v222_banco_rete.py`: Rete di sicurezza del Banco: dopo un avvio fallito si parte in Classica con la fascia, alla seconda la scelta diventa Classica; Officina sul secondo monitor spenta sul Mac; prova d'avvio di GitHub anche nel Banco
- `test_v223_studio.py`: Studia la macchina (in prova): prove guidate su K40 (scheda M2 Nano) e Ruida con schede finte, in qualsiasi ordine; il laser non si accende mai (comandi permessi, chiavi sbagliate innocue), diario e rapporto, indirizzo nascosto, difetti rimessi apposta
- `test_v223_studio.py` (Banco): Studia la macchina nell'interfaccia Banco
- `test_v224_atomstack.py`: Atomstack X30 Pro / S30 Pro / A30 Pro: modelli nel catalogo e scheda riconosciuta dalla versione del firmware (la marca non la scrive), con X20 Pro e X40 Pro fra i candidati

## Disegno e modifica (28)

- `test_editor_ui.py`: Editor: mouse e tastiera sulla tela
- `test_v04.py`: Progetti .lbrn2, galleria forme, comandi da Claude (MCP)
- `test_v173.py` (Banco): Riavvio dalle linee DTR/RTS e strumento Misura nell'interfaccia Banco
- `test_v1713.py`: Raccordo su un angolo solo (rettangolo e strumento Nodi)
- `test_v1716.py`: Rilievo 3D su tavola (in prova), distanza esatta e forbici
- `test_v1716.py` (Banco): Rilievo 3D, distanza esatta e forbici nell'interfaccia Banco
- `test_v1717.py`: Forbici: pezzi agganciati in una forma sola; Unisci estremi corretto
- `test_v182_raggio.py`: Raggio degli angoli nella barra in alto; raggio anche per poligoni e stelle
- `test_v182_raggio.py` (Banco): Raggio degli angoli nella barra del Banco
- `test_v183_gerber.py` (Banco): Circuiti stampati (Gerber) nell'interfaccia Banco
- `test_v1811_aggancio.py`: Aggancio mentre si sposta: angoli, mezzerie, centri e nodi dell'oggetto, non il punto del mouse
- `test_v1811_aggancio.py` (Banco): Aggancio mentre si sposta nell'interfaccia Banco
- `test_v190_interfaccia.py`: Doppio clic = strumento bloccato; scritte delle linguette dei piani
- `test_v190_interfaccia.py` (Banco): Strumento bloccato e linguette nell'interfaccia Banco
- `test_v192_analisi.py` (Banco): Banco sugli schermi piccoli, avvio fermo al suo posto, barra della selezione, ricerca e Preferenze
- `test_v195_nodi.py`: Strumento Nodi: più nodi selezionati insieme, nodi di più forme, unione di due nodi (J fonde, Maiusc+J collega)
- `test_v195_nodi.py` (Banco): Strumento Nodi con più nodi e unione nell'interfaccia Banco
- `test_v196_tracciati.py`: Tracciati puliti: Semplifica tracciati con lo scarto misurato, disegno a mano libera, Allinea e Distribuisci sui nodi
- `test_v196_tracciati.py` (Banco): Semplifica tracciati, mano libera e nodi nell'interfaccia Banco
- `test_v200_selezione.py`: Selezione più visibile: linea piena con alone del colore d'accento
- `test_v200_selezione.py` (Banco): Selezione più visibile nell'interfaccia Banco
- `test_v204_piano_veloce.py`: Editor veloce con i disegni complessi: forme e selezione disegnate una volta sola e non a ogni movimento del mouse, clic sui gruppi, tracciati letti in blocco
- `test_v204_piano_veloce.py` (Banco): Editor veloce con i disegni complessi nell'interfaccia Banco
- `test_v204_piano_veloce.py` (scala125): Editor veloce con i disegni complessi su uno schermo al 125%
- `test_v209_disegno.py`: Guide dai righelli (aggancio, salvate nel progetto, piano ruotato), deformazione a 4 punti (prospettiva) e a 16 punti (griglia), larghezza delle fessure degli incastri
- `test_v211_grigio.py` (Banco): Grigio delle forme nell'interfaccia Banco
- `test_v202_linee_piatte.py`: Linee orizzontali, verticali e punti dentro la selezione col rettangolo e negli ingombri
- `test_v202_linee_piatte.py` (Banco): Linee piatte nella selezione nell'interfaccia Banco

## Interfaccia (47)

- `test_v06.py`: Lingue: inglese, italiano, spagnolo, francese, portoghese
- `test_v07.py`: Interfaccia Banco: ricerca comandi, strati, percorso, menu radiale, cabina, Officina
- `test_v101.py`: Avvio robusto: errori visibili, istanza unica, scelta interfaccia, installatore
- `test_v106.py`: Aspetto: tema scuro, chiaro o come Windows, colore principale
- `test_v176.py` (Banco): Pennelli precisi e simulatore nell'interfaccia Banco
- `test_v1711.py` (Banco): Aggiornamento dal programma nell'interfaccia Banco
- `test_v1713.py` (Banco): Raccordo su un angolo solo nell'interfaccia Banco
- `test_v180.py` (Banco): Versione per Linux nell'interfaccia Banco
- `test_v186_menu.py` (Banco): Tasto destro nel Banco: resta il menu radiale
- `test_v188_chiusure.py` (Banco): Chiusure improvvise e blocchi nell'interfaccia Banco
- `test_v1814_makerhub.py`: MakerHub (in prova): i quattro strumenti nel menu e il disegno che arriva dal loro sito
- `test_v1814_makerhub.py` (Banco): MakerHub nell'interfaccia Banco
- `test_v192_strumenti.py`: Barra degli strumenti: pulsante Strumenti e comando unico per MakerHub
- `test_v192_strumenti.py` (Banco): Menu Strumenti e comando unico per MakerHub nell'interfaccia Banco
- `test_v192_analisi.py` (chiaro): Tema chiaro: testi leggibili sulle righe selezionate
- `test_v193_avvio.py`: Avvio robusto: Windows troppo vecchio detto chiaro, icona giusta sulla barra di Windows
- `test_v193_cerca.py` (Banco): Ricerca comandi nell'interfaccia Banco: resta la finestrella
- `test_v196_varie.py` (Banco): Freccette nei campi, vista dei piani e CRLF nell'interfaccia Banco
- `test_v200_nomi.py` (Banco): Nome del progetto e file di provenienza nell'interfaccia Banco
- `test_v202_barra.py`: Barra in basso: «File: …» leggibile, posizione e velocità vuote senza spazio, laser collegato senza allargare
- `test_v202_barra.py` (Banco): Barra in basso leggibile nell'interfaccia Banco
- `test_v203_misure.py` (Banco): Barra delle misure nell'interfaccia Banco: numeri interi senza allargare la barra
- `test_v206_rapporti.py` (Banco): Rapporti del 18/11 nell'interfaccia Banco
- `test_v207_svg_grigi.py` (Banco): SVG con riempimenti grigi nell'interfaccia Banco
- `test_v207_scia.py` (Banco): Scia dell'incisione nell'interfaccia Banco
- `test_v206_cook.py` (Banco): Free Laser Cook nell'interfaccia Banco
- `test_v207_barra.py`: Barra in alto personalizzabile: i comandi che usi di più dopo quelli di sempre, nell'ordine scelto, ricordati; finestra con Cerca, Aggiungi, Togli, Su, Giù, Svuota; tasto destro sulle barre
- `test_v207_barra.py` (Banco): Barra personalizzabile: nel Banco la voce non c'è
- `test_v209_laser.py` (Banco): Più laser e tendina dei laser nell'interfaccia Banco
- `test_v209_disegno.py` (Banco): Guide, deformazione e fessure nell'interfaccia Banco
- `test_v210_ripresa.py` (Banco): Ripresa dal disco e Parti da qui nell'interfaccia Banco
- `test_v211_joystick.py` (Banco): Joystick pronto e fedele nell'interfaccia Banco
- `test_v212_moduli.py` (Banco): Moduli aggiuntivi nell'interfaccia Banco
- `test_v212_velocita.py` (Banco): Velocità costante e spostamenti a vuoto nell'interfaccia Banco
- `test_v212_joystick_fisico.py` (Banco): Joystick fisico nell'interfaccia Banco
- `test_v212_continuo.py` (Banco): «Continuo» e joystick al bordo vero nell'interfaccia Banco
- `test_v212_primo_avvio.py`: Primo avvio (rapporto E698, Mac M1): finestra della scelta distrutta prima della finestra principale, pulizia della memoria sospesa durante la costruzione e riattivata anche se fallisce, porte del sistema del Mac in fondo e segnate
- `test_v212_primo_avvio.py` (Banco): Primo avvio nell'interfaccia Banco
- `test_v201_finestra.py`: La finestra non si allarga mai oltre lo schermo (scritta «File:» della barra in basso), in tutte le lingue
- `test_v201_finestra.py` (Banco): Finestra che resta nello schermo nell'interfaccia Banco
- `test_v201_nomi.py` (Banco): Nome del progetto che segue i file nell'interfaccia Banco
- `test_v202_pausa.py` (Banco): Pausa prima di un livello nell'interfaccia Banco
- `test_v220_galleria.py` (Banco): Galleria dei lavori condivisi nell'interfaccia Banco
- `test_v220_incastri.py`: Adatta gli incastri allo spessore: spessore trovato da solo, fessure e fori allargati al centro, tacche più profonde, linguette più lunghe, bordi a dita con le punte ferme, angoli e tetti obliqui, incastri troppo vicini lasciati come sono, andata e ritorno
- `test_v220_incastri.py` (Banco): Adatta gli incastri allo spessore nell'interfaccia Banco
- `test_v224_caratteri.py`: Grandezza dei caratteri dell'interfaccia: stessi pixel sugli schermi a 72 punti per pollice (Mac), scelta in Impostazioni e nelle Preferenze (85–150%), ogni foglio di stile e ogni carattere passa dallo stesso punto
- `test_v224_caratteri.py` (Banco): Grandezza dei caratteri nell'interfaccia Banco

## Avvio, installazione, aggiornamenti e assistenza (9)

- `test_v104_aggiorna.py`: Aggiornamento dal programma: Release di GitHub, SHA-256, installatore /AGGIORNA
- `test_v178.py`: Ricevitore dei rapporti attivo: pulsante Invia
- `test_v1711.py`: Aggiornamento dal programma: errori visibili e nuovi tentativi
- `test_v188_chiusure.py`: Chiusura improvvisa dopo l'invio di un rapporto; traccia quando la finestra si pianta
- `test_v189_uscita.py`: Finestra chiusa = programma chiuso: timer e chiusura garantita
- `test_v1812_pacchetti.py`: Costruzione su GitHub: lo specchio dei pacchetti che non risponde non ferma più la Release
- `test_v1816_prove.py`: Prove su GitHub: una volta sola per versione, quattro suite insieme, secondo tentativo da sole
- `test_v1816_avvio.py`: Guardia d'avvio: gli errori prima della finestra vengono scritti e mostrati, anche senza Qt
- `test_v190_cpu.py`: Processori vecchi: istruzioni lette all'avvio e librerie compatibili
