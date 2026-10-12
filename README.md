# du-mcp

A small [MCP](https://modelcontextprotocol.io) server that lets an agent analyze disk space. It wraps GNU `df` and `du` and returns structured JSON, so the agent can find the full filesystem and then drill down into whatever is using the space.

**Requires Linux** (GNU `df`/`du`; macOS's BSD versions lack the flags used) and Python 3.11+.

## Tools

### `df(path=None)`

Free space per mounted filesystem (`df -B1 --output=...`).

- no `path`: every mounted filesystem
- `path`: only the filesystem containing it

Returns `filesystems`: a list of `{source, fstype, mount, size, used, available, percent_used}` (sizes in bytes), plus any `errors`.

### `du(path="/", depth=1)`

Disk usage of `path` and its subdirectories down to `depth` levels (`du -x -B1 --max-depth=depth`).

- sizes are allocated bytes
- symlinks are not followed and other filesystems are not entered
- entries are sorted largest first and include `path` itself as its total
- output is capped at 200 entries (`omitted_entries` says how many were cut) and the call times out after 60 s

Returns `entries` (`{path, bytes}`), `omitted_entries`, `errors` and `error_count`. Unreadable directories show up in `errors` and don't fail the call.

### Intended use

The agent calls `df` to see which filesystem is full, then calls `du` repeatedly: shallow on a high-level path first, then deeper on the largest entries.

## Setup

```sh
uv sync
```

### Use with Claude Code

Register it for your user:

```sh
claude mcp add du-mcp -- uv --directory /path/to/du-mcp run main.py
```

Or open Claude Code in this folder: [.mcp.json](.mcp.json) registers the server for the project (Claude Code asks you to approve it the first time). Check it with `/mcp`.

### Try it interactively

```sh
uv run mcp dev main.py   # opens the MCP Inspector
```

## Tests

```sh
uv run pytest
```

The tests build temporary directory trees and also run against your real mounts (for `df`), so they need GNU `df`/`du`.

## Security notes

- Commands are run as argument lists with no shell. Paths are resolved to absolute paths and passed after `--`, and `du` uses NUL-separated output, so hostile filenames can't inject commands, options or fake entries.
- The tools can see the names and sizes of anything the server's user can read, and the server has **no path allowlist**. That is fine over stdio; add restrictions before exposing it over HTTP.
- Filenames come back to the agent as-is. Treat them as untrusted data: a file in a shared directory could be named like an instruction.
