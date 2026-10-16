"""
Telas do dashboard de FLUXO (para donos e gerentes).

Estas views juntam os dados (de fluxo/consultas.py) e entregam ao template.
As contas de numeros moram em consultas.py; aqui ficam so a comparacao entre
periodos e as frases automaticas ("O que os numeros dizem").
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.formats import number_format

from contas.models import Empresa, Usuario
from lojas.models import Loja
from monitor.models import StatusLoja

from .consultas import (
    entradas_por_dia,
    indicadores_do_periodo,
    indicadores_por_dia_da_semana,
    indicadores_por_turno,
    mapa_de_horarios,
    media_por_hora_do_dia,
    pontas_por_dia,
    serie_diaria,
)

# Opcoes de periodo (em dias) mostradas como botoes na tela.
PERIODOS = [7, 30, 42, 60, 90]
PERIODO_PADRAO = 30


def loja_permitida(usuario, empresa_slug, loja_slug):
    """
    Devolve a loja SE o usuario puder ve-la; senao, "nao encontrada" (404).

    - administrador DualFlux: qualquer loja;
    - dono: qualquer loja da empresa dele;
    - gerente: so as lojas marcadas para ele.
    """
    empresa = get_object_or_404(Empresa, slug=empresa_slug)
    loja = get_object_or_404(Loja, empresa=empresa, slug=loja_slug)

    if usuario.papel == Usuario.Papel.ADMIN:
        return loja
    if usuario.empresa_id != empresa.id:
        raise Http404
    if empresa.status != Empresa.Status.ATIVA:
        raise PermissionDenied
    if usuario.papel == Usuario.Papel.GERENTE and not usuario.lojas.filter(pk=loja.pk).exists():
        raise Http404
    return loja


def classificar(indice):
    """
    Etiqueta da ponta comparada com a media do PERIODO (100% = igual a media).
    Devolve (texto, classe_css).
    """
    if indice < 80:
        return "abaixo do normal", "fraca"
    if indice <= 120:
        return "normal", "normal"
    return "acima do normal", "forte"


def marcar_extremos(grupos):
    """
    Em [(grupo, indicadores)], marca a MAIOR e a MENOR conversao do trio:
    indicadores["destaque"] = "maior", "menor" ou "".
    """
    conversoes = [ind["conversao"] for _, ind in grupos if ind["conversao"] is not None]
    for _, ind in grupos:
        ind["destaque"] = ""
        if conversoes and ind["conversao"] is not None:
            if ind["conversao"] == max(conversoes):
                ind["destaque"] = "maior"
            elif ind["conversao"] == min(conversoes):
                ind["destaque"] = "menor"
    return grupos


def para_grafico(pares):
    """Transforma [(rotulo, valor), ...] no formato que o Chart.js espera."""
    return {"rotulos": [rotulo for rotulo, _ in pares], "valores": [valor for _, valor in pares]}


def n(valor, casas=0):
    """Numero no padrao brasileiro (12.180 / 29,1 / 1.234,56) para usar dentro de frases."""
    return number_format(valor, decimal_pos=casas, use_l10n=True, force_grouping=True)


# ----------------------------------------------------------------------
# Comparacao com o periodo anterior
# ----------------------------------------------------------------------

def variacao(atual, anterior):
    """Variacao percentual entre dois periodos: {"valor": 4.2, "sobe": True}, ou None."""
    if atual is None or not anterior:
        return None
    percentual = (float(atual) - float(anterior)) / float(anterior) * 100
    return {"valor": round(abs(percentual), 1), "sobe": percentual >= 0}


def comparar_com_anterior(loja, data_inicial, dias, resumo):
    """
    Compara o periodo com os N dias ANTERIORES (ex.: 30 dias com os 30 dias antes).

    HONESTIDADE: so compara se o periodo anterior tiver movimento em pelo menos
    80% dos dias. Numa loja recem-instalada, comparar com um periodo quase vazio
    mostraria um "crescimento" enorme e falso.
    """
    fim = data_inicial - timedelta(days=1)
    inicio = fim - timedelta(days=dias - 1)
    dias_com_movimento = sum(1 for dia in serie_diaria(loja, inicio, fim) if dia["entradas"] > 0)
    if dias_com_movimento < dias * 0.8:
        return None

    anterior = indicadores_do_periodo(loja, inicio, fim)
    conversao = None
    if resumo["conversao"] is not None and anterior["conversao"] is not None:
        # Conversao compara em PONTOS PERCENTUAIS (29,1% -> 29,8% = +0,7 p.p.).
        diferenca = resumo["conversao"] - anterior["conversao"]
        conversao = {"valor": round(abs(diferenca), 1), "sobe": diferenca >= 0}

    return {
        "entradas": variacao(resumo["entradas"], anterior["entradas"]),
        "vendas": variacao(resumo["vendas"], anterior["vendas"]),
        "conversao": conversao,
        "receita_por_visitante": variacao(resumo["receita_por_visitante"], anterior["receita_por_visitante"]),
    }


# ----------------------------------------------------------------------
# "O que os numeros dizem": frases automaticas (regras, sem IA)
# ----------------------------------------------------------------------

def gerar_insights(resumo, turnos, semana, mapa, comparacao, dias):
    """Transforma os numeros em conclusoes prontas para o dono decidir."""
    insights = []
    conversao_media = resumo["conversao"]

    # 1) O turno com MENOR conversao, e quanto ele deixa de vender (estimativa).
    validos = [(grupo, ind) for grupo, ind in turnos if ind["entradas"] and ind["conversao"] is not None]
    if validos and conversao_media is not None and resumo["entradas"]:
        grupo, pior = min(validos, key=lambda item: item[1]["conversao"])
        participacao = pior["entradas"] / resumo["entradas"] * 100
        texto = (
            f"A {grupo.lower()} recebe {n(participacao)}% das entradas, mas tem a menor conversão "
            f"do dia: {n(pior['conversao'], 1)}%."
        )
        if pior["conversao"] < conversao_media and resumo["ticket_medio"]:
            vendas_extras = round(pior["entradas"] * (conversao_media - pior["conversao"]) / 100)
            valor = vendas_extras * resumo["ticket_medio"]
            texto += (
                f" Se ela convertesse como a média da loja ({n(conversao_media, 1)}%), seriam cerca de "
                f"{n(vendas_extras)} vendas a mais no período (R$ {n(valor, 2)})."
            )
        insights.append({"tipo": "alerta", "icone": "🔻", "texto": texto})

    # 2) O pico de movimento.
    maior = mapa["destaques"]["maior"]
    if maior:
        entradas, dia, hora = maior
        casas = 0 if mapa["por_data"] else 1
        complemento = "no dia" if mapa["por_data"] else "em média"
        insights.append({
            "tipo": "pico",
            "icone": "🔥",
            "texto": (
                f"{dia}, das {hora}h às {hora + 1}h, é o pico de movimento: {n(entradas, casas)} entradas "
                f"{complemento}. É o horário que mais pede equipe completa no balcão."
            ),
        })

    # 3) Dias da semana: o que mais e o que menos converte.
    validos = [(grupo, ind) for grupo, ind in semana if ind["entradas"] and ind["conversao"] is not None]
    if len(validos) >= 2:
        dia_melhor, melhor = max(validos, key=lambda item: item[1]["conversao"])
        dia_pior, pior = min(validos, key=lambda item: item[1]["conversao"])
        insights.append({
            "tipo": "info",
            "icone": "📅",
            "texto": (
                f"{dia_melhor} é o dia que melhor converte ({n(melhor['conversao'], 1)}%); "
                f"{dia_pior.lower()} é o que menos converte ({n(pior['conversao'], 1)}%)."
            ),
        })

    # 4) Tendencia em relacao ao periodo anterior.
    if comparacao and comparacao["entradas"]:
        entradas = comparacao["entradas"]
        texto = (
            f"As entradas {'subiram' if entradas['sobe'] else 'caíram'} {n(entradas['valor'], 1)}% "
            f"em relação aos {dias} dias anteriores"
        )
        conversao = comparacao["conversao"]
        if conversao:
            texto += f", e a conversão {'subiu' if conversao['sobe'] else 'caiu'} {n(conversao['valor'], 1)} p.p."
        else:
            texto += "."
        insights.append({"tipo": "tendencia", "icone": "📈" if entradas["sobe"] else "📉", "texto": texto})

    return insights


# ----------------------------------------------------------------------
# A tela da loja
# ----------------------------------------------------------------------

@login_required
def loja_painel(request, empresa_slug, loja_slug):
    loja = loja_permitida(request.user, empresa_slug, loja_slug)

    # Periodo escolhido pelos botoes (?dias=7). Valor estranho = padrao.
    try:
        dias = int(request.GET.get("dias", PERIODO_PADRAO))
    except ValueError:
        dias = PERIODO_PADRAO
    if dias not in PERIODOS:
        dias = PERIODO_PADRAO

    # "Hoje" no fuso DA LOJA. O periodo vai ate ONTEM: o dia de hoje ainda
    # esta pela metade e distorceria a comparacao com os dias inteiros.
    hoje = datetime.now(ZoneInfo(loja.fuso_horario)).date()
    data_final = hoje - timedelta(days=1)
    data_inicial = data_final - timedelta(days=dias - 1)

    # --- Indicadores (entradas + vendas sempre juntas) ---
    resumo = indicadores_do_periodo(loja, data_inicial, data_final)
    comparacao = comparar_com_anterior(loja, data_inicial, dias, resumo)
    turnos = marcar_extremos(indicadores_por_turno(loja, data_inicial, data_final))
    semana = marcar_extremos(indicadores_por_dia_da_semana(loja, data_inicial, data_final))
    mapa = mapa_de_horarios(loja, data_inicial, data_final)
    serie = serie_diaria(loja, data_inicial, data_final)

    # --- Fluxo ---
    por_dia = entradas_por_dia(loja, data_inicial, data_final)
    por_hora = [(hora, media) for hora, media in media_por_hora_do_dia(loja, data_inicial, data_final) if media > 0]

    pontas = pontas_por_dia(loja, data_inicial, data_final)
    for linha in pontas["dias"]:
        linha["leitura_abertura"], linha["css_abertura"] = classificar(linha["indice_abertura"])
        linha["leitura_fechamento"], linha["css_fechamento"] = classificar(linha["indice_fechamento"])
    pontas["dias"].reverse()  # na tabela, o dia mais recente aparece primeiro

    contexto = {
        "empresa": loja.empresa,
        "loja": loja,
        "dias": dias,
        "periodos": PERIODOS,
        "data_inicial": data_inicial,
        "data_final": data_final,
        # Cabecalho vitrine
        "status": StatusLoja.objects.filter(loja=loja).first(),
        "horario_hoje": loja.horarios.filter(dia_semana=hoje.weekday()).first(),
        "resumo": resumo,
        "comparacao": comparacao,
        "insights": gerar_insights(resumo, turnos, semana, mapa, comparacao, dias),
        # Secoes
        "media_diaria": round(resumo["entradas"] / dias),
        "turnos": turnos,
        "semana": semana,
        "mapa": mapa,
        "pontas": pontas,
        # Dados dos graficos: vao para o template como JSON (ver json_script).
        "grafico_linhas": {
            "rotulos": [dia["dia"].strftime("%d/%m") for dia in serie],
            "entradas": [dia["entradas"] for dia in serie],
            "vendas": [dia["vendas"] for dia in serie],
            "conversao": [
                round(dia["vendas"] / dia["entradas"] * 100, 1) if dia["entradas"] else None for dia in serie
            ],
            "receita": [
                round(float(dia["faturamento"]) / dia["entradas"], 2) if dia["entradas"] else None for dia in serie
            ],
        },
        "grafico_dias": para_grafico([(dia.strftime("%d/%m"), entradas) for dia, entradas in por_dia]),
        "grafico_horas": para_grafico([(f"{hora}h", media) for hora, media in por_hora]),
        "grafico_turnos_entradas": para_grafico([(g, ind["entradas"]) for g, ind in turnos]),
        "grafico_turnos_vendas": para_grafico([(g, ind["vendas"]) for g, ind in turnos]),
        "grafico_semana_entradas": para_grafico([(g, ind["entradas"]) for g, ind in semana]),
        "grafico_semana_vendas": para_grafico([(g, ind["vendas"]) for g, ind in semana]),
    }
    return render(request, "fluxo/loja_painel.html", contexto)