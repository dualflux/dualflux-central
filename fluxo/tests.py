"""
Testes automaticos da API de eventos (POST /api/v1/eventos/).

Cada teste e uma REGRA do contrato escrita como codigo. Rodam num banco
temporario, criado do zero e apagado no fim: os dados reais nao sao tocados.

Para rodar:  docker compose exec web python manage.py test fluxo
"""

import uuid
from datetime import datetime, timezone as tz

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from contas.models import Empresa
from lojas.models import Camera, Loja, TokenApi

from .api import LIMITE_POR_LOTE
from .models import Evento

URL = "/api/v1/eventos/"


def evento(camera="cam1", direcao="entrada", instante="2026-10-14T13:58:21Z", id_evento=None):
    """Monta UM evento no formato do contrato (com uuid novo, se nao for informado)."""
    return {
        "uuid": str(id_evento or uuid.uuid4()),
        "camera": camera,
        "direcao": direcao,
        "instante": instante,
    }


class ApiEventosTest(TestCase):

    def setUp(self):
        """Roda ANTES de cada teste: monta duas empresas, cada uma com sua loja e token."""
        self.cliente = APIClient()

        empresa_a = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.loja_a = Loja.objects.create(empresa=empresa_a, nome="Loja A", slug="loja-a")
        Camera.objects.create(loja=self.loja_a, codigo="cam1", nome="Porta")
        self.registro_a, self.token_a = TokenApi.gerar(self.loja_a)

        empresa_b = Empresa.objects.create(nome="Rede B", slug="rede-b")
        self.loja_b = Loja.objects.create(empresa=empresa_b, nome="Loja B", slug="loja-b")
        Camera.objects.create(loja=self.loja_b, codigo="cam1", nome="Porta")
        self.registro_b, self.token_b = TokenApi.gerar(self.loja_b)

    def enviar(self, token, eventos):
        """Faz o POST como o servidor da loja faria."""
        return self.cliente.post(
            URL, {"eventos": eventos}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    # ------------------------------------------------------------------
    # Autenticacao: quem nao tem token valido nao grava nada
    # ------------------------------------------------------------------

    def test_sem_token_recebe_401(self):
        resposta = self.cliente.post(URL, {"eventos": [evento()]}, format="json")
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(Evento.objects.count(), 0)

    def test_token_inventado_recebe_401(self):
        resposta = self.enviar("dfx_00000000_" + "0" * 64, [evento()])
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(Evento.objects.count(), 0)

    def test_token_revogado_recebe_401(self):
        self.registro_a.revogado_em = timezone.now()
        self.registro_a.save()
        resposta = self.enviar(self.token_a, [evento()])
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(Evento.objects.count(), 0)

    # ------------------------------------------------------------------
    # Gravacao e idempotencia
    # ------------------------------------------------------------------

    def test_envio_valido_grava_os_eventos(self):
        resposta = self.enviar(self.token_a, [evento(), evento(direcao="saida")])
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"recebidos": 2, "novos": 2, "duplicados": 0})
        self.assertEqual(Evento.objects.filter(loja=self.loja_a).count(), 2)

    def test_reenvio_do_mesmo_lote_nao_duplica(self):
        lote = [evento(), evento()]
        self.enviar(self.token_a, lote)
        resposta = self.enviar(self.token_a, lote)  # a "queda de internet": reenvia tudo
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"recebidos": 2, "novos": 0, "duplicados": 2})
        self.assertEqual(Evento.objects.count(), 2)

    def test_uuid_repetido_dentro_do_lote_grava_uma_vez(self):
        mesmo_id = uuid.uuid4()
        resposta = self.enviar(self.token_a, [evento(id_evento=mesmo_id), evento(id_evento=mesmo_id)])
        self.assertEqual(resposta.json()["novos"], 1)
        self.assertEqual(Evento.objects.count(), 1)

    def test_marca_o_ultimo_uso_do_token(self):
        self.assertIsNone(self.registro_a.ultimo_uso_em)
        self.enviar(self.token_a, [evento()])
        self.registro_a.refresh_from_db()
        self.assertIsNotNone(self.registro_a.ultimo_uso_em)

    # ------------------------------------------------------------------
    # Isolamento entre empresas (a regra de seguranca mais importante)
    # ------------------------------------------------------------------

    def test_token_da_loja_b_grava_somente_na_loja_b(self):
        self.enviar(self.token_b, [evento(), evento()])
        self.assertEqual(Evento.objects.filter(loja=self.loja_b).count(), 2)
        self.assertEqual(Evento.objects.filter(loja=self.loja_a).count(), 0)

    def test_mesmo_uuid_em_lojas_diferentes_nao_conflita(self):
        # O uuid e unico POR LOJA: a loja B nao "bloqueia" um evento da loja A.
        mesmo_id = uuid.uuid4()
        self.enviar(self.token_a, [evento(id_evento=mesmo_id)])
        resposta = self.enviar(self.token_b, [evento(id_evento=mesmo_id)])
        self.assertEqual(resposta.json()["novos"], 1)
        self.assertEqual(Evento.objects.count(), 2)

    # ------------------------------------------------------------------
    # Validacao: dado malformado responde 400 e NADA e gravado
    # ------------------------------------------------------------------

    def test_instante_sem_fuso_e_recusado(self):
        resposta = self.enviar(self.token_a, [evento(instante="2026-10-14T13:58:21")])
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Evento.objects.count(), 0)

    def test_direcao_invalida_e_recusada(self):
        resposta = self.enviar(self.token_a, [evento(direcao="lateral")])
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Evento.objects.count(), 0)

    def test_um_evento_ruim_recusa_o_lote_inteiro(self):
        # Ou entra tudo, ou nada: evita lote "pela metade" no banco.
        resposta = self.enviar(self.token_a, [evento(), evento(direcao="lateral")])
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Evento.objects.count(), 0)

    def test_lote_vazio_e_recusado(self):
        resposta = self.enviar(self.token_a, [])
        self.assertEqual(resposta.status_code, 400)

    def test_lote_acima_do_limite_e_recusado(self):
        resposta = self.enviar(self.token_a, [evento() for _ in range(LIMITE_POR_LOTE + 1)])
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Evento.objects.count(), 0)

    # ------------------------------------------------------------------
    # Fuso horario e cameras
    # ------------------------------------------------------------------

    def test_horario_com_outro_fuso_e_convertido_para_utc(self):
        # 09:58 em Campo Grande (-04:00) e o mesmo momento que 13:58 em UTC.
        self.enviar(self.token_a, [evento(instante="2026-10-14T09:58:21-04:00")])
        gravado = Evento.objects.get().instante
        self.assertEqual(gravado, datetime(2026, 10, 14, 13, 58, 21, tzinfo=tz.utc))

    def test_camera_desconhecida_e_criada_automaticamente(self):
        resposta = self.enviar(self.token_a, [evento(camera="cam2")])
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(Camera.objects.filter(loja=self.loja_a, codigo="cam2").exists())

# ======================================================================
# Testes da API de vendas (POST /api/v1/vendas/)
# ======================================================================
from decimal import Decimal

from .models import VendaJanela

URL_VENDAS = "/api/v1/vendas/"


def janela(inicio="2026-10-14T14:00:00Z", transacoes=12, faturamento="845.30"):
    """Monta UMA janela de vendas no formato do contrato."""
    return {"inicio": inicio, "transacoes": transacoes, "faturamento": faturamento}


class ApiVendasTest(TestCase):

    def setUp(self):
        self.cliente = APIClient()
        empresa_a = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.loja_a = Loja.objects.create(empresa=empresa_a, nome="Loja A", slug="loja-a")
        _, self.token_a = TokenApi.gerar(self.loja_a)

        empresa_b = Empresa.objects.create(nome="Rede B", slug="rede-b")
        self.loja_b = Loja.objects.create(empresa=empresa_b, nome="Loja B", slug="loja-b")
        _, self.token_b = TokenApi.gerar(self.loja_b)

    def enviar(self, token, janelas):
        return self.cliente.post(
            URL_VENDAS, {"janelas": janelas}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    def test_sem_token_recebe_401(self):
        resposta = self.cliente.post(URL_VENDAS, {"janelas": [janela()]}, format="json")
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(VendaJanela.objects.count(), 0)

    def test_envio_valido_grava_as_janelas(self):
        resposta = self.enviar(self.token_a, [janela(), janela(inicio="2026-10-14T14:15:00Z")])
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"atualizadas": 2})
        self.assertEqual(VendaJanela.objects.filter(loja=self.loja_a).count(), 2)

    def test_reenvio_substitui_o_valor_em_vez_de_duplicar(self):
        # O cancelamento: a mesma janela volta com uma venda a menos.
        self.enviar(self.token_a, [janela(transacoes=12, faturamento="845.30")])
        self.enviar(self.token_a, [janela(transacoes=11, faturamento="780.10")])
        self.assertEqual(VendaJanela.objects.count(), 1)
        venda = VendaJanela.objects.get()
        self.assertEqual(venda.transacoes, 11)
        self.assertEqual(venda.faturamento, Decimal("780.10"))

    def test_janela_repetida_no_mesmo_lote_vale_a_ultima(self):
        self.enviar(self.token_a, [janela(transacoes=5), janela(transacoes=7)])
        self.assertEqual(VendaJanela.objects.get().transacoes, 7)

    def test_janela_fora_do_multiplo_de_15_minutos_e_recusada(self):
        resposta = self.enviar(self.token_a, [janela(inicio="2026-10-14T14:07:00Z")])
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(VendaJanela.objects.count(), 0)

    def test_horario_com_fuso_local_alinhado_e_aceito(self):
        # 10:15 em Campo Grande (-04:00) = 14:15 UTC: e um inicio de janela valido.
        resposta = self.enviar(self.token_a, [janela(inicio="2026-10-14T10:15:00-04:00")])
        self.assertEqual(resposta.status_code, 200)

    def test_inicio_sem_fuso_e_recusado(self):
        resposta = self.enviar(self.token_a, [janela(inicio="2026-10-14T14:00:00")])
        self.assertEqual(resposta.status_code, 400)

    def test_faturamento_negativo_e_recusado(self):
        resposta = self.enviar(self.token_a, [janela(faturamento="-10.00")])
        self.assertEqual(resposta.status_code, 400)

    def test_faturamento_com_mais_de_2_casas_e_recusado(self):
        resposta = self.enviar(self.token_a, [janela(faturamento="10.555")])
        self.assertEqual(resposta.status_code, 400)

    def test_vendas_da_loja_b_nao_alteram_a_loja_a(self):
        # Mesma janela, lojas diferentes: cada uma tem a sua linha.
        self.enviar(self.token_a, [janela(transacoes=12)])
        self.enviar(self.token_b, [janela(transacoes=3)])
        self.assertEqual(VendaJanela.objects.get(loja=self.loja_a).transacoes, 12)
        self.assertEqual(VendaJanela.objects.get(loja=self.loja_b).transacoes, 3)