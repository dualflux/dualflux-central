# ============================================================
# Receita do container do DualFlux Central (Django).
# ============================================================

# Imagem base: Python 3.12, a mesma versao do notebook e do servidor da loja.
# "slim" e a versao enxuta, sem ferramentas desnecessarias (imagem menor).
FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: nao cria arquivos .pyc (inuteis no container).
# PYTHONUNBUFFERED: mostra os logs na hora (sem isso, o Python segura as mensagens).
# POETRY_VIRTUALENVS_CREATE=false: o container ja e isolado; nao precisa de venv dentro.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.5.1 \
    POETRY_VIRTUALENVS_CREATE=false

# Pasta de trabalho dentro do container.
WORKDIR /app

# Instala o Poetry na MESMA versao do notebook.
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Copia SO a lista de bibliotecas primeiro e instala.
# Por que separado? O Docker guarda cada etapa em cache: se voce mudar so o
# codigo, ele reaproveita esta etapa e nao reinstala tudo de novo (build rapido).
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --only main

# Agora copia o codigo do projeto (respeitando o .dockerignore).
COPY . .

# Porta onde o Django escuta dentro do container.
EXPOSE 8000

# Comando de DESENVOLVIMENTO: servidor simples do Django, que recarrega sozinho
# quando o codigo muda. No VPS (Sprint 6) sera trocado pelo Gunicorn, feito para producao.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]