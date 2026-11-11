"""Evidências de validação -> gera docs/RESULTADOS_AVALIACAO.md (todos os números são medidos aqui).

1. Classificador no conjunto de teste rotulado (frases diferentes das de treino)
2. Anonimização dos dados pessoais fictícios
3. Encaminhamento ponta a ponta (via API simulada + SMTP de teste embutido) x gabarito
4. Etiquetagem dos trechos raspados x amostra rotulada (data/amostra_docs_rotulada.csv)

Uso: python avaliar.py   (depois de python main.py tudo)
"""
import email
import json
import re
import shutil
from collections import Counter
from email import policy
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix

from src.anonimizacao import PADROES, anonimizar
from src.base_quem_resolve import BaseQuemResolve
from src.classificador import Classificador
from src.config import Config
from src.db import conectar
from src.logger import configurar_logger

RAIZ = Path(__file__).resolve().parent
cfg = Config()
log = configurar_logger(cfg.dir_logs, nome="avaliar")
out = []
pct = lambda x: f"{x:.1%}".replace(".", ",")
dec = lambda x: f"{x:.2f}".replace(".", ",")

PARES_EXPLICADOS = {
    frozenset({"arvore_poda_queda", "arvore_sobre_fiacao"}): "as duas falam de árvore e galho; só a menção a fio/cabo separa",
    frozenset({"poste_danificado", "iluminacao_publica"}): "ambas citam 'poste' e 'luz'",
    frozenset({"esgoto", "vazamento_agua"}): "ambas descrevem água escorrendo na rua; o que separa é 'limpa' x 'suja/fedor'",
    frozenset({"fio_energia_caido", "fiacao_telecom_solta"}): "fio/cabo caído: o modelo precisa de pistas como 'faísca' ou 'internet'",
    frozenset({"boca_de_lobo_entupida", "alagamento"}): "bueiro entupido costuma vir junto com rua alagada",
    frozenset({"lixo_acumulado", "coleta_nao_realizada"}): "lixo parado na rua pode ser falta de coleta ou acúmulo",
    frozenset({"lixo_acumulado", "descarte_irregular"}): "'lixo jogado' x 'entulho jogado' é uma fronteira fina",
    frozenset({"lixeira_publica", "lixo_acumulado"}): "lixeira transbordando também é lixo acumulado",
    frozenset({"boca_de_lobo_entupida", "lixo_acumulado"}): "bueiro 'tampado de lixo' mistura as duas",
    frozenset({"arvore_poda_queda", "veiculo_abandonado"}): "'galho caiu em cima de um carro': a palavra 'carro' puxa para veículo",
    frozenset({"calcada_quebrada", "lixo_acumulado"}): "o lixo está 'na calçada': a palavra calçada pesa demais",
    frozenset({"calcada_quebrada", "lixeira_publica"}): "'cesto de lixo da calçada amassado' tem vocabulário de calçada",
    frozenset({"alagamento", "vazamento_agua"}): "'água subiu/entrou nas casas' sem a palavra chuva lembra vazamento",
    frozenset({"alagamento", "veiculo_abandonado"}): "'carro boiando' traz a palavra carro",
}

# =============================================================================================
# 1. Classificador
# =============================================================================================
teste = pd.read_csv(cfg.arquivo_teste, keep_default_na=False)
clf = Classificador.carregar(cfg.caminho_modelo)
n_treino = len(pd.read_csv(cfg.arquivo_treino))
prev = [clf.prever(anonimizar(t)[0]) for t in teste["texto"]]
teste["previsto"], teste["confianca"] = [p[0] for p in prev], [p[1] for p in prev]
acertou = teste["previsto"] == teste["categoria"]
n, ncat = len(teste), teste["categoria"].nunique()
out += ["# Resultados da avaliação", "",
        "> Arquivo gerado por `python avaliar.py`. Todos os números abaixo foram medidos nesta execução, "
        "com dados **sintéticos** (ver limites no fim).", "",
        "## 1. Classificador de categorias (TF-IDF + Regressão Logística)", "",
        f"- Treino: **{n_treino}** frases sintéticas ({n_treino // ncat} por categoria).",
        f"- Teste: **{n}** frases ({n // ncat} por categoria, {ncat} categorias), escritas com **modelos de frase "
        "diferentes** dos de treino, com erros de digitação, caixa alta e dados pessoais fictícios.",
        f"- **Acurácia geral: {pct(acertou.mean())}** ({acertou.sum()}/{n} acertos).", ""]
rep = classification_report(teste["categoria"], teste["previsto"], output_dict=True, zero_division=0)
out += ["| Categoria | Precisão | Recall | F1 | Amostras |", "|---|---|---|---|---|"]
out += [f"| {c} | {dec(v['precision'])} | {dec(v['recall'])} | {dec(v['f1-score'])} | {int(v['support'])} |"
        for c, v in rep.items() if c not in ("accuracy", "macro avg", "weighted avg")]
m = rep["macro avg"]
out += [f"| **média (macro)** | **{dec(m['precision'])}** | **{dec(m['recall'])}** | **{dec(m['f1-score'])}** | {n} |"]

out += ["", "### Limiar de confiança x % automatizado x acerto", "",
        "Se o robô só aceitasse a categoria da IA acima do limiar (o resto iria para revisão humana):", "",
        "| Limiar | % automatizado | Acerto do que foi automatizado | Erros que passariam |", "|---|---|---|---|"]
for lim in [0.0, 0.30, 0.40, 0.50, 0.60, 0.70]:
    auto = teste["confianca"] >= lim
    marca = " **(usado)**" if abs(lim - cfg.limiar_confianca) < 1e-9 else ""
    out.append(f"| {dec(lim)}{marca} | {pct(auto.mean())} | {pct(acertou[auto].mean()) if auto.any() else '-'} | "
               f"{(~acertou[auto]).sum()} |")

erros = teste[~acertou]
pares = Counter(frozenset({a, b}) for a, b in zip(erros["categoria"], erros["previsto"]))
out += ["", "### Análise dos erros", "", f"{len(erros)} erros. Pares de categorias mais confundidos:", "",
        "| Par confundido | Erros | Por que confunde |", "|---|---|---|"]
for par, q in pares.most_common(8):
    out.append(f"| {' x '.join(sorted(par))} | {q} | {PARES_EXPLICADOS.get(par, '-')} |")
out += ["", "Exemplos de erros (texto já anonimizado):", "",
        "| Texto | Esperado | Previsto | Confiança |", "|---|---|---|---|"]
for r in erros.sort_values("confianca", ascending=False).head(12).itertuples():
    t = anonimizar(r.texto)[0].replace("|", "/")[:95]
    out.append(f"| {t} | {r.categoria} | {r.previsto} | {r.confianca:.0%} |")
altos = (erros["confianca"] >= cfg.limiar_confianca).sum()
out += ["", f"Dos {len(erros)} erros, **{altos}** tiveram confiança ≥ {cfg.limiar_confianca:.0%}: são os que o "
        "limiar sozinho não segura. No encaminhamento há uma segunda trava: a IA precisa **concordar** com a "
        "categoria escolhida pelo cidadão (seção 3)."]

cm = confusion_matrix(teste["categoria"], teste["previsto"], labels=clf.classes)
fig, ax = plt.subplots(figsize=(12, 11))
ConfusionMatrixDisplay(cm, display_labels=[c[:16] for c in clf.classes]).plot(ax=ax, xticks_rotation=90, colorbar=False)
ax.set_title("Matriz de confusão - conjunto de teste")
plt.tight_layout()
plt.savefig(RAIZ / "docs" / "matriz_confusao.png", dpi=110)
out += ["", "![Matriz de confusão](matriz_confusao.png)"]

# =============================================================================================
# 2. Anonimização
# =============================================================================================
total, vazou, por_tipo = 0, [], Counter()
for r in teste.itertuples():
    mascarado = anonimizar(r.texto)[0].lower()
    for campo in ("nome", "cpf", "telefone", "email"):
        valor = str(getattr(r, campo) or "")
        if valor:
            total += 1
            por_tipo[campo] += 1
            if valor.lower() in mascarado:
                vazou.append((campo, mascarado[:90]))
out += ["", "## 2. Anonimização de dados pessoais", "",
        f"- Dados pessoais fictícios inseridos nos {n} textos de teste: **{total}** "
        f"({', '.join(f'{k}: {v}' for k, v in sorted(por_tipo.items()))})",
        f"- **Taxa de mascaramento: {pct((total - len(vazou)) / max(total, 1))}** ({total - len(vazou)}/{total})"]
out += [f"- Vazou: {c} em \"{t}\"" for c, t in vazou]
out += ["- Limite conhecido: nome só é detectado depois de gatilhos (\"meu nome é\", \"sou\", \"me chamo\", "
        "\"aqui é o/a\"). Nome solto no meio da frase não é detectado.",
        "- Um número de 11 dígitos sem pontuação (ex.: celular `119...`) é marcado como [CPF] em vez de [TELEFONE]: "
        "continua mascarado, só o rótulo fica impreciso."]

# =============================================================================================
# 3. Encaminhamento ponta a ponta (isolado, via API simulada + SMTP embutido)
# =============================================================================================
import gerar_dados
from src.email_envio import EnviadorEmail
from src.encaminhador import Encaminhador
from src.mock_api import MockAPI
from src.relatorio import Relatorio
from src.repositorio import RepositorioSQLite, obter_repositorio
from src.smtp_local import SMTPLocal

dir_e2e = RAIZ / "avaliacao_execucao"
shutil.rmtree(dir_e2e, ignore_errors=True)
(dir_e2e / "data").mkdir(parents=True)
shutil.copy(cfg.arquivo_base, dir_e2e / "data" / "base_quem_resolve.json")
c2 = Config(base=dir_e2e, smtp_porta=1026, backoff_segundos=0.1, caminho_modelo=cfg.caminho_modelo)
c2.criar_pastas()
gerar_dados.main(c2.dir_data, c2.arquivo_db)
gab = pd.read_csv(c2.arquivo_gabarito)
base = BaseQuemResolve.carregar(c2.arquivo_base)


def rodar_encaminhamento(api_url):
    c2.api_base_url = api_url
    rel = Relatorio("encaminhar_avaliacao", log)
    repo = obter_repositorio(c2, log, rel)
    enc = Encaminhador(c2, log, rel, base, clf, repo, EnviadorEmail(c2, log))
    enc.executar()
    return rel, enc, repo


with SMTPLocal(dir_e2e / "caixa_teste", "localhost", 1026) as smtp, MockAPI(c2.arquivo_db, porta=0) as api:
    rel1, enc1, repo1 = rodar_encaminhamento(api.url)
    recebidos_1 = smtp.recebidos
    rel2, enc2, _ = rodar_encaminhamento(api.url)  # reexecução: deve enviar 0
    recebidos_2 = smtp.recebidos - recebidos_1

decisoes = pd.DataFrame(enc1.decisoes, columns=["id", "decisao", "detalhe"])
mm = gab.merge(decisoes, on="id", how="left")
mm["decisao"] = mm["decisao"].fillna("nao_listada")
sqlite = RepositorioSQLite(c2.arquivo_db)
mm["status_final"] = [sqlite.status_de(i) for i in mm["id"]]
esp_env = mm[mm["decisao_esperada"] == "enviar"]
enviadas = mm[mm["decisao"] == "enviada"]
envio_errado = enviadas[enviadas["decisao_esperada"] != "enviar"]
resp_certo = (enviadas["detalhe"] == enviadas["responsavel_esperado"]).sum()
esp_rev = mm[mm["decisao_esperada"] == "revisao"]
ign = mm[mm["decisao_esperada"] == "ignorar"]

# Vazamento de dados pessoais nos e-mails efetivamente recebidos
vazamentos = 0
for eml in (dir_e2e / "caixa_teste").glob("*.eml"):
    corpo = email.message_from_bytes(eml.read_bytes(), policy=policy.default).get_body().get_content()
    descricao = corpo.split("(dados pessoais mascarados):", 1)[-1].split("\n\n")[0]
    vazamentos += sum(bool(p.search(descricao)) for _, p in PADROES)

out += ["", "## 3. Encaminhamento ponta a ponta (RF33) x gabarito", "",
        f"Execução isolada em `avaliacao_execucao/`: **{len(gab)} ocorrências simuladas** lidas pela **API simulada** "
        "(mesmo contrato de `CONTRATOS.md`, seção E), e-mails entregues a um SMTP de teste embutido.", "",
        "| Grupo do gabarito | Qtde | Resultado do robô |", "|---|---|---|",
        f"| Válidas com categoria correta (esperado: enviar) | {len(esp_env)} | "
        f"{(esp_env['decisao'] == 'enviada').sum()} enviadas, {(esp_env['decisao'] == 'revisao').sum()} para revisão humana |",
        f"| Categoria final errada (esperado: revisão) | {(esp_rev['observacao'].str.startswith('categoria')).sum()} | "
        f"{(esp_rev[esp_rev['observacao'].str.startswith('categoria')]['decisao'] == 'revisao').sum()} barradas na revisão |",
        f"| Dados inválidos (esperado: revisão) | {(esp_rev['observacao'].str.startswith('inválida')).sum()} | "
        f"{(esp_rev[esp_rev['observacao'].str.startswith('inválida')]['decisao'] == 'revisao').sum()} barradas na revisão |",
        f"| Já enviadas antes (esperado: ignorar) | {len(ign)} | {(ign['decisao'] == 'nao_listada').sum()} ignoradas "
        "(não vêm na lista de pendentes) |", "",
        f"- **Envios errados (ocorrência enviada que deveria ir para revisão): {len(envio_errado)}**",
        f"- Enviadas para o responsável correto: **{resp_certo}/{len(enviadas)}**",
        f"- Taxa de automação das válidas: **{pct((esp_env['decisao'] == 'enviada').mean())}**; o resto foi para "
        "revisão por divergência ou confiança baixa da IA (falso alarme: custa tempo de um atendente, não um envio errado).",
        f"- E-mails recebidos pelo SMTP de teste: **{recebidos_1}**; status `enviada` gravado via API (PATCH): "
        f"**{(mm.loc[mm['decisao'] == 'enviada', 'status_final'] == 'enviada').sum()}/{len(enviadas)}**",
        f"- Dados pessoais encontrados no texto dos e-mails enviados: **{vazamentos}**",
        f"- **Reexecução (idempotência):** 2ª rodada leu {rel2.contadores['pendentes_lidas']} pendentes "
        f"e enviou **{recebidos_2}** e-mails.", ""]
motivos = Counter(re.match(r"[^:(]+", d).group(0).strip() for _, decisao, d in enc1.decisoes if decisao == "revisao")
out += ["Motivos da revisão humana: " + ", ".join(f"{k} ({v})" for k, v in motivos.most_common()), ""]

# Limiar no encaminhamento (regra: IA concorda com a categoria E confiança >= limiar)
with conectar(c2.arquivo_db) as con:
    todas = pd.read_sql_query("SELECT id, descricao FROM ocorrencia", con)
avaliaveis = gab.merge(todas, on="id")
avaliaveis = avaliaveis[avaliaveis["decisao_esperada"].isin(["enviar"]) |
                        avaliaveis["observacao"].str.startswith("categoria")]
pv = [clf.prever(anonimizar(t)[0]) for t in avaliaveis["descricao"]]
avaliaveis["ia"], avaliaveis["conf"] = [p[0] for p in pv], [p[1] for p in pv]
out += ["Mesma regra de decisão com outros limiares (válidas + categoria errada; inválidas são barradas pela validação):", "",
        "| Limiar | Válidas enviadas | Categoria errada enviada (erro grave) |", "|---|---|---|"]
for lim in [0.0, 0.30, 0.40, 0.50, 0.60]:
    envia = (avaliaveis["ia"] == avaliaveis["categoria_final"]) & (avaliaveis["conf"] >= lim)
    ok = avaliaveis["decisao_esperada"] == "enviar"
    marca = " **(usado)**" if abs(lim - cfg.limiar_confianca) < 1e-9 else ""
    out.append(f"| {dec(lim)}{marca} | {(envia & ok).sum()}/{ok.sum()} ({pct((envia & ok).sum() / ok.sum())}) | "
               f"{(envia & ~ok).sum()}/{(~ok).sum()} |")

# =============================================================================================
# 4. Etiquetagem dos trechos raspados
# =============================================================================================
out += ["", "## 4. Etiquetagem dos trechos raspados (metadado do RAG)", ""]
amostra_path = cfg.dir_data / "amostra_docs_rotulada.csv"
if amostra_path.exists() and cfg.arquivo_conhecimento.exists():
    amostra = pd.read_csv(amostra_path, keep_default_na=False)
    kb = pd.DataFrame([{"id": d["id"], "categoria_ia": d["metadados"]["categoria"],
                        "confianca": d["metadados"]["confianca_categoria"]}
                       for d in map(json.loads, cfg.arquivo_conhecimento.read_text(encoding="utf-8").splitlines())])
    total_kb = len(kb)
    j = amostra.merge(kb, on="id", how="left")
    achados = j[j["categoria_ia"].notna()]
    certo = achados["categoria_ia"] == achados["categoria_rotulada"]
    out += [f"- Base de conhecimento atual: **{total_kb} trechos**; "
            f"{(kb['categoria_ia'] != 'geral').sum()} com categoria e {(kb['categoria_ia'] == 'geral').sum()} como `geral` "
            f"(confiança < {cfg.limiar_etiqueta_docs:.0%}).",
            f"- Amostra rotulada: **{len(amostra)} trechos** (`data/amostra_docs_rotulada.csv`); encontrados na base "
            f"atual: {len(achados)}.",
            f"- **Acerto da etiqueta: {pct(certo.mean()) if len(achados) else '-'}** ({certo.sum()}/{len(achados)}).",
            "- Regra de rótulo: a categoria do assunto do trecho no contexto da página; `geral` quando o trecho não "
            "trata de nenhuma das 20 categorias.", ""]
    if (~certo).any():
        out += ["| Trecho | Rótulo | IA | Confiança |", "|---|---|---|---|"]
        out += [f"| {r.trecho[:80].replace('|', '/')} | {r.categoria_rotulada} | {r.categoria_ia} | {r.confianca:.0%} |"
                for r in achados[~certo].itertuples()]
    if len(achados) < len(amostra):
        out += ["", f"- {len(amostra) - len(achados)} trecho(s) da amostra não existem mais na base (o site mudou "
                "o texto e o id do trecho mudou): rotule de novo."]
    rot_por = amostra["rotulado_por"].iloc[0] if "rotulado_por" in amostra else ""
    if "CONFERIR" in str(rot_por).upper():
        out += ["", "> ⚠️ Os rótulos da amostra ainda são um **rascunho** e precisam ser conferidos por uma pessoa."]
else:
    out += ["- Amostra rotulada ou base de conhecimento ausente: rode `python main.py coletar`."]

out += ["", "## Limites desta avaliação", "",
        "- Todos os textos de cidadão são **sintéticos**, escritos a partir de modelos de frase. Textos reais são mais "
        "variados: a acurácia real tende a ser menor e o modelo deve ser retreinado com dados reais anonimizados.",
        "- O conjunto de teste usa modelos de frase diferentes dos de treino, mas o vocabulário de cada categoria é "
        "parecido; isso mede generalização de forma limitada.",
        "- A amostra de trechos raspados tem só 30 itens, rotulados por uma pessoa: serve como evidência, não como "
        "estimativa estatística precisa."]

(RAIZ / "docs" / "RESULTADOS_AVALIACAO.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
