"""
App "monitor": a SAUDE de cada loja, vinda do heartbeat ("estou vivo").

StatusLoja guarda so a ULTIMA noticia de cada loja (uma linha por loja,
sobrescrita a cada heartbeat). As perguntas "esta online?", "relogio certo?"
sao respondidas na hora, comparando com o relogio do central: uma loja que
parou de mandar heartbeat vira "offline" sozinha, sem nenhuma rotina extra.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone

from lojas.models import Loja

# Sem heartbeat ha mais que isto = loja offline.
# 3 minutos = 3 heartbeats perdidos (envio a cada 60 s): tolera uma falha
# isolada de internet sem disparar alarme falso.
LIMITE_ONLINE = timedelta(minutes=3)

# Diferenca maxima aceitavel entre o relogio da loja e o do central.
# Acima disso, os horarios das contagens ficam suspeitos.
LIMITE_RELOGIO_SEGUNDOS = 120


class StatusLoja(models.Model):
    """Ultima noticia recebida de uma loja."""

    # OneToOne: no maximo UMA linha de status por loja.
    loja = models.OneToOneField(Loja, on_delete=models.CASCADE, related_name="status")

    ultimo_heartbeat = models.DateTimeField("ultimo heartbeat")
    versao = models.CharField("versao do software", max_length=20, blank=True)
    hostname_informado = models.CharField(
        "hostname informado", max_length=63, blank=True,
        help_text="Nome que a maquina diz ter. Diferente do cadastro = disco trocado ou clonado errado.",
    )
    uptime_s = models.PositiveIntegerField("ligado ha (s)", null=True, blank=True)
    disco_livre_pct = models.PositiveSmallIntegerField("disco livre (%)", null=True, blank=True)

    # Lista com o estado de cada camera, exatamente como a loja enviou:
    # [{"codigo": "cam1", "ok": true, "fps": 7.3, "ultimo_evento": "..."}]
    cameras = models.JSONField("cameras", default=list, blank=True)

    eventos_pendentes = models.PositiveIntegerField("eventos pendentes de envio", null=True, blank=True)
    ultimo_erro_sync = models.CharField("ultimo erro do envio", max_length=300, blank=True)

    # Relogio da loja MENOS relogio do central, em segundos.
    # Positivo = loja adiantada; negativo = loja atrasada.
    diferenca_relogio_s = models.IntegerField("diferenca de relogio (s)", null=True, blank=True)

    class Meta:
        verbose_name = "status da loja"
        verbose_name_plural = "status das lojas"

    # --- Respostas calculadas na hora (nao ficam gravadas) ---

    @property
    def online(self):
        return timezone.now() - self.ultimo_heartbeat <= LIMITE_ONLINE

    @property
    def relogio_ok(self):
        if self.diferenca_relogio_s is None:
            return True
        return abs(self.diferenca_relogio_s) <= LIMITE_RELOGIO_SEGUNDOS

    @property
    def cameras_ok(self):
        # Todas as cameras informadas estao ok? (lista vazia = nada a reclamar)
        return all(camera.get("ok") for camera in self.cameras)

    def __str__(self):
        return f"{self.loja} - {'online' if self.online else 'OFFLINE'}"
