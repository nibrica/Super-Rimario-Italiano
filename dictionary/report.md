# Dictionary QA report

Built: 2026-10-27

## Sources

| source | status | version | sha256 | size | fetched | url |
|---|---|---|---|---|---|---|
| kaikki_en | unchanged | "6addda20-4918ce8" | 7ac16b2fb860 | 76647656 | 2026-10-27T02:04:11Z | https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl.gz |
| kaikki_it | unchanged | "6addbc8a-29d17f3" | 1e8e9edd2b11 | 43849715 | 2026-10-27T02:04:11Z | https://kaikki.org/dictionary/downloads/it/it-extract.jsonl.gz |
| leipzig_news | unchanged | "f9380fc-62df65df7f580" | 90ed9f839c50 | 261325052 | 2026-10-27T02:04:12Z | https://downloads.wortschatz-leipzig.de/corpora/ita_news_2024_1M.tar.gz |
| morphit | unchanged | Thu, 03 May 2018 10:51:58 GMT | b137343dc095 | 2617548 | 2026-10-27T02:04:11Z | https://docs.sslmit.unibo.it/lib/exe/fetch.php?media=resources:morph-it.tgz |
| opensubtitles | unchanged | "a1b4df0d31f9783eb198ce2e2575d4061fc39adadf788f9a564422fe04d8a759" | b23b0c6a3f59 | 9677728 | 2026-10-27T02:04:12Z | https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/it/it_full.txt |
| wordfreq | unchanged | 3.1.1 |  |  | 2026-10-27T02:04:11Z | https://pypi.org/project/wordfreq/3.1.1/ |

## Output

|  |  |
|---|---|
| file | parole-accenti-frequenze.csv |
| rows | 581,808 |
| distinct words | 578,797 |
| size | 10,034,933 bytes |
| gzipped | 2,906,171 bytes |
| sha256 | `1954472e86af5a604907bdc1ce82c421ccf2e00bcb66791dc2d275e7fb4ce1e2` |

## Row counts

**By tier**

| tier | rows |
|---|---|
| attested | 443978 |
| predicted | 15273 |
| propagated | 122557 |

**By supporting source** (a row counts once per source)

| source | rows |
|---|---|
| kaikki_en | 409784 |
| kaikki_it | 102584 |
| model | 15273 |
| morphit | 17654 |
| paradigm.enclitic | 61245 |
| paradigm.nominal | 33059 |
| paradigm.single_vowel | 154 |
| paradigm.suffix | 10960 |
| paradigm.verb_ending | 30612 |
| paradigm.verb_rhizotonic | 1635 |

**By flag**

| flag | rows |
|---|---|
| none | 545375 |
| 1 non-default | 3011 |
| 2 predicted | 15273 |
| 4 vulgar | 2268 |
| 8 archaic | 11630 |
| 16 proper | 8088 |

**By Zipf band**

| zipf | rows |
|---|---|
| < 1 | 419129 |
| 1–2 | 83112 |
| 2–3 | 51946 |
| 3–4 | 21563 |
| 4–5 | 5261 |
| 5–6 | 705 |
| ≥ 6 | 92 |

**Excluded lexicon forms by reason**

| reason | forms |
|---|---|
| abbreviation | 280 |
| chars | 4059 |
| few_lexicons | 317529 |
| loanword | 1651 |
| low_confidence | 14813 |
| misspelling | 242 |
| proper_no_freq | 2298 |
| proper_no_kaikki | 223 |

## Gold accuracy

Accuracy: **97.41%** on 116 gold rows (3 misses).

| gold | default | reason | output | note |
|---|---|---|---|---|
| rùbrica |  | missing reading | rubrìca | rùbrica (standard stress (DOP)) |
| persuàdere |  | missing reading | persuadère | persuàdere (standard stress (DOP)) |
| guaìna |  | missing reading | guàina | guaìna (standard stress (DOP)) |

## Model

| metric | value |
|---|---|
| n_train | 300000 |
| cv_accuracy | 0.988 |
| cv_accuracy_confident | 0.997 |
| coverage_confident | 0.965 |
| n_cv | 100487 |
| temperature | 2.286 |
| n_cv_noun | 9443 |
| cv_accuracy_noun | 0.955 |
| cv_accuracy_confident_noun | 0.986 |
| coverage_confident_noun | 0.872 |
| n_cv_adj | 7910 |
| cv_accuracy_adj | 0.983 |
| cv_accuracy_confident_adj | 0.994 |
| coverage_confident_adj | 0.946 |
| n_cv_verb | 81514 |
| cv_accuracy_verb | 0.994 |
| cv_accuracy_confident_verb | 0.999 |
| coverage_confident_verb | 0.981 |
| n_cv_name | 835 |
| cv_accuracy_name | 0.893 |
| cv_accuracy_confident_name | 0.981 |
| coverage_confident_name | 0.626 |

## Frequency pairs

Agreement: **100.00%** on 57 pairs (0 misses).

## Diff against the previous build

Previous CSV: 899,429 rows, 896,347 words.

**Forms added:** 0 (most frequent first)

_none_

**Forms removed:** 317,550 (most frequent first)

| form | old zipf×100 |
|---|---|
| aaleniàna | 32 |
| aaleniàne | 32 |
| aaleniàni | 32 |
| aaleniàno | 32 |
| àbache | 32 |
| abachìste | 32 |
| abacìsti | 32 |
| abadìte | 32 |
| abadìti | 32 |
| abalienànti | 32 |
| abalienaziòni | 32 |
| abandonàndosi | 32 |
| abandonàntesi | 32 |
| abandonàntisi | 32 |
| abandonàrti | 32 |
| abandonàtasi | 32 |
| abandonàtesi | 32 |
| abandonàtevi | 32 |
| abandonàtisi | 32 |
| abandonàtosi | 32 |
| abandoniàmoci | 32 |
| abandonwàri (2) | 32 |
| abantìco | 32 |
| abapicàle | 32 |
| abaptìsta | 32 |
| abaptìsti | 32 |
| abarognosìa | 32 |
| abarognosìe | 32 |
| abàrra (8) | 32 |
| abarrài (8) | 32 |
| abarràmmo (8) | 32 |
| abarràndo (8) | 32 |
| abarràndosi (8) | 32 |
| abàrrano (8) | 32 |
| abarrànte (8) | 32 |
| abarràntesi (8) | 32 |
| abarràre (8) | 32 |
| abarràrono (8) | 32 |
| abarràrsi (8) | 32 |
| abarràsse (8) | 32 |
| abarràssero (8) | 32 |
| abarràssi (8) | 32 |
| abarràssimo (8) | 32 |
| abarràste (8) | 32 |
| abarràsti (8) | 32 |
| abarràte (8) | 32 |
| abarràtevi (8) | 32 |
| abàrrati (8) | 32 |
| abarràto (8) | 32 |
| abarràtosi (8) | 32 |

**Stress changed:** 0 forms (set of stressed positions differs)

_none_

**Default reading changed:** 0 forms

_none_

## Stress conflicts between sources

403 conflicts (most frequent forms first).

| form | lemma | pos | readings | zipf |
|---|---|---|---|---|
| vengono | venire | verb | kaikki_en:vèngono kaikki_it:vengòno | 5.19 |
| luogo | luogo | noun | kaikki_en:luògo kaikki_it:lùogo | 5.18 |
| credere | credere | verb | kaikki_en:crédere kaikki_en:credére kaikki_it:crèdere | 4.91 |
| ipotesi | ipoteso | noun | kaikki_en:ipotési kaikki_it:ipòtesi | 4.65 |
| mettendo | mettere | verb | kaikki_en:mettèndo kaikki_it:mèttendo | 4.58 |
| tragedia | tragedia | noun | kaikki_en:tragèdia kaikki_en:tragedìa kaikki_it:tragèdia | 4.54 |
| tantissimo | tanto | adj | kaikki_en:tantìssimo kaikki_it:tantissìmo | 4.50 |
| manager | manager | noun | kaikki_en:mànager kaikki_it:manàger | 4.49 |
| chiamano | chiamare | verb | kaikki_en:chiàmano kaikki_it:chiamàno | 4.44 |
| capita | capito | adj | kaikki_en:capìta kaikki_it:càpita | 4.42 |
| rappresentano | rappresentare | verb | kaikki_en:rappresèntano kaikki_it:rappresentàno | 4.31 |
| portale | portale | phrase | kaikki_en:portàle kaikki_it:pórtale | 4.30 |
| riguardano | riguardare | verb | kaikki_en:riguàrdano kaikki_it:riguardàno | 4.27 |
| circuito | circuito | adj | kaikki_en:circùito kaikki_it:circuìto | 4.25 |
| siccome | siccome | conj | kaikki_en:sìccome kaikki_en:siccóme | 4.23 |
| contano | contare | verb | kaikki_en:cóntano kaikki_it:contàno | 4.17 |
| volevamo | volere | verb | kaikki_en:volévamo kaikki_en:volevàmo | 4.13 |
| bottiglie | bottiglia | noun | kaikki_en:bottìglie kaikki_it:bòttiglie | 4.10 |
| calcoli | calcolo | noun | kaikki_en:càlcoli kaikki_it:calcòli | 3.99 |
| girano | girare | verb | kaikki_en:gìrano kaikki_it:giràno | 3.89 |
| pavia | pavia | noun | kaikki_en:pavìa kaikki_it:pàvia | 3.88 |
| libano | libano | noun | kaikki_en:lìbano kaikki_it:libàno | 3.87 |
| brividi | brivido | noun | kaikki_en:brìvidi kaikki_it:brivìdi | 3.87 |
| pakistan | pakistan | name | kaikki_en:pàkistan kaikki_en:pakistàn kaikki_it:pakistàn | 3.79 |
| amelia | amelia | noun | kaikki_en:amèlia kaikki_it:amelìa | 3.72 |
| intimi | intimo | adj | kaikki_en:ìntimi kaikki_it:intìmi | 3.72 |
| intimi | intimo | noun | kaikki_en:ìntimi kaikki_it:intìmi | 3.72 |
| tragedie | tragedia | noun | kaikki_en:tragèdie kaikki_en:tragedìe kaikki_it:tragèdie | 3.69 |
| temono | temere | verb | kaikki_en:témono kaikki_it:temòno | 3.69 |
| pandemia | pandemia | noun | kaikki_en:pandèmia kaikki_en:pandemìa kaikki_it:pandemìa | 3.68 |
| nascondendo | nascondere | verb | kaikki_en:nascondèndo kaikki_it:nascòndendo | 3.68 |
| tirano | tirare | verb | kaikki_en:tìrano kaikki_it:tiràno | 3.67 |
| spoiler | spoiler | noun | kaikki_en:spòiler kaikki_it:spoìler | 3.64 |
| indossano | indossare | verb | kaikki_en:indòssano kaikki_it:indossàno | 3.61 |
| colon | colon | noun | kaikki_en:còlon kaikki_en:colòn kaikki_it:còlon | 3.57 |
| innovative | innovativo | adj | kaikki_en:innovatìve kaikki_it:innovàtive | 3.56 |
| piovere | piovere | verb | kaikki_en:piòvere kaikki_en:piovére kaikki_it:piòvere | 3.55 |
| mania | mania | noun | kaikki_en:mània kaikki_en:manìa kaikki_it:manìa morphit:manìa | 3.54 |
| irlandesi | irlandese | adj | kaikki_en:irlandési kaikki_it:irlàndesi | 3.52 |
| irlandesi | irlandese | noun | kaikki_en:irlandési kaikki_it:irlàndesi | 3.52 |
| costringendo | costringere | verb | kaikki_en:costringèndo kaikki_it:costrìngendo | 3.52 |
| diffondendo | diffondere | verb | kaikki_en:diffondèndo kaikki_it:diffòndendo | 3.52 |
| briciole | briciola | noun | kaikki_en:bricìole kaikki_it:briciòle | 3.48 |
| karaoke | karaoke | noun | kaikki_en:karàoke kaikki_en:karaòke kaikki_it:karaòke | 3.47 |
| promuovendo | promuovere | verb | kaikki_en:promuovèndo kaikki_it:promuòvendo | 3.47 |
| ucraini | ucraino | adj | kaikki_en:ucràini kaikki_it:ucraìni | 3.46 |
| ucraini | ucraino | noun | kaikki_en:ucràini kaikki_it:ucraìni | 3.46 |
| danesi | danese | adj | kaikki_en:danési kaikki_it:dànesi | 3.44 |
| bangkok | bangkok | name | kaikki_en:bàngkok kaikki_en:bangkòk kaikki_it:bangkòk | 3.40 |
| iraniani | iraniano | adj | kaikki_en:iraniàni kaikki_it:ìraniani | 3.40 |

## Homographs split 50/50

365 homographs split 50/50 (override candidates).

| form | readings | reason | zipf |
|---|---|---|---|
| leggere | lèggere, leggère | no lemma unique to each row | 4.90 |
| internet | ìnternet, internèt | same lemmas | 4.78 |
| separati | sèparati, sepàrati, separàti | same lemmas (participle group) | 4.13 |
| console | cònsole, consòle | same lemmas | 4.11 |
| tradito | tràdito, tradìto | no lemma unique to each row | 4.11 |
| potevamo | potèvamo, potevàmo | same lemmas | 4.09 |
| iraq | ìraq, iràq | same lemmas | 4.03 |
| costato | còstato, costàto | no lemma unique to each row | 3.91 |
| elevati | èlevati, elèvati, elevàti | same lemmas (participle group) | 3.86 |
| magazine | màgazine, magazìne | same lemmas | 3.84 |
| vladimir | vlàdimir, vladìmir | same lemmas | 3.82 |
| facevamo | facèvamo, facevàmo | same lemmas | 3.76 |
| incubi | ìncubi, incùbi | no lemma unique to each row | 3.75 |
| etero | ètero, etèro | same lemmas | 3.68 |
| ambiti | àmbiti, ambìti | no lemma unique to each row | 3.67 |
| carmine | càrmine, carmìne | same lemmas | 3.67 |
| tradita | tràdita, tradìta | no lemma unique to each row | 3.60 |
| conseguito | consèguito, conseguìto | no lemma unique to each row | 3.59 |
| balia | bàlia, balìa | same lemmas | 3.56 |
| lasciatelo | làsciatelo, lasciàtelo | same lemmas | 3.55 |
| elia | èlia, elìa | same lemmas | 3.55 |
| wikipedia | wikipèdia, wikipedìa | same lemmas | 3.51 |
| fieno | fìeno, fièno | no lemma unique to each row | 3.40 |
| spiccioli | spìccioli, spicciòli | no lemma unique to each row | 3.39 |
| retina | rètina, retìna | no lemma unique to each row | 3.37 |
| cesareo | cesàreo, cesarèo | same lemmas | 3.36 |
| fatiche | fàtiche, fatìche | no lemma unique to each row | 3.33 |
| kosovo | kòsovo, kosòvo | same lemmas | 3.32 |
| nocciolo | nòcciolo, nocciòlo | same lemmas | 3.31 |
| traditi | tràditi, tradìti | no lemma unique to each row | 3.29 |
| ultras | ùltras, ultràs | same lemmas | 3.29 |
| formica | fòrmica, formìca | no lemma unique to each row | 3.22 |
| amnistia | amnìstia, amnistìa | no lemma unique to each row | 3.22 |
| helsinki | hèlsinki, helsìnki | same lemmas | 3.19 |
| irrita | ìrrita, irrìta | no lemma unique to each row | 3.17 |
| decimi | dècimi, decìmi | no lemma unique to each row | 3.15 |
| bevute | bèvute, bevùte | no lemma unique to each row | 3.15 |
| vermont | vèrmont, vermònt | same lemmas | 3.14 |
| edema | èdema, edèma | same lemmas | 3.10 |
| fuor | fùor, fuòr | same lemmas | 3.09 |
| monitora | monìtora, monitòra | same lemmas | 3.07 |
| surplus | sùrplus, surplùs | same lemmas | 3.02 |
| spicciolo | spìcciolo, spicciòlo | no lemma unique to each row | 3.01 |
| monotono | monòtono, monotòno | same lemmas | 2.99 |
| camerun | càmerun, camerùn | same lemmas | 2.99 |
| avaro | àvaro, avàro | same lemmas | 2.99 |
| uzbekistan | uzbèkistan, uzbekistàn | same lemmas | 2.96 |
| shogun | shògun, shogùn | same lemmas | 2.95 |
| lettone | lèttone, lettòne | same lemmas | 2.92 |
| frullati | frùllati, frullàti | no lemma unique to each row | 2.91 |

## Largest frequency disagreements

The 1,455 largest gaps between a down-weighted source estimate and the other sources (the merge keeps at most 2,000), largest first.

| form | source | zipf source | zipf others | weight factor |
|---|---|---|---|---|
| calciomercato | opensubtitles | 0.107 | 3.826 | 0.250 |
| giampaolo | opensubtitles | 0.107 | 3.574 | 0.250 |
| bergoglio | opensubtitles | 0.107 | 3.456 | 0.250 |
| piaggio | opensubtitles | 0.107 | 3.439 | 0.250 |
| pisana | opensubtitles | 0.107 | 3.429 | 0.250 |
| casaleggio | opensubtitles | 0.107 | 3.397 | 0.250 |
| estense | opensubtitles | 0.107 | 3.389 | 0.250 |
| conegliano | opensubtitles | 0.107 | 3.371 | 0.250 |
| accise | opensubtitles | 0.107 | 3.366 | 0.250 |
| gdf | opensubtitles | 0.107 | 3.362 | 0.250 |
| oristano | opensubtitles | 0.107 | 3.320 | 0.250 |
| parmense | opensubtitles | 0.107 | 3.316 | 0.250 |
| zingaretti | opensubtitles | 0.107 | 3.310 | 0.250 |
| precariato | opensubtitles | 0.107 | 3.310 | 0.250 |
| icardi | opensubtitles | 0.107 | 3.282 | 0.250 |
| partenopea | opensubtitles | 0.107 | 3.274 | 0.250 |
| viviani | opensubtitles | 0.107 | 3.272 | 0.250 |
| friulani | opensubtitles | 0.107 | 3.266 | 0.250 |
| pedemontana | opensubtitles | 0.107 | 3.256 | 0.250 |
| foibe | opensubtitles | 0.107 | 3.249 | 0.250 |
| fumagalli | opensubtitles | 0.107 | 3.249 | 0.250 |
| montella | opensubtitles | 0.107 | 3.246 | 0.250 |
| garfagnana | opensubtitles | 0.107 | 3.237 | 0.250 |
| jesolo | opensubtitles | 0.107 | 3.233 | 0.250 |
| sangro | opensubtitles | 0.107 | 3.230 | 0.250 |
| raiuno | opensubtitles | 0.107 | 3.225 | 0.250 |
| appiano | opensubtitles | 0.107 | 3.219 | 0.250 |
| verbania | opensubtitles | 0.107 | 3.216 | 0.250 |
| vicentino | opensubtitles | 0.107 | 3.198 | 0.250 |
| castiglioni | opensubtitles | 0.107 | 3.191 | 0.250 |
| giulianova | opensubtitles | 0.107 | 3.186 | 0.250 |
| bormio | opensubtitles | 0.107 | 3.181 | 0.250 |
| facchinetti | opensubtitles | 0.107 | 3.155 | 0.250 |
| canavese | opensubtitles | 0.107 | 3.155 | 0.250 |
| arcore | opensubtitles | 0.107 | 3.155 | 0.250 |
| reggina | opensubtitles | 0.107 | 3.151 | 0.250 |
| cremonini | opensubtitles | 0.107 | 3.143 | 0.250 |
| piacentino | opensubtitles | 0.107 | 3.142 | 0.250 |
| aquilano | opensubtitles | 0.107 | 3.141 | 0.250 |
| chieri | opensubtitles | 0.107 | 3.134 | 0.250 |
| estensi | opensubtitles | 0.107 | 3.129 | 0.250 |
| renziani | opensubtitles | 0.107 | 3.120 | 0.250 |
| bankitalia | opensubtitles | 0.107 | 3.104 | 0.250 |
| eucaristica | opensubtitles | 0.107 | 3.104 | 0.250 |
| europeista | opensubtitles | 0.107 | 3.095 | 0.250 |
| effettuazione | opensubtitles | 0.107 | 3.092 | 0.250 |
| toninelli | opensubtitles | 0.107 | 3.092 | 0.250 |
| quirico | opensubtitles | 0.107 | 3.086 | 0.250 |
| obbligatorietà | opensubtitles | 0.107 | 3.083 | 0.250 |
| tenco | opensubtitles | 0.107 | 3.068 | 0.250 |

## Low-confidence predictions left out

14,917 predictions (14,848 forms) were below the confidence threshold of their POS (adj 0.90, name 0.97, noun 0.90, verb 0.90; any other POS 0.90) and were not shipped; 14,813 of those forms have no other reading and are left out (most frequent first).

| prediction | confidence | zipf |
|---|---|---|
| l | 0.000 | 6.60 |
| d | 0.000 | 5.69 |
| c | 0.000 | 5.65 |
| s | 0.000 | 5.21 |
| tv | 0.000 | 5.17 |
| n | 0.000 | 4.96 |
| b | 0.000 | 4.89 |
| teàm | 0.823 | 4.80 |
| m | 0.000 | 4.79 |
| km | 0.000 | 4.78 |
| x | 0.000 | 4.78 |
| leadèr | 0.384 | 4.78 |
| t | 0.000 | 4.71 |
| goògle | 0.647 | 4.63 |
| weekènd | 0.826 | 4.62 |
| jàmes | 0.727 | 4.60 |
| pd | 0.000 | 4.57 |
| àlex | 0.954 | 4.53 |
| okày | 0.639 | 4.51 |
| streèt | 0.527 | 4.51 |
| washìngton | 0.930 | 4.50 |
| g | 0.000 | 4.47 |
| r | 0.000 | 4.44 |
| p | 0.000 | 4.44 |
| dàniel | 0.463 | 4.43 |
| v | 0.000 | 4.42 |
| thòmas | 0.667 | 4.41 |
| àngeles | 0.561 | 4.41 |
| sàrah | 0.768 | 4.40 |
| oùt | 0.623 | 4.40 |
| loùis | 0.628 | 4.38 |
| grèen | 0.813 | 4.38 |
| businèss | 0.476 | 4.38 |
| chàrles | 0.964 | 4.37 |
| prìvacy | 0.592 | 4.37 |
| f | 0.000 | 4.37 |
| williàm | 0.506 | 4.36 |
| desìgn | 0.566 | 4.36 |
| my | 0.000 | 4.35 |
| taylòr | 0.527 | 4.34 |
| kèvin | 0.749 | 4.34 |
| richàrd | 0.725 | 4.32 |
| pc | 0.000 | 4.32 |
| strèaming | 0.747 | 4.31 |
| leàgue | 0.879 | 4.30 |
| mm | 0.000 | 4.30 |
| chàrlie | 0.962 | 4.30 |
| emàil | 0.882 | 4.29 |
| netwòrk | 0.834 | 4.29 |
| òpen | 0.896 | 4.28 |

## Most frequent forms without attested stress

137,156 forms have only propagated or predicted stress; the 200 most frequent (work through these first):

| # | form | tier | zipf | lemmas |
|---|---|---|---|---|
| 1 | ì | propagated | 6.86 | i, il, la, le, lo |
| 2 | dèl | propagated | 6.85 | del |
| 3 | dèlle | propagated | 6.37 | della |
| 4 | nèlla | propagated | 6.23 | nel, nella, nelle |
| 5 | dàl | propagated | 6.19 | dal |
| 6 | sùl | propagated | 6.13 | sul |
| 7 | dèllo | propagated | 5.54 | del, dello |
| 8 | sùi | predicted | 5.52 | sui, sul |
| 9 | nègli | predicted | 5.50 | negli, nel, nelle |
| 10 | sùlle | propagated | 5.48 | sulla |
| 11 | nèllo | propagated | 5.22 | nel, nelle, nello |
| 12 | unìti | propagated | 5.10 | unire, unito |
| 13 | èh | propagated | 4.99 | eh |
| 14 | onlìne | predicted | 4.89 | online |
| 15 | stòrie | propagated | 4.88 | storia |
| 16 | sùgli | predicted | 4.87 | sugli, sul |
| 17 | còi | predicted | 4.77 | coi, col |
| 18 | dottòr | propagated | 4.70 | dottore |
| 19 | ricèrche | propagated | 4.64 | ricerca |
| 20 | còlpi | propagated | 4.63 | colpo |
| 21 | pàlle | propagated | 4.54 | palla |
| 22 | àfrica | propagated | 4.53 | africo |
| 23 | tàl | propagated | 4.50 | tal, tale |
| 24 | vedèrlo | propagated | 4.49 | vedere |
| 25 | scientìfica | propagated | 4.47 | scientifico |
| 26 | màl | propagated | 4.46 | mal, male |
| 27 | potèri | propagated | 4.45 | potere |
| 28 | ìa | predicted | 4.44 | ia |
| 29 | èmma | predicted | 4.44 | emma |
| 30 | avvocàti | propagated | 4.43 | avvocato |
| 31 | giornàte | propagated | 4.41 | giornata |
| 32 | crìtiche | propagated | 4.38 | critica, critico |
| 33 | parlàrne | propagated | 4.38 | parlare |
| 34 | màil | predicted | 4.38 | mail |
| 35 | lìve | propagated | 4.38 | live |
| 36 | iniziàta | propagated | 4.37 | iniziare, iniziato |
| 37 | partecipànti | propagated | 4.34 | partecipante, partecipare |
| 38 | professòr | propagated | 4.34 | professore |
| 39 | assolùta | propagated | 4.31 | assoluto |
| 40 | leggèra | propagated | 4.31 | leggere, leggero |
| 41 | ucràina | propagated | 4.29 | ucraino |
| 42 | crìmini | propagated | 4.29 | crimine |
| 43 | entràti | propagated | 4.28 | entrare |
| 44 | califòrnia | propagated | 4.27 | californio |
| 45 | olimpìadi | propagated | 4.27 | olimpiade |
| 46 | colpìta | propagated | 4.27 | colpire, colpito |
| 47 | lìngue | propagated | 4.27 | lingua |
| 48 | intenziòni | propagated | 4.26 | intenzione |
| 49 | fì | propagated | 4.26 | fio |
| 50 | vedèrla | propagated | 4.25 | vedere |
| 51 | avèrmi | propagated | 4.22 | avere |
| 52 | pèrdite | propagated | 4.20 | perdita |
| 53 | aiutàrti | propagated | 4.19 | aiutare |
| 54 | occupàta | propagated | 4.18 | occupare, occupato |
| 55 | scienziàti | propagated | 4.18 | scienziato |
| 56 | vòn | propagated | 4.18 | von |
| 57 | tantìssimi | propagated | 4.16 | tanto |
| 58 | energìe | propagated | 4.16 | energia |
| 59 | iphòne | propagated | 4.16 | iphone |
| 60 | preoccupàrti | propagated | 4.15 | preoccupare |
| 61 | mònica | propagated | 4.15 | monico |
| 62 | padròni | propagated | 4.14 | padrone |
| 63 | chiàcchiere | propagated | 4.14 | chiacchiera |
| 64 | trovàrlo | propagated | 4.12 | trovare |
| 65 | relatìve | propagated | 4.12 | relativo |
| 66 | costruìta | propagated | 4.12 | costruire, costruito |
| 67 | requisìti | propagated | 4.11 | requisire, requisito |
| 68 | tètte | propagated | 4.11 | tetta |
| 69 | bottìglie | propagated | 4.10 | bottiglia |
| 70 | portàrlo | propagated | 4.10 | portare |
| 71 | prènderlo | propagated | 4.10 | prendere |
| 72 | àlan | propagated | 4.10 | alare |
| 73 | dìgli | propagated | 4.10 | dicere, dire |
| 74 | tantìssime | propagated | 4.09 | tanto |
| 75 | versiòni | propagated | 4.09 | versione |
| 76 | pressiòni | propagated | 4.09 | pressione |
| 77 | potèrlo | propagated | 4.09 | poter, potere |
| 78 | abbandonàta | propagated | 4.08 | abbandonare, abbandonato |
| 79 | catène | propagated | 4.08 | catena |
| 80 | nìna | predicted | 4.08 | nina |
| 81 | futùri | propagated | 4.08 | futuro |
| 82 | vedèrti | propagated | 4.08 | vedere |
| 83 | matèrie | propagated | 4.07 | materia |
| 84 | realizzàta | propagated | 4.07 | realizzare, realizzato |
| 85 | nà | propagated | 4.07 | na |
| 86 | seràte | propagated | 4.07 | serata |
| 87 | sentìrmi | propagated | 4.06 | sentire |
| 88 | iscrìtti | propagated | 4.06 | iscritto, iscrivere |
| 89 | riguardànti | propagated | 4.06 | riguardante, riguardare |
| 90 | pòllici | propagated | 4.06 | pollice |
| 91 | ùltra | predicted | 4.05 | ultra |
| 92 | lìne | propagated | 4.05 | lino |
| 93 | appartamènti | propagated | 4.05 | appartamento |
| 94 | dàmmi | propagated | 4.04 | dare |
| 95 | registràta | propagated | 4.04 | registrare, registrato |
| 96 | unìta | propagated | 4.04 | unire, unito |
| 97 | quàrti | propagated | 4.03 | quarto |
| 98 | teorìe | propagated | 4.03 | teoria |
| 99 | pà | propagated | 4.02 | papà |
| 100 | prèndermi | propagated | 4.01 | prendere |
| 101 | fantàstici | propagated | 4.01 | fantastico |
| 102 | avèrti | propagated | 4.00 | avere |
| 103 | aiutàrci | propagated | 4.00 | aiutare |
| 104 | sapèrne | propagated | 4.00 | sapere |
| 105 | fantàsmi | propagated | 4.00 | fantasma |
| 106 | dròni | propagated | 4.00 | drone |
| 107 | prèstiti | propagated | 4.00 | prestito |
| 108 | significatìva | propagated | 3.99 | significativo |
| 109 | rènderlo | propagated | 3.99 | rendere |
| 110 | lasciàrlo | propagated | 3.99 | lasciare |
| 111 | fissàta | propagated | 3.99 | fissare, fissato |
| 112 | ùsb | propagated | 3.98 | usb |
| 113 | aiutàrla | propagated | 3.98 | aiutare |
| 114 | amànda | predicted | 3.98 | amanda |
| 115 | emissiòni | propagated | 3.98 | emissione |
| 116 | nucleàri | propagated | 3.97 | nucleare |
| 117 | mèle | propagated | 3.97 | mela, melo |
| 118 | tenèrlo | propagated | 3.97 | tenere |
| 119 | èssermi | propagated | 3.97 | essere |
| 120 | ritrovàta | propagated | 3.97 | ritrovare, ritrovato |
| 121 | trasferìti | propagated | 3.96 | trasferire, trasferito |
| 122 | concrète | propagated | 3.96 | concreto |
| 123 | approvàta | propagated | 3.96 | approvare |
| 124 | ricevùte | propagated | 3.96 | ricevere, ricevuta |
| 125 | còrde | propagated | 3.96 | corda |
| 126 | rì | propagated | 3.95 | rio |
| 127 | làsciami | propagated | 3.94 | lasciare |
| 128 | aiutàrlo | propagated | 3.94 | aiutare |
| 129 | portàrla | propagated | 3.94 | portare |
| 130 | quartièr | propagated | 3.94 | quartiere |
| 131 | usàrlo | propagated | 3.94 | usare |
| 132 | capìrlo | propagated | 3.94 | capire |
| 133 | rubàta | propagated | 3.93 | rubare, rubato |
| 134 | aiutàrmi | propagated | 3.93 | aiutare |
| 135 | potèrsi | propagated | 3.93 | poter, potere |
| 136 | sconosciùta | propagated | 3.93 | sconoscere, sconosciuto |
| 137 | mèga | predicted | 3.92 | mega |
| 138 | deputàti | propagated | 3.92 | deputare, deputato |
| 139 | condòtti | propagated | 3.92 | condotto, condurre |
| 140 | chièdermi | propagated | 3.91 | chiedere |
| 141 | ascòltami | propagated | 3.91 | ascoltare |
| 142 | patatìne | propagated | 3.91 | patatina |
| 143 | màra | predicted | 3.91 | mara |
| 144 | sentìrti | propagated | 3.91 | sentire |
| 145 | riportàta | propagated | 3.91 | riportare |
| 146 | màschere | propagated | 3.90 | maschera |
| 147 | uccìderlo | propagated | 3.90 | uccidere |
| 148 | spìriti | propagated | 3.90 | spirito |
| 149 | vedèrli | propagated | 3.90 | vedere |
| 150 | riflettòri | propagated | 3.90 | riflettore |
| 151 | sòmme | propagated | 3.90 | somma, sommo |
| 152 | spaventàta | propagated | 3.90 | spaventare, spaventato |
| 153 | pùb | propagated | 3.90 | pub |
| 154 | causàta | propagated | 3.89 | causare |
| 155 | universitàri | propagated | 3.89 | universitario |
| 156 | scoprìrlo | propagated | 3.89 | scoprire |
| 157 | collegàta | propagated | 3.89 | collegare, collegato |
| 158 | prènderla | propagated | 3.88 | prendere |
| 159 | ràp | propagated | 3.88 | rap |
| 160 | drìve | propagated | 3.88 | drive |
| 161 | crèdimi | propagated | 3.88 | credere |
| 162 | nascòste | propagated | 3.88 | nascondere, nascosto |
| 163 | lontàne | propagated | 3.88 | lontano |
| 164 | universitària | propagated | 3.87 | universitario |
| 165 | significatìvi | propagated | 3.87 | significativo |
| 166 | fottùta | propagated | 3.87 | fottere, fottuto |
| 167 | gestìta | propagated | 3.87 | gestire |
| 168 | brìvidi | propagated | 3.87 | brivido |
| 169 | scusàtemi | propagated | 3.86 | scusare |
| 170 | guàrdami | propagated | 3.86 | guardare |
| 171 | tìzi | propagated | 3.86 | tizio |
| 172 | tarìffe | propagated | 3.85 | tariffa |
| 173 | rilevànti | propagated | 3.85 | rilevante, rilevare |
| 174 | succèssa | propagated | 3.85 | succedere |
| 175 | càpitan | propagated | 3.85 | capitare |
| 176 | lasciàrti | propagated | 3.84 | lasciare |
| 177 | bìrre | propagated | 3.84 | birra |
| 178 | contribuènti | propagated | 3.84 | contribuente, contribuire |
| 179 | bò | propagated | 3.84 | bo |
| 180 | chiàmami | propagated | 3.83 | chiamare |
| 181 | telespettatòri | propagated | 3.83 | telespettatore |
| 182 | pròfughi | propagated | 3.83 | profugo |
| 183 | mistèri | propagated | 3.83 | mistero |
| 184 | pòrtami | propagated | 3.83 | portare |
| 185 | còlpe | propagated | 3.83 | colpa |
| 186 | parlàrti | propagated | 3.82 | parlare |
| 187 | aiùtami | propagated | 3.82 | aiutare |
| 188 | statunitènsi | propagated | 3.82 | statunitense |
| 189 | sùn | propagated | 3.82 | sun |
| 190 | prènderti | propagated | 3.82 | prendere |
| 191 | cugìni | propagated | 3.82 | cugino |
| 192 | lasciàrla | propagated | 3.82 | lasciare |
| 193 | còm | propagated | 3.82 | com |
| 194 | pochìssimi | propagated | 3.81 | pochissimo, poco |
| 195 | regolàri | propagated | 3.81 | regolare |
| 196 | miglioramènti | propagated | 3.81 | miglioramento |
| 197 | chiamàrlo | propagated | 3.81 | chiamare |
| 198 | aumentàta | propagated | 3.81 | aumentare, aumentato |
| 199 | dìllo | propagated | 3.81 | dicere, dire |
| 200 | cominciàta | propagated | 3.80 | cominciare |

## Source correlations

Spearman correlation of each source against the mean of the others (leave-one-out).

| source | spearman | n |
|---|---|---|
| leipzig_news | 0.700 | 134632 |
| opensubtitles | 0.690 | 134632 |
| wordfreq | 0.862 | 134632 |
