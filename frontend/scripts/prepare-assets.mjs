import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { cp, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pdfRoot = dirname(require.resolve('pdfjs-dist/package.json'));
const swaggerRoot = dirname(require.resolve('swagger-ui-dist/package.json'));
await mkdir(join(root, 'public', 'pdfjs'), { recursive: true });
for (const name of ['cmaps', 'standard_fonts', 'wasm']) {
  await cp(join(pdfRoot, name), join(root, 'public', 'pdfjs', name), { recursive: true });
}
await mkdir(join(root, 'public', 'swagger'), { recursive: true });
for (const name of ['swagger-ui.css', 'swagger-ui-bundle.js', 'favicon-32x32.png']) {
  await cp(join(swaggerRoot, name), join(root, 'public', 'swagger', name));
}
