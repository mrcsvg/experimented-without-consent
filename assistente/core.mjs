// Núcleo da página do assistente: tudo o que não precisa de DOM nem de rede.
// Roda no navegador (import pelo app.js) e no Node (core.test.mjs).
//
// A trava (`faltando`) reproduz `coding_flow.Fluxo.faltando` do Python. Os
// casos em test/portao.json são gerados pelo Python, e o teste compara.

// Campo de linha que a resposta de outro campo torna exigível: dizer que há
// programa opt-in sem dizer qual não é uma codificação verificável.
export const LINE_EXIGIDA = { v6_which: ["v6_optin_beta", "Yes"] };

const vazio = (valor) => !valor || (Array.isArray(valor) && valor.length === 0);

export function faltando(variavel, reg) {
  const pend = [];
  for (const c of variavel.campos) {
    const valor = (reg || {})[c.chave];
    if ((c.tipo === "select" || c.tipo === "checks") && vazio(valor)) {
      pend.push([c.chave, "resposta"]);
    } else if (c.tipo === "text" && vazio(valor)) {
      pend.push([c.chave, c.chave === "keyword_log" ? "log de palavras-chave" : "evidência"]);
    } else if (c.chave in LINE_EXIGIDA && vazio(valor)) {
      const [gatilho, valorGatilho] = LINE_EXIGIDA[c.chave];
      if ((reg || {})[gatilho] === valorGatilho) {
        pend.push([c.chave, `exigido porque ${gatilho} = ${valorGatilho}`]);
      }
    }
  }
  return pend;
}

export function logSugerido(piso) {
  if (!piso) return "";
  if (piso.log_sugerido) return piso.log_sugerido;
  return (piso.docs || [])
    .filter((d) => d.log_line)
    .map((d) => `${d.file.split("/").pop()}: ${d.log_line}`)
    .join("\n");
}

function tituloDoDoc(citacao, docs) {
  const d = (docs || []).find((x) => (citacao.file && x.file === citacao.file) || (citacao.doc != null && x.n === citacao.doc));
  return d ? d.titulo : "";
}

// “frase” (Documento n: título, onde). Sem travessão, de propósito.
export function textoDeEvidencia(citacao, docs) {
  const partes = [];
  if (citacao.doc != null) {
    const titulo = tituloDoDoc(citacao, docs);
    partes.push(`Documento ${citacao.doc}${titulo ? `: ${titulo}` : ""}`);
  }
  if (citacao.onde) partes.push(citacao.onde);
  const onde = partes.length ? ` (${partes.join(", ")})` : "";
  return `“${(citacao.verbatim || "").trim()}”${onde}`;
}

export function chaveDoLink(hash) {
  const m = /(?:^#|&)k=([^&]+)/.exec(hash || "");
  return m && m[1] ? decodeURIComponent(m[1]) : null;
}

// Por serviço: o que está pendente de envio no navegador vence; senão o `_ts`
// maior; empate fica com o servidor. Serviço só local e não pendente é cópia
// velha de algo que o servidor já não tem: fica, para não perder, mas marcado.
export function mesclar(local, servidor) {
  const records = {};
  const pendentes = [];
  const nomes = new Set([...Object.keys(local || {}), ...Object.keys(servidor || {})]);
  for (const s of nomes) {
    const l = (local || {})[s];
    const r = (servidor || {})[s];
    if (l && l._pendente) { records[s] = l; pendentes.push(s); continue; }
    if (!r) { records[s] = l; continue; }
    if (!l) { records[s] = r; continue; }
    records[s] = (Number(l._ts) || 0) > (Number(r._ts) || 0) ? l : r;
  }
  return { records, pendentes };
}

// ============================================================ notas por trecho
// Versão B (04/10/2026): o codificador dá uma nota a cada trecho e a resposta
// da variável é calculada do critério congelado. As opções de nota, os tipos
// de documento e os extras vêm do codebook.json (`notas`, `tipos_doc`,
// `extras`), exportados por analysis/exportar-codebook.py.
//
// O tipo e o registro de cada documento são metadado do corpus (decisão de
// 04/10/2026, à noite): chegam em `d.docs[i].tipo` e `.registro`, publicados
// pelo exportar-piso.py a partir de analysis/tipos-doc.json. O codificador não
// classifica documentos; um `docs_tipo` gravado pela versão anterior é ignorado.

export const NAO_E_ISSO = "x";

// FNV-1a de 32 bits sobre UTF-8, em 8 hex. O mesmo cálculo existe em
// copiloto.py: os ids dos trechos têm de bater entre a página e o copiloto.
export function hash8(texto) {
  const bytes = new TextEncoder().encode(texto);
  let h = 0x811c9dc5;
  for (const b of bytes) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
}

export function idDoHit(hit) { return `h:${hash8(`${hit.file}\n${hit.kwic}`)}`; }

function notaDe(reg, vid, id) {
  const n = reg && reg.notas && reg.notas[vid] && reg.notas[vid][id];
  return n ? n.nota : undefined;
}
function comDe(reg, vid, id) {
  const n = reg && reg.notas && reg.notas[vid] && reg.notas[vid][id];
  return (n && n.com) || "";
}
const relevante = (nota) => nota !== undefined && nota !== NAO_E_ISSO && !(Array.isArray(nota) && nota.length === 0);

export function registroPadrao(codebook, tipo) {
  const t = (codebook.tipos_doc || []).find((x) => x.valor === tipo);
  return t ? t.registro : null;
}

// Os trechos de uma variável: busca por palavra-chave e citações do modelo,
// com ids estáveis. Na V9 entram também os trechos da V1 que receberam nível
// 1 a 3, já julgados como "divulga aqui" até o codificador dizer o contrário.
export function trechosDaVariavel(vid, d, reg) {
  const hits = ((d.piso && d.piso.por_variavel) || {})[vid] || [];
  const cits = (d.citacoes || {})[vid] || [];
  const lista = [
    ...hits.map((h) => ({ id: idDoHit(h), origem: "piso", verbatim: h.kwic, file: h.file, doc: h.n,
                          onde: `palavra-chave "${h.termo}"`, termo: h.termo, flag: h.flag, total_no_doc: h.total_no_doc })),
    ...cits.map((c, i) => ({ id: `c:${vid}-${i + 1}`, origem: "modelo", verbatim: c.verbatim, file: c.file, doc: c.doc, onde: c.onde || "" })),
  ];
  if (vid === "V9") {
    const vistos = new Set(lista.map((t) => t.id));
    for (const t of trechosDaVariavel("V1", d, reg)) {
      const n = notaDe(reg, "V1", t.id);
      if (relevante(n) && !vistos.has(t.id)) lista.push({ ...t, origem: "v1", notaV1: n });
    }
  }
  return lista;
}

function notaEfetiva(reg, vid, t) {
  const n = notaDe(reg, vid, t.id);
  if (n !== undefined) return n;
  return t.origem === "v1" ? "sim" : undefined;
}

export function textoDeEvidenciaNotas(vid, specVid, trechos, relevantes, comentario, docs, linhasExtras = []) {
  const ops = (specVid && specVid.opcoes) || [];
  const rotulo = (valor) => { const o = ops.find((x) => x.valor === valor); return o ? o.rotulo : String(valor); };
  const linhas = relevantes.map((t) =>
    `${textoDeEvidencia(t, docs)} · nota: ${[].concat(t.nota).map(rotulo).join(", ")}${t.com ? ` · comentário: ${t.com}` : ""}`);
  if (!relevantes.length) {
    linhas.push(trechos.length
      ? `Nenhum dos ${trechos.length} trechos sustenta outra resposta (todos julgados: não é isso).`
      : "Nenhum trecho localizado para esta variável.");
  }
  linhas.push(...linhasExtras);
  if (comentario) linhas.push(`Comentário: ${comentario}`);
  return linhas.join("\n");
}

// Os campos planos (os mesmos de hoje) calculados das notas, com a evidência
// montada. `origem[campo]` diz se veio do cálculo, de um extra ou de correção.
export function derivar(codebook, reg, d) {
  reg = reg || {};
  const campos = {}; const evidencias = {}; const origem = {}; const n = {};
  const spec = codebook.notas || {};
  const docPorArquivo = new Map((d.docs || []).map((doc) => [doc.file, doc]));
  const tipoDoDoc = (file) => (docPorArquivo.get(file) || {}).tipo || null;
  const registroDoDoc = (file) => {
    const doc = docPorArquivo.get(file);
    return doc && doc.tipo ? (doc.registro || registroPadrao(codebook, doc.tipo)) : null;
  };
  const agregarRegistro = (files) => {
    const s = new Set(files.map(registroDoDoc).filter(Boolean));
    return s.size === 2 ? "both" : s.size === 1 ? [...s][0] : "";
  };

  for (const v of codebook.variaveis) {
    const vid = v.vid;
    if (vid === "KW") continue;
    const trechos = trechosDaVariavel(vid, d, reg);
    const julgados = trechos.filter((t) => notaEfetiva(reg, vid, t) !== undefined);
    const rel = trechos.filter((t) => relevante(notaEfetiva(reg, vid, t)))
      .map((t) => ({ ...t, nota: notaEfetiva(reg, vid, t), com: comDe(reg, vid, t.id) }));
    n[vid] = { total: trechos.length, julgados: julgados.length, relevantes: rel.length };
    const ops = (spec[vid] || {}).opcoes || [];
    const ordem = ops.map((o) => o.valor);
    const uniao = () => { const s = new Set(); for (const t of rel) for (const x of [].concat(t.nota)) s.add(x); return ordem.filter((x) => s.has(x)); };
    const linhasExtras = [];
    switch (vid) {
      case "V1": {
        const niveis = rel.map((t) => Number(t.nota)).filter((x) => x >= 1);
        const teto = niveis.length ? Math.max(...niveis) : 0;
        campos.v1_code = String(teto);
        campos.v1_register = teto ? agregarRegistro(rel.filter((t) => Number(t.nota) === teto).map((t) => t.file)) : "";
        const vinc = rel.filter((t) => registroDoDoc(t.file) === "binding").map((t) => Number(t.nota)).filter((x) => x >= 1);
        const tetoVinc = vinc.length ? Math.max(...vinc) : 0;
        if (teto && tetoVinc !== teto) linhasExtras.push(`Nível do registro vinculante sozinho: ${tetoVinc}.`);
        break;
      }
      case "V2": campos.v2_framing = uniao(); break;
      case "V3": { const u = new Set(uniao()); for (const o of ops) campos[o.campo] = u.has(o.valor) ? "Yes" : "No"; break; }
      case "V4": { const u = uniao(); campos.v4_basis = u.length ? u : ["not stated"]; break; }
      case "V5": {
        const idx = rel.map((t) => ordem.indexOf(t.nota)).filter((i) => i >= 0);
        campos.v5_optout = idx.length ? ordem[Math.max(...idx)] : "none";
        break;
      }
      case "V6": campos.v6_optin_beta = rel.length ? "Yes" : "No"; break;
      case "V7": campos.v7_debrief = rel.length ? "Yes" : "No"; break;
      case "V8": campos.v8_ethics = rel.length ? "Yes" : "No"; break;
      case "V9": {
        const tipos = new Set(rel.map((t) => tipoDoDoc(t.file)).filter(Boolean));
        campos.v9_where = (codebook.tipos_doc || []).map((t) => t.valor).filter((x) => tipos.has(x));
        campos.v9_register = rel.length ? agregarRegistro(rel.map((t) => t.file)) : "";
        break;
      }
      default: break;
    }
    for (const chave of (codebook.extras || {})[vid] || []) {
      campos[chave] = (reg.extras || {})[chave] || "";
      origem[chave] = "extra";
    }
    for (const c of v.campos) {
      if (c.tipo === "text") continue;
      if (!origem[c.chave]) origem[c.chave] = "calculado";
      if (reg.override && c.chave in reg.override) { campos[c.chave] = reg.override[c.chave]; origem[c.chave] = "corrigido"; }
    }
    const campoTexto = v.campos.find((c) => c.tipo === "text");
    if (campoTexto) {
      evidencias[vid] = textoDeEvidenciaNotas(vid, spec[vid], trechos, rel, (reg.comentarios || {})[vid] || "", d.docs, linhasExtras);
      campos[campoTexto.chave] = evidencias[vid];
    }
  }
  campos.keyword_log = reg.keyword_log || "";
  campos.notes = reg.notes || "";
  return { campos, evidencias, origem, n };
}

export function etapas(codebook) { return codebook.variaveis.map((v) => v.vid); }

// A trava por etapa. Devolve [[o que, motivo], ...]; vazia = pode confirmar.
export function faltandoEtapa(codebook, etapa, reg, d) {
  reg = reg || {};
  if (etapa === "KW") return vazio(reg.keyword_log) ? [["keyword_log", "log de palavras-chave"]] : [];
  const pend = [];
  const trechos = trechosDaVariavel(etapa, d, reg);
  const semNota = trechos.filter((t) => t.origem !== "v1" && notaDe(reg, etapa, t.id) === undefined).length;
  if (semNota) pend.push(["trechos", `${semNota} trecho${semNota === 1 ? "" : "s"} sem nota`]);
  if (!trechos.length && !(reg.confirmadas || {})[etapa]) pend.push(["confirmar", "sem trechos: confirme a ausência"]);
  const { campos } = derivar(codebook, reg, d);
  if (etapa === "V4" && vazio(campos.v4_region_gated)) pend.push(["v4_region_gated", "resposta"]);
  if (etapa === "V6" && campos.v6_optin_beta === "Yes" && vazio(campos.v6_which)) pend.push(["v6_which", "exigido porque v6_optin_beta = Yes"]);
  return pend;
}

// Uma etapa só fecha com a trava aberta E o clique em Confirmar.
export function fechadas(codebook, reg, d) {
  const saida = {};
  for (const e of etapas(codebook)) saida[e] = faltandoEtapa(codebook, e, reg, d).length === 0 && !!((reg || {}).confirmadas || {})[e];
  return saida;
}

export function progressoEtapas(codebook, reg, d) {
  const f = fechadas(codebook, reg, d);
  return { feitas: Object.values(f).filter(Boolean).length, total: etapas(codebook).length };
}

export function concluidoEtapas(codebook, reg, d) {
  const p = progressoEtapas(codebook, reg, d);
  return p.feitas === p.total;
}

export function primeiraEtapaIncompleta(codebook, reg, d) {
  const f = fechadas(codebook, reg, d);
  const lista = etapas(codebook);
  const i = lista.findIndex((e) => !f[e]);
  return i === -1 ? lista.length - 1 : i;
}

// Aplica a sugestão do copiloto só onde o codificador ainda não disse nada.
export function aplicarNotas(reg, vid, sugestao, trechos) {
  const notas = { ...((reg || {}).notas || {}) };
  notas[vid] = { ...(notas[vid] || {}) };
  for (const t of trechos || []) {
    if (t.origem === "v1" || notas[vid][t.id] !== undefined) continue;
    const s = ((sugestao || {}).notas || {})[t.id];
    if (s !== undefined && s !== null && s !== "") notas[vid][t.id] = { nota: s };
  }
  const extras = { ...((reg || {}).extras || {}) };
  for (const [k, val] of Object.entries((sugestao || {}).extras || {})) {
    if (vazio(extras[k]) && !vazio(val)) extras[k] = val;
  }
  return { ...(reg || {}), notas, extras };
}

// Na lista de serviços a página não tem os trechos de todos os 26 carregados,
// então o progresso de cada serviço se mede pelas confirmações: uma etapa só
// é confirmada com a trava aberta, e qualquer edição na etapa a reabre.
export function progressoConfirmado(codebook, reg) {
  const conf = (reg || {}).confirmadas || {};
  const lista = etapas(codebook);
  return { feitas: lista.filter((e) => conf[e]).length, total: lista.length };
}

export function concluidoConfirmado(codebook, reg) {
  const p = progressoConfirmado(codebook, reg);
  return p.feitas === p.total;
}

export function proximoServicoPorConfirmacao(codebook, records, atual) {
  const ordem = codebook.servicos;
  const inicio = atual ? ordem.indexOf(atual) + 1 : 0;
  for (let k = 0; k < ordem.length; k++) {
    const s = ordem[(inicio + k) % ordem.length];
    if (!concluidoConfirmado(codebook, (records || {})[s] || {})) return s;
  }
  return null;
}
