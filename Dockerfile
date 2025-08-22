FROM node:20-alpine
WORKDIR /app

# Install the CLI once at build time
RUN npm i -g mcp_exe@0.12.0

# Copy your app
COPY . .

# Helpful for surfacing errors instead of swallowing them
ENV NODE_OPTIONS=--unhandled-rejections=strict

# Run the bridge
CMD ["sh","-c","mcp_exe --ws \"$WS_URL\" --mcp-config ./mcp.json --mcp-js ./custom-mcp-config.js --verbose"]
