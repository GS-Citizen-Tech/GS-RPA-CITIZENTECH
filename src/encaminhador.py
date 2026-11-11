"""RF33: encaminhamento automático das ocorrências pendentes ao órgão responsável.

Para cada ocorrência com status pendente_envio:
  1. valida o formato (contrato);
  2. anonimiza a descrição (CPF, telefone, e-mail, nome);
  3. IA (b): confere se a descrição bate com a categoria_final. Divergência ou confiança baixa
     -> revisão humana (não envia);
  4. consulta a base quem-resolve e monta o e-mail;
  5. envia por SMTP. Deu certo -> marca como enviada. Falhou -> NÃO muda o status, registra no log.

Idempotência: state/enviados.json guarda cada ocorrência já enviada (escrita atômica). Se o
e-mail saiu mas a marcação do status falhou, a próxima execução só tenta marcar de novo, sem
reenviar o e-mail.
"""
import json
import shutil
from datetime import datetime

import pandas as pd

from src.anonimizacao import anonimizar
from src.email_envio import DestinatarioNaoPermitido, montar_email
from src.resiliencia import CircuitoAberto, FalhaPersistente
from src.validacao import validar_ocorrencia

COLUNAS_REVISAO = ["id", "protocolo", "motivo", "categoria_final", "categoria_ia", "confianca_ia",
                   "descricao_anonimizada", "registrado_em"]


class RegistroEnviados:
    def __init__(self, caminho, relatorio):
        self.caminho, self.rel = caminho, relatorio
        self.dados = self._carregar()

    def _carregar(self):
        if not self.caminho.exists():
            return {}
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("formato inesperado")
            return dados
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            backup = self.caminho.with_name(f"{self.caminho.stem}.corrompido_{datetime.now():%Y%m%d%H%M%S}.json")
            shutil.move(self.caminho, backup)
            self.rel.erro(f"Registro de enviados corrompido ({e}); guardado em {backup.name}. Recomeçando vazio: "
                          "o status no banco/API continua impedindo reenvio do que já foi marcado como enviada.")
            return {}

    def __contains__(self, id_oc):
        return id_oc in self.dados

    def marcar(self, id_oc, **info):
        self.dados[id_oc] = {**self.dados.get(id_oc, {}), **info}
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.caminho)  # escrita atômica


class Encaminhador:
    def __init__(self, cfg, logger, relatorio, base, classificador, repositorio, enviador):
        self.cfg, self.log, self.rel = cfg, logger, relatorio
        self.base, self.clf, self.repo, self.enviador = base, classificador, repositorio, enviador
        self.registro = RegistroEnviados(cfg.arquivo_enviados, relatorio)
        self.revisao = []
        self.decisoes = []  # (id, decisão, motivo) para avaliação

    # ---------- saídas ----------
    def _para_revisao(self, oc, motivo, texto_anon="", cat_ia="", conf_ia=None):
        self.rel.contadores["revisao_humana"] += 1
        self.log.info(f"Ocorrência {oc.get('protocolo') or oc.get('id')} -> revisão humana: {motivo}")
        self.revisao.append({"id": oc.get("id"), "protocolo": oc.get("protocolo"), "motivo": motivo,
                             "categoria_final": oc.get("categoria_final"), "categoria_ia": cat_ia,
                             "confianca_ia": None if conf_ia is None else round(conf_ia, 3),
                             "descricao_anonimizada": texto_anon,
                             "registrado_em": datetime.now().isoformat(timespec="seconds")})
        self.decisoes.append((oc.get("id"), "revisao", motivo))

    def _salvar_revisao(self):
        caminho = self.cfg.arquivo_revisao
        novos = pd.DataFrame(self.revisao, columns=COLUNAS_REVISAO)
        try:
            antigos = pd.read_csv(caminho, dtype=str, keep_default_na=False) if caminho.exists() else None
        except Exception as e:  # arquivo corrompido: guarda e recomeça
            self.rel.erro(f"Fila de revisão ilegível ({type(e).__name__}); recriada.")
            antigos = None
        df = novos if antigos is None else pd.concat([antigos, novos.astype(str)], ignore_index=True)
        df = df.drop_duplicates("id", keep="last")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(caminho, index=False, encoding="utf-8-sig")

    def _marcar_status(self, oc, observacao):
        try:
            self.repo.marcar_enviada(oc["id"], observacao)
            self.registro.marcar(oc["id"], status_sincronizado=True)
            return True
        except Exception as e:
            self.rel.erro(f"E-mail de {oc['protocolo']} enviado, mas o status não foi atualizado ({str(e)[:150]}). "
                          "A próxima execução tenta marcar de novo SEM reenviar.")
            self.rel.contadores["status_nao_sincronizado"] += 1
            return False

    # ---------- uma ocorrência ----------
    def processar(self, oc):
        id_oc = oc.get("id")
        if id_oc in self.registro:  # já enviada antes: só sincroniza o status
            self.log.info(f"Ocorrência {oc.get('protocolo')} já foi enviada; apenas atualizando o status.")
            if self._marcar_status(oc, "E-mail já enviado anteriormente (sincronização de status)"):
                self.rel.contadores["status_sincronizado_sem_reenvio"] += 1
            self.decisoes.append((id_oc, "ja_enviada", "sincronização"))
            return

        problemas = validar_ocorrencia(oc, self.base.ids_categorias)
        texto_anon, pii = anonimizar(oc.get("descricao"))
        for tipo, n in pii.items():
            self.rel.contadores[f"dados_pessoais_mascarados_{tipo.lower()}"] += n
        if problemas:
            return self._para_revisao(oc, "dado inválido: " + "; ".join(problemas), texto_anon)

        if self.clf is None:
            return self._para_revisao(oc, "classificador indisponível: conferência da IA não pôde ser feita",
                                      texto_anon)
        cat_ia, conf, segunda, _ = self.clf.prever(texto_anon)
        if cat_ia != oc["categoria_final"]:
            return self._para_revisao(oc, f"divergência: descrição parece '{cat_ia}' ({conf:.0%}), "
                                          f"ocorrência diz '{oc['categoria_final']}'", texto_anon, cat_ia, conf)
        if conf < self.cfg.limiar_confianca:
            return self._para_revisao(oc, f"confiança baixa da IA ({conf:.0%} < {self.cfg.limiar_confianca:.0%}; "
                                          f"2ª opção: {segunda})", texto_anon, cat_ia, conf)

        categoria, responsavel = self.base.roteamento(oc["categoria_final"])
        if oc.get("responsavel_id") and oc["responsavel_id"] != responsavel["id"]:
            return self._para_revisao(oc, f"responsável da ocorrência ({oc['responsavel_id']}) diverge da base "
                                          f"({responsavel['id']})", texto_anon, cat_ia, conf)

        msg = montar_email(self.cfg, oc, texto_anon, categoria, responsavel)
        try:
            self.enviador.enviar(msg)
        except DestinatarioNaoPermitido as e:
            return self._para_revisao(oc, f"envio bloqueado pela trava de segurança: {e}", texto_anon, cat_ia, conf)
        except (CircuitoAberto, FalhaPersistente) as e:
            self.rel.contadores["falha_envio_mantida_pendente"] += 1
            self.log.error(f"Falha no envio de {oc['protocolo']} ({str(e)[:120]}): status mantido como "
                           "pendente_envio para nova tentativa.")
            self.decisoes.append((id_oc, "falha_envio", str(e)[:120]))
            return

        self.rel.contadores["emails_enviados"] += 1
        (self.cfg.dir_emails / f"{oc['protocolo']}.eml").write_bytes(bytes(msg))  # cópia da caixa de saída
        self.registro.marcar(id_oc, protocolo=oc["protocolo"], destinatario=msg["To"],
                             enviado_em=datetime.now().isoformat(timespec="seconds"), status_sincronizado=False)
        self.log.info(f"Enviada {oc['protocolo']} -> {msg['To']} ({categoria['id']}, IA {conf:.0%})")
        self._marcar_status(oc, f"E-mail enviado para caixa de teste: {msg['To']}")
        self.decisoes.append((id_oc, "enviada", responsavel["id"]))

    # ---------- execução ----------
    def executar(self):
        self.cfg.dir_emails.mkdir(parents=True, exist_ok=True)
        try:
            pendentes = self.repo.listar_pendentes()
        except Exception as e:
            self.rel.erro(f"Não foi possível ler as ocorrências pendentes ({str(e)[:160]}): nada enviado.")
            return
        self.rel.contadores["pendentes_lidas"] = len(pendentes)
        self.log.info(f"{len(pendentes)} ocorrência(s) pendente(s) de envio via {self.repo.nome}")
        for oc in pendentes:
            try:
                self.processar(oc)
            except Exception as e:  # nenhum erro inesperado derruba o lote; status não muda
                self.rel.contadores["erros_inesperados"] += 1
                self.rel.erro(f"Erro inesperado na ocorrência {oc.get('id')}: {type(e).__name__}: {e}")
        if self.revisao:
            self._salvar_revisao()
        if self.rel.contadores["falha_envio_mantida_pendente"]:
            self.rel.erro(f"{self.rel.contadores['falha_envio_mantida_pendente']} ocorrência(s) não enviada(s) por "
                          "falha no SMTP; continuam pendente_envio.")
