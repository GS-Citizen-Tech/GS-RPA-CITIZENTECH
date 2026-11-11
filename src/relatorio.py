"""Relatório de execução (.md e .json em output/) com contadores e ocorrências (avisos e erros)."""
import json
from collections import Counter
from datetime import datetime


class Relatorio:
    def __init__(self, etapa, logger):
        self.etapa, self.log = etapa, logger
        self.inicio = datetime.now()
        self.contadores = Counter()
        self.ocorrencias = []
        self.extras = {}

    def aviso(self, msg):
        self.log.warning(msg)
        self.ocorrencias.append({"nivel": "AVISO", "mensagem": msg})

    def erro(self, msg):
        self.log.error(msg)
        self.ocorrencias.append({"nivel": "ERRO", "mensagem": msg})

    def como_dict(self):
        return {"etapa": self.etapa, "inicio": self.inicio.isoformat(timespec="seconds"),
                "duracao_segundos": round((datetime.now() - self.inicio).total_seconds(), 2),
                **dict(self.contadores), **self.extras, "ocorrencias": self.ocorrencias}

    def salvar(self, dir_saida):
        dir_saida.mkdir(parents=True, exist_ok=True)
        dados = self.como_dict()
        nome = dir_saida / f"relatorio_{self.etapa}_{self.inicio:%Y%m%d_%H%M%S}"
        nome.with_suffix(".json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        linhas = [f"# Relatório de execução: {self.etapa} ({dados['inicio']})", ""]
        linhas += [f"- **{k.replace('_', ' ')}**: {v}" for k, v in dados.items()
                   if k not in ("ocorrencias", "etapa", "inicio") and not isinstance(v, list)]
        linhas += ["", "## Ocorrências"]
        linhas += [f"- [{o['nivel']}] {o['mensagem']}" for o in self.ocorrencias] or ["- nenhuma"]
        nome.with_suffix(".md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return dados
