#!/usr/bin/env sh
# Usage: HF_USER=<you> HF_TOKEN=<token> sh scripts/deploy_hf.sh
set -eu
SPACE="https://${HF_USER}:${HF_TOKEN}@huggingface.co/spaces/${HF_USER}/aaw-moderator"
TMP="$(mktemp -d)"
git clone --depth 1 "$SPACE" "$TMP/space"
find "$TMP/space" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD | tar -x -C "$TMP/space"
{
  printf -- '---\ntitle: Afandem\nemoji: 🛍️\ncolorFrom: green\ncolorTo: gray\nsdk: docker\napp_port: 7860\npinned: false\n---\n\n'
  cat README.md
} > "$TMP/space/README.md"
cd "$TMP/space"
git add -A
git -c user.name="$(git -C "$OLDPWD" config user.name)" -c user.email="$(git -C "$OLDPWD" config user.email)" commit -m "deploy $(git -C "$OLDPWD" rev-parse --short HEAD)"
git push
echo "https://huggingface.co/spaces/${HF_USER}/aaw-moderator"
