FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
RUN mkdir -p /data/uploads
EXPOSE 8091
CMD ["gunicorn", "--bind", "0.0.0.0:8091", "--workers", "2", "--threads", "4", "--timeout", "40", "app:app"]
