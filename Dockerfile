# Slim Python base with certs
FROM python:3.11-slim

# --- System prep ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    PIP_NO_CACHE_DIR=1

# Install certs & minimal deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependency caching: copy reqs first ---
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Now copy source (won’t invalidate pip layer unless files change)
COPY server.py mcp_pipe.py ./

# Environment (set these in Railway > Variables; shown here for documentation only)
# MCP_ENDPOINT       = wss://api.xiaozhi.me/mcp/?token=...
# N8N_BASE_URL       = https://n8n-808-xxxxx.vm.elestio.app
# N8N_WEBHOOK_PATH   = /webhook/xiaozhi

# Optional: add a simple healthcheck (portless process, so just a no-op ping of python)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "print('ok')" || exit 1

# Run the stdio <-> WSS bridge
CMD ["python", "mcp_pipe.py", "server.py"]
