// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    const Schema = z.object({
      text: z.string().describe("Text to echo back")
    });

    // Test tool: echo back any text sent to it
    server.tool(
      "echo_text",
      "Echo back text (for connectivity tests).",
      Schema,
      async ({ text }) => ({
        content: [{ type: "text", text }]
      })
    );

    // Optional: add a simple ping tool for sanity checks
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      z.object({}).optional(),
      async () => ({
        content: [{ type: "text", text: "pong" }]
      })
    );
  }
};
