"""Print the scripted offline demo, step by step: ``uv run python -m conferge.demo``."""

from __future__ import annotations

from conferge.demo.engine import replay
from conferge.demo.seed import build_world


def render(result: dict) -> str:
    world = build_world()
    titles = {e.id: e.title for e in world.events}
    names = {p.id: p.name for p in world.people}
    out = ["[FIXTURE] Conferge offline demo: every record below is synthetic or simulated.", ""]
    d = result["discovery"]
    out.append(f"1. Discovery ({d['source_mode']}): {d['events']} events, {d['people']} people, "
               f"{d['lodging']} stays, {d['flights']} flights")
    out.append("2. Goals: " + ", ".join(f"{g['id']}={g['priority']}" for g in result["goals"]))
    out.append("3. Top people (fictional personas):")
    for p in result["top_people"]:
        path = " -> ".join(f"{n['kind']}:{n['id']}" for n in p["path"])
        out.append(f"   {p['score']:>5}  {names[p['id']]:<20} {p['presence']:<9} {path}")
    out.append("4. Plan:")
    for e in result["plan"]["events"]:
        out.append(f"   {e['start_at']}  {e['title']} (value {e['value']})")
    for c in result["plan"]["clashes"]:
        out.append(f"   Anti-FOMO: {c['explanation']} Distance {c['distance_km']} km.")
    t = result["travel"]
    out.append(f"5. Travel ({t['label']}): flight {t['flight_id']} [{t['flight_price_status']}], "
               f"stay {t['lodging_id']} [{t['lodging_price_status']}], "
               f"total {t['simulated_total_usd']} / {t['budget_usd']} USD")
    out.append(f"   {t['proactive_suggestion']}")
    diff = result["diff"]
    out.append(f"6. Change: {result['change']['event_id']} -> {result['change']['type']}")
    out.append("   removed: " + ", ".join(titles[i] for i in diff["removed"]))
    out.append("   added:   " + ", ".join(titles[i] for i in diff["added"]))
    out.append("   top people after: " + ", ".join(names[i] for i in result["top_people_after"]))
    return "\n".join(out)


if __name__ == "__main__":
    print(render(replay()))
