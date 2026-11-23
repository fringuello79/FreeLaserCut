# FreeLaserCut 0.22.4 su macOS Ventura Intel

La patch aggiunge `--ventura` allo script di build per macOS. Il pacchetto aggiuntivo usa Python 3.13.18, Qt/PySide6 Essentials e Shiboken6 6.9.3 e OpenCV headless 4.11.0.86. Nei controlli sulle wheel, alcuni moduli Intel di PySide6 6.10.3 dichiarano macOS 15 anche se il nome della wheel indica macOS 13. PySide6 6.9.3 richiede Python precedente a 3.14. La wheel Intel di OpenCV 5.0.0.93 richiede macOS 14. OpenCV 4.11.0.86 è disponibile per macOS 13 e si installa con NumPy 2.5.4. Lo script seleziona le wheel per Ventura anche quando gira su un macOS più recente e controlla il deployment target dei binari Intel prima di firmare l’app. [Qt per macOS](https://doc.qt.io/qt-6.9/macos.html) · [PySide6 Essentials 6.9.3](https://pypi.org/project/PySide6-Essentials/6.9.3/#files) · [OpenCV headless 4.11.0.86](https://pypi.org/project/opencv-python-headless/4.11.0.86/#files)

## Costruire il pacchetto

Se hai già il branch `mac-ventura`, esegui direttamente il comando di build qui sotto. I passaggi `git clone` e `git apply` servono per applicare la patch a una copia pulita del tag ufficiale.

Servono un Mac Intel con macOS 13 o successivo, Python 3.12, gli strumenti da riga di comando di Xcode (`xcode-select --install` se mancanti) e accesso a GitHub e PyPI. Lo script scarica Python 3.13.18 e lo include nell’app. Metti `freelasercut-0.22.4-ventura.patch` nella cartella da cui esegui questi comandi.

```sh
git clone --branch v0.22.4 --depth 1 https://github.com/fringuello79/FreeLaserCut.git FreeLaserCut
cd FreeLaserCut
git rev-parse HEAD
# Commit atteso: 6a2c54635d75ba401088c106d0e5de3b70f48fce
git apply --check ../freelasercut-0.22.4-ventura.patch
git apply ../freelasercut-0.22.4-ventura.patch
python3.12 build/prepara_mac.py --arch x86_64 --ventura

dmg=FreeLaserCut-0.22.4-macOS-ventura-x86_64.dmg
hdiutil verify "build/$dmg"
(cd build && shasum -a 256 "$dmg" > "$dmg.sha256" && shasum -a 256 -c "$dmg.sha256")
```

Il `.dmg` e il checksum si trovano in `build/`. L’app per le prove è in `build/mac-ventura/` insieme a `dipendenze.json`, il rapporto di pip con versioni, wheel e hash. La build ufficiale si ottiene con `python3.12 build/prepara_mac.py --arch x86_64` e usa un’altra cartella di lavoro. Il pacchetto Ventura mantiene lo stesso identificativo dell’app, perciò installarlo nello stesso percorso sostituisce la copia presente e usa le stesse preferenze.

Per costruire su GitHub Actions, il manutentore può usare il workflow di anteprima macOS su un ramo `mac-ventura`. Nel job di prova basta tenere il runner `macos-15-intel`, aggiungere `--ventura` al comando di build, usare `build/mac-ventura/FreeLaserCut.app` nelle verifiche e caricare il `.dmg` Ventura, il checksum e `build/mac-ventura/dipendenze.json` come artefatti. Il runner verifica la build su macOS 15. Il collaudo finale va eseguito su Ventura. [Workflow di anteprima](https://github.com/fringuello79/FreeLaserCut/blob/6a2c54635d75ba401088c106d0e5de3b70f48fce/.github/workflows/mac.yml)

## Adattare una versione precedente dai sorgenti

Apri il checkout del tag da adattare. Esegui `git apply --check` con la patch. Se lo script differisce, riporta le modifiche alla versione di Python, alla selezione delle wheel, al controllo dei binari, al minimo nel plist e al nome del pacchetto. Riporta anche la correzione in `freelasercut/ui/banco.py` che mantiene vive le azioni della barra dei menu con PySide6 6.9. Conserva i pin originali di quella versione dove compatibili. Se il suo NumPy è incompatibile con OpenCV 4.11.0.86, verifica insieme le versioni di Python, NumPy e OpenCV. Ripeti l’intero collaudo con il `.dmg` del tag scelto. Il `.dmg` già distribuito contiene i binari originali e va sostituito da una nuova build.

## Provare su Ventura 13.7.8

La patch si applica al commit indicato sopra. Su Windows sono passati i 41 controlli di `tests/test_v208_mac.py` e i 40 di `tests/test_v222_banco_rete.py` con Python 3.13, PySide6 6.9 e OpenCV 4.11. Sono passate anche le prove mirate di importazione, nomi dei progetti e dimensione dei caratteri in Banco e Classica. È stato verificato il requisito macOS dei 424 binari Intel nelle wheel e nel runtime scaricati. Restano da eseguire la creazione del `.dmg` e il collaudo completo su macOS.

Da Terminale, nella cartella del sorgente, esegui i test con il runtime della build e poi avvia l’app confezionata in entrambe le interfacce.

```sh
app=build/mac-ventura/FreeLaserCut.app
codesign --verify --deep --strict "$app"
plutil -extract LSMinimumSystemVersion raw "$app/Contents/Info.plist"
QT_QPA_PLATFORM=offscreen PYTHONUNBUFFERED=1 "$app/Contents/Resources/python/bin/python3.13" tests/run_tests.py
FLC_UI=classica "$app/Contents/MacOS/FreeLaserCut" --self-test > selftest-classica.txt
FLC_UI=banco "$app/Contents/MacOS/FreeLaserCut" --self-test > selftest-banco.txt
grep -H -i 'piattaforma Qt cocoa\|ESITO: tutto a posto' selftest-classica.txt selftest-banco.txt
grep -i 'interfaccia Banco: ok' selftest-banco.txt
```

Verifica che il minimo sia `13.0` e che ciascun log riporti sia `cocoa` sia `ESITO: tutto a posto`. Apri il `.dmg` dal Finder e avvia l’app seguendo il LEGGIMI incluso. Prova l’apertura e il salvataggio di una copia di un progetto `.flcut`. Con emissione del laser disabilitata, verifica che il controller compaia tra le porte USB e che l’app legga lo stato della macchina. Registra a parte eventuali prove con camera e Wi-Fi. Un test d’avvio su un Mac con una versione più recente non sostituisce la prova su Ventura.
