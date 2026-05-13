import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const cacheDir = path.resolve(process.cwd(), 'cache');

function cachePath(key) {
  return path.join(cacheDir, `${key}.json`);
}

export async function readJsonCache(key) {
  try {
    const filePath = cachePath(key);
    const content = await readFile(filePath, 'utf8');
    return JSON.parse(content);
  } catch (error) {
    return null;
  }
}

export async function writeJsonCache(key, value) {
  await mkdir(cacheDir, { recursive: true });
  const filePath = cachePath(key);
  await writeFile(filePath, JSON.stringify(value, null, 2), 'utf8');
}
