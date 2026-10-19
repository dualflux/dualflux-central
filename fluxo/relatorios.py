"""
RELATORIOS: tela onde o cliente MONTA o relatorio que quer.

Escolhe a loja, o periodo (botoes rapidos ou datas livres) e liga/desliga cada
parte do relatorio. O botao "Gerar relatorio" abre a pagina de relatorio da loja
(a MESMA view do painel, com outro template) so com as partes ligadas.

Permissoes: as mesmas da Visao da rede (dono ve todas as lojas, gerente so as dele).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .rede import empresa_permitida, lojas_visiveis
from .views import PERIODO_PADRAO, PERIODOS

# Partes do relatorio: (codigo, titulo, explicacao). O codigo vai na URL (?secoes=...).
SECOES = [
    ("resumo", "Números principais", "Entradas, vendas, conversão, faturamento, ticket e receita por visitante."),
    ("insights", "Insights", "As conclusões automáticas do período."),
    ("linhas", "Entradas e vendas (linhas)", "As duas curvas, dia a dia, na mesma escala."),
    ("dias", "Entradas por dia (barras)", "Com o dia de maior movimento em destaque."),
    ("horas", "Quando a loja enche (barras)", "Média de entradas em cada hora do dia."),
    ("destaques", "Destaques do período", "Maior movimento, período mais cheio, fora do horário."),
    ("turnos", "Turnos", "Entradas x vendas na manhã, tarde e noite."),
    ("semana", "Dias da semana", "Entradas x vendas de segunda a domingo."),
    ("pontas", "Abertura e fechamento", "Primeira e última hora de cada dia."),
]


@login_required
def relatorios(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    lojas = list(lojas_visiveis(request.user, empresa).order_by("nome"))

    # "Ontem" no fuso da primeira loja: o relatorio vai no maximo ate ontem (dia completo).
    fuso = ZoneInfo(lojas[0].fuso_horario) if lojas else ZoneInfo("America/Campo_Grande")
    ontem = datetime.now(fuso).date() - timedelta(days=1)

    contexto = {
        "empresa": empresa,
        "lojas": lojas,
        "periodos": PERIODOS,
        "periodo_padrao": PERIODO_PADRAO,
        "secoes": SECOES,
        "ontem": ontem,
        "inicio_padrao": ontem - timedelta(days=PERIODO_PADRAO - 1),
    }
    return render(request, "fluxo/relatorios.html", contexto)
