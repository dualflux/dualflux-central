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


class Loja(models.Model):
    """Unidade fisica do cliente. Cada loja tem UM servidor local."""

    # PROTECT: nao deixa apagar uma empresa que ainda tem lojas (protege o historico).
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="lojas")
    nome = models.CharField("nome", max_length=120)
    slug = models.SlugField(
        "endereco",
        max_length=60,
        help_text="Parte da URL: app.dualflux.com.br/<empresa>/<endereco>.",
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