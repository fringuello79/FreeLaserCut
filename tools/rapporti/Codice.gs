/**
 * FreeLaserCut — ricevitore dei rapporti per l'assistenza (Google Apps Script), versione 2.
 *
 * Gira sull'account Google del progetto (freelasercut@gmail.com). FreeLaserCut gli manda un rapporto
 * SOLO quando l'utente preme «Invia» nella finestra Aiuto → Invia un rapporto all'assistenza.
 *
 * Cosa fa:
 *  - salva il rapporto (.zip) e un testo leggibile (descrizione + riassunto tecnico) nella cartella
 *    di Google Drive «FreeLaserCut - rapporti» e manda un'email di avviso;
 *  - SCREMA da solo, senza intelligenza artificiale: rapporti vuoti, doppioni della stessa persona,
 *    versioni vecchie; scrive una riga per rapporto nel foglio «Registro rapporti»;
 *  - ogni mattina prepara un LOTTO («FLC lotto AAAA-MM-GG») quando ci sono almeno LOTTO_MIN rapporti
 *    utili nuovi, oppure il lunedì se ce n'è almeno uno: il lotto è un testo breve, raggruppato per
 *    problema, che Claude legge per l'analisi settimanale (pochi token).
 *
 * Nessuna password nel programma: FreeLaserCut conosce solo l'indirizzo pubblico di questa app web.
 * Rapporti, testi, lotti e righe del registro più vecchi di 12 mesi si cancellano da soli
 * (vedi l'informativa privacy).
 *
 * Installazione / aggiornamento: incolla tutto il file nel progetto su script.google.com, esegui una
 * volta la funzione «installa», poi Esegui il deployment → Gestisci deployment → matita → Versione:
 * Nuova versione → Esegui il deployment (l'indirizzo /exec resta lo stesso).
 */

const CARTELLA = 'FreeLaserCut - rapporti';
const REGISTRO = 'Registro rapporti';
const AVVISA = 'freelasercut@gmail.com';
const REPO = 'fringuello79/FreeLaserCut';
const MAX_BYTE = 10 * 1024 * 1024;   // rapporto più grande: 10 MB
const MAX_AL_GIORNO = 300;           // protezione contro gli abusi
const GIORNI_DA_TENERE = 365;        // poi tutto si cancella da solo
const LOTTO_MIN = 5;                 // rapporti utili nuovi che fanno partire un lotto
const GIORNO_LOTTO = 1;              // lunedì: lotto anche con un solo rapporto utile
const GIORNI_DOPPIONE = 14;          // stessa persona e stesso problema entro questi giorni = doppione
const RISPOSTA_AUTOMATICA = false;   // true: risponde da solo «ricevuto» a chi ha lasciato l'email
const INTESTAZIONE = ['Data', 'Codice', 'Versione', 'Oggetto', 'Descrizione (breve)', 'Contatto', 'Firma',
                      'Stato', 'Nota', 'Lotto', 'Testo', 'Zip'];

/** Da eseguire dall'editor (anche più volte): cartella, registro e operazioni automatiche. */
function installa() {
  cartella_();
  registro_();
  ScriptApp.getProjectTriggers()
    .filter(t => ['pulisci', 'preparaLotto'].indexOf(t.getHandlerFunction()) >= 0)
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('pulisci').timeBased().everyDays(1).atHour(3).create();
  ScriptApp.newTrigger('preparaLotto').timeBased().everyDays(1).atHour(6).create();
  ultimaVersione_();  // chiede subito il permesso di leggere le versioni pubblicate su GitHub
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

    const dir = cartella_();
    const blob = Utilities.newBlob(byte, 'application/zip', 'rapporto-' + codice + '.zip');
    const zip = dir.createFile(blob);
    zip.setDescription('FreeLaserCut ' + versione + ' · ' + oggetto);
    const testo = [
      'Codice: ' + codice, 'Versione: ' + versione, 'Oggetto: ' + oggetto, '',
      '— DESCRIZIONE DELL\'UTENTE —', descrizione || '(vuota)', '',
      '— RIASSUNTO TECNICO —', riassunto,
    ].join('\n');
    const txt = dir.createFile('rapporto-' + codice + '.txt', testo, MimeType.PLAIN_TEXT);

    const v = valuta_(codice, versione, oggetto, descrizione, contatto, riassunto);
    registro_().appendRow([new Date(), codice, versione, oggetto, compatto_(descrizione, 300),
      contatto ? 'sì' : 'no', v.firma, v.stato, v.nota, '', txt.getUrl(), zip.getUrl()]);

    MailApp.sendEmail({
      to: AVVISA,
      subject: '[FLC rapporto' + (v.stato === 'nuovo' ? '' : ' · ' + v.stato) + '] ' + versione + ' · ' + codice
        + (oggetto ? ' · ' + oggetto : ''),
      body: 'Contatto per la risposta: ' + (contatto || '(nessuno)') + '\nScrematura: ' + v.stato
        + (v.nota ? ' (' + v.nota + ')' : '') + '\nFile in Drive: ' + zip.getUrl() + '\n\n' + testo,
      attachments: [blob],
      replyTo: emailValida_(contatto) ? contatto : AVVISA,
    });
    if (RISPOSTA_AUTOMATICA && emailValida_(contatto) && v.stato !== 'doppione') {
      rispondi_(contatto, codice, v.vecchia);
    }
    return risposta_({ ok: true, codice: codice });
  } catch (err) {
    return risposta_({ ok: false, errore: String(err).slice(0, 200) });
  }
}

/** Ogni mattina: se ci sono abbastanza rapporti utili nuovi (o è lunedì), prepara il lotto per Claude. */
function preparaLotto() {
  const oggi = new Date();
  const lunedi = Number(Utilities.formatDate(oggi, 'Europe/Rome', 'u')) === GIORNO_LOTTO;
  lotto_(lunedi ? 1 : LOTTO_MIN);
}

/** Da eseguire a mano dall'editor se si vuole subito un lotto con tutto quello che c'è di nuovo. */
function lottoAdesso() {
  lotto_(1);
}

function lotto_(minimo) {
  const sh = registro_();
  const righe = sh.getDataRange().getValues();
  const col = indici_(righe[0]);
  const nuove = [];
  let scartati = 0;
  for (let i = 1; i < righe.length; i++) {
    const r = righe[i];
    if (r[col.Lotto]) continue;
    if (r[col.Stato] === 'nuovo') nuove.push(i);
    else scartati++;
  }
  if (nuove.length < minimo) return;
  const nome = 'FLC lotto ' + Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyy-MM-dd');

  // raggruppa per firma del problema
  const gruppi = {};
  nuove.forEach(i => {
    const r = righe[i];
    const f = r[col.Firma] || ('oggetto: ' + String(r[col.Oggetto]).toLowerCase());
    (gruppi[f] = gruppi[f] || []).push(r);
  });
  const ordine = Object.keys(gruppi).sort((a, b) => gruppi[b].length - gruppi[a].length);
  const out = [nome, 'Rapporti utili: ' + nuove.length + ' · scartati dalla scrematura: ' + scartati
    + ' · ultima versione pubblicata: ' + (ultimaVersione_() || '?'), ''];
  ordine.forEach((f, n) => {
    const g = gruppi[f];
    const versioni = Array.from(new Set(g.map(r => r[col.Versione]))).join(', ');
    out.push('## Problema ' + (n + 1) + ' — ' + g.length + (g.length === 1 ? ' rapporto' : ' rapporti') + ' · versioni ' + versioni);
    out.push('Firma: ' + f);
    g.forEach(r => {
      out.push('- ' + r[col.Codice] + ' · ' + r[col.Versione] + ' · contatto ' + r[col.Contatto]
        + (r[col.Nota] ? ' · ' + r[col.Nota] : '') + ' · ' + r[col.Oggetto]);
      out.push('  ' + String(r[col.Descrizione]).replace(/\s+/g, ' '));
      out.push('  testo completo: ' + r[col.Testo]);
    });
    out.push('');
  });
  cartella_().createFile(nome + '.txt', out.join('\n'), MimeType.PLAIN_TEXT);
  for (let i = 1; i < righe.length; i++) {
    if (!righe[i][col.Lotto]) sh.getRange(i + 1, col.Lotto + 1).setValue(nome);
  }
}

/** Ogni notte: cestina rapporti, testi e lotti più vecchi di GIORNI_DA_TENERE e le loro righe nel registro. */
function pulisci() {
  const limite = new Date(Date.now() - GIORNI_DA_TENERE * 24 * 3600 * 1000);
  const reg = registro_();
  const files = cartella_().getFiles();
  while (files.hasNext()) {
    const f = files.next();
    if (f.getId() !== reg.getParent().getId() && f.getDateCreated() < limite) f.setTrashed(true);
  }
  const righe = reg.getDataRange().getValues();
  for (let i = righe.length - 1; i >= 1; i--) {
    if (righe[i][0] instanceof Date && righe[i][0] < limite) reg.deleteRow(i + 1);
  }
  const oggi = 'n-' + Utilities.formatDate(new Date(), 'Europe/Rome', 'yyyyMMdd');
  const props = PropertiesService.getScriptProperties();
  Object.keys(props.getProperties()).forEach(k => { if (k.indexOf('n-') === 0 && k !== oggi) props.deleteProperty(k); });
}

// ------------------------------------------------------------------ scrematura
function valuta_(codice, versione, oggetto, descrizione, contatto, riassunto) {
  const errore = (riassunto.match(/Ultimo errore del programma: (.*)/) || [])[1] || '';
  const allarme = (riassunto.match(/Ultimo allarme: (\d+)/) || [])[1] || '';
  const firma = errore ? 'errore: ' + normalizza_(errore)
    : allarme ? 'allarme ' + allarme
    : 'oggetto: ' + normalizza_(oggetto);
  // testo scritto davvero dall'utente, senza le etichette della finestra
  const scritto = (oggetto + ' ' + descrizione)
    .replace(/Cosa stavi facendo:|Cosa ti aspettavi:|Cosa è successo:|Succede:.*$/gm, '')
    .replace(/[\s\W_]+/g, '');
  const ultima = ultimaVersione_();
  const vecchia = !!(ultima && versione && confronta_(versione, ultima) < 0);
  const nota = vecchia ? 'versione vecchia (ultima ' + ultima + ')' : '';

  if (scritto.length < 15 && !errore && !allarme) {
    return { stato: 'scartato', nota: 'senza descrizione né errori', firma: firma, vecchia: vecchia };
  }
  if (contatto) {
    const dop = doppione_(contatto, firma, codice);
    if (dop) return { stato: 'doppione', nota: 'come ' + dop, firma: firma, vecchia: vecchia };
  }
  return { stato: 'nuovo', nota: nota + (scritto.length < 15 ? (nota ? ' · ' : '') + 'solo dati tecnici' : ''),
           firma: firma, vecchia: vecchia };
}

function doppione_(contatto, firma, codice) {
  // l'email non va nel registro: si tiene solo un'impronta (hash) del contatto con le firme recenti
  const limite = new Date(Date.now() - GIORNI_DOPPIONE * 24 * 3600 * 1000);
  const chiave = 'c-' + Utilities.base64EncodeWebSafe(
    Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, contatto.trim().toLowerCase())).slice(0, 16);
  const props = PropertiesService.getScriptProperties();
  const visti = JSON.parse(props.getProperty(chiave) || '[]').filter(v => new Date(v[0]) >= limite);
  const uguale = visti.filter(v => v[1] === firma)[0];
  visti.push([new Date().toISOString(), firma, codice]);
  props.setProperty(chiave, JSON.stringify(visti.slice(-20)));
  return uguale ? uguale[2] : '';
}

function normalizza_(s) {
  return String(s || '').toLowerCase()
    .replace(/[a-z]:\\[^\s]*/g, '')        // percorsi di Windows
    .replace(/0x[0-9a-f]+/g, '#')          // indirizzi
    .replace(/\d+([.,]\d+)?/g, '#')        // numeri
    .replace(/\s+/g, ' ').trim().slice(0, 140);
}

function confronta_(a, b) {
  const x = String(a).replace(/^v/, '').split('.').map(Number);
  const y = String(b).replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d;
  }
  return 0;
}

function ultimaVersione_() {
  const cache = CacheService.getScriptCache();
  const c = cache.get('ultima');
  if (c) return c;
  try {
    const r = UrlFetchApp.fetch('https://api.github.com/repos/' + REPO + '/releases/latest',
      { muteHttpExceptions: true, headers: { 'User-Agent': 'FreeLaserCut-rapporti' } });
    if (r.getResponseCode() !== 200) return '';
    const v = String(JSON.parse(r.getContentText()).tag_name || '').replace(/^v/, '');
    if (v) cache.put('ultima', v, 6 * 3600);
    return v;
  } catch (err) {
    return '';
  }
}

function rispondi_(a, codice, vecchia) {
  const righe = [
    'Ciao,',
    '',
    'il tuo rapporto è arrivato, grazie. Il codice è ' + codice + ': se vuoi aggiungere qualcosa, rispondi a questa mail.',
  ];
  if (vecchia) {
    righe.push('', 'Intanto, se puoi, aggiorna FreeLaserCut (Aiuto → Cerca aggiornamenti…): il problema potrebbe '
      + 'essere già risolto nella versione nuova.');
  }
  righe.push('', 'FreeLaserCut');
  MailApp.sendEmail({ to: a, subject: 'FreeLaserCut: rapporto ' + codice + ' ricevuto', body: righe.join('\n'),
    replyTo: AVVISA });
}

// ------------------------------------------------------------------ utilità
function cartella_() {
  const it = DriveApp.getFoldersByName(CARTELLA);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CARTELLA);
}

/** Il foglio del registro (lo crea nella cartella la prima volta). */
function registro_() {
  const dir = cartella_();
  const it = dir.getFilesByName(REGISTRO);
  let ss;
  if (it.hasNext()) {
    ss = SpreadsheetApp.open(it.next());
  } else {
    ss = SpreadsheetApp.create(REGISTRO);
    DriveApp.getFileById(ss.getId()).moveTo(dir);
    const sh = ss.getSheets()[0];
    sh.appendRow(INTESTAZIONE);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, INTESTAZIONE.length).setFontWeight('bold');
  }
  return ss.getSheets()[0];
}

function indici_(intestazione) {
  const c = {};
  intestazione.forEach((h, i) => { c[String(h).split(' ')[0]] = i; });
  return c;
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

function emailValida_(s) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(s || '').trim());
}

/** La descrizione in una riga, con etichette corte (meno testo da leggere nel lotto). */
function compatto_(s, max) {
  return breve_(String(s || '')
    .replace(/Cosa stavi facendo:/g, 'facevo:')
    .replace(/Cosa ti aspettavi:/g, '· atteso:')
    .replace(/Cosa è successo:/g, '· successo:')
    .replace(/Succede:/g, '· succede:'), max);
}

function breve_(s, max) {
  return String(s || '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function pulito_(v, max) {
  return String(v == null ? '' : v).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '').slice(0, max);
}

function risposta_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
