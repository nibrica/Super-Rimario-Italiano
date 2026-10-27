# Super Rimario Italiano

Super Rimario Italiano è un dizionario di rime online per la lingua italiana. Questo strumento permette di trovare rime, assonanze atone, assonanze semplici e consonanze, ordinandole per frequenza d'uso.

## Versione online

Il rimario è disponibile online su L'AvisioBlog all'indirizzo https://www.lavisioblog.it/super-rimario-italiano

## Caratteristiche

- Ricerca rapida di rime, assonanze e consonanze
- Ordinamento dei risultati per frequenza d'uso
- Gestione delle parole omografe come àncora/ancòra

## Generazione del dizionario

Il dizionario utilizzato da Super Rimario Italiano (`dictionary/out/parole-accenti-frequenze.csv`) è generato combinando diverse fonti, tutte scaricate automaticamente nella loro versione più recente:

- Le voci italiane del Wiktionary inglese e del Wikizionario italiano, già estratte da [Kaikki.org](https://kaikki.org/) (wiktextract): accenti, pronuncia IPA, sillabazione e coniugazioni
- [Morph-it!](https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it), con circa 505.000 forme flesse dell'italiano
- Le frequenze d'uso di [wordfreq](https://github.com/rspeer/wordfreq), dei sottotitoli di OpenSubtitles ([FrequencyWords](https://github.com/hermitdave/FrequencyWords)) e delle notizie recenti della [Leipzig Corpora Collection](https://wortschatz.uni-leipzig.de/en/download/Italian)

Il processo è gestito dal pacchetto Python in `dictionary/`, che non usa più `espeak`, il dump XML del Wikizionario né la lista CoLFIS. L'accento delle parole che nessuna fonte riporta viene ricavato dalle altre forme dello stesso verbo o della stessa parola (*càpito* → *càpitano*, *dìmmelo*) e, solo in ultima istanza, stimato da un modello addestrato sulle parole note: queste parole sono segnalate nel dizionario, e alcuni accenti potrebbero comunque essere errati.
Le parole omografe con accento diverso (*àncora*/*ancòra*, *prìncipi*/*princìpi*) hanno righe separate, ognuna con la propria frequenza, e una delle due è indicata come lettura predefinita. Le frequenze sono in scala Zipf e riflettono l'italiano di oggi, scritto e parlato.

I dettagli (fonti, fasi, formato del file, correzioni manuali) sono in [`dictionary/README.md`](dictionary/README.md).
Per migliorare la qualità di questo dizionario è consigliabile contribuire al Wikizionario, oppure segnalare gli errori: le correzioni manuali sono in `dictionary/curation/overrides.tsv`.

## Installazione e uso locale

1. Clona questo repository
2. Apri `index.html` in un browser moderno (è necessario un ambiente server)
3. Per rigenerare il dizionario:
   - Installa [uv](https://docs.astral.sh/uv/) (installa da solo Python e le dipendenze; non servono pacchetti di sistema)
   - Dalla cartella `dictionary/`, esegui `uv run rimario-build`: scarica le versioni più recenti delle fonti e genera `dictionary/out/`
   - Con `uv run rimario-build --offline` il dizionario viene rigenerato usando le fonti già scaricate

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

L'elenco completo, con il testo di attribuzione di ogni fonte, le pubblicazioni da citare e le versioni usate per l'ultima generazione, è in [`dictionary/out/ATTRIBUTION.md`](dictionary/out/ATTRIBUTION.md), che va mostrato o collegato ovunque venga usato il dizionario.
