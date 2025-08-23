# mcp_pipe.py
import asyncio, os, sys, json, logging, websockets, subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s - MCP_PIPE - %(levelname)s - %(message)s")
log = logging.getLogger("MCP_PIPE")

MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT")
if not MCP_ENDPOINT:
    print("Set MCP_ENDPOINT first", file=sys.stderr)
    sys.exit(1)

async def main(script_path: str):
    log.info("Connecting to WebSocket server...")
    async with websockets.connect(MCP_ENDPOINT) as ws:
        log.info("Connected. Starting %s", script_path)
        proc = subprocess.Popen([sys.executable, script_path],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        async def ws_to_proc():
            while True:
                msg = await ws.recv()
                proc.stdin.write(msg + "\n")
                proc.stdin.flush()
        async def proc_to_ws():
            while True:
                line = await asyncio.to_thread(proc.stdout.readline)
                if not line: break
                await ws.send(line.rstrip("\n"))
        await asyncio.gather(ws_to_proc(), proc_to_ws())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mcp_pipe.py server.py", file=sys.stderr); sys.exit(1)
    asyncio.run(main(sys.argv[1]))
