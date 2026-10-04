// Testes do núcleo do /api/state, com um GitHub de mentira em memória.
//   node --test server/
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
  for (const body of [undefined, {}, { servico: "", registro: {} }, { servico: "Z", registro: "x" }, { servico: "Z", registro: [] }]) {
    const r = res();
    await h(req("PUT", { chave: ENV.EWC_KEY, body }), r);
    assert.equal(r.codigo, 400, JSON.stringify(body));
  }
  assert.equal(gh.chamadas.length, 0, "corpo inválido não chega ao GitHub");
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

test("duas gravações seguidas: a segunda vê o _ts da primeira e passa", async () => {
  const gh = githubFalso();
  let t = 100;
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl, agora: () => (t += 1) });
  let r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY_ENSAIO, body: { servico: "Z", registro: { a: 1 }, base_ts: 0 } }), r);
  const ts1 = r.corpo._ts;
  r = res();
  await h(req("PUT", { chave: ENV.EWC_KEY_ENSAIO, body: { servico: "Z", registro: { a: 2 }, base_ts: ts1 } }), r);
  assert.equal(r.codigo, 200);
  assert.ok(r.corpo._ts > ts1);
  assert.equal(JSON.parse(gh.arquivos.get("audit/ensaio-progress.json").content).records.Z.a, 2);
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

test("método desconhecido: 405 com allow", async () => {
  const gh = githubFalso();
  const h = criarHandler({ env: ENV, fetchImpl: gh.fetchImpl });
  const r = res();
  await h(req("POST", { chave: ENV.EWC_KEY }), r);
  assert.equal(r.codigo, 405);
  assert.equal(r.cabecalhos.allow, "GET, PUT, DELETE");
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
