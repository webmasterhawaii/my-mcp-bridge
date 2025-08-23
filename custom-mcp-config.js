// -------- n8n webhook tool (REQUIRES message) --------
const WebhookSchema = z.object({
  fullUrl: z.string().url().optional(),
  baseUrl: z.string().url().optional(),
  path: z.string().optional(),

  method: z.enum(["GET", "POST", "PUT", "PATCH"]).default("POST"),
  headers: z.record(z.string()).default({}),
  query: z.record(z.string()).default({}),

  // REQUIRED: force the model to pass the user's utterance
  message: z.string().min(1, "Put the user's full message here"),

  // Optional: if you want to pass richer JSON too
  payloadJson: z.string().optional()
}).refine(v => v.fullUrl || (v.baseUrl && v.path), {
  message: "Provide fullUrl OR baseUrl+path"
});

server.tool(
  "n8n_webhook_call",
  "Forward the user's request to n8n. Always pass the full user utterance in 'message'.",
  WebhookSchema,
  async (args /*, context */) => {
    // Build URL
    const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
    const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
    const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();
    const u = new URL(urlStr);
    for (const [k, v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

    // Body we send to n8n
    const body = { message: args.message };
    if (typeof args.payloadJson === "string" && args.payloadJson.trim() !== "") {
      try { body.payload = JSON.parse(args.payloadJson); }
      catch { body.payload = { raw: args.payloadJson, parseError: true }; }
    }

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
