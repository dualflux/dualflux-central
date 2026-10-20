"""Enderecos reservados: nenhuma empresa ou loja pode usar os nomes das telas."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from lojas.models import validar_slug_loja

from .models import validar_slug_livre


class SlugsReservadosTests(SimpleTestCase):
    def test_empresa_nao_usa_endereco_do_sistema(self):
        for nome in ("clientes", "acesso", "conta", "admin", "api", "login"):
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                validar_slug_livre(nome)

    def test_loja_nao_usa_endereco_do_sistema(self):
        for nome in ("relatorios", "equipe"):
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                validar_slug_loja(nome)

    def test_nomes_normais_continuam_livres(self):
        validar_slug_livre("farmacia-central")
        validar_slug_loja("loja-centro")
