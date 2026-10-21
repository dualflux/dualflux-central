"""
AGENDA: quando enviar. Roda a cada minuto pelo comando 'python manage.py avisos'.

- Diario: a partir do horario escolhido (padrao 07:30), uma vez por dia, com os numeros de ONTEM.
- Semanal: toda segunda, no mesmo horario, com a semana anterior (segunda a domingo).
- Alertas urgentes: loja sem sinal / camera com falha, na hora. O mesmo alerta nao se repete
  por 6 horas (se continuar, avisa de novo depois disso).
So recebe quem deu o aceite, esta ativo e e de empresa ativa. Admin DualFlux nao recebe por aqui.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from contas.models import Empresa, Usuario
from fluxo.alertas import alertas_de_agora
from fluxo.rede import lojas_visiveis
from monitor.models import StatusLoja

from .canais import enviar
from .mensagens import mensagem_alerta, resumo_diario, resumo_semanal
from .models import EnvioAviso, PreferenciaAviso

log = logging.getLogger(__name__)

REPETIR_ALERTA_APOS = timedelta(hours=6)


def preferencias_que_recebem():
    return (PreferenciaAviso.objects
            .filter(aceite_em__isnull=False, usuario__is_active=True,
                    usuario__papel__in=[Usuario.Papel.DONO, Usuario.Papel.GERENTE],
                    usuario__empresa__status=Empresa.Status.ATIVA)
            .select_related("usuario", "usuario__empresa"))


def ciclo(agora=None):
    """Uma passada: envia o que estiver na hora. Devolve quantos avisos foram enviados."""
    agora = agora or timezone.now()
    local = timezone.localtime(agora)
    hoje = local.date()
    enviados = 0

    for pref in preferencias_que_recebem():
        if not pref.canais_ativos():
            continue
        usuario, empresa = pref.usuario, pref.usuario.empresa
        try:
            na_hora = local.time() >= pref.horario
            if pref.receber_diario and na_hora and pref.ultimo_diario != hoje:
                enviar(pref, resumo_diario(usuario, empresa, hoje - timedelta(days=1)), EnvioAviso.Tipo.DIARIO)
                pref.ultimo_diario = hoje
                pref.save(update_fields=["ultimo_diario"])
                enviados += 1
            if pref.receber_semanal and na_hora and hoje.weekday() == 0 and pref.ultimo_semanal != hoje:
                enviar(pref, resumo_semanal(usuario, empresa, hoje - timedelta(days=7)), EnvioAviso.Tipo.SEMANAL)
                pref.ultimo_semanal = hoje
                pref.save(update_fields=["ultimo_semanal"])
                enviados += 1
            if pref.receber_alertas:
                enviados += _alertas_urgentes(pref, agora)
        except Exception:
            # Um cliente com problema nao pode impedir o envio dos outros.
            log.exception("Falha ao preparar avisos do usuario %s", usuario.pk)
    return enviados


def _alertas_urgentes(pref, agora):
    usuario, empresa = pref.usuario, pref.usuario.empresa
    lojas = list(lojas_visiveis(usuario, empresa))
    status = {s.loja_id: s for s in StatusLoja.objects.filter(loja__in=lojas)}
    enviados = 0
    for loja in lojas:
        if loja.pk not in status:
            continue  # loja que nunca conectou (ainda em instalacao): nao fica avisando
        for alerta in alertas_de_agora(loja, status[loja.pk]):
            chave = f"{loja.pk}:{alerta['titulo']}"
            recente = EnvioAviso.objects.filter(usuario=usuario, tipo=EnvioAviso.Tipo.ALERTA, chave=chave,
                                                criado_em__gte=agora - REPETIR_ALERTA_APOS).exists()
            if not recente:
                enviar(pref, mensagem_alerta(empresa, loja, alerta), EnvioAviso.Tipo.ALERTA, chave=chave)
                enviados += 1
    return enviados
