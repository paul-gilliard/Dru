document.addEventListener('click', function(e){
  // Toggle collapse/expand exercise
  if (e.target.matches('.toggle-collapse')) {
    e.preventDefault();
    e.stopPropagation();
    const exerciseBlock = e.target.closest('.exercise-block');
    const isCollapsed = exerciseBlock.classList.toggle('collapsed');
    const select = exerciseBlock.querySelector('.exercise-select');
    
    // Update button text
    e.target.textContent = isCollapsed ? '+' : '−';
    
    // Update exercise name display
    const nameDisplay = exerciseBlock.querySelector('.exercise-name-display');
    if (select) {
      nameDisplay.textContent = select.value || '—';
    }
  }
  
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
        .replace('__EX_REM__', `ex_rem_${day}[]`)
      );
    });
    
    // Store day on exercise block for later reference
    exerciseBlock.setAttribute('data-day', day);
    
    // Attach event listeners for this exercise
    const addSeriesBtn = clone.querySelector('.add-series');
    const deleteExerciseBtn = clone.querySelector('.delete-exercise');
    const exerciseSelect = clone.querySelector('.exercise-select');
    
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
    
    // Add listener for exercise select change
    exerciseSelect.addEventListener('change', function() {
      updateMuscleName(this);
      // Update exercise name display for collapsed view
      const nameDisplay = exerciseBlock.querySelector('.exercise-name-display');
      nameDisplay.textContent = this.value || '—';
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

  // Handle main series checkbox (only one per exercise)
  if (e.target.matches('.series-main-checkbox')) {
    const seriesRow = e.target.closest('.series-row');
    const seriesItems = seriesRow.closest('.series-items');
    
    if (e.target.checked) {
      // Uncheck all other checkboxes in this exercise
      seriesItems.querySelectorAll('.series-main-checkbox').forEach(cb => {
        if (cb !== e.target) {
          cb.checked = false;
        }
      });
    }
  }

  // Remove row (legacy support)
  if (e.target.matches('.remove-row, .btn-remove')) {
    e.preventDefault();
    const tr = e.target.closest('tr');
    if (tr) tr.remove();
  }
});

// Store exercises data for muscle group lookup
let exercisesDatabase = [];

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
      exercisesDatabase = exercises; // Store for later lookup
      
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
          // Also update muscle display for existing exercises
          updateMuscleName(select);
          // Update exercise name display for collapsed view
          const nameDisplay = select.closest('.exercise-block').querySelector('.exercise-name-display');
          if (nameDisplay && select.value) {
            nameDisplay.textContent = select.value;
          }
        }
      });
    })
    .catch(err => {
      console.error('Erreur chargement exercices:', err);
    });
}

// Update muscle display when exercise is selected
function updateMuscleName(select) {
  const exerciseBlock = select.closest('.exercise-block');
  if (!exerciseBlock) return;
  
  const muscleDiv = exerciseBlock.querySelector('.exercise-muscle');
  const exerciseName = select.value;
  
  if (!exerciseName) {
    muscleDiv.textContent = '—';
    return;
  }
  
  // Find exercise in database
  const exercise = exercisesDatabase.find(ex => ex.name === exerciseName);
  if (exercise) {
    muscleDiv.textContent = exercise.muscle_group || '—';
  } else {
    muscleDiv.textContent = '—';
  }
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
    const isMain = row.getAttribute('data-is-main') === 'true';
    parseSeriesDescription(row, desc);
    
    // Check the main series checkbox if applicable
    if (isMain) {
      const checkbox = row.querySelector('.series-main-checkbox');
      if (checkbox) checkbox.checked = true;
    }
  });

  // Populate all exercise selects on page load
  populateExerciseSelects();
  
  // Add change listeners to all exercise selects
  document.querySelectorAll('.exercise-select').forEach(select => {
    select.addEventListener('change', function() {
      updateMuscleName(this);
    });
  });
});

function parseSeriesDescription(row, description) {
  // Example: "S1: 8 reps, Rest: 0.5min, RIR: 2"
  // Extract: reps, rest, rir
  const repsMatch = description.match(/(\d+)\s*reps/i);
  const restMatch = description.match(/Rest:\s*([\d.]+)\s*min/i);
  const rirMatch = description.match(/RIR:\s*([\d.]+)/i);

  // Find inputs within the row
  const inputs = row.querySelectorAll('input');
  if (inputs.length < 3) {
    console.warn('parseSeriesDescription: expected at least 3 inputs, found', inputs.length);
    return;
  }

  // inputs are: Reps, Rest, RIR (in order from grid template)
  if (repsMatch) inputs[0].value = repsMatch[1];
  if (restMatch) inputs[1].value = restMatch[1];
  if (rirMatch) inputs[2].value = rirMatch[1];
}

// Confirmation modal helpers
(function(){
  const modal = document.getElementById('confirm-modal');
  const msgEl = document.getElementById('confirm-message');
  const yesBtn = document.getElementById('confirm-yes');
  const noBtn = document.getElementById('confirm-no');
  
  const recapModal = document.getElementById('recap-modal');
  const recapContent = document.getElementById('recap-content');
  const recapCloseBtn = document.getElementById('recap-close');

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
  
  function showRecap() {
    recapModal.setAttribute('aria-hidden', 'false');
  }
  function hideRecap() {
    recapModal.setAttribute('aria-hidden', 'true');
  }

  // floating buttons
  const saveFloat = document.getElementById('save-float');
  const cancelFloat = document.getElementById('cancel-float');
  const recapFloat = document.getElementById('recap-float');
  const form = document.getElementById('program-form');

  if (saveFloat) {
    saveFloat.addEventListener('click', function(){
      showConfirm('Enregistrer le programme ? Toutes les modifications seront sauvegardées.', function(){
        // Remove any existing series hidden inputs first
        const existingInputs = form.querySelectorAll('input[name*="ex_series_"][type="hidden"], input[name*="ex_main_"][type="hidden"]');
        existingInputs.forEach(input => input.remove());
        
        // Build series descriptions from series grid data BEFORE submit
        const seriesByDay = {};
        const mainSeriesByDay = {};
        document.querySelectorAll('.exercise-block').forEach(exerciseBlock => {
          const day = exerciseBlock.getAttribute('data-day');
          if (!day) return;
          
          if (!seriesByDay[day]) seriesByDay[day] = [];
          if (!mainSeriesByDay[day]) mainSeriesByDay[day] = [];
          
          const seriesRows = exerciseBlock.querySelectorAll('.series-row');
          let seriesDescription = '';
          let mainSeriesNumber = null;
          
          seriesRows.forEach((row, idx) => {
            const reps = row.querySelector('input[placeholder="Reps"]')?.value || '';
            const rest = row.querySelector('input[placeholder="Rest (min)"]')?.value || '';
            const rir = row.querySelector('input[placeholder="RIR"]')?.value || '';
            const isMain = row.querySelector('.series-main-checkbox')?.checked || false;
            
            // Build series line: "S1: 8 reps, Rest: 0.5min, RIR: 2"
            let line = `S${idx + 1}:`;
            if (reps) line += ` ${reps} reps`;
            if (rest) line += `, Rest: ${rest}min`;
            if (rir) line += `, RIR: ${rir}`;
            
            seriesDescription += line + '\n';
            
            if (isMain) {
              mainSeriesNumber = idx + 1;
            }
          });
          
          seriesByDay[day].push(seriesDescription.trim());
          mainSeriesByDay[day].push(mainSeriesNumber);
        });
        
        // Create hidden inputs for all series data and main series
        for (const day in seriesByDay) {
          seriesByDay[day].forEach((seriesDesc, idx) => {
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = `ex_series_${day}[]`;
            hiddenInput.value = seriesDesc;
            form.appendChild(hiddenInput);
            
            // Add main series number
            const mainInput = document.createElement('input');
            mainInput.type = 'hidden';
            mainInput.name = `ex_main_${day}[]`;
            mainInput.value = mainSeriesByDay[day][idx] || '';
            form.appendChild(mainInput);
          });
        }
        
        // Debug log
        console.log('Series data to submit:', seriesByDay);
        console.log('Main series:', mainSeriesByDay);
        
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

  if (recapFloat) {
    recapFloat.addEventListener('click', function(){
      generateRecap();
      showRecap();
    });
  }

  if (recapCloseBtn) {
    recapCloseBtn.addEventListener('click', hideRecap);
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

  // close modals on backdrop click
  const backdrop1 = modal ? modal.querySelector('.confirm-modal-backdrop') : null;
  const backdrop2 = recapModal ? recapModal.querySelector('.confirm-modal-backdrop') : null;
  if (backdrop1) backdrop1.addEventListener('click', hideConfirm);
  if (backdrop2) backdrop2.addEventListener('click', hideRecap);

  // escape key
  window.addEventListener('keydown', function(e){
    if (e.key === 'Escape') {
      if (modal && modal.getAttribute('aria-hidden') === 'false') {
        hideConfirm();
      }
      if (recapModal && recapModal.getAttribute('aria-hidden') === 'false') {
        hideRecap();
      }
    }
  });
  
  // Generate recap content
  function generateRecap() {
    let html = '';
    const days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
    const muscleStats = {}; // Track series count by muscle group
    
    for (let day = 0; day < 7; day++) {
      const dayContainer = document.getElementById(`exercises_day_${day}`);
      const exerciseBlocks = dayContainer ? dayContainer.querySelectorAll('.exercise-block') : [];
      
      if (exerciseBlocks.length === 0) continue;
      
      html += `<div style="margin-bottom: 20px;">`;
      html += `<h4 style="color: #0b63d6; margin-bottom: 8px;">${days[day]}</h4>`;
      html += `<ul style="margin: 0; padding-left: 20px;">`;
      
      exerciseBlocks.forEach(block => {
        const select = block.querySelector('.exercise-select');
        const muscleDiv = block.querySelector('.exercise-muscle');
        const seriesItems = block.querySelector('.series-items');
        const seriesCount = seriesItems ? seriesItems.querySelectorAll('.series-row').length : 0;
        
        const exerciseName = select ? select.value : '—';
        const muscleName = muscleDiv ? muscleDiv.textContent : '—';
        
        // Track muscle stats
        if (muscleName && muscleName !== '—') {
          if (!muscleStats[muscleName]) {
            muscleStats[muscleName] = 0;
          }
          muscleStats[muscleName] += seriesCount;
        }
        
        html += `<li><strong>${exerciseName}</strong> <em style="color: #666;">(${muscleName})</em> <span style="color: #0b63d6; font-weight: 600;">${seriesCount}S</span></li>`;
      });
      
      html += `</ul>`;
      html += `</div>`;
    }
    
    if (!html) {
      html = '<p style="color: #999; font-style: italic;">Aucun exercice programmé</p>';
    } else {
      // Add muscle summary at the bottom
      html += `<div style="margin-top: 24px; padding-top: 16px; border-top: 2px solid rgba(15,23,42,0.1);">`;
      html += `<h4 style="color: #374151; margin-bottom: 12px; font-weight: 600;">Résumé par muscle :</h4>`;
      html += `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;">`;
      
      Object.keys(muscleStats).sort().forEach(muscle => {
        const count = muscleStats[muscle];
        html += `<div style="padding: 10px; background: #f3f4f6; border-radius: 6px; border-left: 4px solid #0b63d6;">`;
        html += `<strong style="color: #0b63d6;">${muscle}</strong><br>`;
        html += `<span style="color: #666; font-size: 0.9rem;">${count} séries</span>`;
        html += `</div>`;
      });
      
      html += `</div>`;
      html += `</div>`;
    }
    
    recapContent.innerHTML = html;
  }
})();

// Drag and drop functionality for reordering exercises
let draggedElement = null;

// Handle save button click - submit the form
document.addEventListener('click', function(e) {
  if (e.target.matches('.save-program-btn')) {
    // Submit the form
    const form = document.getElementById('program-form');
    if (form) {
      form.submit();
    }
  }
});

document.addEventListener('dragstart', function(e) {
  if (e.target.matches('.exercise-block')) {
    draggedElement = e.target;
    e.target.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', e.target.innerHTML);
  }
});

document.addEventListener('dragover', function(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  
  // Add drag-over styling to container or exercise blocks
  if (e.target.matches('.exercise-block') && e.target !== draggedElement) {
    e.target.classList.add('drag-over');
  }
  if (e.target.matches('.exercises-container')) {
    e.target.style.backgroundColor = '#f0f0f0';
  }
});

document.addEventListener('dragleave', function(e) {
  if (e.target.matches('.exercise-block')) {
    e.target.classList.remove('drag-over');
  }
  if (e.target.matches('.exercises-container')) {
    e.target.style.backgroundColor = '';
  }
});

document.addEventListener('drop', function(e) {
  e.preventDefault();
  
  const dropTarget = e.target.closest('.exercise-block') || e.target.closest('.exercises-container');
  
  if (draggedElement && dropTarget && dropTarget !== draggedElement) {
    if (dropTarget.matches('.exercise-block')) {
      // Swap position with target exercise in the same container
      const container = draggedElement.closest('.exercises-container');
      const targetContainer = dropTarget.closest('.exercises-container');
      
      if (container === targetContainer) {
        // Same day: swap order
        const allBlocks = Array.from(container.querySelectorAll('.exercise-block'));
        const draggedIndex = allBlocks.indexOf(draggedElement);
        const targetIndex = allBlocks.indexOf(dropTarget);
        
        if (draggedIndex < targetIndex) {
          dropTarget.after(draggedElement);
        } else {
          dropTarget.before(draggedElement);
        }
      }
    } else if (dropTarget.matches('.exercises-container')) {
      // Move to different container (different day)
      dropTarget.appendChild(draggedElement);
      draggedElement.setAttribute('data-day', dropTarget.id.split('_')[2]);
    }
  }
  
  // Clean up styling
  document.querySelectorAll('.exercise-block.drag-over').forEach(el => {
    el.classList.remove('drag-over');
  });
  document.querySelectorAll('.exercises-container').forEach(el => {
    el.style.backgroundColor = '';
  });
});

document.addEventListener('dragend', function(e) {
  if (e.target.matches('.exercise-block')) {
    e.target.classList.remove('dragging');
    draggedElement = null;
  }
});