// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // Safety logs
    process.on("uncaughtException", e => console.error("[MCP] uncaughtException", e));
    process.on("unhandledRejection", e => console.error("[MCP] unhandledRejection", e));

    // Tiny fetcher
    async function doFetch(url, { method = "GET", headers = {} }) {
      const res = await fetch(url, { method, headers: { ...headers } });
      const text = await res.text().catch(() => "");
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // --- Echo (sanity tool) ---
    const EchoSchema = z.object({ text: z.string().default("ping") });
    server.tool(
      "echo_text",
      "Echo back text for connectivity tests.",
      EchoSchema,
      async ({ text }) => ({ content: [{ type: "text", text }] })
    );

    // --- n8n via QUERY (?query=...) ---
    // ZERO fancy validation so it never blocks the tool from registering.
    const N8nSchema = z.object({
      message: z.string().optional(), // we’ll accept anything
      method: z.enum(["GET","POST"]).default("GET")
    });
    server.tool(
      "n8n_webhook_call",
      "Send the user's utterance to n8n via GET query (?query=...). Requires env N8N_BASE_URL and N8N_WEBHOOK_PATH.",
      N8nSchema,
      async (args, context) => {
        // Build from env only (simplest & robust)
        const base = process.env.N8N_BASE_URL;
        const path = process.env.N8N_WEBHOOK_PATH;
        if (!base || !path) {
          return { content: [{ type: "text", text: "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH." }] };
        }
        const u = new URL(path, base);
        const userText =
          (args.message && args.message.trim()) ||
          (context?.lastUserMessage && String(context.lastUserMessage).trim()) ||
          "(empty)";
        u.searchParams.set("query", userText);

        console.log("[MCP] n8n_webhook_call →", u.toString());
        const res = await doFetch(u.toString(), { method: args.method || "GET" });

        return {
          content: [
            { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
            { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
          ]
        };
      }
    );

    console.log("[MCP] registering tools: echo_text, n8n_webhook_call");
  }
};
