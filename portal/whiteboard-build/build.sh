#!/bin/sh
# Rebuilds portal/whiteboard/vendor/ from the pinned versions in package.json and package-lock.json.
# Runs in a throw-away node:24-alpine container, so nothing is installed on the server (see README.md).
#   /src: this folder (read-only)   /out: portal/whiteboard/vendor (its contents are replaced)
set -eu
mkdir -p /work
cp /src/package.json /src/package-lock.json /src/vite.config.mjs /src/collect-licenses.mjs /work/
cp -r /src/src /work/src
cd /work
npm ci --no-audit --no-fund --loglevel=error
NODE_OPTIONS=--max-old-space-size=1536 npx vite build
# Fonts: every family Excalidraw offers, from the package itself. Xiaolai (the hand-drawn Chinese, Japanese and Korean
# font, 13 MB) is left out: those characters show in the browser's own font instead.
mkdir -p dist/fonts
for family in node_modules/@excalidraw/excalidraw/dist/prod/fonts/*; do
  [ "$(basename "$family")" = Xiaolai ] && continue
  cp -r "$family" dist/fonts/
done
node collect-licenses.mjs dist/THIRD_PARTY_LICENSES.txt
( cd dist && find . -type f | sort | while read -r f; do printf '%s  %s\n' "$(sha256sum "$f" | cut -c1-64)" "${f#./}"; done ) > /tmp/SHA256SUMS
mv /tmp/SHA256SUMS dist/SHA256SUMS
find /out -mindepth 1 ! -path /out/.gitattributes -delete 2>/dev/null || true
cp -r dist/. /out/
echo "built: $(find dist -type f | wc -l) files, $(du -sh dist | cut -f1)"
