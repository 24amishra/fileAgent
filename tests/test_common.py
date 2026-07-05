"""Tests for the safety-critical bits of common.py — no network, no API key."""

from pathlib import Path

from workspace_manager.common import (categorize, human, is_bundle, iter_files,
                                      safe_move)


def test_human_readable_sizes():
    assert human(0) == "0.0B"
    assert human(1024) == "1.0KB"
    assert human(25 * 1024 * 1024) == "25.0MB"


def test_categorize_by_extension():
    assert categorize(Path("x.dmg")) == "installer"
    assert categorize(Path("x.png")) == "image"
    assert categorize(Path("x.py")) == "code"
    assert categorize(Path("x.unknown")) == "other"


def test_bundles_are_opaque():
    assert is_bundle(Path("/Applications/Foo.app"))
    assert is_bundle(Path("~/Pictures/Library.photoslibrary"))
    assert not is_bundle(Path("/some/dir"))


def test_iter_files_treats_bundle_as_single_item(tmp_path):
    # A .app "bundle" with internal files must be yielded as ONE path,
    # never descended into.
    app = tmp_path / "Thing.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "bin").write_text("x")
    (tmp_path / "loose.txt").write_text("hello")

    found = set(iter_files(tmp_path, protected_dir_names=set()))
    assert app in found                              # bundle yielded whole
    assert (tmp_path / "loose.txt") in found         # ordinary file yielded
    # nothing from inside the bundle leaks out:
    assert not any("Thing.app" in str(p) and p != app for p in found)


def test_iter_files_prunes_protected_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x")
    (tmp_path / "keep.txt").write_text("x")

    found = set(iter_files(tmp_path, protected_dir_names={"node_modules"}))
    assert (tmp_path / "keep.txt") in found
    assert not any("node_modules" in str(p) for p in found)


def test_safe_move_never_overwrites(tmp_path):
    src1 = tmp_path / "a.txt"; src1.write_text("1")
    dest = tmp_path / "out" / "a.txt"
    final1 = safe_move(src1, dest)
    assert final1 == dest

    src2 = tmp_path / "a2.txt"; src2.write_text("2")
    final2 = safe_move(src2, dest)          # same target name -> must not clobber
    assert final2 != final1
    assert final1.read_text() == "1"
    assert final2.read_text() == "2"
