# Lena's studio (AG Studio, React) is built first; the shop serves it at /studio.
FROM node:22-slim AS studio
WORKDIR /src/studio
COPY studio/package.json studio/package-lock.json ./
RUN npm ci
COPY studio/ ./
RUN npm run build   # vite outDir ../web/studio -> /src/web/studio

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY opencounter ./opencounter
COPY web ./web
COPY --from=studio /src/web/studio ./web/studio
COPY demo ./demo
ENV OPENCOUNTER_DATA=/tmp/opencounter
EXPOSE 8000
# behind Render's proxy: trust its X-Forwarded-Proto so redirects (e.g. /mcp → /mcp/) stay on https
CMD ["sh", "-c", "uvicorn opencounter.web:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
