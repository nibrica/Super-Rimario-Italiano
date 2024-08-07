// Super Rimario Italiano
// Copyright (C) 2024 Nicolò Brigadoi Calamari
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.


const dictionary_link = "parole-accenti-frequenze_2024-08-06.csv";

let resize_timeout = null;
let segmenter = null;
let collator = null;
let alphabetical_order = null;
let dictionary = null;

let slide_index = 0;

//Compare two segmented strings backwards, using a custom alphabetical order
function CompareSegmentedStringsBackwards(a, b) {
    const min_length = Math.min(a.length, b.length);
    for (let iii = 0; iii < min_length; iii++) {
        const order_a = alphabetical_order.get(a[a.length - 1 - iii].segment);
        const order_b = alphabetical_order.get(b[b.length - 1 - iii].segment);
        if (order_a !== order_b) return order_a - order_b;
    }
    return a.length - b.length;
}

//Find the position of the accent in the query string
function GetQueryAccent(query) {

    //Recursive binary search to find a specific word
    function SearchWordIndex(start, end) {
        if (start > end) return -1;
        const index = Math.floor(start + ((end - start) * 0.5));
        if (collator.compare(dictionary[index][0], query) === 0) return index;
        if (CompareSegmentedStringsBackwards(segmented_query, [...segmenter.segment(dictionary[index][0])]) < 0) {
            return SearchWordIndex(start, index - 1);
        }
        else return SearchWordIndex(index + 1, end);
    }

    //No need for segmentation, as there should only be ASCII characters
    function ExplicitAccent(word_index) {
        const word = dictionary[word_index][0];
        const accent = dictionary[word_index][1];
        return word.substring(0, accent + 1) + "\u0300" + word.substring(accent + 1);
    }

    function HandleHomograph(current_index, alternative_index) {
        document.getElementById("homograph-message").style.display = "inline";
        document.getElementById("homograph-message").innerHTML = "Rime con <b>" + ExplicitAccent(current_index) +
            "</b>. Intendevi <b><span class='word-button' onmousedown='SearchFromButton(this)'>" +
            ExplicitAccent(alternative_index) + "</span></b>?";
    }

    function GetFirstAccent() {
        if (query_index > 0) {
            const previous_index = query_index - 1;
            if (collator.compare(dictionary[previous_index][0], query) == 0) {
                HandleHomograph(previous_index, query_index);
                return previous_index;
            }
        }
        if (query_index < dictionary.length - 1) {
            const next_index = query_index + 1;
            if (collator.compare(dictionary[next_index][0], query) == 0) {
                HandleHomograph(query_index, next_index);
                return query_index;
            }
        }
        return query_index;
    }

    document.getElementById("homograph-message").style.display = "none";
    HideSystemMessage();
    const accent = query.search(/[àèìòùáéíóú]/u);
    if (accent >= 0) return accent;
    const segmented_query = [...segmenter.segment(query)];
    const query_index = SearchWordIndex(0, dictionary.length);
    if (query_index < 0) {
        document.getElementById("query-label").innerHTML = "<i>“" + query + "”</i> non è nel dizionario";
        ShowSystemMessage("Per cercare le rime che non sono nel dizionario è necessario indicare esplicitamente l'accento. (Es. <i>italiàno</i>)");
        return -1;
    }
    return dictionary[GetFirstAccent()][1];
}

//Search the dictionary for a given termination
function SearchRhymes(suffix_changed) {

    //Recursive binary search to find a string with a specific termination
    function SearchRhymeIndex(start, end) {
        if (start > end) return -1;
        const index = Math.floor(start + ((end - start) * 0.5));
        if (dictionary[index][0].endsWith(suffix_changed.word)) return index;
        if (CompareSegmentedStringsBackwards(segmented_word, [...segmenter.segment(dictionary[index][0])]) < 0) {
            return SearchRhymeIndex(start, index - 1);
        }
        else return SearchRhymeIndex(index + 1, end);
    }

    //Search all the entries before and after the found rhyme while the termination matches
    function SearchRhymesFromIndex() {
        const found_rhymes = [];
        for (let iii = found_rhyme_index; iii < dictionary.length && dictionary[iii][0].endsWith(suffix_changed.word); iii++) {
            if (dictionary[iii][0].length - dictionary[iii][1] === suffix_changed.word.length) {
                found_rhymes.push({ index: iii, changed: suffix_changed.changed });
            }
        }
        for (let iii = found_rhyme_index - 1; iii >= 0 && dictionary[iii][0].endsWith(suffix_changed.word); iii--) {
            if (dictionary[iii][0].length - dictionary[iii][1] === suffix_changed.word.length) {
                found_rhymes.push({ index: iii, changed: suffix_changed.changed });
            }
        }
        return found_rhymes;
    }

    const segmented_word = [...segmenter.segment(suffix_changed.word)];
    const found_rhyme_index = SearchRhymeIndex(0, dictionary.length);
    if (found_rhyme_index < 0) return [];
    return SearchRhymesFromIndex(found_rhyme_index);
}

//Generate combinations of similar consonats to search for the assonances
function GenerateConsonantCombinations(suffix) {
    const max_changes = 3;
    const similar_consonants = {
        "r": "ln",
        "t": "pdbn",
        "p": "tdbm",
        "s": "fzv",
        "d": "tpn",
        "f": "szv",
        "g": "c",
        "l": "rn",
        "z": "s",
        "c": "g",
        "v": "sfz",
        "b": "tpdm",
        "n": "rtdlm",
        "m": "pbn"
    };
    const consonants = Object.keys(similar_consonants);

    //No need for segmentation, as we made sure that there are only ASCII characters
    function Generate(word, index, changed) {
        for (; index < word.length; index++) {
            if (consonants.includes(word[index])) break;
        }
        if (index === word.length || changed.length >= max_changes) {
            return [{ word: word, changed: changed }];
        }
        const results = Generate(word, index + 1, changed);
        for (const substitution of similar_consonants[word[index]]) {
            const new_word = word.slice(0, index) + substitution + word.slice(index + 1);
            results.push(...Generate(new_word, index + 1, changed.concat([index])));
        }
        return results;
    }

    return Generate(suffix, 1, []);
}

//Generate combinations of vowels for the search of consonances and atonal assonaces
function GenerateVowelCombinations(suffix) {
    const max_changes = 3;
    const vowels = "aeiou";

    //No need for segmentation, as we made sure that there are only ASCII characters
    function Generate(word, index, changed) {
        for (; index < word.length; index++) {
            if (vowels.includes(word[index])) break;
        }
        if (index === word.length || changed.length >= max_changes) {
            return [{ word: word, changed: changed }]
        };
        const results = [];
        for (const substitution of vowels) {
            //Skip combinations with double vowels (es. 'aa')
            if (collator.compare(word[index], substitution) == 0) {
                if (index === 0) {
                    results.push(...Generate(word, index + 1, changed));
                }
                else if (collator.compare(word[index - 1], substitution) != 0) {
                    results.push(...Generate(word, index + 1, changed));
                }
            }
            else {
                const new_word = word.slice(0, index) + substitution + word.slice(index + 1);
                if (index === 0) {
                    results.push(...Generate(new_word, index + 1, changed.concat([index])));
                }
                else if (collator.compare(word[index - 1], substitution) != 0) {
                    results.push(...Generate(new_word, index + 1, changed.concat([index])));
                }
            }
        }
        return results;
    }

    function GenerateAccented() {
        const results = [];
        for (const vowel of ["à", "è", "é", "ì", "ò", "ù"]) {
            if (collator.compare(accented_final, vowel) != 0) {
                results.push({ word: vowel, changed: [0] });
            }
        }
        return results;
    }

    const accented_final = suffix.match(/[àèéìòù]$/u);
    if (accented_final) {
        return GenerateAccented();
    }
    return Generate(suffix, 0, []);
}

function SearchPerfectRhymes(rhyme_suffix) {
    const found_rhymes = SearchRhymes({ word: rhyme_suffix, changed: [] });
    if (rhyme_suffix.endsWith("è")) {
        found_rhymes.push(...SearchRhymes({ word: "é", changed: [] }));
    }
    else if (rhyme_suffix.endsWith("é")) {
        found_rhymes.push(...SearchRhymes({ word: "è", changed: [] }));
    }
    return found_rhymes;
}

function SearchImperfectRhymes(suffix_changed_list) {
    const found_rhymes = [];
    for (const suffix_changed of suffix_changed_list) {
        if (suffix_changed.changed.length === 0) {
            continue;
        }
        found_rhymes.push(...SearchRhymes(suffix_changed));
    }
    return found_rhymes;
}

//Sort by frequency
function SortPerfectRhymes(indexes) {
    return indexes.sort((a, b) => dictionary[b.index][2] - dictionary[a.index][2]);
}

//Sort by number of differences, then by frequency
function SortImperfectRhymes(rhymes_changed_list) {
    return rhymes_changed_list.sort((a, b) => {
        const changes_difference = a.changed.length - b.changed.length;
        if (changes_difference !== 0) {
            return changes_difference;
        }
        else return dictionary[b.index][2] - dictionary[a.index][2]
    });
}

function PrintPerfectRhymes(rhymes_changed_list, query) {

    //Make a plain word list
    function MakeRhymeList() {
        let text = "";
        for (const data of rhymes_changed_list) {
            if (collator.compare(dictionary[data.index][0], query) !== 0) {
                text += "<div>" + dictionary[data.index][0] + "</div>";
            }
        }
        return text;
    }

    const text = MakeRhymeList();
    if (text.length === 0) {
        document.getElementById("rhymes-box").innerHTML = "<div class='results-none'>Nessuna rima trovata</div>";
        return;
    }
    document.getElementById("rhymes-box").innerHTML = text;
}

function PrintAtonalAssonances(rhymes_changed_list) {

    //Make a word list of clickable divs
    function MakeAtonalList() {
        let text = "";
        for (const data of rhymes_changed_list) {
            text += "<div class='word-button' onmousedown='SearchFromButton(this)'>" +
                dictionary[data.index][0] + "</div>";
        }
        return text;
    }

    if (rhymes_changed_list.length === 0) {
        document.getElementById("atonal-assonances-box").innerHTML = "<div class='results-none'>Nessuna assonanza atona trovata</div>";
        return;
    }
    document.getElementById("atonal-assonances-box").innerHTML = MakeAtonalList(rhymes_changed_list);
}

function PrintAssonances(rhymes_changed_list) {

    //Make a word list of clickable divs, with collapsable subsection header
    function MakeAssonanceList() {
        let title_plural;
        let text = "";
        let last_change = -1;
        for (const data of rhymes_changed_list) {
            if (data.changed.length !== last_change) {
                last_change = data.changed.length;
                title_plural = (data.changed.length == 1) ? "a" : "e";
                text += "<br></span></div><div class='results-section'><button class='section-button'" +
                    "title='Esapndi/collassa sezione' onmousedown='CollapseSection(this)' data-show='on'><span>▾</span> " +
                    data.changed.length + " differenz" + title_plural + "</button><span>";
            }
            text += "<div class='word-button' onmousedown='SearchFromButton(this)'>" +
                dictionary[data.index][0] + "</div>";
        }
        return text.slice(17);
    }

    if (rhymes_changed_list.length === 0) {
        document.getElementById("assonances-box").innerHTML = "<div class='results-none'>Nessuna assonanza semplice trovata</div>";
        return;
    }
    document.getElementById("assonances-box").innerHTML = MakeAssonanceList();
}

function PrintConsonances(rhymes_changed_list) {

    //Make a word list of clickable divs, with collapsable subsection header,
    //while extracting the atonal assonances from the list
    function MakeConsonanceList() {
        let title_plural;
        let text = "";
        let last_change = -1;
        const atonal_assonances = [];
        for (const data of rhymes_changed_list) {
            if (data.changed.length === 1) {
                if (data.changed[0] === 0) {
                    atonal_assonances.push(data);
                    continue;
                }
            }
            if (data.changed.length !== last_change) {
                last_change = data.changed.length;
                title_plural = (data.changed.length == 1) ? "a" : "e";
                text += "<br></span></div><div class='results-section'><button class='section-button'" +
                    "title='Esapndi/collassa sezione' onmousedown='CollapseSection(this)' data-show='on'><span>▾</span> " +
                    data.changed.length + " differenz" + title_plural + "</button><span>";
            }
            text += "<div class='word-button' onmousedown='SearchFromButton(this)'>" +
                dictionary[data.index][0] + "</div>";
        }
        return { text: text.slice(17), atonal_assonances: atonal_assonances };
    }

    const text_and_atonal_assonances = MakeConsonanceList();
    if (text_and_atonal_assonances.text.length === 0) {
        document.getElementById("consonances-box").innerHTML = "<div class='results-none'>Nessuna consonanza trovata</div>";
        return text_and_atonal_assonances.atonal_assonances;
    }
    document.getElementById("consonances-box").innerHTML = text_and_atonal_assonances.text;
    return text_and_atonal_assonances.atonal_assonances;
}

//Main search function
function Search(query) {

    function RemoveNonFinalAccents() {
        return query
            .replace(/[àá](?!$)/ug, "a")
            .replace(/[èé](?!$)/ug, "e")
            .replace(/[ìí](?!$)/ug, "i")
            .replace(/[òó](?!$)/ug, "o")
            .replace(/[ùú](?!$)/ug, "u");
    }

    function SetNewURL() {
        const url = new URL(window.location);
        url.searchParams.set("q", query);
        window.history.pushState(null, "Rime con " + normalized_query, url);
        document.title = "Rime con " + normalized_query + " | Super Rimario Italiano";
    }

    if (!dictionary || !segmenter) {
        console.warn("Search disabed");
        return;
    }

    if (query.length === 0) return;
    query = query.normalize("NFC").toLowerCase().replace(/[^a-zàáèéìíòóùú -]/ug, "");
    const normalized_query = RemoveNonFinalAccents();
    SetNewURL();
    const query_accent = GetQueryAccent(query);
    if (query_accent < 0) return;
    document.getElementById("query-label").innerHTML = "Rime con " + normalized_query;
    ResetNavigation();
    const rhyme_suffix = normalized_query.substring(query_accent);
    if (rhyme_suffix.length < 16) {
        PrintPerfectRhymes(SortPerfectRhymes(SearchPerfectRhymes(rhyme_suffix)), normalized_query);
        PrintAssonances(SortImperfectRhymes(SearchImperfectRhymes(
            GenerateConsonantCombinations(rhyme_suffix), rhyme_suffix
        )));
        PrintAtonalAssonances(PrintConsonances(SortImperfectRhymes(SearchImperfectRhymes(
            GenerateVowelCombinations(rhyme_suffix), rhyme_suffix
        ))));
    }
    else {
        PrintPerfectRhymes([], normalized_query);
        PrintAtonalAssonances([]);
        PrintAssonances([]);
        PrintConsonances([]);
    }
}

function SearchFromBar(key = "Enter") {
    if (key === "Enter") {
        Search(document.getElementById("search-bar").value);
    }
}

function SearchFromButton(element) {
    document.getElementById("search-bar").value = element.innerHTML;
    Search(element.innerHTML);
}

async function CollapseSection(element) {
    if (element.dataset.show === "on") {
        element.dataset.show = "off";
        element.parentElement.children[1].style.display = "none";
        element.children[0].innerHTML = "▸";
        element.style.fontStyle = "italic";
    }
    else {
        element.dataset.show = "on";
        element.parentElement.children[1].style.display = "inline";
        element.children[0].innerHTML = "▾";
        element.style.fontStyle = "normal";
    }

}

function ShowSystemMessage(message) {
    document.getElementById("system-message").dataset.show = "on";
    document.getElementById("system-message").style.display = "inline";
    document.getElementById("system-message").innerHTML = message;
    for (const nav of document.getElementById("navigation").children) {
        nav.style.display = "none";
    }
    HandleResize();
}

function HideSystemMessage() {
    document.getElementById("system-message").dataset.show = "off";
    document.getElementById("system-message").style.display = "none";
    for (const nav of document.getElementById("navigation").children) {
        nav.style.display = "inline";
    }
}

function DisplayError(message, error) {
    document.getElementById("query-label").style.display = "none";
    document.getElementById("system-message").innerHTML = message;
    console.error(message, error);
    ShowSystemMessage(message);
}

function HandleResize() {
    const result_boxes = document.getElementById("results-box").children;
    for (let iii = 0; iii < result_boxes.length; iii++) {
        if ((slide_index !== iii && window.innerWidth < 768) ||
            document.getElementById("system-message").dataset.show === "on") {
            result_boxes[iii].style.display = "none";
        }
        else result_boxes[iii].style.display = "inline";
    }
}

function UpdateNavigation() {
    document.getElementById("previous-button").disabled = (slide_index === 0);
    document.getElementById("next-button").disabled = (slide_index === 3);
    document.getElementById("slide-label").innerHTML = (slide_index + 1) + "/4";
}

function ResetNavigation() {
    slide_index = 0;
    UpdateNavigation();
    HandleResize();
}

function SlideNavigation(amount) {
    const new_slide_index = slide_index + amount;
    if (new_slide_index >= 0 && new_slide_index <= 3) {
        slide_index = new_slide_index;
        UpdateNavigation();
        HandleResize();
    }
}

async function SharePage() {
    try {
        await navigator.share({ title: document.title, url: window.location.href });
    } catch (error) {
        console.error(error);
    }
}

async function InitPage() {
    async function FetchAndParseCSV() {
        try {
            let data = await fetch(dictionary_link);
            if (!data.ok) throw "invalid response";
            data = await data.text();
            data = data.split('\n');
            data = data.map(row => {
                const [str1, int1, int2] = row.split(',');
                return [str1, parseInt(int1), parseInt(int2)];
            });
            while (isNaN(data[data.length - 1][1])) data.pop();
            return data;
        } catch (error) {
            DisplayError("Errore: il download del dizionario è fallito.", error);
            return null;
        }
    }

    function ParseURLParams() {
        const url_params = new URLSearchParams(window.location.search);
        const url_params_query = url_params.get("q");
        if (url_params_query) {
            if (url_params_query.length > 0) {
                document.getElementById("search-bar").value = url_params_query;
                Search(url_params_query);
            }
        }
        else document.getElementById("search-bar").focus();
    }

    window.addEventListener("resize", function () {
        this.clearTimeout(resize_timeout);
        resize_timeout = this.setTimeout(HandleResize, 100);
    });
    ResetNavigation();
    try {
        segmenter = new Intl.Segmenter("it", { granularity: "grapheme" });
        collator = new Intl.Collator("it", { sensitivity: "variant" });
    } catch (error) {
        DisplayError("Errore: il tuo browser non è supportato. Per continuare aggiornarlo alla versione più recente.", error);
        return;
    }
    alphabetical_order = new Map(
        Array.from(segmenter.segment("abcdefghijklmnopqrstuvwxyzàáèéìíòóùú")).map(
            (segment, index) => [segment.segment, index])
    );
    dictionary = await FetchAndParseCSV();
    if (!dictionary) return;
    if (navigator.share) document.getElementById("share-button").style.display = "inline-block";
    document.getElementsByClassName("search-button")[0].disabled = false;
    document.getElementById("query-label").innerHTML = "&nbsp;";
    ParseURLParams();
}

InitPage();
