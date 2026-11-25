const $ = sel => document.querySelector(sel);
const state = {origin:null, originLabel:'', markers:[], mapPlaces:[], map:null, pickingOrigin:false, routeOptions:[]};
const fallbackCenter = [88.437,22.578];
let toastTimer;
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),4600);}
function escapeHTML(value=''){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function api(path, options={}){
 const response=await fetch('/api/'+path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
 let data;try{data=await response.json();}catch{throw Error('Server returned an invalid response.');}
 if(!response.ok)throw Error(data.detail||data.error||`HTTP ${response.status}`);
 return data;
}
function busy(button,flag){if(!button)return;button.disabled=flag;if(flag){if(!button.dataset.original)button.dataset.original=button.innerHTML;button.textContent='Working…';}else if(button.dataset.original){button.innerHTML=button.dataset.original;delete button.dataset.original;}}
function setTab(name){document.querySelectorAll('.nav-link').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));document.querySelectorAll('.tabview').forEach(x=>x.classList.toggle('active',x.id==='tab-'+name));$('#crumb-active').textContent={explore:'Discover',nearby:'Nearby places',routes:'Directions',trips:'Trip planner'}[name];$('#result-area').innerHTML='';}
document.querySelectorAll('.nav-link').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));

function syncMapPlaces(items=[]){
 state.mapPlaces=(Array.isArray(items)?items:[]).slice(0,15).map((p,i)=>({
  index:i+1,
  name:p.name||'Unnamed place',
  address:p.address||'',
  category:p.category||p.categories||'',
  distance_m:p.distance_m??null,
  lat:Number.isFinite(Number(p.lat))?Number(p.lat):null,
  lon:Number.isFinite(Number(p.lon))?Number(p.lon):null
 }));
}

async function setOrigin(loc,label,resolveName=false){
 state.origin={lat:Number(loc.lat),lon:Number(loc.lon)};
 state.originLabel=label||'Selected location';
 state.mapPlaces=[];
 $('#location-label').textContent=state.originLabel;
 $('#route-origin-label').textContent=state.originLabel;
 $('#map-caption').textContent=`Exploring near ${state.originLabel}`;
 $('#loc-modal').hidden=true;
 $('#origin-choice-list').innerHTML='';
 state.pickingOrigin=false;
 if(state.map){state.map.getCanvas().style.cursor='';clearRoute();}
 showMarkers([{lat:state.origin.lat,lon:state.origin.lon,name:state.originLabel}],false);
 state.map?.flyTo({center:[state.origin.lon,state.origin.lat],zoom:14});
 toast(`Starting point: ${state.originLabel}`);

 if(resolveName){
  try{
   const rev=await api(`reverse?lat=${state.origin.lat}&lon=${state.origin.lon}`);
   if(rev.label){
    state.originLabel=rev.label;
    $('#location-label').textContent=rev.label;
    $('#route-origin-label').textContent=rev.label;
    $('#map-caption').textContent=`Exploring near ${rev.label}`;
   }
  }catch{}
 }
}

function openOrigin(){state.pickingOrigin=false;$('#loc-modal').hidden=false;$('#origin-choice-list').innerHTML='';setTimeout(()=>$('#origin-query').focus(),60);}
$('#locate-btn').addEventListener('click',openOrigin);$('#route-change-start').onclick=openOrigin;
$('#close-modal').onclick=()=>$('#loc-modal').hidden=true;
$('#loc-modal').onclick=e=>{if(e.target.id==='loc-modal')$('#loc-modal').hidden=true;};

function makeLocationChoices(target,arr,onPick){
 target.innerHTML='';
 const title=document.createElement('div');title.className='choices-heading';
 title.textContent=`${arr.length} possible location${arr.length===1?'':'s'} — choose the exact one:`;
 target.appendChild(title);
 arr.forEach((place,i)=>{
  const button=document.createElement('button');button.type='button';button.className='location-choice';
  const n=document.createElement('span');n.className='choice-number';n.textContent=String(i+1).padStart(2,'0');
  const t=document.createElement('span');t.className='choice-name';t.textContent=place.name;
  button.append(n,t);button.onclick=()=>onPick(place);target.appendChild(button);
 });
}

$('#origin-form').onsubmit=async e=>{
 e.preventDefault();const btn=e.submitter;busy(btn,true);
 try{
  const bias=state.origin?`&lat=${state.origin.lat}&lon=${state.origin.lon}`:'';
  const arr=(await api('geocode?q='+encodeURIComponent($('#origin-query').value.trim())+bias)).results;
  if(!arr.length)throw Error('No location found. Try a specific street or landmark.');
  if(arr.length===1){await setOrigin(arr[0],arr[0].name);return;}
  makeLocationChoices($('#origin-choice-list'),arr,selected=>setOrigin(selected,selected.name));
 }catch(err){toast(err.message);}finally{busy(btn,false);}
};

$('#pick-map-origin').onclick=()=>{
 if(!state.map){toast('Map is not ready. Please type a starting address.');return;}
 state.pickingOrigin=true;$('#loc-modal').hidden=true;
 state.map.getCanvas().style.cursor='crosshair';
 toast('Click a road on the map to choose your starting point.');
};

function locate(){
 if(!navigator.geolocation){toast('Your browser does not support location access. Use a place name instead.');return;}
 toast('Fetching GPS coordinates…');
 navigator.geolocation.getCurrentPosition(
  p=>setOrigin({lat:p.coords.latitude,lon:p.coords.longitude},'My current location',true),
  e=>toast('Location unavailable or permission denied. You can enter a place instead.'),
  {enableHighAccuracy:true,timeout:14000,maximumAge:30000}
 );
}
$('#modal-geolocate').onclick=locate;

function initMap(){
 if(typeof maplibregl==='undefined'){toast('Map library unavailable. Check your internet connection.');return;}
 try{
  state.map=new maplibregl.Map({container:'map',style:'https://tiles.openfreemap.org/styles/liberty',center:fallbackCenter,zoom:11,attributionControl:true});
  state.map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');
  state.map.on('click',e=>{
   if(!state.pickingOrigin)return;
   setOrigin({lat:e.lngLat.lat,lon:e.lngLat.lng},`Map pin (${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)})`,true);
  });
  state.map.on('error',()=>{});
 }catch(e){toast('Map could not start: '+e.message);}
}

function clearRoute(){if(!state.map)return;if(state.map.getLayer('wayfinder-route'))state.map.removeLayer('wayfinder-route');if(state.map.getSource('wayfinder-route'))state.map.removeSource('wayfinder-route');}

function showMarkers(items,fit=true){
 if(!state.map)return;
 state.markers.forEach(m=>m.remove());
 state.markers=[];
 const bounds=new maplibregl.LngLatBounds();
 items.filter(p=>Number.isFinite(Number(p.lat))&&Number.isFinite(Number(p.lon))).forEach((p,i)=>{
  const element=document.createElement('div');
  const isOrigin=state.origin && i===0 && items.length>1;
  element.style.cssText=isOrigin
   ?'width:16px;height:16px;border:3px solid #0b0e13;border-radius:50%;background:#60a5fa;box-shadow:0 0 0 4px #60a5fa44,0 3px 12px #000a;cursor:pointer'
   :'width:15px;height:15px;border:3px solid #11241a;border-radius:50%;background:#c0ffbd;box-shadow:0 0 0 4px #c0ffbd44,0 3px 12px #000a;cursor:pointer';
  const marker=new maplibregl.Marker({element}).setLngLat([p.lon,p.lat]).setPopup(new maplibregl.Popup({offset:14}).setHTML(`<strong>${escapeHTML(p.name)}</strong>${p.address?'<br>'+escapeHTML(p.address):''}`)).addTo(state.map);
  state.markers.push(marker);
  bounds.extend([p.lon,p.lat]);
 });
 if(fit&&items.length>0){
  if(items.length===1)state.map.flyTo({center:[items[0].lon,items[0].lat],zoom:14});
  else state.map.fitBounds(bounds,{padding:65,maxZoom:14,duration:850});
 }
}

function displayRoute(data,start,end){
 if(!state.map)return;
 const fn=()=>{
  clearRoute();
  const geometry=data.geometry;
  if(geometry&&geometry.coordinates){
   state.map.addSource('wayfinder-route',{type:'geojson',data:{type:'Feature',properties:{},geometry}});
   state.map.addLayer({id:'wayfinder-route',type:'line',source:'wayfinder-route',paint:{'line-color':'#b9f2ba','line-width':5,'line-opacity':.92}});
  }
  showMarkers([{...start,name:state.originLabel||'Start'},{...end,name:end.name||'Destination'}]);
 };
 if(state.map.isStyleLoaded())fn();else state.map.once('load',fn);
}

function renderPlaces(items,heading='Nearby places'){
 syncMapPlaces(items);
 const holder=$('#result-area');
 if(!items.length){
  holder.innerHTML='<div class="empty">No mapped places found in this search radius. Try a broader category or increase the search radius.</div>';
  return;
 }
 holder.innerHTML=`<div class="result-head"><h3>${escapeHTML(heading)}</h3><span>${items.length} mapped places</span></div>`+
  items.map((p,i)=>`<div class="place-card" data-index="${i}" tabindex="0" role="button">
   <div class="number">${String(i+1).padStart(2,'0')}</div>
   <div class="place-data"><strong>${escapeHTML(p.name)}</strong><small>${escapeHTML(p.address||'No address available')}</small></div>
   <div class="place-distance">${p.distance_m>=1000?(p.distance_m/1000).toFixed(1)+' km':p.distance_m+' m'}</div>
   <button type="button" class="route-here-btn" data-route-index="${i}" title="Get directions here">Route ↗</button>
  </div>`).join('');

 holder.querySelectorAll('.place-card').forEach(row=>{
  const idx=Number(row.dataset.index);
  const p=items[idx];
  const pick=()=>{
   state.map?.flyTo({center:[p.lon,p.lat],zoom:15});
   state.markers[idx+(state.origin?1:0)]?.togglePopup();
  };
  row.onclick=e=>{
   if(e.target.closest('.route-here-btn'))return;
   pick();
  };
  row.onkeydown=e=>{if(e.key==='Enter')pick();};
 });

 holder.querySelectorAll('.route-here-btn').forEach(btn=>{
  btn.onclick=async e=>{
   e.stopPropagation();
   const p=items[Number(btn.dataset.routeIndex)];
   if(!state.origin){openOrigin();toast('Set a starting point first.');return;}
   setTab('routes');
   $('#route-destination').value=p.name;
   await calculateRoute(p);
  };
 });

 showMarkers(state.origin?[{...state.origin,name:state.originLabel},...items]:items);
}

async function doNearby(category, radius=5000){
 if(!state.origin){openOrigin();throw Error('Choose a starting point first.');}
 const results=(await api('places',{method:'POST',body:JSON.stringify({...state.origin,category,keyword:category,radius})})).results;
 renderPlaces(results,`${category.charAt(0).toUpperCase()+category.slice(1)} near you`);
}

$('#nearby-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;busy(b,true);try{await doNearby($('#place-type').value,Number($('#place-radius').value));}catch(err){toast(err.message);}finally{busy(b,false);}};

function renderRoute(route,destination){
 const km=(route.distance_m/1000).toFixed(1),mins=Math.max(1,Math.round(route.duration_s/60));
 $('#result-area').innerHTML=`<div class="result-head"><h3>Suggested route</h3><span>${escapeHTML(route.mode)}</span></div><div class="route-card"><div class="route-metrics"><div class="metric"><strong>${km} km</strong><span>ROUTE DISTANCE</span></div><div class="metric"><strong>${mins} min</strong><span>ESTIMATED TIME</span></div></div><div class="route-note">From: ${escapeHTML(state.originLabel)}<br>To: ${escapeHTML(destination.name)}.<br>Times are estimates without live traffic.</div>${route.steps?.length?'<ol class="steps">'+route.steps.slice(0,10).map(t=>'<li>'+escapeHTML(t)+'</li>').join('')+'</ol>':''}</div>`;
 displayRoute(route,state.origin,destination);$('#map-caption').textContent=`${km} km • approximately ${mins} min`;
}

function showRouteOptions(locations){
 state.routeOptions=locations;
 const holder=$('#result-area');holder.innerHTML='';
 const head=document.createElement('div');head.className='result-head';
 head.innerHTML='<h3>Choose your destination</h3><span>Geocoding matches</span>';holder.appendChild(head);
 const msg=document.createElement('p');msg.className='result-helper';
 msg.textContent='The destination name matches multiple places. Pick the correct location before calculating the route.';
 holder.appendChild(msg);
 const list=document.createElement('div');list.className='location-choices';holder.appendChild(list);
 makeLocationChoices(list,locations,selected=>calculateRoute(selected));
}

function showRouteFailure(err,destination){
 clearRoute();showMarkers([{...state.origin,name:state.originLabel||'Starting point'},destination]);
 const holder=$('#result-area');holder.innerHTML='';
 const panel=document.createElement('div');panel.className='route-error';
 const h=document.createElement('h3');h.textContent='Route could not be connected';
 const p=document.createElement('p');p.textContent=err.message;
 const origin=document.createElement('p');origin.className='route-error-locations';
 origin.textContent=`From: ${state.originLabel} • To: ${destination.name}`;
 const buttons=document.createElement('div');buttons.className='route-error-actions';
 const change=document.createElement('button');change.textContent='Change starting point';change.className='outline-btn';change.onclick=openOrigin;
 const alternatives=document.createElement('button');alternatives.textContent='Try another destination';alternatives.className='outline-btn';
 alternatives.onclick=()=>{if(state.routeOptions.length>1)showRouteOptions(state.routeOptions);else $('#route-destination').focus();};
 buttons.append(change,alternatives);panel.append(h,p,origin,buttons);holder.appendChild(panel);
 $('#map-caption').textContent='Route unavailable — verify both map markers';
}

async function calculateRoute(destination){
 const btn=$('#route-form button[type="submit"]');busy(btn,true);
 try{
  const route=await api('route',{method:'POST',body:JSON.stringify({start:state.origin,end:{lat:destination.lat,lon:destination.lon},mode:$('#route-mode').value})});
  renderRoute(route,destination);
 }catch(err){showRouteFailure(err,destination);}finally{busy(btn,false);}
}

$('#route-form').onsubmit=async e=>{
 e.preventDefault();const b=e.submitter;busy(b,true);
 try{
  if(!state.origin){openOrigin();throw Error('Choose your starting point first.');}
  const bias=`&lat=${state.origin.lat}&lon=${state.origin.lon}`;
  const options=(await api('geocode?q='+encodeURIComponent($('#route-destination').value.trim())+bias)).results;
  if(!options.length)throw Error('Destination not found. Add a street name or the neighborhood.');
  state.routeOptions=options;
  if(options.length>1){showRouteOptions(options);return;}
  await calculateRoute(options[0]);
 }catch(err){toast(err.message);}finally{busy(b,false);}
};

function renderTrip(trip){
 const days=Array.isArray(trip.days)?trip.days:[];
 const isMapped=trip.source==='mapped';
 const note=isMapped?'Gemini is unavailable. This is a map-based outline using real mapped places, not an optimized AI itinerary. For large regions, use a city name.':'AI-written draft. Place details, distances and costs are not independently verified.';
 $('#result-area').innerHTML=`<div class="result-head"><h3>${escapeHTML(trip.title||'Your itinerary')}</h3><span>${days.length} days</span></div><div class="trip-source-banner ${isMapped?'warn':''}">${escapeHTML(note)}</div><div class="trip-overview">${escapeHTML(trip.overview||'')}</div>`+days.map((d,i)=>`<div class="trip-day"><h4>DAY ${d.day||i+1} · ${escapeHTML(d.title||'Explore')}</h4>${d.stops?.length?'<ul>'+d.stops.map(s=>`<li><strong>${escapeHTML(s.name)}</strong> — ${escapeHTML(s.description)}</li>`).join('')+'</ul>':'<p class="result-helper">No verified mapped stops for this day. Add destinations manually.</p>'}</div>`).join('')+`<div class="budget-note">${escapeHTML(trip.budget_note||'Estimated costs and hours should be independently verified.')}</div>`;
 if(isMapped&&trip.places?.length){syncMapPlaces(trip.places);showMarkers(trip.places);$('#map-caption').textContent=`${trip.places.length} mapped suggestions near ${trip.center?.name||'your destination'}`;}
}

$('#trip-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;busy(b,true);try{const data=await api('trip',{method:'POST',body:JSON.stringify({destination:$('#trip-destination').value,days:+$('#trip-days').value,travelers:+$('#trip-travelers').value,budget:+$('#trip-budget').value,interests:$('#trip-interests').value})});renderTrip(data);}catch(err){toast(err.message);}finally{busy(b,false);}};

function message(role,text){const el=document.createElement('div');el.className='message '+role;el.textContent=text;$('#chat-log').appendChild(el);$('#chat-log').scrollTop=$('#chat-log').scrollHeight;}

async function sendPrompt(text){
 message('user',text);$('#chat-input').value='';
 const button=$('#chat-form button');busy(button,true);
 try{
  const data=await api('chat',{method:'POST',body:JSON.stringify({message:text,origin:state.origin,origin_label:state.originLabel})});
  message('assistant',data.text||'Done.');
  if(data.kind==='places'){
   if(data.center&&(!state.origin)){
    state.origin=data.center;
    state.originLabel='Requested area';
    $('#location-label').textContent='Requested area';
   }
   renderPlaces(data.results||[],'Recommended nearby');
  }
  if(data.kind==='route'){if(!state.origin)state.origin={lat:0,lon:0};renderRoute(data.route,data.destination);}
  if(data.kind==='trip')renderTrip(data.trip);
  if(data.ai_available===false)updateAIStatus(false,data.ai_error||'Gemini generation unavailable; map tools still work.');
  else if(data.ai_available===true)updateAIStatus(true,'Gemini is responding.');
 }catch(err){message('assistant','I couldn’t complete that request: '+err.message);toast(err.message);}finally{busy(button,false);}
}

if($('#chat-form')){$('#chat-form').onsubmit=e=>{e.preventDefault();const text=($('#chat-input')?.value||'').trim();if(text)sendPrompt(text);};}
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>sendPrompt(b.dataset.prompt));
$('#reset-map').onclick=()=>{clearRoute();state.mapPlaces=[];showMarkers([],false);state.map?.flyTo({center:state.origin?[state.origin.lon,state.origin.lat]:fallbackCenter,zoom:11});};

// ---------- Dedicated AI assistant bubble ----------
const assistantHistory=[];
let aiBusy=false;
function updateAIStatus(available,detail='',model=''){
 const badge=$('#ai-indicator'), conn=$('#assistant-connection');
 badge.dataset.state=available?'ok':'bad';
 $('#connection-state').textContent=available?'AI connected':'AI unavailable';
 $('#assistant-connection-text').textContent=detail || (available?'Gemini connected.':'Gemini is unavailable.');
 $('#assistant-model').textContent=model?`Gemini · ${model}`:(available?'Gemini online':'Gemini connection needs attention');
 conn.classList.toggle('error',!available);
 badge.title=detail||'Open AI assistant';
}
async function checkAI(){
 $('#ai-indicator').dataset.state='working';
 $('#connection-state').textContent='Testing Gemini…';
 $('#assistant-connection-text').textContent='Checking model and generating a short test reply…';
 const b=$('#assistant-retry');busy(b,true);
 try{
  const data=await api('ai/status?probe=true');
  updateAIStatus(!!data.available,data.detail||'No details supplied',data.model||'');
  if(!data.available && [429,503].includes(data.status_code)){
   $('#connection-state').textContent='Gemini temporarily busy';
  }
 }catch(err){updateAIStatus(false,'Connection check failed: '+err.message);}
 finally{busy(b,false);}
}
function openAI(open){
 $('#assistant-drawer').hidden=!open;
 $('#assistant-fab').setAttribute('aria-expanded',String(open));
 $('#assistant-fab').setAttribute('aria-label',open?'Close AI chat':'Open AI chat');
 $('#assistant-fab .fab-label').textContent=open?'Close AI':'Ask AI';
 if(open){setTimeout(()=>$('#assistant-input').focus(),80);$('#assistant-log').scrollTop=$('#assistant-log').scrollHeight;}
}
$('#assistant-fab').onclick=()=>openAI($('#assistant-drawer').hidden);
$('#assistant-close').onclick=()=>openAI(false);
$('#ai-indicator').onclick=()=>openAI(true);
$('#assistant-retry').onclick=checkAI;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#assistant-drawer').hidden)openAI(false);});
function aiMessage(role,text,sources=[]){
 const box=document.createElement('div');box.className='assistant-msg '+(role==='user'?'me':'bot');
 const content=document.createElement('span');content.textContent=text;
 box.appendChild(content);
 if(role!=='user'&&Array.isArray(sources)&&sources.length){
  const cite=document.createElement('div');
  cite.className='assistant-sources';
  sources.slice(0,3).forEach((s,idx)=>{
   if(!s?.url)return;
   if(idx>0)cite.append(' · ');
   const a=document.createElement('a');
   a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';
   a.textContent=s.title||s.url;
   cite.appendChild(a);
  });
  if(cite.childNodes.length)box.appendChild(cite);
 }
 $('#assistant-log').appendChild(box);
 $('#assistant-log').scrollTop=$('#assistant-log').scrollHeight;
 return content;
}
async function askAI(text){
 if(!text||aiBusy)return;
 const history=assistantHistory.slice(-10);
 aiMessage('user',text);
 assistantHistory.push({role:'user',content:text});
 $('#assistant-input').value='';
 const btn=$('#assistant-form button');aiBusy=true;busy(btn,true);
 const pending=aiMessage('assistant','Thinking…');
 try{
  const out=await api('assistant',{method:'POST',body:JSON.stringify({message:text,history,origin:state.origin,origin_label:state.originLabel,map_places:state.mapPlaces})});
  pending.textContent=out.text;
  if(Array.isArray(out.sources)&&out.sources.length){
   const cite=document.createElement('div');
   cite.className='assistant-sources';
   out.sources.slice(0,3).forEach((s,idx)=>{
    if(!s?.url)return;
    if(idx>0)cite.append(' · ');
    const a=document.createElement('a');
    a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';
    a.textContent=s.title||s.url;
    cite.appendChild(a);
   });
   if(cite.childNodes.length)pending.parentElement?.appendChild(cite);
  }
  assistantHistory.push({role:'assistant',content:out.text});
  if(out.places&&out.places.length){
   renderPlaces(out.places,'Mapped results from Ask AI');
  }
  updateAIStatus(true,'Gemini connected and responding.',out.model||'');
 }catch(err){
  const temporary=/high demand|overload|rate.limit|temporar|cooldown|HTTP 503|HTTP 429/i.test(err.message);
  pending.textContent=temporary
   ? `Gemini is temporarily busy. The app tried alternative models but none responded.\n\n${err.message}\n\nYour Geoapify map search, routes and basic trip planner can still work.`
   : `Gemini could not answer: ${err.message}\n\nCheck your Gemini key and model access in AI Studio. Nearby search, directions and map-based trip drafts can still work.`;
  updateAIStatus(false,err.message);
 }finally{aiBusy=false;busy(btn,false);$('#assistant-log').scrollTop=$('#assistant-log').scrollHeight;}
}
$('#assistant-form').onsubmit=e=>{e.preventDefault();askAI($('#assistant-input').value.trim());};
document.querySelectorAll('[data-ai-prompt]').forEach(btn=>btn.onclick=()=>askAI(btn.dataset.aiPrompt));
initMap();
api('health').then(d=>{
 if(!d.geoapify_configured)toast('Add a Geoapify key in .env to use map search and directions.');
 if(!d.gemini_configured){updateAIStatus(false,'GEMINI_API_KEY is missing in .env. Add your key and restart the launcher.');}
 else checkAI();
}).catch(()=>updateAIStatus(false,'Server unavailable. Start the Python launcher.'));