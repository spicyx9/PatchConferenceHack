"""Conservative person deduplication.

Same person when one of these holds:
1. same source-declared LinkedIn or GitHub profile URL;
2. same folded name and same company id.
Same folded name with one side missing the company (or different companies) is reported
as `ambiguous` and never merged. All source rows are kept in `merged_from` and evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from conferge.people.models import PersonProfile
from conferge.people.taxonomy import fold

_FILLABLE = ("company_id", "role", "title", "public_profile_url", "linkedin_url",
             "github_url", "x_handle", "bio", "match_confidence", "identity_confidence")


@dataclass(frozen=True)
class Ambiguity:
    left_id: str
    right_id: str
    reason: str


def _url_key(url: object | None) -> str | None:
    if url is None:
        return None
    text = str(url).lower().split("?")[0].split("#")[0].rstrip("/")
    return text.replace("://linkedin.com", "://www.linkedin.com")


def _keys(profile: PersonProfile) -> list[str]:
    p = profile.person
    keys = []
    for prefix, url in (("li", p.linkedin_url), ("gh", p.github_url)):
        key = _url_key(url)
        if key:
            keys.append(f"{prefix}:{key}")
    if p.company_id:
        keys.append(f"nc:{fold(p.name)}|{p.company_id}")
    return keys


def _rank(profile: PersonProfile) -> tuple[int, int, str]:
    # Keep the id of the richest, most confirmed record as canonical.
    return (-len(profile.confirmed), -sum(1 for f in _FILLABLE
                                         if getattr(profile.person, f) is not None),
            profile.id)


def _merge(group: list[PersonProfile]) -> PersonProfile:
    group = sorted(group, key=_rank)
    base = group[0]
    person = base.person
    update: dict[str, object] = {}
    topics, roles, evidence = list(person.topics), list(person.roles), list(person.evidence)
    for other in group[1:]:
        op = other.person
        for name in _FILLABLE:
            if getattr(person, name) is None and update.get(name) is None:
                value = getattr(op, name)
                if value is not None:
                    update[name] = value
        topics += [t for t in op.topics if t not in topics]
        roles += [r for r in op.roles if r not in roles]
        evidence += [e for e in op.evidence if e not in evidence]
    update.update(topics=topics, roles=roles, evidence=evidence)
    presences, seen = [], set()
    talks: list[str] = []
    merged_from: list[str] = []
    company_name = base.company_name
    for profile in group:
        for presence in profile.presences:
            key = (presence.event_id, presence.kind)
            if key not in seen:
                seen.add(key)
                presences.append(presence)
        talks += [t for t in profile.talk_titles if t not in talks]
        merged_from += [m for m in profile.merged_from if m not in merged_from]
        company_name = company_name or profile.company_name
    return PersonProfile(person=person.model_copy(update=update), company_name=company_name,
                         presences=presences, talk_titles=talks, merged_from=merged_from)


def dedupe(profiles: list[PersonProfile]) -> tuple[list[PersonProfile], list[Ambiguity]]:
    parent = list(range(len(profiles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for index, profile in enumerate(profiles):
        for key in _keys(profile):
            if key in owner:
                parent[find(index)] = find(owner[key])
            else:
                owner[key] = index
    groups: dict[int, list[PersonProfile]] = {}
    for index, profile in enumerate(profiles):
        groups.setdefault(find(index), []).append(profile)
    merged = [_merge(g) if len(g) > 1 else g[0] for g in groups.values()]

    ambiguities: list[Ambiguity] = []
    by_name: dict[str, list[PersonProfile]] = {}
    for profile in merged:
        by_name.setdefault(fold(profile.person.name), []).append(profile)
    for same in by_name.values():
        for i, left in enumerate(same):
            for right in same[i + 1:]:
                lc, rc = left.person.company_id, right.person.company_id
                reason = ("same name, different companies" if lc and rc
                          else "same name, company unknown on one side")
                ambiguities.append(Ambiguity(left.id, right.id, reason))
    merged.sort(key=lambda p: p.id)
    return merged, ambiguities
