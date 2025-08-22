// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // 0-arg health check tool (no schema surprises)
    const Empty = z.object({}); // truly empty args
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      Empty,
      async () => {
        console.log("[MCP] ping_tool called");
        return { content: [{ type: "text", text: "pong" }] };
      }
    );

    // Echo tool with OPTIONAL text (defaults handled in code)
    const EchoSchema = z.object({
      text: z.string().describe("Text to echo back").optional()
    });
    server.tool(
      "echo_text",
      "Echo back text (if none provided, returns 'hello').",
      EchoSchema,
      async ({ text }) => {
        const out = text ?? "hello";
        console.log("[MCP] echo_text called with:", out);
        return { content: [{ type: "text", text: out }] };
      }
    );

    console.log("[MCP] registering tools: ping_tool, echo_text");
  }
};
