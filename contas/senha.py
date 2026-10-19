"""
TROCAR SENHA: qualquer usuario logado troca a PROPRIA senha.

Usamos as telas prontas do Django (PasswordChangeView), so com a nossa aparencia.
Elas ja fazem o que importa para seguranca:
- pedem a senha ATUAL (quem pegar um computador logado nao consegue trocar);
- aplicam as regras de senha forte (AUTH_PASSWORD_VALIDATORS do settings);
- depois da troca, derrubam as outras sessoes abertas desse usuario em outros
  computadores, e mantem a pessoa logada so onde ela trocou.
"""

from django.contrib.auth.views import PasswordChangeDoneView, PasswordChangeView
from django.urls import reverse_lazy


class TrocarSenha(PasswordChangeView):
    template_name = "contas/trocar_senha.html"
    success_url = reverse_lazy("senha_alterada")


class SenhaAlterada(PasswordChangeDoneView):
    template_name = "contas/senha_alterada.html"
