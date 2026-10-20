"""Testes da tela Equipe: so o dono, so gerentes da propria empresa."""

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from lojas.models import Loja

from .models import Empresa, Usuario


class EquipeTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.outra = Empresa.objects.create(nome="Rede B", slug="rede-b")
        self.loja = Loja.objects.create(empresa=self.empresa, nome="Loja 1", slug="loja-1")
        self.loja_outra = Loja.objects.create(empresa=self.outra, nome="Loja X", slug="loja-x")
        self.dono = Usuario.objects.create_user("dono@a.com", "SenhaDono2026!", papel="dono", empresa=self.empresa)
        self.gerente = Usuario.objects.create_user("ger@a.com", "SenhaGer2026!", papel="gerente", empresa=self.empresa)
        self.gerente_b = Usuario.objects.create_user("ger@b.com", "SenhaGerB2026!", papel="gerente", empresa=self.outra)

    def test_dono_convida_gerente_sem_senha_e_com_codigo(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse("gerente_novo", args=["rede-a"]),
                                    {"first_name": "Ana", "email": "ana@a.com", "lojas": [self.loja.pk]})
        self.assertRedirects(resposta, reverse("equipe", args=["rede-a"]))
        ana = Usuario.objects.get(email="ana@a.com")
        self.assertEqual((ana.papel, ana.empresa), ("gerente", self.empresa))
        self.assertFalse(ana.has_usable_password())
        self.assertEqual(list(ana.lojas.all()), [self.loja])
        self.assertEqual(len(mail.outbox), 1)

    def test_dono_nao_pode_dar_loja_de_outra_empresa(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("gerente_novo", args=["rede-a"]),
                         {"first_name": "Ana", "email": "ana@a.com", "lojas": [self.loja_outra.pk]})
        self.assertFalse(Usuario.objects.filter(email="ana@a.com").exists())

    def test_gerente_nao_acessa_equipe(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse("equipe", args=["rede-a"])).status_code, 404)

    def test_dono_nao_mexe_em_gerente_de_outra_empresa(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse("gerente_ativar", args=["rede-a", self.gerente_b.pk]))
        self.assertEqual(resposta.status_code, 404)
        self.gerente_b.refresh_from_db()
        self.assertTrue(self.gerente_b.is_active)

    def test_dono_nao_desativa_a_si_mesmo(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse("gerente_ativar", args=["rede-a", self.dono.pk]))
        self.assertEqual(resposta.status_code, 404)

    def test_desativar_corta_o_acesso_na_hora(self):
        cliente_gerente = self.client_class()
        cliente_gerente.force_login(self.gerente)
        self.client.force_login(self.dono)
        self.client.post(reverse("gerente_ativar", args=["rede-a", self.gerente.pk]))
        resposta = cliente_gerente.get(reverse("empresa_inicio", args=["rede-a"]))
        self.assertEqual(resposta.status_code, 302)  # mandado para o login

    def test_acao_por_get_nao_funciona(self):
        self.client.force_login(self.dono)
        self.assertEqual(self.client.get(reverse("gerente_ativar", args=["rede-a", self.gerente.pk])).status_code, 405)
