document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const programSelect = document.getElementById('stats-program-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
  const muscleSelect = document.getElementById('stats-muscle-select');
  const clearMuscle = document.getElementById('clear-muscle');
  const exSelect = document.getElementById('stats-exercise-select');
  const clearEx = document.getElementById('clear-exercise');
  const toggleKcals = document.getElementById('toggle-kcals');
  const toggleWater = document.getElementById('toggle-water');
  const toggleSleep = document.getElementById('toggle-sleep');
  const datePreset = document.getElementById('date-preset');
  const dateStart = document.getElementById('date-start');
  const dateEnd = document.getElementById('date-end');
  const applyDateFilter = document.getElementById('apply-date-filter');

  let journalChart = new Chart(chartJournalCtx, {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Poids (kg)', data: [], borderColor:'#0b63d6', yAxisID:'y'},
      // optional datasets pushed later
    ] },
    options: { interaction:{mode:'index',intersect:false}, scales:{ y:{type:'linear',position:'left'}, y_kcals:{display:false,position:'right'} } }
  });

  let performanceChart = null;
  let otherSeriesChart = null;
  let tonnageChart = null;
  let tonnageCache = null;
  let programExercises = {}; // Track exercises from selected program
  let selectedProgramId = null; // Track selected program
  let dateRange = { start: null, end: null }; // Date filter state

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

  // Set date preset
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
      loadTonnage(athleteId);
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
      loadTonnage(athleteId);
      loadSummary(athleteId);
    }
  });

  async function loadJournal(athleteId){
    const res = await fetch(`/coach/stats/athlete/${athleteId}/journal.json`);
    if (!res.ok) return;
    let data = await res.json();
    data = filterByDateRange(data); // Apply date filter
    const labels = data.map(d=>d.date);
    const weight = data.map(d=> d.weight === null ? null : Number(d.weight));
    const kcals = data.map(d=> d.kcals === null ? null : Number(d.kcals));
    const water = data.map(d=> d.water_ml === null ? null : Number(d.water_ml));
    const sleep = data.map(d=> d.sleep_hours === null ? null : Number(d.sleep_hours));

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
    
    // Fill journal table with selected metrics
    const journalTableBody = document.getElementById('journal-table-body');
    const journalTableHead = document.getElementById('journal-table-head');
    
    // Build headers dynamically based on toggles
    let headers = '<tr style="background: #f3f4f6; border-bottom: 2px solid #d1d5db;"><th style="padding:12px; text-align:left; font-weight:600;">Date</th><th style="padding:12px; text-align:center; font-weight:600;">Poids (kg)</th>';
    if (toggleKcals.checked) headers += '<th style="padding:12px; text-align:center; font-weight:600;">Kcals</th>';
    if (toggleWater.checked) headers += '<th style="padding:12px; text-align:center; font-weight:600;">Eau (ml)</th>';
    if (toggleSleep.checked) headers += '<th style="padding:12px; text-align:center; font-weight:600;">Sommeil (h)</th>';
    headers += '</tr>';
    journalTableHead.innerHTML = headers;
    
    // Build rows
    journalTableBody.innerHTML = '';
    data.forEach((entry, idx) => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #e5e7eb';
      let row = `<td style="padding:12px;">${entry.date}</td><td style="padding:12px; text-align:center;">${weight[idx] !== null ? weight[idx].toFixed(1) : '—'}</td>`;
      if (toggleKcals.checked) row += `<td style="padding:12px; text-align:center;">${kcals[idx] !== null ? Math.round(kcals[idx]) : '—'}</td>`;
      if (toggleWater.checked) row += `<td style="padding:12px; text-align:center;">${water[idx] !== null ? Math.round(water[idx]) : '—'}</td>`;
      if (toggleSleep.checked) row += `<td style="padding:12px; text-align:center;">${sleep[idx] !== null ? sleep[idx].toFixed(1) : '—'}</td>`;
      tr.innerHTML = row;
      journalTableBody.appendChild(tr);
    });
    
    document.getElementById('journal-table-container').style.display = 'block';
  }

  let perfCache = null;
  let muscleDetailCache = {
    '7days': {},
    '14days': {},
    '28days': {}
  }; // Cache for muscle details - preloaded on athlete selection
  
  // Global cache for summary data by athlete
  let summaryCache = {
    '7days': {}, // athleteId -> data
    '14days': {},
    '28days': {}
  };

  // Preload all muscle details for all periods when athlete is selected
  async function preloadAllMuscleDetails(athleteId) {
    try {
      // Load all details in parallel for faster loading
      const [data7, data14, data28] = await Promise.all([
        fetch(`/coach/stats/athlete/${athleteId}/summary-7days.json`).then(r => r.ok ? r.json() : null),
        fetch(`/coach/stats/athlete/${athleteId}/summary-14days.json`).then(r => r.ok ? r.json() : null),
        fetch(`/coach/stats/athlete/${athleteId}/summary-28days.json`).then(r => r.ok ? r.json() : null)
      ]);

      // Extract and cache muscle details from each response
      if (data7?.tonnage_by_exercise_and_muscle) {
        muscleDetailCache['7days'] = data7.tonnage_by_exercise_and_muscle;
      }
      if (data14?.tonnage_by_exercise_and_muscle) {
        muscleDetailCache['14days'] = data14.tonnage_by_exercise_and_muscle;
      }
      if (data28?.tonnage_by_exercise_and_muscle) {
        muscleDetailCache['28days'] = data28.tonnage_by_exercise_and_muscle;
      }
      
      console.log('Muscle details preloaded for all periods');
    } catch (err) {
      console.error('Error preloading muscle details:', err);
    }
  }
  async function loadPerformance(athleteId){
    // Use program-specific endpoint if program is selected
    const url = selectedProgramId 
      ? `/coach/stats/athlete/${athleteId}/program/${selectedProgramId}/performance.json`
      : `/coach/stats/athlete/${athleteId}/performance.json`;
    const res = await fetch(url);
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
    // populate exercise select with filter based on selected muscle group
    const selectedMuscle = muscleSelect.value;
    updateExercisesForMuscle(selectedMuscle);
    
    // clear tables
    document.getElementById('main-series-table').querySelector('tbody').innerHTML = '';
    document.getElementById('other-series-table').querySelector('tbody').innerHTML = '';
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
    document.getElementById('perf-chart-container').style.display = 'none';
    document.getElementById('other-series-chart-container').style.display = 'none';
  }

  async function loadTonnage(athleteId){
    try {
      // Use program-specific endpoint if program is selected
      const url = selectedProgramId 
        ? `/coach/stats/athlete/${athleteId}/program/${selectedProgramId}/tonnage-by-muscle.json`
        : `/coach/stats/athlete/${athleteId}/tonnage-by-muscle.json`;
      const res = await fetch(url);
      if (!res.ok) {
        console.log('Tonnage load failed:', res.status);
        return;
      }
      let data = await res.json();
      
      // Filter tonnage data by date range
      if (dateRange.start || dateRange.end) {
        const filteredData = {};
        Object.keys(data).forEach(muscle => {
          filteredData[muscle] = filterByDateRange(data[muscle]);
        });
        data = filteredData;
      }
      
      tonnageCache = data;
      // populate muscle group select
      muscleSelect.innerHTML = '<option value="">— choisir un groupe musculaire —</option>';
      Object.keys(data).sort().forEach(muscle=>{
        const opt = document.createElement('option'); opt.value = muscle; opt.textContent = muscle; muscleSelect.appendChild(opt);
      });
      // clear chart
      document.getElementById('tonnage-chart-container').style.display = 'none';
    } catch (err) {
      console.error('Error loading tonnage:', err);
    }
  }

  // Generic function to load and cache summary data
  async function loadSummaryData(athleteId, period) {
    // Check cache first
    if (summaryCache[period][athleteId]) {
      return summaryCache[period][athleteId];
    }
    
    // Fetch from API
    try {
      const res = await fetch(`/coach/stats/athlete/${athleteId}/summary-${period}.json`);
      if (!res.ok) {
        console.log(`Summary ${period} load failed:`, res.status);
        return null;
      }
      const data = await res.json();
      
      // Cache it
      summaryCache[period][athleteId] = data;
      return data;
    } catch (err) {
      console.error(`Error loading summary ${period}:`, err);
      return null;
    }
  }

  async function loadSummary(athleteId){
    try {
      const data = await loadSummaryData(athleteId, '7days');
      if (!data) return;
      
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
      const data = await loadSummaryData(athleteId, '14days');
      if (!data) return;
      
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
      const data = await loadSummaryData(athleteId, '28days');
      if (!data) return;
      
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

  function renderTonnage(muscleGroup){
    if (!tonnageCache || !tonnageCache[muscleGroup]) return;
    
    const tonnageData = tonnageCache[muscleGroup];
    createTonnageChart(tonnageData);
    
    // Fill tonnage table
    const tonnageTableBody = document.getElementById('tonnage-table-body');
    tonnageTableBody.innerHTML = '';
    tonnageData.forEach(entry => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #e5e7eb';
      tr.innerHTML = `
        <td style="padding:12px;">${entry.date}</td>
        <td style="padding:12px; text-align:center;">${entry.tonnage !== null ? entry.tonnage.toFixed(2) : '—'}</td>
      `;
      tonnageTableBody.appendChild(tr);
    });
    
    document.getElementById('tonnage-chart-container').style.display = 'block';
  }

  function createTonnageChart(tonnageData){
    const tonnageCtx = document.getElementById('chart-tonnage').getContext('2d');
    
    // Destroy old chart if exists
    if (tonnageChart) {
      tonnageChart.destroy();
    }
    
    const labels = tonnageData.map(d => d.date);
    const tonnage = tonnageData.map(d => d.tonnage);
    
    tonnageChart = new Chart(tonnageCtx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Tonnage total (reps × poids)',
            data: tonnage,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            tension: 0.3,
            fill: true,
            pointBackgroundColor: '#10b981',
            pointRadius: 5,
            pointBorderWidth: 2,
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
            title: { display: true, text: 'Tonnage (reps × kg)', font: { weight: 'bold' } },
            beginAtZero: true
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
      programSelect.style.display = 'none';
      programSelect.innerHTML = '<option value="">— choisir un programme —</option>';
      selectedProgramId = null;
      // Hide loaders when no athlete selected
      document.getElementById('summary-7days-loader').classList.remove('show');
      document.getElementById('summary-14days-loader').classList.remove('show');
      document.getElementById('summary-28days-loader').classList.remove('show');
      return;
    }
    
    // Show loaders when athlete is selected
    document.getElementById('summary-7days-loader').classList.add('show');
    document.getElementById('summary-14days-loader').classList.add('show');
    document.getElementById('summary-28days-loader').classList.add('show');
    
    // Load programs for this athlete
    try {
      const res = await fetch(`/api/athlete/${athleteId}/programs`);
      if (!res.ok) return;
      const data = await res.json();
      
      programSelect.innerHTML = '<option value="">— choisir un programme —</option>';
      data.programs.forEach(prog => {
        const opt = document.createElement('option');
        opt.value = prog.id;
        opt.textContent = prog.name;
        programSelect.appendChild(opt);
      });
      
      // Show program select if there are programs
      if (data.programs.length > 0) {
        programSelect.style.display = 'inline-block';
      } else {
        programSelect.style.display = 'none';
      }
    } catch (err) {
      console.error('Error loading programs:', err);
    }
    
    // Clear performance data since program needs to be selected
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
    document.getElementById('perf-chart-container').style.display = 'none';
    document.getElementById('other-series-chart-container').style.display = 'none';
    
    await loadJournal(athleteId);
    await loadTonnage(athleteId);
    await loadSummary(athleteId);
    await loadSummary14days(athleteId);
    await loadSummary28days(athleteId);
    await preloadAllMuscleDetails(athleteId);
  });

  programSelect.addEventListener('change', async function(){
    const programId = this.value;
    const athleteId = athleteSelect.value;
    
    if (!programId) {
      selectedProgramId = null;
      programExercises = {};
      document.getElementById('main-series-container').style.display = 'none';
      document.getElementById('other-series-container').style.display = 'none';
      document.getElementById('perf-chart-container').style.display = 'none';
      document.getElementById('other-series-chart-container').style.display = 'none';
      exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
      muscleSelect.innerHTML = '<option value="">— choisir un groupe musculaire —</option>';
      document.getElementById('tonnage-chart-container').style.display = 'none';
      return;
    }
    
    selectedProgramId = programId;
    
    // Load exercises for this program FIRST
    try {
      const res = await fetch(`/api/program/${programId}/exercises`);
      if (!res.ok) {
        console.error('Failed to load program exercises:', res.status);
        return;
      }
      const data = await res.json();
      
      // Store program exercises globally
      programExercises = {};
      data.exercises.forEach(ex => {
        programExercises[ex.name] = ex.muscle;
      });
      
      // THEN load performance data (which will now use the program-specific endpoint)
      await loadPerformance(athleteId);
      
      // Load tonnage too
      await loadTonnage(athleteId);
      
      // The backend already filters the data, so we just need to populate the select dropdowns
      // Update exercise select with exercises from this program (already in perfCache)
      if (perfCache) {
        exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
        Object.keys(perfCache).sort().forEach(ex => {
          const opt = document.createElement('option');
          opt.value = ex;
          opt.textContent = ex;
          exSelect.appendChild(opt);
        });
      }
      
      // Update muscle select with only muscles from program exercises
      muscleSelect.innerHTML = '<option value="">— choisir un groupe musculaire —</option>';
      const programMuscles = new Set();
      Object.values(programExercises).forEach(muscle => {
        if (muscle) programMuscles.add(muscle);
      });
      Array.from(programMuscles).sort().forEach(muscle => {
        const opt = document.createElement('option');
        opt.value = muscle;
        opt.textContent = muscle;
        muscleSelect.appendChild(opt);
      });
    } catch (err) {
      console.error('Error loading program exercises:', err);
    }
  });

  // Function to update exercise select based on selected muscle group and program
  function updateExercisesForMuscle(muscleGroup) {
    exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
    if (!muscleGroup) {
      // Show exercises for selected program or all if no program selected
      if (perfCache) {
        Object.keys(perfCache).sort().forEach(ex => {
          // If a program is selected, only show exercises from that program
          if (selectedProgramId && programExercises[ex] === undefined) {
            return;
          }
          const opt = document.createElement('option');
          opt.value = ex;
          opt.textContent = ex;
          exSelect.appendChild(opt);
        });
      }
      return;
    }
    // Show only exercises for selected muscle group (and from selected program if any)
    if (perfCache) {
      Object.keys(perfCache).sort().forEach(ex => {
        const exData = perfCache[ex];
        // Check if exercise belongs to the selected muscle group
        if (exData.muscle_group === muscleGroup) {
          // If a program is selected, only show exercises from that program
          if (selectedProgramId && programExercises[ex] === undefined) {
            return;
          }
          const opt = document.createElement('option');
          opt.value = ex;
          opt.textContent = ex;
          exSelect.appendChild(opt);
        }
      });
    }
  }

  muscleSelect.addEventListener('change', function(){
    const muscle = this.value;
    if (!muscle) { 
      document.getElementById('tonnage-chart-container').style.display = 'none';
      updateExercisesForMuscle(null); // Show all exercises
      return; 
    }
    renderTonnage(muscle);
    updateExercisesForMuscle(muscle); // Filter exercises for this muscle group
  });

  clearMuscle.addEventListener('click', function(){
    muscleSelect.value = '';
    document.getElementById('tonnage-chart-container').style.display = 'none';
    updateExercisesForMuscle(null); // Show all exercises
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
      const id = athleteSelect.value;
      if (id) loadJournal(id);
    });
  });

  // Event delegation for muscle detail buttons - data is preloaded in cache
  document.addEventListener('click', function(e) {
    if (e.target.matches('.show-muscle-detail')) {
      const muscle = e.target.getAttribute('data-muscle');
      const summary = e.target.getAttribute('data-summary');
      
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

      const data = muscleDetailCache[summary][muscle];
      
      // Simulate small delay for UX feedback
      setTimeout(() => {
        // Build detail HTML
        let html = `<h4 style="margin-top:0;">${muscle}</h4>`;
        html += '<table style="width:100%; border-collapse:collapse; margin-top:12px;">';
        html += `<tr style="background:#f3f4f6; border-bottom:2px solid #d1d5db;">
          <th style="padding:8px; text-align:left; font-weight:600;">Exercice</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:100px;">Semaine courante</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:100px;">Il y a 2 sem.</th>
          <th style="padding:8px; text-align:center; font-weight:600; width:80px;">Évolution</th>
        </tr>`;
        
        Object.keys(data.tonnage_diff_by_exercise || {}).sort().forEach(exercise => {
          const current = data.current_tonnage_by_exercise[exercise] || 0;
          const previous = data.previous_tonnage_by_exercise[exercise] || 0;
          const diff = data.tonnage_diff_by_exercise[exercise] || 0;
          const arrow = diff > 0 ? '📈' : (diff < 0 ? '📉' : '→');
          const diffStr = diff >= 0 ? `+${diff.toFixed(0)}` : `${diff.toFixed(0)}`;
          
          html += `<tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px;">${exercise}</td>
            <td style="padding:8px; text-align:center;">${current.toFixed(0)}</td>
            <td style="padding:8px; text-align:center;">${previous.toFixed(0)}</td>
            <td style="padding:8px; text-align:center;">${diffStr} ${arrow}</td>
          </tr>`;
        });
        
        html += '</table>';
        
        document.getElementById('muscle-detail-content').innerHTML = html;
      }, 200); // Small delay for visual feedback
    }
  });
});