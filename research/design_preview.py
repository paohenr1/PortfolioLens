"""Explicitly synthetic market UI, available only in local debug development."""

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

# These are design fixtures, not a provider integration or an S&P constituent list.
SECTORS = (
    (
        "Technology",
        "tech",
        "30",
        (
            ("MSFT", "Microsoft", "0.62", "421.80", "3.12T", 3),
            ("AAPL", "Apple", "-0.21", "194.32", "2.91T", 3),
            ("NVDA", "NVIDIA", "1.82", "138.24", "3.39T", 3),
            ("AVGO", "Broadcom", "1.15", "250.12", "1.18T", 2),
            ("AMD", "Advanced Micro Devices", "0.38", "154.30", "249B", 1),
            ("CRM", "Salesforce", "-0.45", "288.40", "274B", 1),
            ("ACN", "Accenture", "0.12", "350.20", "220B", 1),
            ("CSCO", "Cisco", "-0.28", "57.10", "227B", 1),
        ),
    ),
    (
        "Communication services",
        "comms",
        "10",
        (
            ("GOOGL", "Alphabet", "0.68", "172.50", "2.05T", 3),
            ("META", "Meta Platforms", "1.24", "478.20", "1.21T", 2),
            ("NFLX", "Netflix", "-0.73", "96.10", "410B", 1),
            ("DIS", "Walt Disney", "0.18", "108.20", "195B", 1),
        ),
    ),
    (
        "Consumer discretionary",
        "consumer",
        "11",
        (
            ("AMZN", "Amazon", "0.92", "179.80", "1.87T", 3),
            ("TSLA", "Tesla", "-2.15", "255.20", "820B", 2),
            ("HD", "Home Depot", "0.36", "367.80", "365B", 1),
            ("NKE", "Nike", "-0.61", "74.20", "109B", 1),
        ),
    ),
    (
        "Financials",
        "finance",
        "14",
        (
            ("JPM", "JPMorgan Chase", "0.28", "248.10", "740B", 3),
            ("BRK.B", "Berkshire Hathaway", "-0.32", "482.30", "1.04T", 3),
            ("BAC", "Bank of America", "-0.18", "44.20", "338B", 1),
            ("GS", "Goldman Sachs", "0.44", "590.20", "185B", 1),
        ),
    ),
    (
        "Health care",
        "health",
        "10",
        (
            ("LLY", "Eli Lilly", "1.43", "871.40", "870B", 3),
            ("UNH", "UnitedHealth", "-0.62", "566.20", "520B", 2),
            ("JNJ", "Johnson & Johnson", "0.20", "159.80", "385B", 1),
            ("ABBV", "AbbVie", "0.55", "189.40", "334B", 1),
        ),
    ),
    (
        "Industrials",
        "industrials",
        "8",
        (
            ("GE", "GE Aerospace", "0.71", "181.10", "198B", 2),
            ("CAT", "Caterpillar", "-0.33", "362.70", "175B", 2),
            ("RTX", "RTX", "0.25", "119.20", "159B", 1),
        ),
    ),
    (
        "Energy",
        "energy",
        "4",
        (
            ("XOM", "Exxon Mobil", "-0.44", "113.20", "460B", 3),
            ("CVX", "Chevron", "-0.28", "152.30", "285B", 2),
        ),
    ),
    (
        "Consumer staples",
        "staples",
        "5",
        (
            ("PG", "Procter & Gamble", "0.18", "165.20", "390B", 2),
            ("KO", "Coca-Cola", "0.24", "62.70", "270B", 2),
            ("PEP", "PepsiCo", "-0.31", "170.10", "234B", 1),
        ),
    ),
    (
        "Utilities",
        "utilities",
        "3",
        (
            ("NEE", "NextEra Energy", "0.30", "72.30", "148B", 3),
            ("SO", "Southern Company", "0.12", "85.60", "94B", 2),
        ),
    ),
    (
        "Materials",
        "materials",
        "2",
        (
            ("LIN", "Linde", "0.10", "441.20", "210B", 3),
            ("SHW", "Sherwin-Williams", "-0.22", "345.80", "86B", 2),
        ),
    ),
    (
        "Real estate",
        "estate",
        "3",
        (
            ("PLD", "Prologis", "0.39", "115.10", "106B", 3),
            ("AMT", "American Tower", "0.15", "198.40", "92B", 2),
        ),
    ),
)


def preview_sectors():
    sectors = []
    sector_changes = {
        "tech": "+0.80%",
        "comms": "+0.60%",
        "consumer": "-0.30%",
        "finance": "+0.10%",
        "health": "+0.40%",
        "industrials": "+0.20%",
        "energy": "-0.40%",
        "staples": "+0.20%",
        "utilities": "+0.30%",
        "materials": "+0.10%",
        "estate": "+0.20%",
    }
    for name, key, weight, stocks in SECTORS:
        rows = []
        for symbol, company, change, price, cap, size in stocks:
            move = float(change)
            direction = "gain" if move >= 0 else "loss"
            strength = 3 if abs(move) >= 1 else 2 if abs(move) >= 0.4 else 1
            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "change": f"{move:+.2f}%",
                    "price": price,
                    "cap": cap,
                    "movement": f"{direction}-{strength}",
                    "size": size,
                    "direction": "positive" if move >= 0 else "negative",
                }
            )
        sectors.append(
            {
                "name": name,
                "key": key,
                "weight": weight,
                "stocks": rows,
                "change": sector_changes[key],
                "direction": "negative" if sector_changes[key].startswith("-") else "positive",
            }
        )
    return sectors


@require_safe
@never_cache
def markets_preview(request):
    if not settings.DEBUG or settings.ENVIRONMENT.production:
        raise Http404
    return render(request, "research/markets_preview.html", {"sectors": preview_sectors()})
