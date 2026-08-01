#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/tanmoysrt/beagle"
PREFIX="${BEAGLE_PREFIX:-$HOME/.local/share/beagle}"
BIN_DIR="${BEAGLE_BIN_DIR:-$HOME/.local/bin}"
MIN_PYTHON="3.11"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

find_python() {
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c "import sys; raise SystemExit(sys.version_info < (3, 11))"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

command -v git >/dev/null 2>&1 || die "git is required but was not found."
PYTHON="$(find_python)" || die "Python $MIN_PYTHON or newer is required but was not found."
say "Using $($PYTHON --version) at $(command -v "$PYTHON")"

# Run from a clone if there is one; otherwise fetch the source.
if [ -f "$(dirname "$0")/pyproject.toml" ]; then
    SOURCE="$(cd "$(dirname "$0")" && pwd)"
    say "Installing from this checkout: $SOURCE"
else
    SOURCE="$PREFIX/src"
    if [ -d "$SOURCE/.git" ]; then
        say "Updating $SOURCE"
        git -C "$SOURCE" pull --ff-only
    else
        say "Cloning $REPO into $SOURCE"
        mkdir -p "$(dirname "$SOURCE")"
        git clone --depth 1 "$REPO" "$SOURCE"
    fi
fi

say "Creating the virtual environment in $PREFIX/venv"
mkdir -p "$PREFIX"
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet "$SOURCE"

say "Writing the launcher to $BIN_DIR/beagle"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/beagle" <<LAUNCHER
#!/usr/bin/env bash
exec "$PREFIX/venv/bin/beagle" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/beagle"

CONFIG_DIR="${BEAGLE_DATA_DIR:-$PWD/data}"
if [ ! -f "$CONFIG_DIR/config.toml" ] && [ -f "$SOURCE/data/config.example.toml" ]; then
    mkdir -p "$CONFIG_DIR"
    cp "$SOURCE/data/config.example.toml" "$CONFIG_DIR/config.toml"
    chmod 600 "$CONFIG_DIR/config.toml"
    say "Created $CONFIG_DIR/config.toml from the example"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH. Add this line to your shell profile:"
       warn "    export PATH=\"\$PATH:$BIN_DIR\"" ;;
esac

echo
say "Beagle is installed. $("$BIN_DIR/beagle" --help >/dev/null 2>&1 && echo "The command answers.")"
cat <<NEXT

Next steps:

  1. Put your API keys in $CONFIG_DIR/config.toml
     Set repo.url to the repository that you want to review.

  2. Check the configuration:
       beagle --config $CONFIG_DIR/config.toml doctor

  3. Make the index:
       beagle --config $CONFIG_DIR/config.toml index

  4. Review a branch:
       beagle --config $CONFIG_DIR/config.toml review my-branch

To remove Beagle, delete $PREFIX and $BIN_DIR/beagle.
NEXT
