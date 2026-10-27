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

// Entry point: reads the config from #rimario, loads the dictionary, and
// connects the engine (search.js) to the view (ui.js). Owns the filter
// preferences, the browser history (?q=) and document.title.

import { FLAGS, cleanQuery } from './text.js';
import { loadDictionary } from './dictionary.js';
import { resolve, run } from './search.js';
import { createUI } from './ui.js';

const DEFAULT_DICTIONARY_URL = '../dictionary/out/parole-accenti-frequenze.csv';
const DEFAULT_ATTRIBUTION_URL = '../dictionary/out/ATTRIBUTION.md';
const PREFS_KEY = 'superRimario.filters.v1';
const DEFAULT_PREFS = Object.freeze({ proper: true, archaic: false, vulgar: false });

const MSG_LOAD_FAILED = 'Non è stato possibile scaricare il dizionario. Controlla la connessione e riprova.';
const MSG_UNEXPECTED = 'Si è verificato un errore imprevisto. Ricarica la pagina e riprova.';

/* ---------- Config ---------- */

/**
 * Reads the injection points (data attributes) of the root element.
 * @param {HTMLElement} root
 */
function readConfig(root) {
    const data = root.dataset;
    const bytes = Number.parseInt(data.dictionaryBytes ?? '', 10);
    const baseTitle = document.title;
    return {
        dictionaryUrl: data.dictionaryUrl || DEFAULT_DICTIONARY_URL,
        attributionUrl: data.attributionUrl || DEFAULT_ATTRIBUTION_URL,
        expectedBytes: Number.isFinite(bytes) && bytes > 0 ? bytes : null,
        baseTitle,
        titleSuffix: (data.titleSuffix || baseTitle).trim(),
    };
}

/* ---------- Preferences ---------- */

/** @returns {{ proper: boolean, archaic: boolean, vulgar: boolean }} */
function loadPrefs() {
    const prefs = { ...DEFAULT_PREFS };
    try {
        const raw = window.localStorage.getItem(PREFS_KEY);
        const stored = raw ? JSON.parse(raw) : null;
        if (stored && typeof stored === 'object') {
            for (const key of Object.keys(DEFAULT_PREFS)) {
                if (typeof stored[key] === 'boolean') prefs[key] = stored[key];
            }
        }
    } catch {
        // Storage unavailable or corrupted: defaults.
    }
    return prefs;
}

function savePrefs(prefs) {
    try {
        window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch {
        // Storage unavailable (private mode, quota, blocked): ignore.
    }
}

/** Flags of the rows the current preferences hide. */
function hideFlagsOf(prefs) {
    return (prefs.proper ? 0 : FLAGS.PROPER)
        | (prefs.archaic ? 0 : FLAGS.ARCHAIC)
        | (prefs.vulgar ? 0 : FLAGS.VULGAR);
}

/* ---------- URL helpers ---------- */

/** The current ?q= value, or null when absent or empty. */
function currentQ() {
    return new URLSearchParams(window.location.search).get('q') || null;
}

/** The current URL with ?q= set to term (or removed when term is null); hash dropped. */
function urlWithQ(term) {
    const url = new URL(window.location.href);
    url.hash = '';
    if (term === null) url.searchParams.delete('q');
    else url.searchParams.set('q', term);
    return url.href;
}

/* ---------- App ---------- */

function boot() {
    const root = document.getElementById('rimario');
    if (!root || root.dataset.sriBooted) return;
    root.dataset.sriBooted = 'true';

    const holder = { ui: null };
    try {
        start(root, holder);
    } catch (error) {
        console.error('Super Rimario: boot failed', error);
        holder.ui?.showFatal(MSG_UNEXPECTED, false);
    }
}

/**
 * Wires everything together.
 * @param {HTMLElement} root
 * @param {{ ui: object|null }} holder receives the ui as soon as it exists (so boot can report errors)
 */
function start(root, holder) {
    const config = readConfig(root);
    let prefs = loadPrefs();

    let dict = null;          // Dictionary once loaded
    let loading = false;      // a load is in flight
    let pending = null;       // { term, source, mode } waiting for the dictionary
    let current = null;       // { term, query } of the result on screen (OK resolutions only)

    const ui = createUI(root, {
        onSearch: (term, source) => search(term, source, 'push'),
        onFiltersChange,
        onHome,
        onRetry: retry,
    });
    holder.ui = ui;

    ui.setFilters(prefs);
    ui.setAttributionUrl(config.attributionUrl);
    ui.setHomeUrl(urlWithQ(null));

    function setTitle(label) {
        if (label === null) document.title = config.baseTitle;
        else if (config.titleSuffix) document.title = `Rime con ${label} | ${config.titleSuffix}`;
        else document.title = `Rime con ${label}`;
    }

    function fail(error) {
        console.error('Super Rimario: search failed', error);
        current = null;
        ui.showFatal(MSG_UNEXPECTED, false);
    }

    /**
     * Searches term, or queues it while the dictionary is not ready.
     * @param {string} term raw text
     * @param {'form'|'chip'|'history'|'initial'} source
     * @param {'push'|'replace'|'none'} mode history handling
     */
    function search(term, source, mode) {
        if (dict) {
            execute(term, source, mode);
            return;
        }
        const cleaned = cleanQuery(term);
        if (!cleaned) {
            // Nothing searchable: answer right away, no need to wait.
            pending = null;
            setTitle(null);
            ui.showMessage({ ok: false, reason: 'empty', term: '' });
            return;
        }
        pending = { term, source, mode };
        if (loading) {
            ui.showQueued(cleaned);
        } else {
            retry();   // the previous load failed: a new search tries again
        }
    }

    function execute(term, source, mode) {
        try {
            const res = resolve(dict, term);
            if (res.term) ui.setQueryText(res.term);
            if (!res.ok) {
                current = null;
                setTitle(null);
                ui.showMessage(res);
                return;
            }
            const result = run(dict, res.query, { hideFlags: hideFlagsOf(prefs) });
            current = { term: res.term, query: res.query };
            // URL and title first, so "Condividi" picks up the new ones.
            updateHistory(res.term, mode);
            setTitle(res.query.label);
            ui.showResults(dict, result, { source, preserveView: false });
        } catch (error) {
            fail(error);
        }
    }

    function updateHistory(term, mode) {
        if (mode === 'none') return;
        const url = urlWithQ(term);
        if (mode === 'push' && currentQ() !== term) {
            window.history.pushState({ sri: true }, '', url);
        } else {
            window.history.replaceState({ sri: true }, '', url);
        }
    }

    function onFiltersChange(newPrefs) {
        prefs = newPrefs;
        savePrefs(prefs);
        if (!dict || !current) return;
        try {
            const result = run(dict, current.query, { hideFlags: hideFlagsOf(prefs) });
            ui.showResults(dict, result, { source: 'filter', preserveView: true });
        } catch (error) {
            fail(error);
        }
    }

    function showHome() {
        pending = null;
        current = null;
        ui.showIdle();
        ui.setQueryText('');
        setTitle(null);
    }

    function onHome() {
        if (new URLSearchParams(window.location.search).has('q')) {
            window.history.pushState({ sri: true }, '', urlWithQ(null));
        }
        showHome();
        ui.focusInput();
    }

    function onPopState() {
        const q = currentQ();
        if (q === null) {
            showHome();
            return;
        }
        // A popstate that doesn't change ?q= (e.g. an in-page #anchor of the theme): keep the view.
        if (current && current.term === q) return;
        ui.setQueryText(q);
        search(q, 'history', 'none');
    }

    async function load() {
        if (loading || dict) return;
        loading = true;
        ui.showLoading(0, null);
        let loaded;
        try {
            loaded = await loadDictionary(config.dictionaryUrl, {
                onProgress: ui.showLoading,
                expectedBytes: config.expectedBytes,
            });
        } catch (error) {
            console.error('Super Rimario: dictionary load failed', error);
            loading = false;
            ui.showFatal(MSG_LOAD_FAILED, true);
            return;
        }
        loading = false;
        dict = loaded;
        ui.hideLoading();
        if (pending) {
            const { term, source, mode } = pending;
            pending = null;
            execute(term, source, mode);
        }
    }

    function retry() {
        if (loading || dict) return;
        // Clear the error message; restore the idle or queued state of boot.
        ui.showIdle();
        if (pending) ui.showQueued(cleanQuery(pending.term));
        load();
    }

    window.addEventListener('popstate', onPopState);
    load();   // synchronously marks the load as in flight, so the search below is queued

    // Initial ?q= handling.
    const initialQ = currentQ();
    if (initialQ !== null) {
        ui.setQueryText(initialQ);
        search(initialQ, 'initial', 'replace');
    } else {
        ui.showIdle();
    }

    // Focus the input on desktop when the widget is visible; never on touch, never scroll.
    if (initialQ === null && window.matchMedia('(pointer: fine)').matches) {
        const top = root.getBoundingClientRect().top;
        if (top >= 0 && top < window.innerHeight) ui.focusInput();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
    boot();
}
