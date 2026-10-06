FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Every program file of DA Management (README.md lists them). tests/ and .env stay out (.dockerignore).
COPY *.py ./
EXPOSE 8080
CMD ["gunicorn","-b","0.0.0.0:8080","--workers","2","--threads","4","app:app"]
