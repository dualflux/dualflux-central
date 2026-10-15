"""
Status das lojas no Django Admin: SO PARA CONSULTA.

O status chega apenas pelo heartbeat das lojas. Aqui voce ve, numa lista,
quais lojas estao online, se as cameras estao ok e se o relogio esta certo.
"""

from django.contrib import admin

from .models import StatusLoja


@admin.register(StatusLoja)
class StatusLojaAdmin(admin.ModelAdmin):
    list_display = (
        "loja", "esta_online", "cameras_em_ordem", "relogio_em_ordem",
        "ultimo_heartbeat", "versao", "disco_livre_pct", "eventos_pendentes",
    )
    list_filter = ("loja__empresa",)
    list_select_related = ("loja", "loja__empresa")

    # @admin.display(boolean=True) faz o admin mostrar icones (verde/vermelho)
    # em vez de "True"/"False".
    @admin.display(boolean=True, description="online")
    def esta_online(self, obj):
        return obj.online

    @admin.display(boolean=True, description="cameras ok")
    def cameras_em_ordem(self, obj):
        return obj.cameras_ok

    @admin.display(boolean=True, description="relogio ok")
    def relogio_em_ordem(self, obj):
        return obj.relogio_ok

    # Tudo so leitura.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False