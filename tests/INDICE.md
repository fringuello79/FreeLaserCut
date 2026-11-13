# Prove automatiche di FreeLaserCut, per area

Generato da `tests/run_tests.py` (non modificare a mano): ogni suite sta nell'area della sua descrizione.
Suite: 137. Lancio completo: `python tests/run_tests.py`; una sola: `python tests/<file> [banco]`.

## Wi-Fi, rete e telefono (12)

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

## Telecamera e guardia fiamme (5)

- `test_v107.py`: Telecamera: la scelta si ricorda, «Nessuna» non accende la webcam
- `test_v111.py`: Fiamma con il cuore bianco, nomi sotto i comandi
- `test_v175.py`: Calibrazione della camera con i punti messi a mano sui dischi incisi
- `test_v175.py` (Banco): Punti a mano della camera nell'interfaccia Banco
- `test_v181_camera.py` (Banco): Telecamere del Falcon A1 nell'interfaccia Banco

## Nesting e piani di lavoro (13)

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

## Materiali (4)

- `test_v03.py`: Materiali, test materiale, vettorizzazione, testo variabile e curvo
- `test_v160.py`: Materiali imparati: la curva del tuo legno dalle foto dei test, toni e anteprima
- `test_v160.py` (Banco): Materiali imparati nell'interfaccia Banco
- `test_v192_analisi.py`: Scorciatoie valide, ordine dei tagli, preparazione del lavoro con Annulla, materiali per potenza, Preferenze, ricerca comandi, anteprime

## Foto e immagini (15)

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

## Lavoro e G-code (18)

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

## Macchina, connessione e profili (31)

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

## Disegno e modifica (15)

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

## Interfaccia (15)

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
