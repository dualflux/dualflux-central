"""
MENSAGENS: o que dizer. Nao sabe por onde vai sair (Telegram, e-mail ou WhatsApp).

Regras de comparacao (as mesmas dos Alertas):
- entradas de ontem x media dos MESMOS dias da semana das 4 semanas anteriores;
- conversao de ontem x conversao das 4 semanas anteriores (soma primeiro, divide depois).
Cada pessoa so ve as lojas que pode ver (gerente: so a loja dele).
Nenhum dado pessoal vai na mensagem: so numeros das lojas e um link que exige login.
"""

from datetime import timedelta
from html import escape

from django.conf import settings
from django.urls import reverse

from fluxo.alertas import _abre_no_dia, _numero
from fluxo.consultas import NOMES_DIAS, serie_diaria
from fluxo.rede import lojas_visiveis

from .canais import Mensagem


def _link(caminho):
    base = getattr(settings, "DUALFLUX_SITE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}{caminho}"


def _conversao(vendas, entradas):
    return vendas / entradas * 100 if entradas else None


def _seta_pct(atual, normal):
    if not normal:
        return ""
    variacao = (atual / normal - 1) * 100
    if abs(variacao) < 0.5:
        return " (= normal)"
    return f" ({'▲' if variacao > 0 else '▼'} {_numero(abs(variacao))}%)"


def _seta_pp(atual, media):
    if atual is None or media is None:
        return ""
    diferenca = atual - media
    if abs(diferenca) < 0.05:
        return " (= média)"
    return f" ({'▲' if diferenca > 0 else '▼'} {_numero(abs(diferenca), 1)} p.p.)"


def numeros_do_dia(loja, dia):
    """Numeros de um dia e a base de comparacao. None se a loja nao abre nesse dia."""
    if not _abre_no_dia(loja, dia):
        return None
    serie = {d["dia"]: d for d in serie_diaria(loja, dia - timedelta(days=28), dia)}
    atual = serie[dia]
    mesmos = [serie[dia - timedelta(days=7 * n)]["entradas"] for n in range(1, 5)]
    mesmos = [v for v in mesmos if v > 0]
    anteriores = [d for chave, d in serie.items() if chave < dia]
    return {
        "entradas": atual["entradas"],
        "vendas": atual["vendas"],
        "conversao": _conversao(atual["vendas"], atual["entradas"]),
        "normal_entradas": sum(mesmos) / len(mesmos) if len(mesmos) >= 2 else None,
        "media_conversao": _conversao(sum(d["vendas"] for d in anteriores), sum(d["entradas"] for d in anteriores)),
    }


def _bloco_loja(nome, n):
    linhas = [f"<b>{escape(nome)}</b>"]
    if n is None:
        linhas.append("Fechada ontem.")
        return "\n".join(linhas)
    linhas.append(f"👥 Entradas: <b>{_numero(n['entradas'])}</b>{_seta_pct(n['entradas'], n['normal_entradas'])}")
    linhas.append(f"🛒 Vendas: <b>{_numero(n['vendas'])}</b>")
    if n["conversao"] is not None:
        linhas.append(f"🎯 Conversão: <b>{_numero(n['conversao'], 1)}%</b>{_seta_pp(n['conversao'], n['media_conversao'])}")
    return "\n".join(linhas)


def resumo_diario(usuario, empresa, dia):
    """Resumo de UM dia (normalmente ontem), de todas as lojas que a pessoa pode ver."""
    lojas = list(lojas_visiveis(usuario, empresa).prefetch_related("horarios").order_by("nome"))
    nome_dia = NOMES_DIAS[dia.weekday()].lower()
    partes = [f"📊 <b>DualFlux · Resumo de {dia:%d/%m}</b>", f"{escape(empresa.nome)} · {nome_dia}"]
    total_e = total_v = 0
    for loja in lojas:
        n = numeros_do_dia(loja, dia)
        partes.append(_bloco_loja(loja.nome, n))
        if n:
            total_e += n["entradas"]
            total_v += n["vendas"]
    if len(lojas) > 1:
        conv = _conversao(total_v, total_e)
        partes.append(f"<b>Rede</b>: {_numero(total_e)} entradas · {_numero(total_v)} vendas"
                      + (f" · {_numero(conv, 1)}%" if conv is not None else ""))
    if not lojas:
        partes.append("Nenhuma loja disponível para você.")
    caminho = (reverse("loja_painel", args=[empresa.slug, lojas[0].slug]) if len(lojas) == 1
               else reverse("empresa_inicio", args=[empresa.slug]))
    partes.append(f'🔗 <a href="{_link(caminho)}">Abrir o painel</a>')
    return Mensagem(f"DualFlux - Resumo de {dia:%d/%m} - {empresa.nome}", "\n\n".join(partes))


def resumo_semanal(usuario, empresa, segunda):
    """Semana de segunda a domingo (a que comeca em 'segunda') x media das 4 semanas anteriores."""
    domingo = segunda + timedelta(days=6)
    lojas = list(lojas_visiveis(usuario, empresa).order_by("nome"))
    partes = [f"🗓️ <b>DualFlux · Semana {segunda:%d/%m} a {domingo:%d/%m}</b>", escape(empresa.nome)]
    for loja in lojas:
        serie = serie_diaria(loja, segunda - timedelta(days=28), domingo)
        semana = [d for d in serie if d["dia"] >= segunda]
        antes = [d for d in serie if d["dia"] < segunda]
        e, v = sum(d["entradas"] for d in semana), sum(d["vendas"] for d in semana)
        e_media = sum(d["entradas"] for d in antes) / 4
        conv, conv_media = _conversao(v, e), _conversao(sum(d["vendas"] for d in antes), sum(d["entradas"] for d in antes))
        linhas = [f"<b>{escape(loja.nome)}</b>",
                  f"👥 Entradas: <b>{_numero(e)}</b>{_seta_pct(e, e_media)}",
                  f"🛒 Vendas: <b>{_numero(v)}</b>"]
        if conv is not None:
            linhas.append(f"🎯 Conversão: <b>{_numero(conv, 1)}%</b>{_seta_pp(conv, conv_media)}")
        melhor = max(semana, key=lambda d: d["entradas"], default=None)
        if melhor and melhor["entradas"]:
            linhas.append(f"⭐ Dia mais movimentado: {NOMES_DIAS[melhor['dia'].weekday()].lower()} ({_numero(melhor['entradas'])})")
        partes.append("\n".join(linhas))
    if not lojas:
        partes.append("Nenhuma loja disponível para você.")
    partes.append(f'🔗 <a href="{_link(reverse("relatorios", args=[empresa.slug]))}">Montar o relatório completo</a>')
    return Mensagem(f"DualFlux - Semana {segunda:%d/%m} a {domingo:%d/%m} - {empresa.nome}", "\n\n".join(partes))


def mensagem_alerta(empresa, loja, alerta):
    corpo = (f"🚨 <b>{escape(alerta['titulo'])}</b>\n{escape(loja.nome)} · {escape(empresa.nome)}\n\n"
             f"{escape(alerta['texto'])}\n\n"
             f'🔗 <a href="{_link(reverse("alertas", args=[empresa.slug]))}">Ver alertas</a>')
    return Mensagem(f"DualFlux - {alerta['titulo']} - {loja.nome}", corpo)
