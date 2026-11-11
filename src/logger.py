"""Log em arquivo (logs/robo_AAAAMMDD.log) e na tela."""
import logging
import sys
from datetime import datetime


def configurar_logger(dir_logs, nome="quem_resolve_rpa"):
    # Console do Windows usa cp1252: evita erro de codificação com acentos e símbolos
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    dir_logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(nome)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
    arq = logging.FileHandler(dir_logs / f"robo_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    arq.setFormatter(fmt)
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(fmt)
    logger.addHandler(arq)
    logger.addHandler(tela)
    return logger
