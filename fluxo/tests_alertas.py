"""Testes dos Alertas: regras de movimento/conversao e permissoes."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from contas.models import Empresa, Usuario
from lojas.models import Loja

from .alertas import alertas_de_ontem

ONTEM = date(2026, 10, 13)  # uma terca


def serie_falsa(entradas_ontem, vendas_ontem, entradas_normal=400, vendas_normal=120):
    """28 dias de historico 'normal' + o dia de ontem."""
    def falsa(loja, inicio, fim):
        dias = []
        dia = inicio
        while dia <= fim:
            e, v = (entradas_ontem, vendas_ontem) if dia == ONTEM else (entradas_normal, vendas_normal)
            dias.append({"dia": dia, "entradas": e, "vendas": v, "faturamento": Decimal("0")})
            dia += timedelta(days=1)
        return dias
    return falsa


class RegrasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.loja = Loja.objects.create(empresa=self.empresa, nome="Loja 1", slug="loja-1")

    def gerar(self, *args):
        with patch("fluxo.alertas.serie_diaria", serie_falsa(*args)):
            cache.clear()
            return alertas_de_ontem(self.loja, ONTEM)

    def test_movimento_normal_nao_alerta(self):
        self.assertEqual(self.gerar(410, 123), [])

    def test_movimento_baixo_alerta_atencao(self):
        alertas = self.gerar(200, 60)
        self.assertEqual([a["gravidade"] for a in alertas], ["atencao"])
        self.assertIn("abaixo do normal", alertas[0]["titulo"])

    def test_movimento_alto_e_boa_noticia(self):
        alertas = self.gerar(600, 180)
        self.assertEqual([a["gravidade"] for a in alertas], ["boa"])

    def test_conversao_em_queda(self):
        alertas = self.gerar(400, 80)  # 20% contra 30% de media
        self.assertTrue(any("Conversão caiu" in a["titulo"] for a in alertas))


class PermissaoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.outra = Empresa.objects.create(nome="Rede B", slug="rede-b")
        self.loja1 = Loja.objects.create(empresa=self.empresa, nome="Loja 1", slug="loja-1")
        self.loja2 = Loja.objects.create(empresa=self.empresa, nome="Loja 2", slug="loja-2")
        self.gerente = Usuario.objects.create_user("g@a.com", "SenhaGer2026!", papel="gerente", empresa=self.empresa)
        self.gerente.lojas.set([self.loja1])

    def test_gerente_ve_so_alertas_da_loja_dele(self):
        self.client.force_login(self.gerente)
        resposta = self.client.get(reverse("alertas", args=["rede-a"]))
        self.assertContains(resposta, "Loja 1")
        self.assertNotContains(resposta, "Loja 2")

    def test_outra_empresa_nao_abre(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse("alertas", args=["rede-b"])).status_code, 404)
