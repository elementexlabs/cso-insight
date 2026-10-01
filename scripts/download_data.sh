#!/usr/bin/env bash
# Acquire a pinned feed into a separate path; never replace the frozen snapshot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="https://openamend.org/data/EEADP_CSO.csv"
EXPECTED="0e8a56ebf1870646431de7c1d326065fbcd9cd27f63132e0790e79eb5ef231c3"
# Resolve aliases/symlinks before comparing the destination with the frozen path.
DEST=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "${1:-$ROOT/data/raw/ma_eea_cso.download.csv}")
FROZEN=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$ROOT/data/raw/ma_eea_cso.csv")
if [ "$DEST" = "$FROZEN" ] || { [ -e "$DEST" ] && [ -e "$FROZEN" ] && [ "$DEST" -ef "$FROZEN" ]; }; then
  echo "Refusing to overwrite the frozen snapshot. See docs/DATA_MANIFEST.md for recovery." >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
TMP=$(mktemp "$(dirname "$DEST")/.download-XXXXXX")
trap 'rm -f "$TMP"' EXIT
if ! curl -fsSL "$URL" -o "$TMP"; then
  echo "Acquisition failed; retained files unchanged. See docs/DATA_MANIFEST.md for recovery." >&2
  exit 1
fi
ACTUAL=$(shasum -a 256 "$TMP" | awk '{print $1}')
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "SHA-256 mismatch: got $ACTUAL expected $EXPECTED; retained files unchanged." >&2
  echo "Stop; recover the matching snapshot via docs/DATA_MANIFEST.md. A changed feed requires a separately versioned analysis." >&2
  exit 1
fi
mv -f "$TMP" "$DEST"
echo "Downloaded and verified acquisition: $DEST"
echo "See docs/DATA_MANIFEST.md to install a matching snapshot only when the frozen path is absent."
