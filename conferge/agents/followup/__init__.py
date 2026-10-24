"""Window 16: follow-up drafts after a MET memory, proposed for validation, never sent."""

from conferge.agents.followup.agent import FollowUpAgent, best_goal, drafts_for_context, run
from conferge.agents.followup.draft import (
    FOLLOW_UP_DELAY_DAYS,
    FollowUpDraft,
    NextAction,
    draft_followup,
)

__all__ = [
    "FOLLOW_UP_DELAY_DAYS",
    "FollowUpAgent",
    "FollowUpDraft",
    "NextAction",
    "best_goal",
    "draft_followup",
    "drafts_for_context",
    "run",
]
