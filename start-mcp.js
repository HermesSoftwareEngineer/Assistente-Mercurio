/**
 * Starts the mcp-obsidian MCP server using OBSIDIAN_VAULT_PATH from .env.
 * Run with: npm run mcp
 */
require("dotenv").config();
const { spawn } = require("child_process");

const vaultPath = process.env.OBSIDIAN_VAULT_PATH;
if (!vaultPath) {
  console.error("❌ OBSIDIAN_VAULT_PATH not set in .env");
  process.exit(1);
}

console.log(`🗂️  Starting mcp-obsidian → ${vaultPath}`);
const child = spawn("npx", ["-y", "mcp-obsidian", vaultPath], {
  stdio: "inherit",
  shell: true,
});
child.on("close", (code) => process.exit(code ?? 0));
