FROM python:3.12-slim
WORKDIR /app
# pg_dump and pg_restore for the backup that Delete retired makes first (backups.py). The client must be at least as new as the
# database server (Debian 12 ships 15, like the Supabase image).
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && apt-get clean
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Every program file of DA Management (README.md lists them). tests/ and .env stay out (.dockerignore).
COPY *.py ./
EXPOSE 8080
# --timeout 300: a large Historical CSV or roster Apply can take longer than gunicorn's default 30 s, which killed the
# worker in the middle of it (the waiting upload stays; the Apply is rolled back).
CMD ["gunicorn","-b","0.0.0.0:8080","--workers","2","--threads","4","--timeout","300","app:app"]
