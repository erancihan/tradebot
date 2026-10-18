"""Settings builders: turn the configured names into live components.

Split from ``config.py`` so the dataclass reads as the list of knobs and the
safety gate. Each builder imports its package lazily, so merely loading
config never pulls in pandas.
"""

from __future__ import annotations


class SettingsBuilders:
    """Mixed into ``Settings``; reads its allocation, selector, universe,
    notify and overlay fields."""

    def build_allocator(self):
        """Instantiate the configured allocator, or None for legacy sizing.

        Imported lazily so merely loading config never pulls in pandas.
        """
        if self.allocation_name is None:
            return None
        from .allocation import build_allocator

        return build_allocator(self.allocation_name, self.allocation_params)

    def build_selector(self):
        """Instantiate the configured selector, or None for no membership gate."""
        if self.selector_name is None:
            return None
        from .selection import build_selector

        return build_selector(self.selector_name, self.selector_params)

    def build_universe(self):
        """Instantiate the configured universe source, or None for the static list."""
        if self.universe_name is None:
            return None
        from .universe import build_universe

        return build_universe(self.universe_name, self.universe_params)

    def build_notifier(self, link_signer=None):
        """Instantiate the configured notifier (log-only unless a channel is set).
        ``link_signer`` (``tradebot.autopilot.links``) arms the push's buttons."""
        from .notify import build_notifier

        return build_notifier(self.notify_webhook_url, self.notify_ntfy_topic,
                              self.notify_ntfy_server, public_url=self.notify_public_url,
                              link_signer=link_signer)

    def build_overlays(self) -> list:
        """Instantiate the configured overlay chain (empty list when unset)."""
        if not self.overlays:
            return []
        if self.allocation_name is None:
            raise ValueError(
                "portfolio.overlays requires an allocation scheme "
                "(set portfolio.allocation, e.g. `equal`)"
            )
        from .overlays import build_overlay

        return [build_overlay(o.get("name"), o.get("params")) for o in self.overlays]
