# Marassi CCTV Inspection
MVP Web App / PWA for 3 parties:
- Security Supervisor
- CCTV Monitor
- Administration

No Unit Number field. The requester is identified by name + affiliation:
مالك / مستأجر / صيف / زائر / شركة / أخرى

Workflow:
New Request -> Under CCTV Review -> Review Completed -> Closed
or Rejected.

Features:
- Role-based dashboards
- Automatic request number CCTV-YYYY-000001
- Notifications
- CCTV review result
- Camera list
- Search period
- Screenshot/PDF attachment
- Audit trail
- Administration reports
- CSV export
- Print / Save as PDF
- PWA manifest/service worker

Demo accounts:
security / security123
cctv / cctv123
admin / admin123

Run:
pip install -r requirements.txt
python app.py

For production: replace demo passwords, use password hashing, CSRF, HTTPS, stronger upload validation, database backups and proper secret management.
