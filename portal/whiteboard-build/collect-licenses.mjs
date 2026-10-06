// Writes the licence of every package in the bundle (production dependencies only, from `npm ls`) to one text file,
// so the vendored folder carries the copyright notices that the MIT and similar licences ask for.
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// npm ls exits with an error when a package's optional peer range does not name React 19 (it still prints the tree).
let listed
try { listed = execFileSync('npm', ['ls', '--omit=dev', '--all', '--json', '--long'], { encoding: 'utf8', maxBuffer: 256 << 20, stdio: ['ignore', 'pipe', 'ignore'] }) }
catch (error) { listed = error.stdout }
const tree = JSON.parse(listed)
const seen = new Map()
;(function walk(deps) {
  for (const [name, info] of Object.entries(deps || {})) {
    if (info.path && !seen.has(`${name}@${info.version}`)) seen.set(`${name}@${info.version}`, { name, version: info.version, dir: info.path })
    walk(info.dependencies)
  }
})(tree.dependencies)
const parts = ['Third-party software in portal/whiteboard/vendor/ (built by portal/whiteboard-build; see its README.md).', '']
for (const { name, version, dir } of [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))) {
  const pkg = JSON.parse(readFileSync(path.join(dir, 'package.json'), 'utf8'))
  const license = typeof pkg.license === 'string' ? pkg.license : pkg.license?.type || (pkg.licenses || []).map(l => l.type || l).join(', ') || 'see the package'
  const file = existsSync(dir) ? readdirSync(dir).find(f => /^(licen[cs]e|copying)(\.|$)/i.test(f)) : null
  parts.push('='.repeat(78), `${name} ${version} (${license})`, '='.repeat(78))
  parts.push(file ? readFileSync(path.join(dir, file), 'utf8').trim() : `No licence file in the package; its package.json says: ${license}.`, '')
}
writeFileSync(process.argv[2], parts.join('\n') + '\n')
console.log(`licences of ${seen.size} packages written`)
