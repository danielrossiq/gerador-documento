"""Notificações (e-mail). Interface + provedor SMTP opcional + provedor de console para desenvolvimento."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Notifier(Protocol):
    def send_password_reset(self, to_email: str, link: str) -> None: ...
    def send_client_answer(self, to_email: str, document: str, link: str) -> None: ...


class ConsoleNotifier:
    """Sem SMTP configurado: em desenvolvimento imprime o link no log; em produção só avisa que não enviou."""

    def send_password_reset(self, to_email: str, link: str) -> None:
        if get_settings().is_production:
            log.warning("email_nao_enviado_sem_smtp", extra={"template": "password_reset"})
        else:
            # somente em dev/teste: o link é um segredo de curta duração
            log.warning("DEV email de recuperação (não enviado): %s", link)

    def send_client_answer(self, to_email: str, document: str, link: str) -> None:
        # sem SMTP o aviso fica só no app (contador de respostas); nada de e-mail/nome do documento no log
        log.info("email_nao_enviado_sem_smtp", extra={"template": "client_answer"})


class SmtpNotifier:
    def __init__(self, host: str, port: int, user: str | None, password: str | None, sender: str) -> None:
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def send_password_reset(self, to_email: str, link: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Recuperação de senha"
        msg["From"] = self.sender
        msg["To"] = to_email
        msg.set_content(
            f"Você pediu para redefinir sua senha.\n\nAbra o link (válido por 1 hora):\n{link}\n\nSe não foi você, ignore este e-mail."
        )
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.starttls()
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)

    def send_client_answer(self, to_email: str, document: str, link: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"Seu cliente respondeu: {document[:80]}"
        msg["From"] = self.sender
        msg["To"] = to_email
        msg.set_content(
            f"Os dados para o documento “{document}” chegaram pelo link que você enviou.\n\n"
            f"Abra para conferir e gerar:\n{link}\n\nOs dados ficam no DocFeito, não neste e-mail."
        )
        self._send(msg)

    def _send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.starttls()
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


def get_notifier() -> Notifier:
    import os

    host = os.environ.get("SMTP_HOST")
    if host:
        return SmtpNotifier(
            host,
            int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USER"),
            os.environ.get("SMTP_PASSWORD"),
            os.environ.get("SMTP_FROM", "no-reply@localhost"),
        )
    return ConsoleNotifier()
