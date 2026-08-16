# syntax=docker/dockerfile:1
# BookScope 一键容器：先构建前端 dist，再装后端，同源托管。
FROM node:22-alpine AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY bookscope ./bookscope
RUN pip install --no-cache-dir .
COPY --from=web /app/web/dist ./web/dist
ENV BOOKSCOPE_STATIC_DIR=/app/web/dist
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "bookscope.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
