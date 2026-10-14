"""
Telas dos CLIENTES (donos e gerentes): login e pagina inicial da empresa.

O /admin e o portao da equipe DualFlux. Estas telas sao o portao dos clientes.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import Empresa, Usuario


class LoginForm(AuthenticationForm):
    """Formulario de login padrao do Django, com UMA regra a mais."""

    def confirm_login_allowed(self, user):
        # A regra padrao: recusa usuario desativado ("Ativo" desmarcado).
        super().confirm_login_allowed(user)
        # A nossa regra: recusa usuario de empresa suspensa.
        if user.empresa and user.empresa.status != Empresa.Status.ATIVA:
            raise forms.ValidationError(
                "O acesso desta empresa esta suspenso. Fale com a DualFlux.",
                code="empresa_suspensa",
            )


class Login(LoginView):
    """Tela de login. O Django ja faz quase tudo; so trocamos o formulario."""

    form_class = LoginForm
    # Quem ja esta logado e abre /login/ vai direto para a sua pagina.
    redirect_authenticated_user = True


@login_required  # quem nao esta logado e mandado para /login/
def inicio(request):
    """Porta de entrada: decide para onde cada usuario vai depois do login."""
    usuario = request.user
    if usuario.papel == Usuario.Papel.ADMIN:
        return redirect("admin:index")
    return redirect("empresa_inicio", empresa_slug=usuario.empresa.slug)


@login_required
def empresa_inicio(request, empresa_slug):
    """
    Pagina inicial da empresa: app.dualflux.com.br/<empresa>/
    Por enquanto lista as lojas; na Sprint 4 vira o dashboard.
    """
    empresa = get_object_or_404(Empresa, slug=empresa_slug)
    usuario = request.user
    eh_admin = usuario.papel == Usuario.Papel.ADMIN

    # REGRA MULTI-TENANT: so o administrador ve qualquer empresa.
    # Para os outros, empresa diferente da sua = "nao encontrada" (404),
    # sem revelar que aquela empresa existe.
    if not eh_admin and usuario.empresa_id != empresa.id:
        raise Http404

    # Empresa suspensa depois que a pessoa ja estava logada.
    if not eh_admin and empresa.status != Empresa.Status.ATIVA:
        raise PermissionDenied

    # Gerente: so as lojas marcadas para ele. Dono e administrador: todas.
    if usuario.papel == Usuario.Papel.GERENTE:
        lojas = usuario.lojas.filter(empresa=empresa, ativa=True)
    else:
        lojas = empresa.lojas.filter(ativa=True)

    return render(request, "contas/empresa_inicio.html", {"empresa": empresa, "lojas": lojas})