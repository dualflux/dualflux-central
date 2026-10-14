"""
Registro de Empresa e Usuario no Django Admin (/admin).

O admin e a ferramenta de ADMINISTRACAO DualFlux (so voce acessa):
cadastrar clientes, usuarios e, depois, lojas e tokens.
Os clientes nunca usam esta tela; eles terao o dashboard proprio.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

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

    def clean(self):
        """
        Trava das lojas do gerente.

        Por que aqui no formulario, e nao no clean() do modelo? Porque um campo
        "muitos para muitos" so e gravado DEPOIS do usuario; no clean() do modelo
        as lojas escolhidas ainda nao estao disponiveis. O formulario ja as tem.
        """
        dados = super().clean()
        empresa = dados.get("empresa")
        papel = dados.get("papel")
        lojas = dados.get("lojas")

        if lojas:
            # Dono ve todas as lojas da empresa; administrador ve tudo.
            # Marcar lojas para eles nao faria sentido e confundiria depois.
            if papel != Usuario.Papel.GERENTE:
                raise ValidationError({"lojas": "So o gerente tem lojas marcadas. Deixe vazio para dono e administrador."})

            # A regra de seguranca: nenhuma loja de OUTRA empresa.
            de_fora = [loja for loja in lojas if empresa is None or loja.empresa_id != empresa.id]
            if de_fora:
                nomes = ", ".join(str(loja) for loja in de_fora)
                raise ValidationError({"lojas": f"Estas lojas sao de outra empresa: {nomes}"})

        return dados


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

    # Caixa dupla para escolher lojas: disponiveis a esquerda, escolhidas a direita.
    filter_horizontal = ("lojas",)

    # Tela de EDICAO de um usuario existente, dividida em blocos.
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("first_name", "last_name")}),
        ("Acesso ao DualFlux", {"fields": ("empresa", "papel", "lojas")}),
        ("Permissoes do painel", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )

    # Tela de CRIACAO de um usuario novo: so o essencial.
    # As lojas do gerente sao escolhidas depois, na tela de edicao.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "empresa", "papel", "password1", "password2"),
        }),
    )