"""The component registries rendered as form specs (Run, What-if, Settings)."""

from __future__ import annotations


def param_specs(cls) -> list[dict]:
    """A constructor's simple keyword params as ``{name, type, default}``.

    Only int/float/bool/str defaults become form fields: anything richer (a
    meta strategy's roster, a derived ``None``) keeps its default and stays a
    config-file affair. ``bool`` is checked before ``int`` because it *is* an
    ``int`` in Python and would otherwise render as a number box.
    """
    import inspect

    params: list[dict] = []
    for pname, p in inspect.signature(cls.__init__).parameters.items():
        if pname == "self" or p.default is inspect.Parameter.empty:
            continue
        if isinstance(p.default, bool):
            kind = "bool"
        elif isinstance(p.default, int):
            kind = "int"
        elif isinstance(p.default, float):
            kind = "float"
        elif isinstance(p.default, str):
            kind = "str"
        else:
            continue
        params.append({"name": pname, "type": kind, "default": p.default})
    return params


def strategy_catalog() -> list[dict]:
    """The strategy registry as form specs: name + simple constructor params."""
    from ....strategies import STRATEGIES

    return [{"name": name, "params": param_specs(STRATEGIES[name])}
            for name in sorted(STRATEGIES)]


def stack_catalog() -> dict[str, list[str]]:
    """Allocators and selectors a form can pick by name alone.

    ``explicit`` is left out: it needs a weight per symbol, which is a
    config-file affair, like a meta strategy's roster.
    """
    from ....allocation import ALLOCATORS
    from ....selection import SELECTORS

    return {"allocators": [n for n in ALLOCATORS if n != "explicit"],
            "selectors": sorted(SELECTORS)}


def stack_specs() -> dict[str, list[dict]]:
    """``stack_catalog`` with each component's form params, for the Settings page."""
    from ....allocation import ALLOCATORS
    from ....selection import SELECTORS

    names = stack_catalog()
    return {"allocators": [{"name": n, "params": param_specs(ALLOCATORS[n])}
                           for n in names["allocators"]],
            "selectors": [{"name": n, "params": param_specs(SELECTORS[n])}
                          for n in names["selectors"]]}
