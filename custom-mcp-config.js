// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    process.on("uncaughtException", e =>
      console.error("[MCP] uncaughtException", e)
    );
    process.on("unhandledRejection", e =>
      console.error("[MCP] unhandledRejection", e)
    );

    async function doFetch(url, { method = "GET", headers = {} }) {
      const init = { method, headers: { ...headers } };
      const res = await fetch(url, init);
      const text = await res.text().catch(() => "");
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
      return { ok: res.ok, status: res.status, data };
    }

    // -------- Health check tool --------
    const Empty = z.object({});
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      Empty,
      async () => ({ content: [{ type: "text", text: "pong" }] })
    );

    // -------- n8n webhook tool (QUERY MODE) --------
    const WebhookSchema = z.object({
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),
      method: z.enum(["GET", "POST"]).default("GET"), // Default to GET for query usage
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),
      text: z.string().optional()
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), {
      message: "Provide fullUrl OR baseUrl+path"
    });

    server.tool(
      "n8n_webhook_call",
      "Automatically sends ANYTHING the user says to your n8n webhook via query parameters.",
      WebhookSchema,
      async (args, context) => {
        // Grab user’s spoken text from Xiaozhi if not explicitly provided
        let userText = args.text || (context?.lastUserMessage) || "(empty)";

        // Build URL
        const base = args.fullUrl
          ? null
          : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl
          ? null
          : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl
          ? args.fullUrl
          : new URL(path, base).toString();

        const u = new URL(urlStr);

        // Always pass the user query as a URL param
        u.searchParams.set("query", userText);

        // Include any extra query params if configured
        for (const [k, v] of Object.entries(args.query || {})) {
          u.searchParams.set(k, v);
        }

        console.log("[MCP] n8n_webhook_call sending query:", u.toString());

        const res = await doFetch(u.toString(), {
          method: args.method || "GET",
          headers: args.headers || {}
        });

        return {
          content: [
            {
              type: "text",
              text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}`
            },
            {
              type: "text",
              text:
                typeof res.data === "string"
                  ? res.data
                  : JSON.stringify(res.data, null, 2)
            }
          ]
        };
      }
    );

    console.log("[MCP] registering tools: ping_tool, n8n_webhook_call");
  }
};
