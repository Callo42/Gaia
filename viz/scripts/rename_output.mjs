#!/usr/bin/env node
// Renames dist/index.html -> dist/template.html, verifies the
// __GRAPH_DATA__ placeholder is intact, and copies the bundle into the
// Python package ship location (gaia/cli/starmap_assets/template.html).
import { existsSync, renameSync, readFileSync, statSync, unlinkSync, copyFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(__dirname, '..', 'dist');
const src = resolve(distDir, 'index.html');
const dst = resolve(distDir, 'template.html');

if (!existsSync(src)) {
  console.error(`[rename] expected ${src} to exist`);
  process.exit(1);
}

if (existsSync(dst)) unlinkSync(dst);
renameSync(src, dst);

const html = readFileSync(dst, 'utf-8');
if (!html.includes('<!--__GRAPH_DATA__-->')) {
  console.error('[rename] FAIL: placeholder <!--__GRAPH_DATA__--> missing from built HTML');
  process.exit(1);
}

const size = statSync(dst).size;
const sizeKb = (size / 1024).toFixed(1);
console.log(`[rename] dist/template.html ready (${sizeKb} KB, placeholder OK)`);

const shipDir = resolve(__dirname, '..', '..', 'gaia', 'cli', 'starmap_assets');
const shipPath = resolve(shipDir, 'template.html');
mkdirSync(shipDir, { recursive: true });
copyFileSync(dst, shipPath);
console.log(`[rename] copied to ${shipPath}`);
