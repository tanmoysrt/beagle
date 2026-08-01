#!/usr/bin/env bash
set -euo pipefail

RAW="https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/beagle"
BIN_DIR="${BEAGLE_BIN_DIR:-$HOME/.local/bin}"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required but was not found."
python3 -c "import sys; raise SystemExit(sys.version_info < (3, 7))" \
    || die "Python 3.7 or newer is required. Found: $(python3 -V 2>&1)"

mkdir -p "$BIN_DIR"
HERE="$(cd "$(dirname "$0")" && pwd)"

EXISTING="$(command -v beagle 2>/dev/null || true)"
if [ -n "$EXISTING" ] && ! grep -q "Thin client for a Beagle server" "$EXISTING" 2>/dev/null; then
    warn "A different 'beagle' is already on your PATH: $EXISTING"
    warn "That is probably the server package. This client will shadow it if"
    warn "$BIN_DIR comes first. Use BEAGLE_BIN_DIR to install somewhere else."
    printf 'Continue? [y/N] '
    read -r reply
    case "$reply" in [yY]*) ;; *) die "Stopped." ;; esac
fi

if [ -f "$HERE/beagle" ]; then
    say "Installing from $HERE/beagle"
    cp "$HERE/beagle" "$BIN_DIR/beagle"
else
    say "Downloading the client"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$RAW" -o "$BIN_DIR/beagle"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$BIN_DIR/beagle" "$RAW"
    else
        die "curl or wget is required but neither was found."
    fi
fi

chmod +x "$BIN_DIR/beagle"
say "Installed to $BIN_DIR/beagle ($(wc -l < "$BIN_DIR/beagle") lines, no dependencies)"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH. Add this line to your shell profile:"
       warn "    export PATH=\"\$PATH:$BIN_DIR\"" ;;
esac

cat <<NEXT

Connect to your server:

    beagle login https://beagle.internal:8080 --token <token> --author "$(whoami)"

Then, in any repository:

    beagle review
    beagle findings <review-id>
    beagle feedback <finding-id> false_positive "we do this on purpose"

To remove the client, delete $BIN_DIR/beagle.
NEXT
