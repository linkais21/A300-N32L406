'use strict';
process.on('uncaughtException', err => console.error('[CRASH] uncaught:', err.message));
process.on('unhandledRejection', err => console.error('[CRASH] unhandled:', err));

const net       = require('net');
const http      = require('http');
const fs        = require('fs');
const path      = require('path');
const WebSocket = require('ws');
const { DatabaseSync } = require('node:sqlite');

const JT808_PORT           = 8898;
const HTTP_PORT            = 8080;
const HEARTBEAT_TIMEOUT_MS = 200000;

// ── DB ────────────────────────────────────────────────────────────────────────
const db = new DatabaseSync(path.join(__dirname, 'data.db'));
db.exec('PRAGMA journal_mode=WAL;');
db.exec(`
  CREATE TABLE IF NOT EXISTS devices (
    imei TEXT PRIMARY KEY, phone TEXT,
    first_seen INTEGER, last_seen INTEGER, online INTEGER DEFAULT 0,
    lat REAL, lon REAL, speed REAL, heading INTEGER, altitude INTEGER,
    acc_on INTEGER DEFAULT 0, gps_fixed INTEGER DEFAULT 0,
    satellites INTEGER DEFAULT 0, csq INTEGER DEFAULT 0,
    alarm_flags INTEGER DEFAULT 0, status_flags INTEGER DEFAULT 0,
    mileage INTEGER DEFAULT 0, voltage REAL DEFAULT 0,
    firmware TEXT, iccid TEXT, pid TEXT,
    last_online_start INTEGER DEFAULT 0
  );
  CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT, ts INTEGER,
    lat REAL, lon REAL, speed REAL, heading INTEGER, altitude INTEGER,
    acc_on INTEGER, gps_fixed INTEGER, satellites INTEGER, csq INTEGER,
    alarm_flags INTEGER, status_flags INTEGER, mileage INTEGER
  );
  CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT, ts INTEGER, type TEXT, detail TEXT, lat REAL, lon REAL, acked INTEGER DEFAULT 0
  );
  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT, ts INTEGER, type TEXT, data TEXT
  );
  CREATE TABLE IF NOT EXISTS blindzone (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT, ts INTEGER, lat REAL, lon REAL, speed REAL,
    heading INTEGER, uploaded INTEGER DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_loc ON locations(imei, ts);
  CREATE INDEX IF NOT EXISTS idx_alm ON alarms(imei, ts);
  CREATE INDEX IF NOT EXISTS idx_evt ON events(imei, ts);
`);
// migrate existing DB that may not have last_online_start column
try { db.exec(`ALTER TABLE devices ADD COLUMN last_online_start INTEGER DEFAULT 0`); } catch(e) {}

const Q = {
  upsertDev:   db.prepare(`INSERT INTO devices(imei,phone,first_seen,last_seen,online) VALUES(?,?,?,?,1)
                           ON CONFLICT(imei) DO UPDATE SET last_seen=excluded.last_seen,online=1`),
  setOnlineStart: db.prepare(`UPDATE devices SET last_online_start=? WHERE imei=?`),
  getOnlineStart: db.prepare(`SELECT last_online_start FROM devices WHERE imei=?`),
  updatePos:   db.prepare(`UPDATE devices SET lat=?,lon=?,speed=?,heading=?,altitude=?,acc_on=?,gps_fixed=?,
                           satellites=?,csq=?,alarm_flags=?,status_flags=?,mileage=?,last_seen=? WHERE imei=?`),
  updateInfo:  db.prepare(`UPDATE devices SET firmware=?,iccid=?,pid=?,last_seen=? WHERE imei=?`),
  updateVolt:  db.prepare(`UPDATE devices SET voltage=? WHERE imei=?`),
  setOffline:  db.prepare(`UPDATE devices SET online=0 WHERE imei=?`),
  insLoc:      db.prepare(`INSERT INTO locations(imei,ts,lat,lon,speed,heading,altitude,acc_on,gps_fixed,satellites,csq,alarm_flags,status_flags,mileage) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`),
  insAlarm:    db.prepare(`INSERT INTO alarms(imei,ts,type,detail,lat,lon) VALUES(?,?,?,?,?,?)`),
  insEvent:    db.prepare(`INSERT INTO events(imei,ts,type,data) VALUES(?,?,?,?)`),
  insBlind:    db.prepare(`INSERT INTO blindzone(imei,ts,lat,lon,speed,heading) VALUES(?,?,?,?,?,?)`),
  ackAlarm:    db.prepare(`UPDATE alarms SET acked=1 WHERE id=?`),
  getDevices:  db.prepare(`SELECT * FROM devices ORDER BY last_seen DESC`),
  getLocs:     db.prepare(`SELECT * FROM locations WHERE imei=? ORDER BY ts DESC LIMIT ?`),
  getTrack:    db.prepare(`SELECT * FROM locations WHERE imei=? AND ts>=? AND ts<=? ORDER BY ts ASC`),
  getAlarms:   db.prepare(`SELECT * FROM alarms WHERE imei=? ORDER BY ts DESC LIMIT 100`),
  getAlarmAll: db.prepare(`SELECT a.*,d.imei FROM alarms a JOIN devices d ON a.imei=d.imei WHERE a.acked=0 ORDER BY a.ts DESC LIMIT 50`),
  getEvents:   db.prepare(`SELECT * FROM events WHERE imei=? ORDER BY ts DESC LIMIT 200`),
  getBlind:    db.prepare(`SELECT * FROM blindzone WHERE imei=? AND uploaded=0 ORDER BY ts ASC LIMIT 100`),
  markBlind:   db.prepare(`UPDATE blindzone SET uploaded=1 WHERE id=?`),
};

// ── JT808 codec ───────────────────────────────────────────────────────────────
const FLAG=0x7E, ESC=0x7D;

function unescape808(raw) {
  const out=[];
  for(let i=0;i<raw.length;i++){
    if(raw[i]===ESC&&i+1<raw.length){
      if(raw[i+1]===0x02){out.push(FLAG);i++;}
      else if(raw[i+1]===0x01){out.push(ESC);i++;}
      else out.push(raw[i]);
    } else out.push(raw[i]);
  }
  return Buffer.from(out);
}

function bcd2str(buf){ return buf.reduce((s,b)=>s+((b>>4)&0xF).toString()+(b&0xF).toString(),''); }
function str2bcd(s,len){
  const out=Buffer.alloc(len,0);
  for(let i=0;i<len;i++){
    const h=s[i*2]?(s[i*2]-'0'):0, l=s[i*2+1]?(s[i*2+1]-'0'):0;
    out[i]=(h<<4)|l;
  }
  return out;
}
function bcdTime2ms(b){
  const [yy,mo,dd,hh,mm,ss]=[...b].map(x=>((x>>4)*10)+(x&0xF));
  return Date.UTC(2000+yy,mo-1,dd,hh-8,mm,ss);
}

function parseLoc(body){
  if(body.length<28)return null;
  const alarm=body.readUInt32BE(0), status=body.readUInt32BE(4);
  const latr=body.readUInt32BE(8), lonr=body.readUInt32BE(12);
  const alt=body.readUInt16BE(16), spd=body.readUInt16BE(18)/10;
  const hdg=body.readUInt16BE(20), ts=bcdTime2ms(body.slice(22,28));
  const lat=latr/1e6*((status&0x08)?-1:1);
  const lon=lonr/1e6*((status&0x04)?-1:1);
  let sat=0,csq=0,mlg=0; let p=28;
  while(p+2<=body.length){
    const id=body[p],len=body[p+1]; p+=2;
    if(id===0x31&&len>=1)sat=body[p];
    if(id===0x30&&len>=1)csq=body[p];
    if(id===0x01&&len>=4)mlg=body.readUInt32BE(p);
    if(id===0xE2&&len>=2){}  // voltage extra info
    p+=len;
  }
  return{alarm,status,lat,lon,alt,spd,hdg,ts,
    acc_on:(status&0x01)?1:0, gps_fixed:(status&0x02)?1:0,
    satellites:sat,csq,mileage:mlg};
}

function buildFrame(msgId,phone6,body,sn){
  const total=12+body.length+1;
  const raw=Buffer.alloc(total);
  raw.writeUInt16BE(msgId,0);
  raw.writeUInt16BE(body.length&0x03FF,2);
  phone6.copy(raw,4);
  raw.writeUInt16BE(sn&0xFFFF,10);
  body.copy(raw,12);
  let cs=0; for(let i=0;i<total-1;i++) cs^=raw[i];
  raw[total-1]=cs;
  const out=[FLAG];
  for(let i=0;i<total;i++){
    const b=raw[i];
    if(b===FLAG){out.push(ESC,0x02);}
    else if(b===ESC){out.push(ESC,0x01);}
    else out.push(b);
  }
  out.push(FLAG);
  return Buffer.from(out);
}

function resp8001(phone6,sn,msgId,result=0){
  const b=Buffer.alloc(5);
  b.writeUInt16BE(sn,0); b.writeUInt16BE(msgId,2); b[4]=result;
  return buildFrame(0x8001,phone6,b,sn+100);
}

// alarm type decode
const ALARM_BITS={
  0:'紧急报警(SOS)',1:'超速报警',2:'疲劳驾驶',3:'危险驾驶行为',
  4:'GNSS模块故障',5:'GNSS天线未接',6:'GNSS天线短路',7:'终端主电源欠压',
  8:'终端主电源掉电',9:'终端LCD故障',10:'TTS模块故障',11:'摄像头故障',
  18:'当天累计驾驶超时',19:'超时停车',20:'进出区域',21:'进出路线',
  22:'路段行驶时间不足/过长',23:'路线偏离报警',24:'车辆VSS故障',
  25:'车辆油量异常',26:'车辆被盗',27:'车辆非法点火',28:'车辆非法位移',
  29:'碰撞侧翻报警',30:'侧翻报警',31:'非法开门报警'
};

function decodeAlarms(flags){
  const types=[];
  for(let i=0;i<32;i++) if(flags&(1<<i)) types.push(ALARM_BITS[i]||`报警位${i}`);
  return types;
}

// ── Sessions ──────────────────────────────────────────────────────────────────
const sessions=new Map(); // imei->{socket,hbTimer,first_connected,sn}
let snCounter=1;

function nextSn(){ return snCounter=(snCounter+1)&0xFFFF; }

function broadcastWs(msg){
  const s=JSON.stringify(msg);
  for(const c of wss.clients) if(c.readyState===WebSocket.OPEN) c.send(s);
}

function markOffline(imei){
  const sess=sessions.get(imei);
  if(!sess)return;
  clearTimeout(sess.hbTimer);
  clearTimeout(sess.socket && sess.socket._hbTimer);
  sessions.delete(imei);
  Q.setOffline.run(imei);
  Q.setOnlineStart.run(0,imei);   // clear so next connect starts fresh
  Q.insEvent.run(imei,Date.now(),'offline',null);
  broadcastWs({type:'offline',imei,ts:Date.now()});
  console.log(`[808] offline ${imei}`);
}

function resetHb(imei,socket){
  // cancel all existing timers for this socket
  clearTimeout(socket._hbTimer);
  const sess=sessions.get(imei);
  if(sess) clearTimeout(sess.hbTimer);
  const t=setTimeout(()=>{
    // only fire if this socket is still the active session
    const cur=sessions.get(imei);
    if(cur && cur.socket===socket){
      console.log(`[808] hb timeout ${imei}`);
      markOffline(imei);
    }
    socket.destroy();
  },HEARTBEAT_TIMEOUT_MS);
  socket._hbTimer=t;
  if(sess && sess.socket===socket) sess.hbTimer=t;
}

// ── TCP server ────────────────────────────────────────────────────────────────
const tcp=net.createServer(socket=>{
  let rxBuf=Buffer.alloc(0);
  let imei=null, phone6=null;

  function processFrame(raw){
    const frame=unescape808(raw);
    if(frame.length<13)return;
    const cs_calc=frame.slice(0,frame.length-1).reduce((a,b)=>a^b,0);
    if(cs_calc!==frame[frame.length-1])return;

    const msgId=frame.readUInt16BE(0);
    const bodyLen=frame.readUInt16BE(2)&0x03FF;
    phone6=frame.slice(4,10);
    const sn=frame.readUInt16BE(10);
    const body=frame.slice(12,12+bodyLen);
    const now=Date.now();

    // keep-alive
    if(imei) resetHb(imei,socket);

    switch(msgId){
      case 0x0100:{ // register
        const ph=bcd2str(phone6).replace(/^0+/,'');
        imei=ph;
        Q.upsertDev.run(imei,ph,now,now);
        Q.insEvent.run(imei,now,'register',null);
        const auth=Buffer.from('A300AUTH');
        const rb=Buffer.alloc(3+auth.length);
        rb.writeUInt16BE(sn,0); rb[2]=0; auth.copy(rb,3);
        socket.write(buildFrame(0x8100,phone6,rb,nextSn()));
        console.log(`[808] register ${imei}`);
        break;
      }
      case 0x0102:{ // auth
        imei=imei||bcd2str(phone6).replace(/^0+/,'');
        Q.upsertDev.run(imei,bcd2str(phone6),now,now);
        if(!sessions.has(imei)){
          // restore last_online_start from DB so uptime survives server restarts
          const row=Q.getOnlineStart.get(imei);
          const fc=(row&&row.last_online_start)?row.last_online_start:now;
          Q.setOnlineStart.run(fc,imei);
          sessions.set(imei,{socket,hbTimer:socket._hbTimer||null,first_connected:fc});
          broadcastWs({type:'online',imei,ts:now,first_connected:fc});
        }
        resetHb(imei,socket);
        Q.insEvent.run(imei,now,'auth',JSON.stringify({imei,phone:bcd2str(phone6)}));
        socket.write(resp8001(phone6,sn,0x0102,0));
        console.log(`[808] auth OK ${imei}`);
        break;
      }
      case 0x0002:{ // heartbeat
        imei=imei||bcd2str(phone6).replace(/^0+/,'');
        Q.upsertDev.run(imei,bcd2str(phone6),now,now);
        if(!sessions.has(imei)){
          const row=Q.getOnlineStart.get(imei);
          const fc=(row&&row.last_online_start)?row.last_online_start:now;
          Q.setOnlineStart.run(fc,imei);
          sessions.set(imei,{socket,hbTimer:socket._hbTimer||null,first_connected:fc});
          broadcastWs({type:'online',imei,ts:now,first_connected:fc});
        }
        resetHb(imei,socket);
        socket.write(resp8001(phone6,sn,0x0002,0));
        Q.insEvent.run(imei,now,'heartbeat',null);
        broadcastWs({type:'heartbeat',imei,ts:now});
        break;
      }
      case 0x0200:{ // location
        const loc=parseLoc(body);
        if(!loc)break;
        imei=imei||bcd2str(phone6).replace(/^0+/,'');
        Q.upsertDev.run(imei,bcd2str(phone6),now,now);
        if(!sessions.has(imei)){
          const row=Q.getOnlineStart.get(imei);
          const fc=(row&&row.last_online_start)?row.last_online_start:now;
          Q.setOnlineStart.run(fc,imei);
          sessions.set(imei,{socket,hbTimer:null,first_connected:fc});
          broadcastWs({type:'online',imei,ts:now,first_connected:fc});
        }
        Q.updatePos.run(loc.lat,loc.lon,loc.spd,loc.hdg,loc.alt,
          loc.acc_on,loc.gps_fixed,loc.satellites,loc.csq,
          loc.alarm,loc.status,loc.mileage,now,imei);
        Q.insLoc.run(imei,loc.ts,loc.lat,loc.lon,loc.spd,loc.hdg,loc.alt,
          loc.acc_on,loc.gps_fixed,loc.satellites,loc.csq,
          loc.alarm,loc.status,loc.mileage);
        // alarm handling
        if(loc.alarm){
          decodeAlarms(loc.alarm).forEach(type=>{
            Q.insAlarm.run(imei,now,type,'0x'+loc.alarm.toString(16).padStart(8,'0'),loc.lat,loc.lon);
          });
          broadcastWs({type:'alarm',imei,ts:now,alarm:loc.alarm,lat:loc.lat,lon:loc.lon,
            types:decodeAlarms(loc.alarm)});
        }
        resetHb(imei,socket);
        socket.write(resp8001(phone6,sn,0x0200,0));
        Q.insEvent.run(imei,now,'location',JSON.stringify({
          lat:loc.lat,lon:loc.lon,spd:loc.spd,hdg:loc.hdg,alt:loc.alt,
          acc_on:loc.acc_on,gps_fixed:loc.gps_fixed,
          satellites:loc.satellites,csq:loc.csq,mileage:loc.mileage,
          alarm:loc.alarm?'0x'+loc.alarm.toString(16).padStart(8,'0'):null,
          status:'0x'+loc.status.toString(16).padStart(8,'0')
        }));
        broadcastWs({type:'location',imei,...loc,ts:now});
        break;
      }
      case 0x0201:{ // blind zone upload  
        const loc=parseLoc(body);
        if(!loc)break;
        imei=imei||bcd2str(phone6).replace(/^0+/,'');
        Q.insBlind.run(imei,loc.ts,loc.lat,loc.lon,loc.spd,loc.hdg);
        Q.markBlind.run(0); // mark immediately as processed
        Q.insLoc.run(imei,loc.ts,loc.lat,loc.lon,loc.spd,loc.hdg,loc.alt,
          loc.acc_on,loc.gps_fixed,loc.satellites,loc.csq,loc.alarm,loc.status,loc.mileage);
        socket.write(resp8001(phone6,sn,0x0201,0));
        broadcastWs({type:'blindzone',imei,...loc});
        break;
      }
      case 0x0107:{ // terminal info
        // body: hardware_ver(1)+firmware_ver(1)+ICCID(20)+...
        let fw='', iccid='', pid='';
        if(body.length>=2){
          const hv=body[0], sv=body[1];
          fw=`HW${hv} SW${sv}`;
        }
        // parse TLV attributes  
        try{
          // firmware string may appear later; just grab raw hex for now
          fw=body.slice(0,Math.min(body.length,64)).toString('hex');
        }catch(e){}
        imei=imei||bcd2str(phone6).replace(/^0+/,'');
        Q.updateInfo.run(fw,iccid,pid,now,imei);
        Q.insEvent.run(imei,now,'info',JSON.stringify({fw}));
        socket.write(resp8001(phone6,sn,0x0107,0));
        break;
      }
      case 0x0301:{ // device text reply (response to our 0x8300 command)
        if(body.length>=2){
          const text=body.slice(1).toString('utf8').replace(/\r\n$/,'').replace(/\r$/,'').replace(/\n$/,'');
          if(imei) Q.insEvent.run(imei,now,'cmd_reply',text);
          broadcastWs({type:'cmd_reply',imei,ts:now,text});
        }
        break;
      }
      case 0x8300:{ // platform->device text passthrough, no action needed
        break;
      }
      default:
        if(phone6) socket.write(resp8001(phone6,sn,msgId,0));
        break;
    }
  }

  socket.on('data',chunk=>{
    rxBuf=Buffer.concat([rxBuf,chunk]);
    let start=-1;
    for(let i=0;i<rxBuf.length;i++){
      if(rxBuf[i]===FLAG){
        if(start===-1){start=i;}
        else if(i>start+1){ processFrame(rxBuf.slice(start+1,i)); start=i; }
        else{start=i;}
      }
    }
    rxBuf=start>=0?rxBuf.slice(start):Buffer.alloc(0);
    if(rxBuf.length>8192)rxBuf=Buffer.alloc(0);
  });
  socket.on('close',()=>markOffline(imei));
  socket.on('error',()=>markOffline(imei));
});

tcp.listen(JT808_PORT,()=>console.log(`[TCP] JT808 :${JT808_PORT}`));

// ── AT command sender (JT808 0x8300 text message) ────────────────────────────
function sendCmd(imei,cmd){
  const sess=sessions.get(imei);
  if(!sess||!sess.socket)return{ok:false,msg:'设备不在线'};
  const ph=imei.padStart(12,'0');
  const phone6=str2bcd(ph,6);
  // strip trailing # if already present, then add once
  const cmdClean=cmd.replace(/#$/, '');
  const txt=Buffer.from(cmdClean+'#','utf8');
  const body=Buffer.alloc(1+txt.length);
  body[0]=0x01; // flag: display
  txt.copy(body,1);
  console.log(`[808] sendCmd to ${imei}: ${cmdClean}#`);
  try{
    sess.socket.write(buildFrame(0x8300,phone6,body,nextSn()));
    Q.insEvent.run(imei,Date.now(),'cmd_sent',cmdClean+'#');
    return{ok:true};
  }catch(e){
    console.error(`[808] sendCmd error: ${e.message}`);
    return{ok:false,msg:e.message};
  }
}

// ── HTTP API ──────────────────────────────────────────────────────────────────
function parseBody(req){
  return new Promise(res=>{
    let d=''; req.on('data',c=>d+=c); req.on('end',()=>{try{res(JSON.parse(d));}catch{res({});}});
  });
}

const httpServer=http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://x');
  const url=u.pathname, qs=Object.fromEntries(u.searchParams);

  res.setHeader('Access-Control-Allow-Origin','*');
  if(req.method==='OPTIONS'){res.writeHead(204);res.end();return;}

  // static
  if(url==='/'||url==='/index.html'){
    res.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});
    res.end(fs.readFileSync(path.join(__dirname,'public','index.html')));
    return;
  }

  res.setHeader('Content-Type','application/json;charset=utf-8');

  if(url==='/api/devices'){
    const devs=Q.getDevices.all().map(d=>({
      ...d,
      uptime_ms:sessions.has(d.imei)?Date.now()-sessions.get(d.imei).first_connected:0,
      is_session_live:sessions.has(d.imei)
    }));
    res.end(JSON.stringify(devs));return;
  }
  if(url==='/api/locations'){
    const{imei,limit=200}=qs;
    if(!imei){res.writeHead(400);res.end('{}');return;}
    res.end(JSON.stringify(Q.getLocs.all(imei,parseInt(limit))));return;
  }
  if(url==='/api/track'){
    const{imei,from,to}=qs;
    if(!imei){res.writeHead(400);res.end('{}');return;}
    const f=from?parseInt(from):Date.now()-86400000;
    const t=to?parseInt(to):Date.now();
    res.end(JSON.stringify(Q.getTrack.all(imei,f,t)));return;
  }
  if(url==='/api/alarms'){
    const{imei}=qs;
    if(imei) res.end(JSON.stringify(Q.getAlarms.all(imei)));
    else res.end(JSON.stringify(Q.getAlarmAll.all()));
    return;
  }
  if(url==='/api/events'){
    const{imei}=qs;
    if(!imei){res.writeHead(400);res.end('{}');return;}
    res.end(JSON.stringify(Q.getEvents.all(imei)));return;
  }
  if(url==='/api/ack_alarm'&&req.method==='POST'){
    const{id}=await parseBody(req);
    Q.ackAlarm.run(id);
    res.end('{"ok":true}');return;
  }
  if(url==='/api/cmd'&&req.method==='POST'){
    const{imei,cmd}=await parseBody(req);
    if(!imei||!cmd){res.writeHead(400);res.end('{}');return;}
    const r=sendCmd(imei,cmd);
    res.end(JSON.stringify(r));return;
  }
  res.writeHead(404);res.end('{}');
});

const wss=new WebSocket.Server({server:httpServer});
wss.on('connection',ws=>{
  const devs=Q.getDevices.all().map(d=>({
    ...d,
    online:sessions.has(d.imei)?1:0,
    uptime_ms:sessions.has(d.imei)?Date.now()-sessions.get(d.imei).first_connected:0
  }));
  ws.send(JSON.stringify({type:'init',devices:devs}));
  // push unacked alarms
  ws.send(JSON.stringify({type:'alarms_unacked',alarms:Q.getAlarmAll.all()}));
});

httpServer.listen(HTTP_PORT,()=>console.log(`[HTTP] dashboard http://localhost:${HTTP_PORT}`));

// periodic uptime broadcast
setInterval(()=>{
  const online=[...sessions.keys()].map(imei=>({
    imei,uptime_ms:Date.now()-sessions.get(imei).first_connected
  }));
  if(online.length) broadcastWs({type:'uptime',devices:online,ts:Date.now()});
},10000);








