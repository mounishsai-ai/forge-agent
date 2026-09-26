"""A tiny MCP server (stdio, stdlib only) used by tests/test_mcp.py and for manual testing.

Tools:  echo(text) -> text        add(a, b) -> a + b   (isError=true if a/b are not numbers)
If ECHO_MCP_LOG is set, every tools/call is appended to that file (proof the tool really ran).
Run it by hand and type:  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
"""
import json
import os
import sys

TOOLS = [
    {"name": "echo", "description": "Echo the given text back.",
     "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
                     "properties": {"text": {"type": "string"}}, "required": ["text"],
                     "additionalProperties": False}},
    {"name": "add", "description": "Add two numbers and return the sum.",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
]


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name, args):
    log = os.environ.get("ECHO_MCP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tool": name, "arguments": args}) + "\n")
    if name == "echo":
        return text_result(str(args.get("text", "")))
    if name == "add":
        a, b = args.get("a"), args.get("b")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
            return text_result(f"add needs two numbers, got a={a!r} b={b!r}", is_error=True)
        total = a + b
        if float(total).is_integer():
            total = int(total)       # models often send 2.0 / 40.0; answer 42, not 42.0
        return text_result(str(total))
    return None


def main():
    sys.stdout.reconfigure(newline="\n")   # no \r\n on Windows
    print("echo-mcp-server starting", file=sys.stderr, flush=True)   # stderr = logging, allowed
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:          # notification (e.g. notifications/initialized): no reply
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-11-25"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-mcp-server", "version": "0.1"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params", {})
            result = call_tool(p.get("name"), p.get("arguments") or {})
            if result is None:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32602, "message": f"Unknown tool: {p.get('name')}"}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "result": result})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})


if __name__ == "__main__":
    main()
