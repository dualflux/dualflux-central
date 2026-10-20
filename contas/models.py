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

    # Lojas que o GERENTE pode ver. O dono ve todas as lojas da empresa,
    # entao para ele este campo fica vazio.
    # "lojas.Loja" vai entre aspas (texto) de proposito: o app lojas ja importa
    # o contas (Loja aponta para Empresa); se o contas importasse o lojas,
    # um ficaria esperando o outro carregar (importacao circular, aquele erro de hoje).
    lojas = models.ManyToManyField(
        "lojas.Loja",
        blank=True,
        related_name="gerentes",
        verbose_name="lojas",
        help_text="So para gerente: as lojas que ele pode ver.",
    )

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

# ----------------------------------------------------------------------
# CODIGO DE ACESSO (6 digitos): "esqueci minha senha" e convite de gerente
# ----------------------------------------------------------------------
import secrets  # noqa: E402  (gerador de numeros proprio para seguranca)
from datetime import timedelta  # noqa: E402

from django.utils import timezone  # noqa: E402
from django.utils.crypto import constant_time_compare, salted_hmac  # noqa: E402


class CodigoAcesso(models.Model):
    """
    Codigo de 6 digitos enviado por e-mail para a pessoa criar uma senha nova.

    Seguranca:
    - o codigo NUNCA e gravado: so o "hash" dele (como as senhas);
    - vale por pouco tempo (15 min para recuperar senha, 3 dias para convite);
    - no maximo 5 tentativas erradas; depois disso o codigo e anulado;
    - e de uso unico: depois de criada a senha, nao vale mais.
    """

    class Finalidade(models.TextChoices):
        RECUPERAR = "recuperar", "Recuperar senha"
        CONVITE = "convite", "Convite (primeiro acesso)"

    MAX_TENTATIVAS = 5
    VALIDADE = {Finalidade.RECUPERAR: timedelta(minutes=15), Finalidade.CONVITE: timedelta(days=3)}

    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name="codigos_acesso")
    finalidade = models.CharField(max_length=10, choices=Finalidade.choices)
    codigo_hash = models.CharField(max_length=64)
    criado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()
    tentativas = models.PositiveSmallIntegerField(default=0)
    usado_em = models.DateTimeField(null=True, blank=True, help_text="Usado ou anulado: nao vale mais.")

    class Meta:
        verbose_name = "codigo de acesso"
        verbose_name_plural = "codigos de acesso"
        indexes = [models.Index(fields=["usuario", "criado_em"])]

    @staticmethod
    def _hash(usuario_id, codigo):
        # HMAC com a SECRET_KEY: sem a chave do servidor, o hash nao revela o codigo.
        return salted_hmac("dualflux.codigo-acesso", f"{usuario_id}:{codigo}").hexdigest()

    @classmethod
    def gerar(cls, usuario, finalidade):
        """Cria um codigo novo (anulando os anteriores) e devolve (registro, codigo_em_texto)."""
        agora = timezone.now()
        cls.objects.filter(usuario=usuario, usado_em__isnull=True).update(usado_em=agora)
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        registro = cls.objects.create(
            usuario=usuario, finalidade=finalidade,
            codigo_hash=cls._hash(usuario.pk, codigo),
            expira_em=agora + cls.VALIDADE[finalidade],
        )
        return registro, codigo

    @property
    def valido(self):
        return self.usado_em is None and self.tentativas < self.MAX_TENTATIVAS and timezone.now() < self.expira_em

    def conferir(self, codigo):
        """True se o codigo bate. Cada erro conta uma tentativa."""
        if not self.valido:
            return False
        if constant_time_compare(self.codigo_hash, self._hash(self.usuario_id, codigo.strip())):
            return True
        self.tentativas += 1
        self.save(update_fields=["tentativas"])
        return False

    def __str__(self):
        return f"{self.usuario} - {self.get_finalidade_display()} - {self.criado_em:%d/%m %H:%M}"


# ----------------------------------------------------------------------
# Enderecos reservados acrescentados com as telas novas.
# validar_slug_livre le SLUGS_RESERVADOS na hora de validar, entao basta
# completar a lista aqui (o que ja existia continua valendo).
# ----------------------------------------------------------------------
SLUGS_RESERVADOS_SISTEMA = {
    "admin", "api", "login", "logout", "static", "media",
    "clientes", "acesso", "conta",
}
SLUGS_RESERVADOS = frozenset(SLUGS_RESERVADOS) | SLUGS_RESERVADOS_SISTEMA
