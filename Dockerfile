FROM python:3.11-slim

WORKDIR /app
COPY server.py mcp_pipe.py requirements.txt ./

# system deps (optional but useful for SSL/requests)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# ENV you’ll set in Railway’s Variables UI:
# MCP_ENDPOINT   = wss://api.xiaozhi.me/mcp/?token=...
# N8N_BASE_URL   = https://n8n-808-xxxx.vm.elestio.app
# N8N_WEBHOOK_PATH = /webhook/xiaozhi

CMD ["python", "mcp_pipe.py", "server.py"]
