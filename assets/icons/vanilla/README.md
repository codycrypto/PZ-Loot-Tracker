# Vanilla item icons (not included)

Project Zomboid's item icons are The Indie Stone's art, so they aren't in this repo.
Extract them from your own game install with one command from the repo root:

    uv run --with pillow build/extract_icons.py

That fills this folder with `Item_*.png` files plus `icons.js`. Reload the tracker to see them.
Without them, items show 8×8 category glyphs. Everything else works the same.
See the main README ("Item icons") for passing the game path yourself.
