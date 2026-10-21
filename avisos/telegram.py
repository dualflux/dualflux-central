"""
TELEGRAM: le as mensagens que chegaram ao robo e responde.

Sem endereco publico (funciona no notebook e no servidor): o sistema PERGUNTA ao Telegram
se chegou algo novo (getUpdates). Nao precisa abrir porta nem configurar webhook.

O que o robo entende:
- /start CODIGO  -> conecta a conversa a conta da pessoa (codigo de uso unico, gerado no sistema);
- /parar         -> desconecta (para de receber);
- qualquer outra -> explica como conectar.
So conversas privadas: grupos e canais sao ignorados.
"""

import logging

from django.core.cache import cache
from django.db import transaction

from .canais import ErroEnvio, chamar_telegram, telegram_configurado, telegram_responder
from .models import EstadoTelegram, PreferenciaAviso

log = logging.getLogger(__name__)

TEXTO_COMO_CONECTAR = ("Olá! Eu envio os relatórios do <b>DualFlux</b>.\n\n"
                       "Para conectar, entre no DualFlux, abra <b>Configurações → Notificações</b> "
                       "e toque em <b>Conectar Telegram</b>.")


def _responder(chat_id, texto):
    try:
        telegram_responder(chat_id, texto)
    except ErroEnvio as erro:
        log.warning("Resposta do robo nao enviada: %s", erro)


def tratar_mensagem(mensagem):
    chat = mensagem.get("chat") or {}
    if chat.get("type") != "private":
        return  # grupos e canais: ignora
    chat_id = chat.get("id")
    texto = (mensagem.get("text") or "").strip()
    nome = (mensagem.get("from") or {}).get("first_name", "")

    if texto.startswith("/start"):
        partes = texto.split(maxsplit=1)
        codigo = partes[1].strip() if len(partes) > 1 else ""
        pref = PreferenciaAviso.pelo_codigo_telegram(codigo)
        if pref is None:
            ja_conectado = PreferenciaAviso.objects.filter(telegram_chat_id=chat_id).exists()
            _responder(chat_id, "Você já está conectado ao DualFlux. ✅" if ja_conectado and not codigo
                       else (TEXTO_COMO_CONECTAR if not codigo
                             else "Este link de conexão venceu ou já foi usado. Gere outro em Configurações → Notificações."))
            return
        pref.conectar_telegram(chat_id, nome)
        _responder(chat_id, f"Pronto{', ' + nome if nome else ''}! ✅\n\nVocê vai receber aqui os avisos do "
                            f"<b>DualFlux</b>. Para parar a qualquer momento, envie /parar.")
        return

    if texto.startswith("/parar"):
        pref = PreferenciaAviso.objects.filter(telegram_chat_id=chat_id).first()
        if pref:
            pref.desconectar_telegram()
            _responder(chat_id, "Feito. Você não vai mais receber avisos aqui. "
                                "Para voltar, use Conectar Telegram nas Configurações do DualFlux.")
        else:
            _responder(chat_id, "Esta conversa não está conectada a nenhuma conta.")
        return

    _responder(chat_id, TEXTO_COMO_CONECTAR)


def processar_atualizacoes(espera=0):
    """Le as mensagens novas do robo e trata cada uma. 'espera' = segundos aguardando (long polling).
    Devolve quantas tratou, ou None se outra leitura ja estava em andamento."""
    if not telegram_configurado():
        return 0
    # Uma leitura por vez (o comando 'avisos' e a tela podem chamar ao mesmo tempo).
    if not cache.add("avisos:telegram:lendo", 1, timeout=espera + 30):
        return None  # outra leitura em andamento
    try:
        estado = EstadoTelegram.atual()
        atualizacoes = chamar_telegram("getUpdates", {"offset": estado.ultimo_update + 1, "timeout": espera,
                                                      "allowed_updates": ["message"]}, timeout=espera + 15) or []
        for item in atualizacoes:
            try:
                if "message" in item:
                    with transaction.atomic():
                        tratar_mensagem(item["message"])
            except Exception:
                # Uma mensagem com problema nao pode travar a fila: registra e segue.
                log.exception("Erro ao tratar mensagem do Telegram (update %s)", item.get("update_id"))
            EstadoTelegram.objects.filter(pk=1).update(ultimo_update=item["update_id"])
        return len(atualizacoes)
    finally:
        cache.delete("avisos:telegram:lendo")
