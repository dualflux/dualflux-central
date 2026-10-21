"""
AVISOS: relatorios e alertas enviados para fora do sistema (Telegram, e-mail; WhatsApp no futuro).

- PreferenciaAviso: o que cada pessoa quer receber, quando e por onde. Cada um cuida so da sua.
- EnvioAviso: registro de cada envio (o que, para quem, por onde, se deu certo). Nao guarda o texto.
- EstadoTelegram: ate onde ja lemos as mensagens que chegaram ao robo (uma linha so).

Seguranca:
- o codigo para conectar o Telegram e de uso unico, vale 30 minutos e so o "hash" fica no banco;
- do Telegram guardamos so o numero da conversa (chat_id) e o primeiro nome, nada mais;
- o aceite (LGPD) fica gravado com data e hora; sem aceite, nada e enviado.
"""

import hashlib
import secrets
from datetime import time, timedelta

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

VALIDADE_CODIGO_TELEGRAM = timedelta(minutes=30)


def _hash(codigo):
    return hashlib.sha256(codigo.encode()).hexdigest()


class PreferenciaAviso(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferencia_aviso")

    # O que receber
    receber_diario = models.BooleanField("Resumo diário (números de ontem)", default=True)
    receber_semanal = models.BooleanField("Resumo semanal (toda segunda)", default=True)
    receber_alertas = models.BooleanField("Alertas urgentes (loja sem sinal, câmera com falha)", default=True)
    horario = models.TimeField("Horário do envio", default=time(7, 30))

    # Por onde
    canal_telegram = models.BooleanField("Telegram", default=True)
    canal_email = models.BooleanField("E-mail", default=False)

    # Telegram (preenchido quando a pessoa aperta "Iniciar" no robo)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_nome = models.CharField(max_length=80, blank=True)
    telegram_conectado_em = models.DateTimeField(null=True, blank=True)
    telegram_codigo_hash = models.CharField(max_length=64, blank=True)
    telegram_codigo_em = models.DateTimeField(null=True, blank=True)

    # Para o WhatsApp no futuro (opcional)
    celular = models.CharField(
        "Celular com DDD", max_length=15, blank=True,
        validators=[RegexValidator(r"^\d{10,13}$", "Use só números, com DDD. Ex.: 67999998888")])

    # LGPD: sem aceite, nada e enviado
    aceite_em = models.DateTimeField(null=True, blank=True)

    # Controle do agendamento (evita mandar duas vezes no mesmo dia)
    ultimo_diario = models.DateField(null=True, blank=True)
    ultimo_semanal = models.DateField(null=True, blank=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "preferência de avisos"
        verbose_name_plural = "preferências de avisos"

    def __str__(self):
        return f"Avisos de {self.usuario}"

    @property
    def telegram_conectado(self):
        return self.telegram_chat_id is not None

    def canais_ativos(self):
        """Canais por onde esta pessoa recebe AGORA (marcado e pronto para uso)."""
        canais = []
        if self.canal_telegram and self.telegram_conectado:
            canais.append("telegram")
        if self.canal_email and self.usuario.email:
            canais.append("email")
        return canais

    def novo_codigo_telegram(self):
        """Gera o codigo de uso unico do link t.me/...?start=CODIGO. Devolve o codigo (so desta vez)."""
        codigo = secrets.token_urlsafe(18)  # 24 caracteres: letras, numeros, - e _
        self.telegram_codigo_hash = _hash(codigo)
        self.telegram_codigo_em = timezone.now()
        self.save(update_fields=["telegram_codigo_hash", "telegram_codigo_em", "atualizado_em"])
        return codigo

    @classmethod
    def pelo_codigo_telegram(cls, codigo):
        """Preferencia dona deste codigo, se ainda valido. Codigo vencido ou errado: None."""
        if not codigo or len(codigo) > 64:
            return None
        pref = cls.objects.filter(telegram_codigo_hash=_hash(codigo)).select_related("usuario").first()
        if not pref or not pref.telegram_codigo_em:
            return None
        if timezone.now() - pref.telegram_codigo_em > VALIDADE_CODIGO_TELEGRAM:
            return None
        return pref

    def conectar_telegram(self, chat_id, nome):
        # Uma conversa do Telegram so pode estar ligada a uma conta: solta de quem tinha antes.
        PreferenciaAviso.objects.filter(telegram_chat_id=chat_id).exclude(pk=self.pk).update(
            telegram_chat_id=None, telegram_nome="", telegram_conectado_em=None)
        self.telegram_chat_id = chat_id
        self.telegram_nome = (nome or "")[:80]
        self.telegram_conectado_em = timezone.now()
        self.telegram_codigo_hash = ""
        self.telegram_codigo_em = None
        self.save()

    def desconectar_telegram(self):
        self.telegram_chat_id = None
        self.telegram_nome = ""
        self.telegram_conectado_em = None
        self.save()


class EnvioAviso(models.Model):
    class Tipo(models.TextChoices):
        DIARIO = "diario", "Resumo diário"
        SEMANAL = "semanal", "Resumo semanal"
        ALERTA = "alerta", "Alerta urgente"
        TESTE = "teste", "Teste"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="envios_aviso")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    canal = models.CharField(max_length=12)
    chave = models.CharField(max_length=120, blank=True, help_text="Identifica o alerta, para nao repetir.")
    ok = models.BooleanField(default=False)
    erro = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "envio de aviso"
        verbose_name_plural = "envios de avisos"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} → {self.usuario} ({self.canal})"


class EstadoTelegram(models.Model):
    """Uma linha so: o ultimo 'update' do Telegram ja processado."""
    ultimo_update = models.BigIntegerField(default=0)

    @classmethod
    def atual(cls):
        return cls.objects.get_or_create(pk=1)[0]
