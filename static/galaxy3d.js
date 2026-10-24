/* Perspective-projected 3D graph. Positions are presentation only, never evidence. */
(function () {
  'use strict';
  class Galaxy3D {
    constructor(container, graph, callbacks) {
      this.host=container;this.callbacks=callbacks;this.yaw=0.35;this.pitch=0.9;this.scale=1;
      this.turning=!matchMedia('(prefers-reduced-motion: reduce)').matches;this.visible=true;this.alive=true;
      this.nodes=graph.nodes.map((n,i)=>{
        const a=i*2.399963, r=graph.nodes.length>40?70+Math.sqrt(i)*25:150;
        return {...n,x:Math.cos(a)*r,y:Math.sin(a)*r,z:Math.sin(i*1.73)*r*0.42,degree:0,featured:n.type==='Person' && i%37===0};
      });
      this.byId=new Map(this.nodes.map(n=>[n.id,n]));
      this.edges=graph.edges.filter(e=>this.byId.has(e.source)&&this.byId.has(e.target));
      this.edges.forEach(e=>{this.byId.get(e.source).degree++;this.byId.get(e.target).degree++;});
      this.radius=Math.max(220,...this.nodes.map(n=>Math.hypot(n.x,n.y,n.z)));
      this.dense=this.nodes.length>40;
      this.canvas=document.createElement('canvas');this.canvas.tabIndex=0;
      this.canvas.setAttribute('role','img');
      this.canvas.setAttribute('aria-label','3D connections. Drag or use arrow keys to rotate. Scroll or use plus and minus to zoom. Select people in the adjacent list for details.');
      this.canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;outline-offset:-4px;';
      container.replaceChildren(this.canvas);this.ctx=this.canvas.getContext('2d');
      this.events=new AbortController();const on=(name,fn)=>this.canvas.addEventListener(name,fn,{signal:this.events.signal});
      on('pointerdown',e=>{this.down={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,moved:false};this.canvas.setPointerCapture(e.pointerId);});
      on('pointermove',e=>{
        if(this.down){const d=this.down;d.moved ||= Math.hypot(e.clientX-d.startX,e.clientY-d.startY)>5;
          this.yaw+=(e.clientX-d.x)*0.007;this.pitch=Math.max(-1.5,Math.min(1.5,this.pitch+(e.clientY-d.y)*0.007));d.x=e.clientX;d.y=e.clientY;this.schedule();}
        else {const rect=this.canvas.getBoundingClientRect();this.hover=this.pick(e.clientX-rect.left,e.clientY-rect.top);this.canvas.style.cursor=this.hover?'pointer':'grab';this.schedule();}
      });
      on('pointerup',e=>{if(this.down&&!this.down.moved){const rect=this.canvas.getBoundingClientRect(),n=this.pick(e.clientX-rect.left,e.clientY-rect.top);if(n)this.callbacks.select(n);}
        this.down=null;this.schedule();});
      on('pointercancel',()=>{this.down=null;});on('pointerleave',()=>{this.hover=null;this.schedule();});
      this.canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom(this.scale*Math.exp(-e.deltaY*0.001));},{passive:false,signal:this.events.signal});
      on('keydown',e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key)){e.preventDefault();
        if(e.key==='ArrowLeft')this.yaw-=0.1;if(e.key==='ArrowRight')this.yaw+=0.1;if(e.key==='ArrowUp')this.pitch-=0.1;if(e.key==='ArrowDown')this.pitch+=0.1;
        if(e.key==='+'||e.key==='=')this.zoom(this.scale*1.15);if(e.key==='-')this.zoom(this.scale/1.15);this.schedule();}});
      this.observer=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;if(this.visible)this.schedule();});this.observer.observe(container);
      document.addEventListener('visibilitychange',()=>{if(!document.hidden)this.schedule();},{signal:this.events.signal});
      this.resize();
    }
    schedule(){if(this.alive&&!this.frame)this.frame=requestAnimationFrame(t=>{this.frame=null;this.paint(t);});}
    resize(){this.width=this.host.clientWidth;this.height=this.host.clientHeight;if(!this.width||!this.height)return;
      const dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=this.width*dpr;this.canvas.height=this.height*dpr;this.ctx.setTransform(dpr,0,0,dpr,0,0);this.schedule();}
    fit(){this.scale=1;this.yaw=0.35;this.pitch=0.9;this.resize();}
    zoom(value){if(value===undefined)return this.scale;this.scale=Math.max(0.4,Math.min(4,value));this.schedule();}
    select(id){this.selected=this.byId.get(id);this.schedule();}
    toggle(){this.turning=!this.turning;this.schedule();return this.turning;}
    pick(x,y){return [...(this.projected||[])].reverse().find(n=>Math.hypot(n.sx-x,n.sy-y)<Math.max(n.size+4,9));}
    project(n){const c=Math.cos(this.yaw),s=Math.sin(this.yaw),cp=Math.cos(this.pitch),sp=Math.sin(this.pitch);
      const x=n.x*c-n.y*s,y=n.x*s+n.y*c,z=y*sp+n.z*cp,vertical=y*cp-n.z*sp;
      const depth=1/(1+z/(this.radius*3));const unit=Math.min(this.width,this.height)*0.4/this.radius*this.scale;
      return {...n,sx:this.width/2+x*unit*depth,sy:this.height/2+vertical*unit*depth,zdepth:z,depth,
        size:(this.dense?(n.type==='Person'?3.2:2.1):(n.type==='Person'?11:7))*depth*Math.sqrt(this.scale)};}
    paint(t){if(!this.alive||!this.visible||document.hidden)return;
      const dt=Math.min(40,t-(this.lastTime||t));this.lastTime=t;
      if(this.turning&&!this.down&&!this.hover)this.yaw+=dt*0.000055;
      const ctx=this.ctx,w=this.width,h=this.height;ctx.clearRect(0,0,w,h);
      this.projected=this.nodes.map(n=>this.project(n)).sort((a,b)=>b.zdepth-a.zdepth);
      const projected=new Map(this.projected.map(n=>[n.id,n]));const active=this.hover||this.selected;
      const nearby=new Set(active?[active.id]:[]);if(active)this.edges.forEach(e=>{if(e.source===active.id)nearby.add(e.target);if(e.target===active.id)nearby.add(e.source);});
      // Orbit guides rotate with the data, giving the otherwise abstract graph depth.
      [0.55,0.85,1.12].forEach(r=>{ctx.beginPath();for(let i=0;i<=90;i++){const a=i/90*Math.PI*2,p=this.project({x:Math.cos(a)*this.radius*r,y:Math.sin(a)*this.radius*r,z:0});if(i)ctx.lineTo(p.sx,p.sy);else ctx.moveTo(p.sx,p.sy);}
        ctx.strokeStyle='rgba(139,143,163,0.10)';ctx.lineWidth=0.7;ctx.stroke();});
      this.edges.forEach(e=>{const a=projected.get(e.source),b=projected.get(e.target),lit=active&&(e.source===active.id||e.target===active.id);
        ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo(b.sx,b.sy);ctx.lineWidth=lit?1.4:0.65;
        ctx.strokeStyle=lit?'rgba(113,131,170,0.65)':active?'rgba(143,153,179,0.035)':this.dense?'rgba(143,153,179,0.14)':'rgba(143,153,179,0.35)';ctx.stroke();});
      this.projected.forEach(n=>{const lit=!active||nearby.has(n.id);ctx.globalAlpha=lit?Math.max(.4,Math.min(1,n.depth)):0.16;
        const color=this.callbacks.colors[n.type]||'#7182b7';
        const halo=ctx.createRadialGradient(n.sx,n.sy,0,n.sx,n.sy,n.size*4);halo.addColorStop(0,color+'40');halo.addColorStop(1,color+'00');ctx.fillStyle=halo;ctx.beginPath();ctx.arc(n.sx,n.sy,n.size*4,0,Math.PI*2);ctx.fill();
        const sphere=ctx.createRadialGradient(n.sx-n.size*.35,n.sy-n.size*.4,0,n.sx,n.sy,n.size);sphere.addColorStop(0,'#ffffff');sphere.addColorStop(.35,color);sphere.addColorStop(1,color);ctx.fillStyle=sphere;
        ctx.beginPath();ctx.arc(n.sx,n.sy,n.size,0,Math.PI*2);ctx.fill();
        if(active&&n.id===active.id){ctx.strokeStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.arc(n.sx,n.sy,n.size+4,0,Math.PI*2);ctx.stroke();}
        const label=!this.dense||(active&&nearby.has(n.id))||(!active&&n.featured);
        if(label&&lit){ctx.font=`${n.type==='Person'?600:400} ${active||!this.dense?12:10}px Inter, Arial, sans-serif`;ctx.textAlign='center';
          const text=n.label.length>30?n.label.slice(0,28)+'…':n.label;ctx.lineWidth=4;ctx.strokeStyle='#fcfbfa';ctx.strokeText(text,n.sx,n.sy+n.size+17);ctx.fillStyle='#575d6d';ctx.fillText(text,n.sx,n.sy+n.size+17);}
      });ctx.globalAlpha=1;
      if(this.turning&&!this.down&&!this.hover)this.schedule();
    }
    destroy(){this.alive=false;cancelAnimationFrame(this.frame);this.events.abort();this.observer.disconnect();this.canvas.remove();}
  }
  window.Galaxy3D=Galaxy3D;
})();
