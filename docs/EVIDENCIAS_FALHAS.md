# Evidências de tratamento de falhas

> Arquivo gerado por `python demo_falhas.py`. Cada cenário roda numa pasta isolada em `demo_falhas_execucao/`, com o mesmo código do robô principal (`main.py`).

| # | Falha provocada | Como o robô reagiu | Resultado medido |
|---|---|---|---|
| 1 | Site fora do ar (domínio inexistente) | Retry com espera exponencial; após 2 falhas seguidas o circuit breaker desliga o site e as fontes usam o snapshot | 3/3 fontes vieram do snapshot; 30 trechos gravados |
| 2 | Site fora do ar e snapshot ausente para uma das fontes | A fonte sem snapshot é ignorada com erro no log; a outra segue normalmente | fontes sem dados: 1; via snapshot: 1; trechos gravados: 11 |
| 3 | Snapshot HTML corrompido, manifesto corrompido e registro de enviados (state) corrompido | Snapshot inútil é descartado; manifesto e registro são recriados, com backup do arquivo ruim | trechos gravados: 11; e-mails enviados depois: 1; backup: enviados.corrompido_20261110212542.json |
| 4 | Base 'quem resolve o quê' corrompida | Sem roteamento confiável o robô não envia nada; as ocorrências continuam pendentes | status antes {'pendente_envio': 3} -> depois {'pendente_envio': 3} |
| 5 | Ocorrências inválidas (descrição vazia/curta, categoria fora da base, prioridade 9, id não-UUID, origem inválida) | Validação barra o envio e manda para a fila de revisão humana com o motivo | 6/6 para revisão; e-mails enviados: 0; status: {'pendente_envio': 6} |
| 6 | API do Quem Resolve? fora do ar | Retry com espera exponencial no GET /health e uso da reserva SQLite local | fonte usada: SQLite local (reserva); e-mails enviados: 1 |
| 7 | Servidor SMTP fora do ar | Retry com espera exponencial; circuit breaker após 2 falhas seguidas; nenhum status é alterado | status antes {'pendente_envio': 5} -> depois {'pendente_envio': 5}; mantidas pendentes: 3 |
| 8 | Reexecução, incluindo falha da API ao marcar 'enviada' depois do e-mail sair | O registro state/enviados.json impede reenvio; a rodada seguinte só sincroniza o status | 1ª rodada (PATCH falhando): 3 e-mails, status {'pendente_envio': 5}. 2ª rodada: 0 e-mails novos, 3 status sincronizados, status {'enviada': 3, 'pendente_envio': 2}. 3ª rodada: 2 pendentes, 0 e-mails novos |

Em todos os cenários a execução terminou normalmente (sem traceback), com o problema registrado no log e no relatório de execução.

## Ocorrências registradas por cenário

**1. Site fora do ar (domínio inexistente)**
- [AVISO] [sp156_952] site indisponível (GET https://sp156-fora-do-ar.invalid/robots.txt: ConnectionError (NameResolutionError)): usando snapshot salvo (sp156_952.html).
- [AVISO] [sp156_2641] site indisponível (GET https://sp156-fora-do-ar.invalid/robots.txt: ConnectionError (NameResolutionError)): usando snapshot salvo (sp156_2641.html).
- [AVISO] [sp156_938] site desligado nesta execução (circuit breaker aberto para 'sp156-fora-do-ar.invalid'): usando snapshot salvo (sp156_938.html).

```
2026-11-10 21:25:35 | WARNING  | GET https://sp156-fora-do-ar.invalid/robots.txt: falhou (tentativa 1/3): ConnectionError (NameResolutionError)
2026-11-10 21:25:35 | INFO     | GET https://sp156-fora-do-ar.invalid/robots.txt: aguardando 0.1s antes de tentar de novo
2026-11-10 21:25:35 | WARNING  | GET https://sp156-fora-do-ar.invalid/robots.txt: falhou (tentativa 2/3): ConnectionError (NameResolutionError)
2026-11-10 21:25:35 | INFO     | GET https://sp156-fora-do-ar.invalid/robots.txt: aguardando 0.2s antes de tentar de novo
2026-11-10 21:25:35 | WARNING  | GET https://sp156-fora-do-ar.invalid/robots.txt: falhou (tentativa 3/3): ConnectionError (NameResolutionError)
2026-11-10 21:25:35 | WARNING  | [sp156_952] site indisponível (GET https://sp156-fora-do-ar.invalid/robots.txt: ConnectionError (NameResolutionError)): usando snapshot salvo (sp156_952.html).
2026-11-10 21:25:35 | WARNING  | GET https://sp156-fora-do-ar.invalid/robots.txt: falhou (tentativa 1/3): ConnectionError (NameResolutionError)
2026-11-10 21:25:35 | INFO     | GET https://sp156-fora-do-ar.invalid/robots.txt: aguardando 0.1s antes de tentar de novo
2026-11-10 21:25:35 | WARNING  | GET https://sp156-fora-do-ar.invalid/robots.txt: falhou (tentativa 2/3): ConnectionError (NameResolutionError)
2026-11-10 21:25:35 | INFO     | GET https://sp156-fora-do-ar.invalid/robots.txt: aguardando 0.2s antes de tentar de novo
```

**2. Site fora do ar e snapshot ausente para uma das fontes**
- [AVISO] [sp156_952] site indisponível (GET https://sp156-fora-do-ar.invalid/robots.txt: ConnectionError (NameResolutionError)): usando snapshot salvo (sp156_952.html).
- [ERRO] [sp156_1037] site indisponível (GET https://sp156-fora-do-ar.invalid/robots.txt: ConnectionError (NameResolutionError)) e não há snapshot em sp156_1037.html: fonte ignorada.

**3. Snapshot HTML corrompido, manifesto corrompido e registro de enviados (state) corrompido**
- [ERRO] Manifesto de snapshots corrompido (Expecting property name enclosed in double quotes: line 1 column 2 (char 1)); recriando.
- [AVISO] [sp156_952] modo offline: usando snapshot salvo (sp156_952.html).
- [AVISO] [sp156_720] modo offline: usando snapshot salvo (sp156_720.html).
- [ERRO] [sp156_720] snapshot inutilizável (marcador de início 'O QUE É' não encontrado): fonte ignorada.
- [ERRO] Registro de enviados corrompido (Expecting value: line 1 column 1 (char 0)); guardado em enviados.corrompido_20261110212542.json. Recomeçando vazio: o status no banco/API continua impedindo reenvio do que já foi marcado como enviada.

**4. Base 'quem resolve o quê' corrompida**
- [ERRO] Base quem-resolve inválida (base_quem_resolve.json corrompido: Expecting ',' delimiter: line 1 column 37 (char 36)): sem roteamento confiável, nenhuma ocorrência foi enviada e todas continuam pendente_envio.

**5. Ocorrências inválidas (descrição vazia/curta, categoria fora da base, prioridade 9, id não-UUID, origem inválida)**
- (nenhuma ocorrência de erro)

```
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261108-NG8Q4 -> revisão humana: dado inválido: categoria_final desconhecida: 'buraco'
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261109-CH4J9 -> revisão humana: dado inválido: prioridade fora de 1 a 5: 9
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261109-WTYPC -> revisão humana: dado inválido: id ausente ou não é UUID
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261109-WSQY8 -> revisão humana: dado inválido: descrição vazia ou com menos de 5 caracteres
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261110-B7U3D -> revisão humana: dado inválido: descrição vazia ou com menos de 5 caracteres
2026-11-10 21:25:46 | INFO     | Ocorrência QR-261110-CYB2P -> revisão humana: dado inválido: origem inválida: 'whatsapp'
```

**6. API do Quem Resolve? fora do ar**
- [ERRO] API indisponível (API GET /health: ConnectionError (NewConnectionError)). Usando a reserva SQLite local.

```
2026-11-10 21:25:50 | WARNING  | API GET /health: falhou (tentativa 1/3): ConnectionError (NewConnectionError)
2026-11-10 21:25:50 | INFO     | API GET /health: aguardando 0.1s antes de tentar de novo
2026-11-10 21:25:52 | WARNING  | API GET /health: falhou (tentativa 2/3): ConnectionError (NewConnectionError)
2026-11-10 21:25:52 | INFO     | API GET /health: aguardando 0.2s antes de tentar de novo
2026-11-10 21:25:55 | WARNING  | API GET /health: falhou (tentativa 3/3): ConnectionError (NewConnectionError)
2026-11-10 21:25:55 | ERROR    | API indisponível (API GET /health: ConnectionError (NewConnectionError)). Usando a reserva SQLite local.
2026-11-10 21:25:55 | INFO     | 3 ocorrência(s) pendente(s) de envio via SQLite local (reserva)
```

**7. Servidor SMTP fora do ar**
- [ERRO] 3 ocorrência(s) não enviada(s) por falha no SMTP; continuam pendente_envio.

```
2026-11-10 21:26:02 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: falhou (tentativa 1/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:02 | INFO     | SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: aguardando 0.1s antes de tentar de novo
2026-11-10 21:26:06 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: falhou (tentativa 2/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:06 | INFO     | SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: aguardando 0.2s antes de tentar de novo
2026-11-10 21:26:10 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: falhou (tentativa 3/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:10 | ERROR    | Falha no envio de QR-261109-8KW4K (SMTP envio [Quem Resolve?] QR-261109-8KW4K - Iluminação pública: ConnectionRefusedError (conexão recusada: nada escutand): status ma
2026-11-10 21:26:14 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-DXHRR - Iluminação pública: falhou (tentativa 1/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:14 | INFO     | SMTP envio [Quem Resolve?] QR-261109-DXHRR - Iluminação pública: aguardando 0.1s antes de tentar de novo
2026-11-10 21:26:18 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-DXHRR - Iluminação pública: falhou (tentativa 2/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:18 | INFO     | SMTP envio [Quem Resolve?] QR-261109-DXHRR - Iluminação pública: aguardando 0.2s antes de tentar de novo
2026-11-10 21:26:22 | WARNING  | SMTP envio [Quem Resolve?] QR-261109-DXHRR - Iluminação pública: falhou (tentativa 3/3): ConnectionRefusedError (conexão recusada: nada escutando na porta)
2026-11-10 21:26:22 | ERROR    | Circuit breaker ABERTO para 'SMTP localhost:1027' após 2 falhas seguidas: o serviço não será mais chamado nesta execução.
```

**8. Reexecução, incluindo falha da API ao marcar 'enviada' depois do e-mail sair**
- [ERRO] E-mail de QR-261109-8KW4K enviado, mas o status não foi atualizado (API PATCH /ocorrencias/963f586b-06a7-4685-9a00-9307557c6b9c/status: HTTPError: 503 Server Error: Service Unavailable). A próxima execução tenta marcar de novo SEM reenviar.
- [ERRO] E-mail de QR-261109-DXHRR enviado, mas o status não foi atualizado (API PATCH /ocorrencias/80166230-eaa4-479a-87dd-96bc7c59174d/status: HTTPError: 503 Server Error: Service Unavailable). A próxima execução tenta marcar de novo SEM reenviar.
- [ERRO] E-mail de QR-261110-BQHPX enviado, mas o status não foi atualizado (circuit breaker aberto para 'API Quem Resolve?'). A próxima execução tenta marcar de novo SEM reenviar.
