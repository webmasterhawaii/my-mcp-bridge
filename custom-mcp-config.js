// -------- n8n webhook tool (QUERY MODE) --------
const WebhookSchema = z.object({
  fullUrl: z.string().url().optional(),
  baseUrl: z.string().url().optional(),
  path: z.string().optional(),
  method: z.enum(["GET", "POST"]).default("GET"), // use GET for query
  headers: z.record(z.string()).default({}),
  query: z.record(z.string()).default({}),
  // accept either "message" or "text"
  message: z.string().optional(),
  text: z.string().optional()
}).refine(v => v.fullUrl || (v.baseUrl && v.path) || (process.env.N8N_BASE_URL && process.env.N8N_WEBHOOK_PATH), {
  message: "Provide fullUrl OR baseUrl+path OR set N8N_BASE_URL and N8N_WEBHOOK_PATH"
});

server.tool(
  "n8n_webhook_call",
  "Send the user's request to n8n via query string (?query=...). Prefer the 'message' field.",
  WebhookSchema,
  async (args, context) => {
    // ✅ Prefer message → text → lastUserMessage → (empty)
    const userText =
      (typeof args.message === "string" && args.message.trim().length ? args.message :
       typeof args.text === "string" && args.text.trim().length ? args.text :
       (context?.lastUserMessage && String(context.lastUserMessage).trim().length ? context.lastUserMessage : "(empty)"));

    // Build URL
    const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
    const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
    const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();

    const u = new URL(urlStr);

    // Always set ?query=<userText>
    u.searchParams.set("query", userText);

    // Include any extra query params
    for (const [k, v] of Object.entries(args.query || {})) {
      u.searchParams.set(k, v);
    }

    console.log("[MCP] n8n_webhook_call args:", JSON.stringify(args));
    console.log("[MCP] n8n_webhook_call sending query:", u.toString());

    const res = await doFetch(u.toString(), {
      method: args.method || "GET",
      headers: args.headers || {}
    });

    return {
      content: [
        { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
        { type: "text", text: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2) }
      ]
    };
  }
);
