document.addEventListener('DOMContentLoaded', function(){
  const athleteSelect = document.getElementById('stats-athlete-select');
  const chartJournalCtx = document.getElementById('chart-journal').getContext('2d');
  const chartPerfCtx = document.getElementById('chart-performance').getContext('2d');
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

  let perfChart = new Chart(chartPerfCtx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: { interaction:{mode:'index',intersect:false}, scales:{ y:{type:'linear'} } }
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
    Object.keys(data).forEach(ex=>{
      const opt = document.createElement('option'); opt.value = ex; opt.textContent = ex; exSelect.appendChild(opt);
    });
    // clear chart
    perfChart.data.labels = [];
    perfChart.data.datasets = [];
    perfChart.update();
  }

  function renderExercise(ex){
    if (!perfCache || !perfCache[ex]) return;
    const series = perfCache[ex];
    const labels = series.map(s=>s.date);
    const avgLoad = series.map(s=> s.avg_load === null ? null : Number(s.avg_load.toFixed(2)));
    const avgReps = series.map(s=> s.avg_reps === null ? null : Number(s.avg_reps.toFixed(2)));
    perfChart.data.labels = labels;
    perfChart.data.datasets = [
      { label: `${ex} — charge moyenne (kg)`, data: avgLoad, borderColor:'#0b63d6', tension:0.2 },
      { label: `${ex} — reps moy.`, data: avgReps, borderColor:'#ef4444', tension:0.2 }
    ];
    perfChart.update();
  }

  athleteSelect.addEventListener('change', async function(){
    const id = this.value;
    if (!id) return;
    await loadJournal(id);
    await loadPerformance(id);
  });

  exSelect.addEventListener('change', function(){
    const ex = this.value;
    if (!ex) { perfChart.data.labels=[]; perfChart.data.datasets=[]; perfChart.update(); return; }
    renderExercise(ex);
  });

  clearEx.addEventListener('click', function(){
    exSelect.value = '';
    perfChart.data.labels=[]; perfChart.data.datasets=[]; perfChart.update();
  });

  [toggleKcals, toggleWater, toggleSleep].forEach(el=>{
    el.addEventListener('change', function(){
      const id = athleteSelect.value;
      if (id) loadJournal(id);
    });
  });
});