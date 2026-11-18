"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const format = (value, digits = 2) => Number(value).toLocaleString(undefined, {maximumFractionDigits: digits});
  const title = value => value.charAt(0).toUpperCase() + value.slice(1);
  const colors = {energy: "#2d6b55", transport: "#65917e", shopping: "#a58c57", food: "#87964d", water: "#568a9b", other: "#82718f"};
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const state = {data: null, custom: null, original: null, request: 0, layers: null, dark: false,
    view: "contour", surface: null, viewRequest: 0};
  const map = L.map("footprint-map", {scrollWheelZoom: false, zoomControl: true, preferCanvas: false}).setView([22.323,114.258],13);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, minZoom: 8, updateWhenIdle: true, keepBuffer: 1, crossOrigin: true,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.control.scale({imperial:false, maxWidth:100}).addTo(map);
  tiles.on("tileerror", () => {$("tile-status").hidden = false;});
  let surfaceRefresh = null;
  tiles.on("tileload", () => {
    $("tile-status").hidden = true;
    if(state.view==="3d"&&state.surface){clearTimeout(surfaceRefresh);surfaceRefresh=setTimeout(updateSurface,150);}
  });
  function set(id, value) { $(id).textContent = value; }
  function surfaceUnavailable() {
    setMapView("contour");$("surface-view-button").disabled=true;
    $("surface-status").hidden=false;
    set("surface-status","3D is unavailable on this device. The contour map remains available.");
  }
  function updateSurface() {
    if(state.view!=="3d"||!state.surface||!state.data)return;
    const result=state.surface.update(state.data,map,state.dark);
    $("surface-status").hidden=false;
    set("surface-status","Height = smoothed density (kg CO₂e/km²), exaggerated for clarity."+
      (result.streetTiles?"":" Street texture unavailable; activity locations and heights are still shown."));
  }
  async function setMapView(view) {
    const requestId=++state.viewRequest;state.view=view;
    $("footprint-map-wrap").dataset.view=view;
    $("footprint-surface").hidden=view!=="3d";$("surface-controls").hidden=view!=="3d";
    $("surface-status").hidden=true;
    $("contour-view-button").classList.toggle("selected",view==="contour");
    $("surface-view-button").classList.toggle("selected",view==="3d");
    $("contour-view-button").setAttribute("aria-pressed",String(view==="contour"));
    $("surface-view-button").setAttribute("aria-pressed",String(view==="3d"));
    map.getContainer().setAttribute("aria-hidden",String(view==="3d"));
    if(view==="contour"){if(state.surface)state.surface.setVisible(false);map.invalidateSize({animate:false});return;}
    $("surface-status").hidden=false;set("surface-status","Loading 3D landscape…");
    $("surface-view-button").disabled=true;
    let failed=false;
    try{
      if(!state.surface){const module=await import("./footprint-surface.js");if(requestId!==state.viewRequest)return;
        state.surface=module.createFootprintSurface($("surface-canvas"),$("surface-labels"),surfaceUnavailable);}
      if(requestId!==state.viewRequest)return;
      state.surface.setVisible(true);updateSurface();state.surface.reset();
    }catch(error){failed=true;surfaceUnavailable();}
    finally{$("surface-view-button").disabled=failed;}
  }
  function indexPreview() {
    const value=Number($("index-preview").value),angle=(value+1)*Math.PI/2;
    $("index-needle").setAttribute("x2",String(150-92*Math.cos(angle)));
    $("index-needle").setAttribute("y2",String(145-92*Math.sin(angle)));
    const text=(value>0?"+":"")+value.toFixed(2);
    set("index-number",text);set("gauge-score",text);
    $("green-index-gauge").setAttribute("aria-label","Synthetic green living index "+text+". Minus one left, zero up, plus one right.");
  }
  function boundsForActivities(rows) {return L.latLngBounds(rows.map(row => [row.lat,row.lon]));}
  function fit() {
    const rows = state.data && state.data.activities;
    if (rows && rows.length) map.fitBounds(boundsForActivities(rows).pad(.24), {maxZoom:14, animate:false, padding:[25,35]});
    updateSurface();if(state.view==="3d"&&state.surface)state.surface.reset();
  }
  function chooseCategory(name) {$("category-filter").value = name; refresh();}
  function treemap() {
    const host = $("footprint-treemap"); host.replaceChildren();
    const data = state.data;
    const leaves = data.categories.filter(row => row.co2e_kg > 0);
    if (!leaves.length) {host.textContent = "No positive emissions in this selection."; return;}
    const root = d3.hierarchy({children:leaves}).sum(row=>row.co2e_kg || 0).sort((a,b)=>b.value-a.value);
    d3.treemap().size([host.clientWidth,host.clientHeight]).paddingInner(0).round(false)(root);
    root.leaves().forEach(node=>{
      const row=node.data, width=node.x1-node.x0, height=node.y1-node.y0;
      const button=document.createElement("button");button.type="button";button.className="tree-tile";
      Object.assign(button.style,{left:node.x0+"px",top:node.y0+"px",width:width+"px",height:height+"px",background:colors[row.name]});
      const label=title(row.name)+", "+format(row.share*100,1)+"%, "+format(row.co2e_kg)+" kg CO₂e";
      button.setAttribute("aria-label",label);button.title=label;
      if(width>90 && height>58){const name=document.createElement("strong"),share=document.createElement("span");name.textContent=title(row.name);share.textContent=format(row.share*100,1)+"%";button.append(name,share);
        if(height>110){const amount=document.createElement("small");amount.textContent=format(row.co2e_kg)+" kg CO₂e";button.append(amount);}}
      button.addEventListener("click",()=>chooseCategory(row.name));host.append(button);
    });
  }
  function ramp(t) {
    const stops=[[0,[225,238,234]],[.2,[82,158,171]],[.4,[119,181,144]],[.6,[232,206,121]],[.8,[230,155,96]],[1,[216,92,80]]];
    const i=Math.min(4,Math.floor(Math.max(0,Math.min(1,t))*5));const f=(t-stops[i][0])/.2;
    return stops[i][1].map((v,j)=>Math.round(v+(stops[i+1][1][j]-v)*f));
  }
  function landscape() {
    if(state.layers) state.layers.remove();state.layers=L.layerGroup().addTo(map);
    const data=state.data, grid=data.grid;$("map-empty").hidden=Boolean(grid);
    set("density-max",grid?format(grid.max,1):"0");set("density-mid",grid?format(grid.max/2,1):"0");
    if(!grid)return;
    const canvas=document.createElement("canvas");canvas.width=canvas.height=grid.size;
    const context=canvas.getContext("2d"), pixels=context.createImageData(grid.size,grid.size);
    grid.values.forEach((value,i)=>{const t=value/grid.max, rgb=ramp(t);pixels.data.set([...rgb,Math.round(165*Math.min(1,t/.15)*Math.min(1,t*8))],i*4);});
    context.putImageData(pixels,0,0);L.imageOverlay(canvas.toDataURL(),grid.bounds,{opacity:1,interactive:false}).addTo(state.layers);
    const levels=[.03,.08,.16,.28,.42,.58,.76,.92].map(v=>v*grid.max);
    const contours=d3.contours().size([grid.size,grid.size]).thresholds(levels)(grid.values);
    const south=grid.bounds[0][0],west=grid.bounds[0][1],north=grid.bounds[1][0],east=grid.bounds[1][1];
    contours.forEach(contour=>{
      const geometry={type:"MultiPolygon",coordinates:contour.coordinates.map(polygon=>polygon.map(ring=>ring.map(([x,y])=>[west+x/grid.size*(east-west),north-y/grid.size*(north-south)])))};
      L.geoJSON(geometry,{interactive:false,style:{color:state.dark?"#f8f7dc":"#416d54",weight:.8,opacity:.22+contour.value/grid.max*.35,fill:false}}).addTo(state.layers);
    });
    const grouped=new Map();data.activities.forEach(row=>{const key=row.lat.toFixed(5)+","+row.lon.toFixed(5);if(!grouped.has(key))grouped.set(key,{lat:row.lat,lon:row.lon,total:0,rows:[]});const point=grouped.get(key);point.total+=row.co2e_kg;point.rows.push(row);});
    [...grouped.values()].forEach(point=>{
      const marker=L.circleMarker([point.lat,point.lon],{radius:5+Math.sqrt(point.total)*1.6,color:"#fff",weight:2,fillColor:"#315c46",fillOpacity:1}).addTo(state.layers);
      const details=document.createElement("div");point.rows.forEach(row=>{const line=document.createElement("div");line.textContent=row.name+" · "+format(row.co2e_kg)+" kg CO₂e";details.append(line);});marker.bindPopup(details);
      const named=point.rows.find(row=>/home energy|road commute|cafe/i.test(row.name));
      if(named || grouped.size<=3){const label=document.createElement("div");label.textContent=point.rows.length>1?"Home activities":point.rows[0].name;const amount=document.createElement("span");amount.textContent=format(point.total)+" kg CO₂e";label.append(amount);marker.bindTooltip(label,{permanent:true,direction:"top",offset:[0,-8],className:"peak-label"});}
    });
  }
  function render(data,fitMap) {
    state.data=data;set("footprint-total",format(data.total_kg));set("inside-total",format(data.inside_kg));set("outside-total",format(data.outside_kg));
    set("footprint-count",data.activities.length+" activities in this view");set("activity-count",data.activities.length+" activities");
    set("data-classification",data.classification==="example"?"EXAMPLE DAY":"CUSTOM PREVIEW");
    if(data.classification==="example")$("example-notice").replaceChildren(document.createTextNode("Synthetic Hong Kong activities, not your personal footprint. Real sensor readings remain separate."));
    else set("example-notice","Your preview inputs are shown below. Emission estimates are unverified and are not saved to the sensor database.");
    const key=$("category-key");key.replaceChildren();data.categories.forEach(row=>{const button=document.createElement("button");button.type="button";
      const dot=document.createElement("span");dot.className="category-dot";dot.style.background=colors[row.name];
      const name=document.createElement("span");name.textContent=title(row.name);const amount=document.createElement("span");amount.className="category-amount";amount.textContent=format(row.co2e_kg)+" kg";
      const share=document.createElement("span");share.className="category-share";share.textContent=format(row.share*100,1)+"%";button.append(dot,name,amount,share);button.addEventListener("click",()=>chooseCategory(row.name));key.append(button);});
    const body=$("activity-rows");body.replaceChildren();data.activities.forEach(row=>{const tr=document.createElement("tr");[row.name,row.scope,row.category,format(row.co2e_kg),format(data.total_kg?row.co2e_kg/data.total_kg*100:0,1)+"%"].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});body.append(tr);});
    if(!data.activities.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="empty-row";td.textContent="No activities match these filters.";tr.append(td);body.append(tr);}
    const leader=data.categories[0];const reflection=leader&&data.total_kg?title(leader.name)+" contributes "+format(leader.share*100,1)+"% of this selection.":"No positive emissions in this selection.";
    set("reflection-title",reflection);const suggestion=leader&&leader.name==="transport"?"Which journey could you review for a lower-emission travel option?":leader&&leader.name==="energy"?"Which home energy use could you understand better before changing it?":leader&&leader.name==="shopping"?"Which purchase could you reconsider, repair or use for longer?":"Which activity would you like to understand or change next?";
    set("reflection-copy",suggestion+" These are reflection questions, not measured savings.");set("prompt-title",reflection);set("prompt-body",suggestion);
    set("source-detail",data.provenance.source+". "+data.provenance.storage+".");set("method-detail",data.provenance.method+". Grid integral: "+format(data.grid?data.grid.integrated_kg:0,3)+" kg CO₂e; selected input total: "+format(data.total_kg,3)+" kg CO₂e.");set("limit-detail",data.provenance.limitations);
    treemap();landscape();if(fitMap)fit();else updateSurface();set("living-status",data.classification==="example"?"Synthetic preview · ready":"Custom preview · not saved");
  }
  async function refresh(fitMap=true) {
    const requestId=++state.request;set("living-status","Updating preview…");
    const filters={scope:$("scope-filter").value,category:$("category-filter").value,bandwidth_m:Number($("smoothing").value)};
    try {
      const response=await fetch(state.custom?"/api/v1/living/preview":"/api/v1/living/example?"+new URLSearchParams(filters),state.custom?{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({...filters,activities:state.custom})}:{credentials:"same-origin",cache:"no-store"});
      if(response.status===401){location.assign("/");return;}const data=await response.json();if(!response.ok)throw new Error(data.message||"Preview unavailable");if(requestId!==state.request)return;
      if(!state.original && data.classification==="example")state.original=data.activities;
      render(data,fitMap);$("living-error").hidden=true;
    } catch(error){if(requestId!==state.request)return;set("living-error",error.message);$("living-error").hidden=false;set("living-status","Preview unavailable");}
  }
  $("scope-filter").addEventListener("change",()=>refresh());$("category-filter").addEventListener("change",()=>refresh());$("smoothing").addEventListener("change",()=>refresh(false));
  $("clear-category").addEventListener("click",()=>chooseCategory("all"));$("fit-map").addEventListener("click",fit);
  $("theme-button").addEventListener("click",()=>{state.dark=!state.dark;document.querySelector(".living-app").classList.toggle("dark",state.dark);$("theme-button").setAttribute("aria-pressed",String(state.dark));set("theme-button",state.dark?"Light map":"Dark map");if(state.data){landscape();updateSurface();}});
  $("edit-data").addEventListener("click",()=>{const editor=$("data-editor");editor.hidden=!editor.hidden;$("edit-data").setAttribute("aria-expanded",String(!editor.hidden));if(!editor.hidden){$("activity-json").value=JSON.stringify(state.custom||state.original||[],null,2);$("activity-json").focus();}});
  $("apply-data").addEventListener("click",()=>{try{const rows=JSON.parse($("activity-json").value);if(!Array.isArray(rows))throw new Error("Use a JSON array of activities.");state.custom=rows;set("editor-status","Applying preview…");refresh().then(()=>set("editor-status",$("living-error").hidden?"Preview applied; not saved.":"Fix the inputs and apply again."));}catch(error){set("editor-status",error.message);}});
  $("reset-example").addEventListener("click",()=>{state.custom=null;$("scope-filter").value="all";$("category-filter").value="all";$("activity-json").value=JSON.stringify(state.original||[],null,2);set("editor-status","Example restored.");refresh();});
  $("export-living").addEventListener("click",()=>{if(!state.data)return;const blob=new Blob([JSON.stringify({...state.data,index_preview:{value:Number($("index-preview").value),classification:"synthetic_manual",definition:"Scoring model not defined; independent of activity data"}},null,2)],{type:"application/json"});const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="sensorlab-footprint-preview.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $("reflection-button").addEventListener("click",()=>$("reflection-dialog").showModal());["close-reflection","dismiss-reflection"].forEach(id=>$(id).addEventListener("click",()=>$("reflection-dialog").close()));
  $("contour-view-button").addEventListener("click",()=>setMapView("contour"));
  $("surface-view-button").addEventListener("click",()=>setMapView("3d"));
  $("reset-surface").addEventListener("click",()=>{if(state.surface)state.surface.reset();});
  $("rotate-surface-left").addEventListener("click",()=>{if(state.surface)state.surface.rotate(-Math.PI/8);});
  $("rotate-surface-right").addEventListener("click",()=>{if(state.surface)state.surface.rotate(Math.PI/8);});
  $("zoom-surface-in").addEventListener("click",()=>{if(state.surface)state.surface.zoom(.85);});
  $("zoom-surface-out").addEventListener("click",()=>{if(state.surface)state.surface.zoom(1.18);});
  new ResizeObserver(()=>{if(state.data)treemap();map.invalidateSize({animate:false});updateSurface();}).observe($("footprint-map"));
  $("index-preview").addEventListener("input",indexPreview);indexPreview();refresh();
}());
