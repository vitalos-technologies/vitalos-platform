"""Per-admin Relay alert preferences: the My notifications grid, sound and browser notifications."""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import record

from . import selectors
from .models import (
    DIGEST,
    EMAIL,
    HANDOFF_REQUESTED,
    IN_APP,
    NO_ANSWER,
    REMINDER,
    VISITOR_REPLIED,
    RelayPreference,
)


@dataclass(frozen=True)
class GridRow:
    key: str
    label: str
    in_app: bool  # default
    email: bool  # default
    in_app_available: bool = True


GRID = (
    GridRow(HANDOFF_REQUESTED, "A visitor asks for a person", True, True),
    GridRow(VISITOR_REPLIED, "Visitor replies in my conversation", True, True),
    GridRow(REMINDER, "No one has joined after {minutes} minutes", True, True),
    GridRow(NO_ANSWER, "Relay could not answer (no handoff)", True, False),
    GridRow(DIGEST, "Daily digest", False, True, in_app_available=False),
)
GRID_KEYS = tuple(row.key for row in GRID)


def defaults() -> dict[str, dict[str, bool]]:
    return {row.key: {IN_APP: row.in_app, EMAIL: row.email} for row in GRID}


def _merge(stored: dict | None) -> dict[str, dict[str, bool]]:
    prefs = defaults()
    for row in GRID:
        value = (stored or {}).get(row.key)
        if isinstance(value, dict):
            for channel in (IN_APP, EMAIL):
                if isinstance(value.get(channel), bool):
                    prefs[row.key][channel] = value[channel]
        if not row.in_app_available:
            prefs[row.key][IN_APP] = False
    return prefs


@dataclass
class Preferences:
    grid: dict[str, dict[str, bool]]
    sound: bool = False
    browser: bool = False

    def wants(self, kind: str, channel: str) -> bool:
        """Types outside the grid (token cap, FAQ attention) are always on for the people who get them."""
        if kind not in self.grid:
            return True
        return self.grid[kind][channel]


def get(user) -> Preferences:
    pref = RelayPreference.objects.filter(user=user).first()
    if pref is None:
        return Preferences(defaults())
    return Preferences(_merge(pref.prefs), sound=pref.sound, browser=pref.browser)


def for_users(users) -> dict[int, Preferences]:
    """Preferences for many users in one query."""
    stored = {pref.user_id: pref for pref in RelayPreference.objects.filter(user__in=users)}
    result = {}
    for user in users:
        pref = stored.get(user.pk)
        result[user.pk] = (
            Preferences(_merge(pref.prefs), sound=pref.sound, browser=pref.browser)
            if pref
            else Preferences(defaults())
        )
    return result


@transaction.atomic
def save(user, grid: dict, *, sound: bool, browser: bool, request=None) -> Preferences:
    if not selectors.can_access(user):
        raise PermissionDenied
    merged = _merge(grid)
    RelayPreference.objects.update_or_create(
        user=user, defaults={"prefs": merged, "sound": bool(sound), "browser": bool(browser)}
    )
    record(
        "relay.preferences_changed",
        request=request,
        actor=user,
        entity=user,
        summary="Changed site assistant notification preferences",
        preferences=merged,
        sound=bool(sound),
        browser=bool(browser),
    )
    return Preferences(merged, sound=bool(sound), browser=bool(browser))
