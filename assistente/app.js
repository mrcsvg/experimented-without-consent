// A página do assistente: DOM, rede e armazenamento. A lógica sem DOM está em
// core.mjs. Os dados congelados vêm do site do corpus; as respostas vão para
// /api/state, neste mesmo site, e ficam também no navegador.
//
// Versão B (04/10/2026): o codificador classifica os documentos, dá uma nota a
// cada trecho e a resposta de cada variável é calculada do critério congelado.
import {
  derivar, faltandoEtapa, etapas, fechadas, progressoEtapas, primeiraEtapaIncompleta,
  trechosDaVariavel, aplicarNotas, registroPadrao,
  progressoConfirmado, concluidoConfirmado, proximoServicoPorConfirmacao,
  logSugerido, chaveDoLink, mesclar, NAO_E_ISSO,
} from "./core.mjs";

// Em localhost, ?corpus=... aponta para uma cópia local do site do corpus
// (server/dev.mjs serve o repositório irmão em /corpus). Em produção, só o site.
const CORPUS = (location.hostname === "localhost" && new URLSearchParams(location.search).get("corpus"))
  || "https://experimented-without-consent-corpus.vercel.app";
const LS = { records: "ewc.records", abertura: "ewc.abertura", chave: "ewc.chave" };
const ATRASOS = [5000, 10000, 20000, 30000];
const DEBOUNCE = 1200;
const SUB = { notas: {}, extras: {}, override: {}, comentarios: {}, confirmadas: {} };

const E = {
  chave: null, modo: null, codebook: null, indice: null,
  records: {}, baseTs: {}, pendentes: new Set(), gravando: new Map(), tentativa: {}, recibo: {},
  servico: null, i: 0, cache: new Map(), textos: new Map(), copilotoAberto: false, corrigindo: false, timerEdicao: null,
  avisoConflito: false,
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
  const d = { slug, piso, docs: piso.docs, citacoes: (sug && sug.citacoes) || {},
              copiloto: cop && cop.formato === 2 && !cop.invalida ? cop : null };
  E.cache.set(nome, d);
  return d;
}

// --------------------------------------------------------------------- gravação

function registro(servico) {
  const r = (E.records[servico] ||= {});
  for (const k of Object.keys(SUB)) if (!r[k] || typeof r[k] !== "object") r[k] = {};
  return r;
}

function semMeta(reg) { const { _pendente, ...resto } = reg; return resto; }

// Os campos planos (os de hoje, que o κ lê) são recalculados das notas a cada
// mudança, e gravados junto com os dados estruturados.
function sincronizar(servico) {
  const d = E.cache.get(servico);
  if (!d) return;
  Object.assign(registro(servico), derivar(E.codebook, registro(servico), d).campos);
}

function marcarEdicao(servico) {
  sincronizar(servico);
  registro(servico)._pendente = true;
  E.pendentes.add(servico);
  persistirLocal();
  clearTimeout(E.timerEdicao);
  E.timerEdicao = setTimeout(() => salvar(servico), DEBOUNCE);
  pintarRecibos();
}

// Qualquer edição numa etapa já confirmada a reabre: confirmar é dizer
// "está pronto", e o que mudou depois ainda não foi dito.
function editar(etapa) {
  const reg = registro(E.servico);
  if (reg.confirmadas[etapa]) delete reg.confirmadas[etapa];
  marcarEdicao(E.servico);
}

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
      if (E.servico === servico) { E.avisoConflito = true; render(); }
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

function mostrar(html, manterScroll = false) {
  const y = window.scrollY;
  limpar(app);
  app.appendChild(el(`<div>${html}</div>`));
  window.scrollTo(0, manterScroll ? y : 0);
}

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
<p>A página leva você por um serviço de cada vez: as nove variáveis e o log de palavras-chave, <b>uma por tela</b>. O tipo de cada documento (política de privacidade, termos de uso, aviso de pesquisa, central de ajuda, blog) já vem dado com o corpus e aparece ao lado de cada trecho. O tipo decide se o documento obriga a plataforma ou não. Se achar que um tipo está errado, anote em Notas.</p>
<p>Em cada variável a página mostra os trechos dos documentos que falam do assunto, vindos de duas buscas: a busca por palavra-chave, que procura os 12 termos do protocolo no texto congelado e não deixa nada de fora, e a busca do modelo, que localiza passagens que descrevem experimentação sem usar nenhum dos termos. <b>Você dá uma nota a cada trecho</b>: o que aquele trecho mostra, nas opções da variável, ou "não se aplica" quando o trecho fala de outra coisa, usa a palavra em outro sentido ou é só índice, sumário ou título de seção. Pode comentar qualquer trecho.</p>
<p>A trilha no alto da tela mostra as dez etapas com a conta de trechos julgados em cada uma. Pode clicar em qualquer etapa, na ordem que preferir; o serviço só fica concluído quando as dez estiverem confirmadas.</p>
<p>A <b>resposta da variável é calculada das suas notas</b>, pela regra do codebook: o nível mais alto na V1, a união nas de múltipla escolha, o degrau mais alto na V5, qualquer trecho nas de Sim/Não, os tipos dos documentos na V9. A caixa "Resposta calculada" mostra o resultado. Se discordar do cálculo, "corrigir à mão" abre os campos. Há um comentário por variável. Quando estiver satisfeito, <b>Confirmar e seguir</b>.</p>
<p>Em cada tela há o botão <b>ver sugestão do copiloto</b>. Ele mostra o que um modelo de linguagem daria de nota a cada trecho, e <b>aplicar sugestão</b> preenche só os trechos que você ainda não julgou. A decisão é sua. O copiloto só viu o texto congelado, e o prompt dele está publicado, no link dentro da própria caixa.</p>
<p>Pode parar a qualquer momento e fechar a página. Quando voltar, ela abre onde você parou. O botão <b>Voltar</b> deixa rever o que já confirmou.</p>

<h2>Duas regras que afetam o resultado</h2>
<p><b>Leia sempre o texto congelado, nunca a página ao vivo.</b> As plataformas reescrevem as políticas sem avisar. Se os dois codificadores lerem versões diferentes, a discordância fica indistinguível de mudança no documento.</p>
<p><b>Confira a confirmação ao lado do botão.</b> Cada nota é gravada num servidor. Verde, "gravado às", significa que chegou. Vermelho significa que não chegou e que a página vai tentar de novo sozinha; se ficar vermelho, pare e avise. Não deixe o mesmo serviço aberto em duas janelas ao mesmo tempo.</p>
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
  const proximo = proximoServicoPorConfirmacao(cb, E.records, null);
  const itens = cb.servicos.map((s) => {
    const p = progressoConfirmado(cb, E.records[s] || {});
    const estado = p.feitas === p.total ? `<span class="estado feito">concluído</span>`
      : p.feitas === 0 ? `<span class="estado">não iniciado</span>` : `<span class="estado">${p.feitas} de ${p.total} etapas</span>`;
    return `<li><a href="#" data-servico="${esc(s)}">${esc(s)}</a>${estado}</li>`;
  }).join("");
  const feitos = cb.servicos.filter((s) => concluidoConfirmado(cb, E.records[s] || {})).length;
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
  let d;
  try {
    d = await dadosDoServico(nome);
  } catch (e) {
    telaErro(`${nome}: ${e.message}`);
    return;
  }
  E.servico = nome;
  // Serviço concluído abre no resumo; os outros, na primeira etapa aberta.
  E.i = concluidoConfirmado(E.codebook, registro(nome)) ? etapas(E.codebook).length : primeiraEtapaIncompleta(E.codebook, registro(nome), d);
  E.copilotoAberto = false;
  E.corrigindo = false;
  E.avisoConflito = false;
  render();
}

function render(manterScroll = false) {
  if (!E.servico) { telaContinuar(); return; }
  const lista = etapas(E.codebook);
  if (E.i >= lista.length) return renderResumo();
  const etapa = lista[E.i];
  if (etapa === "KW") return renderKW();
  return renderVariavel(etapa, manterScroll);
}

// ---------------------------------------------------------------- cabeçalho

const rotuloEtapa = (e) => e;

// Tipo e registro de um documento: metadado do corpus (d.docs), nunca do codificador.
const rotuloTipo = (cb, valor) => ((cb.tipos_doc || []).find((t) => t.valor === valor) || {}).rotulo || valor || "";
const rotuloTipoCurto = (cb, valor) => rotuloTipo(cb, valor).replace(/\s*\(.*\)$/, "");
const registroDoDoc = (cb, doc) => (doc && doc.tipo && (doc.registro || registroPadrao(cb, doc.tipo))) || null;

function cabecalhoServico(d) {
  const cb = E.codebook;
  const reg = registro(E.servico);
  const lista = etapas(cb);
  const f = fechadas(cb, reg, d);
  const p = progressoEtapas(cb, reg, d);
  const tudo = p.feitas === p.total;
  // Contagens por etapa (trechos julgados / total) para a trilha e a linha de cima.
  const n = derivar(cb, reg, d).n;
  const atual = lista[E.i];
  // Toda etapa é clicável, em qualquer ordem: a trava é da confirmação, não da
  // navegação. Só o resumo espera as dez confirmadas.
  const trilha = lista.map((e, k) => {
    const cls = k === E.i ? "atual" : f[e] ? "fechado" : "aberto";
    const c = n[e];
    const conta = c ? `<small>${c.julgados}/${c.total}</small>` : "";
    return `<button class="${cls}" data-passo="${k}" title="${c ? `${c.julgados} de ${c.total} trechos julgados` : "log de palavras-chave"}">${esc(rotuloEtapa(e))}${conta}</button>`;
  }).join("") + `<button class="${E.i >= lista.length ? "atual" : tudo ? "fechado" : "futuro"}" data-passo="${lista.length}" ${tudo ? "" : "disabled"} title="${tudo ? "" : "abre quando as dez etapas estiverem confirmadas"}">resumo</button>`;
  const contaAtual = atual && n[atual] ? ` · ${esc(atual)}: ${n[atual].julgados} de ${n[atual].total} trechos julgados` : "";
  return `<div class="cabecalho">
    <div class="linha1"><h1>${esc(E.servico)}</h1>
      <span class="suave">${p.feitas} de ${p.total} etapas confirmadas${contaAtual}</span>
      <span class="recibo"></span></div>
    <div class="trilha">${trilha}</div>
    <p class="pequeno suave" style="margin:6px 0 0"><a href="#" id="voltar-lista">todos os serviços</a> · <a href="#" id="regras">cinco regras gerais</a> · <a href="/assistente/copiloto.html" target="_blank" rel="noopener">como o copiloto funciona</a></p>
  </div>`;
}

function ligarCabecalho(d) {
  for (const b of app.querySelectorAll(".trilha button[data-passo]")) {
    b.onclick = () => { if (!b.disabled) { E.i = Number(b.dataset.passo); E.copilotoAberto = false; E.corrigindo = false; render(); } };
  }
  for (const b of app.querySelectorAll("button[data-abrir]")) {
    b.onclick = () => abrirDocumento(b.dataset.abrir, b.dataset.trecho || null, d);
  }
  const vl = document.getElementById("voltar-lista");
  if (vl) vl.onclick = (ev) => { ev.preventDefault(); salvar(E.servico); E.servico = null; telaContinuar(); };
  const rg = document.getElementById("regras");
  if (rg) rg.onclick = (ev) => { ev.preventDefault(); abrirRegras(); };
}

function rodape() {
  return `<footer class="rodape">Texto congelado em ${esc(E.indice.frozen_at ? E.indice.frozen_at.slice(0, 10) : "")} · critério congelado em ${esc(E.codebook.congelado_em)}</footer>`;
}

function blocoNotasGerais(reg) {
  return `<div class="caixa papel" style="margin-top:28px">
      <label class="rotulo" for="notas"><b>Notas sobre este serviço</b> <span class="suave pequeno">dúvidas de regra, casos de fronteira, diferenças entre documentos</span></label>
      <textarea id="notas" style="width:100%;min-height:70px;margin-top:6px;font:inherit;padding:8px 10px;border:1px solid var(--linha);border-radius:8px">${esc(reg.notes || "")}</textarea>
    </div>`;
}

function ligarNotasGerais(reg) {
  const notas = document.getElementById("notas");
  if (notas) notas.addEventListener("input", () => { reg.notes = notas.value; marcarEdicao(E.servico); });
}

function mostrarFalta(pend, etapa, d) {
  const caixa = document.getElementById("falta");
  if (!caixa) return;
  const nomes = pend.map(([chave, motivo]) => {
    if (chave === "trechos") {
      // Quais trechos, pelo número da tela, com link que rola até cada um.
      const reg = registro(E.servico);
      const semNota = d ? trechosDaVariavel(etapa, d, reg)
        .map((t, k) => ({ t, num: k + 1 }))
        .filter(({ t }) => t.origem !== "v1" && ((reg.notas[etapa] || {})[t.id] || {}).nota === undefined)
        .map(({ num }) => num) : [];
      const quais = semNota.length ? ` Sem nota: ${semNota.map((n) => `<a href="#" data-ir="${n}">${n}</a>`).join(", ")}.` : "";
      return `<li><b>Trechos:</b> ${esc(motivo)}.${quais} Dê uma nota a cada um, ou use "marcar os restantes como não se aplica".</li>`;
    }
    if (chave === "confirmar") return `<li>${esc(motivo)}: clique de novo em Confirmar.</li>`;
    if (chave === "keyword_log") return `<li><b>Log de palavras-chave:</b> não pode ficar vazio.</li>`;
    const v = E.codebook.variaveis.find((x) => x.vid === etapa);
    const c = v && v.campos.find((x) => x.chave === chave);
    if (c) return `<li><b>${esc(c.rotulo)}:</b> falta ${esc(motivo)}</li>`;
    return `<li><b>${esc(chave)}:</b> ${esc(motivo)}</li>`;
  }).join("");
  caixa.innerHTML = `<div class="falta">Para seguir, falta:<ul style="margin:6px 0 0">${nomes}</ul></div>`;
  // Rolagem instantânea: a suave não roda em aba oculta nem com movimento reduzido.
  for (const a of caixa.querySelectorAll("a[data-ir]")) {
    a.onclick = (ev) => {
      ev.preventDefault();
      const alvo = document.getElementById(`trecho-${a.dataset.ir}`);
      if (alvo) alvo.scrollIntoView({ block: "center" });
    };
  }
  caixa.scrollIntoView({ block: "center" });
}

function confirmarEtapa(etapa, d) {
  const reg = registro(E.servico);
  let pend = faltandoEtapa(E.codebook, etapa, reg, d);
  // Variável sem trechos: o primeiro clique confirma a ausência.
  if (pend.length === 1 && pend[0][0] === "confirmar") {
    reg.confirmadas[etapa] = true;
    pend = faltandoEtapa(E.codebook, etapa, reg, d);
  }
  if (pend.length) { mostrarFalta(pend, etapa, d); return; }
  reg.confirmadas[etapa] = true;
  marcarEdicao(E.servico);
  E.i += 1;
  E.copilotoAberto = false;
  E.corrigindo = false;
  E.avisoConflito = false;
  render();
}

function voltarEtapa() {
  salvar(E.servico);
  E.i -= 1;
  E.copilotoAberto = false;
  E.corrigindo = false;
  E.avisoConflito = false;
  render();
}

// ------------------------------------------------------------ tela da variável

// `tela` é o rótulo escrito para o codificador; `rotulo` é o que o copiloto recebeu.
function rotuloNota(spec, valor) {
  if (valor === NAO_E_ISSO) return "não se aplica";
  const o = (spec.opcoes || []).find((x) => x.valor === valor);
  return o ? (o.tela || o.rotulo) : String(valor);
}

// Os valores do codebook são em inglês e estão congelados. A tela mostra o
// rótulo em português e o valor original ao lado, para o registro continuar
// rastreável: "interesse legítimo (legitimate interest)".
const ROTULO_VALOR = { Yes: "Sim", No: "Não", binding: "vinculante", "non-binding": "não vinculante", both: "nos dois registros",
  none: "nenhum", "not stated": "não declarada", "not-verifiable (vantage)": "não verificável" };
function rotuloValor(vid, chave, valor) {
  const cb = E.codebook;
  const spec = (cb.notas || {})[vid];
  const o = spec && (spec.opcoes || []).find((x) => x.valor === String(valor) && (!x.campo || x.campo === chave));
  if (o) return { texto: o.tela || o.rotulo, deNota: true };
  if ((cb.tipos_doc || []).some((t) => t.valor === valor)) return { texto: rotuloTipoCurto(cb, valor), deNota: false };
  return { texto: ROTULO_VALOR[valor] || String(valor), deNota: false };
}

function legivel(vid, c, valor) {
  const um = (x) => {
    const { texto, deNota } = rotuloValor(vid, c.chave, x);
    const ajuda = deNota ? "" : (E.codebook.ajuda_valores || {})[`${c.chave}:${x}`] || "";
    return `<b>${esc(texto)}</b>${texto !== String(x) ? ` <span class="suave">(${esc(x)})</span>` : ""}${ajuda ? ` <span class="suave">${esc(ajuda)}</span>` : ""}`;
  };
  if (Array.isArray(valor)) return valor.length ? valor.map(um).join("<br>") : "(nenhum)";
  if (valor === "" || valor == null) return "(vazio)";
  return um(valor);
}

function controleHtml(vid, c, valor, prefixo) {
  // Rádios ou caixas para um campo, com `prefixo` no name para não colidir.
  const marcados = new Set(Array.isArray(valor) ? valor : valor ? [valor] : []);
  if (c.tipo === "select" || c.tipo === "checks") {
    const tipo = c.tipo === "select" ? "radio" : "checkbox";
    return `<div class="opcoes compacto">${c.opcoes.filter((o) => o !== "").map((o) => {
      const { texto, deNota } = rotuloValor(vid, c.chave, o);
      const av = deNota ? "" : (E.codebook.ajuda_valores || {})[`${c.chave}:${o}`] || "";
      return `<label class="${marcados.has(o) ? "marcado" : ""}"><input type="${tipo}" name="${prefixo}${esc(c.chave)}" value="${esc(o)}" ${marcados.has(o) ? "checked" : ""}><b>${esc(texto)}</b>${texto !== o ? ` <span class="suave">(${esc(o)})</span>` : ""}${av ? ` <span class="suave">${esc(av)}</span>` : ""}</label>`;
    }).join("")}</div>`;
  }
  return `<input type="text" name="${prefixo}${esc(c.chave)}" value="${esc(valor || "")}" placeholder="${esc(c.placeholder || "")}">`;
}

function caixaCalculo(v, reg, d) {
  const cb = E.codebook;
  const x = derivar(cb, reg, d);
  const extras = new Set((cb.extras || {})[v.vid] || []);
  const n = x.n[v.vid] || { relevantes: 0, julgados: 0, total: 0 };
  const temOverride = v.campos.some((c) => c.chave in reg.override);
  const linhas = v.campos.filter((c) => c.tipo !== "text").map((c) => {
    const rotulo = c.tela || c.rotulo;
    const origem = x.origem[c.chave];
    if (origem === "fixo") {
      // Resposta que o 2º codificador não tem como dar (core.mjs: FIXOS). Só o
      // rótulo e o valor: a ajuda do codebook fala de "sua vantagem", e aqui não há.
      const fixo = x.campos[c.chave];
      return `<div class="calc-linha"><span class="rotulo">${esc(rotulo)}</span><span class="tag">fixo</span>
        <span class="valor"><b>${esc(rotuloValor(v.vid, c.chave, fixo).texto)}</b> <span class="suave">(${esc(fixo)})</span></span>
        ${c.ajuda_tela ? `<div class="ajuda pequeno suave" style="flex-basis:100%;margin:0">${esc(c.ajuda_tela)}</div>` : ""}</div>`;
    }
    if (extras.has(c.chave)) {
      return `<div class="calc-linha"><span class="rotulo">${esc(rotulo)}</span><span class="tag">responda</span>
        ${c.ajuda_tela ? `<div class="ajuda pequeno suave" style="flex-basis:100%;margin:0">${esc(c.ajuda_tela)}</div>` : ""}${controleHtml(v.vid, c, reg.extras[c.chave], "extra-")}</div>`;
    }
    const tag = origem === "corrigido" ? `<span class="tag corrigido">corrigida à mão</span>`
      : `<span class="tag">calculada de ${n.relevantes} trecho${n.relevantes === 1 ? "" : "s"}</span>`;
    const valorHtml = E.corrigindo ? controleHtml(v.vid, c, x.campos[c.chave], "override-") : `<span class="valor">${legivel(v.vid, c, x.campos[c.chave])}</span>`;
    return `<div class="calc-linha"><span class="rotulo">${esc(rotulo)}</span>${tag}${valorHtml}</div>`;
  }).join("");
  return `<div class="calculo" id="calculo">
    <div class="calc-titulo"><b>Resposta calculada</b> <span class="suave pequeno">${n.julgados} de ${n.total} trechos julgados · ${n.relevantes} relevante${n.relevantes === 1 ? "" : "s"}</span></div>
    ${linhas}
    <div class="botoes" style="margin:8px 0 0">
      ${E.corrigindo ? `<button class="pequeno" id="fechar-correcao">fechar a correção</button>` : `<button class="pequeno" id="corrigir">corrigir à mão</button>`}
      ${temOverride ? `<button class="pequeno" id="voltar-calculo">voltar ao cálculo</button>` : ""}
    </div>
    <details class="pequeno" style="margin-top:8px"><summary class="suave" style="cursor:pointer">evidência que será gravada</summary><pre class="evidencia">${esc(x.evidencias[v.vid] || "")}</pre></details>
  </div>`;
}

function renderVariavel(vid, manterScroll) {
  const cb = E.codebook;
  const v = cb.variaveis.find((x) => x.vid === vid);
  const d = E.cache.get(E.servico);
  const reg = registro(E.servico);
  const spec = (cb.notas || {})[vid] || { modo: "um", opcoes: [] };
  const trechos = trechosDaVariavel(vid, d, reg);
  const notasVid = reg.notas[vid] || {};
  const sug = d.copiloto && d.copiloto.variaveis ? d.copiloto.variaveis[vid] : null;
  const julgados = trechos.filter((t) => t.origem === "v1" || notasVid[t.id] !== undefined).length;

  // Quantos trechos de cada palavra, por documento, estão na tela: o piso mostra
  // no máximo 3 por palavra por documento, e o codificador precisa saber quando
  // há ocorrências que ele não está vendo.
  // O piso traz as primeiras ocorrências de cada palavra em cada documento, em
  // ordem de texto (revisao.piso, TETO_POR_TERMO_DOC): "ocorrência k de N".
  const naTela = {};
  const ordinal = new Map();
  for (const t of trechos) {
    if (t.origem !== "piso") continue;
    const chave = `${t.file}\n${t.termo}`;
    naTela[chave] = (naTela[chave] || 0) + 1;
    ordinal.set(t.id, naTela[chave]);
  }
  const contagem = (t) => {
    const total = Number(t.total_no_doc) || 0;
    const aqui = naTela[`${t.file}\n${t.termo}`] || 0;
    const k = ordinal.get(t.id) || 1;
    if (total <= 1) return "única ocorrência neste documento";
    if (total <= aqui) return `ocorrência ${k} de ${total} neste documento`;
    return `ocorrência ${k} de ${total} neste documento · só as ${aqui} primeiras estão na página; para as outras, abra o documento e use a busca do navegador`;
  };
  // Numeração estável: a ordem de trechosDaVariavel sobre dados congelados.
  const itens = trechos.map((t, k) => {
    const num = k + 1;
    const n = notasVid[t.id];
    const nota = n !== undefined ? n.nota : (t.origem === "v1" ? "sim" : undefined);
    const marcados = new Set(nota === undefined ? [] : [].concat(nota));
    const doc = d.docs.find((x) => x.n === t.doc) || {};
    const titulo = doc.titulo || "";
    const tipo = rotuloTipoCurto(cb, doc.tipo);
    const origem = t.origem === "piso" ? `<span class="origem">palavra-chave <b>${esc(t.termo)}</b> · ${esc(contagem(t))}</span>`
      : t.origem === "modelo" ? `<span class="origem">localizado pelo modelo</span>`
      : `<span class="origem">herdado da V1 <b>(nível ${esc(t.notaV1)})</b></span>`;
    const botoes = (spec.opcoes || []).map((o) => `<button class="nota ${marcados.has(o.valor) ? "marcado" : ""}" data-id="${esc(t.id)}" data-nota="${esc(o.valor)}">${esc(o.tela || o.rotulo)}</button>`).join("")
      + `<button class="nota x ${nota === NAO_E_ISSO ? "marcado" : ""}" data-id="${esc(t.id)}" data-nota="${NAO_E_ISSO}">não se aplica</button>`
      + `<button class="pequeno comentar" data-com="${esc(t.id)}">${n && n.com ? "comentário ✎" : "comentar"}</button>`;
    const sugerida = E.copilotoAberto && sug && sug.notas && sug.notas[t.id] !== undefined
      ? `<span class="sug">copiloto: ${esc([].concat(sug.notas[t.id]).map((x) => rotuloNota(spec, x)).join(", "))}</span>` : "";
    return `<div class="item ${t.origem} ${nota === undefined ? "" : nota === NAO_E_ISSO ? "descartado" : "relevante"}" data-item="${esc(t.id)}" id="trecho-${num}">
      <h3 class="num">Trecho ${num}</h3>
      <div class="meta">${origem}${t.flag ? `<div class="flag">⚠ ${esc(t.flag)}</div>` : ""}</div>
      <div class="texto">${esc(t.verbatim)}</div>
      <div class="onde">Documento ${t.doc}${titulo ? `: ${esc(titulo)}` : ""}${tipo ? ` · ${esc(tipo)}` : ""}${t.onde ? ` · ${esc(t.onde)}` : ""}
        <button class="pequeno" data-abrir="${esc(t.file)}" data-trecho="${esc(t.verbatim)}">abrir no documento</button></div>
      <div class="notas">${botoes} ${sugerida}</div>
      <div class="com ${n && n.com ? "" : "oculto"}"><input type="text" data-com-input="${esc(t.id)}" value="${esc(n && n.com ? n.com : "")}" placeholder="comentário curto sobre este trecho"></div>
    </div>`;
  }).join("");

  const copilotoHtml = sug ? `<div class="botoes" style="margin:6px 0">
      <button class="copiloto" id="ver-copiloto">${E.copilotoAberto ? "esconder sugestão" : "ver sugestão do copiloto"}</button>
      ${E.copilotoAberto ? `<button class="copiloto" id="aplicar">aplicar sugestão nos trechos sem nota</button>` : ""}
    </div>${E.copilotoAberto ? `<div class="sugestao"><b>Copiloto</b> ${esc(sug.razao || "")}
      ${Object.keys(sug.extras || {}).length ? `<div class="pequeno">Perguntas avulsas sugeridas: ${Object.entries(sug.extras).map(([k, val]) => `${esc(k)} = ${esc(val || "(vazio)")}`).join(" · ")}</div>` : ""}
      <div class="pequeno"><a href="/assistente/copiloto.html" target="_blank" rel="noopener">como o copiloto funciona</a></div></div>` : ""}`
    : `<p class="pequeno suave">O copiloto não tem sugestão para esta variável.</p>`;

  mostrar(`${cabecalhoServico(d)}
    <div class="pergunta">[${esc(vid)}] ${esc(v.pergunta || v.titulo)}</div>
    <p class="lembrete">${esc(v.lembrete)} <a href="#" id="criterio">critério completo</a></p>
    ${E.avisoConflito ? `<div class="aviso">Este serviço foi alterado em outra janela. Recarreguei as respostas; confira e continue.</div>` : ""}
    ${copilotoHtml}
    <div class="evid">
      <h3>Trechos <span class="suave pequeno" id="contador">${julgados} de ${trechos.length} julgados</span></h3>
      <p class="pequeno suave">Para cada trecho, escolha a opção que diz o que ele mostra para esta pergunta. Marque <b>"não se aplica"</b> quando o trecho não serve de evidência. Três casos: a palavra está em outro sentido (Exemplo: testar a segurança do sistema, período grátis de teste); o assunto é outro; o trecho é índice, sumário, título de seção ou menu, sem a frase que afirma a coisa. Nesse último caso a frase costuma aparecer como outro trecho, logo abaixo. Na dúvida, "abrir no documento" mostra o entorno.</p>
      ${trechos.length ? itens : `<p class="suave">Nenhum trecho localizado para esta variável, nem pela busca por palavra-chave nem pelo modelo. Se concordar com a ausência, confirme.</p>`}
      ${julgados < trechos.length ? `<div class="botoes"><button class="secundario" id="restantes">marcar os ${trechos.length - julgados} restantes como "não se aplica"</button></div>` : ""}
    </div>
    ${caixaCalculo(v, reg, d)}
    <div class="campo"><label class="rotulo" for="comentario"><b>Comentário sobre esta variável</b> <span class="suave pequeno">opcional; entra na evidência gravada</span></label>
      <textarea id="comentario">${esc(reg.comentarios[vid] || "")}</textarea></div>
    <div id="falta"></div>
    <div class="botoes">
      ${E.i > 0 ? `<button class="secundario" id="voltar">Voltar</button>` : ""}
      <button class="primario" id="confirmar">Confirmar e seguir</button>
      <span class="recibo"></span>
    </div>
    ${blocoNotasGerais(reg)}
    ${rodape()}`, manterScroll);

  ligarCabecalho(d);
  pintarRecibos();
  ligarNotasGerais(reg);
  document.getElementById("criterio").onclick = (ev) => { ev.preventDefault(); abrirCriterio(v); };

  const definirNota = (id, valor) => {
    reg.notas[vid] ||= {};
    const atual = reg.notas[vid][id] || {};
    let nova;
    if (valor === NAO_E_ISSO) nova = NAO_E_ISSO;
    else if (spec.modo === "varios") {
      const lista = Array.isArray(atual.nota) ? [...atual.nota] : [];
      const k = lista.indexOf(valor);
      if (k >= 0) lista.splice(k, 1); else lista.push(valor);
      nova = lista.length ? lista : undefined;
    } else nova = atual.nota === valor ? undefined : valor;
    if (nova === undefined) {
      if (atual.com) reg.notas[vid][id] = { com: atual.com }; else delete reg.notas[vid][id];
      if (reg.notas[vid][id] && reg.notas[vid][id].nota === undefined && !reg.notas[vid][id].com) delete reg.notas[vid][id];
    } else {
      reg.notas[vid][id] = { ...atual, nota: nova };
    }
    editar(vid);
    renderVariavel(vid, true);
  };
  for (const b of app.querySelectorAll("button.nota[data-id]")) b.onclick = () => definirNota(b.dataset.id, b.dataset.nota);
  for (const b of app.querySelectorAll("button[data-com]")) {
    b.onclick = () => { const caixa = app.querySelector(`.item[data-item="${CSS.escape(b.dataset.com)}"] .com`); caixa.classList.toggle("oculto"); if (!caixa.classList.contains("oculto")) caixa.querySelector("input").focus(); };
  }
  for (const inp of app.querySelectorAll("input[data-com-input]")) {
    inp.addEventListener("input", () => {
      const id = inp.dataset.comInput;
      reg.notas[vid] ||= {};
      reg.notas[vid][id] = { ...(reg.notas[vid][id] || {}), com: inp.value };
      if (!inp.value && reg.notas[vid][id].nota === undefined) delete reg.notas[vid][id];
      marcarEdicao(E.servico);
    });
    inp.addEventListener("change", () => atualizarCalculo(v, reg, d));
  }
  const rest = document.getElementById("restantes");
  if (rest) rest.onclick = () => {
    reg.notas[vid] ||= {};
    for (const t of trechos) if (t.origem !== "v1" && (reg.notas[vid][t.id] || {}).nota === undefined) reg.notas[vid][t.id] = { ...(reg.notas[vid][t.id] || {}), nota: NAO_E_ISSO };
    editar(vid);
    renderVariavel(vid, true);
  };
  const ver = document.getElementById("ver-copiloto");
  if (ver) ver.onclick = () => { E.copilotoAberto = !E.copilotoAberto; renderVariavel(vid, true); };
  const ap = document.getElementById("aplicar");
  if (ap) ap.onclick = () => {
    E.records[E.servico] = aplicarNotas(reg, vid, sug, trechos);
    editar(vid);
    renderVariavel(vid, true);
  };
  ligarCalculo(v, reg, d);
  const com = document.getElementById("comentario");
  com.addEventListener("input", () => { reg.comentarios[vid] = com.value; marcarEdicao(E.servico); });
  com.addEventListener("change", () => atualizarCalculo(v, reg, d));
  const btnVoltar = document.getElementById("voltar");
  if (btnVoltar) btnVoltar.onclick = voltarEtapa;
  document.getElementById("confirmar").onclick = () => confirmarEtapa(vid, d);
}

function atualizarCalculo(v, reg, d) {
  const antigo = document.getElementById("calculo");
  if (!antigo) return;
  antigo.replaceWith(el(caixaCalculo(v, reg, d)));
  ligarCalculo(v, reg, d);
}

function ligarCalculo(v, reg, d) {
  const cb = E.codebook;
  const extras = new Set((cb.extras || {})[v.vid] || []);
  const corr = document.getElementById("corrigir");
  if (corr) corr.onclick = () => { E.corrigindo = true; atualizarCalculo(v, reg, d); };
  const fechar = document.getElementById("fechar-correcao");
  if (fechar) fechar.onclick = () => { E.corrigindo = false; atualizarCalculo(v, reg, d); };
  const vc = document.getElementById("voltar-calculo");
  if (vc) vc.onclick = () => { for (const c of v.campos) delete reg.override[c.chave]; E.corrigindo = false; editar(v.vid); atualizarCalculo(v, reg, d); };
  const ler = (c, prefixo) => {
    if (c.tipo === "select") { const m = document.querySelector(`#calculo input[name="${prefixo}${CSS.escape(c.chave)}"]:checked`); return m ? m.value : ""; }
    if (c.tipo === "checks") return [...document.querySelectorAll(`#calculo input[name="${prefixo}${CSS.escape(c.chave)}"]:checked`)].map((x) => x.value);
    const i = document.querySelector(`#calculo input[name="${prefixo}${CSS.escape(c.chave)}"]`); return i ? i.value : "";
  };
  for (const c of v.campos) {
    if (c.tipo === "text") continue;
    const prefixo = extras.has(c.chave) ? "extra-" : "override-";
    for (const inp of document.querySelectorAll(`#calculo [name="${prefixo}${CSS.escape(c.chave)}"]`)) {
      const aplicar = (rerender) => {
        const valor = ler(c, prefixo);
        if (extras.has(c.chave)) reg.extras[c.chave] = valor; else reg.override[c.chave] = valor;
        editar(v.vid);
        if (rerender) atualizarCalculo(v, reg, d);
      };
      if (inp.type === "text") { inp.addEventListener("input", () => aplicar(false)); inp.addEventListener("change", () => aplicar(true)); }
      else inp.addEventListener("change", () => aplicar(true));
    }
  }
}

// ---------------------------------------------------------- palavras-chave

function renderKW() {
  const cb = E.codebook;
  const v = cb.variaveis.find((x) => x.vid === "KW");
  const d = E.cache.get(E.servico);
  const reg = registro(E.servico);
  if (!reg.keyword_log) { reg.keyword_log = logSugerido(d.piso); sincronizar(E.servico); }
  mostrar(`${cabecalhoServico(d)}
    <div class="pergunta">[KW] ${esc(v.pergunta || v.titulo)}</div>
    <p class="lembrete">${esc(v.lembrete)} <a href="#" id="criterio">critério completo</a></p>
    <p class="suave">O log já vem preenchido com as contagens automáticas, documento por documento. Corrija o que for falso positivo. O que ficar aqui é o registro do que você procurou.</p>
    <div class="campo"><label class="rotulo" for="f-keyword_log">${esc(v.campos[0].rotulo)}</label>
      <textarea id="f-keyword_log" style="min-height:160px">${esc(reg.keyword_log || "")}</textarea></div>
    <div id="falta"></div>
    <div class="botoes"><button class="secundario" id="voltar">Voltar</button><button class="primario" id="confirmar">Confirmar e seguir</button><span class="recibo"></span></div>
    ${blocoNotasGerais(reg)}
    ${rodape()}`);
  ligarCabecalho(d);
  pintarRecibos();
  ligarNotasGerais(reg);
  document.getElementById("criterio").onclick = (ev) => { ev.preventDefault(); abrirCriterio(v); };
  const ta = document.getElementById("f-keyword_log");
  ta.addEventListener("input", () => { reg.keyword_log = ta.value; editar("KW"); });
  document.getElementById("voltar").onclick = voltarEtapa;
  document.getElementById("confirmar").onclick = () => confirmarEtapa("KW", d);
}

// ------------------------------------------------------------------- resumo

function renderResumo() {
  const cb = E.codebook;
  const d = E.cache.get(E.servico);
  const reg = registro(E.servico);
  const x = derivar(cb, reg, d);
  const docs = d.docs.map((doc) => `<div><span class="suave">${doc.n}.</span> ${esc(doc.titulo || doc.file)}: <b>${esc(rotuloTipo(cb, doc.tipo) || "(sem tipo)")}</b>${registroDoDoc(cb, doc) ? ` · ${registroDoDoc(cb, doc) === "binding" ? "vinculante" : "não vinculante"}` : ""}</div>`).join("");
  const linhas = cb.variaveis.map((v) => {
    const valores = v.campos.filter((c) => c.tipo !== "text").map((c) => {
      const val = x.campos[c.chave];
      const t = Array.isArray(val) ? val.join(", ") : (val || "");
      const tag = x.origem[c.chave] === "corrigido" ? ` <span class="tag corrigido">corrigida à mão</span>` : "";
      return `<div><span class="suave">${esc(c.rotulo)}:</span> <b>${esc(t || "(vazio)")}</b>${tag}</div>`;
    }).join("");
    const n = x.n[v.vid];
    const texto = v.campos.find((c) => c.tipo === "text");
    const ev = texto ? (x.campos[texto.chave] || "").trim() : "";
    return `<tr><th>[${esc(v.vid)}] ${esc(v.titulo)}${n ? `<div class="pequeno suave">${n.relevantes} de ${n.total} trechos relevantes</div>` : ""}</th>
      <td>${valores}${ev ? `<div class="pequeno suave">${esc(ev.length > 240 ? ev.slice(0, 239) + "…" : ev)}</div>` : ""}</td></tr>`;
  }).join("");
  const proximo = proximoServicoPorConfirmacao(cb, E.records, E.servico);
  mostrar(`${cabecalhoServico(d)}
    <h2>Resumo de ${esc(E.servico)}</h2>
    <p class="suave">As dez etapas estão confirmadas. Confira e siga para o próximo serviço, ou volte para rever.</p>
    <div class="caixa"><b>Documentos</b>${docs}</div>
    <div class="caixa resumo"><table>${linhas}</table></div>
    ${reg.notes ? `<div class="caixa papel"><b>Notas:</b> ${esc(reg.notes)}</div>` : ""}
    <div class="botoes">
      <button class="secundario" id="voltar">Voltar</button>
      <button class="primario" id="proximo" data-rotulo="${proximo ? `Próximo serviço: ${esc(proximo)}` : "Concluir"}">…</button>
      <span class="recibo"></span>
    </div>`);
  ligarCabecalho(d);
  pintarRecibos();
  document.getElementById("voltar").onclick = () => { E.i = etapas(cb).length - 1; render(); };
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
  const corpo = abrirPainel(esc(doc.titulo || file), `<p class="nota">Documento ${doc.n || ""}${doc.tipo ? ` · ${esc(rotuloTipoCurto(E.codebook, doc.tipo))}` : ""} · texto congelado ·<a href="${esc(url)}" target="_blank" rel="noopener">baixar o arquivo congelado</a></p><p class="nota">carregando…</p>`);
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
  corpo.innerHTML = `<p class="nota">Documento ${doc.n || ""}${doc.tipo ? ` · ${esc(rotuloTipoCurto(E.codebook, doc.tipo))}` : ""} · texto congelado ·<a href="${esc(url)}" target="_blank" rel="noopener">baixar o arquivo congelado</a>${trecho && !pos ? " · trecho não localizado automaticamente; use a busca do navegador" : ""}</p>`;
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
