#!/usr/bin/env python3
"""Stop hook — self-improvement + Nexus lesson-saving cycle."""

import json

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": (
            "[POST-RESPONSE: self-improving + self-learning + Nexus cycle]\n"
            "Check the following:\n"
            "1. Were corrections given or mistakes made? → Use memory_save_lesson MCP tool to permanently save the lesson.\n"
            "2. New user preferences revealed? → Use memory_save MCP tool (memory_type=preference).\n"
            "3. Important facts or project context learned? → Use memory_save (memory_type=world or experience).\n"
            "4. Should ALL agents know this? → Use memory_save_global.\n"
            "5. Was the response optimal? Note what to improve next time.\n"
            "6. Update MEMORY.md if important user/project context was revealed.\n"
            "These steps run silently — only act if there is something genuinely worth saving."
        ),
    }
}))
