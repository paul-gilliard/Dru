document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
  const exSelect = document.getElementById('stats-exercise-select');
  const clearEx = document.getElementById('clear-exercise');
  const performanceLoader = document.getElementById('performance-loader');
  const toggleKcals = document.getElementById('toggle-kcals');
  const toggleWater = document.getElementById('toggle-water');
  const toggleSleep = document.getElementById('toggle-sleep');
  const datePreset = document.getElementById('date-preset');
  const dateStart = document.getElementById('date-start');
  const dateEnd = document.getElementById('date-end');
  const applyDateFilter = document.getElementById('apply-date-filter');
  const journalViewMode = document.getElementById('journal-view-mode');
  const journalPrevButton = document.getElementById('journal-prev-period');
  const journalNextButton = document.getElementById('journal-next-period');

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
  let dateRange = { start: null, end: null }; // Date filter state
  let journalData = []; // All journal data loaded
  let journalViewMode_value = 'week'; // 'week' or 'month'
  let journalCurrentDate = new Date(); // Current date for navigation

  // Filter data by date range
  function filterByDateRange(data) {
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

  // Filter data by date range
  function filterByDateRange(data) {
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

  // Get date range for journal view
  function getJournalDateRange() {
    const current = journalCurrentDate;
    let start, end;
    
    if (journalViewMode_value === 'week') {
      const d = new Date(current);
      const day = d.getDay();
      const diff = d.getDate() - day + (day === 0 ? -6 : 1);
      start = new Date(d.setDate(diff));
      end = new Date(start);
      end.setDate(end.getDate() + 6);
    } else {
      start = new Date(current.getFullYear(), current.getMonth(), 1);
      end = new Date(current.getFullYear(), current.getMonth() + 1, 0);
    }
    
    return {
      start: start.toISOString().split('T')[0],
      end: end.toISOString().split('T')[0]
    };
  }

  // Update journal display
  function updateJournalDisplay() {
    console.log('updateJournalDisplay called, journalData length:', journalData.length);
    
    if (!journalData || journalData.length === 0) {
      console.log('No journal data');
      document.getElementById('journal-avg-weight').textContent = '—';
      document.getElementById('journal-avg-kcals').textContent = '—';
      document.getElementById('journal-avg-water').textContent = '—';
      document.getElementById('journal-avg-sleep').textContent = '—';
      
      journalChart.data.labels = [];
      journalChart.data.datasets = [{ label: 'Poids (kg)', data: [], borderColor:'#0b63d6', yAxisID:'y', fill:false, borderWidth:2 }];
      journalChart.update();
      
      document.getElementById('journal-table-body').innerHTML = '<tr><td colspan="5" style="padding:20px; text-align:center; color:#94a3b8;">Aucune donnée pour cette période</td></tr>';
      return;
    }

    const range = getJournalDateRange();
    const viewData = journalData.filter(e => e.date >= range.start && e.date <= range.end);

    console.log('Displaying', viewData.length, 'entries from', range.start, 'to', range.end);

    // Calculate stats
    let weightSum = 0, weightCount = 0;
    let kcalsSum = 0, kcalsCount = 0;
    let waterSum = 0, waterCount = 0;
    let sleepSum = 0, sleepCount = 0;

    viewData.forEach(entry => {
      if (entry.weight !== null && entry.weight !== undefined) {
        weightSum += Number(entry.weight);
        weightCount++;
      }
      if (entry.kcals !== null && entry.kcals !== undefined) {
        kcalsSum += Number(entry.kcals);
        kcalsCount++;
      }
      if (entry.water_ml !== null && entry.water_ml !== undefined) {
        waterSum += Number(entry.water_ml);
        waterCount++;
      }
      if (entry.sleep_hours !== null && entry.sleep_hours !== undefined) {
        sleepSum += Number(entry.sleep_hours);
        sleepCount++;
      }
    });

    // Update stat cards
    document.getElementById('journal-avg-weight').textContent = weightCount > 0 ? (weightSum/weightCount).toFixed(1) + ' kg' : '—';
    document.getElementById('journal-avg-kcals').textContent = kcalsCount > 0 ? Math.round(kcalsSum/kcalsCount) : '—';
    document.getElementById('journal-avg-water').textContent = waterCount > 0 ? Math.round(waterSum/waterCount) + ' ml' : '—';
    document.getElementById('journal-avg-sleep').textContent = sleepCount > 0 ? (sleepSum/sleepCount).toFixed(1) + ' h' : '—';

    // Update chart
    const labels = viewData.map(d => d.date);
    const weights = viewData.map(d => d.weight !== null && d.weight !== undefined ? Number(d.weight) : null);
    const kcalsData = viewData.map(d => d.kcals !== null && d.kcals !== undefined ? Number(d.kcals) : null);
    const waterData = viewData.map(d => d.water_ml !== null && d.water_ml !== undefined ? Number(d.water_ml) : null);
    const sleepData = viewData.map(d => d.sleep_hours !== null && d.sleep_hours !== undefined ? Number(d.sleep_hours) : null);

    journalChart.data.labels = labels;
    journalChart.data.datasets = [
      { label: 'Poids (kg)', data: weights, borderColor:'#0b63d6', yAxisID:'y', fill:false, borderWidth:2, tension:0.3 }
    ];

    if (toggleKcals.checked) {
      journalChart.data.datasets.push({ label:'Kcals', data: kcalsData, borderColor:'#ef4444', yAxisID:'y_kcals', fill:false, borderWidth:2, tension:0.3 });
      journalChart.options.scales.y_kcals = { display:true, position:'right' };
    } else {
      journalChart.options.scales.y_kcals = { display:false };
    }

    if (toggleWater.checked) {
      journalChart.data.datasets.push({ label:'Eau (ml)', data: waterData, borderColor:'#06b6d4', yAxisID:'y', fill:false, borderWidth:2, tension:0.3 });
    }

    if (toggleSleep.checked) {
      journalChart.data.datasets.push({ label:'Sommeil (h)', data: sleepData, borderColor:'#8b5cf6', yAxisID:'y', fill:false, borderWidth:2, tension:0.3 });
    }

    journalChart.update();

    // Update table
    const tableBody = document.getElementById('journal-table-body');
    tableBody.innerHTML = '';
    viewData.forEach((entry, idx) => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #e5e7eb';
      tr.style.background = idx % 2 === 0 ? '#ffffff' : '#f8fafc';
      const w = entry.weight !== null && entry.weight !== undefined ? Number(entry.weight).toFixed(1) : '—';
      const k = entry.kcals !== null && entry.kcals !== undefined ? Math.round(Number(entry.kcals)) : '—';
      const wa = entry.water_ml !== null && entry.water_ml !== undefined ? Math.round(Number(entry.water_ml)) : '—';
      const s = entry.sleep_hours !== null && entry.sleep_hours !== undefined ? Number(entry.sleep_hours).toFixed(1) : '—';
      tr.innerHTML = `<td style="padding:10px;">${entry.date}</td><td style="padding:10px; text-align:center;">${w}</td><td style="padding:10px; text-align:center;">${k}</td><td style="padding:10px; text-align:center;">${wa}</td><td style="padding:10px; text-align:center;">${s}</td>`;
      tableBody.appendChild(tr);
    });
  }
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
    console.log('loadJournal called for athlete', athleteId);
    const res = await fetch(`/coach/stats/athlete/${athleteId}/journal.json`);
    if (!res.ok) {
      console.error('Journal fetch failed:', res.status);
      return;
    }
    journalData = await res.json();
    console.log('Journal data loaded:', journalData.length, 'entries');
    journalCurrentDate = new Date();
    updateJournalDisplay();
  }

  let perfCache = null;
  let muscleDetailCache = {
    '7days': {},
    '14days': {},
    '21days': {},
    '28days': {}
  }; // Cache for muscle details - preloaded on athlete selection
  
  let seriesCache = {}; // Cache for exercise series data - preloaded
  let currentComparisonContext = {}; // Store current comparison context for series display
  
  // Global cache for summary data by athlete
  let summaryCache = {
    '7days': {}, // athleteId -> data
    '14days': {},
    '28days': {}
  };

  // Muscle details are now preloaded via loadQuickData() - no separate function needed
  async function loadPerformance(athleteId){
    if (performanceLoader) performanceLoader.classList.add('show');
    try {
      const res = await fetch(`/coach/stats/athlete/${athleteId}/performance.json`);
      if (!res.ok) return;
      let data = await res.json();
      
      // Filter performance data by date range
      if (dateRange.start || dateRange.end) {
        const filteredData = {};
        Object.keys(data).forEach(ex => {
          filteredData[ex] = filterByDateRange(data[ex]);
        });
        data = filteredData;
      }
      
      perfCache = data;
      // Populate exercise select with all exercises
      exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
      if (data) {
        Object.keys(data).sort().forEach(ex => {
          const opt = document.createElement('option');
          opt.value = ex;
          opt.textContent = ex;
          exSelect.appendChild(opt);
        });
      }
      
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
      const endTime = performance.now();
      console.log(`Quick-data loaded in ${(endTime - startTime).toFixed(2)}ms`);
      
      // Process journal data
      if (data.journal) {
        console.log(`Processing ${data.journal.length} journal entries...`);
        const labels = data.journal.map(d=>d.date);
        const weight = data.journal.map(d=> d.weight === null ? null : Number(d.weight));
        const kcals = data.journal.map(d=> d.kcals === null ? null : Number(d.kcals));
        const water = data.journal.map(d=> d.water_ml === null ? null : Number(d.water_ml));
        const sleep = data.journal.map(d=> d.sleep_hours === null ? null : Number(d.sleep_hours));

        journalChart.data.labels = labels;
        journalChart.data.datasets = [
          { label: 'Poids (kg)', data: weight, borderColor:'#0b63d6', tension:0.2, yAxisID:'y' }
        ];
        if (toggleKcals.checked) {
          journalChart.data.datasets.push({ label:'Kcals', data: kcals, borderColor:'#ef4444', tension:0.2, yAxisID:'y_kcals' });
          journalChart.options.scales.y_kcals = { display:true, position:'right' };
        } else {
          journalChart.options.scales.y_kcals = { display:false };
        }
        if (toggleWater.checked) {
          journalChart.data.datasets.push({ label:'Eau (ml)', data: water, borderColor:'#06b6d4', tension:0.2, yAxisID:'y' });
        }
        if (toggleSleep.checked) {
          journalChart.data.datasets.push({ label:'Sommeil (h)', data: sleep, borderColor:'#10b981', tension:0.2, yAxisID:'y' });
        }
        journalChart.update();
      }
      
      // Cache the summary data and exercise details
      if (data.summary_7days) {
        summaryCache['7days'][athleteId] = data.summary_7days;
        if (data.summary_7days.exercise_details_by_muscle) {
          muscleDetailCache['7days'] = data.summary_7days.exercise_details_by_muscle;
        }
        await displayComparison(1, data.summary_7days);
      }
      if (data.summary_14days) {
        summaryCache['14days'][athleteId] = data.summary_14days;
        if (data.summary_14days.exercise_details_by_muscle) {
          muscleDetailCache['14days'] = data.summary_14days.exercise_details_by_muscle;
        }
        await displayComparison(2, data.summary_14days);
      }
      if (data.summary_21days) {
        summaryCache['21days'] = data.summary_21days;
        if (data.summary_21days.exercise_details_by_muscle) {
          muscleDetailCache['21days'] = data.summary_21days.exercise_details_by_muscle;
        }
        await displayComparison(3, data.summary_21days);
      }
      if (data.summary_28days) {
        summaryCache['28days'][athleteId] = data.summary_28days;
        if (data.summary_28days.exercise_details_by_muscle) {
          muscleDetailCache['28days'] = data.summary_28days.exercise_details_by_muscle;
        }
        await displayComparison(4, data.summary_28days);
      }
      
      // Cache series data (preloaded)
      if (data.series_by_exercise) {
        seriesCache = data.series_by_exercise;
        console.log(`Preloaded ${Object.keys(seriesCache).length} exercises with series data`);
      }
      
    } catch (err) {
      console.error('Error loading quick-data:', err);
    }
  }

  // Generic display function for all 4 comparisons
  async function displayComparison(tableNum, data) {
    if (!data) return;
    
    const getArrow = (diff) => {
      if (diff === null || diff === undefined) return '—';
      if (Math.abs(diff) < 0.1) return '→';
      return diff > 0 ? '📈' : '📉';
    };
    
    const formatValue = (val, decimals = 1) => {
      if (val === null || val === undefined) return '—';
      return Number(val).toFixed(decimals);
    };
    
    const formatDiff = (val, decimals = 1) => {
      if (val === null || val === undefined) return '—';
      const num = Number(val).toFixed(decimals);
      const sign = parseFloat(num) > 0 ? '+' : '';
      return sign + num;
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
    const poidsArrow = getArrow(data.weight_diff);
    const poidsCurrent = formatValue(data.weight_current, 2);
    const poidsPrevious = formatValue(data.weight_previous, 2);
    const poidsDiff = formatDiff(data.weight_diff, 2);
    poidsTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Poids (kg)</td>
      <td style="padding:8px; text-align:center;">${poidsCurrent}</td>
      <td style="padding:8px; text-align:center;">${poidsPrevious}</td>
      <td style="padding:8px; text-align:center;">${poidsDiff} ${poidsArrow}</td>
    `;
    tbody.appendChild(poidsTr);
    
    // Kcals
    let kcalsTr = document.createElement('tr');
    kcalsTr.style.borderBottom = '1px solid #e5e7eb';
    const kcalsArrow = getArrow(data.kcals_diff);
    const kcalsCurrent = formatValue(data.kcals_current, 0);
    const kcalsPrevious = formatValue(data.kcals_previous, 0);
    const kcalsDiff = formatDiff(data.kcals_diff, 0);
    kcalsTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Kcals</td>
      <td style="padding:8px; text-align:center;">${kcalsCurrent}</td>
      <td style="padding:8px; text-align:center;">${kcalsPrevious}</td>
      <td style="padding:8px; text-align:center;">${kcalsDiff} ${kcalsArrow}</td>
    `;
    tbody.appendChild(kcalsTr);
    
    // Eau
    let eauTr = document.createElement('tr');
    eauTr.style.borderBottom = '1px solid #e5e7eb';
    const eauArrow = getArrow(data.water_diff);
    const eauCurrent = formatValue(data.water_current, 0);
    const eauPrevious = formatValue(data.water_previous, 0);
    const eauDiff = formatDiff(data.water_diff, 0);
    eauTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Eau (ml)</td>
      <td style="padding:8px; text-align:center;">${eauCurrent}</td>
      <td style="padding:8px; text-align:center;">${eauPrevious}</td>
      <td style="padding:8px; text-align:center;">${eauDiff} ${eauArrow}</td>
    `;
    tbody.appendChild(eauTr);
    
    // Sommeil
    let sommeilTr = document.createElement('tr');
    sommeilTr.style.borderBottom = '1px solid #e5e7eb';
    const sommeilArrow = getArrow(data.sleep_diff);
    const sommeilCurrent = formatValue(data.sleep_current, 1);
    const sommeilPrevious = formatValue(data.sleep_previous, 1);
    const sommeilDiff = formatDiff(data.sleep_diff, 1);
    sommeilTr.innerHTML = `
      <td style="padding:8px; font-weight:600;">Sommeil (h)</td>
      <td style="padding:8px; text-align:center;">${sommeilCurrent}</td>
      <td style="padding:8px; text-align:center;">${sommeilPrevious}</td>
      <td style="padding:8px; text-align:center;">${sommeilDiff} ${sommeilArrow}</td>
    `;
    tbody.appendChild(sommeilTr);
    
    // Tonnage par muscle with detail buttons
    if (data.tonnage_diff_by_muscle) {
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        const arrow = getArrow(diff);
        const diffStr = formatDiff(diff, 0);
        
        // Map tableNum to period name for muscle detail cache
        let period = '7days';
        if (tableNum === 2) period = '14days';
        if (tableNum === 3) period = '21days';
        if (tableNum === 4) period = '28days';
        
        tr.innerHTML = `
          <td style="padding:8px; font-weight:600;">${muscle}</td>
          <td style="padding:8px; text-align:center; text-decoration:underline; cursor:pointer;" class="show-muscle-detail" data-muscle="${muscle}" data-summary="${period}" data-label1="${data.label1}" data-label2="${data.label2}">Détails</td>
          <td style="padding:8px; text-align:center;"></td>
          <td style="padding:8px; text-align:center;">${diffStr} ${arrow}</td>
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
      
      // Get arrow function based on change
      const getArrow = (diff) => {
        if (diff === null || diff === undefined) return '—';
        if (Math.abs(diff) < 0.1) return '→';
        return diff > 0 ? '📈' : '📉';
      };
      
      const formatDiff = (val, decimals = 1) => {
        if (val === null || val === undefined) return '—';
        const num = Number(val).toFixed(decimals);
        const sign = parseFloat(num) > 0 ? '+' : '';
        return sign + num;
      };
      
      // Update summary values with differences
      const weightArrow = getArrow(data.weight_diff);
      const weightValue = data.weight_diff !== null ? 
        `${formatDiff(data.weight_diff, 2)} kg ${weightArrow}` : '—';
      document.getElementById('summary-weight').textContent = weightValue;
      
      const kcalsArrow = getArrow(data.kcals_diff);
      const kcalsValue = data.kcals_diff !== null ? 
        `${formatDiff(data.kcals_diff, 0)} cal ${kcalsArrow}` : '—';
      document.getElementById('summary-kcals').textContent = kcalsValue;
      
      const waterArrow = getArrow(data.water_diff);
      const waterValue = data.water_diff !== null ? 
        `${formatDiff(data.water_diff, 0)} ml ${waterArrow}` : '—';
      document.getElementById('summary-water').textContent = waterValue;
      
      const sleepArrow = getArrow(data.sleep_diff);
      const sleepValue = data.sleep_diff !== null ? 
        `${formatDiff(data.sleep_diff, 1)} h ${sleepArrow}` : '—';
      document.getElementById('summary-sleep').textContent = sleepValue;
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-tonnage-body');
      tonnageBody.innerHTML = '';
      
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        const arrow = getArrow(diff);
        const diffStr = formatDiff(diff, 0);
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffStr} ${arrow}</td>
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
      
      // Get arrow function based on change
      const getArrow = (diff) => {
        if (diff === null || diff === undefined) return '—';
        if (Math.abs(diff) < 0.1) return '→';
        return diff > 0 ? '📈' : '📉';
      };
      
      const formatDiff = (val, decimals = 1) => {
        if (val === null || val === undefined) return '—';
        const num = Number(val).toFixed(decimals);
        const sign = parseFloat(num) > 0 ? '+' : '';
        return sign + num;
      };
      
      // Update summary values with differences
      const weightArrow = getArrow(data.weight_diff);
      const weightValue = data.weight_diff !== null ? 
        `${formatDiff(data.weight_diff, 2)} kg ${weightArrow}` : '—';
      document.getElementById('summary-14days-weight').textContent = weightValue;
      
      const kcalsArrow = getArrow(data.kcals_diff);
      const kcalsValue = data.kcals_diff !== null ? 
        `${formatDiff(data.kcals_diff, 0)} cal ${kcalsArrow}` : '—';
      document.getElementById('summary-14days-kcals').textContent = kcalsValue;
      
      const waterArrow = getArrow(data.water_diff);
      const waterValue = data.water_diff !== null ? 
        `${formatDiff(data.water_diff, 0)} ml ${waterArrow}` : '—';
      document.getElementById('summary-14days-water').textContent = waterValue;
      
      const sleepArrow = getArrow(data.sleep_diff);
      const sleepValue = data.sleep_diff !== null ? 
        `${formatDiff(data.sleep_diff, 1)} h ${sleepArrow}` : '—';
      document.getElementById('summary-14days-sleep').textContent = sleepValue;
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-14days-tonnage-body');
      tonnageBody.innerHTML = '';
      
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        const arrow = getArrow(diff);
        const diffStr = formatDiff(diff, 0);
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffStr} ${arrow}</td>
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
      
      // Get arrow function based on change
      const getArrow = (diff) => {
        if (diff === null || diff === undefined) return '—';
        if (Math.abs(diff) < 0.1) return '→';
        return diff > 0 ? '📈' : '📉';
      };
      
      const formatDiff = (val, decimals = 1) => {
        if (val === null || val === undefined) return '—';
        const num = Number(val).toFixed(decimals);
        const sign = parseFloat(num) > 0 ? '+' : '';
        return sign + num;
      };
      
      // Update summary values with differences
      const weightArrow = getArrow(data.weight_diff);
      const weightValue = data.weight_diff !== null ? 
        `${formatDiff(data.weight_diff, 2)} kg ${weightArrow}` : '—';
      document.getElementById('summary-28days-weight').textContent = weightValue;
      
      const kcalsArrow = getArrow(data.kcals_diff);
      const kcalsValue = data.kcals_diff !== null ? 
        `${formatDiff(data.kcals_diff, 0)} cal ${kcalsArrow}` : '—';
      document.getElementById('summary-28days-kcals').textContent = kcalsValue;
      
      const waterArrow = getArrow(data.water_diff);
      const waterValue = data.water_diff !== null ? 
        `${formatDiff(data.water_diff, 0)} ml ${waterArrow}` : '—';
      document.getElementById('summary-28days-water').textContent = waterValue;
      
      const sleepArrow = getArrow(data.sleep_diff);
      const sleepValue = data.sleep_diff !== null ? 
        `${formatDiff(data.sleep_diff, 1)} h ${sleepArrow}` : '—';
      document.getElementById('summary-28days-sleep').textContent = sleepValue;
      
      // Fill tonnage rows with detail buttons
      const tonnageBody = document.getElementById('summary-28days-tonnage-body');
      tonnageBody.innerHTML = '';
      Object.keys(data.tonnage_diff_by_muscle).sort().forEach(muscle => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #e5e7eb';
        const diff = data.tonnage_diff_by_muscle[muscle];
        const arrow = getArrow(diff);
        const diffStr = formatDiff(diff, 0);
        tr.innerHTML = `
          <td style="padding:12px; font-weight:600;">${muscle}</td>
          <td style="padding:12px; text-align:center;">${diffStr} ${arrow}</td>
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
    if (!perfCache || !perfCache[ex]) return;
    
    const mainSeriesContainer = document.getElementById('main-series-container');
    const otherSeriesContainer = document.getElementById('other-series-container');
    const perfChartContainer = document.getElementById('perf-chart-container');
    const mainTableBody = document.getElementById('main-series-table').querySelector('tbody');
    const otherTableBody = document.getElementById('other-series-table').querySelector('tbody');
    
    mainTableBody.innerHTML = '';
    otherTableBody.innerHTML = '';
    
    const data = perfCache[ex];
    
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

  athleteSelect.addEventListener('change', async function(){
    const athleteId = this.value;
    if (!athleteId) {
      // Hide loaders when no athlete selected
      for (let i = 1; i <= 4; i++) {
        const loader = document.getElementById(`comparison-${i}-loader`);
        if (loader) loader.classList.remove('show');
      }
      return;
    }
    
    // Show loaders when athlete is selected
    for (let i = 1; i <= 4; i++) {
      const loader = document.getElementById(`comparison-${i}-loader`);
      if (loader) loader.classList.add('show');
    }
    
    // Clear performance data
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
    document.getElementById('perf-chart-container').style.display = 'none';
    document.getElementById('other-series-chart-container').style.display = 'none';
    
    // Load journal data
    console.log(`Loading journal for athlete ${athleteId}...`);
    await loadJournal(athleteId);
    
    // Load quick-data FIRST (all summaries + exercise details in one call) - BLOCKING
    console.log(`Loading quick-data for athlete ${athleteId}...`);
    await loadQuickData(athleteId);
    
    // Load performance in background (NON-BLOCKING)
    console.log('Starting background load of performance...');
    loadPerformance(athleteId).then(() => console.log('Performance loaded'));
  });
  exSelect.addEventListener('change', function(){
    const ex = this.value;
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

  [toggleKcals, toggleWater, toggleSleep].forEach(el=>{
    el.addEventListener('change', function(){
      updateJournalDisplay();
    });
  });

  // Journal navigation
  journalViewMode.addEventListener('change', function() {
    journalViewMode_value = this.value;
    journalCurrentDate = new Date();
    updateJournalDisplay();
  });

  journalPrevButton.addEventListener('click', function() {
    if (journalViewMode_value === 'week') {
      journalCurrentDate.setDate(journalCurrentDate.getDate() - 7);
    } else {
      journalCurrentDate.setMonth(journalCurrentDate.getMonth() - 1);
    }
    updateJournalDisplay();
  });

  journalNextButton.addEventListener('click', function() {
    if (journalViewMode_value === 'week') {
      journalCurrentDate.setDate(journalCurrentDate.getDate() + 7);
    } else {
      journalCurrentDate.setMonth(journalCurrentDate.getMonth() + 1);
    }
    updateJournalDisplay();
  });

  // Event delegation for muscle detail buttons - data is preloaded in cache
  document.addEventListener('click', function(e) {
    if (e.target.matches('.show-muscle-detail')) {
      const muscle = e.target.getAttribute('data-muscle');
      const summary = e.target.getAttribute('data-summary');
      const label1 = e.target.getAttribute('data-label1');
      const label2 = e.target.getAttribute('data-label2');
      
      // Store context for series display
      currentComparisonContext = {
        summary: summary,
        label1: label1,
        label2: label2
      };
      
      // Show modal with spinner
      document.getElementById('muscle-detail-modal').style.display = 'flex';
      document.getElementById('muscle-detail-title').textContent = `Détail par exercice - ${muscle}`;
      document.getElementById('muscle-detail-content').innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; gap:12px;">
          <div class="spinner"></div>
          <span style="color:#94a3b8; font-size:0.9rem;">Chargement des détails...</span>
        </div>
      `;
      
      // Get data from cache (preloaded on athlete selection)
      if (!muscleDetailCache[summary] || !muscleDetailCache[summary][muscle]) {
        document.getElementById('muscle-detail-content').innerHTML = '<p style="color:#ef4444;">Données non disponibles</p>';
        return;
      }

      const exercisesByMuscle = muscleDetailCache[summary][muscle];
      
      // Simulate small delay for UX feedback
      setTimeout(() => {
        // Build detail HTML
        let html = `<h4 style="margin-top:0;">${muscle}</h4>`;
        html += '<table style="width:100%; border-collapse:collapse; margin-top:12px;">';
        html += `<tr style="background:#f3f4f6; border-bottom:2px solid #d1d5db;">
          <th style="padding:8px; text-align:left; font-weight:600;">Exercice</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:100px;">Période courante</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:100px;">Période précédente</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:80px;">Évolution</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:80px;">Détail</th>
        </tr>`;
        
        // exercisesByMuscle is { exercise_name: { current, previous, diff } }
        Object.keys(exercisesByMuscle || {}).sort().forEach(exercise => {
          const exerciseData = exercisesByMuscle[exercise] || {};
          const current = exerciseData.current || 0;
          const previous = exerciseData.previous || 0;
          const diff = exerciseData.diff || 0;
          const arrow = diff > 0 ? '📈' : (diff < 0 ? '📉' : '→');
          const diffStr = diff >= 0 ? `+${diff.toFixed(0)}` : `${diff.toFixed(0)}`;
          
          html += `<tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px;">${exercise}</td>
            <td style="padding:8px; text-align:center;">${current.toFixed(0)}</td>
            <td style="padding:8px; text-align:center;">${previous.toFixed(0)}</td>
            <td style="padding:8px; text-align:center;">${diffStr} ${arrow}</td>
            <td style="padding:8px; text-align:center;">
              <button class="show-exercise-series secondary" data-exercise="${exercise}" style="font-size:0.75rem; padding:4px 8px; cursor:pointer;">Détail</button>
            </td>
          </tr>`;
        });
        
        html += '</table>';
        
        document.getElementById('muscle-detail-content').innerHTML = html;
      }, 200); // Small delay for visual feedback
    }
  });

  // Event delegation for exercise series detail buttons
  document.addEventListener('click', function(e) {
    if (e.target.matches('.show-exercise-series')) {
      const exercise = e.target.getAttribute('data-exercise');
      
      // Show modal with spinner
      document.getElementById('series-detail-modal').style.display = 'flex';
      document.getElementById('series-detail-title').textContent = `Détail des séries - ${exercise}`;
      document.getElementById('series-detail-content').innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; gap:12px;">
          <div class="spinner"></div>
          <span style="color:#94a3b8; font-size:0.9rem;">Chargement des séries...</span>
        </div>
      `;
      
      // Use preloaded series data
      setTimeout(() => {
        const data = seriesCache[exercise];
        
        if (!data || Object.keys(data).length === 0) {
          let html = `<h4 style="margin-top:0;">${exercise}</h4>`;
          html += '<p style="color:#94a3b8;">Aucune série enregistrée</p>';
          document.getElementById('series-detail-content').innerHTML = html;
          return;
        }
        
        let html = `<h4 style="margin-top:0;">${exercise}</h4>`;
        
        // Get comparison context
        const summary = currentComparisonContext.summary || '7days';
        const label1 = currentComparisonContext.label1 || 'Semaine courante';
        const label2 = currentComparisonContext.label2 || 'Semaine précédente';
        
        // Map summary to week boundaries
        const today = new Date();
        let currentWeekStart, currentWeekEnd, prevWeekStart, prevWeekEnd;
        
        if (summary === '7days') {
          // S vs S-1
          currentWeekStart = new Date(today);
          currentWeekStart.setDate(today.getDate() - today.getDay());
          currentWeekEnd = new Date(currentWeekStart);
          currentWeekEnd.setDate(currentWeekStart.getDate() + 6);
          
          prevWeekStart = new Date(currentWeekStart);
          prevWeekStart.setDate(currentWeekStart.getDate() - 7);
          prevWeekEnd = new Date(prevWeekStart);
          prevWeekEnd.setDate(prevWeekStart.getDate() + 6);
        } else if (summary === '14days') {
          // S vs S-2
          const currentWeekStart_temp = new Date(today);
          currentWeekStart_temp.setDate(today.getDate() - today.getDay());
          currentWeekStart = currentWeekStart_temp;
          currentWeekEnd = new Date(currentWeekStart);
          currentWeekEnd.setDate(currentWeekStart.getDate() + 6);
          
          prevWeekStart = new Date(currentWeekStart);
          prevWeekStart.setDate(currentWeekStart.getDate() - 14);
          prevWeekEnd = new Date(prevWeekStart);
          prevWeekEnd.setDate(prevWeekStart.getDate() + 6);
        } else if (summary === '21days') {
          // S-1 vs S-2
          const currentWeekStart_temp = new Date(today);
          currentWeekStart_temp.setDate(today.getDate() - today.getDay());
          currentWeekStart = new Date(currentWeekStart_temp);
          currentWeekStart.setDate(currentWeekStart_temp.getDate() - 7);
          currentWeekEnd = new Date(currentWeekStart);
          currentWeekEnd.setDate(currentWeekStart.getDate() + 6);
          
          prevWeekStart = new Date(currentWeekStart);
          prevWeekStart.setDate(currentWeekStart.getDate() - 7);
          prevWeekEnd = new Date(prevWeekStart);
          prevWeekEnd.setDate(prevWeekStart.getDate() + 6);
        } else if (summary === '28days') {
          // S-1 vs S-3
          const currentWeekStart_temp = new Date(today);
          currentWeekStart_temp.setDate(today.getDate() - today.getDay());
          currentWeekStart = new Date(currentWeekStart_temp);
          currentWeekStart.setDate(currentWeekStart_temp.getDate() - 7);
          currentWeekEnd = new Date(currentWeekStart);
          currentWeekEnd.setDate(currentWeekStart.getDate() + 6);
          
          prevWeekStart = new Date(currentWeekStart);
          prevWeekStart.setDate(currentWeekStart.getDate() - 14);
          prevWeekEnd = new Date(prevWeekStart);
          prevWeekEnd.setDate(prevWeekStart.getDate() + 6);
        }
        
        // Function to check if date is in week range
        const isInWeek = (dateStr, weekStart, weekEnd) => {
          const d = new Date(dateStr);
          return d >= weekStart && d <= weekEnd;
        };
        
        // Sort dates
        const sortedDates = Object.keys(data).sort().reverse();
        
        // Separate dates by week
        const currentWeekDates = sortedDates.filter(d => isInWeek(d, currentWeekStart, currentWeekEnd));
        const prevWeekDates = sortedDates.filter(d => isInWeek(d, prevWeekStart, prevWeekEnd));
        const otherDates = sortedDates.filter(d => !isInWeek(d, currentWeekStart, currentWeekEnd) && !isInWeek(d, prevWeekStart, prevWeekEnd));
        
        // Helper to build table for a set of dates
        const buildWeekTable = (dates, weekLabel) => {
          if (dates.length === 0) {
            return `<div style="color:#94a3b8; text-align:center; padding:12px;">Aucune donnée</div>`;
          }
          
          let table = `<div style="margin-bottom:12px;">`;
          table += `<h5 style="margin:0 0 8px 0; color:#0b63d6; font-size:0.9rem;">${weekLabel}</h5>`;
          
          dates.forEach(date => {
            const series = data[date];
            table += `<div style="margin-bottom:8px; border:1px solid #d1d5db; border-radius:4px; padding:8px; background:#fff;">`;
            table += `<div style="font-weight:600; font-size:0.85rem; color:#333; margin-bottom:6px;">${date}</div>`;
            table += '<table style="width:100%; border-collapse:collapse; font-size:0.8rem;">';
            table += `<tr style="background:#f9fafb; border-bottom:1px solid #e5e7eb;">
              <th style="padding:4px; text-align:center; font-weight:600;">S</th>
              <th style="padding:4px; text-align:center; font-weight:600;">Reps</th>
              <th style="padding:4px; text-align:center; font-weight:600;">Poids</th>
              <th style="padding:4px; text-align:center; font-weight:600;">RPE</th>
            </tr>`;
            
            // Sort series by series_number
            series.sort((a, b) => (a.series_number || 0) - (b.series_number || 0));
            
            series.forEach(s => {
              const seriesNum = s.series_number || '—';
              const reps = s.reps !== null && s.reps !== undefined ? s.reps.toFixed(1) : '—';
              const load = s.load !== null && s.load !== undefined ? s.load.toFixed(1) : '—';
              const rpe = s.rpe !== null && s.rpe !== undefined ? s.rpe : '—';
              
              table += `<tr style="border-bottom:1px solid #e5e7eb;">
                <td style="padding:4px; text-align:center;">${seriesNum}</td>
                <td style="padding:4px; text-align:center;">${reps}</td>
                <td style="padding:4px; text-align:center;">${load}</td>
                <td style="padding:4px; text-align:center;">${rpe}</td>
              </tr>`;
            });
            
            table += '</table>';
            table += '</div>';
          });
          
          table += '</div>';
          return table;
        };
        
        // Build 2-column layout for current and previous week with actual labels
        html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px;">';
        html += `<div style="border:1px solid #e5e7eb; border-radius:6px; padding:12px; background:#f9fafb;">`;
        html += buildWeekTable(currentWeekDates, label1);
        html += '</div>';
        html += `<div style="border:1px solid #e5e7eb; border-radius:6px; padding:12px; background:#f9fafb;">`;
        html += buildWeekTable(prevWeekDates, label2);
        html += '</div>';
        html += '</div>';
        
        // Add other dates below if any
        if (otherDates.length > 0) {
          html += '<div style="margin-top:12px; border-top:2px solid #e5e7eb; padding-top:12px;">';
          html += '<h5 style="margin:0 0 8px 0; color:#64748b; font-size:0.9rem;">Autres dates</h5>';
          html += buildWeekTable(otherDates, '');
          html += '</div>';
        }
        
        document.getElementById('series-detail-content').innerHTML = html;
      }, 100);
    }
  });
});