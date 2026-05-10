/**
 * Weekly Compare — shared helper to compute arbitrary week-vs-week comparisons
 * client-side from quick-data.json raw fields (journal + series_by_exercise + exercise_muscle_map).
 *
 * Produces the same `summary_*days` shape used by displayComparison(InCard):
 *   { label1, label2,
 *     weight_current, weight_previous, weight_diff,
 *     kcals_current, kcals_previous, kcals_diff,
 *     water_current, water_previous, water_diff,
 *     sleep_current, sleep_previous, sleep_diff,
 *     tonnage_diff_by_muscle: { muscle: diff },
 *     exercise_details_by_muscle: { muscle: { exName: { current, previous, diff } } }
 *   }
 */
(function (global) {
    'use strict';

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

    function weekLabel(weekOffset) {
        if (weekOffset === 0) return 'Cette sem.';
        return 'S-' + weekOffset;
    }

    function avg(values) {
        const v = values.filter(x => x !== null && x !== undefined && !isNaN(x));
        if (!v.length) return null;
        return v.reduce((a, b) => a + Number(b), 0) / v.length;
    }

    function calcJournalAverages(journal, start, end) {
        const filtered = (journal || []).filter(e => e.date >= start && e.date <= end);
        return {
            weight: avg(filtered.map(e => e.weight)),
            kcals:  avg(filtered.map(e => e.kcals)),
            water:  avg(filtered.map(e => e.water_ml)),
            sleep:  avg(filtered.map(e => e.sleep_hours)),
        };
    }

    /**
     * Compute tonnage by muscle and exercise details for a week range.
     * Returns { byMuscle: {muscle: total}, byMuscleEx: {muscle: {ex: total}} }
     */
    function calcTonnage(seriesByExercise, exerciseMuscleMap, start, end) {
        const byMuscle = {};
        const byMuscleEx = {};
        const series = seriesByExercise || {};
        const muscleMap = exerciseMuscleMap || {};

        for (const [exName, byDate] of Object.entries(series)) {
            const muscle = muscleMap[exName];
            if (!muscle) continue;
            for (const [date, sList] of Object.entries(byDate)) {
                if (date < start || date > end) continue;
                for (const s of sList) {
                    if (s.load == null || s.reps == null) continue;
                    const ton = Number(s.load) * Number(s.reps);
                    if (!ton) continue;
                    byMuscle[muscle] = (byMuscle[muscle] || 0) + ton;
                    if (!byMuscleEx[muscle]) byMuscleEx[muscle] = {};
                    byMuscleEx[muscle][exName] = (byMuscleEx[muscle][exName] || 0) + ton;
                }
            }
        }
        return { byMuscle, byMuscleEx };
    }

    /**
     * Build a summary_*days-shaped object for arbitrary week offsets A vs B.
     * aOffset = current (default 0 = this week), bOffset = previous (default 1).
     */
    function computeComparison(quickData, aOffset, bOffset) {
        const a = getWeekBounds(aOffset);
        const b = getWeekBounds(bOffset);
        const aLabel = weekLabel(aOffset);
        const bLabel = weekLabel(bOffset);

        const aJ = calcJournalAverages(quickData.journal, a.start, a.end);
        const bJ = calcJournalAverages(quickData.journal, b.start, b.end);
        const aT = calcTonnage(quickData.series_by_exercise, quickData.exercise_muscle_map, a.start, a.end);
        const bT = calcTonnage(quickData.series_by_exercise, quickData.exercise_muscle_map, b.start, b.end);

        const subOrNull = (x, y) => (x != null && y != null) ? (x - y) : null;

        const muscles = new Set([...Object.keys(aT.byMuscle), ...Object.keys(bT.byMuscle)]);
        const tonnage_diff_by_muscle = {};
        muscles.forEach(m => { tonnage_diff_by_muscle[m] = (aT.byMuscle[m] || 0) - (bT.byMuscle[m] || 0); });

        const exercise_details_by_muscle = {};
        muscles.forEach(m => {
            const aEx = aT.byMuscleEx[m] || {};
            const bEx = bT.byMuscleEx[m] || {};
            const exNames = new Set([...Object.keys(aEx), ...Object.keys(bEx)]);
            exercise_details_by_muscle[m] = {};
            exNames.forEach(ex => {
                const c = aEx[ex] || 0;
                const p = bEx[ex] || 0;
                exercise_details_by_muscle[m][ex] = { current: c, previous: p, diff: c - p };
            });
        });

        return {
            label1: aLabel, label2: bLabel,
            week_a_range: a, week_b_range: b,
            weight_current: aJ.weight, weight_previous: bJ.weight, weight_diff: subOrNull(aJ.weight, bJ.weight),
            kcals_current:  aJ.kcals,  kcals_previous:  bJ.kcals,  kcals_diff:  subOrNull(aJ.kcals,  bJ.kcals),
            water_current:  aJ.water,  water_previous:  bJ.water,  water_diff:  subOrNull(aJ.water,  bJ.water),
            sleep_current:  aJ.sleep,  sleep_previous:  bJ.sleep,  sleep_diff:  subOrNull(aJ.sleep,  bJ.sleep),
            tonnage_diff_by_muscle,
            exercise_details_by_muscle,
        };
    }

    /**
     * Build <option> HTML for a week select with N weeks back.
     */
    function buildWeekOptions(weeksBack) {
        const N = weeksBack || 13;
        let html = '';
        for (let i = 0; i < N; i++) {
            const { start } = getWeekBounds(i);
            html += `<option value="${i}">${weekLabel(i)} (${start})</option>`;
        }
        return html;
    }

    global.WeeklyCompare = {
        getWeekBounds, weekLabel, computeComparison, buildWeekOptions
    };
})(window);
