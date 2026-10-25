from flask import Flask, request, jsonify, send_from_directory, session, abort, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, os, uuid, base64
import stripe
from datetime import datetime, timedelta
from urllib.parse import urlsplit
try:
    from authlib.integrations.flask_client import OAuth
except ImportError:
    OAuth=None

BASE=os.path.dirname(os.path.abspath(__file__))
APP_ENV=os.environ.get("BASECOAT_ENV","development").lower()
DEMO_MODE=os.environ.get("BASECOAT_DEMO_MODE","1")=="1" and APP_ENV!="production"
DATA_DIR=os.environ.get("BASECOAT_DATA_DIR",BASE)
os.makedirs(DATA_DIR,exist_ok=True)
DB=os.path.join(DATA_DIR,"basecoat.db")
UPLOAD=os.path.join(DATA_DIR,"uploads")
os.makedirs(UPLOAD,exist_ok=True)

app=Flask(__name__, static_folder="web")
if APP_ENV=="production":app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
if APP_ENV=="production" and not os.environ.get("BASECOAT_SECRET"):
    raise RuntimeError("Set BASECOAT_SECRET to a long random value in the hosting dashboard")
app.secret_key=os.environ.get("BASECOAT_SECRET","local-test-secret-change-before-deploy")
app.config["MAX_CONTENT_LENGTH"]=125*1024*1024
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=APP_ENV=="production")
oauth=OAuth(app) if OAuth else None
GOOGLE_ENABLED=bool(oauth and os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
if GOOGLE_ENABLED:
    oauth.register(name="google",client_id=os.environ["GOOGLE_CLIENT_ID"],client_secret=os.environ["GOOGLE_CLIENT_SECRET"],server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",client_kwargs={"scope":"openid email profile"})

@app.before_request
def production_origin_check():
    if APP_ENV!="production" or request.path=="/api/stripe/webhook" or request.method in ("GET","HEAD","OPTIONS"):return
    origin=request.headers.get("Origin")
    if not origin or urlsplit(origin).netloc.lower()!=request.host.lower():abort(403)

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="same-origin"
    if APP_ENV=="production":response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response

def db():
    c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row;c.execute("PRAGMA busy_timeout=30000");return c
def init():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,name TEXT NOT NULL,rate REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS ranks(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,sort_order INTEGER NOT NULL DEFAULT 0,can_manage_chats INTEGER NOT NULL DEFAULT 0,can_inspect INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,type TEXT,worker_id INTEGER,customer_id INTEGER,progress INTEGER DEFAULT 0,status TEXT DEFAULT 'New',total REAL DEFAULT 0,address TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,sender_id INTEGER,text TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,user_id INTEGER,path TEXT,caption TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS time_entries(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,job_id INTEGER,clock_in TEXT,clock_out TEXT);
    CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,total REAL,deposit REAL,paid REAL DEFAULT 0,status TEXT DEFAULT 'Unpaid');
    CREATE TABLE IF NOT EXISTS blueprints(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER UNIQUE NOT NULL,png_path TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS job_blueprints(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER NOT NULL,plane TEXT NOT NULL,png_path TEXT NOT NULL,scale REAL,units TEXT NOT NULL DEFAULT 'ft',origin_x REAL NOT NULL DEFAULT 0,origin_y REAL NOT NULL DEFAULT 0,canvas_width REAL,canvas_height REAL,updated_at TEXT NOT NULL,UNIQUE(job_id,plane));
    CREATE TABLE IF NOT EXISTS pay_adjustments(id INTEGER PRIMARY KEY AUTOINCREMENT,worker_id INTEGER NOT NULL,kind TEXT NOT NULL,amount REAL NOT NULL,reason TEXT NOT NULL,authorized INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_groups(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,name TEXT NOT NULL,job_id INTEGER,rank_id INTEGER,created_by INTEGER,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_group_members(group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,added_by INTEGER,created_at TEXT NOT NULL,PRIMARY KEY(group_id,user_id));
    CREATE TABLE IF NOT EXISTS group_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,group_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS inspections(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER NOT NULL,inspector_id INTEGER NOT NULL,rating INTEGER NOT NULL,notes TEXT NOT NULL,created_at TEXT NOT NULL,blueprint_plane TEXT NOT NULL DEFAULT 'xy',blueprint_markers TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS inspection_photos(id INTEGER PRIMARY KEY AUTOINCREMENT,inspection_id INTEGER NOT NULL,path TEXT NOT NULL,caption TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS job_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL,description TEXT NOT NULL,address TEXT NOT NULL,preferred_date TEXT NOT NULL DEFAULT '',budget REAL,status TEXT NOT NULL DEFAULT 'pending',reviewed_by INTEGER,review_note TEXT NOT NULL DEFAULT '',job_id INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS blacklist(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL UNIQUE,reason TEXT NOT NULL,created_at TEXT NOT NULL,created_by INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS pricing_settings(key TEXT PRIMARY KEY,value REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS work_types(name TEXT PRIMARY KEY,hours_per_sheet REAL NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,remote_ip TEXT NOT NULL,attempted_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS worker_locations(user_id INTEGER PRIMARY KEY,job_id INTEGER NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL,accuracy REAL,updated_at TEXT NOT NULL);
    """)
    for column in ["employment_status TEXT NOT NULL DEFAULT 'active'","rank_id INTEGER","approval_status TEXT NOT NULL DEFAULT 'approved'","google_sub TEXT","auth_provider TEXT NOT NULL DEFAULT 'password'"]:
        try:c.execute("ALTER TABLE users ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for column in ["can_manage_chats INTEGER NOT NULL DEFAULT 0","can_inspect INTEGER NOT NULL DEFAULT 0"]:
        try:c.execute("ALTER TABLE ranks ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    try:c.execute("ALTER TABLE jobs ADD COLUMN customer_id INTEGER")
    except sqlite3.OperationalError:pass
    for column in ["site_lat REAL","site_lon REAL","geofence_radius_m REAL NOT NULL DEFAULT 152.4"]:
        try:c.execute("ALTER TABLE jobs ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for column in ["canvas_width REAL","canvas_height REAL"]:
        try:c.execute("ALTER TABLE job_blueprints ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for column in ["payment_requested_at TEXT","stripe_session_id TEXT"]:
        try:c.execute("ALTER TABLE invoices ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for column in ["blueprint_plane TEXT NOT NULL DEFAULT 'xy'","blueprint_markers TEXT NOT NULL DEFAULT '[]'","blueprint_png_path TEXT"]:
        try:c.execute("ALTER TABLE inspections ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for column in ["drywall_sheets REAL NOT NULL DEFAULT 0","crew_hours REAL NOT NULL DEFAULT 0","crew_size INTEGER NOT NULL DEFAULT 1","labor_rate REAL NOT NULL DEFAULT 0","sheet_cost REAL NOT NULL DEFAULT 15","profit_target REAL NOT NULL DEFAULT 500","material_cost REAL NOT NULL DEFAULT 0","labor_cost REAL NOT NULL DEFAULT 0","additional_costs REAL NOT NULL DEFAULT 0","pricing_complete INTEGER NOT NULL DEFAULT 0"]:
        try:c.execute("ALTER TABLE jobs ADD COLUMN "+column)
        except sqlite3.OperationalError:pass
    for key,value in [("drywall_sheet_cost",15),("minimum_profit",500),("default_labor_rate",22)]:
        c.execute("INSERT OR IGNORE INTO pricing_settings(key,value) VALUES(?,?)",(key,value))
    for name,hours in [("Drywall Install",0.50),("Drywall Repair",1.25),("Taping & Finishing",0.75),("Texture",0.50),("Custom Work",1.00)]:
        c.execute("INSERT OR IGNORE INTO work_types(name,hours_per_sheet) VALUES(?,?)",(name,hours))
    admin=c.execute("SELECT id FROM users WHERE role='owner' LIMIT 1").fetchone()
    if not admin:
        if APP_ENV=="production":
            owner_email=os.environ.get("BASECOAT_OWNER_EMAIL","").strip().lower();owner_password=os.environ.get("BASECOAT_OWNER_PASSWORD","");owner_name=os.environ.get("BASECOAT_OWNER_NAME","Basecoat Owner").strip()
            if not owner_email or len(owner_password)<14:raise RuntimeError("For first production startup, set BASECOAT_OWNER_EMAIL and BASECOAT_OWNER_PASSWORD (at least 14 characters)")
            c.execute("INSERT INTO users(email,password,role,name,rate) VALUES(?,?,?,?,0)",(owner_email,generate_password_hash(owner_password),"owner",owner_name))
        else:
            c.execute("INSERT INTO users(email,password,role,name,rate) VALUES(?,?,?,?,?)",("jroliverioxxxx@gmail.com",generate_password_hash("321"),"owner","Jacob",0))
    for pos,(name,manager,inspector) in enumerate([("Apprentice",0,0),("Technician",0,0),("Lead",0,0),("Foreman",1,0),("Inspector",0,1)]):
        c.execute("INSERT OR IGNORE INTO ranks(name,sort_order,can_manage_chats,can_inspect) VALUES(?,?,?,?)",(name,pos,manager,inspector))
    c.execute("UPDATE ranks SET can_manage_chats=1 WHERE lower(name) IN ('foreman','foremen')")
    c.execute("UPDATE ranks SET can_inspect=1 WHERE lower(name)='inspector'")
    if APP_ENV!="production":
        for email,name,role,rate in [("worker@basecoat.local","Mike","worker",22),("customer@basecoat.local","Smith Customer","customer",0)]:
            if not c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
                c.execute("INSERT INTO users(email,password,role,name,rate) VALUES(?,?,?,?,?)",(email,generate_password_hash("basecoat123"),role,name,rate))
        c.execute("UPDATE jobs SET customer_id=(SELECT id FROM users WHERE email='customer@basecoat.local') WHERE customer_id IS NULL AND name='Smith Residence'")
        worker_demo=c.execute("SELECT id,rank_id FROM users WHERE email='worker@basecoat.local'").fetchone()
        if worker_demo and not worker_demo["rank_id"]:
            rank=c.execute("SELECT id FROM ranks WHERE name='Technician'").fetchone()
            if rank:c.execute("UPDATE users SET rank_id=? WHERE id=?",(rank["id"],worker_demo["id"]))
        if not c.execute("SELECT id FROM jobs").fetchone():
            worker=c.execute("SELECT id FROM users WHERE role='worker'").fetchone()["id"]
            customer=c.execute("SELECT id FROM users WHERE email='customer@basecoat.local'").fetchone()["id"]
            cur=c.execute("INSERT INTO jobs(name,type,worker_id,customer_id,progress,status,total,address,created_at) VALUES(?,?,?,?,?,?,?,?,?)",("Smith Residence","Drywall Repair",worker,customer,75,"In Progress",1200,"123 Main St","2026-10-25"))
            jid=cur.lastrowid;c.execute("INSERT INTO invoices(job_id,total,deposit,paid,status) VALUES(?,?,?,?,?)",(jid,1200,300,300,"Deposit Paid"))
    for rank in c.execute("SELECT id,name FROM ranks").fetchall():
        group=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(rank["id"],)).fetchone()
        if not group:
            cur=c.execute("INSERT INTO chat_groups(kind,name,rank_id,created_at) VALUES('rank',?,?,?)",(rank["name"]+" rank chat",rank["id"],datetime.utcnow().isoformat()));group_id=cur.lastrowid
            for worker in c.execute("SELECT id FROM users WHERE role='worker' AND employment_status='active' AND rank_id=?",(rank["id"],)).fetchall():
                c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,created_at) VALUES(?,?,?)",(group_id,worker["id"],datetime.utcnow().isoformat()))
    for job in c.execute("SELECT id,name,worker_id FROM jobs").fetchall():
        group=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(job["id"],)).fetchone()
        if not group:
            group_id=c.execute("INSERT INTO chat_groups(kind,name,job_id,created_at) VALUES('job',?,?,?)",("Site · "+job["name"],job["id"],datetime.utcnow().isoformat())).lastrowid
            if job["worker_id"]:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,created_at) VALUES(?,?,?)",(group_id,job["worker_id"],datetime.utcnow().isoformat()))
    company=c.execute("SELECT id FROM chat_groups WHERE kind='company' LIMIT 1").fetchone()
    if company:company_id=company["id"]
    else:company_id=c.execute("INSERT INTO chat_groups(kind,name,created_at) VALUES('company','Everyone · Company Chat',?)",(datetime.utcnow().isoformat(),)).lastrowid
    for person in c.execute("SELECT id FROM users WHERE role='owner' OR (role='worker' AND employment_status='active')").fetchall():
        c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,created_at) VALUES(?,?,?)",(company_id,person["id"],datetime.utcnow().isoformat()))
    c.commit();c.close()
init()

def current():
    if not session.get("uid"): return None
    c=db(); u=c.execute("SELECT * FROM users WHERE id=?",(session["uid"],)).fetchone();c.close()
    if u and u["role"]=="worker" and u["employment_status"]!="active":session.clear();return None
    return u
def ok(role=None):
    u=current()
    if not u:return None
    if u["role"]=="worker" and u["approval_status"]!="approved":return None
    if role and u["role"] not in role:return None
    return u

def permissions(u,c=None):
    if u["role"]=="owner": return {"can_manage":True,"can_inspect":True}
    if u["role"]!="worker" or not u["rank_id"]: return {"can_manage":False,"can_inspect":False}
    own= c is None
    if own:c=db()
    row=c.execute("SELECT can_manage_chats,can_inspect FROM ranks WHERE id=?",(u["rank_id"],)).fetchone()
    if own:c.close()
    return {"can_manage":bool(row and row["can_manage_chats"]),"can_inspect":bool(row and row["can_inspect"])}

def stamp(): return datetime.utcnow().isoformat()

def pricing_data(c):
    settings={r["key"]:float(r["value"]) for r in c.execute("SELECT key,value FROM pricing_settings").fetchall()}
    types=[dict(r) for r in c.execute("SELECT name,hours_per_sheet FROM work_types ORDER BY name").fetchall()]
    return settings,types

def calculate_quote(c,d,job_type):
    settings,types=pricing_data(c)
    try:
        sheets=float(d.get("drywall_sheets",0) or 0)
        crew_size=int(d.get("crew_size",1) or 1)
        labor_rate=float(d.get("labor_rate",settings.get("default_labor_rate",22)))
        sheet_cost=float(d.get("sheet_cost",settings.get("drywall_sheet_cost",15)))
        additional_costs=float(d.get("additional_costs",0) or 0)
        profit_target=float(d.get("profit_target",settings.get("minimum_profit",500)))
    except (TypeError,ValueError):raise ValueError("Enter valid numbers for sheets, crew size, labor rate, material cost, and profit target")
    if sheets<0 or crew_size<1 or crew_size>100 or labor_rate<0 or sheet_cost<0 or additional_costs<0:raise ValueError("Sheets and costs cannot be negative, and crew size must be 1–100")
    min_profit=max(500,float(settings.get("minimum_profit",500)))
    if profit_target<min_profit:raise ValueError("Profit target must be at least $%.2f"%min_profit)
    factor=next((float(t["hours_per_sheet"]) for t in types if t["name"]==job_type),1.0)
    raw_hours=d.get("crew_hours")
    try:crew_hours=float(raw_hours) if str(raw_hours or "").strip() else (sheets*factor/crew_size)
    except (TypeError,ValueError):raise ValueError("Enter a valid estimated time per worker")
    if crew_hours<0:raise ValueError("Estimated time cannot be negative")
    material_cost=sheets*sheet_cost
    labor_cost=crew_hours*crew_size*labor_rate
    floor=material_cost+labor_cost+additional_costs+profit_target
    try:quote_total=float(d.get("quote_total",floor))
    except (TypeError,ValueError):raise ValueError("Enter a valid customer price")
    if quote_total+0.000001<floor:raise ValueError("Price must cover estimated materials and labor and leave at least $%.2f profit"%profit_target)
    return {"drywall_sheets":sheets,"crew_hours":crew_hours,"crew_size":crew_size,"labor_rate":labor_rate,"sheet_cost":sheet_cost,"profit_target":profit_target,"material_cost":round(material_cost,2),"labor_cost":round(labor_cost,2),"additional_costs":round(additional_costs,2),"total":round(quote_total,2),"minimum_quote":round(floor,2),"type_hours_per_sheet":factor}

def ensure_job_chat(c,jid,name,worker_id=None,add_member=True):
    row=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(jid,)).fetchone()
    if row:gid=row["id"];c.execute("UPDATE chat_groups SET name=? WHERE id=?",("Site · "+name,gid))
    else:gid=c.execute("INSERT INTO chat_groups(kind,name,job_id,created_at) VALUES('job',?,?,?)",("Site · "+name,jid,stamp())).lastrowid
    if worker_id and add_member:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,created_at) VALUES(?,?,?)",(gid,worker_id,stamp()))
    return gid

@app.route("/")
def index(): return send_from_directory("web","index.html")
@app.route("/auth/google")
def google_start():
    role=request.args.get("role","")
    if role not in ("customer","worker"):return "Choose customer or worker sign-up.",400
    if not GOOGLE_ENABLED:return "Google sign-in is not configured yet. The app owner must add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the hosting settings.",503
    session["google_signup_role"]=role
    return oauth.google.authorize_redirect(url_for("google_callback",_external=True))
@app.route("/auth/google/callback")
def google_callback():
    if not GOOGLE_ENABLED:return "Google sign-in is not configured.",503
    try:
        token=oauth.google.authorize_access_token();claims=token.get("userinfo") or oauth.google.parse_id_token(token)
    except Exception:return "Google sign-in could not be verified. Please try again.",400
    sub=str(claims.get("sub", ""));email=str(claims.get("email","")).strip().lower();name=str(claims.get("name","")).strip() or email
    if not sub or not email or claims.get("email_verified") is not True:return "Google must provide a verified email address.",400
    requested=session.pop("google_signup_role",None);c=db();u=c.execute("SELECT * FROM users WHERE google_sub=?",(sub,)).fetchone()
    if not u:
        u=c.execute("SELECT * FROM users WHERE lower(email)=?",(email,)).fetchone()
        if u:
            if u["google_sub"] and u["google_sub"]!=sub:c.close();return "This account is linked to another Google account.",403
            c.execute("UPDATE users SET google_sub=?,auth_provider='google' WHERE id=?",(sub,u["id"]))
            u=c.execute("SELECT * FROM users WHERE id=?",(u["id"],)).fetchone()
        else:
            if requested not in ("customer","worker"):c.close();return "Choose customer or worker signup from the login page.",400
            status="pending" if requested=="worker" else "approved"
            cur=c.execute("INSERT INTO users(email,password,role,name,rate,employment_status,approval_status,google_sub,auth_provider) VALUES(?,?,?,?,0,'active',?,?, 'google')",(email,generate_password_hash(uuid.uuid4().hex),requested,name,status,sub));u=c.execute("SELECT * FROM users WHERE id=?",(cur.lastrowid,)).fetchone()
    if u["email"].lower()!=email:c.close();return "Google account email does not match the linked account.",403
    c.commit();c.close();session["uid"]=u["id"]
    return redirect("/?application=pending" if u["role"]=="worker" and u["approval_status"]!="approved" else "/")
@app.route("/api/public-config")
def public_config():return jsonify(google_enabled=GOOGLE_ENABLED)
@app.route("/api/login",methods=["POST"])
def login():
    d=request.json or {}; c=db();remote_ip=request.remote_addr or "unknown";cutoff=(datetime.utcnow()-timedelta(minutes=15)).isoformat()
    c.execute("DELETE FROM login_attempts WHERE attempted_at<?",(cutoff,))
    if c.execute("SELECT COUNT(*) n FROM login_attempts WHERE remote_ip=?",(remote_ip,)).fetchone()["n"]>=10:c.close();return jsonify(error="Too many sign-in attempts. Wait 15 minutes and try again."),429
    u=c.execute("SELECT * FROM users WHERE lower(email)=lower(?)",(str(d.get("email","")).strip(),)).fetchone()
    if not u or not check_password_hash(u["password"],d.get("password","")):
        c.execute("INSERT INTO login_attempts(remote_ip,attempted_at) VALUES(?,?)",(remote_ip,datetime.utcnow().isoformat()));c.commit();c.close();return jsonify(error="Invalid email or password"),401
    if u["role"]=="worker" and u["employment_status"]!="active":c.close();return jsonify(error="This worker account is inactive. Contact the owner."),403
    c.execute("DELETE FROM login_attempts WHERE remote_ip=?",(remote_ip,));rank=c.execute("SELECT name FROM ranks WHERE id=?",(u["rank_id"],)).fetchone() if u["rank_id"] else None;c.close()
    session["uid"]=u["id"];return jsonify(id=u["id"],email=u["email"],name=u["name"],role=u["role"],rate=u["rate"],rank=rank["name"] if rank else None,employment_status=u["employment_status"],approval_status=u["approval_status"],**permissions(u))
@app.route("/api/logout",methods=["POST"])
def logout(): session.clear();return jsonify(ok=True)
@app.route("/api/password",methods=["POST"])
def change_password():
    u=ok()
    if not u:return jsonify(error="Sign in first"),401
    d=request.json or {};old=str(d.get("current_password",""));new=str(d.get("new_password",""))
    if len(new)<12:return jsonify(error="Use a new password with at least 12 characters"),400
    c=db();row=c.execute("SELECT password FROM users WHERE id=?",(u["id"],)).fetchone()
    if not row or not check_password_hash(row["password"],old):c.close();return jsonify(error="Current password is incorrect"),400
    c.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(new),u["id"]));c.commit();c.close();return jsonify(ok=True)
@app.route("/api/me")
def me():
    u=current()
    if not u:return jsonify(authenticated=False)
    rank=None
    if u["rank_id"]:
        c=db();r=c.execute("SELECT name FROM ranks WHERE id=?",(u["rank_id"],)).fetchone();c.close();rank=r["name"] if r else None
    return jsonify(authenticated=True,id=u["id"],email=u["email"],name=u["name"],role=u["role"],rate=u["rate"],rank=rank,employment_status=u["employment_status"],approval_status=u["approval_status"],**permissions(u))
@app.route("/api/jobs")
def jobs():
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db()
    preview="COALESCE((SELECT '/uploads/'||b.png_path FROM job_blueprints b WHERE b.job_id=j.id AND b.plane='xy'),(SELECT '/uploads/'||b.png_path FROM job_blueprints b WHERE b.job_id=j.id ORDER BY b.updated_at DESC LIMIT 1),(SELECT '/uploads/'||b.png_path FROM blueprints b WHERE b.job_id=j.id LIMIT 1)) blueprint_url"
    invoice_fields=",i.status invoice_status,i.paid invoice_paid,i.payment_requested_at"
    caps=permissions(u)
    if u["role"]=="worker" and not caps["can_inspect"] and not caps["can_manage"]:
        rows=c.execute("SELECT j.*,u.name worker,cu.email customer_email,"+preview+invoice_fields+" FROM jobs j LEFT JOIN users u ON u.id=j.worker_id LEFT JOIN users cu ON cu.id=j.customer_id LEFT JOIN invoices i ON i.job_id=j.id WHERE j.worker_id=? ORDER BY j.id DESC",(u["id"],)).fetchall()
    elif u["role"]=="customer":
        rows=c.execute("SELECT j.*,u.name worker,cu.email customer_email,"+preview+invoice_fields+" FROM jobs j LEFT JOIN users u ON u.id=j.worker_id LEFT JOIN users cu ON cu.id=j.customer_id LEFT JOIN invoices i ON i.job_id=j.id WHERE j.customer_id=? ORDER BY j.id DESC",(u["id"],)).fetchall()
    else: rows=c.execute("SELECT j.*,u.name worker,cu.email customer_email,"+preview+invoice_fields+" FROM jobs j LEFT JOIN users u ON u.id=j.worker_id LEFT JOIN users cu ON cu.id=j.customer_id LEFT JOIN invoices i ON i.job_id=j.id ORDER BY j.id DESC").fetchall()
    c.close();return jsonify(jobs=[dict(x) for x in rows])
@app.route("/api/jobs",methods=["POST"])
def create_job():
    u=ok(["owner"]); 
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {}; c=db()
    job_type=str(d.get("type","Drywall Repair")).strip() or "Drywall Repair"
    try:quote=calculate_quote(c,d,job_type)
    except ValueError as e:c.close();return jsonify(error=str(e)),400
    customer=None
    if d.get("customer_email"):
        customer=c.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND role='customer'",(d["customer_email"].strip(),)).fetchone()
        if not customer:c.close();return jsonify(error="No customer account matches that email"),400
    worker_id=None
    try:worker_id=int(d.get("worker_id")) if str(d.get("worker_id","")).strip() else None
    except (TypeError,ValueError):c.close();return jsonify(error="Choose a valid assigned worker"),400
    if worker_id and not c.execute("SELECT id FROM users WHERE id=? AND role='worker' AND employment_status='active'",(worker_id,)).fetchone():c.close();return jsonify(error="Choose an active worker"),400
    name=str(d.get("name","New Job")).strip() or "New Job"
    cur=c.execute("INSERT INTO jobs(name,type,worker_id,customer_id,progress,status,total,address,created_at,drywall_sheets,crew_hours,crew_size,labor_rate,sheet_cost,profit_target,material_cost,labor_cost,additional_costs,pricing_complete) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
              (name,job_type,worker_id,customer["id"] if customer else None,0,"New",quote["total"],d.get("address",""),stamp(),quote["drywall_sheets"],quote["crew_hours"],quote["crew_size"],quote["labor_rate"],quote["sheet_cost"],quote["profit_target"],quote["material_cost"],quote["labor_cost"],quote["additional_costs"]))
    jid=cur.lastrowid;ensure_job_chat(c,jid,name,worker_id);c.execute("INSERT INTO invoices(job_id,total,deposit,paid,status) VALUES(?,?,0,0,'Unpaid')",(jid,quote["total"]));c.commit();c.close();return jsonify(id=jid,quote=quote)
@app.route("/api/jobs/<int:jid>",methods=["PATCH"])
def update_job(jid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {};c=db()
    if not c.execute("SELECT id FROM jobs WHERE id=?",(jid,)).fetchone():c.close();return jsonify(error="Job not found"),404
    locked=c.execute("SELECT status FROM invoices WHERE job_id=?",(jid,)).fetchone()
    if locked and locked["status"]=="Payment Requested" and ("total" in d or "customer_email" in d or ("status" in d and str(d["status"]).lower()!="complete")):
        c.close();return jsonify(error="A final payment request is active. Resolve or collect it before changing the price, customer, or job status."),409
    fields=[];vals=[]
    for k in ["name","type","progress","status","worker_id","address"]:
        if k in d: fields.append(k+"=?");vals.append(d[k])
    if "total" in d:
        try:manual_total=float(d["total"])
        except (TypeError,ValueError):c.close();return jsonify(error="Enter a valid price"),400
        pricing=c.execute("SELECT material_cost,labor_cost,profit_target FROM jobs WHERE id=?",(jid,)).fetchone()
        setting=c.execute("SELECT value FROM pricing_settings WHERE key='minimum_profit'").fetchone();min_profit=max(500,float(setting["value"]) if setting else 500)
        floor=float(pricing["material_cost"])+float(pricing["labor_cost"])+float(pricing["additional_costs"])+max(min_profit,float(pricing["profit_target"]))
        if manual_total+0.000001<floor:c.close();return jsonify(error="Price must preserve at least $%.2f estimated profit"%max(min_profit,float(pricing["profit_target"]))),400
        fields.append("total=?");vals.append(manual_total);c.execute("UPDATE invoices SET total=? WHERE job_id=?",(manual_total,jid))
    if "customer_email" in d:
        email=str(d.get("customer_email") or "").strip()
        customer=c.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND role='customer'",(email,)).fetchone() if email else None
        if email and not customer:c.close();return jsonify(error="No customer account matches that email"),400
        fields.append("customer_id=?");vals.append(customer["id"] if customer else None)
    if not fields:return jsonify(ok=True)
    prior=c.execute("SELECT worker_id FROM jobs WHERE id=?",(jid,)).fetchone()
    vals.append(jid);c.execute("UPDATE jobs SET "+",".join(fields)+" WHERE id=?",vals)
    job=c.execute("SELECT name,worker_id FROM jobs WHERE id=?",(jid,)).fetchone()
    ensure_job_chat(c,jid,job["name"],job["worker_id"],False)
    if prior and prior["worker_id"] and prior["worker_id"]!=job["worker_id"]:
        grp=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(jid,)).fetchone()
        if grp:c.execute("DELETE FROM chat_group_members WHERE group_id=? AND user_id=?",(grp["id"],prior["worker_id"]))
    if prior and prior["worker_id"]!=job["worker_id"] and job["worker_id"]:
        grp=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(jid,)).fetchone()
        if grp:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(grp["id"],job["worker_id"],u["id"],stamp()))
    c.commit();c.close();return jsonify(ok=True)

@app.route("/api/jobs/<int:jid>/price",methods=["PATCH"])
def reprice_job(jid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {};c=db();job=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    invoice_row=c.execute("SELECT status FROM invoices WHERE job_id=?",(jid,)).fetchone()
    if invoice_row and invoice_row["status"]=="Payment Requested":c.close();return jsonify(error="A final payment request is active. Resolve or collect it before changing the price."),409
    job_type=str(d.get("type",job["type"] or "Custom Work")).strip() or "Custom Work"
    try:quote=calculate_quote(c,d,job_type)
    except ValueError as e:c.close();return jsonify(error=str(e)),400
    worker_id=None
    try:worker_id=int(d.get("worker_id")) if str(d.get("worker_id","")).strip() else None
    except (TypeError,ValueError):c.close();return jsonify(error="Choose a valid assigned worker"),400
    if worker_id and not c.execute("SELECT id FROM users WHERE id=? AND role='worker' AND employment_status='active'",(worker_id,)).fetchone():c.close();return jsonify(error="Choose an active worker"),400
    customer_id=job["customer_id"]
    if "customer_email" in d:
        email=str(d.get("customer_email") or "").strip()
        customer=c.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND role='customer'",(email,)).fetchone() if email else None
        if email and not customer:c.close();return jsonify(error="No customer account matches that email"),400
        customer_id=customer["id"] if customer else None
    c.execute("UPDATE jobs SET name=?,type=?,address=?,worker_id=?,customer_id=?,total=?,drywall_sheets=?,crew_hours=?,crew_size=?,labor_rate=?,sheet_cost=?,profit_target=?,material_cost=?,labor_cost=?,additional_costs=?,pricing_complete=1 WHERE id=?",(str(d.get("name",job["name"])).strip() or job["name"],job_type,d.get("address",job["address"]),worker_id,customer_id,quote["total"],quote["drywall_sheets"],quote["crew_hours"],quote["crew_size"],quote["labor_rate"],quote["sheet_cost"],quote["profit_target"],quote["material_cost"],quote["labor_cost"],quote["additional_costs"],jid))
    c.execute("UPDATE invoices SET total=? WHERE job_id=?",(quote["total"],jid))
    ensure_job_chat(c,jid,str(d.get("name",job["name"])).strip() or job["name"],worker_id,False)
    if job["worker_id"]!=worker_id:
        group=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(jid,)).fetchone()
        if group:
            if job["worker_id"]:c.execute("DELETE FROM chat_group_members WHERE group_id=? AND user_id=?",(group["id"],job["worker_id"]))
            if worker_id:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(group["id"],worker_id,u["id"],stamp()))
    c.commit();c.close();return jsonify(ok=True,quote=quote)

@app.route("/api/jobs/<int:jid>",methods=["DELETE"])
def delete_job(jid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();job=c.execute("SELECT id FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    files=[]
    for table in ["photos","blueprints","job_blueprints"]:
        rows=c.execute("SELECT path FROM photos WHERE job_id=?",(jid,)).fetchall() if table=="photos" else c.execute("SELECT png_path FROM "+table+" WHERE job_id=?",(jid,)).fetchall()
        for row in rows:files.append(row[0])
    for row in c.execute("SELECT blueprint_png_path FROM inspections WHERE job_id=? AND blueprint_png_path IS NOT NULL",(jid,)).fetchall():files.append(row[0])
    for row in c.execute("SELECT path FROM inspection_photos WHERE inspection_id IN (SELECT id FROM inspections WHERE job_id=?)",(jid,)).fetchall():files.append(row[0])
    c.execute("DELETE FROM inspection_photos WHERE inspection_id IN (SELECT id FROM inspections WHERE job_id=?)",(jid,))
    for table in ["messages","photos","time_entries","invoices","blueprints","job_blueprints","inspections"]:c.execute("DELETE FROM "+table+" WHERE job_id=?",(jid,))
    group=c.execute("SELECT id FROM chat_groups WHERE kind='job' AND job_id=?",(jid,)).fetchone()
    if group:c.execute("DELETE FROM group_messages WHERE group_id=?",(group["id"],));c.execute("DELETE FROM chat_group_members WHERE group_id=?",(group["id"],));c.execute("DELETE FROM chat_groups WHERE id=?",(group["id"],))
    c.execute("DELETE FROM jobs WHERE id=?",(jid,));c.commit();c.close()
    for name in files:
        try:os.remove(os.path.join(UPLOAD,os.path.basename(name)))
        except OSError:pass
    return jsonify(ok=True)
@app.route("/api/messages/<int:jid>")
def get_messages(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();job=c.execute("SELECT id,worker_id,customer_id FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    if u["role"]=="worker" and job["worker_id"]!=u["id"] or u["role"]=="customer" and job["customer_id"]!=u["id"]:c.close();return jsonify(error="You do not have access to this job conversation"),403
    rows=c.execute("SELECT m.*,u.name FROM messages m JOIN users u ON u.id=m.sender_id WHERE job_id=? ORDER BY m.id",(jid,)).fetchall();c.close()
    return jsonify(messages=[dict(x) for x in rows])
@app.route("/api/messages/<int:jid>",methods=["POST"])
def post_message(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    d=request.json or {};text=str(d.get("text","")).strip()
    if not text:return jsonify(error="Type a message first"),400
    if len(text)>4000:return jsonify(error="Messages must be 4,000 characters or less"),400
    c=db();job=c.execute("SELECT id,worker_id,customer_id FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    if u["role"]=="worker" and job["worker_id"]!=u["id"] or u["role"]=="customer" and job["customer_id"]!=u["id"]:c.close();return jsonify(error="You do not have access to this job conversation"),403
    c.execute("INSERT INTO messages(job_id,sender_id,text,created_at) VALUES(?,?,?,?)",(jid,u["id"],text,datetime.utcnow().isoformat()));c.commit();c.close();return jsonify(ok=True)
@app.route("/api/photos/<int:jid>",methods=["POST"])
def photo(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    f=request.files.get("photo")
    if not f:return jsonify(error="No photo"),400
    ext=os.path.splitext(secure_filename(f.filename))[1] or ".jpg";name=str(uuid.uuid4())+ext;f.save(os.path.join(UPLOAD,name))
    c=db();c.execute("INSERT INTO photos(job_id,user_id,path,caption,created_at) VALUES(?,?,?,?,?)",(jid,u["id"],name,request.form.get("caption",""),datetime.utcnow().isoformat()));c.commit();c.close()
    return jsonify(url="/uploads/"+name)
@app.route("/uploads/<path:name>")
def uploads(name):
    u=ok()
    if not u:abort(401)
    if os.path.basename(name)!=name:abort(404)
    c=db()
    row=c.execute("""SELECT job_id FROM photos WHERE path=?
      UNION SELECT job_id FROM blueprints WHERE png_path=?
      UNION SELECT job_id FROM job_blueprints WHERE png_path=?
      UNION SELECT i.job_id FROM inspection_photos p JOIN inspections i ON i.id=p.inspection_id WHERE p.path=?
      UNION SELECT job_id FROM inspections WHERE blueprint_png_path=? LIMIT 1""",(name,name,name,name,name)).fetchone()
    if not row:c.close();abort(404)
    job=c.execute("SELECT worker_id,customer_id FROM jobs WHERE id=?",(row["job_id"],)).fetchone()
    allowed=bool(job and u["role"]=="owner")
    if job and u["role"]=="customer":allowed=job["customer_id"]==u["id"]
    if job and u["role"]=="worker":
        caps=permissions(u,c);allowed=job["worker_id"]==u["id"] or caps["can_inspect"] or caps["can_manage"]
    c.close()
    if not allowed:abort(403)
    return send_from_directory(UPLOAD,name)
@app.route("/api/time/start",methods=["POST"])
def time_start():
    u=ok(["worker"])
    if not u:return jsonify(error="Active worker account required"),403
    d=request.json or {};c=db()
    if c.execute("SELECT id FROM time_entries WHERE user_id=? AND clock_out IS NULL",(u["id"],)).fetchone():c.close();return jsonify(error="You are already clocked in"),409
    job=c.execute("SELECT id,worker_id FROM jobs WHERE id=?",(d.get("job_id"),)).fetchone()
    if not job or job["worker_id"]!=u["id"]:c.close();return jsonify(error="Choose a job assigned to you"),403
    c.execute("INSERT INTO time_entries(user_id,job_id,clock_in) VALUES(?,?,?)",(u["id"],job["id"],datetime.utcnow().isoformat()));c.commit();c.close();return jsonify(ok=True)
@app.route("/api/time/stop",methods=["POST"])
def time_stop():
    u=ok(["worker"])
    if not u:return jsonify(error="Active worker account required"),403
    c=db();row=c.execute("SELECT * FROM time_entries WHERE user_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
    c.execute("DELETE FROM worker_locations WHERE user_id=?",(u["id"]))
    if row:c.execute("UPDATE time_entries SET clock_out=? WHERE id=?",(datetime.utcnow().isoformat(),row["id"]));c.commit()
    c.close();return jsonify(ok=True)
@app.route("/api/time")
def time_entries():
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();rows=c.execute("SELECT t.*,j.name job FROM time_entries t LEFT JOIN jobs j ON j.id=t.job_id WHERE t.user_id=? ORDER BY t.id DESC",(u["id"],)).fetchall();c.close()
    return jsonify(entries=[dict(x) for x in rows])
@app.route("/api/invoices/<int:jid>")
def invoice(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();r=c.execute("SELECT i.* FROM invoices i JOIN jobs j ON j.id=i.job_id WHERE i.job_id=? AND (?='owner' OR j.customer_id=?)",(jid,u["role"],u["id"])).fetchone();c.close()
    return jsonify(invoice=dict(r) if r else None)
@app.route("/api/invoices")
def invoices():
    u=ok(["owner","customer"])
    if not u:return jsonify(error="Owner or customer account required"),403
    c=db();base="SELECT i.*,j.name job_name,j.status job_status,j.address FROM invoices i JOIN jobs j ON j.id=i.job_id"
    rows=c.execute(base+(" ORDER BY i.id DESC" if u["role"]=="owner" else " WHERE j.customer_id=? ORDER BY i.id DESC"),() if u["role"]=="owner" else (u["id"],)).fetchall();c.close()
    return jsonify(invoices=[dict(r) for r in rows])
@app.route("/api/payment-config")
def payment_config():
    return jsonify(stripe_enabled=APP_ENV=="production" and bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_WEBHOOK_SECRET")),demo_mode=DEMO_MODE)
@app.route("/api/invoices/<int:jid>/request-payment",methods=["POST"])
def request_invoice_payment(jid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();job=c.execute("SELECT id,status,customer_id FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    if str(job["status"]).lower()!="complete":c.close();return jsonify(error="Mark the job complete before requesting final payment"),400
    if not job["customer_id"]:c.close();return jsonify(error="Link a customer account to this job before requesting payment"),400
    row=c.execute("SELECT * FROM invoices WHERE job_id=?",(jid,)).fetchone()
    if not row:c.close();return jsonify(error="Invoice not found"),404
    if float(row["total"] or 0)<=float(row["paid"] or 0):c.close();return jsonify(error="There is no remaining balance to request"),400
    if row["status"]=="Payment Requested":c.close();return jsonify(error="Payment has already been requested"),409
    requested=stamp();c.execute("UPDATE invoices SET status='Payment Requested',payment_requested_at=? WHERE job_id=?",(requested,jid));c.commit();c.close()
    return jsonify(ok=True,status="Payment Requested",payment_requested_at=requested)
@app.route("/api/payments/demo/<int:jid>",methods=["POST"])
def pay(jid):
    if not DEMO_MODE:return jsonify(error="Demo payments are disabled in production; use Stripe checkout"),403
    u=ok(["owner","customer"])
    if not u:return jsonify(error="Unauthorized"),403
    c=db();r=c.execute("SELECT i.*,j.customer_id FROM invoices i JOIN jobs j ON j.id=i.job_id WHERE i.job_id=? AND (?='owner' OR (j.customer_id=? AND i.status='Payment Requested'))",(jid,u["role"],u["id"])).fetchone()
    if not r:return jsonify(error="Invoice not found"),404
    remaining=max(0,r["total"]-r["paid"])
    if not remaining:c.close();return jsonify(error="Invoice has no remaining balance"),400
    c.execute("UPDATE invoices SET paid=total,status='Paid' WHERE job_id=?",(jid,));c.commit();c.close()
    return jsonify(ok=True,paid=remaining,status="Paid")

@app.route("/api/payments/checkout/<int:jid>",methods=["POST"])
def stripe_checkout(jid):
    u=ok(["customer"])
    if not u:return jsonify(error="Customer account required"),403
    if APP_ENV!="production":return jsonify(error="Live checkout is available only on the hosted production site"),403
    if not os.environ.get("STRIPE_SECRET_KEY") or not os.environ.get("STRIPE_WEBHOOK_SECRET"):return jsonify(error="Secure online payments are not fully configured yet"),503
    c=db();c.execute("BEGIN IMMEDIATE");row=c.execute("SELECT i.*,j.name job_name,j.customer_id FROM invoices i JOIN jobs j ON j.id=i.job_id WHERE i.job_id=? AND j.customer_id=?",(jid,u["id"])).fetchone()
    if not row:c.close();return jsonify(error="Invoice not found"),404
    if row["status"]!="Payment Requested":c.close();return jsonify(error="The owner has not requested payment for this invoice"),400
    amount=max(0,int(round((float(row["total"])-float(row["paid"]))*100)))
    if amount<=0:c.close();return jsonify(error="Invoice has no remaining balance"),400
    stripe.api_key=os.environ["STRIPE_SECRET_KEY"]
    existing=row["stripe_session_id"]
    if existing:
        try:
            prior=stripe.checkout.Session.retrieve(existing)
            if prior.status=="open":c.close();return jsonify(url=prior.url)
            if prior.status=="complete":c.close();return jsonify(error="Stripe is confirming the payment. Refresh Payments in a moment."),409
        except Exception:app.logger.info("Unable to reuse prior checkout session for invoice %s",jid)
    base_url=os.environ.get("BASECOAT_PUBLIC_URL",request.host_url.rstrip("/"))
    if APP_ENV=="production" and not base_url.startswith("https://"):
        c.close();return jsonify(error="Set BASECOAT_PUBLIC_URL to the secure HTTPS address for your site"),503
    try:
        checkout=stripe.checkout.Session.create(mode="payment",currency="usd",customer_email=u["email"],client_reference_id=str(jid),line_items=[{"price_data":{"currency":"usd","product_data":{"name":"Basecoat · "+row["job_name"],"description":"Final invoice balance"},"unit_amount":amount},"quantity":1}],metadata={"job_id":str(jid),"customer_id":str(u["id"])},success_url=base_url+"/?payment=success&session_id={CHECKOUT_SESSION_ID}",cancel_url=base_url+"/?payment=cancelled",idempotency_key="basecoat-invoice-%s-%s"%(jid,uuid.uuid4()))
    except Exception:
        app.logger.exception("Stripe checkout creation failed for invoice %s",jid);c.close();return jsonify(error="Could not start secure checkout. Please try again or contact Basecoat."),502
    c.execute("UPDATE invoices SET stripe_session_id=? WHERE job_id=?",(checkout.id,jid));c.commit();c.close();return jsonify(url=checkout.url)

@app.route("/api/stripe/webhook",methods=["POST"])
def stripe_webhook():
    secret=os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:return jsonify(error="Webhook not configured"),503
    try:event=stripe.Webhook.construct_event(request.get_data(cache=False),request.headers.get("Stripe-Signature",""),secret)
    except (ValueError,stripe.error.SignatureVerificationError):return jsonify(error="Invalid webhook signature"),400
    if event["type"] in ("checkout.session.completed","checkout.session.async_payment_succeeded"):
        checkout=event["data"]["object"]
        metadata=checkout.get("metadata") or {}
        try:jid=int(metadata.get("job_id","0"))
        except (TypeError,ValueError):jid=0
        if jid and checkout.get("payment_status")=="paid":
            c=db();invoice=c.execute("SELECT total,paid,stripe_session_id FROM invoices WHERE job_id=?",(jid,)).fetchone()
            expected=int(round((float(invoice["total"])-float(invoice["paid"]))*100)) if invoice else 0
            if invoice and invoice["stripe_session_id"]==checkout.get("id") and expected>0 and checkout.get("amount_total")==expected and checkout.get("currency")=="usd" and float(invoice["paid"] or 0)<float(invoice["total"] or 0):
                c.execute("UPDATE invoices SET paid=total,status='Paid' WHERE job_id=?",(jid,));c.commit()
            elif invoice and invoice["stripe_session_id"]==checkout.get("id"):app.logger.error("Stripe amount did not match current invoice %s; manual reconciliation is required",jid)
            c.close()
    elif event["type"] in ("checkout.session.async_payment_failed","checkout.session.expired"):
        checkout=event["data"]["object"]
        c=db();c.execute("UPDATE invoices SET stripe_session_id=NULL WHERE stripe_session_id=?",(checkout.get("id"),));c.commit();c.close()
    return jsonify(received=True)
@app.route("/api/blueprint/save",methods=["POST"])
def blueprint():
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Unauthorized"),403
    d=request.json or {};data=d.get("png","")
    if "," in data:data=data.split(",",1)[1]
    name="blueprint_"+str(uuid.uuid4())+".png";open(os.path.join(UPLOAD,name),"wb").write(base64.b64decode(data))
    return jsonify(url="/uploads/"+name)

@app.route("/api/blueprints/<int:jid>",methods=["GET"])
def get_job_blueprint(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    plane=request.args.get("plane","xy").lower()
    if plane not in ["xy","xz","yz"]:return jsonify(error="Unknown blueprint view"),400
    c=db();row=c.execute("SELECT png_path,scale,units,origin_x,origin_y,canvas_width,canvas_height,updated_at FROM job_blueprints WHERE job_id=? AND plane=?",(jid,plane)).fetchone()
    if not row and plane=="xy":
        old=c.execute("SELECT png_path,updated_at FROM blueprints WHERE job_id=?",(jid,)).fetchone()
        if old:row={"png_path":old["png_path"],"scale":None,"units":"ft","origin_x":0,"origin_y":0,"canvas_width":None,"canvas_height":None,"updated_at":old["updated_at"]}
    c.close()
    if not row:return jsonify(blueprint=None)
    return jsonify(blueprint={"url":"/uploads/"+row["png_path"],"scale":row["scale"],"units":row["units"],"origin_x":row["origin_x"],"origin_y":row["origin_y"],"canvas_width":row["canvas_width"],"canvas_height":row["canvas_height"],"updated_at":row["updated_at"]})

@app.route("/api/blueprints/<int:jid>",methods=["PUT"])
def save_job_blueprint(jid):
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Owner or worker access required"),403
    d=request.json or {};data=d.get("png","");plane=str(d.get("plane","xy")).lower()
    if plane not in ["xy","xz","yz"]:return jsonify(error="Unknown blueprint view"),400
    if "," in data:data=data.split(",",1)[1]
    try:raw=base64.b64decode(data,validate=True)
    except Exception:return jsonify(error="Invalid PNG data"),400
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):return jsonify(error="Blueprint must be a PNG image"),400
    c=db();job=c.execute("SELECT id FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    name="blueprint_"+str(jid)+"_"+str(uuid.uuid4())+".png"
    with open(os.path.join(UPLOAD,name),"wb") as f:f.write(raw)
    updated=datetime.utcnow().isoformat()
    try:scale=float(d["scale"]) if d.get("scale") else None
    except (TypeError,ValueError):c.close();return jsonify(error="Invalid calibration scale"),400
    units=d.get("units","ft")
    if units not in ["ft","in","m","cm"]:units="ft"
    try:origin_x=float(d.get("origin_x",0));origin_y=float(d.get("origin_y",0))
    except (TypeError,ValueError):c.close();return jsonify(error="Invalid origin coordinates"),400
    try:canvas_width=float(d.get("canvas_width"));canvas_height=float(d.get("canvas_height"))
    except (TypeError,ValueError):c.close();return jsonify(error="Canvas size is required to preserve the drawing scale"),400
    c.execute("INSERT INTO job_blueprints(job_id,plane,png_path,scale,units,origin_x,origin_y,canvas_width,canvas_height,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,plane) DO UPDATE SET png_path=excluded.png_path,scale=excluded.scale,units=excluded.units,origin_x=excluded.origin_x,origin_y=excluded.origin_y,canvas_width=excluded.canvas_width,canvas_height=excluded.canvas_height,updated_at=excluded.updated_at",(jid,plane,name,scale,units,origin_x,origin_y,canvas_width,canvas_height,updated))
    c.commit();c.close();return jsonify(ok=True,url="/uploads/"+name,updated_at=updated)
@app.route("/api/accounts",methods=["GET","POST"])
def accounts():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db()
    if request.method=="GET":
        rows=c.execute("SELECT id,name,email,role,rate,employment_status,approval_status,rank_id FROM users ORDER BY role,name").fetchall();c.close();return jsonify(accounts=[dict(x) for x in rows])
    d=request.json or {};name=str(d.get("name","")).strip();email=str(d.get("email","")).strip().lower();password=str(d.get("password", ""));role=str(d.get("role", ""))
    if not name or len(name)>100 or "@" not in email or len(email)>254:c.close();return jsonify(error="Enter a name and valid email address"),400
    if role not in ("worker","customer"):c.close();return jsonify(error="Choose a worker or customer account"),400
    if len(password)<12:c.close();return jsonify(error="Set a temporary password with at least 12 characters"),400
    if c.execute("SELECT id FROM users WHERE lower(email)=lower(?)",(email,)).fetchone():c.close();return jsonify(error="An account with that email already exists"),409
    rank_id=None;rate=0
    if role=="worker":
        try:rate=max(0,float(d.get("rate",0)))
        except (TypeError,ValueError):c.close();return jsonify(error="Enter a valid hourly rate"),400
        try:rank_id=int(d.get("rank_id")) if d.get("rank_id") else None
        except (TypeError,ValueError):c.close();return jsonify(error="Choose a valid rank"),400
        if rank_id and not c.execute("SELECT id FROM ranks WHERE id=?",(rank_id,)).fetchone():c.close();return jsonify(error="Rank not found"),404
    cur=c.execute("INSERT INTO users(email,password,role,name,rate,employment_status,rank_id) VALUES(?,?,?,?,?,'active',?)",(email,generate_password_hash(password),role,name,rate,rank_id));uid=cur.lastrowid
    if role=="worker":
        company=c.execute("SELECT id FROM chat_groups WHERE kind='company' LIMIT 1").fetchone()
        if company:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(company["id"],uid,u["id"],stamp()))
        if rank_id:
            group=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(rank_id,)).fetchone()
            if group:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(group["id"],uid,u["id"],stamp()))
    c.commit();c.close();return jsonify(ok=True,id=uid)

@app.route("/api/worker-applications",methods=["GET"])
def worker_applications():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();rows=c.execute("SELECT id,name,email,rank_id FROM users WHERE role='worker' AND approval_status='pending' ORDER BY id").fetchall();c.close()
    return jsonify(applications=[dict(x) for x in rows])

@app.route("/api/worker-applications/<int:uid>",methods=["PATCH"])
def review_worker_application(uid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {};decision=d.get("decision")
    if decision not in ("approved","declined"):return jsonify(error="Choose approve or decline"),400
    c=db();worker=c.execute("SELECT id FROM users WHERE id=? AND role='worker' AND approval_status='pending'",(uid,)).fetchone()
    if not worker:c.close();return jsonify(error="Pending worker application not found"),404
    if decision=="approved":
        try:rate=max(0,float(d.get("rate",22)));rank_id=int(d.get("rank_id")) if d.get("rank_id") else None
        except (TypeError,ValueError):c.close();return jsonify(error="Enter a valid hourly rate and rank"),400
        if rank_id and not c.execute("SELECT id FROM ranks WHERE id=?",(rank_id,)).fetchone():c.close();return jsonify(error="Rank not found"),404
        c.execute("UPDATE users SET approval_status='approved',rate=?,rank_id=? WHERE id=?",(rate,rank_id,uid))
        company=c.execute("SELECT id FROM chat_groups WHERE kind='company' LIMIT 1").fetchone()
        if company:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(company["id"],uid,u["id"],stamp()))
        if rank_id:
            group=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(rank_id,)).fetchone()
            if group:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(group["id"],uid,u["id"],stamp()))
    else:c.execute("UPDATE users SET approval_status='declined',employment_status='fired' WHERE id=?",(uid,))
    c.commit();c.close();return jsonify(ok=True)

def distance_m(lat1,lon1,lat2,lon2):
    from math import radians,sin,cos,asin,sqrt
    dlat=radians(lat2-lat1);dlon=radians(lon2-lon1);a=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 6371000*2*asin(sqrt(a))

@app.route("/api/jobs/<int:jid>/geofence",methods=["PATCH"])
def set_geofence(jid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {}
    try:lat=float(d["lat"]);lon=float(d["lon"]);radius=float(d.get("radius_m",152.4))
    except (KeyError,TypeError,ValueError):return jsonify(error="Enter a valid site location and radius"),400
    if not -90<=lat<=90 or not -180<=lon<=180 or not 25<=radius<=5000:return jsonify(error="Coordinates or radius are outside the allowed range"),400
    c=db();cur=c.execute("UPDATE jobs SET site_lat=?,site_lon=?,geofence_radius_m=? WHERE id=?",(lat,lon,radius,jid));c.commit();c.close()
    if not cur.rowcount:return jsonify(error="Job not found"),404
    return jsonify(ok=True)

@app.route("/api/locations/current",methods=["POST","DELETE"])
def worker_location():
    u=ok(["worker"])
    if not u:return jsonify(error="Approved worker account required"),403
    c=db()
    if request.method=="DELETE":c.execute("DELETE FROM worker_locations WHERE user_id=?",(u["id"])) ;c.commit();c.close();return jsonify(ok=True)
    d=request.json or {}
    try:lat=float(d["lat"]);lon=float(d["lon"]);accuracy=max(0,float(d.get("accuracy",0)))
    except (KeyError,TypeError,ValueError):c.close();return jsonify(error="Invalid location coordinates"),400
    if not -90<=lat<=90 or not -180<=lon<=180:c.close();return jsonify(error="Invalid location coordinates"),400
    active=c.execute("SELECT j.id,j.site_lat,j.site_lon,j.geofence_radius_m FROM time_entries t JOIN jobs j ON j.id=t.job_id WHERE t.user_id=? AND t.clock_out IS NULL ORDER BY t.id DESC LIMIT 1",(u["id"],)).fetchone()
    if not active:c.close();return jsonify(error="Location sharing is only available during an active shift"),403
    c.execute("INSERT INTO worker_locations(user_id,job_id,lat,lon,accuracy,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET job_id=excluded.job_id,lat=excluded.lat,lon=excluded.lon,accuracy=excluded.accuracy,updated_at=excluded.updated_at",(u["id"],active["id"],lat,lon,accuracy,stamp()));c.commit();c.close();return jsonify(ok=True)

@app.route("/api/locations")
def active_worker_locations():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();rows=c.execute("SELECT u.id worker_id,u.name worker,j.id job_id,j.name job,j.address,j.site_lat,j.site_lon,j.geofence_radius_m,l.lat,l.lon,l.accuracy,l.updated_at FROM time_entries t JOIN users u ON u.id=t.user_id JOIN jobs j ON j.id=t.job_id LEFT JOIN worker_locations l ON l.user_id=u.id AND l.job_id=j.id WHERE t.clock_out IS NULL AND u.role='worker' AND u.employment_status='active' ORDER BY u.name").fetchall();c.close();now=datetime.utcnow();result=[]
    for row in rows:
        item=dict(row);item["distance_m"]=None;item["inside_site"]=None;item["stale"]=True
        if row["lat"] is not None:
            try:item["stale"]=(now-datetime.fromisoformat(row["updated_at"])).total_seconds()>120
            except Exception:pass
            if row["site_lat"] is not None and row["site_lon"] is not None:
                item["distance_m"]=distance_m(row["site_lat"],row["site_lon"],row["lat"],row["lon"]);item["inside_site"]=item["distance_m"]<=row["geofence_radius_m"]
        result.append(item)
    return jsonify(workers=result)

@app.route("/api/workers")
def workers():
    u=ok(["owner","worker"])
    if not u or (u["role"]!="owner" and not permissions(u)["can_manage"]):return jsonify(error="Owner or authorized foreman only"),403
    c=db();rows=c.execute("SELECT u.id,u.name,u.email,u.rate,u.employment_status,u.rank_id,r.name rank FROM users u LEFT JOIN ranks r ON r.id=u.rank_id WHERE u.role='worker' ORDER BY u.employment_status,u.name").fetchall();c.close();return jsonify(workers=[dict(x) for x in rows])

@app.route("/api/ranks",methods=["GET","POST"])
def manage_ranks():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db()
    if request.method=="GET":
        rows=c.execute("SELECT id,name,sort_order,can_manage_chats,can_inspect FROM ranks ORDER BY sort_order,id").fetchall();c.close();return jsonify(ranks=[dict(x) for x in rows])
    d=request.json or {};name=str(d.get("name","")).strip()
    if not name or len(name)>40:c.close();return jsonify(error="Enter a rank name up to 40 characters"),400
    try:
        cur=c.execute("INSERT INTO ranks(name,sort_order,can_manage_chats,can_inspect) VALUES(?,COALESCE((SELECT MAX(sort_order)+1 FROM ranks),0),?,?)",(name,int(bool(d.get("can_manage_chats"))),int(bool(d.get("can_inspect")))));rid=cur.lastrowid
        gid=c.execute("INSERT INTO chat_groups(kind,name,rank_id,created_at) VALUES('rank',?,?,?)",(name+" rank chat",rid,stamp())).lastrowid;c.commit()
    except sqlite3.IntegrityError:c.close();return jsonify(error="That rank already exists"),409
    c.close();return jsonify(ok=True,id=rid,group_id=gid)

@app.route("/api/ranks/<int:rid>",methods=["PATCH","DELETE"])
def manage_rank(rid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db()
    if request.method=="DELETE":
        if not c.execute("SELECT id FROM ranks WHERE id=?",(rid,)).fetchone():c.close();return jsonify(error="Rank not found"),404
        group=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(rid,)).fetchone()
        if group:c.execute("DELETE FROM group_messages WHERE group_id=?",(group["id"],));c.execute("DELETE FROM chat_group_members WHERE group_id=?",(group["id"],));c.execute("DELETE FROM chat_groups WHERE id=?",(group["id"],))
        c.execute("UPDATE users SET rank_id=NULL WHERE rank_id=?",(rid,));c.execute("DELETE FROM ranks WHERE id=?",(rid,));c.commit();c.close();return jsonify(ok=True)
    d=request.json or {};name=str(d.get("name","")).strip()
    if not name or len(name)>40:c.close();return jsonify(error="Enter a rank name up to 40 characters"),400
    try:
        cur=c.execute("UPDATE ranks SET name=?,can_manage_chats=?,can_inspect=? WHERE id=?",(name,int(bool(d.get("can_manage_chats"))),int(bool(d.get("can_inspect"))),rid))
        c.execute("UPDATE chat_groups SET name=? WHERE kind='rank' AND rank_id=?",(name+" rank chat",rid));c.commit()
    except sqlite3.IntegrityError:c.close();return jsonify(error="That rank already exists"),409
    changed=cur.rowcount;c.close()
    if not changed:return jsonify(error="Rank not found"),404
    return jsonify(ok=True)

@app.route("/api/workers/<int:uid>",methods=["PATCH"])
def update_worker(uid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {};c=db();worker=c.execute("SELECT id,rank_id,employment_status FROM users WHERE id=? AND role='worker'",(uid,)).fetchone()
    if not worker:c.close();return jsonify(error="Worker not found"),404
    fields=[];values=[]
    if "rate" in d:
        try:rate=float(d["rate"])
        except (TypeError,ValueError):c.close();return jsonify(error="Enter a valid hourly rate"),400
        if rate<0:c.close();return jsonify(error="Hourly rate cannot be negative"),400
        fields.append("rate=?");values.append(rate)
    if "rank_id" in d:
        rank_id=d["rank_id"]
        if rank_id in (None,""):rank_id=None
        else:
            try:rank_id=int(rank_id)
            except (TypeError,ValueError):c.close();return jsonify(error="Choose a valid rank"),400
            if not c.execute("SELECT id FROM ranks WHERE id=?",(rank_id,)).fetchone():c.close();return jsonify(error="Rank not found"),404
        fields.append("rank_id=?");values.append(rank_id)
    if "employment_status" in d:
        status=d["employment_status"]
        if status not in ["active","fired"]:c.close();return jsonify(error="Choose active or fired"),400
        fields.append("employment_status=?");values.append(status)
        if status=="fired":
            c.execute("UPDATE jobs SET worker_id=NULL WHERE worker_id=? AND lower(status)!='complete'",(uid,))
            c.execute("UPDATE time_entries SET clock_out=? WHERE user_id=? AND clock_out IS NULL",(stamp(),uid))
            c.execute("DELETE FROM worker_locations WHERE user_id=?",(uid,))
    if not fields:c.close();return jsonify(error="No worker changes provided"),400
    values.append(uid);c.execute("UPDATE users SET "+",".join(fields)+" WHERE id=?",values)
    if "rank_id" in d:
        c.execute("DELETE FROM chat_group_members WHERE user_id=? AND group_id IN (SELECT id FROM chat_groups WHERE kind='rank')",(uid,))
        if rank_id:
            grp=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(rank_id,)).fetchone()
            if grp:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(grp["id"],uid,u["id"],stamp()))
    if d.get("employment_status")=="fired":c.execute("DELETE FROM chat_group_members WHERE user_id=?",(uid,))
    if d.get("employment_status")=="active" and worker["rank_id"]:
        grp=c.execute("SELECT id FROM chat_groups WHERE kind='rank' AND rank_id=?",(worker["rank_id"],)).fetchone()
        if grp:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(grp["id"],uid,u["id"],stamp()))
    if d.get("employment_status")=="active":
        company=c.execute("SELECT id FROM chat_groups WHERE kind='company' LIMIT 1").fetchone()
        if company:c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(company["id"],uid,u["id"],stamp()))
    c.commit();c.close();return jsonify(ok=True)

@app.route("/api/payroll/<int:uid>")
def worker_payroll(uid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();worker=c.execute("SELECT id,name,rate FROM users WHERE id=? AND role='worker'",(uid,)).fetchone()
    if not worker:c.close();return jsonify(error="Worker not found"),404
    entries=c.execute("SELECT clock_in,clock_out FROM time_entries WHERE user_id=? AND clock_out IS NOT NULL",(uid,)).fetchall()
    hours=0.0
    for entry in entries:
        try:hours+=max(0,(datetime.fromisoformat(entry["clock_out"])-datetime.fromisoformat(entry["clock_in"])).total_seconds()/3600)
        except (TypeError,ValueError):pass
    adjustments=c.execute("SELECT id,kind,amount,reason,authorized,status,created_at FROM pay_adjustments WHERE worker_id=? ORDER BY id DESC",(uid,)).fetchall();c.close()
    pending=[dict(x) for x in adjustments if x["status"]=="pending"]
    deductions=sum(x["amount"] for x in pending if x["kind"]=="deduction");bonuses=sum(x["amount"] for x in pending if x["kind"]=="bonus")
    gross=hours*worker["rate"]
    return jsonify(worker=dict(worker),hours=round(hours,2),gross=round(gross,2),deductions=round(deductions,2),bonuses=round(bonuses,2),net_estimate=round(gross-deductions+bonuses,2),adjustments=[dict(x) for x in adjustments])

@app.route("/api/payroll/<int:uid>/adjustments",methods=["POST"])
def add_pay_adjustment(uid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    d=request.json or {};kind=d.get("kind");reason=str(d.get("reason","")).strip()
    if kind not in ["deduction","bonus"]:return jsonify(error="Choose a deduction or bonus"),400
    try:amount=float(d.get("amount"))
    except (TypeError,ValueError):return jsonify(error="Enter a valid amount"),400
    if amount<=0:return jsonify(error="Amount must be greater than zero"),400
    if not reason:return jsonify(error="Add a reason for the adjustment"),400
    authorized=1 if d.get("authorized") is True else 0
    if kind=="deduction" and not authorized:return jsonify(error="Confirm you have documented authorization before recording a pay deduction"),400
    c=db();worker=c.execute("SELECT id FROM users WHERE id=? AND role='worker'",(uid,)).fetchone()
    if not worker:c.close();return jsonify(error="Worker not found"),404
    c.execute("INSERT INTO pay_adjustments(worker_id,kind,amount,reason,authorized,created_at) VALUES(?,?,?,?,?,?)",(uid,kind,amount,reason,authorized,datetime.utcnow().isoformat()));c.commit();c.close()
    return jsonify(ok=True)

@app.route("/api/customers")
def customers():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();rows=c.execute("SELECT id,name,email FROM users WHERE role='customer'").fetchall();c.close();return jsonify(customers=[dict(x) for x in rows])

@app.route("/api/pricing-settings",methods=["GET","PUT"])
def pricing_settings_api():
    u=ok()
    if not u or (request.method=="PUT" and u["role"]!="owner") or (request.method=="GET" and u["role"]!="owner" and not permissions(u)["can_manage"]):return jsonify(error="Owner or authorized foreman only"),403
    c=db()
    if request.method=="GET":
        settings,types=pricing_data(c);c.close();return jsonify(settings=settings,work_types=types)
    d=request.json or {}
    try:
        sheet_cost=float(d.get("drywall_sheet_cost"))
        minimum_profit=float(d.get("minimum_profit"))
        labor_rate=float(d.get("default_labor_rate"))
    except (TypeError,ValueError):c.close();return jsonify(error="Enter valid pricing amounts"),400
    if sheet_cost<0 or labor_rate<0 or minimum_profit<500:c.close();return jsonify(error="Sheet cost and labor rate cannot be negative. Minimum profit cannot be below $500."),400
    c.execute("UPDATE pricing_settings SET value=? WHERE key='drywall_sheet_cost'",(sheet_cost,))
    c.execute("UPDATE pricing_settings SET value=? WHERE key='minimum_profit'",(minimum_profit,))
    c.execute("UPDATE pricing_settings SET value=? WHERE key='default_labor_rate'",(labor_rate,))
    for item in d.get("work_types",[]):
        name=str(item.get("name","")).strip()
        try:hours=float(item.get("hours_per_sheet"))
        except (TypeError,ValueError):c.close();return jsonify(error="Enter valid hours-per-sheet estimates for every work type"),400
        if not name or len(name)>60 or hours<0:c.close();return jsonify(error="Work type names must be 1–60 characters and estimated hours cannot be negative"),400
        c.execute("INSERT INTO work_types(name,hours_per_sheet) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET hours_per_sheet=excluded.hours_per_sheet",(name,hours))
    c.commit();settings,types=pricing_data(c);c.close();return jsonify(ok=True,settings=settings,work_types=types)

def group_access(u,c,gid,manage=False):
    g=c.execute("SELECT * FROM chat_groups WHERE id=?",(gid,)).fetchone()
    if not g:return None
    caps=permissions(u,c)
    if u["role"]=="owner" or caps["can_manage"]:return g
    member=c.execute("SELECT 1 FROM chat_group_members WHERE group_id=? AND user_id=?",(gid,u["id"])).fetchone()
    return g if member else None

@app.route("/api/chat-groups")
def chat_groups():
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Team accounts only"),403
    c=db();caps=permissions(u,c)
    where="" if u["role"]=="owner" or caps["can_manage"] else "WHERE EXISTS (SELECT 1 FROM chat_group_members m WHERE m.group_id=g.id AND m.user_id=?)"
    args=() if not where else (u["id"],)
    rows=c.execute("SELECT g.*,r.name rank_name,j.name job_name FROM chat_groups g LEFT JOIN ranks r ON r.id=g.rank_id LEFT JOIN jobs j ON j.id=g.job_id "+where+" ORDER BY g.kind,g.name",args).fetchall();c.close()
    return jsonify(groups=[dict(x) for x in rows])

@app.route("/api/chat-groups/<int:gid>")
def get_chat_group(gid):
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Team accounts only"),403
    c=db();g=group_access(u,c,gid)
    if not g:c.close();return jsonify(error="You are not a member of this group"),403
    caps=permissions(u,c);manager=(u["role"]=="owner" or caps["can_manage"]) and g["kind"]!="company"
    members=c.execute("SELECT u.id,u.name,u.email,r.name rank FROM chat_group_members m JOIN users u ON u.id=m.user_id LEFT JOIN ranks r ON r.id=u.rank_id WHERE m.group_id=? ORDER BY u.name",(gid,)).fetchall()
    workers=c.execute("SELECT u.id,u.name,u.email,r.name rank FROM users u LEFT JOIN ranks r ON r.id=u.rank_id WHERE u.role='worker' AND u.employment_status='active' ORDER BY u.name").fetchall() if manager else []
    msgs=c.execute("SELECT m.*,u.name FROM group_messages m JOIN users u ON u.id=m.sender_id WHERE m.group_id=? ORDER BY m.id DESC LIMIT 100",(gid,)).fetchall();c.close()
    return jsonify(group=dict(g),members=[dict(x) for x in members],workers=[dict(x) for x in workers],messages=[dict(x) for x in reversed(msgs)],can_manage=manager)

@app.route("/api/chat-groups/<int:gid>/messages",methods=["POST"])
def post_group_message(gid):
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Team accounts only"),403
    text=str((request.json or {}).get("text","")).strip()
    if not text or len(text)>4000:return jsonify(error="Enter a message up to 4,000 characters"),400
    c=db()
    if not group_access(u,c,gid):c.close();return jsonify(error="You are not a member of this group"),403
    c.execute("INSERT INTO group_messages(group_id,sender_id,text,created_at) VALUES(?,?,?,?)",(gid,u["id"],text,stamp()));c.commit();c.close();return jsonify(ok=True)

@app.route("/api/chat-groups/<int:gid>/members",methods=["POST"])
def add_group_member(gid):
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Team accounts only"),403
    c=db();g=group_access(u,c,gid,True)
    if not g:c.close();return jsonify(error="Only the owner or an authorized foreman can manage group members"),403
    try:uid=int((request.json or {}).get("user_id"))
    except (TypeError,ValueError):c.close();return jsonify(error="Choose an active worker"),400
    worker=c.execute("SELECT id FROM users WHERE id=? AND role='worker' AND employment_status='active'",(uid,)).fetchone()
    if not worker:c.close();return jsonify(error="Active worker not found"),404
    c.execute("INSERT OR IGNORE INTO chat_group_members(group_id,user_id,added_by,created_at) VALUES(?,?,?,?)",(gid,uid,u["id"],stamp()));c.commit();c.close();return jsonify(ok=True)

@app.route("/api/chat-groups/<int:gid>/members/<int:uid>",methods=["DELETE"])
def remove_group_member(gid,uid):
    u=ok(["owner","worker"])
    if not u:return jsonify(error="Team accounts only"),403
    c=db();g=group_access(u,c,gid,True)
    if not g:c.close();return jsonify(error="Only the owner or an authorized foreman can manage group members"),403
    if g["kind"]=="company":c.close();return jsonify(error="The company chat includes every active team member. Fire or deactivate a worker to remove their access."),400
    c.execute("DELETE FROM chat_group_members WHERE group_id=? AND user_id=?",(gid,uid));c.commit();c.close();return jsonify(ok=True)

@app.route("/api/inspections/<int:jid>",methods=["GET","POST"])
def job_inspections(jid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();job=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
    if not job:c.close();return jsonify(error="Job not found"),404
    caps=permissions(u,c)
    allowed=u["role"]=="owner" or (u["role"]=="worker" and (job["worker_id"]==u["id"] or caps["can_inspect"] or caps["can_manage"]))
    if not allowed:c.close();return jsonify(error="You cannot view this inspection report"),403
    if request.method=="POST":
        if u["role"]!="owner" and not caps["can_inspect"]:c.close();return jsonify(error="Inspector rank required"),403
        d=request.json or {};notes=str(d.get("notes","")).strip()
        try:rating=int(d.get("rating"))
        except (TypeError,ValueError):c.close();return jsonify(error="Choose a rating from 1 to 5"),400
        if rating<1 or rating>5 or not notes:c.close();return jsonify(error="Choose a 1–5 rating and add inspection notes"),400
        plane=str(d.get("blueprint_plane","xy"));markers=d.get("blueprint_markers",[])
        if plane not in ("xy","xz","yz"):plane="xy"
        if not isinstance(markers,list) or len(markers)>100:c.close();return jsonify(error="Invalid blueprint issue markers"),400
        try:
            clean=[]
            for m in markers:
                x=float(m.get("x"));y=float(m.get("y"));note=str(m.get("note","")).strip()[:240]
                if not 0<=x<=1 or not 0<=y<=1:raise ValueError()
                clean.append({"x":x,"y":y,"note":note})
        except (TypeError,ValueError,AttributeError):c.close();return jsonify(error="Invalid blueprint issue markers"),400
        bp=c.execute("SELECT png_path FROM job_blueprints WHERE job_id=? AND plane=?",(jid,plane)).fetchone() if clean else None
        if clean and not bp:c.close();return jsonify(error="Save a blueprint for this view before adding location pins"),400
        snapshot=None
        if bp:
            snapshot="inspection_blueprint_"+str(uuid.uuid4())+".png"
            with open(os.path.join(UPLOAD,snapshot),"wb") as out,open(os.path.join(UPLOAD,bp["png_path"]),"rb") as src:out.write(src.read())
        cur=c.execute("INSERT INTO inspections(job_id,inspector_id,rating,notes,created_at,blueprint_plane,blueprint_markers,blueprint_png_path) VALUES(?,?,?,?,?,?,?,?)",(jid,u["id"],rating,notes,stamp(),plane,__import__('json').dumps(clean),snapshot));c.commit();iid=cur.lastrowid
        c.close();return jsonify(ok=True,id=iid)
    rows=c.execute("SELECT i.*,u.name inspector FROM inspections i JOIN users u ON u.id=i.inspector_id WHERE i.job_id=? ORDER BY i.id DESC",(jid,)).fetchall();result=[]
    for row in rows:
        item=dict(row)
        try:item["blueprint_markers"]=__import__('json').loads(item.get("blueprint_markers") or "[]")
        except ValueError:item["blueprint_markers"]=[]
        item["blueprint_url"]="/uploads/"+item["blueprint_png_path"] if item.get("blueprint_png_path") else None
        item["photos"]=[dict(p) for p in c.execute("SELECT id,path,caption,created_at FROM inspection_photos WHERE inspection_id=? ORDER BY id",(item["id"],)).fetchall()]
        for photo in item["photos"]:photo["url"]="/uploads/"+photo.pop("path")
        result.append(item)
    c.close();return jsonify(inspections=result)

@app.route("/api/inspections/<int:jid>/<int:iid>/photos",methods=["POST"])
def inspection_photos(jid,iid):
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();job=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone();caps=permissions(u,c)
    if not job or not c.execute("SELECT id FROM inspections WHERE id=? AND job_id=? AND inspector_id=?",(iid,jid,u["id"])).fetchone():
        c.close();return jsonify(error="Inspection report not found"),404
    if u["role"]!="owner" and not caps["can_inspect"]:c.close();return jsonify(error="Inspector rank required"),403
    files=request.files.getlist("photos")
    if not files or len(files)>10:c.close();return jsonify(error="Choose between 1 and 10 photos"),400
    saved=[]
    for f in files:
        if not f.filename:continue
        ext=os.path.splitext(secure_filename(f.filename))[1].lower()
        if ext not in (".jpg",".jpeg",".png",".webp",".gif"):c.close();return jsonify(error="Use JPG, PNG, WEBP, or GIF photos"),400
        name="inspection_"+str(uuid.uuid4())+ext;path=os.path.join(UPLOAD,name);f.save(path)
        if os.path.getsize(path)>12*1024*1024:
            os.remove(path);c.close();return jsonify(error="Each photo must be 12 MB or smaller"),400
        caption=str(request.form.get("caption", "")).strip()[:240]
        c.execute("INSERT INTO inspection_photos(inspection_id,path,caption,created_at) VALUES(?,?,?,?)",(iid,name,caption,stamp()));saved.append("/uploads/"+name)
    c.commit();c.close();return jsonify(ok=True,photos=saved)

@app.route("/api/job-requests",methods=["GET","POST"])
def job_requests():
    u=ok()
    if not u:return jsonify(error="Unauthorized"),401
    c=db();caps=permissions(u,c)
    if request.method=="POST":
        if u["role"]!="customer":c.close();return jsonify(error="Customer account required"),403
        if c.execute("SELECT id FROM blacklist WHERE customer_id=?",(u["id"],)).fetchone():c.close();return jsonify(error="This account cannot submit new job requests. Contact Basecoat for information."),403
        d=request.json or {};description=str(d.get("description","")).strip();address=str(d.get("address","")).strip()
        if not description or not address:c.close();return jsonify(error="Describe the work and enter the job-site address"),400
        budget=None
        try:budget=float(d["budget"]) if str(d.get("budget","")).strip() else None
        except (TypeError,ValueError):c.close();return jsonify(error="Enter a valid budget or leave it blank"),400
        cur=c.execute("INSERT INTO job_requests(customer_id,description,address,preferred_date,budget,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(u["id"],description,address,str(d.get("preferred_date", "")),budget,stamp(),stamp()));c.commit();rid=cur.lastrowid
        c.close();return jsonify(ok=True,id=rid)
    if u["role"]=="customer":rows=c.execute("SELECT q.*,u.name customer_name FROM job_requests q JOIN users u ON u.id=q.customer_id WHERE q.customer_id=? ORDER BY q.id DESC",(u["id"],)).fetchall()
    elif u["role"]=="owner" or caps["can_manage"]:rows=c.execute("SELECT q.*,u.name customer_name,u.email customer_email FROM job_requests q JOIN users u ON u.id=q.customer_id ORDER BY q.id DESC").fetchall()
    else:c.close();return jsonify(error="Owner or foreman access required"),403
    c.close();return jsonify(requests=[dict(x) for x in rows])

@app.route("/api/job-requests/<int:rid>",methods=["PATCH"])
def review_job_request(rid):
    u=ok();
    if not u:return jsonify(error="Unauthorized"),401
    c=db();caps=permissions(u,c)
    if u["role"]!="owner" and not caps["can_manage"]:c.close();return jsonify(error="Owner or foreman access required"),403
    q=c.execute("SELECT * FROM job_requests WHERE id=?",(rid,)).fetchone()
    if not q:c.close();return jsonify(error="Request not found"),404
    if q["status"]!="pending":c.close();return jsonify(error="This request has already been reviewed"),409
    d=request.json or {};status=d.get("status")
    if status not in ["accepted","declined"]:c.close();return jsonify(error="Choose accept or decline"),400
    note=str(d.get("review_note","")).strip();jid=q["job_id"]
    if status=="accepted" and not jid:
        if not all(k in d for k in ["drywall_sheets","crew_size","labor_rate","sheet_cost","profit_target","quote_total"]):c.close();return jsonify(error="Price this request before accepting it"),400
        name=str(d.get("name") or "Customer request").strip()[:100]
        job_type=str(d.get("type") or "Drywall Repair").strip()
        try:quote=calculate_quote(c,d,job_type)
        except ValueError as e:c.close();return jsonify(error=str(e)),400
        worker_id=None
        try:worker_id=int(d.get("worker_id")) if str(d.get("worker_id","")).strip() else None
        except (TypeError,ValueError):c.close();return jsonify(error="Choose a valid assigned worker"),400
        if worker_id and not c.execute("SELECT id FROM users WHERE id=? AND role='worker' AND employment_status='active'",(worker_id,)).fetchone():c.close();return jsonify(error="Choose an active worker"),400
        cur=c.execute("INSERT INTO jobs(name,type,worker_id,customer_id,progress,status,total,address,created_at,drywall_sheets,crew_hours,crew_size,labor_rate,sheet_cost,profit_target,material_cost,labor_cost,additional_costs,pricing_complete) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",(name,job_type,worker_id,q["customer_id"],0,"New",quote["total"],q["address"],stamp(),quote["drywall_sheets"],quote["crew_hours"],quote["crew_size"],quote["labor_rate"],quote["sheet_cost"],quote["profit_target"],quote["material_cost"],quote["labor_cost"],quote["additional_costs"]))
        jid=cur.lastrowid;ensure_job_chat(c,jid,name,worker_id);c.execute("INSERT INTO invoices(job_id,total,deposit,paid,status) VALUES(?,?,0,0,'Unpaid')",(jid,quote["total"]))
    c.execute("UPDATE job_requests SET status=?,reviewed_by=?,review_note=?,job_id=?,updated_at=? WHERE id=?",(status,u["id"],note,jid,stamp(),rid));c.commit();c.close();return jsonify(ok=True,job_id=jid)

@app.route("/api/blacklist",methods=["GET","POST"])
def manage_blacklist():
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db()
    if request.method=="GET":
        rows=c.execute("SELECT b.*,u.name customer_name,u.email customer_email FROM blacklist b JOIN users u ON u.id=b.customer_id ORDER BY b.id DESC").fetchall();c.close();return jsonify(entries=[dict(x) for x in rows])
    d=request.json or {};email=str(d.get("email","")).strip();reason=str(d.get("reason","")).strip()
    customer=c.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND role='customer'",(email,)).fetchone()
    if not customer or not reason:c.close();return jsonify(error="Enter an existing customer email and a documented reason"),400
    try:c.execute("INSERT INTO blacklist(customer_id,reason,created_at,created_by) VALUES(?,?,?,?)",(customer["id"],reason,stamp(),u["id"]))
    except sqlite3.IntegrityError:c.close();return jsonify(error="That customer is already on the request block list"),409
    c.commit();c.close();return jsonify(ok=True)

@app.route("/api/blacklist/<int:bid>",methods=["DELETE"])
def remove_blacklist(bid):
    u=ok(["owner"])
    if not u:return jsonify(error="Owner only"),403
    c=db();c.execute("DELETE FROM blacklist WHERE id=?",(bid,));c.commit();c.close();return jsonify(ok=True)

@app.route("/api/health")
def health():return jsonify(ok=True,app="Basecoat",version="1.1.0")
if __name__=="__main__": app.run(host="127.0.0.1",port=5000,debug=False)

