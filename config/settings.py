"""
Configuracoes do DualFlux Central (servidor SaaS).

Regra de ouro deste arquivo: NENHUMA senha ou chave escrita aqui.
Tudo o que muda de um ambiente para outro (notebook, homologacao, producao)
vem do arquivo .env, lido pela biblioteca django-environ. Assim este arquivo
pode ir para o Git sem expor nada.
"""

from pathlib import Path

import environ

# BASE_DIR = pasta raiz do projeto (onde estao o manage.py e o .env).
# __file__ e este arquivo (config/settings.py); subindo dois niveis chegamos a raiz.
BASE_DIR = Path(__file__).resolve().parent.parent

# Env() define os TIPOS de algumas variaveis. No .env tudo e texto;
# aqui avisamos que DJANGO_DEBUG deve virar booleano (True/False),
# com padrao False: se a variavel faltar, o site sobe no modo SEGURO.
env = environ.Env(DJANGO_DEBUG=(bool, False))

# Le o .env da raiz do projeto. Variaveis que ja existirem no ambiente
# (por exemplo, passadas pelo Docker Compose) tem prioridade sobre o arquivo.
environ.Env.read_env(BASE_DIR / ".env")


# ------------------------------------------------------------------
# Seguranca basica
# ------------------------------------------------------------------

# Chave que assina sessoes de login e cookies. Sem valor padrao de proposito:
# se faltar no .env, o Django para com erro em vez de subir com chave fraca.
SECRET_KEY = env("DJANGO_SECRET_KEY")

# True so no notebook: mostra erros detalhados no navegador.
DEBUG = env("DJANGO_DEBUG")

# Enderecos aceitos pelo site. env.list() transforma "a,b,c" em ["a", "b", "c"].
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])


# ------------------------------------------------------------------
# Aplicacoes instaladas
# ------------------------------------------------------------------

INSTALLED_APPS = [
    # Apps que ja vem com o Django:
    "django.contrib.admin",         # painel administrativo (/admin)
    "django.contrib.auth",          # usuarios, senhas, permissoes
    "django.contrib.contenttypes",  # base usada pelo auth e pelo admin
    "django.contrib.sessions",      # mantem o usuario logado entre paginas
    "django.contrib.messages",      # mensagens do tipo "salvo com sucesso"
    "django.contrib.staticfiles",   # CSS, JavaScript e imagens
    # Nossos apps:
    "contas",  # Empresa e Usuario
    "lojas",   # Regiao, Loja, Camera e Horario de funcionamento
    "fluxo",   # Eventos de entrada/saida, janelas de 15 min e vendas
    "monitor", # Saude das lojas: heartbeat e status online/offline
    "rest_framework",  # Django REST Framework: a API que recebe os dados das lojas
]

# ATENCAO: o modelo de Usuario personalizado (login por e-mail) precisa existir
# ANTES da primeira migracao do banco. Por isso a linha abaixo fica comentada
# ate criarmos o app "contas" -- e NAO rodamos "migrate" antes disso.
# AUTH_USER_MODEL = "contas.Usuario"

AUTH_USER_MODEL = "contas.Usuario"

# ------------------------------------------------------------------
# Middlewares: "filtros" por onde toda requisicao passa, em ordem
# ------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # protege formularios contra envio forjado
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Pasta para os templates (telas) gerais do projeto, como a de login.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "contas.contexto.menu_lateral",  # menu lateral em todas as telas
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ------------------------------------------------------------------
# Banco de dados: PostgreSQL, com os dados de conexao vindos do .env
# ------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
    }
}


# ------------------------------------------------------------------
# Validacao de senhas dos usuarios do SaaS (regras padrao do Django)
# ------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ------------------------------------------------------------------
# Idioma e fuso horario
# ------------------------------------------------------------------

LANGUAGE_CODE = "pt-br"

# USE_TZ = True: o banco guarda TODOS os horarios em UTC, com fuso anexado.
# E a mesma regra do contrato da API: as lojas enviam em UTC.
USE_TZ = True

# Fuso usado para EXIBIR horarios quando nenhum outro for indicado (ex.: no admin).
# Nos dashboards, cada loja sera exibida no fuso_horario cadastrado nela.
TIME_ZONE = "America/Campo_Grande"

USE_I18N = True


# ------------------------------------------------------------------
# Arquivos estaticos (CSS, JavaScript, imagens)
# ------------------------------------------------------------------

STATIC_URL = "static/"
# Pasta onde o "collectstatic" junta tudo para o Nginx servir no VPS.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Tipo padrao das chaves primarias: inteiro grande (aguenta bilhoes de eventos).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login dos clientes: para onde ir quando precisa entrar, depois de entrar e depois de sair.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

# Numeros no padrao brasileiro nas telas: 2.911 e 14,2
USE_THOUSAND_SEPARATOR = True

# Pasta das imagens e arquivos da marca (logo, icones).
STATICFILES_DIRS = [BASE_DIR / "static"]


# ----------------------------------------------------------------------
# SESSAO (quanto tempo a pessoa continua logada)
# ----------------------------------------------------------------------
# Sem isto, o Django mantem o login por 2 semanas: perigoso em computador
# de loja, onde varias pessoas usam a mesma maquina.

# Desloga depois de 8 horas SEM USO (um turno de trabalho).
SESSION_COOKIE_AGE = 8 * 60 * 60

# Cada clique "renova" as 8 horas: quem esta usando nao e deslogado no meio.
SESSION_SAVE_EVERY_REQUEST = True

# Fechou o navegador, saiu do sistema.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# ----------------------------------------------------------------------
# SEGURANCA DE PRODUCAO (liga sozinho quando DEBUG=False, ou seja, no VPS)
# ----------------------------------------------------------------------
# No notebook (DEBUG=True) nada disto vale: continua http://localhost:8000.
# No servidor, o Nginx recebe o HTTPS e repassa para o Django.
if not DEBUG:
    import os

    # O Nginx avisa "esta conexao veio por HTTPS" neste cabecalho.
    # Sem isto, o Django acharia que tudo e http e entraria em loop de redirecionamento.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # W008: quem chegar por http:// e mandado para https://.
    SECURE_SSL_REDIRECT = True

    # W012 e W016: cookies de login e de formulario so viajam criptografados.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # W004 (HSTS): o navegador passa a usar SEMPRE https neste dominio.
    # Comeca em 1 hora (3600). Depois de confirmar que o HTTPS esta estavel,
    # sobe para 1 ano (31536000) no .env do servidor: DJANGO_HSTS_SECONDS=31536000
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

    # Enderecos https de onde os formularios podem vir (ex.: https://app.dualflux.com.br).
    # Varios separados por virgula, no .env do servidor.
    CSRF_TRUSTED_ORIGINS = [
        origem.strip() for origem in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origem.strip()
    ]


# ----------------------------------------------------------------------
# BLOQUEIO DE TENTATIVAS DE SENHA (django-axes)
# ----------------------------------------------------------------------
# Depois de 5 senhas erradas para o mesmo e-mail, vindas do mesmo computador
# (IP), o acesso fica bloqueado por 30 minutos. Vale para o login do cliente
# e para a Administracao. Cada tentativa fica registrada (ver na Administracao).
#
# Por que "e-mail + IP" e nao so o e-mail? Se fosse so o e-mail, um invasor
# poderia bloquear o dono DE PROPOSITO, errando a senha dele 5 vezes.
INSTALLED_APPS = [*INSTALLED_APPS, "axes"]

# O AxesMiddleware deve ser o ULTIMO da lista.
MIDDLEWARE = [*MIDDLEWARE, "axes.middleware.AxesMiddleware"]

# O axes confere o bloqueio ANTES do Django conferir a senha.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5                              # tentativas erradas permitidas
AXES_COOLOFF_TIME = 0.5                             # horas de bloqueio (0.5 = 30 minutos)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True                        # acertou a senha: zera a contagem
AXES_LOCKOUT_TEMPLATE = "registration/bloqueado.html"

# No servidor, o Nginx fica na frente do Django: o IP verdadeiro de quem acessa
# vem no cabecalho X-Forwarded-For (1 proxy = o Nginx).
if not DEBUG:
    AXES_IPWARE_PROXY_COUNT = 1
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]


# ----------------------------------------------------------------------
# E-MAIL (codigos de acesso; depois, convites e alertas)
# ----------------------------------------------------------------------
# No notebook: o e-mail NAO sai de verdade, aparece no terminal
# (docker compose logs web). No servidor, o .env define o servico real:
#   DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#   DJANGO_EMAIL_HOST, DJANGO_EMAIL_PORT, DJANGO_EMAIL_USER, DJANGO_EMAIL_PASSWORD
import os  # noqa: E402

EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "DualFlux <naoresponda@dualflux.com.br>")
