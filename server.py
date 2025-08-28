# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, threading, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-async-poller")

mcp = FastMCP("n8n-async-poller")

# In-memory job store:
# JOBS[cid] = {
#   status: "pending" | "done" | "error",
#   started: float,
#   updated: float,
#   last_spoken: float,
#   message: str,        # final message (when done/error) or unused
#   delivered: bool,     # True once we've spoken the final result
# }
JOBS = {}

# ---------- helpers ----------

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
            (isinstance(data.get("text"), str) and data["text"])
            or (isinstance(data.get("summary"), str) and data["summary"])
            or (isinstance(data.get("summary"), dict)
                and isinstance(data["summary"].get("output"), str)
                and data["summary"]["output"])
            or (isinstance(data.get("data"), dict)
                and isinstance(data["data"].get("output"), str)
                and data["data"]["output"])
            or str(data)
        )
    return str(data)

def _truncate(txt: str, n=900):
    txt = (txt or "").strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"

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
        speakable = _truncate(_extract_speakable(resp)) or "Done."
        status = "done" if resp.ok else "error"
        msg = speakable if resp.ok else f"Request failed ({resp.status_code})."
    except requests.Timeout:
        status, msg = "error", "Request timed out upstream."
    except Exception as e:
        status, msg = "error", f"Request error: {e}"

    job = JOBS.get(cid)
    if job:
        job["status"] = status
        job["message"] = msg
        job["updated"] = time.time()

# ---------- tools ----------

@mcp.tool()
def start_n8n_job(keywords: str, method: str = "POST") -> dict:
    """
    Start an asynchronous n8n job. Returns a correlation ID immediately.
    The assistant should poll with poll_n8n_job every ~2–3s to keep the session alive.
    """
    cid = str(uuid.uuid4())
    now = time.time()
    JOBS[cid] = {
        "status": "pending",
        "started": now,
        "updated": now,
        "last_spoken": 0.0,
        "message": "",
        "delivered": False,
    }
    method = (method or "POST").upper()

    t = threading.Thread(target=_run_n8n_job, args=(cid, keywords, method), daemon=True)
    t.start()

    return {
        "cid": cid,
        "status": "pending",
        "message": "Got it — I’m on it. I’ll keep you posted.",
        "next_poll_after_ms": 2000  # first follow-up poll suggestion
    }

@mcp.tool()
def poll_n8n_job(
    cid: str,
    speak_progress_every_secs: int = 6,
    max_wait_secs: int = 0
) -> dict:
    """
    Polls status:
      - Always returns fast to avoid timeouts.
      - While pending: only include a progress *message* every `speak_progress_every_secs`.
        (Silent polls keep the session alive but won't make the agent speak.)
      - When done/error: return the final message *once* and mark it delivered.
        Subsequent polls will return an empty message so the agent stops repeating.
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID.", "next_poll_after_ms": 2000}

    # Optional local wait (disabled by default)
    if max_wait_secs and job["status"] == "pending":
        deadline = time.time() + max_wait_secs
        while time.time() < deadline and job["status"] == "pending":
            time.sleep(0.25)

    # Finished path
    if job["status"] in ("done", "error"):
        if not job.get("delivered"):
            job["delivered"] = True
            # speak once, then go silent on subsequent polls
            return {
                "cid": cid,
                "status": job["status"],
                "message": job["message"] or "Done.",
                "done": True,
                "next_poll_after_ms": 0
            }
        else:
            # Already delivered final result → say nothing further
            return {
                "cid": cid,
                "status": job["status"],
                "message": "",
                "done": True,
                "next_poll_after_ms": 0
            }

    # Pending path
    now = time.time()
    elapsed = int(now - job["started"])
    since_spoken = now - (job.get("last_spoken") or 0.0)

    if since_spoken >= speak_progress_every_secs:
        job["last_spoken"] = now
        return {
            "cid": cid,
            "status": "pending",
            "message": f"Still working… ({elapsed}s elapsed)",
            "done": False,
            "next_poll_after_ms": 2000
        }
    else:
        # Silent poll – keeps Xiaozhi alive, no spoken output
        return {
            "cid": cid,
            "status": "pending",
            "message": "",
            "done": False,
            "next_poll_after_ms": 2000
        }

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

# ---------- run ----------
if __name__ == "__main__":
    mcp.run(transport="stdio")
