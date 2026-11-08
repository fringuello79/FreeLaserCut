# Ricevitore dei rapporti per l'assistenza

`Codice.gs` è un piccolo programma di Google Apps Script che gira sull'account Google del progetto
(freelasercut@gmail.com). Riceve i rapporti che le persone inviano da *Aiuto → Invia un rapporto all'assistenza*,
li salva nella cartella di Google Drive **FreeLaserCut - rapporti** e manda un'email di avviso con la descrizione e il
riassunto tecnico (lo .zip è anche allegato). I rapporti più vecchi di 12 mesi vanno da soli nel cestino.

Nel programma FreeLaserCut c'è solo l'indirizzo pubblico dell'app web (`SUPPORT_URL` in `freelasercut/support.py`):
nessuna password. Limiti: 10 MB per rapporto, 300 rapporti al giorno.

## Installazione (una volta sola)
1. Entra in Google con **freelasercut@gmail.com** e apri **script.google.com** → **Nuovo progetto**.
2. Cancella il testo che c'è, incolla tutto `Codice.gs`, dai al progetto il nome «FreeLaserCut rapporti» e salva.
3. Nella barra in alto scegli la funzione **installa** e premi **Esegui**. Google chiede l'autorizzazione:
   **Rivedi le autorizzazioni** → scegli l'account → **Avanzate** → **Vai a FreeLaserCut rapporti (non sicuro)** →
   **Consenti** (lo script è tuo: il messaggio «non sicuro» compare per tutti gli script non pubblicati).
4. **Esegui il deployment** → **Nuovo deployment** → ingranaggio → **App web**.
   *Esegui come:* **Me** · *Chi può accedere:* **Chiunque** → **Esegui il deployment**.
5. Copia l'**URL dell'app web** (finisce con `/exec`) e mettilo in `SUPPORT_URL`.
   Aprendolo nel browser deve comparire «FreeLaserCut: ricevitore dei rapporti attivo.»

Se cambi lo script: **Esegui il deployment** → **Gestisci i deployment** → matita → *Versione:* **Nuova versione**
→ **Esegui il deployment** (l'indirizzo resta lo stesso).
