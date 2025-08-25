from mcp.server.fastmcp import FastMCP
import logging, os, requests, json, threading, uuid, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
    s = s or ""
    return s if len(s) <= n else (s[:n] + "…")

def _as_text(data) -> str:
    try:
        if isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False)
        return str(data)
    except Exception:
        return str(data)

def _post_async(url: str, params: dict, body: dict):
    """Background worker to post to n8n without blocking Xiaozhi."""
    try:
        r = requests.post(url, params=params, json=body, timeout=30, headers={"User-Agent": "mcp-n8n/1.0"})
        try:
            data = r.json()
        except Exception:
            data = r.text
        print(f"[n8n_async] HTTP {r.status_code} ok={r.ok} url={r.url}", flush=True)
        print(f"[n8n_async] response_preview={_short(_as_text(data))}", flush=True)
    except Exception as e:
        print(f"[n8n_async] ERROR: {e}", flush=True)

def _call_sync(url: str, params: dict, body: dict, method: str, timeout: int):
    """Synchronous call to n8n, returns (ok, status, summary)."""
    method = (method or "POST").upper()
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "mcp-n8n/1.0"})
        else:
            r = requests.post(url, params=params, json=body, timeout=timeout, headers={"User-Agent": "mcp-n8n/1.0"})
    except Exception as e:
        return False, 0, f"Request to n8n failed: {e}"

    # parse and produce a tiny summary
    try:
        data = r.json()
    except Exception:
        data = r.text

    summary = None
    if isinstance(data, dict):
        if isinstance(data.get("summary"), str) and data["summary"].strip():
            summary = data["summary"].strip()
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str):
            summary = _short(data["data"]["output"].strip())
    if not summary:
        summary = f"Done. (HTTP {r.status_code})" if r.ok else f"n8n returned HTTP {r.status_code}."

    return bool(r.ok), int(r.status_code), summary

# ---------- tools ----------

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(
    keywords: str,
    mode: str = "auto",          # "auto" | "sync" | "async"
    waitSeconds: int = 7,         # used when mode in {"auto","sync"}
    method: str = "POST",
    correlation_id: str = "",
) -> dict:
    """
    Forward user's request to n8n. Dual-mode:
      - auto: try sync for waitSeconds; if not done, fallback to async
      - sync: wait up to waitSeconds
      - async: fire-and-forget immediately

    Sends BOTH:
      • query: ?q=<keywords>&cid=<uuid>
      • body:  {keywords, message, text, correlationId}
    """
    try:
        url, _status_url = _build_urls()
    except RuntimeError as e:
        return {"ok": False, "result": str(e)}

    kw = (keywords or "").strip() or "(empty)"
    cid = (correlation_id or "").strip() or str(uuid.uuid4())
    params = {"q": kw, "cid": cid}
    body = {"keywords": kw, "message": kw, "text": kw, "correlationId": cid}

    print(f"[n8n_query] mode={mode} wait={waitSeconds}s URL={url}", flush=True)
    print(f"[n8n_query] PARAMS={json.dumps(params, ensure_ascii=False)}", flush=True)
    print(f"[n8n_query] BODY={json.dumps(body, ensure_ascii=False)}", flush=True)

    mode = (mode or "auto").lower()
    wait = max(1, min(int(waitSeconds or 7), 12))  # keep under Xiaozhi’s typical timeout

    if mode == "async":
        threading.Thread(target=_post_async, args=(url, params, body), daemon=True).start()
        return {"ok": True, "status": "accepted", "correlationId": cid, "result": f"Got it. Working on “{kw}”. (id: {cid[:8]})"}

    if mode == "sync":
        ok, status, summary = _call_sync(url, params, body, method, timeout=wait)
        return {"ok": ok, "status": status, "result": summary}

    # auto: try sync quickly, then fall back to async
    t0 = time.time()
    ok, status, summary = _call_sync(url, params, body, method, timeout=wait)
    elapsed = time.time() - t0
    if ok or status in (200, 201, 202, 204):
        return {"ok": ok, "status": status, "result": summary}
    else:
        # Fall back to async fire-and-forget and respond immediately
        print(f"[n8n_query:auto] sync path not ready (status={status}). Falling back to async.", flush=True)
        threading.Thread(target=_post_async, args=(url, params, body), daemon=True).start()
        return {"ok": True, "status": "accepted", "correlationId": cid, "result": f"Working on “{kw}”. I’ll keep going in the background. (id: {cid[:8]})"}

@mcp.tool()
def n8n_get_status(correlation_id: str) -> dict:
    """
    Optional status poller. Requires N8N_STATUS_PATH env, e.g. /webhook/status
    Your n8n flow should store results by correlationId and return a short summary.
    """
    base = os.environ.get("N8N_BASE_URL")
    status_path = os.environ.get("N8N_STATUS_PATH")
    if not base or not status_path:
        return {"ok": False, "result": "Status endpoint not configured (set N8N_STATUS_PATH)."}

    url = f"{base}{status_path}"
    params = {"cid": correlation_id}
    try:
        r = requests.get(url, params=params, timeout=8, headers={"User-Agent": "mcp-n8n/1.0"})
        try:
            data = r.json()
        except Exception:
            data = r.text
    except Exception as e:
        return {"ok": False, "result": f"Status check failed: {e}"}

    # Build a short result
    summary = None
    if isinstance(data, dict):
        if isinstance(data.get("summary"), str) and data["summary"].strip():
            summary = data["summary"].strip()
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str):
            summary = _short(data["data"]["output"].strip())
    if not summary:
        summary = f"Status HTTP {getattr(r, 'status_code', '?')}."

    return {"ok": True, "result": summary}

if __name__ == "__main__":
    mcp.run(transport="stdio")
