/* VAULT - pages/auth.js
   Sign-in and first-run setup page (templates/accounts/auth.html), BdREN VAULT design:
   - the animated background on <canvas id="scene">, showing VAULT's two jobs: rack devices and the Bangladesh
     map send configuration backups into CONFIG BACKUP, and switches / routers ask RADIUS / AAA to check a login
     (Access-Request out, Access-Accept back). Decoration only, aria-hidden; one still frame for reduced motion;
   - show / hide password, Caps Lock hint, button ripple, required-field check with a shake, and a busy
     "Signing in..." button. The form itself is a normal POST to the server (no JavaScript needed to sign in). */

const form = document.getElementById('loginForm');
const user = document.getElementById('username');
const pwd = document.getElementById('password');
const statusEl = document.getElementById('status');
const btn = document.getElementById('submitBtn');
const btnLabel = btn.querySelector('.label');
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ============ Code-drawn background: devices → config backups → VAULT ============ */
(function(){
  const cv = document.getElementById('scene');
  const ctx = cv.getContext('2d');
  let W, H, DPR, base, small, devices, vault, flows, packets, mapDots, cities, leds, tags, pulses, motes, mapInfo;
  let aaa, authFlows, authPackets, authPulses;

  // Simplified Bangladesh outline (lon, lat)
  const BD = [[88.3,26.4],[88.5,26.62],[88.75,26.3],[89.1,26.0],[89.6,26.05],[89.85,25.95],[89.85,25.3],
    [90.4,25.15],[91.0,25.2],[91.6,25.15],[92.05,25.1],[92.45,24.9],[92.25,24.5],[91.9,24.3],[91.6,24.1],
    [91.35,24.1],[91.2,23.7],[91.15,23.45],[91.3,23.1],[91.6,22.95],[91.8,23.4],[92.05,23.65],[92.25,23.5],
    [92.35,22.9],[92.6,22.15],[92.6,21.4],[92.3,20.7],[92.05,21.15],[91.9,21.6],[91.8,22.2],[91.5,22.5],
    [91.0,22.8],[90.6,22.55],[90.4,21.9],[89.9,21.9],[89.4,21.8],[89.0,21.7],[89.05,22.1],[88.95,22.6],
    [88.75,23.2],[88.55,23.6],[88.7,24.2],[88.1,24.5],[88.0,24.75],[88.45,25.2],[88.6,25.5],[88.1,25.8]];
  const CITIES = [[90.4,23.8,1],[91.8,22.35],[88.6,24.37],[89.55,22.8],[91.87,24.9],[89.25,25.75],[90.35,22.7],[90.4,24.75]];

  const rand = (a,b) => a + Math.random()*(b-a);
  const inside = (x,y,poly) => { let c=false; for(let i=0,j=poly.length-1;i<poly.length;j=i++){const[xi,yi]=poly[i],[xj,yj]=poly[j];if(((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi)+xi))c=!c;} return c; };
  const bez = (f,t) => { const u=1-t; return [u*u*u*f.x1+3*u*u*t*f.c1x+3*u*t*t*f.c2x+t*t*t*f.x2, u*u*u*f.y1+3*u*u*t*f.c1y+3*u*t*t*f.c2y+t*t*t*f.y2]; };
  const curve = (c,f) => { c.beginPath(); c.moveTo(f.x1,f.y1); c.bezierCurveTo(f.c1x,f.c1y,f.c2x,f.c2y,f.x2,f.y2); };
  const rr = (c,x,y,w,h,r) => { c.beginPath(); c.moveTo(x+r,y); c.arcTo(x+w,y,x+w,y+h,r); c.arcTo(x+w,y+h,x,y+h,r); c.arcTo(x,y+h,x,y,r); c.arcTo(x,y,x+w,y,r); c.closePath(); };

  const glow = document.createElement('canvas'); glow.width = glow.height = 64;
  (()=>{ const g=glow.getContext('2d'),r=g.createRadialGradient(32,32,0,32,32,32);
    r.addColorStop(0,'rgba(255,255,255,1)');r.addColorStop(.15,'rgba(201,236,246,.95)');
    r.addColorStop(.4,'rgba(97,181,227,.35)');r.addColorStop(1,'rgba(67,144,217,0)');
    g.fillStyle=r;g.fillRect(0,0,64,64); })();
  const spot = (c,x,y,s,a) => { c.globalAlpha=Math.max(0,Math.min(1,a)); c.drawImage(glow,x-s/2,y-s/2,s,s); c.globalAlpha=1; };

  const GREEN=[95,255,160], CYAN=[90,220,255], AMBER=[255,190,80];
  // the map's dots shimmer in a few phase groups, each drawn as ONE path and fill (hundreds of dots per frame)
  const DOT_BUCKETS = 8;
  const led = (x,y,col,sp,size=3) => leds.push({x,y,c:col,sp,ph:Math.random()*6.28,size});
  const FONT = '"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif';

  function devGeom(d){
    d.h = d.type==='server' ? d.w*.2 : d.type==='switch' ? d.w*.17 : d.w*.22;
    d.dx = d.w*.46; d.dy = d.w*.26;
    d.topX = d.x + d.w/2 + d.dx/2;
    d.topY = d.y - d.units*d.h - d.dy/2;
  }

  function build(){
    DPR = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    cv.width = W*DPR; cv.height = H*DPR;
    const portrait = H > W;
    small = Math.min(W,H) < 560;
    const horizon = H * (portrait ? .7 : .62);

    /* ---- Bangladesh map with regional sites ---- */
    const mw = portrait ? W*.34 : Math.min(W*.19, H*.34);
    const cxm = portrait ? W*.76 : W*.81, cym = portrait ? H*.27 : H*.3;
    const lon0=88, lon1=92.7, lat0=20.6, lat1=26.7;
    const mh = mw*(lat1-lat0)/((lon1-lon0)*Math.cos(23.7*Math.PI/180));
    const gap = Math.max(3.2, mw/40);
    const toXY = (lon,lat) => [cxm-mw/2+(lon-lon0)/(lon1-lon0)*mw, cym-mh/2+(lat1-lat)/(lat1-lat0)*mh];
    mapDots = [];
    for (let py=cym-mh/2; py<=cym+mh/2; py+=gap)
      for (let px=cxm-mw/2; px<=cxm+mw/2; px+=gap){
        const lon=lon0+(px-(cxm-mw/2))/mw*(lon1-lon0), lat=lat1-(py-(cym-mh/2))/mh*(lat1-lat0);
        if (inside(lon,lat,BD)) mapDots.push({x:px,y:py,b:Math.floor(Math.random()*DOT_BUCKETS)});
      }
    cities = CITIES.map(([lon,lat,cap]) => { const [x,y]=toXY(lon,lat); return {x,y,cap:!!cap,ph:rand(0,6.28)}; });
    mapInfo = {cx:cxm,cy:cym,w:mw,h:mh};

    /* ---- devices (left) and the vault (right) ---- */
    // small screens size by their SHORT side: a landscape phone (812x375) otherwise got giant, overlapping devices
    const sm = Math.min(W,H);
    const u = small ? Math.max(38, sm*.12) : Math.min(100, Math.max(54, W*.062));
    const D = (fx,fy,units,sc,type,name,file) => { const d={x:fx*W,y:fy*H,w:u*sc,units,type,name,file}; devGeom(d); return d; };
    // network devices (named) back up to CONFIG BACKUP and ask RADIUS / AAA about logins; the servers are scenery
    devices = portrait
      ? [D(.03,.86,2,.85,'switch','BdREN-Core-SW1','running-config'), D(.24,.93,1,.95,'router','BdREN-Core-R1','running-config')]
      : [D(.035,.74,4,.95,'server','',''),
         D(.135,.69,2,.9,'switch','BdREN-Core-SW1','running-config'),
         D(.225,.77,1,1,'router','BdREN-Core-R1','running-config'),
         D(.06,.9,1,1.05,'router','BdREN-Dist-R1','running-config'),
         D(.18,.93,3,1,'server','','')];
    devices.sort((a,b)=>a.y-b.y);

    const R = small ? Math.max(30, sm*.085) : Math.min(78, Math.max(44, W*.045));
    vault = portrait ? {x:W*.8, y:H*.9, R} : {x:W*.81, y:H*.8, R};
    const ry = R*.34, dh = R*.42, vgap = R*.08;
    vault.ry = ry; vault.dh = dh; vault.vgap = vgap;
    vault.topX = vault.x; vault.topY = vault.y - 2*(dh+vgap) - dh;

    /* ---- backup flow paths ---- */
    flows = devices.filter(d => d.type !== 'server').map(d => {
      const lift = H * (portrait ? .12 : rand(.2,.3));
      const top = Math.min(d.topY, vault.topY) - lift;
      return {kind:'dev', dev:d, x1:d.topX, y1:d.topY, x2:vault.topX, y2:vault.topY,
        c1x:d.topX + (vault.topX-d.topX)*.25, c1y:top, c2x:d.topX + (vault.topX-d.topX)*.75, c2y:top};
    });
    cities.forEach(cty => {
      flows.push({kind:'city', x1:cty.x, y1:cty.y, x2:vault.topX, y2:vault.topY,
        c1x:cty.x, c1y:cty.y + (vault.topY-cty.y)*.55, c2x:vault.topX, c2y:vault.topY - (vault.topY-cty.y)*.45});
    });
    const devFlows = flows.filter(f=>f.kind==='dev'), cityFlows = flows.filter(f=>f.kind==='city');
    packets = [];
    devFlows.forEach((f,i) => packets.push({f, t: -i*.35 - Math.random()*.3, sp: rand(.11,.16)}));
    cityFlows.forEach((f,i) => packets.push({f, t: -Math.random()*1.5, sp: rand(.25,.4)}));

    /* ---- RADIUS / AAA: switches and routers ask it to check each login ---- */
    // side by side with CONFIG BACKUP (right of it on wide screens, left of it on phones), labels on one line
    const ar = vault.R * .72;
    const side = Math.max(vault.R + ar*2.2, small ? 108 : 140);   // keeps the two labels apart on phones
    aaa = {x: portrait ? vault.x - side : Math.min(vault.x + side, W - (small ? 54 : 70)),   // label stays on screen
           y: vault.y + vault.ry - ar*1.4 + (small?0:1), r: ar};
    const loginDevs = devices.filter(d => d.type !== 'server');
    authFlows = loginDevs.map(d => {
      const top = Math.min(d.topY, aaa.y - aaa.r) - H * (portrait ? .1 : rand(.14,.22));
      return {kind:'auth', dev:d, x1:d.topX, y1:d.topY, x2:aaa.x, y2:aaa.y - aaa.r,
        c1x:d.topX + (aaa.x-d.topX)*.25, c1y:top, c2x:d.topX + (aaa.x-d.topX)*.75, c2y:top};
    });
    authPackets = authFlows.map((f,i) => ({f, t: -i*1.1 - rand(.4,1.4), sp: rand(.34,.44), back:false}));
    authPulses = [];
    // the regional sites on the map log in through RADIUS / AAA too (teal links), not only back up
    cities.forEach(cty => {
      const f = {kind:'cauth', x1:cty.x, y1:cty.y, x2:aaa.x, y2:aaa.y - aaa.r,
        c1x:cty.x, c1y:cty.y + (aaa.y-cty.y)*.55, c2x:aaa.x, c2y:aaa.y - aaa.r - (aaa.y-cty.y)*.45};
      flows.push(f);
      packets.push({f, t: -rand(.5,3.5), sp: rand(.22,.34)});
    });

    leds = []; tags = []; pulses = [];
    motes = Array.from({length: small?8:16}, () => ({x:rand(0,W),y:rand(0,H),s:rand(1,2.2),sp:rand(5,14),ph:rand(0,6.28)}));

    base = document.createElement('canvas'); base.width = W*DPR; base.height = H*DPR;
    const c = base.getContext('2d'); c.scale(DPR,DPR);
    drawStatic(c, horizon);
  }

  function drawStatic(c, horizon){
    // faint stars
    for (let i=0;i<(small?40:90);i++){
      const a=rand(.06,.28); c.fillStyle=`rgba(181,212,240,${a})`;
      c.fillRect(rand(0,W),rand(0,horizon*.8),a>.22?1.5:1,a>.22?1.5:1);
    }
    // perspective grid floor
    const vx = W/2, vy = horizon - H*.12;
    c.save(); c.beginPath(); c.rect(0,horizon,W,H-horizon); c.clip();
    const fade = c.createLinearGradient(0,horizon,0,H);
    fade.addColorStop(0,'rgba(102,165,224,0)'); fade.addColorStop(1,'rgba(102,165,224,.18)');
    c.strokeStyle = fade; c.lineWidth = 1;
    for (let i=-30;i<=30;i++){ c.beginPath(); c.moveTo(vx,vy); c.lineTo(vx+i*W*.06,H*1.4); c.stroke(); }
    for (let t=0;t<1;t+=.06){ const y=horizon+(H-horizon)*t*t; c.beginPath(); c.moveTo(0,y); c.lineTo(W,y); c.stroke(); }
    c.restore();
    const hg = c.createLinearGradient(0,horizon-H*.06,0,horizon+H*.06);
    hg.addColorStop(0,'rgba(86,163,222,0)'); hg.addColorStop(.5,'rgba(86,163,222,.1)'); hg.addColorStop(1,'rgba(86,163,222,0)');
    c.fillStyle = hg; c.fillRect(0,horizon-H*.06,W,H*.12);

    // map halo
    const m = mapInfo;
    const mg = c.createRadialGradient(m.cx,m.cy,0,m.cx,m.cy,m.w*1.1);
    mg.addColorStop(0,'rgba(86,163,222,.16)'); mg.addColorStop(1,'rgba(86,163,222,0)');
    c.fillStyle = mg; c.fillRect(m.cx-m.w*1.2,m.cy-m.h,m.w*2.4,m.h*2);

    // flow rails (faint base line under the animated dashes)
    c.lineWidth = 1;
    flows.forEach(f => {
      c.strokeStyle = f.kind==='dev' ? 'rgba(131,194,232,.16)' : 'rgba(131,194,232,.08)';
      curve(c,f); c.stroke();
    });
    c.strokeStyle = 'rgba(110,200,230,.12)';
    authFlows.forEach(f => { curve(c,f); c.stroke(); });
    drawAAA(c, aaa);

    // light pools, then devices and vault (back to front)
    const pool = (px,py,rx,ry,a) => {
      const g = c.createRadialGradient(px,py,0,px,py,rx);
      g.addColorStop(0,`rgba(86,163,222,${a})`); g.addColorStop(1,'rgba(86,163,222,0)');
      c.save(); c.translate(px,py); c.scale(1,ry/rx); c.translate(-px,-py);
      c.fillStyle = g; c.beginPath(); c.arc(px,py,rx,0,6.283); c.fill(); c.restore();
    };
    devices.forEach(d => { pool(d.x+d.w*.7, d.y-d.w*.05, d.w*1.1, d.w*.3, .28); drawDevice(c,d); });
    pool(vault.x, vault.y, vault.R*2.4, vault.R*.7, .4);
    drawVault(c, vault);

    // device hostnames
    if (!small){
      c.font = `600 10px ${FONT}`; c.textAlign = 'center'; c.fillStyle = 'rgba(184,212,233,.6)';
      if ('letterSpacing' in c) c.letterSpacing = '.5px';
      devices.forEach(d => { if (d.name) c.fillText(d.name, d.x + d.w*.5, d.y + 13); });
    }

    // depth fog
    const fog = c.createLinearGradient(0,horizon-H*.05,0,H);
    fog.addColorStop(0,'rgba(17,39,77,.2)'); fog.addColorStop(.4,'rgba(17,39,77,0)'); fog.addColorStop(1,'rgba(4,10,22,.4)');
    c.fillStyle = fog; c.fillRect(0,horizon-H*.05,W,H);
  }

  /* Rack-mount hardware: graphite chassis, rack ears, vents, drive bays, port blocks */
  function drawDevice(c,d){
    const {x,y,w,units,type,h,dx,dy} = d;
    const SH = units*h, t = y-SH;

    // contact shadow on the floor
    c.save(); c.translate(x+w*.5+dx*.5, y-dy*.5); c.scale(1,.32);
    const sh = c.createRadialGradient(0,0,0,0,0,w*.85);
    sh.addColorStop(0,'rgba(2,6,16,.55)'); sh.addColorStop(1,'rgba(2,6,16,0)');
    c.fillStyle = sh; c.beginPath(); c.arc(0,0,w*.85,0,6.283); c.fill(); c.restore();

    /* ---- side panel with vent grooves ---- */
    const sg = c.createLinearGradient(x+w,0,x+w+dx,0);
    sg.addColorStop(0,'#1e2838'); sg.addColorStop(1,'#0c131f');
    c.fillStyle = sg;
    c.beginPath(); c.moveTo(x+w,t); c.lineTo(x+w+dx,t-dy); c.lineTo(x+w+dx,y-dy); c.lineTo(x+w,y); c.closePath(); c.fill();
    c.lineWidth = 1;
    for (let i=0;i<units;i++){
      const yb = y-i*h, yt = yb-h;
      c.strokeStyle = 'rgba(0,0,0,.45)';
      c.beginPath(); c.moveTo(x+w,yb); c.lineTo(x+w+dx,yb-dy); c.stroke();
      c.strokeStyle = 'rgba(0,0,0,.35)';
      for (let k=1;k<=4;k++){ // short vent slots near the front of each unit
        const f = .12 + k*.09, sx = x+w+dx*f, sy0 = yt - dy*f + h*.28, sy1 = yb - dy*f - h*.28;
        c.beginPath(); c.moveTo(sx,sy0); c.lineTo(sx,sy1); c.stroke();
      }
    }
    c.strokeStyle = 'rgba(137,186,231,.18)';
    c.beginPath(); c.moveTo(x+w,t); c.lineTo(x+w+dx,t-dy); c.lineTo(x+w+dx,y-dy); c.stroke();

    /* ---- front panels ---- */
    for (let i=0;i<units;i++){
      const top = y-(i+1)*h;
      // chassis face: brushed graphite
      const fg = c.createLinearGradient(x,top,x,top+h);
      fg.addColorStop(0,'#374356'); fg.addColorStop(.12,'#2a3445'); fg.addColorStop(1,'#181f2b');
      c.fillStyle = fg; c.fillRect(x,top,w,h);
      c.fillStyle = 'rgba(207,228,246,.22)'; c.fillRect(x,top,w,1);
      c.fillStyle = 'rgba(1,4,11,.7)'; c.fillRect(x,top+h-1,w,1);
      // rack ears with screws
      const ear = Math.max(3, w*.04);
      c.fillStyle = '#1e2735'; c.fillRect(x,top+1,ear,h-2); c.fillRect(x+w-ear,top+1,ear,h-2);
      c.fillStyle = 'rgba(0,0,0,.4)'; c.fillRect(x+ear,top+1,1,h-2); c.fillRect(x+w-ear-1,top+1,1,h-2);
      const screw = (sx,sy) => { c.fillStyle='rgba(157,178,203,.55)'; c.beginPath(); c.arc(sx,sy,Math.max(.8,w*.008),0,6.283); c.fill(); };
      screw(x+ear/2, top+h*.3); screw(x+w-ear/2, top+h*.3);
      if (h > 14){ screw(x+ear/2, top+h*.72); screw(x+w-ear/2, top+h*.72); }
      const L = x+ear+2, R = x+w-ear-2, IW = R-L;   // usable panel width

      if (type==='server'){
        // honeycomb intake vent
        const vx0 = L+1, vx1 = L+IW*.24, vy0 = top+h*.2, vy1 = top+h*.8, st = Math.max(2, w*.022);
        c.fillStyle = 'rgba(6,10,18,.65)'; rr(c,vx0-1,vy0-1,vx1-vx0+2,vy1-vy0+2,1.5); c.fill();
        c.fillStyle = 'rgba(80,108,143,.35)';
        let row = 0;
        for (let yy=vy0+st*.5; yy<vy1; yy+=st*.85, row++)
          for (let xx=vx0+st*.5+(row%2?st*.5:0); xx<vx1; xx+=st){ c.beginPath(); c.arc(xx,yy,st*.28,0,6.283); c.fill(); }
        // hot-swap drive carriers
        const n = 4, bx0 = L+IW*.28, bw = IW*.12, bgp = IW*.018;
        for (let b=0;b<n;b++){
          const bx = bx0 + b*(bw+bgp), by = top+h*.16, bh = h*.68;
          c.fillStyle = '#0e1520'; rr(c,bx,by,bw,bh,1.2); c.fill();
          const cg = c.createLinearGradient(0,by,0,by+bh);
          cg.addColorStop(0,'#3e4a5d'); cg.addColorStop(1,'#252f3e');
          c.fillStyle = cg; c.fillRect(bx+1,by+1,bw-2,bh*.45);           // carrier latch
          c.fillStyle = 'rgba(216,233,247,.25)'; c.fillRect(bx+1,by+1,bw-2,1);
          c.fillStyle = 'rgba(0,0,0,.45)';
          for (let k=1;k<4;k++) c.fillRect(bx+bw*k/4,by+bh*.58,1,bh*.3); // carrier grille
          led(bx+bw*.82, by+bh*.28, Math.random()<.85?CYAN:AMBER, rand(3,9), 1.8);
        }
        // control panel: power button + health LEDs
        const px = L+IW*.83, pw = IW*.17;
        c.fillStyle = 'rgba(8,14,24,.75)'; rr(c,px,top+h*.16,pw,h*.68,1.5); c.fill();
        const pr = Math.min(h*.2, pw*.18);
        c.strokeStyle = 'rgba(125,237,171,.55)'; c.lineWidth = 1;
        c.beginPath(); c.arc(px+pw*.3, top+h*.5, pr, 0, 6.283); c.stroke();
        led(px+pw*.3, top+h*.5, GREEN, .4, 2.2);
        led(px+pw*.68, top+h*.36, CYAN, rand(1,3), 1.7);
        led(px+pw*.68, top+h*.64, GREEN, .7, 1.7);
      } else if (type==='switch'){
        // status cluster (SYS / PWR / FAN)
        c.fillStyle = 'rgba(8,14,24,.6)'; c.fillRect(L,top+h*.18,IW*.1,h*.64);
        led(L+IW*.03, top+h*.34, GREEN, .5, 1.5);
        led(L+IW*.07, top+h*.34, GREEN, .8, 1.5);
        led(L+IW*.03, top+h*.66, CYAN, rand(1,3), 1.5);
        // two blocks of 6×2 RJ45 ports
        const pw = IW*.04, pg = IW*.008, blockGap = IW*.03;
        let px = L+IW*.13;
        for (let blk=0;blk<2;blk++){
          c.fillStyle = 'rgba(4,8,15,.55)'; rr(c,px-1.5,top+h*.1,6*pw+5*pg+3,h*.8,1.5); c.fill();
          for (let p=0;p<6;p++){
            for (let r=0;r<2;r++){
              const xx = px + p*(pw+pg), yy = top + h*(.16 + r*.38), ph = h*.3;
              c.fillStyle = '#06090d'; c.fillRect(xx,yy,pw,ph);
              c.fillStyle = 'rgba(149,173,201,.22)'; c.fillRect(xx,yy,pw,1);           // metal shield edge
              c.fillStyle = '#06090d'; c.fillRect(xx+pw*.3, r ? yy+ph : yy-1, pw*.4, 1);  // latch notch
              if (Math.random()<.75) led(xx+pw*.78, r ? yy+ph-1.2 : yy+1.2, Math.random()<.85?GREEN:AMBER, rand(4,11), 1.2);
            }
          }
          px += 6*pw + 5*pg + blockGap;
        }
        // SFP uplink cages
        const sx0 = L+IW*.78, sw = IW*.045;
        for (let s2=0;s2<4;s2++){
          const xx = sx0 + s2*(sw+IW*.008);
          c.fillStyle = '#626e81'; c.fillRect(xx,top+h*.24,sw,h*.5);
          c.fillStyle = '#080c12'; c.fillRect(xx+1,top+h*.24+1.5,sw-2,h*.5-3);
          led(xx+sw/2, top+h*.16, CYAN, rand(2,6), 1.2);
        }
      } else { // router
        // two line-card module slots
        const mx0 = L, mw = IW*.3, mg = IW*.02;
        for (let m=0;m<2;m++){
          const mx = mx0 + m*(mw+mg), my = top+h*.12, mh = h*.76;
          c.fillStyle = '#202a39'; rr(c,mx,my,mw,mh,1.5); c.fill();
          c.strokeStyle = 'rgba(170,198,226,.18)'; c.lineWidth = 1; c.stroke();
          c.fillStyle = 'rgba(157,178,203,.5)';
          c.beginPath(); c.arc(mx+mw*.06,my+mh*.5,Math.max(.8,w*.008),0,6.283); c.arc(mx+mw*.94,my+mh*.5,Math.max(.8,w*.008),0,6.283); c.fill();
          if (m===0){
            for (let p=0;p<4;p++){
              const xx = mx+mw*(.14+p*.19), yy = my+mh*.3;
              c.fillStyle = '#626e81'; c.fillRect(xx,yy,mw*.15,mh*.42);
              c.fillStyle = '#080c12'; c.fillRect(xx+1,yy+1.5,mw*.15-2,mh*.42-3);
              led(xx+mw*.075, my+mh*.18, GREEN, rand(3,8), 1.3);
            }
          } else {
            c.fillStyle = 'rgba(0,0,0,.4)';
            for (let k=0;k<6;k++) c.fillRect(mx+mw*(.16+k*.12), my+mh*.25, 1, mh*.5);  // blank panel vents
          }
        }
        // management + console ports
        const cx0 = L+IW*.66;
        c.fillStyle = '#06090d'; c.fillRect(cx0,top+h*.34,IW*.06,h*.32); c.fillRect(cx0+IW*.08,top+h*.34,IW*.06,h*.32);
        c.fillStyle = 'rgba(149,173,201,.22)'; c.fillRect(cx0,top+h*.34,IW*.06,1); c.fillRect(cx0+IW*.08,top+h*.34,IW*.06,1);
        // status LEDs
        led(L+IW*.86, top+h*.35, GREEN, .5, 2);
        led(L+IW*.93, top+h*.35, CYAN, rand(1,3), 2);
        led(L+IW*.86, top+h*.66, GREEN, rand(2,5), 2);
        led(L+IW*.93, top+h*.66, AMBER, rand(.3,.8), 2);
      }
    }
    // front edge rim light
    c.strokeStyle = 'rgba(164,206,238,.3)'; c.lineWidth = 1; c.strokeRect(x+.5,t+.5,w-1,SH-1);

    /* ---- top cover ---- */
    const tg = c.createLinearGradient(x,t,x+w+dx,t-dy);
    tg.addColorStop(0,'#40516a'); tg.addColorStop(1,'#232e41');
    c.fillStyle = tg;
    c.beginPath(); c.moveTo(x,t); c.lineTo(x+w,t); c.lineTo(x+w+dx,t-dy); c.lineTo(x+dx,t-dy); c.closePath(); c.fill();
    c.strokeStyle = 'rgba(175,220,241,.6)'; c.lineWidth = 1; c.stroke();
    const P = (uu,v) => [x + uu*w + v*dx, t - v*dy];
    // seam + rear vent slots
    c.strokeStyle = 'rgba(0,0,0,.3)';
    { const [a1,b1]=P(.03,.18),[a2,b2]=P(.97,.18); c.beginPath(); c.moveTo(a1,b1); c.lineTo(a2,b2); c.stroke(); }
    c.strokeStyle = 'rgba(7,12,22,.55)';
    for (let k=0;k<9;k++){ const uu=.12+k*.085; const [p1,q1]=P(uu,.62),[p2,q2]=P(uu,.9); c.beginPath(); c.moveTo(p1,q1); c.lineTo(p2,q2); c.stroke(); }
    if (type==='router'){
      // engraved router glyph
      const [cx,cy] = P(.5,.4), ew = w*.16, eh = dy*.2;
      c.strokeStyle = 'rgba(200,232,246,.55)'; c.lineWidth = 1.1;
      c.beginPath(); c.ellipse(cx,cy,ew,eh,0,0,6.283); c.stroke();
      const arrow = (x1,y1,x2,y2) => { c.beginPath(); c.moveTo(x1,y1); c.lineTo(x2,y2); c.stroke();
        const a=Math.atan2(y2-y1,x2-x1),s=2.6; c.beginPath(); c.moveTo(x2,y2); c.lineTo(x2-s*Math.cos(a-.5),y2-s*Math.sin(a-.5)); c.moveTo(x2,y2); c.lineTo(x2-s*Math.cos(a+.5),y2-s*Math.sin(a+.5)); c.stroke(); };
      arrow(cx-ew*.85,cy,cx-ew*.3,cy); arrow(cx+ew*.85,cy,cx+ew*.3,cy);
    } else {
      // small label plate
      const [l1,m1]=P(.08,.3),[l2,m2]=P(.34,.3),[l3,m3]=P(.34,.48),[l4,m4]=P(.08,.48);
      c.fillStyle = 'rgba(207,228,246,.14)';
      c.beginPath(); c.moveTo(l1,m1); c.lineTo(l2,m2); c.lineTo(l3,m3); c.lineTo(l4,m4); c.closePath(); c.fill();
    }
    // specular sheen along the front-top edge
    const strip = c.createLinearGradient(x,0,x+w,0);
    strip.addColorStop(0,'rgba(142,212,237,0)'); strip.addColorStop(.5,'rgba(184,230,244,.75)'); strip.addColorStop(1,'rgba(142,212,237,0)');
    c.fillStyle = strip; c.fillRect(x,t-.5,w,1.5);
    // floor glow line
    const fl = c.createLinearGradient(x,0,x+w,0);
    fl.addColorStop(0,'rgba(107,191,230,0)'); fl.addColorStop(.5,'rgba(143,217,238,.7)'); fl.addColorStop(1,'rgba(107,191,230,0)');
    c.fillStyle = fl; c.fillRect(x,y-1,w,1.5);
  }

  // The VAULT: three stacked storage disks with a padlock on top
  function drawVault(c,v){
    const {x,y,R,ry,dh,vgap} = v;
    for (let i=0;i<3;i++){
      const by = y - i*(dh+vgap), ty = by - dh;
      const g = c.createLinearGradient(x-R,0,x+R,0);
      g.addColorStop(0,'#16294c'); g.addColorStop(.42,'#395d92'); g.addColorStop(.58,'#4b75b0'); g.addColorStop(1,'#112142');
      c.fillStyle = g;
      c.beginPath(); c.moveTo(x-R,ty); c.lineTo(x-R,by); c.ellipse(x,by,R,ry,0,Math.PI,0,true);
      c.lineTo(x+R,ty); c.ellipse(x,ty,R,ry,0,0,Math.PI,false); c.closePath(); c.fill();
      // glowing rim at the base of each disk
      c.strokeStyle='rgba(142,212,237,.85)'; c.lineWidth=1.5; c.shadowColor='#62c4e6'; c.shadowBlur=8;
      c.beginPath(); c.ellipse(x,by,R,ry,0,0,Math.PI); c.stroke(); c.shadowBlur=0;
      // seam just under the top edge
      c.strokeStyle='rgba(208,233,247,.35)'; c.lineWidth=1;
      c.beginPath(); c.ellipse(x,ty+dh*.12,R,ry,0,.15,Math.PI-.15); c.stroke();
      // activity LEDs along the curved front
      for (let k=0;k<5;k++){
        const lx = x - R*.55 + k*R*.27;
        const ly = ty + dh*.55 + ry*Math.sqrt(Math.max(0,1-((lx-x)/R)**2));
        led(lx, ly, k===0?GREEN:CYAN, k===0?.5:rand(2,6), 2.4);
      }
    }
    // top cap
    const ty = v.topY;
    const cg = c.createRadialGradient(x,ty-ry*.3,0,x,ty,R);
    cg.addColorStop(0,'#79a3d7'); cg.addColorStop(1,'#3c6197');
    c.fillStyle = cg; c.beginPath(); c.ellipse(x,ty,R,ry,0,0,6.283); c.fill();
    c.strokeStyle='rgba(221,240,249,.75)'; c.lineWidth=1.2; c.stroke();
    // padlock emblem, foreshortened onto the lid
    c.save(); c.translate(x,ty); c.scale(1,.6);
    const lw = R*.36, lh = R*.26;
    c.strokeStyle='rgba(242,249,253,.95)'; c.lineWidth=2.2;
    c.beginPath(); c.arc(0,-lh*.5,lw*.3,Math.PI,0); c.stroke();
    c.fillStyle='rgba(242,249,253,.95)'; rr(c,-lw/2,-lh*.5,lw,lh,3); c.fill();
    c.fillStyle='#3c6197'; c.beginPath(); c.arc(0,-lh*.05,lh*.14,0,6.283); c.fill();
    c.restore();
    // label
    c.font = `700 ${small?9:11}px ${FONT}`; c.textAlign='center';
    if ('letterSpacing' in c) c.letterSpacing = small ? '1.5px' : '2.5px';
    c.fillStyle='rgba(212,234,247,.85)';
    c.fillText('CONFIG BACKUP', x, y + ry + (small?13:18));
    if ('letterSpacing' in c) c.letterSpacing = '0px';
  }

  // RADIUS / AAA: same blue-steel palette and glowing cyan rim as the backup store, a shield-and-check emblem
  function drawAAA(c,n){
    const {x,y,r} = n;
    const pg = c.createRadialGradient(x,y,0,x,y,r*2.4);
    pg.addColorStop(0,'rgba(86,163,222,.22)'); pg.addColorStop(1,'rgba(86,163,222,0)');
    c.fillStyle = pg; c.beginPath(); c.arc(x,y,r*2.4,0,6.283); c.fill();
    c.strokeStyle = 'rgba(142,212,237,.2)'; c.lineWidth = 1; c.beginPath(); c.arc(x,y,r*1.4,0,6.283); c.stroke();
    const dg = c.createLinearGradient(x-r,y,x+r,y);
    dg.addColorStop(0,'#16294c'); dg.addColorStop(.42,'#395d92'); dg.addColorStop(.58,'#4b75b0'); dg.addColorStop(1,'#112142');
    c.fillStyle = dg; c.beginPath(); c.arc(x,y,r,0,6.283); c.fill();
    c.strokeStyle = 'rgba(142,212,237,.85)'; c.lineWidth = 1.5; c.shadowColor = '#62c4e6'; c.shadowBlur = 8;
    c.beginPath(); c.arc(x,y,r,0,6.283); c.stroke(); c.shadowBlur = 0;
    c.strokeStyle = 'rgba(208,233,247,.3)'; c.lineWidth = 1; c.beginPath(); c.arc(x,y,r*.82,0,6.283); c.stroke();
    const s = r*.95;
    c.save(); c.translate(x,y);
    c.fillStyle = 'rgba(242,249,253,.96)';
    c.beginPath(); c.moveTo(0,-s*.5); c.lineTo(s*.38,-s*.34); c.lineTo(s*.38,s*.02);
    c.quadraticCurveTo(s*.36,s*.36,0,s*.52); c.quadraticCurveTo(-s*.36,s*.36,-s*.38,s*.02); c.lineTo(-s*.38,-s*.34); c.closePath(); c.fill();
    c.strokeStyle = '#3c6197'; c.lineWidth = Math.max(1.6, r*.09); c.lineCap = 'round'; c.lineJoin = 'round';
    c.beginPath(); c.moveTo(-s*.16,s*.02); c.lineTo(-s*.03,s*.15); c.lineTo(s*.19,-s*.12); c.stroke();
    c.restore();
    c.font = `700 ${small?9:11}px ${FONT}`; c.textAlign = 'center';
    if ('letterSpacing' in c) c.letterSpacing = small ? '1.5px' : '2.5px';
    c.fillStyle = 'rgba(212,234,247,.85)';
    c.fillText('RADIUS / AAA', x, y + r*1.4 + (small?13:17));
    if ('letterSpacing' in c) c.letterSpacing = '0px';
  }

  // file / config icon for travelling packets
  function docIcon(c,x,y,s,a){
    c.globalAlpha = a;
    const w = s*.8, h = s, f = s*.28;
    c.fillStyle='rgba(238,249,252,.95)';
    c.beginPath(); c.moveTo(x-w/2,y-h/2); c.lineTo(x+w/2-f,y-h/2); c.lineTo(x+w/2,y-h/2+f); c.lineTo(x+w/2,y+h/2); c.lineTo(x-w/2,y+h/2); c.closePath(); c.fill();
    c.fillStyle='rgba(60,97,151,.9)';
    for (let i=0;i<3;i++) c.fillRect(x-w/2+s*.14, y-h/2+s*(.38+i*.18), w*(i===2?.45:.65), Math.max(1,s*.07));
    c.globalAlpha = 1;
  }

  // icon: 'up' = a backup leaving a device, 'ok' = done, 'user' = someone logging in
  function addTag(x,y,text,icon,now){
    if (tags.length >= (small?1:3)) return;
    if (tags.some(t => Math.abs(t.x-x) < 60 && Math.abs(t.y-y) < 26)) return;   // never stack two labels
    tags.push({x,y,text,icon,t0:now});
  }
  // who logs in, and the access level RADIUS / AAA grants them (VAULT's three levels)
  // a level of null = RADIUS / AAA REJECTS the login (unknown user or wrong password)
  const LOGINS = [['ahsan','Super-admin'],['noc','Read-write'],['shamim','Super-admin'],['rouf','Read-only'],
                  ['guest',null],['unknown',null]];

  function drawTag(tg,now){
    const age = now - tg.t0, life = 2.4;
    if (age > life) return false;
    const a = age < .3 ? age/.3 : age > life-.5 ? (life-age)/.5 : 1;
    const yy = tg.y - age*8;
    ctx.font = `600 11px ${FONT}`;
    const tw = ctx.measureText(tg.text).width, pw = tw + 30, ph = 22;
    tg.x = Math.max(pw/2 + 6, Math.min(W - pw/2 - 6, tg.x));   // a long label near an edge stays on screen
    const ok = tg.icon === 'ok', no = tg.icon === 'no';
    ctx.globalAlpha = a;
    ctx.fillStyle = no ? 'rgba(48,16,26,.88)' : 'rgba(12,27,51,.85)'; rr(ctx, tg.x-pw/2, yy-ph, pw, ph, 11); ctx.fill();
    ctx.strokeStyle = ok ? 'rgba(110,231,214,.65)' : no ? 'rgba(255,123,136,.7)' : 'rgba(131,194,232,.55)'; ctx.lineWidth = 1; ctx.stroke();
    // icon: check = granted / saved, cross = rejected, arrow = backup leaving, person = someone logging in
    const ix = tg.x - pw/2 + 12, iy = yy - ph/2;
    ctx.strokeStyle = ok ? '#6ee7d6' : no ? '#ff7b88' : '#93d1ed'; ctx.lineWidth = 1.8; ctx.beginPath();
    if (ok){ ctx.moveTo(ix-4,iy); ctx.lineTo(ix-1,iy+3); ctx.lineTo(ix+4,iy-3); }
    else if (no){ ctx.moveTo(ix-3.5,iy-3.5); ctx.lineTo(ix+3.5,iy+3.5); ctx.moveTo(ix+3.5,iy-3.5); ctx.lineTo(ix-3.5,iy+3.5); }
    else if (tg.icon === 'user'){ ctx.arc(ix,iy-2.2,2.2,0,6.283); ctx.moveTo(ix+4,iy+4.5); ctx.arc(ix,iy+4.5,4,0,Math.PI,true); }
    else { ctx.moveTo(ix,iy+4); ctx.lineTo(ix,iy-4); ctx.moveTo(ix-3,iy-1); ctx.lineTo(ix,iy-4); ctx.lineTo(ix+3,iy-1); }
    ctx.stroke();
    ctx.fillStyle = '#e8f3fb'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(tg.text, ix + 9, iy + .5);
    ctx.textBaseline = 'alphabetic'; ctx.globalAlpha = 1;
    return true;
  }

  let last = 0;
  function frame(ms){
    const now = ms/1000, dt = Math.min(.05, now - (last || now)); last = now;
    if (!base || !base.width || !base.height){ if (!reduceMotion) requestAnimationFrame(frame); return; }
    ctx.setTransform(DPR,0,0,DPR,0,0);
    ctx.clearRect(0,0,W,H);
    ctx.drawImage(base,0,0,W,H);
    ctx.globalCompositeOperation = 'lighter';

    // flowing dashes along backup paths
    ctx.lineWidth = 1.4; ctx.setLineDash([3,11]); ctx.lineDashOffset = -now*28;
    flows.forEach(f => { ctx.strokeStyle = f.kind==='dev' ? 'rgba(149,209,237,.45)' : f.kind==='cauth' ? 'rgba(110,214,224,.2)' : 'rgba(149,209,237,.22)'; curve(ctx,f); ctx.stroke(); });
    ctx.strokeStyle = 'rgba(110,214,224,.3)';
    authFlows.forEach(f => { curve(ctx,f); ctx.stroke(); });
    ctx.setLineDash([]);

    // map dots with a gentle shimmer: one path per phase group instead of one fill per dot
    for (let b=0;b<DOT_BUCKETS;b++){
      ctx.fillStyle = `rgba(116,196,231,${.42 + .22*Math.sin(now*1.4 + b*6.283/DOT_BUCKETS)})`;
      ctx.beginPath();
      for (const d of mapDots) if (d.b === b){ ctx.moveTo(d.x+1.3,d.y); ctx.arc(d.x, d.y, 1.3, 0, 6.283); }
      ctx.fill();
    }
    // regional sites
    cities.forEach(cy => {
      const k = .6 + .4*Math.sin(now*2+cy.ph);
      spot(ctx, cy.x, cy.y, (cy.cap?26:15)*(.9+.2*k), cy.cap ? .95 : .55+.3*k);
    });

    // vault core glow + arrival pulses
    spot(ctx, vault.topX, vault.topY, vault.R*1.6*(1+.06*Math.sin(now*2)), .35+.1*Math.sin(now*2));
    pulses = pulses.filter(p => {
      const a = (now - p) / 1.3; if (a > 1) return false;
      ctx.strokeStyle = `rgba(142,212,237,${.7*(1-a)})`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.ellipse(vault.topX, vault.topY, vault.R*(1+a*.9), vault.ry*(1+a*.9), 0, 0, 6.283); ctx.stroke();
      return true;
    });

    // RADIUS / AAA glow + a ring each time a login request reaches it
    spot(ctx, aaa.x, aaa.y, aaa.r*2.6*(1+.05*Math.sin(now*2.3)), .22+.08*Math.sin(now*2.3));
    authPulses = authPulses.filter(p => {
      const a = (now - p.t) / 1.1; if (a > 1) return false;
      ctx.strokeStyle = p.bad ? `rgba(255,123,136,${.75*(1-a)})` : `rgba(142,212,237,${.7*(1-a)})`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(aaa.x, aaa.y, aaa.r*(1+a*.9), 0, 6.283); ctx.stroke();
      return true;
    });

    // server LEDs
    leds.forEach(l => {
      const on = .25 + .75*Math.max(0,Math.sin(now*l.sp+l.ph));
      ctx.fillStyle = `rgba(${l.c[0]},${l.c[1]},${l.c[2]},${on})`;
      const z = l.size || 3;
      ctx.fillRect(l.x-z/2,l.y-z/2,z,z);
      if (on > .8) spot(ctx,l.x,l.y,z*3,.45);
    });

    // packets: config files from devices, small pings from regional sites (to the backup store and to RADIUS / AAA)
    packets.forEach(p => {
      const prev = p.t;
      p.t += p.sp * dt;
      if (prev < 0 && p.t >= 0 && p.f.kind==='dev') addTag(p.f.dev.topX, p.f.dev.topY - 14, small ? 'Backing up' : `Backing up ${p.f.dev.file}`, 'up', now);
      if (p.t >= 1){
        if (p.f.kind==='cauth') authPulses.push({t:now, bad:false}); else pulses.push(now);
        if (p.f.kind==='dev') addTag(vault.topX, vault.topY - vault.R*.55, small ? 'Backup saved' : `${p.f.dev.name} · backup saved`, 'ok', now);
        p.t = p.f.kind==='dev' ? -rand(.8,2.2) : -rand(.5,2.5);
      }
      if (p.t < 0) return;
      const [x,y] = bez(p.f,p.t);
      if (p.f.kind==='dev'){
        for (let k=4;k>=1;k--){ const tt=p.t-k*.015; if (tt<0) continue; const [tx,ty]=bez(p.f,tt); spot(ctx,tx,ty,9-k,.4-k*.07); }
        spot(ctx,x,y,small?20:26,.6);
        ctx.globalCompositeOperation = 'source-over';
        docIcon(ctx,x,y,small?9:11,1);
        ctx.globalCompositeOperation = 'lighter';
      } else {
        spot(ctx,x,y,8,.8);
        if (p.f.kind==='cauth'){ ctx.fillStyle = 'rgba(110,231,214,.9)'; ctx.beginPath(); ctx.arc(x,y,1.7,0,6.283); ctx.fill(); }
      }
    });

    // logins: a blue Access-Request travels to RADIUS / AAA, a teal Access-Accept comes back
    // the story: "ahsan → login" at a device, then RADIUS / AAA answers "ahsan · Super-admin access",
    // or, for an unknown user / wrong password, "guest · access rejected" in red
    authPackets.forEach(p => {
      const prev = p.t;
      p.t += p.sp * dt;
      if (!p.back && prev < 0 && p.t >= 0){
        p.who = LOGINS[Math.floor(Math.random()*LOGINS.length)];
        if (!small) addTag(p.f.dev.topX, p.f.dev.topY - 40, `${p.who[0]} → login`, 'user', now);
      }
      if (p.t >= 1){
        if (!p.back){
          const [who, level] = p.who || LOGINS[0];
          p.back = true; p.t = 0; p.bad = !level; authPulses.push({t:now, bad:p.bad});
          if (p.bad) addTag(aaa.x, aaa.y - aaa.r*1.5, `${who} · access rejected`, 'no', now);
          else addTag(aaa.x, aaa.y - aaa.r*1.5, small ? `${who} · access granted` : `${who} · ${level} access`, 'ok', now);
        } else { p.back = false; p.t = -rand(1.4,3.2); }
      }
      if (p.t < 0) return;
      const tt = p.back ? 1 - p.t : p.t;
      // request: soft blue; answer: teal when granted, red when rejected
      const col = !p.back ? '150,190,255' : p.bad ? '255,123,136' : '110,231,214';
      for (let k=3;k>=1;k--){ const q = p.back ? tt + k*.02 : tt - k*.02; if (q<0||q>1) continue; const [qx,qy]=bez(p.f,q); spot(ctx,qx,qy,7-k,.35-k*.07); }
      const [x,y] = bez(p.f,tt);
      spot(ctx,x,y,small?14:18,.5);
      ctx.fillStyle = `rgb(${col})`; ctx.beginPath(); ctx.arc(x,y,small?2.4:3,0,6.283); ctx.fill();
    });

    // a few drifting motes
    motes.forEach(m => {
      m.y -= m.sp*dt; if (m.y < -10){ m.y = H+10; m.x = rand(0,W); }
      spot(ctx, m.x + Math.sin(now*.6+m.ph)*6, m.y, m.s*5, .25+.2*Math.sin(now+m.ph));
    });

    ctx.globalCompositeOperation = 'source-over';
    tags = tags.filter(tg => drawTag(tg,now));

    if (!reduceMotion) requestAnimationFrame(frame);
  }

  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { build(); if (reduceMotion) frame(performance.now()); }, 120); });
  build();
  requestAnimationFrame(frame);
})();

/* show / hide password */
document.getElementById('togglePassword').addEventListener('click', e => {
  const show = pwd.type === 'password';
  pwd.type = show ? 'text' : 'password';
  e.currentTarget.setAttribute('aria-pressed', show);
  e.currentTarget.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  pwd.focus();
});

/* caps lock warning */
const caps = document.getElementById('caps');
['keyup','keydown'].forEach(t => pwd.addEventListener(t, e => {
  if (e.getModifierState) caps.classList.toggle('on', e.getModifierState('CapsLock'));
}));
pwd.addEventListener('blur', () => caps.classList.remove('on'));

/* clear the invalid state while typing */
[user, pwd].forEach(i => i.addEventListener('input', () => i.parentElement.classList.remove('invalid')));

/* button ripple */
btn.addEventListener('pointerdown', e => {
  if (reduceMotion) return;
  const r = btn.getBoundingClientRect(), d = Math.max(r.width, r.height);
  const s = document.createElement('span');
  s.className = 'ripple';
  s.style.width = s.style.height = d + 'px';
  s.style.left = (e.clientX - r.left - d/2) + 'px';
  s.style.top = (e.clientY - r.top - d/2) + 'px';
  btn.appendChild(s);
  s.addEventListener('animationend', () => s.remove());
});

function setStatus(msg, cls){ statusEl.textContent = msg; statusEl.className = 'status ' + (cls || ''); }
function shake(){ form.classList.remove('shake'); void form.offsetWidth; form.classList.add('shake'); }

/* the server answered with an error (wrong password, lockout): the card shakes once on load */
form.addEventListener('animationend', e => { if (e.animationName === 'shake') form.classList.remove('shake'); });

form.addEventListener('submit', e => {
  const u = user.value.trim(), p = pwd.value, confirm = form.elements.confirm;
  user.parentElement.classList.toggle('invalid', !u);
  pwd.parentElement.classList.toggle('invalid', !p);
  if (!u || !p){ e.preventDefault(); setStatus('Username and password are required.', 'err'); shake(); (u ? pwd : user).focus(); return; }
  if (confirm && confirm.value !== p){
    e.preventDefault(); confirm.parentElement.classList.add('invalid');
    setStatus('The two passwords are different. Type the same password in both fields.', 'err'); shake(); confirm.focus(); return;
  }
  if (btn.disabled){ e.preventDefault(); return; }
  btn.disabled = true; btn.classList.add('loading');
  btnLabel.textContent = confirm ? 'Please wait…' : 'Signing in…';
  setStatus('', '');
});
