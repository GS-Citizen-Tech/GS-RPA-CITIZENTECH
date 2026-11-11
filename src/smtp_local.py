"""Servidor SMTP local de teste embutido (aiosmtpd), para rodar tudo num só terminal.

Equivale a `python -m aiosmtpd -n -l localhost:1025`, mas grava cada e-mail recebido como .eml
numa "caixa de teste" (pasta), o que serve de evidência do envio. Nada sai da máquina.
"""
from datetime import datetime


class _GravarEmPasta:
    def __init__(self, pasta):
        self.pasta = pasta
        self.recebidos = 0

    async def handle_DATA(self, server, session, envelope):
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.recebidos += 1
        destino = envelope.rcpt_tos[0].split("@")[0] if envelope.rcpt_tos else "sem_destino"
        nome = self.pasta / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{destino}.eml"
        nome.write_bytes(envelope.original_content or envelope.content)
        return "250 Message accepted for delivery"


class SMTPLocal:
    def __init__(self, pasta, host="localhost", porta=1025):
        from aiosmtpd.controller import Controller
        self.handler = _GravarEmPasta(pasta)
        self.controller = Controller(self.handler, hostname=host, port=porta)

    @property
    def recebidos(self):
        return self.handler.recebidos

    def __enter__(self):
        self.controller.start()
        return self

    def __exit__(self, *exc):
        self.controller.stop()
