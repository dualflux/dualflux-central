"""
API de ingestao de eventos:  POST /api/v1/eventos/

Recebe um lote de cruzamentos enviado pelo servidor local da loja.
Regras do contrato:
- reenviar o mesmo lote NAO duplica (idempotencia pelo uuid);
- camera desconhecida e criada sozinha (nome = codigo; renomeie depois no admin);
- instante sempre com fuso (o local envia em UTC, com "Z").
"""

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from lojas.autenticacao import LojaAutenticada, TokenLojaAuthentication
from lojas.models import Camera

from .models import Evento

LIMITE_POR_LOTE = 500


# ----------------------------------------------------------------------
# Validacao (serializers): o "porteiro" do JSON que chega
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


class EventoEntradaSerializer(serializers.Serializer):
    """Formato de UM evento no JSON."""

    uuid = serializers.UUIDField()
    camera = serializers.SlugField(max_length=50)
    direcao = serializers.ChoiceField(choices=Evento.Direcao.choices)
    instante = InstanteComFusoField()


class LoteEventosSerializer(serializers.Serializer):
    """Formato do corpo inteiro: {"eventos": [ ... ]}, de 1 a 500 eventos."""

    eventos = EventoEntradaSerializer(many=True, allow_empty=False, max_length=LIMITE_POR_LOTE)


# ----------------------------------------------------------------------
# O endpoint
# ----------------------------------------------------------------------

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