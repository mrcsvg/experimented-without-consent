# Tipo de documento como metadado do corpus

Data: 05/10/2026 (decisão de 04/10 à noite). Marcus Garcia, depois de testar a
versão B no ensaio: "Tirar esse passo do caminho do Marcelo. O tipo de um
documento é atributo do corpus, não julgamento do codificador."

## O problema

A versão B abria cada serviço com um passo zero: o codificador dizia o tipo de
cada documento (política de privacidade, termos de uso, aviso de pesquisa
separado, central de ajuda, blog). Três respostas do codebook dependem disso: o
registro do teto na V1 (e a nota "nível do registro vinculante sozinho"), os
locais na V9 e o registro agregado na V9. O custo: 157 documentos, 6 por
serviço em média, 10 no máximo, um clique cada, antes da primeira pergunta de
verdade.

A etiqueta da captura (`role` em `md/index.json`) só existe para 55 dos 157
documentos, e só diz vinculante ou não; os cinco tipos que a V9 pede não
existiam por documento em lugar nenhum. O critério congelado diz que "registro
não é hospedagem" (o Privacy Notice da Amazon vive sob /help/ e é vinculante):
é um julgamento sobre o documento, feito uma vez.

## A decisão

O tipo (e, por ele, o registro) de cada documento é metadado do corpus,
decidido à mão uma única vez, compartilhado pelos dois codificadores. A página
não pergunta nada sobre documentos: abre cada serviço direto na V1 e mostra o
tipo ao lado de cada trecho, no resumo e no painel do documento. As três
respostas continuam calculadas, só que de um tipo fixo.

## O que mudou

- `analysis/tipos-doc.json`: fonte única, `{file: {tipo[, registro]}}` para os
  157 documentos, com os sinais que geraram o rascunho e a marca `conferir`.
- `analysis/tipos-doc.py`: `--rascunho` (URL e título, sugestão do copiloto,
  etiqueta da captura), `--tabela`, `--check`, `--self-test`. Regra do
  rascunho no docstring. Resultado em 05/10: 157 documentos, 16 a conferir;
  67 políticas de privacidade, 39 termos, 28 blog/imprensa/pesquisa, 22
  centrais de ajuda, 1 aviso de pesquisa separado.
- `analysis/exportar-piso.py`: cada documento do piso sai com `tipo` e
  `registro`; documento sem tipo interrompe a exportação; o self-test cobre
  cobertura exata do corpus, padrão do registro, recusa de tipo inválido.
- `assistente/core.mjs`: `derivar` lê o tipo de `d.docs`; `etapas` são as dez
  variáveis; sem `DOCS`, sem `aplicarTipos`; `docs_tipo` e `confirmadas.DOCS`
  de registros antigos são ignorados. Testes em `derivar.test.mjs`.
- `assistente/app.js`, `index.html`: o passo dos documentos saiu; abertura
  com dez etapas; tipo ao lado de cada trecho e no painel do documento.
- `analysis/exportar-codebook.py`: regra geral 2 (a evidência é montada dos
  trechos, não digitada) e 3 (o registro já vem decidido) reescritas.
- `assistente/copiloto.html`: diz que a sugestão de tipo do arquivo não é usada.
- `analysis/pre-entrega.py`: confere que a página não tem o passo e que o piso
  publicado traz tipo e registro; a ponte do κ monta o registro sem `docs_tipo`.

O copiloto não foi regenerado: os 26 arquivos e o prompt publicado continuam
os mesmos. A sugestão `documentos` que eles trazem serviu só de sinal para o
rascunho.

## Consequência para o κ e para o artigo

`v1_register`, `v9_register` e `v9_where` continuam no κ, mas passam a medir o
que importa: em que tipo de documento cada codificador viu o nível mais alto e
a divulgação, dado um tipo por documento que os dois compartilham. O parágrafo
de confiabilidade do artigo deve dizer isso: tipo e registro são metadados do
corpus, fixados antes da segunda codificação, não julgamentos independentes.

## Procedimento

1. `python3 analysis/tipos-doc.py --rascunho` (uma vez) e conferência humana
   das linhas marcadas; depois `conferido_em` no arquivo.
2. `python3 analysis/publicar-corpus.py --destino ../experimented-without-consent-corpus --so-assistente`
   e `--check`; push do corpus (publica).
3. `vercel deploy --prod --yes` no instrumento (Marcus).
4. `python3 analysis/pre-entrega.py` contra o que está no ar.

Pendente em 05/10: a conferência das 16 linhas marcadas (lista no chat) e o
carimbo `conferido_em`.
