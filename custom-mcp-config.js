// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // Log unexpected errors so they don't fail silently during tools/list
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
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // -------- health check --------
    const Empty = z.object({});
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      Empty,
      async () => ({ content: [{ type: "text", text: "pong" }] })
    );

    // -------- n8n webhook (schema kept very simple) --------
    const WebhookSchema = z.object({
      // Provide either fullUrl OR baseUrl+path
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),

      method: z.enum(["GET", "POST", "PUT", "PATCH"]).default("POST"),
      // Keep records as string=>string to stay serializable in tool metadata
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),

      // JSON payload as a STRING; we parse it safely inside the tool
      payloadJson: z.string().optional(),

      // convenience plain text (used if no payloadJson provided)
      text: z.string().optional()
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), { message: "Provide fullUrl OR baseUrl+path" });

    server.tool(
      "n8n_webhook_call",
      "POST/GET to your n8n Webhook and return its response. Supply payloadJson as a JSON string.",
      WebhookSchema,
      async (args) => {
        // Build URL
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
        const u = new URL(urlStr);
        for (const [k, v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

        // Build a non-empty body
        let body;
        if (args.payloadJson && args.payloadJson.trim() !== "") {
          try { body = JSON.parse(args.payloadJson); }
          catch { body = { payloadParseError: true, raw: args.payloadJson }; }
        } else if (args.text) {
          body = { text: args.text };
        } else {
          body = { ping: true };
        }

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
