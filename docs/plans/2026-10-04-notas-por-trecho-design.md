# Notas por trecho: desenho (versão B)

Data: 04/10/2026. Decisão de Marcus Garcia depois de ver a página no ar: "o
codificador deveria poder atribuir uma nota a cada trecho; depois os trechos e
evidências devem ser unidos de forma automática, com possibilidade de
comentário". Entre a triagem (A) e o código por trecho (B), escolheu B.

## O que muda para o codificador

1. **Passo zero de cada serviço: os documentos.** Antes da V1, uma tela lista
   os documentos. Para cada um, o tipo: política de privacidade (inclui aviso de
   cookies e tabela de bases legais), termos de uso, aviso de pesquisa separado,
   central de ajuda, blog/imprensa/site de pesquisa. O registro (vinculante ou
   não) vem do tipo e pode ser virado à mão: "registro não é hospedagem".
2. **Uma nota por trecho, em cada variável.** Os trechos são os de hoje (busca
   por palavra-chave e citações do modelo). A nota segue o critério congelado:

   | variável | nota por trecho | resposta calculada |
   |---|---|---|
   | V1 | 1, 2, 3 (nível que o trecho mostra) | teto; registro = dos documentos onde o teto aparece |
   | V2 | enquadramentos presentes (vários) | união |
   | V3 | nomeia atividades · experimento específico · preço | Yes em cada um com trecho |
   | V4 | base legal declarada (várias) | união; vazio = not stated |
   | V5 | degrau mostrado | o mais alto da escada |
   | V6, V7, V8 | é isso | Yes se houver trecho |
   | V9 | divulga experimentação aqui | tipos dos documentos; registro agregado |

   Todo trecho tem "não é isso" e um comentário curto opcional. Embaixo da lista,
   "marcar os restantes como não é isso". Contador "n de N trechos julgados".
   Na V9 entram, já marcados, os trechos que receberam nível 1 a 3 na V1.
3. **Resposta calculada** numa caixa ("calculada de N trechos"), com "corrigir à
   mão" (abre os campos; a caixa passa a dizer "corrigida à mão") e um comentário
   por variável. Perguntas que não vêm de trecho continuam perguntas: V4 (tabela
   só na UE; finalidade mapeada), V6 (qual programa), V3 (alvos nomeados).
4. **A evidência não é digitada:** é a lista dos trechos marcados, com a nota e
   o comentário de cada um. Variável sem trecho relevante grava "nenhum dos N
   trechos sustenta outra resposta". Na V1, quando o teto do registro vinculante
   sozinho difere do teto, a diferença entra na evidência (o critério pede).
5. **Copiloto por trecho.** Rodada nova do modelo, mesmo material congelado,
   prompt novo publicado. "ver sugestão" mostra a nota sugerida ao lado de cada
   trecho e a resposta que sairia; "aplicar sugestão" preenche só o que ainda não
   tem nota. No passo dos documentos, sugere o tipo de cada um.
6. **Trava.** Documentos todos tipados antes da V1. Variável fecha com todos os
   trechos julgados e as perguntas avulsas respondidas; sem trecho, fecha com um
   clique de confirmação.

## O que fica gravado, por serviço

```
docs_tipo:   { arquivo: { tipo, registro, virado } }
notas:       { V1: { id_do_trecho: { nota, com } }, ... }    // nota: valor ou lista; "x" = não é isso
extras:      { v3_targets, v4_mapped_purpose, v4_region_gated, v6_which }
override:    { campo: valor }                                 // só o corrigido à mão
comentarios: { V1: "..." }
confirmadas: { V1: true }                                     // o clique em Confirmar
+ os campos de hoje, calculados (v1_code, v1_register, v1_evidence, ...), keyword_log, notes, _ts
```

Ids de trecho: `c:V1-3` (citação, mesma numeração do copiloto) e `h:<8 hex>`
(hit da busca, sha256 de arquivo + trecho). O κ continua lendo os campos
calculados; `compute-agreement.py` não muda. O julgamento trecho a trecho vira
dado publicável.

## Fonte única das regras

As opções de nota por variável, os tipos de documento e o registro padrão saem
de `exportar-codebook.py` (`codebook.json`: `notas`, `tipos_doc`). A página lê
de lá; o copiloto lê de lá; os testes em JavaScript leem a mesma coisa pelo
`assistente/test/portao.json`. O cálculo (`derivar`) vive em
`assistente/core.mjs`, com um teste por regra.

## Fora do escopo

Mudar o critério congelado; mostrar a etiqueta `role` da passada 1; chamadas ao
modelo durante a codificação.
