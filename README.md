# Super Rimario Italiano

Super Rimario Italiano è un dizionario di rime online per la lingua italiana. Questo strumento permette di trovare rime, assonanze atone, assonanze semplici e consonanze, ordinandole per frequenza d'uso.

## Versione online

Il rimario è disponibile online su L'AvisioBlog all'indirizzo https://www.lavisioblog.it/super-rimario-italiano

## Caratteristiche

- Ricerca rapida di rime, assonanze atone, assonanze semplici e consonanze
- Ordinamento dei risultati per frequenza d'uso, con assonanze e consonanze raggruppate per numero di differenze
- Gestione delle parole omografe con tutte le loro letture, come àncora/ancòra o prìncipi/princìpi
- Rime tra terminazioni in *qu* e *cu*, come iniquo/cospicuo
- Ricerca di parole non presenti nel dizionario indicando l'accento, es. *italiàno*
- Filtri per nomi propri, parole arcaiche e poetiche, parole volgari e offensive (le preferenze vengono ricordate)
- Segnalazione delle parole con accento stimato automaticamente
- Ogni ricerca ha un proprio link, condivisibile con il pulsante "Condividi"; i tasti avanti e indietro del browser funzionano
- Utilizzabile da tastiera e con i lettori di schermo

## Generazione del dizionario

Il dizionario utilizzato da Super Rimario Italiano (`web/parole-accenti-frequenze.csv`) è generato combinando diverse fonti, tutte scaricate automaticamente nella loro versione più recente:

- Le voci italiane del Wiktionary inglese e del Wikizionario italiano, già estratte da [Kaikki.org](https://kaikki.org/) (wiktextract): accenti, pronuncia IPA, sillabazione e coniugazioni
- [Morph-it!](https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it), con circa 505.000 forme flesse dell'italiano
- Le frequenze d'uso di [wordfreq](https://github.com/rspeer/wordfreq), dei sottotitoli di OpenSubtitles ([FrequencyWords](https://github.com/hermitdave/FrequencyWords)) e delle notizie recenti della [Leipzig Corpora Collection](https://wortschatz.uni-leipzig.de/en/download/Italian)

Il processo è gestito dal pacchetto Python in `dictionary/`, che non usa più `espeak`, il dump XML del Wikizionario né la lista CoLFIS. L'accento delle parole che nessuna fonte riporta viene ricavato dalle altre forme dello stesso verbo o della stessa parola (*càpito* → *càpitano*, *dìmmelo*) e, solo in ultima istanza, stimato da un modello addestrato sulle parole note: queste parole sono segnalate nel dizionario, e alcuni accenti potrebbero comunque essere errati.
Le parole omografe con accento diverso (*àncora*/*ancòra*, *prìncipi*/*princìpi*) hanno righe separate, ognuna con la propria frequenza, e una delle due è indicata come lettura predefinita. Le frequenze sono in scala Zipf e riflettono l'italiano di oggi, scritto e parlato. Una forma che nessun corpus contiene entra solo se la riportano almeno due lessici (Morph-it! e i due Wiktionary), tranne i verbi con pronomi enclitici (*portàndoglielo*): così il dizionario scende da 16 a 10 MB e perde gli errori di battitura che compaiono in un solo lessico. Gli articoli e i pronomi atoni (*il*, *la*, *un*, *mi*, *si*, *ci*, *ne*…) non sono nel dizionario: non hanno un accento proprio, quindi non fanno rima, e con la loro frequenza scavalcherebbero le rime vere (*si*, *mi*, *ci* prima di *così*).

I dettagli (fonti, fasi, formato del file, correzioni manuali) sono in [`dictionary/README.md`](dictionary/README.md).
Per migliorare la qualità di questo dizionario è consigliabile contribuire al Wikizionario, oppure segnalare gli errori: le correzioni manuali sono in `dictionary/curation/overrides.tsv`.

## Installazione e uso locale

Durante lo sviluppo i file in `web/` (HTML, CSS, SVG, moduli JavaScript e il dizionario `web/parole-accenti-frequenze.csv`, già incluso nel repository) si usano così come sono, senza passaggi di compilazione. Per la pubblicazione si usa `build.py` (vedi [Compilazione per la pubblicazione](#compilazione-per-la-pubblicazione)).

1. Clona questo repository
2. Dalla cartella principale del repository avvia un server locale: `python3 -m http.server 8000` (aprire `index.html` direttamente come file non funziona, perché il dizionario viene scaricato dalla pagina)
3. Apri http://localhost:8000/web/ in un browser
4. Per rigenerare il dizionario:
   - Installa [uv](https://docs.astral.sh/uv/) (installa da solo Python e le dipendenze; non servono pacchetti di sistema)
   - Dalla cartella `dictionary/`, esegui `uv run rimario-build`: scarica le versioni più recenti delle fonti e aggiorna `web/parole-accenti-frequenze.csv`, `web/ATTRIBUTION.md` e il resoconto `dictionary/report.md`
   - Con `uv run rimario-build --offline` il dizionario viene rigenerato usando le fonti già scaricate

### Requisiti del browser

Serve un browser recente che supporti i moduli ES (`<script type="module">`) e le container query CSS: Chrome ed Edge 105 o successivi, Firefox 110 o successivi, Safari 16 o successivi. `Intl.Segmenter` non è più necessario.

### Integrazione

Il rimario è tutto dentro l'elemento `#rimario` di `web/index.html`, compreso tra i commenti `<!-- rimario:begin -->` e `<!-- rimario:end -->`, e si configura con questi attributi:

| Attributo | Significato | Valore predefinito |
|---|---|---|
| `data-dictionary-url` | URL del file CSV del dizionario (gli URL relativi partono dalla pagina) | `parole-accenti-frequenze.csv` |
| `data-attribution-url` | URL della pagina con fonti e licenze del dizionario | `ATTRIBUTION.md` |
| `data-title-suffix` | Testo dopo "Rime con X \| " nel titolo della pagina | il titolo iniziale della pagina |
| `data-dictionary-bytes` | Dimensione del CSV decompresso, per mostrare l'avanzamento del download quando il server lo comprime | nessuno |

Tutto il CSS è limitato a `#rimario` e annulla gli stili del tema che lo ospita, quindi il rimario si può inserire in una pagina esistente (per esempio WordPress) senza conflitti. Se il sito ha un'intestazione fissa in alto, impostane l'altezza nella variabile CSS `--sri-sticky-top` (per esempio `#rimario { --sri-sticky-top: 64px; }`), così le schede dei risultati restano visibili sotto di essa.

### Compilazione per la pubblicazione

Servono Python 3.14 (solo la libreria standard) ed [esbuild](https://esbuild.github.io/) 0.28 nel `PATH`. Dalla cartella principale del repository:

```sh
python3 build.py                     # URL di caricamento: la cartella di WordPress del mese corrente
python3 build.py --upload-base URL   # un'altra cartella, es. https://www.lavisioblog.it/wp-content/uploads/2026/10/
```

La cartella `build/` (ignorata da git) viene cancellata e ricreata a ogni esecuzione; se un controllo fallisce, lo script si ferma con un errore e non lascia nessuna `build/`. Contiene:

- `build/web/`: il sito autonomo. Ogni file tranne `index.html` ha nel nome i primi 10 caratteri del suo sha256 (es. `parole-accenti-frequenze-<hash>.csv`), quindi cambia nome solo quando cambia il contenuto e il browser può tenerlo in cache senza scadenza. Il CSS è minificato; `js/app.js` e i moduli che importa sono riuniti e minificati in un unico `js/app-<hash>.js`. Per provarlo in locale: `python3 -m http.server 8001 --directory build/web`
- `build/wordpress.html`: la versione per L'AvisioBlog, un unico frammento HTML con il CSS incorporato e il JavaScript (lo stesso di `build/web/`) e il logo come data URI
- `build/wordpress-uploads/`: i file da caricare su WordPress, con gli stessi nomi con hash. WordPress non accetta file `.md`, quindi l'attribuzione viene caricata come `ATTRIBUTION-<hash>.txt`, con lo stesso contenuto preceduto da un BOM UTF-8 (il blog serve i file statici senza indicare la codifica, e il testo contiene lettere accentate), quindi con un hash diverso da quello del `.md`

La compilazione imposta `data-dictionary-bytes` in entrambe le versioni e, per il blog, `data-title-suffix` e gli URL assoluti del dizionario e dell'attribuzione. Il tema del blog impone con `!important` alcune proprietà ai pulsanti (colore, maiuscolo, dimensione e peso del carattere, arrotondamento), quindi nella versione per il blog tutte le dichiarazioni del CSS del rimario su quelle proprietà diventano `!important` (l'elenco è `WORDPRESS_IMPORTANT` in `build.py`).

Per pubblicare su WordPress:

1. Carica i file di `build/wordpress-uploads/` da Media › Aggiungi nuovo, non dall'editor della pagina: WordPress mette i file caricati da una pagina nella cartella del mese di quella pagina, e l'URL cambierebbe
2. Controlla che l'URL di ogni file caricato sia esattamente quello stampato da `build.py`; se non lo è, rilancia lo script con `--upload-base` impostato sulla cartella usata da WordPress
3. Incolla il contenuto di `build/wordpress.html` in un blocco "HTML personalizzato" della pagina. Il frammento contiene `<script>` e `<style>`, quindi serve un utente con il permesso `unfiltered_html` (amministratore o editor su un sito singolo)

## Contribuire

Sono benvenuti contributi per migliorare Super Rimario Italiano.

## Licenze

### Codice principale

Il codice principale di Super Rimario Italiano è rilasciato sotto la GNU General Public License v3.0 o successiva (GPL-3.0-or-later).

Super Rimario Italiano è software libero: puoi redistribuirlo e/o modificarlo secondo i termini della GNU General Public License come pubblicata dalla Free Software Foundation, sia la versione 3 della Licenza, sia (a tua scelta) una versione successiva.

Super Rimario Italiano è distribuito nella speranza che sia utile, ma SENZA ALCUNA GARANZIA; senza neppure la garanzia implicita di COMMERCIABILITÀ o IDONEITÀ PER UN PARTICOLARE SCOPO. Vedere la GNU General Public License per maggiori dettagli.

Dovresti aver ricevuto una copia della GNU General Public License insieme a Super Rimario Italiano. In caso contrario, consulta <https://www.gnu.org/licenses/>.

### Dati del dizionario

Il dizionario è generato a partire dalle seguenti fonti, utilizzate secondo le rispettive licenze:

- **Wiktionary inglese e Wikizionario italiano**, progetti della Wikimedia Foundation Inc., un'organizzazione non-profit, con i dati estratti da Kaikki.org tramite wiktextract (Tatu Ylonen, LREC 2022): Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0). Per i dettagli, visita: https://creativecommons.org/licenses/by-sa/4.0/
- **Morph-it!** - Marco Baroni, Eros Zanchetta, Università di Bologna: Creative Commons Attribution-ShareAlike 2.0 (CC BY-SA 2.0) e LGPL. Poiché il sito di Morph-it! blocca i download automatici, l'archivio originale (`morph-it.tgz`, con la licenza `lgpl.txt` e il readme) è ridistribuito senza modifiche in questo repository, in `dictionary/mirror/morphit/`, con la stessa licenza
- **wordfreq** - Robyn Speer: i dati sono rilasciati sotto licenza CC BY-SA 4.0
- **FrequencyWords** - Hermit Dave, liste di frequenza dai sottotitoli di OpenSubtitles 2018: CC BY-SA 4.0
- **Leipzig Corpora Collection** - Università di Lipsia (Goldhahn, Eckart, Quasthoff, LREC 2012), notizie in italiano: Creative Commons Attribution 4.0 (CC BY 4.0)

L'elenco completo, con il testo di attribuzione di ogni fonte, le pubblicazioni da citare e le versioni usate per l'ultima generazione, è in [`web/ATTRIBUTION.md`](web/ATTRIBUTION.md), che va mostrato o collegato ovunque venga usato il dizionario.
