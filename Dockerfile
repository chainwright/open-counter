FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY opencounter ./opencounter
COPY web ./web
COPY demo ./demo
ENV OPENCOUNTER_DATA=/tmp/opencounter
EXPOSE 8000
CMD ["sh", "-c", "uvicorn opencounter.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
