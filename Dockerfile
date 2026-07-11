FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 18900
CMD ["python", "main.py"]
