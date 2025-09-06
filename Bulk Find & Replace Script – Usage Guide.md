# Bulk Find & Replace Script – Usage Guide

This script is in the root folder. It recursively scans a folder tree and performs text find-and-replace operations on matching files. It is designed to be safe, flexible, and especially useful for managing Obsidian vaults or large code/text repositories.

---

## 🔍 Preview Changes

Run in **dry-run mode** to see what would be changed without writing any files:

```bash
python bulk_find_replace.py --find "Old" --replace "New" --ext .md .txt --dry-run
```

- `--find` → text string to search for.
    
- `--replace` → text string to replace with.
    
- `--ext` → limit to files with specified extensions.
    
- `--dry-run` → shows affected files and replacement counts, no writes.
    

---

## 💾 Apply Changes with Backups

Make the replacements and create backups of each modified file:

```bash
python bulk_find_replace.py --find "Old" --replace "New" --ext .md .txt --backup .bak
```

- `--backup .bak` → creates a copy of the original file before writing changes (e.g., `file.md.bak`).
    

---

## 🗂️ Bracketing Mode (-b)

A special **bracketing flag** automatically wraps search matches with `[[` and `]]` if they are not already surrounded:

```bash
python bulk_find_replace.py --find "Spirit" -b --ext .md
```

- Example: `Spirit` → `[[Spirit]]`
    
- If the word is already bracketed (`[[Spirit]]`), it will be left untouched.
    

Use this when retrofitting Obsidian-style wiki-links across your notes.

---

## ⚙️ Useful Flags

- `--exclude-dir build dist` → skip specific directories.
    
- `--include "**/*.md" "**/*.txt"` → only include files matching glob patterns.
    
- `--case-sensitive` → make search case-sensitive (default is case-insensitive).
    
- `--follow-symlinks` → descend into symlinked directories.
    

---

## 🚫 Default Exclusions

The script skips common junk folders unless `--no-default-excludes` is used:

- `.git`
    
- `node_modules`
    
- `.obsidian`
    
- `__pycache__`
    
- `venv` / `.venv`
    

---

## 🧪 Examples

1. Replace all mentions of _Zuko_ with _Prince Zuko_ in markdown:
    
    ```bash
    python bulk_find_replace.py --find "Zuko" --replace "Prince Zuko" --ext .md
    ```
    
2. Update _Ba Sing Se_ mentions and preview before applying:
    
    ```bash
    python bulk_find_replace.py --find "Ba Sing Se" --replace "Ba Sing Se" --ext .md .txt --dry-run
    ```
    
3. Add Obsidian-style links around _spirit_ in notes:
    
    ```bash
    python bulk_find_replace.py --find "spirit" -b --ext .md
    ```
    
4. Process only `notes/` folder, excluding `archive/`:
    
    ```bash
    python bulk_find_replace.py notes --find "spirit" --replace "Spirit" --include "**/*.md" --exclude-dir archive
    ```
    

---

## 🛡️ Safety Tips

- Always start with `--dry-run`.
    
- Use `--backup` if applying wide changes.
    
- Limit scope with `--ext` or `--include` to avoid unintended edits.
    

---

✅ With this script, bulk editing across a vault or project becomes quick, reversible, and safe.

### More usages Examples

- Build a backlinks list for `[[action]].md` (scan only markdown):
    
    `python bulk_find_replace.py --ext .md --collectionfile [[action]].md`
    
- Combine with normal find/replace (runs both pipelines):
    
    `python bulk_find_replace.py --find "spirit" --replace "Spirit" --ext .md \   --collectionfile [[action]].md --collectionfile Condition.md`
    
- Compact, color-coded output:
    
    `python bulk_find_replace.py --ext .md --collectionfile [[action]].md --compact`