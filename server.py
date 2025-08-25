from mcp.server.fastmcp import FastMCP
import logging, os, requests, json, threading, uuid, time

# Logs go to stderr by default -> SAFE for MCP stdio
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("n8n-forwarder")

mcp = FastMCP("n8n-forwarder")

# ---------- helpers ----------

def _build_urls():
    base = os.environ.get("N8N_BASE_URL")
    path = os.environ.get("N8N_WEBHOOK_PATH")
    status_path = os.environ.get("N8N_STATUS_PATH")  # optional
    if not base or not path:
        raise RuntimeError("Missing N8N_BASE_URL or N8N_WEBHOOK_PATH")
    return f"{base}{path}", (f"{base}{status_path}" if status_path else None)

def _short(s: str, n: int = 600) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[:n] + "…")

def _as_text(data) -> str:
    try:
        return json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
    except Exception:
        return str(data)

def _post_async(url: str, params: dict, body: dict):
    """Background worker: post to n8n (logs only)."""
    try:
        r = requests.post(url, params=params, json=body, timeout=30, headers={"User-Agent": "mcp-n8n/1.0"})
        try:
            data = r.json()
        except Exception:
            data = r.text
        logger.info("[n8n_async] HTTP %s ok=%s url=%s", r.status_code, r.ok, r.url)
        logger.info("[n8n_async] response_preview=%s", _short(_as_text(data)))
    except Exception as e:
        logger.warning("[n8n_async] ERROR: %s", e)

def _call_sync(url: str, params: dict, body: dict, method: str, timeout: int):
    """Synchronous call to n8n; returns a SHORT string for Xiaozhi to speak."""
    method = (method or "POST").upper()
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "mcp-n8n/1.0"})
        else:
            r = requests.post(url, params=params, json=body, timeout=timeout, headers={"User-Agent": "mcp-n8n/1.0"})
    except Exception as e:
        return f"Request to n8n failed: {e}"

    # Parse, then extract a tiny human sentence
    try:
        data = r.json()
    except Exception:
        data = r.text

    # Prefer a concise summary from n8n
    summary = None
    if isinstance(data, dict):
        if isinstance(data.get("summary"), str) and data["summary"].strip():
            summary = data["summary"].strip()
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str):
            summary = _short(data["data"]["output"])
    if not summary:
        summary = f"Done. (HTTP {r.status_code})" if r.ok else f"n8n returned HTTP {r.status_code}."

    return _short(summary, 800)  # keep well under ~1KB

# ---------- tools ----------

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(
    keywords: str,
    mode: str = "auto",          # "auto" | "sync" | "async"
    waitSeconds: int = 7,        # used when mode in {"auto","sync"}
    method: str = "POST",
    correlation_id: str = "",
) -> str:
    """
    Dual-mode forward to n8n. Always returns a SHORT STRING for Xiaozhi to speak.

    Sends BOTH:
      • query: ?q=<keywords>&cid=<uuid>
      • body:  {keywords, message, text, correlationId}
    """
    try:
        url, _status_url = _build_urls()
    except RuntimeError as e:
        return str(e)

    kw = (keywords or "").strip() or "(empty)"
    cid = (correlation_id or "").strip() or str(uuid.uuid4())
    params = {"q": kw, "cid": cid}
    body = {"keywords": kw, "message": kw, "text": kw, "correlationId": cid}

    logger.info("[n8n_query] mode=%s wait=%ss URL=%s", mode, waitSeconds, url)
    logger.info("[n8n_query] PARAMS=%s", _as_text(params))
    logger.info("[n8n_query] BODY=%s", _as_text(body))

    mode = (mode or "auto").lower()
    wait = max(1, min(int(waitSeconds or 7), 12))  # under Xiaozhi’s timeout

    if mode == "async":
        threading.Thread(target=_post_async, args=(url, params, body), daemon=True).start()
        return f"Got it. Working on “{kw}”. (id: {cid[:8]})"

    if mode == "sync":
        summary = _call_sync(url, params, body, method, timeout=wait)
        return summary

    # auto: try sync quickly, then async fallback
    summary = _call_sync(url, params, body, method, timeout=wait)
    if summary.startswith("Done.") or summary.startswith("n8n returned HTTP 2"):
        return summary
    # If it wasn’t a clear success, fall back to async fire-and-forget
    logger.info("[n8n_query:auto] fallback to async")
    threading.Thread(target=_post_async, args=(url, params, body), daemon=True).start()
    return f"Working on “{kw}”. I’ll keep going in the background. (id: {cid[:8]})"

@mcp.tool()
def n8n_get_status(correlation_id: str) -> str:
    """
    Optional status poller (needs N8N_STATUS_PATH). Returns a SHORT STRING.
    """
    base = os.environ.get("N8N_BASE_URL")
    status_path = os.environ.get("N8N_STATUS_PATH")
    if not base or not status_path:
        return "Status endpoint not configured (set N8N_STATUS_PATH)."

    url = f"{base}{status_path}"
    params = {"cid": correlation_id}
    try:
        r = requests.get(url, params=params, timeout=8, headers={"User-Agent": "mcp-n8n/1.0"})
        try:
            data = r.json()
        except Exception:
            data = r.text
    except Exception as e:
        return f"Status check failed: {e}"

    if isinstance(data, dict):
        if isinstance(data.get("summary"), str) and data["summary"].strip():
            return _short(data["summary"])
        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str):
            return _short(data["data"]["output"])
    return f"Status HTTP {getattr(r, 'status_code', '?')}."

if __name__ == "__main__":
    mcp.run(transport="stdio")
