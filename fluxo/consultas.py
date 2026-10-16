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

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


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

def pontas_por_dia(loja, data_inicial, data_final):
    """
    Pontas do dia avaliadas DIA A DIA contra a media do PERIODO.

    1) Media de abertura do periodo = media das entradas na PRIMEIRA hora
       de funcionamento, considerando todos os dias com movimento.
    2) Media de fechamento do periodo = o mesmo, na ULTIMA hora.
    3) Cada dia: a abertura dele comparada com a media de abertura,
       e o fechamento dele comparado com a media de fechamento.

    indice = valor do dia / media do periodo * 100  (100 = igual a media)
    """
    horarios = {h.dia_semana: (h.abre, h.fecha) for h in loja.horarios.all()}
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)

    # 1) Abertura e fechamento de cada dia com movimento.
    linhas = []
    for dia in sorted({dia for (dia, _hora) in contagem}):
        semana = dia.weekday()
        if semana not in horarios:
            continue  # dia em que a loja nao abre
        abre, fecha = horarios[semana]
        ultima_hora = (fecha.hour - 1) if fecha.minute == 0 else fecha.hour
        linhas.append({
            "data": dia,
            "dia_semana": NOMES_DIAS[semana],
            "horario": f"{abre:%H:%M}-{fecha:%H:%M}",
            "abertura": contagem.get((dia, abre.hour), 0),
            "fechamento": contagem.get((dia, ultima_hora), 0),
        })

    if not linhas:
        return {"media_abertura": 0, "media_fechamento": 0, "dias": []}

    # 2) As duas reguas do periodo.
    media_abertura = sum(linha["abertura"] for linha in linhas) / len(linhas)
    media_fechamento = sum(linha["fechamento"] for linha in linhas) / len(linhas)

    # 3) Cada dia comparado com a regua correspondente.
    for linha in linhas:
        linha["indice_abertura"] = round(linha["abertura"] / media_abertura * 100) if media_abertura else 0
        linha["indice_fechamento"] = round(linha["fechamento"] / media_fechamento * 100) if media_fechamento else 0

    return {
        "media_abertura": round(media_abertura, 1),
        "media_fechamento": round(media_fechamento, 1),
        "dias": linhas,
    }

# Turnos usados na rosca "entradas por turno": (nome, hora inicial, hora final).
# A hora final NAO entra no turno: "Tarde" vai das 12:00 ate 17:59.
TURNOS = [("Manhã", 0, 12), ("Tarde", 12, 18), ("Noite", 18, 24)]


def entradas_por_turno(loja, data_inicial, data_final):
    """Lista [(turno, entradas)] no periodo: quanto do movimento cai em cada turno."""
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    totais = {nome: 0 for nome, _inicio, _fim in TURNOS}
    for (_dia, hora), total in contagem.items():
        for nome, inicio, fim in TURNOS:
            if inicio <= hora < fim:
                totais[nome] += total
                break
    return list(totais.items())


def entradas_por_dia_da_semana(loja, data_inicial, data_final):
    """Lista [(dia da semana, entradas)] no periodo: o peso de cada dia no total."""
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    totais = [0] * 7
    for (dia, _hora), total in contagem.items():
        totais[dia.weekday()] += total
    return list(zip(NOMES_DIAS, totais))

# ======================================================================
# PACOTE DE INDICADORES: entradas e vendas SEMPRE juntas.
# Regra do produto: venda nunca aparece sozinha. Toda tela que mostra
# venda recebe, da mesma funcao, as entradas e a conversao do mesmo grupo.
# ======================================================================
from decimal import Decimal

from django.db.models import Sum

from .models import VendaJanela


def _vendas_por_dia_e_hora(loja, data_inicial, data_final):
    """
    Igual a _entradas_por_dia_e_hora, mas para as vendas.
    Devolve {(dia, hora): (transacoes, faturamento)} na hora local da loja.
    """
    fuso = ZoneInfo(loja.fuso_horario)
    inicio = datetime.combine(data_inicial, time.min, tzinfo=fuso)
    fim = datetime.combine(data_final + timedelta(days=1), time.min, tzinfo=fuso)

    vendas = VendaJanela.objects.filter(loja=loja, janela_inicio__gte=inicio, janela_inicio__lt=fim)
    if loja.dados_validos_desde:
        vendas = vendas.filter(janela_inicio__gte=loja.dados_validos_desde)

    linhas = (
        vendas
        .annotate(dia=TruncDate("janela_inicio", tzinfo=fuso), hora=ExtractHour("janela_inicio", tzinfo=fuso))
        .values("dia", "hora")
        .annotate(transacoes=Sum("transacoes"), faturamento=Sum("faturamento"))
    )
    return {(linha["dia"], linha["hora"]): (linha["transacoes"], linha["faturamento"]) for linha in linhas}


def calcular_indicadores(entradas, vendas, faturamento):
    """
    Os seis numeros de um grupo. As razoes sao calculadas AQUI, no fim,
    a partir dos totais ja somados (nunca media de percentuais).
    Razao impossivel (divisao por zero) fica None = "sem dados".
    """
    return {
        "entradas": entradas,
        "vendas": vendas,
        "faturamento": faturamento,
        "conversao": round(vendas / entradas * 100, 1) if entradas else None,
        "ticket_medio": (faturamento / vendas).quantize(Decimal("0.01")) if vendas else None,
        "receita_por_visitante": (faturamento / entradas).quantize(Decimal("0.01")) if entradas else None,
    }


def indicadores_agrupados(loja, data_inicial, data_final, grupo_de, grupos_em_ordem):
    """
    Junta entradas e vendas do periodo e soma por GRUPO.

    grupo_de: funcao (dia, hora) -> nome do grupo (ex.: "Tarde", "Sexta").
    grupos_em_ordem: lista dos grupos na ordem de exibicao; grupo sem dado sai zerado.
    Devolve [(grupo, indicadores)].
    """
    entradas = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    vendas = _vendas_por_dia_e_hora(loja, data_inicial, data_final)

    # [entradas, vendas, faturamento] de cada grupo.
    somas = {grupo: [0, 0, Decimal("0")] for grupo in grupos_em_ordem}
    for (dia, hora), total in entradas.items():
        somas[grupo_de(dia, hora)][0] += total
    for (dia, hora), (transacoes, faturamento) in vendas.items():
        soma = somas[grupo_de(dia, hora)]
        soma[1] += transacoes
        soma[2] += faturamento

    return [(grupo, calcular_indicadores(*somas[grupo])) for grupo in grupos_em_ordem]


def turno_da_hora(hora):
    """Nome do turno de uma hora, pelos cortes de TURNOS."""
    for nome, inicio, fim in TURNOS:
        if inicio <= hora < fim:
            return nome
    return TURNOS[-1][0]


def indicadores_do_periodo(loja, data_inicial, data_final):
    """O resumo do topo da tela: os seis numeros do periodo inteiro."""
    return indicadores_agrupados(loja, data_inicial, data_final, lambda dia, hora: "periodo", ["periodo"])[0][1]


def indicadores_por_turno(loja, data_inicial, data_final):
    nomes = [nome for nome, _inicio, _fim in TURNOS]
    return indicadores_agrupados(loja, data_inicial, data_final, lambda dia, hora: turno_da_hora(hora), nomes)


def indicadores_por_dia_da_semana(loja, data_inicial, data_final):
    return indicadores_agrupados(
        loja, data_inicial, data_final, lambda dia, hora: NOMES_DIAS[dia.weekday()], NOMES_DIAS
    )
# ======================================================================
# MAPA DE HORARIOS (hora x dia), com cores relativas a propria loja
# ======================================================================

# Faixas de cor, da mais fraca a mais forte (alem de "vazio" = sem movimento).
FAIXAS_MAPA = ["baixo", "moderado", "alto", "muito-alto", "pico"]
NOMES_FAIXAS = {
    "vazio": "sem movimento", "baixo": "baixo", "moderado": "moderado",
    "alto": "alto", "muito-alto": "muito alto", "pico": "pico",
}


def _percentil(valores_ordenados, fracao):
    """Valor que deixa 'fracao' dos valores abaixo dele (ex.: 0.9 = os 10% mais altos ficam acima)."""
    if not valores_ordenados:
        return 0
    posicao = round(fracao * (len(valores_ordenados) - 1))
    return valores_ordenados[posicao]


def mapa_de_horarios(loja, data_inicial, data_final):
    """
    Grade hora x dia com as entradas, pronta para a tela.

    - Ate 7 dias: uma coluna por DATA (total de entradas).
    - Mais de 7 dias: uma coluna por DIA DA SEMANA (MEDIA de entradas daquela hora).
    - Linhas: so as horas de funcionamento da loja.
    - Cores RELATIVAS a propria loja: as faixas sao cortadas pelos percentis
      dos valores da grade (25%, 50%, 75%, 90%). "Pico" = os 10% mais altos.
    """
    contagem = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    horarios = {h.dia_semana: (h.abre, h.fecha) for h in loja.horarios.all()}

    def ultima_hora(fecha):
        return (fecha.hour - 1) if fecha.minute == 0 else fecha.hour

    # 1) Horas exibidas: da primeira abertura a ultima hora de funcionamento.
    if horarios:
        primeira = min(abre.hour for abre, _ in horarios.values())
        ultima = max(ultima_hora(fecha) for _, fecha in horarios.values())
    else:
        primeira, ultima = 0, 23
    horas = list(range(primeira, ultima + 1))

    # 2) Colunas: datas (periodo curto) ou dias da semana (periodo longo).
    #    "rotulos" = curtos, para o cabecalho da grade ("Sex 10/10");
    #    "nomes" = completos, para os destaques ("Sexta, 10/10").
    total_dias = (data_final - data_inicial).days + 1
    por_data = total_dias <= 7
    if por_data:
        colunas = [data_inicial + timedelta(days=n) for n in range(total_dias)]
        rotulos = [f"{NOMES_DIAS[dia.weekday()][:3]} {dia:%d/%m}" for dia in colunas]
        nomes = [f"{NOMES_DIAS[dia.weekday()]}, {dia:%d/%m}" for dia in colunas]

        def valor(coluna, hora):
            return contagem.get((coluna, hora), 0)
    else:
        colunas = list(range(7))
        rotulos = [nome[:3] for nome in NOMES_DIAS]
        nomes = list(NOMES_DIAS)
        somas = defaultdict(int)
        datas_da_semana = defaultdict(set)
        for (dia, hora), total in contagem.items():
            somas[(dia.weekday(), hora)] += total
            datas_da_semana[dia.weekday()].add(dia)

        def valor(coluna, hora):
            quantas = len(datas_da_semana[coluna])
            return round(somas[(coluna, hora)] / quantas, 1) if quantas else 0

    grade = [[valor(coluna, hora) for coluna in colunas] for hora in horas]

    # 3) Faixas de cor relativas a propria loja.
    positivos = sorted(v for linha in grade for v in linha if v > 0)
    limites = [_percentil(positivos, fracao) for fracao in (0.25, 0.5, 0.75, 0.9)]

    def faixa(v):
        if v <= 0:
            return "vazio"
        for nome, limite in zip(FAIXAS_MAPA, limites):
            if v <= limite:
                return nome
        return "pico"

    linhas = [
        {"hora": hora, "celulas": [{"valor": v, "faixa": faixa(v)} for v in linha]}
        for hora, linha in zip(horas, grade)
    ]

    # Legenda: "vazio", as 4 faixas com limite ("ate X") e o "pico" ("acima de X").
    legenda = [{"faixa": "vazio", "nome": NOMES_FAIXAS["vazio"], "ate": None, "acima": None}]
    for nome, limite in zip(FAIXAS_MAPA[:-1], limites):
        legenda.append({"faixa": nome, "nome": NOMES_FAIXAS[nome], "ate": limite, "acima": None})
    legenda.append({"faixa": "pico", "nome": NOMES_FAIXAS["pico"], "ate": None, "acima": limites[-1] if limites else 0})

    # 4) Destaques do periodo.
    celulas = [(v, nomes[i], hora) for hora, linha in zip(horas, grade) for i, v in enumerate(linha) if v > 0]
    celulas.sort(key=lambda celula: celula[0], reverse=True)
    totais_coluna = [sum(linha[i] for linha in grade) for i in range(len(colunas))]
    totais_hora = [sum(linha) for linha in grade]
    total_geral = sum(totais_hora)

    # Bloco de 6 horas seguidas com mais movimento.
    tamanho = min(6, len(horas))
    melhor_inicio = max(range(len(horas) - tamanho + 1), key=lambda i: sum(totais_hora[i:i + tamanho]), default=0)
    bloco_total = sum(totais_hora[melhor_inicio:melhor_inicio + tamanho])

    # Hora mais movimentada, somando todos os dias (media por dia).
    indice_pico = totais_hora.index(max(totais_hora)) if total_geral else 0

    # Entradas fora do horario de funcionamento (reposicao, faxina... ou algo a investigar).
    fora_do_horario = 0
    if horarios:
        for (dia, hora), total in contagem.items():
            horario = horarios.get(dia.weekday())
            if horario is None or not (horario[0].hour <= hora <= ultima_hora(horario[1])):
                fora_do_horario += total

    destaques = {
        # (entradas, nome do dia, hora)
        "maior": celulas[0] if celulas else None,
        "segundo": celulas[1] if len(celulas) > 1 else None,
        # (nome do dia, entradas no dia)
        "dia_maior": (nomes[totais_coluna.index(max(totais_coluna))], round(max(totais_coluna), 1)) if total_geral else None,
        # (hora inicial, hora final, media de entradas por dia nessa hora)
        "hora_pico": (
            (horas[indice_pico], horas[indice_pico] + 1, round(totais_hora[indice_pico] / len(colunas), 1))
            if total_geral else None
        ),
        # (hora inicial, hora final, % das entradas do dia)
        "bloco": (
            (horas[melhor_inicio], horas[melhor_inicio] + tamanho, round(bloco_total / total_geral * 100))
            if total_geral else None
        ),
        "fora_do_horario": fora_do_horario,
    }

    return {
        "por_data": por_data,
        "rotulos": rotulos,
        "linhas": linhas,
        "legenda": legenda,
        "destaques": destaques,
    }

def serie_diaria(loja, data_inicial, data_final):
    """
    Uma linha por dia do periodo, com entradas, vendas e faturamento JUNTOS
    (venda nunca aparece sozinha). Base do grafico de linhas, dos minigraficos
    do cabecalho e da comparacao com o periodo anterior.
    Dias sem movimento entram com zero (o grafico nao "pula" dias).
    """
    entradas = _entradas_por_dia_e_hora(loja, data_inicial, data_final)
    vendas = _vendas_por_dia_e_hora(loja, data_inicial, data_final)

    # [entradas, vendas, faturamento] de cada dia.
    somas = defaultdict(lambda: [0, 0, Decimal("0")])
    for (dia, _hora), total in entradas.items():
        somas[dia][0] += total
    for (dia, _hora), (transacoes, faturamento) in vendas.items():
        somas[dia][1] += transacoes
        somas[dia][2] += faturamento

    resultado = []
    dia = data_inicial
    while dia <= data_final:
        total_entradas, total_vendas, total_faturamento = somas[dia]
        resultado.append({
            "dia": dia,
            "entradas": total_entradas,
            "vendas": total_vendas,
            "faturamento": total_faturamento,
        })
        dia += timedelta(days=1)
    return resultado