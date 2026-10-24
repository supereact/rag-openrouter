import { afterEach, describe, expect, it } from 'vitest'
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, sep } from 'node:path'
import { pathToFileURL } from 'node:url'
import { prepareStaticRoutes } from './prepare-static-routes.mjs'

const directories = []
afterEach(async () => {
  await Promise.all(directories.splice(0).map(path => rm(path, {recursive: true, force: true})))
})

async function output() {
  const directory = await mkdtemp(join(tmpdir(), 'rag-static-routes-'))
  directories.push(directory)
  await writeFile(join(directory, 'index.html'), '<html><div id="root"></div><script src="/assets/app.js"></script></html>')
  return pathToFileURL(directory + sep)
}

describe('Vercel static page URLs without rewrites', () => {
  it('creates the public shell for every application URL and a 404 document', async () => {
    const routes = JSON.parse(await readFile(join(process.cwd(), 'src/page-routes.json'), 'utf8'))
    const target = await output()
    await prepareStaticRoutes(target, routes)
    const html = await readFile(new URL('index.html', target), 'utf8')
    for (const route of [...routes.workspace, ...routes.public]) {
      expect(await readFile(new URL(`${route.slice(1)}.html`, target), 'utf8')).toBe(html)
    }
    expect(await readFile(new URL('404.html', target), 'utf8')).toBe(html)
    const config = JSON.parse(await readFile(join(process.cwd(), 'vercel.json'), 'utf8'))
    expect(config.cleanUrls).toBe(true)
    expect(config).not.toHaveProperty('rewrites')
    expect(config).not.toHaveProperty('routes')
  })

  it('rejects duplicate or unsafe paths before writing route files', async () => {
    const target = await output()
    for (const workspace of [['/../outside'], ['/documents', '/documents'], ['https://evil.example']]) {
      await expect(prepareStaticRoutes(target, {workspace, public: []})).rejects.toThrow('Static page routes')
    }
    expect(await readdir(target)).toEqual(['index.html'])
  })
})
