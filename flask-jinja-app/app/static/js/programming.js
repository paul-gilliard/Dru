document.addEventListener('click', function(e){
  if (e.target.matches('.add-row')) {
    const day = e.target.getAttribute('data-day');
    const tbody = document.getElementById('tbody_day_' + day);
    const template = document.getElementById('row-template').querySelector('tr').cloneNode(true);
    const map = {
      '__NAME__': `ex_name_${day}[]`,
      '__SETS__': `ex_sets_${day}[]`,
      '__REPS__': `ex_reps_${day}[]`,
      '__REST__': `ex_rest_${day}[]`,
      '__RIR__': `ex_rir_${day}[]`,
      '__INT__': `ex_int_${day}[]`,
      '__MUSC__': `ex_musc_${day}[]`,
      '__REM__': `ex_rem_${day}[]`
    };
    template.querySelectorAll('input').forEach((inp)=>{
      const pname = inp.getAttribute('name');
      for (const key in map) {
        if (pname === key) {
          inp.setAttribute('name', map[key]);
          break;
        }
      }
    });
    tbody.appendChild(template);
  }

  if (e.target.matches('.remove-row')) {
    const tr = e.target.closest('tr');
    if (tr) tr.remove();
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