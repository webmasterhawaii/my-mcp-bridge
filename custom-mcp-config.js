// /app/custom-mcp-config.js
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
      let data; try { data = JSON.parse(text); } catch { data = text; }
      return { ok: res.ok, status: res.status, data };
    }

    // ---- ping ----
    const Empty = z.object({});
    server.tool("ping_tool","Return 'pong' (connectivity test).",Empty, async () => ({
      content: [{ type: "text", text: "pong" }]
    }));

    // ---- n8n webhook (REQUIRES message) ----
    const WebhookSchema = z.object({
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),
      method: z.enum(["GET","POST","PUT","PATCH"]).default("POST"),
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),
      message: z.string().min(1, "Put the user's full message here")
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), { message: "Provide fullUrl OR baseUrl+path" });

    server.tool(
      "n8n_webhook_call",
      "Forward the user's request to n8n. Always pass the full user utterance in 'message'.",
      WebhookSchema,
      async (args) => {
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
        const u = new URL(urlStr);
        for (const [k,v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

        const body = { message: args.message };
        console.log("[MCP] n8n_webhook_call sending body:", body);

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
