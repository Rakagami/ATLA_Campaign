# bulk_find_replace.py — Quickstart

Copy-paste friendly commands. See also: [[bulk_find_replace (Manual)]], [[bulk_find_replace (FAQ)]]

> Tips: start with `--dry-run`, scope with `--ext .md`, keep backups with `--backup .bak`.

---

## Safe wiki-link bracketing

Bracket plain mentions, skipping already-linked:

`python bulk_find_replace.py --ext .md --find "Bumi" --bracket --dry-run python bulk_find_replace.py --ext .md --find "Bumi" --bracket --backup .bak`

## Literal find/replace

`python bulk_find_replace.py --ext .md --find "Omashu" --replace "City of Omashu" --backup .bak`

Case-sensitive:

`python bulk_find_replace.py --ext .md --case-sensitive --find "Spirit" --replace "spirit" --backup .bak`

With punctuation/special chars (still literal):

`python bulk_find_replace.py --ext .md --find "[Action]" --replace "[Combat]" --backup .bak`

## Scope control

Only session logs:

`python bulk_find_replace.py Sessions --ext .md --include "**/Session*.md" --find "Appa" --replace "Appa the Sky Bison"`

Exclude extra dirs:

`python bulk_find_replace.py --ext .md --exclude-dir "Archive" "Exports" --find "Sokka" --replace "Sokka (Water Tribe)"`

Single file:

`python bulk_find_replace.py Notes/NPCs/Katara.md --find "Waterbending" --replace "Waterbending (Healing)"`

Follow symlinks (rare):

`python bulk_find_replace.py --follow-symlinks --ext .md --find "Ba Sing Se" --replace "Ba Sing Se (Lower Ring)"`

Multiple roots:

`python bulk_find_replace.py Notes Lore --ext .md --find "Pai Sho" --replace "Pai Sho (White Lotus)"`

## Collections (backlinks)

Create/update `Action.md` backlinks block + `AllAction.md` embeds:

`python bulk_find_replace.py --ext .md --collectionfile "Indexes/Action.md" --compact`

## Append lines

Append a footer if missing:

`python bulk_find_replace.py --ext .md --append "[[Index:NPCs]]" --backup .bak`

Combine append + replace in one pass:

`python bulk_find_replace.py --ext .md \   --append "[[Index:Sessions]]" \   --find "Zuko" --replace "Zuko (Crowned Prince)" \   --backup .bak --compact`

---

That’s it. Keep `--dry-run` until output looks right; then drop it and keep `--backup .bak` for safety.