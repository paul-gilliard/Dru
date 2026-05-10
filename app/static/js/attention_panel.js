/**
 * Attention Panel — Coach insights for a single athlete based on quick-data.json
 *
 * Provides a 4-tab period selector (S vs S-1, S vs S-2, S-1 vs S-2, S-1 vs S-3)
 * and analyses series_by_exercise per exercise to classify each into:
 *   - regression  : at least one series has lower load OR (same load AND lower reps)
 *   - stagnation  : ALL comparable series have strictly identical load AND reps
 *   - healthy     : has progress or mixed neutral
 *   - new         : exists in current week, not in previous
 *   - abandoned   : existed in previous, not in current
 *
 * Plus body weight delta from journal data.
 *
 * Public API:
 *   AttentionPanel.render(containerEl, quickData) — renders panel into container
 */
(function (global) {
    'use strict';

    const PERIODS = [
        { key: 'S_S1',  label: 'S vs S-1',  curOffset: 0, prevOffset: 1 },
        { key: 'S_S2',  label: 'S vs S-2',  curOffset: 0, prevOffset: 2 },
        { key: 'S1_S2', label: 'S-1 vs S-2', curOffset: 1, prevOffset: 2 },
        { key: 'S1_S3', label: 'S-1 vs S-3', curOffset: 1, prevOffset: 3 },
    ];

    // --- Date helpers ---
    function getMonday(d) {
        const dd = new Date(d);
        const day = dd.getDay();
        const diff = dd.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(dd.setDate(diff));
    }
    function addDays(d, n) { return new Date(new Date(d).setDate(d.getDate() + n)); }
    function iso(d) { return d.toISOString().split('T')[0]; }

    function getWeekBounds(weekOffset) {
        // weekOffset 0 = current week, 1 = last week, etc.
        const monday = getMonday(new Date());
        const start = addDays(monday, -7 * weekOffset);
        const end   = addDays(start, 6);
        return { start: iso(start), end: iso(end) };
    }

    /**
     * Get the LAST session date (string) of an exercise within a week range.
     * Returns null if no session in that range.
     */
    function getLastSessionDate(seriesByDate, weekStart, weekEnd) {
        const dates = Object.keys(seriesByDate)
            .filter(d => d >= weekStart && d <= weekEnd)
            .sort();
        return dates.length ? dates[dates.length - 1] : null;
    }

    /**
     * Compare two arrays of series (same exercise, two different sessions).
     * Returns one of: 'regression' | 'stagnation' | 'healthy'
     *
     * Pairs by series_number (S1 vs S1, S2 vs S2...). Ignores series numbers
     * that only exist in one of the two sessions (no pair to compare).
     *
     * Rule:
     *   regression : ANY pair where curLoad < prevLoad OR (curLoad == prevLoad AND curReps < prevReps)
     *   stagnation : EVERY pair has curLoad == prevLoad AND curReps == prevReps
     *   healthy    : everything else (progression or mixed neutral)
     */
    function classifyExercise(curSeries, prevSeries) {
        // Build maps by series_number
        const curBy  = {};
        const prevBy = {};
        curSeries.forEach(s => { if (s.series_number != null) curBy[s.series_number] = s; });
        prevSeries.forEach(s => { if (s.series_number != null) prevBy[s.series_number] = s; });

        const commonNums = Object.keys(curBy).filter(n => prevBy[n]);
        if (commonNums.length === 0) {
            // No paired series — treat as healthy by default (we can't say)
            return 'healthy';
        }

        let allEqual = true;
        let hasRegression = false;

        for (const num of commonNums) {
            const c = curBy[num];
            const p = prevBy[num];
            const cLoad = c.load == null ? null : Number(c.load);
            const pLoad = p.load == null ? null : Number(p.load);
            const cReps = c.reps == null ? null : Number(c.reps);
            const pReps = p.reps == null ? null : Number(p.reps);

            // Skip incomplete pairs
            if (cLoad == null || pLoad == null || cReps == null || pReps == null) continue;

            // Equality check (strict)
            const sameLoad = cLoad === pLoad;
            const sameReps = cReps === pReps;
            if (!sameLoad || !sameReps) allEqual = false;

            // Regression check
            if (cLoad < pLoad) hasRegression = true;
            else if (sameLoad && cReps < pReps) hasRegression = true;
        }

        if (hasRegression) return 'regression';
        if (allEqual) return 'stagnation';
        return 'healthy';
    }

    /**
     * Analyse all exercises for a given period.
     * Returns { regression: [...], stagnation: [...], healthy: [...], new: [...], abandoned: [...] }
     */
    function analyse(quickData, period) {
        const seriesByEx = quickData.series_by_exercise || {};
        const cur  = getWeekBounds(period.curOffset);
        const prev = getWeekBounds(period.prevOffset);

        const buckets = { regression: [], stagnation: [], healthy: [], new: [], abandoned: [] };

        for (const [exName, seriesByDate] of Object.entries(seriesByEx)) {
            const curDate  = getLastSessionDate(seriesByDate, cur.start,  cur.end);
            const prevDate = getLastSessionDate(seriesByDate, prev.start, prev.end);

            if (!curDate && !prevDate) continue; // not active in either week
            if (curDate && !prevDate) { buckets.new.push(exName); continue; }
            if (!curDate && prevDate) { buckets.abandoned.push(exName); continue; }

            const verdict = classifyExercise(seriesByDate[curDate], seriesByDate[prevDate]);
            buckets[verdict].push(exName);
        }

        // Sort all buckets alphabetically
        Object.keys(buckets).forEach(k => buckets[k].sort());
        return buckets;
    }

    /**
     * Body weight comparison for a period.
     */
    function bodyWeightAnalyse(quickData, period) {
        // Map period key to summary key
        const key = {
            'S_S1':  'summary_7days',
            'S_S2':  'summary_14days',
            'S1_S2': 'summary_21days',
            'S1_S3': 'summary_28days',
        }[period.key];
        const summary = quickData[key] || {};
        return {
            current:  summary.weight_current,
            previous: summary.weight_previous,
            diff:     summary.weight_diff,
        };
    }

    function bwBadge(bw) {
        if (bw.diff == null || bw.current == null) {
            return `<span style="color:#94a3b8;">Pas de donnée poids corporel</span>`;
        }
        const diff = Number(bw.diff);
        const cur  = Number(bw.current).toFixed(1);
        const prev = bw.previous != null ? Number(bw.previous).toFixed(1) : '—';
        if (diff > 0.1)  return `<span style="color:#0369a1;font-weight:700;">↑ +${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        if (diff < -0.1) return `<span style="color:#b91c1c;font-weight:700;">↓ ${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        return `<span style="color:#475569;font-weight:600;">→ Stable (${cur} kg)</span>`;
    }

    // --- Render ---

    function buildExoList(items, color) {
        if (!items.length) return `<div style="color:#94a3b8;font-size:0.78rem;font-style:italic;">Aucun</div>`;
        return items.map(name =>
            `<span style="display:inline-block;background:${color};color:#fff;border-radius:4px;padding:2px 8px;margin:2px 3px 2px 0;font-size:0.75rem;font-weight:600;">${name}</span>`
        ).join('');
    }

    function renderPanelContent(quickData, period) {
        const bw = bodyWeightAnalyse(quickData, period);
        const ex = analyse(quickData, period);

        const rows = [
            { icon: '⚖️', label: 'Poids corporel',     bg: '#eff6ff', borderColor: '#3b82f6', content: bwBadge(bw) },
            { icon: '🔴', label: `Régressions (${ex.regression.length})`, bg: '#fef2f2', borderColor: '#ef4444', content: buildExoList(ex.regression, '#ef4444') },
            { icon: '🟠', label: `Stagnations (${ex.stagnation.length})`, bg: '#fffbeb', borderColor: '#f59e0b', content: buildExoList(ex.stagnation, '#f59e0b') },
            { icon: '🟢', label: `En bonne santé (${ex.healthy.length})`, bg: '#f0fdf4', borderColor: '#10b981', content: buildExoList(ex.healthy, '#10b981') },
        ];
        if (ex.new.length) {
            rows.push({ icon: '🆕', label: `Nouveaux (${ex.new.length})`, bg: '#eef2ff', borderColor: '#6366f1', content: buildExoList(ex.new, '#6366f1') });
        }
        if (ex.abandoned.length) {
            rows.push({ icon: '🚫', label: `Abandonnés (${ex.abandoned.length})`, bg: '#f1f5f9', borderColor: '#64748b', content: buildExoList(ex.abandoned, '#64748b') });
        }

        return rows.map(r => `
            <div style="background:${r.bg};border-left:3px solid ${r.borderColor};border-radius:4px;padding:8px 10px;margin-bottom:6px;">
                <div style="font-weight:700;font-size:0.78rem;color:#1e293b;margin-bottom:4px;">${r.icon} ${r.label}</div>
                <div style="line-height:1.6;">${r.content}</div>
            </div>
        `).join('');
    }

    function render(container, quickData) {
        if (!container) return;
        if (!quickData || !quickData.series_by_exercise) {
            container.innerHTML = '<div style="color:#94a3b8;font-size:0.85rem;">Données non disponibles</div>';
            return;
        }

        // Unique ID prefix to avoid clashes when multiple panels coexist (bilan-hebdo)
        const uid = 'ap_' + Math.random().toString(36).slice(2, 9);

        const tabsHtml = PERIODS.map((p, i) => `
            <button type="button" data-period="${p.key}"
                class="${uid}-tab" style="
                    flex:1;padding:6px 4px;border:none;cursor:pointer;
                    background:${i === 0 ? '#667eea' : '#f1f5f9'};
                    color:${i === 0 ? '#fff' : '#475569'};
                    font-size:0.72rem;font-weight:700;
                    border-radius:6px;transition:all 0.15s;">
                ${p.label}
            </button>
        `).join('');

        container.innerHTML = `
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:1.1rem;">🎯</span>
                    <h4 style="margin:0;font-size:0.95rem;font-weight:700;color:#1e293b;">Points d'attention coach</h4>
                </div>
                <div style="display:flex;gap:4px;margin-bottom:10px;" id="${uid}-tabs">${tabsHtml}</div>
                <div id="${uid}-content"></div>
            </div>
        `;

        const contentEl = container.querySelector(`#${uid}-content`);
        const tabBtns   = container.querySelectorAll(`.${uid}-tab`);

        function activate(periodKey) {
            tabBtns.forEach(btn => {
                const active = btn.dataset.period === periodKey;
                btn.style.background = active ? '#667eea' : '#f1f5f9';
                btn.style.color      = active ? '#fff'    : '#475569';
            });
            const period = PERIODS.find(p => p.key === periodKey) || PERIODS[0];
            contentEl.innerHTML = renderPanelContent(quickData, period);
        }

        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => activate(btn.dataset.period));
        });

        // Initial render with first period
        activate(PERIODS[0].key);
    }

    global.AttentionPanel = { render };
})(window);
