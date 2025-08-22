// --- inside configureMcp(...) ---

const WebhookSchema = z.object({
  fullUrl: z.string().url().optional(),
  baseUrl: z.string().url().optional(),
  path: z.string().optional(),
  method: z.enum(["GET","POST","PUT","PATCH"]).default("POST"),
  headers: z.record(z.string()).default({}),
  query: z.record(z.string()).default({}),
  payload: z.any().optional(),
  text: z.string().optional()  // allow plain text fallback
}).refine(v => v.fullUrl || (v.baseUrl && v.path), { message: "Provide fullUrl or baseUrl+path" });

server.tool(
  "n8n_webhook_call",
  "Invoke an n8n Webhook and return its response.",
  WebhookSchema,
  async (args) => {
    const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
    const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
    const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();

    // Build URL + query
    const u = new URL(urlStr);
    for (const [k,v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

    // *** FORCE a JSON body ***
    let body = args.payload;
    if (typeof body === "string") body = { text: body };
    if (!body && args.text) body = { text: args.text };
    if (!body) body = { ping: true };  // last-resort non-empty body

    // Ensure content-type json
    const headers = { "content-type": "application/json", ...(args.headers || {}) };

    const res = await fetch(u.toString(), {
      method: args.method || "POST",
      headers,
      body: JSON.stringify(body)
    });

    const text = await res.text().catch(() => "");
    let data; try { data = JSON.parse(text); } catch { data = text; }

    return {
      content: [
        { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
        { type: "text", text: typeof data === "string" ? data : JSON.stringify(data, null, 2) }
      ]
    };
  }
);
