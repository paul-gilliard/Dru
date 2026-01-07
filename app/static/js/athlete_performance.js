document.addEventListener('DOMContentLoaded', function(){
  const dateInput = document.getElementById('perf-entry-date');
  const viewSummaryBtn = document.getElementById('view-summary-btn');
  const table = document.getElementById('perf-entries-table');
  const tbody = table ? table.querySelector('tbody') : null;
  let rows = table ? Array.from(table.querySelectorAll('tbody tr[data-entry-date]')) : [];
  const editModal = document.getElementById('perf-edit-modal');
  const perfForm = document.getElementById('perf-add-form');
  const exerciseSelect = document.getElementById('perf-exercise');
  const seriesSelect = document.getElementById('perf-series');

  // set default date to today if empty
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0,10);
  }

  function filterByDate(d) {
    console.log('Filtering by date:', d);
    console.log('Total rows in table:', rows.length);
    let visibleCount = 0;
    rows.forEach(r=>{
      const rdate = r.getAttribute('data-entry-date');
      const isVisible = (d === '' || rdate === d);
      r.style.display = isVisible ? '' : 'none';
      if (isVisible) visibleCount++;
    });
    console.log('Visible rows after filter:', visibleCount);
  }

  // Recharge les performances depuis le serveur pour une date donnée
  async function loadPerformancesByDate(date) {
    try {
      const sessionId = window.location.pathname.match(/session\/(\d+)/)?.[1];
      if (!sessionId) {
        console.error('Session ID not found');
        return;
      }

      const response = await fetch(`/api/athlete/performance/session/${sessionId}/by-date?date=${encodeURIComponent(date)}`);
      if (!response.ok) {
        throw new Error('Failed to fetch performances');
      }

      const data = await response.json();
      console.log('Loaded performances:', data);

      // Vider le tableau existant
      if (tbody) {
        tbody.innerHTML = '';
      }

      // Reconstruire les lignes
      if (data.entries && data.entries.length > 0) {
        data.entries.forEach(entry => {
          const row = document.createElement('tr');
          row.setAttribute('data-entry-id', entry.id);
          row.setAttribute('data-entry-date', entry.entry_date);
          row.innerHTML = `
            <td>${entry.entry_date}</td>
            <td>${entry.exercise}</td>
            <td>${entry.series_number || '—'}</td>
            <td>${entry.reps || ''}</td>
            <td>${entry.load || ''}</td>
            <td>${entry.notes || ''}</td>
            <td>
              <button type="button" class="edit-btn edit-perf-btn" data-entry-id="${entry.id}">Modifier</button>
              <button type="button" class="delete-btn delete-perf-btn" data-entry-id="${entry.id}">Supprimer</button>
            </td>
          `;
          tbody.appendChild(row);
          
          // Réattacher l'event listener au bouton d'édition
          row.querySelector('.edit-perf-btn').addEventListener('click', function(){
            openEdit(this.getAttribute('data-entry-id'));
          });
          
          // Réattacher l'event listener au bouton de suppression
          row.querySelector('.delete-perf-btn').addEventListener('click', function(){
            deletePerformance(this.getAttribute('data-entry-id'), entry.exercise);
          });
        });

        // Réasigner les rows
        rows = Array.from(tbody.querySelectorAll('tr[data-entry-date]'));
      } else {
        // Aucune donnée : afficher un message
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="7" class="no-entries">Aucune performance enregistrée pour cette date.</td>';
        tbody.appendChild(row);
        rows = [];
      }
    } catch (error) {
      console.error('Erreur lors du chargement des performances:', error);
      alert('Erreur lors du chargement des données');
    }
  }

  // initial filter after date input has been set (including via localStorage)
  setTimeout(() => {
    if (dateInput) filterByDate(dateInput.value);
  }, 50);

  // change listener - charger les nouvelles données au changement de date
  if (dateInput) dateInput.addEventListener('change', function(){
    loadPerformancesByDate(this.value);
  });

  // open summary page button
  if (viewSummaryBtn && dateInput) {
    viewSummaryBtn.addEventListener('click', function(){
      const d = dateInput.value || new Date().toISOString().slice(0,10);
      // navigate to summary route for this session
      const sid = window.location.pathname.match(/session\/(\d+)/);
      const sessionId = sid ? sid[1] : null;
      if (!sessionId) {
        alert('Session introuvable');
        return;
      }
      window.location.href = `/athlete/performance/session/${sessionId}/summary?date=${encodeURIComponent(d)}`;
    });
  }

  // Edit modal helpers
  async function openEdit(entryId) {
    try {
      const res = await fetch(`/athlete/performance/entry/${entryId}.json`);
      if (!res.ok) throw new Error('failed');
      const data = await res.json();
      document.getElementById('edit-entry-id').value = data.id;
      document.getElementById('edit-entry-date').value = data.entry_date || '';
      document.getElementById('edit-exercise').value = data.exercise || '';
      document.getElementById('edit-series-number').value = data.series_number ?? '';
      document.getElementById('edit-reps').value = (data.reps !== null && data.reps !== undefined) ? String(data.reps) : '';
      document.getElementById('edit-load').value = data.load ?? '';
      document.getElementById('edit-notes').value = data.notes || '';
      // set form action
      document.getElementById('perf-edit-form').action = `/athlete/performance/entry/${data.id}/edit`;
      editModal.setAttribute('aria-hidden','false');
    } catch (err) {
      alert('Impossible de charger l\'entrée.');
    }
  }

  // attach edit buttons
  document.querySelectorAll('.edit-perf-btn').forEach(btn=>{
    btn.addEventListener('click', function(){
      const id = btn.getAttribute('data-entry-id');
      openEdit(id);
    });
  });

  // attach delete buttons
  document.querySelectorAll('.delete-perf-btn').forEach(btn=>{
    btn.addEventListener('click', function(){
      const id = btn.getAttribute('data-entry-id');
      const row = btn.closest('tr');
      const exerciseName = row.querySelector('td:nth-child(2)').textContent;
      deletePerformance(id, exerciseName);
    });
  });

  // modal cancel / backdrop close
  const backdrop = editModal ? editModal.querySelector('.confirm-modal-backdrop') : null;
  const cancelBtn = document.getElementById('perf-edit-cancel');
  if (cancelBtn) cancelBtn.addEventListener('click', ()=> editModal.setAttribute('aria-hidden','true'));
  if (backdrop) backdrop.addEventListener('click', ()=> editModal.setAttribute('aria-hidden','true'));
  window.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && editModal && editModal.getAttribute('aria-hidden') === 'false') {
      editModal.setAttribute('aria-hidden','true');
    }
  });

  // Detect duplicate performance entry (same date + exercise + series)
  if (perfForm) {
    perfForm.addEventListener('submit', function(e){
      const formDate = dateInput.value;
      const formExercise = exerciseSelect.value;
      const formSeries = seriesSelect.value; // could be empty string for "all series"
      
      if (!formDate || !formExercise) return; // let browser validation handle
      
      // Find matching entry
      const matchingEntry = (window.PERF_ENTRIES || []).find(entry => 
        entry.entry_date === formDate &&
        entry.exercise === formExercise &&
        (entry.series_number === (formSeries ? parseInt(formSeries) : null) || 
         (formSeries === '' && entry.series_number === null))
      );
      
      if (matchingEntry) {
        e.preventDefault();
        if (confirm(`Une performance existe déjà pour ${formExercise} le ${formDate}${formSeries ? ' (série ' + formSeries + ')' : ''}.\n\nVoulez-vous modifier la performance existante à la place ?`)) {
          openEdit(matchingEntry.id);
        }
      }
    });
  }

  // after successful edit the server redirects; optional: you could do AJAX submit and update row in DOM
});