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
from typing import Dict, List, Tuple


DEFAULT_EXCLUDES = {".git", "node_modules", ".obsidian", "__pycache__", "venv", ".venv"}
DEFAULT_EXTS = {".md", ".markdown", ".txt"}


def gather_file_tree(root: Path, exts=DEFAULT_EXTS, excludes=DEFAULT_EXCLUDES) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Return a mapping of path parts joined by '/' to aggregated size in bytes.

    Keys include directories and files. Directory keys end with '/'.
    """
    root = root.resolve()
    sizes: Dict[str, int] = {}
    # Map from file key (relative path) to file content (for .md files)
    contents: Dict[str, str] = {}

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
                    # Read text, but keep it reasonably sized for hover
                    txt = p.read_text(encoding='utf-8', errors='replace')
                    # Trim to first 2000 chars to avoid huge hover payloads
                    contents[file_key] = txt[:2000]
            except Exception:
                # ignore read errors
                pass
            # Add directory aggregated sizes
            for i in range(1, len(parts)):
                dir_key = "/".join(parts[:i]) + "/"
                sizes[dir_key] = sizes.get(dir_key, 0) + (size or 1)
            # Also add root directory bucket
            sizes["/"] = sizes.get("/", 0) + (size or 1)

    return sizes, contents


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
    sizes, contents = gather_file_tree(root, exts=exts, excludes=excludes)
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

    # Build hovertext for each node. For file leaf nodes, prefer markdown content if available.
    hovertexts: List[str] = []
    for node_id in ids:
        if node_id.endswith('/'):
            hovertexts.append('')
        else:
            txt = contents.get(node_id, '')
            if txt:
                # Replace newlines for HTML hover and shorten further if needed
                h = txt.replace('\n', '<br>')
                if len(h) > 1000:
                    h = h[:1000] + '...'
                hovertexts.append(h)
            else:
                hovertexts.append('')

    # Compute depth per node and map to colors.
    depths: List[int] = []
    for node_id in ids:
        if node_id == "/":
            d = 0
        else:
            # depth = number of separators; directories have trailing slash which counts
            d = node_id.count('/')
        depths.append(d)

    max_depth = max(depths) if depths else 1

    def depth_to_hex(depth: int) -> str:
        # Map depth to a hue along the circle; normalize by max_depth
        h = (depth / max_depth) if max_depth > 0 else 0.0
        # Use moderate saturation and value for pleasant colors
        r, g, b = colorsys.hsv_to_rgb(h * 0.75, 0.5, 0.95)
        return '#{0:02x}{1:02x}{2:02x}'.format(int(r * 255), int(g * 255), int(b * 255))

    colors: List[str] = [depth_to_hex(d) for d in depths]

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
        hovertext=hovertexts,
        hovertemplate='%{label}<br>%{hovertext}<extra></extra>',
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
