# Notas por trecho: plano de implementação

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. TDD em toda função pura (`assistente/core.mjs`, exportadores, `copiloto.py`). Textos do codificador seguem `estilo-marcus`.

**Goal:** Trocar o campo de evidência digitado por uma nota por trecho, com resposta calculada do critério, correção à mão e comentário; passo de documentos; copiloto por trecho.

**Architecture:** As regras (opções de nota, tipos de documento, registro padrão) saem de `exportar-codebook.py` para `codebook.json`. O cálculo e a trava ficam em `core.mjs` (`derivar`, `faltandoEtapa`), testados em Node. `app.js` ganha o passo dos documentos, as linhas de nota e a caixa da resposta. `copiloto.py` passa ao formato 2 (nota por trecho, tipo por documento). Desenho: `docs/plans/2026-10-04-notas-por-trecho-design.md`.

**Produção não muda até o teste no navegador passar.** Ramo `assistente-codificacao` (PR #9 aberto).

---

## Tarefa 1: regras na fonte única (`exportar-codebook.py`)

Acrescentar a `codebook.json`:

```json
"tipos_doc": [
  {"valor": "privacy policy", "rotulo": "política de privacidade (inclui cookies e bases legais)", "registro": "binding"},
  {"valor": "ToS/conditions", "rotulo": "termos de uso", "registro": "binding"},
  {"valor": "research notice separado", "rotulo": "aviso de pesquisa separado", "registro": "non-binding"},
  {"valor": "help centre", "rotulo": "central de ajuda", "registro": "non-binding"},
  {"valor": "blog/PR/site de pesquisa", "rotulo": "blog, imprensa ou site de pesquisa", "registro": "non-binding"}
],
"notas": {
  "V1": {"modo": "um", "opcoes": [{"valor": "1", "rotulo": "1 · só melhorar"}, {"valor": "2", "rotulo": "2 · testar usuários"}, {"valor": "3", "rotulo": "3 · experimento / A/B"}]},
  "V2": {"modo": "varios", "opcoes": [{"valor": "service improvement", "rotulo": "melhoria do serviço"}, {"valor": "research", "rotulo": "pesquisa"}, {"valor": "human-subjects research", "rotulo": "pesquisa com humanos"}, {"valor": "social-good/community", "rotulo": "bem da comunidade"}]},
  "V3": {"modo": "varios", "opcoes": [{"valor": "activities", "rotulo": "nomeia atividades"}, {"valor": "specific", "rotulo": "experimento específico"}, {"valor": "pricing", "rotulo": "preço como alvo"}]},
  "V4": {"modo": "varios", "opcoes": [{"valor": "legitimate interest", "rotulo": "interesse legítimo"}, {"valor": "consent", "rotulo": "consentimento"}, {"valor": "contract", "rotulo": "contrato"}]},
  "V5": {"modo": "um", "opcoes": [{"valor": "GDPR-objection-only", "rotulo": "só objeção do GDPR"}, {"valor": "cookie/ads-only", "rotulo": "só cookies / anúncios"}, {"valor": "dedicated", "rotulo": "opt-out dedicado"}, {"valor": "opt-in", "rotulo": "opt-in"}]},
  "V6": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "programa beta / opt-in"}]},
  "V7": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "é debriefing"}]},
  "V8": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "revisão ética ou risco"}]},
  "V9": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "divulga experimentação aqui"}]}
},
"extras": {"V3": ["v3_targets"], "V4": ["v4_mapped_purpose", "v4_region_gated"], "V6": ["v6_which"]}
```

Self-test: os valores de V2, V4, V5 são exatamente as opções dos campos do codebook (menos `not stated` e `none`, que são a ausência); V1 cobre 1..3; `tipos_doc` cobre as cinco opções de `v9_where`; nenhum travessão. `fixtures-portao.py` passa a gravar `notas`, `tipos_doc` e `extras` no `portao.json`. Regenerar `codebook.json` e `portao.json`. Commit.

## Tarefa 2: cálculo e trava em `core.mjs`, com testes

API nova:

```js
export function idDoHit(hit)                                   // "h:" + sha-like de file+kwic (hash simples e estável, 8 hex)
export function trechosDaVariavel(vid, d, reg)                 // [{id, verbatim, doc, file, onde, origem: "piso"|"modelo"|"v1", flag?, termo?}]
export function registroPadrao(codebook, tipo)
export function derivar(codebook, reg, d)                      // -> {campos: {...flat}, evidencias: {V1: "texto"}, origem: {campo: "calculado"|"corrigido"|"extra"}, n: {V1: {julgados, total, relevantes}}}
export function faltandoEtapa(codebook, etapa, reg, d)         // etapa = "DOCS" | vid; devolve [[o que, motivo]]
export function etapas(codebook)                               // ["DOCS", ...vids]
export function progressoEtapas(codebook, reg, d)              // {feitas, total: 11}
export function primeiraEtapaIncompleta(codebook, reg, d)
export function aplicarNotas(reg, vid, sugestao)               // só nos trechos sem nota; devolve novo reg
export function textoDeEvidenciaNotas(vid, notasSpec, trechos, notas, comentario, docs)
```

Regras de `derivar` (uma função por variável, testada com casos à mão):
- V1: `v1_code` = max das notas (sem "x"); nenhum → "0". `v1_register` = registros dos documentos dos trechos no teto → binding | non-binding | both; `v1_code` 0 → "". Evidência inclui "Nível do registro vinculante sozinho: k" quando difere do teto.
- V2: união → lista na ordem das opções.
- V3: `v3_activities`/`v3_specific`/`v3_pricing` = Yes se algum trecho tiver a tag; `v3_targets` = extra.
- V4: união; vazio → ["not stated"]; `v4_mapped_purpose`, `v4_region_gated` = extras.
- V5: degrau mais alto na ordem GDPR-objection-only < cookie/ads-only < dedicated < opt-in; nenhum → "none".
- V6: Yes se algum "sim"; `v6_which` = extra. V7, V8: idem.
- V9: trechos = citações da V9 ∪ trechos da V1 com nota 1..3 (pré-marcados "sim", origem "v1"); `v9_where` = tipos dos documentos dos "sim" (ordem das opções); `v9_register` = binding | non-binding | both; sem "sim" → [] e "".
- `override[campo]` substitui o calculado; `origem[campo] = "corrigido"`.
- Textos de evidência: `vN_evidence` (V8: `v8_note`) montados de `textoDeEvidenciaNotas`; `keyword_log` e `notes` passam direto.

Trava `faltandoEtapa`:
- DOCS: documento sem tipo → `[file, "tipo do documento"]`.
- Vn: DOCS incompleto → `["DOCS", "documentos antes"]`; trecho sem nota → `["trechos", "k sem nota"]`; extras obrigatórios vazios (`v4_region_gated` sempre; `v6_which` quando Yes); sem trechos e sem `confirmadas[vid]` → `["confirmar", "sem trechos: confirme a ausência"]`.
- KW: `keyword_log` vazio.

Teste de compatibilidade: um registro completo derivado passa no `faltando` antigo (do `coding_flow`) para toda variável, exceto `v1_register` quando `v1_code` = "0".

## Tarefa 3: a página (`app.js`)

- Etapas: `["DOCS", ...]`; trilha mostra "Docs" primeiro.
- Tela DOCS: por documento: título, URL, "abrir texto congelado", botões de tipo (5), e, escolhido o tipo, o registro com botão para virar ("vinculante" / "não vinculante"). Copiloto: "ver sugestão" marca os tipos sugeridos; "aplicar" preenche os sem tipo.
- Tela da variável: lembrete + critério; lista de trechos com a linha de botões de nota (rótulos de `notas[vid]`), "não é isso", ícone de comentário (campo de uma linha); contador; botão "marcar os restantes como não é isso"; caixa "Resposta calculada" (campos e valores legíveis, "calculada de N trechos"; "corrigir à mão" abre os campos; "voltar ao cálculo" limpa o override); perguntas avulsas (extras) como campos; comentário da variável; Voltar / Confirmar; recibo.
- "ver sugestão do copiloto": etiqueta roxa por trecho com a nota sugerida e a resposta que sairia; "aplicar sugestão" → `aplicarNotas` + extras vazios.
- Resumo: campos calculados por variável, com "corrigida à mão" onde houver, e os totais de trechos julgados.
- Gravação: `derivar` roda a cada mudança e grava os campos planos junto com os estruturados.

## Tarefa 4: copiloto formato 2 (`copiloto.py`)

Mensagem: acrescenta a lista de trechos por variável com ids (`h:`/`c:`), e os documentos com número, título e URL. Pede: `documentos: [{n, tipo}]`, `variaveis: [{vid, notas: [{id, nota, valores}], extras: [{chave, valor}], razao}]`. Esquema compacto em lista. Validação: todo id existe; nota dentro das opções de `notas[vid]` ou "x"; `valores` só nas de modo "varios"; extras dentro das opções; tipo dentro de `tipos_doc`. `--simular`, `--estimar`, um serviço com leitura humana, depois os 26; `prompt.md` e `index.json` novos; `--check`. Publicar no corpus (`publicar-corpus.py --so-assistente`, manifesto) e conferir no ar.

## Tarefa 5: pré-entrega e testes no navegador

`pre-entrega.py`: copiloto formato 2 (notas por trecho, tipos de documento), `codebook.json` com `notas`/`tipos_doc`, ponte até o κ a partir de um registro derivado por `core.mjs` (rodar `node` para gerar o registro). Roteiro no navegador: passo dos documentos, V1 com notas e teto calculado, correção à mão, comentário, "marcar os restantes", V9 herdando da V1, resumo, recarga, conflito, zerar. Depois: commit, push, pedir o deploy.
