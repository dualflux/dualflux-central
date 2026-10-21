"""Testes das Configuracoes: minha conta e horarios das lojas."""

from django.test import TestCase
from django.urls import reverse

from lojas.models import HorarioFuncionamento, Loja

from .models import Empresa, Usuario


def dias(abertos, abre="08:00", fecha="18:00"):
    dados = {}
    for d in range(7):
        if d in abertos:
            dados[f"aberta_{d}"] = "1"
        dados[f"abre_{d}"], dados[f"fecha_{d}"] = abre, fecha
    return dados


class ConfiguracoesTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.loja = Loja.objects.create(empresa=self.empresa, nome="Loja 1", slug="loja-1")
        self.dono = Usuario.objects.create_user("dono@a.com", "SenhaDono2026!", papel="dono", empresa=self.empresa)
        self.gerente = Usuario.objects.create_user("g@a.com", "SenhaGer2026!", papel="gerente", empresa=self.empresa)
        self.url_h = reverse("horarios_loja", args=["rede-a", "loja-1"])

    def test_qualquer_um_corrige_o_proprio_nome(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse("configuracoes", args=["rede-a"]), {"first_name": "Bia", "last_name": "Souza"})
        self.gerente.refresh_from_db()
        self.assertEqual(self.gerente.get_full_name(), "Bia Souza")

    def test_dono_salva_horarios(self):
        self.client.force_login(self.dono)
        self.client.post(self.url_h, dias({0, 1, 2, 3, 4}, "07:00", "22:00"))
        self.assertEqual(sorted(self.loja.horarios.values_list("dia_semana", flat=True)), [0, 1, 2, 3, 4])

    def test_nao_deixa_todos_os_dias_fechados(self):
        HorarioFuncionamento.objects.create(loja=self.loja, dia_semana=0, abre="08:00", fecha="18:00")
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url_h, dias(set()))
        self.assertContains(resposta, "pelo menos um dia aberto")
        self.assertEqual(self.loja.horarios.count(), 1)  # nada foi apagado

    def test_fechar_antes_de_abrir_e_recusado(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url_h, dias({0}, "18:00", "08:00"))
        self.assertContains(resposta, "Fechar deve ser depois de abrir")
        self.assertEqual(self.loja.horarios.count(), 0)

    def test_gerente_nao_edita_horarios(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(self.url_h).status_code, 404)
