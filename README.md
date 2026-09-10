# Marassi CCTV Inspection v6

نظام Web App / PWA لإدارة طلبات فحص كاميرات المراقبة بين Security وCCTV وAdministration.

## Workflow
Security creates request → CCTV starts review → CCTV completes result → Administration approves/closes OR requests recheck.

## Roles
- Security Supervisor: إنشاء ومتابعة طلباته.
- CCTV Monitor: استلام الطلبات، بدء الفحص، تسجيل النتيجة، الكاميرات والفترة الزمنية والملاحظات والمرفقات.
- Administration: متابعة كل الطلبات، Feedback، Close/Recheck، التقارير، المستخدمين، CSV وDatabase Backup.

## v6 improvements
- Dashboard احترافي مع KPIs وأولوية وحالات وفلاتر وبحث وLatest Activity.
- صلاحيات وصول على مستوى الطلبات.
- CSRF protection لكل عمليات POST.
- Password hashing للمستخدمين الجدد، مع ترقية كلمات المرور القديمة تلقائياً عند تسجيل الدخول.
- إدارة المستخدمين: إنشاء، تفعيل/تعطيل، وتحديث كلمة المرور.
- Multiple images + attachment.
- حماية الوصول إلى المرفقات للمستخدمين المسجلين والمصرح لهم.
- حد أقصى لحجم الرفع 10MB.
- Analytics: status / affiliation / priority / monthly trend / locations.
- CSV export وDatabase backup من Administration.
- PWA + Print / Save as PDF.

## Demo accounts
- security / security123
- cctv / cctv123
- admin / admin123

## Run
```bash
pip install -r requirements.txt
python app.py
```

## Production checklist
استخدم SECRET_KEY ثابت وسري، HTTPS، قاعدة بيانات خارجية أو backup policy، rate limiting، reverse proxy، والتحقق من نوع الملف بالمحتوى وليس الامتداد فقط. غيّر حسابات الـDemo قبل التشغيل الفعلي.


### v7 deployment fix
- Dashboard redesigned while preserving existing route/variable names.
- Flask now uses explicit absolute `templates` and `static` folders to avoid `TemplateNotFound` caused by deployment working-directory differences.
- Procfile uses `gunicorn wsgi:application`.

### v7 bug fixes / additions
- PWA manifest had an empty `icons` array (no installable app icon) — added real 192px/512px icons plus a favicon and apple-touch-icon, all wired into `layout.html`, `login.html`, and cached by the service worker.
- "Low" priority was defined on the backend (`PRIORITIES`) but missing from the New Request form's dropdown — added.
- The printed request (`/print/<id>`) was missing "رقم الوحدة" and "تبعية الموظف / الشركة", which are shown on the request detail page — added for consistency.
- The dashboard status badge had no color rule for "New Request" (only Closed/Rejected/Under Review/Review Completed had one) — added.
- Reported app version was inconsistent ("6.0" on `/health`, "v6" in the sidebar) while the README already documented a v7 change — unified to v7 everywhere.
- Removed a stale compiled `__pycache__` file that had been left inside the shipped project folder.
