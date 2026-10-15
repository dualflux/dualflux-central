"""
Autenticacao da API: como o central reconhece QUAL LOJA esta enviando.

A loja manda o cabecalho:   Authorization: Bearer dfx_xxxxxxxx_yyyy...
Esta classe le o cabecalho, confere o token e entrega o token (e a loja) para a view.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions, permissions

from .models import TokenApi


class TokenLojaAuthentication(authentication.BaseAuthentication):
    palavra_chave = "Bearer"

    def authenticate(self, request):
        # O cabecalho chega em bytes; convertemos para texto.
        cabecalho = authentication.get_authorization_header(request).decode("latin-1")
        if not cabecalho:
            # Sem cabecalho: "nao autenticado". A permissao abaixo recusa com 401.
            return None

        partes = cabecalho.split()
        if len(partes) != 2 or partes[0] != self.palavra_chave:
            raise exceptions.AuthenticationFailed("Cabecalho invalido. Use: Authorization: Bearer <token>")

        token = TokenApi.verificar(partes[1])
        if token is None:
            raise exceptions.AuthenticationFailed("Token invalido ou revogado.")

        # A loja NAO e um usuario do sistema (nao faz login, nao tem senha).
        # Por isso request.user fica anonimo, e o TOKEN vai em request.auth.
        # As views pegam a loja assim: request.auth.loja
        return (AnonymousUser(), token)

    def authenticate_header(self, request):
        # Com isto o DRF responde 401 (nao autenticado) em vez de 403 (proibido),
        # que e a resposta correta para "faltou ou errou a credencial".
        return self.palavra_chave


class LojaAutenticada(permissions.BasePermission):
    """So deixa passar requisicoes que chegaram com um token de loja valido."""

    def has_permission(self, request, view):
        return isinstance(request.auth, TokenApi)