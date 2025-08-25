from mcp.server.fastmcp import FastMCP
import logging, os, requests, json, threading, uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
mcp = FastMCP("n8n-forwarder")

def _post_to_n8n(url: str, params: dict, body: dict):
    """Background worker: fire the webhook and log the result. Non-blocking for Xiaozhi."""
    try:
        # You can raise/adjust timeout if your workflow is slow; this does NOT affect Xiaozhi now.
        r = requests.post(url, params=params, json=body, timeout=30, headers={"User-Agent": "mcp-n8n/1.0"})
        try:
            data = r.json()
        except Exception:
            data = r.text
        print(f"[n8n_async] HTTP {r.status_code} ok={r.ok} url={r.url}", flush=True)
        # Keep logs short:
        preview = (json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data))[:600]
        print(f"[n8n_async] response_preview={preview}", flush=True)
    except Exception as e:
        print(f"[n8n_async] ERROR posting to n8n: {e}", flush=True)

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(keywords: str, correlation_id: str = "") -> dict:
    """
    Fire-and-forget forward of the user's request to n8n, then return instantly.

    Sends BOTH:
      • query string: ?q=<keywords>&cid=<correlation_id>
      • JSON body:   { keywords, message, text, correlationId }

    Env required:
      N8N_BASE_URL   e.g. https://n8n-xxx.elestio.app   (no trailing slash)
      N8N_WEBHOOK_PATH e.g. /webhook/xiaozhi            (leading slash)
    """
    base = os.environ.get("N8N_BASE_URL")
    path = os.environ.get("N8N_WEBHOOK_PATH")
    if not base or not path:
        return {
            "ok": False,
            "result": "n8n is not configured (missing N8N_BASE_URL or N8N_WEBHOOK_PATH).",
        }

    kw = (keywords or "").strip() or "(empty)"
    cid = correlation_id.strip() or str(uuid.uuid4())
    url = f"{base}{path}"
    params = {"q": kw, "cid": cid}
    body = {"keywords": kw, "message": kw, "text": kw, "correlationId": cid}

    # Log what we are sending (visible in Railway logs)
    print(f"[n8n_query] URL: {url}", flush=True)
    print(f"[n8n_query] PARAMS: {json.dumps(params, ensure_ascii=False)}", flush=True)
    print(f"[n8n_query] BODY: {json.dumps(body, ensure_ascii=False)}", flush=True)

    # Spawn background thread so we return immediately to Xiaozhi
    t = threading.Thread(target=_post_to_n8n, args=(url, params, body), daemon=True)
    t.start()

    # Return a tiny payload so Xiaozhi speaks it and doesn't time out
    return {
        "ok": True,
        "status": "accepted",
        "correlationId": cid,
        # 👇 short string; Xiaozhi will speak this
        "result": f"Got it. Working on “{kw}”. (id: {cid[:8]})"
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
