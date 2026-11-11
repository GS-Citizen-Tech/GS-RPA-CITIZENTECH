# Proteção de dados, ética e ODS

## Proteção de dados (LGPD)

- **Só dados sintéticos ou públicos.** As ocorrências, os textos de treino e de teste e os dados pessoais (nomes, CPFs, telefones e e-mails) são inventados por `gerar_dados.py`. As páginas raspadas são públicas e institucionais (Carta de Serviços do SP156 e FAQ do SP Regula).
- **Minimização.** A descrição do cidadão é anonimizada antes de ser classificada, gravada na fila de revisão ou enviada por e-mail. Na avaliação, 100% dos dados pessoais fictícios do conjunto de teste foram mascarados, e os e-mails enviados tinham 0 dados pessoais detectáveis (ver [`RESULTADOS_AVALIACAO.md`](RESULTADOS_AVALIACAO.md)). Nenhum dado pessoal vai para API externa: o scraping só faz GET em páginas públicas.
- **Nenhum envio real.** Os destinatários são caixas fictícias (`*@caixa-teste.local`), e uma trava em `src/email_envio.py` bloqueia qualquer outro domínio. O padrão é um SMTP local, sem internet.
- **Segredos fora do código.** URL e token da API e credenciais SMTP ficam no `.env`, que está no `.gitignore`. O modelo é o `.env.example`.

## Ética e limites do modelo

- **O modelo erra, e isso foi medido.** A acurácia no teste sintético é a de [`RESULTADOS_AVALIACAO.md`](RESULTADOS_AVALIACAO.md). As maiores confusões ficam entre categorias vizinhas: árvore em geral x árvore sobre fiação, poste x iluminação, esgoto x vazamento de água. Com texto real a acurácia tende a ser menor.
- **Revisão humana em vez de "chute".** O robô só envia quando a IA concorda com a categoria escolhida pelo cidadão e tem confiança de pelo menos 40%. O resto vai para um atendente, com o motivo. A troca é deliberada: na avaliação, nenhuma ocorrência com categoria errada foi enviada, ao custo de cerca de 1 em cada 3 ocorrências corretas ir para a revisão manual.
- **Viés de linguagem.** Quem escreve muito diferente dos exemplos de treino (gírias regionais, outro idioma, texto muito curto) cai mais na revisão humana e pode esperar mais. O modelo deve ser retreinado com dados reais anonimizados e auditado por categoria e por região.
- **Anonimização por regras tem limite.** Um nome solto, sem gatilho como "meu nome é", não é detectado.
- **Scraping responsável.** O robô respeita o robots.txt, se identifica no User-Agent, espera 2 segundos entre requisições ao mesmo site, para de chamar o site após falhas seguidas (circuit breaker) e coleta poucas páginas, só de conteúdo público. As fontes são citadas nos metadados de cada trecho e no e-mail.
- **Emergências não são roteadas por e-mail.** Violência e risco imediato ficam com o guardrail de outro módulo. Para categorias de risco (fio de energia caído, cheiro de gás), o e-mail sai marcado como `[URGENTE]` e lembra que o cidadão deve acionar o canal de emergência: o e-mail é só registro.
- **A base precisa de validação.** As regras de `data/base_quem_resolve.json` sem fonte oficial estão marcadas como "a validar". Nenhum telefone ou e-mail de órgão foi inventado.

## ODS

- **ODS 11 (Cidades e comunidades sustentáveis):** encaminha ao responsável certo problemas de zeladoria e limpeza urbana, como buraco, iluminação, lixo, bueiro e árvore, reduzindo o tempo em que o problema fica sem dono.
- **ODS 16 (Instituições eficazes, responsáveis e transparentes):** cada ocorrência tem protocolo, a regra de roteamento cita a fonte oficial, toda decisão do robô (enviada, revisão e motivo) fica no log e no relatório, e as dúvidas da IA vão para uma pessoa.
