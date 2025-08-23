from mcp.server.fastmcp import FastMCP
import logging, os, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
mcp = FastMCP("n8n-forwarder")

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(keywords: str, method: str = "POST") -> dict:
    """
    Forward the user's request to n8n using BOTH:
      - query string: ?q=...
      - JSON body: {keywords, message, text}
    Requires env:
      N8N_BASE_URL (e.g. https://n8n-xxx.elestio.app)
      N8N_WEBHOOK_PATH (e.g. /webhook/xiaozhi)
    """
    base = os.environ.get("N8N_BASE_URL")
    path = os.environ.get("N8N_WEBHOOK_PATH")
    if not base or not path:
        return {"ok": False, "error": "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH", "base": base, "path": path}

    url = f"{base}{path}"
    params = {"q": keywords}
    body = {"keywords": keywords, "message": keywords, "text": keywords}
    method = (method or "POST").upper()

    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=15)
        else:
            r = requests.post(url, params=params, json=body, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"Request failed: {e}", "url": url, "params": params, "body": body}

    try:
        data = r.json()
    except Exception:
        data = r.text

    return {
        "ok": r.ok,
        "status": r.status_code,
        "url": r.url,
        "echo": {"query_q": keywords, "body_keywords": keywords},
        "response": data,
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
