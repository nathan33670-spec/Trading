FROM python:3.12-slim

WORKDIR /srv

# CLI Claude Code : permet d'utiliser Claude via l'abonnement Pro/Max
# (secret claude_code_oauth_token) au lieu de l'API payante.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Durcissement : le core tourne sans privilèges. /secrets appartient à app
# pour que le volume nommé en hérite à sa création.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /secrets && chown app:app /secrets /srv
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
