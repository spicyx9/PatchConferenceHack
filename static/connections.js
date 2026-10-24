/* Scoped connection explorer. All text from profiles/models is escaped. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const colors = {Person:'#bad3c4', Company:'#e7e2f2', Event:'#ead1ba', Topic:'#e8ebee', Goal:'#202d29', User:'#202d29'};
  const labels = {WORKS_AT:'works at', SPEAKS_AT:'speaks at', ABOUT:'about', HOSTS:'hosts', HAS_GOAL:'prioritizes', ATTENDS_CONFIRMED:'attends'};
  let scope='all', all=[], shown=[], cy=null, request=0, selected=null, busy=false;
  async function api(path, body) {
    const response = await fetch('/api/v1/'+path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not load connections.');
    return result;
  }
  const initials = name => name.split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('');
  function personRows(items) {
    $('connection-results').innerHTML = items.length ? items.map(p=>`<button class="connection-person ${selected===p.id?'selected':''}" data-person="${esc(p.id)}">
      <span class="person-monogram">${esc(initials(p.name))}</span><span class="person-row-copy"><b>${esc(p.name)}</b>
      <small>${esc(p.title || p.company || 'Profile')}</small>${p.reason?`<span class="match-reason">${esc(p.reason)}</span>`:''}</span><span class="person-arrow">↗</span></button>`).join('') : '<div class="connection-empty">No people found.<p>Try a different query or list.</p></div>';
  }
  function fit() { if(cy && $('graph').clientWidth) {cy.resize();cy.fit(undefined,45);} }
  function draw(graph) {
    if(cy) {cy.destroy();cy=null;}
    const nodes=graph.nodes || [], edges=graph.edges || [];
    $('graph-backend').textContent = graph.backend==='falkordb' ? 'FalkorDB' : 'Graph unavailable';
    $('network-count').textContent = nodes.length ? `${nodes.length} nodes · ${edges.length} links` : '';
    $('graph-focus-summary').textContent=`${nodes.length} entities in the current network.`;
    $('graph-legend').innerHTML=Object.keys(colors).filter(t=>nodes.some(n=>n.type===t)).map(t=>`<span><i style="background:${colors[t]}"></i>${t==='Goal'?'Priority':esc(t)}</span>`).join('');
    $('graph-fallback').textContent=nodes.map(n=>`${n.type}: ${n.label}`).join(' · ');
    $('graph').setAttribute('data-layout-ready','false');
    if(!nodes.length || typeof cytoscape==='undefined') {
      $('graph').innerHTML='<div class="network-empty">'+(!nodes.length?'No connections in this list yet.':'Graph viewer unavailable. People are listed alongside.')+'</div>';
      return;
    }
    $('graph').innerHTML='';
    const types=['Goal','Topic','Person','Event','Company','User'];
    const groups={};nodes.forEach(n=>(groups[n.type] ||= []).push(n));
    const elements=nodes.map(n=>{
      const group=groups[n.type], index=group.indexOf(n), column=types.indexOf(n.type);
      return {data:{...n,color:colors[n.type]||'#e9e9e9'},position:{x:column*190+((index%2)*20),y:index*100-(group.length*50)}};
    }).concat(edges.map(e=>({data:{...e,edgeLabel:labels[e.type]||e.type}})));
    cy=cytoscape({container:$('graph'),elements,minZoom:0.25,maxZoom:2.5,wheelSensitivity:0.2,
      style:[
        {selector:'node',style:{'background-color':'data(color)','border-color':'#ffffff','border-width':3,'label':'data(label)',
          'font-family':'Inter, Arial, sans-serif','font-size':18,'font-weight':500,'color':'#46534e','text-valign':'bottom','text-margin-y':9,
          'text-wrap':'ellipsis','text-max-width':155,'width':38,'height':38,'overlay-opacity':0}},
        {selector:'node[type="Person"]',style:{'width':58,'height':58,'border-width':4,'font-size':20,'font-weight':650,'color':'#1c3028'}},
        {selector:'node[type="Company"]',style:{'shape':'round-rectangle','width':35,'height':35}},
        {selector:'node[type="Event"]',style:{'shape':'round-rectangle','width':36,'height':36}},
        {selector:'node[type="Goal"]',style:{'shape':'round-rectangle','width':124,'height':46,'color':'#ffffff','font-size':14,'text-valign':'center','text-margin-y':0,'text-max-width':110,'text-wrap':'wrap'}},
        {selector:'edge',style:{'width':1.2,'line-color':'#aebfb5','curve-style':'bezier','opacity':0.85,'target-arrow-shape':'none'}},
        {selector:'node:selected',style:{'border-color':'#759b85','border-width':4}},
        {selector:'.muted',style:{'opacity':0.14}},
        {selector:'edge:selected',style:{'line-color':'#597f6c','width':2.5,'label':'data(edgeLabel)','font-size':10,'text-background-color':'#fafcf9','text-background-opacity':1,'text-background-padding':4}},
      ],layout:{name:'cose',randomize:false,animate:false,nodeRepulsion:()=>6500,idealEdgeLength:()=>65,
        edgeElasticity:()=>80,gravity:0.8,numIter:600,padding:45,fit:true,stop:()=>{$('graph').setAttribute('data-layout-ready','true');}}});
    cy.nodes().positions(n=>({x:n.position('x')*1.15,y:n.position('y')*0.67}));
    cy.on('tap','node',event=>{const d=event.target.data();if(d.type==='Person') focus(d.id);else showNode(d);});
    cy.on('tap','edge',event=>{const d=event.target.data();$('graph-detail').innerHTML=`<div class="connection-detail"><span class="detail-kicker">RELATIONSHIP</span><h3>${esc(labels[d.type]||d.type)}</h3><p>${esc(cy.getElementById(d.source).data('label'))} → ${esc(cy.getElementById(d.target).data('label'))}</p><small>Source: ${esc(d.source_mode || 'unknown')} · ${esc(d.evidence_source || '')}</small></div>`;});
    fit();
  }
  function showNode(d) {
    $('graph-detail').innerHTML=`<div class="connection-detail"><span class="detail-kicker">${esc(d.type)}</span><h3>${esc(d.label)}</h3><small>${esc(d.source_mode)}</small></div>`;
  }
  function details(p,path) {
    const sources=p.sources.filter(s=>s.source_url && /^https?:\/\//.test(s.source_url));
    $('graph-detail').innerHTML=`<div class="connection-detail"><span class="detail-kicker">${p.met?'RECORDED MEETING':'PROFILE'} · ${esc(p.source_mode)}</span>
      <h3>${esc(p.name)}</h3><p>${esc([p.title,p.company].filter(Boolean).join(' · '))}</p>
      ${p.bio?`<p class="detail-bio">${esc(p.bio.slice(0,420))}</p>`:''}
      <div class="topic-pills">${p.topics.slice(0,5).map(t=>`<span>${esc(t)}</span>`).join('')}</div>
      ${path && path.path && path.path.length?`<h4>Connection path</h4><ol class="connection-path">${path.path.filter(x=>x.node).map(x=>`<li>${esc(x.node.label)}</li>`).join('')}</ol>`:'<p class="muted">No goal path recorded.</p>'}
      ${p.events.length?`<h4>Sessions</h4><ul class="connection-sessions">${p.events.slice(0,3).map(e=>`<li>${esc(e.title)}</li>`).join('')}</ul>`:''}
      ${sources.length?`<h4>Sources</h4>${sources.slice(0,3).map(s=>`<a class="connection-source-link" href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">${esc(s.provider)} ↗</a>`).join('')}`:''}</div>`;
  }
  async function focus(id) {
    const ticket=++request;selected=id;
    $('graph-detail').textContent='Loading profile…';
    personRows(shown);
    try {
      const [data,path]=await Promise.all([api(`connections?scope=${scope}&focus=${encodeURIComponent(id)}`),api(`graph/path?person=${encodeURIComponent(id)}`).catch(()=>null)]);
      if(ticket!==request)return;
      const p=data.items.find(x=>x.id===id);
      if(!p){$('graph-detail').textContent='This person is not in the selected list.';return;}
      draw(data.graph);details(p,path);
      if(cy)cy.getElementById(id).select();
    } catch(e){if(ticket===request)$('graph-detail').textContent=e.message;}
  }
  async function render() {
    const ticket=++request;
    try {
      const data=await api('connections?scope='+scope);
      if(ticket!==request)return;
      all=data.items;const visible=new Set(data.graph.nodes.filter(n=>n.type==='Person').map(n=>n.id));shown=[...all.filter(p=>visible.has(p.id)),...all.filter(p=>!visible.has(p.id))].slice(0,30);selected=null;
      $('connections-count').textContent=`${all.length} people in ${scope==='met'?'your recorded meetings':'the conference directory'}`;
      $('connection-ai-status').textContent=data.ai_configured?'AI search ready':'Keyword search · OpenAI not connected';
      $('connection-results-title').textContent='People';$('connection-clear').hidden=true;
      $('connection-summary').textContent=all.length>30?'Showing 30 people. Search the full list.':'';
      $('graph-detail').innerHTML='';personRows(shown);draw(data.graph);
    }catch(e){$('connection-summary').textContent=e.message;}
  }
  async function search(event) {
    if(event)event.preventDefault();
    const query=$('connection-query').value.trim();if(query.length<2||busy)return;
    const ticket=++request;busy=true;$('connection-submit').disabled=true;$('connection-submit').textContent='Searching…';
    $('connection-summary').textContent='Searching this list…';$('graph-detail').innerHTML='';
    try {
      const result=await api('connections/search',{query,scope});if(ticket!==request)return;
      shown=result.items;selected=null;personRows(shown);
      $('connection-results-title').textContent=`${shown.length} matches`;
      $('connection-summary').textContent=result.summary;$('connection-clear').hidden=false;
      $('connection-ai-status').textContent=result.mode==='semantic'?'OpenAI + FalkorDB vectors':result.mode==='keyword'?'Keyword search':'No matches';
      if(!shown.length)draw({nodes:[],edges:[],backend:'falkordb'});
      if(shown.length){const data=await api(`connections?scope=${scope}&focus=${encodeURIComponent(shown[0].id)}`);if(ticket===request)draw(data.graph);}
    }catch(e){if(ticket===request)$('connection-summary').textContent=e.message;}
    finally{busy=false;$('connection-submit').disabled=false;$('connection-submit').innerHTML='Find people <span aria-hidden="true">↗</span>';}
  }
  $('connection-search').addEventListener('submit',search);
  document.querySelectorAll('[data-connection-scope]').forEach(button=>button.addEventListener('click',()=>{
    scope=button.dataset.connectionScope;
    document.querySelectorAll('[data-connection-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    render();
  }));
  document.querySelectorAll('[data-connection-query]').forEach(button=>button.addEventListener('click',()=>{$('connection-query').value=button.dataset.connectionQuery;search();}));
  $('connection-results').addEventListener('click',e=>{const b=e.target.closest('[data-person]');if(b)focus(b.dataset.person);});
  $('connection-clear').addEventListener('click',()=>{$('connection-query').value='';render();});
  $('network-fit').addEventListener('click',fit);
  $('network-zoom-in').addEventListener('click',()=>{if(cy)cy.zoom(cy.zoom()*1.2);});
  $('network-zoom-out').addEventListener('click',()=>{if(cy)cy.zoom(cy.zoom()/1.2);});
  new ResizeObserver(fit).observe($('graph'));
  window.Connections={render,focus};
})();
