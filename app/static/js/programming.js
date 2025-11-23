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
    
    // Fill the newly created exercise select with exercise options
    populateExerciseSelects(exerciseBlock);
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

// Populate exercise selects with fetched exercises
function populateExerciseSelects(container = null) {
  // Construct the API endpoint path
  const apiUrl = '/coach/exercises.json';
  
  console.log('Fetching exercises from:', apiUrl);
  
  fetch(apiUrl)
    .then(response => {
      console.log('Response status:', response.status);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(exercises => {
      console.log('Received exercises:', exercises);
      
      // Select all exercise-select elements (or just in container if provided)
      const selects = container 
        ? container.querySelectorAll('.exercise-select')
        : document.querySelectorAll('.exercise-select');
      
      console.log('Found', selects.length, 'exercise-select elements');
      
      selects.forEach(select => {
        const currentValue = select.getAttribute('data-value') || select.value;
        
        // Build options
        let html = '<option value="">-- Sélectionner un exercice --</option>';
        exercises.forEach(ex => {
          html += `<option value="${ex.name}">${ex.name} (${ex.muscle_group})</option>`;
        });
        select.innerHTML = html;
        
        // Restore selected value if any
        if (currentValue) {
          select.value = currentValue;
        }
      });
    })
    .catch(err => {
      console.error('Erreur chargement exercices:', err);
    });
}

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

// Parse existing series descriptions and load into inputs
document.addEventListener('DOMContentLoaded', function() {
  // Parse existing series data from series-description attribute
  document.querySelectorAll('.series-row[data-series-description]').forEach(row => {
    const desc = row.getAttribute('data-series-description');
    parseSeriesDescription(row, desc);
  });

  // Populate all exercise selects on page load
  populateExerciseSelects();

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

function parseSeriesDescription(row, description) {
  // Example: "S1: 8 reps 100kg, Rest: 60s, RIR: 2, Int: 1"
  // Extract: reps, load, rest, rir, intensification
  const repsMatch = description.match(/(\d+)\s*reps/i);
  const loadMatch = description.match(/(\d+(?:\.\d+)?)\s*kg/i);
  const restMatch = description.match(/Rest:\s*(\d+)/i);
  const rirMatch = description.match(/RIR:\s*([\d.]+)/i);
  const intMatch = description.match(/Int:\s*(\d+)/i);

  const repsInput = row.querySelector('input[placeholder="Reps"]');
  const loadInput = row.querySelector('input[placeholder="Poids"]');
  const restInput = row.querySelector('input[placeholder="Rest (s)"]');
  const rirInput = row.querySelector('input[placeholder="RIR"]');
  const intInput = row.querySelector('input[placeholder="Int"]');

  if (repsMatch && repsInput) repsInput.value = repsMatch[1];
  if (loadMatch && loadInput) loadInput.value = loadMatch[1];
  if (restMatch && restInput) restInput.value = restMatch[1];
  if (rirMatch && rirInput) rirInput.value = rirMatch[1];
  if (intMatch && intInput) intInput.value = intMatch[1];
}

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