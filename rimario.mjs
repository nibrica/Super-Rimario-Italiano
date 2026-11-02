#!/usr/bin/env node
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

// Command-line front end to the engine in web/js. Needs Node 22.7 or later.

import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { parseDictionary } from './web/js/dictionary.js';
import { resolve, run } from './web/js/search.js';
import { FLAGS } from './web/js/text.js';

const DICTIONARY = new URL('web/parole-accenti-frequenze.csv', import.meta.url);
const TYPES = {
    rhymes: 'Rhymes',
    atonal: 'Atonal assonances',
    assonances: 'Assonances',
    consonances: 'Consonances',
};
const ALL_TYPES = Object.keys(TYPES);
const HELP = `Usage: rimario [flags] word

Finds Italian rhymes, atonal assonances, assonances and consonances of a word,
most frequent first. Mark the stress with an accent to pick a reading (àncora)
or to search a word missing from the dictionary (blorfò).

Flags:
  -m, --max N         maximum words, split evenly among the printed types;
                      a type's unused share is not reassigned (default: 100)
  -t, --type LIST     types to print, comma-separated or repeated:
                      ${ALL_TYPES.join(', ')} (default: all)
      --[no-]proper   include proper nouns (default: yes)
      --[no-]archaic  include archaic and poetic words (default: no)
      --[no-]vulgar   include vulgar and offensive words (default: no)
  -h, --help          show this help

Lines starting with # are headers: grep '^[^#]' keeps only the words.
Exit status: 0 word searched, 1 word not found, 2 usage error.

Dictionary sources and licences: web/ATTRIBUTION.md`;

function die(message, code = 2) {
    console.error(`rimario: ${message}`);
    process.exit(code);
}

let values, positionals;
try {
    ({ values, positionals } = parseArgs({
        allowPositionals: true,
        allowNegative: true,
        options: {
            max: { type: 'string', short: 'm', default: '100' },
            type: { type: 'string', short: 't', multiple: true },
            proper: { type: 'boolean', default: true },
            archaic: { type: 'boolean', default: false },
            vulgar: { type: 'boolean', default: false },
            help: { type: 'boolean', short: 'h' },
        },
    }));
} catch (error) {
    die(error.message);
}

if (values.help) {
    console.log(HELP);
    process.exit(0);
}
if (positionals.length !== 1) die('expected exactly one word (see --help)');

const max = Number(values.max);
if (!Number.isInteger(max) || max < 1) die(`--max must be a positive integer, got '${values.max}'`);

const requested = values.type?.flatMap((t) => t.split(',')) ?? ALL_TYPES;
const bad = requested.find((t) => !ALL_TYPES.includes(t));
if (bad !== undefined) die(`unknown --type '${bad}' (choose from ${ALL_TYPES.join(', ')})`);
const types = ALL_TYPES.filter((t) => requested.includes(t));

const dict = parseDictionary(readFileSync(DICTIONARY, 'utf8'));
const res = resolve(dict, positionals[0]);
if (!res.ok && res.reason === 'empty') die(`no usable word in '${positionals[0]}'`);
if (!res.ok) {
    const hint = res.candidates.length ? ` Where does the stress fall? Try: ${res.candidates.join(' ')}` : '';
    die(`'${res.term}' is not in the dictionary.${hint}`, 1);
}

const hideFlags = (values.proper ? 0 : FLAGS.PROPER)
    | (values.archaic ? 0 : FLAGS.ARCHAIC)
    | (values.vulgar ? 0 : FLAGS.VULGAR);
const { query, groups, totals, imperfectSkipped } = run(dict, res.query, { hideFlags });

if (query.row === -1) console.error(`Note: ${query.readings.length ? 'this stress is' : 'word is'} not in the dictionary, using the stress you marked.`);
if (query.predicted) console.error('Note: the stress of this word was estimated and may be wrong.');
if (imperfectSkipped) console.error('Note: ending too long, only rhymes were searched.');

console.log(`# ${query.label}`);
types.forEach((type, i) => {
    let left = Math.floor(max / types.length) + (i < max % types.length ? 1 : 0);
    console.log(`\n## ${TYPES[type]} (${Math.min(left, totals[type])} of ${totals[type]})`);
    groups[type].forEach((rows, g) => {
        const shown = rows.slice(0, left);
        left -= shown.length;
        if (shown.length && groups[type].length > 1) console.log(`### ${g + 1} change${g ? 's' : ''}`);
        for (const row of shown) console.log(dict.displayWord(row));
    });
});
