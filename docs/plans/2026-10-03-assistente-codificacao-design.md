# Assistente de codificação do 2º codificador: desenho

Data: 03/10/2026. Decisões tomadas com Marcus Garcia nesta data.

## Por que existe

O 2º codificador (Prof. Marcelo Maia) ia codificar os 26 serviços num notebook
do Colab com um painel em ipywidgets. Em 03/10/2026 o Marcus testou o painel,
salvou e não viu resultado nenhum. Todos os testes anteriores tinham rodado fora
do Colab: o código foi testado, a tela nunca. O notebook sai. Entra uma página
web em formato de assistente, testada no navegador antes de qualquer entrega.

Também se descobriu que o servidor `/api/state` substituía o arquivo inteiro a
cada gravação e aceitava gravação de qualquer visitante, inclusive do instrumento
público em HTML. Qualquer pessoa podia desfazer respostas do 2º codificador.

## Decisões

1. **Página web, sem Colab.** HTML e JavaScript puros, sem framework e sem build.
2. **Formato de assistente.** Uma pergunta por tela, na ordem V1 a V9 e depois o
   log de palavras-chave. Quase tudo custa um clique.
3. **Copiloto de IA, atrás de um botão.** A sugestão de código aparece quando o
   codificador clica em "ver sugestão". O clique não é registrado: a IA é um
   acelerador, e a responsabilidade é do codificador. Em troca, os prompts do
   copiloto ficam visíveis dentro da página e publicados no repositório.
4. **Sugestões congeladas, não ao vivo.** Um script roda uma vez, antes da
   codificação, só com material congelado. Sem chave de API em servidor.
5. **Modo ensaio.** Um segundo link, com chave própria, grava num arquivo
   separado. Tudo o mais é igual.
6. **Etiquetas [vinculante] escondidas.** Elas vêm da passada 1
   (`freeze-sources.py cmd_inventory`). O codificador decide pela função do
   documento, como o guia manda.
7. **A página inicial do site passa a ser o assistente.** O instrumento antigo em
   HTML mostrava anotações da passada 1; ele fica no histórico do git.
8. **Os notebooks 04 e 05 e o painel em ipywidgets saem do pacote.**

## Parte 1: a tela do codificador

**Entrada.** Link único. Na primeira vez, uma tela de contexto e o botão
"Começar". Depois, a página abre em "Continuar", no ponto em que parou.

**Serviço.** Nome, lista de documentos (cada um abre o texto congelado; a página
original em letra menor) e progresso "n de 10".

**Uma pergunta por tela.** Cada tela tem:
- a pergunta em linguagem simples e o lembrete; o critério completo num painel
  lateral;
- a evidência: trechos da busca por palavra-chave e as citações congeladas do
  modelo, com link para o documento;
- os campos da variável;
- o campo de evidência, preenchido com um clique no trecho ou digitado;
- o botão "ver sugestão do copiloto", que mostra valores propostos, razão em uma
  ou duas frases e os trechos que a sustentam, e o botão "aplicar sugestão";
- "Confirmar e seguir", com a confirmação "gravado às hh:mm" ao lado, e "Voltar".

**Palavras-chave.** O log vem preenchido com as contagens automáticas. O
codificador corrige e confirma.

**Fim do serviço.** Resumo das dez respostas e "Próximo serviço", que abre o
próximo incompleto. No fim dos 26, "Pronto. Obrigado."

**Trava.** Não avança sem resposta e sem evidência (mesma regra do
`coding_flow.py`).

## Parte 2: o copiloto

**Entrada do script**, por serviço e variável: critério e guia da variável,
citações verificadas do serviço (`sugestoes/`), contagens de palavras-chave,
lista de documentos. Nunca: códigos ou anotações da passada 1, etiquetas de
vinculante, respostas do 2º codificador.

**Saída**, por serviço e variável: valor proposto por campo, razão em uma ou
duas frases, confiança, índices das citações usadas.

**Onde fica.** Um arquivo por serviço no site do corpus (`copiloto/`), público e
`noindex`, como as citações. Quem tiver o endereço lê tudo sem o botão; por
decisão do Marcus, isso não importa.

**Transparência.** Link "como o copiloto funciona" dentro da caixa de sugestão:
prompt exato, modelo, data e o que ele recebeu.

## Parte 3: chave, gravação e servidor

**Chave** no fragmento do link (`#k=...`). O navegador não envia o fragmento, e a
chave não aparece em log. A página guarda a chave e a envia num cabeçalho. Duas
chaves (real e ensaio) em variáveis de ambiente da Vercel; a real também no
Keychain do Mac do Marcus. O link do codificador sai de um comando local.

**Gravação** por serviço, no formato de hoje (`{"records": {servico: registro}}`,
com `_ts`). O servidor substitui só o serviço gravado. Cada gravação continua
virando um commit no ramo `coder2-data`. `compute-agreement.py` não muda.

**Duas janelas.** A página envia o `_ts` que viu por último; se o servidor tiver
um mais novo, recusa, e a página recarrega e avisa.

**Rede.** Cópia local no navegador antes de enviar. Confirmação vermelha e nova
tentativa automática em caso de falha. "Próximo serviço" só abre depois da
confirmação do servidor.

**Ensaio.** Arquivo `audit/ensaio-progress.json` no mesmo ramo. Botão "zerar
ensaio".

## Parte 4: construção e teste

Ordem: servidor com testes; dados congelados publicados (sugestões do copiloto,
contagens de palavras-chave, codebook em JSON); página; página do copiloto.

Teste: pré-visualização da Vercel ligada ao arquivo de ensaio; um serviço
inteiro codificado no navegador do app, com confirmação, recarga e commit
conferidos; teste de cinco minutos do Marcus com roteiro curto; produção e troca
da página inicial. Depois disso, escopo congelado.

O PR #8 não é mergeado: o novo ramo parte dele e o novo PR o substitui.

O artigo: a seção de confiabilidade passa a declarar o copiloto, os prompts
publicados e a origem congelada das sugestões.
