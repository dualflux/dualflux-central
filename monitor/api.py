"""
API de heartbeat:  POST /api/v1/heartbeat/

A loja envia, a cada 60 s, um "estou vivo" com o estado do servidor local.
O central sobrescreve a linha de StatusLoja daquela loja e devolve o
proprio relogio (a loja pode usar para conferir o dela).
"""

from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

# Reaproveitamos o campo de horario que EXIGE fuso, criado para os eventos.
from fluxo.api import InstanteComFusoField
from lojas.autenticacao import LojaAutenticada, TokenLojaAuthentication

from .models import StatusLoja


class CameraStatusSerializer(serializers.Serializer):
    """Estado de UMA camera, como a loja informa."""

    codigo = serializers.SlugField(max_length=50)
    ok = serializers.BooleanField()
    fps = serializers.FloatField(required=False, allow_null=True, min_value=0)
    ultimo_evento = InstanteComFusoField(required=False, allow_null=True)


class SyncStatusSerializer(serializers.Serializer):
    """Como esta a fila de envio no servidor local."""

    eventos_pendentes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    ultimo_erro = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=300)


class HeartbeatSerializer(serializers.Serializer):
    """Formato do corpo do heartbeat (o contrato combinado)."""

    versao = serializers.CharField(max_length=20)
    hostname = serializers.CharField(max_length=63, required=False, allow_blank=True)
    relogio = InstanteComFusoField()
    uptime_s = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    disco_livre_pct = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100)
    cameras = CameraStatusSerializer(many=True, required=False)
    sync = SyncStatusSerializer(required=False)


class HeartbeatView(APIView):
    authentication_classes = [TokenLojaAuthentication]
    permission_classes = [LojaAutenticada]

    def post(self, request):
        dados = HeartbeatSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        valido = dados.validated_data

        token = request.auth
        agora = timezone.now()

        # Diferenca entre o relogio da loja e o do central, em segundos.
        diferenca = round((valido["relogio"] - agora).total_seconds())

        # .data devolve as cameras ja em formato de texto (datas em ISO),
        # pronto para guardar no campo JSON.
        cameras = dados.data.get("cameras", [])
        sync = valido.get("sync") or {}

        # update_or_create: cria a linha da loja no primeiro heartbeat
        # e SOBRESCREVE nos seguintes (sempre uma linha por loja).
        StatusLoja.objects.update_or_create(
            loja=token.loja,
            defaults={
                "ultimo_heartbeat": agora,
                "versao": valido["versao"],
                "hostname_informado": valido.get("hostname", ""),
                "uptime_s": valido.get("uptime_s"),
                "disco_livre_pct": valido.get("disco_livre_pct"),
                "cameras": cameras,
                "eventos_pendentes": sync.get("eventos_pendentes"),
                "ultimo_erro_sync": sync.get("ultimo_erro") or "",
                "diferenca_relogio_s": diferenca,
            },
        )

        token.marcar_uso()
        return Response({"relogio_servidor": agora.isoformat()})
    