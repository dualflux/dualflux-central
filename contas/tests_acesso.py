"""Testes do acesso por codigo (esqueci a senha / primeiro acesso)."""

import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CodigoAcesso, Empresa, Usuario


class AcessoPorCodigoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Farmacia X", slug="farmacia-x")
        self.usuario = Usuario.objects.create_user(
            "dono@x.com", "SenhaAntiga2026", papel=Usuario.Papel.DONO, empresa=self.empresa)

    def pedir_codigo(self, email="dono@x.com"):
        self.client.post(reverse("esqueci_senha"), {"email": email})
        if not mail.outbox:
            return None
        return re.search(r"Seu código: (\d{3}) (\d{3})", mail.outbox[-1].body).group(0)[-7:].replace(" ", "")

    def test_email_inexistente_tem_a_mesma_resposta_e_nao_envia(self):
        resposta = self.client.post(reverse("esqueci_senha"), {"email": "ninguem@x.com"})
        self.assertRedirects(resposta, reverse("confirmar_codigo"))
        self.assertEqual(len(mail.outbox), 0)

    def test_fluxo_completo_troca_a_senha_e_entra(self):
        codigo = self.pedir_codigo()
        self.assertEqual(len(codigo), 6)
        resposta = self.client.post(reverse("confirmar_codigo"), {"email": "dono@x.com", "codigo": codigo})
        self.assertRedirects(resposta, reverse("nova_senha"))
        self.client.post(reverse("nova_senha"), {"new_password1": "NovaSenhaForte!2026", "new_password2": "NovaSenhaForte!2026"})
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("NovaSenhaForte!2026"))
        # Codigo de uso unico: nao vale de novo.
        resposta = self.client.post(reverse("confirmar_codigo"), {"email": "dono@x.com", "codigo": codigo})
        self.assertEqual(resposta.status_code, 200)

    def test_cinco_erros_anulam_o_codigo(self):
        codigo = self.pedir_codigo()
        errado = "000000" if codigo != "000000" else "111111"
        for _ in range(5):
            self.client.post(reverse("confirmar_codigo"), {"email": "dono@x.com", "codigo": errado})
        resposta = self.client.post(reverse("confirmar_codigo"), {"email": "dono@x.com", "codigo": codigo})
        self.assertEqual(resposta.status_code, 200)  # nem o certo vale mais

    def test_codigo_expirado_nao_vale(self):
        codigo = self.pedir_codigo()
        CodigoAcesso.objects.update(expira_em=timezone.now() - timedelta(minutes=1))
        resposta = self.client.post(reverse("confirmar_codigo"), {"email": "dono@x.com", "codigo": codigo})
        self.assertEqual(resposta.status_code, 200)

    def test_nova_senha_sem_codigo_volta_para_o_inicio(self):
        resposta = self.client.get(reverse("nova_senha"))
        self.assertRedirects(resposta, reverse("esqueci_senha"))

    def test_codigo_nao_fica_gravado_em_texto(self):
        codigo = self.pedir_codigo()
        self.assertNotIn(codigo, CodigoAcesso.objects.get().codigo_hash)
