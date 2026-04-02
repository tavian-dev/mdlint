"""Tests for mdlint."""

import os
import tempfile
from pathlib import Path

import pytest

from mdlint import (
    Issue, check_duplicate_titles, check_file, check_orphans,
    extract_links, find_markdown_files, parse_frontmatter,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# --- Frontmatter ---

class TestParseFrontmatter:
    def test_no_frontmatter(self):
        assert parse_frontmatter("# Hello\nWorld") == {}

    def test_basic(self):
        content = "---\ntype: fact\nconfidence: 0.8\n---\nBody"
        meta = parse_frontmatter(content)
        assert meta["type"] == "fact"
        assert meta["confidence"] == "0.8"

    def test_incomplete_frontmatter(self):
        assert parse_frontmatter("---\ntype: fact\n") == {}


# --- Link Extraction ---

class TestExtractLinks:
    def test_wikilink(self):
        links = extract_links("See [[other-file]] for details")
        assert len(links) == 1
        assert links[0] == (1, "other-file")

    def test_wikilink_with_display(self):
        links = extract_links("See [[other-file|display text]]")
        assert len(links) == 1
        assert links[0] == (1, "other-file")

    def test_markdown_link(self):
        links = extract_links("See [details](other.md)")
        assert len(links) == 1
        assert links[0] == (1, "other.md")

    def test_no_links(self):
        assert extract_links("Plain text, no links here") == []

    def test_multiple_links_same_line(self):
        links = extract_links("[[a]] and [[b]] together")
        assert len(links) == 2

    def test_multiline(self):
        links = extract_links("Line one [[a]]\nLine two [[b]]")
        assert links[0] == (1, "a")
        assert links[1] == (2, "b")


# --- File Checks ---

class TestCheckFile:
    def test_empty_file(self, tmp_dir):
        f = tmp_dir / "empty.md"
        write_file(f, "")
        issues = check_file(f, tmp_dir, set(), {})
        assert any(i.code == "W001" for i in issues)

    def test_missing_frontmatter_field(self, tmp_dir):
        f = tmp_dir / "test.md"
        write_file(f, "---\ntype: fact\n---\nContent")
        issues = check_file(f, tmp_dir, set(), {"type": "str", "confidence": "float"})
        assert any(i.code == "W002" and "confidence" in i.message for i in issues)

    def test_invalid_float_field(self, tmp_dir):
        f = tmp_dir / "test.md"
        write_file(f, "---\nconfidence: not-a-number\n---\nContent")
        issues = check_file(f, tmp_dir, set(), {"confidence": "float"})
        assert any(i.code == "E002" for i in issues)

    def test_broken_wikilink(self, tmp_dir):
        f = tmp_dir / "test.md"
        write_file(f, "Link to [[nonexistent]]")
        issues = check_file(f, tmp_dir, {str(f.resolve())}, {})
        assert any(i.code == "E003" for i in issues)

    def test_valid_wikilink(self, tmp_dir):
        target = tmp_dir / "target.md"
        write_file(target, "# Target")
        f = tmp_dir / "test.md"
        write_file(f, "Link to [[target]]")
        all_files = {str(target.resolve()), str(f.resolve())}
        issues = check_file(f, tmp_dir, all_files, {})
        assert not any(i.code == "E003" for i in issues)

    def test_valid_date_field(self, tmp_dir):
        f = tmp_dir / "test.md"
        write_file(f, "---\ndate: 2026-04-02\n---\nContent")
        issues = check_file(f, tmp_dir, set(), {"date": "date"})
        assert not any(i.code == "W003" for i in issues)

    def test_invalid_date_field(self, tmp_dir):
        f = tmp_dir / "test.md"
        write_file(f, "---\ndate: yesterday\n---\nContent")
        issues = check_file(f, tmp_dir, set(), {"date": "date"})
        assert any(i.code == "W003" for i in issues)


# --- Orphans ---

class TestOrphans:
    def test_detects_orphan(self, tmp_dir):
        write_file(tmp_dir / "a.md", "# A")
        write_file(tmp_dir / "b.md", "# B\n[[a]]")
        files = find_markdown_files(tmp_dir)
        issues = check_orphans(files, tmp_dir)
        # b links to a, so a is not orphaned. But b IS orphaned.
        orphan_files = [i.file for i in issues]
        assert "b.md" in orphan_files
        assert "a.md" not in orphan_files

    def test_no_orphans_when_bidirectional(self, tmp_dir):
        write_file(tmp_dir / "a.md", "# A\n[[b]]")
        write_file(tmp_dir / "b.md", "# B\n[[a]]")
        files = find_markdown_files(tmp_dir)
        issues = check_orphans(files, tmp_dir)
        assert len(issues) == 0

    def test_skips_special_files(self, tmp_dir):
        write_file(tmp_dir / "README.md", "# README")
        write_file(tmp_dir / "STATE.md", "# State")
        files = find_markdown_files(tmp_dir)
        issues = check_orphans(files, tmp_dir)
        assert len(issues) == 0


# --- Duplicates ---

class TestDuplicates:
    def test_detects_duplicate_title(self, tmp_dir):
        write_file(tmp_dir / "a.md", "# My Title")
        write_file(tmp_dir / "b.md", "# My Title")
        files = find_markdown_files(tmp_dir)
        issues = check_duplicate_titles(files, tmp_dir)
        assert any(i.code == "W004" for i in issues)

    def test_different_titles_ok(self, tmp_dir):
        write_file(tmp_dir / "a.md", "# Title A")
        write_file(tmp_dir / "b.md", "# Title B")
        files = find_markdown_files(tmp_dir)
        issues = check_duplicate_titles(files, tmp_dir)
        assert len(issues) == 0

    def test_frontmatter_title_duplicate(self, tmp_dir):
        write_file(tmp_dir / "a.md", "---\ntitle: Same\n---\n")
        write_file(tmp_dir / "b.md", "---\ntitle: same\n---\n")
        files = find_markdown_files(tmp_dir)
        issues = check_duplicate_titles(files, tmp_dir)
        assert any(i.code == "W004" for i in issues)


# --- File Discovery ---

class TestFileDiscovery:
    def test_finds_md_files(self, tmp_dir):
        write_file(tmp_dir / "a.md", "content")
        write_file(tmp_dir / "sub" / "b.md", "content")
        files = find_markdown_files(tmp_dir)
        assert len(files) == 2

    def test_skips_hidden_dirs(self, tmp_dir):
        write_file(tmp_dir / ".hidden" / "a.md", "content")
        files = find_markdown_files(tmp_dir)
        assert len(files) == 0

    def test_skips_archive(self, tmp_dir):
        write_file(tmp_dir / "archive" / "old.md", "content")
        files = find_markdown_files(tmp_dir)
        assert len(files) == 0
