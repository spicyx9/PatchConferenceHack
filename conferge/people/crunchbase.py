"""Crunchbase company funding (Bright Data SERP lookup + Crunchbase companies dataset).

Pattern: Bright Data open-enrich ``tools/crunchbase-tool.ts`` (Google SERP restricted to
``site:crunchbase.com/organization`` to find the organization URL, then the Crunchbase
dataset collects it) with the trigger + poll loop of ``conferge/people/linkedin.py``.

- ``find_crunchbase_url``: one SERP query through the SERP zone with ``brd_json=1``; a URL
  is returned only for one clear candidate, never built from a company name.
- ``fetch_company``: ``POST /datasets/v3/trigger`` (at most 10 URLs) then
  ``/progress`` + ``/snapshot`` polling; rows are returned as Bright Data sent them.
- ``normalize``: funding fields read from several candidate keys; a missing or non-USD
  value stays None, nothing is invented.

Dataset field names (UNVERIFIED against a live snapshot; no Crunchbase sample is in this
repo, docs/knowledge/13-brightdata.md only lists the dataset id ``gd_l1vijqt9jfj7olije``).
They follow the public Bright Data "Crunchbase companies information" schema:
``name``, ``url``, ``funding_rounds`` {``last_funding_at``, ``last_funding_type``,
``num_funding_rounds``, ``value`` {``value``, ``currency``, ``value_usd``}},
``funding_rounds_list`` [{``announced_on``, ``investment_type``, ``money_raised``,
``lead_investors``}], ``investors`` / ``featured_investors``, ``num_employees``,
``founded_date``, ``investor_type``, ``num_investments``. Alternative spellings are
accepted; see ``_FUNDING_KEYS`` etc. The first real snapshot should confirm them.

Investor detection (``is_investor``): ``investor_type`` non-empty, or ``num_investments`` /
``num_investments_funding_rounds`` > 0, or ``investments`` non-empty, or a type field
(``type``, ``company_type``, ``organization_types``, ``role``, ``roles``) containing
"investor". The row name must also match the company (else False).
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from conferge.core.brightdata import BrightDataClient, BrightDataError, record_call, record_usage

PROVIDER = "brightdata:crunchbase"
DEFAULT_DATASET_ID = "gd_l1vijqt9jfj7olije"
MAX_URLS = 10
ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = ROOT / "data" / "probes"
PUBLIC_CACHE = ROOT / "data" / "cache" / "crunchbase_public.json"

Sleep = Callable[[float], Awaitable[Any]]


class CrunchbaseUnavailable(RuntimeError):
    """Sanitized failure of a Crunchbase dataset call; never carries secrets or bodies."""


def dataset_id() -> str:
    """BRIGHTDATA_CRUNCHBASE_DATASET (env or .env), evaluated at call time, else the default."""
    from conferge.core.settings import env_value

    return env_value("BRIGHTDATA_CRUNCHBASE_DATASET") or DEFAULT_DATASET_ID


# ---------------------------------------------------------------------------
# SERP lookup
# ---------------------------------------------------------------------------


def build_query(name: str) -> str:
    return f'"{name.strip()}" site:crunchbase.com/organization'


def norm(text: str | None) -> str:
    """Lowercase alphanumerics only ("Example Labs, Inc." -> "examplelabsinc")."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_.]*")


def canonical_org_url(url: str) -> str | None:
    """``https://www.crunchbase.com/organization/<slug>`` or None (subpaths dropped)."""
    try:
        parsed = urlparse(html.unescape(url.strip()))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"crunchbase.com", "www.crunchbase.com"}:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2 or segments[0].lower() != "organization":
        return None
    slug = re.split(r"%3f|%23", segments[1], flags=re.I)[0]
    if not _SLUG_RE.fullmatch(slug):
        return None
    return f"https://www.crunchbase.com/organization/{slug.lower()}"


def _unwrap_google(href: str) -> str:
    parsed = urlparse(html.unescape(href))
    if parsed.path == "/url" and (not parsed.hostname or "google" in parsed.hostname):
        query = parse_qs(parsed.query)
        return (query.get("q") or query.get("url") or [""])[0]
    return html.unescape(href)


_HREF_RE = re.compile(r"href=\"([^\"]+)\"", re.I)
_BARE_RE = re.compile(r"https?://(?:www\.)?crunchbase\.com/organization/[A-Za-z0-9\-_.]+", re.I)
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


def parse_serp(text: str) -> list[str]:
    """Canonical organization URLs from brd_json organic results (HTML fallback), deduped."""
    links: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        for item in (data.get("organic") if isinstance(data, dict) else None) or []:
            if isinstance(item, dict):
                link = item.get("link") or item.get("url")
                if isinstance(link, str):
                    links.append(link)
    else:
        body = _SCRIPT_RE.sub(" ", text)
        links += [_unwrap_google(h) for h in _HREF_RE.findall(body)]
        links += _BARE_RE.findall(body)
    out: list[str] = []
    for link in links:
        url = canonical_org_url(link)
        if url and url not in out:
            out.append(url)
    return out


def _agrees(target: str, slug: str) -> bool:
    """Slug and company name agree: equal, or one is the other plus a suffix (momentic-ai)."""
    return bool(target and slug) and (slug == target or slug.startswith(target)
                                      or target.startswith(slug))


def pick_candidate(name: str, urls: Iterable[str]) -> str | None:
    """The one slug that agrees with the company name; None when none or several do.

    Decision: a lone SERP result whose slug does not match the name is rejected; funding
    attached to the wrong organisation would be an invented relation.
    """
    distinct = list(dict.fromkeys(urls))
    target = norm(name)
    exact = [u for u in distinct if norm(u.rsplit("/", 1)[-1]) == target]
    if len(exact) == 1:
        return exact[0]
    agreeing = [u for u in distinct if _agrees(target, norm(u.rsplit("/", 1)[-1]))]
    return agreeing[0] if len(agreeing) == 1 and not exact else None


async def serp_json(client: BrightDataClient, query: str, *, country: str = "us") -> str:
    """Google SERP with ``brd_json=1`` through the SERP zone (core ``serp()`` cannot add it)."""
    if not client.serp_zone:
        raise BrightDataError("BRIGHTDATA_SERP_ZONE not configured")
    url = "https://www.google.com/search?" + urlencode(
        {"q": query, "gl": country, "hl": "en", "brd_json": "1"})
    response = await client._request(
        "POST", "/request", payload={"zone": client.serp_zone, "url": url, "format": "raw"})
    record_usage("serp")
    record_call("serp", rows=1, status="ready")
    return response.text


async def find_crunchbase_url(client: BrightDataClient, name: str) -> str | None:
    """Crunchbase organization URL of ``name``, only when the SERP gives one clear candidate."""
    if not name or not name.strip():
        return None
    text = await serp_json(client, build_query(name))
    return pick_candidate(name, parse_serp(text))


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


async def fetch_company(
    client: BrightDataClient, urls: list[str], *, max_wait: float = 600, poll: float = 10,
    sleep: Sleep = asyncio.sleep, progress_out: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Trigger one collection of up to 10 URLs, poll it, return (rows as sent, snapshot_id).

    Error rows (``{"error": ...}``) are kept: callers skip them. ``progress_out`` receives the
    last ``/progress`` body (where any cost field Bright Data sends would appear).
    """
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return [], None
    if len(urls) > MAX_URLS:
        raise ValueError(f"at most {MAX_URLS} urls per Crunchbase collection")
    snapshot_id: str | None = None
    try:
        snapshot_id = await client.trigger_dataset(dataset_id(), [{"url": u} for u in urls])
        started = time.monotonic()
        waited = 0.0
        while True:
            progress = await client.snapshot_progress(snapshot_id)
            if progress_out is not None:
                progress_out.clear()
                progress_out.update(progress)
            status = str(progress.get("status") or "").lower()
            if status in {"failed", "canceled", "cancelled"}:
                raise CrunchbaseUnavailable(f"snapshot {snapshot_id} {status}")
            if status == "ready":
                out = await client.snapshot_results(snapshot_id)
                if out.status == "ready":
                    return _rows(out.data), snapshot_id
            if max(waited, time.monotonic() - started) >= max_wait:
                raise CrunchbaseUnavailable(
                    f"snapshot {snapshot_id} not ready after {max_wait:.0f}s")
            await sleep(poll)
            waited += poll
    except BrightDataError as exc:
        raise CrunchbaseUnavailable(str(exc)[:200]) from exc


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_FUNDING_KEYS = ("total_funding_usd", "funding_total_usd", "total_funding_amount",
                 "total_funding", "funding_total", "funds_total", "funds_raised")
_ROUND_TYPE_KEYS = ("last_funding_type", "last_round_type", "last_funding_round_type")
_ROUND_DATE_KEYS = ("last_funding_at", "last_funding_date", "last_round_date",
                    "last_funding_on")
_INVESTOR_KEYS = ("investors", "top_investors", "featured_investors", "lead_investors")
_EMPLOYEE_KEYS = ("num_employees", "employee_range", "employees", "employee_count",
                  "num_employees_enum", "company_size")
_FOUNDED_KEYS = ("founded_date", "founded_on", "founded", "founded_year")
_MULT = {"": 1, "k": 10**3, "thousand": 10**3, "m": 10**6, "million": 10**6, "mm": 10**6,
         "b": 10**9, "billion": 10**9, "bn": 10**9, "t": 10**12, "trillion": 10**12}
_MONEY_RE = re.compile(
    r"^(?P<cur>US\$|USD|\$)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<mult>k|thousand|mm|m|million|bn|b|billion|t|trillion)?\s*(?P<cur2>USD)?$", re.I)


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if not _blank(row.get(key)):
            return row[key]
    return None


def _decimal_str(value: Decimal) -> str | None:
    if value < 0:
        return None
    text = format(value.normalize(), "f")
    return text


def parse_money_usd(value: Any) -> str | None:
    """USD amount as a decimal string ("$12.5M" -> "12500000"); other currencies -> None."""
    if _blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        if not _blank(value.get("value_usd")):
            return parse_money_usd(value["value_usd"])
        currency = value.get("currency") or value.get("currency_code")
        if currency is not None and str(currency).strip().upper() not in {"USD", "US$", "$"}:
            return None
        return parse_money_usd(value.get("value", value.get("amount")))
    if isinstance(value, (int, float, Decimal)):
        try:
            return _decimal_str(Decimal(str(value)))
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None
    match = _MONEY_RE.match(value.strip())
    if not match:
        return None  # "€12M", "CA$5M", "undisclosed": not a USD amount
    try:
        amount = Decimal(match["num"].replace(",", ""))
    except InvalidOperation:
        return None
    return _decimal_str(amount * _MULT[(match["mult"] or "").lower()])


_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y")


def parse_date(value: Any) -> str | None:
    """ISO date of a full date (ISO, ISO datetime, "May 1, 2024"); partial or unknown -> None."""
    if isinstance(value, dict):
        value = value.get("value") or value.get("date")
    if isinstance(value, (datetime, date)):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_founded(value: Any) -> str | None:
    """ISO date, or a 4-digit year string when only the year is known (precision "year")."""
    precision = None
    if isinstance(value, dict):
        precision = str(value.get("precision") or "").lower()
        value = value.get("value") or value.get("date")
    if isinstance(value, int) and not isinstance(value, bool) and 1000 < value < 3000:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"\d{4}", value.strip()):
        return value.strip()
    iso = parse_date(value)
    if iso and precision == "year":
        return iso[:4]
    return iso


def _names(value: Any) -> list[str]:
    if _blank(value):
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, dict):
        for key in ("name", "value", "title"):
            if isinstance(value.get(key), str) and value[key].strip():
                return [value[key].strip()]
        for key in ("investor", "identifier", "organization"):
            if isinstance(value.get(key), dict):
                return _names(value[key])
        return []
    if isinstance(value, list):
        return [n for item in value for n in _names(item)]
    return []


def _rounds(row: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = row.get("funding_rounds_list") or row.get("funding_rounds_details") or []
    if isinstance(row.get("funding_rounds"), list):
        rounds = rounds or row["funding_rounds"]
    return [r for r in rounds if isinstance(r, dict)] if isinstance(rounds, list) else []


def _latest_round(row: dict[str, Any]) -> dict[str, Any] | None:
    dated = [(d, r) for r in _rounds(row)
             if (d := parse_date(r.get("announced_on") or r.get("date") or r.get("announced_date")))]
    return max(dated, key=lambda x: x[0])[1] if dated else None


_ENUM_RE = re.compile(r"^c_0*(\d+)_(0*\d+|max)$", re.I)


def _employee_range(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or _blank(value):
        return None
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if match := _ENUM_RE.match(text):
        high = match[2]
        return f"{match[1]}+" if high.lower() == "max" else f"{match[1]}-{int(high)}"
    return text


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    """Public funding summary of one dataset row; any field the row lacks stays None."""
    summary = row.get("funding_rounds") if isinstance(row.get("funding_rounds"), dict) else {}
    latest = _latest_round(row) or {}

    total = parse_money_usd(_first(row, _FUNDING_KEYS))
    if total is None and summary:
        total = parse_money_usd(summary.get("value"))

    round_type = _first(row, _ROUND_TYPE_KEYS) or summary.get("last_funding_type") \
        or latest.get("investment_type") or latest.get("round_type")
    if isinstance(round_type, dict):
        round_type = round_type.get("value")
    round_date = parse_date(_first(row, _ROUND_DATE_KEYS)) or parse_date(
        summary.get("last_funding_at")) or parse_date(
        latest.get("announced_on") or latest.get("date") or latest.get("announced_date"))

    investors: list[str] = []
    for key in _INVESTOR_KEYS:
        for item in row.get(key) or []:
            # Real rows (snapshot sd_mvmv474n1abc3ijv2z): investors[] are investments whose
            # investor name is investor.value; the item's own value is the investment title.
            if isinstance(item, dict) and isinstance(item.get("investor"), dict):
                name = item["investor"].get("value") or item["investor"].get("name")
                if isinstance(name, str) and name.strip():
                    investors.append(name.strip())
            else:
                investors += _names([item])
    for rnd in _rounds(row):
        investors += _names(rnd.get("lead_investors"))
        investors += [n for n in _names(rnd.get("investors")) if " investment in " not in n]
    seen: set[str] = set()
    unique = [n for n in investors if not (n.casefold() in seen or seen.add(n.casefold()))]

    listed = [r for r in (row.get("funding_rounds_list") or []) if isinstance(r, dict)]
    amounts = [parse_money_usd((r.get("money_raised") or {}).get("value_usd"))
               if isinstance(r.get("money_raised"), dict) else None for r in listed]
    detailed = [r for r in (row.get("funding_rounds_detailed") or []) if isinstance(r, dict)]
    last_amount = None
    if round_type and len(detailed) == len(listed):
        idx = next((i for i, r in enumerate(detailed) if r.get("type") == round_type), None)
        last_amount = amounts[idx] if idx is not None else None
    expected = summary.get("num_funding_rounds") if summary else None
    if total is None and listed and all(a is not None for a in amounts) and expected == len(listed):
        # Every round is listed with its USD amount: the total is their sum, nothing estimated.
        total = str(sum(Decimal(a) for a in amounts))  # type: ignore[arg-type]

    return {
        "total_funding_usd": total,
        "last_round_amount_usd": last_amount,
        "last_round_type": str(round_type).strip() if isinstance(round_type, str)
        and round_type.strip() else None,
        "last_round_date": round_date,
        "investors": unique,
        "employee_range": _employee_range(_first(row, _EMPLOYEE_KEYS)),
        "founded": parse_founded(_first(row, _FOUNDED_KEYS)),
    }


def _positive(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and float(str(value).replace(",", "")) > 0
    except (TypeError, ValueError):
        return False


def _mentions_investor(value: Any) -> bool:
    if isinstance(value, str):
        return "investor" in value.casefold()
    if isinstance(value, list):
        return any(_mentions_investor(v) for v in value)
    if isinstance(value, dict):
        return _mentions_investor(value.get("value") or value.get("name"))
    return False


def is_investor(row: dict[str, Any], company_name: str | None = None) -> bool:
    """True only when the row itself marks the organization as an investor (module doc)."""
    if not isinstance(row, dict) or row.get("error"):
        return False
    row_name = row.get("name")
    if company_name and isinstance(row_name, str) and norm(row_name) != norm(company_name):
        return False
    if not _blank(row.get("investor_type")):
        return True
    if _positive(row.get("num_investments")) or _positive(
            row.get("num_investments_funding_rounds")):
        return True
    if isinstance(row.get("investments"), list) and row["investments"]:
        return True
    return any(_mentions_investor(row.get(k))
               for k in ("type", "company_type", "organization_types", "role", "roles"))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_companies(ranked_person_ids: Iterable[str], people: Iterable[Any],
                     companies: Iterable[Any], top_speakers: int = 20,
                     max_companies: int = 10) -> list[Any]:
    """Companies with the most speakers among the top ``top_speakers`` ranked speakers.

    Ties by company name; at most ``max_companies``.
    """
    by_id = {p.id: p for p in people}
    by_company = {c.id: c for c in companies}
    speakers: list[Any] = []
    for pid in ranked_person_ids:
        if len(speakers) == top_speakers:
            break
        person = by_id.get(pid)
        if person and person.participation == "confirmed_speaker" and person not in speakers:
            speakers.append(person)
    counts: dict[str, int] = {}
    for person in speakers:
        if person.company_id in by_company:
            counts[person.company_id] = counts.get(person.company_id, 0) + 1
    order = sorted(counts, key=lambda cid: (-counts[cid], by_company[cid].name.casefold(), cid))
    return [by_company[cid] for cid in order[:max_companies]]


# ---------------------------------------------------------------------------
# Graph write (GraphStore only)
# ---------------------------------------------------------------------------


def _existing_company(store: Any, company_id: str) -> dict[str, Any]:
    from conferge.graph.queries import run_read

    try:
        rows = run_read(store, "MATCH (n:Company {id: $id}) RETURN properties(n)",
                        {"id": company_id})
    except Exception:  # noqa: BLE001 - unreadable graph: write only non-None values
        return {}
    return dict(rows[0][0]) if rows and isinstance(rows[0][0], dict) else {}


def write_company(store: Any, company_id: str, funding: dict[str, Any], *,
                  crunchbase_url: str | None, snapshot_id: str | None,
                  collected_at: datetime, investor: bool,
                  existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """MERGE the Crunchbase funding onto the Company node through ``GraphStore.merge_node``.

    Nested ``funding`` is stored as a JSON string (the store accepts scalars and flat lists
    only), merged key by key with any existing ``funding``: a non-null existing value is
    never replaced, a None is never written. ``is_investor`` is written only when True.
    Returns the properties written.
    """
    current = _existing_company(store, company_id) if existing is None else dict(existing)
    try:
        old_funding = json.loads(current["funding"]) if current.get("funding") else {}
    except (TypeError, ValueError):
        old_funding = {}
    merged = dict(old_funding) if isinstance(old_funding, dict) else {}
    for key, value in funding.items():
        if _blank(merged.get(key)) and not _blank(value):
            merged[key] = value
    props: dict[str, Any] = {}
    if merged and merged != old_funding:
        props["funding"] = json.dumps(merged, sort_keys=True, ensure_ascii=False)
        # Provenance of the funding written now (only when this run adds something).
        props.update({
            "crunchbase_provider": PROVIDER, "crunchbase_snapshot_id": snapshot_id,
            "crunchbase_collected_at": collected_at.astimezone(timezone.utc).isoformat(),
        })
    if crunchbase_url and _blank(current.get("crunchbase_url")):
        props["crunchbase_url"] = crunchbase_url
    if investor and current.get("is_investor") is not True:
        props["is_investor"] = True
    props = {k: v for k, v in props.items() if v is not None}
    if props:
        store.merge_node("Company", company_id, props)
    return props


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------


def write_raw(rows: list[dict[str, Any]], *, snapshot_id: str | None, collected_at: datetime,
              directory: Path = PROBE_DIR) -> Path:
    """Raw rows to ``data/probes/crunchbase_<YYYY-MM-DD>.json`` (gitignored)."""
    path = directory / f"crunchbase_{collected_at.date().isoformat()}.json"
    directory.mkdir(parents=True, exist_ok=True)
    body = {"provider": PROVIDER, "dataset_id": dataset_id(), "snapshot_id": snapshot_id,
            "collected_at": collected_at.isoformat(), "records": rows}
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def public_entry(company: Any, crunchbase_url: str, funding: dict[str, Any], *,
                 snapshot_id: str | None, collected_at: datetime) -> dict[str, Any]:
    return {"company_id": company.id, "name": company.name, "crunchbase_url": crunchbase_url,
            "funding": funding, "snapshot_id": snapshot_id,
            "collected_at": collected_at.astimezone(timezone.utc).isoformat(),
            "source_url": crunchbase_url, "provider": PROVIDER}


def write_public_cache(entries: Iterable[dict[str, Any]], path: Path = PUBLIC_CACHE) -> Path:
    """Public fields only (company id, name, URL, normalized funding, snapshot, timestamps)."""
    keep = ("company_id", "name", "crunchbase_url", "funding", "snapshot_id", "collected_at",
            "source_url", "provider")
    clean = [{k: e.get(k) for k in keep} for e in entries]
    clean.sort(key=lambda e: str(e["company_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": PROVIDER, "companies": clean}, indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_public_cache(path: Path | str = PUBLIC_CACHE) -> dict[str, dict[str, Any]]:
    """company_id -> public entry; missing or unreadable file -> {}."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = body.get("companies") if isinstance(body, dict) else None
    return {str(e["company_id"]): e for e in entries or []
            if isinstance(e, dict) and e.get("company_id")}


def round_label(round_type: str | None) -> str | None:
    """"series_b" -> "Series B" (display only)."""
    if not round_type:
        return None
    words = re.split(r"[_\s]+", round_type.strip())
    return " ".join(w.upper() if len(w) == 1 else w.capitalize() for w in words if w)


def company_view(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fields the /people company card shows, with one cached evidence entry."""
    if not entry or not isinstance(entry.get("funding"), dict):
        return None
    f = entry["funding"]
    last = None
    if f.get("last_round_type") or f.get("last_round_date"):
        last = {"type": f.get("last_round_type"), "label": round_label(f.get("last_round_type")),
                "date": f.get("last_round_date")}
    return {
        "funding": f, "last_round": last,
        "evidence": {"provider": entry.get("provider") or PROVIDER, "source_mode": "cached",
                     "source_url": entry.get("source_url") or entry.get("crunchbase_url"),
                     "collected_at": entry.get("collected_at"),
                     "raw_ref": entry.get("snapshot_id")},
    }
