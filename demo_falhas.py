"""Provoca falhas previsíveis em pastas isoladas (demo_falhas_execucao/) e mostra que o robô
registra no log, segue um caminho seguro e termina a execução. Gera docs/EVIDENCIAS_FALHAS.md.

Uso: python demo_falhas.py   (depois de python main.py tudo, que treina o modelo e salva os snapshots)
"""
import json
import random
import shutil
from pathlib import Path

import gerar_dados
from main import etapa_coletar, etapa_encaminhar
from src.config import Config
from src.db import conectar
from src.logger import configurar_logger
from src.mock_api import MockAPI
from src.smtp_local import SMTPLocal

RAIZ = Path(__file__).resolve().parent
BASE = RAIZ / "demo_falhas_execucao"
PRINCIPAL = Config()
PORTA_SMTP = 1027
cenarios = []


def preparar(nome, **extra):
    base = BASE / nome
    shutil.rmtree(base, ignore_errors=True)
    (base / "data" / "snapshots").mkdir(parents=True)
    shutil.copy(PRINCIPAL.arquivo_base, base / "data" / "base_quem_resolve.json")
    cfg = Config(base=base, backoff_segundos=0.1, atraso_requisicoes=0, timeout_http=3, smtp_timeout=3,
                 max_falhas_seguidas=2, caminho_modelo=PRINCIPAL.caminho_modelo, smtp_porta=PORTA_SMTP,
                 smtp_auto_local=False, **extra)  # aqui o SMTP fora do ar é proposital
    cfg.criar_pastas()
    return cfg, configurar_logger(cfg.dir_logs, nome=f"demo_{nome}")


def fontes(cfg, lista):
    cfg.arquivo_fontes.write_text(json.dumps({"fontes": lista}, ensure_ascii=False), encoding="utf-8")


def fonte_original(id_fonte, **mudancas):
    todas = json.loads(PRINCIPAL.arquivo_fontes.read_text(encoding="utf-8"))["fontes"]
    return {**next(f for f in todas if f["id"] == id_fonte), **mudancas}


def copiar_snapshot(cfg, id_fonte):
    shutil.copy(PRINCIPAL.dir_snapshots / f"{id_fonte}.html", cfg.dir_snapshots / f"{id_fonte}.html")


def inserir_ocorrencias(cfg, n=5, invalidas=False):
    base = {"categorias": {c["id"]: c for c in json.loads(cfg.arquivo_base.read_text(encoding="utf-8"))["categorias"]}}
    ocs, gab = gerar_dados.gerar_ocorrencias(base, random.Random(156))
    grupo = "revisao" if invalidas else "enviar"
    ids = gab[(gab["decisao_esperada"] == grupo) &
              (gab["observacao"].str.startswith("inválida") if invalidas else True)]["id"].head(n).tolist()
    escolhidas = [o for o in ocs if o["id"] in ids]
    gerar_dados.gravar_ocorrencias(cfg.arquivo_db, escolhidas)
    return len(escolhidas)


def status(cfg):
    with conectar(cfg.arquivo_db) as con:
        return dict(con.execute("SELECT status, COUNT(*) FROM ocorrencia GROUP BY status").fetchall())


def emails(cfg):
    return len(list((cfg.base / "caixa_teste").glob("*.eml")))


def trecho_log(cfg, filtro, n=10):
    linhas = next(cfg.dir_logs.glob("*.log")).read_text(encoding="utf-8").splitlines()
    return [l for l in linhas if any(f in l for f in filtro)][:n]


def registrar(titulo, reacao, resultado, rel, log_trecho=None):
    cenarios.append({"titulo": titulo, "reacao": reacao, "resultado": resultado,
                     "ocorrencias": rel.ocorrencias if rel else [], "log": log_trecho or []})


# 1. Site fora do ar -> retry, circuit breaker e snapshot ----------------------------------------
cfg, log = preparar("1_site_fora_do_ar")
fontes(cfg, [fonte_original(i, url=f"https://sp156-fora-do-ar.invalid/servico/{i}") for i in ("sp156_952", "sp156_2641", "sp156_938")])
for i in ("sp156_952", "sp156_2641", "sp156_938"):
    copiar_snapshot(cfg, i)
rel = etapa_coletar(cfg, log)
registrar("Site fora do ar (domínio inexistente)",
          "Retry com espera exponencial; após 2 falhas seguidas o circuit breaker desliga o site e as fontes usam o snapshot",
          f"{rel.contadores['fontes_via_snapshot']}/3 fontes vieram do snapshot; {rel.contadores['trechos_gravados']} "
          "trechos gravados", rel, trecho_log(cfg, ["falhou", "aguardando", "Circuit breaker", "snapshot"]))

# 2. Snapshot ausente --------------------------------------------------------------------------
cfg, log = preparar("2_snapshot_ausente")
fontes(cfg, [fonte_original("sp156_952", url="https://sp156-fora-do-ar.invalid/952"),
             fonte_original("sp156_1037", url="https://sp156-fora-do-ar.invalid/1037")])
copiar_snapshot(cfg, "sp156_952")  # 1037 fica sem snapshot de propósito
rel = etapa_coletar(cfg, log)
registrar("Site fora do ar e snapshot ausente para uma das fontes",
          "A fonte sem snapshot é ignorada com erro no log; a outra segue normalmente",
          f"fontes sem dados: {rel.contadores['fontes_sem_dados']}; via snapshot: {rel.contadores['fontes_via_snapshot']}; "
          f"trechos gravados: {rel.contadores['trechos_gravados']}", rel)

# 3. Arquivos e estado corrompidos -------------------------------------------------------------
cfg, log = preparar("3_arquivos_corrompidos")
fontes(cfg, [fonte_original("sp156_952"), fonte_original("sp156_720")])
copiar_snapshot(cfg, "sp156_952")
(cfg.dir_snapshots / "sp156_720.html").write_bytes(bytes(random.Random(1).randrange(256) for _ in range(3000)))
(cfg.dir_snapshots / "manifesto.json").write_text("{corrompido", encoding="utf-8")
rel_c = etapa_coletar(cfg, log, offline=True)
inserir_ocorrencias(cfg, 3)
cfg.arquivo_enviados.write_text("isto não é json", encoding="utf-8")
with SMTPLocal(cfg.base / "caixa_teste", "localhost", PORTA_SMTP):
    rel_e = etapa_encaminhar(cfg, log)
rel_c.ocorrencias += rel_e.ocorrencias
backups = [p.name for p in cfg.dir_state.glob("*.corrompido_*")]
registrar("Snapshot HTML corrompido, manifesto corrompido e registro de enviados (state) corrompido",
          "Snapshot inútil é descartado; manifesto e registro são recriados, com backup do arquivo ruim",
          f"trechos gravados: {rel_c.contadores['trechos_gravados']}; e-mails enviados depois: "
          f"{rel_e.contadores['emails_enviados']}; backup: {', '.join(backups) or '-'}", rel_c)

# 4. Base quem-resolve corrompida -> nenhum envio, status intacto ------------------------------
cfg, log = preparar("4_base_corrompida")
inserir_ocorrencias(cfg, 3)
cfg.arquivo_base.write_text('{"categorias": [ {"id": "buraco_via"', encoding="utf-8")
antes = status(cfg)
rel = etapa_encaminhar(cfg, log)
registrar("Base 'quem resolve o quê' corrompida",
          "Sem roteamento confiável o robô não envia nada; as ocorrências continuam pendentes",
          f"status antes {antes} -> depois {status(cfg)}", rel)

# 5. Dados inválidos ---------------------------------------------------------------------------
cfg, log = preparar("5_dados_invalidos")
n_inv = inserir_ocorrencias(cfg, 6, invalidas=True)
with SMTPLocal(cfg.base / "caixa_teste", "localhost", PORTA_SMTP):
    rel = etapa_encaminhar(cfg, log)
registrar("Ocorrências inválidas (descrição vazia/curta, categoria fora da base, prioridade 9, id não-UUID, origem inválida)",
          "Validação barra o envio e manda para a fila de revisão humana com o motivo",
          f"{rel.contadores['revisao_humana']}/{n_inv} para revisão; e-mails enviados: {rel.contadores['emails_enviados']}; "
          f"status: {status(cfg)}", rel, trecho_log(cfg, ["revisão humana"]))

# 6. API fora do ar -> fallback SQLite ---------------------------------------------------------
cfg, log = preparar("6_api_fora_do_ar", api_base_url="http://127.0.0.1:9")
inserir_ocorrencias(cfg, 3)
with SMTPLocal(cfg.base / "caixa_teste", "localhost", PORTA_SMTP):
    rel = etapa_encaminhar(cfg, log)
registrar("API do Quem Resolve? fora do ar",
          "Retry com espera exponencial no GET /health e uso da reserva SQLite local",
          f"fonte usada: {rel.extras['fonte_das_ocorrencias']}; e-mails enviados: {rel.contadores['emails_enviados']}",
          rel, trecho_log(cfg, ["API", "reserva"]))

# 7. SMTP fora do ar -> status não muda ---------------------------------------------------------
cfg, log = preparar("7_smtp_fora_do_ar")
inserir_ocorrencias(cfg, 5)
antes = status(cfg)
rel = etapa_encaminhar(cfg, log)  # nenhum SMTP escutando na porta
registrar("Servidor SMTP fora do ar",
          "Retry com espera exponencial; circuit breaker após 2 falhas seguidas; nenhum status é alterado",
          f"status antes {antes} -> depois {status(cfg)}; mantidas pendentes: "
          f"{rel.contadores['falha_envio_mantida_pendente']}", rel,
          trecho_log(cfg, ["SMTP", "Circuit breaker", "pendente_envio"], 12))

# 8. Reexecução idempotente + falha ao marcar o status (PATCH) ---------------------------------
cfg, log = preparar("8_reexecucao_idempotente")
inserir_ocorrencias(cfg, 5)
with SMTPLocal(cfg.base / "caixa_teste", "localhost", PORTA_SMTP):
    with MockAPI(cfg.arquivo_db, porta=0, falhar_patch=True) as api:   # e-mail sai, PATCH falha
        cfg.api_base_url = api.url
        r1 = etapa_encaminhar(cfg, log)
    e1, s1 = emails(cfg), status(cfg)
    with MockAPI(cfg.arquivo_db, porta=0) as api:                       # API volta ao normal
        cfg.api_base_url = api.url
        r2 = etapa_encaminhar(cfg, log)
    e2, s2 = emails(cfg), status(cfg)
    with MockAPI(cfg.arquivo_db, porta=0) as api:                       # terceira rodada
        cfg.api_base_url = api.url
        r3 = etapa_encaminhar(cfg, log)
    e3 = emails(cfg)
r1.ocorrencias += r2.ocorrencias + r3.ocorrencias
registrar("Reexecução, incluindo falha da API ao marcar 'enviada' depois do e-mail sair",
          "O registro state/enviados.json impede reenvio; a rodada seguinte só sincroniza o status",
          f"1ª rodada (PATCH falhando): {r1.contadores['emails_enviados']} e-mails, status {s1}. "
          f"2ª rodada: {e2 - e1} e-mails novos, {r2.contadores['status_sincronizado_sem_reenvio']} status sincronizados, "
          f"status {s2}. 3ª rodada: {r3.contadores['pendentes_lidas']} pendentes, {e3 - e2} e-mails novos", r1)

# ---------- relatório ----------
md = ["# Evidências de tratamento de falhas", "",
      "> Arquivo gerado por `python demo_falhas.py`. Cada cenário roda numa pasta isolada em "
      "`demo_falhas_execucao/`, com o mesmo código do robô principal (`main.py`).", "",
      "| # | Falha provocada | Como o robô reagiu | Resultado medido |", "|---|---|---|---|"]
for i, c in enumerate(cenarios, 1):
    md.append(f"| {i} | {c['titulo']} | {c['reacao']} | {c['resultado']} |")
md += ["", "Em todos os cenários a execução terminou normalmente (sem traceback), com o problema registrado no log "
       "e no relatório de execução.", "", "## Ocorrências registradas por cenário", ""]
for i, c in enumerate(cenarios, 1):
    md.append(f"**{i}. {c['titulo']}**")
    md += [f"- [{o['nivel']}] {o['mensagem'][:260]}" for o in c["ocorrencias"]] or ["- (nenhuma ocorrência de erro)"]
    if c["log"]:
        md += ["", "```"] + [l[:200] for l in c["log"]] + ["```"]
    md.append("")
(RAIZ / "docs" / "EVIDENCIAS_FALHAS.md").write_text("\n".join(md), encoding="utf-8")
print("\n".join(md))
