# Firma dell'installatore e Microsoft Store

Windows mostra "PC protetto da Windows" (SmartScreen) per i programmi scaricati da Internet che non hanno
ancora una buona reputazione. Dal 2024 nemmeno i certificati EV la danno subito: la reputazione cresce con
i download firmati sempre con la stessa identità. Le strade per FreeLaserCut, dalla più consigliata:

## 1. Microsoft Store (gratuito, nessun avviso)

- Registrazione come sviluppatore individuale gratuita su <https://storedeveloper.microsoft.com>
  (account Microsoft personale, documento d'identità e selfie). Il nome pubblico può essere `fringuello79`.
- Microsoft firma il pacchetto MSIX, lo ospita e distribuisce gli aggiornamenti da sola.
- Passi:
  1. In Partner Center crea l'app "FreeLaserCut" e copia da *Identità del prodotto* i valori
     `Package/Identity/Name` e `Package/Identity/Publisher`.
  2. `python build/prepara_installer.py` (se `build/stage` non c'è), poi
     `python build/prepara_msix.py --identity <Name> --publisher "<Publisher>" --display fringuello79`.
  3. Su Windows, con il Windows SDK: `makeappx pack /d build\msix_layout /p build\FreeLaserCut-<versione>.msix`.
  4. Carica il file `.msix` in Partner Center, con descrizione, screenshot (`docs/screenshot`) e
     l'informativa sulla privacy (FreeLaserCut non raccoglie dati).
- L'app gira come "applicazione desktop con attendibilità totale" (`runFullTrust`): porte USB/COM, camera e
  file funzionano come nell'installatore normale. Le preferenze dell'app dello Store restano separate da
  quelle dell'installatore classico.

## 2. SignPath Foundation (gratuito, per l'installatore scaricabile)

- Firma gratuita per progetti open source con licenza OSI (GPL-3.0 va bene): <https://signpath.org>.
- Nel certificato compare **SignPath Foundation** come editore, quindi il tuo nome non compare.
- Requisiti principali: installatore costruito dal codice pubblico su un servizio di CI
  (pronto: `.github/workflows/installatore.yml`), approvazione manuale di ogni firma,
  autenticazione a due fattori su GitHub, una pagina "Code signing policy" sul sito del progetto.
- Dopo l'approvazione: si toglie il commento al passo "Firma (SignPath)" nel workflow e si aggiunge il
  segreto `SIGNPATH_API_TOKEN`.

## 3. Certificato personale Certum "Open Source Code Signing" (circa 49 € + IVA)

- Certificato in cloud (app SimplySign, nessuna chiavetta).
- **Contiene il tuo nome e cognome** ("Open Source Developer, Nome Cognome"), visibile a chi installa.
- Firma: `makensis -DVER=x.y.z "-DSIGN=signtool sign /fd sha256 /tr http://time.certum.pl /td sha256 /a" build\installer.nsi`
  (firma insieme installatore e disinstallatore).

## Da non fare

- Certificati autofirmati: per chi scarica l'avviso è anche peggiore.
- Comprare un EV solo per togliere l'avviso: dal 2024 non dà più la fiducia immediata.
