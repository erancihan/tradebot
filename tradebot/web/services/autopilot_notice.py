"""What an approval tells its approver: the page's notice and a link's reply.

An ``ApprovalResult`` says why each line was not submitted; this module puts
it in words. The page is behind the access gate, so its notice names the
symbols and the broker's error. A link's holder may be anyone who read the
ntfy topic, so its reply gives counts only; the page has the detail.
"""

from __future__ import annotations

CLOSED = ("The market is closed, so nothing was submitted: the waiting trades "
          "expired, and the first pass after the open lists new ones.")
RESIZED = "re-sized since this push; open the newest push"


def approval_notice(result, asked: int) -> str | None:
    """The page's notice for an approval, or None when all of it went through."""
    if result.closed:
        return CLOSED
    parts: list[str] = []
    if result.held:
        parts.append(f"{len(result.held)} re-sized since the page showed them "
                     f"({', '.join(result.held)}): check the new sizes and approve again.")
    if result.moved:
        parts.append(f"The position in {', '.join(result.moved)} changed since the pass, "
                     "so that trade expired unsent.")
    if result.failed:
        parts.append("Order failed: " + "; ".join(f"{s} ({e})" for s, e in result.failed)
                     + ". It is still waiting; approve again to retry.")
    rest = asked - result.submitted - len(result.held) - len(result.moved) - len(result.failed)
    if result.stale:
        parts.append(f"{asked} of {asked} trades were not submitted: they had expired "
                     "(older than one poll).")
    elif rest > 0:
        parts.append(f"{rest} of {asked} trades were not submitted: they had expired "
                     "or were no longer pending.")
    return " ".join(parts) or None


def link_reply(batch_id: int, verb: str, result) -> dict:
    """A link's JSON: the count, plus why lines were left alone when any were."""
    if verb != "approve":
        return {"batch_id": batch_id, "rejected": result.rejected}
    body: dict = {"batch_id": batch_id, "approved": result.submitted}
    if result.closed:
        body["message"] = "market closed: nothing submitted"
    if result.held:
        body["held"] = len(result.held)
        body["message"] = f"{len(result.held)} {RESIZED}"
    if result.moved:
        body["expired"] = len(result.moved)
    return body


def link_failure(result) -> str:
    """A 502's detail when the broker refused lines that are still pending."""
    return (f"{len(result.failed)} order(s) failed and are still waiting; "
            "see the Autopilot page")
