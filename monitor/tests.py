"""
Testes automaticos do heartbeat (POST /api/v1/heartbeat/) e do StatusLoja.

Para rodar:  docker compose exec web python manage.py test monitor
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from contas.models import Empresa
from lojas.models import Loja, TokenApi

from .models import StatusLoja

URL = "/api/v1/heartbeat/"


class HeartbeatTest(TestCase):

    def setUp(self):
        self.cliente = APIClient()
        empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.loja = Loja.objects.create(empresa=empresa, nome="Loja A", slug="loja-a")
        _, self.token = TokenApi.gerar(self.loja)

    def heartbeat(self, relogio=None, **extra):
        """Envia um heartbeat; por padrao com o relogio certo (agora)."""
        corpo = {
            "versao": "1.4.0",
            "relogio": (relogio or timezone.now()).isoformat(),
            "cameras": [{"codigo": "cam1", "ok": True, "fps": 7.3}],
            **extra,
        }
        return self.cliente.post(URL, corpo, format="json", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_sem_token_recebe_401(self):
        resposta = self.cliente.post(URL, {"versao": "1.0"}, format="json")
        self.assertEqual(resposta.status_code, 401)

    def test_primeiro_heartbeat_cria_o_status(self):
        resposta = self.heartbeat()
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("relogio_servidor", resposta.json())
        status = StatusLoja.objects.get(loja=self.loja)
        self.assertTrue(status.online)
        self.assertTrue(status.cameras_ok)

    def test_heartbeats_seguintes_sobrescrevem_uma_linha_so(self):
        self.heartbeat(versao="1.4.0")
        self.heartbeat(versao="1.5.0")
        self.assertEqual(StatusLoja.objects.count(), 1)
        self.assertEqual(StatusLoja.objects.get().versao, "1.5.0")

    def test_loja_sem_heartbeat_ha_mais_de_3_minutos_fica_offline(self):
        self.heartbeat()
        status = StatusLoja.objects.get()
        # Simula a passagem do tempo: o ultimo heartbeat foi ha 4 minutos.
        status.ultimo_heartbeat = timezone.now() - timedelta(minutes=4)
        status.save()
        self.assertFalse(status.online)

    def test_relogio_da_loja_atrasado_e_detectado(self):
        # Loja com relogio 10 minutos atrasado (ex.: bateria da placa fraca).
        self.heartbeat(relogio=timezone.now() - timedelta(minutes=10))
        status = StatusLoja.objects.get()
        self.assertFalse(status.relogio_ok)
        self.assertLess(status.diferenca_relogio_s, -500)

    def test_camera_com_problema_e_detectada(self):
        self.heartbeat(cameras=[{"codigo": "cam1", "ok": False}])
        self.assertFalse(StatusLoja.objects.get().cameras_ok)

    def test_relogio_sem_fuso_e_recusado(self):
        resposta = self.heartbeat(relogio=None, versao="1.4.0")  # monta normal...
        corpo = {"versao": "1.4.0", "relogio": "2026-10-14T13:58:21"}  # ...e agora sem fuso
        resposta = self.cliente.post(URL, corpo, format="json", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(resposta.status_code, 400)