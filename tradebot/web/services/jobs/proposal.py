"""Refresh job for the Today page: compute a proposal and store it."""

from __future__ import annotations


def _run_proposal(params: dict) -> tuple[dict, None, dict]:
    """Build the inputs, ask the advisor, write the proposal. Orders nothing.

    The strategy stack comes from the server's settings, the same objects the
    engine would build, so a suggestion matches what a paper pass would do.
    """
    from ....advisor import propose
    from ....risk import RiskManager
    from ....storage import Storage
    from ....strategies import build_strategy
    from .. import advisor_service

    settings = params["settings"]
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    selector, allocator = settings.build_selector(), settings.build_allocator()
    overlays = settings.build_overlays()
    lookback = advisor_service.lookback_bars([strategy, selector, allocator, *overlays])
    inputs = advisor_service.build_inputs(
        settings, trading_db=params["trading_db"], cache_dir=params["cache_dir"],
        lookback=lookback,
    )
    proposal = propose(
        symbols=list(settings.symbols), strategy=strategy,
        risk=RiskManager(settings.risk), selector=selector, allocator=allocator,
        overlays=overlays, **inputs,
    )
    with Storage(params["trading_db"]) as store:
        batch_id = store.record_proposal(proposal, settings.mode)
    trades = sum(1 for line in proposal.lines if line.order_qty)
    return ({"proposal_id": batch_id, "lines": len(proposal.lines), "trades": trades},
            None, proposal.provenance)
