"""
Enderecos (URLs) do DualFlux Central.

Ordem importa: o Django testa de cima para baixo. Por isso os enderecos fixos
(admin, api, login, logout) vem ANTES dos enderecos com slug da empresa/loja.
"""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from contas import views as contas_views
from contas.acesso import confirmar_codigo, esqueci_senha, nova_senha
from contas.clientes import clientes
from contas import equipe as equipe_views
from contas.senha import SenhaAlterada, TrocarSenha
from fluxo.api import EventosView, VendasView
from fluxo.rede import empresa_painel
from fluxo.relatorios import relatorios
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
    # Acesso por codigo de 6 digitos: esqueci a senha e primeiro acesso (convite).
    path("acesso/esqueci/", esqueci_senha, name="esqueci_senha"),
    path("acesso/codigo/", confirmar_codigo, name="confirmar_codigo"),
    path("acesso/nova-senha/", nova_senha, name="nova_senha"),

    # Telas do cliente.
    path("", contas_views.inicio, name="inicio"),
    # Central do administrador DualFlux (antes das rotas com slug: "clientes" nao e empresa).
    path("clientes/", clientes, name="clientes"),
    # Trocar a propria senha (qualquer usuario logado).
    path("conta/senha/", TrocarSenha.as_view(), name="trocar_senha"),
    path("conta/senha/alterada/", SenhaAlterada.as_view(), name="senha_alterada"),
    # Visao da rede: o nome continua "empresa_inicio" para nao quebrar links antigos.
    path("<slug:empresa_slug>/", empresa_painel, name="empresa_inicio"),
    # Tela onde o cliente monta o relatorio (antes da rota da loja: "relatorios" nao e loja).
    path("<slug:empresa_slug>/relatorios/", relatorios, name="relatorios"),
    # Equipe: so o dono (gerentes da propria empresa).
    path("<slug:empresa_slug>/equipe/", equipe_views.equipe, name="equipe"),
    path("<slug:empresa_slug>/equipe/novo/", equipe_views.gerente_novo, name="gerente_novo"),
    path("<slug:empresa_slug>/equipe/<int:pk>/", equipe_views.gerente_editar, name="gerente_editar"),
    path("<slug:empresa_slug>/equipe/<int:pk>/convite/", equipe_views.gerente_reenviar_convite, name="gerente_reenviar_convite"),
    path("<slug:empresa_slug>/equipe/<int:pk>/ativo/", equipe_views.gerente_ativar, name="gerente_ativar"),
    path("<slug:empresa_slug>/<slug:loja_slug>/", loja_painel, name="loja_painel"),
    # Relatorio da loja: a MESMA view do painel, desenhando outro template (numeros identicos).
    path("<slug:empresa_slug>/<slug:loja_slug>/relatorio/", loja_painel,
         {"template": "fluxo/loja_relatorio.html"}, name="loja_relatorio"),
]
