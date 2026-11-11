"""Base "Quem resolve o quê" (RF32): carrega e valida data/base_quem_resolve.json."""
import json


class BaseInvalida(Exception):
    pass


CAMPOS_CATEGORIA = ["id", "nome", "responsavel_id", "canal", "emergencia", "fonte_url", "status_fonte"]
CAMPOS_RESPONSAVEL = ["id", "nome", "canal", "contato", "url", "email_teste"]


class BaseQuemResolve:
    def __init__(self, dados):
        self.dados = dados
        self.categorias = {c["id"]: c for c in dados["categorias"]}
        self.responsaveis = {r["id"]: r for r in dados["responsaveis"]}

    @classmethod
    def carregar(cls, caminho):
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise BaseInvalida(f"arquivo {caminho.name} não encontrado") from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise BaseInvalida(f"{caminho.name} corrompido: {e}") from e
        erros = []
        for c in dados.get("categorias", []):
            erros += [f"categoria {c.get('id')}: falta '{k}'" for k in CAMPOS_CATEGORIA if k not in c]
            if c.get("emergencia") not in ("sim", "nao", "depende"):
                erros.append(f"categoria {c.get('id')}: emergencia inválida")
        for r in dados.get("responsaveis", []):
            erros += [f"responsável {r.get('id')}: falta '{k}'" for k in CAMPOS_RESPONSAVEL if k not in r]
        ids_resp = {r.get("id") for r in dados.get("responsaveis", [])}
        erros += [f"categoria {c['id']}: responsável '{c['responsavel_id']}' não existe"
                  for c in dados.get("categorias", []) if c.get("responsavel_id") not in ids_resp]
        if not dados.get("categorias"):
            erros.append("nenhuma categoria")
        if erros:
            raise BaseInvalida("; ".join(erros[:5]))
        return cls(dados)

    @property
    def ids_categorias(self):
        return list(self.categorias)

    def roteamento(self, categoria_id):
        """Retorna (categoria, responsavel) ou None se a categoria não existir."""
        cat = self.categorias.get(categoria_id)
        if not cat:
            return None
        return cat, self.responsaveis[cat["responsavel_id"]]
