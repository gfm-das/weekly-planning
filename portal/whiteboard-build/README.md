# Whiteboard bundle (Excalidraw + React)

The portal's Whiteboard page (`portal/whiteboard/`) uses Excalidraw, which is a React component. It is built once,
here, into plain files in `portal/whiteboard/vendor/`, and those files are committed. Nothing is built or installed on
the server: nginx serves the vendored files as they are.

| Package | Version | Licence |
|---|---|---|
| `@excalidraw/excalidraw` | 0.18.1 | MIT |
| `react`, `react-dom` | 19.3.0 | MIT |
| `vite` (build only) | 8.3.1 | MIT |

Every other version is pinned by `package-lock.json`. The licences of everything in the bundle are collected into
`vendor/THIRD_PARTY_LICENSES.txt`, and `vendor/SHA256SUMS` lists every built file with its checksum.

## What is in `vendor/`

- `gfm-excalidraw.js`: one ES module with what `src/entry.js` exports (Excalidraw, its helpers, React and
  `createRoot`). The page imports it: `import * as X from './vendor/gfm-excalidraw.js'`.
- `chunks/`: parts loaded only when needed (Excalidraw's 55 languages, the Mermaid diagram tools and so on).
- `gfm-excalidraw.css`: Excalidraw's styles.
- `fonts/`: Excalidraw's fonts (Excalifont, Nunito, Virgil, Lilita, Comic Shanns, Cascadia, Liberation,
  Assistant). Xiaolai (the hand-drawn Chinese, Japanese and Korean font, 13 MB) is left out: those characters use the
  browser's own font. `vite.config.mjs` points Excalidraw's font fallback at this folder, so the page never contacts
  another site (Excalidraw would otherwise ask esm.sh).
- About 9 MB in total. Opening a board loads the main module and styles (about 260 KB compressed by nginx) and the
  parts it needs; the rest loads only when used.

`.gitattributes` in `vendor/` keeps the files byte for byte on every checkout, so `SHA256SUMS` always matches.

## Rebuilding (only to change a version)

In a throw-away `node:24-alpine` container, from the repository root in Git Bash (it downloads the pinned packages
into the container only; the build itself takes a few seconds, `npm ci` about a minute):

```sh
MSYS_NO_PATHCONV=1 docker run --rm --name gfm-whiteboard-build --memory 2g \
  -v "$(pwd -W)/portal/whiteboard-build:/src:ro" -v "$(pwd -W)/portal/whiteboard/vendor:/out" \
  node:24-alpine sh /src/build.sh
```

`build.sh` copies this folder into the container, runs `npm ci` and `vite build`, adds the fonts, the licences and
`SHA256SUMS`, then replaces the contents of `portal/whiteboard/vendor/` (only the files it built and `.gitattributes`
are left).

To change a version: edit `package.json`, run `npm install --package-lock-only` in a throw-away container the same way
(with `/src` writable), rebuild, then check the page (`portal-api/tests/edge_whiteboard.ps1`). When Excalidraw
changes, `vite.config.mjs` stops the build with a clear message if the esm.sh font fallback is no longer where it
expects it; look at the new code and adjust the marker.

To check that the vendored files are what this folder builds, build into an empty folder instead of `vendor/` and
compare: `diff <folder>/SHA256SUMS portal/whiteboard/vendor/SHA256SUMS` (no output when they are the same). The build
is reproducible: done this way on 28 Sep, all 202 files were identical.
