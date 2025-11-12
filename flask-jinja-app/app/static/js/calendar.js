// Simple responsive month calendar with toggle (no external libs)
(function(){
  const ctx = window.PAGE_CONTEXT || {};
  let current = new Date();
  const el = id => document.getElementById(id);

  function pad(n){ return n<10?'0'+n:''+n; }

  function monthKey(d){
    return d.getFullYear() + '-' + pad(d.getMonth()+1);
  }

  async function fetchAvailability(year, month){
    const q = monthKey(new Date(year, month-1, 1));
    const res = await fetch(`/api/availability?month=${q}&location=${encodeURIComponent(ctx.location)}`);
    if(!res.ok) return [];
    const j = await res.json();
    return j.dates || [];
  }

  async function toggleDate(dateStr){
    const res = await fetch('/api/availability/toggle', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({date: dateStr, location: ctx.location})
    });
    return res.json();
  }

  function renderGrid(year, month, availSet){
    const start = new Date(year, month-1, 1);
    const daysInMonth = new Date(year, month, 0).getDate();
    const startWeekday = start.getDay(); // 0..6 (Sun..Sat)
    // we want week starting Monday: shift
    const shift = (startWeekday + 6) % 7;
    const weeks = Math.ceil((shift + daysInMonth) / 7);

    const container = document.createElement('div');
    container.className = 'card';
    // week day headers
    const header = document.createElement('div');
    header.style.display = 'grid';
    header.style.gridTemplateColumns = 'repeat(7,1fr)';
    header.style.gap = '6px';
    header.style.marginBottom = '8px';
    ['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'].forEach(d => {
      const h = document.createElement('div');
      h.style.fontWeight = '700';
      h.style.textAlign = 'center';
      h.textContent = d;
      header.appendChild(h);
    });
    container.appendChild(header);

    const grid = document.createElement('div');
    grid.style.display = 'grid';
    grid.style.gridTemplateColumns = 'repeat(7,1fr)';
    grid.style.gap = '8px';

    for(let w=0; w<weeks; w++){
      for(let d=0; d<7; d++){
        const cellIndex = w*7 + d;
        const dayNumber = cellIndex - shift + 1;
        const cell = document.createElement('div');
        cell.style.minHeight = '66px';
        cell.style.borderRadius = '8px';
        cell.style.padding = '6px';
        cell.style.background = '#fff';
        cell.style.border = '1px solid rgba(15,23,42,0.04)';
        cell.style.display = 'flex';
        cell.style.flexDirection = 'column';
        cell.style.justifyContent = 'space-between';
        cell.style.cursor = ctx.is_coach ? 'pointer' : 'default';

        if(dayNumber >=1 && dayNumber <= daysInMonth){
          const dateObj = new Date(year, month-1, dayNumber);
          const iso = dateObj.toISOString().slice(0,10);
          const top = document.createElement('div');
          top.style.fontWeight = '700';
          top.style.fontSize = '0.95rem';
          top.textContent = dayNumber;
          const status = document.createElement('div');
          status.className = 'meta';
          status.style.fontSize = '0.9rem';
          status.textContent = availSet.has(iso) ? 'Disponible' : '—';
          if(availSet.has(iso)){
            status.style.color = '#064e3b';
            cell.style.background = 'linear-gradient(180deg,#ecfdf5,#fff)';
            cell.style.border = '1px solid rgba(16,185,129,0.12)';
          }
          cell.appendChild(top);
          cell.appendChild(status);

          if(ctx.is_coach){
            cell.addEventListener('click', async function(){
              const res = await toggleDate(iso);
              // simple update: toggle class based on response
              if(res.status === 'added'){
                status.textContent = 'Disponible';
                status.style.color = '#064e3b';
                cell.style.background = 'linear-gradient(180deg,#ecfdf5,#fff)';
                cell.style.border = '1px solid rgba(16,185,129,0.12)';
                availSet.add(iso);
              } else if(res.status === 'removed'){
                status.textContent = '—';
                status.style.color = '';
                cell.style.background = '#fff';
                cell.style.border = '1px solid rgba(15,23,42,0.04)';
                availSet.delete(iso);
              }
            });
          }
        } else {
          cell.style.background = 'transparent';
          cell.style.border = 'none';
        }
        grid.appendChild(cell);
      }
    }
    container.appendChild(grid);
    return container;
  }

  async function renderMonth(d){
    const year = d.getFullYear();
    const month = d.getMonth()+1;
    el('month-label').textContent = d.toLocaleString('default', {month:'long', year:'numeric'});
    const dates = await fetchAvailability(year, month);
    const availSet = new Set(dates);
    const cal = renderGrid(year, month, availSet);
    const holder = el('calendar');
    holder.innerHTML = '';
    holder.appendChild(cal);
  }

  function init(){
    // create controls
    const prev = el('prev-month');
    const next = el('next-month');
    prev.addEventListener('click', ()=>{ current.setMonth(current.getMonth()-1); renderMonth(current); });
    next.addEventListener('click', ()=>{ current.setMonth(current.getMonth()+1); renderMonth(current); });

    renderMonth(current);
  }

  document.addEventListener('DOMContentLoaded', init);
})();