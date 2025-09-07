from pathlib import Path
import argparse
import os
import re
import sys
from shutil import copy2
from typing import Iterator, List, Optional, Sequence, Tuple
import fnmatch

DEFAULT_EXCLUDES = {".git", "node_modules", ".obsidian", "__pycache__", "venv", ".venv", "DMs Part"}

# -------- Color helpers --------
class Colors:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def colorize(enabled: bool, text: str, *effects: str) -> str:
    if not enabled or not effects:
        return text
    return "".join(effects) + text + Colors.RESET


def iter_files(
    roots: Sequence[Path],
    include_globs: Sequence[str],
    exclude_dirs: Sequence[str],
    use_default_excludes: bool,
    follow_symlinks: bool,
) -> Iterator[Path]:
    """Yield files under roots honoring include patterns and directory excludes."""
    # Normalize to names (not paths) for exclude dirs
    excludes = set(exclude_dirs)
    if use_default_excludes:
        excludes |= DEFAULT_EXCLUDES

    for root in roots:
        if root.is_file():
            # For single files, still apply include_globs if provided
            rel = root.name
            if include_globs:
                if not any(fnmatch.fnmatch(rel, patt) or fnmatch.fnmatch(str(root), patt) for patt in include_globs):
                    continue
            yield root
            continue

        for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            # Prune excluded directories
            pruned = []
            for d in list(dirnames):
                if d in excludes:
                    pruned.append(d)
            for d in pruned:
                dirnames.remove(d)

            for fname in filenames:
                fpath = Path(dirpath) / fname
                if include_globs:
                    # Test both path relative to root and absolute string
                    # Build a path relative to the starting root for matching with **
                    try:
                        rel = str(fpath.relative_to(root))
                    except Exception:
                        rel = str(fpath)
                    if not any(fnmatch.fnmatch(rel, patt) or fnmatch.fnmatch(str(fpath), patt) for patt in include_globs):
                        continue
                yield fpath


def should_process_file(path: Path, exts: Sequence[str]) -> bool:
    if not exts:
        return True
    if not path.is_file():
        return False
    return path.suffix.lower() in {e.lower() for e in exts}


def load_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Not a UTF-8 text file
        return None
    except Exception:
        return None


def write_text_with_backup(path: Path, content: str, backup_suffix: Optional[str], color: bool) -> None:
    if backup_suffix:
        try:
            copy2(path, Path(str(path) + backup_suffix))
        except Exception as e:
            # Warning printed in yellow if color is enabled
            print(colorize(color, f"[warn] Failed to create backup for {path}: {e}", Colors.YELLOW), file=sys.stderr)
    path.write_text(content, encoding="utf-8")


# -------- Append String to Files --------
def append_string_to_files(
    files: Sequence[Path],
    append_str: str,
    dry_run: bool,
    backup_suffix: Optional[str],
    color: bool,
    compact: bool,
) -> int:
    changed_files = 0
    for f in files:
        text = load_text(f)
        if text is None:
            continue
        # Only append if not already present at the end
        if text.rstrip().endswith(append_str):
            if compact:
                print(f"{colorize(color, '[SKIP]', Colors.GRAY)} {colorize(color, str(f), Colors.DIM)} (already present)")
            else:
                print(f"[skip] {f} (already present)")
            continue
        new_text = text
        if not text.endswith("\n"):
            new_text += "\n"
        new_text += append_str + "\n"
        changed_files += 1
        if compact:
            tag = "DRY" if dry_run else "WRITE"
            tag_color = Colors.CYAN if dry_run else Colors.GREEN
            print(f"{colorize(color, '[' + tag + ']', tag_color)} {colorize(color, str(f), Colors.BOLD)} (appended)")
        else:
            if dry_run:
                print(f"[dry-run] {f} -> appended string")
            else:
                print(f"[write] {f} -> appended string")
        if not dry_run:
            write_text_with_backup(f, new_text, backup_suffix, color)
    return changed_files


def make_replacer(
    needle: str,
    replacement: Optional[str],
    case_sensitive: bool,
    bracket_mode: bool,
) -> Tuple[re.Pattern, str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    escaped = re.escape(needle)

    if bracket_mode:
        # Match the needle anywhere, but only wrap if neighbors are not letters
        pattern = re.compile(escaped, flags)

        def repl_func(match):
            s = match.string
            start, end = match.start(), match.end()
            # Check left neighbor
            if start > 0 and s[start-1].isalpha():
                return match.group(0)
            # Check right neighbor
            if end < len(s) and s[end].isalpha():
                return match.group(0)
            # Scan left for [[ and right for ]]
            left = s.rfind('[[', 0, start)
            right = s.find(']]', end)
            # If there is a [[ before and a ]] after, and no ]] between [[ and match, and no [[ between match and ]], it's inside a wiki-link
            if left != -1 and right != -1:
                # Ensure there is no ]] between [[ and match
                if s.find(']]', left, start) == -1 and s.find('[[', end, right) == -1:
                    return match.group(0)  # Already inside a link
            return f"[[{match.group(0)}]]"

        return pattern, repl_func

    # Normal replacement mode
    pattern = re.compile(escaped, flags)
    if replacement is None:
        # Should never happen if args are validated, but guard anyway.
        replacement = ""
    return pattern, replacement


def process_file(
    path: Path,
    pattern: re.Pattern,
    repl: str,
) -> Tuple[int, Optional[str]]:
    text = load_text(path)
    if text is None:
        return 0, None
    # If repl is a function, use it; else, use as string
    if callable(repl):
        new_text, n = pattern.subn(repl, text)
    else:
        new_text, n = pattern.subn(repl, text)
    if n == 0:
        return 0, None
    return n, new_text


# ---------- Backlink Collection Utilities ----------

COLL_BEGIN_TMPL = "<!-- BEGIN-AUTO-COLLECTION:{label} -->"
COLL_END = "<!-- END-AUTO-COLLECTION -->"

def best_relative_without_suffix(path: Path, roots: Sequence[Path]) -> str:
    """Return the shortest nice relative path (POSIX) without file suffix."""
    candidates: List[str] = []
    for r in roots:
        try:
            rel = path.relative_to(r)
            candidates.append(str(rel))
        except Exception:
            pass
    if not candidates:
        candidates.append(str(path))
    # Pick the shortest string representation
    chosen = min(candidates, key=len)
    # Drop suffix and normalize separators
    return str(Path(chosen).with_suffix("")).replace("\\", "/")


def gather_backlinks(
    label: str,
    candidate_files: Sequence[Path],
    exclude_path: Path,
) -> List[Path]:
    """Return files that contain a wiki-link to the label (case-insensitive)."""
    # Pattern matches [[...]] links, capturing the link target (before | or # or ]])
    link_pattern = re.compile(r"\[\[\s*([^\]|#]+)", re.IGNORECASE)
    results: List[Path] = []
    for f in candidate_files:
        if f == exclude_path:
            continue
        text = load_text(f)
        if text is None:
            continue
        # Find all wiki-links in the file
        found = False
        for m in link_pattern.finditer(text):
            link_target = m.group(1).strip()
            # Compare as whole word (case-insensitive)
            if link_target.lower() == label.lower():
                found = True
                break
        if found:
            results.append(f)
    # Sort by filename (case-insensitive), stable
    results.sort(key=lambda p: str(p).lower())
    return results


def update_collection_block(
    target_file: Path,
    roots: Sequence[Path],
    backlinks: List[Path],
    label: str,
    dry_run: bool,
    backup_suffix: Optional[str],
    color: bool,
    compact: bool,
) -> Tuple[bool, int]:
    """Insert or replace the auto-collection block inside target_file. Returns (changed, count)."""
    begin = COLL_BEGIN_TMPL.format(label=label)
    end = COLL_END

    # # Build the new block text
    lines = [begin, "## Backlinks", ""]

    # Add ASCII graph to the markdown block, centered on cwd and only showing folders/files with backlinks
    from collections import defaultdict
    cwd = os.path.relpath(os.getcwd(), str(roots[0]) if roots else os.getcwd())
    # Build a tree of all backlink paths
    tree = defaultdict(dict)
    for p in backlinks:
        rel = os.path.relpath(str(p), str(roots[0]) if roots else os.getcwd())
        parts = rel.split(os.sep)
        d = tree
        for part in parts:
            if part not in d:
                d[part] = {}
            d = d[part]
    def print_tree(d, prefix="", is_last=True):
        items = list(d.items())
        for idx, (name, subtree) in enumerate(items):
            connector = "└── " if idx == len(items)-1 else "├── "
            # Only bracket files (leaf nodes), not folders
            if subtree:
                lines.append(f"{prefix}{connector}{name}")
                extension = "    "  # Always use spaces, no vertical lines
                print_tree(subtree, prefix + extension, True)
            else:
                lines.append(f"{prefix}{connector}[[{name}]]")
    lines.append(f"  {cwd}/")
    print_tree(tree, prefix="  ")
    lines.append("")  # trailing newline
    lines.append(end)
    lines.append("")  # trailing newline
    block_text = "\n".join(lines)


    # Delete the old file if it exists before writing a new one
    if target_file.exists():
        try:
            target_file.unlink()
        except Exception as e:
            print(colorize(color, f"[warn] Failed to delete old file {target_file}: {e}", Colors.YELLOW), file=sys.stderr)
        content = ""
    else:
        content = ""

    # Replace or append the block
    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    if pattern.search(content):
        new_content = pattern.sub(block_text, content, count=1)
    else:
        # Ensure final newline then append
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + block_text

    changed = new_content != content

    if changed:
        if compact:
            print(
                f"{colorize(color, '[COLL]', Colors.MAGENTA)} "
                f"{colorize(color, str(target_file), Colors.BOLD)} "
                f"{colorize(color, '(' + str(len(backlinks)) + ')', Colors.GRAY)}"
            )
        else:
            print(f"[collect] {target_file} <- {len(backlinks)} backlink(s)")
        if not dry_run:
            write_text_with_backup(target_file, new_content, backup_suffix, color)

    else:
        if compact:
            print(
                f"{colorize(color, '[SKIP]', Colors.GRAY)} "
                f"{colorize(color, str(target_file), Colors.DIM)} "
                f"{colorize(color, '(' + str(len(backlinks)) + ')', Colors.GRAY)}"
            )
        else:
            print(f"[skip] {target_file} (no changes)")

    return changed, len(backlinks)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recursively bulk find & replace text in files (safe for Obsidian vaults and repos)."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Root paths to scan. Defaults to current directory.",
    )
    parser.add_argument(
        "--find",
        help="Text to search for. Case-insensitive by default (use --case-sensitive to toggle).",
    )
    parser.add_argument(
        "--replace",
        help="Replacement text. Ignored if bracketing mode (-b) is enabled.",
    )
    parser.add_argument(
        "--ext",
        nargs="*",
        default=[],
        help="File extensions to include (e.g., --ext .md .txt). If omitted, all files are considered.",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        default=[],
        help='Glob patterns to include (e.g., --include \"**/*.md\" \"**/*.txt\").',
    )
    parser.add_argument(
        "--exclude-dir",
        nargs="*",
        default=[],
        help="Directory names to exclude (in addition to defaults).",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help=f"Do not exclude default directories: {', '.join(sorted(DEFAULT_EXCLUDES))}.",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Make search case-sensitive (default is case-insensitive).",
    )
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Descend into symlinked directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    parser.add_argument(
        "--backup",
        default=None,
        help="Backup suffix to use when writing changes (e.g., .bak). Backup created only if a file is modified.",
    )
    parser.add_argument(
        "-b",
        "--bracket",
        action="store_true",
        help="Bracketing mode: wrap matches with [[...]] if not already bracketed. Ignores --replace.",
    )
    # NEW: compact/color flags
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Short, color-coded output (does not change functionality).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors even if the terminal supports them.",
    )
    # NEW: collection files
    parser.add_argument(
        "--collectionfile",
        action="append",
        default=[],
        help=(
            "Path to a target note to maintain a backlinks list inside. "
            "Label inferred from file name (stem); e.g., Action.md collects files containing [[Action]]. "
            "Use multiple times for multiple targets."
        ),
    )

    # NEW: append string to end of files
    parser.add_argument(
        "--append",
        help="String to append to the end of each file (e.g., --append '[[Earthbending]]').",
    )

    args = parser.parse_args(argv)

    # Validation: allow either find/replace/bracket OR collection mode (or both)

    if not args.collectionfile and not args.append:
        if not args.find:
            parser.error("--find is required unless --collectionfile or --append is used.")
        if not args.bracket and args.replace is None:
            parser.error("--replace is required unless bracketing mode (-b/--bracket) is used.")
    else:
        if args.find and (not args.bracket) and (args.replace is None):
            parser.error("--replace is required when using --find (unless -b/--bracket).")

    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # Decide on color usage
    color_enabled = sys.stdout.isatty() and (os.environ.get("NO_COLOR") is None) and (not args.no_color)

    roots = [Path(p).resolve() for p in args.paths]

    # Candidate files to scan
    files_iter = iter_files(
        roots=roots,
        include_globs=args.include,
        exclude_dirs=args.exclude_dir,
        use_default_excludes=not args.no_default_excludes,
        follow_symlinks=args.follow_symlinks,
    )
    candidate_files = [p for p in files_iter if should_process_file(p, args.ext)]

    total_changes = 0
    changed_files: List[Tuple[Path, int]] = []

    # ---------- Append String Pipeline ----------
    if args.append:
        appended = append_string_to_files(
            candidate_files,
            args.append,
            args.dry_run,
            args.backup,
            color_enabled,
            args.compact,
        )
        if args.compact:
            print(f"{colorize(color_enabled, 'Summary:', Colors.BOLD)} {colorize(color_enabled, 'APPEND', Colors.BLUE if args.dry_run else Colors.GREEN)} files={len(candidate_files)} appended={appended}")
        else:
            print(f"\n=== Summary (Append) ===")
            print(f"Files scanned: {len(candidate_files)}")
            print(f"Files appended: {appended}")
        # If only append was requested, skip the rest
        if not (args.find or args.collectionfile):
            return 0

    # ---------- Find/Replace pipeline ----------
    if args.find:
        pattern, repl = make_replacer(
            needle=args.find,
            replacement=args.replace,
            case_sensitive=args.case_sensitive,
            bracket_mode=args.bracket,
        )

        for f in candidate_files:
            n, new_text = process_file(f, pattern, repl)
            if n > 0 and new_text is not None:
                changed_files.append((f, n))
                total_changes += n
                if args.compact:
                    tag = "DRY" if args.dry_run else "WRITE"
                    tag_color = Colors.CYAN if args.dry_run else Colors.GREEN
                    print(
                        f"{colorize(color_enabled, '[' + tag + ']', tag_color)} "
                        f"{colorize(color_enabled, str(f), Colors.BOLD)} "
                        f"{colorize(color_enabled, '(' + str(n) + ')', Colors.GRAY)}"
                    )
                else:
                    if args.dry_run:
                        print(f"[dry-run] {f} -> {n} replacement(s)")
                    else:
                        print(f"[write] {f} -> {n} replacement(s)")
                if not args.dry_run:
                    write_text_with_backup(f, new_text, args.backup, color_enabled)

    # ---------- Collection pipeline ----------
    collections_updated = 0
    collections_items = 0
    backlink_graph = []  # For ASCII graph output
    if args.collectionfile:
        for t in args.collectionfile:
            target = Path(t).resolve()
            label = target.stem
            backlinks = gather_backlinks(label, candidate_files, exclude_path=target)
            changed, count = update_collection_block(
                target, roots, backlinks, label, args.dry_run, args.backup, color_enabled, args.compact
            )
            if changed:
                collections_updated += 1
            collections_items += count
            # Collect for ASCII graph
            backlink_graph.append((label, [best_relative_without_suffix(p, roots) for p in backlinks]))

    # ---------- Summary ----------
    if args.compact:
        parts = [
            colorize(color_enabled, "Summary:", Colors.BOLD),
        ]
        if args.find:
            mode = "DRY" if args.dry_run else "APPLIED"
            parts.append(colorize(color_enabled, mode, Colors.BLUE if args.dry_run else Colors.GREEN))
            parts += [
                f"files={len(candidate_files)}",
                f"changed={len(changed_files)}",
                f"repl={total_changes}",
            ]
            if not args.dry_run and args.backup:
                parts.append(f"backup={args.backup}")
        if args.collectionfile:
            parts += [
                f"collections={collections_updated}/{len(args.collectionfile)}",
                f"items={collections_items}",
            ]
        print(" ".join(parts))
    else:
        if args.find:
            mode = "DRY-RUN (no writes)" if args.dry_run else "APPLIED (writes performed)"
            print("\n=== Summary (Find/Replace) ===")
            print(f"Mode: {mode}")
            print(f"Files scanned: {len(candidate_files)}")
            print(f"Files changed: {len(changed_files)}")
            print(f"Total replacements: {total_changes}")
            if not args.dry_run and args.backup:
                print(f"Backup suffix used: {args.backup}")
            if not changed_files:
                print("No changes made.")
            else:
                # Show a short top-10 preview of changed files
                print("\nChanged files (up to 10 shown):")
                for f, n in changed_files[:10]:
                    print(f"  {f} ({n})")
                if len(changed_files) > 10:
                    print(f"  ... and {len(changed_files) - 10} more")
        if args.collectionfile:
            print("\n=== Summary (Collections) ===")
            print(f"Targets updated: {collections_updated}/{len(args.collectionfile)}")
            print(f"Total backlinks enumerated: {collections_items}")
            if not args.find:
                # If only collections were requested, still show scanned file count
                print(f"Files scanned: {len(candidate_files)}")


    # ---------- ASCII Graph Output for Collections ----------
    if args.collectionfile and backlink_graph:
        from collections import defaultdict
        print("\n=== Backlink Graph (ASCII) ===")
        cwd = os.path.relpath(os.getcwd(), str(roots[0]) if roots else os.getcwd())
        for label, links in backlink_graph:
            # Build tree for this label
            tree = defaultdict(dict)
            for link in links:
                rel = os.path.relpath(str(link), str(roots[0]) if roots else os.getcwd())
                parts = rel.split(os.sep)
                d = tree
                for part in parts:
                    if part not in d:
                        d[part] = {}
                    d = d[part]
            def print_tree(d, prefix="", is_last=True):
                items = list(d.items())
                for idx, (name, subtree) in enumerate(items):
                    connector = "└── " if idx == len(items)-1 else "├── "
                    # Only bracket files (leaf nodes), not folders
                    if subtree:
                        print(f"{prefix}{connector}{name}")
                        extension = "    "  # Always use spaces, no vertical lines
                        print_tree(subtree, prefix + extension, True)
                    else:
                        print(f"{prefix}{connector}[[{name}]]")
            print_tree(tree, prefix="  ")
        print()
    return 0


if __name__ == "__main__":
    # Avoid auto-running when executed inside Jupyter/IPython during code generation.
    # In normal CLI use (`python bulk_find_replace.py ...`), this condition will be False.
    is_ipy = os.path.basename(sys.argv[0]) in {"ipykernel_launcher.py", "KernelApp.py"}
    if not is_ipy:
        try:
            raise SystemExit(main())
        except KeyboardInterrupt:
            print("\nAborted by user.", file=sys.stderr)
            raise SystemExit(130)
