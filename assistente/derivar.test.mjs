// Testes do cálculo por notas (versão B): uma regra por variável, contra o
// critério congelado, mais a trava por etapa.
//   node --test "assistente/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  idDoHit, trechosDaVariavel, registroPadrao, derivar, faltandoEtapa, etapas,
  fechadas, progressoEtapas, primeiraEtapaIncompleta, aplicarNotas, faltando,
} from "./core.mjs";
import * as core from "./core.mjs";

const fx = JSON.parse(readFileSync(new URL("./test/portao.json", import.meta.url), "utf8"));
const CB = { servicos: fx.servicos, variaveis: fx.variaveis, notas: fx.notas, tipos_doc: fx.tipos_doc, extras: fx.extras };
const porVid = Object.fromEntries(CB.variaveis.map((v) => [v.vid, v]));

// Um serviço de brinquedo: dois documentos, alguns trechos. O tipo e o
// registro de cada documento são metadado do corpus (decisão de 04/10/2026):
// chegam em d.docs, nunca do registro do codificador.
const HIT1 = { termo: "experiment", kwic: "…we may experiment with features…", flag: null, file: "s/01.md", n: 1, total_no_doc: 2 };
const HIT8 = { termo: "ethics", kwic: "…Our Code of Ethics…", flag: "falso positivo comum", file: "s/02.md", n: 2, total_no_doc: 1 };
const D = {
  docs: [{ n: 1, file: "s/01.md", titulo: "Privacy Policy", url: "https://s/privacy", tipo: "privacy policy", registro: "binding" },
         { n: 2, file: "s/02.md", titulo: "Engineering Blog", url: "https://s/blog", tipo: "blog/PR/site de pesquisa", registro: "non-binding" }],
  piso: { por_variavel: { V1: [HIT1], V3: [HIT1], V8: [HIT8] } },
  citacoes: {
    V1: [{ doc: 2, file: "s/02.md", onde: "§1", verbatim: "we run A/B tests" }],
    V2: [{ doc: 1, file: "s/01.md", onde: "§2", verbatim: "research that improves our services" }],
    V5: [{ doc: 1, file: "s/01.md", onde: "§7", verbatim: "you may object" },
         { doc: 2, file: "s/02.md", onde: "§9", verbatim: "turn off experiments in settings" }],
    V9: [{ doc: 1, file: "s/01.md", onde: "§3", verbatim: "we test features" }],
  },
};
const ID_HIT1 = idDoHit(HIT1);

function reg(extra = {}) {
  return { notas: {}, extras: {}, override: {}, comentarios: {}, confirmadas: {}, ...extra };
}

test("idDoHit é estável, curto e muda com o trecho", () => {
  assert.match(ID_HIT1, /^h:[0-9a-f]{8}$/);
  assert.equal(idDoHit({ ...HIT1 }), ID_HIT1);
  assert.notEqual(idDoHit({ ...HIT1, kwic: "outro" }), ID_HIT1);
  assert.match(idDoHit({ file: "a.md", kwic: "ab" }), /^h:[0-9a-f]{8}$/);
});

test("trechosDaVariavel junta piso e citações com ids; V9 herda os da V1 com nota", () => {
  const t1 = trechosDaVariavel("V1", D, reg());
  assert.deepEqual(t1.map((t) => [t.id, t.origem]), [[ID_HIT1, "piso"], ["c:V1-1", "modelo"]]);
  assert.equal(t1[0].verbatim, HIT1.kwic);
  assert.equal(t1[0].onde, 'palavra-chave "experiment"');
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "x" } } } });
  const t9 = trechosDaVariavel("V9", D, r);
  assert.deepEqual(t9.map((t) => [t.id, t.origem]), [["c:V9-1", "modelo"], [ID_HIT1, "v1"]]);
  assert.equal(t9[1].notaV1, "2");
});

test("registroPadrao segue o tipo", () => {
  assert.equal(registroPadrao(CB, "privacy policy"), "binding");
  assert.equal(registroPadrao(CB, "help centre"), "non-binding");
  assert.equal(registroPadrao(CB, "inexistente"), null);
});

test("V1: teto, registro do teto e nota do vinculante sozinho", () => {
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } } } });
  const x = derivar(CB, r, D);
  assert.equal(x.campos.v1_code, "3");
  assert.equal(x.campos.v1_register, "non-binding");
  assert.match(x.campos.v1_evidence, /Nível do registro vinculante sozinho: 2/);
  assert.match(x.campos.v1_evidence, /“we run A\/B tests” \(Documento 2: Engineering Blog, §1\) · nota: 3/);
  assert.equal(x.origem.v1_code, "calculado");
  assert.deepEqual(x.n.V1, { total: 2, julgados: 2, relevantes: 2 });
});

test("V1: teto nos dois registros = both; sem trecho relevante = 0 e registro vazio", () => {
  const ambos = derivar(CB, reg({ notas: { V1: { [ID_HIT1]: { nota: "3" }, "c:V1-1": { nota: "3" } } } }), D);
  assert.equal(ambos.campos.v1_register, "both");
  const nada = derivar(CB, reg({ notas: { V1: { [ID_HIT1]: { nota: "x" }, "c:V1-1": { nota: "x" } } } }), D);
  assert.equal(nada.campos.v1_code, "0");
  assert.equal(nada.campos.v1_register, "");
  assert.match(nada.campos.v1_evidence, /Nenhum dos 2 trechos sustenta outra resposta/);
});

test("V2: união na ordem das opções", () => {
  const r = reg({ notas: { V2: { "c:V2-1": { nota: ["research", "service improvement"] } } } });
  assert.deepEqual(derivar(CB, r, D).campos.v2_framing, ["service improvement", "research"]);
  assert.deepEqual(derivar(CB, reg(), D).campos.v2_framing, []);
});

test("V3: tags viram Yes/No por campo; alvos vêm do extra", () => {
  const r = reg({ notas: { V3: { [ID_HIT1]: { nota: ["activities", "pricing"] } } }, extras: { v3_targets: "features; preço" } });
  const c = derivar(CB, r, D).campos;
  assert.equal(c.v3_activities, "Yes");
  assert.equal(c.v3_specific, "No");
  assert.equal(c.v3_pricing, "Yes");
  assert.equal(c.v3_targets, "features; preço");
});

test("V4: união, vazio vira not stated, extras passam", () => {
  const vazio = derivar(CB, reg({ extras: { v4_region_gated: "not-verifiable (vantage)" } }), D).campos;
  assert.deepEqual(vazio.v4_basis, ["not stated"]);
  assert.equal(vazio.v4_region_gated, "not-verifiable (vantage)");
  const r = reg({ notas: { V4: { "c:V2-1": { nota: ["contract", "legitimate interest"] } } } });
  // V4 não tem trecho neste brinquedo; a nota em id desconhecido é ignorada.
  assert.deepEqual(derivar(CB, r, D).campos.v4_basis, ["not stated"]);
});

test("V5: o degrau mais alto; nenhum = none", () => {
  assert.equal(derivar(CB, reg(), D).campos.v5_optout, "none");
  const r = reg({ notas: { V5: { "c:V5-1": { nota: "GDPR-objection-only" }, "c:V5-2": { nota: "x" } } } });
  assert.equal(derivar(CB, r, D).campos.v5_optout, "GDPR-objection-only");
  const dois = reg({ notas: { V5: { "c:V5-1": { nota: "GDPR-objection-only" }, "c:V5-2": { nota: "dedicated" } } } });
  assert.equal(derivar(CB, dois, D).campos.v5_optout, "dedicated", "o degrau mais alto, não o primeiro");
  const invertido = reg({ notas: { V5: { "c:V5-1": { nota: "dedicated" }, "c:V5-2": { nota: "GDPR-objection-only" } } } });
  assert.equal(derivar(CB, invertido, D).campos.v5_optout, "dedicated", "a ordem dos trechos não importa");
});

test("V6, V7, V8: Yes se houver trecho com nota; V8 grava a evidência em v8_note", () => {
  const r = reg({ notas: { V8: { [idDoHit(HIT8)]: { nota: "sim", com: "na verdade é código de conduta" } } }, extras: { v6_which: "" } });
  const c = derivar(CB, r, D).campos;
  assert.equal(c.v8_ethics, "Yes");
  assert.match(c.v8_note, /Our Code of Ethics/);
  assert.match(c.v8_note, /comentário: na verdade é código de conduta/);
  assert.equal(c.v6_optin_beta, "No");
  assert.equal(c.v7_debrief, "No");
});

test("V9: herda os trechos da V1, usa os tipos dos documentos e o registro agregado", () => {
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } }, V9: { "c:V9-1": { nota: "x" } } } });
  const c = derivar(CB, r, D).campos;
  assert.deepEqual(c.v9_where, ["privacy policy", "blog/PR/site de pesquisa"]);
  assert.equal(c.v9_register, "both");
  // O codificador pode desmarcar um herdado na V9.
  const r2 = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } }, V9: { "c:V9-1": { nota: "x" }, "c:V1-1": { nota: "x" } } } });
  const c2 = derivar(CB, r2, D).campos;
  assert.deepEqual(c2.v9_where, ["privacy policy"]);
  assert.equal(c2.v9_register, "binding");
  assert.deepEqual(derivar(CB, reg(), D).campos.v9_where, []);
  assert.equal(derivar(CB, reg(), D).campos.v9_register, "");
});

test("correção à mão substitui o calculado e fica marcada", () => {
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } } }, override: { v1_code: "2" } });
  const x = derivar(CB, r, D);
  assert.equal(x.campos.v1_code, "2");
  assert.equal(x.origem.v1_code, "corrigido");
  assert.equal(x.campos.v1_register, "non-binding", "o que não foi corrigido continua calculado");
});

test("comentário da variável entra na evidência; keyword_log e notes passam direto", () => {
  const r = reg({ comentarios: { V7: "tema nunca aparece" }, keyword_log: "01.md: experiment:2", notes: "nota geral" });
  const c = derivar(CB, r, D).campos;
  assert.match(c.v7_evidence, /Nenhum trecho localizado para esta variável/);
  assert.match(c.v7_evidence, /Comentário: tema nunca aparece/);
  assert.equal(c.keyword_log, "01.md: experiment:2");
  assert.equal(c.notes, "nota geral");
});

test("o tipo do documento é metadado do corpus: não há passo de documentos", () => {
  assert.deepEqual(etapas(CB), ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "KW"]);
  assert.equal(core.DOCS, undefined, "a constante do passo saiu");
  assert.equal(core.aplicarTipos, undefined, "a aplicação de tipos pelo copiloto saiu");
  const notas = { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } } };
  // Um registro antigo com docs_tipo (versão B de 04/10 à tarde) não manda mais:
  // o teto está no blog, e o blog é não vinculante no corpus.
  const antigo = reg({ notas, docs_tipo: { "s/02.md": { tipo: "privacy policy", registro: "binding" } } });
  assert.equal(derivar(CB, antigo, D).campos.v1_register, "non-binding");
  // Sem registro explícito no corpus, vale o padrão do tipo.
  const semRegistro = { ...D, docs: D.docs.map(({ registro, ...doc }) => doc) };
  const x = derivar(CB, reg({ notas }), semRegistro);
  assert.equal(x.campos.v1_register, "non-binding");
  assert.match(x.campos.v1_evidence, /Nível do registro vinculante sozinho: 2/);
  assert.deepEqual(derivar(CB, reg({ notas }), semRegistro).campos.v9_where, ["privacy policy", "blog/PR/site de pesquisa"]);
  // Corpus sem tipo (não deve acontecer): calcula sem quebrar, com registro vazio.
  const semTipo = { ...D, docs: D.docs.map(({ tipo, registro, ...doc }) => doc) };
  const y = derivar(CB, reg({ notas }), semTipo);
  assert.equal(y.campos.v1_code, "3");
  assert.equal(y.campos.v1_register, "");
  assert.deepEqual(y.campos.v9_where, []);
  // A trava da V1 não pede mais os documentos.
  assert.deepEqual(faltandoEtapa(CB, "V1", { notas: {} }, D), [["trechos", "2 trechos sem nota"]]);
});

test("trava: trechos sem nota, extras e ausência confirmada", () => {
  assert.deepEqual(faltandoEtapa(CB, "V1", reg(), D), [["trechos", "2 trechos sem nota"]]);
  const umSo = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" } } } });
  assert.deepEqual(faltandoEtapa(CB, "V1", umSo, D), [["trechos", "1 trecho sem nota"]]);
  const v4 = reg();
  assert.deepEqual(faltandoEtapa(CB, "V4", v4, D), [["confirmar", "sem trechos: confirme a ausência"], ["v4_region_gated", "resposta"]]);
  const v6sim = reg({ notas: { V6: {} }, extras: {}, confirmadas: { V6: true } });
  // V6 não tem trechos no brinquedo: Yes só por correção à mão.
  v6sim.override = { v6_optin_beta: "Yes" };
  assert.deepEqual(faltandoEtapa(CB, "V6", v6sim, D), [["v6_which", "exigido porque v6_optin_beta = Yes"]]);
  const v9 = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "x" } } } });
  assert.deepEqual(faltandoEtapa(CB, "V9", v9, D), [["trechos", "1 trecho sem nota"]], "o herdado da V1 já conta como julgado");
  assert.deepEqual(faltandoEtapa(CB, "KW", reg(), D), [["keyword_log", "log de palavras-chave"]]);
});

test("fechadas exige confirmação; progresso conta 10 etapas; retoma na primeira aberta", () => {
  // Uma confirmação DOCS gravada pela versão anterior é ignorada.
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } } }, confirmadas: { DOCS: true } });
  const f = fechadas(CB, r, D);
  assert.equal(f.DOCS, undefined);
  assert.equal(f.V1, false, "sem o clique em Confirmar não fecha");
  r.confirmadas.V1 = true;
  assert.equal(fechadas(CB, r, D).V1, true);
  assert.deepEqual(progressoEtapas(CB, r, D), { feitas: 1, total: 10 });
  assert.equal(primeiraEtapaIncompleta(CB, r, D), 1);
  assert.equal(primeiraEtapaIncompleta(CB, reg(), D), 0);
});

test("aplicarNotas preenche só o que não tem nota", () => {
  const r = reg({ notas: { V1: { [ID_HIT1]: { nota: "1" } } } });
  const sug = { notas: { [ID_HIT1]: "3", "c:V1-1": "3" }, extras: {} };
  const novo = aplicarNotas(r, "V1", sug, trechosDaVariavel("V1", D, r));
  assert.equal(novo.notas.V1[ID_HIT1].nota, "1", "não passa por cima");
  assert.equal(novo.notas.V1["c:V1-1"].nota, "3");
  assert.equal(r.notas.V1["c:V1-1"], undefined, "não altera a entrada");
  const r4 = reg({ extras: { v4_mapped_purpose: "já escrito" } });
  const n4 = aplicarNotas(r4, "V4", { notas: {}, extras: { v4_mapped_purpose: "outra", v4_region_gated: "No" } }, []);
  assert.equal(n4.extras.v4_mapped_purpose, "já escrito");
  assert.equal(n4.extras.v4_region_gated, "No");
});

test("compatibilidade: um registro derivado completo passa na trava antiga de cada variável", () => {
  const r = reg({
    notas: {
      V1: { [ID_HIT1]: { nota: "2" }, "c:V1-1": { nota: "3" } },
      V2: { "c:V2-1": { nota: ["research"] } },
      V3: { [ID_HIT1]: { nota: ["activities"] } },
      V5: { "c:V5-1": { nota: "GDPR-objection-only" }, "c:V5-2": { nota: "x" } },
      V8: { [idDoHit(HIT8)]: { nota: "x" } },
    },
    extras: { v3_targets: "features", v4_mapped_purpose: "improve", v4_region_gated: "No", v6_which: "" },
    keyword_log: "01.md: experiment:2",
  });
  const c = derivar(CB, r, D).campos;
  for (const v of CB.variaveis) {
    assert.deepEqual(faltando(v, c), [], v.vid);
  }
});

test("progresso por confirmação: conta etapas confirmadas; próximo serviço dá a volta", async () => {
  const { progressoConfirmado, concluidoConfirmado, proximoServicoPorConfirmacao } = await import("./core.mjs");
  const todas = Object.fromEntries(etapas(CB).map((e) => [e, true]));
  assert.deepEqual(progressoConfirmado(CB, {}), { feitas: 0, total: 10 });
  assert.deepEqual(progressoConfirmado(CB, { confirmadas: { DOCS: true, V1: true } }), { feitas: 1, total: 10 }, "DOCS antigo não conta");
  assert.equal(concluidoConfirmado(CB, { confirmadas: todas }), true);
  const cb = { ...CB, servicos: ["A", "B", "C"] };
  assert.equal(proximoServicoPorConfirmacao(cb, { A: { confirmadas: todas } }, null), "B");
  assert.equal(proximoServicoPorConfirmacao(cb, { A: { confirmadas: todas }, C: { confirmadas: todas } }, "C"), "B");
  assert.equal(proximoServicoPorConfirmacao(cb, { A: { confirmadas: todas }, B: { confirmadas: todas }, C: { confirmadas: todas } }, "A"), null);
});
