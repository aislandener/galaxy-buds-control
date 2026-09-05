# AGENTS.md

## Commit workflow

Commit every time you change code in this repo — don't batch unrelated changes into one commit.

After every `git commit` in this repo, run:

```
omarchy plugin update aislandener.galaxy-buds --yes
```

This refreshes the installed Omarchy plugin so local testing reflects the latest commit.

Then run `omarchy-restart-shell` to reload the live shell — do this every time without asking first, so QML/Panel changes are visible immediately.
