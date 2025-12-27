import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import esbuild from 'esbuild';
import * as sass from 'sass';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = path.resolve(__dirname, '..');
const srcDir = path.join(root, 'src');
const distDir = path.join(root, 'dist');

const args = new Set(process.argv.slice(2));
const watch = args.has('--watch');

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

async function buildOnce() {
  ensureDir(distDir);

  const templatePath = path.join(srcDir, 'template.html');
  const scssPath = path.join(srcDir, 'styles.scss');
  const tsEntrySrc = path.join(srcDir, 'overlay.ts');
  const tsEntryRoot = path.join(root, 'overlay.ts');
  const tsEntry = fs.existsSync(tsEntrySrc) ? tsEntrySrc : tsEntryRoot;

  const template = fs.readFileSync(templatePath, 'utf8');

  const cssResult = sass.compile(scssPath, {
    style: 'compressed',
    quietDeps: true,
  });
  const css = cssResult.css;

  const jsResult = await esbuild.build({
    entryPoints: [tsEntry],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['es2022'],
    minify: true,
    write: false,
    legalComments: 'none',
  });

  const js = jsResult.outputFiles[0].text;

  const html = template
    .replace('/*__CSS__*/', css)
    .replace('/*__JS__*/', js);

  const outPath = path.join(distDir, 'overlay.html');
  // Safety: remove any leftover placeholder artifacts (and an accidental '&' that may follow)
  const cleaned = html.replace(/\/\*__JS__\*\/&?/g, '');
  if (cleaned.includes('__JS__')) {
    process.stderr.write('[warn] overlay build: leftover placeholder found in output\n');
  }
  fs.writeFileSync(outPath, cleaned, 'utf8');

  process.stdout.write(`[build] dist/overlay.html updated\n`);
}

function debounce(fn, ms) {
  let t = null;
  return () => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn().catch((e) => console.error(e)), ms);
  };
}

await buildOnce();

if (watch) {
  const rerun = debounce(buildOnce, 80);
  fs.watch(srcDir, { recursive: true }, (_event, _filename) => rerun());
  process.stdout.write('[watch] watching src/ for changes...\n');
  // keep process alive
  await new Promise(() => { });
}
