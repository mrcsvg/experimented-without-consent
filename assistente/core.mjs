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

export function fechados(codebook, reg) {
  const saida = {};
  for (const v of codebook.variaveis) saida[v.vid] = faltando(v, reg).length === 0;
  return saida;
}

export function progresso(codebook, reg) {
  const f = fechados(codebook, reg);
  return { feitas: Object.values(f).filter(Boolean).length, total: codebook.variaveis.length };
}

export function concluido(codebook, reg) {
  const p = progresso(codebook, reg);
  return p.feitas === p.total;
}

// Abre na primeira variável ainda incompleta, não na V1. Tudo respondido abre
// na última, para rever.
export function primeiroIncompleto(codebook, reg) {
  const i = codebook.variaveis.findIndex((v) => faltando(v, reg).length > 0);
  return i === -1 ? codebook.variaveis.length - 1 : i;
}

// O próximo serviço incompleto depois de `atual`, na ordem do codebook, dando
// a volta. null quando os 26 estão concluídos.
export function proximoServico(codebook, records, atual) {
  const ordem = codebook.servicos;
  const inicio = atual ? ordem.indexOf(atual) + 1 : 0;
  for (let k = 0; k < ordem.length; k++) {
    const s = ordem[(inicio + k) % ordem.length];
    if (!concluido(codebook, (records || {})[s] || {})) return s;
  }
  return null;
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

// Preenche os campos da variável com a sugestão e a evidência com as citações
// indicadas. Campo de texto já escrito pelo codificador fica como está.
export function aplicarSugestao(variavel, reg, sugestao, citacoesPorId, docs) {
  const novo = { ...(reg || {}) };
  const chaves = new Set(variavel.campos.map((c) => c.chave));
  for (const [chave, valor] of Object.entries(sugestao.campos || {})) {
    if (!chaves.has(chave)) continue;
    const campo = variavel.campos.find((c) => c.chave === chave);
    novo[chave] = campo.tipo === "checks" ? [].concat(valor || []) : (valor == null ? "" : String(valor));
  }
  const citadas = (sugestao.citacoes || []).map((id) => (citacoesPorId || {})[id]).filter(Boolean);
  const evidencia = citadas.length
    ? citadas.map((c) => textoDeEvidencia(c, docs)).join("\n")
    : (sugestao.razao ? `Copiloto: ${sugestao.razao}` : "");
  for (const c of variavel.campos) {
    if (c.tipo === "text" && c.chave !== "keyword_log" && vazio(novo[c.chave]) && evidencia) {
      novo[c.chave] = evidencia;
    }
  }
  return novo;
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
