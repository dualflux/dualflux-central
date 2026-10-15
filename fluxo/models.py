"""
App "fluxo": os DADOS que as lojas enviam ao central.

Evento = UM cruzamento da linha (entrada ou saida), exatamente como no
banco local (eventos_cruzamento), mas com:
- uuid: o mesmo gerado no local; garante que reenviar nao duplica;
- instante em UTC (o local converte a hora de Campo Grande antes de enviar).
"""

from django.db import models

from lojas.models import Camera, Loja


class Evento(models.Model):
    """Um cruzamento de linha. Nunca e alterado depois de gravado."""

    class Direcao(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saida"

    # PROTECT: nao deixa apagar loja ou camera que tenha eventos (protege o historico).
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="eventos")
    camera = models.ForeignKey(Camera, on_delete=models.PROTECT, related_name="eventos")

    # Identificador gerado NO SERVIDOR DA LOJA. E a "impressao digital" do evento:
    # se o mesmo uuid chegar duas vezes (reenvio apos falha de internet),
    # o banco recusa a copia.
    uuid = models.UUIDField("uuid")

    # Momento do cruzamento. Com USE_TZ=True o Django grava em UTC.
    instante = models.DateTimeField("instante")
    direcao = models.CharField("direcao", max_length=7, choices=Direcao.choices)

    # Quando o central recebeu: diferenca grande entre instante e recebido_em
    # mostra que a loja ficou sem internet e reenviou depois.
    recebido_em = models.DateTimeField("recebido em", auto_now_add=True)

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        constraints = [
            # A TRAVA DE IDEMPOTENCIA: o mesmo uuid so existe uma vez por loja.
            models.UniqueConstraint(fields=["loja", "uuid"], name="evento_uuid_unico_por_loja"),
        ]
        indexes = [
            # Indice = "sumario" que o banco consulta antes de varrer a tabela.
            # Torna rapida a pergunta mais comum do dashboard:
            # "eventos da loja X entre tal e tal hora".
            models.Index(fields=["loja", "instante"], name="evento_loja_instante_idx"),
        ]

    def __str__(self):
        return f"{self.loja} | {self.camera.codigo} | {self.direcao} | {self.instante:%d/%m %H:%M:%S}"