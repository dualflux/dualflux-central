"""
CONFIGURACOES -> NOTIFICACOES: cada pessoa escolhe o que recebe, quando e por onde.

Acesso minimo: cada um ve e altera SO a propria preferencia. Ninguem mexe na de outra pessoa.
Acoes que mudam algo sao so por POST (com CSRF).
"""

from datetime import time, timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from contas.models import Usuario
from fluxo.rede import empresa_permitida

from .canais import ErroEnvio, enviar, telegram_configurado
from .mensagens import resumo_diario
from .models import EnvioAviso, PreferenciaAviso
from .telegram import processar_atualizacoes

LIMITE_TESTES_POR_HORA = 5
HORARIOS = [time(h, m) for h in range(5, 13) for m in (0, 30)]  # 05:00 ... 12:30


class FormPreferencia(forms.ModelForm):
    horario = forms.TypedChoiceField(
        label="Horário do envio", coerce=lambda v: time.fromisoformat(v),
        choices=[(h.strftime("%H:%M"), h.strftime("%H:%M")) for h in HORARIOS])
    aceite = forms.BooleanField(label="Aceito receber", required=False)

    class Meta:
        model = PreferenciaAviso
        fields = ["receber_diario", "receber_semanal", "receber_alertas", "horario",
                  "canal_telegram", "canal_email", "celular"]

    def clean(self):
        dados = super().clean()
        recebe = dados.get("receber_diario") or dados.get("receber_semanal") or dados.get("receber_alertas")
        if recebe and not dados.get("aceite"):
            self.add_error("aceite", "Para receber, marque que aceita receber os avisos.")
        if recebe and not (dados.get("canal_telegram") or dados.get("canal_email")):
            self.add_error(None, "Escolha pelo menos um canal: Telegram ou e-mail.")
        return dados


def _contexto(request, empresa, pref, form, extra=None):
    contexto = {
        "empresa": empresa, "pref": pref, "form": form,
        "telegram_pronto": telegram_configurado(),
        "robo": getattr(settings, "TELEGRAM_BOT_USUARIO", ""),
        "envios": EnvioAviso.objects.filter(usuario=request.user)[:8],
        "aviso": request.session.pop("aviso_notificacao", None),
    }
    contexto.update(extra or {})
    return contexto


def _pode_receber(usuario):
    return usuario.papel in (Usuario.Papel.DONO, Usuario.Papel.GERENTE) and usuario.empresa_id


@login_required
def notificacoes(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    if not _pode_receber(request.user):
        return render(request, "avisos/notificacoes.html", {"empresa": empresa, "sem_acesso": True})
    pref, _ = PreferenciaAviso.objects.get_or_create(usuario=request.user)
    inicial = {"horario": pref.horario.strftime("%H:%M"), "aceite": pref.aceite_em is not None}
    form = FormPreferencia(request.POST or None, instance=pref, initial=inicial)
    if request.method == "POST" and form.is_valid():
        pref = form.save(commit=False)
        if form.cleaned_data["aceite"]:
            pref.aceite_em = pref.aceite_em or timezone.now()
        else:
            pref.aceite_em = None  # sem aceite: para de enviar
        pref.save()
        request.session["aviso_notificacao"] = ("ok", "Preferências salvas.")
        return redirect("notificacoes", empresa_slug=empresa.slug)
    return render(request, "avisos/notificacoes.html", _contexto(request, empresa, pref, form))


@login_required
@require_POST
def conectar_telegram(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    if not _pode_receber(request.user) or not telegram_configurado():
        return redirect("notificacoes", empresa_slug=empresa.slug)
    pref, _ = PreferenciaAviso.objects.get_or_create(usuario=request.user)
    codigo = pref.novo_codigo_telegram()
    # Abre o robo ja com o codigo: a pessoa so aperta "Iniciar".
    return redirect(f"https://t.me/{settings.TELEGRAM_BOT_USUARIO}?start={codigo}")


@login_required
@require_POST
def desconectar_telegram(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    pref = PreferenciaAviso.objects.filter(usuario=request.user).first()
    if pref and pref.telegram_conectado:
        pref.desconectar_telegram()
        request.session["aviso_notificacao"] = ("ok", "Telegram desconectado.")
    return redirect("notificacoes", empresa_slug=empresa.slug)


@login_required
@require_GET
def status_telegram(request, empresa_slug):
    """A tela pergunta a cada poucos segundos se a pessoa ja apertou 'Iniciar' no robo."""
    empresa_permitida(request.user, empresa_slug)
    pref = PreferenciaAviso.objects.filter(usuario=request.user).first()
    if pref and not pref.telegram_conectado and pref.telegram_codigo_hash:
        try:
            processar_atualizacoes(0)  # le o robo agora (sem esperar o comando 'avisos')
        except ErroEnvio:
            pass
        pref.refresh_from_db()
    return JsonResponse({"conectado": bool(pref and pref.telegram_conectado),
                         "nome": pref.telegram_nome if pref else ""})


@login_required
@require_POST
def enviar_teste(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    pref = PreferenciaAviso.objects.filter(usuario=request.user).first()
    if not _pode_receber(request.user) or not pref:
        return redirect("notificacoes", empresa_slug=empresa.slug)
    uma_hora = timezone.now() - timedelta(hours=1)
    if EnvioAviso.objects.filter(usuario=request.user, tipo=EnvioAviso.Tipo.TESTE, criado_em__gte=uma_hora).count() >= LIMITE_TESTES_POR_HORA:
        request.session["aviso_notificacao"] = ("erro", "Muitos testes seguidos. Tente de novo daqui a pouco.")
    elif not pref.canais_ativos():
        request.session["aviso_notificacao"] = ("erro", "Nenhum canal pronto: conecte o Telegram ou marque o e-mail e salve.")
    else:
        ontem = timezone.localdate() - timedelta(days=1)
        mensagem = resumo_diario(request.user, empresa, ontem)
        resultados = enviar(pref, mensagem, EnvioAviso.Tipo.TESTE)
        nomes = {"telegram": "Telegram", "email": "e-mail"}
        if all(ok for _, ok, _ in resultados):
            request.session["aviso_notificacao"] = ("ok", "Teste enviado por " + " e ".join(nomes[c] for c, _, _ in resultados) + ".")
        else:
            falhas = "; ".join(f"{nomes[c]}: {erro}" for c, ok, erro in resultados if not ok)
            request.session["aviso_notificacao"] = ("erro", f"Não foi possível enviar. {falhas}")
    return redirect("notificacoes", empresa_slug=empresa.slug)
