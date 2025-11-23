document.addEventListener('click', function(e){
  // Add new exercise
  if (e.target.matches('.add-exercise, .btn-add-exercise')) {
    const day = e.target.getAttribute('data-day');
    const container = document.getElementById(`exercises_day_${day}`);
    const template = document.getElementById('exercise-template');
    const clone = template.content.cloneNode(true);
    
    // Update field names with day number
    const exerciseBlock = clone.querySelector('.exercise-block');
    const fields = clone.querySelectorAll('[name*="__"]');
    fields.forEach(field => {
      const name = field.getAttribute('name');
      field.setAttribute('name', name
        .replace('__EX_NAME__', `ex_name_${day}[]`)
        .replace('__EX_MUSC__', `ex_musc_${day}[]`)
        .replace('__EX_REM__', `ex_rem_${day}[]`)
      );
    });
    
    // Store day on exercise block for later reference
    exerciseBlock.setAttribute('data-day', day);
    
    // Attach event listeners for this exercise
    const addSeriesBtn = clone.querySelector('.add-series');
    const deleteExerciseBtn = clone.querySelector('.delete-exercise');
    
    addSeriesBtn.addEventListener('click', function(evt) {
      evt.preventDefault();
      const seriesList = exerciseBlock.querySelector('.series-list');
      const seriesItems = seriesList.querySelector('.series-items');
      addSeriesRow(seriesItems);
    });
    
    deleteExerciseBtn.addEventListener('click', function(evt) {
      evt.preventDefault();
      exerciseBlock.remove();
    });
    
    container.appendChild(clone);
  }

  // Add new series row
  if (e.target.matches('.add-series')) {
    e.preventDefault();
    const seriesList = e.target.closest('.series-list');
    const seriesItems = seriesList.querySelector('.series-items');
    addSeriesRow(seriesItems);
  }

  // Delete series row
  if (e.target.matches('.delete-series')) {
    e.preventDefault();
    const seriesRow = e.target.closest('.series-row');
    seriesRow.remove();
    // Update series numbers
    const seriesItems = seriesRow.closest('.series-items');
    updateSeriesNumbers(seriesItems);
  }

  // Delete exercise
  if (e.target.matches('.delete-exercise')) {
    e.preventDefault();
    const exerciseBlock = e.target.closest('.exercise-block');
    exerciseBlock.remove();
  }

  // Remove row (legacy support)
  if (e.target.matches('.remove-row, .btn-remove')) {
    e.preventDefault();
    const tr = e.target.closest('tr');
    if (tr) tr.remove();
  }
});

function addSeriesRow(seriesItems) {
  const template = document.getElementById('series-template');
  const clone = template.content.cloneNode(true);
  
  // Count existing series to auto-increment
  const seriesCount = seriesItems.querySelectorAll('.series-row').length + 1;
  const label = clone.querySelector('.series-number');
  label.textContent = `S${seriesCount}`;
  
  seriesItems.appendChild(clone);
}

function updateSeriesNumbers(seriesItems) {
  const rows = seriesItems.querySelectorAll('.series-row');
  rows.forEach((row, index) => {
    const label = row.querySelector('.series-number');
    label.textContent = `S${index + 1}`;
  });
}

// Override form submission to build series_description from grid data
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('program-form');
  if (form) {
    form.addEventListener('submit', function(e) {
      // Build series descriptions from series grid data
      document.querySelectorAll('.exercise-block').forEach(exerciseBlock => {
        const day = exerciseBlock.getAttribute('data-day');
        if (!day) return;
        
        const seriesRows = exerciseBlock.querySelectorAll('.series-row');
        let seriesDescription = '';
        
        seriesRows.forEach((row, idx) => {
          const reps = row.querySelector('input[placeholder="Reps"]')?.value || '';
          const load = row.querySelector('input[placeholder="Poids"]')?.value || '';
          const rest = row.querySelector('input[placeholder="Rest (s)"]')?.value || '';
          const rir = row.querySelector('input[placeholder="RIR"]')?.value || '';
          const Int = row.querySelector('input[placeholder="Int"]')?.value || '';
          
          // Build series line: "S1: 8 reps 100kg, Rest: 60s, RIR: 2, Int: 1"
          let line = `S${idx + 1}:`;
          if (reps) line += ` ${reps} reps`;
          if (load) line += ` ${load}kg`;
          if (rest) line += `, Rest: ${rest}s`;
          if (rir) line += `, RIR: ${rir}`;
          if (Int) line += `, Int: ${Int}`;
          
          seriesDescription += line + '\n';
        });
        
        // Create hidden input for series_description if needed, or use hidden field
        // For now, we'll create a FormData-like approach by modifying how we send
        // Actually, we need to add hidden inputs for the backend to parse correctly
        // The backend expects ex_series_<day>[] to contain the series description
        
        // We'll inject a hidden input with the series description
        const hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.name = `ex_series_${day}[]`;
        hiddenInput.value = seriesDescription.trim();
        form.appendChild(hiddenInput);
      });
    });
  }
});

// Confirmation modal helpers
(function(){
  const modal = document.getElementById('confirm-modal');
  const msgEl = document.getElementById('confirm-message');
  const yesBtn = document.getElementById('confirm-yes');
  const noBtn = document.getElementById('confirm-no');

  let onConfirm = null;

  function showConfirm(message, callback) {
    onConfirm = callback;
    msgEl.textContent = message;
    modal.setAttribute('aria-hidden', 'false');
  }
  function hideConfirm() {
    modal.setAttribute('aria-hidden', 'true');
    onConfirm = null;
  }

  // floating buttons
  const saveFloat = document.getElementById('save-float');
  const cancelFloat = document.getElementById('cancel-float');
  const form = document.getElementById('program-form');

  if (saveFloat) {
    saveFloat.addEventListener('click', function(){
      showConfirm('Enregistrer le programme ? Toutes les modifications seront sauvegardées.', function(){
        // submit form
        if (form) {
          // disable buttons to prevent multiple submit
          saveFloat.disabled = true;
          form.submit();
        }
      });
    });
  }

  if (cancelFloat) {
    cancelFloat.addEventListener('click', function(){
      const returnUrl = cancelFloat.getAttribute('data-return-url') || '/coach/programming';
      showConfirm("Vous n'enregistrerez pas vos modifications. Continuer ?", function(){
        window.location.href = returnUrl;
      });
    });
  }

  // modal buttons
  if (yesBtn) yesBtn.addEventListener('click', function(){
    if (typeof onConfirm === 'function') {
      const cb = onConfirm;
      hideConfirm();
      // small timeout to allow modal to close visually
      setTimeout(cb, 60);
    }
  });
  if (noBtn) noBtn.addEventListener('click', function(){
    hideConfirm();
  });

  // close modal on backdrop click
  const backdrop = modal ? modal.querySelector('.confirm-modal-backdrop') : null;
  if (backdrop) backdrop.addEventListener('click', hideConfirm);

  // escape key
  window.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && modal && modal.getAttribute('aria-hidden') === 'false') {
      hideConfirm();
    }
  });
})();