"""
ICONES 3D do DualFlux (Microsoft Fluent Emoji, licenca MIT: gratuito, sem link).

Por que imagens e nao emojis?
Emoji e desenhado pelo aparelho: cada sistema (Windows, Android, iPhone)
mostra um desenho diferente. As imagens ficam em static/img/icones/ e
aparecem IGUAIS em qualquer tela.

Dois jeitos de usar no template (depois de {% load icones %}):

    {% icone "lampada" %}            -> icone pelo nome do arquivo (tamanho padrao 28)
    {% icone "loja" 20 %}            -> com tamanho em pixels
    {{ insight.icone|icone_emoji }}  -> converte o emoji que a view mandou

O filtro permite que as views continuem mandando emojis (ex.: "🔥") sem
mudar nada no Python: o template troca pelo icone 3D. Emoji desconhecido
continua aparecendo como emoji (nada quebra).
"""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

# Emoji -> nome do arquivo em static/img/icones/ (sem o .png).
# O "️" e um caractere invisivel que alguns emojis carregam; e removido antes.
EMOJI_PARA_ICONE = {
    "💡": "lampada", "🔥": "fogo", "💰": "saco-dinheiro", "📡": "antena", "⚠": "aviso",
    "📈": "grafico-sobe", "📉": "grafico-desce", "📊": "grafico-barras",
    "🔻": "seta-vermelha-baixo", "🔺": "seta-vermelha-cima", "⬆": "seta-cima", "⬇": "seta-baixo",
    "👥": "pessoas", "🚪": "porta", "🛒": "carrinho", "🏪": "loja", "🏬": "rede",
    "📅": "calendario", "📆": "calendario", "🗓": "calendario-espiral",
    "⏰": "despertador", "⏱": "cronometro", "🕘": "despertador", "🕐": "despertador", "⏳": "ampulheta",
    "🌅": "nascer-sol", "☀": "sol", "🌙": "lua", "🌗": "nascer-sol", "🌧": "chuva",
    "📍": "alfinete", "🔔": "sino", "⚙": "engrenagem", "🏆": "trofeu", "🎯": "alvo",
    "✅": "check", "⚡": "raio", "✨": "brilho", "🌟": "estrela", "⭐": "estrela", "🚀": "foguete",
    "🔍": "lupa", "🧾": "recibo", "🪙": "moeda",
}


def _imagem(nome, tamanho, classe=""):
    return format_html(
        '<img src="{}" width="{}" height="{}" alt="" class="ic3d {}" loading="lazy" decoding="async">',
        static(f"img/icones/{nome}.png"), tamanho, tamanho, classe,
    )


@register.simple_tag
def icone(nome, tamanho=28, classe=""):
    """Desenha um icone 3D pelo nome do arquivo."""
    return _imagem(nome, tamanho, classe)


@register.filter
def icone_emoji(emoji, tamanho=28):
    """Troca um emoji pelo icone 3D equivalente (ou devolve o proprio emoji)."""
    texto = str(emoji or "").replace("️", "").strip()
    nome = EMOJI_PARA_ICONE.get(texto)
    if nome is None:
        return emoji
    return _imagem(nome, tamanho)
