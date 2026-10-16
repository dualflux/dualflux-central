"""
VISAO DA REDE: a pagina da empresa, que o dono abre primeiro.

Mostra a rede inteira (todas as lojas somadas) e compara as lojas entre si,
com os mesmos numeros da tela de cada loja: entradas, vendas, conversao,
ticket medio e receita por visitante.

Regra de ouro (a mesma de sempre): os numeros da REDE sao calculados somando
entradas, vendas e faturamento de todas as lojas e SO DEPOIS dividindo.
Nunca e a media das conversoes das lojas (isso daria peso igual a uma loja
pequena e a uma grande, e o resultado sairia errado).
"""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from contas.models import Empresa, Usuario
from monitor.models import StatusLoja

from .consultas import calcular_indicadores, indicadores_do_periodo, serie_diaria
from .views import PERIODO_PADRAO, PERIODOS, n, variacao


# ----------------------------------------------------------------------
# Permissoes (as mesmas regras da pagina antiga da empresa)
# ----------------------------------------------------------------------

def empresa_permitida(usuario, empresa_slug):
    """Devolve a empresa SE o usuario puder ve-la; senao, "nao encontrada" (404)."""
    empresa = get_object_or_404(Empresa, slug=empresa_slug)
    eh_admin = usuario.papel == Usuario.Papel.ADMIN
    if not eh_admin and usuario.empresa_id != empresa.id:
        raise Http404
    if not eh_admin and empresa.status != Empresa.Status.ATIVA:
        raise PermissionDenied
    return empresa


def lojas_visiveis(usuario, empresa):
    """Gerente: so as lojas dele. Dono e administrador: todas as lojas ativas."""
    if usuario.papel == Usuario.Papel.GERENTE:
        return usuario.lojas.filter(empresa=empresa, ativa=True)
    return empresa.lojas.filter(ativa=True)


# ----------------------------------------------------------------------
# "O que os numeros dizem" da rede: frases automaticas comparando as lojas
# ----------------------------------------------------------------------

def gerar_insights_rede(rede, lojas, comparacao, dias):
    insights = []
    com_conversao = [item for item in lojas if item["ind"]["conversao"] is not None and item["ind"]["entradas"]]

    # 1) Melhor x pior conversao, e quanto a pior deixa de vender (estimativa).
    if len(com_conversao) >= 2:
        melhor = max(com_conversao, key=lambda item: item["ind"]["conversao"])
        pior = min(com_conversao, key=lambda item: item["ind"]["conversao"])
        diferenca = melhor["ind"]["conversao"] - pior["ind"]["conversao"]
        if diferenca > 0:
            texto = (
                f"A {pior['loja'].nome} converte {n(pior['ind']['conversao'], 1)}%, "
                f"{n(diferenca, 1)} p.p. abaixo da {melhor['loja'].nome} ({n(melhor['ind']['conversao'], 1)}%)."
            )
            ticket = pior["ind"]["ticket_medio"] or rede["ticket_medio"]
            if ticket:
                vendas_extras = round(pior["ind"]["entradas"] * diferenca / 100)
                texto += (
                    f" Se ela convertesse como a {melhor['loja'].nome}, seriam cerca de {n(vendas_extras)} vendas "
                    f"a mais no período (R$ {n(vendas_extras * ticket, 2)})."
                )
            insights.append({"tipo": "alerta", "icone": "🔻", "texto": texto})

    # 2) A loja que mais recebe gente.
    if rede["entradas"] and len(lojas) >= 2:
        maior = max(lojas, key=lambda item: item["ind"]["entradas"])
        participacao = maior["ind"]["entradas"] / rede["entradas"] * 100
        insights.append({
            "tipo": "pico",
            "icone": "🔥",
            "texto": f"A {maior['loja'].nome} recebe {n(participacao)}% das entradas da rede "
                     f"({n(maior['ind']['entradas'])} pessoas no período).",
        })

    # 3) Quanto cada visitante rende em cada loja.
    com_receita = [item for item in lojas if item["ind"]["receita_por_visitante"] is not None]
    if len(com_receita) >= 2:
        melhor = max(com_receita, key=lambda item: item["ind"]["receita_por_visitante"])
        pior = min(com_receita, key=lambda item: item["ind"]["receita_por_visitante"])
        if melhor is not pior:
            insights.append({
                "tipo": "info",
                "icone": "💰",
                "texto": f"Cada pessoa que entra rende R$ {n(melhor['ind']['receita_por_visitante'], 2)} na "
                         f"{melhor['loja'].nome} e R$ {n(pior['ind']['receita_por_visitante'], 2)} na {pior['loja'].nome}.",
            })

    # 4) Lojas sem sinal agora (o servidor da loja parou de mandar o "estou vivo").
    sem_sinal = [item["loja"].nome for item in lojas if not (item["status"] and item["status"].online)]
    if sem_sinal:
        insights.append({
            "tipo": "aviso",
            "icone": "📡",
            "texto": f"Sem sinal no momento: {', '.join(sem_sinal)}. "
                     f"Os números dessas lojas podem estar incompletos desde a última conexão.",
        })

    # 5) Tendencia da rede em relacao ao periodo anterior.
    if comparacao and comparacao["entradas"]:
        entradas = comparacao["entradas"]
        texto = (
            f"As entradas da rede {'subiram' if entradas['sobe'] else 'caíram'} {n(entradas['valor'], 1)}% "
            f"em relação aos {dias} dias anteriores"
        )
        conversao = comparacao["conversao"]
        texto += (f", e a conversão {'subiu' if conversao['sobe'] else 'caiu'} {n(conversao['valor'], 1)} p.p."
                  if conversao else ".")
        insights.append({"tipo": "tendencia", "icone": "📈" if entradas["sobe"] else "📉", "texto": texto})

    return insights


# ----------------------------------------------------------------------
# A pagina
# ----------------------------------------------------------------------

@login_required
def empresa_painel(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    lojas = list(lojas_visiveis(request.user, empresa).order_by("nome"))

    # Periodo escolhido pelos botoes (?dias=7). Valor estranho = padrao.
    try:
        dias = int(request.GET.get("dias", PERIODO_PADRAO))
    except ValueError:
        dias = PERIODO_PADRAO
    if dias not in PERIODOS:
        dias = PERIODO_PADRAO

    # "Hoje" no fuso da primeira loja (todas as lojas do piloto estao no mesmo fuso).
    fuso = ZoneInfo(lojas[0].fuso_horario) if lojas else ZoneInfo("America/Campo_Grande")
    hoje = datetime.now(fuso).date()
    data_final = hoje - timedelta(days=1)
    data_inicial = data_final - timedelta(days=dias - 1)
    fim_anterior = data_inicial - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)

    # --- Cada loja: indicadores, serie diaria, comparacao e status ---
    itens = []
    soma = [0, 0, Decimal("0")]            # entradas, vendas, faturamento da rede
    soma_anterior = [0, 0, Decimal("0")]
    todas_comparaveis = bool(lojas)
    serie_rede = defaultdict(lambda: [0, 0, Decimal("0")])

    for loja in lojas:
        ind = indicadores_do_periodo(loja, data_inicial, data_final)
        serie = serie_diaria(loja, data_inicial, data_final)
        for dia in serie:
            serie_rede[dia["dia"]][0] += dia["entradas"]
            serie_rede[dia["dia"]][1] += dia["vendas"]
            serie_rede[dia["dia"]][2] += dia["faturamento"]

        # Comparacao honesta: so se o periodo anterior tiver dados em 80% dos dias.
        dias_anteriores = sum(1 for dia in serie_diaria(loja, inicio_anterior, fim_anterior) if dia["entradas"] > 0)
        comparavel = dias_anteriores >= dias * 0.8
        anterior = indicadores_do_periodo(loja, inicio_anterior, fim_anterior) if comparavel else None
        todas_comparaveis = todas_comparaveis and comparavel

        soma[0] += ind["entradas"]
        soma[1] += ind["vendas"]
        soma[2] += ind["faturamento"]
        if anterior:
            soma_anterior[0] += anterior["entradas"]
            soma_anterior[1] += anterior["vendas"]
            soma_anterior[2] += anterior["faturamento"]

        itens.append({
            "loja": loja,
            "ind": ind,
            "status": StatusLoja.objects.filter(loja=loja).first(),
            "var_entradas": variacao(ind["entradas"], anterior["entradas"]) if anterior else None,
            "var_vendas": variacao(ind["vendas"], anterior["vendas"]) if anterior else None,
            "spark": [dia["entradas"] for dia in serie],
            "destaque": "",
        })

    # --- A rede: soma primeiro, divide depois ---
    rede = calcular_indicadores(*soma)
    comparacao = None
    if todas_comparaveis:
        anterior_rede = calcular_indicadores(*soma_anterior)
        conversao = None
        if rede["conversao"] is not None and anterior_rede["conversao"] is not None:
            diferenca = rede["conversao"] - anterior_rede["conversao"]
            conversao = {"valor": round(abs(diferenca), 1), "sobe": diferenca >= 0}
        comparacao = {
            "entradas": variacao(rede["entradas"], anterior_rede["entradas"]),
            "vendas": variacao(rede["vendas"], anterior_rede["vendas"]),
            "conversao": conversao,
            "receita_por_visitante": variacao(rede["receita_por_visitante"], anterior_rede["receita_por_visitante"]),
        }

    # Melhor e pior conversao entre as lojas (so faz sentido com 2 ou mais).
    com_conversao = [item for item in itens if item["ind"]["conversao"] is not None]
    if len(com_conversao) >= 2:
        max(com_conversao, key=lambda item: item["ind"]["conversao"])["destaque"] = "melhor"
        min(com_conversao, key=lambda item: item["ind"]["conversao"])["destaque"] = "atencao"

    online = sum(1 for item in itens if item["status"] and item["status"].online)
    ranking = sorted(itens, key=lambda item: item["ind"]["conversao"] if item["ind"]["conversao"] is not None else -1,
                     reverse=True)

    dias_ordenados = sorted(serie_rede)
    contexto = {
        "empresa": empresa,
        "dias": dias,
        "periodos": PERIODOS,
        "data_inicial": data_inicial,
        "data_final": data_final,
        "rede": rede,
        "comparacao": comparacao,
        "lojas": itens,
        "ranking": ranking,
        "total_lojas": len(itens),
        "lojas_online": online,
        "insights": gerar_insights_rede(rede, itens, comparacao, dias),
        # Dados dos graficos (json_script no template).
        "grafico_rede": {
            "rotulos": [dia.strftime("%d/%m") for dia in dias_ordenados],
            "entradas": [serie_rede[dia][0] for dia in dias_ordenados],
            "vendas": [serie_rede[dia][1] for dia in dias_ordenados],
            "conversao": [
                round(serie_rede[dia][1] / serie_rede[dia][0] * 100, 1) if serie_rede[dia][0] else None
                for dia in dias_ordenados
            ],
            "receita": [
                round(float(serie_rede[dia][2]) / serie_rede[dia][0], 2) if serie_rede[dia][0] else None
                for dia in dias_ordenados
            ],
        },
        "grafico_lojas": {
            "rotulos": [item["loja"].nome for item in itens],
            "entradas": [item["ind"]["entradas"] for item in itens],
            "vendas": [item["ind"]["vendas"] for item in itens],
        },
        "sparks_lojas": [item["spark"] for item in itens],
    }
    return render(request, "fluxo/empresa_painel.html", contexto)
