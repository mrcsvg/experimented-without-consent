# Assistente de codificação: plano de implementação

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development em toda função pura. Todo texto que o codificador lê segue a skill `estilo-marcus` (sem travessão, frase curta, uma ideia por frase, sem metáfora).

**Goal:** Substituir o notebook do Colab por uma página web em formato de assistente, com copiloto de IA congelado, modo ensaio e gravação por serviço, testada no navegador real antes de chegar ao 2º codificador.

**Architecture:** Três peças. (1) O servidor `api/state.js` na Vercel passa a exigir chave, a gravar por serviço e a ter um arquivo de ensaio. (2) Scripts Python geram dados congelados (codebook em JSON, piso de palavras-chave, sugestões do copiloto) e os publicam no site do corpus, que já serve o Markdown e as citações com CORS aberto. (3) A página, em HTML e JavaScript puros, lê tudo do site do corpus, grava no servidor e guarda cópia local no navegador. A lógica sem DOM fica em módulos `.mjs` testados com `node --test`.

**Tech Stack:** Node 25 (`node:test`, `node:crypto`), Vercel serverless (Node), Python 3 stdlib + `anthropic` (só o gerador do copiloto), HTML/CSS/JS sem framework e sem build.

**Desenho aprovado:** `docs/plans/2026-10-03-assistente-codificacao-design.md`.

**Repositórios:**
- instrumento (este): `~/Documents/UFPR/PPGCD/Papers/experimented-without-consent`, ramo `assistente-codificacao` (parte de `recibo-de-gravacao`).
- corpus: `~/Documents/UFPR/PPGCD/Papers/experimented-without-consent-corpus`, ramo `main`; push publica em `https://experimented-without-consent-corpus.vercel.app`.
- paper (privado): `~/Documents/UFPR/PPGCD/Papers/ethics-in-digita-experimentation`; só `audit/compute-agreement.py` é sincronizado, e o formato não muda.

**Fatos que o executor precisa saber:**
- `api/state.js` hoje: proxy fino para a GitHub Contents API, arquivo `audit/coder2-progress.json` no ramo `coder2-data`, sem autenticação, PUT substitui o arquivo inteiro. Env: `GITHUB_TOKEN` (PAT fine-grained, Contents R/W neste repo), opcionais `GH_REPO`, `GH_BRANCH`, `GH_PATH`.
- O servidor está vazio: `{"records":{}}`.
- `analysis/codebook.py` lê o codebook de `index.html` (constantes JS `DATA`, `CRIT`, `GLOSA`, `KWTERMS` etc.) e expõe `VARIAVEIS` (10: V1..V9 e KW), `SERVICOS` (26, na ordem), `criterio(crit_key)`, `glosa_criterio(v)`, `pergunta(v)`, `lembrete(v)`, `CRIT_CONGELADO`.
- `analysis/revisao.py` expõe `Corpus(origem)`, `varredura(servico, corpus)`, `piso(servico, corpus)`, `TERMO_PARA_VARIAVEL`, `_regras_gerais(corpus)`, `FONTE_CRIT`, `_cliente()` (lê `EWC_ANTHROPIC_KEY`), `MAX_TOKENS`.
- `analysis/patterns.py` expõe `scan_text(texto) -> (counts, hits)` e a lista de 12 termos com `regex` e `flag`.
- `analysis/build-md-corpus.py` expõe `slug(nome)`.
- Site do corpus: `md/index.json` (`services[]` com `name`, `slug`, `docs[]` com `n`, `file`, `url`, `chars`, `sha256_text`, `captured_at`, e `role`, que a página ignora), `md/<slug>/<arquivo>.md` (front matter YAML e corpo em texto), `sugestoes/<slug>.json` (`citacoes` por variável: `doc`, `file`, `onde`, `role`, `verbatim`), tudo com `access-control-allow-origin: *`. `lib/` contém o runtime do notebook e uma cópia do instrumento antigo; sai.
- Pré-visualizações da Vercel exigem login (302 para `vercel.com/sso-api`). O teste de tela roda em `vercel dev` local; o teste do Marcus roda em produção, em modo ensaio.
- A chave da API Anthropic nunca aparece no chat nem em arquivo: `EWC_ANTHROPIC_KEY="$(security find-generic-password -s ewc-anthropic-key -w)"` inline no comando.
- Nada da passada 1 chega à página: nem códigos, nem anotações (`DATA.services[].docs` do instrumento antigo), nem etiquetas `role`/[vinculante].

---

## Tarefa 1: núcleo do servidor, puro e testado

**Files:**
- Create: `server/state-core.mjs`
- Test: `server/state-core.test.mjs`

**Step 1: escrever os testes que falham**

```js
// server/state-core.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { modoDaChave, aplicar, criarHandler } from "./state-core.mjs";

const ENV = { GITHUB_TOKEN: "t", EWC_KEY: "chave-real-123456", EWC_KEY_ENSAIO: "chave-ensaio-1234" };

test("modoDaChave distingue real, ensaio e inválida", () => {
  assert.equal(modoDaChave("chave-real-123456", ENV), "real");
  assert.equal(modoDaChave("chave-ensaio-1234", ENV), "ensaio");
  assert.equal(modoDaChave("outra", ENV), null);
  assert.equal(modoDaChave(undefined, ENV), null);
  assert.equal(modoDaChave("chave-real-123456", { ...ENV, EWC_KEY: "" }), null);
});

test("aplicar substitui só o serviço gravado e carimba _ts", () => {
  const atual = { records: { Pinterest: { v1_code: "1", _ts: 10 } } };
  const r = aplicar(atual, "Zalando", { v1_code: "3" }, 0, 1000);
  assert.equal(r.conflito, false);
  assert.deepEqual(r.dados.records.Pinterest, { v1_code: "1", _ts: 10 });
  assert.equal(r.dados.records.Zalando.v1_code, "3");
  assert.equal(r.dados.records.Zalando.service, "Zalando");
  assert.equal(r.dados.records.Zalando._ts, 1000);
  assert.equal(r._ts, 1000);
  assert.equal(atual.records.Zalando, undefined, "não altera o objeto de entrada");
});

test("aplicar recusa quando o servidor tem versão mais nova que a vista", () => {
  const atual = { records: { Zalando: { v1_code: "2", _ts: 500 } } };
  const r = aplicar(atual, "Zalando", { v1_code: "3" }, 400, 1000);
  assert.equal(r.conflito, true);
  assert.deepEqual(r.registro, { v1_code: "2", _ts: 500 });
});

test("aplicar aceita quando a versão vista é a do servidor", () => {
  const atual = { records: { Zalando: { v1_code: "2", _ts: 500 } } };
  const r = aplicar(atual, "Zalando", { v1_code: "3" }, 500, 1000);
  assert.equal(r.conflito, false);
  assert.equal(r.dados.records.Zalando._ts, 1000);
});

test("aplicar nunca devolve _ts menor ou igual ao anterior", () => {
  const atual = { records: { Zalando: { _ts: 5000 } } };
  const r = aplicar(atual, "Zalando", {}, 5000, 1000); // relógio atrasado
  assert.equal(r._ts, 5001);
});

// --- handler com um GitHub de mentira -------------------------------------
function githubFalso(inicial = {}) {
  const arquivos = new Map(Object.entries(inicial)); // path -> {content, sha}
  let n = 0;
  const chamadas = [];
  const fetchImpl = async (url, opts = {}) => {
    const u = new URL(url);
    const path = decodeURIComponent(u.pathname.split("/contents/")[1]);
    chamadas.push({ method: opts.method || "GET", path });
    if ((opts.method || "GET") === "GET") {
      const a = arquivos.get(path);
      if (!a) return new Response("{}", { status: 404 });
      return Response.json({ sha: a.sha, content: Buffer.from(a.content).toString("base64") });
    }
    const body = JSON.parse(opts.body);
    const a = arquivos.get(path);
    if (a && body.sha !== a.sha) return new Response("{}", { status: 409 });
    arquivos.set(path, { content: Buffer.from(body.content, "base64").toString("utf8"), sha: `sha${++n}` });
    return Response.json({ ok: true });
  };
  return { fetchImpl, arquivos, chamadas };
}

function req(method, { chave, body } = {}) {
  return { method, headers: chave ? { "x-ewc-key": chave } : {}, body };
}
function res() {
  const r = { codigo: 0, corpo: null, cabecalhos: {} };
  r.status = (c) => { r.codigo = c; return r; };
  r.json = (b) => { r.corpo = b; return r; };
  r.setHeader = (k, v) => { r.cabecalhos[k] = v; };
  return r;
}

test("sem chave: 401, e o GitHub não é chamado", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  const r = res();
  await h(req("GET"), r);
  assert.equal(r.codigo, 401);
  assert.equal(gh.chamadas.length, 0);
});

test("GET com chave de ensaio lê o arquivo de ensaio e informa o modo", async () => {
  const gh = githubFalso({ "audit/ensaio-progress.json": { content: '{"records":{"X":{"_ts":1}}}', sha: "a" } });
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  const r = res();
  await h(req("GET", { chave: ENV.EWC_KEY_ENSAIO }), r);
  assert.equal(r.codigo, 200);
  assert.equal(r.corpo.modo, "ensaio");
  assert.deepEqual(r.corpo.records, { X: { _ts: 1 } });
  assert.equal(gh.chamadas[0].path, "audit/ensaio-progress.json");
});

test("GET com chave real lê o arquivo real; arquivo ausente vale vazio", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  const r = res();
  await h(req("GET", { chave: ENV.EWC_KEY }), r);
  assert.equal(r.codigo, 200);
  assert.deepEqual(r.corpo.records, {});
  assert.equal(r.corpo.modo, "real");
  assert.equal(gh.chamadas[0].path, "audit/coder2-progress.json");
});

test("PUT grava um serviço, devolve _ts e vira um commit", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl, agora: () => 7000 });
  const r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY, body: { servico: "Zalando", registro: { v1_code: "3" }, base_ts: 0 } }), r);
  assert.equal(r.codigo, 200);
  assert.equal(r.corpo.ok, true);
  assert.equal(r.corpo._ts, 7000);
  const gravado = JSON.parse(gh.arquivos.get("audit/coder2-progress.json").content);
  assert.equal(gravado.records.Zalando.v1_code, "3");
  assert.equal(gravado.records.Zalando._ts, 7000);
  assert.ok(gravado.saved_at);
});

test("PUT com base_ts velho: 409 com o registro do servidor, sem gravar", async () => {
  const gh = githubFalso({ "audit/coder2-progress.json": { content: '{"records":{"Zalando":{"v1_code":"2","_ts":500}}}', sha: "a" } });
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  const r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY, body: { servico: "Zalando", registro: { v1_code: "3" }, base_ts: 400 } }), r);
  assert.equal(r.codigo, 409);
  assert.equal(r.corpo.conflito, true);
  assert.equal(r.corpo.registro.v1_code, "2");
  assert.equal(gh.chamadas.filter((c) => c.method === "PUT").length, 0);
});

test("PUT malformado: 400", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  for (const body of [undefined, {}, { servico: "", registro: {} }, { servico: "Z", registro: "x" }]) {
    const r = res();
    await h(req("PUT", { chave: ENV.EWC_KEY, body }), r);
    assert.equal(r.codigo, 400, JSON.stringify(body));
  }
});

test("PUT aceita corpo como string JSON (como a Vercel às vezes entrega)", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl, agora: () => 1 });
  const r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY, body: JSON.stringify({ servico: "Z", registro: { a: 1 }, base_ts: 0 }) }), r);
  assert.equal(r.codigo, 200);
});

test("PUT com sha desatualizado no GitHub: relê e tenta de novo uma vez", async () => {
  const gh = githubFalso({ "audit/coder2-progress.json": { content: '{"records":{}}', sha: "a" } });
  let primeiro = true;
  const original = gh.fetchImpl;
  const fetchImpl = async (url, opts = {}) => {
    if ((opts.method || "GET") === "PUT" && primeiro) { primeiro = false; return new Response("{}", { status: 409 }); }
    return original(url, opts);
  };
  const h = criarHandler({ env: ENV, fetchImpl });
  const r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY, body: { servico: "Z", registro: { a: 1 }, base_ts: 0 } }), r);
  assert.equal(r.codigo, 200);
  assert.equal(JSON.parse(gh.arquivos.get("audit/coder2-progress.json").content).records.Z.a, 1);
});

test("DELETE zera só o ensaio; no real é 405", async () => {
  const gh = githubFalso({
    "audit/ensaio-progress.json": { content: '{"records":{"X":{"_ts":1}}}', sha: "a" },
    "audit/coder2-progress.json": { content: '{"records":{"Y":{"_ts":1}}}', sha: "b" },
  });
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  let r = res();
  await h(req("DELETE", { chave: ENV.EWC_KEY_ENSAIO }), r);
  assert.equal(r.codigo, 200);
  assert.deepEqual(JSON.parse(gh.arquivos.get("audit/ensaio-progress.json").content).records, {});
  r = res();
  await h(req("DELETE", { chave: ENV.EWC_KEY }), r);
  assert.equal(r.codigo, 405);
  assert.deepEqual(JSON.parse(gh.arquivos.get("audit/coder2-progress.json").content).records, { Y: { _ts: 1 } });
});

test("GITHUB_TOKEN ausente: 503 antes de qualquer coisa", async () => {
  const h = criarHandler({ env: { ...ENV, GITHUB_TOKEN: "" }, fetchImpl: async () => { throw new Error("não devia chamar"); } });
  const r = res();
  await h(req("GET", { chave: ENV.EWC_KEY }), r);
  assert.equal(r.codigo, 503);
});

test("erro do GitHub vira 502 com mensagem", async () => {
  const h = criarHandler({ env: ENV, fetchImpl: async () => new Response("{}", { status: 500 }) });
  const r = res();
  await h(req("GET", { chave: ENV.EWC_KEY }), r);
  assert.equal(r.codigo, 502);
  assert.match(r.corpo.error, /GitHub GET 500/);
});
```

**Step 2: rodar e ver falhar**

Run: `cd ~/Documents/UFPR/PPGCD/Papers/experimented-without-consent && node --test server/`
Expected: falha com `Cannot find module './state-core.mjs'`.

**Step 3: implementar**

```js
// server/state-core.mjs
// Núcleo do /api/state, sem nada da Vercel: recebe env, fetch e relógio por
// parâmetro para o teste rodar com um GitHub de mentira. O que muda em relação
// ao servidor anterior (julho): chave obrigatória, gravação por serviço com
// controle de versão (_ts) e um segundo arquivo para o modo ensaio.
import { timingSafeEqual } from "node:crypto";

const CAMINHOS = { real: "GH_PATH", ensaio: "GH_PATH_ENSAIO" };
const PADRAO = { real: "audit/coder2-progress.json", ensaio: "audit/ensaio-progress.json" };

function igual(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && timingSafeEqual(x, y);
}

export function modoDaChave(chave, env) {
  if (!chave) return null;
  if (env.EWC_KEY && igual(chave, env.EWC_KEY)) return "real";
  if (env.EWC_KEY_ENSAIO && igual(chave, env.EWC_KEY_ENSAIO)) return "ensaio";
  return null;
}

export function aplicar(atual, servico, registro, baseTs, agora) {
  const records = { ...((atual && atual.records) || {}) };
  const existente = records[servico];
  const tsServidor = (existente && Number(existente._ts)) || 0;
  if (tsServidor > (Number(baseTs) || 0)) return { conflito: true, registro: existente };
  const _ts = Math.max(agora, tsServidor + 1);
  records[servico] = { ...registro, service: servico, _ts };
  return { conflito: false, dados: { records, saved_at: new Date(agora).toISOString() }, _ts };
}

export function criarHandler({ env, fetchImpl, agora = () => Date.now() }) {
  const repo = env.GH_REPO || "mrcsvg/experimented-without-consent";
  const branch = env.GH_BRANCH || "coder2-data";
  const api = (path) => `https://api.github.com/repos/${repo}/contents/${path}`;
  const gh = (url, opts = {}) => fetchImpl(url, {
    ...opts,
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "assistente-coder2",
      ...(opts.headers || {}),
    },
  });

  async function ler(path) {
    const r = await gh(`${api(path)}?ref=${branch}`);
    if (r.status === 404) return { sha: null, dados: { records: {} } };
    if (!r.ok) throw new Error(`GitHub GET ${r.status}`);
    const j = await r.json();
    return { sha: j.sha, dados: JSON.parse(Buffer.from(j.content, "base64").toString("utf8")) };
  }

  async function escrever(path, dados, sha, mensagem) {
    const body = {
      message: mensagem,
      content: Buffer.from(JSON.stringify(dados, null, 1)).toString("base64"),
      branch,
      ...(sha ? { sha } : {}),
    };
    return gh(api(path), { method: "PUT", body: JSON.stringify(body) });
  }

  // Lê, aplica e grava; se o sha ficou velho entre a leitura e a escrita,
  // relê e repete uma vez. `montar(atual)` devolve {dados, resposta} ou {recusa}.
  async function transacao(path, montar) {
    for (let tentativa = 0; tentativa < 2; tentativa++) {
      const { sha, dados: atual } = await ler(path);
      const m = montar(atual);
      if (m.recusa) return m.recusa;
      const r = await escrever(path, m.dados, sha, m.mensagem);
      if (r.ok) return { status: 200, corpo: m.resposta };
      if (r.status !== 409 && r.status !== 422) throw new Error(`GitHub PUT ${r.status}`);
    }
    throw new Error("GitHub PUT: conflito de sha duas vezes seguidas");
  }

  return async function handler(req, res) {
    if (!env.GITHUB_TOKEN) return res.status(503).json({ error: "GITHUB_TOKEN não configurado" });
    const modo = modoDaChave(req.headers && req.headers["x-ewc-key"], env);
    if (!modo) return res.status(401).json({ error: "chave ausente ou inválida" });
    const path = env[CAMINHOS[modo]] || PADRAO[modo];
    try {
      if (req.method === "GET") {
        const { dados } = await ler(path);
        return res.status(200).json({ ...dados, modo });
      }
      if (req.method === "PUT") {
        let b = req.body;
        if (typeof b === "string") { try { b = JSON.parse(b); } catch { b = null; } }
        if (!b || typeof b !== "object" || typeof b.servico !== "string" || !b.servico
            || !b.registro || typeof b.registro !== "object" || Array.isArray(b.registro))
          return res.status(400).json({ error: "esperado {servico, registro, base_ts}" });
        const t = agora();
        const r = await transacao(path, (atual) => {
          const a = aplicar(atual, b.servico, b.registro, b.base_ts, t);
          if (a.conflito) return { recusa: { status: 409, corpo: { conflito: true, registro: a.registro } } };
          return { dados: a.dados, resposta: { ok: true, _ts: a._ts, modo },
                   mensagem: `coder2 (${modo}): ${b.servico} ${new Date(t).toISOString()}` };
        });
        return res.status(r.status).json(r.corpo);
      }
      if (req.method === "DELETE") {
        if (modo !== "ensaio") return res.status(405).json({ error: "só o ensaio pode ser zerado" });
        const r = await transacao(path, () => ({
          dados: { records: {}, saved_at: new Date(agora()).toISOString() },
          resposta: { ok: true, modo }, mensagem: "ensaio zerado",
        }));
        return res.status(r.status).json(r.corpo);
      }
      res.setHeader("allow", "GET, PUT, DELETE");
      return res.status(405).json({ error: "método não suportado" });
    } catch (e) {
      return res.status(502).json({ error: String(e.message || e) });
    }
  };
}
```

**Step 4: rodar e ver passar**

Run: `node --test server/`
Expected: todos `ok`, 0 falhas.

**Step 5: commit**

```bash
git add server/state-core.mjs server/state-core.test.mjs
git commit -m "Servidor: núcleo puro com chave, gravação por serviço e ensaio

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Tarefa 2: ligar o núcleo à função da Vercel

**Files:**
- Modify: `api/state.js` (reescrever inteiro)
- Create: `.vercelignore`

**Step 1: reescrever `api/state.js`**

```js
// Persistência do 2º codificador: proxy fino para a GitHub Contents API.
// Toda a lógica está em ../server/state-core.mjs, que roda em teste sem Vercel.
//
// Env (Vercel): GITHUB_TOKEN (PAT fine-grained, Contents R/W neste repo),
//               EWC_KEY (chave do link real), EWC_KEY_ENSAIO (chave do link de ensaio).
// Opcionais:    GH_REPO · GH_BRANCH (coder2-data) · GH_PATH (audit/coder2-progress.json)
//               · GH_PATH_ENSAIO (audit/ensaio-progress.json)
//
// Cada gravação vira um commit no ramo coder2-data: backup, sincronização
// entre máquinas e trilha de quando cada codificação mudou.
import { criarHandler } from "../server/state-core.mjs";

const handler = criarHandler({ env: process.env, fetchImpl: fetch });
export default handler;
```

**Step 2: `.vercelignore`** (só o que o site precisa sobe: página, `assistente/`, `api/`, `server/`)

```
analysis/
notebooks/
protocol/
docs/
instrument/
server/*.test.mjs
assistente/*.test.mjs
assistente/test/
*.md
CITATION.cff
LICENSE
LICENSE-DATA
.claude/
```

**Step 3: conferir que o import resolve em Node**

Run: `node -e "import('./api/state.js').then(m => console.log(typeof m.default))"`
Expected: `function`.

**Step 4: commit**

```bash
git add api/state.js .vercelignore
git commit -m "api/state usa o núcleo testado; .vercelignore deixa só o site subir

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Tarefa 3: chaves, ambiente local e teste do servidor de verdade

Nenhuma chave aparece no chat. A real vai só para o Keychain e para a Vercel. A de ensaio pode aparecer (ela só grava no arquivo de ensaio).

**Step 1: gerar e guardar as chaves**

```bash
cd ~/Documents/UFPR/PPGCD/Papers/experimented-without-consent
REAL="$(openssl rand -hex 16)"; ENSAIO="$(openssl rand -hex 16)"
security add-generic-password -U -s ewc-coder2-key -a real -w "$REAL"
security add-generic-password -U -s ewc-coder2-key -a ensaio -w "$ENSAIO"
for amb in production preview development; do
  printf %s "$REAL"   | vercel env add EWC_KEY "$amb" --force
  printf %s "$ENSAIO" | vercel env add EWC_KEY_ENSAIO "$amb" --force
done
unset REAL ENSAIO
```
Expected: `Added Environment Variable` seis vezes. Nada impresso além disso.

**Step 2: ambiente local**

```bash
vercel env pull .env.local --environment development --yes
grep -c "EWC_KEY" .env.local    # esperado: 2
git check-ignore .env.local      # esperado: .env.local (está no .gitignore)
```

**Step 3: subir `vercel dev` e bater com curl**

Criar `.claude/launch.json` no repo do paper (é o cwd da sessão):
```json
{ "version": "0.0.1", "configurations": [ {
  "name": "assistente",
  "runtimeExecutable": "sh",
  "runtimeArgs": ["-c", "cd ../experimented-without-consent && vercel dev --listen 3000 --yes"],
  "port": 3000 } ] }
```
Subir com `preview_start name=assistente`. Depois:
```bash
K="$(security find-generic-password -s ewc-coder2-key -a ensaio -w)"
curl -s -o /dev/null -w "sem chave: %{http_code}\n" http://localhost:3000/api/state
curl -s -H "x-ewc-key: $K" http://localhost:3000/api/state; echo
curl -s -X PUT -H "x-ewc-key: $K" -H "content-type: application/json" \
  -d '{"servico":"Zalando","registro":{"v1_code":"3"},"base_ts":0}' http://localhost:3000/api/state; echo
curl -s -X PUT -H "x-ewc-key: $K" -H "content-type: application/json" \
  -d '{"servico":"Zalando","registro":{"v1_code":"1"},"base_ts":0}' http://localhost:3000/api/state; echo
curl -s -X DELETE -H "x-ewc-key: $K" http://localhost:3000/api/state; echo
gh api "repos/mrcsvg/experimented-without-consent/commits?sha=coder2-data&per_page=3" --jq '.[].commit.message'
```
Expected: `401`; `{"records":{},"modo":"ensaio"}`; `{"ok":true,"_ts":...,"modo":"ensaio"}`; `{"conflito":true,"registro":{...}}`; `{"ok":true,"modo":"ensaio"}`; commits `ensaio zerado` e `coder2 (ensaio): Zalando ...`.

Se o `vercel dev` reclamar de `.mjs` fora de `api/`, mover o núcleo para `api/_lib/state-core.mjs` (a Vercel não publica como função o que começa com `_`) e ajustar o import e o teste.

**Step 4: commit** (`.claude/launch.json` fica no repo do paper; conferir se `.claude/` está versionado lá antes de commitar).

---

## Tarefa 4: o instrumento antigo sai da raiz

**Files:**
- Move: `index.html` → `instrument/index.html`
- Modify: `analysis/codebook.py:39`, e todo script que referencia `index.html` na raiz

**Step 1: mover e achar referências**

```bash
git mv index.html instrument/index.html
grep -rn "index.html" analysis/*.py README.md | grep -v "gerar-notebook"
```

**Step 2: ajustar caminhos.** Em `codebook.py`: `HTML = Path(__file__).resolve().parent.parent / "instrument" / "index.html"`. Mesmo ajuste em `inject-frozen.py` (alvo da injeção) e em `publicar-corpus.py` / `pre-entrega.py` (as duas serão reescritas nas tarefas 9 e 15; aqui só o suficiente para não quebrar o `--check`).

**Step 3: conferir**

Run: `python3 analysis/codebook.py --check && python3 analysis/congelar-sugestoes.py --simular && python3 analysis/coding_flow.py --self-test | tail -2`
Expected: os três passam como antes.

**Step 4: commit**

```bash
git add -A
git commit -m "Instrumento antigo vai para instrument/: a raiz passa a ser o assistente

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Tarefa 5: `exportar-codebook.py` → `assistente/codebook.json`

**Files:**
- Create: `analysis/exportar-codebook.py`
- Output: `../experimented-without-consent-corpus/assistente/codebook.json`

**Formato de saída:**
```json
{
  "gerado_em": "...", "congelado_em": "2026-07-04", "fonte_crit": "texto exato do codebook v2, congelado em 04/07/2026",
  "servicos": ["AliExpress", "..."],
  "variaveis": [
    {"vid": "V1", "titulo": "Reconhecimento de experimentação", "regra": "...",
     "pergunta": "...", "lembrete": "...", "guia_html": "...", "crit_html": "...", "crit_sha": "...",
     "campos": [{"chave": "v1_code", "rotulo": "...", "tipo": "select", "opcoes": ["", "0", "1", "2", "3"], "placeholder": ""}]}
  ],
  "termos": [{"term": "experiment", "flag": null}, ...],
  "termo_para_variavel": {"experiment": ["V1", "V3"], ...},
  "regras_gerais_html": "..."
}
```
`crit_sha` é o SHA de `CRIT_CONGELADO`, para a página poder dizer "texto congelado, hash ...". Nenhuma âncora do piloto (`ANCHORS`) e nenhum nome de serviço entram.

**Step 1: self-test que falha** (`--self-test` no próprio script, no estilo do repositório): gera para um diretório temporário e afirma: 10 variáveis na ordem V1..V9, KW; 26 serviços; toda variável tem `pergunta`, `lembrete`, `guia_html`, `crit_html` não vazios; `crit_sha` bate com `C.CRIT_CONGELADO`; a string "ANCHORS" e nenhum nome de `C.SERVICOS` aparecem em `guia_html`/`crit_html`; `termo_para_variavel` igual a `R.TERMO_PARA_VARIAVEL`.

**Step 2: rodar, ver falhar; Step 3: implementar** lendo de `codebook.py` e `revisao.py` (`_regras_gerais(corpus)` precisa de um `Corpus`; passar `R.Corpus("../experimented-without-consent-corpus/md")`). HTML da glosa vem de `C.glosa_criterio(v).html`... conferir a API real antes (`python3 -c "import analysis.codebook as C; print(C.glosa_criterio('v1'))"`).

**Step 4: gerar e conferir**

```bash
python3 analysis/exportar-codebook.py --self-test
python3 analysis/exportar-codebook.py --corpus ../experimented-without-consent-corpus/md \
  --out ../experimented-without-consent-corpus/assistente/codebook.json
python3 -c "import json; d=json.load(open('../experimented-without-consent-corpus/assistente/codebook.json')); print(len(d['variaveis']), len(d['servicos']))"
```
Expected: `10 26`.

**Step 5: commit** (só no repo do instrumento por enquanto; o corpus é commitado na tarefa 9).

---

## Tarefa 6: `exportar-piso.py` → `assistente/piso/<slug>.json`

**Files:**
- Create: `analysis/exportar-piso.py`
- Output: `../experimented-without-consent-corpus/assistente/piso/<slug>.json` (26) e `index.json`

**Formato por serviço:**
```json
{"servico": "Wikipedia", "slug": "wikipedia", "gerado_em": "...", "corpus_built_at": "...",
 "docs": [{"n": 1, "file": "wikipedia/01-....md", "url": "https://...", "chars": 54842,
           "titulo": "Wikimedia Foundation Privacy Policy", "counts": {"experiment": 3}, "log_line": "experiment:3 / test:2"}],
 "por_variavel": {"V1": [{"termo": "experiment", "kwic": "...", "flag": null, "file": "...", "n": 1, "total_no_doc": 3}]},
 "log_sugerido": "01-wiki-policy-privacy-policy.md: experiment:3 / test:2\n02-...: ..."}
```
Sem `role` em lugar nenhum. `titulo` = primeira linha não vazia do corpo depois do front matter, até 120 caracteres. `log_sugerido` segue `coding_flow.Fluxo.log_sugerido` (nome do arquivo e `termo:n` separados por ` / `).

**Step 1: self-test que falha**: para um serviço real do corpus local, afirma: `docs` tem o mesmo número que `md/index.json`; nenhum `role` no JSON serializado; `por_variavel` só tem chaves de `R.TERMO_PARA_VARIAVEL` (valores); cada hit tem `kwic` não vazio e `n` que existe em `docs`; `log_sugerido` tem uma linha por documento com texto; títulos não vazios.

**Step 2–3: implementar** com `R.Corpus`, `R.varredura`, `R.piso`. Reutilizar `R.piso(servico, corpus, dossie=dossie)` para não varrer duas vezes.

**Step 4: gerar os 26 e conferir**

```bash
python3 analysis/exportar-piso.py --self-test
python3 analysis/exportar-piso.py --corpus ../experimented-without-consent-corpus/md --out ../experimented-without-consent-corpus/assistente/piso
ls ../experimented-without-consent-corpus/assistente/piso | wc -l   # 27 (26 + index.json)
grep -l '"role"' ../experimented-without-consent-corpus/assistente/piso/*.json | wc -l   # 0
```

**Step 5: commit** no repo do instrumento.

---

## Tarefa 7: `copiloto.py`: prompt, validação e simulação (sem gastar)

**Files:**
- Create: `analysis/copiloto.py`
- Output (tarefa 8): `../experimented-without-consent-corpus/assistente/copiloto/<slug>.json`, `prompt.md`, `index.json`

**O prompt do sistema** (texto exato; o SHA dele vai no arquivo e na página de transparência):

```
Você é o copiloto de um codificador humano num estudo documental. O estudo
classifica o que plataformas online declaram sobre experimentação com os
próprios usuários, e em que tipo de documento declaram.

Para um serviço de cada vez, você recebe: o codebook (o critério congelado e o
guia de cada variável), citações copiadas palavra por palavra dos documentos
congelados do serviço, cada uma com um identificador, e a contagem de 12
palavras-chave por documento. Você propõe um valor para cada campo de cada
variável, com uma razão curta.

Regras:
1. Só o material fornecido conta. Não use conhecimento externo sobre a plataforma.
2. Cada razão cita as citações usadas pelos identificadores (por exemplo V1-2).
   Se nenhuma citação sustenta outra resposta, proponha a resposta de ausência
   prevista no codebook (0, No, none, not stated) e escreva na razão: "nenhuma
   citação sustenta outra resposta".
3. Os valores vêm da lista de opções de cada campo, escritos exatamente como na
   lista. Campo de múltipla escolha recebe uma lista. Campo de linha recebe
   texto curto, ou vazio.
4. Para decidir se um documento é vinculante, use a função do documento, pela
   URL e pelo título: política de privacidade, termos de uso e tabela de bases
   legais obrigam a plataforma; blog, central de ajuda e material de imprensa
   não obrigam.
5. Na variável V4, campo v4_region_gated: quando os documentos não trazem
   tabela de bases legais por finalidade, a resposta é "not-verifiable
   (vantage)", nunca "No".
6. Confiança: "alta" quando a citação diz literalmente o que o campo pergunta;
   "média" quando exige interpretação; "baixa" quando a evidência é indireta
   ou ambígua.
7. A decisão é do codificador humano. Você sugere. Não insista e não use
   linguagem persuasiva.
8. Responda só com JSON, no formato pedido. Razões em português, com no máximo
   duas frases.
```

**A mensagem do usuário**, montada por `montar_mensagem(servico, codebook, citacoes, piso)`:
1. "SERVIÇO: <nome>".
2. "DOCUMENTOS:" lista `n. <titulo> <url> (<chars> caracteres)`, sem `role`.
3. "CONTAGEM DE PALAVRAS-CHAVE POR DOCUMENTO:" uma linha por documento com `log_line`.
4. "CODEBOOK:" para cada variável V1..V9 (KW fora): `[Vn] título`, `Pergunta: ...`, `Critério congelado: <texto do CRIT sem HTML>`, `Guia: <texto da glosa sem HTML>`, `Campos:` uma linha por campo que não é `text`: `chave (tipo): opções`.
5. "CITAÇÕES:" para cada variável, cada citação como `Vn-i (documento n, <onde>): "<verbatim>"`.
6. "FORMATO DA RESPOSTA:" o JSON esperado:
```json
{"V1": {"campos": {"v1_code": "2", "v1_register": "both"}, "razao": "...", "confianca": "média", "citacoes": ["V1-2"]}, "...": "..."}
```

**Validação** (`validar(resposta, codebook, ids_validos) -> list[str]` de problemas, vazia se ok): toda variável V1..V9 presente; todo campo select/checks/line presente em `campos`; select com valor em `opcoes` e diferente de `""`; checks com lista não vazia, subconjunto de `opcoes`; line string até 200 caracteres; `confianca` em {alta, média, baixa}; `razao` string até 400 caracteres; `citacoes` lista de ids existentes. Resposta com cerca de código (```json) é limpa antes do `json.loads`.

**Campos de texto** (`*_evidence`, `v8_note`): não são pedidos ao modelo. A página os preenche a partir das citações indicadas em `citacoes` (tarefa 10).

**Step 1: `--simular` que falha**: com um cliente falso que devolve uma resposta canônica válida, afirma:
- `montar_mensagem` não contém `role`, `binding`, `vinculante`, `[` seguido de `vinculante`; contém "V1-1" e o nome do serviço; não contém nenhuma anotação do instrumento antigo (basta afirmar que não contém a string "codificado em" nem "passada 1");
- `validar` aceita a resposta canônica; rejeita valor fora das opções, checks vazio, variável ausente, id de citação inexistente;
- `gerar_um` com o cliente falso devolve o registro com `modelo`, `prompt_sha` (12 hex), `gerado_em`, `entrada_sha`, `variaveis` com 9 chaves e `uso`;
- `prompt_md()` contém o texto do sistema e a descrição da mensagem.

**Step 2: rodar e ver falhar. Step 3: implementar.** Cliente real: `R._cliente()` (lê `EWC_ANTHROPIC_KEY`). Modelo padrão `claude-opus-5-5`, parâmetro `--modelo`. Resposta inválida: repetir uma vez com a lista de problemas anexada à mensagem; se ainda inválida, gravar `{"invalida": [...]}` para aquele serviço e seguir. `--estimar` imprime a soma de `count_tokens` dos 26 antes de gastar.

**Step 4: `python3 analysis/copiloto.py --simular`** → passa. **Step 5: commit.**

---

## Tarefa 8: rodar o copiloto de verdade e publicar

**Step 1: estimar**

```bash
cd ~/Documents/UFPR/PPGCD/Papers/experimented-without-consent
EWC_ANTHROPIC_KEY="$(security find-generic-password -s ewc-anthropic-key -w)" \
python3 analysis/copiloto.py --corpus ../experimented-without-consent-corpus/md --estimar
```
Expected: tokens de entrada por serviço (ordem de 10 a 20 mil) e o total.

**Step 2: um serviço só, ler o resultado com olhos humanos**

```bash
EWC_ANTHROPIC_KEY="$(security find-generic-password -s ewc-anthropic-key -w)" \
python3 analysis/copiloto.py --corpus ../experimented-without-consent-corpus/md \
  --out ../experimented-without-consent-corpus/assistente/copiloto --so Wikipedia
python3 -c "import json; d=json.load(open('../experimented-without-consent-corpus/assistente/copiloto/wikipedia.json')); [print(v, x['campos'], x['confianca'], '|', x['razao']) for v,x in d['variaveis'].items()]"
```
Conferir: valores dentro das opções, razões curtas em português, ids de citação coerentes. Se o modelo `claude-opus-5-5` não existir para a conta, repetir com `--modelo claude-opus-5` e registrar.

**Step 3: os 26** (mesmo comando sem `--so`). Depois `python3 analysis/copiloto.py --out ../experimented-without-consent-corpus/assistente/copiloto --check` → 26 arquivos válidos, 0 inválidos, `prompt.md` e `index.json` presentes.

**Step 4: commit** no repo do instrumento (`analysis/copiloto.py` já foi; aqui nada muda além do que a tarefa 9 publica).

---

## Tarefa 9: publicar no site do corpus e tirar `lib/` do ar

**Files (repo do corpus):**
- Add: `assistente/codebook.json`, `assistente/piso/*.json`, `assistente/copiloto/*.json`, `assistente/copiloto/prompt.md`, `assistente/manifest.json`
- Delete: `lib/` (runtime do notebook e cópia do instrumento antigo com anotações da passada 1)
- Modify: `vercel.json` (acrescentar `Content-Type: text/plain; charset=utf-8` para `/md/(.*)`, para o link de download abrir no navegador)

**Files (repo do instrumento):**
- Modify: `analysis/publicar-corpus.py`: remover `publicar_runtime` e a cópia de `index.html`; acrescentar `publicar_assistente(destino)` que escreve `assistente/manifest.json` com sha256 de cada arquivo de `assistente/`, e `--check` que confere o manifesto contra os arquivos.

**Step 1:** ajustar `publicar-corpus.py` (self-test ou `--check` cobre o manifesto). **Step 2:** rodar `python3 analysis/publicar-corpus.py --destino ../experimented-without-consent-corpus --check`. **Step 3:** no repo do corpus: `git rm -r lib && git add assistente vercel.json && git commit && git push origin main`. **Step 4:** conferir no ar:

```bash
S=https://experimented-without-consent-corpus.vercel.app
curl -s -o /dev/null -w "codebook %{http_code}\n" $S/assistente/codebook.json
curl -s -o /dev/null -w "piso %{http_code}\n" $S/assistente/piso/wikipedia.json
curl -s -o /dev/null -w "copiloto %{http_code}\n" $S/assistente/copiloto/wikipedia.json
curl -s -o /dev/null -w "lib (deve ser 404): %{http_code}\n" $S/lib/index.html
curl -s -D - -o /dev/null $S/md/wikipedia/01-wiki-policy-privacy-policy.md | grep -i content-type
```

**Step 5: commit** no repo do instrumento.

---

## Tarefa 10: núcleo da página, puro e testado (`assistente/core.mjs`)

**Files:**
- Create: `assistente/core.mjs`, `assistente/core.test.mjs`
- Create: `analysis/fixtures-portao.py` → `assistente/test/portao.json` (casos gerados pelo `coding_flow.Fluxo.faltando`, para o JS reproduzir a trava do Python)

**API do módulo:**
```js
export const LINE_EXIGIDA = { v6_which: ["v6_optin_beta", "Yes"] };
export function faltando(variavel, reg)            // [[chave, motivo], ...] igual ao Python
export function fechados(codebook, reg)            // {V1: true, ...}
export function progresso(codebook, reg)           // {feitas, total}
export function concluido(codebook, reg)           // bool
export function primeiroIncompleto(codebook, reg)  // índice em codebook.variaveis (último se tudo fechado)
export function proximoServico(codebook, records, atual) // próximo incompleto depois de `atual` na ordem; dá a volta; null se nenhum
export function logSugerido(piso)                  // piso.log_sugerido, ou monta a partir de docs[].log_line
export function textoDeEvidencia(citacao, docs)    // `“verbatim” (Documento n: título, onde)`
export function aplicarSugestao(variavel, reg, sugestao, citacoesPorId, docs) // novo reg: campos + text fields preenchidos
export function chaveDoLink(hash)                  // "#k=abc" → "abc"; "" → null
export function mesclar(local, servidor)           // por serviço, _ts maior vence; devolve {records, pendentes:[servicos locais mais novos]}
```

**Step 1: fixtures do portão**

```bash
python3 analysis/fixtures-portao.py --out assistente/test/portao.json
```
O script monta, para cada variável, registros parciais: vazio; só select; select + evidência; checks vazio; `v6_optin_beta=Yes` sem `v6_which`; `v6_optin_beta=No` sem `v6_which`; KW vazio e preenchido. Grava `[{vid, reg, esperado: faltando}]` usando `coding_flow.Fluxo` com um `Estado` offline.

**Step 2: testes que falham** (`node --test assistente/`): um teste que percorre `portao.json` e compara `faltando(variavel, reg)` com `esperado`; testes diretos para `proximoServico` (dá a volta; devolve null quando todos concluídos), `primeiroIncompleto` (tudo fechado → último), `aplicarSugestao` (preenche select/checks/line; `v1_evidence` recebe as citações indicadas; sem citações, recebe a `razao`; não apaga campos que a sugestão não menciona), `textoDeEvidencia` (sem travessão), `chaveDoLink`, `mesclar` (local mais novo vira pendente; servidor mais novo vence; serviço só local vira pendente).

**Step 3: implementar. Step 4: passar. Step 5: commit.**

---

## Tarefa 11: a página, em fatias com verificação no navegador

**Files:**
- Create: `index.html` (casca, CSS), `assistente/app.js` (DOM, fetch, armazenamento), `assistente/copiloto.html`
- Dados em tempo de execução: `const CORPUS = "https://experimented-without-consent-corpus.vercel.app"`; `md/index.json`, `assistente/codebook.json`, `assistente/piso/<slug>.json`, `sugestoes/<slug>.json`, `assistente/copiloto/<slug>.json`, `md/<file>`.

Cada fatia termina com: `preview_start name=assistente`, abrir `http://localhost:3000/#k=<chave de ensaio>` no navegador do app, conferir o que a fatia prometeu, e commit.

**Fatia A: casca, chave, carga e telas de entrada.**
- Sem `#k=`: tela "Este endereço precisa do link que você recebeu."; sem chamada ao servidor.
- Com chave: `GET /api/state`; 401 → "A chave deste link não é válida."; ok → guarda `modo`.
- `modo === "ensaio"`: faixa amarela fixa no topo "Ensaio: nada aqui conta" com o botão "zerar ensaio" (confirmação em duas etapas, chama `DELETE`).
- Primeira vez (`localStorage.ewc_viu_abertura` ausente): tela de contexto com o texto da abertura (reescrito de `gerar-notebook-revisao.ABERTURA`: "notebook" vira "página", "célula" some, "Codifique só por esta página") e o botão "Começar".
- Depois: tela "Continuar" com a lista dos 26 serviços (concluído / em andamento n de 10 / não iniciado) e o botão grande "Continuar: <próximo incompleto>".
- Verificar: as quatro situações acima, no navegador.

**Fatia B: a tela da variável.**
- Cabeçalho: nome do serviço, "N documentos", lista de documentos (título, link "abrir texto congelado" que abre o visor da fatia F, URL original em letra menor), progresso "n de 10" e a trilha das dez etapas.
- Corpo: `[Vn] título`; a pergunta e o lembrete; botão "critério completo" que abre painel lateral com `guia_html` e, embaixo, `crit_html` com a nota "texto exato do codebook v2, congelado em 04/07/2026".
- Evidência: "Busca por palavra-chave: N trechos" (hits do piso para a variável, com a nota `flag` quando houver) e "Localizado pelo modelo: N citações" (de `sugestoes/`, só `verbatim`, `Documento n: título` e `onde`). Cada item tem "abrir no documento" e "usar como evidência" (acrescenta `textoDeEvidencia` ao campo de evidência, sem apagar o que já está lá).
- Campos: gerados de `codebook.variaveis[i].campos`: select → botões de rádio com rótulo; checks → caixas; line → input; text → textarea.
- Botões: "Voltar" (grava sem trava e volta), "Confirmar e seguir" (trava: lista o que falta em vermelho e não avança; passa: grava e avança). Ao lado, o recibo: "gravando…", "gravado às hh:mm", ou vermelho "não gravou: tentando de novo".
- Gravação: `salvar(servico)` monta `{servico, registro, base_ts}`; sucesso → `base_ts = _ts`; 409 → substitui o registro local pelo do servidor, mostra faixa "Este serviço foi alterado em outra janela. Recarreguei as respostas; confira e continue." e re-renderiza; falha de rede → marca pendente em `localStorage`, tenta de novo em 5 s, depois 10, 20, 30 s.
- Verificar: responder V1 com clique no trecho; recibo verde; recarregar e voltar ao mesmo ponto; `gh api .../audit/ensaio-progress.json?ref=coder2-data` mostra o serviço.

**Fatia C: palavras-chave e fim do serviço.**
- Etapa KW: textarea já preenchido com `logSugerido(piso)` quando o campo está vazio, e o texto "Corrija o que for falso positivo. O que ficar aqui é o registro do que você procurou."
- Depois da KW: tela de resumo com as dez respostas (valor e evidência resumida), "Voltar" e "Próximo serviço", desabilitado enquanto houver gravação pendente deste serviço ("aguardando gravação").
- Quando `proximoServico` devolve null: "Pronto. Os 26 serviços estão codificados. Obrigado."
- Verificar: fechar um serviço inteiro; resumo; próximo abre sozinho.

**Fatia D: o copiloto.**
- Botão "ver sugestão do copiloto" abaixo da evidência. Clique: caixa com `campos` (rótulo: valor), `confianca`, `razao`, as citações indicadas (verbatim curto) e o link "como o copiloto funciona" (`/assistente/copiloto.html`). Botão "aplicar sugestão" chama `aplicarSugestao` e re-renderiza os campos; o codificador ainda confirma.
- Sem arquivo ou variável `invalida`: "O copiloto não tem sugestão para esta variável."
- Verificar: abrir, aplicar, conferir campos e evidência preenchidos.

**Fatia E: notas.** Campo "Notas sobre este serviço" no fim da tela da variável, gravado junto com o registro (`notes`), com o botão "salvar notas" e recibo próprio.

**Fatia F: visor de documento.** Painel lateral que busca `md/<file>`, remove o front matter, mostra o corpo em `<pre>` com quebra de linha, destaca o trecho (`verbatim` ou `kwic`, comparados com espaços normalizados) com `<mark>` e rola até ele. Não achou: abre no topo com a nota "trecho não localizado automaticamente". Link "baixar o arquivo congelado" para a URL do md.

**Fatia G: `assistente/copiloto.html`.** Busca `assistente/copiloto/prompt.md` e `index.json` do corpus e mostra: modelo, data, SHA do prompt, o texto do sistema e a descrição da mensagem, e a frase "O copiloto recebeu só o texto congelado: nenhum código ou anotação da primeira codificação."

**Estilo:** uma coluna de até 820 px, fonte do sistema, botões grandes, contraste alto, funciona em 1024 px de largura. Sem travessão em texto nenhum (`grep -c "—" index.html assistente/app.js` → 0).

**Commit a cada fatia.**

---

## Tarefa 12: roteiro de teste completo no navegador real

Com `vercel dev` no ar e a chave de ensaio:

1. Zerar ensaio.
2. Primeira abertura: contexto → Começar → Continuar abre o primeiro serviço na V1.
3. Codificar o serviço inteiro clicando (dez etapas), com uma sugestão aplicada e uma evidência por clique no trecho. Recibo verde em todas.
4. Recarregar no meio (na V5): volta na V5 com V1–V4 preenchidas.
5. Conflito: com `curl`, gravar o mesmo serviço com `base_ts` atual; na página, Confirmar → faixa de conflito e registro recarregado.
6. Rede fora: parar o `vercel dev`, Confirmar → recibo vermelho; religar → fica verde sozinho; `gh api` mostra o commit.
7. Visor: abrir uma citação; o trecho aparece marcado.
8. Resumo → Próximo serviço → abre o seguinte.
9. Outro navegador (aba anônima do navegador do app, ou `curl`): o registro está lá.
10. `python3 analysis/compute-agreement.py` com `curl -s -H "x-ewc-key: $K" http://localhost:3000/api/state > /tmp/ensaio.json` como entrada do 2º codificador → roda sem erro (κ de um serviço não significa nada, mas o formato passa).

Cada item que falhar vira correção com teste antes de seguir. Registrar o resultado dos 10 itens no commit final da tarefa.

---

## Tarefa 13: `pre-entrega.py` para o assistente, e o fim dos notebooks

**Files:**
- Modify: `analysis/pre-entrega.py`: seções 2, 3 e 5 passam a conferir o assistente: `index.html` e `assistente/*.js` publicados iguais ao repositório (sha256 via curl), `assistente/manifest.json` do corpus bate com os arquivos, `/api/state` responde 401 sem chave, `node --test server/ assistente/` passa, nenhum `—` nos textos, nenhum `role` em `piso/`, nenhuma string de anotação da passada 1 nos arquivos publicados. Seção 6 (ponte até o κ) passa a montar o registro no formato que a página grava.
- Delete: `notebooks/04-revisao-assistida.ipynb`, `notebooks/05-ensaio.ipynb`, `analysis/gerar-notebook-revisao.py`, `analysis/teste-widgets-reais.py`.
- Modify: `README.md` (seção do 2º codificador: a página, o link, o ensaio, o copiloto), `CITATION.cff` se citar o notebook.

`revisao.py` fica (o `piso`, a `varredura`, o `Corpus` e o `sugerir` são usados pelos exportadores). A classe `Painel` e o código de ipywidgets saem numa tarefa própria depois do aceite, para não misturar.

Run: `python3 analysis/pre-entrega.py --completo` → todas as checagens passam. Commit.

---

## Tarefa 14: produção e o teste do Marcus

1. Descobrir como a produção é publicada: `vercel inspect https://experimented-without-consent.vercel.app 2>&1 | grep -i "git\|branch"`. Se vier de git (`main`): abrir PR do ramo `assistente-codificacao` para `main`, fechar o PR #8 com a nota "substituído por #N", mergear; a Vercel publica. Se não vier de git: `vercel --prod` depois do merge.
2. Conferir em produção: `curl -s -o /dev/null -w "%{http_code}\n" https://experimented-without-consent.vercel.app/api/state` → 401; a página abre sem `#k=` com a tela "precisa do link"; com a chave de ensaio, o fluxo da tarefa 12 itens 1–3 e 8 no navegador do app.
3. Entregar ao Marcus (via usuário) o roteiro de dez linhas e o comando que imprime o link de ensaio no terminal dele:
   ```bash
   echo "https://experimented-without-consent.vercel.app/#k=$(security find-generic-password -s ewc-coder2-key -a ensaio -w)"
   ```
4. Depois do aval do usuário: o comando do link real (`-a real`). Zerar o ensaio. Escopo congelado.

---

## Tarefa 15 (depois do aceite): limpeza

- Remover `Painel` e o código de ipywidgets de `revisao.py`, com os self-tests correspondentes; manter `piso`, `varredura`, `Corpus`, `sugerir`, `SISTEMA` (impressão `d45b11e32988` intocada).
- Atualizar `protocol/` e o README do corpus para apontar o `assistente/`.
- Memória e parágrafo da seção de confiabilidade do artigo (copiloto, prompts publicados, origem congelada das sugestões, exposição do instrumento de julho).
