// Copies the protocol and format chapters (docs/NN-*.md) into the site's reference section, adding Starlight
// frontmatter and rewriting links between chapters. sdk/docs stays the single source; the copies are not committed.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, rmSync, copyFileSync } from 'node:fs';
import { join, dirname, posix } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', '..', 'docs');
const target = join(here, '..', 'src', 'content', 'docs', 'reference');
rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
for (const file of readdirSync(source).filter((f) => /^\d\d-.*\.md$/.test(f)).sort()) {
  const text = readFileSync(join(source, file), 'utf8');
  const heading = text.match(/^#\s+(.+)$/m)?.[1] ?? file;
  const order = Number(file.slice(0, 2));
  const body = text
    .replace(/^#\s+.+\n/m, '')
    // Diagrams live in site/public/diagrams, which the site serves at /diagrams.
    .replace(/\]\(\.\.\/site\/public\/diagrams\/([^)\s]+)\)/g, '](/diagrams/$1)')
    // Links that leave sdk/docs go to the file on GitHub (resolved from sdk/docs first), then links between chapters
    // become site links. In this order, so a rewritten chapter link (../NN-name/) is not sent to GitHub.
    .replace(/\]\((\.\.\/[^)\s]+)\)/g, (_, rel) => `](https://github.com/movetrics/sdk/blob/main/${posix.normalize(`docs/${rel}`)})`)
    .replace(/\]\((\d\d-[^)#]+)\.md(#[^)]*)?\)/g, (_, name, hash) => `](../${name.toLowerCase()}/${hash ?? ''})`);
  const front = `---\ntitle: ${JSON.stringify(heading)}\nsidebar:\n  order: ${order}\n---\n\n`;
  writeFileSync(join(target, file), front + body);
}
// The Cloud API page renders the Cloud's own OpenAPI file, copied here so the page and the API never disagree.
copyFileSync(join(source, '..', 'contracts', 'movetrics-public-api-v1.json'), join(here, '..', 'public', 'api', 'movetrics-public-api-v1.json'));
console.log(`reference: ${readdirSync(target).length} chapters from sdk/docs`);
