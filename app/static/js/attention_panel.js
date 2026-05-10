/**
 * Attention Panel — Coach insights with custom A/B week selection.
 *
 * Public API:
 *   AttentionPanel.render(container, quickData, options)
 *     options = {
 *       weeksBack: 13,                                  // weeks offered in selects
 *       defaultA: 0, defaultB: 1,
 *       onChange: (aOffset, bOffset) => { ... }         // fires when selection changes (and on init)
 *     }
 *
 * Classification rules (paired series only, incomplete ignored):
 *   - All paired non-incomplete identical -> Stagnation
 *   - countProgress > countRegression && tonnageΔ ≥ 0 -> Progrès
 *   - countProgress > countRegression && tonnageΔ < 0 -> Vue du coach (review)
 *   - countRegression > countProgress && tonnageΔ ≤ 0 -> Régression
 *   - countRegression > countProgress && tonnageΔ > 0 -> Vue du coach
 *   - Tie: tonnage tranche (>0 progrès, <0 régression, =0 stagnation)
 */
(function (global) {
    'use strict';

    // --- Date helpers (kept local; mirror WeeklyCompare to avoid hard dep) ---
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
    function weekLabel(o) { return o === 0 ? 'Cette sem.' : ('S-' + o); }

    function getLastSessionDate(seriesByDate, weekStart, weekEnd) {
        const dates = Object.keys(seriesByDate)
            .filter(d => d >= weekStart && d <= weekEnd)
            .sort();
        return dates.length ? dates[dates.length - 1] : null;
    }

    function avg(values) {
        const v = values.filter(x => x !== null && x !== undefined && !isNaN(x));
        if (!v.length) return null;
        return v.reduce((a, b) => a + Number(b), 0) / v.length;
    }

    function bodyWeightForRange(journal, start, end) {
        const filtered = (journal || []).filter(e => e.date >= start && e.date <= end);
        return avg(filtered.map(e => e.weight));
    }

    function classifyExercise(curSeries, prevSeries, curDate, prevDate) {
        const curBy  = {};
        const prevBy = {};
        curSeries.forEach(s  => { if (s.series_number != null) curBy[s.series_number]  = s; });
        prevSeries.forEach(s => { if (s.series_number != null) prevBy[s.series_number] = s; });

        const allNums  = new Set([...Object.keys(curBy), ...Object.keys(prevBy)]);
        const paired   = [...allNums].filter(n => curBy[n] && prevBy[n]).sort((a,b) => Number(a)-Number(b));
        const unpairedCur  = [...allNums].filter(n => curBy[n]  && !prevBy[n]).map(n => curBy[n]);
        const unpairedPrev = [...allNums].filter(n => prevBy[n] && !curBy[n]).map(n => prevBy[n]);

        const rows = [];
        let countProgress = 0, countRegression = 0, countSame = 0;
        let curTonnage = 0, prevTonnage = 0;

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
                curTonnage  += cLoad * cReps;
                prevTonnage += pLoad * pReps;
                if (cLoad < pLoad || (sameLoad && cReps < pReps)) {
                    rowVerdict = 'regression';
                    countRegression++;
                } else if (sameLoad && sameReps) {
                    rowVerdict = 'same';
                    countSame++;
                } else {
                    rowVerdict = 'progress';
                    countProgress++;
                }
            }

            rows.push({ num: Number(num), cLoad, cReps, pLoad, pReps, rowVerdict });
        }

        const tonnageDiff = curTonnage - prevTonnage;
        const totalCounted = countProgress + countRegression + countSame;

        let verdict = 'progress';
        if (totalCounted === 0) verdict = 'progress';
        else if (countProgress === 0 && countRegression === 0) verdict = 'stagnation';
        else if (countProgress > countRegression) verdict = tonnageDiff < 0 ? 'review' : 'progress';
        else if (countRegression > countProgress) verdict = tonnageDiff > 0 ? 'review' : 'regression';
        else {
            if (tonnageDiff > 0)      verdict = 'progress';
            else if (tonnageDiff < 0) verdict = 'regression';
            else                       verdict = 'stagnation';
        }

        return {
            verdict, curDate, prevDate, rows,
            unpaired: { cur: unpairedCur, prev: unpairedPrev },
            stats: { countProgress, countRegression, countSame, curTonnage, prevTonnage, tonnageDiff }
        };
    }

    function analyse(quickData, aOffset, bOffset) {
        const seriesByEx = quickData.series_by_exercise || {};
        const cur  = getWeekBounds(aOffset);
        const prev = getWeekBounds(bOffset);

        const buckets = { regression: [], review: [], stagnation: [], progress: [], new: [], abandoned: [] };

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

    function bwBadge(curW, prevW) {
        if (curW == null && prevW == null)
            return `<span style="color:#94a3b8;">Pas de donnée poids corporel</span>`;
        const cur  = curW  != null ? Number(curW).toFixed(1)  : '—';
        const prev = prevW != null ? Number(prevW).toFixed(1) : '—';
        if (curW == null || prevW == null)
            return `<span style="color:#475569;">Poids: ${cur} kg vs ${prev} kg</span>`;
        const diff = Number(curW) - Number(prevW);
        if (diff > 0.1)  return `<span style="color:#0369a1;font-weight:700;">↑ +${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        if (diff < -0.1) return `<span style="color:#b91c1c;font-weight:700;">↓ ${diff.toFixed(2)} kg</span> <span style="color:#64748b;font-size:0.85em;">(${cur} kg vs ${prev} kg)</span>`;
        return `<span style="color:#475569;font-weight:600;">→ Stable (${cur} kg)</span>`;
    }

    function buildDetailHtml(detail, curLabel, prevLabel) {
        if (!detail) return '';
        const { rows, curDate, prevDate, unpaired, stats } = detail;
        const fmt = v => v != null ? v : '—';

        const verdictStyle = {
            regression:  { bg: '#fef2f2', color: '#b91c1c', icon: '↓', text: 'Régression' },
            progress:    { bg: '#f0fdf4', color: '#15803d', icon: '↑', text: 'Progrès' },
            same:        { bg: '#f8fafc', color: '#475569', icon: '→', text: 'Identique' },
            incomplete:  { bg: '#fafafa', color: '#94a3b8', icon: '?', text: 'Incomplet' },
        };

        const bodyRows = rows.map(r => {
            const vs = verdictStyle[r.rowVerdict] || verdictStyle.incomplete;
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:4px 8px;color:#64748b;font-size:0.75rem;font-weight:600;">S${r.num}</td>
                <td style="padding:4px 8px;text-align:center;font-size:0.75rem;">${fmt(r.cLoad)} kg × ${fmt(r.cReps)} reps</td>
                <td style="padding:4px 8px;text-align:center;font-size:0.75rem;color:#94a3b8;">${fmt(r.pLoad)} kg × ${fmt(r.pReps)} reps</td>
                <td style="padding:4px 6px;text-align:center;">
                    <span style="display:inline-flex;align-items:center;gap:2px;background:${vs.bg};color:${vs.color};border-radius:4px;padding:2px 6px;font-size:0.7rem;font-weight:700;">
                        ${vs.icon} ${vs.text}
                    </span>
                </td>
            </tr>`;
        }).join('');

        let unpairedHtml = '';
        if (unpaired.cur.length) {
            const pills = unpaired.cur.map(s => `S${s.series_number} (${fmt(s.load)}kg×${fmt(s.reps)})`).join(', ');
            unpairedHtml += `<div style="margin-top:6px;font-size:0.72rem;color:#6366f1;">🆕 Séries nouvelles (pas de comparaison): ${pills}</div>`;
        }
        if (unpaired.prev.length) {
            const pills = unpaired.prev.map(s => `S${s.series_number} (${fmt(s.load)}kg×${fmt(s.reps)})`).join(', ');
            unpairedHtml += `<div style="margin-top:4px;font-size:0.72rem;color:#64748b;">🚫 Séries abandonnées: ${pills}</div>`;
        }

        let tonnageHtml = '';
        if (stats && (stats.countProgress + stats.countRegression + stats.countSame) > 0) {
            const td = stats.tonnageDiff;
            const tdColor = td > 0 ? '#15803d' : (td < 0 ? '#b91c1c' : '#475569');
            const tdSign  = td > 0 ? '+' : '';
            tonnageHtml = `<div style="margin-top:8px;padding-top:6px;border-top:1px dashed #e5e7eb;display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;font-size:0.72rem;">
                <span style="color:#475569;">
                    🟢 ${stats.countProgress} progrès &middot;
                    🔴 ${stats.countRegression} régression(s) &middot;
                    → ${stats.countSame} identique(s)
                </span>
                <span style="color:${tdColor};font-weight:700;">
                    Tonnage: ${stats.curTonnage} vs ${stats.prevTonnage} kg (${tdSign}${td})
                </span>
            </div>`;
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
                        <th style="padding:4px 6px;text-align:center;font-size:0.7rem;color:#94a3b8;font-weight:600;">Résultat</th>
                    </tr>
                </thead>
                <tbody>${bodyRows}</tbody>
            </table>
            ${tonnageHtml}
            ${unpairedHtml}
        </div>`;
    }

    function buildExoList(items, bgColor, curLabel, prevLabel) {
        if (!items.length) return `<div style="color:#94a3b8;font-size:0.78rem;font-style:italic;">Aucun</div>`;
        return items.map((item, i) => {
            const detailId = `ap-detail-${item.name.replace(/\s+/g,'_').replace(/[^a-zA-Z0-9_]/g,'')}_${i}_${Math.random().toString(36).slice(2,6)}`;
            const hasDetail = item.detail && item.detail.rows.length;
            const cursor    = hasDetail ? 'pointer' : 'default';
            const titleAttr = hasDetail ? 'title="Cliquer pour voir le détail des séries"' : '';
            const arrow     = hasDetail ? ' ▾' : '';
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

    function renderPanelContent(container, quickData, aOffset, bOffset) {
        const a = getWeekBounds(aOffset);
        const b = getWeekBounds(bOffset);
        const aLabel = weekLabel(aOffset);
        const bLabel = weekLabel(bOffset);

        const curW  = bodyWeightForRange(quickData.journal, a.start, a.end);
        const prevW = bodyWeightForRange(quickData.journal, b.start, b.end);

        const ex = analyse(quickData, aOffset, bOffset);

        const rows = [
            { icon: '⚖️', label: 'Poids corporel',                          bg: '#eff6ff', border: '#3b82f6', content: bwBadge(curW, prevW) },
            { icon: '🔴', label: `Régressions (${ex.regression.length})`,   bg: '#fef2f2', border: '#ef4444', content: buildExoList(ex.regression,  '#ef4444', aLabel, bLabel) },
            { icon: '👀', label: `Vue du coach (${ex.review.length})`,      bg: '#fdf4ff', border: '#a855f7', content: buildExoList(ex.review,      '#a855f7', aLabel, bLabel) },
            { icon: '🟠', label: `Stagnations (${ex.stagnation.length})`,   bg: '#fffbeb', border: '#f59e0b', content: buildExoList(ex.stagnation,  '#f59e0b', aLabel, bLabel) },
            { icon: '🟢', label: `Progrès (${ex.progress.length})`,         bg: '#f0fdf4', border: '#10b981', content: buildExoList(ex.progress,    '#10b981', aLabel, bLabel) },
        ];
        if (ex.new.length)
            rows.push({ icon: '🆕', label: `Nouveaux (${ex.new.length})`,      bg: '#eef2ff', border: '#6366f1', content: buildExoList(ex.new,       '#6366f1', aLabel, bLabel) });
        if (ex.abandoned.length)
            rows.push({ icon: '🚫', label: `Abandonnés (${ex.abandoned.length})`, bg: '#f1f5f9', border: '#64748b', content: buildExoList(ex.abandoned, '#64748b', aLabel, bLabel) });

        container.innerHTML = rows.map(r => `
            <div style="background:${r.bg};border-left:3px solid ${r.border};border-radius:4px;padding:8px 10px;margin-bottom:6px;">
                <div style="font-weight:700;font-size:0.78rem;color:#1e293b;margin-bottom:4px;">${r.icon} ${r.label}</div>
                <div style="line-height:1.8;">${r.content}</div>
            </div>
        `).join('');

        container.querySelectorAll('[data-detail-id]').forEach(pill => {
            pill.addEventListener('click', () => {
                const id = pill.dataset.detailId;
                const detailEl = container.querySelector(`#${id}`);
                if (!detailEl) return;
                const open = detailEl.style.display !== 'none';
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

    function buildWeekOptions(weeksBack) {
        const N = weeksBack || 13;
        let html = '';
        for (let i = 0; i < N; i++) {
            const { start } = getWeekBounds(i);
            html += `<option value="${i}">${weekLabel(i)} (${start})</option>`;
        }
        return html;
    }

    function render(container, quickData, options) {
        if (!container) return;
        if (!quickData || !quickData.series_by_exercise) {
            container.innerHTML = '<div style="color:#94a3b8;font-size:0.85rem;">Données non disponibles</div>';
            return;
        }
        const opts = options || {};
        const weeksBack = opts.weeksBack || 13;
        const onChange = typeof opts.onChange === 'function' ? opts.onChange : null;
        const defaultA = opts.defaultA != null ? opts.defaultA : 0;
        const defaultB = opts.defaultB != null ? opts.defaultB : 1;

        const uid = 'ap_' + Math.random().toString(36).slice(2, 9);
        const weekOpts = buildWeekOptions(weeksBack);

        container.innerHTML = `
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:1.1rem;">🎯</span>
                    <h4 style="margin:0;font-size:0.95rem;font-weight:700;color:#1e293b;">Points d'attention coach</h4>
                </div>
                <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap;font-size:0.78rem;">
                    <label style="display:flex;align-items:center;gap:4px;color:#475569;font-weight:600;">
                        Sem. A
                        <select id="${uid}-a" style="padding:3px 6px;border:1px solid #cbd5e1;border-radius:4px;font-size:0.78rem;">${weekOpts}</select>
                    </label>
                    <span style="color:#94a3b8;">vs</span>
                    <label style="display:flex;align-items:center;gap:4px;color:#475569;font-weight:600;">
                        Sem. B
                        <select id="${uid}-b" style="padding:3px 6px;border:1px solid #cbd5e1;border-radius:4px;font-size:0.78rem;">${weekOpts}</select>
                    </label>
                </div>
                <div id="${uid}-content"></div>
            </div>`;

        const contentEl = container.querySelector(`#${uid}-content`);
        const selA = container.querySelector(`#${uid}-a`);
        const selB = container.querySelector(`#${uid}-b`);
        selA.value = String(defaultA);
        selB.value = String(defaultB);

        function refresh() {
            const a = parseInt(selA.value, 10);
            const b = parseInt(selB.value, 10);
            renderPanelContent(contentEl, quickData, a, b);
            if (onChange) {
                try { onChange(a, b); } catch (e) { console.error(e); }
            }
        }

        selA.addEventListener('change', refresh);
        selB.addEventListener('change', refresh);
        refresh();
    }

    global.AttentionPanel = { render };
})(window);
