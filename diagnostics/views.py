"""
The workflow's pages, behind the admin's login and look.

    /                  find the charger, start a case (and the latest cases)
    /cases/<id>/       the next question, or the diagnosis once nothing is missing

The charger's state is read live on every page; the diagnosis is written into the case when the
last question is answered. Once diagnosed, the rep can ask Claude for an assessment of the whole
case, and escalate it to the tech team as a Jira issue.
"""

import logging

import anthropic
import httpx
from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from config.roles import DATA
from config.roles import SUPPORT
from config.roles import has_role
from config.roles import role_required
from diagnostics import assistant
from diagnostics import jira
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

log = logging.getLogger(__name__)

RECENT_CASES = 20


def start(request: HttpRequest) -> HttpResponse:
    # The site's home page: people who only query the data land on the admin's tables.
    if not has_role(request.user, SUPPORT):
        if has_role(request.user, DATA):
            return redirect("admin:index")
        raise PermissionDenied("Needs the support or the data role.")
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


@role_required(SUPPORT)
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
        elif action == "assess" and question is None:
            return ask_claude(request, case, situation)
        elif action == "escalate":
            return escalate(request, case)
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
        "can_assess": assistant.enabled(),
        "can_escalate": jira.enabled(),
    }
    return TemplateResponse(request, "diagnostics/case.html", context)


def update(request: HttpRequest, case: Case, action: str | None) -> HttpResponse:
    """The rep's other buttons. Each reopens the case, so the diagnosis is written again."""
    if action == "back":
        case.answers = without_last_answer(case.answers)
        # Claude assessed the old answers.
        case.assessment = {}
    elif action == "restart":
        case.answers = {}
        case.assessment = {}
    elif action == "close":
        case.status = Case.Status.CLOSED
        case.save()
        return HttpResponseRedirect(request.path)
    elif action != "rediagnose":
        return HttpResponseRedirect(request.path)
    case.status = Case.Status.OPEN
    case.save()
    return HttpResponseRedirect(request.path)


def ask_claude(request: HttpRequest, case: Case, situation: Situation) -> HttpResponse:
    if not assistant.enabled():
        return HttpResponseRedirect(request.path)
    try:
        assessment = assistant.assess(situation)
    except anthropic.APIError:
        # Claude being down or busy is no reason for an error page: the rest of the case works.
        log.exception("Claude's assessment of case %s failed", case.pk)
        messages.error(request, "Claude couldn't assess the case right now. Try again later.")
        return HttpResponseRedirect(request.path)
    case.record_assessment(assessment, settings.ANTHROPIC_MODEL, situation.now)
    return HttpResponseRedirect(request.path)


def escalate(request: HttpRequest, case: Case) -> HttpResponse:
    """A Jira issue from Claude's ticket draft, once per case."""
    if not jira.enabled() or not case.assessment or case.jira_issue:
        return HttpResponseRedirect(request.path)
    description = "\n".join(
        [
            case.assessment["ticket_description"],
            "",
            f"Case: {request.build_absolute_uri(case.get_absolute_url())}",
            f"Support ticket: {case.ticket or 'none'}",
            f"Escalated by {request.user} from the support diagnostics, with an assessment by"
            f" {case.assessment_model}.",
            "",
            "What the diagnostics saw:",
            case.summary,
        ]
    )
    try:
        issue = jira.JiraClient().create_issue(case.assessment["ticket_title"], description)
    except httpx.HTTPError:
        log.exception("Creating the Jira issue for case %s failed", case.pk)
        messages.error(request, "Jira refused the ticket. Try again, or create it by hand.")
        return HttpResponseRedirect(request.path)
    case.record_escalation(issue)
    messages.success(request, f"Created {issue.key}.")
    return HttpResponseRedirect(request.path)
