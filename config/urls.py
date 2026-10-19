"""
Enderecos (URLs) do DualFlux Central.

Ordem importa: o Django testa de cima para baixo. Por isso os enderecos fixos
(admin, api, login, logout) vem ANTES dos enderecos com slug da empresa/loja.
"""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from contas import views as contas_views
from contas.clientes import clientes
from contas.senha import SenhaAlterada, TrocarSenha
from fluxo.api import EventosView, VendasView
from fluxo.rede import empresa_painel
from fluxo.views import loja_painel
from monitor.api import HeartbeatView

urlpatterns = [
    path("admin/", admin.site.urls),

    # API usada pelos servidores das lojas (token Bearer).
    path("api/v1/eventos/", EventosView.as_view(), name="api_eventos"),
    path("api/v1/vendas/", VendasView.as_view(), name="api_vendas"),
    path("api/v1/heartbeat/", HeartbeatView.as_view(), name="api_heartbeat"),

    # Entrada e saida do sistema.
    path("login/", contas_views.Login.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),

    # Telas do cliente.
    path("", contas_views.inicio, name="inicio"),
    # Central do administrador DualFlux (antes das rotas com slug: "clientes" nao e empresa).
    path("clientes/", clientes, name="clientes"),
    # Trocar a propria senha (qualquer usuario logado).
    path("conta/senha/", TrocarSenha.as_view(), name="trocar_senha"),
    path("conta/senha/alterada/", SenhaAlterada.as_view(), name="senha_alterada"),
    # Visao da rede: o nome continua "empresa_inicio" para nao quebrar links antigos.
    path("<slug:empresa_slug>/", empresa_painel, name="empresa_inicio"),
    path("<slug:empresa_slug>/<slug:loja_slug>/", loja_painel, name="loja_painel"),
]
