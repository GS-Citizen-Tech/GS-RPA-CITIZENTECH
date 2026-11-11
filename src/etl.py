"""Tema: Pandas/ETL (RF31) -> limpa e normaliza os textos raspados, quebra em trechos (chunks)
prontos para o RAG, etiqueta cada trecho com a IA e grava em JSONL + tabela SQL documento_base.
"""
import hashlib
import json
import re
import unicodedata

import pandas as pd

from src.db import conectar

RUIDO = [r"\(link direciona para portal externo\)", r"\(abre em nova (guia|aba)\)", r"\bportable_wifi_off\b",
         r"\bchevron_right\b", r"\bexpand_more\b", r"\block\b(?= Anônimo)"]


def limpar_texto(t):
    t = unicodedata.normalize("NFC", str(t))
    t = re.sub(r"[​-‏‪-‮⁠﻿\xad]", "", t)  # caracteres invisíveis
    for padrao in RUIDO:
        t = re.sub(padrao, " ", t)
    t = re.sub(r"\s+([.;,:)])", r"\1", t)   # "Subprefeituras ;" -> "Subprefeituras;"
    t = re.sub(r"(^|\s)-\s+", r"\1• ", t)    # marcadores de lista soltos
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"[“”]\s*", '"', t)
    return re.sub(r"\s+", " ", t).strip(" ;")


def quebrar(texto, limite):
    """Quebra em trechos de até `limite` caracteres respeitando o fim das frases."""
    if len(texto) <= limite:
        return [texto]
    frases = re.split(r"(?<=[.;!?])\s+", texto)
    trechos, atual = [], ""
    for f in frases:
        while len(f) > limite:  # frase gigante: corte duro
            if atual:
                trechos.append(atual)
                atual = ""
            trechos.append(f[:limite])
            f = f[limite:]
        if len(atual) + len(f) + 1 > limite and atual:
            trechos.append(atual)
            atual = f
        else:
            atual = f"{atual} {f}".strip()
    if atual:
        trechos.append(atual)
    return trechos


def id_trecho(url, secao, texto):
    return hashlib.sha1(f"{url}|{secao}|{texto}".encode("utf-8")).hexdigest()[:12]


def transformar(registros, limite_chunk, min_caracteres=25):
    """registros brutos -> DataFrame de trechos limpos, sem duplicatas."""
    df = pd.DataFrame(registros, columns=["fonte_id", "titulo", "url", "secao", "texto", "origem", "coletado_em"])
    if df.empty:
        return df.assign(id=[], n_caracteres=[])
    brutos = len(df)
    df["secao"] = df["secao"].map(limpar_texto)
    df["texto"] = df["texto"].map(limpar_texto)
    df["texto"] = df["texto"].map(lambda t: quebrar(t, limite_chunk))
    df = df.explode("texto", ignore_index=True)
    df = df[df["texto"].str.len() >= min_caracteres]
    df = df.drop_duplicates(subset=["fonte_id", "texto"]).reset_index(drop=True)
    df["n_caracteres"] = df["texto"].str.len()
    df["id"] = [id_trecho(u, s, t) for u, s, t in zip(df["url"], df["secao"], df["texto"])]
    df.attrs["registros_brutos"] = brutos
    return df


def etiquetar(df, classificador, limiar):
    """(a) Metadado do RAG: categoria mais provável do trecho; abaixo do limiar vira 'geral'."""
    if df.empty or classificador is None:
        return df.assign(categoria_ia="geral", confianca_ia=0.0)
    entradas = (df["titulo"] + ". " + df["secao"] + ". " + df["texto"]).tolist()
    previsoes = classificador.prever_lote(entradas)
    df["categoria_ia"] = [c if p >= limiar else "geral" for c, p in previsoes]
    df["confianca_ia"] = [round(p, 3) for _, p in previsoes]
    return df


def carregar(df, caminho_jsonl, caminho_db):
    """Grava JSONL (escrita atômica) e espelha na tabela documento_base."""
    caminho_jsonl.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho_jsonl.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in df.to_dict("records"):
            f.write(json.dumps({
                "id": r["id"], "texto": r["texto"],
                "metadados": {"fonte_id": r["fonte_id"], "titulo": r["titulo"], "url": r["url"],
                              "secao": r["secao"], "categoria": r["categoria_ia"],
                              "confianca_categoria": r["confianca_ia"], "origem": r["origem"],
                              "coletado_em": r["coletado_em"]}}, ensure_ascii=False) + "\n")
    tmp.replace(caminho_jsonl)
    with conectar(caminho_db) as con:
        con.execute("DELETE FROM documento_base")
        con.executemany(
            "INSERT INTO documento_base VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(r["id"], r["fonte_id"], r["url"], r["titulo"], r["secao"], r["texto"], int(r["n_caracteres"]),
              r["origem"], r["coletado_em"], r["categoria_ia"], float(r["confianca_ia"]))
             for r in df.to_dict("records")])
