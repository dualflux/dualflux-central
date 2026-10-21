"""
App "lojas": O QUE e monitorado.

- Regiao: agrupamento de lojas de uma empresa ("Zona Sul", "Interior"),
  usado nos comparativos entre blocos de lojas.
- Loja: a unidade fisica, ligada ao servidor local (hostname).
- Camera: cada camera da loja, com o MESMO codigo do loja.yaml ("cam1").
- HorarioFuncionamento: abre/fecha por dia da semana. E o denominador dos
  indicadores "por hora aberta", da analise das pontas do dia e do alerta
  de loja parada.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from contas.models import Empresa


def validar_fuso(valor):
    """Aceita so nomes de fuso validos, como 'America/Campo_Grande'."""
    try:
        ZoneInfo(valor)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(f'"{valor}" nao e um fuso horario valido. Ex.: America/Campo_Grande')


class Regiao(models.Model):
    """Agrupamento de lojas DENTRO de uma empresa (cadastro, nao texto livre)."""

    # CASCADE: se a empresa sumir, suas regioes somem junto (regiao nao tem dado proprio).
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="regioes")
    nome = models.CharField("nome", max_length=60)

    class Meta:
        verbose_name = "regiao"
        verbose_name_plural = "regioes"
        ordering = ["nome"]
        constraints = [
            # A mesma empresa nao pode ter duas regioes com o mesmo nome.
            models.UniqueConstraint(fields=["empresa", "nome"], name="regiao_nome_unico_por_empresa"),
        ]

    def __str__(self):
        return self.nome


# Enderecos que ficam logo depois do nome da empresa (ex.: /rede/relatorios/):
# uma loja com esse nome ficaria escondida atras da tela.
SLUGS_LOJA_RESERVADOS = {"relatorios", "equipe", "alertas", "configuracoes"}


def validar_slug_loja(valor):
    """Impede cadastrar loja com um endereco reservado do sistema."""
    from django.core.exceptions import ValidationError
    if valor in SLUGS_LOJA_RESERVADOS:
        raise ValidationError(f'"{valor}" e um endereco reservado do sistema. Escolha outro.')


class Loja(models.Model):
    """Unidade fisica do cliente. Cada loja tem UM servidor local."""

    # PROTECT: nao deixa apagar uma empresa que ainda tem lojas (protege o historico).
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="lojas")
    nome = models.CharField("nome", max_length=120)
    slug = models.SlugField(
        "endereco",
        max_length=60,
        help_text="Parte da URL: app.dualflux.com.br/<empresa>/<endereco>.",
        validators=[validar_slug_loja],
    )

    # Nome do servidor local (padrao cliente-cidade-NN). Liga o SaaS a maquina fisica.
    # null=True: varias lojas podem estar "sem servidor ainda" sem violar o unique.
    hostname = models.CharField(
        "servidor local",
        max_length=63,
        unique=True,
        null=True,
        blank=True,
        help_text="Nome da maquina na loja, no padrao cliente-cidade-NN.",
    )

    fuso_horario = models.CharField(
        "fuso horario", max_length=50, default="America/Campo_Grande", validators=[validar_fuso]
    )
    endereco = models.CharField("endereco completo", max_length=200, blank=True)
    cidade = models.CharField("cidade", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)

    # SET_NULL: apagar uma regiao nao apaga a loja; ela so fica "sem regiao".
    regiao = models.ForeignKey(
        Regiao,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lojas",
        verbose_name="regiao",
    )

    ativa = models.BooleanField(
        "ativa", default=True, help_text="Desmarque para loja fechada: some dos dashboards, o historico fica."
    )
    dados_validos_desde = models.DateTimeField(
        "dados validos desde",
        null=True,
        blank=True,
        help_text="Contagens anteriores a esta data/hora (testes da instalacao) ficam fora dos relatorios.",
    )

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "loja"
        verbose_name_plural = "lojas"
        ordering = ["empresa__nome", "nome"]
        constraints = [
            # O endereco da loja e unico DENTRO da empresa:
            # duas empresas podem ter, cada uma, sua loja "centro".
            models.UniqueConstraint(fields=["empresa", "slug"], name="loja_slug_unico_por_empresa"),
        ]

    def clean(self):
        super().clean()
        self.uf = self.uf.upper()
        # A regiao escolhida precisa ser da MESMA empresa da loja
        # (senao uma loja da empresa A apareceria num comparativo da empresa B).
        if self.regiao_id and self.empresa_id and self.regiao.empresa_id != self.empresa_id:
            raise ValidationError({"regiao": "Esta regiao pertence a outra empresa."})

    def __str__(self):
        return f"{self.empresa} - {self.nome}"


class Camera(models.Model):
    """Camera de uma loja. O codigo e o mesmo usado no loja.yaml do servidor local."""

    # PROTECT: os eventos de contagem vao apontar para a camera;
    # apagar a camera apagaria historico. Para desativar, use "ativa".
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="cameras")
    codigo = models.SlugField(
        "codigo", max_length=50, help_text='Mesmo codigo do loja.yaml, ex.: "cam1".'
    )
    nome = models.CharField("nome", max_length=80, blank=True, help_text='Ex.: "Porta principal".')
    ativa = models.BooleanField("ativa", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "camera"
        verbose_name_plural = "cameras"
        ordering = ["loja", "codigo"]
        constraints = [
            # "cam1" so pode existir uma vez em cada loja.
            models.UniqueConstraint(fields=["loja", "codigo"], name="camera_codigo_unico_por_loja"),
        ]

    def __str__(self):
        return f"{self.codigo} ({self.nome})" if self.nome else self.codigo


class HorarioFuncionamento(models.Model):
    """
    Horario de UM dia da semana de uma loja.

    Regras:
    - no maximo uma linha por dia;
    - dia sem linha = loja fechada naquele dia;
    - loja SEM NENHUMA linha = tratada como aberta 24 h (comportamento de hoje).
    Para loja que fecha a meia-noite, use 23:59.
    """

    # Segunda = 0 ... Domingo = 6: mesma numeracao do Python (datetime.weekday()),
    # o que simplifica os calculos do dashboard.
    class DiaSemana(models.IntegerChoices):
        SEGUNDA = 0, "Segunda"
        TERCA = 1, "Terca"
        QUARTA = 2, "Quarta"
        QUINTA = 3, "Quinta"
        SEXTA = 4, "Sexta"
        SABADO = 5, "Sabado"
        DOMINGO = 6, "Domingo"

    # CASCADE: horario nao tem sentido sem a loja.
    loja = models.ForeignKey(Loja, on_delete=models.CASCADE, related_name="horarios")
    dia_semana = models.PositiveSmallIntegerField("dia da semana", choices=DiaSemana.choices)
    abre = models.TimeField("abre")
    fecha = models.TimeField("fecha")

    class Meta:
        verbose_name = "horario de funcionamento"
        verbose_name_plural = "horarios de funcionamento"
        ordering = ["loja", "dia_semana"]
        constraints = [
            models.UniqueConstraint(fields=["loja", "dia_semana"], name="horario_um_por_dia"),
            # Garantido pelo banco: fechar sempre depois de abrir.
            models.CheckConstraint(name="horario_fecha_depois_de_abrir", condition=Q(fecha__gt=F("abre"))),
        ]

    def clean(self):
        super().clean()
        if self.abre and self.fecha and self.fecha <= self.abre:
            raise ValidationError({"fecha": "O horario de fechar deve ser depois do de abrir (use 23:59 para meia-noite)."})

    def __str__(self):
        return f"{self.get_dia_semana_display()}: {self.abre:%H:%M}-{self.fecha:%H:%M}"

# ======================================================================
# Token de API: a "chave" com que o servidor local da loja se identifica.
# (Os imports ficam aqui para manter todo o assunto "token" num bloco so.)
# ======================================================================
import hashlib
import hmac
import secrets

from django.utils import timezone


def _hash_token(token_texto):
    """SHA-256 do token. Rapido de proposito: o token e longo e aleatorio."""
    return hashlib.sha256(token_texto.encode()).hexdigest()


class TokenApi(models.Model):
    """
    Credencial de UMA loja para enviar dados ao central.

    - O token completo aparece UMA unica vez, na hora de gerar; depois so o hash fica guardado.
    - Uma loja pode ter mais de um token: permite trocar o token sem derrubar a loja
      (gera o novo, atualiza o .env da loja, revoga o antigo).
    """

    PREFIXO_FIXO = "dfx"  # identifica de cara que e um token DualFlux

    loja = models.ForeignKey(Loja, on_delete=models.CASCADE, related_name="tokens")
    prefixo = models.CharField("prefixo", max_length=8, unique=True, editable=False)
    hash = models.CharField("hash", max_length=64, editable=False)
    descricao = models.CharField("descricao", max_length=100, blank=True,
                                 help_text='Ex.: "Servidor da loja, instalado em 15/10".')
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    ultimo_uso_em = models.DateTimeField("ultimo uso", null=True, blank=True, editable=False)
    revogado_em = models.DateTimeField("revogado em", null=True, blank=True,
                                       help_text="Preenchido = token cancelado; a loja deixa de conseguir enviar.")

    class Meta:
        verbose_name = "token de API"
        verbose_name_plural = "tokens de API"
        ordering = ["-criado_em"]

    @property
    def ativo(self):
        return self.revogado_em is None

    @classmethod
    def gerar(cls, loja, descricao=""):
        """
        Cria um token novo para a loja.
        Devolve (registro, token_texto). O token_texto deve ser copiado AGORA:
        ele nao fica guardado em lugar nenhum.
        """
        prefixo = secrets.token_hex(4)    # 8 caracteres: a parte visivel
        segredo = secrets.token_hex(32)   # 64 caracteres: a parte secreta
        token_texto = f"{cls.PREFIXO_FIXO}_{prefixo}_{segredo}"
        registro = cls.objects.create(
            loja=loja, prefixo=prefixo, hash=_hash_token(token_texto), descricao=descricao
        )
        return registro, token_texto

    @classmethod
    def verificar(cls, token_texto):
        """
        Recebe o token enviado pela loja e devolve o registro, ou None se invalido.
        Usado pela API em TODA requisicao.
        """
        partes = (token_texto or "").split("_")
        if len(partes) != 3 or partes[0] != cls.PREFIXO_FIXO:
            return None
        registro = cls.objects.select_related("loja", "loja__empresa").filter(prefixo=partes[1]).first()
        if registro is None or not registro.ativo:
            return None
        # compare_digest compara em tempo constante: impede descobrir o hash
        # medindo quanto tempo a comparacao demora (ataque de temporizacao).
        if not hmac.compare_digest(registro.hash, _hash_token(token_texto)):
            return None
        return registro

    def marcar_uso(self):
        """Registra o ultimo uso (mostra no admin se a loja esta mandando dados)."""
        self.ultimo_uso_em = timezone.now()
        self.save(update_fields=["ultimo_uso_em"])

    def __str__(self):
        situacao = "ativo" if self.ativo else "revogado"
        return f"{self.PREFIXO_FIXO}_{self.prefixo}_... ({situacao})"
