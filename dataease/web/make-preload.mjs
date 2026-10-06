// Makes web/gfm/preload.js: the list of DataEase's script and style files that the Dashboards page needs, so the
// browser asks for all of them at once (<link rel="modulepreload">) instead of finding them one after another.
//
// Where the list comes from: the front's own log of a real visit. Open Dashboards in the portal once, then run (from the
// repository root, PowerShell):
//   docker logs gfm-dataease-web --since 30m 2>&1 | docker run --rm -i -v "${PWD}\dataease\web:/w" -w /w node:24-alpine node make-preload.mjs
// It writes gfm/preload.js next to this file. Do it again after every DataEase update (the file names carry its version,
// for example -2.10.20-dataease.js); a name that no longer exists is harmless (one extra request that is refused).
// Then raise the ?v= of preload.js in default.conf and restart gfm-dataease-web (docs: dataease/README.md).
import { readFileSync, writeFileSync } from 'node:fs';

const log = readFileSync(0, 'utf8');
const wanted = /^\/(assets\/(chunk|css)\/|js\/)[^?\s]*-\d+\.\d+\.\d+-dataease\.(js|css)$/;
const paths = new Set();
for (const line of log.split('\n')) {
  const found = /"GET (\S+) HTTP/.exec(line);
  const path = found && found[1].split('?')[0];
  if (path && wanted.test(path)) paths.add(path);
}
if (paths.size < 20) {
  console.error(`Only ${paths.size} files in the log: open Dashboards in the portal first, then run this again.`);
  process.exit(1);
}
const list = [...paths].sort();
writeFileSync(new URL('./gfm/preload.js', import.meta.url), `/* Made by web/make-preload.mjs: ${list.length} files of the Dashboards page, asked for at once. */
(function () {
  var files = ${JSON.stringify(list)};
  var head = document.head;
  files.forEach(function (path) {
    var link = document.createElement('link');
    if (/\\.css$/.test(path)) { link.rel = 'preload'; link.as = 'style'; } else { link.rel = 'modulepreload'; }
    link.href = path;
    head.appendChild(link);
  });
})();
`);
console.log(`${list.length} files written to gfm/preload.js`);
