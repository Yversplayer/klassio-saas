release: python backend/tools/release.py
web: gunicorn --chdir backend --workers ${WEB_CONCURRENCY:-2} --threads 4 --worker-class gthread --timeout 60 --graceful-timeout 30 --error-logfile - --access-logfile - --access-logformat "%(h)s %(t)s \"%(m)s %(U)s\" %(s)s %(b)s %(D)sµs" --bind 0.0.0.0:$PORT app:app
