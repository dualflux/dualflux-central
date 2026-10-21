"""
CANAIS: o "carteiro" de cada meio de envio. Todos tem a mesma funcao: enviar(pref, mensagem).

Para ligar o WhatsApp no futuro: criar enviar_whatsapp(pref, mensagem) aqui e registrar em CANAIS.
O resto do sistema (o que dizer, quando enviar) nao muda.

O token do robo fica so no .env (TELEGRAM_BOT_TOKEN). Ele NUNCA aparece em log ou mensagem de erro.
"""

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


class ErroEnvio(Exception):
    """Falha ao enviar. A mensagem e curta e nunca contem o token."""

    def __init__(self, motivo, bloqueado=False):
        super().__init__(motivo)
        self.bloqueado = bloqueado  # a pessoa bloqueou o robo / apagou a conversa


def telegram_configurado():
    return bool(getattr(settings, "TELEGRAM_BOT_TOKEN", ""))


def chamar_telegram(metodo, dados=None, timeout=15):
    """Chama a API oficial do Telegram (https://api.telegram.org). Devolve o 'result' da resposta."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ErroEnvio("Telegram não configurado (falta TELEGRAM_BOT_TOKEN no .env).")
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    corpo = json.dumps(dados or {}).encode()
    pedido = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            retorno = json.loads(resposta.read().decode())
    except urllib.error.HTTPError as erro:
        try:
            descricao = json.loads(erro.read().decode()).get("description", "")
        except Exception:
            descricao = ""
        bloqueado = erro.code == 403 or "chat not found" in descricao.lower()
        raise ErroEnvio(f"Telegram recusou ({erro.code}): {descricao[:120]}", bloqueado=bloqueado) from None
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        motivo = getattr(erro, "reason", erro)
        raise ErroEnvio(f"Sem conexão com o Telegram: {str(motivo)[:120]}") from None
    if not retorno.get("ok"):
        raise ErroEnvio(f"Telegram recusou: {str(retorno.get('description', ''))[:120]}")
    return retorno.get("result")


def telegram_responder(chat_id, texto):
    """Mensagem simples do robo (ex.: 'Pronto, conectado!')."""
    return chamar_telegram("sendMessage", {"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                           "disable_web_page_preview": True})


# ----------------------------------------------------------------------
# Os carteiros
# ----------------------------------------------------------------------

def enviar_telegram(pref, mensagem):
    if not pref.telegram_chat_id:
        raise ErroEnvio("Telegram não conectado.")
    try:
        telegram_responder(pref.telegram_chat_id, mensagem.html)
    except ErroEnvio as erro:
        if erro.bloqueado:
            # A pessoa bloqueou o robo ou apagou a conversa: desconecta para nao insistir.
            pref.desconectar_telegram()
        raise


def enviar_email(pref, mensagem):
    try:
        send_mail(mensagem.titulo, mensagem.texto, None, [pref.usuario.email])
    except Exception as erro:
        raise ErroEnvio(f"E-mail não enviado: {str(erro)[:120]}") from None


CANAIS = {
    "telegram": enviar_telegram,
    "email": enviar_email,
    # "whatsapp": enviar_whatsapp,   <- no futuro
}


class Mensagem:
    """Uma mensagem pronta: HTML simples (Telegram) e texto puro (e-mail), gerado do mesmo conteudo."""

    def __init__(self, titulo, html_texto):
        self.titulo = titulo
        self.html = html_texto

    @property
    def texto(self):
        sem_tags = re.sub(r"<a href=\"([^\"]+)\">([^<]+)</a>", r"\2: \1", self.html)
        sem_tags = re.sub(r"<[^>]+>", "", sem_tags)
        return html.unescape(sem_tags)


def enviar(pref, mensagem, tipo, chave=""):
    """Envia por todos os canais ativos da pessoa e registra cada tentativa. Devolve [(canal, ok, erro)]."""
    from .models import EnvioAviso

    resultados = []
    for canal in pref.canais_ativos():
        ok, erro = True, ""
        try:
            CANAIS[canal](pref, mensagem)
        except ErroEnvio as falha:
            ok, erro = False, str(falha)[:200]
            log.warning("Aviso %s para usuario %s por %s falhou: %s", tipo, pref.usuario_id, canal, erro)
        EnvioAviso.objects.create(usuario=pref.usuario, tipo=tipo, canal=canal, chave=chave[:120], ok=ok, erro=erro)
        resultados.append((canal, ok, erro))
    return resultados
