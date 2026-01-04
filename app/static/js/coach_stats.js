document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
  const muscleSelect = document.getElementById('stats-muscle-select');
  const clearMuscle = document.getElementById('clear-muscle');
  const exSelect = document.getElementById('stats-exercise-select');
  const clearEx = document.getElementById('clear-exercise');
  const toggleKcals = document.getElementById('toggle-kcals');
  const toggleWater = document.getElementById('toggle-water');
  const toggleSleep = document.getElementById('toggle-sleep');

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

  async function loadJournal(athleteId){
    const res = await fetch(`/coach/stats/athlete/${athleteId}/journal.json`);
    if (!res.ok) return;
    const data = await res.json();
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
  }

  let perfCache = null;
  async function loadPerformance(athleteId){
    const res = await fetch(`/coach/stats/athlete/${athleteId}/performance.json`);
    if (!res.ok) return;
    const data = await res.json();
    perfCache = data;
    // populate exercise select
    exSelect.innerHTML = '<option value="">— choisir un exercice —</option>';
    Object.keys(data).sort().forEach(ex=>{
      const opt = document.createElement('option'); opt.value = ex; opt.textContent = ex; exSelect.appendChild(opt);
    });
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
      const res = await fetch(`/coach/stats/athlete/${athleteId}/tonnage-by-muscle.json`);
      if (!res.ok) {
        console.log('Tonnage load failed:', res.status);
        return;
      }
      const data = await res.json();
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

  function renderTonnage(muscleGroup){
    if (!tonnageCache || !tonnageCache[muscleGroup]) return;
    
    const tonnageData = tonnageCache[muscleGroup];
    createTonnageChart(tonnageData);
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
    const id = this.value;
    if (!id) return;
    await loadJournal(id);
    await loadPerformance(id);
    await loadTonnage(id);
  });

  muscleSelect.addEventListener('change', function(){
    const muscle = this.value;
    if (!muscle) { 
      document.getElementById('tonnage-chart-container').style.display = 'none';
      return; 
    }
    renderTonnage(muscle);
  });

  clearMuscle.addEventListener('click', function(){
    muscleSelect.value = '';
    document.getElementById('tonnage-chart-container').style.display = 'none';
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
});