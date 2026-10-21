"""Admin DualFlux: so consulta (quem esta conectado e o historico de envios). Ninguem edita por aqui."""

from django.contrib import admin

from .models import EnvioAviso, PreferenciaAviso


class SoLeitura(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PreferenciaAviso)
class PreferenciaAvisoAdmin(SoLeitura):
    list_display = ("usuario", "receber_diario", "receber_semanal", "receber_alertas", "horario",
                    "telegram_conectado", "canal_email", "aceite_em")
    list_filter = ("receber_diario", "receber_semanal", "receber_alertas", "canal_email")
    search_fields = ("usuario__email",)
    # O hash do codigo de conexao e o numero da conversa nao aparecem.
    exclude = ("telegram_codigo_hash", "telegram_codigo_em", "telegram_chat_id")

    @admin.display(boolean=True, description="Telegram")
    def telegram_conectado(self, obj):
        return obj.telegram_conectado


@admin.register(EnvioAviso)
class EnvioAvisoAdmin(SoLeitura):
    list_display = ("criado_em", "usuario", "tipo", "canal", "ok", "erro")
    list_filter = ("tipo", "canal", "ok")
    search_fields = ("usuario__email",)
