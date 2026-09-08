import os, sqlite3, secrets
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.utils import secure_filename

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,"marassi_cctv.db")
UPLOAD=os.path.join(BASE,"static","uploads")
os.makedirs(UPLOAD,exist_ok=True)

app=Flask(__name__, static_folder="static")
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))
ALLOWED={"png","jpg","jpeg","webp","pdf"}

ROLES={"security":"مشرف الأمن","cctv":"مراقب الكاميرات CCTV","admin":"Administration - الإدارة"}
STATUSES=["New Request","Under CCTV Review","Review Completed","Closed","Rejected"]

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL, role TEXT NOT NULL, active INTEGER DEFAULT 1,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_no TEXT UNIQUE NOT NULL,
      request_date TEXT NOT NULL, requester_name TEXT NOT NULL,
      affiliation TEXT NOT NULL, mobile TEXT, event_description TEXT NOT NULL,
      event_time TEXT, event_location TEXT, specifications TEXT,
      priority TEXT DEFAULT 'Normal', status TEXT NOT NULL,
      cctv_by INTEGER, review_start TEXT, review_end TEXT,
      cctv_result TEXT, cameras_checked TEXT, footage_start TEXT,
      footage_end TEXT, cctv_notes TEXT, attachment TEXT,
      recipient_signature TEXT, recipient_time TEXT, created_by INTEGER NOT NULL,
      closed_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
      old_status TEXT, new_status TEXT NOT NULL, changed_by INTEGER NOT NULL,
      changed_at TEXT NOT NULL, note TEXT);
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      request_id INTEGER, title TEXT NOT NULL, body TEXT NOT NULL,
      is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
    """)
    for u,p,r in [("security","security123","security"),("cctv","cctv123","cctv"),("admin","admin123","admin")]:
        c.execute("INSERT OR IGNORE INTO users(username,password,role,created_at) VALUES(?,?,?,?)",
                  (u,p,r,datetime.now().isoformat(timespec="seconds")))
    c.commit(); c.close()

def me():
    if "user_id" not in session:return None
    c=db(); u=c.execute("SELECT * FROM users WHERE id=? AND active=1",(session["user_id"],)).fetchone(); c.close()
    return u

def req_login(f):
    @wraps(f)
    def w(*a,**k):
        if not me(): return redirect(url_for("login"))
        return f(*a,**k)
    return w

def role(*roles):
    def d(f):
        @wraps(f)
        def w(*a,**k):
            u=me()
            if not u:return redirect(url_for("login"))
            if u["role"] not in roles:
                flash("ليس لديك صلاحية لهذه العملية."); return redirect(url_for("dashboard"))
            return f(*a,**k)
        return w
    return d

def now(): return datetime.now().isoformat(timespec="seconds")
def next_no(c):
    y=datetime.now().year
    r=c.execute("SELECT request_no FROM requests WHERE request_no LIKE ? ORDER BY id DESC LIMIT 1",(f"CCTV-{y}-%",)).fetchone()
    n=(int(r["request_no"].split("-")[-1])+1) if r else 1
    return f"CCTV-{y}-{n:06d}"

def notify(c, roles, request_id, title, body):
    ids=c.execute("SELECT id FROM users WHERE active=1 AND role IN (%s)" % ",".join("?"*len(roles)),roles).fetchall()
    for x in ids:c.execute("INSERT INTO notifications(user_id,request_id,title,body,created_at) VALUES(?,?,?,?,?)",
                           (x["id"],request_id,title,body,now()))

def set_status(c,rid,new_status,note=""):
    old=c.execute("SELECT status FROM requests WHERE id=?",(rid,)).fetchone()["status"]
    uid=me()["id"]
    c.execute("UPDATE requests SET status=?,updated_at=? WHERE id=?",(new_status,now(),rid))
    c.execute("INSERT INTO history(request_id,old_status,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?,?)",
              (rid,old,new_status,uid,now(),note))

@app.context_processor
def ctx():
    u=me()
    if not u:return {"me":None,"roles":ROLES,"unread":0}
    c=db(); n=c.execute("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",(u["id"],)).fetchone()["n"]; c.close()
    return {"me":u,"roles":ROLES,"unread":n}

@app.route("/")
def home(): return redirect(url_for("dashboard") if me() else url_for("login"))

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE username=? AND password=? AND active=1",
                            (request.form.get("username","").strip(),request.form.get("password",""))).fetchone(); c.close()
        if u: session.clear(); session["user_id"]=u["id"]; return redirect(url_for("dashboard"))
        flash("بيانات الدخول غير صحيحة.")
    return render_template("login.html")

@app.post("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@req_login
def dashboard():
    u=me(); c=db()
    if u["role"]=="security": rows=c.execute("SELECT * FROM requests WHERE created_by=? ORDER BY id DESC",(u["id"],)).fetchall()
    elif u["role"]=="cctv": rows=c.execute("SELECT * FROM requests WHERE status IN ('New Request','Under CCTV Review','Review Completed') ORDER BY id DESC").fetchall()
    else: rows=c.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
    stats={s:c.execute("SELECT COUNT(*) n FROM requests WHERE status=?",(s,)).fetchone()["n"] for s in STATUSES}
    total=c.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"]
    c.close(); return render_template("dashboard.html",rows=rows,stats=stats,total=total)

@app.route("/requests/new",methods=["GET","POST"])
@req_login
@role("security","admin")
def new_request():
    if request.method=="POST":
        f=request.form
        if not f.get("requester_name","").strip() or not f.get("event_description","").strip() or not f.get("affiliation","").strip():
            flash("الاسم والصفة وبيان الحدث حقول مطلوبة."); return render_template("request_form.html",data=f)
        c=db(); t=now(); rn=next_no(c)
        cur=c.execute("""INSERT INTO requests
        (request_no,request_date,requester_name,affiliation,mobile,event_description,event_time,event_location,specifications,priority,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rn,f.get("request_date") or datetime.now().strftime("%Y-%m-%d"),f["requester_name"].strip(),
         f["affiliation"].strip(),f.get("mobile","").strip(),f["event_description"].strip(),
         f.get("event_time",""),f.get("event_location","").strip(),f.get("specifications","").strip(),
         f.get("priority","Normal"),"New Request",me()["id"],t,t))
        rid=cur.lastrowid
        c.execute("INSERT INTO history(request_id,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?)",(rid,"New Request",me()["id"],t,"تم إنشاء الطلب"))
        notify(c,["cctv","admin"],rid,"طلب فحص كاميرات جديد",f"تم إنشاء الطلب {rn} ويحتاج إلى المتابعة.")
        c.commit(); c.close(); flash(f"تم إنشاء {rn}."); return redirect(url_for("request_detail",rid=rid))
    return render_template("request_form.html",data={})

@app.route("/requests/<int:rid>")
@req_login
def request_detail(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    h=c.execute("SELECT h.*,u.username FROM history h JOIN users u ON u.id=h.changed_by WHERE h.request_id=? ORDER BY h.id",(rid,)).fetchall()
    c.close()
    if not r:return "Not found",404
    return render_template("request_detail.html",r=r,h=h)

@app.post("/requests/<int:rid>/start")
@req_login
@role("cctv")
def start(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="New Request": c.close(); flash("لا يمكن بدء هذه المراجعة."); return redirect(url_for("dashboard"))
    t=now(); c.execute("UPDATE requests SET cctv_by=?,review_start=?,updated_at=? WHERE id=?",(me()["id"],t,t,rid))
    set_status(c,rid,"Under CCTV Review","بدأ مراقب CCTV مراجعة الطلب.")
    notify(c,["security","admin"],rid,"بدأ فحص CCTV",f"الطلب {r['request_no']} أصبح قيد مراجعة الكاميرات.")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/complete")
@req_login
@role("cctv")
def complete(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="Under CCTV Review": c.close(); flash("الطلب ليس قيد المراجعة."); return redirect(url_for("dashboard"))
    f=request.form; attachment=""
    file=request.files.get("attachment")
    if file and file.filename:
        ext=file.filename.rsplit(".",1)[-1].lower()
        if ext not in ALLOWED: c.close(); flash("نوع المرفق غير مسموح."); return redirect(url_for("request_detail",rid=rid))
        attachment=f"{rid}_{secrets.token_hex(6)}_{secure_filename(file.filename)}"; file.save(os.path.join(UPLOAD,attachment))
    t=now()
    c.execute("""UPDATE requests SET review_end=?,cctv_result=?,cameras_checked=?,footage_start=?,footage_end=?,cctv_notes=?,attachment=?,updated_at=? WHERE id=?""",
              (t,f.get("cctv_result",""),f.get("cameras_checked",""),f.get("footage_start",""),f.get("footage_end",""),f.get("cctv_notes",""),attachment,t,rid))
    set_status(c,rid,"Review Completed","تم إنهاء فحص الكاميرات وتسجيل النتيجة.")
    notify(c,["security","admin"],rid,"اكتمل فحص CCTV",f"تم تسجيل نتيجة فحص {r['request_no']}.")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/close")
@req_login
@role("admin")
def close(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="Review Completed": c.close(); flash("لا يمكن الإغلاق قبل اكتمال فحص CCTV."); return redirect(url_for("request_detail",rid=rid))
    t=now(); c.execute("UPDATE requests SET recipient_signature=?,recipient_time=?,closed_by=?,updated_at=? WHERE id=?",
                       (request.form.get("recipient_signature",""),t,me()["id"],t,rid))
    set_status(c,rid,"Closed","تم إغلاق الطلب بواسطة Administration.")
    notify(c,["security","cctv"],rid,"تم إغلاق الطلب",f"الطلب {r['request_no']} تم إغلاقه.")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/reject")
@req_login
@role("admin")
def reject(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if r and r["status"] not in ("Closed","Rejected"):
        set_status(c,rid,"Rejected",request.form.get("note","سبب الرفض غير محدد"))
        notify(c,["security","cctv"],rid,"تم رفض الطلب",f"الطلب {r['request_no']} تم رفضه.")
        c.commit()
    c.close(); return redirect(url_for("request_detail",rid=rid))

@app.route("/notifications")
@req_login
def notifications():
    c=db(); rows=c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(me()["id"],)).fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(me()["id"],)); c.commit(); c.close()
    return render_template("notifications.html",rows=rows)

@app.route("/reports")
@req_login
@role("admin")
def reports():
    c=db()
    by_status=c.execute("SELECT status,COUNT(*) count FROM requests GROUP BY status").fetchall()
    by_aff=c.execute("SELECT affiliation,COUNT(*) count FROM requests GROUP BY affiliation ORDER BY count DESC").fetchall()
    by_loc=c.execute("SELECT COALESCE(NULLIF(event_location,''),'غير محدد') location,COUNT(*) count FROM requests GROUP BY event_location ORDER BY count DESC LIMIT 10").fetchall()
    by_priority=c.execute("SELECT priority,COUNT(*) count FROM requests GROUP BY priority").fetchall()
    c.close(); return render_template("reports.html",by_status=by_status,by_aff=by_aff,by_loc=by_loc,by_priority=by_priority)

@app.route("/users")
@req_login
@role("admin")
def users():
    c=db(); rows=c.execute("SELECT * FROM users ORDER BY id").fetchall(); c.close(); return render_template("users.html",rows=rows)

@app.post("/users/new")
@req_login
@role("admin")
def users_new():
    f=request.form
    try:
        c=db(); c.execute("INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)",(f["username"].strip(),f["password"],f["role"],now())); c.commit(); c.close(); flash("تم إنشاء المستخدم.")
    except sqlite3.IntegrityError: flash("اسم المستخدم موجود بالفعل.")
    return redirect(url_for("users"))

@app.get("/export")
@req_login
@role("admin")
def export_csv():
    import csv, io
    c=db(); rows=c.execute("SELECT request_no,request_date,requester_name,affiliation,mobile,event_description,event_time,event_location,priority,status,cctv_result,cameras_checked,review_start,review_end,created_at,updated_at FROM requests ORDER BY id DESC").fetchall(); c.close()
    out=io.StringIO(); w=csv.writer(out); w.writerow(rows[0].keys() if rows else ["request_no"]); w.writerows([list(r) for r in rows])
    from flask import Response
    return Response("\ufeff"+out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=marassi_cctv_requests.csv"})

@app.route("/print/<int:rid>")
@req_login
def print_request(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone(); c.close()
    if not r:return "Not found",404
    return render_template("print_request.html",r=r)

@app.route("/static/uploads/<path:name>")
def uploads(name): return send_from_directory(UPLOAD,name)

@app.get("/health")
def health():
    return {"status":"ok","app":"Marassi CCTV Inspection"}

init_db()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
