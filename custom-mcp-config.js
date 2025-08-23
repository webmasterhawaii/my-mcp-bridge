// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // ---------- Safety & diagnostics ----------
    process.on("uncaughtException", e => console.error("[MCP] uncaughtException", e));
    process.on("unhandledRejection", e => console.error("[MCP] unhandledRejection", e));

    // Helper: small fetch wrapper that returns {ok,status,data}
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

    // ---------- ping_tool ----------
    const Empty = z.object({});
    server.tool(
      "ping_tool",
      "Return 'pong' (connectivity test).",
      Empty,
      async () => ({ content: [{ type: "text", text: "pong" }] })
    );

    // ---------- n8n_webhook_call (REQUIRES message) ----------
    const N8nSchema = z.object({
      fullUrl: z.string().url().optional(),           // If provided, used as-is
      baseUrl: z.string().url().optional(),           // Else base + path + query
      path: z.string().optional(),
      method: z.enum(["GET","POST","PUT","PATCH"]).default("POST"),
      headers: z.record(z.string()).default({}),
      query: z.record(z.string()).default({}),
      message: z.string().min(1, "Put the user's full message here")
    }).refine(v => v.fullUrl || (v.baseUrl && v.path) || (process.env.N8N_BASE_URL && process.env.N8N_WEBHOOK_PATH), {
      message: "Provide fullUrl OR baseUrl+path OR set N8N_BASE_URL and N8N_WEBHOOK_PATH env vars"
    });

    server.tool(
      "n8n_webhook_call",
      "Forward the user's request to n8n. Always pass the full user utterance in 'message'.",
      N8nSchema,
      async (args) => {
        // Build URL
        const base = args.fullUrl ? null : (args.baseUrl || process.env.N8N_BASE_URL);
        const path = args.fullUrl ? null : (args.path || process.env.N8N_WEBHOOK_PATH);
        const urlStr = args.fullUrl ? args.fullUrl : new URL(path, base).toString();

        const u = new URL(urlStr);
        for (const [k, v] of Object.entries(args.query || {})) u.searchParams.set(k, v);

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

    // ---------- perplexity_search (Perplexityai-Server) ----------
    const PerplexitySchema = z.object({
      query: z.string().min(1).describe("The user question or search query"),
      search_depth: z.enum(["basic","deep"]).default("basic"),
      top_k: z.number().int().min(1).max(10).default(5),
      include_sources: z.boolean().default(true),
      model: z.string().optional(),
      focus: z.string().optional(),
      extra: z.record(z.any()).default({})
    });

    server.tool(
      "perplexity_search",
      "Ask Perplexity to answer a question with web search and citations.",
      PerplexitySchema,
      async (args) => {
        const baseUrl = process.env.PERPLEXITY_SERVER_URL;              // e.g. https://perplexity-server.example.com
        const endpointPath = process.env.PERPLEXITY_SERVER_PATH || "/api/actions/run";
        const apiKey = process.env.PERPLEXITY_SERVER_KEY || "";         // optional

        if (!baseUrl) {
          return { content: [{ type: "text", text: "Perplexity server not configured: set PERPLEXITY_SERVER_URL." }] };
        }
        const url = new URL(endpointPath, baseUrl).toString();

        // Common “server action” shape; adjust if your server expects a different payload
        const payload = {
          action: "PERPLEXITYAI_PERPLEXITY_AI_SEARCH",
          input: {
            query: args.query,
            search_depth: args.search_depth,
            top_k: args.top_k,
            include_sources: args.include_sources,
            model: args.model,
            focus: args.focus,
            ...args.extra
          }
        };

        const headers = { "content-type": "application/json" };
        if (apiKey) headers["authorization"] = `Bearer ${apiKey}`;

        const res = await doFetch(url, { method: "POST", headers, body: payload });

        // Normalize response into brief text + optional sources
        let answer = "";
        let sources = [];
        const raw = res.data;

        try {
          if (typeof raw === "string") {
            answer = raw;
          } else if (raw && typeof raw === "object") {
            answer =
              raw.answer ??
              raw.summary ??
              raw.output?.text ??
              raw.data?.answer ??
              JSON.stringify(raw);
            sources =
              raw.sources ??
              raw.citations ??
              raw.output?.sources ??
              raw.data?.sources ??
              [];
          }
        } catch { /* keep defaults */ }

        if (typeof answer === "string" && answer.length > 1200) {
          answer = answer.slice(0, 1150) + " …(truncated)";
        }

        const parts = [{ type: "text", text: answer || `HTTP ${res.status} (${res.ok ? "OK" : "Error"})` }];
        if (Array.isArray(sources) && sources.length) {
          parts.push({ type: "text", text: `Sources: ${JSON.stringify(sources).slice(0, 2000)}` });
        }
        return { content: parts };
      }
    );

    console.log("[MCP] registering tools: ping_tool, n8n_webhook_call, perplexity_search");
  }
};
