// custom-mcp-config.js — SAFE MINIMAL
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // Guardrails
    process.on("uncaughtException", e => console.error("[MCP] uncaughtException", e));
    process.on("unhandledRejection", e => console.error("[MCP] unhandledRejection", e));

    async function doFetch(url, opts = {}) {
      const method = opts.method || "GET";
      const headers = { ...(opts.headers || {}) };
      const res = await fetch(url, { method, headers });
      const text = await res.text().catch(() => "");
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // --- Simple echo tool (sanity check) ---
    const EchoSchema = z.object({ text: z.string().optional() });
    server.tool(
      "echo_text",
      "Echo a short string (connectivity test).",
      EchoSchema,
      async ({ text }) => ({ content: [{ type: "text", text: text || "pong" }] })
    );

    // --- n8n via QUERY (?query=...) — SUPER ROBUST, NO enum/default ---
    const N8nSchema = z.object({
      message: z.string().optional(),
      text: z.string().optional(),
      query: z.string().optional(),
      method: z.string().optional() // "GET" or "POST" (we'll default to GET in code)
    });

    server.tool(
      "n8n_webhook_call",
      "Forward the user's utterance to n8n via GET ?query=...",
      N8nSchema,
      async (args, context) => {
        try {
          const base = process.env.N8N_BASE_URL;
          const path = process.env.N8N_WEBHOOK_PATH;
          if (!base || !path) {
            return { content: [{ type: "text", text: "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH env vars." }] };
          }

          const url = new URL(path, base);

          // Pick a non-empty user string from args → context → fallback
          const vals = [];
          if (args && typeof args === "object") {
            for (const k of ["message", "text", "query"]) {
              if (typeof args[k] === "string" && args[k].trim()) vals.push(args[k].trim());
            }
            // last resort: first non-empty string value in args
            if (!vals.length) {
              for (const v of Object.values(args)) {
                if (typeof v === "string" && v.trim()) { vals.push(v.trim()); break; }
              }
            }
          }
          if (context && context.lastUserMessage && String(context.lastUserMessage).trim()) {
            vals.push(String(context.lastUserMessage).trim());
          }
          const userText = vals[0] || "(empty)";

          url.searchParams.set("query", userText);

          console.log("[MCP] n8n_webhook_call RAW args:", safeJson(args));
          console.log("[MCP] n8n_webhook_call derived userText:", userText);
          console.log("[MCP] n8n_webhook_call final URL:", url.toString());

          const res = await doFetch(url.toString(), { method: (args && args.method) || "GET" });

          return {
            content: [
              { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
              { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
            ]
          };
        } catch (e) {
          console.error("[MCP] n8n_webhook_call error:", e);
          return { content: [{ type: "text", text: `n8n_webhook_call failed: ${String(e && e.message || e)}` }] };
        }
      }
    );

    function safeJson(x) { try { return JSON.stringify(x); } catch { return "[unserializable]"; } }

    console.log("[MCP] registering tools: echo_text, n8n_webhook_call");
  }
};
