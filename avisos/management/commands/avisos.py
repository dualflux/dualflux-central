"""
python manage.py avisos            -> fica rodando: le o robo do Telegram e envia o que estiver na hora.
python manage.py avisos --uma-vez  -> uma passada so (para testar, ou para rodar pelo cron).

Rode UMA copia so (duas copias mandariam a mesma mensagem duas vezes).
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from avisos.agenda import ciclo
from avisos.canais import ErroEnvio, telegram_configurado
from avisos.telegram import processar_atualizacoes

log = logging.getLogger(__name__)

INTERVALO_AGENDA = 60  # segundos entre as conferencias de horario
ESPERA_TELEGRAM = 20   # segundos que o Telegram segura a pergunta esperando mensagem nova


class Command(BaseCommand):
    help = "Envia os relatórios e alertas (Telegram/e-mail) e atende o robô do Telegram."

    def add_arguments(self, parser):
        parser.add_argument("--uma-vez", action="store_true", help="Faz uma passada e termina.")

    def handle(self, *args, **opcoes):
        if not telegram_configurado():
            self.stdout.write(self.style.WARNING("Telegram não configurado (TELEGRAM_BOT_TOKEN vazio): só e-mail."))

        if opcoes["uma_vez"]:
            self._ler_telegram(0)
            self.stdout.write(f"Avisos enviados: {ciclo()}")
            return

        self.stdout.write(self.style.SUCCESS("Avisos DualFlux rodando. Ctrl+C para parar."))
        ultima_agenda = 0.0
        try:
            while True:
                close_old_connections()
                if telegram_configurado():
                    self._ler_telegram(ESPERA_TELEGRAM)
                else:
                    time.sleep(INTERVALO_AGENDA)
                if time.monotonic() - ultima_agenda >= INTERVALO_AGENDA:
                    ultima_agenda = time.monotonic()
                    try:
                        enviados = ciclo()
                        if enviados:
                            self.stdout.write(f"Avisos enviados: {enviados}")
                    except Exception:
                        log.exception("Erro no ciclo de avisos")
                        time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Parado.")

    def _ler_telegram(self, espera):
        try:
            lidas = processar_atualizacoes(espera)
            if lidas is None:
                time.sleep(2)  # a tela estava lendo ao mesmo tempo: espera um pouco
            elif lidas:
                self.stdout.write(f"Mensagens do robô tratadas: {lidas}")
        except ErroEnvio as erro:
            self.stdout.write(self.style.WARNING(f"Telegram: {erro}"))
            time.sleep(5)
