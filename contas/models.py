"""
App "contas": QUEM usa o DualFlux Central.

- Empresa: o cliente (ex.: a rede de farmacias). Cada empresa tem um
  endereco proprio no site: app.dualflux.com.br/<slug>.
- Usuario: a pessoa que faz login. Entra com E-MAIL (nao com "username").

Regra de seguranca central (multi-tenant): todo usuario, exceto o
administrador DualFlux, pertence a UMA empresa e so pode ver dados dela.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

# Enderecos que o proprio sistema usa. Se uma empresa tivesse o slug "admin",
# a URL app.dualflux.com.br/admin ficaria ambigua (painel ou empresa?).
SLUGS_RESERVADOS = {"admin", "api", "login", "logout", "static", "media", "conta", "contas"}


def validar_slug_livre(valor):
    """Impede cadastrar empresa com um endereco reservado do sistema."""
    if valor in SLUGS_RESERVADOS:
        raise ValidationError(f'"{valor}" e um endereco reservado do sistema. Escolha outro.')


class Empresa(models.Model):
    """O cliente do SaaS. Lojas e usuarios pendem desta tabela."""

    # TextChoices: lista fechada de opcoes. No banco grava o valor curto
    # ("ativa"); na tela aparece o rotulo ("Ativa").
    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        SUSPENSA = "suspensa", "Suspensa"

    # Por enquanto so existe o plano do piloto. Planos pagos entram depois:
    # acrescentar uma opcao aqui e so uma migracao pequena.
    class Plano(models.TextChoices):
        PILOTO = "piloto", "Piloto"

    nome = models.CharField("nome", max_length=120)
    slug = models.SlugField(
        "endereco",
        max_length=60,
        unique=True,  # duas empresas nunca podem ter o mesmo endereco
        validators=[validar_slug_livre],
        help_text="Parte da URL: app.dualflux.com.br/<endereco>. So letras minusculas, numeros e hifen.",
    )
    status = models.CharField("situacao", max_length=10, choices=Status.choices, default=Status.ATIVA)
    plano = models.CharField("plano", max_length=20, choices=Plano.choices, default=Plano.PILOTO)

    # auto_now_add: preenchido uma vez, na criacao. auto_now: atualizado a cada salvamento.
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["nome"]

    def __str__(self):
        # E assim que a empresa aparece em listas e no admin.
        return self.nome


class UsuarioManager(BaseUserManager):
    """
    O "Manager" e quem cria usuarios (inclusive pelo comando createsuperuser).
    O padrao do Django exige "username"; como entramos por e-mail,
    precisamos de um Manager proprio.
    """

    use_in_migrations = True

    def _criar(self, email, password, **campos):
        if not email:
            raise ValueError("O e-mail e obrigatorio.")
        # E-mail sempre em minusculas: "Ana@Farmacia.com" e "ana@farmacia.com"
        # sao a mesma pessoa e nao podem virar dois cadastros.
        email = self.normalize_email(email).lower()
        usuario = self.model(email=email, **campos)
        usuario.set_password(password)  # grava so o HASH da senha, nunca a senha
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **campos):
        campos.setdefault("is_staff", False)
        campos.setdefault("is_superuser", False)
        return self._criar(email, password, **campos)

    def create_superuser(self, email, password=None, **campos):
        # Superusuario = administrador DualFlux: acessa o painel e nao tem empresa.
        campos.setdefault("is_staff", True)
        campos.setdefault("is_superuser", True)
        campos.setdefault("papel", Usuario.Papel.ADMIN)
        if campos["is_staff"] is not True or campos["is_superuser"] is not True:
            raise ValueError("Superusuario precisa de is_staff=True e is_superuser=True.")
        return self._criar(email, password, **campos)

    def get_by_natural_key(self, email):
        # Usado no login: aceita o e-mail digitado com maiusculas ou minusculas.
        return self.get(email__iexact=email)


class Usuario(AbstractUser):
    """
    Pessoa que acessa o sistema. Herdamos de AbstractUser para aproveitar
    tudo o que o Django ja faz (senha com hash, permissoes, sessao) e so
    trocamos o necessario: login por e-mail, empresa e papel.
    """

    class Papel(models.TextChoices):
        ADMIN = "admin", "Administrador DualFlux"
        DONO = "dono", "Dono da rede"
        GERENTE = "gerente", "Gerente de loja"

    # Remove o campo "username" herdado: o login e pelo e-mail.
    username = None
    email = models.EmailField("e-mail", unique=True)

    # PROTECT: o banco recusa apagar uma empresa que ainda tem usuarios.
    # Evita apagar, por engano, o acesso de toda uma rede de lojas.
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
        verbose_name="empresa",
        help_text="Vazio somente para administradores DualFlux.",
    )
    papel = models.CharField("papel", max_length=10, choices=Papel.choices, default=Papel.GERENTE)

    # O vinculo do gerente com as lojas dele entra quando criarmos o app "lojas".

    USERNAME_FIELD = "email"  # campo usado para entrar no sistema
    REQUIRED_FIELDS = []      # o createsuperuser pede so e-mail e senha

    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            # Regra garantida PELO BANCO, nao so pelas telas:
            # administrador DualFlux NAO tem empresa; dono e gerente TEM empresa.
            # Mesmo um erro de programacao nao consegue gravar um gerente "sem empresa"
            # (que poderia acabar enxergando dados de todos).
            models.CheckConstraint(
                name="usuario_papel_e_empresa_coerentes",
                condition=(
                    Q(papel="admin", empresa__isnull=True)
                    | (~Q(papel="admin") & Q(empresa__isnull=False))
                ),
            ),
        ]

    def clean(self):
        # Mesma regra da constraint, mas com mensagem amigavel na tela do admin
        # (a constraint do banco e a ultima barreira; esta e a primeira).
        super().clean()
        if self.papel == self.Papel.ADMIN and self.empresa_id:
            raise ValidationError({"empresa": "Administrador DualFlux nao pertence a nenhuma empresa."})
        if self.papel != self.Papel.ADMIN and not self.empresa_id:
            raise ValidationError({"empresa": "Dono e gerente precisam pertencer a uma empresa."})

    def save(self, *args, **kwargs):
        # Garante o e-mail em minusculas mesmo quando gravado pelo admin.
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email