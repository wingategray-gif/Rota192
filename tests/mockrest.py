"""A small stand-in for Supabase's REST and sign-in endpoints, backed by the local Postgres,
so the page can be tested end to end with the real access rules. Test use only."""
import json, base64, time, uuid, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qsl
import psycopg2, psycopg2.extras
import os
DSN = os.environ.get("CREW_TEST_DSN", "dbname=crew user=postgres host=/var/run/postgresql")
PK = {"members": ["user_id"], "people": ["id"], "people_private": ["person_id"], "rotations": ["id"], "training": ["person_id"],
      "away": ["id"], "accom": ["key"], "settings": ["key"], "offers": ["id"], "vols": ["id"], "ideas": ["id"],
      "idea_votes": ["idea_id", "user_id"], "log": ["id"]}
JSONCOLS = {"tr", "data", "value"}
CODES = {}

def b64(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
def jwt(sub, email): return b64({"alg": "HS256", "typ": "JWT"}) + "." + b64({"sub": sub, "email": email, "role": "authenticated", "aud": "authenticated", "exp": int(time.time()) + 3600}) + ".sig"
def claims(h):
    a = (h.get("Authorization") or "").replace("Bearer ", "")
    try:
        p = a.split(".")[1]; p += "=" * (-len(p) % 4); return json.loads(base64.urlsafe_b64decode(p))
    except Exception: return None
def session(uid, email):
    return {"access_token": jwt(uid, email), "token_type": "bearer", "expires_in": 3600, "expires_at": int(time.time()) + 3600,
            "refresh_token": "r-" + uid, "user": {"id": uid, "email": email, "aud": "authenticated", "role": "authenticated",
            "app_metadata": {}, "user_metadata": {}, "created_at": "2026-11-27T00:00:00Z"}}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body=None, extra=None):
        data = b"" if body is None else json.dumps(body, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Expose-Headers", "Content-Range")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n) or b"null") if n else None
    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PATCH(self): self.route("PATCH")
    def do_DELETE(self): self.route("DELETE")
    def do_HEAD(self): self.route("GET")
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS"); self.send_header("Access-Control-Expose-Headers", "Content-Range"); self.end_headers()
    def route(self, m):
        u = urlparse(self.path); q = parse_qsl(u.query, keep_blank_values=True); path = u.path
        try:
            if path.startswith("/auth/v1/"): return self.auth(m, path[9:], dict(q))
            if path.startswith("/rest/v1/rpc/"): return self.rpc(path[13:])
            if path.startswith("/rest/v1/"): return self.rest(m, path[9:], q)
            self.send(404, {"message": "not found"})
        except Exception as e:
            self.send(500, {"message": str(e)})
    def auth(self, m, op, q):
        b = self.body() if m == "POST" else None
        if op == "otp": CODES[b["email"].lower()] = "123456"; return self.send(200, {})
        if op == "verify":
            email = b["email"].lower()
            if b.get("token") != CODES.get(email): return self.send(403, {"code": 403, "error_code": "otp_expired", "msg": "Token has expired or is invalid"})
            con = psycopg2.connect(DSN); con.autocommit = True; c = con.cursor()
            c.execute("select id from auth.users where lower(email)=%s", (email,)); r = c.fetchone()
            uid = str(r[0]) if r else str(uuid.uuid4())
            if not r: c.execute("insert into auth.users(id,email) values (%s,%s)", (uid, email))
            con.close(); return self.send(200, session(uid, email))
        if op == "user":
            cl = claims(self.headers)
            if not cl: return self.send(401, {"msg": "no user"})
            return self.send(200, session(cl["sub"], cl.get("email", ""))["user"])
        if op == "logout": return self.send(204)
        if op == "token":
            rt = (b or {}).get("refresh_token", "")
            uid = rt[2:]; con = psycopg2.connect(DSN); c = con.cursor(); c.execute("select email from auth.users where id=%s", (uid,)); r = c.fetchone(); con.close()
            return self.send(200, session(uid, r[0])) if r else self.send(400, {"msg": "bad"})
        return self.send(200, {})
    def conn(self):
        con = psycopg2.connect(DSN); c = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cl = claims(self.headers)
        if cl and cl.get("sub"):
            c.execute("set role authenticated"); c.execute("select set_config('request.jwt.claims',%s,true)", (json.dumps(cl),))
        else:
            c.execute("set role anon")
        return con, c
    def err(self, con, e):
        con.rollback(); code = getattr(e, "pgcode", "") or ""
        msg = str(e).split("\n")[0]
        self.send(403 if code == "42501" else 400, {"code": code, "message": msg, "details": None, "hint": None})
    def where(self, q):
        cl, args = [], []
        for k, v in q:
            if k in ("select", "order", "limit", "columns", "on_conflict"): continue
            op, _, val = v.partition(".")
            if op == "eq": cl.append(f'"{k}" = %s'); args.append(val)
            elif op == "is" and val == "null": cl.append(f'"{k}" is null')
            else: raise Exception("filter not supported: " + k + "=" + v)
        return (" where " + " and ".join(cl)) if cl else "", args
    def val(self, k, v): return psycopg2.extras.Json(v) if k in JSONCOLS else v
    def rest(self, m, t, q):
        if t not in PK: return self.send(404, {"message": "no table " + t})
        con, c = self.conn()
        try:
            w, args = self.where(q); d = dict(q)
            if m == "GET":
                sql = f"select * from public.{t}{w}"
                if "order" in d:
                    col, _, dirn = d["order"].partition("."); sql += f' order by "{col}" ' + ("desc" if dirn.startswith("desc") else "asc")
                if "limit" in d: sql += " limit " + str(int(d["limit"]))
                c.execute(sql, args); rows = c.fetchall(); con.commit()
                if "vnd.pgrst.object" in (self.headers.get("Accept") or ""):
                    return self.send(200, rows[0]) if len(rows) == 1 else self.send(406, {"message": "JSON object requested, multiple (or no) rows returned", "code": "PGRST116"})
                return self.send(200, rows)
            if m == "POST":
                b = self.body(); rows = b if isinstance(b, list) else [b]
                upsert = "merge-duplicates" in (self.headers.get("Prefer") or "")
                for r in rows:
                    cols = list(r.keys()); ph = ",".join(["%s"] * len(cols))
                    sql = f'insert into public.{t} ({",".join(chr(34)+x+chr(34) for x in cols)}) values ({ph})'
                    if upsert:
                        pk = PK[t]; upd = [x for x in cols if x not in pk]
                        sql += f' on conflict ({",".join(pk)}) do ' + ("update set " + ",".join(f'"{x}"=excluded."{x}"' for x in upd) if upd else "nothing")
                    c.execute(sql, [self.val(k, r[k]) for k in cols])
                con.commit(); return self.send(201, [])
            if m == "PATCH":
                b = self.body(); cols = list(b.keys())
                c.execute(f'update public.{t} set {",".join(chr(34)+x+chr(34)+"=%s" for x in cols)}{w}', [self.val(k, b[k]) for k in cols] + args)
                n = c.rowcount; con.commit(); return self.send(204, None, {"Content-Range": f"*/{n}"})
            if m == "DELETE":
                c.execute(f"delete from public.{t}{w}", args); n = c.rowcount; con.commit(); return self.send(204, None, {"Content-Range": f"*/{n}"})
        except psycopg2.Error as e: return self.err(con, e)
        finally: con.close()
    def rpc(self, fn):
        b = self.body() or {}; con, c = self.conn()
        try:
            c.execute(f"select public.{fn}(" + ",".join(f"{k} => %s" for k in b) + ") as r", list(b.values()))
            r = c.fetchone()["r"]; con.commit(); return self.send(200, r)
        except psycopg2.Error as e: return self.err(con, e)
        finally: con.close()

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8787), H).serve_forever()
