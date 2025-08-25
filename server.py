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
    Forward the user's message to n8n.
    Sends BOTH:
      • query: ?q=<keywords>
      • JSON body: {keywords, message, text}
    Returns a SHORT summary in 'result' so Xiaozhi speaks it.
    """
    base = os.environ.get("N8N_BASE_URL")
    path = os.environ.get("N8N_WEBHOOK_PATH")
    if not base or not path:
        return {
            "ok": False,
            "result": "n8n is not configured (missing N8N_BASE_URL or N8N_WEBHOOK_PATH).",
        }

    kw = (keywords or "").strip() or "(empty)"
    url = f"{base}{path}"
    params = {"q": kw}
    body = {"keywords": kw, "message": kw, "text": kw}

    # Log exactly what we send (Railway)
    print(f"[n8n_query] URL: {url}", flush=True)
    print(f"[n8n_query] PARAMS: {json.dumps(params, ensure_ascii=False)}", flush=True)
    print(f"[n8n_query] BODY: {json.dumps(body, ensure_ascii=False)}", flush=True)

    method = (method or "POST").upper()
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=8, headers={"User-Agent":"mcp-n8n/1.0"})
        else:
            r = requests.post(url, params=params, json=body, timeout=8, headers={"User-Agent":"mcp-n8n/1.0"})
    except Exception as e:
        return {
            "ok": False,
            "result": f"Request to n8n failed: {e}",
        }

    # Parse response lightly
    try:
        data = r.json()
        data_text = json.dumps(data, ensure_ascii=False)
    except Exception:
        data = r.text
        data_text = str(data)

    # Build a short, user-facing summary
    if isinstance(data, dict) and "summary" in data and isinstance(data["summary"], str) and data["summary"].strip():
        summary = data["summary"].strip()
    else:
        if r.ok:
            summary = f"Done (HTTP {r.status_code})."
        else:
            summary = f"n8n returned HTTP {r.status_code}."

    # Trim preview so total payload stays small (<~1KB)
    preview = data_text[:600]
    print(f"[n8n_query] response_len={len(data_text)}, preview_len={len(preview)}", flush=True)

    return {
        "ok": bool(r.ok),
        "status": int(r.status_code),
        # 👇 Xiaozhi will read/use this
        "result": summary,
        # Tiny preview only; remove if you want it even smaller
        "data_preview": preview
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
