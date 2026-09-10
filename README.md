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

### v7.2 fix - deployment was not shipping templates/static at all
The path-guessing fix in v7.1 wasn't enough: the same `TemplateNotFound: login.html`
error kept happening even after redeploying, which means the `templates/` and
`static/` folders genuinely never reached the running container - not just a
wrong-path issue. Since `app.py` is clearly the one file that *is* reliably
deployed (the traceback comes from inside it), the fix now embeds a full copy
of every template and static asset (CSS, service worker, manifest, icons)
directly inside a new `assets.py` file, loaded as Python data structures.

How it works:
- `app.py` always tries the real files under `templates/`/`static/` on disk
  first (so local editing still works normally).
- If a file isn't found on disk, it transparently falls back to the embedded
  copy in `assets.py` - so the app now works correctly even in an environment
  that only deploys the `.py` files.
- The database/uploads folder falls back to a temp directory if the app's own
  directory turns out to be read-only, so the app can still boot and serve
  requests (though on such a host, use a persistent volume for real data).
- A clear one-line note is printed to the logs when the fallback is in use, so
  it's obvious from the logs whether the real files were found or not.

**Deploy `assets.py` together with `app.py`** - it's not optional supporting
data, it's the fallback that keeps the site up when the folders don't arrive.

**How to confirm this version is actually the one running:** open `/health` on
your deployed URL. It must return `"version": "7.2"` and
`"has_embedded_assets": true`. If it shows an older version (or no
`has_embedded_assets` key at all), the platform is still serving a previous
build - trigger a fresh deploy/rebuild (clear any build cache if your host
offers that option) rather than assuming the new files were picked up
automatically.
- Production logs showed `jinja2.exceptions.TemplateNotFound: login.html` on every request, taking the whole site down (500 on `/login`). Root cause: `BASE` was derived from a single `os.path.abspath(__file__)` guess, which can resolve to the wrong directory on some hosts (different working directory at runtime, or a symlinked entrypoint) even though `templates/` and `static/` were deployed correctly. `app.py` now checks several real candidate directories and picks whichever one actually contains `templates/login.html`, and logs a clear diagnostic to stderr if none do, instead of failing silently on every request.
- `/favicon.ico` was 404ing (browsers request it automatically regardless of the `<link rel="icon">` tag) — added an explicit route serving the app icon.
- PWA manifest had an empty `icons` array (no installable app icon) — added real 192px/512px icons plus a favicon and apple-touch-icon, all wired into `layout.html`, `login.html`, and cached by the service worker.
- "Low" priority was defined on the backend (`PRIORITIES`) but missing from the New Request form's dropdown — added.
- The printed request (`/print/<id>`) was missing "رقم الوحدة" and "تبعية الموظف / الشركة", which are shown on the request detail page — added for consistency.
- The dashboard status badge had no color rule for "New Request" (only Closed/Rejected/Under Review/Review Completed had one) — added.
- Reported app version was inconsistent ("6.0" on `/health`, "v6" in the sidebar) while the README already documented a v7 change — unified to v7 everywhere.
- Removed a stale compiled `__pycache__` file that had been left inside the shipped project folder.
