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

    // -------- n8n webhook (keep schema simple) --------
    const WebhookSchema = z.object({
      // Provide either fullUrl OR baseUrl+path
      fullUrl: z.string().url().optional(),
      baseUrl: z.string().url().optional(),
      path: z.string().optional(),

      method: z.enum(["GET","POST","PUT","PATCH"]).default("POST"),
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),

      // Preferred inputs
      payloadJson: z.string().optional(), // stringified JSON
      text: z.string().optional()         // plain text
    }).refine(v => v.fullUrl || (v.baseUrl && v.path), {
      message: "Provide fullUrl OR baseUrl+path"
    });

    server.tool(
      "n8n_webhook_call",
      "Send user's utterance to n8n webhook and return the response.",
      WebhookSchema,
      async (args, context) => {
        // Build URL
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
        const u = new URL(urlStr);
        for (const [k, v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

        // Derive user text from (1) payloadJson, (2) text, (3) context
        let userText;

        if (typeof args.payloadJson === "string" && args.payloadJson.trim() !== "") {
          try {
            const pj = JSON.parse(args.payloadJson);
            if (typeof pj?.text === "string" && pj.text.trim() !== "") {
              userText = pj.text;
            } else {
              // fallback: use the whole object as a compact string
              userText = JSON.stringify(pj);
            }
          } catch {
            userText = args.payloadJson; // raw string if not valid JSON
          }
        }

        if (!userText && typeof args.text === "string" && args.text.trim() !== "") {
          userText = args.text.trim();
        }

        // Try runtime context (may not be provided by all MCP hosts)
        if (!userText && typeof context?.input?.text === "string" && context.input.text.trim() !== "") {
          userText = context.input.text.trim();
        }
        if (!userText && typeof context?.lastUserMessage === "string" && context.lastUserMessage.trim() !== "") {
          userText = context.lastUserMessage.trim();
        }

        // Final fallback so n8n never sees an empty body
        if (!userText) userText = "(missing_text_from_agent)";

        const body = { text: userText };

        try {
          console.log("[MCP] n8n_webhook_call body:", body);
        } catch {}

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
