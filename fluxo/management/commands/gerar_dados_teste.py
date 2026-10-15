"""
Comando: gera dados de TESTE de fluxo E de vendas para uma loja.

Uso (dentro do container):
    python manage.py gerar_dados_teste --loja loja-centro --dias 42 --limpar

Entradas: falsas, mas com o "formato" de uma farmacia real:
- picos de manha (8-10h), almoco (12-13h) e fim de tarde (17-19h);
- sabado um pouco menor, domingo bem menor;
- variacao aleatoria de um dia para o outro;
- so dentro do horario de funcionamento da loja.

Vendas: criadas A PARTIR das entradas, janela por janela de 15 minutos,
com conversao diferente por turno (de proposito, para o dashboard
contar uma historia):
- manha ~31%, tarde ~24% (pico com balcao sobrecarregado), noite ~34%.

PROTECAO: so roda com DEBUG=True (nunca em producao).
"""

import random
import uuid
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from fluxo.models import Evento, VendaJanela
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

# Conversao de teste por turno (mesmos cortes da tela: manha <12h, tarde 12-18h, noite >=18h).
CONVERSAO_POR_TURNO = [(12, 0.31), (18, 0.24), (24, 0.34)]  # (hora final do turno, conversao)

# Valor medio de UMA venda (ticket) e sua variacao, em reais.
TICKET_MEDIO = 62.0
TICKET_VARIACAO = 18.0


def conversao_da_hora(hora):
    """Conversao de teste conforme o turno da hora."""
    for hora_final, conversao in CONVERSAO_POR_TURNO:
        if hora < hora_final:
            return conversao
    return CONVERSAO_POR_TURNO[-1][1]


class Command(BaseCommand):
    help = "Gera entradas e vendas FALSAS (mas realistas) para testar o dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--loja", required=True, help="Endereco (slug) da loja. Ex.: loja-centro")
        parser.add_argument("--dias", type=int, default=42, help="Quantos dias para tras (padrao 42 = 6 semanas)")
        parser.add_argument("--limpar", action="store_true",
                            help="Apaga TODOS os eventos e vendas da loja antes de gerar")
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
            vendas_apagadas, _ = VendaJanela.objects.filter(loja=loja).delete()
            self.stdout.write(f"Apagados {apagados} eventos e {vendas_apagadas} janelas de vendas antigas da loja.")

        hoje = timezone.localdate()
        eventos = []
        # Conta as entradas de cada janela de 15 min (hora local): base das vendas.
        entradas_por_janela = Counter()

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
                    # Janela de 15 min desta entrada (ex.: 10:37 -> 10:30).
                    janela = entrada.replace(minute=entrada.minute // 15 * 15, second=0, microsecond=0)
                    entradas_por_janela[janela] += 1

        # Grava em blocos de 5.000: bem mais rapido que um por um.
        Evento.objects.bulk_create(eventos, batch_size=5000)

        vendas = self._vendas_das_janelas(loja, entradas_por_janela, fuso)
        VendaJanela.objects.bulk_create(vendas, batch_size=5000)

        entradas = len(eventos) // 2
        total_vendas = sum(venda.transacoes for venda in vendas)
        faturamento = sum(venda.faturamento for venda in vendas)
        conversao = total_vendas / entradas * 100 if entradas else 0
        self.stdout.write(self.style.SUCCESS(
            f"Gerados {entradas} entradas e {total_vendas} vendas (conversao {conversao:.1f}%, "
            f"faturamento R$ {faturamento:,.2f}) em {opcoes['dias']} dias para {loja}."
        ))

    @staticmethod
    def _vendas_das_janelas(loja, entradas_por_janela, fuso):
        """
        Para cada janela de 15 min: cada entrada "decide" se compra,
        com a probabilidade do turno; cada compra recebe um valor sorteado.
        """
        vendas = []
        for janela, entradas in entradas_por_janela.items():
            conversao = conversao_da_hora(janela.hour)
            transacoes = sum(1 for _ in range(entradas) if random.random() < conversao)
            valor = sum(max(5.0, random.gauss(TICKET_MEDIO, TICKET_VARIACAO)) for _ in range(transacoes))
            vendas.append(VendaJanela(
                loja=loja,
                janela_inicio=janela.replace(tzinfo=fuso),
                transacoes=transacoes,
                faturamento=Decimal(f"{valor:.2f}"),
            ))
        return vendas

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