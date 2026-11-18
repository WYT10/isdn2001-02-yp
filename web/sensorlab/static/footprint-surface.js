import * as THREE from "./vendor/three.module.js";
import {OrbitControls} from "./vendor/OrbitControls.js";

// The same cell-centred kg CO2e/km2 field used by the contour image.
export function sampleDensity(grid, lat, lon) {
  if (!grid) return 0;
  const [[south,west],[north,east]]=grid.bounds;
  if(lat<south||lat>north||lon<west||lon>east)return 0;
  const x=Math.max(0,Math.min(grid.size-1,(lon-west)/(east-west)*grid.size-.5));
  const y=Math.max(0,Math.min(grid.size-1,(north-lat)/(north-south)*grid.size-.5));
  const ix=Math.floor(x),iy=Math.floor(y),jx=Math.min(ix+1,grid.size-1),jy=Math.min(iy+1,grid.size-1);
  const fx=x-ix,fy=y-iy;
  return (grid.values[iy*grid.size+ix]*(1-fx)+grid.values[iy*grid.size+jx]*fx)*(1-fy)+
         (grid.values[jy*grid.size+ix]*(1-fx)+grid.values[jy*grid.size+jx]*fx)*fy;
}

function densityColor(t) {
  const stops=[[225,238,234],[82,158,171],[119,181,144],[232,206,121],[230,155,96],[216,92,80]];
  t=Math.max(0,Math.min(1,t));const i=Math.min(4,Math.floor(t*5)),f=t*5-i;
  return stops[i].map((value,j)=>(value+(stops[i+1][j]-value)*f)/255);
}

export function createFootprintSurface(host, labelHost, onUnavailable) {
  const canvas=document.createElement("canvas");
  if(!canvas.getContext("webgl2"))throw new Error("3D needs WebGL 2");
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.domElement.tabIndex=0;
  renderer.domElement.setAttribute("role","img");
  renderer.domElement.setAttribute("aria-label","Interactive 3D emission-density landscape. Use the rotate, zoom and reset buttons, or drag the landscape.");
  host.append(renderer.domElement);
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(42,1,.1,1000);
  const controls=new OrbitControls(camera,renderer.domElement);
  controls.enableDamping=false;controls.enablePan=false;
  controls.minPolarAngle=.12;controls.maxPolarAngle=Math.PI/2-.04;
  controls.minDistance=70;controls.maxDistance=350;
  const ambient=new THREE.HemisphereLight(0xffffff,0x667767,2.2);scene.add(ambient);
  const light=new THREE.DirectionalLight(0xffffff,1.7);light.position.set(-40,100,70);scene.add(light);
  let group=null,labels=[],visible=false,current=null,frame=null,lastStreetTiles=0;

  function render() {
    if(!visible||!host.clientWidth||!host.clientHeight)return;
    renderer.render(scene,camera);
    const occupied=[];
    labels.forEach(({element,position,leader})=>{
      const p=position.clone().project(camera);
      element.hidden=p.z>1||p.z<-1||Math.abs(p.x)>1||Math.abs(p.y)>1;
      if(leader)leader.hidden=element.hidden;
      if(element.hidden)return;
      const width=element.offsetWidth,height=element.offsetHeight;
      const x=Math.max(width/2+4,Math.min(host.clientWidth-width/2-4,(p.x*.5+.5)*host.clientWidth));
      let y=Math.max(height+4,(-p.y*.5+.5)*host.clientHeight);
      if(element.classList.contains("activity")){
        for(let attempt=0;attempt<6&&occupied.some(r=>Math.abs(r.x-x)<(r.width+width)/2+4&&Math.abs(r.y-y)<Math.max(r.height,height)+4);attempt++)y=Math.max(height+4,y-height-5);
        occupied.push({x,y,width,height});
      }
      element.style.left=x+"px";element.style.top=y+"px";
      if(leader){const px=(p.x*.5+.5)*host.clientWidth,py=(-p.y*.5+.5)*host.clientHeight;
        leader.style.left=px+"px";leader.style.top=py+"px";leader.style.width=Math.hypot(x-px,y-py)+"px";
        leader.style.transform="rotate("+Math.atan2(y-py,x-px)+"rad)";}
    });
  }
  function schedule(){if(frame===null)frame=requestAnimationFrame(()=>{frame=null;render();});}
  controls.addEventListener("change",schedule);
  renderer.domElement.addEventListener("webglcontextlost",event=>{event.preventDefault();onUnavailable();});
  let lastWidth=0,lastHeight=0;
  function resize(){if(!host.clientWidth||!host.clientHeight)return;const changed=lastWidth!==host.clientWidth||lastHeight!==host.clientHeight;lastWidth=host.clientWidth;lastHeight=host.clientHeight;renderer.setSize(lastWidth,lastHeight,false);camera.aspect=lastWidth/lastHeight;camera.updateProjectionMatrix();if(changed)reset();schedule();}
  new ResizeObserver(resize).observe(host);
  function clear(){
    if(group){scene.remove(group);group.traverse(object=>{if(object.geometry)object.geometry.dispose();if(object.material){if(object.material.map)object.material.map.dispose();object.material.dispose();}});}
    group=new THREE.Group();scene.add(group);labelHost.replaceChildren();labels=[];
  }
  function label(text,position,kind="activity"){
    const element=document.createElement("div");element.className="surface-label "+kind;element.textContent=text;
    const leader=kind==="activity"?document.createElement("div"):null;
    if(leader){leader.className="surface-leader";labelHost.append(leader);}
    labelHost.append(element);labels.push({element,position,leader});
  }
  function update(data,map,dark){
    current={data,map,dark};
    if(!map.getSize().x||!map.getSize().y||!host.clientWidth||!host.clientHeight)return {streetTiles:lastStreetTiles};
    clear();
    scene.background=new THREE.Color(dark?"#182923":"#e9eee7");
    const width=100,depth=100*map.getSize().y/map.getSize().x,n=96;
    const grid=data.grid,position=new THREE.PlaneGeometry(width,depth,n-1,n-1);
    position.rotateX(-Math.PI/2);
    const vertices=position.attributes.position,colors=new Float32Array(vertices.count*4);
    let peak=0;
    for(let i=0;i<vertices.count;i++){
      const x=i%n,y=Math.floor(i/n),point=map.containerPointToLatLng([x/(n-1)*map.getSize().x,y/(n-1)*map.getSize().y]);
      const value=sampleDensity(grid,point.lat,point.lng),ratio=grid?value/grid.max:0;
      vertices.setY(i,ratio*30);peak=Math.max(peak,value);
      const rgb=densityColor(ratio);const color=new THREE.Color().setRGB(...rgb,THREE.SRGBColorSpace);
      colors.set([color.r,color.g,color.b,Math.min(.9,ratio*5)],i*4);
    }
    position.setAttribute("color",new THREE.BufferAttribute(colors,4));position.computeVertexNormals();
    const surface=new THREE.Mesh(position,new THREE.MeshStandardMaterial({vertexColors:true,transparent:true,opacity:.8,roughness:.82,side:THREE.DoubleSide}));
    group.add(surface);
    // Reuse only the already displayed OSM tiles; no extra tile downloads.
    const textureCanvas=document.createElement("canvas");textureCanvas.width=1024;textureCanvas.height=Math.round(1024*depth/width);
    const context=textureCanvas.getContext("2d"),rect=map.getContainer().getBoundingClientRect();
    context.fillStyle=dark?"#34453a":"#e4e9df";context.fillRect(0,0,textureCanvas.width,textureCanvas.height);
    context.filter=dark?"grayscale(1) brightness(.55)":"grayscale(1)";context.globalAlpha=dark?.9:.75;
    let streetTiles=0;
    try{
      map.getPane("tilePane").querySelectorAll("img.leaflet-tile-loaded").forEach(image=>{
        const r=image.getBoundingClientRect();if(r.right<rect.left||r.left>rect.right||r.bottom<rect.top||r.top>rect.bottom)return;
        context.drawImage(image,(r.left-rect.left)/rect.width*textureCanvas.width,(r.top-rect.top)/rect.height*textureCanvas.height,r.width/rect.width*textureCanvas.width,r.height/rect.height*textureCanvas.height);streetTiles++;
      });
      context.getImageData(0,0,1,1);
    }catch(error){streetTiles=0;textureCanvas.width=1;textureCanvas.height=1;const plain=textureCanvas.getContext("2d");plain.fillStyle=dark?"#34453a":"#e4e9df";plain.fillRect(0,0,1,1);}
    const texture=new THREE.CanvasTexture(textureCanvas);texture.colorSpace=THREE.SRGBColorSpace;
    const ground=new THREE.Mesh(new THREE.PlaneGeometry(width,depth),new THREE.MeshBasicMaterial({map:texture,side:THREE.DoubleSide}));ground.rotation.x=-Math.PI/2;ground.position.y=-.2;group.add(ground);
    const outline=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-width/2,0,-depth/2),new THREE.Vector3(width/2,0,-depth/2),new THREE.Vector3(width/2,0,depth/2),new THREE.Vector3(-width/2,0,depth/2)
    ]),new THREE.LineBasicMaterial({color:dark?0x809785:0x8faaa0}));group.add(outline);
    const axis=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-54,0,depth/2),new THREE.Vector3(-54,30,depth/2)]),new THREE.LineBasicMaterial({color:dark?0xc2d8c7:0x54735d}));group.add(axis);
    label("0",new THREE.Vector3(-56,0,depth/2),"axis");
    label((grid?grid.max:0).toLocaleString(undefined,{maximumFractionDigits:1})+" kg CO₂e/km²",new THREE.Vector3(-54,33,depth/2),"axis");
    label("N",new THREE.Vector3(0,0,-depth/2-4),"axis");
    const grouped=new Map();data.activities.forEach(row=>{const key=row.lat.toFixed(5)+","+row.lon.toFixed(5);if(!grouped.has(key))grouped.set(key,{lat:row.lat,lon:row.lon,rows:[],total:0});const p=grouped.get(key);p.rows.push(row);p.total+=row.co2e_kg;});
    [...grouped.values()].forEach(point=>{
      const pixel=map.latLngToContainerPoint([point.lat,point.lon]);
      if(pixel.x<0||pixel.x>map.getSize().x||pixel.y<0||pixel.y>map.getSize().y)return;
      const x=(pixel.x/map.getSize().x-.5)*width,z=(pixel.y/map.getSize().y-.5)*depth,y=grid?sampleDensity(grid,point.lat,point.lon)/grid.max*30:0;
      const pin=new THREE.Mesh(new THREE.SphereGeometry(.75,10,8),new THREE.MeshBasicMaterial({color:0x254d3b}));pin.position.set(x,y+1,z);group.add(pin);
      if(grouped.size<=3||point.rows.some(row=>/home energy|road commute|cafe/i.test(row.name))){
        const name=point.rows.length>1?"Home activities":point.rows[0].name;
        label(name+" · "+point.total.toLocaleString(undefined,{maximumFractionDigits:2})+" kg CO₂e",new THREE.Vector3(x,y+5,z));
      }
    });
    host.dataset.vertexCount=String(vertices.count);host.dataset.maxDensity=String(peak);host.dataset.streetTiles=String(streetTiles);
    host.dataset.maxHeight=String(peak&&grid?peak/grid.max*30:0);
    lastStreetTiles=streetTiles;resize();schedule();return {streetTiles};
  }
  function reset(){
    if(current&&(!current.map.getSize().x||!current.map.getSize().y))return;
    const depth=100*(current?current.map.getSize().y/current.map.getSize().x:1);
    const fov=Math.min(camera.fov*Math.PI/180,2*Math.atan(Math.tan(camera.fov*Math.PI/360)*camera.aspect));
    const distance=Math.hypot(50,depth/2,18)/Math.sin(fov/2)*1.12;
    controls.maxDistance=Math.max(350,distance*2);controls.target.set(0,7,0);
    const direction=new THREE.Vector3(.55,.73,.8).normalize();
    let fittedDistance=distance;
    const box=group?new THREE.Box3().setFromObject(group):null;
    for(let pass=0;pass<4;pass++){
      camera.position.copy(direction.clone().multiplyScalar(fittedDistance)).add(controls.target);controls.update();camera.updateMatrixWorld();
      if(!box||box.isEmpty())break;
      let extent=0;
      for(const x of[box.min.x,box.max.x])for(const y of[box.min.y,box.max.y])for(const z of[box.min.z,box.max.z]){
        const point=new THREE.Vector3(x,y,z).project(camera);extent=Math.max(extent,Math.abs(point.x)/.82,Math.abs(point.y)/.82);
      }
      if(!Number.isFinite(extent)||Math.abs(extent-1)<.02)break;
      fittedDistance=Math.max(controls.minDistance,fittedDistance*extent);
    }
    camera.position.copy(direction.multiplyScalar(fittedDistance)).add(controls.target);controls.update();schedule();
  }
  function rotate(amount){const offset=camera.position.clone().sub(controls.target);offset.applyAxisAngle(new THREE.Vector3(0,1,0),amount);camera.position.copy(controls.target).add(offset);controls.update();schedule();}
  function zoom(factor){camera.position.sub(controls.target).multiplyScalar(factor).clampLength(controls.minDistance,controls.maxDistance).add(controls.target);controls.update();schedule();}
  function setVisible(value){visible=value;controls.enabled=value;if(value){resize();render();}}
  reset();
  return {update,reset,rotate,zoom,setVisible,refresh(){if(current)return update(current.data,current.map,current.dark);}};
}
