/*! freelasercut-link.js 1.0 — pulsante «Manda a FreeLaserCut» per uno strumento web.
 *
 * FreeLaserCut (https://github.com/fringuello79/FreeLaserCut) è un programma libero per incisori laser.
 * Questo file, da solo, è distribuito con licenza MIT: si può usare, copiare e modificare liberamente.
 * © 2026 FreeLaserCut
 *
 * COME SI USA: in fondo alla pagina dello strumento, dopo gli altri script:
 *
 *   <script src="freelasercut-link.js"
 *           data-strumento="Dima Lab"
 *           data-pulsanti="#export = Manda a FreeLaserCut"></script>
 *
 *   (per Dima Lab, Forma Lab, Hinge Lab e Split Lab i due attributi si possono anche omettere: basta
 *   <script src="freelasercut-link.js"></script>, lo strumento si riconosce dal titolo della pagina)
 *
 *   data-strumento  il nome dello strumento, come deve comparire in FreeLaserCut
 *   data-pulsanti   uno o più «selettore = etichetta», separati da punto e virgola: per ogni pulsante della pagina
 *                   che scarica un file da tagliare (SVG, oppure ZIP di SVG) ne compare uno gemello, subito dopo,
 *                   che lo manda a FreeLaserCut invece di scaricarlo
 *
 * CHE COSA FA: quando si preme il pulsante gemello, fa generare il file allo strumento (preme per lui il suo
 * pulsante e prende il file prima che parta lo scaricamento), apre una finestrella su http://127.0.0.1:47821
 * (FreeLaserCut, sul computer di chi guarda la pagina), le passa il file e la finestrella si chiude. Se FreeLaserCut
 * non è aperto propone di riprovare o di scaricare il file come sempre. I pulsanti di prima non cambiano.
 * Non manda niente a nessun server: il file va dal browser al programma, sullo stesso computer.
 */
(function () {
  'use strict';
  if (window.FreeLaserCutLink) return;

  var me = document.currentScript;
  function attr(name, fallback) {
    var v = me && me.getAttribute(name);
    return v === null || v === undefined || v === '' ? fallback : v;
  }

  var VERSION = '1.0';
  var PROTOCOL = 1;
  var PORT = parseInt(attr('data-porta', '47821'), 10) || 47821;
  var FLC = 'http://127.0.0.1:' + PORT;
  var BRIDGE = FLC + '/flc/ponte';
  // Se la pagina non dice niente (per esempio perché gli script sono stati incollati dentro l'HTML e gli attributi
  // data- si sono persi), i quattro strumenti di MakerHub si riconoscono dal titolo.
  var KNOWN = [
    [/dima\s*lab/i, 'Dima Lab', '#export = Manda a FreeLaserCut'],
    [/forma\s*lab/i, 'Forma Lab', '#export = Manda a FreeLaserCut'],
    [/hinge\s*lab/i, 'Hinge Lab', '#export = Manda a FreeLaserCut; #coupon = Provino a FreeLaserCut'],
    [/split\s*lab/i, 'Split Lab', '#download = Manda a FreeLaserCut; #coupon = Provino a FreeLaserCut']
  ];
  var given = window.FreeLaserCutConfig || {};
  var known = null;
  KNOWN.forEach(function (k) { if (!known && k[0].test(document.title || '')) known = k; });
  var TOOL = attr('data-strumento', '') || String(given.strumento || '') || (known ? known[1] : '') ||
    (document.title || '').split(/[·|–—]/)[0].replace(/^\s+|\s+$/g, '') || 'MakerHub';
  var WAIT_FILE = 60000; // quanto si aspetta che lo strumento prepari il file
  var WAIT_READY = 6000; // quanto si aspetta che FreeLaserCut risponda
  var WAIT_DONE = 60000; // quanto si aspetta che FreeLaserCut dica «fatto»

  var T = {
    label: 'Manda a FreeLaserCut',
    tip: 'Manda il disegno a FreeLaserCut, il programma per il laser aperto su questo computer',
    sending: 'Mando il disegno a FreeLaserCut…',
    done: 'Il disegno è arrivato in FreeLaserCut.',
    noAnswer: 'FreeLaserCut non risponde. Aprilo su questo computer e nel suo menu scegli Strumenti → MakerHub → ' +
      '«Ricevi qui i disegni». Poi premi Riprova.',
    blocked: 'Il disegno è pronto, ma il browser non ha aperto la finestra di FreeLaserCut.',
    failed: 'FreeLaserCut non è riuscito a ricevere il disegno.',
    retry: 'Riprova',
    sendNow: 'Manda ora',
    save: 'Scarica il file',
    close: 'Chiudi'
  };

  function parseButtons(text) {
    var out = [];
    String(text || '').split(';').forEach(function (part) {
      var i = part.indexOf('='), sel = (i < 0 ? part : part.slice(0, i)).replace(/^\s+|\s+$/g, '');
      var label = i < 0 ? '' : part.slice(i + 1).replace(/^\s+|\s+$/g, '');
      if (sel) out.push({ sel: sel, label: label || T.label });
    });
    return out;
  }
  var BUTTONS = parseButtons(attr('data-pulsanti', '') || String(given.pulsanti || '') || (known ? known[2] : ''));

  // ------------------------------------------------------------------ prendere il file che lo strumento sta per scaricare
  // Gli strumenti scaricano così: creano un Blob, ne fanno un indirizzo (URL.createObjectURL), lo mettono in un
  // <a download> e lo «premono». Mentre aspettiamo un file, quel clic lo prendiamo noi; altrimenti non cambia niente.
  var nativeClick = HTMLAnchorElement.prototype.click;
  var nativeCreate = URL.createObjectURL;
  var waiting = null; // funzione da chiamare con il file, mentre lo si aspetta
  var waitTimer = 0;
  var blobs = []; // {url, blob} creati mentre si aspetta

  function stopWaiting() {
    waiting = null;
    blobs = [];
    clearTimeout(waitTimer);
  }

  URL.createObjectURL = function (obj) {
    var url = nativeCreate.apply(URL, arguments);
    if (waiting && typeof Blob !== 'undefined' && obj instanceof Blob) {
      blobs.push({ url: url, blob: obj });
      if (blobs.length > 8) blobs.shift();
    }
    return url;
  };

  function grab(a) {
    if (!waiting || !a || !a.hasAttribute || !a.hasAttribute('download')) return false;
    var href = a.href || '', blob = null, i;
    for (i = blobs.length - 1; i >= 0; i--) if (blobs[i].url === href) { blob = blobs[i].blob; break; }
    if (!blob) return false;
    var take = waiting;
    stopWaiting();
    take({ nome: a.getAttribute('download') || 'disegno.svg', tipo: blob.type || '', blob: blob });
    return true;
  }

  HTMLAnchorElement.prototype.click = function () {
    if (grab(this)) return undefined;
    return nativeClick.apply(this, arguments);
  };

  document.addEventListener('click', function (e) {
    var t = e.target, a = t && t.closest ? t.closest('a[download]') : null;
    if (a && grab(a)) { e.preventDefault(); e.stopPropagation(); return; }
    // l'utente ha premuto qualcos'altro: non stiamo più aspettando il file (il prossimo si scarica come sempre)
    if (waiting && e.isTrusted && !(t && t.closest && t.closest('[data-flc-link]'))) stopWaiting();
  }, true);

  function toBuffer(blob) {
    if (blob.arrayBuffer) return blob.arrayBuffer();
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = reject;
      r.readAsArrayBuffer(blob);
    });
  }

  function saveFile(file) {
    var a = document.createElement('a'), url = nativeCreate.call(URL, file.blob);
    a.href = url;
    a.download = file.nome;
    a.style.display = 'none';
    document.body.appendChild(a);
    nativeClick.call(a);
    setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 2000);
  }

  // ------------------------------------------------------------------ il biglietto in basso a destra
  var card = null, cardTimer = 0;

  function css(el, style) {
    for (var k in style) if (Object.prototype.hasOwnProperty.call(style, k)) el.style[k] = style[k];
    return el;
  }

  function note(text, kind, actions, autoHide) {
    hideNote();
    card = css(document.createElement('div'), {
      position: 'fixed', right: '18px', bottom: '18px', zIndex: '2147483000', maxWidth: '360px',
      boxSizing: 'border-box', padding: '14px 16px', borderRadius: '10px', background: '#ffffff', color: '#1d2a26',
      border: '1px solid #cfd8d3', borderLeft: '5px solid ' + (kind === 'ok' ? '#2f8f62' : kind === 'bad' ? '#c0492f' : '#7a8a84'),
      boxShadow: '0 8px 28px rgba(0,0,0,.18)', font: '14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif'
    });
    card.setAttribute('data-flc-link', 'nota');
    card.setAttribute('role', 'status');
    var p = css(document.createElement('div'), { margin: '0' });
    p.textContent = text;
    card.appendChild(p);
    var row = css(document.createElement('div'), { display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px' });
    (actions || []).concat([{ label: T.close, plain: true, run: function () {} }]).forEach(function (act) {
      var b = css(document.createElement('button'), {
        font: 'inherit', padding: '6px 12px', borderRadius: '7px', cursor: 'pointer', margin: '0', width: 'auto',
        border: '1px solid ' + (act.plain ? '#cfd8d3' : '#284c40'), background: act.plain ? '#ffffff' : '#284c40',
        color: act.plain ? '#1d2a26' : '#ffffff'
      });
      b.type = 'button';
      b.textContent = act.label;
      b.addEventListener('click', function (e) { e.stopPropagation(); hideNote(); act.run(); });
      row.appendChild(b);
    });
    if (kind !== 'wait') card.appendChild(row);
    document.body.appendChild(card);
    if (autoHide) cardTimer = setTimeout(hideNote, autoHide);
  }

  function hideNote() {
    clearTimeout(cardTimer);
    if (card) { card.remove(); card = null; }
  }

  // ------------------------------------------------------------------ la consegna
  var job = null; // la consegna in corso: {file, buf, win, ready, sent, done, timer}

  function closeWin(j) {
    try { if (j.win && !j.win.closed) j.win.close(); } catch (e) { /* già chiusa */ }
    j.win = null;
  }

  function offer(j, text, retryLabel) {
    clearTimeout(j.timer);
    var actions = [];
    if (retryLabel) actions.push({ label: retryLabel, run: function () { openBridge(j); } });
    actions.push({ label: T.save, plain: !!retryLabel, run: function () { j.done = true; saveFile(j.file); } });
    note(text, 'bad', actions);
  }

  function pump(j) {
    if (!j.ready || !j.buf || j.sent || !j.win) return;
    j.sent = true;
    j.win.postMessage({ flc: 'disegno', v: PROTOCOL, strumento: TOOL,
      file: [{ nome: j.file.nome, tipo: j.file.tipo, dati: j.buf }] }, FLC);
  }

  function openBridge(j) {
    var w = null, width = 440, height = 300;
    var left = Math.max(0, Math.round((window.screenX || 0) + ((window.outerWidth || width) - width) / 2));
    var top = Math.max(0, Math.round((window.screenY || 0) + ((window.outerHeight || height) - height) / 3));
    j.ready = false;
    j.sent = false;
    j.done = false;
    job = j;
    try {
      w = window.open(BRIDGE, 'freelasercut_ponte', 'popup=yes,width=' + width + ',height=' + height + ',left=' + left + ',top=' + top);
    } catch (e) { w = null; }
    if (!w || w.closed) { offer(j, T.blocked, T.sendNow); return; }
    j.win = w;
    note(T.sending, 'wait');
    clearTimeout(j.timer);
    j.timer = setTimeout(function () {
      if (j.done || j.ready) return;
      closeWin(j);
      offer(j, T.noAnswer, T.retry);
    }, WAIT_READY);
  }

  window.addEventListener('message', function (e) {
    var j = job, d = e.data;
    if (!j || j.done || e.origin !== FLC || !j.win || e.source !== j.win || !d) return;
    if (d.flc === 'pronto') {
      j.ready = true;
      clearTimeout(j.timer);
      j.timer = setTimeout(function () { if (!j.done) { closeWin(j); offer(j, T.noAnswer, T.retry); } }, WAIT_DONE);
      pump(j);
    } else if (d.flc === 'fatto') {
      clearTimeout(j.timer);
      j.done = true;
      if (d.ok) {
        note(String(d.messaggio || '') || T.done, 'ok', [], 9000);
      } else {
        var w = j.win;
        setTimeout(function () { try { if (w && !w.closed) w.close(); } catch (err) { /* già chiusa */ } }, 400);
        j.win = null;
        offer(j, String(d.messaggio || '') || T.failed, null);
      }
    }
  });

  function deliver(file) {
    var j = { file: file, buf: null, win: null, ready: false, sent: false, done: false, timer: 0 };
    openBridge(j); // subito: è il clic dell'utente che permette al browser di aprire la finestra
    toBuffer(file.blob).then(function (buf) { j.buf = buf; pump(j); }, function () {
      closeWin(j);
      offer(j, T.failed, null);
    });
  }

  function start(b) {
    var orig = document.querySelector(b.sel);
    if (!orig || orig.disabled) return;
    hideNote();
    stopWaiting();
    waiting = deliver;
    waitTimer = setTimeout(stopWaiting, WAIT_FILE);
    try {
      orig.click(); // lo strumento fa i suoi controlli e prepara il file, come quando lo si scarica
    } catch (e) {
      stopWaiting();
      throw e;
    }
  }

  // ------------------------------------------------------------------ i pulsanti gemelli
  function ensure() {
    BUTTONS.forEach(function (b) {
      var orig = document.querySelector(b.sel), twins, i, mine = null, cls, par, cs;
      twins = document.querySelectorAll('[data-flc-per="' + b.sel.replace(/"/g, '\\"') + '"]');
      for (i = 0; i < twins.length; i++) {
        if (orig && orig.nextElementSibling === twins[i] && !mine) mine = twins[i];
        else twins[i].remove();
      }
      if (!orig) return;
      if (!mine) {
        mine = document.createElement('button');
        mine.type = 'button';
        mine.setAttribute('data-flc-link', 'pulsante');
        mine.setAttribute('data-flc-per', b.sel);
        mine.textContent = '→ ' + b.label;
        mine.title = T.tip;
        mine.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); start(b); });
        orig.insertAdjacentElement('afterend', mine);
        par = orig.parentElement;
        cs = par && window.getComputedStyle ? getComputedStyle(par) : null;
        if (cs && cs.display.indexOf('flex') >= 0 && cs.flexDirection.indexOf('row') === 0 &&
            cs.justifyContent === 'space-between' && !orig.style.marginLeft) orig.style.marginLeft = 'auto';
      }
      cls = String(orig.className || '').split(/\s+/).filter(function (c) { return c && c !== 'primary' && c !== 'active'; }).join(' ');
      if (mine.className !== cls) mine.className = cls;
      if (mine.disabled !== !!orig.disabled) mine.disabled = !!orig.disabled;
      if (mine.hidden !== !!orig.hidden) mine.hidden = !!orig.hidden;
    });
  }

  var pending = false;
  function later() {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; ensure(); }, 60);
  }

  if (BUTTONS.length) {
    ensure();
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(later).observe(document.documentElement,
        { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'hidden', 'class'] });
    }
    document.addEventListener('DOMContentLoaded', ensure);
    window.addEventListener('load', ensure);
  }

  // Per chi vuole mandare un file da un proprio pulsante: FreeLaserCutLink.manda(svg_o_blob, 'nome.svg'),
  // chiamata dentro il clic dell'utente.
  window.FreeLaserCutLink = {
    versione: VERSION,
    manda: function (data, name) {
      var blob = typeof Blob !== 'undefined' && data instanceof Blob ? data : new Blob([data]);
      hideNote();
      deliver({ nome: String(name || 'disegno.svg'), tipo: blob.type || '', blob: blob });
    }
  };
})();
