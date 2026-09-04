# Profile Maintenance & Architecture Guide

This repository separates its assets into two distinct paths:

- **Static Assets:** 
  - `source/profile-photo.png` $\rightarrow$ `assets/portrait.svg` (Gold ASCII owl portrait).
  - `scripts/make_wordmark.py` $\rightarrow$ `assets/wordmark.svg` (Terminal header/wordmark).
  - Static assets change only when intentionally regenerated.

- **Live Data Assets:** 
  - `data/github-data.json` $\rightarrow$ `assets/contributions.svg` and `assets/stats.svg`.
  - The scheduled workflow refreshes only these public GitHub-data assets daily.

---

## 1. Local Development & Regeneration Commands

### Regenerate Static Assets (Portrait & Wordmark)
```powershell
python -m pip install -r requirements-static.txt
python scripts/prep_photo.py --input "source/profile-photo.png" --output source/profile-photo.png --static
python scripts/make_portrait.py --input source/profile-photo.png --output assets/portrait.svg
python scripts/make_wordmark.py --output assets/wordmark.svg
```

### Regenerate Live GitHub Panels Locally
```powershell
# Set optional GITHUB_TOKEN environment variable for full GraphQL live data
python scripts/fetch_github_data.py --username arindam0025
python scripts/render_contributions.py
python scripts/render_stats.py
```

### Run Unit Tests
```powershell
python -m unittest scripts/test_scripts.py
```

---

## 2. GitHub Actions Workflow

The scheduled job (`.github/workflows/refresh-profile.yml`) runs daily at 03:23 UTC and can be manually dispatched via **Actions $\rightarrow$ Refresh profile activity $\rightarrow$ Run workflow**.

- **Permissions:** `contents: write`
- **Security:** Uses repository-scoped `GITHUB_TOKEN`.
- **Determinism:** Commits only when `git diff` detects real data changes in `assets/` or `data/`.
- **Loop Prevention:** Triggered only on `schedule` and `workflow_dispatch` (no `push` trigger loop).

---

## 3. GitHub Markdown Rendering & Compatibility

- **Standalone SVGs:** Embedded via `<img>` tags for standard GitHub sanitization compatibility.
- **CSS Animations:** Use `@media (prefers-reduced-motion)` fallbacks for accessibility and frozen final animation states.
- **Font Subsetting & Geometry:** Fixed monospace advance widths inside SVGs eliminate cross-platform font rendering glitches.
