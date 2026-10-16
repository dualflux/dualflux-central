"""
Dados do MENU LATERAL, disponiveis em TODAS as telas.

Isto e um "context processor" do Django: uma funcao que roda antes de cada
tela ser desenhada e acrescenta variaveis ao template. Assim o base.html
consegue montar o menu (empresa e lojas) sem que cada view precise lembrar
de mandar esses dados.

As permissoes sao as mesmas das telas:
- gerente: so as lojas marcadas para ele;
- dono: todas as lojas ativas da empresa dele;
- administrador DualFlux (sem empresa): a empresa que ele estiver visitando.
"""

from .models import Empresa, Usuario


def menu_lateral(request):
    usuario = request.user
    if not usuario.is_authenticated:
        return {}

    # resolver_match: qual endereco foi aberto e com quais partes (empresa, loja).
    rota = getattr(request, "resolver_match", None)
    partes = rota.kwargs if rota else {}

    empresa = usuario.empresa
    if empresa is None and usuario.papel == Usuario.Papel.ADMIN and partes.get("empresa_slug"):
        empresa = Empresa.objects.filter(slug=partes["empresa_slug"]).first()
    if empresa is None:
        return {}

    if usuario.papel == Usuario.Papel.GERENTE:
        lojas = usuario.lojas.filter(empresa=empresa, ativa=True)
    else:
        lojas = empresa.lojas.filter(ativa=True)

    return {
        "menu_empresa": empresa,
        "menu_lojas": lojas.order_by("nome"),
        "menu_loja_atual": partes.get("loja_slug"),
        "menu_tela": rota.url_name if rota else "",
    }
