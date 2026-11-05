# weather

A context and tool-use forecast for Ramabana.

The status bar shows how full the context is as a word: `ctx clear 34%` under 50 percent, `ctx cloudy 65%` up to 80, and `ctx storm 92%` above that. The status segment reads `agent.status()['pct_full']` and shows nothing when that value is missing.

Above the prompt, a band draws one sparkline character per turn for the last 20 turns, sized by the number of tool calls that turn. A turn with a failed tool call (a result starting with `ERROR`) is drawn in red. The band is hidden while the agent is busy and before the first turn finishes.

`/weather` prints the number of turns seen, the average tool calls over the kept turns, and the failed calls among them.
