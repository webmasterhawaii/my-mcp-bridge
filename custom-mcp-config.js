// --- n8n via QUERY (?query=...) — robust, with deep logging ---
const N8nSchema = z.object({
  // we accept multiple possible fields so the model can’t “miss”
  message: z.string().optional(),
  text: z.string().optional(),
  query: z.string().optional(),
  method: z.enum(["GET","POST"]).default("GET")
  // no baseUrl/path/fullUrl here on purpose: use env for stability
});

server.tool(
  "n8n_webhook_call",
  "Forward the user's utterance to n8n via GET ?query=... (env: N8N_BASE_URL + N8N_WEBHOOK_PATH).",
  N8nSchema,
  async (args, context) => {
    // 1) Build URL from env (simple & reliable)
    const base = process.env.N8N_BASE_URL;
    const path = process.env.N8N_WEBHOOK_PATH;
    if (!base || !path) {
      return { content: [{ type: "text", text: "Missing N8N_BASE_URL or N8N_WEBHOOK_PATH." }] };
    }
    const u = new URL(path, base);

    // 2) Derive the user text robustly
    const pickFirstNonEmptyString = (obj) => {
      for (const v of Object.values(obj || {})) {
        if (typeof v === "string" && v.trim().length) return v.trim();
      }
      return null;
    };

    let userText =
      (typeof args.message === "string" && args.message.trim()) ||
      (typeof args.text === "string" && args.text.trim()) ||
      (typeof args.query === "string" && args.query.trim()) ||
      pickFirstNonEmptyString(args) ||
      (context?.lastUserMessage && String(context.lastUserMessage).trim()) ||
      null;

    // As ultimate fallback, stringify args so you at least see *something* useful in n8n
    if (!userText) {
      try {
        const asJson = JSON.stringify(args);
        userText = asJson && asJson !== "{}" ? asJson : "(empty)";
      } catch {
        userText = "(empty)";
      }
    }

    // 3) Set query param
    u.searchParams.set("query", userText);

    // 4) Deep logs so you can confirm exactly what happened
    console.log("[MCP] n8n_webhook_call RAW args:", JSON.stringify(args));
    console.log("[MCP] n8n_webhook_call derived userText:", userText);
    console.log("[MCP] n8n_webhook_call final URL:", u.toString());

    // 5) Make the request (GET by default)
    const res = await doFetch(u.toString(), {
      method: args.method || "GET",
      headers: {}
    });

    return {
      content: [
        { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
        { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
      ]
    };
  }
);
