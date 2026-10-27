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

// Pure string helpers shared by the engine and the UI. No DOM access.

/**
 * Bits of the optional fourth CSV column.
 * @type {Readonly<{NON_DEFAULT: number, OPEN: number, CLOSED: number, PREDICTED: number,
 *                  VULGAR: number, ARCHAIC: number, PROPER: number}>}
 */
export const FLAGS = Object.freeze({
    NON_DEFAULT: 1, OPEN: 2, CLOSED: 4, PREDICTED: 8, VULGAR: 16, ARCHAIC: 32, PROPER: 64,
});

// Every character a dictionary word may contain, in code-point order.
const ALPHABET = 'abcdefghijklmnopqrstuvwxyzàèéìíòóùú';
const VOWELS = new Set('aeiouàèéìíòóùú');
const BASE_OF = Object.freeze({
    'à': 'a', 'è': 'e', 'é': 'e', 'ì': 'i', 'í': 'i', 'ò': 'o', 'ó': 'o', 'ù': 'u', 'ú': 'u',
});
const CLASS_OF = Object.freeze({
    a: ['a', 'à'], e: ['e', 'è', 'é'], i: ['i', 'ì', 'í'], o: ['o', 'ò', 'ó'], u: ['u', 'ù', 'ú'],
});
const QUALITY_SWAP = Object.freeze({
    'è': 'é', 'é': 'è', 'ò': 'ó', 'ó': 'ò', 'ì': 'í', 'í': 'ì', 'ù': 'ú', 'ú': 'ù',
});
const GRAVE = Object.freeze({ a: 'à', e: 'è', i: 'ì', o: 'ò', u: 'ù' });
const ACCENTED_RE = /[àèéìíòóùú]/g;
const NOT_IN_ALPHABET_RE = new RegExp(`[^${ALPHABET}]+`);
// A plain vowel followed by an apostrophe that ends the token ("perche'").
const APOSTROPHE_ACCENT_RE = new RegExp(`([aeiou])'(?=$|[^${ALPHABET}])`, 'g');
// Combining marks other than grave (U+0300) and acute (U+0301): "naïve" → "naive", "ç" → "c".
const OTHER_MARKS_RE = /[\u0302-\u036f]/g;
const MAX_QUERY_LENGTH = 50;

/**
 * Whether a character is a vowel (plain or accented).
 * @param {string} ch single character
 * @returns {boolean}
 */
export function isVowel(ch) {
    return VOWELS.has(ch);
}

/**
 * Whether a character is an accented vowel of the dictionary alphabet.
 * @param {string} ch single character
 * @returns {boolean}
 */
export function isAccented(ch) {
    return ch in BASE_OF;
}

/**
 * The plain vowel of an accented vowel ('è' → 'e'); other characters unchanged.
 * @param {string} ch single character
 * @returns {string}
 */
export function baseVowel(ch) {
    return BASE_OF[ch] ?? ch;
}

/**
 * Vowel quality expressed by an accent: è, ò → 'open'; é, ó → 'closed'; otherwise null.
 * @param {string} ch single character
 * @returns {'open' | 'closed' | null}
 */
export function qualityOf(ch) {
    if (ch === 'è' || ch === 'ò') return 'open';
    if (ch === 'é' || ch === 'ó') return 'closed';
    return null;
}

/**
 * All spellings of the same vowel (base or accented input): 'è' → ['e', 'è', 'é'].
 * Non-vowels return [ch].
 * @param {string} ch single character
 * @returns {string[]}
 */
export function vowelClass(ch) {
    return isVowel(ch) ? CLASS_OF[baseVowel(ch)].slice() : [ch];
}

/**
 * Replaces every accented vowel with its base vowel (length preserved).
 * @param {string} s
 * @returns {string}
 */
export function stripAccents(s) {
    return s.replace(ACCENTED_RE, (c) => BASE_OF[c]);
}

/**
 * Like stripAccents, but keeps an accent on the last character ("pèscà" → "pescà").
 * @param {string} s
 * @returns {string}
 */
export function stripAccentsExceptFinal(s) {
    if (s.length < 2) return s;
    return stripAccents(s.slice(0, -1)) + s[s.length - 1];
}

/**
 * Index of the last accented character, or -1.
 * @param {string} s
 * @returns {number}
 */
export function lastAccentIndex(s) {
    for (let i = s.length - 1; i >= 0; i--) {
        if (isAccented(s[i])) return i;
    }
    return -1;
}

/**
 * Swaps the accent of the last character: è↔é, ò↔ó, ì↔í, ù↔ú.
 * @param {string} s
 * @returns {string | null} the new string, or null when the last character has no counterpart
 */
export function swapFinalQuality(s) {
    const last = s[s.length - 1];
    if (!(last in QUALITY_SWAP)) return null;
    return s.slice(0, -1) + QUALITY_SWAP[last];
}

/**
 * Display form of a word with its stressed vowel marked (precomposed characters).
 * An already accented stressed vowel is kept unless it contradicts `quality`.
 * Plain a/i/u get a grave accent; e/o get grave (open, default) or acute (closed).
 * @param {string} word
 * @param {number} stress index of the stressed vowel
 * @param {'open' | 'closed' | null} [quality]
 * @returns {string}
 */
export function markStress(word, stress, quality = null) {
    const ch = word[stress];
    if (!isVowel(ch)) return word;
    if (isAccented(ch) && (quality === null || qualityOf(ch) === quality)) return word;
    const base = baseVowel(ch);
    let marked;
    if (base === 'e') marked = quality === 'closed' ? 'é' : 'è';
    else if (base === 'o') marked = quality === 'closed' ? 'ó' : 'ò';
    else marked = GRAVE[base];
    return word.slice(0, stress) + marked + word.slice(stress + 1);
}

/**
 * Normalizes raw user input into a single dictionary-alphabet token:
 * lower case, other diacritics dropped (ï → i, ç → c), NFC, typographic
 * apostrophes → "'", "e'" at a token end → "è",
 * "á" → "à", every other character is a separator, last non-empty token,
 * at most 50 characters.
 * @param {string} raw
 * @returns {string} '' when nothing usable remains
 */
export function cleanQuery(raw) {
    let s = String(raw ?? '').toLowerCase().normalize('NFD').replace(OTHER_MARKS_RE, '').normalize('NFC');
    s = s.replace(/[’‘`´]/g, "'");
    s = s.replace(APOSTROPHE_ACCENT_RE, (m, v) => GRAVE[v]);
    s = s.replace(/á/g, 'à');
    const tokens = s.split(NOT_IN_ALPHABET_RE);
    for (let i = tokens.length - 1; i >= 0; i--) {
        if (tokens[i]) return tokens[i].slice(0, MAX_QUERY_LENGTH);
    }
    return '';
}

/**
 * Candidate stressed spellings of an unknown word: markStress on each of the
 * last four vowel positions, left to right.
 * @param {string} word
 * @returns {string[]}
 */
export function stressCandidates(word) {
    const positions = [];
    for (let i = 0; i < word.length; i++) {
        if (isVowel(word[i])) positions.push(i);
    }
    return positions.slice(-4).map((i) => markStress(word, i));
}

/**
 * Upper-cases the first character.
 * @param {string} s
 * @returns {string}
 */
export function capitalize(s) {
    return s ? s[0].toUpperCase() + s.slice(1) : s;
}
