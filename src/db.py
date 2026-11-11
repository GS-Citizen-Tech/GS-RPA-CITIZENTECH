"""Tema: SQL -> banco SQLite local que espelha o modelo de dados do PRD (seção 10).

Tabelas: categoria, responsavel, regra_roteamento, documento_base (trechos raspados para o RAG)
e ocorrencia (reserva quando a API não está disponível).
"""
import sqlite3
from contextlib import contextmanager

ESQUEMA = """
CREATE TABLE IF NOT EXISTS responsavel (
    id TEXT PRIMARY KEY, nome TEXT NOT NULL, canal TEXT, contato TEXT, url TEXT, email_teste TEXT);
CREATE TABLE IF NOT EXISTS categoria (
    id TEXT PRIMARY KEY, nome TEXT NOT NULL, emergencia TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS regra_roteamento (
    categoria_id TEXT NOT NULL REFERENCES categoria(id),
    responsavel_id TEXT NOT NULL REFERENCES responsavel(id),
    observacao TEXT, fonte_url TEXT, status_fonte TEXT, validado_em TEXT,
    PRIMARY KEY (categoria_id, responsavel_id));
CREATE TABLE IF NOT EXISTS documento_base (
    id TEXT PRIMARY KEY, fonte_id TEXT, fonte_url TEXT, titulo TEXT, secao TEXT, conteudo TEXT,
    n_caracteres INTEGER, origem TEXT, coletado_em TEXT, categoria_ia TEXT, confianca_ia REAL);
CREATE TABLE IF NOT EXISTS ocorrencia (
    id TEXT PRIMARY KEY, protocolo TEXT, criada_em TEXT, descricao TEXT, lat REAL, lon REAL,
    categoria_sugerida TEXT, confianca REAL, categoria_final TEXT, responsavel_id TEXT,
    corrigida_pelo_cidadao INTEGER, status TEXT NOT NULL, prioridade INTEGER, origem TEXT,
    grupo_duplicata_id TEXT, foto_url TEXT, observacao_status TEXT, atualizada_em TEXT);
CREATE INDEX IF NOT EXISTS ix_ocorrencia_status ON ocorrencia(status);
"""

COLUNAS_OCORRENCIA = ["id", "protocolo", "criada_em", "descricao", "lat", "lon", "categoria_sugerida",
                      "confianca", "categoria_final", "responsavel_id", "corrigida_pelo_cidadao", "status",
                      "prioridade", "origem", "grupo_duplicata_id", "foto_url"]


@contextmanager
def conectar(caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def gravar_base_quem_resolve(caminho_db, base):
    """Espelha data/base_quem_resolve.json nas tabelas categoria/responsavel/regra_roteamento."""
    with conectar(caminho_db) as con:
        con.execute("DELETE FROM regra_roteamento")
        con.executemany("INSERT OR REPLACE INTO responsavel VALUES (?,?,?,?,?,?)",
                        [(r["id"], r["nome"], r["canal"], r["contato"], r["url"], r["email_teste"])
                         for r in base.responsaveis.values()])
        con.executemany("INSERT OR REPLACE INTO categoria VALUES (?,?,?)",
                        [(c["id"], c["nome"], c["emergencia"]) for c in base.categorias.values()])
        regras = []
        for c in base.categorias.values():
            for resp in [c["responsavel_id"], *c.get("outros_responsaveis", [])]:
                regras.append((c["id"], resp, c.get("observacao", ""), c["fonte_url"], c["status_fonte"],
                               base.dados.get("atualizado_em") if c["fonte_url"] else None))
        con.executemany("INSERT OR REPLACE INTO regra_roteamento VALUES (?,?,?,?,?,?)", regras)
    return len(regras)
