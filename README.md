# Super Rimario Italiano

Super Rimario Italiano è un dizionario di rime online per la lingua italiana. Questo strumento permette di trovare rime, assonanze atone, assonanze semplici e consonanze, ordinandole per frequenza d'uso.

## Versione online

Il rimario è disponibile online su L'AvisioBlog.

## Caratteristiche

- Ricerca rapida di rime, assonanze e consonanze
- Ordinamento dei risultati per frequenza d'uso
- Gestione delle parole omografe come àncora/ancòra

## Generazione del dizionario

Il dizionario utilizzato da Super Rimario Italiano è generato utilizzando diverse fonti:

- Dump XML del Wikizionario italiano
- Lista di frequenze CoLFIS
- Altre liste di parole italiane

Il processo di generazione è gestito dallo script Python `build-dictionary.py`, che combina queste fonti e utilizza `espeak` per determinare gli accenti delle parole quando necessario. Questo significa che alcuni accenti saranno errati.
Per migliorare la qualità di questo dizionario è consigliabile contribuire al Wikizionario.

## Installazione e uso locale

1. Clona questo repository
2. Apri `index.html` in un browser moderno (è necessario un ambiente server)
3. Per rigenerare il dizionario:
   - Installa Python 3.x
   - Installa mwxml `pip install mwxml`
   - Installa espeak sul tuo sistema operativo
   - Scarica i file specificati in cima allo script e posizionali nella directory `input`
   - Esegui `python build-dictionary.py`

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
- [WItalian] - Copyright (c) [1997-2018] [Davide G. M. Salvetti] (Licenza GPL-3+)
- [paroleitaliane] - Copyright (c) [2016] [napolux] (Licenza MIT)
- [scalaWords] by [pazqo]

Il testo completo delle licenze per queste fonti è incluso nella cartella 'licenses' di questo progetto.
