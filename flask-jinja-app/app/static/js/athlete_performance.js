document.addEventListener('DOMContentLoaded', function(){
  const dateInput = document.getElementById('perf-entry-date');
  const viewSummaryBtn = document.getElementById('view-summary-btn');
  const table = document.getElementById('perf-entries-table');
  const rows = table ? Array.from(table.querySelectorAll('tbody tr[data-entry-date]')) : [];
  const editModal = document.getElementById('perf-edit-modal');

  // set default date to today if empty
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0,10);
  }

  function filterByDate(d) {
    rows.forEach(r=>{
      const rdate = r.getAttribute('data-entry-date');
      r.style.display = (d === '' || rdate === d) ? '' : 'none';
    });
  }

  // initial filter
  if (dateInput) filterByDate(dateInput.value);

  // change listener
  if (dateInput) dateInput.addEventListener('change', function(){
    filterByDate(this.value);
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
      document.getElementById('edit-sets').value = data.sets ?? '';
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

  // after successful edit the server redirects; optional: you could do AJAX submit and update row in DOM
});