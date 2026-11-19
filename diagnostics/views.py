"""
The workflow's pages, behind the admin's login and look.

    /                  find the charger, start a case (and the latest cases)
    /cases/<id>/       the next question, or the diagnosis once nothing is missing

The charger's state is read live on every page; the diagnosis is written into the case when the
last question is answered.
"""

from django.contrib import admin
from django.http import Http404
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from diagnostics.checks import run_checks
from diagnostics.checks import verdict
from diagnostics.forms import AnswerForm
from diagnostics.forms import StartForm
from diagnostics.models import Case
from diagnostics.snapshot import collect
from diagnostics.snapshot import find_chargers
from diagnostics.snapshot import ocpp_alias
from diagnostics.workflow import Situation
from diagnostics.workflow import asked
from diagnostics.workflow import diagnose
from diagnostics.workflow import lookback
from diagnostics.workflow import next_question
from diagnostics.workflow import without_last_answer
from services.ocpp.models import ChargePointV16

RECENT_CASES = 20


def start(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StartForm(request.POST)
        if form.is_valid():
            case = form.save(commit=False)
            case.created_by = request.user  # type: ignore[assignment]
            case.save()
            return redirect(case)
        # Only a tampered form gets here (both fields are hidden): start over.
        return redirect("start")

    query = request.GET.get("q", "").strip()
    context = admin.site.each_context(request) | {
        "title": "Charger diagnostics",
        "query": query,
        "matches": find_chargers(query) if query else [],
        "recent_cases": Case.objects.select_related("created_by")[:RECENT_CASES],
    }
    return TemplateResponse(request, "diagnostics/start.html", context)


def case_detail(request: HttpRequest, pk: int) -> HttpResponse:
    case = get_object_or_404(Case, pk=pk)
    charge_point = (
        ChargePointV16.objects.using(ocpp_alias(case.tenant))
        .filter(identity=case.identity)
        .first()
    )
    if charge_point is None:
        raise Http404("This charger no longer exists in api-ocpp.")

    now = timezone.now()
    snapshot = collect(case.tenant, charge_point, now, lookback(case.answers))
    situation = Situation(snapshot, run_checks(snapshot, now), case.answers, now)
    question = next_question(situation) if case.status == Case.Status.OPEN else None
    form = AnswerForm(question) if question else None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "answer" and question is not None:
            form = AnswerForm(question, request.POST)
            if form.is_valid():
                case.answers = case.answers | {question.key: form.cleaned_data["answer"]}
                case.save()
                return HttpResponseRedirect(request.path)
        else:
            return update(request, case, action)

    if question is None and case.status == Case.Status.OPEN:
        case.record(diagnose(situation), now)

    severity, overall = verdict(situation.findings)
    context = admin.site.each_context(request) | {
        "title": f"Case #{case.pk}: {case.identity}",
        "case": case,
        "snapshot": snapshot,
        "connector": situation.connector,
        "findings": situation.findings,
        "verdict": severity,
        "overall": overall,
        "asked": asked(situation),
        "question": question,
        "form": form,
        "checked_at": now,
    }
    return TemplateResponse(request, "diagnostics/case.html", context)


def update(request: HttpRequest, case: Case, action: str | None) -> HttpResponse:
    """The rep's other buttons. Each reopens the case, so the diagnosis is written again."""
    if action == "back":
        case.answers = without_last_answer(case.answers)
    elif action == "restart":
        case.answers = {}
    elif action == "close":
        case.status = Case.Status.CLOSED
        case.save()
        return HttpResponseRedirect(request.path)
    elif action != "rediagnose":
        return HttpResponseRedirect(request.path)
    case.status = Case.Status.OPEN
    case.save()
    return HttpResponseRedirect(request.path)
