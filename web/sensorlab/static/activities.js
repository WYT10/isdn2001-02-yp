"use strict";
(function () {
  const $=id=>document.getElementById(id), fmt=(n,d=2)=>Number(n).toLocaleString(undefined,{maximumFractionDigits:d});
  const storageKey="sensorlab-demo-corrections-v1";
  let data=null,corrections=[],requestId=0,storageAvailable=true;
  try {corrections=JSON.parse(sessionStorage.getItem(storageKey)||"[]");if(!Array.isArray(corrections))corrections=[];}catch(error){storageAvailable=false;}
  function el(tag,attrs={},...children){const node=document.createElement(tag);Object.entries(attrs).forEach(([key,value])=>{if(key==="class")node.className=value;else node.setAttribute(key,value);});children.flat().forEach(child=>{if(child!==null&&child!==undefined)node.append(child instanceof Node?child:document.createTextNode(String(child)));});return node;}
  function text(id,value){$(id).textContent=value;}
  function save(){try{sessionStorage.setItem(storageKey,JSON.stringify(corrections));}catch(error){storageAvailable=false;}}
  function refresh(){document.dispatchEvent(new CustomEvent("sensorlab:refresh"));}
  function correct(change){corrections=corrections.filter(row=>row.id!==change.id).concat(change);save();refresh();}
  function button(label,action,style="button outline"){const node=el("button",{type:"button",class:style},label);node.addEventListener("click",action);return node;}
  function link(label,tab,id){const node=el("a",{href:"#"+tab,class:"text-button"},label);if(id)node.addEventListener("click",()=>openRecord(id));return node;}
  function tabFor(row){return row.kind==="trip"?"transport":row.kind==="purchase"?"shopping":"sensors";}
  function showTab(name,focus=false){
    if(!["home","shopping","transport","sensors","overall"].includes(name))name="overall";
    document.querySelector(".living-app").dataset.activeTab=name;
    document.querySelectorAll(".activity-tab").forEach(node=>node.hidden=node.id!=="tab-"+name);
    document.querySelectorAll(".activity-nav a").forEach(node=>{if(node.dataset.tab===name)node.setAttribute("aria-current","page");else node.removeAttribute("aria-current");});
    document.dispatchEvent(new CustomEvent("sensorlab:tab",{detail:{tab:name}}));
    if(focus)$("title-"+name).focus({preventScroll:true});
  }
  function openRecord(id){const row=data&&data.records.find(r=>r.id===id);if(!row)return;const tab=tabFor(row);location.hash=tab;showTab(tab);requestAnimationFrame(()=>{const node=$("record-"+id);if(node){node.scrollIntoView({block:"center",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});node.focus({preventScroll:true});}});}
  window.addEventListener("hashchange",()=>{const name=location.hash.slice(1);if(["home","shopping","transport","sensors","overall"].includes(name))showTab(name,true);else if(name==="data-notes")$("data-notes").open=true;});
  document.addEventListener("sensorlab:open-record",event=>openRecord(event.detail.id));
  $("period-filter").addEventListener("change",refresh);
  $("reset-activities").addEventListener("click",()=>{corrections=[];save();refresh();});
  $("reset-overall").addEventListener("click",()=>$("reset-activities").click());
  function needsMode(row){return row.kind==="trip"&&row.mode===null;}
  function inputButtons(row){const host=el("div",{class:"choice-buttons"});
    ["mtr","bus","car","skip"].forEach(mode=>host.append(button(mode==="mtr"?"MTR":mode.charAt(0).toUpperCase()+mode.slice(1),()=>correct({id:row.id,mode}),row.mode===mode?"button primary":"button outline")));
    return host;
  }
  function catalogueForm(row){
    const select=el("select",{id:"catalogue-"+row.id},el("option",{value:""},"Choose a demo item"));
    Object.entries(data.catalogue).forEach(([key,item])=>select.append(el("option",{value:key},item.name)));
    const form=el("form",{class:"inline-form"},el("label",{for:select.id},"Confirm the item bought"),select,el("button",{type:"submit",class:"button primary"},"Confirm item"));
    form.addEventListener("submit",event=>{event.preventDefault();if(!select.value){select.focus();return;}correct({id:row.id,catalogue:select.value});});return form;
  }
  function showerForm(row){
    const litres=el("input",{id:"litres-"+row.id,type:"number",min:"0.1",max:"1000",step:"0.1",value:row.litres,required:""});
    const minutes=el("input",{id:"minutes-"+row.id,type:"number",min:"0.1",max:"120",step:"0.1",value:row.minutes,required:""});
    const form=el("form",{class:"session-form"},el("label",{for:litres.id},"Litres",litres),el("label",{for:minutes.id},"Minutes",minutes),el("button",{type:"submit",class:"button outline"},"Update demo session"));
    form.addEventListener("submit",event=>{event.preventDefault();correct({id:row.id,litres:Number(litres.value),minutes:Number(minutes.value)});});
    return el("details",{class:"correction-details"},el("summary",{},"Correct this demo session"),form);
  }
  function what(row){
    if(row.kind==="water")return "Last shower used "+fmt(row.litres)+" L over "+fmt(row.minutes)+" min.";
    if(row.kind==="electricity")return (row.id.startsWith("hotpot")?"Last hot pot session used ":"Other recorded home uses consumed ")+fmt(row.kwh)+" kWh.";
    if(row.kind==="trip")return row.mode?row.quantity+" · estimated "+fmt(row.co2e_kg)+" kg CO₂e for the vehicle leg.":"Vehicle trip detected · confirm mode. No carbon estimate yet.";
    if(row.status==="needs_items")return "HK$"+fmt(row.spend_hkd)+" recorded · item details needed.";
    return row.quantity+(row.packaging_g!==null&&row.packaging_g!==undefined?" · "+fmt(row.packaging_g)+" g packaging recorded.":" · packaging weight unknown.");
  }
  function comparison(row){
    if(row.baseline){const value=row.kind==="water"?row.litres:row.kwh,difference=value-row.baseline.value;
      if(Math.abs(difference)<=row.baseline.value*.1)return "About the same as recent "+(row.kind==="water"?"showers":"hot pot sessions")+" on this same fixture.";
      return fmt(Math.abs(difference))+" "+row.baseline.unit+" "+(difference>0?"more":"less")+" than your recent typical "+(row.kind==="water"?"shower":"hot pot session")+".";}
    if(row.kind==="trip")return row.mode?"Mode confirmed in the demo. A comparison needs the same origin and destination.":"MTR, bus and car can give different estimates. Your confirmation matters.";
    if(row.refill_g!==undefined)return "For the same 500 mL, the example refill has "+fmt(row.packaging_g-row.refill_g)+" g less packaging. Weights need verification.";
    if(row.kind==="purchase")return row.co2e_kg===null?"Item and factor evidence are needed before comparing a footprint.":"Estimated "+fmt(row.co2e_kg)+" kg CO₂e from an unverified "+(row.category==="food"?"comparable food category.":"demo product estimate.");
    return "There is not enough comparable appliance history to describe a usual range.";
  }
  function action(row){
    if(row.kind==="water")return "Try a one-minute shorter shower next time, if practical.";
    if(row.kind==="electricity")return "Review the next session on this same appliance before changing a routine.";
    if(row.kind==="trip")return row.mode?"Review a feasible alternative for the next journey below.":"Confirm the travel mode, or skip and leave this journey unresolved.";
    return row.status==="needs_items"?"Add a receipt line or confirm an item from the demo catalogue.":row.refill_g!==undefined?"Compare equal-size bottle and refill options next time.":"Keep the item details so a suitable comparison can be added later.";
  }
  function record(row){
    const historical=row.id.includes("-w"), status=row.status==="needs_items"?"Item details needed":needsMode(row)?row.status==="unresolved_skipped"?"Unresolved · skipped":"Confirm mode":row.status==="corrected_demo"?"Corrected demo":row.kind==="purchase"&&row.co2e_kg!==null?"Unverified estimate":"Demo record";
    const card=el("article",{class:"activity-record",id:"record-"+row.id,tabindex:"-1","data-record-id":row.id},
      el("header",{},el("div",{},el("p",{class:"eyebrow"},row.owner+" · "+row.date),el("h3",{},row.name)),el("span",{class:"status-chip"+(row.status.startsWith("needs")?" pending":"")},status)),
      el("div",{class:"record-fact"},el("span",{class:"step-label"},"What happened"),el("p",{class:"plain-fact"},what(row))),
      el("div",{class:"record-compare"},el("span",{class:"step-label"},"How it compares"),el("p",{},comparison(row))),
      el("div",{class:"record-action"},el("span",{class:"step-label"},"What I can do"),el("p",{},action(row))));
    const actionHost=card.querySelector(".record-action");
    if(!historical&&row.kind==="trip")actionHost.append(inputButtons(row));
    if(!historical&&row.id==="purchase-02")actionHost.append(catalogueForm(row));
    if(!historical&&row.id==="shower-01")actionHost.append(showerForm(row));
    const details=el("details",{class:"estimate-details"},el("summary",{},"How we estimated this"),el("p",{},"Record "+row.id+" · "+row.status+" · Synthetic example."),el("p",{},row.source));
    if(row.baseline)details.append(el("p",{},"Reference: "+row.baseline.name+"; typical "+row.baseline.value+" "+row.baseline.unit+". All sessions are synthetic. No Bayesian threshold model is running."));
    if(row.kind==="trip"){
      details.append(el("p",{},"Journey legs: "+row.legs.join(" → ")+". Stops: "+row.stations+". Distance is illustrative; changing mode does not re-route it."));
      if(row.mode)details.append(el("p",{},fmt(row.km)+" passenger-km × "+row.factor+" "+row.factor_unit+" = "+fmt(row.co2e_kg,4)+" kg CO₂e. "+row.factor_source+". Region: "+row.region+". Version: "+row.version+". Operational scope, not complete vehicle/infrastructure lifecycle."));
      if(row.factor_url)details.append(el("a",{href:row.factor_url,target:"_blank",rel:"noopener"},"Read the MTR source ↗"));
    }
    if(row.raw)details.append(el("p",{},row.raw));
    if(row.kind==="purchase")details.append(el("p",{},"Packaging and product carbon have different scopes. A barcode identifies an item; a receipt or your confirmation establishes a purchase. No merchant, bank, barcode or lifecycle API is connected. Factor region: "+row.region+"; version: "+row.version+"."));
    if(row.co2e_kg===null)details.append(el("p",{},"Carbon estimate unknown; excluded from kg CO₂e totals, not counted as zero."));
    card.append(details);return card;
  }
  function replaceRecords(id,rows){const host=$(id);host.replaceChildren(...rows.map(record));if(!rows.length)host.append(el("p",{class:"empty-records"},"No activities in this date range and setting."));}
  function summary(label,value,note){return el("article",{},el("span",{class:"step-label"},label),el("strong",{},value),el("p",{},note));}
  function plainChange(comparison){const ratio=comparison.change_fraction;if(ratio===null)return "No comparable reference total is available.";return "Tracked estimates were "+fmt(Math.abs(ratio)*100,1)+"% "+(ratio>=0?"lower":"higher")+" than the named reference period.";}
  function renderHome(){
    const shower=data.records.find(row=>row.id==="shower-01"), pending=data.records.filter(row=>needsMode(row)||row.status==="needs_items");
    if(shower&&shower.litres>shower.baseline.value*1.1){text("action-title","A little less time, a little less water.");text("action-copy",fmt(shower.litres-shower.baseline.value)+" L more than your recent typical shower. Try a one-minute shorter shower next time.");$("action-link").textContent="See water use →";$("action-link").href="#sensors";$("action-link").onclick=()=>openRecord(shower.id);$("action-quantity").replaceChildren(fmt(shower.litres),el("small",{},"litres · demo shower"));}
    else{text("action-title","Your tracked week, at a glance.");text("action-copy",plainChange(data.comparison)+" Review what is covered before drawing conclusions.");$("action-link").textContent="See what changed →";$("action-link").href="#overall";$("action-link").onclick=null;$("action-quantity").replaceChildren(fmt(data.comparison.total_kg,1),el("small",{},"kg CO₂e · demo"));}
    text("input-count",pending.length+" unresolved");const host=$("home-inputs");host.replaceChildren();
    const active=pending.filter(row=>row.status!=="unresolved_skipped").slice(0,2);
    active.forEach(row=>{const item=el("article",{class:"input-card"},el("span",{class:"step-label"},row.kind==="trip"?"A journey needs context":"A purchase needs detail"),el("h3",{},row.kind==="trip"?"How did you travel?":"What was in this purchase?"),el("p",{},row.kind==="trip"?"Afternoon journey · mode not confirmed.":"HK$45 at the supermarket. Items are still unknown."));
      if(row.kind==="trip")item.append(inputButtons(row));else item.append(link("Add items →","shopping",row.id));host.append(item);});
    if(!active.length)host.append(el("p",{class:"empty-records"},pending.length?"Nothing more to ask right now. Skipped inputs remain in your inbox.":"You’re up to date with the demo inputs."));
    $("input-inbox").replaceChildren(...pending.map(row=>el("div",{class:"inbox-row"},el("span",{},row.name+" · "+(row.status==="unresolved_skipped"?"skipped, still unresolved":"needs input")),link("Review →",tabFor(row),row.id))));
    const largest=data.comparison.largest_change;
    text("week-copy",plainChange(data.comparison)+(largest?" "+largest.category.charAt(0).toUpperCase()+largest.category.slice(1)+" accounted for "+fmt(Math.abs(largest.change_kg))+" kg of the "+(largest.change_kg>=0?"decrease":"increase")+".":""));
    text("week-coverage","Partial demo coverage · "+data.coverage.pending_trips+" unresolved trips · "+data.coverage.unknown_emissions+" records without a carbon estimate. Comparison: "+data.period.start+"–"+data.period.end+" versus "+data.period.reference_start+"–"+data.period.reference_end+".");
  }
  function render(){
    renderHome();
    const category=data.footprint.category,water=data.records.filter(r=>r.kind==="water"),power=data.records.filter(r=>r.kind==="electricity"),resourceCards=[];
    if(category==="all"||category==="water")resourceCards.push(summary("Water sessions recorded",fmt(water.reduce((sum,r)=>sum+r.litres,0))+" L",water.length+" demo sessions. Water carbon remains unknown."));
    if(category==="all"||category==="energy")resourceCards.push(summary("Electricity recorded",fmt(power.reduce((sum,r)=>sum+r.kwh,0))+" kWh",power.length+" demo uses. Separate uses exclude the hot pot."));
    $("resource-summary").hidden=!resourceCards.length;$("resource-summary").replaceChildren(...resourceCards);
    if(water.length&&(category==="all"||category==="water"))$("resource-summary").firstChild.append(link("See water sessions →","sensors",water[0].id));
    const purchases=data.records.filter(r=>r.kind==="purchase"),knownPacks=purchases.filter(r=>r.packaging_g!==null&&r.packaging_g!==undefined),estimated=purchases.filter(r=>r.co2e_kg!==null);
    $("shopping-summary").replaceChildren(summary("Packaging recorded",fmt(knownPacks.reduce((sum,r)=>sum+r.packaging_g,0))+" g",knownPacks.length+" purchases with example weights; "+(purchases.length-knownPacks.length)+" unknown."),summary("Estimated purchase emissions",estimated.length?fmt(estimated.reduce((sum,r)=>sum+r.co2e_kg,0))+" kg CO₂e":"Unknown",estimated.length+" unverified demo estimates. Unknown purchases excluded."),summary("Purchases logged",purchases.length,purchases.filter(r=>r.status==="needs_items").length+" need item details."));
    replaceRecords("shopping-records",purchases);
    const trips=data.records.filter(r=>r.kind==="trip").sort((a,b)=>b.date.localeCompare(a.date));replaceRecords("recent-trip",trips.slice(0,1));replaceRecords("transport-records",trips.slice(1));document.querySelector(".commute-panel").hidden=!trips.length;
    replaceRecords("water-records",data.records.filter(r=>r.kind==="water"));replaceRecords("electricity-records",data.records.filter(r=>r.kind==="electricity"));
    const c=data.coverage; text("coverage-copy",c.known_records+" of "+c.total_records+" selected records have a carbon estimate. Coverage is incomplete in both periods.");
    $("coverage-list").replaceChildren(...[c.pending_trips+" trips need confirmation (including skipped trips)",c.pending_purchases+" purchases need item details",c.missing_plug_days+" days of example plug data missing",c.unknown_emissions+" selected records and "+c.reference_unknown_emissions+" reference records have unknown emissions"].map(value=>el("li",{},value)));
    const fraction=data.comparison.change_fraction;
    text("comparison-sentence",fraction===null?"No reference":fmt(Math.abs(fraction)*100,1)+"% "+(fraction>=0?"lower":"higher"));
    const shortDate=value=>new Date(value+"T12:00:00").toLocaleDateString("en-GB",{day:"numeric",month:"short"});
    text("reference-label","vs "+shortDate(data.period.reference_start)+"–"+shortDate(data.period.reference_end));
    text("overview-coverage",c.known_records+" of "+c.total_records+" activities estimated");
    text("comparison-method","Known estimates: "+fmt(data.comparison.total_kg,4)+" kg CO₂e. Named reference: "+fmt(data.comparison.reference_kg,4)+" kg CO₂e. Relative change = (reference − selected) / reference; identical date length, scope and category. No score when the reference has no known emissions.");
    const max=Math.max(1,...data.trends.map(r=>r.total_kg));$("weekly-trend").replaceChildren(...data.trends.map(row=>{const bar=el("span",{class:"trend-bar"});bar.style.width=(row.total_kg/max*100)+"%";return el("div",{class:"trend-row"},el("span",{},row.label),el("div",{class:"trend-track"},bar),el("strong",{},fmt(row.total_kg)+" kg"));}));
    text("session-save-state",storageAvailable?"Corrections stay in this browser tab session.":"Browser storage unavailable; corrections last until this page closes.");
    text("activity-status","Demo activities updated. "+c.pending_trips+" unresolved trips.");
  }
  window.SensorActivities={
    async refresh(filters){const id=++requestId;
      const response=await fetch("/api/v1/living/activities/preview",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({...filters,period:$("period-filter").value,corrections})});
      if(response.status===401){location.assign("/");throw new Error("Sign in again.");}const result=await response.json();if(!response.ok)throw new Error(result.message||"Activity preview unavailable");if(id!==requestId)return null;data=result;render();return result;},
    openRecord,
    records(){return data?data.records:[];},
    export(){return data?{...data,corrections}:null;}
  };
  showTab(location.hash.slice(1));
}());
