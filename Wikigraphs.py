#!/usr/bin/env python3
"""
Wikigraphs.py

Scan a workspace (Obsidian vault) and create Plotly Sunburst and Treemap
HTML files that visualize the file/directory structure and file sizes.

Usage:
    python3 Wikigraphs.py --root /path/to/vault --out graphs

Outputs (into out directory):
    - wikigraph_sunburst.html
    - wikigraph_treemap.html

Dependencies: plotly
"""
from __future__ import annotations
import argparse
import os
import plotly
from pathlib import Path
import colorsys
import hashlib
import re
from typing import Dict, List, Tuple


DEFAULT_EXCLUDES = {".git", "node_modules", ".obsidian", "__pycache__", "venv", ".venv"}
DEFAULT_EXTS = {".md", ".markdown", ".txt"}


def gather_file_tree(root: Path, exts=DEFAULT_EXTS, excludes=DEFAULT_EXCLUDES) -> Tuple[Dict[str, int], Dict[str, str], Dict[str, str]]:
    """Return a mapping of path parts joined by '/' to aggregated size in bytes.

    Keys include directories and files. Directory keys end with '/'.
    """
    root = root.resolve()
    sizes: Dict[str, int] = {}
    # Map from file key (relative path) to sanitized file content (for .md files)
    contents: Dict[str, str] = {}
    # Raw file text (un-sanitized) kept to detect special markers like '![['
    raw_contents: Dict[str, str] = {}

    for p in root.rglob("*"):
        # Skip excluded directories
        if any(part in excludes for part in p.parts):
            continue
        if p.is_file() and (not exts or p.suffix.lower() in exts):
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            # relative parts
            rel = p.relative_to(root)
            parts = list(rel.parts)
            # Add file node
            file_key = "/".join(parts)
            sizes[file_key] = size or 1
            # Read markdown content for hover text when available
            try:
                if p.suffix.lower() == '.md':
                    # Read text, sanitize markdown/obsidian syntax, and keep it reasonably sized
                    txt = p.read_text(encoding='utf-8', errors='replace')

                    def sanitize_markdown(s: str) -> str:
                        # Remove YAML frontmatter
                        s = re.sub(r'^---\n.*?\n---\n', '', s, flags=re.S)
                        # Handle Obsidian embeds first: ![[target|display]] -> display, ![[target]] -> target
                        s = re.sub(r'!\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', s)
                        s = re.sub(r'!\[\[([^\]]+)\]\]', r'\1', s)
                        # Obsidian wikilinks with display [[target|display]] -> display
                        s = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', s)
                        # Wikilinks [[target]] -> target
                        s = re.sub(r'\[\[([^\]]+)\]\]', r'\1', s)
                        # Markdown links [text](url) -> text
                        s = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', s)
                        # Remove heading markers at line starts (e.g. #, ##)
                        s = re.sub(r'(?m)^[ \t]*#{1,6}\s*', '', s)
                        # Strip emphasis and code markers *, _, `, ~
                        s = re.sub(r'[\*_`~]+', '', s)
                        # Collapse multiple blank lines
                        s = re.sub(r'\n{3,}', '\n\n', s)
                        # Trim whitespace
                        return s.strip()

                    clean = sanitize_markdown(txt)
                    # Store full sanitized content; trimming will be done at display time
                    contents[file_key] = clean
                    raw_contents[file_key] = txt
            except Exception:
                # ignore read errors
                pass
            # Add directory aggregated sizes
            for i in range(1, len(parts)):
                dir_key = "/".join(parts[:i]) + "/"
                sizes[dir_key] = sizes.get(dir_key, 0) + (size or 1)
            # Also add root directory bucket
            sizes["/"] = sizes.get("/", 0) + (size or 1)

    return sizes, contents, raw_contents


def build_plotly_lists(sizes: Dict[str, int], root_label: str = "root") -> Tuple[List[str], List[str], List[str], List[int]]:
    """Convert sizes mapping into Plotly ids, labels, parents, values lists.

    Returns:
      ids: unique ids for nodes (use canonical keys)
      labels: human-friendly display names
      parents: parent ids (empty string for root)
      values: numeric values
    """
    ids: List[str] = []
    labels: List[str] = []
    parents: List[str] = []
    values: List[int] = []

    # Sort to get deterministic output (shorter keys first)
    items = sorted(sizes.items(), key=lambda kv: (kv[0].count('/'), kv[0]))

    for key, val in items:
        # id is the canonical key
        node_id = key
        # label is basename (for directories show directory name)
        if key == "/":
            label = root_label
            parent = ""
        else:
            # strip trailing slash for name
            stripped = key.rstrip('/')
            parts = stripped.split('/')
            label = parts[-1]
            if len(parts) == 1:
                parent = "/"
            else:
                parent = "/".join(parts[:-1]) + "/"

        ids.append(node_id)
        labels.append(label)
        parents.append(parent)
        values.append(int(val))

    return ids, labels, parents, values


def make_graphs(root: Path, outdir: Path, exts=DEFAULT_EXTS, excludes=DEFAULT_EXCLUDES, mode: str = 'size', embed_js: bool = False) -> None:
    # mode: 'size' uses file byte sizes, 'count' counts each file as 1
    sizes, contents, raw_contents = gather_file_tree(root, exts=exts, excludes=excludes)

    # Auto-create simple Expanded megafiles: for any source whose basename starts with 'Expanded',
    # write a file named 'simple_Expanded_Megafile.md' in the same directory containing the
    # sanitized content with embeds inlined (using the sanitized contents index).
    try:
        for file_key, sanitized in list(contents.items()):
            # basename without trailing slash
            base = Path(file_key).name
            if not base.lower().startswith('expanded'):
                continue

            # helper to find sanitized content for a target name
            def find_sanitized_for(target: str) -> str:
                # Try direct matches: exact key
                for k, v in contents.items():
                    if k.lower() == target.lower():
                        return v
                # Try with .md suffix
                if not target.lower().endswith('.md'):
                    for k, v in contents.items():
                        if k.lower().endswith(target.lower() + '.md'):
                            return v
                # Match by filename suffix
                for k, v in contents.items():
                    if k.lower().endswith('/' + target.lower()) or k.lower().endswith(target.lower()):
                        return v
                return ''

            raw = raw_contents.get(file_key, '')

            def embed_repl(m: re.Match) -> str:
                target = m.group(1).strip()
                if '|' in target:
                    target = target.split('|', 1)[0].strip()
                found = find_sanitized_for(target)
                if found:
                    return '\n' + found + '\n'
                return target

            resolved = re.sub(r'!\[\[([^\]]+)\]\]', embed_repl, raw)
            final_text = resolved.strip() or sanitized

            # write into the same directory as the source file
            src_path = root.joinpath(file_key)
            out_dir = src_path.parent if src_path.parent.exists() else root
            out_path = out_dir / 'simple_Expanded_Megafile.md'
            try:
                out_path.write_text(final_text + '\n', encoding='utf-8')
            except Exception:
                # ignore write errors
                pass
    except Exception:
        # non-fatal; continue
        pass
    # Ensure there's at least a root node
    if not sizes:
        sizes = {"/": 1}
    else:
        sizes.setdefault("/", sum(v for k, v in sizes.items() if not k.endswith('/')) or 1)

    # If count mode, convert file entries to 1 and re-aggregate directories
    if mode == 'count':
        new_sizes: Dict[str, int] = {}
        for k, v in sizes.items():
            # files (no trailing slash) => 1
            if k.endswith('/'):
                # keep directories for now
                new_sizes[k] = new_sizes.get(k, 0)
            else:
                new_sizes[k] = 1
                # add counts to parent directories
                parts = k.split('/')
                for i in range(1, len(parts)):
                    dir_key = '/'.join(parts[:i]) + '/'
                    new_sizes[dir_key] = new_sizes.get(dir_key, 0) + 1
                new_sizes['/'] = new_sizes.get('/', 0) + 1
        sizes = new_sizes

    ids, labels, parents, values = build_plotly_lists(sizes, root_label=root.name)

    # Helper to remove backlink collection blocks from files that declare #collectionfile
    def remove_backlink_collection(s: str) -> str:
        if not s:
            return s
        if '#collectionfile' not in s.lower():
            return s
        # Remove headings that mention 'backlink' and the content under them until next heading
        s = re.sub(r'(?mi)^\s*#{1,6}.*backlink.*\n(?:^(?!\s*#{1,6}).*\n?)*', '', s)
        # Remove plain 'Backlinks' section (no heading) and following list-like lines
        s = re.sub(r'(?mi)^\s*backlinks\s*[:\-]?\s*\n(?:^(?!\s*#{1,6}).*\n?)*', '', s)
        # Remove standalone wikilink list items (common backlink lists)
        s = re.sub(r'(?m)^[ \t]*[-*]\s*\[\[.*?\]\].*\n?', '', s)
        s = re.sub(r'(?m)^[ \t]*\[\[.*?\]\].*\n?', '', s)
        return s.strip()

    # Helper to replace markdown tables with a compact summary representation
    def replace_tables(s: str) -> str:
        if not s:
            return s
        lines = s.splitlines()
        out_lines: List[str] = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            # detect potential table: line contains '|' and next line is a separator like '|---|:---|'
            if '|' in ln and i + 1 < len(lines):
                sep = lines[i + 1]
                if re.match(r'^\s*\|?\s*[:\-]+\s*(\|\s*[:\-]+\s*)*\|?\s*$', sep):
                    # collect data rows after separator
                    header = ln
                    j = i + 2
                    data_rows: List[str] = []
                    while j < len(lines) and '|' in lines[j] and lines[j].strip() != '':
                        data_rows.append(lines[j])
                        j += 1
                    # extract header cells
                    header_cells = [c.strip() for c in re.split(r'\s*\|\s*', header.strip().strip('|')) if c.strip()]
                    # helper to sanitize inline markdown in headers/cells
                    def sanitize_inline(cell: str) -> str:
                        if not cell:
                            return ''
                        # wikilinks [[target|display]] or [[target]] -> display/target
                        cell = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', cell)
                        cell = re.sub(r'\[\[([^\]]+)\]\]', r'\1', cell)
                        # markdown links [text](url) -> text
                        cell = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cell)
                        # remove emphasis and code markers
                        cell = re.sub(r'[\*_`~]+', '', cell)
                        # collapse multiple spaces
                        cell = re.sub(r'\s+', ' ', cell)
                        return cell.strip()

                    if header_cells:
                        # produce a cleaned, full table representation preserving rows
                        clean_header = ' | '.join(sanitize_inline(h) for h in header_cells)
                        out_lines.append(clean_header)
                        # append each data row, cleaned
                        for row in data_rows:
                            row_text = row.strip().strip('|')
                            row_cells = [c.strip() for c in re.split(r'\s*\|\s*', row_text)]
                            clean_row = ' | '.join(sanitize_inline(c) for c in row_cells)
                            out_lines.append(clean_row)
                    else:
                        # no headers found; include raw data rows cleaned
                        for row in data_rows:
                            row_text = row.strip()
                            out_lines.append(sanitize_inline(row_text))
                    i = j
                    continue
            out_lines.append(ln)
            i += 1
        return '\n'.join(out_lines)

    # Build hovertext for each node. For file leaf nodes, prefer markdown content if available.
    hovertexts: List[str] = []
    for node_id in ids:
        if node_id.endswith('/'):
            hovertexts.append('')
        else:
            txt = contents.get(node_id, '')
            if txt:
                # Remove backlink collections and collapse tables first, then convert newlines
                cleaned = replace_tables(remove_backlink_collection(txt))
                h = cleaned.replace('\n', '<br>')
                if len(h) > 1000:
                    h = h[:1000] + '...'
                hovertexts.append(h)
            else:
                hovertexts.append('')

    # Create a treemap-specific hovertext that only shows the first couple of rows
    treemap_hovertexts: List[str] = []
    for node_id in ids:
        if node_id.endswith('/'):
            treemap_hovertexts.append('')
            continue
        raw = contents.get(node_id, '')
        if not raw:
            treemap_hovertexts.append('')
            continue
        # Pre-process to remove backlink collections and collapse tables
        pre = replace_tables(remove_backlink_collection(raw))
        # take first 2 non-empty lines
        lines = pre.splitlines()
        first_lines: List[str] = []
        for ln in lines:
            t = ln.strip()
            if not t:
                continue
            first_lines.append(t)
            if len(first_lines) >= 2:
                break
        if not first_lines and lines:
            first_lines = [lines[0].strip()]
        h = '<br>'.join(first_lines)
        if len(lines) > len(first_lines):
            h = h + '...'
        treemap_hovertexts.append(h)

    # Assign a per-node color derived from a stable MD5 hash of the node id.
    # This produces 'randomized' colors while remaining deterministic across runs.
    def id_to_hex(node_id: str) -> str:
        hval = int(hashlib.md5(node_id.encode('utf-8')).hexdigest()[:8], 16) / 0xffffffff
        # scramble the hue using the golden ratio to avoid clustering
        hue = (hval * 0.61803398875) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
        return '#{0:02x}{1:02x}{2:02x}'.format(int(r * 255), int(g * 255), int(b * 255))

    colors: List[str] = [id_to_hex(n) for n in ids]

    # Prepare short cell text for treemap nodes (sanitized and trimmed)
    cell_texts: List[str] = []
    for node_id in ids:
        txt = ''
        if not node_id.endswith('/'):
            sanitized = contents.get(node_id, '')
            raw = raw_contents.get(node_id, '')
            if sanitized:
                # If the raw file contains embed markers like ![[target]] we should
                # inline the referenced file's full sanitized content in place of the token.
                if raw and '![[' in raw:
                    # helper to find sanitized content for a target name
                    def find_sanitized_for(target: str) -> str:
                        # Try direct matches: exact key
                        for k, v in contents.items():
                            if k.lower() == target.lower():
                                return v
                        # Try with/without .md
                        if not target.lower().endswith('.md'):
                            for k, v in contents.items():
                                if k.lower().endswith(target.lower() + '.md'):
                                    return v
                        # Match by filename suffix
                        for k, v in contents.items():
                            if k.lower().endswith('/' + target.lower()) or k.lower().endswith(target.lower()):
                                return v
                        return ''

                    # replace embeds with the sanitized content of the referenced file
                    def embed_repl(m: re.Match) -> str:
                        target = m.group(1).strip()
                        # strip optional display part if provided (target|display)
                        if '|' in target:
                            target = target.split('|', 1)[0].strip()
                        found = find_sanitized_for(target)
                        if found:
                            return '\n' + found + '\n'
                        # fallback: show the target name
                        return target

                    resolved = re.sub(r'!\[\[([^\]]+)\]\]', embed_repl, raw)
                    # Prefer resolved content if it produced additional material
                    if resolved and resolved != raw:
                        resolved_clean = replace_tables(remove_backlink_collection(resolved))
                        t = re.sub(r'\n+', '<br>', resolved_clean.strip())
                    else:
                        # Fallback to sanitized content for display
                        san_clean = replace_tables(remove_backlink_collection(sanitized))
                        t = san_clean.replace('\n', '<br>')
                    txt = t
                else:
                    san_clean = replace_tables(remove_backlink_collection(sanitized))
                    t = san_clean.replace('\n', '<br>')
                    # Do not truncate treemap cell text — show full sanitized content
                    txt = t
        cell_texts.append(txt)

    # Lazy import plotly
    try:
        import plotly.graph_objects as go
    except Exception as e:
        raise RuntimeError("plotly is required; install with: pip install plotly") from e

    outdir.mkdir(parents=True, exist_ok=True)

    sun = go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="total",
        hovertext=hovertexts,
        hovertemplate='%{label}<br>%{hovertext}<extra></extra>',
        marker=dict(colors=colors, line=dict(width=0.5, color='white')),
    )
    fig_sun = go.Figure(sun)
    fig_sun.update_layout(margin=dict(t=10, l=10, r=10, b=10))
    sun_path = outdir / "wikigraph_sunburst.html"
    fig_sun.write_html(str(sun_path), include_plotlyjs='cdn' if not embed_js else True)

    tre = go.Treemap(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="total",
        hovertext=treemap_hovertexts,
        hovertemplate='%{label}<br>%{hovertext}<extra></extra>',
        text=cell_texts,
    texttemplate='%{label}<br>%{text}<extra></extra>',
    textfont=dict(size=12),
        marker=dict(colors=colors, line=dict(width=0.5, color='white')),
    )
    fig_treemap = go.Figure(tre)
    fig_treemap.update_layout(margin=dict(t=10, l=10, r=10, b=10))
    tre_path = outdir / "wikigraph_treemap.html"
    fig_treemap.write_html(str(tre_path), include_plotlyjs='cdn' if not embed_js else True)

    print(f"Wrote: {sun_path}\nWrote: {tre_path}")

    # Additional charts: top-N files, top-N directories, file-size histogram
    try:
        import plotly.express as px
    except Exception:
        px = None

    # Prepare a simple list of file entries (exclude directories)
    file_items = [(k, v) for k, v in sizes.items() if not k.endswith('/')]

    # Top N files
    def write_top_files(n: int = 20):
        top = sorted(file_items, key=lambda kv: kv[1], reverse=True)[:n]
        if not top:
            return
        names = [k for k, _ in top]
        vals = [v for _, v in top]
        if px:
            fig = px.bar(x=vals, y=names, orientation='h', labels={'x': 'Value', 'y': 'File'}, title=f'Top {n} files by {"size" if mode=="size" else "count"}')
            fig.update_layout(yaxis={'automargin': True}, margin=dict(t=30, l=200))
            out = outdir / f"wikigraph_top_{n}_files.html"
            fig.write_html(str(out), include_plotlyjs='cdn' if not embed_js else True)
        else:
            # Fallback: basic text file
            out = outdir / f"wikigraph_top_{n}_files.txt"
            out.write_text('\n'.join(f"{v}\t{k}" for k, v in top))

    # Top N directories (directories end with '/')
    def write_top_dirs(n: int = 20):
        dirs = [(k, v) for k, v in sizes.items() if k.endswith('/')]
        top = sorted(dirs, key=lambda kv: kv[1], reverse=True)[:n]
        if not top:
            return
        names = [k for k, _ in top]
        vals = [v for _, v in top]
        if px:
            fig = px.bar(x=vals, y=names, orientation='h', labels={'x': 'Value', 'y': 'Directory'}, title=f'Top {n} directories by {"size" if mode=="size" else "count"}')
            fig.update_layout(yaxis={'automargin': True}, margin=dict(t=30, l=200))
            out = outdir / f"wikigraph_top_{n}_dirs.html"
            fig.write_html(str(out), include_plotlyjs='cdn' if not embed_js else True)
        else:
            out = outdir / f"wikigraph_top_{n}_dirs.txt"
            out.write_text('\n'.join(f"{v}\t{k}" for k, v in top))

    # Histogram of file sizes
    def write_histogram(bins: int = 50):
        vals = [v for k, v in file_items if v > 0]
        if not vals:
            return
        if px:
            import numpy as _np
            # Use log-scale bins for readability when sizes vary widely
            log_vals = _np.log10(_np.array(vals))
            fig = px.histogram(x=log_vals, nbins=bins, labels={'x': 'log10(Value)'}, title='File size distribution (log10 scale)')
            fig.update_layout(margin=dict(t=30, l=10, r=10, b=10))
            out = outdir / "wikigraph_file_size_histogram.html"
            fig.write_html(str(out), include_plotlyjs='cdn' if not embed_js else True)
        else:
            out = outdir / "wikigraph_file_size_histogram.txt"
            out.write_text('\n'.join(str(v) for v in vals))

    # Write additional charts
    write_top_files(20)
    write_top_dirs(20)
    write_histogram(50)


def parse_args():
    p = argparse.ArgumentParser(description="Create wikigraph sunburst and treemap HTML files")
    p.add_argument("--root", default='.', help="Path to the vault root")
    p.add_argument("--out", default='graphs', help="Output directory for HTML files")
    p.add_argument("--ext", action='append', help="Extensions to include (e.g. .md). Can be provided multiple times")
    p.add_argument("--exclude", action='append', help="Directory names to exclude (name only). Can be provided multiple times")
    p.add_argument("--embed", action='store_true', help="Embed Plotly JS into the HTML (works offline)")
    p.add_argument("--mode", choices=['size', 'count'], default='size', help="Use file size (bytes) or file count for values")
    return p.parse_args()


def main():
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    outdir = Path(args.out).expanduser().resolve()
    exts = DEFAULT_EXTS if not args.ext else {e if e.startswith('.') else '.' + e for e in args.ext}
    excludes = DEFAULT_EXCLUDES.union(set(args.exclude or []))
    print(f"Scanning: {root}\nExtensions: {sorted(exts)}\nExcludes: {sorted(excludes)}\nMode: {args.mode}\nEmbed JS: {args.embed}\nWriting to: {outdir}")
    make_graphs(root, outdir, exts=exts, excludes=excludes, mode=args.mode, embed_js=args.embed)


if __name__ == '__main__':
    main()
