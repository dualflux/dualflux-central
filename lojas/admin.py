"""
Registro de Regiao e Loja no Django Admin.

Camera e Horario de funcionamento NAO tem tela propria: aparecem DENTRO
da tela da Loja (inlines). Assim voce cadastra tudo de uma loja num lugar so.
"""

from django.contrib import admin

from .models import Camera, HorarioFuncionamento, Loja, Regiao


@admin.register(Regiao)
class RegiaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa")
    list_filter = ("empresa",)
    search_fields = ("nome",)


class HorarioInline(admin.TabularInline):
    """Tabelinha de horarios dentro da tela da Loja (uma linha por dia)."""

    model = HorarioFuncionamento
    extra = 1    # mostra 1 linha em branco; o botao "Adicionar outro" cria mais
    max_num = 7  # no maximo 7 linhas: uma por dia da semana


class CameraInline(admin.TabularInline):
    """Tabelinha de cameras dentro da tela da Loja."""

    model = Camera
    extra = 1
    fields = ("codigo", "nome", "ativa")


@admin.register(Loja)
class LojaAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "regiao", "cidade", "hostname", "ativa")
    list_filter = ("empresa", "regiao", "ativa")
    search_fields = ("nome", "slug", "hostname", "cidade")
    # O endereco (slug) e sugerido enquanto voce digita o nome.
    prepopulated_fields = {"slug": ("nome",)}
    readonly_fields = ("criado_em", "atualizado_em")

    # A tela da loja dividida em blocos, do mais importante ao menos.
    fieldsets = (
        (None, {"fields": ("empresa", "nome", "slug", "ativa")}),
        ("Servidor local", {"fields": ("hostname", "fuso_horario", "dados_validos_desde")}),
        ("Localizacao", {"fields": ("endereco", "cidade", "uf", "regiao")}),
        ("Datas", {"fields": ("criado_em", "atualizado_em")}),
    )

    # Horarios e cameras aparecem no final da tela da loja.
    inlines = [HorarioInline, CameraInline]