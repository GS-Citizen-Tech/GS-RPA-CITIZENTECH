"""PONTO DE ENTRADA do módulo de automação (RPA) do "Quem Resolve?".

Uso:
  python main.py tudo          # gerar -> treinar -> coletar -> encaminhar, em sequência
  python main.py gerar         # RF34: dados sintéticos (treino, teste, ocorrências simuladas)
  python main.py treinar       # treina o classificador TF-IDF + Regressão Logística
  python main.py coletar       # RF30/RF31: scraping -> limpeza -> trechos para o RAG (JSONL + SQL)
  python main.py encaminhar    # RF33: ocorrências pendentes -> e-mail ao órgão -> status enviada

Opções: --offline (coleta só dos snapshots) · --smtp-local (sobe um SMTP de teste embutido
em localhost:1025 durante a execução, gravando os e-mails em output/caixa_teste/).
Cada etapa trata as próprias falhas: um erro numa etapa é registrado e a próxima continua.
"""
import argparse
import sys

import pandas as pd

from src.base_quem_resolve import BaseInvalida, BaseQuemResolve
from src.classificador import Classificador
from src.config import Config
from src.db import gravar_base_quem_resolve
from src.logger import configurar_logger
from src.relatorio import Relatorio


def carregar_classificador(cfg, rel):
    if not cfg.caminho_modelo.exists():
        rel.erro("Modelo do classificador não encontrado (rode 'python main.py treinar'). "
                 "Seguindo sem a IA: nada será enviado sem conferência.")
        return None
    try:
        return Classificador.carregar(cfg.caminho_modelo)
    except Exception as e:
        rel.erro(f"Modelo do classificador ilegível ({type(e).__name__}); seguindo sem a IA.")
        return None


def etapa_gerar(cfg, log):
    rel = Relatorio("gerar", log)
    import gerar_dados
    rel.contadores.update(gerar_dados.main(cfg.dir_data, cfg.arquivo_db))
    return rel


def etapa_treinar(cfg, log):
    rel = Relatorio("treinar", log)
    if not cfg.arquivo_treino.exists():
        rel.aviso("Dados de treino ausentes: gerando dados sintéticos antes.")
        etapa_gerar(cfg, log)
    df = pd.read_csv(cfg.arquivo_treino)
    Classificador.treinar(df).salvar(cfg.caminho_modelo)
    rel.contadores["exemplos_treino"] = len(df)
    rel.contadores["categorias"] = df["categoria"].nunique()
    log.info(f"Modelo treinado com {len(df)} exemplos ({df['categoria'].nunique()} categorias)")
    return rel


def etapa_coletar(cfg, log, offline=False):
    from src.coleta import Coletor, carregar_fontes
    from src.etl import carregar, etiquetar, transformar
    rel = Relatorio("coletar", log)
    try:  # RF32: espelha a base "quem resolve o quê" no SQL
        base = BaseQuemResolve.carregar(cfg.arquivo_base)
        rel.contadores["regras_roteamento_gravadas"] = gravar_base_quem_resolve(cfg.arquivo_db, base)
    except BaseInvalida as e:
        rel.erro(f"Base quem-resolve inválida ({e}); tabelas de roteamento não atualizadas.")
    fontes = carregar_fontes(cfg.arquivo_fontes, rel)
    rel.contadores["fontes_configuradas"] = len(fontes)
    registros = Coletor(cfg, log, rel, offline=offline).coletar(fontes)
    df = transformar(registros, cfg.tamanho_chunk)
    if df.empty:
        rel.erro("Nenhum trecho obtido: a base de conhecimento anterior foi mantida (não sobrescrita).")
        return rel
    df = etiquetar(df, carregar_classificador(cfg, rel), cfg.limiar_etiqueta_docs)
    carregar(df, cfg.arquivo_conhecimento, cfg.arquivo_db)
    rel.contadores["registros_brutos"] = df.attrs.get("registros_brutos", len(registros))
    rel.contadores["trechos_gravados"] = len(df)
    rel.contadores["trechos_etiquetados_com_categoria"] = int((df["categoria_ia"] != "geral").sum())
    log.info(f"Base de conhecimento: {len(df)} trechos em {cfg.arquivo_conhecimento.name} e na tabela documento_base")
    return rel


def etapa_encaminhar(cfg, log, smtp_local=False):
    from src.email_envio import EnviadorEmail
    from src.encaminhador import Encaminhador
    from src.repositorio import obter_repositorio
    rel = Relatorio("encaminhar", log)
    try:
        base = BaseQuemResolve.carregar(cfg.arquivo_base)
    except BaseInvalida as e:
        rel.erro(f"Base quem-resolve inválida ({e}): sem roteamento confiável, nenhuma ocorrência foi enviada "
                 "e todas continuam pendente_envio.")
        return rel
    repo = obter_repositorio(cfg, log, rel)
    rel.extras["fonte_das_ocorrencias"] = repo.nome
    enc = Encaminhador(cfg, log, rel, base, carregar_classificador(cfg, rel), repo, EnviadorEmail(cfg, log))
    from src.smtp_local import HOSTS_LOCAIS, SMTPLocal, smtp_escutando
    if (not smtp_local and cfg.smtp_auto_local and cfg.smtp_host in HOSTS_LOCAIS
            and not smtp_escutando(cfg.smtp_host, cfg.smtp_porta)):
        rel.aviso(f"Nenhum SMTP escutando em {cfg.smtp_host}:{cfg.smtp_porta}: subindo o SMTP de teste "
                  "embutido (e-mails gravados em output/caixa_teste/). Para desligar: SMTP_AUTO_LOCAL=false.")
        smtp_local = True
    if smtp_local:
        with SMTPLocal(cfg.dir_saida / "caixa_teste", cfg.smtp_host, cfg.smtp_porta):
            log.info(f"SMTP de teste embutido ativo em {cfg.smtp_host}:{cfg.smtp_porta}")
            enc.executar()
    else:
        enc.executar()
    rel.extras["decisoes"] = enc.decisoes
    return rel


def resumo(dados):
    chaves = [k for k in dados if k not in ("ocorrencias", "decisoes", "etapa", "inicio")]
    return ", ".join(f"{k}={dados[k]}" for k in chaves)


def main(argv=None):
    p = argparse.ArgumentParser(description="Quem Resolve? - módulo de automação (RPA + IA)")
    p.add_argument("comando", choices=["tudo", "gerar", "treinar", "coletar", "encaminhar"])
    p.add_argument("--offline", action="store_true", help="coleta apenas dos snapshots salvos")
    p.add_argument("--smtp-local", action="store_true", help="sobe um SMTP de teste embutido em localhost:1025")
    args = p.parse_args(argv)

    cfg = Config()
    cfg.criar_pastas()
    log = configurar_logger(cfg.dir_logs)
    etapas = {
        "gerar": lambda: etapa_gerar(cfg, log),
        "treinar": lambda: etapa_treinar(cfg, log),
        "coletar": lambda: etapa_coletar(cfg, log, args.offline),
        "encaminhar": lambda: etapa_encaminhar(cfg, log, args.smtp_local),
    }
    ordem = list(etapas) if args.comando == "tudo" else [args.comando]
    houve_erro = False
    for nome in ordem:
        log.info(f"===== Etapa: {nome} =====")
        try:
            rel = etapas[nome]()
            dados = rel.salvar(cfg.dir_saida)
            houve_erro |= any(o["nivel"] == "ERRO" for o in dados["ocorrencias"])
            print(f"\n[{nome}] {resumo(dados)}\n")
        except Exception as e:  # última barreira: registra e segue para a próxima etapa
            houve_erro = True
            log.critical(f"Falha inesperada na etapa {nome}: {type(e).__name__}: {e}", exc_info=True)
    log.info("===== Fim da execução" + (" (com erros tratados; veja output/relatorio_*.md)" if houve_erro else "") + " =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
