FROM python:3.12-slim

# Pango + a Calibri-compatible font are needed for the PDF export (WeasyPrint)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-crosextra-carlito \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates templates
COPY static static

# HOME=/tmp because the container may run as an arbitrary UID (see docker-compose.yml)
ENV CFD_DB=/data/cfd.db \
    HOME=/tmp \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

# --preload so the database and secret key are initialised once, before workers fork
CMD ["gunicorn", "--preload", "-b", "0.0.0.0:8000", "-w", "2", "--access-logfile", "-", "app:app"]
