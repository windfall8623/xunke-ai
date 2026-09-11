import { readFile, writeFile } from 'node:fs/promises'
import openapiTS, { astToString } from 'openapi-typescript'
import { format } from 'prettier'

const schema = new URL('../../contracts/openapi.json', import.meta.url)
const output = new URL('../src/types/api.generated.ts', import.meta.url)
const formatOptions = JSON.parse(
  await readFile(new URL('../.prettierrc.json', import.meta.url), 'utf8'),
)
const source = await format(
  `/** Generated from contracts/openapi.json. Run npm run api:generate to update. */\n${astToString(await openapiTS(schema))}`,
  { ...formatOptions, parser: 'typescript' },
)
if (process.argv.includes('--check')) {
  const existing = await readFile(output, 'utf8').catch(() => '')
  if (source !== existing) {
    console.error('API types differ from contracts/openapi.json. Run npm run api:generate.')
    process.exitCode = 1
  } else console.log('OpenAPI types are current.')
} else {
  await writeFile(output, source)
  console.log('Generated src/types/api.generated.ts from contracts/openapi.json.')
}
