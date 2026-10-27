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

// All DOM rendering and DOM event handling. Binds to the markup contract of
// index.html (#rimario and its sri-* ids/classes) and talks to app.js only
// through the handlers passed to createUI and the returned ui object.

import { FLAGS } from './text.js';

// Same order as search.js CATEGORIES (tab/column order).
const CATEGORY_IDS = ['rhymes', 'atonal', 'assonances', 'consonances'];

const PAGE_SIZE = 100;
const SWIPE_MIN_DX = 60;
const SWIPE_RATIO = 1.5;
const COPIED_MS = 2000;
const LIVE_DELAY_MS = 100;
const BYTES_PER_MB = 1e6;

const TEXT = {
    loading: 'Caricamento del dizionario…',
    preparing: 'Preparazione del dizionario…',
    queued: (term) => `La ricerca di «${term}» partirà appena il dizionario è pronto.`,
    empty: 'Scrivi una parola per cercarne le rime.',
    notFound: (term) => `«${term}» non è nel dizionario. Dove cade l'accento?`,
    notFoundHint: "Puoi anche scriverla con l'accento, es. italiàno.",
    retry: 'Riprova',
    noteUnknownWord: "Questa parola non è nel dizionario: uso l'accento che hai indicato.",
    noteUnknownReading: "Il dizionario non conosce questa lettura: uso l'accento che hai indicato.",
    notePredicted: "L'accento di questa parola è stimato automaticamente e potrebbe essere sbagliato.",
    noteSkipped: 'La terminazione è troppo lunga: mostro solo le rime.',
    skipped: 'Terminazione troppo lunga per questa ricerca.',
    skippedCount: '–',
    groupsLabel: 'Differenze',
    predictedTitle: 'Accento stimato automaticamente: potrebbe essere sbagliato',
    predictedVh: ' (accento stimato)',
    copied: 'Link copiato',
    copiedAnnounce: 'Link copiato negli appunti',
    copyPrompt: 'Copia il link:',
};

const EMPTY_TEXT = {
    rhymes: 'Nessuna rima trovata.',
    atonal: 'Nessuna assonanza atona trovata.',
    assonances: 'Nessuna assonanza trovata.',
    consonances: 'Nessuna consonanza trovata.',
};

// [singular, plural] for the live-region summary.
const NOUNS = {
    rhymes: ['rima', 'rime'],
    atonal: ['assonanza atona', 'assonanze atone'],
    assonances: ['assonanza', 'assonanze'],
    consonances: ['consonanza', 'consonanze'],
};

const numberFormat = new Intl.NumberFormat('it-IT');
const mbFormat = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function fmt(n) {
    return numberFormat.format(n);
}

function fmtMB(bytes) {
    return `${mbFormat.format(bytes / BYTES_PER_MB)} MB`;
}

function countNoun(cat, n) {
    const [one, many] = NOUNS[cat];
    return `${fmt(n)} ${n === 1 ? one : many}`;
}

function matches(query) {
    return typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/**
 * Builds the view on top of the #rimario markup.
 *
 * @param {HTMLElement} root The #rimario element.
 * @param {{
 *     onSearch: (term: string, source: 'form' | 'chip') => void,
 *     onFiltersChange: (prefs: { proper: boolean, archaic: boolean, vulgar: boolean }) => void,
 *     onHome: () => void,
 *     onRetry: () => void,
 * }} handlers Callbacks provided by app.js.
 * @returns {object} Plain object of closures (see the plan, §2.4).
 */
export function createUI(root, handlers) {
    const byId = (id) => {
        const node = root.querySelector(`#${id}`);
        if (!node) throw new Error(`Rimario: elemento #${id} mancante`);
        return node;
    };

    const form = byId('sri-search');
    const input = byId('sri-input');
    const clearBtn = byId('sri-clear');
    const loading = byId('sri-loading');
    const loadingLabel = byId('sri-loading-label');
    const progress = byId('sri-progress');
    const loadingDetail = byId('sri-loading-detail');
    const message = byId('sri-message');
    const idle = byId('sri-idle');
    const results = byId('sri-results');
    const queryHeading = byId('sri-query-heading');
    const queryWord = byId('sri-query-word');
    const shareBtn = byId('sri-share');
    const shareLabel = shareBtn.querySelector('.sri-share-label');
    const readings = byId('sri-readings');
    const readingsList = byId('sri-readings-list');
    const notes = byId('sri-notes');
    const hiddenNote = byId('sri-hidden-note');
    const tabsEl = byId('sri-tabs');
    const panelsEl = byId('sri-panels');
    const live = byId('sri-live');
    const filterInputs = Array.from(root.querySelectorAll('input[data-pref]'));

    const cats = {};
    for (const cat of CATEGORY_IDS) {
        const tab = byId(`sri-tab-${cat}`);
        const panel = byId(`sri-panel-${cat}`);
        cats[cat] = {
            tab,
            panel,
            tabCount: tab.querySelector('[data-count]'),
            panelCount: panel.querySelector('[data-count]'),
            groupsEl: panel.querySelector('[data-groups]'),
            wordsEl: panel.querySelector('[data-words]'),
            emptyEl: panel.querySelector('[data-empty]'),
            moreEl: panel.querySelector('[data-more]'),
        };
    }

    const shareLabelText = shareLabel ? shareLabel.textContent : '';
    const reducedMotion = matches('(prefers-reduced-motion: reduce)');
    const scrollBehavior = reducedMotion ? 'auto' : 'smooth';

    // View state.
    let current = null;          // { dict, result } of the results on screen
    let view = null;             // { activeTab, group: {cat: g}, shown: {cat: n} }
    let queuedTerm = null;       // term shown in the loading label while waiting
    let fatal = false;
    let liveTimer = 0;
    let copiedTimer = 0;
    let touchStart = null;

    // ---- generic helpers ------------------------------------------------

    function refreshState() {
        let state;
        if (fatal) state = 'fatal';
        else if (!results.hidden) state = 'results';
        else if (!message.hidden) state = 'message';
        else if (!loading.hidden) state = 'loading';
        else state = 'idle';
        root.dataset.state = state;
    }

    function announce(text) {
        clearTimeout(liveTimer);
        live.textContent = '';
        // Re-setting after a short delay makes screen readers repeat identical text.
        liveTimer = setTimeout(() => { live.textContent = text; }, LIVE_DELAY_MS);
    }

    function updateClearButton() {
        clearBtn.hidden = input.value === '';
    }

    function setQueryText(text) {
        input.value = text ?? '';
        updateClearButton();
    }

    function focusInput() {
        input.focus({ preventScroll: true });
    }

    function hideMessage() {
        message.hidden = true;
        message.replaceChildren();
        fatal = false;
    }

    function renderMessage(kind, children) {
        message.dataset.kind = kind;
        message.replaceChildren(...children);
        message.hidden = false;
    }

    // ---- loading ----------------------------------------------------------

    function showLoading(loaded, total) {
        if (fatal) hideMessage();
        loading.hidden = false;

        const known = typeof total === 'number' && total > 0;
        if (queuedTerm === null) {
            loadingLabel.textContent = known && loaded >= total ? TEXT.preparing : TEXT.loading;
        }

        if (known) {
            const fraction = Math.min(1, Math.max(0, loaded / total));
            progress.removeAttribute('data-indeterminate');
            progress.style.setProperty('--sri-progress', String(fraction));
            progress.setAttribute('aria-valuenow', String(Math.round(fraction * 100)));
            loadingDetail.textContent = `${fmtMB(loaded)} di ${fmtMB(total)}`;
        } else {
            progress.setAttribute('data-indeterminate', '');
            progress.style.removeProperty('--sri-progress');
            progress.removeAttribute('aria-valuenow');
            loadingDetail.textContent = loaded > 0 ? fmtMB(loaded) : '';
        }
        if (loadingDetail.textContent) progress.setAttribute('aria-valuetext', loadingDetail.textContent);
        else progress.removeAttribute('aria-valuetext');

        refreshState();
    }

    function hideLoading() {
        loading.hidden = true;
        queuedTerm = null;
        loadingLabel.textContent = TEXT.loading;
        refreshState();
    }

    function showQueued(term) {
        queuedTerm = term;
        loadingLabel.textContent = TEXT.queued(term);
        loading.hidden = false;
        idle.hidden = true;
        hideMessage();
        refreshState();
    }

    // ---- idle / messages ----------------------------------------------------

    function showIdle() {
        hideMessage();
        results.hidden = true;
        idle.hidden = false;
        refreshState();
    }

    function showFatal(text, canRetry) {
        loading.hidden = true;
        queuedTerm = null;
        results.hidden = true;
        idle.hidden = true;
        const children = [el('p', 'sri-message-text', text)];
        if (canRetry) {
            const btn = el('button', 'sri-button sri-retry', TEXT.retry);
            btn.type = 'button';
            children.push(btn);
        }
        renderMessage('error', children);
        fatal = true;
        refreshState();
        announce(text);
    }

    function showMessage(resolution) {
        results.hidden = true;
        idle.hidden = true;
        fatal = false;
        const children = [];
        let spoken;
        if (resolution && resolution.reason === 'not-found') {
            const head = TEXT.notFound(resolution.term);
            children.push(el('p', 'sri-message-text', head));
            const candidates = resolution.candidates || [];
            if (candidates.length > 0) {
                const list = el('ul', 'sri-chips sri-candidates');
                list.setAttribute('role', 'list');
                for (const candidate of candidates) {
                    const btn = el('button', 'sri-chip sri-candidate', candidate);
                    btn.type = 'button';
                    btn.dataset.q = candidate;
                    const li = el('li');
                    li.append(btn);
                    list.append(li);
                }
                children.push(list);
            }
            children.push(el('p', 'sri-message-text', TEXT.notFoundHint));
            spoken = `${head} ${candidates.join(', ')}`.trim();
        } else {
            children.push(el('p', 'sri-message-text', TEXT.empty));
            spoken = TEXT.empty;
        }
        renderMessage('info', children);
        refreshState();
        announce(spoken);
    }

    // ---- results ------------------------------------------------------------

    function groupsOf(cat) {
        return current.result.groups[cat] || [];
    }

    function firstNonEmptyGroup(cat) {
        const index = groupsOf(cat).findIndex((g) => g.length > 0);
        return index < 0 ? 0 : index;
    }

    function computeView(preserve) {
        const { totals } = current.result;
        const old = preserve ? view : null;
        const next = { activeTab: 'rhymes', group: {}, shown: {} };

        if (old && totals[old.activeTab] > 0) {
            next.activeTab = old.activeTab;
        } else {
            next.activeTab = CATEGORY_IDS.find((cat) => totals[cat] > 0) || 'rhymes';
        }

        for (const cat of CATEGORY_IDS) {
            const groups = groupsOf(cat);
            const oldGroup = old ? old.group[cat] : undefined;
            if (oldGroup !== undefined && groups[oldGroup] && groups[oldGroup].length > 0) {
                next.group[cat] = oldGroup;
                next.shown[cat] = Math.max(PAGE_SIZE, old.shown[cat] || 0);
            } else {
                next.group[cat] = firstNonEmptyGroup(cat);
                next.shown[cat] = PAGE_SIZE;
            }
        }
        view = next;
    }

    function wordChip(dict, row) {
        const btn = el('button', 'sri-chip sri-word', dict.displayWord(row));
        btn.type = 'button';
        btn.dataset.q = dict.queryTerm(row);
        if (dict.flags(row) & FLAGS.PREDICTED) {
            btn.classList.add('sri-word--predicted');
            btn.title = TEXT.predictedTitle;
            btn.append(el('span', 'sri-vh', TEXT.predictedVh));
        }
        const li = el('li');
        li.append(btn);
        return li;
    }

    function renderReadings() {
        const { dict, result } = current;
        const { row, readings: rows } = result.query;
        const show = rows.length > 1 || (row === -1 && rows.length > 0);
        readingsList.replaceChildren();
        readings.hidden = !show;
        if (!show) return;

        const byTerm = new Map();   // queryTerm → { row, pressed }
        for (const r of rows) {
            const term = dict.queryTerm(r);
            const entry = byTerm.get(term);
            if (entry) entry.pressed = entry.pressed || r === row;
            else byTerm.set(term, { row: r, pressed: r === row });
        }
        const fragment = document.createDocumentFragment();
        for (const [term, entry] of byTerm) {
            const btn = el('button', 'sri-chip sri-reading', dict.displayWord(entry.row));
            btn.type = 'button';
            btn.dataset.q = term;
            btn.setAttribute('aria-pressed', String(entry.pressed));
            const li = el('li');
            li.append(btn);
            fragment.append(li);
        }
        readingsList.append(fragment);
    }

    function renderNotes() {
        const { query, imperfectSkipped } = current.result;
        const texts = [];
        if (query.row === -1 && query.readings.length === 0) texts.push(TEXT.noteUnknownWord);
        if (query.row === -1 && query.readings.length > 0) texts.push(TEXT.noteUnknownReading);
        if (query.predicted) texts.push(TEXT.notePredicted);
        if (imperfectSkipped) texts.push(TEXT.noteSkipped);
        notes.replaceChildren(...texts.map((t) => el('li', 'sri-note', t)));
        notes.hidden = texts.length === 0;
    }

    function renderHiddenNote() {
        const n = current.result.hidden || 0;
        if (n === 0) hiddenNote.textContent = '';
        else if (n === 1) hiddenNote.textContent = '1 parola nascosta dai filtri';
        else hiddenNote.textContent = `${fmt(n)} parole nascoste dai filtri`;
    }

    function updateTabs() {
        for (const cat of CATEGORY_IDS) {
            const { tab, panel } = cats[cat];
            const selected = cat === view.activeTab;
            tab.setAttribute('aria-selected', String(selected));
            tab.tabIndex = selected ? 0 : -1;
            panel.toggleAttribute('data-active', selected);
        }
    }

    function isSkipped(cat) {
        return current.result.imperfectSkipped && cat !== 'rhymes';
    }

    function renderGroups(cat) {
        const { groupsEl } = cats[cat];
        const groups = groupsOf(cat);
        const total = current.result.totals[cat];
        groupsEl.replaceChildren();
        if (groups.length < 2 || total === 0 || isSkipped(cat)) {
            groupsEl.hidden = true;
            return;
        }
        const fragment = document.createDocumentFragment();
        fragment.append(el('span', 'sri-groups-label', TEXT.groupsLabel));
        groups.forEach((rows, g) => {
            const n = rows.length;
            const btn = el('button', 'sri-group');
            btn.type = 'button';
            btn.dataset.group = String(g);
            btn.setAttribute('aria-pressed', String(g === view.group[cat]));
            btn.setAttribute('aria-label',
                `${g + 1} differenz${g === 0 ? 'a' : 'e'}: ${fmt(n)} ${n === 1 ? 'risultato' : 'risultati'}`);
            btn.disabled = n === 0;
            btn.append(el('span', 'sri-group-n', String(g + 1)), el('span', 'sri-count', fmt(n)));
            fragment.append(btn);
        });
        groupsEl.append(fragment);
        groupsEl.hidden = false;
    }

    function updateGroupPressed(cat) {
        for (const btn of cats[cat].groupsEl.querySelectorAll('.sri-group')) {
            btn.setAttribute('aria-pressed', String(Number(btn.dataset.group) === view.group[cat]));
        }
    }

    function selectedRows(cat) {
        return groupsOf(cat)[view.group[cat]] || [];
    }

    function updateMore(cat) {
        const { moreEl } = cats[cat];
        const remaining = selectedRows(cat).length - view.shown[cat];
        if (remaining > 0) {
            moreEl.textContent = `Mostra altre ${fmt(Math.min(PAGE_SIZE, remaining))} (rimangono ${fmt(remaining)})`;
            moreEl.hidden = false;
        } else {
            moreEl.textContent = '';
            moreEl.hidden = true;
        }
    }

    function renderWords(cat) {
        const { wordsEl, emptyEl } = cats[cat];
        const { dict } = current;
        const rows = selectedRows(cat);
        const end = Math.min(rows.length, view.shown[cat]);
        const fragment = document.createDocumentFragment();
        for (let i = 0; i < end; i++) fragment.append(wordChip(dict, rows[i]));
        wordsEl.replaceChildren(fragment);
        wordsEl.hidden = end === 0;

        let empty = '';
        if (isSkipped(cat)) empty = TEXT.skipped;
        else if (rows.length === 0) empty = EMPTY_TEXT[cat];
        emptyEl.textContent = empty;
        emptyEl.hidden = empty === '';

        updateMore(cat);
    }

    function renderPanel(cat) {
        const { tabCount, panelCount } = cats[cat];
        const text = isSkipped(cat) ? TEXT.skippedCount : fmt(current.result.totals[cat]);
        if (tabCount) tabCount.textContent = text;
        if (panelCount) panelCount.textContent = text;
        renderGroups(cat);
        renderWords(cat);
    }

    function showMore(cat) {
        const { wordsEl } = cats[cat];
        const { dict } = current;
        const rows = selectedRows(cat);
        const start = Math.min(rows.length, view.shown[cat]);
        const end = Math.min(rows.length, start + PAGE_SIZE);
        if (end <= start) return;
        const fragment = document.createDocumentFragment();
        for (let i = start; i < end; i++) fragment.append(wordChip(dict, rows[i]));
        const first = fragment.firstElementChild;
        wordsEl.append(fragment);
        wordsEl.hidden = false;
        view.shown[cat] = start + PAGE_SIZE;
        updateMore(cat);
        first?.querySelector('button')?.focus();
    }

    function selectGroup(cat, g) {
        if (!current || view.group[cat] === g) return;
        view.group[cat] = g;
        view.shown[cat] = PAGE_SIZE;
        updateGroupPressed(cat);
        renderWords(cat);
    }

    function summary() {
        const { query, totals, imperfectSkipped } = current.result;
        if (imperfectSkipped) {
            return `Rime con ${query.label}: ${countNoun('rhymes', totals.rhymes)}; assonanze e consonanze non calcolate.`;
        }
        const parts = CATEGORY_IDS.map((cat) => countNoun(cat, totals[cat]));
        return `Rime con ${query.label}: ${parts.join(', ')}.`;
    }

    function showResults(dict, result, { source, preserveView } = {}) {
        current = { dict, result };
        hideMessage();
        idle.hidden = true;
        results.hidden = false;

        queryWord.textContent = result.query.label;
        renderReadings();
        renderNotes();
        renderHiddenNote();

        computeView(Boolean(preserveView) && view !== null);
        updateTabs();
        for (const cat of CATEGORY_IDS) renderPanel(cat);

        refreshState();
        announce(summary());

        if (source === 'chip') {
            root.scrollIntoView({ block: 'start', behavior: scrollBehavior });
            queryHeading.focus({ preventScroll: true });
        } else if (source === 'form') {
            if (matches('(pointer: coarse)')) input.blur();
        }
    }

    // ---- tabs -----------------------------------------------------------------

    function tabsVisible() {
        return getComputedStyle(tabsEl).display !== 'none';
    }

    function selectTab(cat, focus) {
        if (!current || !cats[cat]) return;
        view.activeTab = cat;
        updateTabs();
        if (focus) cats[cat].tab.focus();
        if (panelsEl.getBoundingClientRect().top < 0) panelsEl.scrollIntoView({ block: 'start' });
    }

    tabsEl.addEventListener('keydown', (event) => {
        const tab = event.target.closest('.sri-tab');
        if (!tab || !current) return;
        const n = CATEGORY_IDS.length;
        const i = CATEGORY_IDS.indexOf(tab.dataset.cat);
        let next;
        switch (event.key) {
            case 'ArrowRight': next = (i + 1) % n; break;
            case 'ArrowLeft': next = (i - 1 + n) % n; break;
            case 'Home': next = 0; break;
            case 'End': next = n - 1; break;
            default: return;
        }
        event.preventDefault();
        selectTab(CATEGORY_IDS[next], true);
    });

    panelsEl.addEventListener('touchstart', (event) => {
        touchStart = event.touches.length === 1
            ? { x: event.touches[0].clientX, y: event.touches[0].clientY }
            : null;
    }, { passive: true });

    panelsEl.addEventListener('touchend', (event) => {
        const start = touchStart;
        touchStart = null;
        if (!start || !current || results.hidden || event.changedTouches.length === 0) return;
        if (!tabsVisible()) return;
        const touch = event.changedTouches[0];
        const dx = touch.clientX - start.x;
        const dy = touch.clientY - start.y;
        if (Math.abs(dx) < SWIPE_MIN_DX || Math.abs(dx) <= SWIPE_RATIO * Math.abs(dy)) return;
        const i = CATEGORY_IDS.indexOf(view.activeTab);
        const next = dx < 0 ? i + 1 : i - 1;   // swipe left → next tab
        if (next < 0 || next >= CATEGORY_IDS.length) return;
        selectTab(CATEGORY_IDS[next], false);
    }, { passive: true });

    panelsEl.addEventListener('touchcancel', () => { touchStart = null; }, { passive: true });

    // ---- share ------------------------------------------------------------------

    function legacyCopy(text) {
        const previous = document.activeElement;
        const area = el('textarea', 'sri-vh');
        area.value = text;
        area.setAttribute('readonly', '');
        area.setAttribute('aria-hidden', 'true');
        area.tabIndex = -1;
        root.append(area);
        let ok = false;
        try {
            area.select();
            area.setSelectionRange(0, text.length);
            ok = document.execCommand('copy');
        } catch {
            ok = false;
        }
        area.remove();
        if (previous && typeof previous.focus === 'function') previous.focus({ preventScroll: true });
        return ok;
    }

    async function copyText(text) {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch {
                // fall through to the legacy path
            }
        }
        return legacyCopy(text);
    }

    function showCopied() {
        if (shareLabel) {
            shareLabel.textContent = TEXT.copied;
            clearTimeout(copiedTimer);
            copiedTimer = setTimeout(() => { shareLabel.textContent = shareLabelText; }, COPIED_MS);
        }
        announce(TEXT.copiedAnnounce);
    }

    async function share() {
        const url = location.href;
        const data = { title: document.title, url };
        if (typeof navigator.share === 'function' && navigator.canShare?.(data) !== false) {
            try {
                await navigator.share(data);
                return;
            } catch (err) {
                if (err && err.name === 'AbortError') return;
            }
        }
        if (await copyText(url)) showCopied();
        else window.prompt(TEXT.copyPrompt, url);
    }

    // ---- events -------------------------------------------------------------------

    root.addEventListener('click', (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) return;

        const home = target.closest('[data-sri-home]');
        if (home) {
            const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
            if (event.button === 0 && !modified) {
                event.preventDefault();
                handlers.onHome();
            }
            return;
        }

        const chip = target.closest('[data-q]');
        if (chip) {
            const term = chip.dataset.q;
            setQueryText(term);
            handlers.onSearch(term, 'chip');
            return;
        }

        const groupBtn = target.closest('.sri-group');
        if (groupBtn) {
            const panel = groupBtn.closest('.sri-panel');
            if (panel) selectGroup(panel.dataset.cat, Number(groupBtn.dataset.group));
            return;
        }

        const more = target.closest('[data-more]');
        if (more) {
            const panel = more.closest('.sri-panel');
            if (panel && current) showMore(panel.dataset.cat);
            return;
        }

        const tab = target.closest('.sri-tab');
        if (tab) {
            selectTab(tab.dataset.cat, false);
            return;
        }

        if (target.closest('#sri-share')) {
            share();
            return;
        }

        if (target.closest('#sri-clear')) {
            setQueryText('');
            focusInput();
            return;
        }

        if (target.closest('#sri-top')) {
            root.scrollIntoView({ block: 'start', behavior: scrollBehavior });
            focusInput();
            return;
        }

        if (target.closest('.sri-retry')) {
            handlers.onRetry();
        }
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        handlers.onSearch(input.value, 'form');
    });

    input.addEventListener('input', updateClearButton);

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && input.value !== '') {
            event.preventDefault();
            setQueryText('');
        }
    });

    root.addEventListener('change', (event) => {
        if (!(event.target instanceof Element) || !event.target.matches('input[data-pref]')) return;
        const prefs = { proper: false, archaic: false, vulgar: false };
        for (const box of filterInputs) {
            if (box.dataset.pref in prefs) prefs[box.dataset.pref] = box.checked;
        }
        handlers.onFiltersChange(prefs);
    });

    // ---- public API ---------------------------------------------------------------

    function setFilters(prefs) {
        for (const box of filterInputs) {
            box.checked = Boolean(prefs && prefs[box.dataset.pref]);
        }
    }

    function setAttributionUrl(url) {
        for (const link of root.querySelectorAll('[data-sri-attribution]')) link.href = url;
    }

    function setHomeUrl(url) {
        for (const link of root.querySelectorAll('[data-sri-home]')) link.href = url;
    }

    updateClearButton();

    return {
        showLoading,
        hideLoading,
        showQueued,
        showIdle,
        showFatal,
        showMessage,
        showResults,
        setFilters,
        setQueryText,
        setAttributionUrl,
        setHomeUrl,
        focusInput,
    };
}
