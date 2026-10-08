release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn core.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 120
