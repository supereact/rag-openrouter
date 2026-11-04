import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

export function validateVercelApiBase(base) {
  if (base === '/api') return
  try {
    const url = new URL(base || '')
    if (url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash) return
  } catch { /* Never include a possibly mistaken secret in the error. */ }
  throw new Error('Set VITE_API_BASE_URL to /api for the Vercel proxy, or a public HTTPS backend URL.')
}

export async function prepareStaticRoutes(output, routes) {
  const html = await readFile(new URL('index.html', output), 'utf8')
  const paths = [...routes.workspace, ...routes.public]
  if (paths.some(path => !/^\/[a-z0-9-]+$/.test(path)) || new Set(paths).size !== paths.length) {
    throw new Error('Static page routes must be unique, single-level application paths.')
  }
  // Public shell only; authentication and protected data load in the browser.
  // Vercel cleanUrls serves /documents.html at /documents without rewrite rules.
  await Promise.all([...paths.map(path => writeFile(new URL(`${path.slice(1)}.html`, output), html)),
    writeFile(new URL('404.html', output), html)])
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (process.env.VERCEL === '1') {
    validateVercelApiBase(process.env.VITE_API_BASE_URL)
  }
  const routes = JSON.parse(await readFile(new URL('../src/page-routes.json', import.meta.url), 'utf8'))
  await prepareStaticRoutes(new URL('../dist/', import.meta.url), routes)
}
