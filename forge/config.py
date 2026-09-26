"""All tunable settings in one place. Each can be overridden with an env var."""
import os

PROJECT = os.environ.get("FORGE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("FORGE_LOCATION", "global")
MODEL = os.environ.get("FORGE_MODEL", "gemini-3.8-flash")
# If the main model keeps failing (overloaded / rate-limited), try these in order.
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]
REQUEST_TIMEOUT = 60   # seconds per model call

MAX_TURNS = int(os.environ.get("FORGE_MAX_TURNS", "50"))           # loop safety cap per user message
COMPACT_AT_TOKENS = int(os.environ.get("FORGE_COMPACT_AT", "150000"))  # auto-summarize past this prompt size
TOOL_OUTPUT_LIMIT = 20_000                                          # chars; longer tool output is truncated
SHELL_INIT = os.environ.get("FORGE_SHELL_INIT", "")                  # prepended to every run_shell command
SHELL_TIMEOUT = 120                                                # seconds
MEMORY_FILES = ["FORGE.md", "AGENTS.md"]                            # project instructions loaded into the prompt
