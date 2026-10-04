// Persistência do 2º codificador: proxy fino para a GitHub Contents API.
// Toda a lógica está em ../server/state-core.mjs, que roda em teste sem Vercel.
//
// Env (Vercel): GITHUB_TOKEN (PAT fine-grained, Contents R/W neste repo),
//               EWC_KEY (chave do link real), EWC_KEY_ENSAIO (chave do link de ensaio).
// Opcionais:    GH_REPO · GH_BRANCH (coder2-data) · GH_PATH (audit/coder2-progress.json)
//               · GH_PATH_ENSAIO (audit/ensaio-progress.json)
//
// Cada gravação vira um commit no ramo coder2-data: backup, sincronização
// entre máquinas e trilha de quando cada codificação mudou.
import { criarHandler } from "../server/state-core.mjs";

const handler = criarHandler({ env: process.env, fetchImpl: fetch });
export default handler;
