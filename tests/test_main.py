import asyncio
import json
import os

import pytest
from mcp.client import Client

import main


@pytest.fixture
def tree(tmp_path):
    """tmp/big/ (20 KiB), tmp/small/ (4 KiB), tmp/link -> big (symlink)."""
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "f").write_bytes(b"x" * 20_000)
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "f").write_bytes(b"x")
    (tmp_path / "link").symlink_to(tmp_path / "big")
    return tmp_path


def by_path(result):
    return {e["path"]: e["bytes"] for e in result["entries"]}


# --- du ---------------------------------------------------------------------


def test_du_depth_1_lists_children_largest_first(tree):
    result = main.du(str(tree), depth=1)
    paths = [e["path"] for e in result["entries"]]
    assert paths[0] == str(tree)
    assert paths.index(str(tree / "big")) < paths.index(str(tree / "small"))
    assert by_path(result)[str(tree / "big")] >= 20_000


def test_du_depth_0_returns_only_root(tree):
    result = main.du(str(tree), depth=0)
    assert list(by_path(result)) == [str(tree)]


def test_du_does_not_follow_symlinks(tree):
    result = main.du(str(tree), depth=2)
    assert str(tree / "link") not in by_path(result)
    # big's 20 KiB is counted once, not twice via the link
    assert by_path(result)[str(tree)] < 2 * by_path(result)[str(tree / "big")]


def test_du_omits_entries_over_the_cap(tree, monkeypatch):
    monkeypatch.setattr(main, "MAX_ENTRIES", 1)
    result = main.du(str(tree), depth=1)
    assert len(result["entries"]) == 1
    assert result["omitted_entries"] >= 1


def test_du_reports_unreadable_directories(tree):
    if os.geteuid() == 0:
        pytest.skip("root can read everything")
    locked = tree / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        result = main.du(str(tree), depth=1)
    finally:
        locked.chmod(0o700)
    assert result["error_count"] >= 1
    assert str(tree) in by_path(result)  # still returns what it could read


def test_du_rejects_negative_depth(tree):
    with pytest.raises(ValueError, match="depth"):
        main.du(str(tree), depth=-1)


def test_du_rejects_missing_path_and_files(tree):
    with pytest.raises(ValueError, match="not a directory"):
        main.du(str(tree / "nope"))
    with pytest.raises(ValueError, match="not a directory"):
        main.du(str(tree / "big" / "f"))


def test_du_survives_hostile_filenames(tmp_path):
    """Newlines/tabs in names must not crash parsing or forge entries."""
    forged = tmp_path / "x\n999999999999\tforged"
    forged.mkdir()
    (tmp_path / "a\nb").mkdir()
    (tmp_path / ";touch pwned").mkdir()
    (tmp_path / "-rf").mkdir()

    result = main.du(str(tmp_path), depth=1)

    sizes = by_path(result)
    assert str(forged) in sizes
    assert all(size < 10**9 for size in sizes.values())
    assert not (tmp_path / "pwned").exists()
    assert not os.path.exists("pwned")


def test_du_treats_dash_prefixed_dir_as_path(tmp_path):
    (tmp_path / "-a").mkdir()
    assert str(tmp_path / "-a") in by_path(main.du(str(tmp_path / "-a"), depth=0))


# --- df ---------------------------------------------------------------------


def test_df_lists_filesystems_with_consistent_numbers():
    result = main.df()
    assert result["filesystems"]
    for fs in result["filesystems"]:
        assert fs["mount"].startswith("/")
        assert fs["used"] <= fs["size"]
        assert fs["percent_used"].endswith("%")


def test_df_with_path_returns_one_filesystem(tmp_path):
    result = main.df(str(tmp_path))
    assert len(result["filesystems"]) == 1
    assert result["filesystems"][0]["size"] > 0


def test_df_rejects_missing_path(tmp_path):
    with pytest.raises(ValueError, match="no such path"):
        main.df(str(tmp_path / "nope"))


def test_df_dash_prefixed_path_is_not_an_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-a").mkdir()
    # resolved to an absolute path, so "-a" can't be read as `df -a`
    assert len(main.df("-a")["filesystems"]) == 1


def test_df_line_regex_handles_spaces_in_source_and_mount():
    line = "my disk\text4\t100\t40\t60\t40%\t/mnt/my disk".replace("\t", " ")
    m = main.DF_LINE.match(line)
    assert m
    source, fstype, size, used, avail, pcent, mount = m.groups()
    assert (source, fstype, mount) == ("my disk", "ext4", "/mnt/my disk")
    assert (int(size), int(used), int(avail), pcent) == (100, 40, 60, "40%")


# --- over the MCP protocol --------------------------------------------------


def call(name, args):
    async def go():
        async with Client(main.mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def test_protocol_lists_both_tools():
    async def go():
        async with Client(main.mcp) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == {"du", "df"}


def test_protocol_du_returns_json(tree):
    res = call("du", {"path": str(tree), "depth": 1})
    assert not res.is_error
    assert str(tree / "big") in by_path(json.loads(res.content[0].text))


@pytest.mark.parametrize("depth", ["1; id", "1e1", "abc"])
def test_protocol_rejects_non_integer_depth(tree, depth):
    assert call("du", {"path": str(tree), "depth": depth}).is_error


def test_protocol_reports_bad_path_as_tool_error(tmp_path):
    assert call("du", {"path": str(tmp_path / "nope")}).is_error
