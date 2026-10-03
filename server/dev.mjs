// Servidor local para o teste de tela: serve os arquivos da raiz e monta a
// mesma função api/state.js em /api/state, como a Vercel faz em produção.
//
//   node server/dev.mjs            # http://localhost:3000
//   PORT=3100 node server/dev.mjs
//
// Lê o .env.local (fora do git) no formato KEY="valor" que o `vercel env pull`
// escreve. As pré-visualizações da Vercel exigem login no site da Vercel, e o
// `vercel dev` busca sozinho o ambiente de desenvolvimento; este arquivo
// existe para o teste rodar com o que está no disco e nada mais.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = path.join(raiz, ".env.local");
if (fs.existsSync(env)) {
  for (const linha of fs.readFileSync(env, "utf8").split("\n")) {
    const m = linha.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^"(.*)"$/, "$1");
  }
}
const { default: state } = await import("../api/state.js");

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".md": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
};

// O `res` que api/state.js espera é o da Vercel: status().json() e setHeader().
function respostaVercel(res) {
  return {
    status(c) { res.statusCode = c; return this; },
    json(b) { res.setHeader("content-type", "application/json; charset=utf-8"); res.end(JSON.stringify(b)); return this; },
    setHeader: (k, v) => res.setHeader(k, v),
  };
}

const porta = Number(process.env.PORT) || 3000;
http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${porta}`);
  if (url.pathname === "/api/state") {
    let body = "";
    for await (const parte of req) body += parte;
    return state({ method: req.method, headers: req.headers, body }, respostaVercel(res));
  }
  let p = path.join(raiz, decodeURIComponent(url.pathname));
  if (p.endsWith("/")) p += "index.html";
  if (!p.startsWith(raiz) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) {
    res.statusCode = 404;
    return res.end("não encontrado");
  }
  res.setHeader("content-type", MIME[path.extname(p)] || "application/octet-stream");
  res.setHeader("cache-control", "no-store");
  fs.createReadStream(p).pipe(res);
}).listen(porta, () => console.log(`assistente local em http://localhost:${porta}`));
