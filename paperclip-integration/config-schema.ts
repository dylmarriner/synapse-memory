/**
 * Paperclip Plugin Configuration Schema with Nexus Backend Support
 * Extends the existing plugin-agent-memory schema to include Nexus options.
 */

import { z } from "zod";

export const nexusConfigSchema = z.object({
  // Nexus backend configuration
  nexusUrl: z.string().optional().describe("Nexus server URL (default: http://100.93.75.87:7777)"),
  nexusSecret: z.string().optional().describe("Nexus API secret"),
  nexusEnabled: z.boolean().optional().describe("Use Nexus as memory backend (default: false)"),
  
  // Agent configuration
  agentId: z.string().optional().describe("Agent identifier for Nexus"),
  
  // Sync options
  syncIdentity: z.boolean().optional().describe("Sync agent identity to Nexus (default: true)"),
  trackActivity: z.boolean().optional().describe("Track agent activity in Nexus registry (default: true)"),
  
  // Fallback configuration
  fallbackToInternal: z.boolean().optional().describe("Fallback to internal DB if Nexus unavailable (default: true)"),
});

export type NexusConfig = z.infer<typeof nexusConfigSchema>;

// Extended instance config schema for the plugin
export const instanceConfigSchema = nexusConfigSchema.extend({
  // Existing Paperclip memory plugin config would go here
  // This is a placeholder for the actual existing schema
  memoryEnabled: z.boolean().optional().describe("Enable memory plugin (default: true)"),
  userProfileEnabled: z.boolean().optional().describe("Enable user profiling (default: true)"),
  writeApproval: z.boolean().optional().describe("Require approval for memory writes (default: false)"),
  memoryCharLimit: z.number().optional().describe("Character limit for memory context (default: 2200)"),
});