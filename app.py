import os, sqlite3, secrets
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,'cctv_inspection.db')
app=Flask(__name__); app.secret_key=os.environ.get('SECRET_KEY',secrets.token_hex(32))
ROLES={'security':'مشرف الأمن','cctv':'مراقب الكاميرات CCTV','admin':'Administration - الإدارة'}
STATUSES=['New Request','Under CCTV Review','Review Completed','Closed','Rejected']
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init_db():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER DEFAULT 1,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,request_no TEXT UNIQUE,request_date TEXT NOT NULL,requester_name TEXT NOT NULL,unit_no TEXT,affiliation TEXT,mobile TEXT,event_description TEXT NOT NULL,event_time TEXT,event_location TEXT,specifications TEXT,cctv_result TEXT,cameras_checked TEXT,review_start TEXT,review_end TEXT,cctv_notes TEXT,recipient_signature TEXT,recipient_time TEXT,status TEXT NOT NULL,created_by INTEGER NOT NULL,cctv_by INTEGER,closed_by INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS request_history(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER,old_status TEXT,new_status TEXT,changed_by INTEGER,changed_at TEXT,note TEXT);''')
 for u,p,r in [('security','security123','security'),('cctv','cctv123','cctv'),('admin','admin123','admin')]: c.execute('INSERT OR IGNORE INTO users(username,password,role,created_at) VALUES(?,?,?,?)',(u,p,r,datetime.now().isoformat(timespec='seconds')))
 c.commit(); c.close()
def me():
 if 'user_id' not in session:return None
 c=db(); x=c.execute('SELECT * FROM users WHERE id=? AND active=1',(session['user_id'],)).fetchone(); c.close(); return x
def reqlogin(f):
 @wraps(f)
 def w(*a,**k): return f(*a,**k) if me() else redirect(url_for('login'))
 return w
def role(*roles):
 def d(f):
  @wraps(f)
  def w(*a,**k):
   u=me()
   if not u:return redirect(url_for('login'))
   if u['role'] not in roles: flash('ليس لديك صلاحية للوصول إلى هذه الصفحة.'); return redirect(url_for('dashboard'))
   return f(*a,**k)
  return w
 return d
def next_no(c):
 y=datetime.now().year; x=c.execute('SELECT request_no FROM requests WHERE request_no LIKE ? ORDER BY id DESC LIMIT 1',(f'CCTV-{y}-%',)).fetchone(); n=1
 if x:
  try:n=int(x['request_no'].split('-')[-1])+1
  except:pass
 return f'CCTV-{y}-{n:06d}'
def status(c,rid,new,uid,note=''):
 x=c.execute('SELECT status FROM requests WHERE id=?',(rid,)).fetchone(); old=x['status'] if x else None; now=datetime.now().isoformat(timespec='seconds'); c.execute('UPDATE requests SET status=?,updated_at=? WHERE id=?',(new,now,rid)); c.execute('INSERT INTO request_history(request_id,old_status,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?,?)',(rid,old,new,uid,now,note))
@app.context_processor
def ctx():return {'me':me(),'roles':ROLES}
@app.route('/')
def home():return redirect(url_for('dashboard')) if me() else redirect(url_for('login'))
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db(); u=c.execute('SELECT * FROM users WHERE username=? AND password=? AND active=1',(request.form.get('username','').strip(),request.form.get('password',''))).fetchone(); c.close()
  if u:session.clear();session['user_id']=u['id'];return redirect(url_for('dashboard'))
  flash('اسم المستخدم أو كلمة المرور غير صحيحة.')
 return render_template('login.html')
@app.post('/logout')
def logout():session.clear();return redirect(url_for('login'))
@app.route('/dashboard')
@reqlogin
def dashboard():
 u=me();c=db(); rows=c.execute('SELECT * FROM requests '+('WHERE created_by=? ' if u['role']=='security' else '')+'ORDER BY id DESC',((u['id'],) if u['role']=='security' else ())).fetchall(); stats={s:c.execute('SELECT COUNT(*) n FROM requests WHERE status=?',(s,)).fetchone()['n'] for s in STATUSES}; total=c.execute('SELECT COUNT(*) n FROM requests').fetchone()['n'];c.close();return render_template('dashboard.html',rows=rows,stats=stats,total=total)
@app.route('/requests/new',methods=['GET','POST'])
@reqlogin
@role('security','admin')
def new_request():
 if request.method=='POST':
  f=request.form
  if not f.get('requester_name','').strip() or not f.get('event_description','').strip():flash('الاسم وبيان الحدث مطلوبان.');return render_template('request_form.html',data=f)
  c=db();now=datetime.now().isoformat(timespec='seconds');no=next_no(c);cur=c.execute('''INSERT INTO requests(request_no,request_date,requester_name,unit_no,affiliation,mobile,event_description,event_time,event_location,specifications,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(no,f.get('request_date') or datetime.now().strftime('%Y-%m-%d'),f.get('requester_name','').strip(),f.get('unit_no','').strip(),f.get('affiliation','').strip(),f.get('mobile','').strip(),f.get('event_description','').strip(),f.get('event_time','').strip(),f.get('event_location','').strip(),f.get('specifications','').strip(),'New Request',me()['id'],now,now));rid=cur.lastrowid;c.execute('INSERT INTO request_history(request_id,new_status,changed_by,changed_at,note) VALUES(?,?,?,?,?)',(rid,'New Request',me()['id'],now,'تم إنشاء الطلب'));c.commit();c.close();flash(f'تم إنشاء الطلب {no}.');return redirect(url_for('view_request',request_id=rid))
 return render_template('request_form.html',data={})
@app.route('/requests/<int:request_id>')
@reqlogin
def view_request(request_id):
 c=db();r=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone();h=c.execute('SELECT h.*,u.username FROM request_history h JOIN users u ON u.id=h.changed_by WHERE h.request_id=? ORDER BY h.id',(request_id,)).fetchall();c.close();return (render_template('request_detail.html',row=r,history=h) if r else ('Not found',404))
@app.post('/requests/<int:request_id>/start-review')
@reqlogin
@role('cctv')
def start_review(request_id):
 c=db();r=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
 if not r or r['status']!='New Request':c.close();flash('لا يمكن بدء المراجعة على هذا الطلب.');return redirect(url_for('dashboard'))
 now=datetime.now().isoformat(timespec='seconds');c.execute('UPDATE requests SET cctv_by=?,review_start=?,updated_at=? WHERE id=?',(me()['id'],now,now,request_id));status(c,request_id,'Under CCTV Review',me()['id'],'بدأ مراقب الكاميرات المراجعة');c.commit();c.close();return redirect(url_for('view_request',request_id=request_id))
@app.post('/requests/<int:request_id>/complete-review')
@reqlogin
@role('cctv')
def complete_review(request_id):
 c=db();r=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
 if not r or r['status']!='Under CCTV Review':c.close();flash('الطلب ليس في حالة مراجعة.');return redirect(url_for('dashboard'))
 f=request.form;now=datetime.now().isoformat(timespec='seconds');c.execute('UPDATE requests SET cctv_result=?,cameras_checked=?,review_end=?,cctv_notes=?,updated_at=? WHERE id=?',(f.get('cctv_result',''),f.get('cameras_checked',''),now,f.get('cctv_notes',''),now,request_id));status(c,request_id,'Review Completed',me()['id'],'تم إنهاء مراجعة الكاميرات');c.commit();c.close();return redirect(url_for('view_request',request_id=request_id))
@app.post('/requests/<int:request_id>/close')
@reqlogin
@role('admin')
def close_request(request_id):
 c=db();r=c.execute('SELECT status FROM requests WHERE id=?',(request_id,)).fetchone()
 if r and r['status']=='Review Completed':now=datetime.now().isoformat(timespec='seconds');c.execute('UPDATE requests SET recipient_signature=?,recipient_time=?,closed_by=?,updated_at=? WHERE id=?',(request.form.get('recipient_signature',''),now,me()['id'],now,request_id));status(c,request_id,'Closed',me()['id'],'تم إغلاق الطلب بواسطة الإدارة');c.commit()
 c.close();return redirect(url_for('view_request',request_id=request_id))
@app.route('/users')
@reqlogin
@role('admin')
def users():
 c=db();r=c.execute('SELECT * FROM users ORDER BY id').fetchall();c.close();return render_template('users.html',rows=r)
@app.post('/users/new')
@reqlogin
@role('admin')
def new_user():
 f=request.form;c=db()
 try:c.execute('INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)',(f.get('username','').strip(),f.get('password',''),f.get('role','security'),datetime.now().isoformat(timespec='seconds')));c.commit();flash('تم إنشاء المستخدم.')
 except sqlite3.IntegrityError:flash('اسم المستخدم موجود بالفعل.')
 c.close();return redirect(url_for('users'))
@app.route('/reports')
@reqlogin
@role('admin')
def reports():
 c=db();a=c.execute('SELECT status,COUNT(*) count FROM requests GROUP BY status').fetchall();b=c.execute("SELECT COALESCE(NULLIF(event_location,''),'غير محدد') location,COUNT(*) count FROM requests GROUP BY event_location ORDER BY count DESC LIMIT 10").fetchall();c.close();return render_template('reports.html',by_status=a,by_location=b)
@app.get('/api/requests')
@reqlogin
def api_requests():
 q=request.args.get('q','').strip();c=db();sql='SELECT id,request_no,requester_name,unit_no,event_location,event_time,status FROM requests';args=()
 if q:sql+=' WHERE request_no LIKE ? OR requester_name LIKE ? OR unit_no LIKE ? OR event_location LIKE ?';args=tuple([f'%{q}%']*4)
 rows=c.execute(sql+' ORDER BY id DESC',args).fetchall();c.close();return jsonify([dict(x) for x in rows])
init_db()
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
