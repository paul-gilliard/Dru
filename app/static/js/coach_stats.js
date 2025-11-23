document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
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
  }

  function renderExercise(ex){
    if (!perfCache || !perfCache[ex]) return;
    
    const mainSeriesContainer = document.getElementById('main-series-container');
    const otherSeriesContainer = document.getElementById('other-series-container');
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
    } else {
      mainSeriesContainer.style.display = 'none';
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
    } else {
      otherSeriesContainer.style.display = 'none';
    }
  }

  athleteSelect.addEventListener('change', async function(){
    const id = this.value;
    if (!id) return;
    await loadJournal(id);
    await loadPerformance(id);
  });

  exSelect.addEventListener('change', function(){
    const ex = this.value;
    if (!ex) { 
      document.getElementById('main-series-container').style.display = 'none';
      document.getElementById('other-series-container').style.display = 'none';
      return; 
    }
    renderExercise(ex);
  });

  clearEx.addEventListener('click', function(){
    exSelect.value = '';
    document.getElementById('main-series-container').style.display = 'none';
    document.getElementById('other-series-container').style.display = 'none';
  });

  [toggleKcals, toggleWater, toggleSleep].forEach(el=>{
    el.addEventListener('change', function(){
      const id = athleteSelect.value;
      if (id) loadJournal(id);
    });
  });
});