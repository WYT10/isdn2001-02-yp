"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const format = (value, digits = 2) => Number(value).toLocaleString(undefined, {maximumFractionDigits: digits});
  const title = value => value.charAt(0).toUpperCase() + value.slice(1);
  const colors = {energy: "#24634f", transport: "#65917e", shopping: "#a58c57", food: "#87964d", water: "#587f91", other: "#6d8b98"};
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const state = {data: null, activityData: null, request: 0, layers: null, dark: false,
    view: "contour", surface: null, viewRequest: 0};
  const map = L.map("footprint-map", {scrollWheelZoom: false, zoomControl: true, preferCanvas: false, zoomSnap:.5}).setView([22.317,114.17],15);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, minZoom: 8, updateWhenIdle: true, keepBuffer: 1, crossOrigin: true, detectRetina: true,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.control.scale({imperial:false, maxWidth:100}).addTo(map);
  tiles.on("tileerror", () => {$("tile-status").hidden = false;});
  let surfaceRefresh = null, initialViewSet = false;
  function defaultMapView(){if(!initialViewSet&&state.data&&document.querySelector(".living-app").dataset.activeTab==="overall"){initialViewSet=true;setMapView("3d");}}
  tiles.on("tileload", () => {
    $("tile-status").hidden = true;
    if(state.view==="3d"&&state.surface){clearTimeout(surfaceRefresh);surfaceRefresh=setTimeout(updateSurface,150);}
  });
  function set(id, value) { $(id).textContent = value; }
  function surfaceUnavailable() {
    setMapView("contour");$("surface-view-button").disabled=true;
    $("surface-status").hidden=false;
    $("surface-status").dataset.warning="true";
    set("surface-status","3D is unavailable on this device. The contour map remains available.");
  }
  function updateSurface() {
    if(state.view!=="3d"||!state.surface||!state.data)return;
    const result=state.surface.update(state.data,map,state.dark);
    $("surface-status").hidden=false;
    $("surface-status").dataset.warning=String(!result.streetTiles);
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
    $("surface-status").dataset.warning="true";
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
  function indexPreview(index) {
    const value=index.value,angle=((value||0)+1)*Math.PI/2;
    $("index-needle").setAttribute("x2",String(150-92*Math.cos(angle)));
    $("index-needle").setAttribute("y2",String(145-92*Math.sin(angle)));
    $("index-needle").style.visibility=value===null?"hidden":"visible";
    const text=value===null?"No score":(value>0?"+":"")+value.toFixed(2);
    set("gauge-score",text);
    set("green-index-value",text);
    $("green-index-gauge").setAttribute("aria-label","Synthetic green index "+text+". Minus one left, zero up, plus one right.");
  }
  function boundsForActivities(rows) {return L.latLngBounds(rows.map(row => [row.lat,row.lon]));}
  function fit() {
    const rows = state.data && state.data.activities;
    if (rows && rows.length) map.fitBounds(boundsForActivities(rows).pad(.02), {maxZoom:16, animate:false, padding:[18,18]});
    map.getContainer().dataset.zoom=String(map.getZoom());
    updateSurface();if(state.view==="3d"&&state.surface)state.surface.reset();
  }
  async function chooseCategory(name) {$("category-filter").value = name;await refresh();(name==="all"?$("footprint-treemap"):$("clear-category")).focus({preventScroll:true});}
  function treemap() {
    const host = $("footprint-treemap"); host.replaceChildren();
    const data = state.data;
    if(!host.clientWidth||!host.clientHeight)return;
    const categories=data.categories.filter(row=>row.co2e_kg>0).map(category=>({name:category.name,children:window.SensorActivities.records().filter(row=>row.category===category.name&&row.co2e_kg>0)}));
    host.tabIndex=-1;
    if(!categories.length){host.textContent="No positive emissions in this selection.";return;}
    const root=d3.hierarchy({children:categories}).sum(row=>row.children?0:row.co2e_kg||0).sort((a,b)=>b.value-a.value);
    function tile(node,x0,y0,x1,y1){
      const named=new Map((node.children||[]).map(child=>[child.data.name,child]));
      if(node.depth!==0||named.size!==5||!["shopping","food","energy","transport","other"].every(name=>named.has(name)))return d3.treemapBinary(node,x0,y0,x1,y1);
      const shopping=named.get("shopping"),food=named.get("food"),energy=named.get("energy"),transport=named.get("transport"),other=named.get("other");
      const left=shopping.value+food.value,right=energy.value+transport.value+other.value;
      const split=x0+(x1-x0)*left/node.value,lower=y0+(y1-y0)*shopping.value/left;
      const base=y0+(y1-y0)*energy.value/right,small=split+(x1-split)*transport.value/(transport.value+other.value);
      [[shopping,x0,y0,split,lower],[food,x0,lower,split,y1],[energy,split,y0,x1,base],[transport,split,base,small,y1],[other,small,base,x1,y1]].forEach(([child,a,b,c,d])=>Object.assign(child,{x0:a,y0:b,x1:c,y1:d}));
    }
    d3.treemap().tile(tile).size([host.clientWidth,host.clientHeight]).padding(0).round(false)(root);
    host.dataset.total=String(root.value);host.dataset.leaves=String(root.leaves().length);
    root.children.forEach(category=>{
      const width=category.x1-category.x0,height=category.y1-category.y0,group=document.createElement("div");group.className="tree-group";group.dataset.category=category.data.name;group.setAttribute("role","group");group.setAttribute("aria-label",title(category.data.name));
      Object.assign(group.style,{left:category.x0+"px",top:category.y0+"px",width:width+"px",height:height+"px",background:colors[category.data.name]});
      category.children.forEach((node,index)=>{
        const row=node.data,w=node.x1-node.x0,h=node.y1-node.y0,button=document.createElement("button");button.type="button";button.className="tree-tile";button.dataset.recordId=row.id;button.dataset.value=String(row.co2e_kg);
        Object.assign(button.style,{left:(node.x0-category.x0)+"px",top:(node.y0-category.y0)+"px",width:w+"px",height:h+"px",background:d3.interpolateRgb(colors[row.category],"#fff")((index%3)*.035)});
        const label=row.name+", "+row.date+", "+format(row.co2e_kg)+" kg CO₂e. Open activity";button.setAttribute("aria-label",label);button.title=label;
        const itemName=row.tree_label||row.name;
        if(w>44&&h>25){const name=document.createElement("strong");name.textContent=itemName;name.style.fontSize=(w>130&&h>100?13:w>75?11:9)+"px";button.append(name);}
        button.addEventListener("click",()=>window.SensorActivities.openRecord(row.id));group.append(button);
      });
      const largest=category.children[0],w=largest.x1-largest.x0,h=largest.y1-largest.y0;
      if(w>44&&h>48){
        const header=document.createElement("button");header.type="button";header.className="tree-category";header.dataset.category=category.data.name;
        const compact=w<135||h<110,share=format(category.value/root.value*100,1)+"%",label=title(category.data.name)+", "+share+", "+format(category.value)+" kg CO₂e. Filter category";
        header.title=label;header.setAttribute("aria-label",label);
        Object.assign(header.style,{left:(largest.x0-category.x0)+"px",top:(largest.y0-category.y0)+"px",width:w+"px",height:Math.max(30,h-25)+"px",fontSize:(w<75?11:compact?15:22)+"px"});
        const name=document.createElement("strong");name.textContent=title(category.data.name);header.append(name);
        if(w>60&&h>70){const percent=document.createElement("span");percent.textContent=share;percent.style.fontSize=(compact?22:36)+"px";header.append(percent);}
        header.addEventListener("click",()=>chooseCategory(category.data.name));group.append(header);
      }
      host.append(group);
    });
    set("treemap-selection",(data.category==="all"?"All categories":title(data.category))+", "+root.leaves().length+" activities with known estimates. Category names filter; item labels open their records.");
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
    if(!grid){map.getContainer().dataset.locations="0";return;}
    const canvas=document.createElement("canvas");canvas.width=canvas.height=grid.size;
    const context=canvas.getContext("2d"), pixels=context.createImageData(grid.size,grid.size);
    grid.values.forEach((value,i)=>{const t=value/grid.max, rgb=ramp(t);pixels.data.set([...rgb,Math.round(165*Math.min(1,t/.15)*Math.min(1,t*8))],i*4);});
    context.putImageData(pixels,0,0);L.imageOverlay(canvas.toDataURL(),grid.bounds,{opacity:1,interactive:false}).addTo(state.layers);
    const levels=[.07,.12,.2,.32,.46,.62,.78,.93].map(v=>v*grid.max);
    const contours=d3.contours().size([grid.size,grid.size]).thresholds(levels)(grid.values);
    const south=grid.bounds[0][0],west=grid.bounds[0][1],north=grid.bounds[1][0],east=grid.bounds[1][1];
    contours.forEach(contour=>{
      const geometry={type:"MultiPolygon",coordinates:contour.coordinates.map(polygon=>polygon.map(ring=>ring.map(([x,y])=>[west+x/grid.size*(east-west),north-y/grid.size*(north-south)])))};
      L.geoJSON(geometry,{interactive:false,style:{color:state.dark?"#f8f7dc":"#416d54",weight:.8,opacity:.22+contour.value/grid.max*.35,fill:false}}).addTo(state.layers);
    });
    const grouped=new Map();data.activities.forEach(row=>{const key=row.lat.toFixed(5)+","+row.lon.toFixed(5);if(!grouped.has(key))grouped.set(key,{lat:row.lat,lon:row.lon,total:0,rows:[]});const point=grouped.get(key);point.total+=row.co2e_kg;point.rows.push(row);});
    const ranked=[...grouped.values()].sort((a,b)=>b.total-a.total);
    map.getContainer().dataset.locations=String(ranked.length);
    ranked.forEach((point,index)=>{
      const marker=L.circleMarker([point.lat,point.lon],{radius:5+Math.sqrt(point.total)*1.6,color:"#fff",weight:2,fillColor:"#315c46",fillOpacity:1}).addTo(state.layers);
      const details=document.createElement("div");point.rows.forEach(row=>{const line=document.createElement("div");line.textContent=row.name+" · "+format(row.co2e_kg)+" kg CO₂e";details.append(line);
        const record=window.SensorActivities.records().find(item=>item.name===row.name&&item.lat===row.lat&&item.lon===row.lon&&item.co2e_kg===row.co2e_kg);
        if(record){const open=document.createElement("button");open.type="button";open.className="text-button";open.textContent="Open activity record →";open.addEventListener("click",()=>window.SensorActivities.openRecord(record.id));details.append(open);}
      });marker.bindPopup(details);
      const label=document.createElement("div");label.textContent=point.rows.length>1?(point.rows.every(row=>row.scope==="inside")?"Home activities":"Activities here"):point.rows[0].name;const amount=document.createElement("span");amount.textContent=format(point.total)+" kg CO₂e";label.append(amount);marker.bindTooltip(label,{permanent:index<2,direction:index===0?"right":index===1?"left":"top",offset:index<2?[index===0?8:-8,0]:[0,-8],className:"peak-label"});
    });
  }
  function render(data,fitMap) {
    state.data=data;set("footprint-total",format(data.total_kg));set("inside-total",format(data.inside_kg));set("outside-total",format(data.outside_kg));
    $("clear-category").hidden=data.category==="all";$("open-category-records").hidden=data.category==="all";
    set("footprint-count",data.activities.length+" activities in this view");set("activity-count",data.activities.length+" activities");
    set("data-classification","DEMO ACTIVITIES");
    const key=$("category-key");key.replaceChildren();data.categories.forEach(row=>{const button=document.createElement("button");button.type="button";
      const dot=document.createElement("span");dot.className="category-dot";dot.style.background=colors[row.name];
      const name=document.createElement("span");name.textContent=title(row.name);const amount=document.createElement("span");amount.className="category-amount";amount.textContent=format(row.co2e_kg)+" kg";
      const share=document.createElement("span");share.className="category-share";share.textContent=format(row.share*100,1)+"%";button.append(dot,name,amount,share);button.addEventListener("click",()=>chooseCategory(row.name));key.append(button);});
    const records=window.SensorActivities.records().filter(row=>data.category==="all"||row.category===data.category);
    set("activity-count",records.length+" records, including unknown estimates");
    const body=$("activity-rows");body.replaceChildren();records.forEach(row=>{const tr=document.createElement("tr");
      const quantity=row.kind==="water"?format(row.litres)+" L":row.kind==="electricity"?format(row.kwh)+" kWh":row.quantity||"Unknown";
      [row.name,row.owner+" / "+row.scope,row.category,quantity,row.co2e_kg===null?"Unknown":format(row.co2e_kg),row.co2e_kg===null?"Unknown":format(data.total_kg?row.co2e_kg/data.total_kg*100:0,1)+"%"].forEach((value,index)=>{const td=document.createElement("td");td.textContent=value;if(index===0){const open=document.createElement("button");open.type="button";open.className="text-button";open.textContent=value;open.addEventListener("click",()=>window.SensorActivities.openRecord(row.id));td.replaceChildren(open);}tr.append(td);});body.append(tr);});
    if(!records.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.className="empty-row";td.textContent="No activities match these filters.";tr.append(td);body.append(tr);}
    const leader=data.categories[0];const reflection=leader&&data.total_kg?title(leader.name)+" contributes "+format(leader.share*100,1)+"% of this selection.":"No positive emissions in this selection.";
    set("reflection-title",reflection);const suggestion=leader&&leader.name==="transport"?"Which journey could you review for a lower-emission travel option?":leader&&leader.name==="energy"?"Which home energy use could you understand better before changing it?":leader&&leader.name==="shopping"?"Which purchase could you reconsider, repair or use for longer?":"Which activity would you like to understand or change next?";
    set("reflection-copy",suggestion+" These are reflection questions, not measured savings.");set("prompt-title",reflection);set("prompt-body",suggestion);
    set("source-detail",data.provenance.source+". "+data.provenance.storage+".");set("method-detail",data.provenance.method+". Grid integral: "+format(data.grid?data.grid.integrated_kg:0,3)+" kg CO₂e; selected input total: "+format(data.total_kg,3)+" kg CO₂e.");set("limit-detail",data.provenance.limitations);
    treemap();landscape();if(fitMap)fit();else updateSurface();set("living-status","Synthetic activities · ready");
  }
  async function refresh(fitMap=true) {
    const requestId=++state.request;set("living-status","Updating preview…");
    const filters={scope:$("scope-filter").value,category:$("category-filter").value,bandwidth_m:Number($("smoothing").value)};
    try {
      const result=await window.SensorActivities.refresh(filters);if(!result||requestId!==state.request)return;
      state.activityData=result;indexPreview(result.green_index);const data=result.footprint;
      render(data,fitMap);defaultMapView();$("living-error").hidden=true;
    } catch(error){if(requestId!==state.request)return;set("living-error",error.message);$("living-error").hidden=false;set("living-status","Preview unavailable");}
  }
  $("scope-filter").addEventListener("change",()=>refresh());$("category-filter").addEventListener("change",()=>refresh());$("smoothing").addEventListener("change",()=>refresh(false));
  $("clear-category").addEventListener("click",()=>chooseCategory("all"));$("fit-map").addEventListener("click",fit);
  $("theme-button").addEventListener("click",()=>{state.dark=!state.dark;document.querySelector(".living-app").classList.toggle("dark",state.dark);$("theme-button").setAttribute("aria-pressed",String(state.dark));set("theme-button",state.dark?"Light map":"Dark map");if(state.data){landscape();updateSurface();}});
  $("export-living").addEventListener("click",()=>{if(!state.activityData)return;const blob=new Blob([JSON.stringify(window.SensorActivities.export(),null,2)],{type:"application/json"});const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="sensorlab-activity-demo.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $("open-category-records").addEventListener("click",()=>{const category=$("category-filter").value;if(category==="other"){$("other-activities").open=true;$("other-activities").scrollIntoView({block:"start"});}else location.hash=category==="transport"?"transport":["shopping","food"].includes(category)?"shopping":["energy","water"].includes(category)?"sensors":"overall";});
  $("reflection-button").addEventListener("click",()=>$("reflection-dialog").showModal());["close-reflection","dismiss-reflection"].forEach(id=>$(id).addEventListener("click",()=>$("reflection-dialog").close()));
  $("contour-view-button").addEventListener("click",()=>{initialViewSet=true;setMapView("contour");});
  $("surface-view-button").addEventListener("click",()=>{initialViewSet=true;setMapView("3d");});
  $("reset-surface").addEventListener("click",()=>{if(state.surface)state.surface.reset();});
  $("rotate-surface-left").addEventListener("click",()=>{if(state.surface)state.surface.rotate(-Math.PI/8);});
  $("rotate-surface-right").addEventListener("click",()=>{if(state.surface)state.surface.rotate(Math.PI/8);});
  $("zoom-surface-in").addEventListener("click",()=>{if(state.surface)state.surface.zoom(.85);});
  $("zoom-surface-out").addEventListener("click",()=>{if(state.surface)state.surface.zoom(1.18);});
  new ResizeObserver(()=>{if(state.data)treemap();map.invalidateSize({animate:false});updateSurface();}).observe($("footprint-map"));
  document.addEventListener("sensorlab:refresh",()=>refresh());
  document.addEventListener("sensorlab:tab",event=>{
    if(event.detail.tab==="overall"){requestAnimationFrame(()=>{map.invalidateSize({animate:false});if(state.data){treemap();fit();defaultMapView();if(state.surface)state.surface.setVisible(state.view==="3d");}});}
    else {if(state.surface)state.surface.setVisible(false);if($("category-filter").value!=="all"){$("category-filter").value="all";refresh();}}
  });
  refresh();
}());
