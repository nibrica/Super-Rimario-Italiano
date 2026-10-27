/*
 * Super Rimario Italiano
 * Copyright (C) 2024 Nicolò Brigadoi Calamari
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

// Query resolution and rhyme search. No DOM access.
//
// A rhyme "suffix" is the word from its stressed vowel to the end. A row matches
// a suffix variant v when its word ends with v and its own suffix has exactly
// v's length (so the stress falls on the same letter).

import {
    FLAGS, baseVowel, cleanQuery, isVowel, lastAccentIndex, markStress,
    qualityOf, stressCandidates, stripAccents, stripAccentsExceptFinal, swapFinalQuality,
    vowelClass,
} from './text.js';

/**
 * Maximum number of letters changed in an assonance or consonance.
 * @type {number}
 */
export const MAX_CHANGES = 3;

/**
 * Longest suffix for which assonances and consonances are computed.
 * @type {number}
 */
export const MAX_IMPERFECT_SUFFIX = 14;

/**
 * Result categories in tab/column order; `groups` = number of change groups
 * (group g holds the results with g + 1 changes).
 * @type {ReadonlyArray<{id: string, groups: number}>}
 */
export const CATEGORIES = Object.freeze([
    { id: 'rhymes', groups: 1 },
    { id: 'atonal', groups: 1 },
    { id: 'assonances', groups: 3 },
    { id: 'consonances', groups: 3 },
]);

// Consonants that sound alike enough for an assonance (ported unchanged).
const SIMILAR_CONSONANTS = Object.freeze({
    r: 'ln',
    t: 'pdbn',
    p: 'tdbm',
    s: 'fzv',
    d: 'tpn',
    f: 'szv',
    g: 'c',
    l: 'rn',
    z: 's',
    c: 'g',
    v: 'sfz',
    b: 'tpdm',
    n: 'rtdlm',
    m: 'pbn',
});
const PLAIN_VOWELS = 'aeiou';
const QU_SPELLINGS = Object.freeze(['qu', 'cu', 'cqu']);

/**
 * @typedef {object} QueryInfo
 * @property {string} word spelling searched
 * @property {number} stress index of the stressed vowel in word
 * @property {'open' | 'closed' | null} quality
 * @property {number} row chosen dictionary row, or -1 when the reading is not in the dictionary
 * @property {number[]} readings all rows of the word's group (ascending); [] when unknown
 * @property {string} label display form
 * @property {boolean} predicted whether the row's stress was estimated automatically
 */

/**
 * @typedef {{ok: false, reason: 'empty', term: ''}
 *         | {ok: false, reason: 'not-found', term: string, candidates: string[]}
 *         | {ok: true, term: string, query: QueryInfo}} Resolution
 */

/**
 * @typedef {object} SearchResult
 * @property {QueryInfo} query
 * @property {string} suffix word.slice(stress)
 * @property {boolean} imperfectSkipped suffix too long for assonances/consonances
 * @property {{rhymes: number[][], atonal: number[][], assonances: number[][], consonances: number[][]}} groups
 *     row indices per change group, sorted by zipf desc, then row asc
 * @property {{rhymes: number, atonal: number, assonances: number, consonances: number}} totals
 * @property {number} hidden rows dropped by hideFlags
 */

function range(start, end) {
    const rows = [];
    for (let i = start; i < end; i++) rows.push(i);
    return rows;
}

function queryInfo(dict, word, stress, quality, row, readings) {
    return {
        word,
        stress,
        quality,
        row,
        readings,
        label: row >= 0 ? dict.displayWord(row) : markStress(word, stress, quality),
        predicted: row >= 0 && (dict.flags(row) & FLAGS.PREDICTED) !== 0,
    };
}

// Row of group [start, end) read with stress k; quality match first, then the
// default reading, then the first. -1 when no row has that stress.
function pickReading(dict, start, end, k, quality) {
    let first = -1;
    let nonDefault = -1;
    for (let i = start; i < end; i++) {
        if (dict.stress(i) !== k) continue;
        if (quality !== null && dict.quality(i) === quality) return i;
        if (first === -1) first = i;
        if (nonDefault === -1 && (dict.flags(i) & FLAGS.NON_DEFAULT) === 0) nonDefault = i;
    }
    return nonDefault !== -1 ? nonDefault : first;
}

/**
 * Turns raw user input into the reading to search for.
 * @param {import('./dictionary.js').Dictionary} dict
 * @param {string} raw text typed by the user (or a chip's data-q)
 * @returns {Resolution}
 */
export function resolve(dict, raw) {
    const term = cleanQuery(raw);
    if (!term) return { ok: false, reason: 'empty', term: '' };

    // A. The exact spelling (or its final è/é swap) is a dictionary word.
    for (const spelling of [term, swapFinalQuality(term)]) {
        if (spelling === null) continue;
        const g = dict.findWord(spelling);
        if (g.start === g.end) continue;
        const row = dict.defaultReading(g.start, g.end);
        const stress = dict.stress(row);
        const quality = dict.quality(row) ?? qualityOf(spelling[stress]);
        return { ok: true, term, query: queryInfo(dict, spelling, stress, quality, row, range(g.start, g.end)) };
    }

    // B. The user marked the stress explicitly.
    const k = lastAccentIndex(term);
    if (k >= 0) {
        const typedQuality = qualityOf(term[k]);
        const kept = stripAccentsExceptFinal(term);
        for (const spelling of [kept, swapFinalQuality(kept), stripAccents(term)]) {
            if (spelling === null) continue;
            const g = dict.findWord(spelling);
            if (g.start === g.end) continue;
            const row = pickReading(dict, g.start, g.end, k, typedQuality);
            const quality = row >= 0 ? dict.quality(row) ?? qualityOf(spelling[k]) : typedQuality;
            return { ok: true, term, query: queryInfo(dict, spelling, k, quality, row, range(g.start, g.end)) };
        }
        return { ok: true, term, query: queryInfo(dict, kept, k, typedQuality, -1, []) };
    }

    // C. Unknown word without an accent: ask where the stress falls.
    return { ok: false, reason: 'not-found', term, candidates: stressCandidates(term) };
}

// Every combination of the qu / cu / cqu spellings before a vowel in s.
function quVariants(s) {
    let parts = [''];
    let i = 0;
    while (i < s.length) {
        let token = null;
        if (s.startsWith('cqu', i)) token = 'cqu';
        else if (s.startsWith('qu', i) || s.startsWith('cu', i)) token = s.slice(i, i + 2);
        if (token !== null && isVowel(s[i + token.length] ?? '')) {
            parts = parts.flatMap((prefix) => QU_SPELLINGS.map((spelling) => prefix + spelling));
            i += token.length;
        } else {
            for (let p = 0; p < parts.length; p++) parts[p] += s[i];
            i++;
        }
    }
    return parts;
}

/**
 * Suffix spellings that count as perfect rhymes of `suffix`: every spelling of the
 * stressed vowel ("ìo" ↔ "io", "è" ↔ "e" ↔ "é") and every qu / cu / cqu spelling
 * before a vowel. Deduplicated, `suffix` first.
 * @param {string} suffix
 * @returns {string[]}
 */
export function perfectVariants(suffix) {
    const rest = suffix.slice(1);
    const out = new Set([suffix]);
    for (const vowel of vowelClass(suffix[0])) {
        for (const v of quVariants(vowel + rest)) out.add(v);
    }
    return [...out];
}

/**
 * Assonance variants: up to MAX_CHANGES consonants (from index 1) replaced by a
 * similar one. Only variants with at least one change, deduplicated.
 * @param {string} suffix unaccented suffix
 * @returns {{suffix: string, changes: number}[]}
 */
export function consonantVariants(suffix) {
    const out = new Map();
    const generate = (word, index, changes) => {
        while (index < word.length && !(word[index] in SIMILAR_CONSONANTS)) index++;
        if (index === word.length || changes >= MAX_CHANGES) {
            if (changes > 0 && !out.has(word)) out.set(word, changes);
            return;
        }
        generate(word, index + 1, changes);
        for (const substitute of SIMILAR_CONSONANTS[word[index]]) {
            generate(word.slice(0, index) + substitute + word.slice(index + 1), index + 1, changes + 1);
        }
    };
    generate(suffix, 1, 0);
    return [...out].map(([s, changes]) => ({ suffix: s, changes }));
}

/**
 * Consonance / atonal assonance variants: up to MAX_CHANGES vowels replaced
 * (never creating a doubled vowel); `stressed` when the stressed vowel (index 0)
 * changed. For a final stress (length 1), every spelling of every other vowel.
 * Only variants with at least one change, deduplicated.
 * @param {string} suffix
 * @returns {{suffix: string, changes: number, stressed: boolean}[]}
 */
export function vowelVariants(suffix) {
    if (suffix.length === 1) {
        const own = baseVowel(suffix);
        const out = [];
        for (const v of PLAIN_VOWELS) {
            if (v === own) continue;
            for (const spelling of vowelClass(v)) out.push({ suffix: spelling, changes: 1, stressed: true });
        }
        return out;
    }
    const out = new Map();
    const generate = (word, index, changes, stressed) => {
        while (index < word.length && !PLAIN_VOWELS.includes(word[index])) index++;
        if (index === word.length || changes >= MAX_CHANGES) {
            if (changes > 0 && !out.has(word)) out.set(word, { suffix: word, changes, stressed });
            return;
        }
        for (const substitute of PLAIN_VOWELS) {
            // Skip combinations with double vowels (e.g. 'aa').
            if (index > 0 && word[index - 1] === substitute) continue;
            if (substitute === word[index]) {
                generate(word, index + 1, changes, stressed);
            } else {
                const changed = word.slice(0, index) + substitute + word.slice(index + 1);
                generate(changed, index + 1, changes + 1, stressed || index === 0);
            }
        }
    };
    generate(stripAccents(suffix), 0, 0, false);
    return [...out.values()];
}

/**
 * Searches rhymes, atonal assonances, assonances and consonances of a resolved query.
 * @param {import('./dictionary.js').Dictionary} dict
 * @param {QueryInfo} query Resolution.query
 * @param {{hideFlags?: number}} [options] rows with any of these FLAGS bits are
 *     dropped and counted in `hidden`
 * @returns {SearchResult}
 */
export function run(dict, query, { hideFlags = 0 } = {}) {
    const word = query.word;
    const suffix = word.slice(query.stress);
    const imperfectSkipped = suffix.length > MAX_IMPERFECT_SUFFIX;
    const groups = {};
    for (const { id, groups: count } of CATEGORIES) {
        groups[id] = Array.from({ length: count }, () => []);
    }
    let hidden = 0;

    const collect = (variant, target) => {
        const n = variant.length;
        const { start, end } = dict.suffixRange(variant);
        for (let r = start; r < end; r++) {
            if (dict.wordLength(r) - dict.stress(r) !== n || dict.equals(r, word)) continue;
            if (dict.flags(r) & hideFlags) hidden++;
            else target.push(r);
        }
    };

    for (const v of perfectVariants(suffix)) collect(v, groups.rhymes[0]);

    if (!imperfectSkipped) {
        if (suffix.length > 1) {
            for (const v of consonantVariants(stripAccents(suffix))) {
                collect(v.suffix, groups.assonances[v.changes - 1]);
            }
        }
        for (const v of vowelVariants(suffix)) {
            const target = v.changes === 1 && v.stressed ? groups.atonal[0] : groups.consonances[v.changes - 1];
            collect(v.suffix, target);
        }
    }

    const byFrequency = (a, b) => dict.zipf(b) - dict.zipf(a) || a - b;
    const totals = {};
    for (const { id } of CATEGORIES) {
        let total = 0;
        for (const rows of groups[id]) {
            rows.sort(byFrequency);
            total += rows.length;
        }
        totals[id] = total;
    }

    return { query, suffix, imperfectSkipped, groups, totals, hidden };
}
