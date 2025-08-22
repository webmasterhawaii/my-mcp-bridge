# Dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .

# Run the MCP bridge and load your test tool.
# WS_URL will be injected by Railway as an environment variable.
CMD ["sh","-c","npx mcp_exe --ws \"$WS_URL\" --mcp-config ./mcp.json --mcp-js ./custom-mcp-config.js --verbose"]
