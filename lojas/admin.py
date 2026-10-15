"""
Registro de Regiao, Loja e Token de API no Django Admin.

Camera, Horario e Token aparecem DENTRO da tela da Loja (inlines).
O token e GERADO por uma acao na lista de lojas e mostrado uma unica vez.
"""

from django.contrib import admin, messages
from django.utils import timezone

from .models import Camera, HorarioFuncionamento, Loja, Regiao, TokenApi


@admin.register(Regiao)
class RegiaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa")
    list_filter = ("empresa",)
    search_fields = ("nome",)


class HorarioInline(admin.TabularInline):
    """Tabelinha de horarios dentro da tela da Loja (uma linha por dia)."""

    model = HorarioFuncionamento
    extra = 1
    max_num = 7


class CameraInline(admin.TabularInline):
    """Tabelinha de cameras dentro da tela da Loja."""

    model = Camera
    extra = 1
    fields = ("codigo", "nome", "ativa")


class TokenInline(admin.TabularInline):
    """
    Tokens da loja, SO PARA CONSULTA. Nao da para criar token aqui porque
    o token precisa ser gerado pelo sistema (aleatorio) e mostrado uma unica vez.
    """

    model = TokenApi
    extra = 0
    can_delete = False
    show_change_link = True  # link para a tela do token (onde fica o "revogar")
    fields = ("prefixo", "descricao", "criado_em", "ultimo_uso_em", "revogado_em")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Loja)
class LojaAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "regiao", "cidade", "hostname", "ativa")
    list_filter = ("empresa", "regiao", "ativa")
    search_fields = ("nome", "slug", "hostname", "cidade")
    prepopulated_fields = {"slug": ("nome",)}
    readonly_fields = ("criado_em", "atualizado_em")

    fieldsets = (
        (None, {"fields": ("empresa", "nome", "slug", "ativa")}),
        ("Servidor local", {"fields": ("hostname", "fuso_horario", "dados_validos_desde")}),
        ("Localizacao", {"fields": ("endereco", "cidade", "uf", "regiao")}),
        ("Datas", {"fields": ("criado_em", "atualizado_em")}),
    )

    inlines = [HorarioInline, CameraInline, TokenInline]
    actions = ["gerar_token"]

    @admin.action(description="Gerar token de API para a loja selecionada")
    def gerar_token(self, request, queryset):
        # Um token por vez: evita mostrar varios tokens misturados na mesma mensagem.
        if queryset.count() != 1:
            self.message_user(request, "Selecione exatamente UMA loja para gerar o token.", messages.ERROR)
            return
        loja = queryset.first()
        _, token_texto = TokenApi.gerar(loja, descricao=f"Gerado por {request.user.email}")
        # Faixa amarela (WARNING) de proposito: chama atencao para copiar AGORA.
        self.message_user(
            request,
            f"Token da loja {loja.nome} - copie AGORA, ele nao sera mostrado de novo: {token_texto}",
            messages.WARNING,
        )


@admin.register(TokenApi)
class TokenApiAdmin(admin.ModelAdmin):
    list_display = ("__str__", "loja", "descricao", "criado_em", "ultimo_uso_em", "revogado_em")
    list_filter = ("loja__empresa", "loja")
    fields = ("loja", "prefixo", "descricao", "criado_em", "ultimo_uso_em", "revogado_em")
    readonly_fields = ("loja", "prefixo", "criado_em", "ultimo_uso_em")
    actions = ["revogar"]

    def has_add_permission(self, request):
        # Token novo so pela acao "Gerar token" na lista de lojas.
        return False

    @admin.action(description="Revogar os tokens selecionados")
    def revogar(self, request, queryset):
        # Revogar = marcar a data; o registro fica, para o historico.
        quantos = queryset.filter(revogado_em__isnull=True).update(revogado_em=timezone.now())
        self.message_user(request, f"{quantos} token(s) revogado(s).", messages.SUCCESS)
