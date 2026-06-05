FROM python:3.11-slim

# Dépendances système (PyMuPDF, drivers DB)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python en premier (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY . .

# Répertoire pour artefacts ML
RUN mkdir -p model_artifacts

# Utilisateur non-root
RUN useradd -m -u 1000 waterflow && chown -R waterflow /app
USER waterflow

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", \
     "main:app"]
