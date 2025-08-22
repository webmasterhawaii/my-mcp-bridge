// custom-mcp-config.js
console.log("[MCP] custom-mcp-config.js loaded");

module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    // Accept empty args {} by providing a default.
    // `.catch('hello')` ensures we still get a value even if it's missing or invalid.
    const EchoSchema = z.object({
      text: z.string().describe("Text to echo back").catch("hello")
    });

    // Echo tool: works even if arguments are {}
    server.tool(
      "echo_text",
      "Echo back text (accepts empty args; defaults to 'hello').",
      EchoSchema,
      async ({ text }) => {
        console.log("[MCP] echo_text called with:", text);
        return { content: [{ type: "text", text }] };
      }
    );

    // No-arg health check
    const PingSchema = z.object({}); // truly no args
    server.tool(
      "ping_tool",
      "Responds with 'pong' to confirm connectivity.",
      PingSchema,
      async () => {
        console.log("[MCP] ping_tool called");
        return { content: [{ type: "text", text: "pong" }] };
      }
    );

    console.log("[MCP] registering tools: echo_text, ping_tool");
  }
};
