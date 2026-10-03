// Testes do núcleo da página, sem DOM.
//   node --test "assistente/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  faltando, fechados, progresso, concluido, primeiroIncompleto, proximoServico,
  logSugerido, textoDeEvidencia, aplicarSugestao, chaveDoLink, mesclar,
} from "./core.mjs";

const fx = JSON.parse(readFileSync(new URL("./test/portao.json", import.meta.url), "utf8"));
const CB = { servicos: fx.servicos, variaveis: fx.variaveis };
const porVid = Object.fromEntries(CB.variaveis.map((v) => [v.vid, v]));

// Um registro completo, para derivar os casos de progresso.
function completo() {
  const reg = {};
  for (const v of CB.variaveis) for (const c of v.campos) {
    if (c.tipo === "select") reg[c.chave] = c.opcoes.find((o) => o);
    else if (c.tipo === "checks") reg[c.chave] = [c.opcoes.find((o) => o)];
    else reg[c.chave] = "texto";
  }
  return reg;
}

test("faltando reproduz a trava do Python em todos os casos gerados", () => {
  assert.ok(fx.casos.length >= 40, "fixtures presentes");
  for (const caso of fx.casos) {
    assert.deepEqual(faltando(porVid[caso.vid], caso.reg), caso.esperado,
      `${caso.vid} · ${caso.nome}`);
  }
});

test("fechados, progresso e concluido", () => {
  const vazio = {};
  assert.deepEqual(progresso(CB, vazio), { feitas: 0, total: 10 });
  assert.equal(concluido(CB, vazio), false);
  const tudo = completo();
  assert.deepEqual(progresso(CB, tudo), { feitas: 10, total: 10 });
  assert.equal(concluido(CB, tudo), true);
  const semKw = { ...tudo, keyword_log: "" };
  assert.equal(fechados(CB, semKw).KW, false);
  assert.equal(fechados(CB, semKw).V1, true);
  assert.deepEqual(progresso(CB, semKw), { feitas: 9, total: 10 });
});

test("primeiroIncompleto abre onde parou, e no fim quando tudo fechou", () => {
  assert.equal(primeiroIncompleto(CB, {}), 0);
  const tudo = completo();
  assert.equal(primeiroIncompleto(CB, tudo), 9);
  const semV5 = { ...tudo, v5_optout: "" };
  assert.equal(primeiroIncompleto(CB, semV5), 4);
});

test("proximoServico anda na ordem, dá a volta e devolve null no fim", () => {
  const cb = { ...CB, servicos: ["A", "B", "C"] };
  const tudo = completo();
  assert.equal(proximoServico(cb, {}, null), "A");
  assert.equal(proximoServico(cb, { A: tudo }, null), "B");
  assert.equal(proximoServico(cb, { A: tudo }, "B"), "C");
  assert.equal(proximoServico(cb, { A: tudo, C: tudo }, "C"), "B", "dá a volta");
  assert.equal(proximoServico(cb, { A: tudo, B: tudo, C: tudo }, "B"), null);
  assert.equal(proximoServico(cb, { B: { v1_code: "1" } }, "A"), "B", "em andamento conta como incompleto");
});

test("logSugerido usa o log do piso, ou monta das contagens", () => {
  assert.equal(logSugerido({ log_sugerido: "01.md: experiment:2" }), "01.md: experiment:2");
  const piso = { docs: [{ file: "x/01-a.md", log_line: "experiment:1 / test:0" }, { file: "x/02-b.md", log_line: "" }] };
  assert.equal(logSugerido(piso), "01-a.md: experiment:1 / test:0");
  assert.equal(logSugerido(null), "");
});

test("textoDeEvidencia: frase, documento e onde, sem travessão", () => {
  const docs = [{ n: 1, file: "w/01-privacy.md", titulo: "Privacy Policy" }];
  const t = textoDeEvidencia({ doc: 1, file: "w/01-privacy.md", onde: "Seção 3", verbatim: "we run A/B tests" }, docs);
  assert.equal(t, "“we run A/B tests” (Documento 1: Privacy Policy, Seção 3)");
  assert.ok(!t.includes("—"));
  const semDoc = textoDeEvidencia({ verbatim: "x", onde: "" }, []);
  assert.equal(semDoc, "“x”");
});

test("aplicarSugestao preenche campos e evidência sem apagar o resto", () => {
  const v1 = porVid.V1;
  const docs = [{ n: 1, file: "w/01.md", titulo: "Privacy Policy" }];
  const cits = { "V1-1": { doc: 1, file: "w/01.md", onde: "§3", verbatim: "we test features" } };
  const sug = { campos: { v1_code: "2", v1_register: "binding" }, razao: "Porque sim.", confianca: "média", citacoes: ["V1-1", "V9-9"] };
  const antes = { notes: "minha nota", v2_framing: ["research"] };
  const depois = aplicarSugestao(v1, antes, sug, cits, docs);
  assert.equal(depois.v1_code, "2");
  assert.equal(depois.v1_register, "binding");
  assert.equal(depois.v1_evidence, "“we test features” (Documento 1: Privacy Policy, §3)");
  assert.equal(depois.notes, "minha nota");
  assert.deepEqual(depois.v2_framing, ["research"]);
  assert.equal(antes.v1_code, undefined, "não altera o registro de entrada");
});

test("aplicarSugestao: sem citação usa a razão; evidência já escrita fica", () => {
  const v7 = porVid.V7;
  const sug = { campos: { v7_debrief: "No" }, razao: "nenhuma citação sustenta outra resposta", confianca: "média", citacoes: [] };
  const a = aplicarSugestao(v7, {}, sug, {}, []);
  assert.equal(a.v7_debrief, "No");
  assert.equal(a.v7_evidence, "Copiloto: nenhuma citação sustenta outra resposta");
  const b = aplicarSugestao(v7, { v7_evidence: "já escrevi" }, sug, {}, []);
  assert.equal(b.v7_evidence, "já escrevi");
});

test("aplicarSugestao põe no máximo três citações na evidência", () => {
  const v1 = porVid.V1;
  const cits = {};
  for (let i = 1; i <= 5; i++) cits[`V1-${i}`] = { doc: 1, file: "w/01.md", onde: `§${i}`, verbatim: `frase ${i}` };
  const sug = { campos: { v1_code: "3" }, razao: "r", confianca: "alta", citacoes: Object.keys(cits) };
  const r = aplicarSugestao(v1, {}, sug, cits, []);
  assert.equal(r.v1_evidence.split("\n").length, 3);
  assert.ok(r.v1_evidence.startsWith("“frase 1”"));
});

test("aplicarSugestao ignora campo que não é da variável e lista para checks", () => {
  const v2 = porVid.V2;
  const sug = { campos: { v2_framing: ["research", "service improvement"], v1_code: "3" }, razao: "r", confianca: "alta", citacoes: [] };
  const r = aplicarSugestao(v2, {}, sug, {}, []);
  assert.deepEqual(r.v2_framing, ["research", "service improvement"]);
  assert.equal(r.v1_code, undefined);
});

test("chaveDoLink lê #k=", () => {
  assert.equal(chaveDoLink("#k=abc123"), "abc123");
  assert.equal(chaveDoLink("#k=abc123&outra=1"), "abc123");
  assert.equal(chaveDoLink("#outra=1"), null);
  assert.equal(chaveDoLink(""), null);
  assert.equal(chaveDoLink("#k="), null);
});

test("mesclar: pendente local vence, senão o _ts maior; servidor desempata", () => {
  const local = {
    A: { v1_code: "1", _ts: 10, _pendente: true },
    B: { v1_code: "2", _ts: 5 },
    C: { v1_code: "3", _ts: 7 },
    E: { v1_code: "9", _pendente: true },
  };
  const servidor = {
    A: { v1_code: "0", _ts: 50 },
    B: { v1_code: "8", _ts: 9 },
    C: { v1_code: "4", _ts: 7 },
    D: { v1_code: "5", _ts: 1 },
  };
  const m = mesclar(local, servidor);
  assert.equal(m.records.A.v1_code, "1", "pendente local vence");
  assert.equal(m.records.B.v1_code, "8", "servidor mais novo vence");
  assert.equal(m.records.C.v1_code, "4", "empate: servidor");
  assert.equal(m.records.D.v1_code, "5", "só no servidor");
  assert.equal(m.records.E.v1_code, "9", "só local, pendente");
  assert.deepEqual(m.pendentes.sort(), ["A", "E"]);
});
