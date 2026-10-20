"""
ACESSO POR CODIGO: "Esqueci minha senha" e "Primeiro acesso" (convite).

Fluxo (3 telas):
1. esqueci_senha: a pessoa digita o e-mail; se ele existir, enviamos um codigo
   de 6 digitos. A mensagem e SEMPRE a mesma (existindo ou nao o e-mail), para
   ninguem descobrir quais e-mails sao clientes.
2. confirmar_codigo: digita e-mail + codigo. Errou 5 vezes: o codigo e anulado.
3. nova_senha: cria a senha (mesmas regras de senha forte) e ja entra no painel.

Protecoes extras:
- no maximo 5 codigos por pessoa por hora (ninguem fica "chutando" codigos novos);
- a tela 3 so abre logo depois de acertar o codigo (10 minutos, na mesma sessao);
- criar a senha nova derruba as sessoes antigas daquela pessoa.
"""

import logging
import time
from datetime import timedelta

from django import forms
from django.contrib.auth import login
from django.contrib.auth.forms import SetPasswordForm
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import CodigoAcesso, Empresa, Usuario

log = logging.getLogger(__name__)

LIMITE_CODIGOS_POR_HORA = 5
JANELA_NOVA_SENHA_S = 10 * 60  # depois de acertar o codigo, 10 min para criar a senha


# ----------------------------------------------------------------------
# Envio do e-mail com o codigo
# ----------------------------------------------------------------------

def enviar_codigo(usuario, finalidade, convidado_por=None):
    """Gera o codigo, manda por e-mail e devolve o codigo (para o dono poder repassar no convite)."""
    _, codigo = CodigoAcesso.gerar(usuario, finalidade)
    codigo_formatado = f"{codigo[:3]} {codigo[3:]}"
    if finalidade == CodigoAcesso.Finalidade.CONVITE:
        assunto = f"Seu acesso ao DualFlux - código {codigo_formatado}"
        abertura = (f"{convidado_por} convidou você para acompanhar o painel da {usuario.empresa.nome} no DualFlux."
                    if convidado_por else "Você foi convidado para acessar o DualFlux.")
        validade = "O código vale por 3 dias."
        passo = "Na tela de login, clique em \"Primeiro acesso\", digite seu e-mail e este código, e crie sua senha."
    else:
        assunto = f"Código para criar uma nova senha - {codigo_formatado}"
        abertura = "Recebemos um pedido para criar uma nova senha para a sua conta no DualFlux."
        validade = "O código vale por 15 minutos."
        passo = "Digite este código na tela que ficou aberta e crie sua nova senha."

    texto = (
        f"Olá{', ' + usuario.first_name if usuario.first_name else ''}!\n\n"
        f"{abertura}\n\n"
        f"Seu código: {codigo_formatado}\n\n"
        f"{passo}\n{validade}\n\n"
        "Se você não pediu isso, ignore este e-mail: sua senha continua a mesma.\n\n"
        "DualFlux - inteligência de fluxo para o varejo físico"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
      <h2 style="margin:0 0 12px">DualFlux</h2>
      <p>{abertura}</p>
      <p style="margin:22px 0;text-align:center">
        <span style="display:inline-block;padding:14px 22px;border-radius:12px;background:#eef4ff;color:#0a5cff;
                     font-size:30px;font-weight:800;letter-spacing:6px">{codigo_formatado}</span>
      </p>
      <p>{passo}<br><strong>{validade}</strong></p>
      <p style="color:#64748b;font-size:13px">Se você não pediu isso, ignore este e-mail: sua senha continua a mesma.</p>
    </div>"""
    send_mail(assunto, texto, None, [usuario.email], html_message=html)
    return codigo_formatado


def pode_receber_codigo(usuario):
    """Conta ativa, de empresa ativa (ou admin), e sem passar do limite de codigos por hora."""
    if not usuario.is_active:
        return False
    if usuario.papel != Usuario.Papel.ADMIN and usuario.empresa.status != Empresa.Status.ATIVA:
        return False
    uma_hora = timezone.now() - timedelta(hours=1)
    return usuario.codigos_acesso.filter(criado_em__gte=uma_hora).count() < LIMITE_CODIGOS_POR_HORA


# ----------------------------------------------------------------------
# Tela 1: pedir o codigo
# ----------------------------------------------------------------------

class FormEmail(forms.Form):
    email = forms.EmailField(label="E-mail")


@require_http_methods(["GET", "POST"])
def esqueci_senha(request):
    form = FormEmail(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        usuario = Usuario.objects.filter(email__iexact=email).select_related("empresa").first()
        if usuario and pode_receber_codigo(usuario):
            enviar_codigo(usuario, CodigoAcesso.Finalidade.RECUPERAR)
        else:
            log.info("Pedido de codigo sem envio (e-mail inexistente, inativo ou limite): %s", email)
        # Mesma resposta em todos os casos.
        request.session["acesso_email"] = email
        return redirect("confirmar_codigo")
    return render(request, "registration/acesso_esqueci.html", {"form": form})


# ----------------------------------------------------------------------
# Tela 2: digitar o codigo
# ----------------------------------------------------------------------

class FormCodigo(forms.Form):
    email = forms.EmailField(label="E-mail")
    codigo = forms.CharField(label="Código", max_length=12)

    def clean_codigo(self):
        codigo = "".join(c for c in self.cleaned_data["codigo"] if c.isdigit())
        if len(codigo) != 6:
            raise forms.ValidationError("O código tem 6 números.")
        return codigo


@require_http_methods(["GET", "POST"])
def confirmar_codigo(request):
    primeiro_acesso = request.GET.get("primeiro") == "1"
    form = FormCodigo(request.POST or None, initial={"email": request.session.get("acesso_email", "")})
    erro = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        usuario = Usuario.objects.filter(email__iexact=email, is_active=True).first()
        registro = (usuario.codigos_acesso.filter(usado_em__isnull=True).order_by("-criado_em").first()
                    if usuario else None)
        if registro and registro.conferir(form.cleaned_data["codigo"]):
            request.session["acesso_codigo_id"] = registro.pk
            request.session["acesso_ok_em"] = time.time()
            return redirect("nova_senha")
        restantes = (CodigoAcesso.MAX_TENTATIVAS - registro.tentativas) if registro and registro.valido else 0
        erro = ("Código incorreto. Você ainda tem {} tentativa{}.".format(restantes, "s" if restantes > 1 else "")
                if restantes else "Código inválido ou expirado. Peça um código novo.")
    return render(request, "registration/acesso_codigo.html",
                  {"form": form, "erro": erro, "primeiro_acesso": primeiro_acesso})


# ----------------------------------------------------------------------
# Tela 3: criar a senha
# ----------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def nova_senha(request):
    codigo_id = request.session.get("acesso_codigo_id")
    ok_em = request.session.get("acesso_ok_em", 0)
    registro = CodigoAcesso.objects.filter(pk=codigo_id).select_related("usuario").first() if codigo_id else None
    if not registro or not registro.valido or time.time() - ok_em > JANELA_NOVA_SENHA_S:
        for chave in ("acesso_codigo_id", "acesso_ok_em"):
            request.session.pop(chave, None)
        return redirect("esqueci_senha")

    usuario = registro.usuario
    form = SetPasswordForm(usuario, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()  # grava so o hash; a troca derruba as sessoes antigas
        agora = timezone.now()
        usuario.codigos_acesso.filter(usado_em__isnull=True).update(usado_em=agora)
        for chave in ("acesso_codigo_id", "acesso_ok_em", "acesso_email"):
            request.session.pop(chave, None)
        login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("inicio")
    return render(request, "registration/acesso_nova_senha.html",
                  {"form": form, "usuario": usuario, "convite": registro.finalidade == CodigoAcesso.Finalidade.CONVITE})
