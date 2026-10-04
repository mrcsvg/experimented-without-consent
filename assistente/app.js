// A página do assistente: DOM, rede e armazenamento. A lógica sem DOM está em
// core.mjs. Os dados congelados vêm do site do corpus; as respostas vão para
// /api/state, neste mesmo site, e ficam também no navegador.
import {
  faltando, fechados, progresso, concluido, primeiroIncompleto, proximoServico,
  logSugerido, textoDeEvidencia, aplicarSugestao, chaveDoLink, mesclar,
} from "./core.mjs";

// Em localhost, ?corpus=... aponta para uma cópia local do site do corpus
// (server/dev.mjs serve o repositório irmão em /corpus). Em produção, só o site.
const CORPUS = (location.hostname === "localhost" && new URLSearchParams(location.search).get("corpus"))
  || "https://experimented-without-consent-corpus.vercel.app";
const LS ={ records: "ewc.records", abertura: "ewc.abertura", chave: "ewc.chave" };
const ATRASOS = [5000, 10000, 20000, 30000];
const DEBOUNCE = 1200;

const E = {
  chave: null, modo: null, codebook: null, indice: null,
  records: {}, baseTs: {}, pendentes: new Set(), gravando: new Map(), tentativa: {}, recibo: {},
  servico: null, i: 0, cache: new Map(), textos: new Map(), copilotoAberto: false, timerEdicao: null,
};

const app = document.getElementById("app");
const painel = document.getElementById("painel");
const faixa = document.getElementById("faixa");

// ------------------------------------------------------------------ utilidades

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hora = () => new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function limpar(no) { while (no.firstChild) no.removeChild(no.firstChild); }

function lerLocal() {
  try { return JSON.parse(localStorage.getItem(LS.records)) || {}; } catch { return {}; }
}
function persistirLocal() {
  try { localStorage.setItem(LS.records, JSON.stringify(E.records)); } catch { /* sem espaço ou sem permissão: o servidor é a fonte */ }
}

// ------------------------------------------------------------------------ rede

async function json(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}
const cabecalhos = () => ({ "content-type": "application/json", "x-ewc-key": E.chave });

async function apiGet() {
  const r = await fetch("/api/state", { headers: cabecalhos(), cache: "no-store" });
  return { status: r.status, corpo: r.ok || r.status === 401 ? await r.json().catch(() => ({})) : {} };
}

async function carregarBase() {
  const [codebook, indice] = await Promise.all([json(`${CORPUS}/assistente/codebook.json`), json(`${CORPUS}/md/index.json`)]);
  E.codebook = codebook;
  E.indice = indice;
}

async function dadosDoServico(nome) {
  if (E.cache.has(nome)) return E.cache.get(nome);
  const svc = E.indice.services.find((s) => s.name === nome);
  const slug = svc.slug;
  const [piso, sug, cop] = await Promise.all([
    json(`${CORPUS}/assistente/piso/${slug}.json`),
    json(`${CORPUS}/sugestoes/${slug}.json`).catch(() => null),
    json(`${CORPUS}/assistente/copiloto/${slug}.json`).catch(() => null),
  ]);
  const citacoesPorId = {};
  for (const [vid, lista] of Object.entries((sug && sug.citacoes) || {})) {
    lista.forEach((c, i) => { citacoesPorId[`${vid}-${i + 1}`] = c; });
  }
  const d = { slug, piso, docs: piso.docs, citacoes: (sug && sug.citacoes) || {}, citacoesPorId,
              copiloto: cop && !cop.invalida ? cop : null };
  E.cache.set(nome, d);
  return d;
}

// --------------------------------------------------------------------- gravação

function registro(servico) { return (E.records[servico] ||= {}); }

function semMeta(reg) { const { _pendente, ...resto } = reg; return resto; }

function marcarEdicao(servico) {
  registro(servico)._pendente = true;
  E.pendentes.add(servico);
  persistirLocal();
  clearTimeout(E.timerEdicao);
  E.timerEdicao = setTimeout(() => salvar(servico), DEBOUNCE);
  pintarRecibos();
}

// Uma gravação por vez por serviço. Quem chama não espera: o recibo conta.
function salvar(servico) {
  clearTimeout(E.timerEdicao);
  const anterior = E.gravando.get(servico) || Promise.resolve();
  const p = anterior.then(() => gravarAgora(servico)).catch(() => false);
  E.gravando.set(servico, p);
  p.finally(() => { if (E.gravando.get(servico) === p) E.gravando.delete(servico); pintarRecibos(); });
  pintarRecibos();
  return p;
}

async function gravarAgora(servico) {
  const reg = registro(servico);
  E.recibo[servico] = { estado: "andamento", texto: "gravando…" };
  pintarRecibos();
  try {
    const r = await fetch("/api/state", {
      method: "PUT", headers: cabecalhos(),
      body: JSON.stringify({ servico, registro: semMeta(reg), base_ts: E.baseTs[servico] || 0 }),
    });
    if (r.status === 409) {
      const j = await r.json();
      E.records[servico] = j.registro || {};
      E.baseTs[servico] = (j.registro && j.registro._ts) || 0;
      E.pendentes.delete(servico);
      persistirLocal();
      E.recibo[servico] = { estado: "erro", texto: "alterado em outra janela" };
      if (E.servico === servico) {
        E.avisoConflito = true;
        render();
      }
      return false;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    E.baseTs[servico] = j._ts;
    reg._ts = j._ts;
    delete reg._pendente;
    E.pendentes.delete(servico);
    E.tentativa[servico] = 0;
    persistirLocal();
    E.recibo[servico] = { estado: "ok", texto: `gravado às ${hora()}` };
    return true;
  } catch (e) {
    const n = E.tentativa[servico] || 0;
    E.tentativa[servico] = n + 1;
    const atraso = ATRASOS[Math.min(n, ATRASOS.length - 1)];
    E.recibo[servico] = { estado: "erro", texto: `não gravou: tentando de novo em ${atraso / 1000} s` };
    setTimeout(() => { if (E.pendentes.has(servico)) salvar(servico); }, atraso);
    return false;
  }
}

function pintarRecibos() {
  const r = E.servico ? E.recibo[E.servico] : null;
  for (const no of document.querySelectorAll(".recibo")) {
    no.className = `recibo ${r ? r.estado : ""}`;
    no.textContent = r ? r.texto : "";
  }
  const btn = document.getElementById("proximo");
  if (btn) {
    const esperando = E.pendentes.has(E.servico) || E.gravando.has(E.servico);
    btn.disabled = esperando;
    btn.textContent = esperando ? "aguardando gravação…" : btn.dataset.rotulo;
  }
}

// ----------------------------------------------------------------------- telas

function mostrar(html) { limpar(app); app.appendChild(el(`<div>${html}</div>`)); window.scrollTo(0, 0); }

function telaSemChave() {
  mostrar(`<h1>Segunda codificação</h1>
    <div class="caixa papel"><p>Este endereço precisa do link que você recebeu. Abra a página por ele, com a parte depois de <code>#</code> inteira.</p></div>`);
}

function telaChaveInvalida() {
  mostrar(`<h1>Segunda codificação</h1>
    <div class="caixa papel"><p>A chave deste link não é válida. Peça o link de novo a quem o enviou.</p></div>`);
}

function telaErro(msg) {
  mostrar(`<h1>Segunda codificação</h1>
    <div class="falta"><p>Não consegui carregar a página: ${esc(msg)}</p><p>Recarregue. Se continuar, avise quem enviou o link.</p></div>`);
}

const ABERTURA = `
<h1>Segunda codificação</h1>
<p class="suave">Prof. Marcelo Maia · 26 serviços · 10 etapas por serviço</p>

<h2>O que o estudo mede</h2>
<p>Plataformas online testam coisas nos seus usuários todos os dias. Elas mudam o que aparece no topo da lista, o texto de uma notificação, a posição de um botão, e medem o efeito comparando grupos de pessoas. Isso se chama experimentação comportamental e é rotina da indústria.</p>
<p>A pergunta do estudo é estreita e documental: <b>o que cada plataforma conta ao usuário sobre isso, e em que tipo de documento ela conta?</b> Ninguém aqui vai descobrir quais experimentos existem. O trabalho é ler o que a plataforma declara e classificar a declaração.</p>
<p>O tipo de documento é o centro do estudo. Uma política de privacidade obriga a plataforma perante o usuário. Um post de blog de engenharia não obriga nada. Quando os dois falam do mesmo assunto em termos diferentes, essa diferença é o dado.</p>

<h2>Os 26 serviços</h2>
<p>Não é uma amostra, é um censo. São os 26 serviços que a Comissão Europeia designou sob o Digital Services Act: 24 como VLOP (<i>very large online platform</i>) e 2 como VLOSE (<i>very large online search engine</i>). A unidade de análise é o serviço, não a empresa: o Google Ireland responde por cinco deles e a Meta por dois. Quatro são plataformas de conteúdo adulto, e estão no censo porque são VLOPs de pleno direito.</p>
<p>Cada serviço tem de 3 a 10 documentos, 157 no total: política de privacidade, termos de uso, aviso de cookies, tabela de bases legais, e o que a plataforma publicou em blog ou central de ajuda sobre o assunto. Todos foram congelados em texto. É esse texto que você lê aqui.</p>

<h2>Por que existe uma segunda codificação</h2>
<p>A primeira passada já foi feita. Uma classificação com fonte única não separa duas coisas: quanto do resultado vem do texto e quanto vem de quem leu o texto. Duas leituras independentes do mesmo material permitem medir a concordância entre elas, e é essa medida que torna o resultado defensável diante de um revisor.</p>
<p><b>Esta página não mostra o que a primeira passada codificou, nem os resultados do estudo.</b> Se você soubesse o que se espera encontrar, sua leitura deixaria de ser uma segunda medição.</p>

<h2>O que você faz</h2>
<p>A página leva você por um serviço de cada vez e, dentro dele, por <b>uma pergunta por tela</b>: as nove variáveis e, no fim, o log de palavras-chave. Em cada tela você lê a evidência, responde, e clica em <b>Confirmar e seguir</b>. Nenhuma etapa fecha sem resposta e sem evidência. O botão <b>Voltar</b> deixa rever o que já respondeu.</p>
<p>A evidência vem em duas listas. A <b>busca por palavra-chave</b> procura os 12 termos do protocolo no texto congelado. Não passa por modelo nenhum e não deixa nada de fora; alguns trechos chegam com aviso, porque o termo costuma aparecer em outro sentido. Depois vem o que <b>o modelo</b> localizou: passagens que descrevem experimentação sem usar nenhum dos termos. O botão <b>usar como evidência</b> copia o trecho para o campo de evidência; <b>abrir no documento</b> mostra o trecho no texto inteiro.</p>
<p>Em cada tela há também o botão <b>ver sugestão do copiloto</b>. Ele mostra o que um modelo de linguagem proporia para aquela variável, com a razão e os trechos que a sustentam, e o botão <b>aplicar sugestão</b> preenche os campos. A decisão é sua. O copiloto só viu o texto congelado, e o prompt dele está publicado, no link dentro da própria caixa.</p>
<p>No fim de cada tela há o campo <b>Notas</b>, para dúvidas de regra e casos de fronteira. Pode parar a qualquer momento e fechar a página. Quando voltar, ela abre onde você parou.</p>

<h2>Duas regras que afetam o resultado</h2>
<p><b>Leia sempre o texto congelado, nunca a página ao vivo.</b> As plataformas reescrevem as políticas sem avisar. Se os dois codificadores lerem versões diferentes, a discordância fica indistinguível de mudança no documento.</p>
<p><b>Confira a confirmação ao lado do botão.</b> Cada resposta é gravada num servidor. Verde, "gravado às", significa que chegou. Vermelho significa que não chegou e que a página vai tentar de novo sozinha; se ficar vermelho, pare e avise. Não deixe o mesmo serviço aberto em duas janelas ao mesmo tempo.</p>
<p><b>Codifique só por esta página.</b> Qualquer outra versão da ferramenta que você tenha recebido antes mostra informações que não devem estar na sua frente durante a codificação.</p>
`;

function telaAbertura() {
  mostrar(`${ABERTURA}
    <div class="botoes"><button class="primario" id="comecar">Começar</button>
    <button class="secundario" id="regras">Ver as cinco regras gerais</button></div>`);
  document.getElementById("comecar").onclick = () => { try { localStorage.setItem(LS.abertura, "1"); } catch {} telaContinuar(); };
  document.getElementById("regras").onclick = abrirRegras;
}

function telaContinuar() {
  const cb = E.codebook;
  const proximo = proximoServico(cb, E.records, null);
  const itens = cb.servicos.map((s) => {
    const reg = E.records[s] || {};
    const p = progresso(cb, reg);
    const estado = p.feitas === p.total ? `<span class="estado feito">concluído</span>`
      : p.feitas === 0 ? `<span class="estado">não iniciado</span>` : `<span class="estado">${p.feitas} de ${p.total}</span>`;
    return `<li><a href="#" data-servico="${esc(s)}">${esc(s)}</a>${estado}</li>`;
  }).join("");
  const feitos = cb.servicos.filter((s) => concluido(cb, E.records[s] || {})).length;
  mostrar(`<h1>Segunda codificação</h1>
    <p class="suave">${feitos} de ${cb.servicos.length} serviços concluídos</p>
    ${proximo ? `<div class="botoes"><button class="primario" id="continuar">Continuar: ${esc(proximo)}</button></div>` : ""}
    <div class="caixa"><ul class="lista-servicos">${itens}</ul></div>
    <p class="pequeno"><a href="#" id="reler">Reler a abertura</a> · <a href="#" id="regras">Cinco regras gerais</a> · <a href="/assistente/copiloto.html" target="_blank" rel="noopener">Como o copiloto funciona</a></p>`);
  if (proximo) document.getElementById("continuar").onclick = () => abrirServico(proximo);
  for (const a of app.querySelectorAll("a[data-servico]")) a.onclick = (ev) => { ev.preventDefault(); abrirServico(a.dataset.servico); };
  document.getElementById("reler").onclick = (ev) => { ev.preventDefault(); telaAbertura(); };
  document.getElementById("regras").onclick = (ev) => { ev.preventDefault(); abrirRegras(); };
  if (!proximo) telaFim();
}

function telaFim() {
  mostrar(`<div class="fim"><h1>Pronto.</h1><p>Os 26 serviços estão codificados. Obrigado.</p>
    <p class="pequeno"><a href="#" id="lista">Ver a lista de serviços</a></p></div>`);
  document.getElementById("lista").onclick = (ev) => { ev.preventDefault(); telaContinuar(); };
}

async function abrirServico(nome) {
  mostrar(`<p class="suave">Carregando ${esc(nome)}…</p>`);
  try {
    await dadosDoServico(nome);
  } catch (e) {
    telaErro(`${nome}: ${e.message}`);
    return;
  }
  E.servico = nome;
  E.i = primeiroIncompleto(E.codebook, registro(nome));
  E.copilotoAberto = false;
  E.avisoConflito = false;
  render();
}

function render() {
  if (!E.servico) { telaContinuar(); return; }
  if (E.i >= E.codebook.variaveis.length) renderResumo();
  else renderVariavel();
}

// ------------------------------------------------------------ tela da variável

function cabecalhoServico(d) {
  const cb = E.codebook;
  const reg = registro(E.servico);
  const p = progresso(cb, reg);
  const f = fechados(cb, reg);
  const trilha = cb.variaveis.map((v, k) => {
    const cls = k === E.i ? "atual" : f[v.vid] ? "fechado" : "futuro";
    return `<button class="${cls}" data-passo="${k}" ${cls === "futuro" ? "disabled" : ""} title="${esc(v.titulo)}">${esc(v.vid)}</button>`;
  }).join("") + `<button class="${E.i >= cb.variaveis.length ? "atual" : p.feitas === p.total ? "fechado" : "futuro"}" data-passo="${cb.variaveis.length}" ${p.feitas === p.total ? "" : "disabled"}>resumo</button>`;
  const docs = d.docs.map((x) => `<li><span class="n">${x.n}.</span>
      <span>${esc(x.titulo || x.file.split("/").pop())}</span>
      <button class="pequeno" data-abrir="${esc(x.file)}">abrir texto congelado</button>
      <span class="suave pequeno">${x.chars.toLocaleString("pt-BR")} caracteres</span>
      <span class="url">página original: <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a></span></li>`).join("");
  return `<div class="cabecalho">
    <div class="linha1"><h1>${esc(E.servico)}</h1>
      <span class="suave">${d.docs.length} documentos · ${p.feitas} de ${p.total} etapas</span>
      <span class="recibo"></span></div>
    <div class="trilha">${trilha}</div>
    <details><summary class="pequeno suave" style="cursor:pointer">documentos do serviço (${d.docs.length})</summary><ul class="docs">${docs}</ul></details>
    <p class="pequeno suave" style="margin:6px 0 0"><a href="#" id="voltar-lista">todos os serviços</a> · <a href="#" id="regras">cinco regras gerais</a></p>
  </div>`;
}

function ligarCabecalho(d) {
  for (const b of app.querySelectorAll(".trilha button[data-passo]")) {
    b.onclick = () => { if (!b.disabled) { E.i = Number(b.dataset.passo); E.copilotoAberto = false; render(); } };
  }
  for (const b of app.querySelectorAll("button[data-abrir]")) {
    b.onclick = () => abrirDocumento(b.dataset.abrir, null, d);
  }
  document.getElementById("voltar-lista").onclick = (ev) => { ev.preventDefault(); salvar(E.servico); E.servico = null; telaContinuar(); };
  document.getElementById("regras").onclick = (ev) => { ev.preventDefault(); abrirRegras(); };
}

function itemEvidencia(cit, d, classe, extra) {
  const titulo = (d.docs.find((x) => x.n === cit.doc) || {}).titulo || "";
  return `<div class="item ${classe}">
    ${extra || ""}
    <div>${esc(cit.verbatim)}</div>
    <div class="onde">Documento ${cit.doc}${titulo ? `: ${esc(titulo)}` : ""}${cit.onde ? ` · ${esc(cit.onde)}` : ""}</div>
    <div class="acoes"><button class="pequeno" data-abrir-trecho="${esc(cit.file)}" data-trecho="${esc(cit.verbatim)}">abrir no documento</button>
      <button class="pequeno" data-usar="${esc(JSON.stringify({ doc: cit.doc, file: cit.file, onde: cit.onde, verbatim: cit.verbatim }))}">usar como evidência</button></div>
  </div>`;
}

function campoHtml(c, reg) {
  const ajuda = (E.codebook.ajuda_campos || {})[c.chave];
  const ajudaHtml = ajuda ? `<div class="ajuda">${esc(Array.isArray(ajuda) ? ajuda[0] : ajuda)}</div>` : "";
  if (c.tipo === "select" || c.tipo === "checks") {
    const atual = reg[c.chave];
    const marcados = new Set(Array.isArray(atual) ? atual : atual ? [atual] : []);
    const ops = c.opcoes.filter((o) => o !== "").map((o) => {
      const av = (E.codebook.ajuda_valores || {})[`${c.chave}:${o}`];
      const texto = av ? ` <span class="suave">${esc(Array.isArray(av) ? av[0] : av)}</span>` : "";
      const tipo = c.tipo === "select" ? "radio" : "checkbox";
      return `<label class="${marcados.has(o) ? "marcado" : ""}"><input type="${tipo}" name="${esc(c.chave)}" value="${esc(o)}" ${marcados.has(o) ? "checked" : ""}><b>${esc(o)}</b>${texto}</label>`;
    }).join("");
    return `<div class="campo" data-campo="${esc(c.chave)}"><span class="rotulo">${esc(c.rotulo)}</span>${ajudaHtml}<div class="opcoes">${ops}</div></div>`;
  }
  if (c.tipo === "line") {
    return `<div class="campo" data-campo="${esc(c.chave)}"><label class="rotulo" for="f-${esc(c.chave)}">${esc(c.rotulo)}</label>${ajudaHtml}
      <input type="text" id="f-${esc(c.chave)}" name="${esc(c.chave)}" value="${esc(reg[c.chave] || "")}" placeholder="${esc(c.placeholder || "")}"></div>`;
  }
  return `<div class="campo" data-campo="${esc(c.chave)}"><label class="rotulo" for="f-${esc(c.chave)}">${esc(c.rotulo)}</label>${ajudaHtml}
    <textarea id="f-${esc(c.chave)}" name="${esc(c.chave)}" placeholder="${esc(c.placeholder || "")}">${esc(reg[c.chave] || "")}</textarea></div>`;
}

function renderVariavel() {
  const cb = E.codebook;
  const v = cb.variaveis[E.i];
  const d = E.cache.get(E.servico);
  const reg = registro(E.servico);
  const ehKw = v.vid === "KW";

  if (ehKw && !reg.keyword_log) {
    reg.keyword_log = logSugerido(d.piso);
  }

  const hits = (d.piso.por_variavel || {})[v.vid] || [];
  const cits = d.citacoes[v.vid] || [];
  const sugestao = d.copiloto && d.copiloto.variaveis ? d.copiloto.variaveis[v.vid] : null;

  const hitsHtml = hits.map((h) => itemEvidencia(
    { doc: h.n, file: h.file, onde: `palavra-chave "${h.termo}"`, verbatim: h.kwic }, d, "piso",
    `<span class="termo">${esc(h.termo)}</span> <span class="suave pequeno">(${h.total_no_doc} no documento)</span>${h.flag ? `<div class="flag">⚠ ${esc(h.flag)}</div>` : ""}`,
  )).join("");
  const citsHtml = cits.map((c) => itemEvidencia(c, d, "modelo")).join("");

  const sugestaoHtml = sugestao ? `<div class="sugestao ${E.copilotoAberto ? "" : "oculto"}" id="caixa-copiloto">
      <div><b>Sugestão do copiloto</b> <span class="conf">· confiança ${esc(sugestao.confianca)}</span></div>
      <ul style="margin:8px 0">${Object.entries(sugestao.campos).map(([k, val]) => {
        const campo = v.campos.find((c) => c.chave === k);
        return `<li>${esc(campo ? campo.rotulo : k)}: <span class="valor">${esc(Array.isArray(val) ? val.join(", ") : (val || "(vazio)"))}</span></li>`;
      }).join("")}</ul>
      <p>${esc(sugestao.razao)}</p>
      ${(sugestao.citacoes || []).length ? `<p class="pequeno suave">Trechos que ela usa: ${sugestao.citacoes.map(esc).join(", ")}</p>` : ""}
      <div class="botoes" style="margin:8px 0 0"><button class="copiloto" id="aplicar">aplicar sugestão</button>
        <a class="pequeno" href="/assistente/copiloto.html" target="_blank" rel="noopener">como o copiloto funciona</a></div>
    </div>` : "";

  const kwTexto = ehKw ? `<p class="suave">O log já vem preenchido com as contagens automáticas, documento por documento. Corrija o que for falso positivo. O que ficar aqui é o registro do que você procurou.</p>` : "";

  mostrar(`${cabecalhoServico(d)}
    <div class="pergunta">[${esc(v.vid)}] ${esc(v.pergunta || v.titulo)}</div>
    <p class="lembrete">${esc(v.lembrete)} <a href="#" id="criterio">critério completo</a></p>
    ${E.avisoConflito ? `<div class="aviso">Este serviço foi alterado em outra janela. Recarreguei as respostas; confira e continue.</div>` : ""}
    ${kwTexto}
    ${ehKw ? "" : `<div class="evid">
      <h3>Busca por palavra-chave <span class="suave pequeno">${hits.length} trecho${hits.length === 1 ? "" : "s"}</span></h3>
      ${hits.length ? hitsHtml : `<p class="suave pequeno">Nenhum dos termos endereçados a esta variável aparece nos documentos.</p>`}
      <h3>Localizado pelo modelo <span class="suave pequeno">${cits.length} citaç${cits.length === 1 ? "ão" : "ões"}</span></h3>
      ${cits.length ? citsHtml : `<p class="suave pequeno">O modelo não localizou passagem para esta variável.</p>`}
    </div>`}
    ${sugestao ? `<div class="botoes" style="margin:6px 0"><button class="copiloto" id="ver-copiloto">${E.copilotoAberto ? "esconder sugestão" : "ver sugestão do copiloto"}</button></div>` : (ehKw ? "" : `<p class="pequeno suave">O copiloto não tem sugestão para esta variável.</p>`)}
    ${sugestaoHtml}
    <div class="campos">${v.campos.map((c) => campoHtml(c, reg)).join("")}</div>
    <div id="falta"></div>
    <div class="botoes">
      ${E.i > 0 ? `<button class="secundario" id="voltar">Voltar</button>` : ""}
      <button class="primario" id="confirmar">Confirmar e seguir</button>
      <span class="recibo"></span>
    </div>
    <div class="caixa papel" style="margin-top:28px">
      <label class="rotulo" for="notas"><b>Notas sobre este serviço</b> <span class="suave pequeno">dúvidas de regra, casos de fronteira, diferenças entre documentos</span></label>
      <textarea id="notas" style="width:100%;min-height:70px;margin-top:6px;font:inherit;padding:8px 10px;border:1px solid var(--linha);border-radius:8px">${esc(reg.notes || "")}</textarea>
    </div>
    <footer class="rodape">Texto congelado em ${esc(E.indice.frozen_at ? E.indice.frozen_at.slice(0, 10) : "")} · critério congelado em ${esc(cb.congelado_em)} · <a href="/assistente/copiloto.html" target="_blank" rel="noopener">como o copiloto funciona</a></footer>`);

  ligarCabecalho(d);
  pintarRecibos();
  document.getElementById("criterio").onclick = (ev) => { ev.preventDefault(); abrirCriterio(v); };

  for (const b of app.querySelectorAll("button[data-abrir-trecho]")) {
    b.onclick = () => abrirDocumento(b.dataset.abrirTrecho, b.dataset.trecho, d);
  }
  for (const b of app.querySelectorAll("button[data-usar]")) {
    b.onclick = () => {
      const cit = JSON.parse(b.dataset.usar);
      const campoTexto = v.campos.find((c) => c.tipo === "text" && c.chave !== "keyword_log");
      if (!campoTexto) return;
      const atual = (reg[campoTexto.chave] || "").trim();
      const linha = textoDeEvidencia(cit, d.docs);
      reg[campoTexto.chave] = atual ? `${atual}\n${linha}` : linha;
      const ta = document.getElementById(`f-${campoTexto.chave}`);
      if (ta) { ta.value = reg[campoTexto.chave]; ta.scrollIntoView({ block: "center", behavior: "smooth" }); }
      marcarEdicao(E.servico);
      b.textContent = "copiado para a evidência";
      b.disabled = true;
    };
  }

  // Campos: cada mudança vai para o registro, para o navegador e, com atraso, para o servidor.
  for (const input of app.querySelectorAll(".campos input, .campos textarea")) {
    input.addEventListener("input", () => lerCampos(v, reg));
    input.addEventListener("change", () => lerCampos(v, reg));
  }
  const notas = document.getElementById("notas");
  notas.addEventListener("input", () => { reg.notes = notas.value; marcarEdicao(E.servico); });

  const btnVer = document.getElementById("ver-copiloto");
  if (btnVer) btnVer.onclick = () => { E.copilotoAberto = !E.copilotoAberto; render(); if (E.copilotoAberto) document.getElementById("caixa-copiloto").scrollIntoView({ block: "start", behavior: "smooth" }); };
  const btnAplicar = document.getElementById("aplicar");
  if (btnAplicar) btnAplicar.onclick = () => {
    E.records[E.servico] = aplicarSugestao(v, reg, sugestao, d.citacoesPorId, d.docs);
    marcarEdicao(E.servico);
    render();
    document.querySelector(".campos").scrollIntoView({ block: "start", behavior: "smooth" });
  };

  const btnVoltar = document.getElementById("voltar");
  if (btnVoltar) btnVoltar.onclick = () => { salvar(E.servico); E.i -= 1; E.copilotoAberto = false; E.avisoConflito = false; render(); };
  document.getElementById("confirmar").onclick = () => {
    lerCampos(v, reg, false);
    const pend = faltando(v, reg);
    const caixa = document.getElementById("falta");
    if (pend.length) {
      const nomes = pend.map(([chave, motivo]) => {
        const c = v.campos.find((x) => x.chave === chave);
        return `<li><b>${esc(c ? c.rotulo : chave)}</b>: falta ${esc(motivo)}</li>`;
      }).join("");
      caixa.innerHTML = `<div class="falta">Para seguir, preencha:<ul style="margin:6px 0 0">${nomes}</ul></div>`;
      caixa.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    salvar(E.servico);
    E.i += 1;
    E.copilotoAberto = false;
    E.avisoConflito = false;
    render();
  };
}

function lerCampos(v, reg, agendar = true) {
  for (const c of v.campos) {
    if (c.tipo === "select") {
      const m = app.querySelector(`input[name="${CSS.escape(c.chave)}"]:checked`);
      reg[c.chave] = m ? m.value : "";
    } else if (c.tipo === "checks") {
      reg[c.chave] = [...app.querySelectorAll(`input[name="${CSS.escape(c.chave)}"]:checked`)].map((x) => x.value);
    } else {
      const no = document.getElementById(`f-${c.chave}`);
      if (no) reg[c.chave] = no.value;
    }
  }
  for (const label of app.querySelectorAll(".opcoes label")) {
    label.classList.toggle("marcado", label.querySelector("input").checked);
  }
  if (agendar) marcarEdicao(E.servico);
}

// ------------------------------------------------------------------- resumo

function renderResumo() {
  const cb = E.codebook;
  const d = E.cache.get(E.servico);
  const reg = registro(E.servico);
  const linhas = cb.variaveis.map((v) => {
    const valores = v.campos.filter((c) => c.tipo !== "text").map((c) => {
      const val = reg[c.chave];
      const t = Array.isArray(val) ? val.join(", ") : (val || "");
      return t ? `<div><span class="suave">${esc(c.rotulo)}:</span> <b>${esc(t)}</b></div>` : "";
    }).join("");
    const textos = v.campos.filter((c) => c.tipo === "text").map((c) => {
      const t = (reg[c.chave] || "").trim();
      return t ? `<div class="pequeno suave">${esc(t.length > 220 ? t.slice(0, 219) + "…" : t)}</div>` : "";
    }).join("");
    return `<tr><th>[${esc(v.vid)}] ${esc(v.titulo)}</th><td>${valores}${textos}</td></tr>`;
  }).join("");
  const proximo = proximoServico(cb, E.records, E.servico);
  mostrar(`${cabecalhoServico(d)}
    <h2>Resumo de ${esc(E.servico)}</h2>
    <p class="suave">As dez etapas estão fechadas. Confira e siga para o próximo serviço, ou volte para rever.</p>
    <div class="caixa resumo"><table>${linhas}</table></div>
    ${reg.notes ? `<div class="caixa papel"><b>Notas:</b> ${esc(reg.notes)}</div>` : ""}
    <div class="botoes">
      <button class="secundario" id="voltar">Voltar</button>
      <button class="primario" id="proximo" data-rotulo="${proximo ? `Próximo serviço: ${esc(proximo)}` : "Concluir"}">…</button>
      <span class="recibo"></span>
    </div>`);
  ligarCabecalho(d);
  pintarRecibos();
  document.getElementById("voltar").onclick = () => { E.i = cb.variaveis.length - 1; render(); };
  document.getElementById("proximo").onclick = () => {
    if (proximo) abrirServico(proximo);
    else { E.servico = null; telaFim(); }
  };
}

// ------------------------------------------------------------------- painéis

function abrirPainel(titulo, corpoHtml) {
  limpar(painel);
  painel.appendChild(el(`<div style="display:contents"><header><h2>${titulo}</h2><button class="pequeno" id="fechar-painel">fechar</button></header>
    <div class="corpo">${corpoHtml}</div></div>`));
  painel.classList.remove("oculto");
  document.getElementById("fechar-painel").onclick = fecharPainel;
  return painel.querySelector(".corpo");
}
function fecharPainel() { painel.classList.add("oculto"); limpar(painel); }
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") fecharPainel(); });

function abrirCriterio(v) {
  abrirPainel(`[${esc(v.vid)}] ${esc(v.titulo)}`, `${v.guia_html || ""}
    ${v.crit_html ? `<div class="crit"><h4>${esc(E.codebook.fonte_crit)}</h4>${v.crit_html}</div>` : ""}`);
}

function abrirRegras() {
  abrirPainel("Regras gerais", E.codebook.regras_gerais_html || "");
}

function normalizarComMapa(texto) {
  const partes = []; const mapa = [];
  let espaco = false;
  for (let i = 0; i < texto.length; i++) {
    const ch = texto[i];
    if (/\s/.test(ch)) { if (!espaco && partes.length) { partes.push(" "); mapa.push(i); } espaco = true; }
    else { partes.push(ch.toLowerCase()); mapa.push(i); espaco = false; }
  }
  return { norm: partes.join(""), mapa };
}

function localizar(texto, trecho) {
  if (!trecho) return null;
  const limpo = trecho.replace(/^[…\.\s]+|[…\.\s]+$/g, "");
  const { norm, mapa } = normalizarComMapa(texto);
  const candidatos = [limpo];
  if (limpo.length > 80) candidatos.push(limpo.slice(Math.floor(limpo.length / 2) - 40, Math.floor(limpo.length / 2) + 40));
  for (const c of candidatos) {
    const alvo = normalizarComMapa(c).norm.trim();
    if (alvo.length < 8) continue;
    const pos = norm.indexOf(alvo);
    if (pos >= 0) return [mapa[pos], mapa[pos + alvo.length - 1] + 1];
  }
  return null;
}

async function abrirDocumento(file, trecho, d) {
  const doc = d.docs.find((x) => x.file === file) || {};
  const url = `${CORPUS}/md/${file}`;
  const corpo = abrirPainel(esc(doc.titulo || file), `<p class="nota">Documento ${doc.n || ""} · texto congelado · <a href="${esc(url)}" target="_blank" rel="noopener">baixar o arquivo congelado</a></p><p class="nota">carregando…</p>`);
  let texto;
  try {
    if (!E.textos.has(file)) {
      const r = await fetch(url, { cache: "force-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      let t = await r.text();
      t = t.replace(/^---\n[\s\S]*?\n---\n/, "");
      E.textos.set(file, t);
    }
    texto = E.textos.get(file);
  } catch (e) {
    corpo.innerHTML = `<p class="nota">Não consegui abrir o texto (${esc(e.message)}). <a href="${esc(url)}" target="_blank" rel="noopener">Abrir o arquivo direto</a>.</p>`;
    return;
  }
  const pos = localizar(texto, trecho);
  const pre = document.createElement("pre");
  if (pos) {
    pre.append(texto.slice(0, pos[0]));
    const m = document.createElement("mark"); m.textContent = texto.slice(pos[0], pos[1]); pre.append(m);
    pre.append(texto.slice(pos[1]));
  } else {
    pre.textContent = texto;
  }
  corpo.innerHTML = `<p class="nota">Documento ${doc.n || ""} · texto congelado · <a href="${esc(url)}" target="_blank" rel="noopener">baixar o arquivo congelado</a>${trecho && !pos ? " · trecho não localizado automaticamente; use a busca do navegador" : ""}</p>`;
  corpo.appendChild(pre);
  const marca = pre.querySelector("mark");
  if (marca) setTimeout(() => marca.scrollIntoView({ block: "center" }), 30);
}

// -------------------------------------------------------------------- ensaio

function ligarEnsaio() {
  faixa.classList.remove("oculto");
  document.body.classList.add("ensaio");
  document.getElementById("zerar").onclick = async () => {
    if (!window.confirm("Zerar o ensaio apaga todas as respostas gravadas com este link de ensaio. Continuar?")) return;
    const r = await fetch("/api/state", { method: "DELETE", headers: cabecalhos() });
    if (!r.ok) { window.alert(`Não consegui zerar (HTTP ${r.status}).`); return; }
    E.records = {}; E.baseTs = {}; E.pendentes.clear(); E.recibo = {}; E.servico = null;
    persistirLocal();
    telaContinuar();
  };
}

// ---------------------------------------------------------------------- início

async function iniciar() {
  let chave = chaveDoLink(location.hash);
  if (chave) { try { localStorage.setItem(LS.chave, chave); } catch {} }
  else { try { chave = localStorage.getItem(LS.chave); } catch {} }
  if (!chave) { telaSemChave(); return; }
  E.chave = chave;

  let servidor;
  try {
    servidor = await apiGet();
  } catch (e) {
    telaErro(`servidor fora do ar (${e.message})`);
    return;
  }
  if (servidor.status === 401) { telaChaveInvalida(); return; }
  if (servidor.status !== 200) { telaErro(`servidor respondeu ${servidor.status}`); return; }
  E.modo = servidor.corpo.modo;
  if (E.modo === "ensaio") ligarEnsaio();

  try {
    await carregarBase();
  } catch (e) {
    telaErro(e.message);
    return;
  }

  const m = mesclar(lerLocal(), servidor.corpo.records || {});
  E.records = m.records;
  for (const [s, reg] of Object.entries(servidor.corpo.records || {})) E.baseTs[s] = reg._ts || 0;
  persistirLocal();
  for (const s of m.pendentes) { E.pendentes.add(s); salvar(s); }

  let viu = false;
  try { viu = !!localStorage.getItem(LS.abertura); } catch {}
  if (viu) telaContinuar(); else telaAbertura();
}

iniciar();
