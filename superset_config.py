import os
SECRET_KEY = os.environ.get('SUPERSET_SECRET_KEY') or 'dev-secret-key-please-change-in-production'
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
