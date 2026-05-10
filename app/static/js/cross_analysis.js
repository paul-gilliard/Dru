/* cross_analysis.js — Analyse croisée tab for coach_stats page */
(function () {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  let quickData    = null;  // window.statsQuickData (quick-data.json)
  let journalFull  = null;  // window.statsJournalFull (journal.json)
  let crossChart   = null;
  let activeMetrics = [];   // { id, label, unit, dec, axis, color, compute }
  let selectedWeeks = [0, 1]; // weeksAgo offsets (0 = this week, 1 = S-1, …)
  let weekDropdownOpen = false;

  // ── Colour palette ───────────────────────────────────────────────────────
  const COLORS = [
    '#0b63d6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#64748b',
    '#1d4ed8', '#dc2626', '#059669', '#d97706', '#7c3aed',
  ];

  // ── Health metric definitions ─────────────────────────────────────────────
  const HEALTH_METRICS = [
    { key: 'weight',      label: 'Poids',          unit: 'kg',   dec: 1, axis: 'y'       },
    { key: 'kcals',       label: 'Kcals',           unit: 'kcal', dec: 0, axis: 'y_right' },
    { key: 'protein',     label: 'Protéines',       unit: 'g',    dec: 0, axis: 'y_right' },
    { key: 'carbs',       label: 'Glucides',        unit: 'g',    dec: 0, axis: 'y_right' },
    { key: 'fats',        label: 'Lipides',         unit: 'g',    dec: 0, axis: 'y_right' },
    { key: 'water_ml',    label: 'Eau',             unit: 'ml',   dec: 0, axis: 'y_right' },
    { key: 'steps',       label: 'Pas',             unit: '',     dec: 0, axis: 'y_right' },
    { key: 'sleep_hours', label: 'Sommeil',         unit: 'h',    dec: 1, axis: 'y'       },
    { key: 'energy',      label: 'Énergie',         unit: '/10',  dec: 0, axis: 'y'       },
    { key: 'stress',      label: 'Stress',          unit: '/10',  dec: 0, axis: 'y'       },
    { key: 'hunger',      label: 'Faim',            unit: '/10',  dec: 0, axis: 'y'       },
  ];

  // ── Performance stat types ────────────────────────────────────────────────
  const PERF_STATS = [
    { key: 'tonnage',    label: 'Tonnage',     unit: 'kg', dec: 0, axis: 'y_right' },
    { key: 'max_load',   label: 'Poids max',   unit: 'kg', dec: 1, axis: 'y'       },
    { key: 'total_reps', label: 'Reps total',  unit: '',   dec: 0, axis: 'y_right' },
    { key: 'avg_load',   label: 'Poids moyen', unit: 'kg', dec: 1, axis: 'y'       },
  ];

  // ── Week helpers ──────────────────────────────────────────────────────────
  function getWeekBounds(weeksAgo) {
    const d = new Date();
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    const monday = new Date(d);
    monday.setDate(diff - weeksAgo * 7);
    monday.setHours(0, 0, 0, 0);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return {
      start: monday.toISOString().split('T')[0],
      end:   sunday.toISOString().split('T')[0],
      label: weeksAgo === 0 ? 'Cette sem.' : `S-${weeksAgo}`,
    };
  }

  // ── Computation helpers ───────────────────────────────────────────────────
  function calcHealthWeekAvg(weeksAgo, key) {
    if (!journalFull) return null;
    const { start, end } = getWeekBounds(weeksAgo);
    const entries = journalFull.filter(e => e.date >= start && e.date <= end);
    const vals = entries.map(e => e[key]).filter(v => v !== null && v !== undefined);
    return vals.length ? vals.reduce((a, b) => a + Number(b), 0) / vals.length : null;
  }

  function getExerciseSeries(exerciseName, weeksAgo) {
    if (!quickData || !quickData.series_by_exercise) return [];
    const { start, end } = getWeekBounds(weeksAgo);
    const byDate = quickData.series_by_exercise[exerciseName] || {};
    return Object.entries(byDate)
      .filter(([date]) => date >= start && date <= end)
      .flatMap(([, s]) => s);
  }

  function computeStatFromSeries(series, statKey) {
    if (!series.length) return null;
    switch (statKey) {
      case 'tonnage': {
        const t = series.filter(s => s.load && s.reps).reduce((sum, s) => sum + s.load * s.reps, 0);
        return t || null;
      }
      case 'max_load': {
        const vals = series.filter(s => s.load).map(s => s.load);
        return vals.length ? Math.max(...vals) : null;
      }
      case 'total_reps': {
        const t = series.filter(s => s.reps).reduce((sum, s) => sum + Number(s.reps), 0);
        return t || null;
      }
      case 'avg_load': {
        const vals = series.filter(s => s.load).map(s => s.load);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      }
      default: return null;
    }
  }

  function calcExerciseWeekStat(weeksAgo, exerciseName, statKey) {
    return computeStatFromSeries(getExerciseSeries(exerciseName, weeksAgo), statKey);
  }

  function calcMuscleWeekStat(weeksAgo, muscleGroup, statKey) {
    if (!quickData || !quickData.exercise_muscle_map) return null;
    const exercises = Object.entries(quickData.exercise_muscle_map)
      .filter(([, m]) => m === muscleGroup)
      .map(([name]) => name);
    const series = exercises.flatMap(ex => getExerciseSeries(ex, weeksAgo));
    return computeStatFromSeries(series, statKey);
  }

  // ── Week dropdown ─────────────────────────────────────────────────────────
  function populateWeekDropdown() {
    const dropdown = document.getElementById('cross-week-dropdown');
    if (!dropdown) return;
    dropdown.innerHTML = '';
    for (let i = 0; i < 24; i++) {
      const { start, label } = getWeekBounds(i);
      const row = document.createElement('div');
      row.className = 'cross-week-option';
      row.dataset.weeksAgo = i;
      row.innerHTML = `
        <label style="display:flex;align-items:center;gap:8px;padding:6px 10px;cursor:pointer;white-space:nowrap;">
          <input type="checkbox" data-weeks-ago="${i}" ${selectedWeeks.includes(i) ? 'checked' : ''}>
          <span>${label}</span>
          <span style="color:#94a3b8;font-size:0.78rem;">${start}</span>
        </label>`;
      row.querySelector('input').addEventListener('change', function () {
        const ago = parseInt(this.dataset.weeksAgo, 10);
        if (this.checked) {
          if (!selectedWeeks.includes(ago)) selectedWeeks.push(ago);
        } else {
          selectedWeeks = selectedWeeks.filter(w => w !== ago);
        }
        selectedWeeks.sort((a, b) => a - b);
        updateWeekChips();
        renderCrossChart();
      });
      dropdown.appendChild(row);
    }
  }

  function toggleWeekDropdown() {
    const dropdown = document.getElementById('cross-week-dropdown');
    const btn      = document.getElementById('cross-week-toggle-btn');
    if (!dropdown) return;
    weekDropdownOpen = !weekDropdownOpen;
    dropdown.style.display = weekDropdownOpen ? 'block' : 'none';
    if (btn) btn.textContent = weekDropdownOpen ? 'Fermer ▲' : 'Sélectionner des semaines ▼';
  }

  function updateWeekChips() {
    const chips = document.getElementById('cross-week-chips');
    if (!chips) return;
    if (selectedWeeks.length === 0) {
      chips.innerHTML = '<span style="color:#94a3b8;font-size:0.85rem;">Aucune semaine sélectionnée</span>';
      return;
    }
    chips.innerHTML = [...selectedWeeks].sort((a, b) => a - b).map(ago => {
      const { label, start } = getWeekBounds(ago);
      return `<span class="cross-chip" style="display:inline-flex;align-items:center;gap:4px;background:#e0f0ff;color:#0b63d6;border:1px solid #bfdbfe;border-radius:20px;padding:3px 10px;font-size:0.82rem;font-weight:600;margin:2px;">
        ${label} <span style="opacity:0.65;font-weight:400;font-size:0.75rem;">${start}</span>
        <button data-remove-week="${ago}" style="background:none;border:none;cursor:pointer;padding:0 0 0 4px;color:#0b63d6;font-size:15px;line-height:1;">×</button>
      </span>`;
    }).join('');
    chips.querySelectorAll('[data-remove-week]').forEach(btn => {
      btn.addEventListener('click', () => removeWeek(parseInt(btn.dataset.removeWeek, 10)));
    });
  }

  function removeWeek(ago) {
    selectedWeeks = selectedWeeks.filter(w => w !== ago);
    const cb = document.querySelector(`#cross-week-dropdown input[data-weeks-ago="${ago}"]`);
    if (cb) cb.checked = false;
    updateWeekChips();
    renderCrossChart();
  }

  // ── Category selectors ────────────────────────────────────────────────────
  function updateCategorySelectors() {
    const category = document.getElementById('cross-category')?.value || '';
    const sub1W = document.getElementById('cross-sub1-wrapper');
    const sub2W = document.getElementById('cross-sub2-wrapper');
    const sub1  = document.getElementById('cross-sub1');
    const sub2  = document.getElementById('cross-sub2');
    const sub1L = document.getElementById('cross-sub1-label');
    if (!sub1W) return;

    sub1W.style.display = 'none';
    sub2W.style.display = 'none';

    if (category === 'sante') {
      sub1W.style.display = 'block';
      sub1L.textContent = 'Métrique :';
      sub1.innerHTML = '<option value="">— Choisir métrique —</option>' +
        HEALTH_METRICS.map(m => `<option value="${m.key}">${m.label}</option>`).join('');

    } else if (category === 'muscle') {
      sub1W.style.display = 'block';
      sub2W.style.display = 'block';
      sub1L.textContent = 'Groupe musculaire :';
      const muscles = quickData
        ? [...new Set(Object.values(quickData.exercise_muscle_map || {}))].sort()
        : [];
      sub1.innerHTML = '<option value="">— Groupe musculaire —</option>' +
        muscles.map(m => `<option value="${m}">${m}</option>`).join('');
      sub2.innerHTML = PERF_STATS.map(s => `<option value="${s.key}">${s.label}</option>`).join('');
      document.getElementById('cross-sub2-label').textContent = 'Stat :';

    } else if (category === 'exercise') {
      sub1W.style.display = 'block';
      sub2W.style.display = 'block';
      sub1L.textContent = 'Exercice :';
      const exercises = quickData
        ? Object.keys(quickData.series_by_exercise || {}).sort()
        : [];
      sub1.innerHTML = '<option value="">— Exercice —</option>' +
        exercises.map(e => `<option value="${e}">${e}</option>`).join('');
      sub2.innerHTML = PERF_STATS.map(s => `<option value="${s.key}">${s.label}</option>`).join('');
      document.getElementById('cross-sub2-label').textContent = 'Stat :';
    }
  }

  // ── Add / remove metrics ──────────────────────────────────────────────────
  function addMetric() {
    const category = document.getElementById('cross-category')?.value || '';
    if (!category) return;

    let metric = null;

    if (category === 'sante') {
      const key = document.getElementById('cross-sub1')?.value || '';
      if (!key) return;
      const def = HEALTH_METRICS.find(m => m.key === key);
      metric = {
        id: `sante_${key}_${Date.now()}`,
        label: def.label,
        unit: def.unit, dec: def.dec, axis: def.axis,
        compute: ago => calcHealthWeekAvg(ago, key),
      };

    } else if (category === 'muscle') {
      const muscle  = document.getElementById('cross-sub1')?.value || '';
      const statKey = document.getElementById('cross-sub2')?.value || 'tonnage';
      if (!muscle) return;
      const sd = PERF_STATS.find(s => s.key === statKey);
      metric = {
        id: `muscle_${muscle}_${statKey}_${Date.now()}`,
        label: `${sd.label} — ${muscle}`,
        unit: sd.unit, dec: sd.dec, axis: sd.axis,
        compute: ago => calcMuscleWeekStat(ago, muscle, statKey),
      };

    } else if (category === 'exercise') {
      const exercise = document.getElementById('cross-sub1')?.value || '';
      const statKey  = document.getElementById('cross-sub2')?.value || 'tonnage';
      if (!exercise) return;
      const sd = PERF_STATS.find(s => s.key === statKey);
      metric = {
        id: `ex_${exercise}_${statKey}_${Date.now()}`,
        label: `${sd.label} — ${exercise}`,
        unit: sd.unit, dec: sd.dec, axis: sd.axis,
        compute: ago => calcExerciseWeekStat(ago, exercise, statKey),
      };
    }

    if (!metric) return;
    metric.color = COLORS[activeMetrics.length % COLORS.length];
    activeMetrics.push(metric);
    updateMetricChips();
    renderCrossChart();
  }

  function removeMetric(id) {
    activeMetrics = activeMetrics.filter(m => m.id !== id);
    // Reassign colours to keep them consistent
    activeMetrics.forEach((m, i) => { m.color = COLORS[i % COLORS.length]; });
    updateMetricChips();
    renderCrossChart();
  }

  function updateMetricChips() {
    const chips = document.getElementById('cross-metric-chips');
    if (!chips) return;
    if (activeMetrics.length === 0) {
      chips.innerHTML = '<span style="color:#94a3b8;font-size:0.85rem;">Aucune métrique ajoutée</span>';
      return;
    }
    chips.innerHTML = activeMetrics.map(m =>
      `<span class="cross-chip" style="display:inline-flex;align-items:center;gap:4px;background:${m.color}18;color:${m.color};border:1.5px solid ${m.color}55;border-radius:20px;padding:3px 10px;font-size:0.82rem;font-weight:600;margin:2px;">
        <span style="display:inline-block;width:9px;height:9px;background:${m.color};border-radius:50%;flex-shrink:0;"></span>
        ${m.label}${m.unit ? ' (' + m.unit + ')' : ''}
        <button data-remove-metric="${m.id}" style="background:none;border:none;cursor:pointer;padding:0 0 0 6px;color:${m.color};font-size:15px;line-height:1;">×</button>
      </span>`
    ).join('');
    chips.querySelectorAll('[data-remove-metric]').forEach(btn => {
      btn.addEventListener('click', () => removeMetric(btn.dataset.removeMetric));
    });
  }

  // ── Chart ─────────────────────────────────────────────────────────────────
  function renderCrossChart() {
    const canvas  = document.getElementById('chart-cross-analysis');
    const empty   = document.getElementById('cross-chart-empty');
    if (!canvas || !empty) return;

    if (crossChart) { crossChart.destroy(); crossChart = null; }

    if (activeMetrics.length === 0 || selectedWeeks.length === 0) {
      empty.style.display = 'flex';
      canvas.style.display = 'none';
      return;
    }

    empty.style.display = 'none';
    canvas.style.display = 'block';

    // Weeks sorted oldest-first for left-to-right chronological display
    const sortedWeeks = [...selectedWeeks].sort((a, b) => b - a);
    const labels = sortedWeeks.map(ago => getWeekBounds(ago).label);

    const round = (v, dec) =>
      v === null || v === undefined ? null :
      dec > 0 ? Math.round(v * Math.pow(10, dec)) / Math.pow(10, dec) : Math.round(v);

    const datasets = activeMetrics.map(metric => ({
      label: metric.label + (metric.unit ? ' (' + metric.unit + ')' : ''),
      data: sortedWeeks.map(ago => round(metric.compute(ago), metric.dec)),
      borderColor: metric.color,
      backgroundColor: metric.color + '18',
      fill: false,
      tension: 0.3,
      yAxisID: metric.axis,
      borderWidth: 2,
      pointRadius: 5,
      pointHoverRadius: 7,
      spanGaps: true,
    }));

    const hasLeft  = activeMetrics.some(m => m.axis === 'y');
    const hasRight = activeMetrics.some(m => m.axis === 'y_right');

    // If only right-axis metrics exist, map them to left so chart doesn't break
    if (!hasLeft && hasRight) {
      datasets.forEach(d => { d.yAxisID = 'y'; });
    }

    const scales = {
      y: {
        type: 'linear', position: 'left',
        grid: { color: 'rgba(0,0,0,0.06)' },
        ticks: { color: '#374151' },
      },
    };
    if (hasLeft && hasRight) {
      scales.y_right = {
        type: 'linear', position: 'right',
        grid: { drawOnChartArea: false },
        ticks: { color: '#374151' },
      };
    }

    crossChart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales,
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label(ctx) {
                const m = activeMetrics[ctx.datasetIndex];
                const v = ctx.parsed.y;
                if (v === null) return `${ctx.dataset.label}: —`;
                return `${ctx.dataset.label}: ${v}${m?.unit ? '\u00a0' + m.unit : ''}`;
              },
            },
          },
        },
      },
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  function tryInit() {
    if (!quickData || !journalFull) return; // wait for both
    populateWeekDropdown();
    updateWeekChips();
    updateCategorySelectors();
    renderCrossChart();
  }

  document.addEventListener('statsDataReady', function () {
    quickData = window.statsQuickData || null;
    tryInit();
  });

  document.addEventListener('statsJournalReady', function () {
    journalFull = window.statsJournalFull || null;
    tryInit();
  });

  // ── DOM setup ─────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    const addBtn    = document.getElementById('cross-add-metric-btn');
    const catSelect = document.getElementById('cross-category');
    const toggleBtn = document.getElementById('cross-week-toggle-btn');

    if (addBtn)    addBtn.addEventListener('click', addMetric);
    if (catSelect) catSelect.addEventListener('change', updateCategorySelectors);
    if (toggleBtn) toggleBtn.addEventListener('click', toggleWeekDropdown);

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
      if (!weekDropdownOpen) return;
      const wrapper = document.getElementById('cross-week-selector-wrapper');
      if (wrapper && !wrapper.contains(e.target)) {
        weekDropdownOpen = true; // will be toggled to false
        toggleWeekDropdown();
      }
    });
  });

  // ── Public API (for onclick attributes if needed) ─────────────────────────
  window.CrossAnalysis = { removeWeek, removeMetric, addMetric };
})();
