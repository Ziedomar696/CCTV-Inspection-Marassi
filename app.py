import os, sqlite3, secrets, io, csv, shutil
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,"marassi_cctv.db")
UPLOAD=os.path.join(BASE,"static","uploads")
os.makedirs(UPLOAD,exist_ok=True)

app=Flask(__name__, static_folder="static")
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"]=10*1024*1024
ALLOWED={"png","jpg","jpeg","webp","pdf"}
IMAGE_ALLOWED={"png","jpg","jpeg","webp"}
ROLES={"security":"مشرف الأمن","cctv":"مراقب الكاميرات CCTV","admin":"Administration - الإدارة"}
STATUSES=["New Request","Under CCTV Review","Review Completed","Closed","Rejected"]
PRIORITIES=["Low","Normal","High","Urgent"]


def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def now(): return datetime.now().isoformat(timespec="seconds")

def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(32)
    return session["csrf"]
app.jinja_env.globals["csrf_token"]=csrf_token

@app.before_request
def protect_posts():
    if request.method=="POST" and request.endpoint not in {"login"}:
        token=request.form.get("csrf_token","")
        if not token or not secrets.compare_digest(token,session.get("csrf", "")):
            return "Invalid CSRF token",400


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
      unit_no TEXT, employee_affiliation TEXT, affiliation TEXT NOT NULL, mobile TEXT, event_description TEXT NOT NULL,
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
    CREATE TABLE IF NOT EXISTS request_images(
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
      filename TEXT NOT NULL, original_name TEXT, uploaded_by INTEGER NOT NULL,
      uploaded_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS admin_feedback(
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
      feedback TEXT NOT NULL, decision TEXT, created_by INTEGER NOT NULL,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      request_id INTEGER, title TEXT NOT NULL, body TEXT NOT NULL,
      is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
    """)
    # Ensure the built-in demo accounts are always usable, including when an
    # older persistent SQLite database already contains these usernames.
    for u,pw,r in [("security","security123","security"),("cctv","cctv123","cctv"),("admin","admin123","admin")]:
        existing = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
        if existing:
            c.execute("UPDATE users SET password=?, role=?, active=1 WHERE username=?",
                      (generate_password_hash(pw), r, u))
        else:
            c.execute("INSERT INTO users(username,password,role,created_at,active) VALUES(?,?,?,?,1)",
                      (u,generate_password_hash(pw),r,now()))
    c.commit(); c.close()

def ensure_columns():
    c=db(); cols={r["name"] for r in c.execute("PRAGMA table_info(requests)").fetchall()}
    for name,typ in [("unit_no","TEXT"),("employee_affiliation","TEXT")]:
        if name not in cols: c.execute(f"ALTER TABLE requests ADD COLUMN {name} {typ}")
    c.commit(); c.close()

def me():
    if "user_id" not in session:return None
    c=db(); u=c.execute("SELECT * FROM users WHERE id=? AND active=1",(session["user_id"],)).fetchone(); c.close(); return u

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

def next_no(c):
    y=datetime.now().year
    r=c.execute("SELECT request_no FROM requests WHERE request_no LIKE ? ORDER BY id DESC LIMIT 1",(f"CCTV-{y}-%",)).fetchone()
    n=(int(r["request_no"].split("-")[-1])+1) if r else 1
    return f"CCTV-{y}-{n:06d}"

def notify(c, roles, request_id, title, body):
    if not roles:return
    ids=c.execute("SELECT id FROM users WHERE active=1 AND role IN (%s)" % ",".join("?"*len(roles)),roles).fetchall()
    for x in ids:c.execute("INSERT INTO notifications(user_id,request_id,title,body,created_at) VALUES(?,?,?,?,?)",(x["id"],request_id,title,body,now()))

def set_status(c,rid,new_status,note=""):
    old=c.execute("SELECT status FROM requests WHERE id=?",(rid,)).fetchone()["status"]
    uid=me()["id"]; t=now()
    c.execute("UPDATE requests SET status=?,updated_at=? WHERE id=?",(new_status,t,rid))
    c.execute("INSERT INTO history(request_id,old_status,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?,?)",(rid,old,new_status,uid,t,note))

def can_view(r):
    u=me()
    return bool(u and (u["role"] in ("admin","cctv") or r["created_by"]==u["id"]))

def valid_upload(file, image_only=False):
    if not file or not file.filename:return False
    ext=file.filename.rsplit(".",1)[-1].lower() if "." in file.filename else ""
    return ext in (IMAGE_ALLOWED if image_only else ALLOWED)

def save_upload(file,rid):
    name=secure_filename(file.filename)
    ext=name.rsplit(".",1)[-1].lower()
    fname=f"{rid}_{secrets.token_hex(8)}_{name}"
    file.save(os.path.join(UPLOAD,fname)); return fname,ext

@app.context_processor
def ctx():
    u=me()
    if not u:return {"me":None,"roles":ROLES,"unread":0}
    c=db(); n=c.execute("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",(u["id"],)).fetchone()["n"]; c.close()
    return {"me":u,"roles":ROLES,"unread":n,"priorities":PRIORITIES}

@app.route("/")
def home(): return redirect(url_for("dashboard") if me() else url_for("login"))

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip(); password=request.form.get("password","")
        c=db(); u=c.execute("SELECT * FROM users WHERE username=? AND active=1",(username,)).fetchone()
        ok=False
        if u:
            try: ok=check_password_hash(u["password"],password)
            except Exception: ok=secrets.compare_digest(u["password"],password)
            if ok and not u["password"].startswith(("scrypt:","pbkdf2:","argon2:")):
                c.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(password),u["id"])); c.commit()
        c.close()
        if ok:
            session.clear(); session["user_id"]=u["id"]; csrf_token(); return redirect(url_for("dashboard"))
        flash("بيانات الدخول غير صحيحة.")
    return render_template("login.html")

@app.post("/logout")
@req_login
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@req_login
def dashboard():
    u=me(); c=db(); params=[]
    if u["role"]=="security":
        where="WHERE r.created_by=?"; params=[u["id"]]
    elif u["role"]=="cctv": where="WHERE r.status IN ('New Request','Under CCTV Review','Review Completed')"
    else: where=""
    rows=c.execute(f"SELECT r.*,cu.username created_user,cu2.username cctv_user FROM requests r LEFT JOIN users cu ON cu.id=r.created_by LEFT JOIN users cu2 ON cu2.id=r.cctv_by {where} ORDER BY CASE r.priority WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 WHEN 'Normal' THEN 3 ELSE 4 END,r.id DESC",params).fetchall()
    stats={s:c.execute("SELECT COUNT(*) n FROM requests r "+("WHERE r.created_by=? AND " if u["role"]=="security" else "WHERE ")+"r.status=?",([u["id"],s] if u["role"]=="security" else [s])).fetchone()["n"] for s in STATUSES}
    total=sum(stats.values())
    overdue=c.execute("SELECT COUNT(*) n FROM requests r WHERE r.status IN ('New Request','Under CCTV Review') AND datetime(r.created_at) < datetime('now','-24 hours')" + (" AND r.created_by=?" if u["role"]=="security" else ""),([u["id"]] if u["role"]=="security" else [])).fetchone()["n"]
    recent=c.execute("SELECT h.*,r.request_no,u.username FROM history h JOIN requests r ON r.id=h.request_id JOIN users u ON u.id=h.changed_by ORDER BY h.id DESC LIMIT 8").fetchall()
    c.close(); return render_template("dashboard.html",rows=rows,stats=stats,total=total,overdue=overdue,recent=recent)

@app.route("/requests/new",methods=["GET","POST"])
@req_login
@role("security","admin")
def new_request():
    if request.method=="POST":
        f=request.form
        if not f.get("requester_name","").strip() or not f.get("event_description","").strip() or not f.get("affiliation","").strip():
            flash("الاسم والصفة وبيان الحدث حقول مطلوبة."); return render_template("request_form.html",data=f)
        priority=f.get("priority","Normal") if f.get("priority") in PRIORITIES else "Normal"
        c=db(); t=now(); rn=next_no(c)
        cur=c.execute("""INSERT INTO requests(request_no,request_date,requester_name,unit_no,employee_affiliation,affiliation,mobile,event_description,event_time,event_location,specifications,priority,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rn,f.get("request_date") or datetime.now().strftime("%Y-%m-%d"),f["requester_name"].strip(),f.get("unit_no","").strip(),f.get("employee_affiliation","").strip(),f["affiliation"].strip(),f.get("mobile","").strip(),f["event_description"].strip(),f.get("event_time",""),f.get("event_location","").strip(),f.get("specifications","").strip(),priority,"New Request",me()["id"],t,t))
        rid=cur.lastrowid
        c.execute("INSERT INTO history(request_id,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?)",(rid,"New Request",me()["id"],t,"تم إنشاء الطلب"))
        notify(c,["cctv","admin"],rid,"طلب فحص كاميرات جديد",f"تم إنشاء الطلب {rn} ويحتاج إلى المتابعة.")
        c.commit(); c.close(); flash(f"تم إنشاء {rn}."); return redirect(url_for("request_detail",rid=rid))
    return render_template("request_form.html",data={})

@app.route("/requests/<int:rid>")
@req_login
def request_detail(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r: c.close(); return "Not found",404
    if not can_view(r): c.close(); flash("لا يمكنك الوصول لهذا الطلب."); return redirect(url_for("dashboard"))
    h=c.execute("SELECT h.*,u.username FROM history h JOIN users u ON u.id=h.changed_by WHERE h.request_id=? ORDER BY h.id",(rid,)).fetchall()
    images=c.execute("SELECT * FROM request_images WHERE request_id=? ORDER BY id",(rid,)).fetchall()
    feedback=c.execute("SELECT af.*,u.username FROM admin_feedback af JOIN users u ON u.id=af.created_by WHERE af.request_id=? ORDER BY af.id DESC",(rid,)).fetchall()
    c.close(); return render_template("request_detail.html",r=r,h=h,images=images,feedback=feedback)

@app.post("/requests/<int:rid>/start")
@req_login
@role("cctv")
def start(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="New Request": c.close(); flash("لا يمكن بدء هذه المراجعة."); return redirect(url_for("dashboard"))
    t=now(); c.execute("UPDATE requests SET cctv_by=?,review_start=?,updated_at=? WHERE id=?",(me()["id"],t,t,rid)); set_status(c,rid,"Under CCTV Review","بدأ مراقب CCTV مراجعة الطلب.")
    notify(c,["security","admin"],rid,"بدأ فحص CCTV",f"الطلب {r['request_no']} أصبح قيد مراجعة الكاميرات.")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/complete")
@req_login
@role("cctv")
def complete(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="Under CCTV Review": c.close(); flash("الطلب ليس قيد المراجعة."); return redirect(url_for("dashboard"))
    f=request.form; result=f.get("cctv_result","").strip(); cameras=f.get("cameras_checked","").strip()
    if not result or not cameras: c.close(); flash("النتيجة والكاميرات التي تمت مراجعتها مطلوبة."); return redirect(url_for("request_detail",rid=rid))
    attachment=""; file=request.files.get("attachment")
    if file and file.filename:
        if not valid_upload(file): c.close(); flash("نوع المرفق غير مسموح."); return redirect(url_for("request_detail",rid=rid))
        attachment,_=save_upload(file,rid)
    t=now()
    for img in request.files.getlist("images"):
        if not img or not img.filename: continue
        if not valid_upload(img,True): c.close(); flash("كل الصور يجب أن تكون JPG أو PNG أو WEBP."); return redirect(url_for("request_detail",rid=rid))
        fname,_=save_upload(img,rid)
        c.execute("INSERT INTO request_images(request_id,filename,original_name,uploaded_by,uploaded_at) VALUES(?,?,?,?,?)",(rid,fname,img.filename,me()["id"],t))
    c.execute("UPDATE requests SET review_end=?,cctv_result=?,cameras_checked=?,footage_start=?,footage_end=?,cctv_notes=?,attachment=?,updated_at=? WHERE id=?",(t,result,cameras,f.get("footage_start",""),f.get("footage_end",""),f.get("cctv_notes","").strip(),attachment,t,rid))
    set_status(c,rid,"Review Completed","تم إنهاء فحص الكاميرات وتسجيل النتيجة."); notify(c,["security","admin"],rid,"اكتمل فحص CCTV",f"تم تسجيل نتيجة فحص {r['request_no']}.")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/admin-action")
@req_login
@role("admin")
def admin_action(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="Review Completed": c.close(); flash("لا توجد مراجعة CCTV مكتملة على هذا الطلب."); return redirect(url_for("request_detail",rid=rid))
    feedback=request.form.get("feedback","").strip(); decision=request.form.get("decision","Close")
    if not feedback: c.close(); flash("اكتب Feedback الإدارة قبل تنفيذ الإجراء."); return redirect(url_for("request_detail",rid=rid))
    if decision not in ("Close","Recheck"): decision="Close"
    t=now(); c.execute("INSERT INTO admin_feedback(request_id,feedback,decision,created_by,created_at) VALUES(?,?,?,?,?)",(rid,feedback,decision,me()["id"],t))
    if decision=="Close":
        c.execute("UPDATE requests SET recipient_signature=?,recipient_time=?,closed_by=?,updated_at=? WHERE id=?",(request.form.get("recipient_signature","").strip(),t,me()["id"],t,rid)); set_status(c,rid,"Closed","تمت مراجعة نتيجة CCTV وإضافة Feedback بواسطة Administration."); notify(c,["security","cctv"],rid,"إغلاق طلب CCTV",f"تم إغلاق الطلب {r['request_no']} بعد مراجعة الإدارة.")
    else:
        set_status(c,rid,"Under CCTV Review","طلبت الإدارة إعادة المراجعة بناءً على Feedback."); notify(c,["cctv","security"],rid,"إعادة مراجعة CCTV",f"الإدارة طلبت إعادة مراجعة {r['request_no']}: {feedback}")
    c.commit(); c.close(); return redirect(url_for("request_detail",rid=rid))

@app.post("/requests/<int:rid>/reject")
@req_login
@role("admin")
def reject(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if r and r["status"] not in ("Closed","Rejected"):
        set_status(c,rid,"Rejected",request.form.get("note","سبب الرفض غير محدد")); notify(c,["security","cctv"],rid,"تم رفض الطلب",f"الطلب {r['request_no']} تم رفضه."); c.commit()
    c.close(); return redirect(url_for("request_detail",rid=rid))

@app.route("/notifications")
@req_login
def notifications():
    c=db(); rows=c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(me()["id"],)).fetchall(); c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(me()["id"],)); c.commit(); c.close(); return render_template("notifications.html",rows=rows)

@app.route("/reports")
@req_login
@role("admin")
def reports():
    c=db(); by_status=c.execute("SELECT status,COUNT(*) count FROM requests GROUP BY status").fetchall(); by_aff=c.execute("SELECT affiliation,COUNT(*) count FROM requests GROUP BY affiliation ORDER BY count DESC").fetchall(); by_loc=c.execute("SELECT COALESCE(NULLIF(event_location,''),'غير محدد') location,COUNT(*) count FROM requests GROUP BY event_location ORDER BY count DESC LIMIT 10").fetchall(); by_priority=c.execute("SELECT priority,COUNT(*) count FROM requests GROUP BY priority").fetchall()
    daily=c.execute("SELECT substr(request_date,1,7) month,COUNT(*) count FROM requests GROUP BY month ORDER BY month DESC LIMIT 12").fetchall(); c.close(); return render_template("reports.html",by_status=by_status,by_aff=by_aff,by_loc=by_loc,by_priority=by_priority,daily=daily)

@app.route("/users")
@req_login
@role("admin")
def users():
    c=db(); rows=c.execute("SELECT * FROM users ORDER BY id").fetchall(); c.close(); return render_template("users.html",rows=rows)

@app.post("/users/new")
@req_login
@role("admin")
def users_new():
    f=request.form; username=f.get("username","").strip(); password=f.get("password",""); r=f.get("role","")
    if not username or len(password)<8 or r not in ROLES: flash("اسم المستخدم والدور صحيحان وكلمة المرور 8 أحرف على الأقل مطلوبة."); return redirect(url_for("users"))
    try:
        c=db(); c.execute("INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)",(username,generate_password_hash(password),r,now())); c.commit(); c.close(); flash("تم إنشاء المستخدم.")
    except sqlite3.IntegrityError: flash("اسم المستخدم موجود بالفعل.")
    return redirect(url_for("users"))

@app.post("/users/<int:uid>/toggle")
@req_login
@role("admin")
def user_toggle(uid):
    if uid==me()["id"]: flash("لا يمكنك تعطيل حسابك الحالي."); return redirect(url_for("users"))
    c=db(); c.execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(uid,)); c.commit(); c.close(); return redirect(url_for("users"))

@app.post("/users/<int:uid>/reset")
@req_login
@role("admin")
def user_reset(uid):
    p=request.form.get("password","")
    if len(p)<8: flash("كلمة المرور يجب أن تكون 8 أحرف على الأقل."); return redirect(url_for("users"))
    c=db(); c.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(p),uid)); c.commit(); c.close(); flash("تم تحديث كلمة المرور."); return redirect(url_for("users"))

@app.get("/export")
@req_login
@role("admin")
def export():
    c=db(); rows=c.execute("SELECT request_no,request_date,requester_name,unit_no,employee_affiliation,affiliation,mobile,event_description,event_time,event_location,priority,status,cctv_result,cameras_checked,review_start,review_end,created_at,updated_at FROM requests ORDER BY id DESC").fetchall(); c.close()
    out=io.StringIO(); w=csv.writer(out); w.writerow(rows[0].keys() if rows else ["request_no"]); w.writerows([list(r) for r in rows]); from flask import Response
    return Response("\ufeff"+out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=marassi_cctv_requests.csv"})

@app.get("/backup")
@req_login
@role("admin")
def backup():
    if not os.path.exists(DB): return "Database not found",404
    c=db(); c.execute("PRAGMA wal_checkpoint(FULL)"); c.close()
    return send_file(DB,as_attachment=True,download_name=f"marassi_cctv_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db",mimetype="application/octet-stream")

@app.route("/print/<int:rid>")
@req_login
def print_request(rid):
    c=db(); r=c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone(); c.close()
    if not r:return "Not found",404
    if not can_view(r): return "Forbidden",403
    return render_template("print_request.html",r=r)

@app.route("/static/uploads/<path:name>")
@req_login
def uploads(name):
    c=db(); r=c.execute("SELECT request_id FROM request_images WHERE filename=? UNION SELECT id FROM requests WHERE attachment=?",(name,name)).fetchone(); c.close()
    if not r: return "Not found",404
    c=db(); req=c.execute("SELECT * FROM requests WHERE id=?",(r["request_id"] if "request_id" in r.keys() else r["id"],)).fetchone(); c.close()
    if not req or not can_view(req): return "Forbidden",403
    return send_from_directory(UPLOAD,name)

@app.get("/health")
def health(): return {"status":"ok","app":"Marassi CCTV Inspection","version":"6.0"}

init_db(); ensure_columns()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
