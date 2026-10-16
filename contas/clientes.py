"""
CLIENTES: a central do administrador DualFlux (so o papel "admin" ve).

Lista todas as empresas e a saude de cada loja, usando o ultimo heartbeat
("estou vivo") que cada servidor de loja enviou (monitor.StatusLoja).

Ordem da lista: primeiro as empresas que precisam de atencao (loja offline,
camera com falha, relogio errado...), depois as demais, em ordem alfabetica.
Assim, ao abrir a tela, o que exige acao ja esta no topo.
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from monitor.models import StatusLoja

from .models import Empresa, Usuario

# Disco livre abaixo disto (em %) vira alerta: a loja pode parar de gravar.
LIMITE_DISCO_PCT = 10

# Mais eventos que isto esperando envio = a loja nao esta conseguindo mandar.
LIMITE_PENDENTES = 500


def saude_da_loja(loja):
    """
    Resume a saude de UMA loja:
    - estado: "online", "offline" ou "nunca" (nunca mandou heartbeat);
    - alertas: lista de frases curtas com o que esta errado.
    """
    try:
        status = loja.status  # OneToOne: pode nao existir ainda
    except StatusLoja.DoesNotExist:
        return {"loja": loja, "status": None, "estado": "nunca",
                "alertas": ["Nunca se conectou à central"]}

    alertas = []
    if not status.online:
        alertas.append("Sem sinal")
    if not status.cameras_ok:
        com_falha = [camera.get("codigo", "?") for camera in status.cameras if not camera.get("ok")]
        alertas.append(f"Câmera com falha: {', '.join(com_falha)}")
    if not status.relogio_ok:
        alertas.append(f"Relógio errado ({status.diferenca_relogio_s:+d} s)")
    if status.disco_livre_pct is not None and status.disco_livre_pct < LIMITE_DISCO_PCT:
        alertas.append(f"Disco quase cheio ({status.disco_livre_pct}% livre)")
    if status.eventos_pendentes and status.eventos_pendentes > LIMITE_PENDENTES:
        alertas.append(f"{status.eventos_pendentes} eventos esperando envio")
    if status.ultimo_erro_sync:
        alertas.append("Erro no envio de dados")

    return {"loja": loja, "status": status, "estado": "online" if status.online else "offline", "alertas": alertas}


@login_required
def clientes(request):
    # Somente o administrador DualFlux. Para os outros, a pagina "nao existe".
    if request.user.papel != Usuario.Papel.ADMIN:
        raise Http404

    # prefetch: busca empresas, lojas e status em poucas consultas (nao uma por loja).
    empresas = Empresa.objects.prefetch_related("lojas__status").order_by("nome")

    itens = []
    for empresa in empresas:
        lojas = [saude_da_loja(loja) for loja in empresa.lojas.all() if loja.ativa]
        lojas.sort(key=lambda item: (not item["alertas"], item["loja"].nome))  # com problema primeiro
        itens.append({
            "empresa": empresa,
            "lojas": lojas,
            "online": sum(1 for item in lojas if item["estado"] == "online"),
            "com_alerta": sum(1 for item in lojas if item["alertas"]),
        })

    # Empresas com loja em alerta primeiro; dentro de cada grupo, ordem alfabetica.
    itens.sort(key=lambda item: (item["com_alerta"] == 0, item["empresa"].nome.lower()))

    todas = [loja for item in itens for loja in item["lojas"]]
    totais = {
        "empresas": len(itens),
        "suspensas": sum(1 for item in itens if item["empresa"].status == Empresa.Status.SUSPENSA),
        "lojas": len(todas),
        "online": sum(1 for loja in todas if loja["estado"] == "online"),
        "offline": sum(1 for loja in todas if loja["estado"] == "offline"),
        "nunca": sum(1 for loja in todas if loja["estado"] == "nunca"),
        "com_alerta": sum(1 for loja in todas if loja["alertas"]),
    }
    return render(request, "contas/clientes.html", {"itens": itens, "totais": totais})
