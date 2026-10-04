// Testes do núcleo da página, sem DOM.
//   node --test "assistente/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { faltando, logSugerido, textoDeEvidencia, chaveDoLink, mesclar } from "./core.mjs";

const fx = JSON.parse(readFileSync(new URL("./test/portao.json", import.meta.url), "utf8"));
const CB = { servicos: fx.servicos, variaveis: fx.variaveis };
const porVid = Object.fromEntries(CB.variaveis.map((v) => [v.vid, v]));

test("faltando reproduz a trava do Python em todos os casos gerados", () => {
  assert.ok(fx.casos.length >= 40, "fixtures presentes");
  for (const caso of fx.casos) {
    assert.deepEqual(faltando(porVid[caso.vid], caso.reg), caso.esperado,
      `${caso.vid} · ${caso.nome}`);
  }
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
