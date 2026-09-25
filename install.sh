#!/bin/bash
# Install mynah: https://github.com/trotha01/mynah
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/trotha01/mynah/main/install.sh | bash
#
# Safe to re-run: every step below is idempotent.

set -euo pipefail

REPO_URL="https://github.com/trotha01/mynah.git"
REPO_BRANCH="main"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "mynah only runs on macOS."
[ "$(uname -m)" = "arm64" ] || die "mynah needs Apple Silicon (MLX doesn't run on Intel Macs)."

step "Checking for uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "not found, installing via the official installer..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH — open a new terminal and re-run this script."
else
  echo "found: $(uv --version)"
fi

step "Installing mynah"
uv tool install --force "git+${REPO_URL}@${REPO_BRANCH}"

UV_BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
case ":$PATH:" in
  *":$UV_BIN_DIR:"*) ;;
  *) warn "$UV_BIN_DIR isn't on your PATH yet. Add it to your shell profile (e.g. ~/.zshrc):
    export PATH=\"$UV_BIN_DIR:\$PATH\"
  Then open a new terminal before running mynah." ;;
esac

step "macOS permissions"
echo "mynah needs Input Monitoring granted to whatever app you launch it from"
echo "(this terminal, if you're reading this here) — to detect the Right Shift + Right Command"
echo "hotkey globally. Opening System Settings now:"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" 2>/dev/null || true

step "Done"
echo "After granting Input Monitoring, launch it with:"
echo "  mynah"
echo ""
echo "Then tap Right Shift + Right Command to hear Claude Code's latest reply. Tap again to stop."
