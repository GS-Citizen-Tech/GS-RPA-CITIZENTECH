"""Tema: automação de e-mail (RF33) -> monta e envia o encaminhamento ao órgão por smtplib.

Padrão: servidor SMTP LOCAL de teste (localhost:1025, sem credenciais). Opcional: Mailtrap ou
Ethereal, configurando SMTP_* no .env. Trava de segurança: só envia para domínios da lista
DOMINIOS_DESTINO_PERMITIDOS (padrão: caixa-teste.local), nunca para e-mails reais de órgãos.
"""
import smtplib
import socket
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from src.resiliencia import CircuitBreaker, com_retry


class DestinatarioNaoPermitido(Exception):
    pass


def montar_email(cfg, oc, descricao_anonimizada, categoria, responsavel):
    urgente = categoria["emergencia"] == "sim"
    msg = EmailMessage()
    msg["From"] = cfg.email_remetente
    msg["To"] = responsavel["email_teste"]
    msg["Subject"] = (("[URGENTE] " if urgente else "") +
                      f"[Quem Resolve?] {oc['protocolo']} - {categoria['nome']}")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(idstring=oc["protocolo"], domain="quemresolve.local")
    msg["X-QuemResolve-Ocorrencia"] = str(oc["id"])
    linhas = [
        "MENSAGEM SIMULADA - protótipo acadêmico Quem Resolve? (FIAP GS 2026.2). Não é uma solicitação real.",
        "",
        f"Protocolo: {oc['protocolo']}",
        f"Categoria: {categoria['nome']} ({categoria['id']})",
        f"Responsável: {responsavel['nome']}",
        f"Canal oficial de referência: {categoria['canal']}",
        f"Prioridade (1 a 5): {oc['prioridade']}",
        f"Origem: {oc['origem']}",
        f"Registrada em: {oc['criada_em']}",
        f"Localização aproximada: lat {oc.get('lat')}, lon {oc.get('lon')}",
        "",
        "Descrição do cidadão (dados pessoais mascarados):",
        descricao_anonimizada,
    ]
    if urgente:
        linhas += ["", "ATENÇÃO: categoria de risco. O cidadão foi orientado a acionar o canal de "
                       "emergência; este e-mail é apenas registro."]
    if categoria.get("observacao"):
        linhas += ["", f"Observação da base: {categoria['observacao']}"]
    linhas += ["", f"Fonte da regra de roteamento: {categoria['fonte_url'] or 'sem fonte oficial (a validar)'}"]
    msg.set_content("\n".join(linhas))
    return msg


class EnviadorEmail:
    def __init__(self, cfg, logger):
        self.cfg, self.log = cfg, logger
        self.breaker = CircuitBreaker(f"SMTP {cfg.smtp_host}:{cfg.smtp_porta}", cfg.max_falhas_seguidas, logger)

    def _verificar_destino(self, msg):
        dominio = msg["To"].rsplit("@", 1)[-1].lower()
        if dominio not in self.cfg.dominios_permitidos:
            raise DestinatarioNaoPermitido(f"domínio {dominio} fora da lista de teste {self.cfg.dominios_permitidos}")

    def _enviar_uma_vez(self, msg):
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_porta, timeout=self.cfg.smtp_timeout) as s:
            if self.cfg.smtp_starttls:
                s.starttls()
            if self.cfg.smtp_usuario:
                s.login(self.cfg.smtp_usuario, self.cfg.smtp_senha)
            s.send_message(msg)

    def enviar(self, msg):
        """Lança DestinatarioNaoPermitido, CircuitoAberto ou FalhaPersistente em caso de falha."""
        self._verificar_destino(msg)
        com_retry(lambda: self._enviar_uma_vez(msg), tentativas=self.cfg.tentativas,
                  backoff=self.cfg.backoff_segundos, logger=self.log, descricao=f"SMTP envio {msg['Subject'][:60]}",
                  erros=(smtplib.SMTPException, OSError, socket.timeout), breaker=self.breaker)
