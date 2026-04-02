#!/usr/bin/env python3
"""mdlint — lint markdown knowledge bases.

Checks for:
- Broken internal links (wikilinks and markdown links)
- Missing required frontmatter fields
- Orphaned files (nothing links to them)
- Duplicate titles
- Empty files

Usage:
    mdlint <directory> [--schema FIELD:TYPE ...] [--json] [--fix-orphans]
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Issue:
    file: str
    line: int
    level: str  # error, warning, info
    code: str
    message: str


def find_markdown_files(directory: Path) -> list[Path]:
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "archive"]
        for f in filenames:
            if f.endswith(".md"):
                files.append(Path(root) / f)
    return sorted(files)


def parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    fm_str = content[3:end].strip()
    meta = {}
    for line in fm_str.split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def extract_links(content: str) -> list[tuple[int, str]]:
    """Extract internal links (wikilinks and markdown links to .md files)."""
    links = []
    for i, line in enumerate(content.split("\n"), 1):
        # Wikilinks: [[filename]] or [[filename|display]]
        for match in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", line):
            links.append((i, match.group(1)))
        # Markdown links to .md files: [text](path.md) or [text](path)
        for match in re.finditer(r"\[([^\]]+?)\]\(([^)]+?\.md)\)", line):
            links.append((i, match.group(2)))
    return links


def check_file(filepath: Path, directory: Path, all_files: set[str],
               schema: dict[str, str]) -> list[Issue]:
    issues = []
    rel = str(filepath.relative_to(directory))

    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        issues.append(Issue(rel, 0, "error", "E001", f"Cannot read file: {e}"))
        return issues

    # Empty file
    if not content.strip():
        issues.append(Issue(rel, 0, "warning", "W001", "File is empty"))
        return issues

    # Frontmatter schema check
    meta = parse_frontmatter(content)
    for field_name, field_type in schema.items():
        if field_name not in meta:
            issues.append(Issue(rel, 0, "warning", "W002",
                              f"Missing frontmatter field: {field_name}"))
        elif field_type == "float":
            try:
                float(meta[field_name])
            except ValueError:
                issues.append(Issue(rel, 0, "error", "E002",
                                  f"Field '{field_name}' should be float, got: {meta[field_name]}"))
        elif field_type == "date":
            if not re.match(r"\d{4}-\d{2}-\d{2}", meta[field_name]):
                issues.append(Issue(rel, 0, "warning", "W003",
                                  f"Field '{field_name}' doesn't look like a date: {meta[field_name]}"))

    # Broken links
    links = extract_links(content)
    for line_num, target in links:
        # Resolve target relative to the file's directory
        target_path = filepath.parent / target
        if not target_path.suffix:
            target_path = target_path.with_suffix(".md")

        # Check various resolution strategies
        resolved = False
        for candidate in [
            target_path,
            directory / target if not target.endswith(".md") else directory / target,
            directory / (target + ".md"),
        ]:
            if str(candidate.resolve()) in all_files or candidate.exists():
                resolved = True
                break

        # Also check by stem (for wikilinks without path)
        if not resolved:
            target_stem = Path(target).stem
            for f in all_files:
                if Path(f).stem == target_stem:
                    resolved = True
                    break

        if not resolved:
            issues.append(Issue(rel, line_num, "error", "E003",
                              f"Broken link: {target}"))

    return issues


def check_orphans(all_files: list[Path], directory: Path) -> list[Issue]:
    """Find files that no other file links to."""
    linked_stems = set()
    for filepath in all_files:
        try:
            content = filepath.read_text(encoding="utf-8")
            links = extract_links(content)
            for _, target in links:
                linked_stems.add(Path(target).stem)
        except (OSError, UnicodeDecodeError):
            continue

    issues = []
    for filepath in all_files:
        rel = str(filepath.relative_to(directory))
        stem = filepath.stem
        # Skip index/readme/state files
        if stem.lower() in ("readme", "index", "state", "memory"):
            continue
        if stem not in linked_stems:
            issues.append(Issue(rel, 0, "info", "I001",
                              f"Orphaned file: nothing links to {stem}"))
    return issues


def check_duplicate_titles(all_files: list[Path], directory: Path) -> list[Issue]:
    """Find files with duplicate titles."""
    titles: dict[str, list[str]] = defaultdict(list)
    for filepath in all_files:
        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta = parse_frontmatter(content)
        title = meta.get("title", meta.get("name", ""))
        if not title:
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        if title:
            titles[title.lower()].append(str(filepath.relative_to(directory)))

    issues = []
    for title, files in titles.items():
        if len(files) > 1:
            issues.append(Issue(files[0], 0, "warning", "W004",
                              f"Duplicate title '{title}' in: {', '.join(files)}"))
    return issues


def main():
    parser = argparse.ArgumentParser(
        prog="mdlint",
        description="Lint markdown knowledge bases for consistency.",
    )
    parser.add_argument("directory", help="Directory to lint")
    parser.add_argument("--schema", nargs="*", default=[],
                       help="Required frontmatter fields (FIELD:TYPE pairs, e.g. type:str confidence:float)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--level", choices=["error", "warning", "info"], default="info",
                       help="Minimum issue level to report")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Parse schema
    schema = {}
    for s in args.schema:
        if ":" in s:
            name, typ = s.split(":", 1)
            schema[name] = typ
        else:
            schema[s] = "str"

    files = find_markdown_files(directory)
    if not files:
        print("No markdown files found.", file=sys.stderr)
        sys.exit(0)

    all_file_paths = {str(f.resolve()) for f in files}
    level_order = {"error": 0, "warning": 1, "info": 2}
    min_level = level_order[args.level]

    # Collect all issues
    all_issues = []
    for filepath in files:
        issues = check_file(filepath, directory, all_file_paths, schema)
        all_issues.extend(issues)

    all_issues.extend(check_orphans(files, directory))
    all_issues.extend(check_duplicate_titles(files, directory))

    # Filter by level
    all_issues = [i for i in all_issues if level_order[i.level] <= min_level]

    if args.json:
        output = [{"file": i.file, "line": i.line, "level": i.level,
                    "code": i.code, "message": i.message} for i in all_issues]
        print(json.dumps(output, indent=2))
    else:
        if not all_issues:
            print(f"✅ {len(files)} files, no issues found.")
            return

        # Group by file
        by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in all_issues:
            by_file[issue.file].append(issue)

        counts = Counter(i.level for i in all_issues)
        print(f"Found {len(all_issues)} issues in {len(by_file)} files "
              f"({counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings, "
              f"{counts.get('info', 0)} info)")
        print()

        emoji = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
        for filepath, issues in sorted(by_file.items()):
            print(f"  {filepath}")
            for issue in issues:
                line_info = f":{issue.line}" if issue.line > 0 else ""
                print(f"    {emoji[issue.level]} [{issue.code}] {issue.message}{line_info}")
            print()

    sys.exit(1 if counts.get("error", 0) > 0 else 0)


if __name__ == "__main__":
    main()
