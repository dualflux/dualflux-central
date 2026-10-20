"""
EQUIPE: o dono cadastra e gerencia os GERENTES da propria empresa.

Regras (todas conferidas no servidor):
- so o DONO da empresa (ou o administrador DualFlux) acessa; gerente recebe 404;
- o dono so mexe em GERENTES da propria empresa (nunca em outro dono, nem em si mesmo);
- as lojas oferecidas sao so as da empresa;
- o gerente novo nasce SEM senha: entra pelo "Primeiro acesso" com o codigo do convite;
- desativar corta o acesso na hora (mesmo de quem esta logado) e anula codigos abertos.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from fluxo.rede import empresa_permitida

from .acesso import enviar_codigo, pode_receber_codigo
from .models import CodigoAcesso, Usuario


def dono_da_empresa(request, empresa_slug):
    """Empresa do endereco, se quem pede for o dono dela (ou admin). Senao, 404."""
    empresa = empresa_permitida(request.user, empresa_slug)
    if request.user.papel not in (Usuario.Papel.DONO, Usuario.Papel.ADMIN):
        raise Http404
    return empresa


def gerente_da_empresa(empresa, pk):
    """So gerentes DESTA empresa podem ser alterados pela tela Equipe."""
    return get_object_or_404(Usuario, pk=pk, empresa=empresa, papel=Usuario.Papel.GERENTE)


def situacao(usuario):
    if not usuario.is_active:
        return "desativado"
    if not usuario.has_usable_password():
        return "pendente"
    return "ativo"


class FormGerente(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail")
    lojas = forms.ModelMultipleChoiceField(queryset=None, label="Lojas", widget=forms.CheckboxSelectMultiple,
                                           error_messages={"required": "Marque pelo menos uma loja."})

    def __init__(self, *args, empresa, editando=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editando = editando
        self.fields["lojas"].queryset = empresa.lojas.filter(ativa=True).order_by("nome")
        if editando:
            self.fields["email"].disabled = True  # o e-mail e o login: nao muda pela tela

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        outros = Usuario.objects.filter(email__iexact=email)
        if self.editando:
            outros = outros.exclude(pk=self.editando.pk)
        if outros.exists():
            raise forms.ValidationError("Este e-mail já está em uso. Se for de outra empresa, fale com o suporte DualFlux.")
        return email


# ----------------------------------------------------------------------
# Lista
# ----------------------------------------------------------------------

@login_required
def equipe(request, empresa_slug):
    empresa = dono_da_empresa(request, empresa_slug)
    pessoas = (Usuario.objects.filter(empresa=empresa).prefetch_related("lojas")
               .order_by("papel", "-is_active", "first_name", "email"))
    itens = [{"u": u, "situacao": situacao(u), "lojas": [l.nome for l in u.lojas.all()]} for u in pessoas]
    # Codigo recem-gerado (convite ou reenvio): mostrado UMA vez, para o dono repassar.
    convite = request.session.pop("equipe_convite", None)
    return render(request, "contas/equipe.html", {"empresa": empresa, "itens": itens, "convite": convite})


def guardar_convite_para_mostrar(request, usuario, codigo):
    request.session["equipe_convite"] = {
        "nome": usuario.get_full_name() or usuario.email,
        "email": usuario.email,
        "codigo": codigo,
        "link": request.build_absolute_uri(reverse("confirmar_codigo") + "?primeiro=1"),
    }


# ----------------------------------------------------------------------
# Novo gerente / editar gerente
# ----------------------------------------------------------------------

@login_required
def gerente_novo(request, empresa_slug):
    empresa = dono_da_empresa(request, empresa_slug)
    form = FormGerente(request.POST or None, empresa=empresa)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        gerente = Usuario.objects.create_user(
            dados["email"], None,  # sem senha: o gerente cria a dele no primeiro acesso
            first_name=dados["first_name"], last_name=dados["last_name"],
            papel=Usuario.Papel.GERENTE, empresa=empresa,
        )
        gerente.lojas.set(dados["lojas"])
        codigo = enviar_codigo(gerente, CodigoAcesso.Finalidade.CONVITE,
                               convidado_por=request.user.get_full_name() or request.user.email)
        guardar_convite_para_mostrar(request, gerente, codigo)
        return redirect("equipe", empresa_slug=empresa.slug)
    return render(request, "contas/equipe_form.html", {"empresa": empresa, "form": form, "editando": None})


@login_required
def gerente_editar(request, empresa_slug, pk):
    empresa = dono_da_empresa(request, empresa_slug)
    gerente = gerente_da_empresa(empresa, pk)
    inicial = {"first_name": gerente.first_name, "last_name": gerente.last_name,
               "email": gerente.email, "lojas": gerente.lojas.all()}
    form = FormGerente(request.POST or None, empresa=empresa, editando=gerente, initial=inicial)
    if request.method == "POST" and form.is_valid():
        gerente.first_name = form.cleaned_data["first_name"]
        gerente.last_name = form.cleaned_data["last_name"]
        gerente.save(update_fields=["first_name", "last_name"])
        gerente.lojas.set(form.cleaned_data["lojas"])
        return redirect("equipe", empresa_slug=empresa.slug)
    return render(request, "contas/equipe_form.html", {"empresa": empresa, "form": form, "editando": gerente})


# ----------------------------------------------------------------------
# Acoes (so por POST: um link malicioso nao consegue disparar)
# ----------------------------------------------------------------------

@login_required
@require_POST
def gerente_reenviar_convite(request, empresa_slug, pk):
    empresa = dono_da_empresa(request, empresa_slug)
    gerente = gerente_da_empresa(empresa, pk)
    if gerente.is_active and not gerente.has_usable_password() and pode_receber_codigo(gerente):
        codigo = enviar_codigo(gerente, CodigoAcesso.Finalidade.CONVITE,
                               convidado_por=request.user.get_full_name() or request.user.email)
        guardar_convite_para_mostrar(request, gerente, codigo)
    return redirect("equipe", empresa_slug=empresa.slug)


@login_required
@require_POST
def gerente_ativar(request, empresa_slug, pk):
    empresa = dono_da_empresa(request, empresa_slug)
    gerente = gerente_da_empresa(empresa, pk)
    gerente.is_active = not gerente.is_active
    gerente.save(update_fields=["is_active"])
    if not gerente.is_active:
        # Desativado: anula codigos abertos. A sessao dele deixa de valer sozinha
        # (o Django recusa usuario inativo a cada pedido).
        gerente.codigos_acesso.filter(usado_em__isnull=True).update(usado_em=timezone.now())
    return redirect("equipe", empresa_slug=empresa.slug)
