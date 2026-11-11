"""Tema: NLP + Machine Learning -> TF-IDF (palavras + n-gramas de caracteres) e Regressão Logística.

Leve, gratuito, roda offline e não exige LLM. Usado em dois pontos do fluxo:
  (a) etiquetar cada trecho raspado com a categoria mais provável (metadado do RAG);
  (b) no encaminhamento, conferir se a descrição bate com a categoria da ocorrência.
Os n-gramas de caracteres deixam o modelo tolerante a erros de digitação ("bueru", "lampada").
"""
import re
import unicodedata

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from src.anonimizacao import anonimizar


def normalizar(texto):
    t = str(texto).lower()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\[(nome|cpf|telefone|email)\]", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def criar_pipeline():
    features = FeatureUnion([
        ("palavras", TfidfVectorizer(preprocessor=normalizar, ngram_range=(1, 2), sublinear_tf=True)),
        ("caracteres", TfidfVectorizer(preprocessor=normalizar, analyzer="char_wb",
                                       ngram_range=(3, 5), sublinear_tf=True)),
    ])
    return Pipeline([("features", features), ("clf", LogisticRegression(max_iter=3000, C=20))])


class Classificador:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    @classmethod
    def treinar(cls, df: pd.DataFrame):
        textos = [anonimizar(t)[0] for t in df["texto"]]  # treina no mesmo formato em que vai prever
        pipe = criar_pipeline()
        pipe.fit(textos, df["categoria"])
        return cls(pipe)

    def salvar(self, caminho):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, caminho)

    @classmethod
    def carregar(cls, caminho):
        return cls(joblib.load(caminho))

    @property
    def classes(self):
        return list(self.pipeline.classes_)

    def probabilidades(self, texto):
        return dict(zip(self.pipeline.classes_, self.pipeline.predict_proba([texto])[0]))

    def prever(self, texto):
        """Retorna (categoria, confianca, segunda_categoria, margem)."""
        probs = self.pipeline.predict_proba([texto])[0]
        classes = self.pipeline.classes_
        ordem = probs.argsort()[::-1]
        p1, p2 = probs[ordem[0]], probs[ordem[1]]
        return classes[ordem[0]], float(p1), classes[ordem[1]], float(p1 - p2)

    def prever_lote(self, textos):
        probs = self.pipeline.predict_proba(list(textos))
        classes = self.pipeline.classes_
        idx = probs.argmax(axis=1)
        return [(classes[i], float(p[i])) for i, p in zip(idx, probs)]
