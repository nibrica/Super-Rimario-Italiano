# Super Rimario Italiano

Super Rimario Italiano è un dizionario di rime online per la lingua italiana. Questo strumento permette di trovare rime, assonanze atone, assonanze semplici e consonanze, ordinandole per frequenza d'uso.

## Versione online

Il rimario è disponibile online su L'AvisioBlog all'indirizzo https://www.lavisioblog.it/super-rimario-italiano

## Caratteristiche

- Ricerca rapida di rime, assonanze atone, assonanze semplici e consonanze
- Ordinamento dei risultati per frequenza d'uso, con assonanze e consonanze raggruppate per numero di differenze
- Gestione delle parole omografe con tutte le loro letture, come àncora/ancòra o pèsca/pésca
- Rime tra terminazioni in *qu* e *cu*, come iniquo/cospicuo
- Ricerca di parole non presenti nel dizionario indicando l'accento, es. *italiàno*
- Filtri per nomi propri, parole arcaiche e poetiche, parole volgari e offensive (le preferenze vengono ricordate)
- Segnalazione delle parole con accento stimato automaticamente
- Ogni ricerca ha un proprio link, condivisibile con il pulsante "Condividi"; i tasti avanti e indietro del browser funzionano
- Utilizzabile da tastiera e con i lettori di schermo

## Generazione del dizionario

Il dizionario utilizzato da Super Rimario Italiano è generato utilizzando diverse fonti:

- Dump XML del Wikizionario italiano
- Lista di frequenze CoLFIS

Il processo di generazione è gestito dallo script Python `build-dictionary.py`, che combina queste fonti e utilizza `espeak` per determinare gli accenti delle parole quando necessario. Questo significa che alcuni accenti saranno errati.
Per migliorare la qualità di questo dizionario è consigliabile contribuire al Wikizionario.

## Installazione e uso locale

Il sito non ha passaggi di compilazione: i file in `web/` (HTML, CSS, SVG e moduli JavaScript) si usano così come sono. Il dizionario viene letto da `dictionary/out/parole-accenti-frequenze.csv`, che quindi deve essere già stato generato.

1. Clona questo repository
2. Dalla cartella principale del repository avvia un server locale: `python3 -m http.server 8000` (aprire `index.html` direttamente come file non funziona, perché il dizionario viene scaricato dalla pagina)
3. Apri http://localhost:8000/web/ in un browser
4. Per rigenerare il dizionario:
   - Installa Python 3.x
   - Installa mwxml `pip install mwxml`
   - Installa espeak sul tuo sistema operativo
   - Scarica i file specificati in cima allo script e posizionali nella directory `input`
   - Esegui `python build-dictionary.py`

### Requisiti del browser

Serve un browser recente che supporti i moduli ES (`<script type="module">`) e le container query CSS: Chrome ed Edge 105 o successivi, Firefox 110 o successivi, Safari 16 o successivi. `Intl.Segmenter` non è più necessario.

### Integrazione

Il rimario è tutto dentro l'elemento `#rimario` di `web/index.html`, compreso tra i commenti `<!-- rimario:begin -->` e `<!-- rimario:end -->`, e si configura con questi attributi:

| Attributo | Significato | Valore predefinito |
|---|---|---|
| `data-dictionary-url` | URL del file CSV del dizionario (gli URL relativi partono dalla pagina) | `../dictionary/out/parole-accenti-frequenze.csv` |
| `data-attribution-url` | URL della pagina con fonti e licenze del dizionario | `../dictionary/out/ATTRIBUTION.md` |
| `data-title-suffix` | Testo dopo "Rime con X \| " nel titolo della pagina | il titolo iniziale della pagina |
| `data-dictionary-bytes` | Dimensione del CSV decompresso, per mostrare l'avanzamento del download quando il server lo comprime | nessuno |

Tutto il CSS è limitato a `#rimario` e annulla gli stili del tema che lo ospita, quindi il rimario si può inserire in una pagina esistente (per esempio WordPress) senza conflitti. Se il sito ha un'intestazione fissa in alto, impostane l'altezza nella variabile CSS `--sri-sticky-top` (per esempio `#rimario { --sri-sticky-top: 64px; }`), così le schede dei risultati restano visibili sotto di essa.

## Contribuire

Sono benvenuti contributi per migliorare Super Rimario Italiano.

## Licenze

### Codice principale

Il codice principale di Super Rimario Italiano è rilasciato sotto la GNU General Public License v3.0 o successiva (GPL-3.0-or-later).

Super Rimario Italiano è software libero: puoi redistribuirlo e/o modificarlo secondo i termini della GNU General Public License come pubblicata dalla Free Software Foundation, sia la versione 3 della Licenza, sia (a tua scelta) una versione successiva.

Super Rimario Italiano è distribuito nella speranza che sia utile, ma SENZA ALCUNA GARANZIA; senza neppure la garanzia implicita di COMMERCIABILITÀ o IDONEITÀ PER UN PARTICOLARE SCOPO. Vedere la GNU General Public License per maggiori dettagli.

Dovresti aver ricevuto una copia della GNU General Public License insieme a Super Rimario Italiano. In caso contrario, consulta <https://www.gnu.org/licenses/>.

### Dati del Wikizionario

Questo progetto fa uso di dati dal Wikizionario italiano (https://it.wiktionary.org/), un progetto della Wikimedia Foundation Inc., un'organizzazione non-profit.I dati estratti dal Wikizionario italiano sono utilizzati sotto la licenza Creative Commons Attribution-ShareAlike 3.0 Unported License (CC BY-SA 3.0). Per i dettagli, visita: https://creativecommons.org/licenses/by-sa/3.0/

### Altre fonti

Questo progetto include anche materiale dalle seguenti fonti

- [Corpus e Lessico di Frequenza dell'Italiano Scritto (CoLFIS)] - Bertinetto Pier Marco, Burani Cristina, Laudanna Alessandro, Marconi Lucia, Ratti Daniela, Rolando Claudia, Thornton Anna Maria. 2005.
