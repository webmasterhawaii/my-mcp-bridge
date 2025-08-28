# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, threading, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-async-poller")

mcp = FastMCP("n8n-async-poller")

# In-memory job store:
# JOBS[cid] = {
#   "status": "pending" | "done" | "error",
#   "started": float(ts),
#   "updated": float(ts),       # last time the worker updated status
#   "last_spoken": float(ts),   # last time we told the user progress
#   "message": str              # final or latest message
# }
JOBS = {}

# -------- helpers --------

def _build_n8n_url():
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    path = os.environ.get("N8N_WEBHOOK_PATH", "")
    if not base or not path:
        raise RuntimeError("Missing N8N_BASE_URL or N8N_WEBHOOK_PATH")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"

def _extract_speakable(resp):
    """Return a short, speakable string from n8n HTTP response."""
    ctype = resp.headers.get("content-type", "")
    if "text/" in ctype or "plain" in ctype:
        return resp.text.strip()
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip() or "Done."
    if isinstance(data, dict):
        # prefer fields that we often set in n8n
        return (
            (isinstance(data.get("text"), str) and data["text"]) or
            (isinstance(data.get("summary"), str) and data["summary"]) or
            (isinstance(data.get("summary"), dict)
                and isinstance(data["summary"].get("output"), str)
                and data["summary"]["output"]) or
            (isinstance(data.get("data"), dict)
                and isinstance(data["data"].get("output"), str)
                and data["data"]["output"]) or
            str(data)
        )
    return str(data)

def _truncate(txt: str, n=900):
    txt = (txt or "").strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"

def _run_n8n_job(cid: str, keywords: str, method: str):
    """Background worker that hits n8n and stores the result into JOBS[cid]."""
    url = _build_n8n_url()
    params = {"q": keywords, "cid": cid}
    body = {
        "keywords": keywords,
        "message": keywords,
        "text": keywords,
        "correlationId": cid
    }
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=40)
        else:
            resp = requests.post(url, params=params, json=body, timeout=40)

        speakable = _truncate(_extract_speakable(resp)) or "Done."
        status = "done" if resp.ok else "error"
        msg = speakable if resp.ok else f"Request failed ({resp.status_code})."

    except requests.Timeout:
        status, msg = "error", "Request timed out upstream."
    except Exception as e:
        status, msg = "error", f"Request error: {e}"

    # store result
    job = JOBS.get(cid)
    if job:
        job["status"] = status
        job["message"] = msg
        job["updated"] = time.time()

# -------- tools --------

@mcp.tool()
def start_n8n_job(keywords: str, method: str = "POST") -> dict:
    """
    Start an asynchronous n8n job. Returns a correlation ID immediately.
    The assistant should then poll with poll_n8n_job every ~6–7 seconds until done.
    """
    cid = str(uuid.uuid4())
    now = time.time()
    JOBS[cid] = {
        "status": "pending",
        "started": now,
        "updated": now,
        "last_spoken": 0.0,   # never spoken yet
        "message": ""
    }
    method = (method or "POST").upper()

    t = threading.Thread(target=_run_n8n_job, args=(cid, keywords, method), daemon=True)
    t.start()

    # Instant response so the assistant can speak right away
    return {
        "cid": cid,
        "status": "pending",
        "message": "Got it — I’m on it. I’ll keep you posted."
    }

@mcp.tool()
def poll_n8n_job(
    cid: str,
    speak_progress_every_secs: int = 6,
    max_wait_secs: int = 0
) -> dict:
    """
    Check status of a previously started job.
    - If pending: returns {status:'pending', message:'' or 'Still working… (Xs elapsed)'}
      *Only* includes the progress message if >= speak_progress_every_secs have passed
      since the last spoken progress, to avoid spammy TTS.
    - If done:    returns {status:'done',  message:'<final text>'}
    - If error:   returns {status:'error', message:'<error text>'}

    The assistant may call this on a timer (~6–7s). If the returned message is empty while
    status is 'pending', the assistant should *not* speak (silent poll).
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID."}

    # Optional short local wait loop (disabled by default)
    if max_wait_secs and job["status"] == "pending":
        deadline = time.time() + max_wait_secs
        while time.time() < deadline and job["status"] == "pending":
            time.sleep(0.25)

    # Finished
    if job["status"] in ("done", "error"):
        return {"cid": cid, "status": job["status"], "message": job["message"] or "Done."}

    # Still pending — throttle spoken progress
    now = time.time()
    elapsed = int(now - job["started"])
    since_spoken = now - (job.get("last_spoken") or 0.0)

    if since_spoken >= max(1, int(speak_progress_every_secs)):
        job["last_spoken"] = now
        return {
            "cid": cid,
            "status": "pending",
            "message": f"Still working… ({elapsed}s elapsed)"
        }
    else:
        # silent poll (no speech)
        return {
            "cid": cid,
            "status": "pending",
            "message": ""
        }

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

# -------- run --------
if __name__ == "__main__":
    mcp.run(transport="stdio")
