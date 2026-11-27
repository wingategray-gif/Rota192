const {chromium}=require('playwright');const fs=require('fs');const {execSync}=require('child_process');
// usage: node tests/e2e.js path/to/backup.json   (a backup downloaded from the app; it holds personal data, never commit it)
const path=require('path');const SBURL=(require('fs').readFileSync(path.join(__dirname,'..','index.html'),'utf8').match(/url:"(https:[^"]+)"/)||[])[1],LOCAL='http://127.0.0.1:8787',PAGE='file://'+path.join(__dirname,'..','index.html');
const BACKUP=process.argv[2];if(!BACKUP){console.log('usage: node tests/e2e.js backup.json');process.exit(1)}
let pass=0,fail=0;const ok=(c,m)=>{if(c)pass++;else{fail++;console.log('FAIL:',m)}};
const PSQL=process.env.CREW_TEST_PSQL||'psql -h /var/run/postgresql -U postgres';const sql=q=>execSync(`${PSQL} -d crew -At -c "${q.replace(/"/g,'\\"')}"`).toString().trim();
(async()=>{const b=await chromium.launch();
async function user(email,w=1100){const ctx=await b.newContext({viewport:{width:w,height:900}});const p=await ctx.newPage();p.errs=[];p.on('pageerror',e=>p.errs.push(e.message));
  await ctx.route(SBURL+'/**',async r=>{const u=new URL(r.request().url());if(u.pathname.startsWith('/realtime'))return r.abort();
    try{const res=await r.fetch({url:LOCAL+u.pathname+u.search});await r.fulfill({response:res})}catch(e){await r.abort()}});
  await ctx.route(/^wss?:/,r=>r.abort());
  await p.goto(PAGE);await p.waitForTimeout(500);
  if(email){await p.fill('#gt-email',email);await p.click('#gt-send');await p.waitForSelector('#gt-code');await p.fill('#gt-code','123456');await p.click('#gt-c button');await p.waitForTimeout(1200)}
  return p}
const tabs=p=>p.$$eval('[data-crv]',e=>e.filter(x=>getComputedStyle(x).display!=='none').map(x=>x.dataset.crv).join(','));
const toast=p=>p.$eval('#toast',e=>e.hidden?'':e.textContent);
// 1. signed out: gate
const anon=await user(null);ok(await anon.$eval('#app',e=>e.hidden)&&!!(await anon.$('#gt-email')),'signed out sees sign-in only');
// wrong code
await anon.fill('#gt-email','edward@example.com');await anon.click('#gt-send');await anon.waitForSelector('#gt-code');await anon.fill('#gt-code','999999');await anon.click('#gt-c button');await anon.waitForTimeout(500);
ok(/didn't work/.test(await toast(anon)),'wrong code refused');await anon.context().close();
// 2. owner
const own=await user('edward@example.com');
ok(!(await own.$eval('#app',e=>e.hidden)),'owner gets in');ok(/owner/i.test(await own.$eval('#rolebar',e=>e.innerText)),'shown as owner');
// restore the backup
await own.click('[data-crv="set"]');await own.setInputFiles('#bk-file',BACKUP);await own.waitForTimeout(300);
await own.click('#bk-restore');await own.click('#bk-restore');await own.waitForTimeout(4000);
const n=sql("select (select count(*) from people)||'/'||(select count(*) from rotations)||'/'||(select count(*) from accom)||'/'||(select count(*) from training)||'/'||(select count(*) from away)||'/'||(select count(*) from log)");
console.log('after restore people/rots/accom/training/away/log:',n,'|',await toast(own));
const B=JSON.parse(fs.readFileSync(BACKUP,'utf8'));const nr=B.rota.people.reduce((a,p)=>a+p.rots.length,0);
ok(n.startsWith(B.rota.people.length+'/'+nr+'/'),'all people and rotations saved');
// reload: data comes back from the database
await own.reload();await own.waitForTimeout(2000);
const cnt=await own.evaluate(()=>[R.people.length,R.people.reduce((a,p)=>a+p.rots.length,0),Object.keys(A.assign).length,(R.log||[]).length]);console.log('reloaded',cnt);
ok(cnt[0]===B.rota.people.length&&cnt[1]===nr,'reload shows the same rota');
ok(cnt[2]===Object.keys(B.accom.assign).length,'accommodation came back');
await own.click('[data-crv="acc"]');console.log('who where:',(await own.$eval('#cr-acc-where',e=>e.innerText.replace(/\n/g,' '))).slice(0,200));
// add Craig Barton's email via Edit
const craig=B.rota.people.find(p=>p.name==='Craig Allen');
await own.click('[data-crv="pp"]');await own.fill('#cr-q','Craig Allen');await own.waitForTimeout(200);
const eb=await own.$('#cr-people .cr-card [data-cre="editPerson"]');ok(!!eb,'edit person button');await eb.click();await own.waitForTimeout(150);
await own.fill('#cre-email','Craig@Example.com');await own.click('#cr-edit [data-cre="save"]');await own.waitForTimeout(1500);
ok(sql(`select email from people_private where person_id='${craig.id}'`)==='craig@example.com','engineer email saved (lower case)');
// invite panel lists Craig until he signs in
await own.reload();await own.waitForTimeout(1500);await own.click('[data-crv="pp"]');
const inv=await own.$eval('#inv-panel',e=>e.hidden?'HIDDEN':e.innerText);ok(/Craig Allen/.test(inv)&&/craig@example.com/.test(inv),'invite panel lists engineer with email');
const href=await own.$eval('#inv-panel li a.btn',e=>e.getAttribute('href'));ok(/^mailto:craig%40example.com\?subject=/.test(href)&&/Rota192|index.html/.test(decodeURIComponent(href)),'invite opens an email with the link');
console.log('invite body:',decodeURIComponent(href.split('body=')[1]).split('\n').slice(0,6).join(' / '));

// 3. engineer signs in, linked automatically
const eng=await user('craig@example.com',390);
ok(/engineer/i.test(await eng.$eval('#rolebar',e=>e.innerText)),'engineer linked on sign-in');ok((await tabs(eng))==='home,tl,eng','engineer tabs '+await tabs(eng));
const vis=await eng.evaluate(()=>[R.people.filter(p=>Object.keys(p.tr||{}).length).map(p=>p.name),Object.keys(A.assign).length,R.people.find(p=>p.id===SB.pid).rots.length,(R.log||[]).length]);
console.log('engineer can see training of:',vis[0],'accom rows',vis[1]);
ok(vis[0].every(n=>n==='Craig Allen'),'engineer only has own training');ok(vis[2]===craig.rots.length,'engineer has all own rotations');ok(vis[3]===0,'engineer gets no history');
const home=await eng.$eval('#cr-v-home',e=>e.innerText);ok(/My rotations/i.test(home),'home renders');
// engineer edits training
await eng.click('[data-hedit]');await eng.waitForTimeout(150);const cb=await eng.$('#hm-ed [data-htk="vca"]');if(cb&&!(await cb.isChecked()))await cb.check();const ve=await eng.$('#hm-ed [data-hte="vca"]');ok(!!ve,'vca date box');if(ve)await ve.fill('2029-05-01');
await eng.click('#hm-ed [data-hsave]');await eng.waitForTimeout(1500);console.log('training save:',await toast(eng));
ok(/2029-05-01/.test(sql(`select tr::text from training where person_id='${craig.id}'`)),'engineer training saved to database');
ok(/Craig Allen/.test(sql("select who from log order by at desc limit 1")),'history names the engineer');
// engineer tries something they can't: change a rotation via the console
await eng.evaluate(()=>{const rd=clone(R);rd.people.find(p=>p.id===SB.pid).rots[0].e+=7;R=rd;saveR()});await eng.waitForTimeout(1500);
console.log('forbidden write:',await toast(eng));ok(/permission/.test(await toast(eng)),'refused change is reported');ok(!/rotation: 1 Oct/.test(sql("select string_agg(what,'|') from log where who='Craig Allen'")),'refused change not written to history');ok(sql(`select e from rotations where id='${craig.rots[0].id}'`)==String(craig.rots[0].e),'engineer cannot change rotations even by force');
await own.reload();await own.waitForTimeout(1500);await own.click('[data-crv="pp"]');ok(!/Craig Allen/.test(await own.$eval('#inv-panel',e=>e.innerText.split('No email yet')[0])),'signed-in engineer drops off the invite list');
// 4. stranger waits, owner makes them a manager
const mg=await user('boss@example.com');ok(/waiting to be let in/i.test(await mg.$eval('#gate',e=>e.innerText)),'unknown email waits');
await own.reload();await own.waitForTimeout(1500);await own.click('[data-crv="pp"]');ok(!(await own.$eval('#pend-panel',e=>e.hidden)),'owner sees waiting list');
await own.click('[data-crv="set"]');const sel=await own.$('#acct-panel select[aria-label="Level for boss@example.com"]');await sel.selectOption('manager');await own.waitForTimeout(1200);
ok(sql("select role from members where email='boss@example.com'")==='manager','owner sets manager');
await mg.click('#gt-check');await mg.waitForTimeout(1500);ok(/manager/i.test(await mg.$eval('#rolebar',e=>e.innerText)),'manager gets in after check again');
ok((await tabs(mg))==='day,tl,pp,eng,acc','manager tabs');
ok(!(await mg.$('#acct-panel select')),'manager has no accounts panel');
// manager offers Craig an extra trip; Craig accepts through the server
const X0=await mg.evaluate(()=>window.__today()+150);
await mg.evaluate(X0=>window.__addOffers([{t:'casual',pid:SB.members.length?R.people.find(p=>p.name==='Craig Allen').id:'',X0,len:14}]),X0);await mg.waitForTimeout(1500);
const OQ=`from offers where person_id='${craig.id}' and (data->>'X0')::int=${X0}`;const od=sql(`select data->>'text' ${OQ}`);console.log('offer:',od);ok(!!sql(`select data->'result' ${OQ}`),'offer carries its rota change');
await eng.reload();await eng.waitForTimeout(1500);const oa=await eng.$('[data-oa]');ok(!!oa,'engineer sees offer');
if(oa){await oa.click();await eng.waitForTimeout(1500);console.log('accept:',await toast(eng));ok(sql(`select count(*) from rotations where person_id='${craig.id}' and s=${X0}`)==='1','accepting puts it on the rota');
  ok(sql(`select status ${OQ}`)==='accepted','offer marked accepted')}
// manager moves accommodation; engineer sees own only
await mg.click('[data-crv="acc"]');const as=await mg.$('.cr-accsel');ok(await as.evaluate(e=>getComputedStyle(e).pointerEvents!=='none'),'manager can change rooms');
// ideas (switched off in the live data, so switch on for the test)
sql("update settings set value=jsonb_build_object('ideas',true) where key='feat'");await eng.reload();await eng.waitForTimeout(1500);
await eng.click('[data-crv="ideas"]');const f=await eng.$('.idea-f');await (await f.$('[data-if="t"]')).fill('Shuttle bus times on the app');await (await f.$('[data-iadd]')).click();await eng.waitForTimeout(1500);
ok(sql("select by_name from ideas limit 1")==='Craig Allen','idea saved with name');
await mg.reload();await mg.waitForTimeout(1500);await mg.click('[data-crv="ideas"]');await mg.click('[data-ivote]');await mg.waitForTimeout(1500);ok(sql("select count(*) from idea_votes")==='1','manager vote saved');
// owner: history readable, names correct
await own.reload();await own.waitForTimeout(1500);await own.click('[data-crv="set"]');const h=await own.$eval('#hist-panel',e=>e.innerText);console.log('history top:',h.split('\n').slice(1,7).join(' | '));
// someone not on file: a manager lets them in from the Rotas tab
const nw=await user('steve.m@example.com');ok(/waiting to be let in/i.test(await nw.$eval('#gate',e=>e.innerText)),'new person waits');
await mg.reload();await mg.waitForTimeout(1500);await mg.click('[data-crv="pp"]');ok(!(await mg.$eval('#pend-panel',e=>e.hidden)),'manager sees waiting list');
const stv=B.rota.people.find(p=>p.name==='Steven Mennell');await mg.selectOption('#pend-panel select',stv.id);await mg.click('#pend-panel [data-pndgo]');await mg.waitForTimeout(1500);
ok(sql("select role||'/'||person_id from members where email='steve.m@example.com'")==='engineer/'+stv.id,'manager lets them in');
ok(sql(`select email from people_private where person_id='${stv.id}'`)==='steve.m@example.com','their email saved on the record');
await nw.click('#gt-check');await nw.waitForTimeout(1500);ok(/engineer/i.test(await nw.$eval('#rolebar',e=>e.innerText)),'they get in as that engineer');
// owner links themself to their own engineer record
const ed=B.rota.people.find(p=>p.name==='Edward Wingate Gray');await own.reload();await own.waitForTimeout(1500);await own.click('[data-crv="set"]');
await own.selectOption('#acct-panel select[aria-label="Engineer record for edward@example.com"]',ed.id);await own.waitForTimeout(1500);
ok(sql("select role||'/'||person_id from members where email='edward@example.com'")==='owner/'+ed.id,'owner links to own record, stays owner');
// a manager can't reach the accounts table to raise themselves
const r2=await mg.evaluate(async()=>{const {error,count}=await sb.from('members').update({role:'admin'},{count:'exact'}).eq('user_id',SB.uid);return error?error.message:String(count)});console.log('manager self-promote:',r2);ok(/Managers can only|0/.test(r2),'manager cannot make themself admin');
// set a level before someone has signed in
const kb=B.rota.people.find(p=>p.name==='Kenneth Brown');
await own.click('[data-crv="pp"]');await own.fill('#cr-q','Kenneth Brown');await own.waitForTimeout(200);
const cards=await own.$$('#cr-people .cr-card');for(const c of cards){if(/^\s*14/.test(await c.innerText())||(await c.innerText()).includes('Kenneth Brown\n')){}};
await (await own.$('#cr-people .cr-card [data-cre="editPerson"]')).click();await own.waitForTimeout(150);await own.fill('#cre-email','ken@example.com');await own.click('#cr-edit [data-cre="save"]');await own.waitForTimeout(1500);
await own.click('[data-crv="set"]');const pl=await own.$('[data-plv]');ok(!!pl,'not-signed-in list shows level picker');
const plid=await own.$eval('[data-plv]',e=>e.dataset.plv);await own.selectOption(`[data-plv="${plid}"]`,'manager');await own.waitForTimeout(1500);
const kem=sql(`select email from people_private where person_id='${plid}'`);ok(sql(`select level from people_private where person_id='${plid}'`)==='manager','pre-set level saved');
const kp=await user(kem);ok(/manager/i.test(await kp.$eval('#rolebar',e=>e.innerText)),'pre-set manager gets manager on first sign-in');
// phone layout of the gate
const ph=await user(null,390);
await eng.click('[data-crv="home"]');
for(const [nm,p] of [['owner',own],['engineer',eng],['manager',mg]])ok(!p.errs.length,nm+' errors '+p.errs);
console.log(`PASS ${pass} FAIL ${fail}`);await b.close()})();
