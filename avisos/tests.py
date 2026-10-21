"""Testes dos Avisos: preferencias, conexao do Telegram, mensagens, agenda e permissoes.

Nenhum teste fala com o Telegram de verdade: as chamadas sao simuladas (mock).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contas.models import Empresa, Usuario
from lojas.models import Loja

from .agenda import ciclo
from .canais import ErroEnvio, enviar, Mensagem
from .mensagens import resumo_diario
from .models import EnvioAviso, PreferenciaAviso
from .telegram import processar_atualizacoes, tratar_mensagem


def serie_falsa(loja, inicio, fim):
    dias, dia = [], inicio
    while dia <= fim:
        dias.append({"dia": dia, "entradas": 400, "vendas": 120, "faturamento": Decimal("0")})
        dia += timedelta(days=1)
    return dias


def msg_privada(chat_id, texto, nome="Ana"):
    return {"chat": {"id": chat_id, "type": "private"}, "from": {"first_name": nome}, "text": texto}


@override_settings(TELEGRAM_BOT_TOKEN="token-de-teste", TELEGRAM_BOT_USUARIO="DualFluxAvisosBot",
                   DUALFLUX_SITE_URL="https://app.exemplo.com.br",
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.empresa = Empresa.objects.create(nome="Rede A", slug="rede-a")
        self.outra = Empresa.objects.create(nome="Rede B", slug="rede-b")
        self.loja1 = Loja.objects.create(empresa=self.empresa, nome="Loja 1", slug="loja-1")
        self.loja2 = Loja.objects.create(empresa=self.empresa, nome="Loja 2", slug="loja-2")
        self.dono = Usuario.objects.create_user("dono@a.com", "SenhaDono2026!", papel="dono", empresa=self.empresa)
        self.gerente = Usuario.objects.create_user("g@a.com", "SenhaGer2026!", papel="gerente", empresa=self.empresa)
        self.gerente.lojas.set([self.loja1])
        self.url = reverse("notificacoes", args=["rede-a"])
        patcher = patch("avisos.mensagens.serie_diaria", serie_falsa)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pref_pronta(self, usuario, **campos):
        pref, _ = PreferenciaAviso.objects.get_or_create(usuario=usuario)
        pref.aceite_em = timezone.now()
        pref.telegram_chat_id = campos.pop("chat_id", 1000 + usuario.pk)
        for nome, valor in campos.items():
            setattr(pref, nome, valor)
        pref.save()
        return pref


class TelaTests(Base):
    def test_exige_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_outra_empresa_nao_abre(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse("notificacoes", args=["rede-b"])).status_code, 404)

    def test_receber_sem_aceite_e_recusado(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url, {"receber_diario": "on", "horario": "07:30", "canal_email": "on"})
        self.assertContains(resposta, "marque que aceita")
        self.assertIsNone(PreferenciaAviso.objects.get(usuario=self.dono).aceite_em)

    def test_salva_com_aceite(self):
        self.client.force_login(self.dono)
        self.client.post(self.url, {"receber_diario": "on", "horario": "06:30", "canal_email": "on", "aceite": "on"})
        pref = PreferenciaAviso.objects.get(usuario=self.dono)
        self.assertIsNotNone(pref.aceite_em)
        self.assertEqual(pref.horario, time(6, 30))
        self.assertFalse(pref.receber_semanal)

    def test_tirar_aceite_para_os_envios(self):
        self.pref_pronta(self.dono)
        self.client.force_login(self.dono)
        self.client.post(self.url, {"horario": "07:30"})
        self.assertIsNone(PreferenciaAviso.objects.get(usuario=self.dono).aceite_em)

    def test_conectar_abre_o_robo_com_codigo(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse("conectar_telegram", args=["rede-a"]))
        self.assertTrue(resposta["Location"].startswith("https://t.me/DualFluxAvisosBot?start="))
        codigo = resposta["Location"].split("start=")[1]
        self.assertEqual(PreferenciaAviso.pelo_codigo_telegram(codigo).usuario, self.dono)
        self.assertNotIn(codigo, PreferenciaAviso.objects.get(usuario=self.dono).telegram_codigo_hash)  # so o hash

    def test_conectar_so_por_post(self):
        self.client.force_login(self.dono)
        self.assertEqual(self.client.get(reverse("conectar_telegram", args=["rede-a"])).status_code, 405)

    @patch("avisos.canais.telegram_responder")
    def test_enviar_teste_por_email(self, _):
        self.pref_pronta(self.dono, chat_id=None, canal_telegram=False, canal_email=True)
        self.client.force_login(self.dono)
        self.client.post(reverse("enviar_teste_aviso", args=["rede-a"]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Loja 1", mail.outbox[0].body)
        self.assertTrue(EnvioAviso.objects.filter(usuario=self.dono, tipo="teste", ok=True).exists())


class TelegramTests(Base):
    def setUp(self):
        super().setUp()
        patcher = patch("avisos.telegram.telegram_responder")
        self.responder = patcher.start()
        self.addCleanup(patcher.stop)
        self.pref = PreferenciaAviso.objects.create(usuario=self.dono)

    def test_start_com_codigo_conecta(self):
        codigo = self.pref.novo_codigo_telegram()
        tratar_mensagem(msg_privada(555, f"/start {codigo}"))
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.telegram_chat_id, 555)
        self.assertEqual(self.pref.telegram_nome, "Ana")
        self.assertEqual(self.pref.telegram_codigo_hash, "")  # codigo de uso unico

    def test_codigo_nao_serve_duas_vezes(self):
        codigo = self.pref.novo_codigo_telegram()
        tratar_mensagem(msg_privada(555, f"/start {codigo}"))
        tratar_mensagem(msg_privada(777, f"/start {codigo}"))
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.telegram_chat_id, 555)

    def test_codigo_vencido_nao_conecta(self):
        codigo = self.pref.novo_codigo_telegram()
        PreferenciaAviso.objects.filter(pk=self.pref.pk).update(telegram_codigo_em=timezone.now() - timedelta(hours=1))
        tratar_mensagem(msg_privada(555, f"/start {codigo}"))
        self.pref.refresh_from_db()
        self.assertIsNone(self.pref.telegram_chat_id)

    def test_grupo_e_ignorado(self):
        codigo = self.pref.novo_codigo_telegram()
        tratar_mensagem({"chat": {"id": -1, "type": "group"}, "from": {}, "text": f"/start {codigo}"})
        self.pref.refresh_from_db()
        self.assertIsNone(self.pref.telegram_chat_id)
        self.responder.assert_not_called()

    def test_parar_desconecta(self):
        self.pref.conectar_telegram(555, "Ana")
        tratar_mensagem(msg_privada(555, "/parar"))
        self.pref.refresh_from_db()
        self.assertIsNone(self.pref.telegram_chat_id)

    def test_le_as_mensagens_e_guarda_a_posicao(self):
        codigo = self.pref.novo_codigo_telegram()
        atualizacoes = [{"update_id": 41, "message": msg_privada(555, f"/start {codigo}")}]
        with patch("avisos.telegram.chamar_telegram", return_value=atualizacoes) as chamada:
            self.assertEqual(processar_atualizacoes(0), 1)
            self.assertEqual(chamada.call_args[0][1]["offset"], 1)
        with patch("avisos.telegram.chamar_telegram", return_value=[]) as chamada:
            processar_atualizacoes(0)
            self.assertEqual(chamada.call_args[0][1]["offset"], 42)  # nao le de novo
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.telegram_chat_id, 555)

    def test_robo_bloqueado_desconecta(self):
        self.pref.conectar_telegram(555, "Ana")
        self.pref.aceite_em = timezone.now()
        self.pref.save()
        with patch("avisos.canais.telegram_responder", side_effect=ErroEnvio("bloqueado", bloqueado=True)):
            resultado = enviar(self.pref, Mensagem("t", "<b>oi</b>"), EnvioAviso.Tipo.TESTE)
        self.assertEqual(resultado[0][1], False)
        self.pref.refresh_from_db()
        self.assertIsNone(self.pref.telegram_chat_id)


class MensagemTests(Base):
    def test_gerente_so_ve_a_loja_dele(self):
        mensagem = resumo_diario(self.gerente, self.empresa, date(2026, 10, 20))
        self.assertIn("Loja 1", mensagem.html)
        self.assertNotIn("Loja 2", mensagem.html)
        self.assertIn("https://app.exemplo.com.br/rede-a/loja-1/", mensagem.html)

    def test_dono_ve_a_rede(self):
        mensagem = resumo_diario(self.dono, self.empresa, date(2026, 10, 20))
        self.assertIn("Loja 2", mensagem.html)
        self.assertIn("Rede", mensagem.html)
        self.assertIn("30,0%", mensagem.html)  # 120 de 400

    def test_texto_puro_para_email(self):
        texto = resumo_diario(self.dono, self.empresa, date(2026, 10, 20)).texto
        self.assertNotIn("<b>", texto)
        self.assertIn("Abrir o painel: https://app.exemplo.com.br/rede-a/", texto)


class AgendaTests(Base):
    def em(self, dia, hora, minuto=0):
        return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=ZoneInfo(timezone.get_current_timezone_name()))

    @patch("avisos.canais.telegram_responder")
    def test_diario_sai_uma_vez_depois_do_horario(self, responder):
        self.pref_pronta(self.dono, receber_semanal=False, receber_alertas=False)
        terca = date(2026, 10, 20)
        ciclo(self.em(terca, 7, 0))
        self.assertEqual(responder.call_count, 0)  # antes das 07:30
        ciclo(self.em(terca, 7, 31))
        ciclo(self.em(terca, 9, 0))
        self.assertEqual(responder.call_count, 1)  # uma vez so no dia
        ciclo(self.em(terca + timedelta(days=1), 7, 31))
        self.assertEqual(responder.call_count, 2)

    @patch("avisos.canais.telegram_responder")
    def test_semanal_so_na_segunda(self, responder):
        self.pref_pronta(self.dono, receber_diario=False, receber_alertas=False)
        ciclo(self.em(date(2026, 10, 20), 8))  # terca
        self.assertEqual(responder.call_count, 0)
        ciclo(self.em(date(2026, 10, 19), 8))  # segunda
        self.assertEqual(responder.call_count, 1)

    @patch("avisos.canais.telegram_responder")
    def test_sem_aceite_nada_sai(self, responder):
        pref = self.pref_pronta(self.dono)
        pref.aceite_em = None
        pref.save()
        ciclo(self.em(date(2026, 10, 19), 9))
        responder.assert_not_called()

    @patch("avisos.canais.telegram_responder")
    def test_empresa_suspensa_nao_recebe(self, responder):
        self.pref_pronta(self.dono)
        Empresa.objects.filter(pk=self.empresa.pk).update(status="suspensa")
        ciclo(self.em(date(2026, 10, 19), 9))
        responder.assert_not_called()

    @patch("avisos.canais.telegram_responder")
    def test_alerta_urgente_nao_repete(self, responder):
        self.pref_pronta(self.gerente, receber_diario=False, receber_semanal=False)
        status_falso = SimpleNamespace(objects=SimpleNamespace(filter=lambda **_: [SimpleNamespace(loja_id=self.loja1.pk)]))
        alerta = [{"gravidade": "urgente", "titulo": "Loja sem sinal", "texto": "Parou de enviar."}]
        with patch("avisos.agenda.StatusLoja", status_falso), patch("avisos.agenda.alertas_de_agora", return_value=alerta):
            agora = timezone.now()
            ciclo(agora)
            ciclo(agora + timedelta(minutes=5))
            self.assertEqual(responder.call_count, 1)
