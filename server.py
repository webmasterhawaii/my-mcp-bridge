# server.py
from mcp.server.fastmcp import FastMCP
import logging, os, requests, uuid, time, threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("n8n-forwarder")

mcp = FastMCP("n8n-forwarder")

# -----------------------------
# helpers
# -----------------------------
def _build_n8n_target():
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    path = os.environ.get("N8N_WEBHOOK_PATH", "")
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    if not base or not path:
        raise RuntimeError("Missing N8N_BASE_URL or N8N_WEBHOOK_PATH")
    return url

def _truncate(txt: str, max_len: int = 900) -> str:
    txt = (txt or "").strip()
    if len(txt) > max_len:
        return txt[: max_len - 1] + "…"
    return txt

def _fire_and_forget(method: str, url: str, params: dict, json_body: dict):
    """Background delivery for auto/async mode; does NOT return anything to the model."""
    def _run():
        try:
            if method == "GET":
                requests.get(url, params=params, timeout=20)
            else:
                requests.post(url, params=params, json=json_body, timeout=20)
        except Exception as e:
            log.warning("[n8n_async_bg] delivery failed: %s", e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# -----------------------------
# tools
# -----------------------------
@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"

@mcp.tool()
def n8n_query(
    keywords: str,
    method: str = "POST",
    mode: str = "sync",           # "sync" | "auto" | "async"
    waitSeconds: int = 22,        # only used for sync/auto
) -> str:
    """
    Send the user's request to n8n and (in sync/auto modes) return the webhook's response
    as a PLAIN STRING so the assistant can speak it.

    ENV required:
      N8N_BASE_URL     e.g. https://n8n-xxxx.elestio.app
      N8N_WEBHOOK_PATH e.g. /webhook/xiaozhi

    Args:
      keywords: the user command / query text
      method:   "POST" (default) or "GET"
      mode:     "sync" (default), "auto" (try sync then fallback to async on timeout), or "async"
      waitSeconds: max seconds we wait for the synchronous HTTP to finish (cap ~25)
    """
    # ---------------- inputs / target
    url = _build_n8n_target()
    cid = str(uuid.uuid4())
    method = (method or "POST").upper()
    mode = (mode or "sync").lower()

    params = {"q": keywords, "cid": cid}
    body = {
        "keywords": keywords,
        "message": keywords,
        "text": keywords,
        "correlationId": cid,
    }

    # ---------------- async-only path
    if mode == "async":
        _fire_and_forget(method, url, params, body)
        return "Got it — I’m working on that now."

    # ---------------- sync / auto path
    # Enforce a safe wait ceiling; Xiaozhi typically can’t wait much > ~25s
    wait = max(5, min(int(waitSeconds or 22), 25))

    log.info("[n8n_query] mode=%s wait=%ss URL=%s", mode, wait, url)
    log.info("[n8n_query] PARAMS=%s", params)
    log.info("[n8n_query] BODY=%s", body)

    start = time.time()
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=wait)
        else:
            resp = requests.post(url, params=params, json=body, timeout=wait)
    except requests.Timeout:
        # only fall back to async if explicitly in auto
        if mode == "auto":
            log.info("[n8n_query:auto] sync timed out; falling back to async fire-and-forget")
            _fire_and_forget(method, url, params, body)
            return "Working on it — I’ll update you shortly."
        # sync mode: no fallback, return a helpful message
        return "Still working on that; please try again in a moment."
    except Exception as e:
        log.warning("[n8n_query] request failed: %s", e)
        return "I couldn’t reach the workflow service."

    # ---------------- normalize response to plain text
    # We prefer text; if JSON, reduce it to a short string if possible.
    text = None
    ctype = resp.headers.get("content-type", "")
    if "text/" in ctype or "plain" in ctype:
        text = resp.text
    else:
        # attempt JSON decode; flatten common shapes
        try:
            data = resp.json()
        except Exception:
            data = resp.text

        if isinstance(data, dict):
            # common shapes you used earlier:
            # - { text: "..." }
            # - { summary: "..." } or { summary: { output: "..." } }
            # - { data: { output: "..." } }
            text = (
                (isinstance(data.get("text"), str) and data.get("text"))
                or (isinstance(data.get("summary"), str) and data.get("summary"))
                or (isinstance(data.get("summary"), dict) and isinstance(data["summary"].get("output"), str) and data["summary"]["output"])
                or (isinstance(data.get("data"), dict) and isinstance(data["data"].get("output"), str) and data["data"]["output"])
                or str(data)
            )
        else:
            text = str(data)

    # Truncate to be safe for MCP/iot-like limits
    spoken = _truncate(text or "Done.")
    return spoken

# -----------------------------
# run
# -----------------------------
if __name__ == "__main__":
    # Use stdio transport; your mcp_pipe.py bridges this to Xiaozhi’s WSS
    mcp.run(transport="stdio")
