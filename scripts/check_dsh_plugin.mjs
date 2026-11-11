/** Offline manifest/patch/package checks; no registry write or publication. */
import { readFile, stat } from 'node:fs/promises';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const manifest = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
const patches = manifest.dsh?.bundle?.patch;
const entries = Array.isArray(patches) ? patches : [patches];
if (!entries.length) throw new Error('Missing dsh.bundle.patch');
for (const patch of entries) {
  if (typeof patch !== 'string' || !patch.startsWith('./') || patch.split(/[\\/]/).includes('..') || isAbsolute(patch)) throw new Error('Unsafe patch path');
  const data = parse(await readFile(resolve(root, patch), 'utf8'));
  if (!Array.isArray(data)) throw new Error('Patch must be a top-level array');
  if (!data.some(op => op.insert?.some(row => row.name === manifest.name))) throw new Error('Patch must insert this package');
}
for (const file of ['dsh/index.mjs', 'dsh/settings.mjs', 'skills/deep-research-agent/SKILL.md', 'skills/deep-research-agent/scripts/research.py', 'skills/deep-research-agent/scripts/research_reading.py', 'skills/deep-research-agent/references/source-registry.json', 'examples/research.env.example']) {
  if (!(await stat(resolve(root, file))).isFile()) throw new Error('Missing package resource: ' + file);
}
if (manifest.scripts?.postinstall || manifest.scripts?.preinstall || manifest.scripts?.install) throw new Error('Unexpected install hook');
console.log(JSON.stringify({ package: manifest.name, version: manifest.version, manifest: 'valid', patch: 'valid', publication: 'not_performed' }));
