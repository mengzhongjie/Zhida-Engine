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
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
# 香港/国内服务器访问 files.pythonhosted.org 偶发超时，默认使用稳定镜像；
# 可在构建时通过 --build-arg PIP_INDEX_URL=... 切换为企业内网或官方源。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
    --default-timeout=120 --retries=5 -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /app/backend/static-admin ./static-admin
COPY --from=frontend-build /app/backend/static-user ./static-user

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 18900
CMD ["python", "main.py"]
