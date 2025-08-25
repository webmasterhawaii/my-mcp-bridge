from mcp.server.fastmcp import FastMCP
import logging, os, requests, json

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
mcp = FastMCP("n8n-forwarder")

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(keywords: str, method: str = "POST") -> dict:
    """
    ALWAYS use this tool to forward the user's message to my n8n workflow.
    Put the full user utterance into 'keywords'.
    The tool sends BOTH:
      • query string: ?q=<keywords>
      • JSON body: {keywords, message, text: <keywords>}
    Env required:
      N8N_BASE_URL (e.g. https://n8n-xxx.elestio.app   ; no trailing slash)
      N8N_WEBHOOK_PATH (e.g. /webhook/xiaozhi          ; leading slash)
    """
    base = os.environ.get("N8N_BASE_URL")
    path = os.environ.get("N8N_WEBHOOK_PATH")
    if not base or not path:
        return {
            "ok": False,
            "error": "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH",
            "base": base,
            "path": path
        }

    # guarantee non-empty string
    kw = (keywords or "").strip() or "(empty)"
    url = f"{base}{path}"
    params = {"q": kw}
    body = {"keywords": kw, "message": kw, "text": kw}
    method = (method or "POST").upper()

    # 🔊 log exactly what we'll send (shows in Railway logs)
    print(f"[n8n_query] URL: {url}", flush=True)
    print(f"[n8n_query] PARAMS: {json.dumps(params, ensure_ascii=False)}", flush=True)
    print(f"[n8n_query] BODY: {json.dumps(body, ensure_ascii=False)}", flush=True)

    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=15, headers={"User-Agent":"mcp-n8n/1.0"})
        else:
            r = requests.post(url, params=params, json=body, timeout=15, headers={"User-Agent":"mcp-n8n/1.0"})
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "error": f"Request failed: {e}",
            "url": url,
            "sent": {"params": params, "body": body}
        }

    try:
        data = r.json()
    except Exception:
        data = r.text

    return {
        "ok": r.ok,
        "status": r.status_code,
        "url": r.url,
        "echo": {"query_q": kw, "body_keywords": kw},
        "response": data
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
