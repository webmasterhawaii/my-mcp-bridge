console.log("[MCP] custom-mcp-config.js loaded (minimal)");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    try {
      const Empty = z.object({});

      server.tool(
        "ping_tool",
        "Return 'pong' (connectivity test).",
        Empty,
        async () => ({ content: [{ type: "text", text: "pong" }] })
      );

      // ultra-simple n8n tool with REQUIRED 'message'
      const WebhookSchema = z.object({
        fullUrl: z.string().url().optional(),
        baseUrl: z.string().url().optional(),
        path: z.string().optional(),
        method: z.enum(["POST","GET"]).default("POST"),
        headers: z.record(z.string()).default({}),
        message: z.string().min(1, "Put the user's message here")
      }).refine(v => v.fullUrl || (v.baseUrl && v.path), {
        message: "Provide fullUrl OR baseUrl+path"
      });

      server.tool(
        "n8n_webhook_call",
        "Forward the user's message to n8n.",
        WebhookSchema,
        async (args) => {
          const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
          const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
          const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
          const res = await fetch(urlStr, {
            method: args.method || "POST",
            headers: { "content-type": "application/json", ...(args.headers || {}) },
            body: JSON.stringify({ message: args.message })
          });
          const text = await res.text().catch(() => "");
          return {
            content: [
              { type: "text", text: `HTTP ${res.status}` },
              { type: "text", text }
            ]
          };
        }
      );

      console.log("[MCP] registered tools: ping_tool, n8n_webhook_call");
    } catch (e) {
      console.error("[MCP] configureMcp error:", e);
      throw e;
    }
  }
};
