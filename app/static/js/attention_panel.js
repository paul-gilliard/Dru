/**
 * Attention Panel â€” Coach insights for a single athlete based on quick-data.json
 *
 * Clickable exercise pills show a series-by-series comparison detail explaining
 * exactly why the exercise was classified regression / stagnation / progress.
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
        const monday = getMonday(new Date());
        const start = addDays(monday, -7 * weekOffset);
        const end   = addDays(start, 6);
        return { start: iso(start), end: iso(end) };
    }

    function getLastSessionDate(seriesByDate, weekStart, weekEnd) {
        const dates = Object.keys(seriesByDate)
            .filter(d => d >= weekStart && d <= weekEnd)
            .sort();
        return dates.length ? dates[dates.length - 1] : null;
    }

    /**
     * Classify an exercise and return rich detail for each series pair.
     * Returns { verdict, curDate, prevDate, rows, unpaired }
     *   rows: [{ num, cLoad, cReps, pLoad, pReps, rowVerdict }]
     *     rowVerdict: 'regression' | 'progress' | 'same' | 'incomplete'
     *   unpaired: { cur: [...series], prev: [...series] }
     */
    function classifyExercise(curSeries, prevSeries, curDate, prevDate) {
        const curBy  = {};
        const prevBy = {};
        curSeries.forEach(s  => { if (s.series_number != null) curBy[s.series_number]  = s; });
        prevSeries.forEach(s => { if (s.series_number != null) prevBy[s.series_number] = s; });

        const allNums  = new Set([...Object.keys(curBy), ...Object.keys(prevBy)]);
        const paired   = [...allNums].filter(n => curBy[n] && prevBy[n]).sort((a,b) => Number(a)-Number(b));
        const unpairedCur  = [...allNums].filter(n => curBy[n]  && !prevBy[n]).map(n => curBy[n]);
        const unpairedPrev = [...allNums].filter(n => prevBy[n] && !curBy[n]).map(n => prevBy[n]);

        let allEqual     = true;
        let hasRegression = false;
        const rows = [];

        for (const num of paired) {
            const c = curBy[num];
            const p = prevBy[num];
            const cLoad = c.load != null ? Number(c.load) : null;
            const pLoad = p.load != null ? Number(p.load) : null;
            const cReps = c.reps != null ? Number(c.reps) : null;
            const pReps = p.reps != null ? Number(p.reps) : null;

            let rowVerdict = 'incomplete';
            if (cLoad != null && pLoad != null && cReps != null && pReps != null) {
                const sameLoad = cLoad === pLoad;
                const sameReps = cReps === pReps;
                if (cLoad < pLoad || (sameLoad && cReps < pReps)) {
                    rowVerdict = 'regression';
                    hasRegression = true;
                    allEqual = false;
                } else if (sameLoad && sameReps) {
                    rowVerdict = 'same';
                } else {
                    rowVerdict = 'progress';
                    allEqual = false;
                }
            }

            rows.push({ num: Number(num), cLoad, cReps, pLoad, pReps, rowVerdict });
        }

        let verdict = 'progress';
        if (hasRegression)               verdict = 'regression';
        else if (allEqual && rows.length) verdict = 'stagnation';

        return { verdict, curDate, prevDate, rows, unpaired: { cur: unpairedCur, prev: unpairedPrev } };
    }

    /**
     * Analyse all exercises. Returns:
     * { regression: [{name, detail}], stagnation: [...], progress: [...], new: [...], abandoned: [...] }
     */
    function analyse(quickData, period) {
        const seriesByEx = quickData.series_by_exercise || {};
        const cur  = getWeekBounds(period.curOffset);
        const prev = getWeekBounds(period.prevOffset);

        const buckets = { regression: [], stagnation: [], progress: [], new: [], abandoned: [] };

        for (const [exName, seriesByDate] of Object.entries(seriesByEx)) {
            const curDate  = getLastSessionDate(seriesByDate, cur.start,  cur.end);
            const prevDate = getLastSessionDate(seriesByDate, prev.start, prev.end);

            if (!curDate && !prevDate) continue;
            if (curDate && !prevDate)  { buckets.new.push({ name: exName, detail: null }); continue; }
            if (!curDate && prevDate)  { buckets.abandoned.push({ name: exName, detail: null }); continue; }

            const detail  = classifyExercise(seriesByDate[curDate], seriesByDate[prevDate], curDate, prevDate);
            buckets[detail.verdict].push({ name: exName, detail });
        }

        Object.keys(buckets).forEach(k => buckets[k].sort((a,b) => a.name.localeCompare(b.name)));
        return buckets;
    }

    // --- Body weight ---
    function bodyWeightAnalyse(quickData, period) {
        const key = { 'S_S1':'summary_7days', 'S_S2':'summary_14days', 'S1_S2':'summary_21days', 'S1_S3':'summary_28days' }[period.key];
        const summary = quickData[key] || {};
        return { current: summary.weight_current, previous: summary.weight_previous, diff: summary.weight_diff };
    }

    function bwBadge(bw) {
        if (bw.diff == null || bw.current == null)
            return `<span style="color:#94a3b8;">Pas de donnÃ©e poids corporel</span>`;
        const diff = Number(bw.diff);
        const cur  = Number(bw.current).toFixed(1);
        const prev = bw.previous != null ? Number(bw.previous).toFixed(1) : 'â€”';
        if (diff > 0.1)  return `<span style="color:#0369a1;font-weight:700;">â†‘ +${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        if (diff < -0.1) return `<span style="color:#b91c1c;font-weight:700;">â†“ ${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        return `<span style="color:#475569;font-weight:600;">â†’ Stable (${cur} kg)</span>`;
    }

    // --- Series detail dropdown (rendered inline below the pill) ---
    function buildDetailHtml(detail, curLabel, prevLabel) {
        if (!detail) return '';
        const { rows, curDate, prevDate, unpaired } = detail;

        const fmt = v => v != null ? v : 'â€”';

        const verdictStyle = {
            regression:  { bg: '#fef2f2', color: '#b91c1c', icon: 'â†“', text: 'RÃ©gression' },
            progress:    { bg: '#f0fdf4', color: '#15803d', icon: 'â†‘', text: 'ProgrÃ¨s' },
            same:        { bg: '#f8fafc', color: '#475569', icon: 'â†’', text: 'Identique' },
            incomplete:  { bg: '#fafafa', color: '#94a3b8', icon: '?', text: 'Incomplet' },
        };

        const bodyRows = rows.map(r => {
            const vs = verdictStyle[r.rowVerdict] || verdictStyle.incomplete;
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:4px 8px;color:#64748b;font-size:0.75rem;font-weight:600;">S${r.num}</td>
                <td style="padding:4px 8px;text-align:center;font-size:0.75rem;">${fmt(r.cLoad)} kg Ã— ${fmt(r.cReps)} reps</td>
                <td style="padding:4px 8px;text-align:center;font-size:0.75rem;color:#94a3b8;">${fmt(r.pLoad)} kg Ã— ${fmt(r.pReps)} reps</td>
                <td style="padding:4px 6px;text-align:center;">
                    <span style="display:inline-flex;align-items:center;gap:2px;background:${vs.bg};color:${vs.color};border-radius:4px;padding:2px 6px;font-size:0.7rem;font-weight:700;">
                        ${vs.icon} ${vs.text}
                    </span>
                </td>
            </tr>`;
        }).join('');

        let unpairedHtml = '';
        if (unpaired.cur.length) {
            const pills = unpaired.cur.map(s => `S${s.series_number} (${fmt(s.load)}kgÃ—${fmt(s.reps)})`).join(', ');
            unpairedHtml += `<div style="margin-top:6px;font-size:0.72rem;color:#6366f1;">ðŸ†• SÃ©ries nouvelles (pas de comparaison): ${pills}</div>`;
        }
        if (unpaired.prev.length) {
            const pills = unpaired.prev.map(s => `S${s.series_number} (${fmt(s.load)}kgÃ—${fmt(s.reps)})`).join(', ');
            unpairedHtml += `<div style="margin-top:4px;font-size:0.72rem;color:#64748b;">ðŸš« SÃ©ries abandonnÃ©es: ${pills}</div>`;
        }

        return `<div style="background:#fff;border:1px solid #e2e8f0;border-radius:6px;padding:10px;margin-top:6px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;gap:8px;flex-wrap:wrap;">
                <span style="font-size:0.72rem;font-weight:700;color:#1e293b;">${curLabel} : <span style="color:#667eea;">${curDate}</span></span>
                <span style="font-size:0.72rem;color:#94a3b8;">vs</span>
                <span style="font-size:0.72rem;font-weight:700;color:#1e293b;">${prevLabel} : <span style="color:#94a3b8;">${prevDate}</span></span>
            </div>
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="border-bottom:2px solid #e5e7eb;">
                        <th style="padding:4px 8px;text-align:left;font-size:0.7rem;color:#94a3b8;font-weight:600;">#</th>
                        <th style="padding:4px 8px;text-align:center;font-size:0.7rem;color:#667eea;font-weight:600;">${curLabel}</th>
                        <th style="padding:4px 8px;text-align:center;font-size:0.7rem;color:#94a3b8;font-weight:600;">${prevLabel}</th>
                        <th style="padding:4px 6px;text-align:center;font-size:0.7rem;color:#94a3b8;font-weight:600;">RÃ©sultat</th>
                    </tr>
                </thead>
                <tbody>${bodyRows}</tbody>
            </table>
            ${unpairedHtml}
        </div>`;
    }

    // --- Pill with toggle detail ---
    function buildExoList(items, bgColor, curLabel, prevLabel) {
        if (!items.length) return `<div style="color:#94a3b8;font-size:0.78rem;font-style:italic;">Aucun</div>`;
        return items.map((item, i) => {
            const detailId = `ap-detail-${item.name.replace(/\s+/g,'_').replace(/[^a-zA-Z0-9_]/g,'')}_${i}_${Math.random().toString(36).slice(2,6)}`;
            const hasDetail = item.detail && item.detail.rows.length;
            const cursor    = hasDetail ? 'pointer' : 'default';
            const titleAttr = hasDetail ? 'title="Cliquer pour voir le dÃ©tail des sÃ©ries"' : '';
            const arrow     = hasDetail ? ' â–¾' : '';
            return `<span style="display:inline-block;margin:2px 3px 2px 0;">
                <span data-detail-id="${detailId}" ${titleAttr}
                    style="display:inline-flex;align-items:center;background:${bgColor};color:#fff;border-radius:4px;padding:3px 10px;font-size:0.75rem;font-weight:600;cursor:${cursor};user-select:none;transition:opacity 0.1s;"
                    onmouseenter="this.style.opacity='0.85'" onmouseleave="this.style.opacity='1'">
                    ${item.name}${arrow}
                </span>
                ${hasDetail ? `<div id="${detailId}" style="display:none;">${buildDetailHtml(item.detail, curLabel, prevLabel)}</div>` : ''}
            </span>`;
        }).join('');
    }

    function renderPanelContent(container, quickData, period) {
        const bw = bodyWeightAnalyse(quickData, period);
        const ex = analyse(quickData, period);

        const curLabel  = PERIODS.find(p => p.key === period.key)?.label.split(' vs ')[0] || 'Courant';
        const prevLabel = PERIODS.find(p => p.key === period.key)?.label.split(' vs ')[1] || 'PrÃ©c.';

        const rows = [
            { icon: 'âš–ï¸', label: 'Poids corporel',                             bg: '#eff6ff', border: '#3b82f6', content: bwBadge(bw),                                                      isText: true },
            { icon: 'ðŸ”´', label: `RÃ©gressions (${ex.regression.length})`,      bg: '#fef2f2', border: '#ef4444', content: buildExoList(ex.regression,  '#ef4444', curLabel, prevLabel) },
            { icon: 'ðŸŸ ', label: `Stagnations (${ex.stagnation.length})`,      bg: '#fffbeb', border: '#f59e0b', content: buildExoList(ex.stagnation,  '#f59e0b', curLabel, prevLabel) },
            { icon: 'ðŸŸ¢', label: `ProgrÃ¨s (${ex.progress.length})`,            bg: '#f0fdf4', border: '#10b981', content: buildExoList(ex.progress,    '#10b981', curLabel, prevLabel) },
        ];
        if (ex.new.length)
            rows.push({ icon: 'ðŸ†•', label: `Nouveaux (${ex.new.length})`,      bg: '#eef2ff', border: '#6366f1', content: buildExoList(ex.new,       '#6366f1', curLabel, prevLabel) });
        if (ex.abandoned.length)
            rows.push({ icon: 'ðŸš«', label: `AbandonnÃ©s (${ex.abandoned.length})`, bg: '#f1f5f9', border: '#64748b', content: buildExoList(ex.abandoned, '#64748b', curLabel, prevLabel) });

        container.innerHTML = rows.map(r => `
            <div style="background:${r.bg};border-left:3px solid ${r.border};border-radius:4px;padding:8px 10px;margin-bottom:6px;">
                <div style="font-weight:700;font-size:0.78rem;color:#1e293b;margin-bottom:4px;">${r.icon} ${r.label}</div>
                <div style="line-height:1.8;">${r.content}</div>
            </div>
        `).join('');

        // Attach toggle handlers for detail dropdowns
        container.querySelectorAll('[data-detail-id]').forEach(pill => {
            pill.addEventListener('click', () => {
                const id = pill.dataset.detailId;
                const detailEl = container.querySelector(`#${id}`);
                if (!detailEl) return;
                const open = detailEl.style.display !== 'none';
                // Close all others in same container
                container.querySelectorAll('[data-detail-id]').forEach(p => {
                    const el = container.querySelector(`#${p.dataset.detailId}`);
                    if (el) el.style.display = 'none';
                    p.style.borderRadius = '4px';
                });
                if (!open) {
                    detailEl.style.display = 'block';
                    pill.style.borderRadius = '4px 4px 0 0';
                }
            });
        });
    }

    function render(container, quickData) {
        if (!container) return;
        if (!quickData || !quickData.series_by_exercise) {
            container.innerHTML = '<div style="color:#94a3b8;font-size:0.85rem;">DonnÃ©es non disponibles</div>';
            return;
        }

        const uid = 'ap_' + Math.random().toString(36).slice(2, 9);

        const tabsHtml = PERIODS.map((p, i) => `
            <button type="button" data-period="${p.key}" class="${uid}-tab" style="
                flex:1;padding:6px 4px;border:none;cursor:pointer;
                background:${i === 0 ? '#667eea' : '#f1f5f9'};
                color:${i === 0 ? '#fff' : '#475569'};
                font-size:0.72rem;font-weight:700;border-radius:6px;transition:all 0.15s;">
                ${p.label}
            </button>`).join('');

        container.innerHTML = `
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:1.1rem;">ðŸŽ¯</span>
                    <h4 style="margin:0;font-size:0.95rem;font-weight:700;color:#1e293b;">Points d'attention coach</h4>
                </div>
                <div style="display:flex;gap:4px;margin-bottom:10px;" id="${uid}-tabs">${tabsHtml}</div>
                <div id="${uid}-content"></div>
            </div>`;

        const contentEl = container.querySelector(`#${uid}-content`);
        const tabBtns   = container.querySelectorAll(`.${uid}-tab`);

        function activate(periodKey) {
            tabBtns.forEach(btn => {
                const active = btn.dataset.period === periodKey;
                btn.style.background = active ? '#667eea' : '#f1f5f9';
                btn.style.color      = active ? '#fff'    : '#475569';
            });
            const period = PERIODS.find(p => p.key === periodKey) || PERIODS[0];
            renderPanelContent(contentEl, quickData, period);
        }

        tabBtns.forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.period)));
        activate(PERIODS[0].key);
    }

    global.AttentionPanel = { render };
})(window);
