FROM python:3.13-slim

WORKDIR /app

# LightGBM needs the OpenMP runtime; tzdata lets TZ set the local time
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 tzdata && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Not root. The app writes to data/ (uploads, merged sales history) and app/ml/artifacts/ (a retrained model).
RUN useradd --create-home --uid 1000 app && chown -R app:app /app/data /app/app/ml/artifacts
USER app

# In a container the tables come from the migrations, as they would in real use, not from create_all.
# Times are stored and shown in local time, and the dispatch wave cut-offs are local times too, so the container
# must not run on UTC: TZ is the warehouses' time zone.
ENV AUTO_CREATE_TABLES=false \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata

EXPOSE 8000

# Start-up loads the model and builds the first plan, which takes a while on a cold start.
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
