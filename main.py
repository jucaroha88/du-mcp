import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    "du-mcp",
    instructions=(
        "Disk space analysis via du. Call `du` repeatedly, starting shallow on a "
        "high-level path and then drilling into the largest entries."
    ),
)

MAX_ENTRIES = 200
TIMEOUT_S = 60


@mcp.tool()
def du(path: str = "/", depth: int = 1) -> dict:
    """Disk usage of `path` and its subdirectories down to `depth` levels.

    Wraps `du -x --max-depth=<depth>`: sizes are allocated bytes, symlinks are not
    followed and other filesystems are not entered. Entries are sorted largest first
    and include `path` itself (its total). Call again with a deeper `depth` or on a
    subdirectory to drill down.
    """
    if depth < 0:
        raise ValueError("depth must be >= 0")
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    try:
        proc = subprocess.run(
            ["du", "-x", "-0", "-B1", f"--max-depth={depth}", "--", str(root)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"du timed out after {TIMEOUT_S}s; try a smaller path or depth")

    entries = []
    # -0 ends each record with NUL, so filenames containing newlines can't break parsing.
    for record in proc.stdout.split("\0"):
        if record:
            size, _, name = record.partition("\t")
            entries.append({"path": name, "bytes": int(size)})
    entries.sort(key=lambda e: e["bytes"], reverse=True)

    # du exits 1 on unreadable dirs but still prints everything it could read.
    errors = proc.stderr.splitlines()
    return {
        "entries": entries[:MAX_ENTRIES],
        "omitted_entries": max(0, len(entries) - MAX_ENTRIES),
        "errors": errors[:10],
        "error_count": len(errors),
    }


def main():
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
