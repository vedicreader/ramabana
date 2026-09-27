"""A tiny stdio MCP server `tests/test_mcpclient.py` spawns as a real subprocess, over the real
JSON-RPC wire mcpmini speaks. `mcpmini.MCPServer`'s own schema helper never emits `annotations`,
so every tool it serves comes back unannotated -- exactly the common case a client has to default
safely for.
"""
import asyncio

from mcpmini.core import MCPServer, serve_stdio


def add(a: int, b: int) -> str:
    "Add two numbers."
    return str(a + b)


async def main():
    srv = MCPServer('test-server', tools=[add])
    await serve_stdio(srv)


if __name__ == '__main__':
    asyncio.run(main())
