"""Acesso às ocorrências (CONTRATOS.md, seção E).

Caminho principal: API do Quem Resolve? (GET /ocorrencias?status=pendente_envio e
PATCH /ocorrencias/{id}/status). Caminho seguro: se API_BASE_URL estiver vazia ou a API não
responder, o robô usa o SQLite local (data/quem_resolve.db), que espelha o mesmo modelo de dados.
"""
from datetime import datetime, timezone

import requests

from src.db import conectar
from src.resiliencia import CircuitBreaker, FalhaPersistente, com_retry


class ErroRepositorio(Exception):
    pass


def _agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RepositorioSQLite:
    nome = "SQLite local (reserva)"

    def __init__(self, caminho_db):
        self.caminho_db = caminho_db

    def listar_pendentes(self):
        with conectar(self.caminho_db) as con:
            linhas = con.execute("SELECT * FROM ocorrencia WHERE status = 'pendente_envio' "
                                 "ORDER BY criada_em").fetchall()
        return [{**dict(l), "corrigida_pelo_cidadao": bool(l["corrigida_pelo_cidadao"])} for l in linhas]

    def marcar_enviada(self, id_ocorrencia, observacao):
        with conectar(self.caminho_db) as con:
            cur = con.execute("UPDATE ocorrencia SET status='enviada', observacao_status=?, atualizada_em=? "
                              "WHERE id=? AND status='pendente_envio'", (observacao, _agora(), id_ocorrencia))
        if cur.rowcount == 0:
            raise ErroRepositorio(f"ocorrência {id_ocorrencia} não está mais pendente no SQLite")

    def status_de(self, id_ocorrencia):
        with conectar(self.caminho_db) as con:
            l = con.execute("SELECT status FROM ocorrencia WHERE id=?", (id_ocorrencia,)).fetchone()
        return l["status"] if l else None


class ClienteAPI:
    nome = "API Quem Resolve?"

    def __init__(self, cfg, logger):
        self.cfg, self.log = cfg, logger
        self.base = cfg.api_base_url
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = "QuemResolve-RPA/1.0"
        if cfg.api_token:
            self.sessao.headers["Authorization"] = f"Bearer {cfg.api_token}"
        self.breaker = CircuitBreaker("API Quem Resolve?", cfg.max_falhas_seguidas, logger)

    def _chamar(self, metodo, caminho, **kw):
        def requisicao():
            r = self.sessao.request(metodo, f"{self.base}{caminho}", timeout=self.cfg.timeout_http, **kw)
            r.raise_for_status()
            return r
        try:
            return com_retry(requisicao, tentativas=self.cfg.tentativas, backoff=self.cfg.backoff_segundos,
                             logger=self.log, descricao=f"API {metodo} {caminho}",
                             erros=(requests.RequestException,), breaker=self.breaker)
        except FalhaPersistente as e:
            raise ErroRepositorio(str(e)) from e

    def verificar(self):
        self._chamar("GET", "/health")

    def listar_pendentes(self):
        r = self._chamar("GET", "/ocorrencias", params={"status": "pendente_envio", "limite": 500})
        try:
            dados = r.json()
        except ValueError as e:
            raise ErroRepositorio("API devolveu resposta que não é JSON") from e
        if not isinstance(dados, list):
            raise ErroRepositorio("API devolveu formato inesperado (esperava uma lista de ocorrências)")
        return dados

    def marcar_enviada(self, id_ocorrencia, observacao):
        self._chamar("PATCH", f"/ocorrencias/{id_ocorrencia}/status",
                     json={"status": "enviada", "observacao": observacao})


def obter_repositorio(cfg, logger, relatorio):
    """API se configurada e saudável; senão, SQLite local (caminho seguro, registrado no log)."""
    if cfg.api_base_url:
        api = ClienteAPI(cfg, logger)
        try:
            api.verificar()
            logger.info(f"Usando a API em {cfg.api_base_url}")
            return api
        except Exception as e:
            relatorio.erro(f"API indisponível ({str(e)[:160]}). Usando a reserva SQLite local.")
    else:
        logger.info("API_BASE_URL não configurada: usando o SQLite local (reserva).")
    return RepositorioSQLite(cfg.arquivo_db)
