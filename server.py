# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, threading, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-async-poller")

mcp = FastMCP("n8n-async-poller")

JOBS = {}  # { cid: {status, started, updated, message} }

def _resolve_webhook_url(workflow: str | None = None, path: str | None = None) -> str:
    """
    Pick the webhook URL:
      - if `path` is provided, use N8N_BASE_URL + path
      - elif `workflow` is provided, try env N8N_WEBHOOK_PATH_<WORKFLOW>
      - else use N8N_WEBHOOK_PATH
    """
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("Missing N8N_BASE_URL")

    if path:
        use_path = path if path.startswith("/") else f"/{path}"
        return f"{base}{use_path}"

    if workflow:
        key = f"N8N_WEBHOOK_PATH_{workflow.upper().replace('-','_')}"
        wf_path = os.environ.get(key)
        if wf_path:
            wf_path = wf_path if wf_path.startswith("/") else f"/{wf_path}"
            return f"{base}{wf_path}"

    default_path = os.environ.get("N8N_WEBHOOK_PATH", "")
    if not default_path:
        raise RuntimeError("Missing N8N_WEBHOOK_PATH")
    default_path = default_path if default_path.startswith("/") else f"/{default_path}"
    return f"{base}{default_path}"

def _extract_speakable(resp):
    ctype = resp.headers.get("content-type", "")
    if "text/" in ctype or "plain" in ctype:
        return resp.text.strip()
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip() or "Done."
    if isinstance(data, dict):
        # Prefer short speakable fields
        if isinstance(data.get("text"), str): return data["text"]
        if isinstance(data.get("summary"), str): return data["summary"]
        if isinstance(data.get("summary"), dict) and isinstance(data["summary"].get("output"), str):
            return data["summary"]["output"]
        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str):
            return data["data"]["output"]
        return str(data)
    return str(data)

def _truncate(txt: str, n=900):
    txt = (txt or "").strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"

def _run_n8n_job(cid: str, url: str, keywords: str, method: str, headers: dict | None):
    params = {"q": keywords, "cid": cid}
    body = {"keywords": keywords, "message": keywords, "text": keywords, "correlationId": cid}
    try:
        if method == "GET":
            resp = requests.get(url, params=params, headers=headers, timeout=40)
        else:
            resp = requests.post(url, params=params, json=body, headers=headers, timeout=40)
        text = _truncate(_extract_speakable(resp)) or "Done."
        status = "done" if resp.ok else "error"
        msg = text if resp.ok else f"Request failed ({resp.status_code})."
    except requests.Timeout:
        status = "error"
        msg = "Request timed out upstream."
    except Exception as e:
        status = "error"
        msg = f"Request error: {e}"

    JOBS[cid]["status"] = status
    JOBS[cid]["message"] = msg
    JOBS[cid]["updated"] = time.time()

@mcp.tool()
def start_n8n_job(
    keywords: str,
    workflow: str | None = None,
    path: str | None = None,
    method: str = "POST",
    authHeader: str | None = None
) -> dict:
    """
    Start an asynchronous n8n job and return a correlation ID immediately.
    Use `workflow` to route to another webhook via env N8N_WEBHOOK_PATH_<WORKFLOW>.
    Or pass an explicit `path` like '/webhook/search'.
    Optional: authHeader='Bearer xxx' if your webhook is protected.
    """
    try:
        url = _resolve_webhook_url(workflow=workflow, path=path)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    cid = str(uuid.uuid4())
    JOBS[cid] = {"status": "pending", "started": time.time(), "updated": time.time(), "message": ""}
    method = (method or "POST").upper()
    headers = {"Authorization": authHeader} if authHeader else None

    t = threading.Thread(target=_run_n8n_job, args=(cid, url, keywords, method, headers), daemon=True)
    t.start()

    return {
        "cid": cid,
        "status": "pending",
        "message": "Got it — I’m on it. I’ll keep you posted."
    }

@mcp.tool()
def poll_n8n_job(cid: str) -> dict:
    """
    Poll the status of a previously started job.
    Returns:
      {cid, status: 'pending'|'done'|'error', message: 'speakable text'}
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID."}
    if job["status"] == "pending":
        elapsed = int(time.time() - job["started"])
        return {"cid": cid, "status": "pending", "message": f"Still working… ({elapsed}s)"}  # speakable
    return {"cid": cid, "status": job["status"], "message": job["message"] or "Done."}

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

if __name__ == "__main__":
    mcp.run(transport="stdio")
