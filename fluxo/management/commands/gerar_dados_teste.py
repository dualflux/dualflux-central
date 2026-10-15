"""
Comando: gera dados de TESTE de fluxo para uma loja.

Uso (dentro do container):
    python manage.py gerar_dados_teste --loja loja-centro --dias 42 --limpar

Cria eventos falsos, mas com o "formato" de uma farmacia real:
- picos de manha (8-10h), almoco (12-13h) e fim de tarde (17-19h);
- sabado um pouco menor, domingo bem menor;
- variacao aleatoria de um dia para o outro;
- so dentro do horario de funcionamento da loja.

PROTECAO: so roda com DEBUG=True (nunca em producao).
"""

import random
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from fluxo.models import Evento
from lojas.models import Camera, HorarioFuncionamento, Loja

# Horario tipico de farmacia, usado nos dias que a loja ainda nao tiver cadastrado.
# Chave: dia da semana (segunda = 0 ... domingo = 6).
HORARIO_PADRAO = {
    0: (time(7), time(22)), 1: (time(7), time(22)), 2: (time(7), time(22)),
    3: (time(7), time(22)), 4: (time(7), time(22)),
    5: (time(8), time(20)),   # sabado
    6: (time(8), time(14)),   # domingo
}

# Media de entradas em cada hora do dia: e o "desenho" do movimento.
MEDIA_POR_HORA = {
    6: 5, 7: 12, 8: 30, 9: 34, 10: 28, 11: 26, 12: 32, 13: 30, 14: 22,
    15: 22, 16: 26, 17: 38, 18: 42, 19: 34, 20: 22, 21: 14, 22: 8, 23: 5,
}

# Peso de cada dia da semana (sexta um pouco mais forte, domingo bem mais fraco).
PESO_DO_DIA = {0: 1.05, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.1, 5: 0.85, 6: 0.55}


class Command(BaseCommand):
    help = "Gera eventos de fluxo FALSOS (mas realistas) para testar o dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--loja", required=True, help="Endereco (slug) da loja. Ex.: loja-centro")
        parser.add_argument("--dias", type=int, default=42, help="Quantos dias para tras (padrao 42 = 6 semanas)")
        parser.add_argument("--limpar", action="store_true", help="Apaga TODOS os eventos da loja antes de gerar")
        parser.add_argument("--semente", type=int, default=42,
                            help="Semente do sorteio: a mesma semente gera sempre os mesmos dados")

    def handle(self, *args, **opcoes):
        # Trava de seguranca: nunca rodar em producao.
        if not settings.DEBUG:
            raise CommandError("Comando de TESTE: so roda com DJANGO_DEBUG=True. Nunca em producao.")

        lojas = Loja.objects.filter(slug=opcoes["loja"])
        if lojas.count() != 1:
            raise CommandError(f'Loja "{opcoes["loja"]}" nao encontrada (ou existe em mais de uma empresa).')
        loja = lojas.get()

        random.seed(opcoes["semente"])
        fuso = ZoneInfo(loja.fuso_horario)
        camera, _ = Camera.objects.get_or_create(loja=loja, codigo="cam1", defaults={"nome": "Porta principal"})
        horarios = self._garantir_horarios(loja)

        if opcoes["limpar"]:
            apagados, _ = Evento.objects.filter(loja=loja).delete()
            self.stdout.write(f"Apagados {apagados} eventos antigos da loja.")

        hoje = timezone.localdate()
        eventos = []
        for dias_atras in range(opcoes["dias"], 0, -1):
            dia = hoje - timedelta(days=dias_atras)
            if dia.weekday() not in horarios:
                continue  # loja fechada neste dia da semana

            abre, fecha = horarios[dia.weekday()]
            abertura = datetime.combine(dia, abre)
            fechamento = datetime.combine(dia, fecha)
            humor_do_dia = random.uniform(0.8, 1.2)  # dias melhores e piores

            ultima_hora = fecha.hour + (1 if fecha.minute else 0)
            for hora in range(abre.hour, ultima_hora):
                inicio = max(datetime.combine(dia, time(hora)), abertura)
                fim = min(datetime.combine(dia, time(hora)) + timedelta(hours=1), fechamento)
                if fim <= inicio:
                    continue

                media = MEDIA_POR_HORA.get(hora, 10) * PESO_DO_DIA[dia.weekday()] * humor_do_dia
                quantidade = max(0, round(random.gauss(media, media * 0.25)))
                for _ in range(quantidade):
                    entrada = inicio + timedelta(seconds=random.uniform(0, (fim - inicio).total_seconds()))
                    saida = entrada + timedelta(minutes=random.uniform(2, 15))  # tempo dentro da loja
                    eventos.append(self._evento(loja, camera, "entrada", entrada, fuso))
                    eventos.append(self._evento(loja, camera, "saida", saida, fuso))

        # Grava em blocos de 5.000: bem mais rapido que um por um.
        Evento.objects.bulk_create(eventos, batch_size=5000)
        entradas = len(eventos) // 2
        self.stdout.write(self.style.SUCCESS(
            f"Gerados {len(eventos)} eventos ({entradas} entradas) em {opcoes['dias']} dias para {loja}."
        ))

    @staticmethod
    def _evento(loja, camera, direcao, horario_local, fuso):
        """Cria o Evento convertendo a hora local da loja para um horario com fuso."""
        return Evento(
            loja=loja, camera=camera, uuid=uuid.uuid4(),
            instante=horario_local.replace(tzinfo=fuso), direcao=direcao,
        )

    def _garantir_horarios(self, loja):
        """Completa os dias sem horario cadastrado com o horario padrao de farmacia."""
        existentes = {h.dia_semana: (h.abre, h.fecha) for h in loja.horarios.all()}
        for dia, (abre, fecha) in HORARIO_PADRAO.items():
            if dia not in existentes:
                HorarioFuncionamento.objects.create(loja=loja, dia_semana=dia, abre=abre, fecha=fecha)
                existentes[dia] = (abre, fecha)
                self.stdout.write(f"Horario padrao criado para o dia {dia} (0=segunda): {abre:%H:%M}-{fecha:%H:%M}")
        return existentes