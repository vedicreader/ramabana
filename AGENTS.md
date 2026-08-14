# Agent instructions

- Always answer the user's question explicitly. After planning, researching, inspecting, or using tools, return the actual requested answer, plan, options, or conclusion in the final response; never end with only progress, status, or a statement that the work is complete.
- When the user asks to continue, first state the current implementation status: what is complete, what remains, and any blocker. Then resume work.
- Before the available tool-call budget is likely to end, proactively send the user a concise progress update: what is complete, what remains, and the next action. Do not wait for budget exhaustion.
- End every work turn with an explicit finishing statement. State the completed result; if blocked or unfinished, state the blocker and exact next action. Never end after tools with only a status update.
