"""Provider-neutral market quote contract used by THI's private collectors."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VERSION = "thi-market-provider-contract-v1.0"
MARKETS = {"moneyline", "spread", "total"}


def iso_time(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def quote(*, provider: str, event_id: str, sport: str, market: str, selection: str,
          price: float, observed_at_utc: str, line: float | None = None,
          available_quantity: float | None = None, last_trade_price: float | None = None,
          deeplink: str | None = None) -> dict:
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market}")
    if not provider or not event_id or not sport or not selection:
        raise ValueError("provider, event_id, sport and selection are required")
    return {
        "contract_version": VERSION,
        "provider": provider,
        "event_id": str(event_id),
        "sport": sport,
        "market": market,
        "selection": selection,
        "line": float(line) if line is not None else None,
        "price": float(price),
        "available_quantity": float(available_quantity) if available_quantity is not None else None,
        "last_trade_price": float(last_trade_price) if last_trade_price is not None else None,
        "observed_at_utc": iso_time(observed_at_utc),
        "deeplink": deeplink,
    }


def novig_quote(event: dict, market: dict, outcome: dict, observed_at_utc: str, partner_id: str | None = None) -> dict:
    """Normalize a documented Novig order-book outcome without requiring credentials."""
    market_type = str(market.get("type") or market.get("market_type") or "").lower()
    selection = str(outcome.get("selection") or outcome.get("name") or "")
    event_id = str(event.get("id") or event.get("event_id") or "")
    url = outcome.get("deeplink")
    if url and partner_id:
        separator = "&" if "?" in str(url) else "?"
        url = f"{url}{separator}partner_id={partner_id}"
    return quote(
        provider="novig", event_id=event_id, sport=str(event.get("sport") or ""),
        market=market_type, selection=selection,
        line=outcome.get("line") or outcome.get("point"),
        price=outcome.get("best_price") if outcome.get("best_price") is not None else outcome.get("price"),
        available_quantity=outcome.get("available_quantity") or outcome.get("quantity"),
        last_trade_price=outcome.get("last_trade_price"), observed_at_utc=observed_at_utc, deeplink=url,
    )
