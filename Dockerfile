# 前端构建阶段：生成相互独立的用户端和管理端静态资源。
FROM node:22-alpine AS frontend-build

WORKDIR /app
COPY frontend-admin/package.json frontend-admin/package-lock.json ./frontend-admin/
RUN cd frontend-admin && npm ci
COPY frontend-admin/ ./frontend-admin/
RUN mkdir -p /app/backend && cd frontend-admin && npm run build

# 运行阶段：只保留 Python 服务与已构建的管理台文件。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /app/backend/static-admin ./static-admin
COPY --from=frontend-build /app/backend/static-user ./static-user

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 18900
CMD ["python", "main.py"]
