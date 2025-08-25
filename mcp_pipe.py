import asyncio, os, sys, logging, subprocess, signal
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - MCP_PIPE - %(levelname)s - %(message)s")
log = logging.getLogger("MCP_PIPE")

MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT")
if not MCP_ENDPOINT:
    print("Set MCP_ENDPOINT env var", file=sys.stderr)
    sys.exit(1)

STOP = asyncio.Event()

def _terminate(proc: subprocess.Popen):
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

def _handle_exit(sig, frame):
    log.info("Received signal %s, shutting down…", sig)
    STOP.set()
signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)

async def run_once(script_path: str):
    log.info("Connecting to WebSocket server…")
    async with websockets.connect(MCP_ENDPOINT) as ws:
        log.info("Connected. Starting %s", script_path)
        proc = subprocess.Popen(
            [sys.executable, script_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )

        async def ws_to_proc():
            try:
                while not STOP.is_set():
                    msg = await ws.recv()
                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", "ignore")
                    if not msg.endswith("\n"):
                        msg += "\n"
                    proc.stdin.write(msg)
                    proc.stdin.flush()
            except Exception as e:
                log.info("ws_to_proc ended: %s", e)

        async def proc_to_ws():
            try:
                while not STOP.is_set():
                    line = await asyncio.to_thread(proc.stdout.readline)
                    if not line:
                        break
                    await ws.send(line.rstrip("\n"))
            except Exception as e:
                log.info("proc_to_ws ended: %s", e)

        async def stderr_to_log():
            try:
                while not STOP.is_set():
                    line = await asyncio.to_thread(proc.stderr.readline)
                    if not line:
                        break
                    # log server stderr as INFO so it doesn't look like an error
                    log.info(line.rstrip("\n"))
            except Exception as e:
                log.info("stderr_to_log ended: %s", e)

        try:
            await asyncio.gather(ws_to_proc(), proc_to_ws(), stderr_to_log())
        finally:
            _terminate(proc)

async def main(script_path: str):
    backoff = 1
    while not STOP.is_set():
        try:
            await run_once(script_path)
            backoff = 1  # reset if we completed normally
        except Exception as e:
            log.info("Disconnected: %s", e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)  # simple backoff

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mcp_pipe.py server.py", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
