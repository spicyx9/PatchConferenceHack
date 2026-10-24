/* Scoped connection explorer. All text from profiles/models is escaped. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const colors = {Person:'#8196bc', Company:'#ac99bc', Event:'#c5a185', Topic:'#a9a7bd', Goal:'#606776', User:'#606776'};
  const labels = {WORKS_AT:'works at', SPEAKS_AT:'speaks at', ABOUT:'about', HOSTS:'hosts', HAS_GOAL:'prioritizes', ATTENDS_CONFIRMED:'attends'};
  let scope='all', all=[], shown=[], cy=null, request=0, selected=null, busy=false;
  const filters={company:'',role:'',topic:''};
  const roleNames={devrel:'Developer relations',engineer:'Engineer',executive:'Executive',founder:'Founder',investor:'Investor',pm:'Product management'};
  const filterNames={company:'All companies',role:'All roles',topic:'All topics'};
  function params(extra={}) {return new URLSearchParams({scope,...filters,...extra}).toString();}
  function filterControls(data) {
    Object.keys(filters).forEach(k=>{
      const options=data.filters[k]||[];
      $('filter-'+k+'-options').innerHTML=['',...options].map(v=>`<button type="button" data-filter-value="${esc(v)}" aria-pressed="${filters[k]===v}">${esc(v?(k==='role'?(roleNames[v]||v):v):filterNames[k])}<span aria-hidden="true">${filters[k]===v?'✓':''}</span></button>`).join('');
      $('filter-'+k+'-value').textContent=filters[k]?(k==='role'?(roleNames[filters[k]]||filters[k]):filters[k]):filterNames[k];
      $('filter-'+k).querySelector('input').value='';
      $('filter-'+k).querySelector('.filter-no-options').hidden=true;
    });
    $('filter-count').textContent=`${data.count} of ${data.total} people`;
    $('filter-reset').hidden=!Object.values(filters).some(Boolean);
  }
  async function api(path, body) {
    const response = await fetch('/api/v1/'+path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not load connections.');
    return result;
  }
  const initials = name => name.split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('');
  function personRows(items) {
    $('connection-results').innerHTML = items.length ? items.map(p=>`<button class="connection-person ${selected===p.id?'selected':''}" data-person="${esc(p.id)}">
      <span class="person-monogram">${esc(initials(p.name))}${p.photo?`<img class="connection-avatar" src="${esc(p.photo.url)}" alt="" loading="lazy" />`:""}</span><span class="person-row-copy"><b>${esc(p.name)}</b>
      <small>${esc(p.title || p.company || 'Profile')}</small>${p.reason?`<span class="match-reason">${esc(p.reason)}</span>`:''}</span><span class="person-arrow">↗</span></button>`).join('') : '<div class="connection-empty">No people found.<p>Try a different query or list.</p></div>';
  }
  function fit() { if(cy && $('graph').clientWidth) {cy.resize();cy.fit(undefined,45);} }
  function draw(graph) {
    if(cy) {cy.destroy();cy=null;}
    const nodes=graph.nodes || [], edges=graph.edges || [];
    $('network-count').textContent = nodes.length ? `${nodes.length} nodes · ${edges.length} links` : '';
    $('graph-focus-summary').textContent=`${nodes.length} entities in the current network.`;
    $('graph-legend').innerHTML=Object.keys(colors).filter(t=>nodes.some(n=>n.type===t)).map(t=>`<span><i style="background:${colors[t]}"></i>${t==='Goal'?'Priority':esc(t)}</span>`).join('');
    $('graph-fallback').textContent=nodes.map(n=>`${n.type}: ${n.label}`).join(' · ');
    $('graph').setAttribute('data-layout-ready','false');
    if(!nodes.length || typeof Galaxy3D==='undefined') {
      $('graph').innerHTML='<div class="network-empty">'+(!nodes.length?'No connections in this list yet.':'Graph viewer unavailable. People are listed alongside.')+'</div>';
      return;
    }
    $('graph').innerHTML='';
    cy=new Galaxy3D($('graph'),graph,{colors,select:d=>{if(d.type==='Person')focus(d.id);else showNode(d);}});
    $('network-orbit').textContent=cy.turning?'Pause orbit':'Resume orbit';
    $('network-orbit').setAttribute('aria-pressed',String(cy.turning));
    $('graph').setAttribute('data-layout-ready','true');
    fit();
  }
  function showNode(d) {
    $('graph-detail').innerHTML=`<div class="connection-detail"><span class="detail-kicker">${esc(d.type)}</span><h3>${esc(d.label)}</h3><small>${esc(d.source_mode)}</small></div>`;
  }
  function details(p,path) {
    const sources=p.sources.filter(s=>s.source_url && /^https?:\/\//.test(s.source_url));
    $('graph-detail').innerHTML=`<div class="connection-detail"><span class="detail-kicker">${p.met?'RECORDED MEETING':'PROFILE'} · ${esc(p.source_mode)}</span>
      ${p.photo?`<img class="connection-profile-photo" src="${esc(p.photo.url)}" alt="${esc(p.name)}" />`:""}<h3>${esc(p.name)}</h3><p>${esc([p.title,p.company].filter(Boolean).join(' · '))}</p>
      ${p.participation==='relevant_candidate'?'<p class="muted">Potential connection · attendance unconfirmed</p>':''}
      ${p.bio?`<p class="detail-bio">${esc(p.bio.slice(0,420))}</p>`:''}
      <div class="topic-pills">${p.topics.slice(0,5).map(t=>`<span>${esc(t)}</span>`).join('')}</div>
      ${path && path.path && path.path.length?`<h4>Connection path</h4><ol class="connection-path">${path.path.filter(x=>x.node).map(x=>`<li>${esc(x.node.label)}</li>`).join('')}</ol>`:'<p class="muted">No goal path recorded.</p>'}
      ${p.events.length?`<h4>Sessions</h4><ul class="connection-sessions">${p.events.slice(0,3).map(e=>`<li>${esc(e.title)}</li>`).join('')}</ul>`:''}
      ${p.photo?`<a class="connection-source-link" href="${esc(p.photo.source_url)}" target="_blank" rel="noopener noreferrer">Photo: ${p.photo.provider==='brightdata:web_unlocker'?'LinkedIn · via Bright Data':'Official team profile'} ↗</a>`:""}
      ${sources.length?`<h4>Sources</h4>${sources.slice(0,3).map(s=>`<a class="connection-source-link" href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">${esc(s.provider)} ↗</a>`).join('')}`:''}</div>`;
  }
  async function focus(id) {
    const ticket=++request;readySearch();selected=id;$('connection-clear').hidden=false;$('network-all').hidden=false;
    $('graph-detail').textContent='Loading profile…';
    personRows(shown);
    try {
      const [data,path]=await Promise.all([api('connections?'+params({focus:id})),api(`graph/path?person=${encodeURIComponent(id)}`).catch(()=>null)]);
      if(ticket!==request)return;
      const p=data.items.find(x=>x.id===id);
      if(!p){$('graph-detail').textContent='This person is not in the selected list.';return;}
      draw(data.graph);details(p,path);
      if(cy)cy.select(id);
    } catch(e){if(ticket===request)$('graph-detail').textContent=e.message;}
  }
  async function render() {
    const ticket=++request;readySearch();
    try {
      const data=await api('connections?'+params());
      if(ticket!==request)return;
      filterControls(data);all=data.items;const visible=new Set(data.graph.nodes.filter(n=>n.type==='Person').map(n=>n.id));shown=[...all.filter(p=>visible.has(p.id)),...all.filter(p=>!visible.has(p.id))];selected=null;
      $('connections-count').textContent=`${all.length} people in ${scope==='met'?'your recorded meetings':'your directory'}`;
      $('connection-results-title').textContent='People';$('connection-clear').hidden=!Object.values(filters).some(Boolean);$('network-all').hidden=!Object.values(filters).some(Boolean);
      $('connection-summary').textContent='';
      $('graph-detail').innerHTML='';personRows(shown);draw(data.graph);
    }catch(e){if(ticket===request)$('connection-summary').textContent=e.message;}
  }
  async function search(event) {
    if(event)event.preventDefault();
    const query=$('connection-query').value.trim();if(query.length<2||busy)return;
    const ticket=++request;busy=true;$('connection-submit').disabled=true;$('connection-submit').textContent='Searching…';
    $('connection-summary').textContent='Searching this list…';$('graph-detail').innerHTML='';
    try {
      const result=await api('connections/search',{query,scope,...filters});if(ticket!==request)return;
      shown=result.items;selected=null;personRows(shown);
      $('connection-results-title').textContent=`${shown.length} matches`;
      $('connection-summary').textContent=result.summary;$('connection-clear').hidden=false;$('network-all').hidden=false;
      if(!shown.length)draw({nodes:[],edges:[],backend:'falkordb'});
      if(shown.length){const data=await api('connections?'+params({focus:shown[0].id}));if(ticket===request)draw(data.graph);}
    }catch(e){if(ticket===request)$('connection-summary').textContent=e.message;}
    finally{if(ticket===request)readySearch();}
  }
  $('connection-results').addEventListener('error',e=>{if(e.target.classList.contains('connection-avatar'))e.target.remove();},true);
  $('connection-search').addEventListener('submit',search);
  document.querySelectorAll('[data-connection-scope]').forEach(button=>button.addEventListener('click',()=>{
    scope=button.dataset.connectionScope;Object.keys(filters).forEach(k=>filters[k]='');$('connection-query').value='';
    document.querySelectorAll('[data-connection-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    render();
  }));
  document.querySelectorAll('[data-connection-query]').forEach(button=>button.addEventListener('click',()=>{$('connection-query').value=button.dataset.connectionQuery;search();}));
  $('connection-results').addEventListener('click',e=>{const b=e.target.closest('[data-person]');if(b)focus(b.dataset.person);});
  function readySearch() {busy=false;$('connection-submit').disabled=false;$('connection-submit').innerHTML='Find people <span aria-hidden="true">↗</span>';}
  function resetSearch() {
    scope='all';
    document.querySelectorAll('[data-connection-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.connectionScope==='all')));
    Object.keys(filters).forEach(k=>filters[k]='');
    document.querySelectorAll('.filter-menu').forEach(menu=>menu.open=false);
    $('connection-query').value='';readySearch();render();
  }
  Object.keys(filters).forEach(k=>{
    const menu=$('filter-'+k),input=menu.querySelector('input'),summary=menu.querySelector('summary');
    menu.addEventListener('toggle',()=>{if(menu.open){document.querySelectorAll('.filter-menu').forEach(other=>{if(other!==menu)other.open=false;});}});
    input.addEventListener('input',()=>{let count=0;menu.querySelectorAll('[data-filter-value]').forEach(b=>{b.hidden=!b.textContent.toLowerCase().includes(input.value.toLowerCase());if(!b.hidden)count++;});menu.querySelector('.filter-no-options').hidden=count>0;});
    menu.addEventListener('click',e=>{const button=e.target.closest('[data-filter-value]');if(!button)return;filters[k]=button.dataset.filterValue;menu.open=false;summary.focus();$('connection-query').value='';render();});
    menu.addEventListener('keydown',e=>{if(e.key==='Escape'){menu.open=false;summary.focus();}});
  });
  document.addEventListener('pointerdown',e=>{document.querySelectorAll('.filter-menu[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;});});
  $('connection-reset').addEventListener('click',resetSearch);
  $('filter-reset').addEventListener('click',resetSearch);
  $('connection-clear').addEventListener('click',resetSearch);
  $('network-all').addEventListener('click',resetSearch);
  $('network-orbit').addEventListener('click',()=>{if(cy){const running=cy.toggle();$('network-orbit').textContent=running?'Pause orbit':'Resume orbit';$('network-orbit').setAttribute('aria-pressed',String(running));}});
  $('network-fit').addEventListener('click',fit);
  $('network-zoom-in').addEventListener('click',()=>{if(cy)cy.zoom(cy.zoom()*1.2);});
  $('network-zoom-out').addEventListener('click',()=>{if(cy)cy.zoom(cy.zoom()/1.2);});
  new ResizeObserver(fit).observe($('graph'));
  window.Connections={render,focus};
})();
