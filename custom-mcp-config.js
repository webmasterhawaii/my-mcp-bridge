// custom-mcp-config.js
process.on('uncaughtException', e => console.error('[MCP] uncaughtException', e));
process.on('unhandledRejection', e => console.error('[MCP] unhandledRejection', e));
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    const ApiSchema = z.object({
      endpoint: z.string().describe("n8n API endpoint, e.g. /rest/workflows or /rest/executions"),
      method: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]).default("GET"),
      query: z.record(z.any()).default({}).describe("Optional query params"),
      payload: z.any().optional().describe("JSON body for POST/PUT/PATCH"),
      apiKey: z.string().optional().describe("Override n8n API key if not set via env"),
      baseUrl: z.string().optional().describe("Override base URL if not set via env")
    });

    server.tool(
      "n8n_api_command",
      "Call any n8n REST API endpoint with optional query and payload",
      ApiSchema,
      async ({ endpoint, method, query, payload, apiKey, baseUrl }) => {
        const urlBase = baseUrl || process.env.N8N_BASE_URL;
        const token = apiKey || process.env.N8N_API_KEY;

        if (!urlBase || !token) {
          return {
            content: [
              { type: "text", text: "Missing configuration: set baseUrl/apiKey or use env vars N8N_BASE_URL + N8N_API_KEY." }
            ]
          };
        }

        // Build full URL with query params
        const url = new URL(endpoint, urlBase);
        Object.entries(query).forEach(([k, v]) => url.searchParams.set(k, v));

        const headers = {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        };

        const res = await fetch(url.toString(), {
          method,
          headers,
          body: ["POST", "PUT", "PATCH"].includes(method) ? JSON.stringify(payload || {}) : undefined
        });

        const text = await res.text();
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }

        return {
          content: [
            { type: "text", text: `HTTP ${res.status} ${res.ok ? "OK" : "ERROR"}` },
            { type: "text", text: typeof data === "string" ? data : JSON.stringify(data, null, 2) }
          ]
        };
      }
    );

    console.log("[MCP] registered tool: n8n_api_command");
  }
};
