"""
Consultas do dashboard: as PERGUNTAS que as telas fazem ao banco.

As telas so chamam estas funcoes e desenham o resultado. Assim:
- as contas podem ser testadas sem navegador;
- a mesma funcao serve para tela, relatorio em PDF ou e-mail semanal;
- se um dia trocarmos a contagem direta por totais prontos (FluxoJanela),
  so este arquivo muda.

Regras comuns:
- tudo na HORA LOCAL da loja (fuso_horario do cadastro);
- so ENTRADAS (cada pessoa conta uma vez, ao entrar);
- eventos antes de loja.dados_validos_desde (testes da instalacao) ficam de fora.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.db.models.functions import ExtractHour, TruncDate

from .models import Evento

NOMES_DIAS = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]


def _entradas_por_dia_e_hora(loja, data_inicial, data_final):
    """
    A consulta-base de todo o dashboard.
    Devolve {(dia, hora): entradas}, ja na hora local da loja.

    O agrupamento e feito PELO BANCO (uma linha por dia+hora), entao
    mesmo com milhoes de eventos so voltam algumas centenas de linhas.
    """
    fuso = ZoneInfo(loja.fuso_horario)
    # Periodo em hora local, convertido para instantes com fuso.
    inicio = datetime.combine(data_inicial, time.min, tzinfo=fuso)
    fim = datetime.combine(data_final + timedelta(days=1), time.min, tzinfo=fuso)

    eventos = Evento.objects.filter(
        loja=loja, direcao=Evento.Direcao.ENTRADA, instante__gte=inicio, instante__lt=fim
    )
    if loja.dados_validos_desde:
        eventos = eventos.filter(instante__gte=loja.dados_validos_desde)

    linhas = (
        eventos
        # tzinfo=fuso: o banco converte de UTC para a hora local ANTES de agrupar.
        .annotate(dia=TruncDate("instante", tzinfo=fuso), hora=ExtractHour("instante", tzinfo=fuso))
        .values("dia", "hora")
        .annotate(total=Count("id"))
    )
    return {(linha["dia"], linha["hora"]): linha["total"] for linha in linhas}


def entradas_por_dia(loja, data_inicial, data_final):
    """Lista [(dia, entradas)] para todos os dias do periodo (dias sem dado = 0)."""
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    por_dia = defaultdict(int)
    for (dia, _hora), total in contagem.items():
        por_dia[dia] += total

    resultado = []
    dia = data_inicial
    while dia <= data_final:
        resultado.append((dia, por_dia.get(dia, 0)))
        dia += timedelta(days=1)
    return resultado


def media_por_hora_do_dia(loja, data_inicial, data_final):
    """
    Lista [(hora, media_de_entradas)] de 0 a 23h.
    Media = total daquela hora / numero de dias COM movimento no periodo.
    """
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    dias_com_movimento = {dia for (dia, _hora) in contagem}
    if not dias_com_movimento:
        return [(hora, 0) for hora in range(24)]

    por_hora = defaultdict(int)
    for (_dia, hora), total in contagem.items():
        por_hora[hora] += total
    return [(hora, round(por_hora.get(hora, 0) / len(dias_com_movimento), 1)) for hora in range(24)]


def pontas_do_dia(loja, data_inicial, data_final):
    """
    Analise das pontas do dia, por dia da semana:
    media de entradas na PRIMEIRA e na ULTIMA hora de funcionamento,
    comparada com a media de uma hora qualquer daquele dia.

    indice = ponta / media_por_hora * 100
      > 100  -> a ponta e mais movimentada que a media (procura forte)
      < 100  -> a ponta e mais fraca que a media (avaliar o horario)

    Simplificacao: considera horarios em hora cheia (ex.: abre 07:00).
    """
    horarios = {h.dia_semana: (h.abre, h.fecha) for h in loja.horarios.all()}
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)

    # Junta, por dia da semana, os totais de cada dia do periodo.
    acumulado = defaultdict(lambda: {"dias": 0, "primeira": 0, "ultima": 0, "total": 0, "horas_abertas": 0})
    dias_do_periodo = {dia for (dia, _hora) in contagem}
    for dia in dias_do_periodo:
        semana = dia.weekday()
        if semana not in horarios:
            continue
        abre, fecha = horarios[semana]
        ultima_hora = (fecha.hour - 1) if fecha.minute == 0 else fecha.hour
        horas_abertas = ultima_hora - abre.hour + 1

        dado = acumulado[semana]
        dado["dias"] += 1
        dado["primeira"] += contagem.get((dia, abre.hour), 0)
        dado["ultima"] += contagem.get((dia, ultima_hora), 0)
        dado["total"] += sum(contagem.get((dia, hora), 0) for hora in range(abre.hour, ultima_hora + 1))
        dado["horas_abertas"] = horas_abertas

    resultado = []
    for semana in sorted(acumulado):
        dado = acumulado[semana]
        dias = dado["dias"]
        media_hora = dado["total"] / dias / dado["horas_abertas"]
        primeira = dado["primeira"] / dias
        ultima = dado["ultima"] / dias
        abre, fecha = horarios[semana]
        resultado.append({
            "dia_semana": NOMES_DIAS[semana],
            "horario": f"{abre:%H:%M}-{fecha:%H:%M}",
            "dias_analisados": dias,
            "media_por_hora": round(media_hora, 1),
            "primeira_hora": round(primeira, 1),
            "indice_primeira": round(primeira / media_hora * 100) if media_hora else 0,
            "ultima_hora": round(ultima, 1),
            "indice_ultima": round(ultima / media_hora * 100) if media_hora else 0,
        })
    return resultado