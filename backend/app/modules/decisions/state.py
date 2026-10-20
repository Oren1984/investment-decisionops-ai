"""Decision lifecycle (PROJECT_PLAN §15.2). Every transition goes through `transition()`."""

from app.core.errors import Conflict

STAGES = ["draft", "scoped", "researching", "analyzing", "scenarios", "quality_review", "ready_for_decision",
          "decided", "execution_linked", "under_review", "closed"]
TERMINAL = {"closed", "cancelled"}

ALLOWED: dict[str, set[str]] = {
    "draft": {"scoped", "cancelled"},
    "scoped": {"researching", "cancelled", "blocked"},
    "researching": {"analyzing", "blocked", "cancelled"},
    "analyzing": {"scenarios", "blocked", "cancelled"},
    "scenarios": {"quality_review", "blocked", "cancelled"},
    "quality_review": {"researching", "ready_for_decision", "blocked", "cancelled"},
    "blocked": {"scoped", "cancelled"},
    "ready_for_decision": {"decided", "scoped"},
    "decided": {"decided", "execution_linked", "under_review"},
    "execution_linked": {"under_review", "execution_linked"},
    "under_review": {"closed"},
    "closed": set(),
    "cancelled": {"scoped"},
}

LABELS = {
    "draft": "Draft", "scoped": "Scoped", "researching": "Researching", "analyzing": "Analyzing",
    "scenarios": "Scenarios", "quality_review": "Quality review", "blocked": "Blocked",
    "ready_for_decision": "Ready for decision", "decided": "Decided", "execution_linked": "Execution linked",
    "under_review": "Under review", "closed": "Closed", "cancelled": "Cancelled",
}

NEXT_ACTION = {
    "draft": "Start a research run",
    "scoped": "Research run starting",
    "researching": "Research in progress",
    "analyzing": "Portfolio and market analysis in progress",
    "scenarios": "Scenario analysis in progress",
    "quality_review": "Critic and quality review in progress",
    "blocked": "Supply the missing input, then restart the run",
    "ready_for_decision": "Review the evidence package and record your decision",
    "decided": "Create an order ticket (optional) or start the post-decision review",
    "execution_linked": "Follow the linked orders, then review the decision",
    "under_review": "Grade process and outcome separately, then capture lessons",
    "closed": "Done",
    "cancelled": "Restart the run if you still need it",
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED.get(current, set())


def transition(decision, target: str) -> None:
    if not can_transition(decision.status, target):
        raise Conflict("invalid_transition",
                       f"A decision in '{LABELS.get(decision.status, decision.status)}' cannot move to "
                       f"'{LABELS.get(target, target)}'.")
    decision.status = target
