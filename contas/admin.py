"""
Registro de Empresa e Usuario no Django Admin (/admin).

O admin e a ferramenta de ADMINISTRACAO DualFlux (so voce acessa):
cadastrar clientes, usuarios e, depois, lojas e tokens.
Os clientes nunca usam esta tela; eles terao o dashboard proprio.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Empresa, Usuario


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    # Colunas da lista de empresas.
    list_display = ("nome", "slug", "status", "plano", "criado_em")
    # Filtros na lateral direita da lista.
    list_filter = ("status", "plano")
    # Caixa de busca: procura pelo nome ou pelo endereco.
    search_fields = ("nome", "slug")
    # Enquanto voce digita o nome, o endereco (slug) e sugerido automaticamente.
    # Ex.: "Farmacias Sao Joao" -> "farmacias-sao-joao". Voce pode editar antes de salvar.
    prepopulated_fields = {"slug": ("nome",)}
    # Datas preenchidas pelo sistema: aparecem, mas nao podem ser editadas.
    readonly_fields = ("criado_em", "atualizado_em")


# --- Formularios do Usuario ---
# Os formularios padrao do Django apontam para o usuario padrao (com username).
# Aqui so dizemos: "use o NOSSO modelo, com o e-mail como login".

class UsuarioCriacaoForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("email",)


class UsuarioAlteracaoForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    # Aproveitamos todo o UserAdmin do Django (troca de senha com hash,
    # permissoes etc.) e so ajustamos os campos.
    form = UsuarioAlteracaoForm
    add_form = UsuarioCriacaoForm

    list_display = ("email", "empresa", "papel", "is_active", "is_staff")
    list_filter = ("papel", "empresa", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    # Tela de EDICAO de um usuario existente, dividida em blocos.
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("first_name", "last_name")}),
        ("Acesso ao DualFlux", {"fields": ("empresa", "papel")}),
        ("Permissoes do painel", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )

    # Tela de CRIACAO de um usuario novo: so o essencial.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "empresa", "papel", "password1", "password2"),
        }),
    )