// custom-mcp-config.js — minimal + robust
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    process.on("uncaughtException", e => console.error("[MCP] uncaughtException", e));
    process.on("unhandledRejection", e => console.error("[MCP] unhandledRejection", e));

    async function doFetch(url, opts = {}) {
      const method = (opts.method || "GET").toUpperCase();
      const headers = { ...(opts.headers || {}) };
      const res = await fetch(url, { method, headers });
      const text = await res.text().catch(() => "");
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // ---- sanity tool
    const EchoSchema = z.object({ text: z.string().optional() });
    server.tool(
      "echo_text",
      "Echo a short string (connectivity test).",
      EchoSchema,
      async ({ text }) => ({ content: [{ type: "text", text: text || "pong" }] })
    );

    // ---- NEW: n8n_query (strongly-typed, required string)
    // Per Xiaozhi guidance, make the name & param crystal clear.
    const N8nQuerySchema = z.object({
      keywords: z.string().min(1).describe("The user's full request or command text.")
    });

    server.tool(
      "n8n_query",
      "Send the user's request to n8n via GET query (?q=...). Always put the full request in 'keywords'. Requires env N8N_BASE_URL and N8N_WEBHOOK_PATH.",
      N8nQuerySchema,
      async ({ keywords }) => {
        const base = process.env.N8N_BASE_URL;
        const path = process.env.N8N_WEBHOOK_PATH;
        if (!base || !path) {
          return { content: [{ type: "text", text: "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH env vars." }] };
        }
        const u = new URL(path, base);
        u.searchParams.set("q", keywords); // <-- use ?q= for clarity

        console.log("[MCP] n8n_query →", u.toString());
        const res = await doFetch(u.toString(), { method: "GET" });

        return {
          content: [
            { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
            { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
          ]
        };
      }
    );

    // ---- legacy flexible tool (kept, but models sometimes omit args)
    const N8nSchema = z.object({
      message: z.string().optional(),
      text: z.string().optional(),
      query: z.string().optional(),
      method: z.string().optional()
    });
    server.tool(
      "n8n_webhook_call",
      "Forward the user's utterance to n8n via GET ?query=... (use 'n8n_query' instead for reliability).",
      N8nSchema,
      async (args, context) => {
        try {
          const base = process.env.N8N_BASE_URL;
          const path = process.env.N8N_WEBHOOK_PATH;
          if (!base || !path) {
            return { content: [{ type: "text", text: "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH env vars." }] };
          }
          const url = new URL(path, base);

          // pick first non-empty string
          const vals = [];
          for (const k of ["message", "text", "query"]) {
            if (args && typeof args[k] === "string" && args[k].trim()) vals.push(args[k].trim());
          }
          if (!vals.length && context && context.lastUserMessage && String(context.lastUserMessage).trim()) {
            vals.push(String(context.lastUserMessage).trim());
          }
          const userText = vals[0] || "(empty)";

          url.searchParams.set("query", userText);

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

    console.log("[MCP] registering tools: echo_text, n8n_query, n8n_webhook_call");
  }
};
