// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    process.on("uncaughtException", e => console.error("[MCP] uncaughtException", e));
    process.on("unhandledRejection", e => console.error("[MCP] unhandledRejection", e));

    async function doFetch(url, { method = "POST", headers = {}, body }) {
      const init = { method, headers: { ...headers } };
      if (body !== undefined) {
        init.body = typeof body === "string" ? body : JSON.stringify(body);
        if (!init.headers["content-type"]) init.headers["content-type"] = "application/json";
      }
      const res = await fetch(url, init);
      const text = await res.text().catch(() => "");
      let data;
      try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // Health check tool
    const Empty = z.object({});
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      Empty,
      async () => ({ content: [{ type: "text", text: "pong" }] })
    );

    // Webhook schema: very simple, we won't depend on Xiaozhi to pass anything
    const WebhookSchema = z.object({
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),
      method: z.enum(["GET", "POST", "PUT", "PATCH"]).default("POST"),
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({})
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), {
      message: "Provide fullUrl OR baseUrl+path"
    }).passthrough();

    server.tool(
      "n8n_webhook_call",
      "Automatically forwards ALL user input to your n8n webhook.",
      WebhookSchema,
      async (args, context) => {
        // Build webhook URL
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
        const u = new URL(urlStr);
        for (const [k, v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

        // Try to auto-extract the user's message
        let userText = "(missing_text)";
        if (context?.input?.text && context.input.text.trim() !== "") {
          userText = context.input.text.trim();
        } else if (context?.lastUserMessage && context.lastUserMessage.trim() !== "") {
          userText = context.lastUserMessage.trim();
        } else if (args?.message && args.message.trim() !== "") {
          userText = args.message.trim();
        }

        // Build body with guaranteed text
        const body = { text: userText };

        console.log("[MCP] n8n_webhook_call sending body:", body);

        // Send request to n8n
        const res = await doFetch(u.toString(), {
          method: args.method || "POST",
          headers: args.headers || {},
          body
        });

        return {
          content: [
            { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
            { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
          ]
        };
      }
    );

    console.log("[MCP] registering tools: ping_tool, n8n_webhook_call");
  }
};
