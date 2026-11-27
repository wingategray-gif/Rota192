"""Checks the access rules in setup.sql against a local Postgres 16 (see README: Testing)."""
import psycopg2, json, uuid, subprocess
import os
HERE=os.path.dirname(os.path.abspath(__file__));PSQL=os.environ.get("CREW_TEST_PSQL","psql -h /var/run/postgresql -U postgres")
# fresh test database: Supabase stand-in, then the real setup script twice (it must be safe to re-run)
for f,db in ((HERE+"/shim.sql","postgres"),(HERE+"/../setup.sql","crew"),(HERE+"/../setup.sql","crew")):
    r=subprocess.run(f"{PSQL} -q -v ON_ERROR_STOP=1 -d {db} -f '{f}'",shell=True,capture_output=True,text=True)
    if r.returncode: print(r.stderr); raise SystemExit("setup failed")
DSN=os.environ.get("CREW_TEST_DSN","dbname=crew user=postgres host=/var/run/postgresql")
su=psycopg2.connect(DSN);su.autocommit=True
P=F=0
def ok(c,m):
    global P,F
    if c: P+=1
    else: F+=1;print("FAIL:",m)
def adm(sql,*a):
    with su.cursor() as c:
        c.execute(sql,a)
        return c.fetchall() if c.description else c.rowcount
def newuser(email):
    uid=str(uuid.uuid4());adm("insert into auth.users(id,email) values (%s,%s)",uid,email);return uid
def as_(uid,sql,*a,fetch=True):
    """run one statement as a signed-in user; returns rows or the error text"""
    conn=psycopg2.connect(DSN)
    try:
        with conn.cursor() as c:
            c.execute("set role authenticated");c.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({"sub":uid,"role":"authenticated"}),))
            c.execute(sql,a)
            r=c.fetchall() if fetch and c.description else c.rowcount
        conn.commit();return r
    except Exception as e:
        conn.rollback();return "ERR:"+str(e).split("\n")[0]
    finally: conn.close()
# --- sign-ins
owner=newuser("edward@example.com")
ok(adm("select role from members where user_id=%s",owner)==[("owner",)],"first sign-in is owner")
# owner sets up people
r=as_(owner,"insert into people(id,no,name) values ('p1',1,'Craig'),('p2',2,'Steven'),('p12',12,'Edward'),('p9',9,'Old')",fetch=False);ok(r==4,f"owner adds people {r}")
ok(as_(owner,"insert into people_private(person_id,email) values ('p1','craig@x.com'),('p12','edward@example.com')",fetch=False)==2,"owner adds emails")
D=adm("select public.day_idx()")[0][0]
as_(owner,f"insert into rotations(id,person_id,s,e,d) values ('r1','p1',{D-3},{D+20},'W##W'),('r2','p2',{D+5},{D+30},'W##W'),('r3','p2',{D+200},{D+230},'W##W'),('r4','p12',{D},{D+10},'W##W')",fetch=False)
as_(owner,"insert into training(person_id,tr) values ('p1','{\"h2s\":{\"exp\":\"2027-01-01\"}}'),('p2','{\"vca\":{\"exp\":\"2028-01-01\"}}')",fetch=False)
as_(owner,"insert into accom(key,person_id,data) values ('r1','p1','{\"loc\":\"h1\"}'),('r2','p2','{\"loc\":\"h2\"}')",fetch=False)
as_(owner,"insert into settings(key,value) values ('hotel','\"Holiday Inn\"'),('ideaWin','false')",fetch=False)
# engineer whose email was added first
craig=newuser("Craig@X.com")
ok(adm("select role,person_id from members where user_id=%s",craig)==[("engineer","p1")],"email links engineer on sign-in (any case)")
# stranger waits
stranger=newuser("random@y.com")
ok(adm("select role from members where user_id=%s",stranger)==[("pending",)],"unknown email is pending")
ok(as_(stranger,"select count(*) from people")[0][0]==0,"pending sees no people")
ok(as_(stranger,"select count(*) from rotations")[0][0]==0,"pending sees no rotations")
ok(as_(stranger,"select count(*) from members")[0][0]==1,"pending sees only own member row")
# engineer reads
ok(as_(craig,"select count(*) from people")[0][0]==4,"engineer sees names")
rots=[x[0] for x in as_(craig,"select id from rotations order by id")]
ok(rots==["r1","r2","r4"],f"engineer sees own + 3-month window only {rots}")
ok([x[0] for x in as_(craig,"select person_id from training")]==["p1"],"engineer sees only own training")
ok([x[0] for x in as_(craig,"select key from accom")]==["r1"],"engineer sees only own accommodation")
ok([x[0] for x in as_(craig,"select person_id from people_private")]==["p1"],"engineer sees only own email")
ok(as_(craig,"select count(*) from members")[0][0]==1,"engineer sees only own account")
ok(as_(craig,"select count(*) from log")[0][0]==0,"engineer can't read history")
# engineer writes
ok(as_(craig,"update training set tr='{\"h2s\":{\"exp\":\"2028-01-01\"}}' where person_id='p1'",fetch=False)==1,"engineer edits own training")
ok(as_(craig,"update training set tr='{}' where person_id='p2'",fetch=False)==0,"engineer can't edit others' training")
ok("ERR" in str(as_(craig,"insert into training(person_id,tr) values ('p9','{}')",fetch=False)),"engineer can't add training for others")
ok(as_(craig,"update rotations set e=e+7 where id='r1'",fetch=False)==0,"engineer can't change rotations")
ok("ERR" in str(as_(craig,"insert into rotations(id,person_id,s,e) values ('x','p1',1,2)",fetch=False)),"engineer can't add rotations")
ok(as_(craig,"update people set name='Hacked' where id='p2'",fetch=False)==0,"engineer can't rename people")
ok(as_(craig,"update accom set data='{}' where key='r1'",fetch=False)==0,"engineer can't change accommodation")
ok(as_(craig,"update members set role='admin' where user_id=%s",craig,fetch=False)==0,"engineer can't raise own level")
ok(as_(craig,"insert into away(id,person_id,s,e) values ('a1','p1',%s,%s)",D+40,D+42,fetch=False)==1,"engineer adds own away dates")
ok("ERR" in str(as_(craig,"insert into away(id,person_id,s,e) values ('a2','p2',1,2)",fetch=False)),"engineer can't add away for others")
ok(as_(craig,"insert into vols(id,person_id,data) values ('v1','p1','{}')",fetch=False)==1,"engineer volunteers")
ok(as_(craig,"select count(*) from settings")[0][0]==2,"engineer reads settings")
ok(as_(craig,"update settings set value='true' where key='ideaWin'",fetch=False)==0,"engineer can't change settings")
ok(as_(craig,"insert into log(id,what,who) values ('l1','did a thing','Fake Name')",fetch=False)==1,"engineer's change is logged")
ok(adm("select who from log where id='l1'")==[("Craig",)],"history uses real name, not what the page says")
ok(as_(craig,"update training set tr=%s where person_id=%s",json.dumps({"h2s":{"exp":"2029-01-01"}}),"p1",fetch=False)==1 and adm("select h2s from people where id=%s","p1")==[(True,)],"H2S dot follows training")
# manager
mgr=newuser("boss@x.com");as_(owner,"update members set role='manager' where user_id=%s",mgr,fetch=False)
ok(adm("select role from members where user_id=%s",mgr)==[("manager",)],"owner makes a manager")
ok(len(as_(mgr,"select id from rotations"))==4,"manager sees all rotations")
ok(as_(mgr,"insert into people(id,no,name) values ('p3',3,'New')",fetch=False)==1,"manager adds engineer")
ok(as_(mgr,"insert into people_private(person_id,email) values ('p3','random@y.com')",fetch=False)==1,"manager adds email")
ok(adm("select role,person_id from members where user_id=%s",stranger)==[("engineer","p3")],"waiting sign-in linked when email added")
ok("ERR" in str(as_(mgr,"update members set role='admin' where user_id=%s",craig,fetch=False)),"manager can't make admins")
ok(as_(mgr,"update settings set value='true' where key='ideaWin'",fetch=False)==1,"manager switches 48h voting")
ok(as_(mgr,"update settings set value='\"X\"' where key='hotel'",fetch=False)==0,"manager can't change hotel setting")
ok(as_(mgr,"update accom set data='{\"loc\":\"h3\"}' where key='r1'",fetch=False)==1,"manager changes accommodation")
ok(as_(mgr,"select count(*) from log")[0][0]==0,"manager can't read history")
ok(as_(mgr,"delete from people where id='p9'",fetch=False)==0,"manager can't delete people")
# owner protections
ok("ERR" in str(as_(mgr,"update members set role='engineer' where user_id=%s",owner,fetch=False)),"nobody demotes the owner")
adm2=newuser("second@x.com");as_(owner,"update members set role='admin' where user_id=%s",adm2,fetch=False)
ok("ERR" in str(as_(adm2,"update members set role='viewer' where user_id=%s",owner,fetch=False)),"admin can't demote owner")
ok(as_(adm2,"delete from members where user_id=%s",owner,fetch=False)==0,"admin can't remove owner")
ok("ERR" in str(as_(owner,"update members set role='owner' where user_id=%s",adm2,fetch=False)),"no second owner")
ok(as_(adm2,"select count(*) from log")[0][0]>=1,"admin reads history")
# viewer
vw=newuser("view@x.com");as_(owner,"update members set role='viewer' where user_id=%s",vw,fetch=False)
ok(sorted(x[0] for x in as_(vw,"select id from rotations"))==["r1","r2","r4"],"viewer sees the 3-month window")
ok(as_(vw,"select count(*) from training")[0][0]==0,"viewer sees no training")
# offers: staff make, engineer answers via function
exp={"r1":{"s":D-3,"e":D+20,"d":"W##W"}}
res={"put":[{"id":"r1","person_id":"p1","s":D-3,"e":D+27,"d":"W#####W"}],"del":[]}
as_(mgr,"insert into offers(id,person_id,data) values ('o1','p1',%s)",json.dumps({"t":"stay","text":"Stay on 1 week","expect":exp,"result":res}),fetch=False)
ok("ERR" in str(as_(craig,"update offers set status='accepted' where id='o1'",fetch=False)) or as_(craig,"update offers set status='accepted' where id='o1'",fetch=False)==0,"engineer can't mark accepted directly")
ok("ERR" in str(as_(stranger,"select respond_offer('o1',true)")),"someone else can't answer it")
ok(as_(craig,"select respond_offer('o1',true)")==[("accepted",)],"engineer accepts")
ok(adm("select e,d from rotations where id='r1'")==[(D+27,"W#####W")],"rota changed on accept")
ok(adm("select status from offers where id='o1'")==[("accepted",)],"offer marked accepted")
ok(adm("select count(*) from log where what like 'Accepted the offer%%' and who='Craig'")[0][0]==1,"accept logged with name")
# stale offer refused
as_(mgr,"insert into offers(id,person_id,data) values ('o2','p1',%s)",json.dumps({"t":"stay","text":"x","expect":exp,"result":res}),fetch=False)
ok(as_(craig,"select respond_offer('o2',true)")==[("changed",)],"stale offer refused")
ok(as_(craig,"select respond_offer('o2',false)")==[("declined",)],"engineer declines")
# ideas
as_(owner,"update settings set value='false' where key='ideaWin'",fetch=False)
for i in range(3): ok(as_(craig,"insert into ideas(id,title,created) values (%s,'Idea','2026-11-27')",f"i{i}",fetch=False)==1,"engineer adds idea")
ok("ERR" in str(as_(craig,"insert into ideas(id,title) values ('i3','Fourth')",fetch=False)),"4th open idea refused")
ok(adm("select by_name from ideas where id='i0'")==[("Craig",)],"idea stamped with name")
ok("ERR" in str(as_(craig,"insert into idea_votes(idea_id,user_id) values ('i0',%s)",craig,fetch=False)),"can't vote own idea")
ok(as_(mgr,"insert into idea_votes(idea_id,user_id) values ('i0',%s)",mgr,fetch=False)==1,"others vote")
ok("ERR" in str(as_(stranger,"insert into idea_votes(idea_id,user_id) values ('i0',%s)",craig,fetch=False)),"can't vote as someone else")
ok(as_(craig,"update ideas set st='planned' where id='i0'",fetch=False)==0,"engineer can't decide")
ok(as_(mgr,"update ideas set st='planned' where id='i0'",fetch=False)==1,"manager decides")
ok(as_(craig,"insert into ideas(id,title) values ('i4','Now allowed')",fetch=False)==1,"slot freed after decision")
# 48h window
as_(mgr,"update settings set value='true' where key='ideaWin'",fetch=False);adm("update ideas set at=now()-interval '3 days' where id='i1'")
ok(sorted(x[0] for x in as_(stranger,"select id from ideas"))==["i0","i2","i4"],"after 48h only managers and author see it")
ok("i1" in [x[0] for x in as_(craig,"select id from ideas")],"author still sees own")
ok("ERR" in str(as_(mgr,"insert into idea_votes(idea_id,user_id) values ('i1',%s)",mgr,fetch=False)),"no votes after 48h")
# pre-set level before first sign-in
ok("ERR" in str(as_(mgr,"update people_private set level='admin' where person_id='p3'",fetch=False)),"manager can't pre-set admin")
as_(owner,"insert into people('id','no','name') values ('p5',5,'Mgr To Be')" if False else "insert into people(id,no,name) values ('p5',5,'Mgr To Be')",fetch=False)
ok(as_(owner,"insert into people_private(person_id,email,level) values ('p5','mgr2@x.com','manager')",fetch=False)==1,"owner pre-sets manager")
m2=newuser("MGR2@x.com");ok(adm("select role,person_id from members where user_id=%s",m2)==[("manager","p5")],"pre-set level applied on first sign-in")
# removing access
ok(as_(owner,"update members set role='pending',person_id=null where user_id=%s",craig,fetch=False)==1,"owner removes access")
ok(as_(craig,"select count(*) from rotations")[0][0]==0,"removed engineer sees nothing")
print(f"PASS {P} FAIL {F}")
