// custom-mcp-config.js
module.exports = {
  configureMcp(server, ResourceTemplate, z) {
    const Schema = z.object({ text: z.string().describe("Text to echo back") });
    server.tool(
      "echo_text",
      "Echo back text (for connectivity tests).",
      Schema,
      async ({ text }) => ({ content: [{ type: "text", text }] })
    );
  }
};