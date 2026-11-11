"""Validação da ocorrência recebida (formato de CONTRATOS.md, seção E).

Erro bloqueante -> a ocorrência não é enviada e vai para a revisão humana com o motivo.
"""
import uuid

STATUS_VALIDOS = {"pendente_envio", "enviada", "possivelmente_resolvida", "resolvida"}
ORIGENS_VALIDAS = {"cidadao", "frota", "ambos"}


def _uuid_valido(valor):
    try:
        uuid.UUID(str(valor))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def validar_ocorrencia(oc, ids_categorias):
    """Retorna a lista de problemas bloqueantes (vazia = válida)."""
    problemas = []
    if not _uuid_valido(oc.get("id")):
        problemas.append("id ausente ou não é UUID")
    descricao = str(oc.get("descricao") or "").strip()
    if len(descricao) < 5:
        problemas.append("descrição vazia ou com menos de 5 caracteres")
    elif len(descricao) > 1000:
        problemas.append("descrição com mais de 1000 caracteres")
    if oc.get("categoria_final") not in ids_categorias:
        problemas.append(f"categoria_final desconhecida: {oc.get('categoria_final')!r}")
    if oc.get("status") not in STATUS_VALIDOS:
        problemas.append(f"status inválido: {oc.get('status')!r}")
    if oc.get("origem") not in ORIGENS_VALIDAS:
        problemas.append(f"origem inválida: {oc.get('origem')!r}")
    try:
        p = int(oc.get("prioridade"))
        if not 1 <= p <= 5:
            raise ValueError
    except (TypeError, ValueError):
        problemas.append(f"prioridade fora de 1 a 5: {oc.get('prioridade')!r}")
    if not str(oc.get("protocolo") or "").strip():
        problemas.append("protocolo ausente")
    return problemas
