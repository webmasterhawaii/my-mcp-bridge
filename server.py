# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, threading, time, re

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-async-poller")
mcp = FastMCP("n8n-async-poller")

JOBS = {}  # cid -> {"status": "pending|done|error", "started": ts, "updated": ts, "message": str}
RECENT_BY_KEY = {}
RECENT_WINDOW_SECS = 30

# ---------- helpers ----------
def _build_n8n_url():
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    path = os.environ.get("N8N_WEBHOOK_PATH", "")
    if not base or not path:
        raise RuntimeError("Missing N8N_BASE_URL or N8N_WEBHOOK_PATH")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"

def _normalize_keywords(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]+", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _extract_speakable(resp):
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

PLACEHOLDER_PAT = re.compile(r"^\s*(looking it up|processing|still working|fetching|checking|loading)\b", re.I)

def _is_placeholder(txt: str) -> bool:
    t = (txt or "").strip()
    if not t:
        return True
    if len(t) < 16:  # very short, likely not the final answer
        return True
    if PLACEHOLDER_PAT.match(t):
        return True
    return False

def _truncate(txt: str, n=900):
    txt = (txt or "").strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"

def _n8n_request(url: str, cid: str, keywords: str, method: str):
    params = {"q": keywords, "cid": cid}
    body = {"keywords": keywords, "message": keywords, "text": keywords, "correlationId": cid}
    if method == "GET":
        return requests.get(url, params=params, timeout=40)
    return requests.post(url, params=params, json=body, timeout=40)

def _run_n8n_job(cid: str, keywords: str, method: str):
    """
    Background worker:
    - Hit n8n every 2s until we get a non-placeholder response or we reach max_wait.
    - Update JOBS[cid] when final content (or error) arrives.
    """
    url = _build_n8n_url()
    max_wait = 60  # seconds
    interval = 2   # seconds
    deadline = time.time() + max_wait
    last_preview = ""

    while True:
        try:
            resp = _n8n_request(url, cid, keywords, method)
            speakable = _extract_speakable(resp)
            preview = _truncate(speakable, 200)
            log.info("[n8n_job] cid=%s http=%s ok=%s preview=%s",
                     cid, resp.status_code, resp.ok, preview)
            if resp.ok and not _is_placeholder(speakable):
                JOBS[cid]["status"] = "done"
                JOBS[cid]["message"] = _truncate(speakable)
                JOBS[cid]["updated"] = time.time()
                return
            else:
                # keep pending, store a gentle progress so the agent can speak occasionally
                last_preview = speakable
                JOBS[cid]["status"] = "pending"
                JOBS[cid]["message"] = ""  # keep poll-driven pacing
                JOBS[cid]["updated"] = time.time()
        except requests.Timeout:
            JOBS[cid]["status"] = "error"
            JOBS[cid]["message"] = "The upstream request timed out."
            JOBS[cid]["updated"] = time.time()
            return
        except Exception as e:
            # transient network error: keep pending unless we hit deadline
            last_preview = f"Network error: {e}"
            JOBS[cid]["status"] = "pending"
            JOBS[cid]["message"] = ""
            JOBS[cid]["updated"] = time.time()

        if time.time() >= deadline:
            JOBS[cid]["status"] = "error"
            JOBS[cid]["message"] = ("Sorry — the source is taking too long. "
                                    "Please try again or narrow the request.")
            JOBS[cid]["updated"] = time.time()
            return

        time.sleep(interval)

# ---------- tools ----------

@mcp.tool()
def start_n8n_job(keywords: str, method: str = "POST", force_new: bool = False) -> dict:
    """
    Start an asynchronous n8n job. Returns a correlation ID immediately.
    Deduplicates identical (normalized) keywords for 30s to avoid duplicate jobs.
    Set force_new=true to bypass dedup.
    """
    norm = _normalize_keywords(keywords)
    now = time.time()
    # purge old
    for k in list(RECENT_BY_KEY.keys()):
        if now - RECENT_BY_KEY[k]["ts"] > RECENT_WINDOW_SECS:
            del RECENT_BY_KEY[k]

    if not force_new and norm in RECENT_BY_KEY:
        cid = RECENT_BY_KEY[norm]["cid"]
        job = JOBS.get(cid)
        if job and job["status"] == "pending":
            return {
                "cid": cid,
                "status": "pending",
                "message": "Already working on that — I’ll keep you posted.",
                "next_poll_after_ms": 2000
            }

    cid = str(uuid.uuid4())
    JOBS[cid] = {"status": "pending", "started": now, "updated": now, "message": ""}
    RECENT_BY_KEY[norm] = {"cid": cid, "ts": now}
    method = (method or "POST").upper()

    threading.Thread(target=_run_n8n_job, args=(cid, keywords, method), daemon=True).start()

    return {
        "cid": cid,
        "status": "pending",
        "message": "Got it — I’m on it. I’ll keep you posted.",
        "next_poll_after_ms": 2000
    }

@mcp.tool()
def poll_n8n_job(cid: str) -> dict:
    """
    Poll job status:
      - pending → speak every ~6s ("Still working… (Xs)") and keep polling (next_poll_after_ms=2000)
      - done/error → return final message and stop (done=true)
    """
    job = JOBS.get(cid)
    if not job:
        return {"cid": cid, "status": "error", "message": "Unknown job ID.", "done": True, "next_poll_after_ms": 0}

    if job["status"] == "pending":
        elapsed = int(time.time() - job.get("started", time.time()))
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

if __name__ == "__main__":
    mcp.run(transport="stdio")
