# Codebook v2 — Auditoria de disclosures de experimentação (DSA VLOPs/VLOSEs)

**Instrumento congelado em 2026-07-04** (pós-piloto; sign-off do autor). Este documento consolida, em forma autônoma, o instrumento que antes vivia espalhado entre `pilot-2026-07-04.md` (§5, revisões A–M) e a aba "Codebook v2" de `coding-template-v2.xlsx`. **É o documento de trabalho do segundo avaliador.** Nenhuma regra aqui é nova; é a v2 congelada, reescrita por extenso.

**Pergunta da auditoria:** o que cada serviço divulga, *ao usuário*, sobre experimentação comportamental (testes A/B e afins) — e em que registro documental?

---

## 1. Regras gerais (valem para todas as variáveis)

**Unidade de análise = o serviço designado**, não o provedor. Google Search, Google Play, Google Maps, Google Shopping e YouTube são cinco linhas distintas; Facebook e Instagram, duas. Em plataformas multi-app com redações divergentes, codificar pelo conjunto documental primário do serviço designado e registrar a variância em Notes.

**Conjunto autoritativo = documentos vinculantes** voltados à UE: política de privacidade/notice, termos/condições de uso, aviso de cookies e anexo/tabela de bases legais (quando existir). Páginas de ajuda, blogs de engenharia, PR e sites corporativos de pesquisa são **registro não-vinculante**: entram na codificação (V1/V9 os capturam), mas *nunca* como se fossem o contrato.

**Registro ≠ hospedagem.** O que torna um documento vinculante é sua função legal, não a URL. O Privacy Notice da Amazon é servido sob URL de `/help/` e é vinculante; o "How Search Works" do Google é um microsite institucional e não é. Em caso de dúvida: o documento se declara parte do acordo com o usuário?

**Evidência primeiro.** Todo código que afirma presença exige **citação verbatim + documento + URL**. Todo código de ausência exige o **log de busca por palavra-chave** (§3) demonstrando a busca. Célula sem evidência é célula não codificada.

**Datação por documento.** Registrar data de vigência (effective date) e data de acesso **de cada documento**, não uma data por plataforma.

**Ausência tem dois sabores.** "No" substantivo (o documento trata do tema e nega/omite o mecanismo) é diferente de "não endereçado no registro" (o tema nunca é contemplado). Na dúvida, registre "No" e anote a distinção em Notes — não dá para distinguir "considerado e rejeitado" de "nunca pensado" só pelo texto.

---

## 2. As 9 variáveis

### V1 — Reconhecimento de experimentação (escada 0–3) + registro

| Código | Critério | Âncora do piloto |
|---|---|---|
| **0** | Nenhum reconhecimento, nem de "melhorar" | — |
| **1** | Só linguagem de "melhorar/aprimorar o serviço"; nem "testar" | Amazon (vinculante) |
| **2** | Reconhece **testar usuários**, mas não nomeia o método | Meta ("testing and troubleshooting new features") |
| **3** | Nomeia **experimento / teste A/B / randomização** explicitamente | Google ("700,000 experiments") |

Codificar o **nível de teto** (o mais alto encontrado em qualquer registro) **e** `v1_register`: onde esse teto vive — `binding` / `non-binding` / `both`. O achado central do estudo mora nessa combinação (ex.: v1=3 + register=non-binding significa "admite experimentar, mas só fora do contrato"). Registre também, em Notes, o nível do registro vinculante sozinho quando diferir do teto.

**Regra de fronteira (nível 2 vs 3):** "test new features" sem menção a grupos/variantes/aleatorização = 2. Qualquer menção a A/B, variantes servidas a usuários distintos, grupos de controle ou "experiments" em sentido experimental = 3. "Trial" de assinatura/período grátis **não** é experimentação (falso positivo comum).

### V2 — Enquadramento (multi-seleção)

Valores: `service improvement` · `research` (genérica) · `human-subjects research` · `social-good/community` · outro (anotar). Marcar **todos** que aparecem, com citação para cada. Co-ocorrência é comum ("research that improves our services" = os dois primeiros). `social-good/community` captura linguagem de "bem-estar da comunidade" (âncora: Instagram) — ecoa a justificativa do estudo de contágio emocional de 2014.

### V3 — Especificidade (decomposta)

- **V3a** — nomeia atividades/superfícies testadas? (Y/N) (ex.: "features", "layout", "ranking")
- **V3b** — nomeia **alvos** de experimento? (lista aberta: ranking, preço, mensagem/copy, afeto/emoção, fricção, defaults…) Distinguir alvo *de experimento* de mera personalização declarada (recomendação algorítmica descrita como feature ≠ alvo de experimento).
- **V3c** — divulga algum experimento **específico/ativo**? (Y/N)
- **V3-pricing** — flag dedicada: **preço/personalização de preço nomeado como alvo?** (Y/N). Cláusula de "erro de precificação" (mispricing) **não** conta. Se preço aparecer só em registro não-vinculante, marcar Y e anotar o registro em Notes — a flag não tem campo próprio de registro na v2 (limitação conhecida; candidata a v3).

### V4 — Base legal declarada (multi-seleção)

Valores: `legitimate interest` · `consent` · `contract` · `not stated` (= não declarada **para experimentação**; inferida da cláusula de melhoria). Registrar também:
- `v4_mapped_purpose`: **qual finalidade declarada** você mapeou como cobrindo experimentação (ex.: "improve services");
- `v4_region_gated` (Y/N): a tabela de bases por finalidade só carrega de IP/locale da UE?

**Atenção de vantagem:** o segundo avaliador deve ler **os documentos do manifesto** (mesmas URLs e datas da 1ª passada). Se um link estiver morto ou o conteúdo visivelmente mudado, **registrar e pular o campo** — não substituir por versão diferente do documento (isso criaria divergência espúria).

### V5 — Opt-out de experimentação (escada)

`none` → `GDPR-objection-only` (só o direito genérico de objeção do Art. 21, sem controle específico de experimento) → `cookie/ads-only` (banner existe, mas governa ads/medição, não experimentação) → `dedicated` (opt-out específico de experimentação) → `opt-in`.

**Escopo estrito à experimentação.** Controle de cookies de analytics não é opt-out de experimento. Falso positivo clássico: banner de consentimento parece opt-out mas rege publicidade.

### V6 — Programa opt-in de beta/teste (Y/N + nome)

TestFlight, Search Labs, canais beta etc. **Eixo ortogonal**: inscreve voluntários em acesso antecipado a features; **não mitiga o V5** — os demais usuários continuam nos experimentos de rotina. Nunca somar V6 com V5.

### V7 — Debriefing (Y/N)

Aviso *posterior* de que a pessoa participou de um experimento. **Excluir explicitamente** (falsos positivos vistos no piloto): aviso de processamento, aviso de decisão automatizada, aviso de mudança de serviço. Nenhum deles é debriefing.

### V8 — Ética / revisão / avaliação de risco (Y/N + nota)

Menção, nos documentos ao usuário, a revisão ética, comitê/board, ou avaliação de risco **para experimentos**. Linguagem borderline de "impacto" (ex.: "impact on you and others" atada a descontinuação de serviço) = N com nota. Avaliações de risco sistêmico do DSA existem por obrigação regulatória, mas se não estão nos documentos ao consumidor, **não viram Y** — registrar como nota de gap regulatório-vs-documento.

### V9 — Onde divulgado (multi-seleção) + registro

Locais: `privacy policy` · `ToS/conditions` · `research notice separado` · `help centre` · `blog/PR/site de pesquisa` · outro. E `v9_register`: `binding` / `non-binding` / `both`. Separar (de novo) registro legal de URL/hosting.

---

## 3. Protocolo de busca por palavra-chave (obrigatório por documento)

Para **cada documento** do conjunto, buscar e registrar contagem de hits de:

`experiment` · `A/B` · `randomi[sz]e` · `test` · `trial` · `beta` · `control group` · `debrief` · `ethics` · `review board` · `IRB` · `risk assessment`

Formato do log: `experiment:0 / A-B:0 / test:3 (PP); experiment:8 (help)`. Hits precisam de triagem manual — "test" acende em "contest", "trial" em "free trial" (contar só usos no sentido experimental, anotar exclusões). **É esse log que torna cada "No" auditável**: a alegação de ausência vem acompanhada da prova de que se procurou.

---

## 4. Instruções específicas do segundo avaliador

1. **Cegueira operacional.** Codifique **a partir dos documentos**, sem consultar os códigos da 1ª passada (`coded-data.json`, `coding-results.md` e a seção 4.3 do paper contêm resultados — não os abra durante a codificação). Sabemos que os achados-título já lhe foram comunicados; isso será declarado na seção de confiabilidade. O que pedimos é que cada célula saia do texto do documento, não da memória do resultado.
2. **Volume a seu critério.** O instrumento aceita qualquer N. Siga a **ordem sugerida** (estratificada por gênero de plataforma, sorteada com semente fixa `20260722`) e pare onde quiser — a ordem garante que qualquer prefixo é uma amostra defensável, com todos os gêneros representados desde o início.
3. **Dúvida de regra ≠ dúvida de julgamento.** Se uma regra do codebook parecer ambígua, anote a dúvida em Notes e codifique mesmo assim (sua melhor leitura). A discussão acontece na adjudicação — *depois* do cálculo de concordância, nunca antes.
4. **Ferramenta.** O instrumento interativo (página web) traz este codebook embutido, os links dos documentos por serviço, os campos das 9 variáveis e exporta um JSON no esquema exato da 1ª passada. Alternativa: a aba "Coding" de `coding-template-v2.xlsx` (colunas I–AH), ignorando as linhas preenchidas.

## 5. O que acontece com o resultado

Concordância calculada por variável (`compute-agreement.py`): **percentual de concordância + tabela de contingência** nas variáveis degeneradas ou quase (V7 e V8 não variaram na 1ª passada; V5 variou minimamente), **κ de Cohen** nas que variam, **κ ponderado** na V1 (ordinal). Depois do cálculo — e só depois — adjudicação conjunta das divergências, com registro de decisão e racional; regras esclarecidas voltam para o codebook como notas de v2.1, sem tocar códigos já lançados sem trilha.
