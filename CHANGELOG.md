# Novità di FreeLaserCut

## 0.18.11 — 11/11/2026
- **Aggancio oggetti: ora si agganciano gli angoli dell'oggetto che sposti** (da una segnalazione su un forum: «l'aggancio non avviene fra angolo ed angolo, ma fra l'angolo dell'oggetto vicino e il punto in cui ho preso l'oggetto col mouse; manca l'effetto magnetico che affianca due elementi ai loro angoli e mezzerie»). Aveva ragione: spostando un oggetto si agganciava il punto del mouse, e l'angolo restava scostato di quanto il mouse distava da lui.
  - **Punto su punto.** Angoli, mezzerie dei lati, centro e nodi dell'oggetto (o di tutta la selezione) si agganciano ad angoli, mezzerie, centri e nodi delle altre forme: angolo su angolo, mezzeria su mezzeria, centro su centro. Non conta più in che punto prendi l'oggetto.
  - **Lato su lato.** Se nessun punto è a tiro, il bordo dell'oggetto si appoggia al bordo di una forma vicina e ci resta mentre lo fai scorrere: due pezzi si affiancano senza fessure anche se non sono allineati in altezza. Il segno giallo dice «lato».
  - **Griglia.** Con l'aggancio alla griglia va sulla griglia l'angolo dell'oggetto, non il punto del mouse: un oggetto che era sulla griglia ci resta.
  - Come prima: raggio di 9 pixel, *Alt* sospende l'aggancio, *Maiusc* tiene lo spostamento su un asse (ora l'aggancio lo rispetta). Disegnare, ridimensionare e spostare i nodi non cambiano.
- Nuova prova automatica `tests/test_v1811_aggancio.py` (40 controlli, Classica e Banco).
- **MakerHub: per ora resta il collegamento diretto (in prova, non ancora attivo per tutti).** Con le funzioni in prova sbloccate, nel menu *Strumenti* c'è **MakerHub – Scatola a incastri**, con il loro logo: un clic apre nel browser il generatore di scatole di MakerHub (maker-hub.it, un servizio esterno: serve un account lì). Il disegno si scarica dal loro sito e si porta in FreeLaserCut con *File → Importa*; i pezzi escono già compensati per il kerf, quindi qui non vanno compensati di nuovo (lo ricorda anche la barra in basso dopo il clic).
  - **Tolta la ricezione automatica dei disegni** preparata nella 0.18.10 (menu *MakerHub* in alto, finestra *Collega MakerHub*, codice di 6 caratteri, ascolto in secondo piano): sul sito di MakerHub quella parte non è ancora attiva. Tornerà quando lo sarà. Da questa versione FreeLaserCut non chiama più i loro server in nessun caso: apre soltanto la pagina nel browser.
- Prova automatica `tests/test_v1811_makerhub.py` al posto di quella della 0.18.10.

## 0.18.10 — 11/11/2026
- **MakerHub dentro FreeLaserCut (in prova, non ancora attivo per tutti).** MakerHub (maker-hub.it) è un servizio esterno, di persone che hanno creduto in FreeLaserCut fin dall'inizio: sul loro sito ci sono generatori di disegni pronti per il laser, per esempio la scatola a incastri. Con le funzioni in prova sbloccate compare il menu **MakerHub**, con il loro logo.
  - **I loro strumenti a un clic.** Ogni voce apre nel browser la pagina giusta del loro sito (serve un account lì). L'elenco si aggiorna dalla finestra *MakerHub*, solo quando lo chiedi.
  - **Il disegno arriva da solo sul piano.** Si collega FreeLaserCut una volta, con il codice di 6 caratteri che dà MakerHub; poi sul sito si preme «Manda a FreeLaserCut» e il disegno compare qui: FreeLaserCut chiede conferma e lo mette al centro del piano con le misure vere, il taglio e l'incisione su due livelli liberi (quelli già usati non vengono toccati), l'incisione prima del taglio, e i valori di partenza proposti da MakerHub. **Il laser non parte mai da solo.**
  - Se i pezzi sono già compensati per lo spessore del taglio, la compensazione di FreeLaserCut su quei livelli resta a zero, e lo dice.
  - **Riservatezza.** FreeLaserCut contatta MakerHub solo dopo che l'hai collegato tu. Manda la sua versione e l'esito di ogni disegno; non manda il nome del computer né quello del progetto, e il modello della macchina solo se lo spunti. *Scollega* ferma tutto. Un lavoro che chiedesse di avviare il laser, o con script, immagini o riferimenti a file esterni, viene scartato.
  - Il protocollo e il programma di esempio da cui parte il collegamento li ha scritti MakerHub. Resta da provare con il loro sito vero: le prove automatiche usano un MakerHub finto.
- Nuova prova automatica `tests/test_v1810_makerhub.py` (75 controlli, Classica e Banco).

## 0.18.9 — 11/11/2026
- **Finestra chiusa, programma chiuso.** Installando un aggiornamento l'installatore poteva fermarsi su «FreeLaserCut è aperto» anche con il programma chiuso: un processo di FreeLaserCut era rimasto vivo senza finestra, e andava chiuso da Gestione attività. Ora alla chiusura FreeLaserCut aspetta al massimo 3 secondi le operazioni ancora in corso e poi termina comunque; se qualcosa non finiva, lo scrive nel registro (che entra nel rapporto per l'assistenza), così la causa si può trovare.
  - I timer del collegamento con la scheda (spegnimento automatico del puntino e della Lucciola, risveglio della scheda) non possono più tenere aperto il programma dopo la chiusura della finestra.
- Nuova prova automatica `tests/test_v189_uscita.py` (8 controlli).

## 0.18.8 — 11/11/2026
Da due rapporti all'assistenza («chiusura improvvisa»).
- **Chiusura improvvisa dopo aver mandato un rapporto.** Chiudendo la finestra *Invia un rapporto all'assistenza* mentre l'invio era ancora in corso, pochi secondi dopo FreeLaserCut si chiudeva di colpo, senza messaggi (nel registro: «access violation»). L'invio in secondo piano, finendo, liberava la finestra già chiusa dal posto sbagliato. Ora la finestra resta in vita finché l'invio è finito e viene liberata dal programma principale. Il rapporto arrivava comunque, e arriva ancora.
  - La stessa protezione vale per le altre finestre che lavorano in secondo piano: *Riconosci la macchina*, la prova della velocità della porta, la prova del collegamento Wi-Fi e la ricerca delle telecamere di rete.
- **Quando il programma «si pianta» ora resta una traccia.** Se la finestra non risponde per più di 8 secondi, FreeLaserCut scrive nel suo registro che cosa stava facendo in quel momento, e quando ha ripreso. Il registro entra nel rapporto per l'assistenza: finora un blocco non lasciava niente da leggere, e non si poteva capire la causa.
- Strumento *Nodi*: dopo aver tolto dei nodi con la tastiera, il tratto evidenziato sotto il mouse poteva non esistere più e il piano non si ridisegnava bene finché non si muoveva il mouse.
- Nuova prova automatica `tests/test_v188_chiusure.py` (12 controlli, Classica e Banco), con la finestra del rapporto chiusa 8 volte durante l'invio.

## 0.18.7 — 11/11/2026
- **Lucciola: il laser resta acceso al minimo** (un'idea di Deborah). Nel pannello *Laser*, sotto *Puntino (tieni premuto)*, c'è il pulsante **Lucciola (resta accesa)**: accende il laser a potenza bassissima e lo lascia acceso, per vedere dove punta la testa mentre si sistema il pezzo, senza tenere premuto niente.
  - **Potenza limitata in base al laser**, letta dai watt del profilo della macchina: al massimo **2%** fino a 5 W, **1,5%** fino a 10 W, **1%** fino a 20 W, **0,5%** oltre (1% se la potenza non è scritta nel profilo). Il limite non si può superare, né dal campo accanto al pulsante né in altro modo; si parte più in basso e si sale solo finché il punto si vede.
  - Da acceso il pulsante diventa **rosso e lampeggia**, con scritto **LASER ACCESO** e il **conto alla rovescia**; sotto compare l'avviso di tenere gli occhiali e restare vicino alla macchina.
  - **Si spegne da solo dopo 5 minuti**; il tempo riparte quando la testa si muove. Si spegne anche quando parte un lavoro o una verifica, in allarme, scollegando la macchina e chiudendo il programma. Un clic sul pulsante lo spegne subito.
  - Alla prima accensione di ogni sessione un avviso chiede conferma: occhiali protettivi per tutti, restare a sorvegliare la macchina, niente di infiammabile sotto il raggio.
  - Anche al minimo è un laser vero: gli occhiali servono sempre.
- Il puntino o la Lucciola rimasti accesi si spengono prima che parta un lavoro o una verifica.
- Nuova prova automatica `tests/test_v187_lucciola.py` (38 controlli, Classica e Banco).

## 0.18.6 — 10/11/2026
- **Menu del tasto destro sul piano** (suggerimento di un utente), nell'interfaccia classica: un clic destro con lo strumento *Selezione* o *Nodi* apre il menu con i comandi più usati, gli stessi dei menu in alto e con le stesse scorciatoie.
  - **Su un oggetto**: *Taglia*, *Copia*, *Incolla*, *Duplica*, *Elimina*; *Raggruppa* o *Separa* (solo quando servono); *Rifletti* in orizzontale e in verticale, *Porta in primo piano* e *in fondo*; *Blocca* o *Sblocca*; *Converti in tracciato*, *Offset*; *Adatta alla selezione*. Se l'oggetto non era selezionato, il clic destro lo seleziona; se era uno di più oggetti selezionati, la selezione resta.
  - **Nel vuoto**: *Incolla* (gli oggetti arrivano dove hai fatto clic), *Incolla sul posto*, *Annulla*, *Ripeti*, *Seleziona tutto*, *Importa*, *Adatta al piano*.
  - Trascinando con il tasto destro non si apre niente, e con gli altri strumenti il tasto destro resta loro (la *Linea* ci chiude il tracciato).
  - Nel Banco non cambia niente: lì c'è già il menu radiale.
- Nuova prova automatica `tests/test_v186_menu.py` (13 controlli; 2 nel Banco).

## 0.18.5 — 10/11/2026
- **Comando dell'air assist a scelta: M8, M7 o nessuno** (richiesta su GitHub). Nel pannello *Macchina*, sotto l'area di lavoro, c'è la scelta **Air assist**: *M8 (il più comune)*, *M7* oppure *Nessun comando* (aria accesa a mano o sempre accesa). Si salva nel profilo della macchina e vale per i lavori, il test materiale, il test della scansione, la ripresa di un lavoro interrotto e il pulsante *Aria*.
  - Era anche un difetto: il profilo aveva già il comando dell'aria (e un profilo .lbdev con M7 lo impostava), ma i lavori e il pulsante usavano sempre M8 e M9. Con una scheda che vuole M7 l'aria non partiva.
  - Chi non tocca niente resta con M8 e M9, come prima.
- Nuova prova automatica `tests/test_v185_aria.py` (29 controlli, Classica e Banco).
- **Stampa e taglia (in prova, non ancora attivo per tutti)**, da una richiesta su GitHub («la funzione print and cut sarebbe il top»). Serve a tagliare con il laser attorno a qualcosa di già stampato con la stampante di casa: adesivi, etichette, sagome di cartoncino.
  - FreeLaserCut mette **due crocette** accanto al disegno (la 1 con un cerchio, la 2 con due) e salva il **PDF da stampare al 100%**, in A4, Letter o A3, con il disegno nelle misure vere. Si stampa quello che sta sui livelli con l'uscita spenta, crocette comprese; si taglia quello che ha l'uscita accesa.
  - Un'immagine si può aggiungere **a colori** per la stampa (l'importazione normale la porta in grigi, perché il laser incide solo quelli): va su un livello che il laser non tocca.
  - Il foglio stampato si fissa sul piano come capita, anche storto. Dopo l'homing si porta la testa, con le frecce e il puntino, sul centro delle due crocette: FreeLaserCut calcola dove sta il foglio, di quanto è ruotato e, se si vuole, di quanto la stampante ha sbagliato la scala, e **sposta il disegno sopra il foglio vero** (un solo passo, Ctrl+Z lo riporta com'era). Poi si avvia il lavoro come sempre.
  - Rifiuta, spiegando perché: crocette troppo vicine, stampa non al 100% (oltre il 3% di differenza), taglio che uscirebbe dall'area di lavoro, macchina senza homing fatto.
  - La funzione è nascosta finché non viene sbloccata in *Impostazioni → Funzioni in prova…*: per ora serve alle prove sulle macchine vere.
- I progetti salvano il compito delle forme speciali (le crocette); i progetti senza crocette restano identici.
- Nuova prova automatica `tests/test_v185_stampa_taglia.py` (63 controlli, 65 nel Banco): calcolo, PDF riletto e misurato, simulatore con un foglio storto di 3°, G-code sul foglio vero.

## 0.18.4 — 10/11/2026
Da un rapporto all'assistenza (Creality Falcon A1 10W: «la verifica dà sempre "la scheda ha smesso di rispondere"», e non si riusciva a incidere).
- **Risposte perse alla fine della verifica e del lavoro.** La scheda del Falcon A1 (ESP32-S3 con USB nativo) ogni tanto non manda la conferma «ok» di una riga: nel registro del rapporto ne mancava 1 su 13483 alla fine della verifica e 2 alla fine di un lavoro inciso per intero. FreeLaserCut aspettava conferme che non sarebbero mai arrivate:
  - la **verifica** si fermava con «la scheda ha smesso di rispondere», **sempre**, e il lavoro non partiva;
  - il **lavoro** veniva inciso tutto, ma non risultava mai finito («il lavoro non avanza»).
- Ora, se tutte le righe sono partite, ne mancano **al massimo 3** e la scheda è ferma e muta da qualche secondo, sono risposte perse: la verifica si chiude normalmente (dopo circa 2 secondi invece di 6) e il lavoro risulta completato, con un avviso che dice quante conferme sono mancate. Se mancano più risposte, oppure fra le ultime righe c'è una pausa G4, resta tutto come prima.
- Il messaggio «FreeLaserCut passa a una comunicazione più prudente: rifai la verifica» compare solo quando la comunicazione cambia davvero. Con le schede che la usano già (come il Falcon A1) rifare la verifica dava lo stesso risultato: ora il messaggio consiglia di scollegare e ricollegare il cavo USB e, se succede ancora, di togliere la spunta «Verifica il G-code con la scheda prima di partire» e mandare un rapporto.
- Il simulatore può perdere delle risposte scelte, per le prove.
- Nuova prova automatica `tests/test_v184_risposte.py` (23 controlli).

## 0.18.3 — 10/11/2026
- **Dopo il nesting i pezzi si scelgono di nuovo uno per uno** (da un commento sotto il video di presentazione: «dopo il nesting vedo gli oggetti come un oggetto solo e non riesco più a modificarli singolarmente»).
  - **Un clic su un oggetto di una selezione multipla seleziona solo quello.** Prima il clic non cambiava niente: con più oggetti selezionati si potevano solo spostare tutti insieme, e per sceglierne uno bisognava prima cliccare nel vuoto. Trascinando si spostano ancora tutti; Maiusc o Ctrl + clic aggiungono e tolgono come prima.
  - **A fine nesting non resta più selezionato tutto**: restano selezionati solo i pezzi che eventualmente non sono entrati.
  - **Linee di taglio comuni** (che unisce apposta i contorni in un tracciato unico): la spunta non viene più ricordata da un nesting all'altro, e il messaggio finale dice che con Ctrl+Z si riavranno i pezzi separati.
- Nuova prova automatica `tests/test_v183_selezione.py` (22 controlli, Classica e Banco).
- **Sito adattato a telefono e tablet**: nella pagina principale, sotto i 1080 px di larghezza, il menù si apre dal pulsante a tre lineette in alto a destra (prima le voci sparivano e basta); voci grandi da toccare, si chiude scegliendo una voce, toccando fuori o con Esc. Nella pagina della privacy gli indirizzi lunghi vanno a capo anche sui telefoni più stretti. Su computer le pagine sono identiche a prima.
- **Circuiti stampati: importazione diretta dei file Gerber** (da una domanda sotto un video: «può fare anche il Mirror per incidere un piccolo circuito stampato?»). *File → Importa*, o i file trascinati sul piano, apre i Gerber (RS-274X e X2) esportati da KiCad, EasyEDA, Eagle, Altium e simili, e i file dei fori Excellon. I file della stessa basetta (rame, contorno, fori) si scelgono insieme e restano a registro; decide il contenuto del file, non l'estensione.
  - Una finestra chiede **cosa incide il laser**: *lo spazio fra le piste* (metodo della vernice: il laser scopre il rame da togliere, l'acido fa il resto) oppure *le piste*; se **specchiare** (proposto da solo per il lato sotto, quello delle saldature); quanto **bordo** incidere attorno al disegno quando manca il contorno della basetta; come segnare i **fori** (diametro vero, solo un punto al centro per la punta, niente). L'**anteprima** mostra in scuro quello che verrà inciso, prima di importare.
  - La basetta arriva sul piano con le **misure vere** (non viene mai ridimensionata, e se è più grande del piano lo dice), come un oggetto solo, su livelli che il progetto non usa ancora: rame in *Riempimento*, contorno in *Linea*. I livelli già usati non vengono toccati.
  - Si leggono: aperture tonde, rettangolari, ad asola, poligonali e a **macro** (comprese quelle di KiCad per le piazzole con gli angoli tondi), tratti, archi, **regioni** (le zone di massa), oggetti scuri e chiari nell'ordine del file, specchio, rotazione e scala delle aperture, ripetizioni, millimetri e pollici. Per i fori: millimetri e pollici, asole e fresature; se il file dei fori non dice quante cifre sono decimali, si sceglie il formato che fa cadere i fori al centro delle piazzole.
  - **Due facce.** Scegliendo insieme il rame del lato sopra e quello del lato sotto, ogni faccia va su un suo **piano di lavoro** («Lato sopra» e «Lato sotto (specchiato)»), nella stessa posizione, con lo stesso bordo, gli stessi fori e le stesse impostazioni di incisione: incidi il primo piano, giri la basetta da sinistra a destra come la pagina di un libro, passi al secondo piano e incidi. Il lato sotto è specchiato attorno al centro dell'ingombro comune (il contorno della basetta, se c'è). Rimettere la basetta esattamente al suo posto dopo averla girata, con una dima o con riferimenti propri, resta compito di chi incide: FreeLaserCut tiene allineate fra loro le due facce, ma non può sapere dove viene appoggiata la basetta; lo dicono la finestra e un messaggio a fine importazione.
  - File vecchi o rovinati: quello che non si può leggere viene detto nella finestra (per esempio «apertura D11 non leggibile: gli oggetti disegnati con lei MANCANO»), mai taciuto. I Gerber vecchissimi senza l'elenco delle aperture (RS-274-D) non si aprono: vanno esportati di nuovo come RS-274X.
  - Dal collegamento con Claude: `flc_import_file` accetta `more_paths` (gli altri file della basetta), `mirror` e `negative`, e risponde con misure, scelte applicate e avvisi; da lì la finestra non si apre mai.
  - Il lettore è scritto da zero sul formato pubblico, senza librerie nuove. Controllato contro i disegni di riferimento di 68 file di prova e su 160 file veri di programmi diversi; resta da provare con il laser su una basetta vera.
- Nuova prova automatica `tests/test_v183_gerber.py` (167 controlli, Classica e Banco).

## 0.18.2 — 10/11/2026
- **Raggio degli angoli nella barra in alto**, subito dopo larghezza e altezza: campo **R** (mm) per rettangoli, poligoni e stelle, e accanto il pulsante dei **quattro angoli** del rettangolo (↖ ↗ ↘ ↙, «Ogni angolo a parte»). Con più forme selezionate il raggio vale per tutte, ognuna al massimo possibile, in un solo passo da annullare. Il raggio resta anche nel pannello *Proprietà*, e i due posti si aggiornano a vicenda.
- **Poligoni e stelle con gli angoli arrotondati** restando forme modificabili (lati, punte, rientranza): archi di cerchio tangenti ai lati, in mm veri anche dopo un ridimensionamento, anche negli angoli rientranti delle stelle; un raggio troppo grande si limita da solo senza che i raccordi si sovrappongano. I progetti senza raggio restano identici.
- Banco: le etichette X, Y, L, A della barra sotto la selezione ora si leggono (erano grigio scuro sul pannello scuro).
- Nuova prova automatica `tests/test_v182_raggio.py` (33 controlli, Classica e Banco).
- Sito: il **tutorial interattivo** (*Costrutto*) funziona anche con l'interfaccia **Banco**, scelta all'inizio della pagina, e ha tre missioni nuove di **Livello 2** (sottobicchiere con il punto di partenza, targhetta con la distanza esatta, inciso centrato sul pezzo); voce *Tutorial* in evidenza nel menu, logo e pulsante «Torna alla home» in cima al tutorial, pulsante *Sostieni* discreto con un piccolo cuore anche nelle altre pagine.

## 0.18.1 — 09/11/2026
- **Versione per Linux, prima uscita vera.** Con la 0.18.0 la prova automatica di GitHub su Ubuntu ha fermato l'AppImage: su un sistema senza alcune librerie di X11 (le estensioni di libxcb, per esempio libxcb-xkb) la finestra non si apriva. La prova ha fatto il suo lavoro: la Release 0.18.0 è uscita solo per Windows, come previsto. Ora quelle librerie sono dentro l'AppImage (licenza MIT) e la costruzione si ferma da sola se il plugin di Qt ne cerca ancora una nel sistema, tranne libxcb stessa.
- **Telecamere dei Creality Falcon** (segnalazione di un tester con Falcon A1 10W: «immagine tutta nera»).
  - Falcon A1 10W, telecamera USB nel coperchio: FreeLaserCut prova da solo più modi di lettura (DirectShow, Media Foundation, MJPG, risoluzione nativa), tiene il primo che non dà un'immagine nera e se lo ricorda; i nomi delle telecamere si leggono anche da Media Foundation e «Falcon»/«Creality» vengono scelte da sole.
  - Falcon A1 Pro, A1C e T1, telecamera di rete: nuova finestra 🌐 per collegarla (192.168.10.1 trovato da solo con il cavo USB, IP del laser in Wi-Fi, ricerca in rete); una richiesta alla volta, perché il server della macchina si blocca con richieste contemporanee.
  - Il pannello della camera spiega cosa fare se l'immagine è nera; il rapporto per l'assistenza contiene anche l'elenco delle telecamere e dei modi provati.
  - Catalogo: area del Falcon A1 10W corretta (381×305, prima era invertita), riconosciuto dal firmware CV40.
  - Non ancora provato su una macchina vera: lo proverà il tester con il rapporto da *Aiuto → Invia un rapporto all'assistenza*.
- **Autofocus: sonda letta al contrario.** Da un utente con laser CO2 e scheda MKS DLC32: con la sonda sull'ingresso «Probe» (IO22) l'autofocus funzionava solo cambiando a mano `$6` da 0 a 1, come succede con le sonde «normalmente chiuse». Ora la finestra *Laser → Asse Z e autofocus* ha il pulsante **Inverti il segnale della sonda ($6: 0 → 1)**: scrive il valore solo dopo la conferma, prima salva una copia delle impostazioni della scheda e poi rilegge `$$` per controllare; premendolo di nuovo si torna come prima. Se la sonda risulta «TOCCATA» per più di 3 secondi, la finestra spiega le due cause possibili (segnale al contrario o sonda non collegata). Con le schede senza `$6` (per esempio FluidNC) il pulsante resta spento e lo spiega. Anche il messaggio dell'allarme 4 rimanda al pulsante.
- Il simulatore tiene conto di `$6` e delle sonde normalmente chiuse.
- Nuova prova automatica `tests/test_v181_sonda.py` (36 controlli, Classica e Banco).
- **Anteprima del Riempimento corretta** (segnalazione di Stefano). Un quadrato con il suo offset sullo stesso livello in Riempimento mostrava l'interno più scuro, come se lì si incidesse di più, mentre il laser incide solo la fascia fra i due contorni (il G-code era giusto). Ora la zona colorata si calcola per livello intero, come il G-code: fascia piena e interno vuoto, sul piano e nelle miniature dei piani di lavoro. Con «Riempi forma per forma» le parti dove due forme si sovrappongono restano più scure, perché lì il laser passa davvero due volte; le linee aperte non si colorano, perché il G-code le ignora.
- Nuova prova automatica `tests/test_v181_anteprima.py` (24 controlli, Classica e Banco), che confronta l'anteprima con i tratti incisi del G-code vero.
- Per il resto non cambia niente rispetto alla 0.18.0.

## 0.18.0 — 09/11/2026
- **Versione per Linux.** FreeLaserCut esce anche per Linux, come **AppImage**: un solo file (`FreeLaserCut-<versione>-x86_64.AppImage`) con dentro lo stesso Python e le stesse librerie dell'installatore per Windows. Si scarica, si rende eseguibile e si apre: niente da installare, niente password. Serve un PC a 64 bit con Ubuntu 22.04, Debian 12, Fedora 35, Linux Mint 21 o più recenti.
- **Di pari passo con Windows.** Le due versioni vengono costruite dallo stesso codice e pubblicate insieme, nella stessa Release e con lo stesso numero: con il tag `vX.Y.Z` GitHub costruisce l'installatore e l'AppImage, li prova (Windows vero; Ubuntu con X11 vero, senza le librerie aggiunte; più Debian, Ubuntu 22.04, Fedora e Arch) e mette tutto in una Release con un solo `SHA256SUMS.txt`. Se la parte Linux non passa la prova, la Release esce lo stesso con la sola versione per Windows.
- **Chi collauda la versione per Linux.** Lo sviluppo e le prove con il laser e la camera veri si fanno su Windows e non si possono ripetere su Linux a ogni versione (troppe distribuzioni, desktop e configurazioni): **il collaudo su Linux lo fa chi lo installa**, sul proprio computer, e i problemi si segnalano da *Aiuto → Invia un rapporto all'assistenza*. Lo spiega una finestra al primo avvio su Linux (poi in *Aiuto → FreeLaserCut per Linux: collaudo e segnalazioni*), le *Informazioni*, il sito, il README e le note di ogni Release. Il rapporto ora contiene anche distribuzione, desktop (X11 o Wayland), piattaforma di Qt e stato delle porte USB; l'informativa parla di «sistema operativo» invece che di Windows.
- **Aggiornamento dal programma anche su Linux**: *Aiuto → Cerca aggiornamenti…* scarica la nuova AppImage della stessa Release, ne controlla l'impronta SHA-256 e, alla chiusura, la mette al posto di quella vecchia (stesso file, stessa cartella: menu e collegamenti restano validi), poi riapre FreeLaserCut. Se la cartella non è scrivibile lo dice prima di scaricare.
- **Porta USB su Linux**: i driver dei chip USB sono già nel sistema; serve il permesso del gruppo `dialout` (`uucp` su Arch). *Riconosci la macchina* ha il pulsante *Permesso della porta USB…* con i passi e il comando da copiare, dice se il tuo utente può già usare la porta e, se Connetti fallisce per i permessi, il messaggio spiega cosa fare.
- **Menu delle applicazioni**: al primo avvio (o da *Aiuto → Aggiungi FreeLaserCut al menu delle applicazioni*) FreeLaserCut si aggiunge al menu del desktop e apre i progetti `.flcut` con il doppio clic, solo per il tuo utente.
- Su Linux: riavvio (lingua, interfaccia) e apertura da Claude partono sempre dal file AppImage; su Wayland con XWayland si usa X11 per finestre e secondo monitor come su Windows (`FLC_WAYLAND=1` per restare su Wayland); certificati HTTPS presi dal sistema anche su Fedora e openSUSE. *Collega a Claude* mostra la riga per **Claude Code** (l'app Claude per desktop non c'è ufficialmente per Linux).
- Nell'AppImage le funzioni compilate con numba (foto, vettorizzazione) restano in cache fra un avvio e l'altro, anche se la cartella temporanea dell'AppImage cambia ogni volta; le cache delle versioni vecchie si tolgono da sole. Se esce una Release senza l'AppImage, la versione per Linux non propone l'aggiornamento e, cercandolo a mano, spiega che arriverà con la versione successiva.
- Nuovo `FreeLaserCut --self-test` (anche `…AppImage --self-test`): prova di avvio che non tocca le impostazioni e stampa le informazioni tecniche da allegare a una segnalazione.
- Nuovi `build/prepara_appimage.py` (costruzione dell'AppImage) e `freelasercut/linux.py`; workflow `installatore.yml` con le parti Linux; licenze delle librerie xcb aggiunte.
- Nuova prova automatica `tests/test_v180.py` (128 controlli, Classica e Banco, anche su Windows); `tests/test_v104_aggiorna.py` aggiornata alla nuova Release con Linux.

## 0.17.18 — 09/11/2026
Da un utente con uno Sculpfun C1.
- **Sculpfun C1 3W e 6W** nel catalogo dei modelli pronti (57 modelli): dati dalle pagine ufficiali Sculpfun, spot 0,04 mm (3W) e 0,06 mm (6W). Il produttore dà l'area 150 × 130 mm senza dire quale lato è X: il profilo parte da 130 × 130 per prudenza e, collegando la macchina, l'area vera si legge dalla scheda. Collegando un C1, *Laser → Riconosci la macchina* propone di scegliere fra 3W e 6W.
- Nuova prova automatica `tests/test_sculpfun_c1.py` (11 controlli).

## 0.17.17 — 09/11/2026
- **Forbici: i pezzi restano agganciati.** Prima, dopo i tagli, le parti rimaste erano forme separate: spostandone una si apriva il contorno e il riempimento non le vedeva come un pezzo unico. Ora, dopo ogni taglio, quello che resta si unisce alle forme **dello stesso livello** che tocca con gli estremi (anche a catena) e, quando il giro si chiude, diventa **un'unica forma chiusa**: si sposta tutta insieme e si riempie. Esempio: un rettangolo e un cerchio sovrapposti, tolte le due parti interne, diventano un solo contorno. Le forme su livelli diversi, bloccate o nascoste restano separate. Sempre un passo da annullare per ogni clic.
- Le forbici riconoscono meglio il contatto a T anche sulle curve: una linea che finisce esattamente su un cerchio ora lo divide sempre in quel punto.
- **Unisci estremi** (*Alt+J*, e lo strumento Nodi quando si trascina un estremo sull'altro) corretto: con due linee orientate al contrario (inizio con inizio, o inizio con fine) un pezzo poteva sparire o essere attaccato dalla parte sbagliata con un salto dritto. Ora le quattro combinazioni danno lo stesso risultato giusto.
- Nuova prova automatica `tests/test_v1717.py` (20 controlli); `tests/test_v1716.py` aggiornata alla nuova regola (pezzi agganciati).

## 0.17.16 — 09/11/2026
- **Forbici** (strumento nuovo, tasto **X**, icona delle cesoie): toglie le eccedenze dove le linee si incrociano, come il *Taglia* dei programmi CAD. Passando sopra una linea si colora di rosso il tratto fra i due incroci più vicini (o fino all'estremo): un clic e quel tratto sparisce. Gli incroci sono calcolati sulle curve vere, quindi i pezzi rimasti si toccano esattamente e le curve restano curve. Contano tutte le linee visibili del piano, anche la forma stessa, i lati in comune e i punti dove una linea tocca l'altra (a T). Con **Maiusc** ci si ferma anche agli angoli; una linea senza incroci si toglie tutta; ogni clic si annulla con Ctrl+Z. Le forme diventano tracciati (come con lo strumento Nodi); i gruppi vanno prima separati.
- **Distanza esatta fra due oggetti** (*Disponi → Distanza esatta…*, nel Banco nel menu *Allinea*), come nei programmi CAD: con due oggetti selezionati si scrive la distanza in mm e quello da spostare si mette lì, in orizzontale o in verticale. Si misura lo **spazio vuoto fra i due**, la distanza **fra i centri** oppure **fra due bordi scelti** (per esempio il bordo destro di uno e il centro dell'altro). Si vede subito sul piano; *Annulla* lascia tutto com'era, *OK* è un solo passo da annullare. Di solito resta fermo il primo selezionato (o quello bloccato), ma si può scegliere; *Dall'altra parte* lo porta sull'altro lato. Avviso se l'oggetto esce dall'area di lavoro. Le misure sono quelle di *Allinea* (l'ingombro dritto, anche per forme ruotate, testi e gruppi).
- **Rilievo 3D su tavola (in prova, non ancora attivo per tutti).** Scolpisce la tavola intera a strati con la testa a altezza fissa, da un'immagine in grigi o da un modello `.stl`/`.obj`: ogni strato è una passata sulle zone che devono scendere ancora, con righe alternate lungo X e lungo Y e i gradini sfumati. Profondità massima 5 mm e mai oltre lo spessore della tavola meno 2 mm.
- **Test di profondità obbligatorio**: una scala di gradini piccola (circa 25 × 4 mm, pochi minuti) da incidere su un ritaglio della stessa tavola; si misurano col calibro il primo e l'ultimo gradino e si dice com'è il fondo. Il rilievo parte solo se l'ultimo gradino è entro il 10% della profondità voluta, altrimenti FreeLaserCut ricalcola le passate (o la potenza, se ci sono fiamme o il fondo è annerito) e chiede un nuovo test. Il test si può saltare solo spuntando una casella con l'avviso dei rischi. Le tarature riuscite si ricordano per materiale e parametri.
- La funzione è nascosta finché non viene sbloccata in *Impostazioni → Funzioni in prova…*: per ora serve alle prove sulle macchine vere prima di aprirla a tutti.
- La ricerca dei comandi del Banco non mostra le funzioni nascoste.
- Nuova prova automatica `tests/test_v1716.py` (102 controlli, 105 nel Banco: rilievo, distanza esatta e forbici); `tests/test_v07.py` aggiornata.

## 0.17.15 — 08/11/2026
- **Raggio degli angoli corretto sui rettangoli ridimensionati.** Se il rettangolo era stato ingrandito o rimpicciolito dopo il disegno, il raggio usava le misure di allora: il massimo restava quello vecchio e, superato quello, i valori più bassi sembravano non cambiare niente. Ora il raggio è in mm veri sulle misure attuali, sotto il campo si vede il massimo (metà del lato più corto) e un valore più alto diventa il massimo.
- `tests/test_v1713.py` con 7 controlli in più (28).

## 0.17.14 — 08/11/2026
Da un utente con un Acmer P3.
- **Acmer P3** nel catalogo (24W, 48W, 2W IR, 2-in-1): area dai profili ufficiali Acmer della microSD (24W e 2W IR 400 × 400 mm, 48W e 2-in-1 400 × 390), velocità fino a 800 mm/s e spot dalla pagina ufficiale, **correzione della scansione avanti e indietro già impostata** con i valori di Acmer. 55 modelli pronti.
- **Laser → Importa un profilo macchina** apre anche il **profilo .lbdev** che molti produttori mettono sulla microSD o sul sito: se ne leggono nome, area di lavoro, velocità della porta, scala di potenza, origine, asse Z, aria e correzione della scansione. I comandi G-code del file non vengono presi. Le macchine non GRBL (per esempio con controller Ruida) vengono rifiutate con il motivo.
- Nuova prova automatica `tests/test_v1714.py` (18 controlli).

## 0.17.13 — 08/11/2026
- **Raccordo anche su un angolo solo.** Nelle *Proprietà* del rettangolo, con **Ogni angolo a parte**, ogni angolo ha il suo raggio (↖ ↗ ↘ ↙; 0 = spigolo vivo): si arrotonda uno solo, alcuni o tutti con raggi diversi. I progetti già salvati restano uguali.
- **Su qualsiasi forma**: con lo strumento *Nodi* (N), tasto **A** su un nodo = arrotonda quello spigolo con un arco del raggio scelto (si ricorda l'ultimo). Funziona tra due tratti dritti (poligoni, stelle, rettangoli, disegni importati); il raggio troppo grande si limita da solo a metà dei lati.
- Nuova prova automatica `tests/test_v1713.py` (21 controlli, Classica e Banco).

## 0.17.12 — 08/11/2026
Dalle prove di due utenti.
- **Schizzo del soggetto, pennello di nuovo veloce.** Più pennellate si davano, più il pennello rallentava: a ogni movimento del mouse si ridisegnavano tutte, pezzo per pezzo (con 40 pennellate 160 millesimi di secondo a movimento). Ora le pennellate finite si disegnano una volta sola e si ridisegna solo quella in corso: 6 millesimi anche con 100 pennellate. Una pennellata ha anche un colore uniforme, senza punti più scuri dove ripassa.
- **Zoom anche sulla foto originale** in *Prepara foto*: rotella o pulsanti *Zoom originale*, tasto destro (o centrale) trascinato per spostarsi, doppio clic col tasto destro per tornare a tutta la foto. Ritaglio, Riquadro e pennelli funzionano anche ingranditi.
- **Cerchio del pennello** sotto il mouse, grande come il pennello; pennello regolabile più fine (fino a metà di prima).
- **Asse Z e autofocus con sonda** (*Laser → Asse Z e autofocus…*), per le macchine con l'asse Z motorizzato: a laser spento la testa scende piano finché la sonda tocca il materiale (comando GRBL G38.2, corsa massima limitata), lo ritocca lentamente e si porta alla distanza di fuoco. Nella finestra si vede dal vivo se la scheda sente la sonda, e se la vede come *finecorsa Z* lo dice: la sonda va collegata all'ingresso «Probe» della scheda (sulla MKS DLC32 è IO22, dal firmware ufficiale MKS), non al finecorsa Z (IO34). Errori spiegati: sonda già toccata ($6), nessun tocco entro la corsa, finecorsa, firmware senza G38.2. Nel pannello *Movimento* compaiono i pulsanti Z ▲ ▼ e *Autofocus*.
- Il simulatore conosce la sonda (G38.2, ingresso Probe o finecorsa Z) per le prove.
- Nuova prova automatica `tests/test_v1712.py` (34 controlli, Classica e Banco); `tests/test_v102.py` aggiornata (la foto originale ora ha lo zoom).

## 0.17.11 — 08/11/2026
- **Aggiornamento dal programma**: se lo scaricamento non riusciva, la finestra compariva e spariva subito senza dire niente (l'errore veniva scambiato per un «Annulla»). Ora il motivo si vede e finisce nel registro, così entra anche nel rapporto per l'assistenza.
- Gli errori passeggeri di GitHub (server occupato, errore 502/503/504, collegamento caduto a metà) si riprovano da soli fino a 3 volte; se GitHub continua a non rispondere, il messaggio lo dice e propone il sito.
- Costruzione dell'installatore: lo scaricamento di Python per Windows riprova da solo se GitHub non risponde.
- Prove automatiche: le suite dalla 0.17.2 in poi non risultano più «interrotte» su Windows a prove superate (chiusura comune in `tests/_uscita.py`). Nuova prova `tests/test_v1711.py` (10 controlli, Classica e Banco).

## 0.17.10 — 08/11/2026
(Il tag v0.17.9 era stato creato con il programma ancora alla 0.17.8, quindi l'installatore non è stato costruito: questa versione la sostituisce.)
- Il riassunto del rapporto contiene anche l'ultimo errore del programma, così i rapporti con lo stesso problema si riconoscono e si raggruppano.
- Ricevitore (`tools/rapporti/Codice.gs`, versione 2): registro dei rapporti, scrematura automatica di rapporti vuoti, doppioni e versioni vecchie, e un riepilogo raggruppato per problema quando ce ne sono abbastanza.

## 0.17.8 — 08/11/2026
- **Invia** nella finestra *Aiuto → Invia un rapporto all'assistenza…* ora c'è: il ricevitore dei rapporti del progetto è attivo, e il rapporto arriva a freelasercut@gmail.com con un clic, senza programmi di posta. Resta anche *Invia per email…*.
- Nuova prova automatica `tests/test_v178.py`; `tests/test_v177.py` prova a parte il caso senza ricevitore.

## 0.17.7 — 08/11/2026
- **Aiuto → Invia un rapporto all'assistenza…** Si racconta cosa è successo (oggetto, cosa stavi facendo, cosa ti aspettavi, cosa è successo, se succede sempre), con l'email solo se si vuole una risposta. Il rapporto ha un codice (FLC-…) e si può vedere prima con *Mostra il contenuto* o salvare come file.
  - **Invia** lo manda al progetto via Internet, senza programmi di posta (al ricevitore del progetto: un'app web di Google Apps Script sull'account freelasercut@gmail.com, `tools/rapporti/`; nel programma c'è solo il suo indirizzo pubblico, nessuna password).
  - **Invia per email…** apre il programma di posta con il messaggio per freelasercut@gmail.com già scritto e la cartella con il rapporto, da trascinare nella mail.
  - Si invia **solo con il consenso** all'informativa privacy, che la finestra riassume; niente parte mai da solo.
- **Rapporto più completo**: oltre a sistema, profilo, $$ e $I, registro della comunicazione ed errori, ora contiene la descrizione, l'ultimo lavoro (impostazioni dei livelli, ingombro, partenza, prime e ultime righe di G-code e dove si è fermato, non il disegno), le porte USB con chip e driver, le ultime copie delle impostazioni della scheda, gli ultimi comandi usati nei menu, le impostazioni di Prepara foto della foto selezionata (senza la foto), la calibrazione della camera, lingua e separatore decimale di Windows, se si usava il simulatore, velocità della porta e ultimo allarme; l'immagine della finestra solo se la si sceglie. Il nome della cartella utente viene sempre tolto.
- **Informativa privacy** aggiornata (sito, `docs/privacy.html`) con il rapporto per l'assistenza: cosa contiene, perché, dove resta (12 mesi), analisi anche con strumenti di intelligenza artificiale, diritti e come chiedere la cancellazione con il codice.
- **Linguette dei piani** (*Piano 1*, *Piano 2*…) più leggibili: scritte più scure e più grandi, fondo meno trasparente.
- Nuova prova automatica `tests/test_v177.py` (24 controlli, Classica e Banco).

## 0.17.6 — 08/11/2026
Dalle prove di un utente.
- **Il simulatore non tocca più il profilo della macchina vera.** Collegandosi al simulatore, le sue impostazioni finte (area 450 × 440, scheda «LS_ESP32-SIM», accelerazioni) entravano nel profilo della macchina, e l'homing lo salvava. Ora con il simulatore la tabella delle impostazioni si vede ma il profilo non cambia, l'homing non lo salva, staccando il simulatore torna il profilo salvato e *Riconosci la macchina* chiama il profilo «Simulatore», così non finisce mai sopra quello della macchina vera.
- **Schizzo del soggetto, pennelli precisi.** *Togli* toglieva «molto più di quello selezionato» e *Tieni* sembrava non fare niente: i pennelli si allargavano da soli ai pezzi con colori simili. Ora di partenza **Tieni e Togli agiscono esattamente dove passa il pennello**, come una gomma, con bordi netti; dove due pennellate si sovrappongono vince l'ultima. Il comportamento di prima resta con la casella **Segui i bordi** (una pennellata e sparisce un oggetto intero), e vale per le pennellate date da quel momento.
- **Riquadro**: di partenza dentro resta tutto e fuori sparisce, niente viene tolto all'interno. Con la casella **Cerca il soggetto nel riquadro** FreeLaserCut cerca da solo il soggetto dentro il riquadro, come prima.
- **Velo rosso** sulla foto originale, a sinistra: si vede subito quali parti spariscono, senza guardare il risultato.
- Gli aiuti salvati nei progetti con le versioni precedenti funzionano come allora.
- Nuova prova automatica `tests/test_v176.py` (23 controlli, Classica e Banco); `tests/test_v05.py` aggiornata (il profilo del simulatore ora si chiama «Simulatore»).

## 0.17.5 — 07/11/2026
- **Calibrazione della camera con i punti messi a mano.** Con il bersaglio inciso (i dischi da 4 mm sul cartone) il riconoscimento automatico poteva prendere per dischi anche macchie fuori dal cartone, e la calibrazione veniva sbagliata. Ora i cerchietti si possono mettere a mano sulla foto:
  - **alla fine della calibrazione** con il bersaglio inciso c'è il pulsante *Controlla i punti a mano…* (e, se la calibrazione non è riuscita, FreeLaserCut chiede se vuoi mettere tu i punti);
  - **in qualunque momento**: pannello *Camera* → *Metti i punti a mano sui dischi incisi…*. Il cartone deve essere ancora dove è stato inciso: la testa si sposta fuori dall'inquadratura (laser spento) e la camera fa una foto. Il punto di parcheggio della testa si ricorda dalla calibrazione precedente.
  - **FreeLaserCut dice quale disco cercare**: numero (lo stesso ordine in cui sono stati incisi, a serpentina dallo zero), riga e colonna, posizione sul piano e uno schema del piano con il disco in rosso. Si comincia dai quattro angoli: il n° 1 è quello vicino allo zero, davanti a sinistra.
  - Il cerchietto si **aggancia da solo** al centro del disco scuro vicino al clic. Dopo i primi 4, FreeLaserCut **trova da solo gli altri** (arancioni, da controllare): si trascinano quelli fuori posto, tasto destro per toglierne uno, *Questo disco non si vede* per saltarne uno.
  - *Calcola e usa la calibrazione* (servono almeno 9 dischi): se un cerchietto è sul disco sbagliato la precisione è troppo bassa e il più sospetto viene indicato in rosso, invece di salvare una calibrazione sbagliata.
- Nuova prova automatica `tests/test_v175.py` (19 controlli, Classica e Banco): foto simulata con 36 dischi e 6 macchie estranee, riconoscimento automatico sbagliato apposta, 4 angoli messi a mano un po' storti, calibrazione precisa entro 0,6 mm.

## 0.17.4 — 07/11/2026
- **Profilo salvato con un'area di lavoro assurda.** Un utente vedeva il piano 365 × 32764 mm anche senza il laser collegato: le versioni precedenti avevano salvato nel profilo un valore letto male dalla scheda, e il profilo resta anche disinstallando (sta nella cartella nascosta `%APPDATA%\FreeLaserCut\profiles`). La 0.17.2 controllava solo le nuove letture. Ora, all'apertura, un profilo con un'area non credibile torna all'area dichiarata dal produttore del modello (o 400 mm per il laser generico; l'asse buono resta), si salva così e un avviso dice cosa è cambiato, con il pulsante *Area di lavoro*.
- **Area di lavoro a mano, anche senza laser collegato**: nel pannello *Macchina* (nel Banco dentro l'Officina) ci sono i due campi X × Y e *Usa questa area*, che salva il profilo e ridisegna il piano. Prima si poteva solo da *Riconosci la macchina*, con il laser collegato.
- **Controlli della macchina:** la riga dell'area si confrontava sempre con la targa del Longer B1 («targa 450×440»), anche con le altre macchine. Ora si confronta con l'area dichiarata dal produttore del modello scelto, se è nel catalogo; altrimenti dice solo l'area.
- `tests/test_v173.py`: 25 controlli (11 nuovi, con un profilo salvato da 365 × 32764 mm).

## 0.17.3 — 07/11/2026
- **Schede ESP32 che restano mute anche dopo il reset morbido.** Dalle immagini di un utente su GitHub (grblHAL su ESP32 con chip USB CH9102): all'apertura della porta l'ESP32 restava in **modalità di programmazione**, dove GRBL non gira, e ripartiva solo premendo il pulsante sulla scheda. Il Ctrl+X della 0.16.3 lì non arriva. Ora, se dopo il Ctrl+X la scheda è ancora muta, FreeLaserCut la **riavvia dalle linee DTR/RTS** della porta USB: è la stessa sequenza dello strumento ufficiale di programmazione delle ESP32 e fa come il pulsante, con la scheda che riparte normale. Poi le due linee restano spente. Una volta sola e solo se la scheda è muta: le schede che rispondono subito, il Wi-Fi e il simulatore non cambiano.
  - Lo stesso anche in **Riconosci la macchina**: se la scheda non risponde, la riavvia una volta dalla porta e riprova.
  - L'avviso «la scheda non risponde» arriva dopo 9 secondi invece di 6, per lasciare a FreeLaserCut il tempo di provare da solo.
  - Nella console il messaggio di avvio dell'ESP32, che a un'altra velocità è una riga di simboli illeggibili, diventa «(messaggio di avvio della scheda a un'altra velocità: illeggibile, è normale)».
- **Strumento Misura leggibile.** La linea gialla chiara e sottile sul piano chiaro si vedeva appena. Ora la linea è arancio scuro con un bordo scuro, i due punti sono pieni e la misura sta su un'etichetta scura con il testo bianco, accanto alla linea senza coprirla. Sotto la distanza si leggono anche ΔX, ΔY e l'angolo.
- Nuova prova automatica `tests/test_v173.py` (14 controlli, Classica e Banco), con una scheda simulata che resta in programmazione finché non viene riavviata dalle linee.

## 0.17.2 — 07/11/2026
Dalle prove di un utente.
- **Area di lavoro non credibile ignorata.** Collegando il laser, il piano era diventato 400 × 234500 mm: la scheda aveva risposto `$131=234500`, probabilmente «234.500» arrivato senza il punto. Ora un'area ($130/$131) sotto 10 mm o sopra 3000 mm non diventa il piano: FreeLaserCut lo dice e rilegge le impostazioni una volta. Se il valore resta, un avviso mostra il valore, il piano che resta in uso e i pulsanti *Impostazioni della scheda* e *Rileggi*. Lo zero (corsa non impostata) resta normale, come prima.
  - Non si usa nemmeno per riconoscere il modello (*Riconosci la macchina*), con una nota che spiega come correggerlo.
  - Il **ripristino di una copia** delle impostazioni non rimanda mai un'area non credibile, e lo dice.
  - Scrivendo un valore così nella tabella delle impostazioni, FreeLaserCut chiede di ricontrollare (con il «No» già scelto).
- **Foto troppo fitte per la porta seriale.** Con il dithering ogni punto è un comando: a velocità alte la porta non riesce a mandarli abbastanza in fretta e la testa va a scatti (segnalato oltre 10000 mm/min). FreeLaserCut ora stima, dalla velocità della porta e dai punti della foto, fin dove si può andare, e lo dice nel riepilogo del pannello Laser e all'avvio.
  - All'avvio si può scegliere **Compatta e avvia**: i punti vicini con la stessa potenza diventano tratti più lunghi, solo nei livelli dove serve. Stessi toni (stessa quantità di bruciato), meno comandi (circa la metà), dettagli più fini un po' meno netti lungo la riga. Con il dithering a diffusione dell'errore la foto si rifà su punti più lunghi; con toni di grigio, retino e soglia i punti vicini si uniscono.
  - Oppure **Avvia così**, con il consiglio di abbassare la risoluzione o la velocità del livello o di alzare la velocità della porta (*Laser → Velocità della porta seriale…*).
  - In Wi-Fi e con il simulatore la stima non si fa.
- **Override sopra il 100% spiegati.** Durante il lavoro velocità e potenza si abbassano sempre, ma sopra il 100% la scheda non supera la sua potenza massima ($30) né la velocità massima degli assi ($110/$111); sui tratti corti contano anche le accelerazioni. È il comportamento di GRBL: ora lo spiegano i suggerimenti dei cursori (e dei pulsanti +/− del Banco), e lasciando un valore sopra il 100% la barra di stato dice fin dove la scheda può davvero salire.
- **Mecpow X3S 7W e X3S 12W** nel catalogo: 360 × 360 mm, 10000 mm/min, spot 0,05 × 0,07 e 0,06 × 0,08 mm, dalle pagine ufficiali Mecpow. Nota sul kit di estensione dell'asse Y (360 × 730 mm). 51 modelli pronti.
- Nuova prova automatica `tests/test_v172.py` (44 controlli, Classica e Banco).

## 0.17.1 — 07/11/2026
- **Aiuti per il soggetto dello Schizzo più prevedibili**, dopo le prove di un utente su foto vere (un'auto, un coccodrillo):
  - **Riquadro**: quello che sta fuori è sempre sfondo. Prima, se dentro il riquadro non si trovava un soggetto, si disegnava tutta la foto; ora resta il riquadro.
  - **Togli** fa sparire la parte sotto il pennello e quello che le è attaccato con colori simili (il canestro intero, l'ombra), solo intorno al pennello. Prima, se lo sfondo non si era trovato da solo, *Togli* non faceva niente.
  - **Tieni** riporta la parte sotto il pennello e quello che le è attaccato, solo intorno al pennello: non aggiunge più pezzi lontani. Su una parte che c'è già (per esempio una ruota) non cambia nulla. Prima un *Tieni* su una foto difficile poteva lasciare solo il pezzo dipinto.
  - Quando lo sfondo non si trova da solo, il riquadro *Soggetto* lo dice e suggerisce il *Riquadro*.
- **Schizzo un po' più leggero**: meno grafite nei mezzi toni, più carta (era ancora un po' «coprente»).
- `tests/test_v170.py`: 30 controlli (6 nuovi sugli aiuti).

## 0.17.0 — 07/11/2026
- **«Schizzo del soggetto» rifatto**, dopo le prove di un utente: sui volti era poco riconoscibile, il tratto era troppo «riempitivo» e lo sfondo non sempre spariva (in una foto di un'auto restavano l'ombra sul ghiaino e il canestro dietro). Tutto dentro FreeLaserCut, senza intelligenza artificiale né file scaricati.
  - **Tratto a matita più realistico:** grafite sfumata a tratti nella direzione della mano (tratti lunghi e corti sovrapposti), un secondo strato incrociato solo nelle ombre più scure, la grana della carta, contorni puliti, occhi e ombre profonde pieni e tanta carta bianca. I volti restano riconoscibili. *Intensità* rende più scuro, *Dettaglio* fa i contorni più fini.
  - **Aiuti per il soggetto:** con l'effetto Schizzo in *Prepara foto* compare il riquadro *Soggetto*. **Riquadro**: trascina sulla foto a sinistra un rettangolo intorno al soggetto (quello che resta fuori è sfondo). **Tieni** e **Togli**: pennellate su quello che deve restare o sparire (ombre, oggetti dietro), con il pennello grande quanto vuoi. *Togli gli aiuti* li cancella. Gli aiuti girano con la foto, valgono anche con il ritaglio e si salvano nel progetto.
  - Senza aiuti il soggetto si cerca come prima, nel riquadro centrale della foto.
- Nuova prova automatica `tests/test_v170.py` (24 controlli, Classica e Banco): soggetto con riquadro, «togli» sull'ombra, «tieni» sul palo, tratto, finestra Prepara foto usata con il mouse.

## 0.16.3 — 07/11/2026
- **Schede ESP32 che restano mute dopo la connessione.** Con alcune schede ESP32, per esempio con il chip USB CH9102 e grblHAL, dopo l'apertura della porta la scheda non rispondeva finché non si premeva il pulsante di reset sulla scheda. Ora, se in 2,5 secondi dalla connessione la scheda non ha mai risposto, FreeLaserCut le manda da solo un reset morbido (Ctrl+X, lo stesso del pulsante) e poi richiede le sue informazioni. Succede una volta sola e solo se la scheda è muta: le schede che rispondono subito, il Wi-Fi e il simulatore non cambiano. Se nemmeno così risponde, resta l'avviso della 0.16.1 con *Riconosci la macchina* e *Velocità a mano…*. Segnalato e provato da un utente su GitHub con un laser CO2 (grblHAL a 250000 e 230400 baud).
- Nuova prova automatica `tests/test_v163.py` (10 controlli, anche con una scheda simulata che resta muta finché non riceve il reset).

## 0.16.2 — 07/11/2026
- **Corretto: homing non riuscito preso per buono.** Se l'homing veniva interrotto da un allarme (per esempio 6, «Homing interrotto da un reset») e la scheda si riavviava e si sbloccava da sola, come fa la scheda LGT del Longer B1, FreeLaserCut prendeva la posizione di quel momento per lo zero della macchina. Pensava di avere le coordinate «negative» e mandava contorno e lavoro fuori dall'area: la macchina rispondeva con l'errore 15 e l'allarme 2 e il lavoro si fermava subito in partenza. Ora un homing con un allarme (o con un riavvio della scheda a metà) non vale: resta l'avviso dell'allarme con *Homing* per rifarlo. Visto in un rapporto per l'assistenza.
- **Messaggio più chiaro:** se un lavoro si ferma per un allarme e subito dopo la scheda si riavvia, il messaggio dice l'allarme (per esempio «Comando oltre l'area di lavoro») invece di «La scheda si è riavviata durante il lavoro».
- **Foto del test dal telefono:** la finestra con il codice QR si apre davanti. Su Windows restava dietro la finestra del Test materiale e bisognava spostarla per vederla.
- Nuova prova automatica `tests/test_v162.py` (11 controlli, Classica e Banco), con la sequenza vera del rapporto.

## 0.16.1 — 07/11/2026
- **Velocità della porta seriale anche a mano.** Di partenza resta 115200 baud (quella standard di GRBL) e *Laser → Riconosci la macchina…* continua a provare da sola 115200, 250000, 230400, 57600, 38400 e 9600 e a salvare quella giusta. Per chi sa che la sua scheda usa un'altra velocità c'è ora *Laser → Velocità della porta seriale…* (anche con il **tasto destro su Connetti**): si sceglie dall'elenco o si scrive il valore (da 1200 a 2000000), si prova con **Prova questa velocità** (apre la porta e chiede alla scheda chi è, senza muovere niente e senza cambiare il profilo) e solo con **Salva nel profilo** diventa quella che usa Connetti. In Wi-Fi e con il simulatore la velocità non conta e la finestra lo dice.
- **Avviso se la scheda non risponde:** se dopo la connessione la scheda resta muta per qualche secondo (di solito velocità sbagliata), compare un avviso con *Riconosci la macchina* e *Velocità a mano…*. Prima sembrava collegata ma non succedeva niente.
- Nuova prova automatica `tests/test_v161.py` (17 controlli, Classica e Banco).

## 0.16.0 — 07/11/2026
- **Materiali imparati: FreeLaserCut impara il tuo legno.** Ogni materiale, e ogni tavola, risponde al laser a modo suo. Dalla foto di un test materiale FreeLaserCut misura come ha risposto il tuo materiale e se lo ricorda; poi lo usa per prevedere il risultato, scegliere la potenza e correggere le foto. Funziona con qualsiasi laser GRBL e non serve niente in più: bastano il test con i riferimenti e una foto (dal telefono, da un file o dalla camera).
  - **Impara:** nel risultato di *Leggi la foto del test* c'è il pulsante **Impara questo materiale…**: un nome nuovo (per esempio «Tiglio 3 mm») oppure **affina** un materiale già imparato. Da ogni quadrato FreeLaserCut ricava quanto diventa scuro il materiale con quella energia (potenza, velocità e interlinea insieme) e il suo colore vero. La curva è sempre crescente: più energia non dà mai un tono più chiaro.
  - **Si affina a ogni foto:** ogni nuovo test dello stesso materiale si aggiunge ai precedenti; le foto più recenti pesano di più, così se la tavola o il lotto cambiano la curva li segue. Si tengono le ultime 12 foto. Se la luce della foto non è uniforme lo dice.
  - **Laser → Materiali imparati…:** l'elenco dei materiali con la loro curva (quanto scurisce a ogni potenza, alla velocità scelta, con i punti misurati) e sotto i **colori che avrà il tuo legno**. Scegli un livello e un **tono** con il cursore: FreeLaserCut dice che potenza serve a quella velocità e, con *Applica al livello*, la imposta (si annulla con Ctrl+Z). Se al 100 % non ci arriva propone la velocità giusta. I valori fuori da quelli provati nei test sono segnati come stima.
  - **Foto con i toni giusti:** il legno non scurisce in proporzione alla potenza (i primi gradi scuriscono molto, poi satura) e nelle foto in scala di grigi i toni scuri si impastano. Scegliendo il materiale imparato nel livello (*Impostazioni del livello → Immagine → Materiale imparato*, oppure *Applica al livello* dalla finestra) i grigi della foto diventano toni **equidistanti sul tuo legno vero**, tra la potenza minima e la massima del livello. Per un livello Immagine *Applica* propone anche le potenze minima e massima adatte a quel materiale.
  - **Anteprima che prevede il risultato:** nell'anteprima del lavoro, in *Resa realistica*, i materiali imparati sono nell'elenco (parte da quello usato dal disegno) e mostrano scurezza e colori misurati sul tuo legno, per scritte, riempimenti e foto. In *Prepara foto* la nuova voce **Sul materiale** mostra in «Come verrà incisa» il risultato previsto su quel legno, con la potenza del livello; con *Usa la potenza consigliata* imposta le potenze adatte.
  - **Da dare a qualcuno:** *Esporta…* salva un materiale imparato in un file `.json`, *Importa…* lo aggiunge (anche da un amico con la stessa macchina). Nessun invio in rete. Se apri un progetto che usa un materiale imparato che non c'è su quel computer, il lavoro si fa lo stesso con i toni come prima e c'è un avviso.
  - **Attenzioni:** il nero pieno di una foto non prende di colpo tutta la potenza quando il legno è già saturo (si ferma dove il legno smette di scurirsi davvero); con il tratteggio incrociato la potenza tiene conto della seconda passata; le linee di taglio non sono nell'elenco dei livelli; se cambi l'interlinea nella finestra va anche sul livello; un materiale della libreria applicato a un livello toglie la curva imparata del precedente; un test senza titolo non viene mescolato con un materiale già imparato. Se l'archivio dei materiali imparati non si riesce a leggere (per esempio modificato a mano) non viene sovrascritto: resta da parte con un altro nome.
- **Taratura da foto sui materiali che il laser schiarisce** (ardesia, alluminio anodizzato nero): se la maggior parte dei quadrati è più chiara del materiale nudo, la misura va dal nudo al bianco pieno. Prima quasi tutti i quadrati risultavano «al massimo» e i valori proposti erano poco utili. Sul legno la lettura è identica a prima.
- Nuova prova automatica `tests/test_v160.py` (78 controlli, con l'interfaccia Classica e con Banco): curva da foto sintetiche di un legno con risposta nota, previsione di un test mai visto, toni equidistanti, ardesia, legno che cambia, file rovinati, G-code, anteprima e finestre. In più 6.000 curve casuali senza errori e una revisione indipendente del codice, con i punti importanti sistemati.

## 0.15.0 — 06/11/2026
- **Piani di lavoro: più lavori nello stesso progetto.** Mentre il laser incide un piano si prepara già il successivo, senza toccare il lavoro in corso.
  - **Linguette sul piatto:** in alto a sinistra, attaccate al bordo del piano disegnato, ci sono le linguette *Piano 1*, *Piano 2*… e il **+** per aggiungerne uno. Clic su una linguetta per passare a quel piano, oppure **Ctrl+PagSu / Ctrl+PagGiù**; doppio clic per rinominarlo (per esempio «Coperchio»); tasto destro per spostarci gli oggetti selezionati, duplicarlo o eliminarlo. Le linguette seguono zoom e spostamenti; se il bordo del piano esce dalla vista restano in alto. Le stesse voci sono in *Modifica → Piani di lavoro*.
  - **Stessa macchina, stessi livelli:** ogni piano ha solo i suoi oggetti; profilo della macchina, area di lavoro e impostazioni dei livelli sono in comune. Anteprima, tempo stimato, *Salva G-code*, contorno, nesting, Puzzle e Scultura lavorano sul piano attivo, e si incide sempre il piano attivo.
  - **Vista d'insieme:** il pulsante accanto al **+** (o **Ctrl+Maiusc+O**, o *Modifica → Piani di lavoro*) mostra tutti i piani affiancati e in ordine (1, 2, 3…, quattro per riga), ognuno con il suo piano, il nome e il numero di oggetti; il piano in incisione ha il bordo arancione, l'avanzamento e il punto dove passa il laser, che si aggiorna mentre incide. Rotella per lo zoom, trascina per spostare, doppio clic sul vuoto per rivederli tutti; un clic su un piano lo apre per modificarlo, Esc torna alla vista normale. Serve per guardare: lì non si modifica niente (i tasti che modificano i disegni non fanno nulla; Avvia, Pausa, Stop, Salva e il cambio di piano funzionano). Ogni piano viene disegnato una volta e riusato, così resta veloce anche durante l'incisione.
  - **Progetti grandi:** con foto vettorializzate o serie di migliaia di pezzi su un piano, il grigio sugli altri piani usa un contorno semplificato: spostare e ingrandire la vista resta veloce.
  - **Riferimenti visibili:** gli oggetti degli altri piani si vedono in grigio sotto il piano attivo (non si selezionano e non vengono incisi); l'icona a forma di strati accanto al **+** li nasconde. Durante l'incisione si vedono anche il percorso del lavoro, la testa e la traccia, da qualunque piano.
  - **Mentre incide:** la linguetta del piano in incisione ha ▶ e l'avanzamento in percentuale. Sugli altri piani si disegna liberamente; nell'interfaccia Banco la cabina di comando si fa da parte (restano la scritta *Incisione in corso* e i pulsanti Pausa e Stop) e torna completa riaprendo il piano in incisione. Il piano in incisione non si può eliminare.
  - **Annulla per piano:** ogni piano ha la sua cronologia; annullare su un piano non cambia gli altri, né i livelli modificati lavorando su un altro piano. *Sposta su un altro piano* si annulla dal piano di partenza (gli oggetti tornano e spariscono dall'altro; se nel frattempo là sono stati raggruppati o eliminati lo dice invece di duplicarli). Un livello non viene mai tolto da un annulla se un altro piano lo usa. Copia e incolla funzionano fra un piano e l'altro.
  - **Un solo file:** tutti i piani, con i nomi e il piano attivo, si salvano nello stesso progetto `.flcut`. I progetti di prima si aprono come *Piano 1*; un progetto con più piani aperto con una versione precedente mostra solo il primo piano (e, se lo si salva con quella versione, gli altri piani si perdono). Con un piano solo il file è identico a prima.
  - I livelli liberi scelti da Puzzle, Scultura, codici QR e a barre e strumenti tengono conto di tutti i piani; importando un `.lbrn2` un livello usato su un altro piano tiene le sue impostazioni; foto e disegni restano su livelli separati anche fra piani diversi.
  - Mentre il laser incide un piano: l'anteprima di un altro piano non copre sulla tela il percorso del lavoro in corso; i numeri di serie avanzano con i testi del piano inciso; se la scheda chiede di rifare la verifica (G55) dopo che sei passato a un altro piano, il lavoro non riparte da solo; la ripresa dopo un'interruzione resta del piano che si stava incidendo.
  - Scorciatoie: **Ctrl+Maiusc+N** nuovo piano, **Ctrl+PagSu / Ctrl+PagGiù** piano precedente / successivo (anche in *Aiuto → Scorciatoie da tastiera*). La rotella sopra le linguette fa lo zoom e non cambia piano; con molti piani compaiono le frecce; nel Banco le linguette non finiscono sotto i pannelli.
  - Collegamento con Claude (MCP): lo stato dice il piano attivo e l'elenco dei piani; *nuovo progetto* e *apri* non buttano via il lavoro non salvato degli altri piani.
- **Corretto (c'era anche prima):** copiando, duplicando o mettendo in serie un gruppo che contiene altri gruppi, i gruppi interni restavano con lo stesso codice dell'originale; separandoli si avevano due forme con lo stesso codice e annulla/selezione potevano confondersi. Ora ogni copia ha codici nuovi.
- Nuova prova automatica `tests/test_v150.py` (92 controlli con l'interfaccia Classica, 94 con Banco: anche un lavoro vero sul simulatore mentre si disegna sull'altro piano, un avvio con verifica, linguette e vista d'insieme usate con il mouse). In più, prima della pubblicazione: prove anche con la grafica vera (X11) oltre che senza schermo, avvio completo del programma, e 25.500 sequenze casuali di 120 operazioni (aggiungi, elimina, raggruppa, sposta fra piani, livelli, annulla/ripeti, duplica ed elimina piani, salva e riapri) senza forme doppie, perse o livelli senza impostazioni.

## 0.14.2 — 06/11/2026
- **Scultura 3D: niente più blocchi con i modelli scomodi.** Un portachiavi 3D (basso e largo) con l'altezza di partenza di 120 mm diventava una scultura larga più di 2 metri, di centinaia di pezzi più grandi del foglio: «Crea i pezzi» restava fermo per decine di minuti e, chiusa la finestra, il programma continuava a lavorare in sottofondo.
  - **Altezza giusta da subito:** aprendo un file `.stl` o `.obj` l'altezza è quella vera del modello (in mm), ridotta solo se la base non entrerebbe nel foglio. Lo stesso quando si cambia l'asse verticale. L'altezza minima ora è 5 mm, così un oggetto basso resta basso.
  - **Avvisi prima:** sotto le misure compare in rosso se ci sono pezzi più grandi del foglio (con le misure del più grande), se servono più di 10 fogli o se i pezzi sono più di 300. Premendo *Crea i pezzi* in questi casi il programma chiede conferma: *Crea comunque* oppure *Torna alle misure*.
  - **Sempre interrompibile:** i calcoli lunghi della scultura e la sistemazione dei pezzi sui fogli mostrano l'avanzamento con il pulsante *Annulla*. Annullando non viene aggiunto nulla al progetto e i livelli restano come prima.
  - **Molto più veloce:** i pezzi vengono preparati una volta sola, quelli più grandi del foglio si mettono subito da parte (a destra, come prima), su un foglio pieno non si provano i pezzi che non ci starebbero e i pezzi uguali (le fette di un oggetto estruso, come un portachiavi o una targa) si riconoscono. Il caso del portachiavi da 168 pezzi passa da oltre mezz'ora a circa 30 secondi; con l'altezza giusta, circa un secondo. Anche il calcolo delle fette è circa 7 volte più veloce.
- Nuova prova automatica `tests/test_v142.py` (21 controlli).

## 0.14.1 — 06/11/2026
- **Anteprima 3D della Scultura disegnata dalla scheda grafica** (*Strumenti → Scultura 3D da modello…*). Prima la disegnava il processore, punto per punto: era lenta (fino a qualche secondo a ogni movimento) e, mentre si girava, sgranata. Ora:
  - si gira e si avvicina in tempo reale, anche con centinaia di pezzi o modelli da milioni di triangoli (oltre i 900.000 l'anteprima usa una copia alleggerita; i pezzi si calcolano sempre sul modello vero);
  - bordi lisci, luce calcolata punto per punto che segue la vista (le facce verso di te sono sempre illuminate), venature del compensato, bordi bruciati dal laser e, negli strati, la riga fra una fetta e l'altra;
  - pavimento con la griglia, ombra morbida che cade dietro la scultura e ombra di contatto dove la scultura tocca terra;
  - le facce con i fori e le forme concave sono disegnate esatte;
  - *Monta* è più fluido: ogni pezzo scende con più passaggi.
- La scheda grafica si usa tramite OpenGL, già compreso in FreeLaserCut: niente da installare. Sotto l'anteprima c'è scritto quale si sta usando, con il nome della scheda grafica; se OpenGL è fatto dal processore (desktop remoto, macchine virtuali) lo dice, perché è più lento.
- **Anteprima semplice sempre di riserva**, quella di prima, che funziona su ogni PC:
  - si usa da sola se OpenGL manca o non va (PC vecchi, desktop remoto, macchine virtuali) o se la scheda grafica dà un errore, e lo dice;
  - si può scegliere a mano togliendo la spunta *Usa la scheda grafica*; la scelta si ricorda;
  - se il driver della scheda grafica chiudesse il programma, alla volta successiva la finestra riparte da sola con l'anteprima semplice e lo scrive; se l'anteprima non disegna nulla entro pochi secondi, si passa da soli a quella semplice;
  - la prova della scheda grafica si fa solo quando serve: con la spunta tolta OpenGL non viene nemmeno toccato.
- Nuova prova automatica `tests/test_v141.py` (33 controlli: anche il disegno vero con la scheda grafica, confrontato con l'anteprima semplice, i fori, le forme concave, il montaggio e i modelli enormi).

## 0.14.0 — 05/11/2026
- **Scultura 3D da modello** (*Strumenti → Scultura 3D da modello…*, nel Banco il pulsante *Scultura*): un modello 3D diventa una scultura di legno da tagliare al laser.
  - Si apre un file `.stl` (binario o di testo) o `.obj`, oppure si usa uno dei modelli inclusi per provare: cuore, stella, sfera, vaso, ciambella. Si scelgono l'asse verticale del modello, l'altezza finita e lo spessore del materiale.
  - **A strati (da incollare)**: il modello viene tagliato a fette dello spessore del legno. Su ogni fetta è inciso, leggero, il contorno della fetta sopra (così si sa dove appoggiarla) e il suo numero, scritto dove possibile nella parte che la fetta successiva coprirà. Le fette con più parti si chiamano 12A, 12B…
  - **A incastro (senza colla)**: sagome incrociate lungo X e lungo Y, con le fessure larghe quanto il legno (più il *Gioco delle fessure*, per legni più spessi o più sottili del previsto): le X hanno le fessure dall'alto, le Y dal basso. Il numero di sagome si sceglie o lo calcola *Automatico*. Le sagome che non si incastrerebbero vengono tolte con un avviso.
  - **Anteprima 3D** fatta da FreeLaserCut, senza bisogno di schede grafiche particolari: si gira trascinando, si avvicina con la rotellina, doppio clic per tornare alla vista iniziale. Tre viste: il modello, la scultura in legno con i bordi bruciati e il montaggio pezzo per pezzo, con il cursore o con ▶ *Monta*.
  - Anche i modelli scaricati meno curati si aprono: STL con qualche byte in più alla fine, modelli fatti di più corpi sovrapposti (restano pieni dove si toccano), triangoli girati al contrario, piccoli buchi nella superficie (i contorni si chiudono da soli, con un avviso). Con i modelli molto grandi (fino a 2 milioni di triangoli) l'anteprima usa una copia alleggerita, mentre i pezzi si calcolano sempre sul modello vero.
  - Gli incroci delle sagome sono controllati su tutto lo spessore del legno, non solo sulla linea di mezzo: anche dove due sagome si sfiorano c'è la fessura, e si montano sempre facendo scendere le Y sulle X.
  - *Crea i pezzi* li sistema sui fogli della misura scelta (di partenza quella del piano), con i fogli numerati. Due livelli nuovi in modalità *Linea*: «Scultura: segni» (leggero) e «Scultura: taglio», eseguiti per ultimi; prima di avviare vanno impostati per il materiale. Un pezzo più grande del foglio viene messo a destra, da sistemare a mano. Tutto si annulla con un solo *Annulla*.
- **Nuovo effetto «Schizzo del soggetto (sfondo tolto)»** in *Prepara foto* → *Effetto*, per chi trovava il ritratto a matita troppo scuro e voleva il primo piano in risalto.
  - Il programma trova da solo il soggetto in primo piano (persona, animale, oggetto) usando i colori della foto e toglie lo sfondo: resta carta bianca, niente da incidere.
  - Il soggetto è disegnato con toni chiari, tratti che seguono il verso del pelo e delle forme e scuri pieni solo dove servono (occhi, naso, ombre profonde).
  - *Intensità* scurisce la mano, *Dettaglio* aggiunge o toglie tratti. Il risultato è sempre lo stesso fra anteprima e incisione.
  - Tutti gli altri effetti restano com'erano, compresi «Matita» e «Ritratto a matita».
- Nuova prova automatica `tests/test_v140.py` (53 controlli).

## 0.13.6 — 05/11/2026
- **Puzzle da foto** (*Strumenti → Puzzle da foto…*, nel Banco il pulsante *Puzzle*): la foto selezionata, o una da scegliere, diventa un puzzle da incidere e tagliare.
  - Si scelgono misure, numero di pezzi (da 4 a 1000), grandezza degli incastri e forma: rettangolo, cuore, cerchio, ovale o una forma chiusa disegnata da te (selezionala insieme alla foto).
  - Gli incastri (testa e collo) sono disegnati da FreeLaserCut con piccole differenze di grandezza, posizione e inclinazione, e le linee sono leggermente mosse, come nei puzzle veri. *Rimescola* dà un altro puzzle; lo stesso puzzle si ritrova sempre uguale fra anteprima e lavoro.
  - Dentro una forma, gli incastri che uscirebbero dal bordo diventano lati dritti e i pezzetti troppo piccoli si uniscono al vicino. Nessun pezzo resta attaccato a un altro per un filo sottile.
  - La finestra mostra il collo più stretto degli incastri e avvisa se pezzi o colli sono troppo piccoli per il legno.
  - Due livelli: la foto in modalità *Immagine* (se era già su un livello Immagine resta lì, con il suo metodo) e i tagli in modalità *Linea* («Puzzle: taglio»), messi per ultimi. Il lavoro incide prima la foto, poi taglia i lati interni e per ultimo il contorno, così il foglio non si sposta. Fuori dalla forma la foto non si incide.
  - Con *Senza foto* si creano solo i tagli, per un puzzle da dipingere o da incidere dopo.
  - Una foto ruotata o dentro un gruppo non si usa: il programma dice come sistemarla. Una forma disegnata che si incrocia (una stella a cinque punte fatta con una linea sola) diventa il suo bordo esterno; le forme senza area vengono rifiutate con un messaggio chiaro. I pezzi hanno sempre almeno 3 mm di lato.
- **Aggiornamenti non più bloccati dal collegamento con Claude.** Chi usa FreeLaserCut con l'app Claude ha un piccolo programma (il server MCP) che usa il Python di FreeLaserCut: l'installatore lo vedeva occupato e chiedeva di chiudere FreeLaserCut anche se era già chiuso. Ora l'installatore chiude da solo solo quel processo, anche a ogni «Riprova»; il collegamento torna attivo riaprendo Claude (o da solo, se Claude lo riavvia). FreeLaserCut aperto non viene mai chiuso senza chiedere. Se l'avviso resta, il messaggio dice di chiudere anche Claude.
- Nuova prova automatica `tests/test_v136.py` (49 controlli).

## 0.13.5 — 05/11/2026
- **Nuovo effetto «Ritratto a matita»** in *Prepara foto* → *Effetto*, per chi voleva un vero disegno a matita come i ritratti fatti a mano. «Matita» resta com'era.
  - Contorni a tratti di matita che seguono le forme e sbordano un poco, come fa chi disegna.
  - Ombre a tratteggio diagonale, incrociato nelle zone più scure, e una leggera grana della carta.
  - I chiari restano carta bianca: lo sfondo non si incide, nemmeno quando è quasi bianco con il rumore della foto.
  - *Intensità* scurisce la mano, *Dettaglio* sceglie tratti più fini o più morbidi. Misure in millimetri, anche per tratteggio e grana: anteprima e incisione uguali.
- **Partenza delle immagini a scelta**: *Impostazioni di taglio* → scheda *Immagine* → *Partenza*.
  - Dall'alto (come sempre) o dal basso, con righe orizzontali.
  - Da sinistra o da destra, con righe verticali.
  - La foto incisa è la stessa: cambia solo il percorso della testa. Di solito le righe orizzontali sono più veloci, perché lungo X si muove solo la testa e lungo Y tutto il portale.
  - La correzione della scansione avanti e indietro (*Laser → Correzione della scansione…*) è misurata lungo X, quindi vale per le righe orizzontali; con le righe verticali non viene applicata.
- **Retino spiegato**: passando con il cursore su *Retino: cella* e *Retino: angolo* compare la spiegazione. I due campi sono attivi solo con il metodo *Mezzetinte (retino)*, l'unico che li usa.
- **Longer Ray5 10W e 20W separati** (49 modelli pronti), con i dati della pagina ufficiale Longer:
  - Ray5 10W: 400 × 400 mm, 10.000 mm/min, spot 0,06 mm;
  - Ray5 20W: dichiarati 400 × 365 mm, qui 365 × 365 per prudenza perché non è indicato quale lato è l'asse X; spot 0,08 × 0,10 mm. Collegandolo, il Ray5 20W viene riconosciuto dall'area letta dalla scheda.

  Chi aveva già scelto la vecchia voce «Longer Ray5 10W / 20W» tiene il suo profilo così com'è.
- **Testi più neutri**: il programma non cita più altri programmi in modo particolare. I progetti `.lbrn2` e `.lbrn` si aprono come prima (*File → Apri*, *Importa*).
- **Logo con il bordo bianco** intorno all'icona, ai suoi elementi e alla scritta: più definito sugli sfondi grigi e scuri. La firma nascosta nel logo è stata reinserita e controllata.
- Nuova prova automatica `tests/test_v135.py` (50 controlli).

## 0.13.4 — 05/11/2026
- **8 modelli pronti in più (48 in tutto)**, con i dati controllati due volte, in modo indipendente, sulle pagine ufficiali dei produttori:
  - Mecpow X3 5W, X3 Pro 10W, X4 22W / X4 Pro 22W, X4 Pro 40W, X5 Pro 33W;
  - Longer Ray5 Mini;
  - Creality CR-Laser Falcon 5W;
  - Atomstack A70 Max.

  Ogni modello ha il link alla sua pagina ufficiale. Quando il produttore dichiara due lati diversi senza dire quale è l'asse X, FreeLaserCut usa il più corto per tutti e due, così la testa non va mai contro il telaio. Collegando la macchina l'area vera si legge comunque dalla scheda, e la nota del modello lo spiega. Le schede Mecpow si riconoscono dal messaggio di avvio.
- **Esclusi per ora** perché le pagine ufficiali mancano o si contraddicono: Atomstack A24/X24 Ultra e X70 Max, Sculpfun S6 Pro, Ortur LM2 Pro S1, xTool D1, Two Trees TS3, NEJE Max 4, Wainlux. Restano da decidere, con dati parziali: Elegoo PhecdaLaser, Longer Ray5 20W (area diversa dal 10W), Sculpfun S30 Ultra.
- **Profili macchina da condividere** (*Laser → Esporta il profilo della macchina…* / *Importa un profilo macchina…*, file `.flcprofile`).
  - Chi ha regolato bene una macchina che non è in catalogo può passare il profilo ad altri.
  - All'importazione ogni valore viene controllato. Sono rifiutati:
    - aree o velocità fuori misura;
    - comandi dell'aria diversi da M7, M8, M9, M106 e M107 (un profilo non può accendere il laser);
    - file che non sono profili.
  - Il profilo importato è segnato «dalla comunità», separato dai modelli verificati, e non ne sovrascrive mai uno esistente.
  - Le prove fatte sulla macchina di chi l'ha esportato (assi provati, coordinate dopo l'homing) ripartono da zero, e il programma chiede la prova delle frecce.
  - Niente viene scritto nella scheda.
- **Canale YouTube**: *Aiuto → Video tutorial su YouTube* apre il canale [Free Laser Cut](https://www.youtube.com/@FreeLaserCut); il link è anche nel README e nella pagina web.
- La pagina web elenca tutti i 48 modelli pronti (prima ne mostrava solo una parte).
- Nuova prova automatica `tests/test_v134.py` (24 controlli).

## 0.13.3 — 05/11/2026
- **Effetti per le foto** in *Prepara foto* → *Effetto*: **Matita**, **Carboncino**, **China (contorni)**, **Fumetto**, **Incisione a linee** (come le banconote), **Linee ondulate**, **Puntinismo**, **Posterizza**, **Rilievo**.
  - Ogni effetto ha due cursori: *Intensità* e un secondo che cambia nome secondo l'effetto (finezza del tratto, dettaglio, righe fitte, punti piccoli, numero di toni). Per le righe si sceglie anche la direzione: orizzontali, verticali o diagonali.
  - Righe e punti hanno misure in millimetri sul materiale, quindi l'anteprima mostra quello che verrà inciso anche con foto molto grandi.
  - Le foto da molti megapixel si elaborano alla risoluzione che serve al laser (fino a 14 punti per mm), così anche gli effetti più pesanti restano veloci.
  - Il bianco resta bianco: sfondo tolto, forma ovale e bordi sfumati non si incidono con nessun effetto (nel fumetto, nella posterizzazione e nel rilievo il tono più chiaro è bianco pieno).
  - China e linee sono già in bianco e nero e si incidono veloci senza retinatura. Matita, carboncino e rilievo rendono meglio con i metodi a punti.
  - La foto originale resta nel progetto: riaprendo *Prepara foto* l'effetto si cambia o si toglie. Funziona anche con *Linee e riempimento* (per esempio China → vettoriale) e con la *Prova foto*.
- **Corretto (solo nelle prove automatiche):** la prova di «Porta la testa qui» con l'origine utente dipendeva dai tempi e su Windows falliva. Ora fissa l'origine sulla scheda simulata. Il programma era già corretto.
- Nuova prova automatica `tests/test_v133.py`.

## 0.13.2 — 04/11/2026
Versione di controllo: revisione completa delle parti delicate (comunicazione con la scheda, assi, configurazione guidata, foto) con una seconda lettura indipendente del codice. Ogni correzione ha la sua prova automatica (`tests/test_v132.py`, `tests/test_v130.py`).

**Sicurezza della macchina**
- **Corretto (grave): una verifica chiesta mentre la macchina non era ferma poteva eseguire davvero il lavoro, con il laser.** La verifica manda `$C` per entrare in modalità di prova. A testa in movimento la scheda lo rifiuta (error:8) e le righe accodate dietro partivano davvero, per esempio premendo *Verifica* durante un *Contorno*. Ora:
  - la verifica parte solo a macchina ferma;
  - `$C` viaggia da solo e le righe partono solo dopo il suo «ok»;
  - se la scheda lo rifiuta, la verifica si chiude senza inviare niente e lo spiega.
- Avvio e verifica bloccati con un messaggio chiaro anche quando la macchina sta ancora facendo un contorno, uno spostamento o è in pausa.
- **Corretto: se la scheda si riavvia a metà lavoro** (calo di tensione, watchdog) il lavoro risulta interrotto e si può riprendere. Prima il programma restava «in lavoro» per sempre.
- **Corretto: una riga di G-code più lunga del buffer della scheda** (file esterni) faceva restare fermo il lavoro senza spiegazioni. Ora il lavoro viene rifiutato subito, con il numero della riga.
- **Comunicazione più robusta:**
  - un errore imprevisto su una risposta della scheda non ferma più la lettura;
  - la verifica che si blocca non si può più chiudere due volte;
  - in Wi-Fi una scrittura lenta non fa più cadere il collegamento.
- **Puntino:** una potenza oltre il 5% salvata non viene più ripresa da sola alla riapertura; si riparte dal 5% e la conferma va data di nuovo.
- **Limiti software della scheda:** il controllo prima dell'avvio ora tiene conto degli assi invertiti.
- Un avviso d'allarme compare sempre, anche se in alto c'era un suggerimento.

**Configurazione guidata e assi**
- **Corretto: con un profilo fuori catalogo** (scheda riconosciuta, profilo rinominato) il primo passo proponeva il Longer B1 e *Avanti* fino in fondo sostituiva il profilo. Ora in cima c'è «Il profilo attuale: …». Probabilmente è il motivo per cui ad alcuni, dopo l'aggiornamento, il programma «tornava» al Longer B1.
- **Assi provati con le frecce:** il loro verso resta quello provato. Dopo l'homing si ricalcolano solo gli assi non provati. Prima, provando un solo asse, l'homing poteva rovesciare proprio quello.
- **«Non lo so» o *Avanti* senza scegliere l'angolo:** gli assi restano com'erano. Prima davano per vero «davanti a sinistra» e, sulle macchine con coordinate negative, il primo homing poteva capovolgere il lavoro.
- L'angolo dello 0 mostrato si ricava sempre da come si muove davvero la macchina, quindi non resta indietro dopo l'homing. Un angolo salvato in automatico dalla 0.13.0/0.13.1 senza prove non viene più dato per vero.
- Scegliendo nella configurazione un altro modello, il nuovo profilo non eredita gli assi della macchina di prima; un homing fatto durante la configurazione non viene annullato da *Fine*.
- **Prova delle frecce:**
  - se la scheda rifiuta lo spostamento perché la testa è sul bordo, ora lo spiega e non conta come prova (prima sembrava un asse al contrario);
  - con la macchina in allarme compare il pulsante *Homing*.
- **Porta la testa qui** con *Origine utente* va sull'origine, dove il lavoro inciderà davvero. Con *Posizione attuale della testa*, anteprima e rombo seguono la testa quando si sposta (senza ricalcolare il lavoro: resta tutto fluido). Con il rotativo e l'asse Y invertito anche contorno e anteprima grande sono al posto giusto.
- Al primo avvio su un PC nuovo non compare più la striscia «Novità» dietro la configurazione.

**Foto e disegni**
- **Corretto: foto e scritta sullo stesso livello** (per esempio un portachiavi): se ne incideva una sola, perché un livello in modalità Immagine incide solo le foto e gli altri solo i disegni. Ora foto e disegni restano su livelli separati:
  - importando una foto dove c'è già una scritta;
  - scrivendo sul livello di una foto;
  - spostando insieme foto e scritta su un livello.
  Quello che si sposta va sempre su un livello nuovo, con le impostazioni di base (mai su un livello già usato, che potrebbe essere un taglio), e la barra di stato dice dove è finito.
- Una foto rimasta su un livello che non è in modalità Immagine (progetti vecchi) ora dà un avviso prima dell'avvio; prima veniva saltata in silenzio.
- **Progetti .lbrn2:** se lo stesso colore ha sia foto sia disegni, la foto va su un livello suo con le impostazioni da immagine e i disegni restano con le loro. Prima i disegni di quel colore sparivano dal lavoro.
- **Formati delle immagini:**
  - le foto dei telefoni scattate in verticale arrivano dritte (rotazione EXIF);
  - le immagini a 16 bit non diventano più bianche;
  - i PNG con un colore trasparente restano trasparenti.
  Provati PNG, JPEG (anche CMYK), WEBP, GIF, TIFF e BMP a 1 bit.
- **Velocità in mm/s:** aprire e chiudere un campo non cambia più la velocità salvata (prima 1000 → 1002 mm/min, 50 → 48 mm/min).
- Una copia delle impostazioni della scheda modificata a mano con un'altra codifica non blocca più la connessione.

**Altro**
- Le prove automatiche su Windows misurano la barra dei nomi con lo stile del programma (prima con quello nativo di Windows 11, che FreeLaserCut non usa).
- Pubblicazione della Release più robusta: se GitHub dà un errore momentaneo, il passo riprova e completa la Release rimasta a metà.
- La 0.13.1 non è stata pubblicata come Release (errore temporaneo di GitHub): le sue novità arrivano con questa versione.

## 0.13.1 — 04/11/2026
- **Livello di aiuto** (*Impostazioni → Livello di aiuto*, e lo stesso sottomenu in *Aiuto*). Prende il posto di *Mostra i nomi sotto i comandi* e di *Modalità esperto*, che potevano sembrare in contrasto e lasciavano una voce grigia. Ora le voci sono tre, ne è attiva sempre una, e scegliendone una le altre si tolgono da sole.
  - **Principiante**: nomi sotto i comandi e accanto ai segni del piano, spiegazioni passando sui segni, suggerimenti.
  - **Normale** (di partenza): solo icone; spiegazioni e suggerimenti.
  - **Esperto**: niente nomi, spiegazioni e suggerimenti come «Fai l'homing».
  - Gli avvisi di sicurezza (puntino oltre il 5%, guardia fiamme, conferme prima di avviare) restano in tutti e tre.
  - Chi aveva i nomi accesi parte da *Principiante*, chi aveva la modalità esperto da *Esperto*.
- L'ultimo passo della configurazione guidata è la stessa scelta a tre.
- **Corretto: comunicazione con la scheda più sicura.** La finestra e il filo che legge le risposte della scheda potevano mandare righe nello stesso istante. In quel caso, raramente, due gruppi di righe partivano in ordine diverso da quello in cui FreeLaserCut aspettava le risposte: un errore della verifica poteva essere attribuito alla riga sbagliata. Ora le righe partono sempre una dopo l'altra nell'ordine giusto. Era emerso come errore saltuario di una prova automatica.
- `tests/test_v130.py` estesa (43 controlli), `tests/test_v111.py` aggiornata.

## 0.13.0 — 04/11/2026
- **Configurazione guidata della macchina** (*Impostazioni → Configurazione guidata della macchina*). Compare al primo avvio; chi aggiorna la trova proposta una volta in alto. Si può rifare quando si vuole. Quattro passi:
  1. **Quale laser hai**: il modello dal catalogo, oppure l'ultima voce se non c'è.
  2. **Dov'è lo 0 della macchina**: si clicca uno dei quattro angoli del piano. È dove va la testa con l'homing o, senza homing, l'angolo da cui parte. Da qui FreeLaserCut ricava il verso degli assi; con le coordinate negative del GRBL classico lo ricalcola da solo dopo il primo homing.
  3. **Prova delle frecce**, con il laser collegato: la testa si sposta di 10 mm a laser spento e deve andare dove indica la freccia. Se va al contrario si preme «correggi» per quell'asse. Le frecce hanno l'ultima parola.
  4. **Quante scritte d'aiuto**: nomi sotto i comandi oppure modalità esperto.
- **Segni del piano più chiari.**
  - Le scritte accanto al rombo del punto di partenza e la nuova scritta «testa del laser» sotto il cerchio compaiono solo con *Mostra i nomi sotto i comandi*.
  - Passando con il mouse su un segno compare una spiegazione su sfondo semitrasparente, come per i comandi. Non compare durante il lavoro.
- **Modalità esperto** (*Impostazioni*): toglie i nomi sotto i comandi, le scritte e le spiegazioni dei segni e i suggerimenti come «Fai l'homing». Gli avvisi di sicurezza (puntino oltre il 5%, guardia fiamme, conferme prima di avviare) restano sempre. Finché è attiva, *Mostra i nomi sotto i comandi* non si può accendere.
- **Macchine senza homing** ($22=0): alla connessione, al posto di «Fai l'homing», un promemoria. Ricorda che lo 0 è dove sta la testa all'accensione e indica l'angolo in cui portarla.
- Spuntando a mano *Inverti l'asse X/Y* l'angolo dello 0 si aggiorna di conseguenza.
- Nuova prova automatica `tests/test_v130.py` (38 controlli).

## 0.12.6 — 03/11/2026
- **Corretto: foto dei progetti .lbrn2 specchiate in *Prepara foto*.** Sul piano la foto era giusta, ma la finestra mostrava i pixel senza lo specchio contenuto nella posizione della foto, quindi la vedeva capovolta.
  - Ora lo specchio viene spostato nei pixel all'apertura del progetto: sul piano ogni pixel resta esattamente dov'era e *Prepara foto* la mostra uguale al piano.
  - Le foto già aperte con la 0.12.5 e salvate nel progetto si raddrizzano da sole quando si apre *Prepara foto* (si può annullare).
- **Corretto: alcuni progetti .lbrn2 non si aprivano** con l'errore «Impossibile aprire il file: 'c0x'». Erano tracciati con maniglie di curva incomplete (solo una delle due coordinate): ora quelle maniglie si ignorano e il tracciato si apre.
- Nuova prova automatica `tests/test_v125.py` (21 controlli); `tests/test_v108.py` aggiornata.

## 0.12.5 — 03/11/2026
- **Due segni diversi sul piano**, per non confondere la testa con il punto di partenza:
  - **cerchio con il mirino**, del colore principale: è la **testa del laser** e si muove solo quando si muove il laser;
  - **rombo magenta con la scritta**: è il **punto di partenza del lavoro**, cioè il punto scelto con i 9 pallini e il posto in cui finirà.
    - Con *Posizione attuale della testa* sta sulla testa, con *Origine utente* sull'origine. Il lavoro (anteprima arancione) si appende lì.
    - In *Coordinate assolute* sta sul punto scelto del disegno, dove andrà la testa con *Porta la testa qui*.
  - Il rombo compare insieme all'anteprima e si sposta subito quando si cambia pallino o partenza.
- `tests/test_v124.py` estesa (13 controlli).

## 0.12.4 — 03/11/2026
- **Porta la testa qui** (pannello Laser, sotto i 9 pallini): con un clic la testa va, a laser spento, sul punto del disegno indicato dal pallino, così com'è disegnato sul piano. Il punto può essere un angolo, il centro di un lato o il centro.
  - Serve per vedere sul materiale dove cadrà un angolo o il centro del lavoro.
  - Con *Solo gli oggetti selezionati* usa la selezione. Se il punto è fuori dal piano, la testa si ferma al bordo e la barra di stato lo dice.
  - I pallini restano attivi anche in coordinate assolute, dove servono solo a questo pulsante.
- Nuova prova automatica `tests/test_v124.py` (9 controlli).

## 0.12.3 — 03/11/2026
- **Corretto: cambiando il punto di riferimento** (i 9 pallini accanto a *Partenza*) o la partenza stessa, l'anteprima sul piano non si muoveva. Ora si sposta subito e la barra di stato dice quale punto del lavoro va sulla testa o sull'origine utente, per esempio «al centro». Con le foto molto grandi l'anteprima resta da chiedere con *Anteprima*.
- **Puntino fino al 20%** (prima al massimo 5%), sia dal pulsante *Puntino* sia da *Contorno → Regola il puntino…*.
  - Quando si supera il 5% compare un avviso: oltre quella soglia il raggio segna, brucia e può incendiare il materiale, e la luce riflessa è più pericolosa per gli occhi. L'avviso ricorda occhiali, spegnimento automatico dopo 20 s, uso su uno scarto e che anche il contorno con il puntino userà quella potenza.
  - Con «No» resta al 5%. Sopra il 5% il valore si vede in arancione.
- **Corretto (0.12.1):** quando FreeLaserCut faceva uscire la scheda dalla modalità di prova, mandava prima una riga vuota. GRBL risponde «ok» anche a quella, e le risposte successive potevano slittare di una: un errore veniva attribuito alla riga sbagliata.
- Nuova prova automatica `tests/test_v123.py` (14 controlli).

## 0.12.2 — 03/11/2026
Da chi usa una scheda **Makerbase MKS DLC32** («premo giù e la testa va su»):
- **Assi invertibili.** Nel pannello Laser, sotto *Posizionamento*, ci sono due spunte: **Inverti l'asse X (destra ↔ sinistra)** e **Inverti l'asse Y (avanti ↔ indietro)**.
  - Servono per le macchine con l'origine dall'altra parte o con un motore montato al contrario.
  - Valgono subito per le frecce di movimento, la posizione della testa sul piano, il contorno, il clic su «Vai qui» e le coordinate del lavoro (anche partendo dalla posizione della testa o dall'origine utente).
  - Il disegno, l'anteprima e il test materiale restano dove li vedi.
  - La scelta si salva nel profilo della macchina, non nella scheda: i parametri `$3`/`$23` non vengono toccati.
- **Unità di misura** (*Impostazioni → Unità di misura*): le velocità si possono vedere e scrivere in **mm/s** invece che in mm/min.
  - Vale per il livello, la tabella dei livelli, le impostazioni rapide, il Banco, la libreria e il test materiale (anche le etichette incise), la correzione della scansione, il jog e la barra di stato.
  - Dentro FreeLaserCut, nei progetti e nel G-code resta tutto in mm/min, come vuole GRBL: cambiare unità non cambia nessun lavoro. Si applica dal riavvio, che FreeLaserCut propone.
- **MKS DLC32 riconosciuta** (produttore «Makerbase»), con una nota: area di lavoro letta dalla scheda, spunte per gli assi e porta 8080 per il Wi-Fi.
  - Se il suo firmware non accetta `G55`, la 0.12.1 lo scopre da sola alla prima verifica.
- Nuova prova automatica `tests/test_v122.py` (29 controlli).

## 0.12.1 — 03/11/2026
Dal rapporto per l'assistenza di chi usa un **Acmer S1** (firmware 1.0.4 del 2025): verifica ferma, testa che si muove a laser spento.
- **Corretto: una scheda rimasta in modalità di prova («Check») si muoveva davvero a laser spento.**
  - Se una verifica restava a metà, la scheda rimaneva in modalità di prova. A una nuova verifica FreeLaserCut mandava di nuovo `$C`, che invece la faceva uscire: la scheda si riavviava, le prime righe (con l'accensione del laser) si perdevano e il resto veniva eseguito come spostamenti.
  - Ora FreeLaserCut riconosce dallo stato che la scheda è in prova e la fa uscire da solo, anche alla connessione. Finché non si è riavviata non manda né verifiche né lavori.
- **Corretto: la verifica restava ferma** (al 62% o al 74%) quando la scheda smetteva di rispondere.
  - Se per 6 secondi non arriva nessuna risposta, la verifica si chiude e spiega cosa è successo; la scheda esce dalla modalità di prova senza muoversi.
  - La comunicazione passa poi a un buffer prudente.
- **Comunicazione prudente con le schede non conosciute.**
  - Il buffer grande dichiarato dalla scheda (`[OPT]`) si usa solo con i firmware provati: Longer, grblHAL e FluidNC.
  - Con gli altri si mandano al massimo 127 caratteri alla volta, come nel GRBL classico. L'Acmer dichiara 511 caratteri ma perdeva risposte.
- **Schede senza G55.**
  - Alcuni firmware, come quello dell'Acmer, rispondono error:20 a `G55`, il sistema di coordinate che FreeLaserCut usa per la posizione «assoluta».
  - Alla prima verifica che lo rivela, FreeLaserCut se lo segna nel profilo, rifà il lavoro in `G54` togliendo l'offset della scheda (stesso punto sul piano), lo verifica di nuovo e lo avvia.
  - Il profilo pronto dell'Acmer S1 è già impostato così; vale anche per il test materiale e la prova della scansione.
- L'esito della verifica non dice più «valido per il tuo B1», ma «per la tua macchina».
- Nuova prova automatica `tests/test_v121.py` (20 controlli). Il simulatore ora sa anche fare la scheda «senza G55» e quella che perde risposte in verifica.

## 0.12.0 — 03/11/2026
- **Laser collegati via Wi-Fi.** Con il pulsante Wi-Fi accanto alla porta si scrive l'indirizzo della scheda (per esempio `192.168.1.50`, porta 23) e *Prova il collegamento* controlla che risponda. Poi tutto funziona come con il cavo USB: lavori, verifica, contorno, stato, *Riconosci la macchina*. Gli indirizzi usati restano nell'elenco delle porte e FreeLaserCut si ricollega da solo all'avvio.
  - Funziona con le schede che accettano il G-code dalla rete (telnet), come FluidNC, grblHAL ed ESP3D (porta 23 di serie) o l'AlgoLaser Delta. I laser che si comandano solo dall'app del produttore restano con il cavo USB.
- **Copie delle impostazioni della scheda** (*Laser → Copie delle impostazioni della scheda…*, anche dal pannello Macchina).
  - FreeLaserCut salva da solo tutti i parametri `$$` quando si collega, se sono cambiati dall'ultima copia, e prima di cambiarne uno: da Macchina, dalla console o da *Riconosci e adatta*.
  - Le copie sono file di testo leggibili, una riga `$numero=valore` ciascuna, e ne restano le ultime 40.
  - Con *Confronta e ripristina* si vede cosa cambierebbe e si rimandano alla scheda solo i valori diversi. Una copia si può anche salvare a mano, esportare o aggiungere da un file.
- **20 modelli pronti in più** (39 in tutto). Nell'elenco il B1 40W resta per primo e gli altri sono in ordine alfabetico.
  - I nuovi: Ortur Aufero Laser 1 e 2, Sculpfun SF-A9 40W, iCube Pro Max 10W, iCube Ultra 12W, Atomstack A5 Pro, Creality Falcon A1 10W, Falcon2 Pro 22/40W e 60W, Two Trees TTS-10 Pro e TTS-20 Pro, AlgoLaser Alpha 22W, Alpha MK2 20W e 40W, Delta 22W, Genmitsu Jinsoku LC-40, L8 20W e 40W, LE5040, Longer Ray5 5W.
  - Area di lavoro, potenza, velocità e dimensione del punto vengono **dalle pagine ufficiali dei produttori**, indicate nel codice.
  - Il riconoscimento usa anche l'area di lavoro letta dalla scheda: se è unica propone il modello da confermare, se più modelli hanno la stessa area li elenca invece di tirare a indovinare.
- Nuova prova automatica `tests/test_v120.py` (41 controlli): una scheda simulata collegata in rete per lavori, impostazioni e riconoscimento, poi copie, confronto, ripristino e catalogo.

## 0.11.2 — 03/11/2026
- **Controllo dal telefono:**
  - nuova sezione **Controllo attività**: la camera si accende da sola durante il lavoro, si aggiorna circa ogni secondo e mostra l'ora dell'ultima immagine. Un tocco la apre a schermo intero; se la camera smette di mandare immagini, la pagina lo dice. Con la guardia fiamme accesa, la pagina lo ricorda;
  - il **logo** di FreeLaserCut nell'intestazione e come icona, se aggiungi la pagina alla schermata Home.
- Prova automatica `tests/test_v111.py` estesa (25 controlli).

## 0.11.1 — 03/11/2026
Dalla prima prova della 0.11.0:
- **Guardia fiamme più attenta:** con un accendino davanti alla camera si vedeva solo il bordo rosso della fiamma, non il cuore chiaro. La camera, abbagliata, vede il cuore quasi bianco. Ora conta anche la zona chiara, purché sia attaccata al bordo caldo della fiamma; una lampada bianca o un foglio illuminato da soli non la fanno scattare.
  - Nuovo pulsante **Salva l'immagine di prova**: salva nella diagnostica la foto della camera e la stessa foto con le zone viste come fiamma, da allegare a una segnalazione.
- **Nomi sotto i comandi** (*Aiuto → Mostra i nomi sotto i comandi*, anche in *Impostazioni* per il Banco): sotto ogni icona delle barre compare un nome corto e piccolo (Apri, Salva, Rettangolo, Codici, Poligono…), nella lingua scelta. È spento di partenza e la scelta si ricorda.
  - A 1920 × 1080 la barra in alto della Classica ci sta tutta, in tutte le lingue. Se non ci sta, ad esempio con lo zoom di Windows al 125%, i comandi in più vanno nel pulsante » in fondo alla barra.
- Nuova prova automatica `tests/test_v111.py` (19 controlli).

## 0.11.0 — 03/11/2026
Tre funzioni nuove, tutte scritte da zero per FreeLaserCut.
- **Guardia fiamme** (*Laser → Guardia fiamme…*, anche nel Banco). È **spenta di partenza** e si attiva con una casella. Durante il lavoro FreeLaserCut guarda la camera scelta nel pannello Camera. Se vede una fiamma per circa un secondo:
  - ferma il lavoro e spegne laser e aria;
  - suona e mostra un avviso rosso;
  - salva una foto nella cartella della diagnostica e lo annota nel registro della comunicazione con la scheda.
  - **Cosa non la fa scattare:**
    - il puntino del laser, la brace normale e le scintille di un solo fotogramma;
    - le luci sempre presenti nell'inquadratura, perché nei primi istanti del lavoro FreeLaserCut impara com'è l'immagine «normale».
  - **Sensibilità** alta, media o bassa, con una prova dal vivo: le zone che verrebbero prese per fiamma si colorano di rosso.
  - È un aiuto in più, non una protezione certificata: la macchina non va mai lasciata da sola.
- **Taratura da foto del test materiale.** Nel *Test materiale* si spunta *Riferimenti per leggere la foto*: agli angoli del test vengono incisi quattro quadratini a scacchiera. Poi si fotografa il test e si preme *Leggi la foto del test…*. La foto può arrivare da un file, dalla camera del laser oppure **direttamente dal telefono**.
  - FreeLaserCut ritrova la griglia anche in una foto storta, in prospettiva o specchiata, e anche con un riferimento coperto.
  - Misura quanto è scuro ogni quadrato rispetto al materiale nudo e propone tre valori, ognuno da scegliere con *Usa questo* e salvare in libreria:
    - **incisione scura**: il quadrato più leggero che arriva quasi al nero;
    - **incisione leggera**: un tono a metà;
    - **foto**: potenza minima e massima per la scala di grigi.
  - **Mini guida** con il pulsante *Come si fa?*.
  - La griglia del test inciso si ricorda, così la foto si può leggere anche più tardi.
- **Controllo dal telefono** (*Laser → Controllo dal telefono…*). È **spento di partenza** e resta acceso solo fino alla chiusura di FreeLaserCut. Il telefono deve essere sullo stesso Wi-Fi del PC; inquadrando il codice QR apre una pagina da cui:
  - vede l'avanzamento con il tempo trascorso e quello che manca, e la camera;
  - può mettere in **Pausa** o fare **Stop**;
  - può inviare la **foto del test materiale**.
  - **Dal telefono non si può avviare né riprendere un lavoro:** per partire bisogna essere davanti alla macchina.
  - **Sicurezza:** l'indirizzo contiene un codice casuale, che si cambia con *Cambia codice*. La pagina risponde solo ai dispositivi della rete di casa e niente passa da internet.
  - **Mini guida** nella finestra, con la nota sul firewall di Windows («Reti private»).
- Nuova prova automatica `tests/test_v110.py` (63 controlli). Le incisioni e le foto delle prove sono simulate: la fiamma, il G-code del test con i riferimenti trasformato in una foto storta e specchiata, Pausa e Stop dal telefono su un lavoro vero del simulatore.

## 0.10.8 — 03/11/2026
Dalle segnalazioni di chi lo usa (issue #3):
- **Corretto: le foto dei progetti .lbrn2 si aprivano specchiate in verticale**, e bisognava rifletterle a mano (e poi ancora in *Prepara foto*). Nei progetti .lbrn2 la prima riga di pixel di una foto sta dalla parte opposta rispetto a FreeLaserCut: ora l'apertura ne tiene conto e la foto arriva dritta, al suo posto e con le sue misure, anche se nel progetto era ruotata.
- **Corretto: i testi dei progetti .lbrn2** con il tracciato di riserva finivano lontani dal loro posto (lo spostamento veniva applicato due volte). Ora restano esattamente dove erano nel progetto, con la stessa altezza.
- Nuova prova automatica `tests/test_v108.py` (7 controlli), più la verifica su progetti .lbrn2 veri confrontati con l'anteprima salvata nel file.

## 0.10.7 — 03/11/2026
Dalla segnalazione di chi lo usa:
- **La scelta della telecamera si ricorda.** Chi non ha una camera sull'incisore e sceglie *Nessuna telecamera* non vede più accendersi la webcam del PC a ogni avvio: FreeLaserCut non apre nessuna camera all'avvio né quando si collega la macchina. Per usarne una basta premere ⟳ e sceglierla; anche la camera scelta si ricorda e si riapre da sola. Con una sola camera e nessuna scelta fatta, FreeLaserCut la propone come prima.
- Nuova prova automatica `tests/test_v107.py` (8 controlli).

## 0.10.6 — 02/11/2026
- **Aspetto a scelta** (*Impostazioni → Aspetto*): **tema scuro** (come sempre, predefinito), **tema chiaro** oppure **come Windows** (segue la modalità chiara o scura di Windows). In più il **colore principale** di pulsanti, selezioni e linguette: blu, verde, viola, arancio o rosa. Vale per la finestra Classica e per il Banco; la scelta si applica dal riavvio, che FreeLaserCut propone subito.
  - Nel tema chiaro anche le parti con colori propri (avvisi in alto, console, pannelli e pulsanti del Banco, pastiglia di stato) diventano chiare: una prova automatica controlla che non resti nessun colore del tema scuro.
- **Corretto:** riavviando FreeLaserCut da una scelta del menu (lingua, interfaccia, aspetto) la nuova copia poteva trovare ancora «aperta» quella che si stava chiudendo e non partire; ora la vecchia smette subito di rispondere.
- Nuova prova automatica `tests/test_v106.py` (18 controlli).

## 0.10.5 — 02/11/2026
- **Correzione della scansione avanti e indietro** (*Laser → Correzione della scansione avanti e indietro…*): incidendo avanti e indietro, le righe di andata e quelle di ritorno possono non finire nello stesso punto (il laser si accende e si spegne con un piccolo ritardo), e i bordi verticali vengono «a pettine». Ora il profilo della macchina ha una tabella velocità → sfasamento e FreeLaserCut sposta ogni riga di metà dello sfasamento, nei riempimenti e nelle foto con la scansione bidirezionale.
  - **Prova da incidere:** righe di rettangoli, una per velocità, con correzioni da 0 a 0,30 mm (si cambia); sotto ogni colonna è inciso il valore. Si sceglie, per ogni velocità, il rettangolo con i bordi più dritti, *Usa questi valori* e *Salva nel profilo*.
  - Fra due velocità della tabella il valore si interpola; oltre cresce in proporzione alla velocità. Con la tabella vuota il G-code resta identico a prima.
- **Acmer S1** (2,5 W / 3,5 W / 6 W, piano 130 × 130 mm) fra i modelli pronti; una scheda che si presenta come ACMER viene riconosciuta.
- Le prove automatiche passano anche sul server Windows di GitHub (corrette alcune prove vecchie che lì non funzionavano).
- Nuova prova automatica `tests/test_v105.py` (29 controlli).

## 0.10.4 — 02/11/2026
- **Aggiornamento dal programma** (versione con l'installatore per Windows): *Aiuto → Cerca aggiornamenti…* legge l'ultima versione pubblicata su GitHub, mostra le novità e, se vuoi, scarica l'installatore, ne controlla l'impronta SHA-256 con `SHA256SUMS.txt` della stessa Release, chiude FreeLaserCut (chiedendo di salvare), installa nella stessa cartella mostrando solo l'avanzamento e lo riapre da solo. Progetti, profili e materiali restano.
  - Al primo avvio FreeLaserCut chiede se può controllare da solo, al massimo **una volta al giorno**; si cambia da *Aiuto → Controlla gli aggiornamenti ogni giorno*. Non invia nessun dato: una sola richiesta a GitHub per sapere qual è l'ultima versione. Una versione si può saltare.
  - La copia del Microsoft Store continua ad aggiornarsi dallo Store; chi usa il codice sorgente aggiorna con git.
  - Per chi pubblica: basta un tag `vX.Y.Z` su GitHub. Il server costruisce l'installatore, lo installa e lo apre su un Windows vero e, se va tutto bene, crea la Release con installatore e `SHA256SUMS.txt` (le note vengono da questo CHANGELOG).
- **Corretto (installatore):** provato su un PC Windows 11 vero, l'installatore non si accorgeva che FreeLaserCut era aperto e cominciava a togliere i file della versione precedente (il messaggio d'errore arrivava dopo, a installazione già a metà). Ora controlla prima che `pythonw.exe` e `python.exe` non siano in uso, sia quando installa sia quando disinstalla, e chiede di chiudere FreeLaserCut prima di toccare qualsiasi file.
- **Primo avvio più rapido:** l'installatore prepara subito i file di Python; prima il primo avvio dopo l'installazione durava circa 25 secondi.
- **Rapporto per l'assistenza** (*Aiuto → Crea rapporto per l'assistenza…*): un file .zip da allegare a una segnalazione, con versione, sistema, schermo, librerie, profilo della macchina, impostazioni `$$`/`$I` lette, registro degli errori e registro della comunicazione con la scheda. Niente progetti, immagini o dati personali: i percorsi della cartella utente diventano «~».
- **Registro della comunicazione con la scheda:** FreeLaserCut ricorda gli ultimi scambi con la macchina (comandi, risposte, cambi di stato, avanzamento) e li salva da solo quando arriva un allarme o un errore, quando il lavoro si interrompe o si perde la connessione, e quando un lavoro **non avanza da 20 secondi con la macchina ferma** (in quel caso lo dice anche nella barra di stato). Serve a capire problemi come il lavoro che non parte con *Stop* acceso.
- **Verifica del lavoro più sicura (`$C`):**
  - se la scheda va in **allarme durante la verifica** (per esempio allarme 2, limiti software superati), la verifica si chiude subito con l'allarme e la **riga colpevole**; FreeLaserCut fa il reset che la scheda aspetta e chiede di sbloccare. Prima la verifica restava «in corso» per sempre e il pulsante *Avvia* non tornava;
  - *Stop*, *Disconnetti* e un riavvio della scheda a metà verifica la chiudono sempre come «Verifica interrotta» (il lavoro non parte).
- **Controllo prima dell'avvio con la corsa vera della scheda:** quando la scheda ha i limiti software attivi (`$20=1`), FreeLaserCut controlla il lavoro anche con `$130`/`$131` letti dalla scheda, non solo con l'area del profilo, e blocca l'avvio se ne esce.
- Il simulatore applica i limiti software anche in modalità verifica, come GRBL; nuova prova automatica `tests/test_v104_verifica.py` (30 controlli).
- Sempre su Windows 11 vero: confermati istanza unica (un secondo avvio porta avanti la finestra già aperta), rifiuto della cartella «Programmi», suggerimenti immediati e *Ottimizza lo spazio* nella barra.

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
- Apertura dei progetti `.lbrn2` e `.lbrn`, galleria di 22 forme parametriche, collegamento a Claude, calibrazione della camera con bersagli incisi.

## 0.3
- Libreria materiali per il Longer B1 40W, test materiale, vettorizzazione delle immagini, testo variabile (date, numerazione, CSV) e testo curvo.

## 0.2
- Editor completo, livelli Linea / Riempimento / Immagine, verifica del G-code, pausa su errore, ripresa del lavoro, regolazioni durante il lavoro, anteprima.

## 0.1
- Connessione e invio dei lavori ai controller GRBL, simulatore del B1, profilo macchina letto dalla scheda, calibrazione della camera.
