"""
Eventos no Django Admin: SO PARA CONSULTA.

Eventos chegam apenas pela API das lojas. Criar ou editar a mao no admin
quebraria a regra de que o evento e uma copia fiel do que a loja contou.
"""

from django.contrib import admin

from .models import Evento


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("instante", "loja", "camera", "direcao", "recebido_em")
    list_filter = ("direcao", "loja__empresa", "loja")
    # Navegacao por data no topo da lista (ano > mes > dia).
    date_hierarchy = "instante"
    # Busca pelo uuid: util para investigar um evento especifico.
    search_fields = ("uuid",)
    # Carrega loja e camera junto, em vez de uma consulta extra por linha.
    list_select_related = ("loja", "camera")

    # Tudo bloqueado para edicao: so leitura.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
