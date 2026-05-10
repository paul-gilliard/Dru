document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
  const exSelect = document.getElementById('stats-exercise-select');
  const clearEx = document.getElementById('clear-exercise');
  const performanceLoader = document.getElementById('performance-loader');
  const datePreset = document.getElementById('date-preset');
  const dateStart = document.getElementById('date-start');
  const dateEnd = document.getElementById('date-end');
  const applyDateFilter = document.getElementById('apply-date-filter');

  let journalChart = new Chart(chartJournalCtx, {
    type: 'line',
    data: { 
      labels: [], 
      datasets: [{ label: 'Poids (kg)', data: [], borderColor:'#0b63d6', yAxisID:'y', fill:false, borderWidth:2 }] 
    },
    options: { 
      responsive: true,
      maintainAspectRatio: false,
      interaction:{mode:'index',intersect:false}, 
      scales:{ 
        y:{type:'linear',position:'left'}, 
        y_kcals:{display:false,position:'right'} 
      } 
    }
  });

  let performanceChart = null;
  let otherSeriesChart = null;
  let weeklyVolumeChart = null;
  let muscleRadarChart = null;
  let exerciseCompareChart = null;
  let santeEvolutionChart = null;
  let santeDetailWeek = 0;
  let advancedTonnageData = null;
  let advancedPerfData = null;
  let dateRange = { start: null, end: null };
  let journalData = [];

  // Filter data by date range (for arrays like main_series or other_series)
  function filterByDateRange(data) {
    if (!data || !Array.isArray(data)) return data;
    if (!dateRange.start && !dateRange.end) return data;
    return data.filter(entry => {
      const entryDate = new Date(entry.date);
      const start = dateRange.start ? new Date(dateRange.start) : null;
      const end = dateRange.end ? new Date(dateRange.end) : null;
      if (start && entryDate < start) return false;
      if (end && entryDate > end) return false;
      return true;
    });
  }

  // ── SANTÉ & POIDS ────────────────────────────────────────────────────────

  // Config-driven metrics (all numeric journal fields except weight)
  const SANTE_EVO_METRICS = [
    { id: 'sante-evo-kcals',   dataKey: 'kcals',       label: 'Kcals',      color: '#ef4444', unit: 'kcal', dec: 0, axis: 'y_right' },
    { id: 'sante-evo-protein', dataKey: 'protein',     label: 'Protéines',  color: '#10b981', unit: 'g',    dec: 0, axis: 'y_right' },
    { id: 'sante-evo-carbs',   dataKey: 'carbs',       label: 'Glucides',   color: '#f59e0b', unit: 'g',    dec: 0, axis: 'y_right' },
    { id: 'sante-evo-fats',    dataKey: 'fats',        label: 'Lipides',    color: '#f97316', unit: 'g',    dec: 0, axis: 'y_right' },
    { id: 'sante-evo-water',   dataKey: 'water_ml',    label: 'Eau',        color: '#06b6d4', unit: 'ml',   dec: 0, axis: 'y_right' },
    { id: 'sante-evo-steps',   dataKey: 'steps',       label: 'Pas',        color: '#84cc16', unit: '',     dec: 0, axis: 'y_right' },
    { id: 'sante-evo-sleep',   dataKey: 'sleep_hours', label: 'Sommeil',    color: '#8b5cf6', unit: 'h',    dec: 1, axis: 'y' },
    { id: 'sante-evo-energy',  dataKey: 'energy',      label: 'Énergie',    color: '#eab308', unit: '/10',  dec: 0, axis: 'y' },
    { id: 'sante-evo-stress',  dataKey: 'stress',      label: 'Stress',     color: '#dc2626', unit: '/10',  dec: 0, axis: 'y' },
    { id: 'sante-evo-hunger',  dataKey: 'hunger',      label: 'Faim',       color: '#78716c', unit: '/10',  dec: 0, axis: 'y' },
  ];

  function getSanteWeekBounds(weeksAgo) {
    const d = new Date();
    d.setDate(d.getDate() - weeksAgo * 7);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    const start = new Date(d);
    start.setDate(diff);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    return {
      start: start.toISOString().split('T')[0],
      end:   end.toISOString().split('T')[0],
      label: weeksAgo === 0 ? 'Cette sem.' : `S-${weeksAgo}`
    };
  }

  function calcWeekStats(weeksAgo) {
    const { start, end } = getSanteWeekBounds(weeksAgo);
    const data = journalData.filter(e => e.date >= start && e.date <= end);
    const avg = key => {
      const vals = data.map(e => e[key]).filter(v => v !== null && v !== undefined);
      return vals.length ? vals.reduce((a, b) => a + Number(b), 0) / vals.length : null;
    };
    const stats = { weight: avg('weight'), count: data.length };
    SANTE_EVO_METRICS.forEach(m => { stats[m.dataKey] = avg(m.dataKey); });
    return stats;
  }

  // Returns a colored pill badge for a diff value
  function diffBadge(diff, dec, unit) {
    if (diff === null || diff === undefined) return '<span style="color:#94a3b8;">—</span>';
    const n = Number(diff);
    const abs = Math.abs(n);
    const sign = n > 0 ? '+' : '';
    const label = sign + n.toFixed(dec) + (unit ? '\u00a0' + unit : '');
    if (abs < 0.1) return `<span style="display:inline-flex;align-items:center;gap:3px;background:#f1f5f9;color:#64748b;border-radius:20px;padding:2px 9px;font-size:0.77rem;font-weight:600;">→ stable</span>`;
    if (n > 0) return `<span style="display:inline-flex;align-items:center;gap:3px;background:#dcfce7;color:#166534;border-radius:20px;padding:2px 9px;font-size:0.77rem;font-weight:600;">↑ ${label}</span>`;
    return `<span style="display:inline-flex;align-items:center;gap:3px;background:#fee2e2;color:#991b1b;border-radius:20px;padding:2px 9px;font-size:0.77rem;font-weight:600;">↓ ${label}</span>`;
  }

  function populateSanteWeekSelects() {
    const selA = document.getElementById('sante-week-a');
    const selB = document.getElementById('sante-week-b');
    if (!selA || !selB) return;
    const aVal = selA.value || '0';
    const bVal = selB.value || '1';
    const opts = Array.from({ length: 13 }, (_, i) => {
      const { start, label } = getSanteWeekBounds(i);
      return `<option value="${i}">${label} (${start})</option>`;
    }).join('');
    selA.innerHTML = opts;
    selB.innerHTML = opts;
    selA.value = aVal;
    selB.value = bVal;
  }

  function renderSanteComparison() {
    const aWeeks = parseInt(document.getElementById('sante-week-a')?.value ?? 0);
    const bWeeks = parseInt(document.getElementById('sante-week-b')?.value ?? 1);
    const a = calcWeekStats(aWeeks);
    const b = calcWeekStats(bWeeks);
    const { label: aLabel } = getSanteWeekBounds(aWeeks);
    const { label: bLabel } = getSanteWeekBounds(bWeeks);

    const card = (id, title, icon, color, aVal, bVal, unit, dec) => {
      const el = document.getElementById(id);
      if (!el) return;
      const fmt = v => v !== null ? Number(v).toFixed(dec) : '—';
      const diff = (aVal !== null && bVal !== null) ? aVal - bVal : null;
      el.innerHTML = `
        <div style="background:#f8fafc; border-radius:8px; padding:14px; border-left:4px solid ${color};">
          <div style="font-size:0.78rem; color:#64748b; margin-bottom:10px; font-weight:600;">${icon} ${title}</div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px;">
            <div>
              <div style="font-size:0.7rem; color:#94a3b8; margin-bottom:2px;">${aLabel}</div>
              <div style="font-size:1.25rem; font-weight:700; color:${color};">${fmt(aVal)}${aVal !== null ? ' '+unit : ''}</div>
            </div>
            <div>
              <div style="font-size:0.7rem; color:#94a3b8; margin-bottom:2px;">${bLabel}</div>
              <div style="font-size:1.25rem; font-weight:700; color:#64748b;">${fmt(bVal)}${bVal !== null ? ' '+unit : ''}</div>
            </div>
          </div>
          <div style="border-top:1px solid #e5e7eb; padding-top:8px; text-align:right;">${diffBadge(diff, dec, unit)}</div>
        </div>`;
    };
    card('sante-card-weight', 'Poids moyen',   '⚖️', '#0b63d6', a.weight,      b.weight,      'kg',   1);
    card('sante-card-kcals',  'Kcals moyen',   '🔥', '#ef4444', a.kcals,       b.kcals,       'kcal', 0);
    card('sante-card-water',  'Eau moyenne',   '💧', '#06b6d4', a.water_ml,    b.water_ml,    'ml',   0);
    card('sante-card-sleep',  'Sommeil moyen', '😴', '#8b5cf6', a.sleep_hours, b.sleep_hours, 'h',    1);
  }

  function renderSanteEvolution() {
    const n = parseInt(document.getElementById('sante-evolution-weeks')?.value ?? 8);

    const labels = [];
    const weeklyStats = [];
    for (let i = n - 1; i >= 0; i--) {
      labels.push(getSanteWeekBounds(i).label);
      weeklyStats.push(calcWeekStats(i));
    }

    const datasets = [{
      label: 'Poids (kg)',
      data: weeklyStats.map(s => s.weight !== null ? Math.round(s.weight * 10) / 10 : null),
      borderColor: '#0b63d6', backgroundColor: 'rgba(11,99,214,0.08)',
      fill: true, tension: 0.3, yAxisID: 'y', borderWidth: 2, pointRadius: 4
    }];

    const scales = {
      y: { type: 'linear', position: 'left', title: { display: true, text: 'Poids (kg)' } }
    };
    let hasRightAxis = false;

    SANTE_EVO_METRICS.forEach(m => {
      if (!document.getElementById(m.id)?.checked) return;
      if (m.axis === 'y_right') hasRightAxis = true;
      const round = v => v !== null ? (m.dec > 0 ? Math.round(v * Math.pow(10, m.dec)) / Math.pow(10, m.dec) : Math.round(v)) : null;
      datasets.push({
        label: m.label + (m.unit ? ' (' + m.unit + ')' : ''),
        data: weeklyStats.map(s => round(s[m.dataKey])),
        borderColor: m.color, fill: false, tension: 0.3,
        yAxisID: m.axis, borderWidth: 2, pointRadius: 3
      });
    });

    if (hasRightAxis) {
      scales.y_right = { type: 'linear', position: 'right', grid: { drawOnChartArea: false } };
    }

    if (santeEvolutionChart) { santeEvolutionChart.destroy(); santeEvolutionChart = null; }
    const canvas = document.getElementById('chart-sante-evolution');
    if (!canvas) return;
    santeEvolutionChart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales,
        plugins: { legend: { position: 'bottom' } }
      }
    });
  }

  function renderSanteDetail() {
    const { start, end, label } = getSanteWeekBounds(santeDetailWeek);
    const titleEl = document.getElementById('sante-detail-title');
    const rangeEl = document.getElementById('sante-detail-range');
    const nextBtn = document.getElementById('sante-detail-next');
    if (titleEl) titleEl.textContent = `Détail — ${label}`;
    if (rangeEl) rangeEl.textContent = `${start} → ${end}`;
    if (nextBtn) nextBtn.disabled = santeDetailWeek === 0;

    const viewData = journalData.filter(e => e.date >= start && e.date <= end);
    const fv = (e, k) => (e[k] !== null && e[k] !== undefined) ? Number(e[k]) : null;

    journalChart.data.labels = viewData.map(d => d.date);
    journalChart.data.datasets = [
      { label: 'Poids (kg)',  data: viewData.map(d => fv(d,'weight')),      borderColor:'#0b63d6', fill:false, tension:0.3, yAxisID:'y',       borderWidth:2, pointRadius:4 },
      { label: 'Kcals',       data: viewData.map(d => fv(d,'kcals')),       borderColor:'#ef4444', fill:false, tension:0.3, yAxisID:'y_kcals', borderWidth:2, borderDash:[4,4], pointRadius:3 },
      { label: 'Eau (ml)',    data: viewData.map(d => fv(d,'water_ml')),    borderColor:'#06b6d4', fill:false, tension:0.3, yAxisID:'y',       borderWidth:2, pointRadius:3 },
      { label: 'Sommeil (h)', data: viewData.map(d => fv(d,'sleep_hours')), borderColor:'#8b5cf6', fill:false, tension:0.3, yAxisID:'y',       borderWidth:2, pointRadius:3 }
    ];
    journalChart.options.scales.y_kcals = { display: true, position: 'right', grid: { drawOnChartArea: false } };
    journalChart.update();

    const tbody = document.getElementById('journal-table-body');
    if (!tbody) return;
    const cols = [
      { key: 'weight',      label: 'Poids (kg)',    fmt: v => Number(v).toFixed(1)   },
      { key: 'kcals',       label: 'Kcals',         fmt: v => Math.round(Number(v))  },
      { key: 'protein',     label: 'Prot. (g)',     fmt: v => Math.round(Number(v))  },
      { key: 'carbs',       label: 'Gluc. (g)',     fmt: v => Math.round(Number(v))  },
      { key: 'fats',        label: 'Lip. (g)',      fmt: v => Math.round(Number(v))  },
      { key: 'water_ml',    label: 'Eau (ml)',      fmt: v => Math.round(Number(v))  },
      { key: 'steps',       label: 'Pas',           fmt: v => Math.round(Number(v))  },
      { key: 'sleep_hours', label: 'Sommeil (h)',   fmt: v => Number(v).toFixed(1)   },
      { key: 'energy',      label: 'Énergie',       fmt: v => Number(v) + '/10'      },
      { key: 'stress',      label: 'Stress',        fmt: v => Number(v) + '/10'      },
      { key: 'hunger',      label: 'Faim',          fmt: v => Number(v) + '/10'      },
    ];
    // Rebuild header dynamically
    const thead = tbody.closest('table').querySelector('thead tr');
    if (thead) {
      thead.innerHTML = '<th style="padding:8px; text-align:left; font-weight:600;">Date</th>' +
        cols.map(c => `<th style="padding:8px; text-align:center; font-weight:600;">${c.label}</th>`).join('');
    }
    if (viewData.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${cols.length + 1}" style="padding:20px; text-align:center; color:#94a3b8;">Aucune donnée pour cette semaine</td></tr>`;
      return;
    }
    tbody.innerHTML = '';
    viewData.forEach((e, idx) => {
      const tr = document.createElement('tr');
      tr.style.cssText = `border-bottom:1px solid #e5e7eb; background:${idx % 2 === 0 ? '#fff' : '#f8fafc'};`;
      const cells = `<td style="padding:8px;">${e.date}</td>` +
        cols.map(c => {
          const v = e[c.key];
          const txt = (v !== null && v !== undefined) ? c.fmt(v) : '—';
          return `<td style="padding:8px;text-align:center;">${txt}</td>`;
        }).join('');
      tr.innerHTML = cells;
      tbody.appendChild(tr);
    });
  }

  function renderSante() {
    populateSanteWeekSelects();
    renderSanteComparison();
    renderSanteEvolution();
    renderSanteDetail();
  }

  // Keep backward compat (datePreset, applyDateFilter callers)
  function updateJournalDisplay() { renderSante(); }

  datePreset.addEventListener('change', function() {
    if (!this.value) {
      dateStart.value = '';
      dateEnd.value = '';
      dateRange = { start: null, end: null };
    } else {
      const days = parseInt(this.value);
      const end = new Date();
      const start = new Date(end);
      start.setDate(start.getDate() - days);
      dateStart.value = start.toISOString().split('T')[0];
      dateEnd.value = end.toISOString().split('T')[0];
      dateRange = { start: dateStart.value, end: dateEnd.value };
    }
    const athleteId = athleteSelect.value;
    if (athleteId) {
      loadJournal(athleteId);
      loadPerformance(athleteId);
      loadSummary(athleteId);
    }
  });

  // Apply custom date filter
  applyDateFilter.addEventListener('click', function() {
    dateRange = { start: dateStart.value, end: dateEnd.value };
    datePreset.value = ''; // Clear preset when using custom dates
    const athleteId = athleteSelect.value;
    if (athleteId) {
      loadJournal(athleteId);
      loadPerformance(athleteId);
      loadSummary(athleteId);
    }
  });

  async function loadJournal(athleteId){
    const res = await fetch(`/coach/stats/athlete/${athleteId}/journal.json`);
    if (!res.ok) {
      console.error('Journal fetch failed:', res.status);
      return;
    }
    journalData = await res.json();
    window.statsJournalFull = journalData;
    document.dispatchEvent(new CustomEvent('statsJournalReady', {}));
    santeDetailWeek = 0;
    renderSante();
  }

  let perfCache = null;
  let remarksData = []; // All remarks/notes from performance entries
  let muscleDetailCache = {
    '7days': {},
    '14days': {},
    '21days': {},
    '28days': {}
  }; // Cache for muscle details - preloaded on athlete selection
  
  let seriesCache = {}; // Cache for exercise series data - preloaded
  let currentComparisonContext = {}; // Store current comparison context for series display
  let muscleDetailChart = null;   // Chart.js instance for muscle detail modal
  let exerciseDetailChart = null; // Chart.js instance for exercise detail modal
  
  // Global cache for summary data by athlete
  let summaryCache = {
    '7days': {}, // athleteId -> data
    '14days': {},
    '28days': {}
  };

  // Muscle details are now preloaded via loadQuickData() - no separate function needed
  // Shared in-flight cache: ensures /performance.json is fetched ONCE per athlete,
  // then reused by populateExerciseSelect and loadPerformance.
  let perfFetchPromise = null;
  let perfFetchAthleteId = null;
  function getPerformanceData(athleteId) {
    if (perfFetchAthleteId === athleteId && perfFetchPromise) {
      return perfFetchPromise;
    }
    perfFetchAthleteId = athleteId;
    perfFetchPromise = fetch(`/coach/stats/athlete/${athleteId}/performance.json`)
      .then(res => res.ok ? res.json() : Promise.reject(new Error('perf fetch failed: ' + res.status)));
    return perfFetchPromise;
  }

  // Load and populate all available exercises (do this only once per athlete)
  async function populateExerciseSelect(athleteId) {
    try {
      // Show the loader when starting to fetch exercises
      if (performanceLoader) performanceLoader.classList.add('show');

      const rawData = await getPerformanceData(athleteId);

      // Immediately populate perfCache with raw (unfiltered) data
      // So that renderExercise can display data while loadPerformance filters in background
      perfCache = rawData;

      exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
      if (rawData) {
        Object.keys(rawData).sort().forEach(ex => {
          const opt = document.createElement('option');
          opt.value = ex;
          opt.textContent = ex;
          exSelect.appendChild(opt);
        });
      }
      
      // Hide the loader ONLY when exercises are actually populated
      if (performanceLoader) performanceLoader.classList.remove('show');
      console.log(`Exercises loaded: ${Object.keys(rawData || {}).length} exercises available`);
    } catch (err) {
      console.error('Error populating exercise select:', err);
      if (performanceLoader) performanceLoader.classList.remove('show');
    }
  }

  async function loadPerformance(athleteId){
    if (performanceLoader) performanceLoader.classList.add('show');
    try {
      let rawData;
      try {
        rawData = await getPerformanceData(athleteId);
      } catch (e) {
        return;
      }
      
      // Now filter performance data by date range for display/cache only
      let data = rawData;
      if (dateRange.start || dateRange.end) {
        const filteredData = {};
        Object.keys(data).forEach(ex => {
          const exData = data[ex];
          filteredData[ex] = {
            main_series: exData.main_series ? filterByDateRange(exData.main_series) : [],
            other_series: exData.other_series ? filterByDateRange(exData.other_series) : []
          };
        });
        data = filteredData;
      }
      
      perfCache = data;
      
      // Extract remarks from performance data - check all entries for notes
      remarksData = [];
      Object.keys(data).forEach(exercise => {
        const exData = data[exercise];
        console.log('Checking exercise:', exercise, exData);
        
        if (exData.main_series && Array.isArray(exData.main_series)) {
          exData.main_series.forEach(entry => {
            if (entry.notes && entry.notes.trim()) {
              remarksData.push({
                date: entry.date,
                exercise: exercise,
                notes: entry.notes
              });
            }
          });
        }
        if (exData.other_series && Array.isArray(exData.other_series)) {
          exData.other_series.forEach(entry => {
            if (entry.notes && entry.notes.trim()) {
              remarksData.push({
                date: entry.date,
                exercise: exercise,
                notes: entry.notes
              });
            }
          });
        }
      });
      
      console.log('Total remarks found:', remarksData.length, remarksData);
      
      console.log('Remarks loaded:', remarksData.length);
      displayRemarks();
            
      // clear tables
      document.getElementById('main-series-table').querySelector('tbody').innerHTML = '';
      document.getElementById('other-series-table').querySelector('tbody').innerHTML = '';
      document.getElementById('main-series-container').style.display = 'none';
      document.getElementById('other-series-container').style.display = 'none';
      document.getElementById('perf-chart-container').style.display = 'none';
      document.getElementById('other-series-chart-container').style.display = 'none';
    } finally {
      if (performanceLoader) performanceLoader.classList.remove('show');
    }
  }

  function displayRemarks() {
    const loader = document.getElementById('remarks-loader');
    const container = document.getElementById('remarks-container');
    const body = document.getElementById('remarks-body');
    const empty = document.getElementById('remarks-empty');
    
    if (!loader) return;
    loader.classList.remove('show');
    
    if (!remarksData || remarksData.length === 0) {
      container.style.display = 'block';
      body.innerHTML = '';
      empty.style.display = 'block';
      return;
    }
    
    container.style.display = 'block';
    empty.style.display = 'none';
    body.innerHTML = '';
    
    // Sort by date descending
    remarksData.sort((a, b) => new Date(b.date) - new Date(a.date));
    
    remarksData.forEach((remark, idx) => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #e5e7eb';
      tr.style.background = idx % 2 === 0 ? '#ffffff' : '#f8fafc';
      tr.innerHTML = `
        <td style="padding:10px; font-family:monospace; color:#64748b;">${remark.date}</td>
        <td style="padding:10px; font-weight:500;">${remark.exercise}</td>
        <td style="padding:10px; color:#475569;">${remark.notes}</td>
      `;
      body.appendChild(tr);
    });
  }



  // Generic function to load and cache summary data
  async function loadSummaryData(athleteId, period) {
    // Check cache first
    if (summaryCache[period][athleteId]) {
      console.log(`Returning cached data for athlete ${athleteId}, period ${period}`);
      return summaryCache[period][athleteId];
    }
    
    // Fetch from API
    try {
      const url = `/coach/stats/athlete/${athleteId}/summary-${period}.json`;
      console.log(`Fetching summary data from: ${url}`);
      const res = await fetch(url);
      if (!res.ok) {
        console.error(`Summary ${period} load failed with status ${res.status}`);
        return null;
      }
      const data = await res.json();
      console.log(`Summary ${period} data received:`, data);
      
      // Cache it
      summaryCache[period][athleteId] = data;
      return data;
    } catch (err) {
      console.error(`Error loading summary ${period}:`, err);
      return null;
    }
  }

  // New optimized function: loads all data in ONE API call
  async function loadQuickData(athleteId) {
    try {
      const startTime = performance.now();
      console.log(`Loading quick-data for athlete ${athleteId}...`);
      
      const res = await fetch(`/coach/stats/athlete/${athleteId}/quick-data.json`);
      if (!res.ok) {
        console.error('Quick-data load failed:', res.status);
        return;
      }
      
      const data = await res.json();
      window.statsQuickData = data;
      const endTime = performance.now();
      console.log(`Quick-data loaded in ${(endTime - startTime).toFixed(2)}ms`);

      // Cache the summary data (still keep 7days for legacy code paths)
      if (data.summary_7days) {
        summaryCache['7days'][athleteId] = data.summary_7days;
        if (data.summary_7days.exercise_details_by_muscle) {
          muscleDetailCache['7days'] = data.summary_7days.exercise_details_by_muscle;
        }
      }
      if (data.summary_14days) {
        summaryCache['14days'][athleteId] = data.summary_14days;
        if (data.summary_14days.exercise_details_by_muscle) {
          muscleDetailCache['14days'] = data.summary_14days.exercise_details_by_muscle;
        }
      }
      if (data.summary_21days) {
        summaryCache['21days'] = data.summary_21days;
        if (data.summary_21days.exercise_details_by_muscle) {
          muscleDetailCache['21days'] = data.summary_21days.exercise_details_by_muscle;
        }
      }
      if (data.summary_28days) {
        summaryCache['28days'][athleteId] = data.summary_28days;
        if (data.summary_28days.exercise_details_by_muscle) {
          muscleDetailCache['28days'] = data.summary_28days.exercise_details_by_muscle;
        }
      }
      
      // Cache series data (preloaded)
      if (data.series_by_exercise) {
        seriesCache = data.series_by_exercise;
        console.log(`Preloaded ${Object.keys(seriesCache).length} exercises with series data`);
      }

      // Render coach attention panel (top-right of page) — also drives the dynamic comparison card
      const attentionContainer = document.getElementById('attention-panel-container');
      if (attentionContainer && window.AttentionPanel && window.WeeklyCompare) {
        window.AttentionPanel.render(attentionContainer, data, {
          weeksBack: 13, defaultA: 0, defaultB: 1,
          onChange: (aOff, bOff) => {
            const labelEl = document.getElementById('comparison-1-label');
            if (labelEl) {
              const aL = aOff === 0 ? 'Cette sem.' : ('S-' + aOff);
              const bL = bOff === 0 ? 'Cette sem.' : ('S-' + bOff);
              labelEl.textContent = `(${aL} vs ${bL})`;
            }
            const compData = window.WeeklyCompare.computeComparison(data, aOff, bOff);
            // Cache for muscle-detail drill-downs (key by 'custom')
            if (compData.exercise_details_by_muscle) {
              muscleDetailCache['custom'] = compData.exercise_details_by_muscle;
            }
            displayComparison(1, compData);
          }
        });
      }

      document.dispatchEvent(new CustomEvent('statsDataReady', {}));

    } catch (err) {
      console.error('Error loading quick-data:', err);
    }
  }

  // Generic display function for all 4 comparisons
  async function displayComparison(tableNum, data) {
    if (!data) return;
    
    const formatValue = (val, decimals = 1) => {
      if (val === null || val === undefined) return '—';
      return Number(val).toFixed(decimals);
    };
    
    const loader = document.getElementById(`comparison-${tableNum}-loader`);
    const container = document.getElementById(`comparison-${tableNum}-container`);
    const tbody = document.getElementById(`comparison-${tableNum}-body`);
    
    if (!tbody) return;
    tbody.innerHTML = '';
    
    // Build header with labels
    const headerHtml = `
      <tr style="background:#f3f4f6; border-bottom:2px solid #d1d5db; font-size:0.85rem;">
        <th style="padding:8px; text-align:left; font-weight:600;">Métrique</th>
        <th style="padding:8px; text-align:center; font-weight:600; width:100px;">${data.label1}</th>
        <th style="padding:8px; text-align:center; font-weight:600; width:100px;">${data.label2}</th>
        <th style="padding:8px; text-align:center; font-weight:600; width:80px;">Diff</th>
      </tr>
    `;
    tbody.innerHTML += headerHtml;
    
    // Poids
    let poidsTr = document.createElement('tr');
    poidsTr.style.borderBottom = '1px solid #e5e7eb';
    const poidsCurrent = formatValue(data.weight_current, 2);
    const poidsPrevious = formatValue(data.weight_previous, 2);
    poidsTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Poids (kg)</td>
      <td style="padding:8px; text-align:center;">${poidsCurrent}</td>
      <td style="padding:8px; text-align:center;">${poidsPrevious}</td>
      <td style="padding:8px; text-align:center;">${diffBadge(data.weight_diff, 2, 'kg')}</td>
    `;
    tbody.appendChild(poidsTr);
    
    // Kcals
    let kcalsTr = document.createElement('tr');
    kcalsTr.style.borderBottom = '1px solid #e5e7eb';
    const kcalsCurrent = formatValue(data.kcals_current, 0);
    const kcalsPrevious = formatValue(data.kcals_previous, 0);
    kcalsTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Kcals</td>
      <td style="padding:8px; text-align:center;">${kcalsCurrent}</td>
      <td style="padding:8px; text-align:center;">${kcalsPrevious}</td>
      <td style="padding:8px; text-align:center;">${diffBadge(data.kcals_diff, 0, 'kcal')}</td>
    `;
    tbody.appendChild(kcalsTr);
    
    // Eau
    let eauTr = document.createElement('tr');
    eauTr.style.borderBottom = '1px solid #e5e7eb';
    const eauCurrent = formatValue(data.water_current, 0);
    const eauPrevious = formatValue(data.water_previous, 0);
    eauTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Eau (ml)</td>
      <td style="padding:8px; text-align:center;">${eauCurrent}</td>
      <td style="padding:8px; text-align:center;">${eauPrevious}</td>
      <td style="padding:8px; text-align:center;">${diffBadge(data.water_diff, 0, 'ml')}</td>
    `;
    tbody.appendChild(eauTr);
    
    // Sommeil
    let sommeilTr = document.createElement('tr');
    sommeilTr.style.borderBottom = '1px solid #e5e7eb';
    const sommeilCurrent = formatValue(data.sleep_current, 1);
    const sommeilPrevious = formatValue(data.sleep_previous, 1);
    sommeilTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Sommeil (h)</td>
      <td style="padding:8px; text-align:center;">${sommeilCurrent}</td>
      <td style="padding:8px; text-align:center;">${sommeilPrevious}</td>
      <td style="padding:8px; text-align:center;">${diffBadge(data.sleep_diff, 1, 'h')}</td>
    `;
    tbody.appendChild(sommeilTr);
    
    // Tonnage par muscle with detail buttons
    if (data.tonnage_diff_by_muscle) {
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        
        // Map tableNum to period name for muscle detail cache
        let period = '7days';
        if (tableNum === 2) period = '14days';
        if (tableNum === 3) period = '21days';
        if (tableNum === 4) period = '28days';
        
        tr.innerHTML = `
          <td style="padding:8px; font-weight:600;">${muscle}</td>
          <td style="padding:8px; text-align:center; text-decoration:underline; cursor:pointer;" class="show-muscle-detail" data-muscle="${muscle}" data-summary="${period}" data-label1="${data.label1}" data-label2="${data.label2}">Détails</td>
          <td style="padding:8px; text-align:center;"></td>
          <td style="padding:8px; text-align:center;">${diffBadge(diff, 0, 'kg')}</td>
        `;
        tbody.appendChild(tr);
      });
    }
    
    loader.classList.remove('show');
    container.style.display = 'block';
  }

  async function loadSummary(athleteId){
    try {
      console.log(`loadSummary called for athlete ${athleteId}`);
      const data = await loadSummaryData(athleteId, '7days');
      if (!data) {
        console.error('No data received for 7days summary');
        document.getElementById('summary-7days-loader').classList.remove('show');
        return;
      }
      
      // Update summary values with differences
      const wEl = document.getElementById('summary-weight');
      if (wEl) wEl.innerHTML = diffBadge(data.weight_diff, 2, 'kg');
      
      const kEl = document.getElementById('summary-kcals');
      if (kEl) kEl.innerHTML = diffBadge(data.kcals_diff, 0, 'kcal');
      
      const wtrEl = document.getElementById('summary-water');
      if (wtrEl) wtrEl.innerHTML = diffBadge(data.water_diff, 0, 'ml');
      
      const slEl = document.getElementById('summary-sleep');
      if (slEl) slEl.innerHTML = diffBadge(data.sleep_diff, 1, 'h');
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-tonnage-body');
      if (!tonnageBody) return;
      tonnageBody.innerHTML = '';
      
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffBadge(diff, 0, 'kg')}</td>
          <td style="padding:12px; text-align:center;">
            <button class="show-muscle-detail secondary" data-muscle="${muscle}" data-summary="7days" style="font-size:0.8rem; padding:4px 8px; cursor:pointer;">Détails</button>
          </td>
        `;
        tonnageBody.appendChild(tr);
      });
      
      document.getElementById('summary-7days-loader').classList.remove('show');
      document.getElementById('summary-7days-container').style.display = 'block';
    } catch (err) {
      console.error('Error loading summary:', err);
      document.getElementById('summary-7days-loader').classList.remove('show');
    }
  }

  async function loadSummary14days(athleteId){
    try {
      console.log(`loadSummary14days called for athlete ${athleteId}`);
      const data = await loadSummaryData(athleteId, '14days');
      if (!data) {
        console.error('No data received for 14days summary');
        document.getElementById('summary-14days-loader').classList.remove('show');
        return;
      }
      
      // Update summary values with differences
      document.getElementById('summary-14days-weight').innerHTML = diffBadge(data.weight_diff, 2, 'kg');
      document.getElementById('summary-14days-kcals').innerHTML = diffBadge(data.kcals_diff, 0, 'kcal');
      document.getElementById('summary-14days-water').innerHTML = diffBadge(data.water_diff, 0, 'ml');
      document.getElementById('summary-14days-sleep').innerHTML = diffBadge(data.sleep_diff, 1, 'h');
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-14days-tonnage-body');
      tonnageBody.innerHTML = '';
      
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffBadge(diff, 0, 'kg')}</td>
          <td style="padding:12px; text-align:center;">
            <button class="show-muscle-detail secondary" data-muscle="${muscle}" data-summary="14days" style="font-size:0.8rem; padding:4px 8px; cursor:pointer;">Détails</button>
          </td>
        `;
        tonnageBody.appendChild(tr);
      });
      
      document.getElementById('summary-14days-loader').classList.remove('show');
      document.getElementById('summary-14days-container').style.display = 'block';
    } catch (err) {
      console.error('Error loading summary-14days:', err);
      document.getElementById('summary-14days-loader').classList.remove('show');
    }
  }

  async function loadSummary28days(athleteId){
    try {
      console.log(`loadSummary28days called for athlete ${athleteId}`);
      const data = await loadSummaryData(athleteId, '28days');
      if (!data) {
        console.error('No data received for 28days summary');
        document.getElementById('summary-28days-loader').classList.remove('show');
        return;
      }
      
      // Update summary values with differences
      document.getElementById('summary-28days-weight').innerHTML = diffBadge(data.weight_diff, 2, 'kg');
      document.getElementById('summary-28days-kcals').innerHTML = diffBadge(data.kcals_diff, 0, 'kcal');
      document.getElementById('summary-28days-water').innerHTML = diffBadge(data.water_diff, 0, 'ml');
      document.getElementById('summary-28days-sleep').innerHTML = diffBadge(data.sleep_diff, 1, 'h');
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-28days-tonnage-body');
      tonnageBody.innerHTML = '';
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffBadge(diff, 0, 'kg')}</td>
          <td style="padding:12px; text-align:center;">
            <button class="show-muscle-detail secondary" data-muscle="${muscle}" data-summary="28days" style="font-size:0.8rem; padding:4px 8px; cursor:pointer;">Détails</button>
          </td>
        `;
        tonnageBody.appendChild(tr);
      });
      
      document.getElementById('summary-28days-loader').classList.remove('show');
      document.getElementById('summary-28days-container').style.display = 'block';
    } catch (err) {
      console.error('Error loading summary-28days:', err);
      document.getElementById('summary-28days-loader').classList.remove('show');
    }
  }

  function renderExercise(ex){
    console.log('renderExercise called with:', ex, 'perfCache:', perfCache);
    if (!perfCache || !perfCache[ex]) {
      console.warn(`No data in perfCache for exercise: ${ex}`);
      return;
    }
    
    const mainSeriesContainer = document.getElementById('main-series-container');
    const otherSeriesContainer = document.getElementById('other-series-container');
    const perfChartContainer = document.getElementById('perf-chart-container');
    const mainTableBody = document.getElementById('main-series-table').querySelector('tbody');
    const otherTableBody = document.getElementById('other-series-table').querySelector('tbody');
    
    mainTableBody.innerHTML = '';
    otherTableBody.innerHTML = '';
    
    const data = perfCache[ex];
    console.log('Exercise data:', data);
    
    // Render main series
    if (data.main_series && data.main_series.length > 0) {
      mainSeriesContainer.style.display = 'block';
      data.main_series.forEach(row => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        tr.innerHTML = `
          <td style="padding:12px;">${row.date}</td>
          <td style="padding:12px; text-align:center;">${row.reps !== null ? row.reps : '—'}</td>
          <td style="padding:12px; text-align:center;">${row.load !== null ? row.load.toFixed(1) : '—'}</td>
        `;
        mainTableBody.appendChild(tr);
      });
      
      // Create performance chart for main series
      createPerformanceChart(data.main_series);
      perfChartContainer.style.display = 'block';
    } else {
      mainSeriesContainer.style.display = 'none';
      perfChartContainer.style.display = 'none';
    }
    
    // Render other series
    if (data.other_series && data.other_series.length > 0) {
      otherSeriesContainer.style.display = 'block';
      data.other_series.forEach(row => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        tr.innerHTML = `
          <td style="padding:12px;">${row.date}</td>
          <td style="padding:12px; text-align:center;">${row.avg_reps !== null ? row.avg_reps.toFixed(1) : '—'}</td>
          <td style="padding:12px; text-align:center;">${row.avg_load !== null ? row.avg_load.toFixed(1) : '—'}</td>
          <td style="padding:12px; text-align:center;">${row.count}</td>
        `;
        otherTableBody.appendChild(tr);
      });
      
      // Create chart for other series
      createOtherSeriesChart(data.other_series);
      document.getElementById('other-series-chart-container').style.display = 'block';
    } else {
      otherSeriesContainer.style.display = 'none';
      document.getElementById('other-series-chart-container').style.display = 'none';
    }
  }

  function createPerformanceChart(mainSeriesData){
    const perfCtx = document.getElementById('chart-performance').getContext('2d');
    
    // Destroy old chart if exists
    if (performanceChart) {
      performanceChart.destroy();
    }
    
    const labels = mainSeriesData.map(d => d.date);
    const reps = mainSeriesData.map(d => d.reps !== null ? d.reps : null);
    const load = mainSeriesData.map(d => d.load !== null ? d.load : null);
    
    performanceChart = new Chart(perfCtx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Reps',
            data: reps,
            backgroundColor: 'rgba(11, 99, 214, 0.7)',
            borderColor: '#0b63d6',
            borderWidth: 1,
            yAxisID: 'y',
            type: 'bar'
          },
          {
            label: 'Poids (kg)',
            data: load,
            borderColor: '#ef4444',
            backgroundColor: 'transparent',
            tension: 0.3,
            yAxisID: 'y1',
            pointBackgroundColor: '#ef4444',
            pointRadius: 5,
            pointBorderWidth: 2,
            type: 'line',
            borderWidth: 2
          }
        ]
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'Reps', font: { weight: 'bold' } },
            beginAtZero: true
          },
          y1: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'Poids (kg)', font: { weight: 'bold' } },
            grid: { drawOnChartArea: false }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top'
          }
        }
      }
    });
  }

  function createOtherSeriesChart(otherSeriesData){
    const otherCtx = document.getElementById('chart-other-series').getContext('2d');
    
    // Destroy old chart if exists
    if (otherSeriesChart) {
      otherSeriesChart.destroy();
    }
    
    const labels = otherSeriesData.map(d => d.date);
    const avgReps = otherSeriesData.map(d => d.avg_reps !== null ? d.avg_reps : null);
    const avgLoad = otherSeriesData.map(d => d.avg_load !== null ? d.avg_load : null);
    
    otherSeriesChart = new Chart(otherCtx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Reps (moy.)',
            data: avgReps,
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            yAxisID: 'y',
            type: 'bar'
          },
          {
            label: 'Poids moy. (kg)',
            data: avgLoad,
            borderColor: '#f97316',
            backgroundColor: 'transparent',
            tension: 0.3,
            yAxisID: 'y1',
            pointBackgroundColor: '#f97316',
            pointRadius: 5,
            pointBorderWidth: 2,
            type: 'line',
            borderWidth: 2
          }
        ]
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'Reps (moy.)', font: { weight: 'bold' } },
            beginAtZero: true
          },
          y1: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'Poids moy. (kg)', font: { weight: 'bold' } },
            grid: { drawOnChartArea: false }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top'
          }
        }
      }
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ADVANCED STATS — Features 1, 3, 4, 5
  // ─────────────────────────────────────────────────────────────────────────

  /** Returns ISO-8601 week key, e.g. "2024-W04" */
  function getISOWeekKey(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 4 - (d.getDay() || 7));
    const yearStart = new Date(d.getFullYear(), 0, 1);
    const weekNum = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return `${d.getFullYear()}-W${String(weekNum).padStart(2, '0')}`;
  }

  function getCurrentAndPrevWeekKeys() {
    const today = new Date();
    const prevWeek = new Date(today);
    prevWeek.setDate(today.getDate() - 7);
    return { current: getISOWeekKey(today), prev: getISOWeekKey(prevWeek) };
  }

  function getWeekKeyAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n * 7);
    return getISOWeekKey(d);
  }

  function setTabLoading(tabName, loading) {
    const s = document.getElementById('tab-spinner-' + tabName);
    if (s) s.classList.toggle('loading', loading);
  }

  function renderAdvancedCharts() {
    if (advancedTonnageData === null || advancedPerfData === null) return;
    renderWeeklyVolume(advancedTonnageData);
    renderMuscleRadar(advancedTonnageData);
    renderExerciseWeekComparison(advancedPerfData);
  }

  async function loadAndRenderAdvancedStats(athleteId) {
    const section = document.getElementById('advanced-stats-section');
    if (!section) return;
    try {
      // Fetch only tonnage (performance data is already in perfCache from loadPerformance)
      const tonnageRes = await fetch(`/coach/stats/athlete/${athleteId}/tonnage-by-muscle.json`);
      advancedTonnageData = tonnageRes.ok ? await tonnageRes.json() : {};
      // perfCache is populated by loadPerformance which runs in parallel — wait for it
      advancedPerfData = perfCache || {};
      section.style.display = 'block';
      renderRegularity(advancedPerfData);
      // Render charts immediately if the analyse tab is currently visible
      if (document.getElementById('tab-analyse').classList.contains('active')) {
        renderAdvancedCharts();
      }
      setTabLoading('analyse', false);
    } catch (err) {
      console.error('Error loading advanced stats:', err);
      setTabLoading('analyse', false);
    }
  }

  /** Feature 5 — Sessions per week over last 4 weeks */
  function renderRegularity(perfData) {
    const container = document.getElementById('regularity-container');
    const empty     = document.getElementById('regularity-empty');
    const badges    = document.getElementById('regularity-badges');
    if (!container || !badges) return;

    const dateSet = new Set();
    Object.values(perfData).forEach(ex => {
      (ex.main_series  || []).forEach(s => dateSet.add(s.date));
      (ex.other_series || []).forEach(s => dateSet.add(s.date));
    });

    if (dateSet.size === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    const today = new Date();
    const weeks = [];
    for (let w = 3; w >= 0; w--) {
      const ref = new Date(today);
      ref.setDate(today.getDate() - w * 7);
      weeks.push({ key: getISOWeekKey(ref), label: w === 0 ? 'Cette sem.' : `S-${w}`, count: 0 });
    }

    dateSet.forEach(dateStr => {
      const key = getISOWeekKey(new Date(dateStr));
      const w = weeks.find(w => w.key === key);
      if (w) w.count++;
    });

    const colors = ['#e5e7eb', '#f59e0b', '#0b63d6', '#10b981'];
    badges.innerHTML = weeks.map(w => {
      const colorIdx = Math.min(w.count, 3);
      const bg = colors[colorIdx];
      const textColor = colorIdx === 0 ? '#94a3b8' : 'white';
      return `<div style="background:${bg}; color:${textColor}; border-radius:8px; padding:12px 20px; text-align:center; min-width:90px;">
        <div style="font-size:0.78rem; margin-bottom:4px; opacity:0.9;">${w.label}</div>
        <div style="font-size:1.6rem; font-weight:700; line-height:1;">${w.count}</div>
        <div style="font-size:0.72rem; margin-top:4px;">séance${w.count !== 1 ? 's' : ''}</div>
      </div>`;
    }).join('');

    container.style.display = 'block';
    empty.style.display = 'none';
  }

  /** Feature 1 — Weekly volume stacked bar chart */
  function renderWeeklyVolume(tonnageData) {
    const container = document.getElementById('weekly-volume-container');
    const empty     = document.getElementById('weekly-volume-empty');
    if (!container) return;

    if (weeklyVolumeChart) { weeklyVolumeChart.destroy(); weeklyVolumeChart = null; }

    if (Object.keys(tonnageData).length === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    const weeklyTonnage = {};
    Object.entries(tonnageData).forEach(([muscle, dates]) => {
      dates.forEach(({ date, tonnage }) => {
        const key = getISOWeekKey(new Date(date));
        if (!weeklyTonnage[key]) weeklyTonnage[key] = {};
        weeklyTonnage[key][muscle] = (weeklyTonnage[key][muscle] || 0) + tonnage;
      });
    });

    const weekKeys = Object.keys(weeklyTonnage).sort().slice(-8);
    if (weekKeys.length === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    const muscles = [...new Set(Object.values(weeklyTonnage).flatMap(w => Object.keys(w)))].sort();
    const palette = ['#0b63d6','#ef4444','#10b981','#f59e0b','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#64748b'];
    const datasets = muscles.map((m, i) => ({
      label: m,
      data: weekKeys.map(k => Math.round(weeklyTonnage[k]?.[m] || 0)),
      backgroundColor: palette[i % palette.length]
    }));

    container.style.display = 'block';
    empty.style.display = 'none';
    weeklyVolumeChart = new Chart(document.getElementById('chart-weekly-volume'), {
      type: 'bar',
      data: { labels: weekKeys, datasets },
      options: {
        responsive: true,
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, title: { display: true, text: 'Tonnage (kg)' } } },
        plugins: { legend: { position: 'bottom' } }
      }
    });
  }

  /** Feature 4 — Muscle radar (dynamic week comparison) */
  function renderMuscleRadar(tonnageData) {
    const container = document.getElementById('muscle-radar-container');
    const empty     = document.getElementById('muscle-radar-empty');
    if (!container) return;

    if (muscleRadarChart) { muscleRadarChart.destroy(); muscleRadarChart = null; }

    if (Object.keys(tonnageData).length === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    const modeSelect = document.getElementById('radar-compare-mode');
    const mode = modeSelect ? modeSelect.value : '0-1';
    const [aWeeks, bWeeks] = mode.split('-').map(Number);
    const aKey = getWeekKeyAgo(aWeeks);
    const bKey = getWeekKeyAgo(bWeeks);
    const weekLabel = n => n === 0 ? 'Cette semaine' : `S-${n}`;

    const weeklyTonnage = {};
    Object.entries(tonnageData).forEach(([muscle, dates]) => {
      dates.forEach(({ date, tonnage }) => {
        const key = getISOWeekKey(new Date(date));
        if (!weeklyTonnage[key]) weeklyTonnage[key] = {};
        weeklyTonnage[key][muscle] = (weeklyTonnage[key][muscle] || 0) + tonnage;
      });
    });

    const muscles = Object.keys(tonnageData).sort();
    const aData = muscles.map(m => Math.round(weeklyTonnage[aKey]?.[m] || 0));
    const bData = muscles.map(m => Math.round(weeklyTonnage[bKey]?.[m] || 0));

    if ([...aData, ...bData].every(v => v === 0)) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    container.style.display = 'block';
    empty.style.display = 'none';
    muscleRadarChart = new Chart(document.getElementById('chart-muscle-radar'), {
      type: 'radar',
      data: {
        labels: muscles,
        datasets: [
          { label: weekLabel(aWeeks), data: aData, borderColor: '#0b63d6', backgroundColor: 'rgba(11,99,214,0.15)', pointBackgroundColor: '#0b63d6' },
          { label: weekLabel(bWeeks), data: bData, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.12)', pointBackgroundColor: '#ef4444' }
        ]
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom' } }
      }
    });
  }

  /** Feature 3 — Exercise comparison (dynamic: S vs S-1, S vs S-2, S-1 vs S-2, S-1 vs S-3) */
  function renderExerciseWeekComparison(perfData) {
    const container = document.getElementById('exercise-compare-container');
    const empty     = document.getElementById('exercise-compare-empty');
    if (!container) return;

    if (exerciseCompareChart) { exerciseCompareChart.destroy(); exerciseCompareChart = null; }

    if (Object.keys(perfData).length === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    const modeSelect = document.getElementById('exercise-compare-mode');
    const mode = modeSelect ? modeSelect.value : '0-1';
    const [aWeeks, bWeeks] = mode.split('-').map(Number);
    const aKey = getWeekKeyAgo(aWeeks);
    const bKey = getWeekKeyAgo(bWeeks);
    const weekLabel = n => n === 0 ? 'Cette semaine' : `S-${n}`;
    const aLabel = weekLabel(aWeeks) + ' (kg)';
    const bLabel = weekLabel(bWeeks) + ' (kg)';

    const maxLoad = series => {
      const vals = series.map(s => s.load || s.avg_load || 0).filter(v => v > 0);
      return vals.length ? Math.max(...vals) : 0;
    };

    const exercises = [];
    Object.entries(perfData).forEach(([name, ex]) => {
      const all = [...(ex.main_series || []), ...(ex.other_series || [])];
      const a = maxLoad(all.filter(s => getISOWeekKey(new Date(s.date)) === aKey));
      const b = maxLoad(all.filter(s => getISOWeekKey(new Date(s.date)) === bKey));
      if (a > 0 || b > 0) exercises.push({ name, a, b });
    });

    if (exercises.length === 0) {
      empty.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    exercises.sort((x, y) => (y.a || y.b) - (x.a || x.b));
    const top = exercises.slice(0, 10);

    container.style.display = 'block';
    empty.style.display = 'none';
    exerciseCompareChart = new Chart(document.getElementById('chart-exercise-compare'), {
      type: 'bar',
      data: {
        labels: top.map(e => e.name),
        datasets: [
          { label: aLabel, data: top.map(e => e.a), backgroundColor: '#0b63d6' },
          { label: bLabel, data: top.map(e => e.b), backgroundColor: 'rgba(239,68,68,0.75)' }
        ]
      },
      options: {
        responsive: true,
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { position: 'bottom' } }
      }
    });
  }

  athleteSelect.addEventListener('change', async function(){
    const athleteId = this.value;
    if (!athleteId) {
      // Hide loaders when no athlete selected
      const remarksLoader = document.getElementById('remarks-loader');
      if (remarksLoader) remarksLoader.classList.remove('show');
      // Reset attention panel placeholder
      const attentionContainer = document.getElementById('attention-panel-container');
      if (attentionContainer) {
        attentionContainer.innerHTML = `<div style="background:#fff;border:1px dashed #cbd5e1;border-radius:8px;padding:24px;text-align:center;color:#94a3b8;font-size:0.9rem;">🎯 Sélectionnez un athlète pour voir les points d'attention</div>`;
      }
      return;
    }
    
    // Show loaders when athlete is selected
    const remarksLoader = document.getElementById('remarks-loader');
    if (remarksLoader) remarksLoader.classList.add('show');

    // Reset advanced data and show tab spinners
    advancedTonnageData = null;
    advancedPerfData = null;
    setTabLoading('recaps', true);
    setTabLoading('sante', true);
    setTabLoading('exercices', true);
    setTabLoading('analyse', true);
    
    // Clear performance data
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
    document.getElementById('perf-chart-container').style.display = 'none';
    document.getElementById('other-series-chart-container').style.display = 'none';
    
    // Load journal data
    console.log(`Loading journal for athlete ${athleteId}...`);
    await loadJournal(athleteId);
    setTabLoading('sante', false);
    
    // Load quick-data FIRST (all summaries + exercise details in one call) - BLOCKING
    console.log(`Loading quick-data for athlete ${athleteId}...`);
    await loadQuickData(athleteId);
    setTabLoading('recaps', false);
    
    // Show content NOW (recaps + sante are ready)
    document.getElementById('no-athlete-msg').style.display = 'none';
    document.getElementById('stats-panes-wrapper').style.display = 'block';

    // Populate exercise select + load performance (non-blocking from here)
    console.log('Populating exercise select...');
    populateExerciseSelect(athleteId);
    
    // Load performance then advanced stats (share the same data)
    console.log('Starting background load of performance...');
    loadPerformance(athleteId).then(() => {
      setTabLoading('exercices', false);
      console.log('Performance loaded');
      loadAndRenderAdvancedStats(athleteId);
    }).catch(err => {
      console.error('Performance load failed:', err);
      setTabLoading('exercices', false);
      setTabLoading('analyse', false);
    });
  });
  exSelect.addEventListener('change', function(){
    const ex = this.value;
    console.log('Exercise select changed to:', ex);
    if (!ex) { 
      document.getElementById('main-series-container').style.display = 'none';
      document.getElementById('other-series-container').style.display = 'none';
      document.getElementById('perf-chart-container').style.display = 'none';
      document.getElementById('other-series-chart-container').style.display = 'none';
      return; 
    }
    renderExercise(ex);
  });

  clearEx.addEventListener('click', function(){
    exSelect.value = '';
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
    document.getElementById('perf-chart-container').style.display = 'none';
    document.getElementById('other-series-chart-container').style.display = 'none';
  });

  // Re-render radar when mode changes
  const radarMode = document.getElementById('radar-compare-mode');
  if (radarMode) {
    radarMode.addEventListener('change', function() {
      if (advancedTonnageData) renderMuscleRadar(advancedTonnageData);
    });
  }

  // Re-render exercise comparison when mode changes
  const exCompareMode = document.getElementById('exercise-compare-mode');
  if (exCompareMode) {
    exCompareMode.addEventListener('change', function() {
      if (advancedPerfData) renderExerciseWeekComparison(advancedPerfData);
    });
  }

  // Santé & Poids – event listeners
  document.getElementById('sante-week-a')?.addEventListener('change', renderSanteComparison);
  document.getElementById('sante-week-b')?.addEventListener('change', renderSanteComparison);
  document.getElementById('sante-evolution-weeks')?.addEventListener('change', renderSanteEvolution);
  SANTE_EVO_METRICS.forEach(m => {
    document.getElementById(m.id)?.addEventListener('change', renderSanteEvolution);
  });
  document.getElementById('sante-detail-prev')?.addEventListener('click', function() {
    santeDetailWeek++;
    renderSanteDetail();
  });
  document.getElementById('sante-detail-next')?.addEventListener('click', function() {
    santeDetailWeek = Math.max(0, santeDetailWeek - 1);
    renderSanteDetail();
  });

  // Event delegation for muscle detail buttons - data is preloaded in cache
  document.addEventListener('click', function(e) {
    if (!e.target.matches('.show-muscle-detail')) return;

    const muscle  = e.target.getAttribute('data-muscle');
    const summary = e.target.getAttribute('data-summary');
    const label1  = e.target.getAttribute('data-label1') || 'Période courante';
    const label2  = e.target.getAttribute('data-label2') || 'Période précédente';

    currentComparisonContext = { summary, label1, label2 };

    document.getElementById('muscle-detail-title').textContent = `${muscle} — ${label1} vs ${label2}`;
    document.getElementById('muscle-detail-content').innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;gap:12px;">
        <div class="spinner"></div>
        <span style="color:#94a3b8;font-size:0.9rem;">Chargement...</span>
      </div>`;
    document.getElementById('muscle-detail-modal').style.display = 'flex';

    if (!muscleDetailCache[summary] || !muscleDetailCache[summary][muscle]) {
      document.getElementById('muscle-detail-content').innerHTML = '<p style="color:#ef4444;">Données non disponibles</p>';
      return;
    }

    const exByMuscle = muscleDetailCache[summary][muscle];
    const exercises  = Object.keys(exByMuscle).sort();

    setTimeout(() => {
      // ── Bar chart datasets ────────────────────────────────────────────────
      const currentTons  = exercises.map(ex => (exByMuscle[ex].current  || 0) / 1000);
      const previousTons = exercises.map(ex => (exByMuscle[ex].previous || 0) / 1000);
      const barColors    = exercises.map(ex => (exByMuscle[ex].diff || 0) >= 0
        ? 'rgba(16,185,129,0.8)' : 'rgba(239,68,68,0.8)');

      // ── Table rows ────────────────────────────────────────────────────────
      const tableRows = exercises.map(ex => {
        const cur  = exByMuscle[ex].current  || 0;
        const prev = exByMuscle[ex].previous || 0;
        const diff = exByMuscle[ex].diff     || 0;
        const pct  = prev > 0 ? Math.round(diff / prev * 100) : null;
        const color  = diff > 0.5 ? '#10b981' : diff < -0.5 ? '#ef4444' : '#9ca3af';
        const arrow  = diff > 0.5 ? '▲' : diff < -0.5 ? '▼' : '→';
        const pctStr = pct !== null ? ` (${pct > 0 ? '+' : ''}${pct}%)` : '';
        return `<tr style="border-bottom:1px solid #e5e7eb;">
          <td style="padding:8px 6px;font-weight:500;">${ex}</td>
          <td style="padding:8px 6px;text-align:center;font-weight:600;">${(cur/1000).toFixed(1)}&nbsp;T</td>
          <td style="padding:8px 6px;text-align:center;color:#64748b;">${(prev/1000).toFixed(1)}&nbsp;T</td>
          <td style="padding:8px 6px;text-align:center;font-weight:700;color:${color};">${arrow}${pctStr}</td>
          <td style="padding:8px 6px;text-align:center;">
            <button class="show-exercise-series secondary" data-exercise="${ex}"
              style="font-size:0.75rem;padding:3px 10px;cursor:pointer;">Voir ▸</button>
          </td>
        </tr>`;
      }).join('');

      const chartH = Math.max(130, exercises.length * 34);
      document.getElementById('muscle-detail-content').innerHTML = `
        <div style="position:relative;height:${chartH}px;margin-bottom:18px;">
          <canvas id="muscle-detail-chart"></canvas>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead>
            <tr style="background:#f3f4f6;border-bottom:2px solid #d1d5db;">
              <th style="padding:8px 6px;text-align:left;">Exercice</th>
              <th style="padding:8px 6px;text-align:center;">${label1}</th>
              <th style="padding:8px 6px;text-align:center;">${label2}</th>
              <th style="padding:8px 6px;text-align:center;">Évolution</th>
              <th style="padding:8px 6px;text-align:center;">Détail</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>`;

      // ── Create bar chart ──────────────────────────────────────────────────
      if (muscleDetailChart) { muscleDetailChart.destroy(); muscleDetailChart = null; }
      const mdCtx = document.getElementById('muscle-detail-chart').getContext('2d');
      muscleDetailChart = new Chart(mdCtx, {
        type: 'bar',
        data: {
          labels: exercises,
          datasets: [
            {
              label: label1,
              data: currentTons,
              backgroundColor: barColors,
              borderRadius: 4,
              order: 1,
            },
            {
              label: label2,
              data: previousTons,
              backgroundColor: 'rgba(148,163,184,0.4)',
              borderRadius: 4,
              order: 2,
            }
          ]
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 14 } },
            tooltip: { callbacks: { label: c => ` ${c.parsed.x.toFixed(2)} T` } }
          },
          scales: {
            x: { beginAtZero: true, title: { display: true, text: 'Tonnage (T)' }, grid: { color: 'rgba(0,0,0,0.05)' } },
            y: { ticks: { font: { size: 11 } } }
          }
        }
      });
    }, 50);
  });

  // Event delegation for exercise series detail buttons
  document.addEventListener('click', function(e) {
    if (!e.target.matches('.show-exercise-series')) return;

    const exercise = e.target.getAttribute('data-exercise');

    document.getElementById('series-detail-title').textContent = exercise;
    document.getElementById('series-detail-content').innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;gap:12px;">
        <div class="spinner"></div>
        <span style="color:#94a3b8;font-size:0.9rem;">Chargement...</span>
      </div>`;
    document.getElementById('series-detail-modal').style.display = 'flex';

    setTimeout(() => {
      // ── 1. Build time-series points (one per session date) ─────────────────
      const rawData = seriesCache[exercise] || {};
      const dates   = Object.keys(rawData).sort();

      const datePoints = dates.map(d => {
        const ss    = rawData[d];
        const loads = ss.map(s => s.load).filter(v => v != null);
        const repsA = ss.map(s => s.reps).filter(v => v != null);
        return {
          date:    d,
          maxLoad: loads.length ? Math.max(...loads)                                   : null,
          avgLoad: loads.length ? loads.reduce((a,b)=>a+b,0)/loads.length             : null,
          avgReps: repsA.length ? repsA.reduce((a,b)=>a+b,0)/repsA.length            : null,
          series:  ss,
        };
      });

      // ── 2. Trend badge (compare last 3 sessions vs 3 before that) ──────────
      let trendHtml = '';
      const loadPts = datePoints.filter(p => p.maxLoad !== null);
      if (loadPts.length >= 4) {
        const half    = Math.min(3, Math.floor(loadPts.length / 2));
        const last    = loadPts.slice(-half).map(p => p.maxLoad);
        const before  = loadPts.slice(-half * 2, -half).map(p => p.maxLoad);
        const avgLast = last.reduce((a,b)=>a+b,0) / last.length;
        const avgBef  = before.reduce((a,b)=>a+b,0) / before.length;
        const delta   = avgLast - avgBef;
        const pct     = avgBef > 0 ? (delta / avgBef * 100).toFixed(1) : null;
        const pctStr  = pct !== null ? ` — ${pct > 0 ? '+' : ''}${pct}% vs séances précédentes` : '';
        if (delta > 0.5) {
          trendHtml = `<div style="display:inline-flex;align-items:center;gap:8px;background:#ecfdf5;border:2px solid #10b981;border-radius:20px;padding:7px 18px;margin-bottom:16px;font-weight:700;color:#065f46;font-size:0.95rem;">
            ▲ En progression<span style="font-weight:400;font-size:0.82rem;">${pctStr}</span></div>`;
        } else if (delta < -0.5) {
          trendHtml = `<div style="display:inline-flex;align-items:center;gap:8px;background:#fef2f2;border:2px solid #ef4444;border-radius:20px;padding:7px 18px;margin-bottom:16px;font-weight:700;color:#991b1b;font-size:0.95rem;">
            ▼ En baisse<span style="font-weight:400;font-size:0.82rem;">${pctStr}</span></div>`;
        } else {
          trendHtml = `<div style="display:inline-flex;align-items:center;gap:8px;background:#f8fafc;border:2px solid #94a3b8;border-radius:20px;padding:7px 18px;margin-bottom:16px;font-weight:700;color:#475569;font-size:0.95rem;">→ Stable</div>`;
        }
      }

      // ── 3. Line color based on trend ───────────────────────────────────────
      let lineColor  = '#0b63d6';
      let fillColor  = 'rgba(11,99,214,0.08)';
      if (loadPts.length >= 4) {
        const half   = Math.min(3, Math.floor(loadPts.length / 2));
        const avgL   = loadPts.slice(-half).map(p=>p.maxLoad).reduce((a,b)=>a+b,0)/half;
        const avgP   = loadPts.slice(-half*2,-half).map(p=>p.maxLoad).reduce((a,b)=>a+b,0)/half;
        if (avgL > avgP + 0.5)      { lineColor = '#10b981'; fillColor = 'rgba(16,185,129,0.08)'; }
        else if (avgL < avgP - 0.5) { lineColor = '#ef4444'; fillColor = 'rgba(239,68,68,0.08)'; }
      }

      // ── 4. Week boundaries for comparison columns ──────────────────────────
      const summary = currentComparisonContext.summary || '7days';
      const label1  = currentComparisonContext.label1  || 'Période courante';
      const label2  = currentComparisonContext.label2  || 'Période précédente';

      function getMonday(d) {
        const day = d.getDay(), diff = d.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(new Date(d).setDate(diff));
      }
      function addDays(d, n) { return new Date(new Date(d).setDate(d.getDate() + n)); }
      function iso(d) { return d.toISOString().split('T')[0]; }

      const mon = getMonday(new Date());
      const wb  = {
        S:  { s: iso(mon),              e: iso(addDays(mon,  6)) },
        S1: { s: iso(addDays(mon, -7)), e: iso(addDays(mon, -1)) },
        S2: { s: iso(addDays(mon,-14)), e: iso(addDays(mon, -8)) },
        S3: { s: iso(addDays(mon,-21)), e: iso(addDays(mon,-15)) },
      };
      const periodKey = { '7days':['S','S1'], '14days':['S','S2'], '21days':['S1','S2'], '28days':['S1','S3'] };
      const [curKey, prevKey] = periodKey[summary] || ['S','S1'];
      const inRange = (d, b) => d >= b.s && d <= b.e;
      const curDates  = dates.filter(d => inRange(d, wb[curKey]));
      const prevDates = dates.filter(d => inRange(d, wb[prevKey]));

      // ── 5. Session card builder ────────────────────────────────────────────
      const buildCard = d => {
        const ss = (rawData[d] || []).slice().sort((a,b)=>(a.series_number||0)-(b.series_number||0));
        const rows = ss.map(s => {
          const reps = s.reps != null ? s.reps : '—';
          const load = s.load != null ? `${s.load} kg` : '—';
          const rpe  = s.rpe  != null ? `RPE ${s.rpe}` : '—';
          return `<tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:3px 6px;text-align:center;color:#94a3b8;font-size:0.78rem;">S${s.series_number||'?'}</td>
            <td style="padding:3px 6px;text-align:center;font-weight:700;color:#0b63d6;">${reps}</td>
            <td style="padding:3px 6px;text-align:center;font-weight:700;color:#374151;">${load}</td>
            <td style="padding:3px 6px;text-align:center;color:#94a3b8;font-size:0.78rem;">${rpe}</td>
          </tr>`;
        }).join('');
        return `<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin-bottom:8px;background:#fff;">
          <div style="font-size:0.8rem;font-weight:600;color:#475569;margin-bottom:6px;">${d}</div>
          <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
            <thead><tr style="border-bottom:1px solid #e5e7eb;">
              <th style="padding:3px 6px;color:#94a3b8;font-weight:500;">#</th>
              <th style="padding:3px 6px;color:#94a3b8;font-weight:500;">Reps</th>
              <th style="padding:3px 6px;color:#94a3b8;font-weight:500;">Poids</th>
              <th style="padding:3px 6px;color:#94a3b8;font-weight:500;">RPE</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
      };

      const buildCol = (periodDates, periodLabel, isCurrent) => {
        const bg  = isCurrent ? '#f0fdf4' : '#f8fafc';
        const bdr = isCurrent ? '#bbf7d0' : '#e2e8f0';
        const content = periodDates.length
          ? periodDates.map(buildCard).join('')
          : `<div style="color:#94a3b8;text-align:center;padding:20px;font-size:0.85rem;">Aucune séance</div>`;
        return `<div style="border:1px solid ${bdr};border-radius:8px;padding:12px;background:${bg};">
          <div style="font-weight:700;font-size:0.85rem;color:#374151;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid ${bdr};">${periodLabel}</div>
          ${content}
        </div>`;
      };

      // ── 6. Assemble HTML ───────────────────────────────────────────────────
      const hasChart = datePoints.length > 0;
      document.getElementById('series-detail-content').innerHTML = `
        ${trendHtml}
        ${hasChart ? `<div style="position:relative;height:210px;margin-bottom:20px;"><canvas id="exercise-detail-chart"></canvas></div>` : ''}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          ${buildCol(curDates,  label1, true)}
          ${buildCol(prevDates, label2, false)}
        </div>`;

      // ── 7. Create dual-axis line chart ─────────────────────────────────────
      if (exerciseDetailChart) { exerciseDetailChart.destroy(); exerciseDetailChart = null; }
      if (hasChart) {
        const ctx = document.getElementById('exercise-detail-chart').getContext('2d');
        const ptR = datePoints.length > 25 ? 2 : 4;
        exerciseDetailChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: datePoints.map(p => p.date),
            datasets: [
              {
                label: 'Poids max (kg)',
                data: datePoints.map(p => p.maxLoad),
                borderColor: lineColor,
                backgroundColor: fillColor,
                fill: true,
                tension: 0.35,
                yAxisID: 'y_load',
                pointRadius: ptR,
                pointHoverRadius: 6,
                borderWidth: 2.5,
              },
              {
                label: 'Reps moy.',
                data: datePoints.map(p => p.avgReps),
                borderColor: '#f59e0b',
                backgroundColor: 'transparent',
                borderDash: [5, 3],
                tension: 0.35,
                yAxisID: 'y_reps',
                pointRadius: ptR,
                pointHoverRadius: 6,
                borderWidth: 2,
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 14 } },
              tooltip: {
                callbacks: {
                  label: c => c.dataset.yAxisID === 'y_load'
                    ? ` ${c.parsed.y?.toFixed(1)} kg`
                    : ` ${c.parsed.y?.toFixed(1)} reps`
                }
              }
            },
            scales: {
              y_load: { type:'linear', position:'left',  title:{ display:true, text:'Poids (kg)' }, grid:{ color:'rgba(0,0,0,0.05)' } },
              y_reps: { type:'linear', position:'right', title:{ display:true, text:'Reps' },       grid:{ drawOnChartArea:false } }
            }
          }
        });
      }
    }, 50);
  });

  // Tab switching
  document.querySelectorAll('.stats-tab').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.stats-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.stats-tab-pane').forEach(p => p.classList.remove('active'));
      this.classList.add('active');
      const pane = document.getElementById('tab-' + this.dataset.tab);
      if (pane) pane.classList.add('active');
      // Lazy-render advanced charts when tab becomes visible (data may already be loaded)
      if (this.dataset.tab === 'analyse') {
        renderAdvancedCharts();
      }
    });
  });

});