#!/usr/bin/env node
/**
 * UPS MCP Server Entry Point
 *
 * This is the main entry point for the UPS Shipping MCP server.
 * It initializes the MCP server with stdio transport for Claude SDK integration.
 *
 * The server validates UPS credentials on startup and fails fast with clear
 * error messages if any required credentials are missing.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// Import config to trigger validation on startup
// This will throw immediately if credentials are missing
import { config } from "./config.js";

// Server name and version
const SERVER_NAME = "ups-mcp";
const SERVER_VERSION = "1.0.0";

/**
 * Main entry point for the UPS MCP server
 */
async function main(): Promise<void> {
  // Log startup to stderr (stdout is reserved for MCP protocol)
  console.error(`[${SERVER_NAME}] Starting UPS MCP Server v${SERVER_VERSION}`);
  console.error(`[${SERVER_NAME}] Using UPS sandbox environment: ${config.baseUrl}`);
  console.error(`[${SERVER_NAME}] Labels output directory: ${config.labelsOutputDir}`);

  // Create MCP server instance
  const server = new McpServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
  });

  // Create stdio transport for communication with Claude SDK
  const transport = new StdioServerTransport();

  // Connect server to transport
  await server.connect(transport);

  console.error(`[${SERVER_NAME}] Server started successfully`);
  console.error(`[${SERVER_NAME}] Waiting for MCP commands...`);
}

// Run the server
main().catch((error: Error) => {
  console.error(`[${SERVER_NAME}] Fatal error:`, error.message);
  process.exit(1);
});
