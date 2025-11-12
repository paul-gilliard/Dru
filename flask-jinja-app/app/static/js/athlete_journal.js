(function(){
  const existingDates = new Map(); // date -> entryId
  (window.JOURNAL_ENTRIES || []).forEach(e => existingDates.set(e.date, e.id));

  const addForm = document.getElementById('journal-add-form');
  const addDate = document.getElementById('add-entry-date');

  if (addForm) {
    addForm.addEventListener('submit', function(e){
      const d = addDate.value;
      if (!d) return; // let browser validation
      if (existingDates.has(d)) {
        e.preventDefault();
        // show modal offering to edit existing entry
        const existingId = existingDates.get(d);
        if (confirm("Une entrée existe déjà pour cette date. Voulez-vous modifier l'entrée existante à la place ?")) {
          // open edit modal for this entry
          openEditModal(existingId);
        } else {
          // do nothing (prevent add)
        }
      }
    });
  }

  // helpers for modal
  const modal = document.getElementById('journal-edit-modal');
  const backdrop = modal ? modal.querySelector('.confirm-modal-backdrop') : null;
  const editForm = document.getElementById('journal-edit-form');

  async function openEditModal(entryId) {
    if (!modal) return;
    // fetch json
    try {
      const res = await fetch(`/athlete/journal/${entryId}.json`);
      if (!res.ok) throw new Error('fetch failed');
      const data = await res.json();
      // populate fields
      document.getElementById('edit-entry-id').value = data.id;
      document.getElementById('edit-entry-date').value = data.entry_date || '';
      document.getElementById('edit-weight').value = data.weight || '';
      document.getElementById('edit-protein').value = data.protein || '';
      document.getElementById('edit-carbs').value = data.carbs || '';
      document.getElementById('edit-fats').value = data.fats || '';
      document.getElementById('edit-kcals').value = data.kcals || '';
      document.getElementById('edit-water').value = data.water_ml || '';
      document.getElementById('edit-steps').value = data.steps || '';
      document.getElementById('edit-sleep').value = data.sleep_hours || '';
      document.getElementById('edit-digestion').value = data.digestion || '';
      document.getElementById('edit-energy').value = data.energy || '';
      document.getElementById('edit-stress').value = data.stress || '';
      document.getElementById('edit-hunger').value = data.hunger || '';
      document.getElementById('edit-food-quality').value = data.food_quality || '';
      document.getElementById('edit-cycle').value = data.menstrual_cycle || '';

      // set form action
      editForm.action = `/athlete/journal/${data.id}/edit`;
      modal.setAttribute('aria-hidden', 'false');
    } catch (err) {
      alert("Impossible de charger l'entrée.");
    }
  }

  // attach edit buttons
  document.querySelectorAll('.edit-entry-btn').forEach(btn=>{
    btn.addEventListener('click', function(){
      const id = btn.getAttribute('data-entry-id');
      openEditModal(id);
    });
  });

  // modal cancel / backdrop
  const cancelBtn = document.getElementById('edit-cancel-btn');
  if (cancelBtn) cancelBtn.addEventListener('click', ()=> modal.setAttribute('aria-hidden','true'));
  if (backdrop) backdrop.addEventListener('click', ()=> modal.setAttribute('aria-hidden','true'));

  // escape to close
  window.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && modal && modal.getAttribute('aria-hidden') === 'false') {
      modal.setAttribute('aria-hidden','true');
    }
  });
})();