"""
Telas do dashboard de FLUXO (para donos e gerentes).

Estas views so juntam os dados (de fluxo/consultas.py) e entregam ao template.
Nenhuma conta e feita aqui: as contas moram em consultas.py.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from contas.models import Empresa, Usuario
from lojas.models import Loja

from .consultas import (
    entradas_por_dia,
    indicadores_do_periodo,
    indicadores_por_dia_da_semana,
    indicadores_por_turno,
    media_por_hora_do_dia,
    pontas_por_dia,
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

    # --- Resumo e trios: o pacote de indicadores (entradas + vendas juntas) ---
    resumo = indicadores_do_periodo(loja, data_inicial, data_final)
    turnos = marcar_extremos(indicadores_por_turno(loja, data_inicial, data_final))
    semana = marcar_extremos(indicadores_por_dia_da_semana(loja, data_inicial, data_final))

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
        "resumo": resumo,
        "media_diaria": round(resumo["entradas"] / dias),
        "turnos": turnos,
        "semana": semana,
        "pontas": pontas,
        # Dados dos graficos: vao para o template como JSON (ver json_script).
        "grafico_dias": para_grafico([(dia.strftime("%d/%m"), entradas) for dia, entradas in por_dia]),
        "grafico_horas": para_grafico([(f"{hora}h", media) for hora, media in por_hora]),
        "grafico_turnos_entradas": para_grafico([(g, ind["entradas"]) for g, ind in turnos]),
        "grafico_turnos_vendas": para_grafico([(g, ind["vendas"]) for g, ind in turnos]),
        "grafico_semana_entradas": para_grafico([(g, ind["entradas"]) for g, ind in semana]),
        "grafico_semana_vendas": para_grafico([(g, ind["vendas"]) for g, ind in semana]),
    }
    return render(request, "fluxo/loja_painel.html", contexto)