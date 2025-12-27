import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = path.resolve(__dirname, '..');
const distDir = path.join(root, 'dist');

fs.rmSync(distDir, { recursive: true, force: true });
console.log('cleaned dist/');
