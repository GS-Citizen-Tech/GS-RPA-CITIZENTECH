"""Tema: expressões regulares -> mascaramento de dados pessoais (LGPD) ANTES de qualquer uso do texto.

A descrição da ocorrência é texto livre do cidadão e pode trazer nome, CPF, telefone ou e-mail.
O e-mail enviado ao órgão, a fila de revisão e os logs só recebem o texto mascarado.
"""
import re

MAIUSC = "A-ZÁÉÍÓÚÂÊÔÃÕÇ"
MINUSC = "a-záéíóúâêôãõç"

PADROES = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("CPF", re.compile(r"(?<!\d)\d{3}\.?\s?\d{3}\.?\s?\d{3}\s?-?\s?\d{2}(?!\d)")),
    ("TELEFONE", re.compile(r"(?<!\d)(?:\+?55\s?)?(?:\(?\d{2}\)?[\s-]?)?9?\d{4}[-\s]?\d{4}(?!\d)")),
]
PALAVRA = r"[^\W\d_]+"
# 1) Gatilhos fortes ("meu nome é", "me chamo", "aqui é o/a"): até 4 palavras, terminando em pontuação
NOME_GATILHO_FORTE = re.compile(
    rf"(?i)\b(meu nome (?:[ée]|eh)|me chamo|aqui (?:[ée]|eh) (?:o|a))\s+({PALAVRA}(?:\s+{PALAVRA}){{0,3}})"
    rf"(?=\s*[.,;!?]|$)")
# 2) "sou Fulano" com nome em maiúscula inicial ou TODO EM MAIÚSCULAS
NOME_CAPITALIZADO = re.compile(
    rf"\b([Ss]ou|SOU|[Mm]eu nome [ée]|MEU NOME [ÉE]|[Mm]e chamo|ME CHAMO|[Aa]ss\.?|[Aa]tt\.?)\s+"
    rf"((?:[{MAIUSC}][{MINUSC}]+|[{MAIUSC}]{{2,}})(?:\s+(?:d[aeo]s?\s+|D[AEO]S?\s+)?"
    rf"(?:[{MAIUSC}][{MINUSC}]+|[{MAIUSC}]{{2,}}))*)")
# 3) "sou fulano de tal, cpf ..." em minúsculas
NOME_ANTES_CPF = re.compile(rf"(?i)\b(sou)\s+({PALAVRA}(?:\s+{PALAVRA}){{0,3}})(?=\s*,?\s*(?:cpf|\[CPF\]))")
PADROES_NOME = [NOME_GATILHO_FORTE, NOME_CAPITALIZADO, NOME_ANTES_CPF]


def anonimizar(texto):
    """Retorna (texto_mascarado, contagem_por_tipo)."""
    texto = "" if texto is None else str(texto)
    contagem = {}
    for tipo, padrao in PADROES:
        texto, n = padrao.subn(f"[{tipo}]", texto)
        if n:
            contagem[tipo] = n
    total_nomes = 0
    for padrao in PADROES_NOME:
        texto, n = padrao.subn(lambda m: f"{m.group(1)} [NOME]", texto)
        total_nomes += n
    if total_nomes:
        contagem["NOME"] = total_nomes
    return texto, contagem
