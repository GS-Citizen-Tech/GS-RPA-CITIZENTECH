"""Tema: resiliência -> retry com espera exponencial e circuit breaker, reaproveitados por
scraping, API e SMTP. Nenhuma falha previsível derruba o robô: quem chama decide o caminho seguro.
"""
import time


class CircuitoAberto(Exception):
    """O serviço falhou demais nesta execução e foi desligado (circuit breaker)."""


class FalhaPersistente(Exception):
    """Todas as tentativas falharam."""


class CircuitBreaker:
    def __init__(self, nome, max_falhas, logger):
        self.nome, self.max_falhas, self.log = nome, max_falhas, logger
        self.falhas_seguidas = 0
        self.aberto = False

    def sucesso(self):
        self.falhas_seguidas = 0

    def falha(self):
        self.falhas_seguidas += 1
        if not self.aberto and self.falhas_seguidas >= self.max_falhas:
            self.aberto = True
            self.log.error(f"Circuit breaker ABERTO para '{self.nome}' após {self.falhas_seguidas} "
                           "falhas seguidas: o serviço não será mais chamado nesta execução.")

    def verificar(self):
        if self.aberto:
            raise CircuitoAberto(f"circuit breaker aberto para '{self.nome}'")


def com_retry(func, *, tentativas, backoff, logger, descricao, erros=(Exception,), breaker=None):
    """Executa func() com até `tentativas` tentativas e espera exponencial (backoff, 2x, 4x...).

    Lança CircuitoAberto (sem tentar) se o breaker estiver aberto, ou FalhaPersistente
    depois da última tentativa. Atualiza o breaker em caso de sucesso/falha final.
    """
    if breaker:
        breaker.verificar()
    ultimo = None
    for n in range(1, tentativas + 1):
        try:
            resultado = func()
            if breaker:
                breaker.sucesso()
            return resultado
        except erros as e:
            ultimo = e
            logger.warning(f"{descricao}: falhou (tentativa {n}/{tentativas}): {type(e).__name__}: "
                           f"{str(e)[:150]}")
            if n < tentativas:
                espera = backoff * (2 ** (n - 1))
                logger.info(f"{descricao}: aguardando {espera:.1f}s antes de tentar de novo")
                time.sleep(espera)
    if breaker:
        breaker.falha()
    raise FalhaPersistente(f"{descricao}: {type(ultimo).__name__}: {ultimo}") from ultimo
