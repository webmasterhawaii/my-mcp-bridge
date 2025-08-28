# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, threading, time, re

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-async-poller")

mcp = FastMCP("n8n-async-poller")

# In-memory job store: { cid: {"status": "pending|done|error", "started": ts, "updated": ts, "message": str} }
JOBS = {}

# Simple recent-dedupe window: for 30s, reuse the same cid for the same (normalized) keywords
RECENT_WINDOW_SECS = 30
RECENT_BY_KEY = {}  # norm_keywords -> {"cid": str, "ts": float}

# ---- helpers ----

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
        return (
            (isinstance(data.get("text"), str) and data["text"]) or
            (isinstance(data.get("summary"), str) and data["summary"]) or
            (isinstance(data.get("summary"), dict) and isinstance(data["summary"].get("output"), str) and data["summary"]["output"]) or
            (isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str) and data["data"]["output"]) or
            str(data)
        )
    return str(data)

def _truncate(txt: str, n=900):
    txt = (txt or "").strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"

def _normalize_keywords(s: str) -> str:
    """Lowercase, trim, collapse spaces; remove noisy punctuation. Used for dedup key."""
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]+", "", s)          # remove punctuation except hyphen/underscore
    s = re.sub(r"\s+", " ", s)               # collapse whitespace
    return s

def _run_n8n_job(cid: str, keywords: str, method: str):
    """Background worker that hits n8n and stores the result into JOBS[cid]."""
    url = _build_n8n_url()
    params = {"q": keywords, "cid": cid}
    body = {"keywords": keywords, "message": keywords, "text": keywords, "correlationId": cid}
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=40)
        else:
            resp = requests.post(url, params=params, json=body, timeout=40)
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

# ---- tools ----

@mcp.tool()
def start_n8n_job(keywords: str, method: str = "POST", force_new: bool = False) -> dict:
    """
    Start an asynchronous n8n job. Returns a correlation ID immediately.
    Deduplicates identical (normalized) keywords for 30s to avoid duplicate jobs.
    Set force_new=true to bypass dedup.
    """
    norm = _normalize_keywords(keywords)
    now = time.time()

    # purge old RECENT entries
    for k in list(RECENT_BY_KEY.keys()):
        if now - RECENT_BY_KEY[k]["ts"] > RECENT_WINDOW_SECS:
            del RECENT_BY_KEY[k]

    if not force_new and norm in RECENT_BY_KEY:
        existing = RECENT_BY_KEY[norm]
        cid = existing["cid"]
        job = JOBS.get(cid)
        if job and job["status"] == "pending":
            # reuse current job
            return {
                "cid": cid,
                "status": "pending",
                "message": "Already working on that — I’ll keep you posted.",
                "next_poll_after_ms": 2000
            }

    # start a new job
    cid = str(uuid.uuid4())
    JOBS[cid] = {"status": "pending", "started": now, "updated": now, "message": ""}
    RECENT_BY_KEY[norm] = {"cid": cid, "ts": now}
    method = (method or "POST").upper()

    t = threading.Thread(target=_run_n8n_job, args=(cid, keywords, method), daemon=True)
    t.start()

    return {
        "cid": cid,
        "status": "pending",
        "message": "Got it — I’m on it. I’ll keep you posted.",
        "next_poll_after_ms": 2000
    }

@mcp.tool()
def poll_n8n_job(cid: str) -> dict:
    """
    Check status of a previously started job.
    - If pending: returns {status:'pending', message:'Still working… (Xs)', next_poll_after_ms:2000}
    - If done:    returns {status:'done',    message:'<final text>', done:true, next_poll_after_ms:0}
    - If error:   returns {status:'error',   message:'<error text>', done:true, next_poll_after_ms:0}
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID.", "done": True, "next_poll_after_ms": 0}

    if job["status"] == "pending":
        elapsed = int(time.time() - job["started"])
        # Only suggest speaking every ~6s; otherwise keep it silent but continue polling.
        speak = (elapsed % 6 == 0)
        return {
            "cid": cid,
            "status": "pending",
            "message": f"Still working… ({elapsed}s)" if speak else "",
            "done": False,
            "next_poll_after_ms": 2000
        }

    # done or error
    return {
        "cid": cid,
        "status": job["status"],
        "message": job["message"] or "Done.",
        "done": True,
        "next_poll_after_ms": 0
    }

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

# ---- run ----
if __name__ == "__main__":
    mcp.run(transport="stdio")
