// serve.mjs —— 本地静态服务器（.glb / .meta.json 的 MIME 要给对）
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const ROOT = process.cwd();
const PORT = Number(process.argv[2] || 8787);
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.glb': 'model/gltf-binary',
  '.gltf': 'model/gltf+json', '.bin': 'application/octet-stream',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.css': 'text/css; charset=utf-8',
};

http.createServer(async (req, res) => {
  try {
    const url = decodeURIComponent((req.url || '/').split('?')[0]);
    let p = normalize(join(ROOT, url === '/' ? '/viewer.html' : url));
    if (!p.startsWith(ROOT)) { res.writeHead(403).end('forbidden'); return; }
    const s = await stat(p);
    if (s.isDirectory()) p = join(p, 'viewer.html');
    const buf = await readFile(p);
    res.writeHead(200, {
      'Content-Type': MIME[extname(p).toLowerCase()] || 'application/octet-stream',
      'Content-Length': buf.length, 'Cache-Control': 'no-store',
    });
    res.end(buf);
  } catch (e) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }).end('404 ' + (e && e.message));
  }
}).listen(PORT, '127.0.0.1', () => console.log('serving http://127.0.0.1:' + PORT + '/'));
