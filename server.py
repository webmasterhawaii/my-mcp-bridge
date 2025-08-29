# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-single-hit")

mcp = FastMCP("n8n-single-hit")

# ---- Config via ENV ----
MIN_POLL_INTERVAL_SECS = int(os.environ.get("MIN_POLL_INTERVAL_SECS", "6"))
MAX_POLLS = int(os.environ.get("MAX_POLLS", "20"))                     # ~2 min at 6s each
N8N_TIMEOUT_SECS = int(os.environ.get("N8N_TIMEOUT_SECS", "40"))       # one-shot HTTP timeout

# In-memory jobs:
# JOBS[cid] = {
#   "status": "pending|done|error",
#   "started": ts,
#   "updated": ts,
#   "message": str,
#   "poll_count": int,
#   "last_poll": ts or 0
# }
JOBS = {}

def _build_n8n_url() -> str:
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    path = os.environ.get("N8N_WEBHOOK_PATH", "")
    if not base or not path:
        raise RuntimeError("Missing N8N_BASE_URL or N8N_WEBHOOK_PATH")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"

def _extract_speakable(resp: requests.Response) -> str:
    """Return a short, speakable string from n8n HTTP response."""
    ctype = (resp.headers.get("content-type") or "").lower()
    if "text/" in ctype or "plain" in ctype:
        return (resp.text or "").strip() or "Done."
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip() or "Done."
    # Try common shapes
    if isinstance(data, dict):
        for path in [
            ("text",),
            ("summary",),
            ("summary", "output"),
            ("data", "output"),
        ]:
            cur = data
            ok = True
            for key in path:
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur.strip():
                return cur.strip()
        # fallback
        return str(data)
    return str(data)

# ------------- TOOLS -------------

@mcp.tool()
def start_n8n_job(keywords: str, method: str = "POST") -> dict:
    """
    Start a job with ONE request to n8n (no polling).
    - If n8n returns a final result synchronously, we store it and status=done.
    - Otherwise we leave status=pending and let the assistant poll locally.

    Returns: { cid, status, message, next_poll_after_ms }
    """
    cid = str(uuid.uuid4())
    JOBS[cid] = {
        "status": "pending",
        "started": time.time(),
        "updated": time.time(),
        "message": "Got it — I’m on it. I’ll keep you posted.",
        "poll_count": 0,
        "last_poll": 0.0,
    }

    try:
        url = _build_n8n_url()
    except Exception as e:
        JOBS[cid]["status"] = "error"
        JOBS[cid]["message"] = f"Config error: {e}"
        JOBS[cid]["updated"] = time.time()
        return {
            "cid": cid,
            "status": "error",
            "message": JOBS[cid]["message"],
            "next_poll_after_ms": MIN_POLL_INTERVAL_SECS * 1000,
        }

    params = {"q": keywords, "cid": cid}
    body = {"keywords": keywords, "message": keywords, "text": keywords, "correlationId": cid}
    method = (method or "POST").upper()

    # ---- ONE outbound request only ----
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=N8N_TIMEOUT_SECS)
        else:
            resp = requests.post(url, params=params, json=body, timeout=N8N_TIMEOUT_SECS)
        preview = _extract_speakable(resp)
        log.info("[n8n_job:single] cid=%s http=%s ok=%s preview=%s",
                 cid, resp.status_code, resp.ok, (preview[:120] if preview else ""))
        if resp.ok:
            # If your n8n flow responds synchronously with the final text, we’re done now.
            JOBS[cid]["status"] = "done"
            JOBS[cid]["message"] = preview or "Done."
            JOBS[cid]["updated"] = time.time()
        else:
            JOBS[cid]["status"] = "error"
            JOBS[cid]["message"] = f"Request failed ({resp.status_code})."
            JOBS[cid]["updated"] = time.time()
    except requests.Timeout:
        # If it times out, we stay pending so the model can keep user engaged.
        # (No retry here—avoids multiple hits/credit burn.)
        JOBS[cid]["status"] = "pending"
        JOBS[cid]["message"] = "Still working…"
        JOBS[cid]["updated"] = time.time()
        log.warning("[n8n_job:single] cid=%s timeout (no retry)", cid)
    except Exception as e:
        JOBS[cid]["status"] = "error"
        JOBS[cid]["message"] = f"Request error: {e}"
        JOBS[cid]["updated"] = time.time()
        log.error("[n8n_job:single] cid=%s error=%s", cid, e)

    return {
        "cid": cid,
        "status": JOBS[cid]["status"],
        "message": JOBS[cid]["message"],
        "next_poll_after_ms": MIN_POLL_INTERVAL_SECS * 1000,
    }

@mcp.tool()
def poll_n8n_job(cid: str) -> dict:
    """
    NEVER calls n8n. Just returns local job status with throttle and limits.
    - Enforces a minimum poll interval (default 6s).
    - Caps total polls (default 20).
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID.", "done": True, "next_poll_after_ms": 0}

    now = time.time()
    # Throttle: if called too soon, return a blank progress (no new speak)
    if job["status"] == "pending":
        since_last = now - job["last_poll"]
        if job["last_poll"] and since_last < MIN_POLL_INTERVAL_SECS:
            return {
                "cid": cid,
                "status": "pending",
                "message": "",  # model should not speak if empty
                "done": False,
                "next_poll_after_ms": int((MIN_POLL_INTERVAL_SECS - since_last) * 1000),
            }

        # Within limits?
        if job["poll_count"] >= MAX_POLLS:
            job["status"] = "error"
            job["message"] = "Taking too long. Please try again later."
            job["updated"] = now

    # Update counters
    job["poll_count"] += 1
    job["last_poll"] = now

    # Compose response
    done = job["status"] in ("done", "error")
    next_ms = 0 if done else MIN_POLL_INTERVAL_SECS * 1000
    return {
        "cid": cid,
        "status": job["status"],
        "message": job["message"] if done else "Still working…",
        "done": done,
        "next_poll_after_ms": next_ms,
    }

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

if __name__ == "__main__":
    mcp.run(transport="stdio")
