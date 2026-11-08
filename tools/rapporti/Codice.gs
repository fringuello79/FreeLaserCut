/**
 * FreeLaserCut — ricevitore dei rapporti per l'assistenza (Google Apps Script).
 *
 * Gira sull'account Google del progetto (freelasercut@gmail.com). FreeLaserCut gli manda un rapporto
 * SOLO quando l'utente preme «Invia» nella finestra Aiuto → Invia un rapporto all'assistenza.
 * Il rapporto (.zip) viene salvato nella cartella di Google Drive «FreeLaserCut - rapporti» e arriva
 * un'email di avviso con la descrizione scritta dall'utente e il riassunto tecnico.
 *
 * Nessuna password nel programma: FreeLaserCut conosce solo l'indirizzo pubblico di questa app web.
 * I rapporti più vecchi di 12 mesi vengono cancellati da soli (vedi l'informativa privacy).
 *
 * Installazione: incolla tutto il file in un nuovo progetto su script.google.com, esegui una volta
 * la funzione «installa», poi pubblica come App web (Esegui come: Me, Chi può accedere: Chiunque).
 */

const CARTELLA = 'FreeLaserCut - rapporti';
const AVVISA = 'freelasercut@gmail.com';
const MAX_BYTE = 10 * 1024 * 1024;   // rapporto più grande: 10 MB
const MAX_AL_GIORNO = 300;           // protezione contro gli abusi
const GIORNI_DA_TENERE = 365;        // poi il rapporto si cancella da solo

/** Da eseguire UNA volta dall'editor: crea la cartella e la pulizia automatica di ogni notte. */
function installa() {
  cartella_();
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'pulisci')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('pulisci').timeBased().everyDays(1).atHour(3).create();
  Logger.log('Pronto. Cartella: ' + cartella_().getUrl());
}

/** Aprendo l'indirizzo nel browser si vede se il ricevitore è attivo. */
function doGet() {
  return ContentService.createTextOutput('FreeLaserCut: ricevitore dei rapporti attivo.');
}

/** Rapporto inviato da FreeLaserCut (JSON con lo .zip in base64). */
function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.app !== 'FreeLaserCut' || !d.zip) return risposta_({ ok: false, errore: 'formato non valido' });
    const byte = Utilities.base64Decode(d.zip);
    if (byte.length > MAX_BYTE) return risposta_({ ok: false, errore: 'rapporto troppo grande' });
    if (byte[0] !== 0x50 || byte[1] !== 0x4B) return risposta_({ ok: false, errore: 'non è un file zip' });
    if (!sottoIlLimite_()) return risposta_({ ok: false, errore: 'troppi rapporti oggi, riprova domani' });

    const codice = pulito_(d.codice, 40).replace(/[^A-Za-z0-9-]/g, '') || Utilities.getUuid().slice(0, 8);
    const versione = pulito_(d.versione, 40);
    const oggetto = pulito_(d.oggetto, 120);
    const descrizione = pulito_(d.descrizione, 6000);
    const contatto = pulito_(d.contatto, 200);
    const riassunto = pulito_(d.riassunto, 30000);

    const blob = Utilities.newBlob(byte, 'application/zip', 'rapporto-' + codice + '.zip');
    const file = cartella_().createFile(blob);
    file.setDescription('FreeLaserCut ' + versione + ' · ' + oggetto + '\n\n' + descrizione);

    const testo = [
      'Nuovo rapporto per l\'assistenza',
      'Codice: ' + codice,
      'Versione: ' + versione,
      'Contatto per la risposta: ' + (contatto || '(nessuno)'),
      'File in Drive: ' + file.getUrl(),
      '',
      '— DESCRIZIONE DELL\'UTENTE —',
      descrizione || '(vuota)',
      '',
      '— RIASSUNTO TECNICO —',
      riassunto,
    ].join('\n');
    MailApp.sendEmail({
      to: AVVISA,
      subject: '[FLC rapporto] ' + versione + ' · ' + codice + (oggetto ? ' · ' + oggetto : ''),
      body: testo,
      attachments: [blob],
      replyTo: contatto && contatto.indexOf('@') > 0 ? contatto : AVVISA,
    });
    return risposta_({ ok: true, codice: codice });
  } catch (err) {
    return risposta_({ ok: false, errore: String(err).slice(0, 200) });
  }
}

/** Ogni notte: cancella (nel cestino di Drive) i rapporti più vecchi di GIORNI_DA_TENERE. */
function pulisci() {
  const limite = new Date(Date.now() - GIORNI_DA_TENERE * 24 * 3600 * 1000);
  const files = cartella_().getFiles();
  while (files.hasNext()) {
    const f = files.next();
    if (f.getDateCreated() < limite) f.setTrashed(true);
  }
  // contatori giornalieri dei giorni passati: non servono più
  const oggi = 'n-' + Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyyMMdd');
  const props = PropertiesService.getScriptProperties();
  Object.keys(props.getProperties()).forEach(k => { if (k.indexOf('n-') === 0 && k !== oggi) props.deleteProperty(k); });
}

// ------------------------------------------------------------------ utilità
function cartella_() {
  const it = DriveApp.getFoldersByName(CARTELLA);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CARTELLA);
}

function sottoIlLimite_() {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties();
    const chiave = 'n-' + Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyyMMdd');
    const n = Number(props.getProperty(chiave) || 0);
    if (n >= MAX_AL_GIORNO) return false;
    props.setProperty(chiave, String(n + 1));
    return true;
  } finally {
    lock.releaseLock();
  }
}

function pulito_(v, max) {
  return String(v == null ? '' : v).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '').slice(0, max);
}

function risposta_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
