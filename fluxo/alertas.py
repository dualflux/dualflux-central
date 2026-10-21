"""
ALERTAS: o sistema avisa sozinho quando algo foge do normal.

Gravidades:
- "urgente": loja sem sinal, camera com falha (agir agora);
- "atencao": movimento de ontem abaixo do normal, conversao de ontem em queda;
- "boa":     movimento de ontem acima do normal.

Regras de comparacao (justas):
- movimento: ontem x media dos MESMOS dias da semana das 4 semanas anteriores
  (terca com terca: sabado sempre e diferente de terca);
- conversao: ontem x conversao das 4 semanas anteriores (soma primeiro, divide depois).

Sem rotina de fundo: calcula quando a tela abre. A parte de "ontem" nao muda
durante o dia, entao fica guardada em cache por 1 hora (nao pesa o menu).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render

from monitor.models import StatusLoja

from .consultas import NOMES_DIAS, serie_diaria
from .rede import empresa_permitida, lojas_visiveis

MOVIMENTO_BAIXO = 0.70        # ontem < 70% do normal  -> atencao
MOVIMENTO_ALTO = 1.30         # ontem > 130% do normal -> boa noticia
QUEDA_CONVERSAO_PP = 5.0      # ontem 5 pontos abaixo da media -> atencao
MINIMO_ENTRADAS_CONVERSAO = 30  # com pouca gente, a conversao oscila demais: nao alerta
ORDEM = {"urgente": 0, "atencao": 1, "boa": 2}


def _numero(valor, casas=0):
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _abre_no_dia(loja, dia):
    """Loja sem horario cadastrado = aberta todo dia; com horario, dia sem linha = fechada."""
    horarios = {h.dia_semana for h in loja.horarios.all()}
    return not horarios or dia.weekday() in horarios


def alertas_de_ontem(loja, ontem):
    """Alertas de movimento e conversao do dia de ontem (guardados em cache por 1 hora)."""
    chave = f"alertas-ontem:{loja.pk}:{ontem.isoformat()}"
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado

    alertas = []
    if _abre_no_dia(loja, ontem):
        serie = {d["dia"]: d for d in serie_diaria(loja, ontem - timedelta(days=28), ontem)}
        hoje_dado = serie[ontem]
        nome_dia = NOMES_DIAS[ontem.weekday()].lower()

        # Movimento: mesmos dias da semana das 4 semanas anteriores, so os que tiveram movimento.
        mesmos_dias = [serie[ontem - timedelta(days=7 * n)]["entradas"] for n in range(1, 5)]
        mesmos_dias = [v for v in mesmos_dias if v > 0]
        if len(mesmos_dias) >= 2:
            normal = sum(mesmos_dias) / len(mesmos_dias)
            razao = hoje_dado["entradas"] / normal if normal else 1
            explicacao = (f"Ontem ({nome_dia}, {ontem:%d/%m}): {_numero(hoje_dado['entradas'])} entradas. "
                          f"O normal para {nome_dia} é {_numero(normal)}.")
            if razao < MOVIMENTO_BAIXO:
                alertas.append({"gravidade": "atencao", "titulo": f"Movimento {_numero((1 - razao) * 100)}% abaixo do normal",
                                "texto": explicacao})
            elif razao > MOVIMENTO_ALTO:
                alertas.append({"gravidade": "boa", "titulo": f"Movimento {_numero((razao - 1) * 100)}% acima do normal",
                                "texto": explicacao})

        # Conversao: ontem x as 4 semanas anteriores (soma primeiro, divide depois).
        anteriores = [d for dia, d in serie.items() if dia < ontem]
        entradas_base = sum(d["entradas"] for d in anteriores)
        vendas_base = sum(d["vendas"] for d in anteriores)
        if hoje_dado["entradas"] >= MINIMO_ENTRADAS_CONVERSAO and entradas_base:
            conv_ontem = hoje_dado["vendas"] / hoje_dado["entradas"] * 100
            conv_media = vendas_base / entradas_base * 100
            if conv_media - conv_ontem >= QUEDA_CONVERSAO_PP:
                alertas.append({
                    "gravidade": "atencao",
                    "titulo": f"Conversão caiu {_numero(conv_media - conv_ontem, 1)} pontos",
                    "texto": (f"Ontem ({ontem:%d/%m}) {_numero(conv_ontem, 1)}% das pessoas compraram; "
                              f"a média das últimas 4 semanas é {_numero(conv_media, 1)}%. "
                              f"Vale olhar atendimento, fila e ruptura de produto."),
                })

    cache.set(chave, alertas, 60 * 60)
    return alertas


def alertas_de_agora(loja, status):
    """Alertas do momento (sinal e cameras): nunca vao para o cache."""
    if status is None:
        return [{"gravidade": "urgente", "titulo": "Loja ainda não conectou",
                 "texto": "O servidor da loja nunca enviou sinal. Fale com o suporte DualFlux."}]
    alertas = []
    if not status.online:
        alertas.append({"gravidade": "urgente", "titulo": "Loja sem sinal",
                        "texto": "O servidor da loja parou de enviar dados. Confira se está ligado e com internet; "
                                 "se continuar, fale com o suporte DualFlux."})
    elif not status.cameras_ok:
        com_falha = ", ".join(c.get("codigo", "?") for c in status.cameras if not c.get("ok"))
        alertas.append({"gravidade": "urgente", "titulo": "Câmera com falha",
                        "texto": f"Câmera sem imagem: {com_falha}. As entradas podem estar sendo perdidas."})
    return alertas


def montar_alertas(usuario, empresa):
    """Todos os alertas das lojas que o usuario pode ver, do mais grave para o menos grave."""
    lojas = list(lojas_visiveis(usuario, empresa).prefetch_related("horarios").order_by("nome"))
    status = {s.loja_id: s for s in StatusLoja.objects.filter(loja__in=lojas)}
    lista = []
    for loja in lojas:
        ontem = datetime.now(ZoneInfo(loja.fuso_horario)).date() - timedelta(days=1)
        for alerta in alertas_de_agora(loja, status.get(loja.pk)) + alertas_de_ontem(loja, ontem):
            lista.append({**alerta, "loja": loja})
    lista.sort(key=lambda a: (ORDEM[a["gravidade"]], a["loja"].nome))
    return lista


def contar_alertas(usuario, empresa):
    """Numero para o contador do menu: so urgentes e de atencao."""
    return sum(1 for a in montar_alertas(usuario, empresa) if a["gravidade"] != "boa")


@login_required
def alertas(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    lista = montar_alertas(request.user, empresa)
    contexto = {
        "empresa": empresa,
        "urgentes": [a for a in lista if a["gravidade"] == "urgente"],
        "atencao": [a for a in lista if a["gravidade"] == "atencao"],
        "boas": [a for a in lista if a["gravidade"] == "boa"],
        "limites": {"baixo": int(MOVIMENTO_BAIXO * 100), "alto": int(MOVIMENTO_ALTO * 100), "conversao": int(QUEDA_CONVERSAO_PP)},
    }
    return render(request, "fluxo/alertas.html", contexto)
