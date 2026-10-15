"""
Mapa de enderecos do DualFlux Central: qual URL chama qual tela.

A ORDEM importa: o Django testa de cima para baixo e usa a primeira que servir.
Por isso o endereco generico "<empresa>/" fica por ULTIMO; senao "login/"
seria confundido com uma empresa chamada "login" (e por isso esses nomes
sao reservados no cadastro de Empresa).
"""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from contas import views as contas_views
from fluxo.api import EventosView

urlpatterns = [
    path("admin/", admin.site.urls),                                  # portao da equipe DualFlux
    # --- API: usada pelos servidores das lojas (token), nunca por pessoas ---
    # O "v1" no caminho permite criar uma "v2" no futuro sem quebrar as lojas
    # que ainda estiverem com o software antigo.
    path("api/v1/eventos/", EventosView.as_view(), name="api_eventos"),
    # --- Telas dos clientes ---
    path("login/", contas_views.Login.as_view(), name="login"),       # portao dos clientes
    path("logout/", LogoutView.as_view(), name="logout"),             # sair
    path("", contas_views.inicio, name="inicio"),                     # decide para onde ir
    path("<slug:empresa_slug>/", contas_views.empresa_inicio, name="empresa_inicio"),
]