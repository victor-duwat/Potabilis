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

# Répertoires ML + données (le volume /data héritera de ce propriétaire)
# Le `sed` retire d'éventuels retours chariot Windows (CRLF) : sans cela, /bin/sh
# lit « set -e\r » et refuse de démarrer. Garantit un build correct même si le
# dépôt est cloné sous Windows (voir aussi .gitattributes).
RUN mkdir -p model_artifacts /data \
    && sed -i 's/\r$//' docker-entrypoint.sh \
    && chmod +x docker-entrypoint.sh

# Utilisateur non-root (propriétaire de /app ET de /data pour l'écriture SQLite/MLflow)
RUN useradd -m -u 1000 waterflow && chown -R waterflow /app /data
USER waterflow

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD curl -f http://localhost:8080/health || exit 1

# L'entrypoint enregistre le modèle (si besoin) puis lance Gunicorn
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
