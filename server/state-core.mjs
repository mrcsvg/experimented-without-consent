// Núcleo do /api/state, sem nada da Vercel: recebe env, fetch e relógio por
// parâmetro para o teste rodar com um GitHub de mentira. O que muda em relação
// ao servidor anterior (julho): chave obrigatória, gravação por serviço com
// controle de versão (_ts) e um segundo arquivo para o modo ensaio.
//
// POR QUE A CHAVE. O servidor de julho aceitava gravação de qualquer visitante
// e substituía o arquivo inteiro. O instrumento público em HTML gravava nele.
// Qualquer pessoa podia, sem querer, desfazer respostas do 2º codificador.
//
// POR QUE POR SERVIÇO. A página grava o registro do serviço que está aberto e
// manda junto o `_ts` que viu por último. Se o servidor tiver um mais novo
// (outra janela gravou), recusa com 409 e devolve o registro atual. A regra já
// existia no painel do notebook; agora quem a cumpre é o servidor.
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
  // relê e repete uma vez. `montar(atual)` devolve {dados, resposta, mensagem}
  // ou {recusa: {status, corpo}}.
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
