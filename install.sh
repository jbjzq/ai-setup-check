#!/usr/bin/env bash
# Install the ai-setup-check skill for Claude Code and Codex, then run the probe once.
# Usage: curl -fsSL https://raw.githubusercontent.com/jbjzq/ai-setup-check/main/install.sh | bash
set -euo pipefail

UPLOAD_URL="https://fl33rhwwbp6jmyr6j2u55uyrji0jwgxr.lambda-url.eu-central-1.on.aws/upload"

REPO="https://github.com/jbjzq/ai-setup-check/archive/refs/heads/main.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$REPO" | tar xz -C "$TMP"
SRC="$TMP/ai-setup-check-main"

for dir in "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  [ -d "$(dirname "$dir")" ] || continue
  mkdir -p "$dir/ai-setup-check"
  cp "$SRC/SKILL.md" "$SRC/goals.md" "$SRC/probe.py" "$SRC/score.py" "$SRC/pdfreport.py" "$SRC/coach.py" "$SRC/htmlreport.py" "$SRC/brand.py" "$dir/ai-setup-check/"
  echo "Installed skill in $dir/ai-setup-check"
done

NAME="$(git config --global user.name 2>/dev/null || true)"
NAME="${NAME:-$USER}"
SLUG="$(printf '%s' "$NAME" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-')"
OUT="$HOME/Desktop/ai-setup-$SLUG.pdf"
[ -d "$HOME/Desktop" ] || OUT="$HOME/ai-setup-$SLUG.pdf"

echo "Scanning your setup (read-only, about a minute)..."
python3 -I "$SRC/probe.py" --name "$NAME" > "$TMP/probe.json"
echo "Writing your personal review with Claude Code (one to three minutes)..."
python3 -I "$SRC/score.py" "$TMP/probe.json" --coach --pdf "$OUT" > "$TMP/report.md"
sed -n '1,/^## What to improve/p' "$TMP/report.md" | head -30
echo
echo "Saved $OUT (your report, with the raw data on the last pages)."

# Optional: upload the PDF to get a private link (unguessable, deleted after a year) instead of sending the file.
# The installer is piped into bash, so the question is read from the terminal itself.
ANSWER=""
if [ -r /dev/tty ]; then
  printf "Upload it to get a shareable link? [Y/n] " > /dev/tty
  read -r ANSWER < /dev/tty || ANSWER="n"
fi
case "$ANSWER" in
  [nN]*) echo "Not uploaded. Send the PDF to JB on Slack." ;;
  *)
    if RESPONSE="$(curl -fsS -X POST -H "Content-Type: application/pdf" --data-binary "@$OUT" "$UPLOAD_URL")"; then
      LINK="$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
      echo
      echo "Your report: $LINK"
      echo "Send that link to JB on Slack."
    else
      echo "Upload failed. Send the PDF to JB on Slack instead."
    fi ;;
esac
