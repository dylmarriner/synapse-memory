export const PLUGIN_ID = "nexus-memory";
export const PLUGIN_VERSION = "1.0.0";
export const DEFAULT_NEXUS_URL = "http://100.93.75.87:7777";
export const DEFAULT_AGENT_PREFIX = "paperclip";

export const TOOL_NAMES = {
  recall: "nexus_recall",
  save: "nexus_save",
  reflect: "nexus_reflect",
  status: "nexus_status",
  consolidate: "nexus_consolidate",
  confirm: "nexus_confirm",
  contradict: "nexus_contradict",
  context_reconstruct: "nexus_context_reconstruct",
} as const;

export const API_ROUTES = {
  health: "health",
  recall: "recall",
  save: "save",
  reflect: "reflect",
  consolidate: "consolidate",
  confirm: "confirm",
  contradict: "contradict",
  context_reconstruct: "context_reconstruct",
} as const;
