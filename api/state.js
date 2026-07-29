// Persistência do instrumento do 2º avaliador: proxy fino para o GitHub Contents API.
// O estado (JSON) vive versionado no branch `coder2-data` do repo do paper —
// cada PUT vira um commit, o que dá backup, sync entre dispositivos e uma
// trilha auditável de quando cada codificação mudou (útil pro replication package).
//
// Env (Vercel): GITHUB_TOKEN — fine-grained PAT com Contents R/W no repo ALVO (o do paper).
//               GH_REPO — OBRIGATÓRIO em produção: mrcsvg/ppgcd-ethics-in-digital-experimentation.
//                 Cuidado: o default no código abaixo é ESTE repo (público), que não tem o
//                 arquivo semeado — sem GH_REPO setado, o GET cai no fallback vazio (404).
// Opcionais:    GH_BRANCH (default coder2-data) · GH_PATH (default audit/coder2-progress.json)
//
// Sem autenticação de leitura/escrita própria: a URL do app é não-listada (noindex) e
// o alvo é um branch isolado, versionado — qualquer escrita indevida é revertível via git.

const REPO = process.env.GH_REPO || "mrcsvg/experimented-without-consent";
const BRANCH = process.env.GH_BRANCH || "coder2-data";
const PATH = process.env.GH_PATH || "audit/coder2-progress.json";
const API = `https://api.github.com/repos/${REPO}/contents/${PATH}`;

const gh = (url, opts = {}) =>
  fetch(url, {
    ...opts,
    headers: {
      authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "coder2-instrument",
      ...(opts.headers || {}),
    },
  });

async function current() {
  const r = await gh(`${API}?ref=${BRANCH}`);
  if (r.status === 404) return { sha: null, data: { records: {} } };
  if (!r.ok) throw new Error(`GitHub GET ${r.status}`);
  const j = await r.json();
  const text = Buffer.from(j.content, "base64").toString("utf8");
  return { sha: j.sha, data: JSON.parse(text) };
}

async function write(data, sha) {
  const body = {
    message: `coder2: autosave ${new Date().toISOString()}`,
    content: Buffer.from(JSON.stringify(data, null, 1)).toString("base64"),
    branch: BRANCH,
    ...(sha ? { sha } : {}),
  };
  return gh(API, { method: "PUT", body: JSON.stringify(body) });
}

export default async function handler(req, res) {
  if (!process.env.GITHUB_TOKEN)
    return res.status(503).json({ error: "GITHUB_TOKEN não configurado" });
  try {
    if (req.method === "GET") {
      const { data } = await current();
      return res.status(200).json(data);
    }
    if (req.method === "PUT") {
      const incoming =
        typeof req.body === "object" && req.body !== null
          ? req.body
          : JSON.parse(req.body || "{}");
      if (!incoming.records || typeof incoming.records !== "object")
        return res.status(400).json({ error: "esperado {records:{...}}" });
      const payload = { records: incoming.records, saved_at: new Date().toISOString() };
      let { sha } = await current();
      let r = await write(payload, sha);
      if (r.status === 409 || r.status === 422) {   // sha desatualizado: 1 retry
        ({ sha } = await current());
        r = await write(payload, sha);
      }
      if (!r.ok) throw new Error(`GitHub PUT ${r.status}`);
      return res.status(200).json({ ok: true });
    }
    res.setHeader("allow", "GET, PUT");
    return res.status(405).json({ error: "método não suportado" });
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e) });
  }
}
