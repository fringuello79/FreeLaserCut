Disegni SVG con contorno e riempimento separati da soli, e riempimenti in toni di grigio che cambiano la potenza, come in MeerK40t; in prova, il collegamento diretto con la xTool M2.

**SVG con contorno e riempimento, riempimenti grigi** (richiesta di France_o, abituato a Inkscape e MeerK40t). In Inkscape ogni figura può avere un contorno colorato e un riempimento grigio: FreeLaserCut prendeva solo il colore del contorno e ignorava il riempimento. Ora, aprendo o importando un SVG:
- una figura chiusa con un **riempimento grigio o nero** diventa **due forme**: il contorno resta una linea sul livello del suo colore (un contorno nero va su C01), il riempimento va su **C00** (Riempimento) con il suo grigio. La trasparenza schiarisce il grigio, come su un foglio bianco;
- su C00 si accende da sola la nuova opzione **«Potenza dal grigio delle forme»** (impostazioni del livello, scheda *Riempimento*): ogni forma si incide con la potenza del suo grigio, **nero = Potenza massima**, grigi in proporzione fino alla **Potenza minima**, il **bianco non si incide**. Dove due forme si coprono conta quella sopra, come nel disegno; i fori restano vuoti;
- con la *vista riempita* il piano mostra ogni forma con il suo grigio;
- restano **come prima**: i loghi tutti neri (contorno e riempimento neri: una forma sola su C00), i riempimenti colorati, le linee aperte, i colori uguali a quelli dei livelli (SVG esportati da FreeLaserCut o da LightBurn). Senza l'opzione, o senza forme grigie, il G-code è identico a prima. Se C00 non è in Riempimento l'opzione non si accende da sola.
- Nuova prova automatica: `tests/test_v207_svg_grigi.py` (43 controlli, Classica e Banco; 6 guasti messi apposta, tutti presi).
- **Da provare sul programma vero:** il file di Inkscape di France_o (contorni blu e riempimenti grigi), inciso su legno.

**xTool M2: configurazione e collegamento diretto (sperimentale, fra le funzioni in prova).** Nel menu *File* compare, solo con le funzioni in prova sbloccate, *xTool M2: collega e invia (sperimentale)*. Nella finestra:
- **configurazione**: indirizzo IP della M2, modulo laser (*Automatico*, cioè quello che dice la macchina, oppure 10, 20 o 40 W), costruttore del modulo (*Automatico*, TO o COS, cambia lo scostamento fra testa e laser), spessore del materiale. *Usa l'area della M2 per il piano* crea il profilo «xTool M2» con l'area del modulo (426 × 320 mm, 426 × 308 o 426 × 312 con il 40 W);
- **collegamento**: la prima volta la M2 chiede di **premere il suo pulsante** per abbinarsi; il gettone che dà resta salvato (*Dimentica l'abbinamento* lo cancella). FreeLaserCut si presenta come ospite, senza nessun account;
- **invio**: *Invia la cornice (potenza zero)* oppure *Invia il lavoro*, scritto dal generatore della 0.20.6 per il modulo e il costruttore che la macchina dichiara. Se il modulo scelto non è quello montato, se la testa è a infrarosso, a inchiostro o in orizzontale, o se la macchina è occupata, non parte niente. La M2 si mette in attesa: **il lavoro parte solo dal pulsante sulla macchina**. Da qui: pausa, riprendi, annulla;
- è la stessa sequenza che xTool Studio usa con la macchina; **non è ancora stata provata su una M2 vera**: il primo passo sarà la cornice a potenza zero, poi un quadratino a bassa potenza.
- Nuova prova automatica: `tests/test_v207_xtool_m2_link.py` (80 controlli, Classica e Banco) contro una M2 finta che chiede il pulsante, manda le notifiche in due forme, scarta un file rovinato, si dice occupata o cade; 14 guasti messi apposta, tutti presi.

**G-code «del piano» (fra le funzioni in prova).** *File → Esegui un file G-code* riconosce un G-code scritto da un programma esterno sul piano di FreeLaserCut (riga `; FreeLaserCut-piano`, coordinate in mm con l'origine in basso a sinistra, potenza da 0 a 1000) e lo adatta al laser del profilo: assi, origine e sistema assoluto come i lavori di FreeLaserCut; potenza riportata ai watt del laser se il file dice per quanti watt è pensata (40 % di 10 W = 10 % di 40 W, mai oltre il 100 %); sopra la velocità massima della macchina rallenta e abbassa la potenza nella stessa proporzione; spostamenti a laser spento fuori dal piano portati sul bordo; una parte da incidere fuori dal piano ferma tutto. Quello che ha fatto è scritto nella richiesta di conferma.

**Scia dell'incisione: si può spegnere** (richiesta di Ale). Durante il lavoro il piano mostra in arancione quello che il laser ha già inciso. Su lavori lunghi (foto, riempimenti grandi) quel disegno che cresce di continuo appesantiva il programma, e si vedeva anche lavorando su un altro piano.
- *Visualizza → Scia dell'incisione sul piano*: spenta, la scia non si disegna e non si raccoglie (la testa del laser si vede e si muove come sempre); la scelta resta anche al riavvio. Il lavoro non cambia.
- Accesa, si ridisegna al massimo 4 volte al secondo invece che a ogni aggiornamento della macchina.
- Mentre il laser incide un piano e tu ne guardi un altro con *Mostra gli altri piani* spento, l'anteprima e la scia del lavoro in corso non si vedono; tornando sul piano del lavoro, o con *Mostra gli altri piani* acceso, si rivedono (con tutto quello inciso nel frattempo).
- Nuova prova automatica: `tests/test_v207_scia.py` (24 controlli, Classica e Banco; 7 guasti messi apposta, tutti presi).

**Barra in basso ferma anche su Windows.** Le scritte della posizione della testa e di velocità e potenza tengono una larghezza fissa, così i numeri che cambiano non spostano il resto della barra. La larghezza era misurata con un carattere diverso da quello con cui la scritta si disegna: su alcuni Windows, con numeri più corti, la scritta si stringeva e il resto della barra saltava di lato. Ora si misura con il carattere vero.
- Le prove automatiche su Windows erano rosse da prima della 0.20.0 per un motivo del server di GitHub (nessun carattere installato nella modalità senza schermo): corretto, e ora sono verdi.

**Creality Falcon A1 Pro 20W** nell'elenco dei modelli (domanda arrivata su YouTube): area 358 × 268 mm, 600 mm/s; collegando la macchina la scheda si riconosce e l'area vera si legge dalla scheda. Il modulo a infrarosso da 2 W non è ancora provato.

---
Installatore per Windows: scarica `FreeLaserCut-0.20.7-Setup.exe`. Chi ha già FreeLaserCut può aggiornare dal programma: *Aiuto → Cerca aggiornamenti…*.

Linux: scarica `FreeLaserCut-0.20.7-x86_64.AppImage`, rendilo eseguibile e aprilo. È lo stesso programma, con le stesse prove automatiche; lo sviluppo e le prove con laser e camera veri però si fanno su Windows, quindi **il collaudo su Linux lo fa chi lo installa**: se qualcosa non va, segnalalo da *Aiuto → Invia un rapporto all'assistenza*.
