// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // Health check
    server.tool("ping_tool", "Health check", z.object({}), async () => (
      { content: [{ type: "text", text: "pong" }] }
    ));

    // Webhook trigger for n8n
    const WebhookSchema = z.object({
      // Use either fullUrl OR baseUrl+path
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),
      method: z.enum(["GET","POST","PUT","PATCH"]).default("POST"),
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),
      payload: z.any().optional()
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), { message: "Provide fullUrl or baseUrl+path" });

    async function doFetch(url, { method='POST', headers={}, body }) {
      const init = { method, headers };
      if (body !== undefined) {
        init.body = typeof body === 'string' ? body : JSON.stringify(body);
        init.headers = { 'content-type': 'application/json', ...headers };
      }
      const res = await fetch(url, init);
      const text = await res.text().catch(() => '');
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    server.tool(
      "n8n_webhook_call",
      "Invoke an n8n Webhook and return its response.",
      WebhookSchema,
      async (args) => {
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();

        const u = new URL(urlStr);
        for (const [k,v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

        const res = await doFetch(u.toString(), {
          method: args.method,
          headers: args.headers || {},
          body: args.payload
        });

        return {
          content: [
            { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
            { type: "text", text: typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2) }
          ]
        };
      }
    );

    console.log("[MCP] registering tools: ping_tool, n8n_webhook_call");
  }
};
