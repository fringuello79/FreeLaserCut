# «Manda a FreeLaserCut» per uno strumento web

`freelasercut-link.js` aggiunge a una pagina web il pulsante **→ Manda a FreeLaserCut**: il disegno fatto nella pagina
arriva sul piano di lavoro di FreeLaserCut, aperto sullo stesso computer, senza scaricarlo e importarlo a mano.

È nato per gli strumenti laser di MakerHub (Dima Lab, Forma Lab, Hinge Lab, Split Lab), che sono di MakerHub e non
stanno in questo repository. Lo script da solo ha licenza MIT: si può mettere in qualsiasi pagina.

## Per chi gestisce la pagina

1. Copiare `freelasercut-link.js` nella cartella dello strumento.
2. In fondo a `index.html`, dopo gli altri script:

   ```html
   <script src="freelasercut-link.js"
           data-strumento="Dima Lab"
           data-pulsanti="#export = Manda a FreeLaserCut"></script>
   ```

   - `data-strumento`: il nome dello strumento, come deve comparire in FreeLaserCut;
   - `data-pulsanti`: uno o più `selettore = etichetta` separati da `;`. Per ogni pulsante della pagina che scarica
     un file da tagliare (un SVG, o uno ZIP di SVG) ne compare uno gemello, subito dopo, con lo stesso stile.

   Per i quattro strumenti di MakerHub i due attributi si possono omettere: lo strumento si riconosce dal titolo.

Il resto della pagina non cambia: i pulsanti di prima scaricano come prima. Lo script non usa cookie, non salva
niente e non chiama nessun server.

Se la pagina sta in un riquadro (`<iframe>`) con `sandbox`, servono `allow-scripts`, `allow-popups` e
`allow-same-origin` (i riquadri di Streamlit li hanno già).

## Come funziona

1. Al clic sul pulsante gemello lo script fa generare il file allo strumento (preme per lui il suo pulsante e prende
   il file prima che parta lo scaricamento).
2. Apre una finestrella su `http://127.0.0.1:47821/flc/ponte`: è una pagina servita da FreeLaserCut, sul computer di
   chi guarda.
3. La finestrella dice «pronto» alla pagina (`postMessage`), la pagina le passa il file, la finestrella lo consegna
   a FreeLaserCut, mostra «fatto» e si chiude.
4. Se FreeLaserCut non risponde entro qualche secondo la pagina propone **Riprova** oppure **Scarica il file**.

Si usa una finestrella, e non una chiamata diretta dalla pagina, perché i browser recenti (Chrome dal 142) chiedono
un permesso alle pagine che chiamano il computer locale e lo negano dentro i riquadri; l'apertura di una finestra no.

## Che cosa accetta FreeLaserCut

- Ascolta solo su `127.0.0.1`, e solo dopo che l'utente ha aperto uno strumento da *Strumenti → MakerHub* (o ha messo
  la spunta a «Ricevi qui i disegni»).
- Accetta disegni solo da pagine `https://maker-hub.it` e sottodomini (lo dice il browser, la pagina non può
  falsificarlo), più le pagine servite dal computer stesso (`http://localhost`, `http://127.0.0.1`) per le prove.
- Un SVG solo va sul piano attivo; uno ZIP con `piano-1.svg`, `piano-2.svg`… mette ogni foglio su un piano di lavoro;
  gli altri SVG di uno ZIP arrivano affiancati. `mappa-montaggio.svg`, i `.txt` e i `.json` vengono saltati.
- Il laser non parte mai: arriva un disegno, che si toglie con Ctrl+Z.

## Da un proprio pulsante

```js
// dentro il clic dell'utente
FreeLaserCutLink.manda(testoSvg_oppure_Blob, 'nome.svg');
```
