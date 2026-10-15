"""
API de ingestao das lojas:
  POST /api/v1/eventos/  -> cruzamentos de linha (entrada/saida)
  POST /api/v1/vendas/   -> vendas agregadas em janelas de 15 minutos

Regras do contrato:
- a loja e identificada pelo TOKEN, nunca pelo JSON;
- eventos: reenviar o mesmo lote NAO duplica (idempotencia pelo uuid);
- eventos: camera desconhecida e criada sozinha (renomeie depois no admin);
- vendas: reenviar uma janela SUBSTITUI o valor (corrige cancelamentos);
- horarios sempre com fuso (o local envia em UTC, com "Z").
"""

from datetime import timezone as fuso_utc

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from lojas.autenticacao import LojaAutenticada, TokenLojaAuthentication
from lojas.models import Camera

from .models import Evento, VendaJanela

LIMITE_POR_LOTE = 500             # eventos por envio
LIMITE_JANELAS_POR_LOTE = 1000    # janelas de vendas por envio (7 dias = 672)


# ----------------------------------------------------------------------
# Campo comum: data/hora que EXIGE fuso
# ----------------------------------------------------------------------

class InstanteComFusoField(serializers.DateTimeField):
    """
    Data/hora que EXIGE fuso. Sem esta regra, o DRF aceitaria "2026-10-14 13:58"
    e assumiria o fuso do central, gravando o horario errado sem avisar.
    """

    def to_internal_value(self, valor):
        convertido = parse_datetime(str(valor))
        if convertido is not None and timezone.is_naive(convertido):
            raise serializers.ValidationError("Informe o fuso. Ex.: 2026-10-14T13:58:21Z")
        return super().to_internal_value(valor)


# ----------------------------------------------------------------------
# EVENTOS
# ----------------------------------------------------------------------

class EventoEntradaSerializer(serializers.Serializer):
    """Formato de UM evento no JSON."""

    uuid = serializers.UUIDField()
    camera = serializers.SlugField(max_length=50)
    direcao = serializers.ChoiceField(choices=Evento.Direcao.choices)
    instante = InstanteComFusoField()


class LoteEventosSerializer(serializers.Serializer):
    """Formato do corpo inteiro: {"eventos": [ ... ]}, de 1 a 500 eventos."""

    eventos = EventoEntradaSerializer(many=True, allow_empty=False, max_length=LIMITE_POR_LOTE)


class EventosView(APIView):
    authentication_classes = [TokenLojaAuthentication]
    permission_classes = [LojaAutenticada]

    def post(self, request):
        # 1) Valida o JSON. Se algo estiver errado, responde 400 com a lista
        #    de erros e NADA e gravado.
        lote = LoteEventosSerializer(data=request.data)
        lote.is_valid(raise_exception=True)

        token = request.auth
        loja = token.loja  # a loja vem do TOKEN, nunca do JSON
        eventos = lote.validated_data["eventos"]

        # 2) Remove uuids repetidos DENTRO do proprio lote.
        por_uuid = {evento["uuid"]: evento for evento in eventos}

        # 3) Descobre quais uuids o central JA tem (reenvio apos falha de internet).
        ja_existem = set(
            Evento.objects.filter(loja=loja, uuid__in=por_uuid.keys()).values_list("uuid", flat=True)
        )
        novos = [evento for uuid, evento in por_uuid.items() if uuid not in ja_existem]

        # 4) Grava tudo numa transacao: ou entra o lote inteiro, ou nada.
        with transaction.atomic():
            cameras = self._cameras_da_loja(loja, {evento["camera"] for evento in novos})
            Evento.objects.bulk_create(
                [
                    Evento(
                        loja=loja,
                        camera=cameras[evento["camera"]],
                        uuid=evento["uuid"],
                        instante=evento["instante"],
                        direcao=evento["direcao"],
                    )
                    for evento in novos
                ],
                # Ultima barreira: se dois envios simultaneos tentarem gravar o
                # mesmo uuid, o banco ignora a copia em vez de dar erro.
                ignore_conflicts=True,
            )

        token.marcar_uso()

        return Response({
            "recebidos": len(eventos),
            "novos": len(novos),
            "duplicados": len(eventos) - len(novos),
        })

    @staticmethod
    def _cameras_da_loja(loja, codigos):
        """
        Devolve {codigo: Camera} para os codigos do lote.
        Camera que o central ainda nao conhece e criada na hora: assim uma
        camera nova instalada na loja nao trava o envio dos dados.
        """
        cameras = {c.codigo: c for c in Camera.objects.filter(loja=loja, codigo__in=codigos)}
        for codigo in codigos - cameras.keys():
            cameras[codigo], _ = Camera.objects.get_or_create(loja=loja, codigo=codigo, defaults={"nome": codigo})
        return cameras


# ----------------------------------------------------------------------
# VENDAS
# ----------------------------------------------------------------------

class JanelaVendaSerializer(serializers.Serializer):
    """Formato de UMA janela de vendas no JSON."""

    inicio = InstanteComFusoField()
    transacoes = serializers.IntegerField(min_value=0)
    # Texto com ate 2 casas decimais ("845.30"), nunca negativo.
    faturamento = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)

    def validate_inicio(self, valor):
        """A janela precisa comecar num multiplo de 15 minutos (14:00, 14:15...)."""
        em_utc = valor.astimezone(fuso_utc.utc)
        if em_utc.minute % 15 or em_utc.second or em_utc.microsecond:
            raise serializers.ValidationError(
                "A janela deve comecar num multiplo de 15 min. Ex.: 14:00, 14:15, 14:30, 14:45."
            )
        return em_utc


class LoteVendasSerializer(serializers.Serializer):
    """Formato do corpo inteiro: {"janelas": [ ... ]}, de 1 a 1.000 janelas."""

    janelas = JanelaVendaSerializer(many=True, allow_empty=False, max_length=LIMITE_JANELAS_POR_LOTE)


class VendasView(APIView):
    authentication_classes = [TokenLojaAuthentication]
    permission_classes = [LojaAutenticada]

    def post(self, request):
        lote = LoteVendasSerializer(data=request.data)
        lote.is_valid(raise_exception=True)

        token = request.auth
        loja = token.loja  # a loja vem do TOKEN, nunca do JSON

        # Se a mesma janela vier repetida no lote, vale a ULTIMA.
        por_inicio = {janela["inicio"]: janela for janela in lote.validated_data["janelas"]}
        registros = [
            VendaJanela(
                loja=loja,
                janela_inicio=inicio,
                transacoes=janela["transacoes"],
                faturamento=janela["faturamento"],
            )
            for inicio, janela in por_inicio.items()
        ]

        with transaction.atomic():
            # "Upsert": insere as janelas novas e SUBSTITUI os valores das que
            # ja existem (ex.: venda cancelada depois do primeiro envio).
            VendaJanela.objects.bulk_create(
                registros,
                update_conflicts=True,
                unique_fields=["loja", "janela_inicio"],
                update_fields=["transacoes", "faturamento", "atualizado_em"],
            )

        token.marcar_uso()
        return Response({"atualizadas": len(registros)})