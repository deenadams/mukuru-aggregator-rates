#!/usr/bin/env python3
"""Fetch Mukuru Taurus published rates, rank payout partners per corridor,
flag switch-off candidates, and write a snapshot + rolling history JSON.

Env vars required:
  TAURUS_TOKEN_URL, TAURUS_API_URL, TAURUS_CLIENT_ID, TAURUS_CLIENT_SECRET, TAURUS_SCOPE
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, date

HISTORY_RETENTION_DAYS = 180
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")

def get_token():
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TAURUS_CLIENT_ID"],
        "client_secret": os.environ["TAURUS_CLIENT_SECRET"],
        "scope": os.environ["TAURUS_SCOPE"],
    }).encode()
    req = urllib.request.Request(os.environ["TAURUS_TOKEN_URL"], data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]

def fetch_all_rates(token):
    base = os.environ["TAURUS_API_URL"]
    items, page, total_pages = [], 1, None
    while total_pages is None or page <= total_pages:
        qs = urllib.parse.urlencode({"page": page, "page_size": 500, "include_disabled": "true"})
        req = urllib.request.Request(f"{base}?{qs}", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        items.extend(body["items"])
        total_pages = body["totalPages"]
        page += 1
    return items

def fetch_mid_rates():
    """USD-based table; returns {currency: units per 1 USD}. Free, no key, ~161 currencies."""
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=30) as resp:
            body = json.load(resp)
        if body.get("result") != "success":
            return {}
        return body["rates"]
    except Exception as e:
        print(f"warning: mid-rate fetch failed: {e}", file=sys.stderr)
        return {}

def cross_mid_rate(rates, pay_in_ccy, pay_out_ccy):
    if pay_in_ccy not in rates or pay_out_ccy not in rates:
        return None
    return rates[pay_out_ccy] / rates[pay_in_ccy]

def corridor_key(item):
    pay_in = item["payIn"]["currencyCode"]
    pay_out_country = item["payOut"]["countryCode"] or item["payOut"]["countryName"]
    pay_out_ccy = item["payOut"]["currencyCode"]
    return f"{pay_in}->{pay_out_country}:{pay_out_ccy}:{item['type']}"

def provider_name(item):
    if item.get("payOutPartner"):
        return item["payOutPartner"]["name"]
    if item["rate"]["source"] == "mukuru":
        return "Mukuru (own rail)"
    return "Unknown"

def build_snapshot(items, mid_rates):
    corridors = {}
    for it in items:
        key = corridor_key(it)
        corridors.setdefault(key, {
            "payInCurrency": it["payIn"]["currencyCode"],
            "payOutCountry": it["payOut"]["countryCode"] or it["payOut"]["countryName"],
            "payOutCurrency": it["payOut"]["currencyCode"],
            "type": it["type"],
            "providers": [],
        })
        mid = cross_mid_rate(mid_rates, it["payIn"]["currencyCode"], it["payOut"]["currencyCode"])
        rate_value = it["rate"]["value"]
        deviation = ((rate_value - mid) / mid) if mid else None
        corridors[key]["providers"].append({
            "provider": provider_name(it),
            "productGuid": it["productGuid"],
            "title": it["title"],
            "rate": rate_value,
            "banded": it["rate"]["banded"],
            "enabled": it["flags"]["enabled"],
            "midRate": mid,
            "deviationVsMid": deviation,
        })

    partner_stats = {}
    corridor_list = []
    for key, c in corridors.items():
        enabled = [p for p in c["providers"] if p["enabled"]]
        best_enabled = max(enabled, key=lambda p: p["rate"], default=None)
        best_overall = max(c["providers"], key=lambda p: p["rate"], default=None)
        missed_opportunity = (
            best_overall is not None and best_enabled is not None
            and best_overall["productGuid"] != best_enabled["productGuid"]
            and not best_overall["enabled"]
        )
        c["bestEnabled"] = best_enabled
        c["bestOverall"] = best_overall if missed_opportunity else None
        c["soleCoverage"] = len(enabled) == 1
        corridor_list.append({"key": key, **c})

        for p in c["providers"]:
            if p["provider"] == "Mukuru (own rail)":
                continue
            s = partner_stats.setdefault(p["provider"], {
                "corridorsServed": 0, "corridorsWon": 0, "soleCoverageCorridors": 0,
            })
            if p["enabled"]:
                s["corridorsServed"] += 1
                if best_enabled and p["productGuid"] == best_enabled["productGuid"]:
                    s["corridorsWon"] += 1
                if len(enabled) == 1:
                    s["soleCoverageCorridors"] += 1

    for name, s in partner_stats.items():
        if s["corridorsWon"] > 0:
            s["verdict"] = "keep-competitive"
        elif s["soleCoverageCorridors"] > 0:
            s["verdict"] = "keep-sole-coverage"
        elif s["corridorsServed"] > 0:
            s["verdict"] = "switch-off-candidate"
        else:
            s["verdict"] = "not-live"

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalCorridors": len(corridor_list),
        "corridors": sorted(corridor_list, key=lambda c: c["key"]),
        "partners": partner_stats,
    }

def update_history(snapshot):
    hist_path = os.path.join(OUT_DIR, "history.json")
    history = {}
    if os.path.exists(hist_path):
        with open(hist_path) as f:
            history = json.load(f)

    today = date.today().isoformat()
    for c in snapshot["corridors"]:
        for p in c["providers"]:
            if p["deviationVsMid"] is None:
                continue
            hkey = f"{c['key']}|{p['provider']}"
            series = history.setdefault(hkey, [])
            series.append({"date": today, "deviationVsMid": round(p["deviationVsMid"], 6), "enabled": p["enabled"]})

    cutoff = (datetime.now(timezone.utc).date().toordinal() - HISTORY_RETENTION_DAYS)
    for hkey in list(history.keys()):
        history[hkey] = [e for e in history[hkey] if date.fromisoformat(e["date"]).toordinal() >= cutoff]
        if not history[hkey]:
            del history[hkey]
    return history

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    token = get_token()
    items = fetch_all_rates(token)
    mid_rates = fetch_mid_rates()
    snapshot = build_snapshot(items, mid_rates)
    history = update_history(snapshot)

    with open(os.path.join(OUT_DIR, "snapshot.json"), "w") as f:
        json.dump(snapshot, f, indent=2)
    with open(os.path.join(OUT_DIR, "history.json"), "w") as f:
        json.dump(history, f, indent=2)

    print(f"Wrote snapshot: {snapshot['totalCorridors']} corridors, {len(snapshot['partners'])} partners")

if __name__ == "__main__":
    main()
