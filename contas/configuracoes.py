"""
CONFIGURACOES

- Minha conta (todos): corrigir nome e sobrenome. E-mail e o login: nao muda aqui.
- Horarios das lojas (so dono e admin): abre/fecha de cada dia da semana.

Regras dos horarios (as mesmas do banco):
- um horario por dia; fechar depois de abrir (meia-noite = 23:59);
- dia sem horario = loja fechada naquele dia;
- PELO MENOS UM dia aberto: loja sem nenhum horario seria tratada como 24 h.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from fluxo.rede import empresa_permitida, lojas_visiveis
from lojas.models import HorarioFuncionamento

from .models import Usuario

DIAS = HorarioFuncionamento.DiaSemana.choices  # [(0, "Segunda"), ...]
NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


class FormConta(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)


def pode_editar_horarios(usuario):
    return usuario.papel in (Usuario.Papel.DONO, Usuario.Papel.ADMIN)


def resumo_horarios(loja):
    """Texto curto: 'Seg a Sex 07:00-22:00 · Sáb 08:00-20:00 · Dom fechada'."""
    por_dia = {h.dia_semana: h for h in loja.horarios.all()}
    if not por_dia:
        return "Sem horário cadastrado (tratada como 24 h)"
    partes = []
    for dia, nome in enumerate(NOMES_DIAS):
        h = por_dia.get(dia)
        partes.append(f"{nome[:3]} {h.abre:%H:%M}–{h.fecha:%H:%M}" if h else f"{nome[:3]} fechada")
    return " · ".join(partes)


@login_required
def configuracoes(request, empresa_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    form = FormConta(request.POST or None, initial={"first_name": request.user.first_name, "last_name": request.user.last_name})
    salvo = False
    if request.method == "POST" and form.is_valid():
        request.user.first_name = form.cleaned_data["first_name"]
        request.user.last_name = form.cleaned_data["last_name"]
        request.user.save(update_fields=["first_name", "last_name"])
        salvo = True
    lojas = []
    if pode_editar_horarios(request.user):
        lojas = [{"loja": l, "resumo": resumo_horarios(l)}
                 for l in lojas_visiveis(request.user, empresa).prefetch_related("horarios").order_by("nome")]
    return render(request, "contas/configuracoes.html",
                  {"empresa": empresa, "form": form, "salvo": salvo, "lojas": lojas,
                   "edita_horarios": pode_editar_horarios(request.user)})


@login_required
def horarios_loja(request, empresa_slug, loja_slug):
    empresa = empresa_permitida(request.user, empresa_slug)
    if not pode_editar_horarios(request.user):
        raise Http404
    loja = get_object_or_404(empresa.lojas, slug=loja_slug, ativa=True)
    atuais = {h.dia_semana: h for h in loja.horarios.all()}

    erros, linhas = [], []
    for dia, _ in DIAS:
        h = atuais.get(dia)
        if request.method == "POST":
            aberta = request.POST.get(f"aberta_{dia}") == "1"
            abre = request.POST.get(f"abre_{dia}", "")
            fecha = request.POST.get(f"fecha_{dia}", "")
        else:
            aberta = h is not None
            abre = f"{h.abre:%H:%M}" if h else "08:00"
            fecha = f"{h.fecha:%H:%M}" if h else "18:00"
        linhas.append({"dia": dia, "nome": NOMES_DIAS[dia], "aberta": aberta, "abre": abre, "fecha": fecha, "erro": ""})

    if request.method == "POST":
        abertos = []
        for linha in linhas:
            if not linha["aberta"]:
                continue
            campo = forms.TimeField()
            try:
                abre, fecha = campo.clean(linha["abre"]), campo.clean(linha["fecha"])
            except forms.ValidationError:
                linha["erro"] = "Horário inválido."
                continue
            if fecha <= abre:
                linha["erro"] = "Fechar deve ser depois de abrir (meia-noite = 23:59)."
                continue
            abertos.append((linha["dia"], abre, fecha))
        if not any(l["aberta"] for l in linhas):
            erros.append("Deixe pelo menos um dia aberto. (Loja sem nenhum horário seria tratada como aberta 24 horas.)")
        if not erros and not any(l["erro"] for l in linhas):
            # Tudo ou nada: apaga os horarios antigos e grava os novos na mesma operacao.
            with transaction.atomic():
                loja.horarios.all().delete()
                HorarioFuncionamento.objects.bulk_create(
                    [HorarioFuncionamento(loja=loja, dia_semana=d, abre=a, fecha=f) for d, a, f in abertos])
            cache.clear()  # os alertas de "ontem" levam o horario em conta: recalcula
            return redirect("configuracoes", empresa_slug=empresa.slug)

    return render(request, "contas/horarios_loja.html", {"empresa": empresa, "loja": loja, "linhas": linhas, "erros": erros})
