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

class VendaJanela(models.Model):
    """
    Vendas de UMA loja em UMA janela de 15 minutos.

    So totais (quantidade de vendas e faturamento): nenhum dado de cliente
    nem numero de cupom chega ao central.

    Diferente do Evento, esta linha PODE mudar: se uma venda for cancelada
    depois, a loja reenvia a janela e o valor novo SUBSTITUI o antigo.
    """

    # PROTECT: nao deixa apagar loja com historico de vendas.
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="vendas_janelas")

    # Inicio da janela, em UTC, sempre "redondo": 14:00, 14:15, 14:30, 14:45.
    janela_inicio = models.DateTimeField("inicio da janela")

    # Os dois valores SOMAVEIS: somando janelas chegamos a qualquer periodo.
    # Conversao e ticket medio sao calculados depois, nunca guardados aqui.
    transacoes = models.PositiveIntegerField("vendas (transacoes)")
    faturamento = models.DecimalField("faturamento", max_digits=12, decimal_places=2)

    # Ultima vez que a loja mandou esta janela (mostra reenvios por cancelamento).
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "venda por janela"
        verbose_name_plural = "vendas por janela"
        constraints = [
            # Uma janela so existe UMA vez por loja: o reenvio atualiza, nao duplica.
            models.UniqueConstraint(fields=["loja", "janela_inicio"], name="venda_janela_unica_por_loja"),
            # Garantido pelo banco: faturamento nunca negativo.
            models.CheckConstraint(name="venda_faturamento_nao_negativo", condition=models.Q(faturamento__gte=0)),
        ]

    def __str__(self):
        return f"{self.loja} | {self.janela_inicio:%d/%m %H:%M} | {self.transacoes} vendas | R$ {self.faturamento}"