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

// Dictionary loader, parser and in-memory index. No DOM access.
//
// CSV format: one row per line, `word,stress,zipf[,flags]`, sorted by reversed
// word (code-point order), then stress, then flags. The whole file is kept as
// one string; rows are described by parallel typed arrays pointing into it, so
// the only per-row cost is 9 bytes.

import { FLAGS, capitalize, isAccented, markStress } from './text.js';

const MAX_WORD_LENGTH = 255;
const PROGRESS_INTERVAL_MS = 50;
const CHAR_NEWLINE = 10;
const CHAR_CR = 13;
const CHAR_COMMA = 44;
const CHAR_0 = 48;
const CHAR_9 = 57;
const CHAR_BOM = 0xfeff;

/**
 * Read-only index over the parsed dictionary. Constructed only by parseDictionary.
 * Rows are 0..size-1 in file order (sorted by reversed word, then stress, then flags).
 */
export class Dictionary {
    #text;
    #start;
    #len;
    #stress;
    #zipf;
    #flags;
    #size;

    /**
     * @param {string} text the CSV text the rows point into
     * @param {Int32Array} start offset of each word in `text`
     * @param {Uint8Array} len word lengths
     * @param {Uint8Array} stress stressed vowel indices
     * @param {Uint16Array} zipf Zipf × 100
     * @param {Uint8Array} flags FLAGS bitfields
     * @private
     */
    constructor(text, start, len, stress, zipf, flags) {
        this.#text = text;
        this.#start = start;
        this.#len = len;
        this.#stress = stress;
        this.#zipf = zipf;
        this.#flags = flags;
        this.#size = start.length;
    }

    /**
     * Number of rows.
     * @type {number}
     */
    get size() {
        return this.#size;
    }

    /**
     * The word of row i (allocates: use for display or results only).
     * @param {number} i row
     * @returns {string}
     */
    word(i) {
        const s = this.#start[i];
        return this.#text.slice(s, s + this.#len[i]);
    }

    /**
     * @param {number} i row
     * @returns {number} length of word(i)
     */
    wordLength(i) {
        return this.#len[i];
    }

    /**
     * @param {number} i row
     * @returns {number} index of the stressed vowel in word(i)
     */
    stress(i) {
        return this.#stress[i];
    }

    /**
     * @param {number} i row
     * @returns {number} Zipf frequency × 100
     */
    zipf(i) {
        return this.#zipf[i];
    }

    /**
     * @param {number} i row
     * @returns {number} FLAGS bitfield (0 when the row had no flags column)
     */
    flags(i) {
        return this.#flags[i];
    }

    /**
     * Compares reversed(word(i)) with reversed(s) in code-unit order; on a common
     * suffix the shorter string is smaller. No allocation.
     * @param {number} i row
     * @param {string} s
     * @returns {number} negative, zero or positive
     */
    compareTo(i, s) {
        const text = this.#text;
        const first = this.#start[i];
        const len = this.#len[i];
        let a = first + len - 1;
        let b = s.length - 1;
        while (a >= first && b >= 0) {
            const d = text.charCodeAt(a) - s.charCodeAt(b);
            if (d !== 0) return d;
            a--;
            b--;
        }
        return len - s.length;
    }

    /**
     * First row with compareTo(row, s) >= 0, or size if none.
     * @param {string} s
     * @returns {number}
     */
    lowerBound(s) {
        let lo = 0;
        let hi = this.#size;
        while (lo < hi) {
            const mid = (lo + hi) >>> 1;
            if (this.compareTo(mid, s) < 0) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    /**
     * Whether word(i) ends with s. No allocation.
     * @param {number} i row
     * @param {string} s
     * @returns {boolean}
     */
    endsWith(i, s) {
        const n = s.length;
        const len = this.#len[i];
        if (n > len) return false;
        const text = this.#text;
        const offset = this.#start[i] + len - n;
        for (let k = n - 1; k >= 0; k--) {
            if (text.charCodeAt(offset + k) !== s.charCodeAt(k)) return false;
        }
        return true;
    }

    /**
     * Whether word(i) === s. No allocation.
     * @param {number} i row
     * @param {string} s
     * @returns {boolean}
     */
    equals(i, s) {
        return this.#len[i] === s.length && this.endsWith(i, s);
    }

    /**
     * Whether word(i) === word(j). No allocation.
     * @param {number} i row
     * @param {number} j row
     * @returns {boolean}
     */
    sameWord(i, j) {
        const len = this.#len[i];
        if (len !== this.#len[j]) return false;
        const text = this.#text;
        const a = this.#start[i];
        const b = this.#start[j];
        for (let k = len - 1; k >= 0; k--) {
            if (text.charCodeAt(a + k) !== text.charCodeAt(b + k)) return false;
        }
        return true;
    }

    /**
     * Rows spelled exactly s.
     * @param {string} s
     * @returns {{start: number, end: number}} end exclusive; start === end when not found
     */
    findWord(s) {
        const start = this.lowerBound(s);
        let end = start;
        while (end < this.#size && this.equals(end, s)) end++;
        return { start, end };
    }

    /**
     * Rows whose word ends with s (they are contiguous).
     * @param {string} s
     * @returns {{start: number, end: number}} end exclusive
     */
    suffixRange(s) {
        const start = this.lowerBound(s);
        let end = start;
        while (end < this.#size && this.endsWith(end, s)) end++;
        return { start, end };
    }

    /**
     * The run of rows with the same word as row i.
     * @param {number} i row
     * @returns {{start: number, end: number}} end exclusive
     */
    groupBounds(i) {
        let start = i;
        let end = i + 1;
        while (start > 0 && this.sameWord(start - 1, i)) start--;
        while (end < this.#size && this.sameWord(end, i)) end++;
        return { start, end };
    }

    /**
     * The default reading among rows [start, end): the first without
     * FLAGS.NON_DEFAULT, else the one with the highest zipf.
     * @param {number} start first row
     * @param {number} end row after the last
     * @returns {number} row
     */
    defaultReading(start, end) {
        let best = start;
        for (let i = start; i < end; i++) {
            if ((this.#flags[i] & FLAGS.NON_DEFAULT) === 0) return i;
            if (this.#zipf[i] > this.#zipf[best]) best = i;
        }
        return best;
    }

    /**
     * Whether row i must be shown with its stress marked: another reading of
     * the same word has a different stress.
     * @param {number} i row
     * @returns {boolean}
     */
    needsStressMark(i) {
        const { start, end } = this.groupBounds(i);
        const stress = this.#stress[i];
        for (let j = start; j < end; j++) {
            if (this.#stress[j] !== stress) return true;
        }
        return false;
    }

    /**
     * Lower-case search term for row i: the word, with its stress marked when
     * needsStressMark(i). What a result chip searches for and puts in ?q=.
     * @param {number} i row
     * @returns {string}
     */
    queryTerm(i) {
        const word = this.word(i);
        return this.needsStressMark(i) ? markStress(word, this.#stress[i]) : word;
    }

    /**
     * Display form of row i: queryTerm(i), capitalized for proper nouns.
     * @param {number} i row
     * @returns {string}
     */
    displayWord(i) {
        const term = this.queryTerm(i);
        return this.#flags[i] & FLAGS.PROPER ? capitalize(term) : term;
    }
}

// Unsigned decimal in text[from, to), or -1 if empty or not all digits.
function parseUint(text, from, to) {
    if (from >= to || to - from > 9) return -1;
    let value = 0;
    for (let k = from; k < to; k++) {
        const c = text.charCodeAt(k);
        if (c < CHAR_0 || c > CHAR_9) return -1;
        value = value * 10 + (c - CHAR_0);
    }
    return value;
}

/**
 * Parses the dictionary CSV in one pass (no split, no per-row objects).
 * Malformed lines are skipped and reported once with console.warn.
 * @param {string} text CSV text (BOM already removed or absent)
 * @returns {Dictionary}
 * @throws {Error} when no valid row remains
 */
export function parseDictionary(text) {
    const length = text.length;

    let lines = 0;
    for (let p = text.indexOf('\n'); p !== -1; p = text.indexOf('\n', p + 1)) lines++;
    if (length > 0 && text.charCodeAt(length - 1) !== CHAR_NEWLINE) lines++;

    const start = new Int32Array(lines);
    const len = new Uint8Array(lines);
    const stress = new Uint8Array(lines);
    const zipf = new Uint16Array(lines);
    const flags = new Uint8Array(lines);
    let count = 0;
    let skipped = 0;

    let pos = 0;
    while (pos < length) {
        let next = text.indexOf('\n', pos);
        if (next === -1) next = length;
        let end = next;
        if (end > pos && text.charCodeAt(end - 1) === CHAR_CR) end--;

        if (end > pos) {
            // Comma positions; a fourth comma makes the line invalid.
            let c1 = -1;
            let c2 = -1;
            let c3 = -1;
            let commas = 0;
            for (let k = pos; k < end && commas < 4; k++) {
                if (text.charCodeAt(k) === CHAR_COMMA) {
                    commas++;
                    if (commas === 1) c1 = k;
                    else if (commas === 2) c2 = k;
                    else if (commas === 3) c3 = k;
                }
            }
            const wordLength = c1 - pos;
            const s = commas >= 2 ? parseUint(text, c1 + 1, c2) : -1;
            const z = commas >= 2 ? parseUint(text, c2 + 1, commas === 3 ? c3 : end) : -1;
            const f = commas === 3 ? parseUint(text, c3 + 1, end) : 0;
            if ((commas === 2 || commas === 3) && wordLength > 0 && wordLength <= MAX_WORD_LENGTH
                && s >= 0 && s < wordLength && z >= 0 && z <= 0xffff && f >= 0 && f <= 0xff) {
                start[count] = pos;
                len[count] = wordLength;
                // A written final accent is always the stress, whatever the column says.
                stress[count] = isAccented(text[c1 - 1]) ? wordLength - 1 : s;
                zipf[count] = z;
                flags[count] = f;
                count++;
            } else {
                skipped++;
            }
        }
        pos = next + 1;
    }

    if (skipped > 0) console.warn(`Dictionary: skipped ${skipped} invalid line(s).`);
    if (count === 0) throw new Error('Dictionary contains no valid rows');
    if (count === lines) return new Dictionary(text, start, len, stress, zipf, flags);
    return new Dictionary(text, start.slice(0, count), len.slice(0, count),
        stress.slice(0, count), zipf.slice(0, count), flags.slice(0, count));
}

/**
 * Downloads, decodes and parses the dictionary, streaming to report progress.
 * @param {string | URL} url
 * @param {object} [options]
 * @param {(loaded: number, total: number | null) => void} [options.onProgress]
 *     bytes received / expected (null = unknown); called at most every ~50 ms and
 *     once at the end with total === loaded
 * @param {number | null} [options.expectedBytes] decompressed size, used when the
 *     response is compressed (Content-Length then counts compressed bytes)
 * @returns {Promise<Dictionary>} rejects with Error on HTTP, network or parse failure
 */
export async function loadDictionary(url, { onProgress, expectedBytes = null } = {}) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Dictionary download failed: HTTP ${response.status}`);

    const encoding = (response.headers.get('Content-Encoding') ?? 'identity').trim().toLowerCase();
    const contentLength = Number.parseInt(response.headers.get('Content-Length') ?? '', 10);
    let total = null;
    if (encoding === 'identity' && contentLength > 0) total = contentLength;
    else if (expectedBytes > 0) total = expectedBytes;

    let text;
    if (response.body && typeof response.body.getReader === 'function') {
        const reader = response.body.getReader();
        // Decode while streaming so the raw bytes never have to be held all at once.
        const decoder = new TextDecoder('utf-8');
        const parts = [];
        let loaded = 0;
        let lastReport = -Infinity;
        onProgress?.(0, total);
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            parts.push(decoder.decode(value, { stream: true }));
            loaded += value.byteLength;
            if (total !== null && loaded > total) total = null;
            const now = Date.now();
            if (now - lastReport >= PROGRESS_INTERVAL_MS) {
                lastReport = now;
                onProgress?.(loaded, total);
            }
        }
        parts.push(decoder.decode());
        onProgress?.(loaded, loaded);
        text = parts.join('');
        parts.length = 0;
        // Let the UI paint "Preparazione del dizionario…" before the blocking work.
        await new Promise((resolve) => setTimeout(resolve));
    } else {
        text = await response.text();
        onProgress?.(text.length, text.length);
        await new Promise((resolve) => setTimeout(resolve));
    }

    if (text.charCodeAt(0) === CHAR_BOM) text = text.slice(1);
    return parseDictionary(text);
}
