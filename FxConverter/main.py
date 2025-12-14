# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

# See PyCharm help at https://www.jetbrains.com/help/pycharm/


from flask import Flask, render_template, request
from datetime import datetime, timedelta, timezone
import requests
import json
import os


CACHE_FILE = "rates_cache.json"




def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r") as f:
        return json.load(f)


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def cache_key(base, target, date):
    return f"{base}_{target}_{date}"


def save_today_rate(base, target, rate):
    cache = load_cache()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    key = cache_key(base, target, today)
    cache[key] = rate

    save_cache(cache)


def is_precache_complete():
    cache = load_cache()
    yesterday = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    for base in ALL_CURRENCIES:
        for target in ALL_CURRENCIES:
            if base == target:
                continue

            key = cache_key(base, target, yesterday)
            if key not in cache:
                return False

    return True


def utc_days_ago(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%d")


def get_rate_open_er(base, target):
    url = f"https://open.er-api.com/v6/latest/{base}"
    data = requests.get(url).json()

    if data.get("result") != "success":
        return None

    return data["rates"].get(target)


def precache_all_currencies():
    if is_precache_complete():
        print("Pre-cache complete — skipping")
        return

    cache = load_cache()
    yesterday = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    for base in ALL_CURRENCIES:
        try:
            response = requests.get(
                f"https://open.er-api.com/v6/latest/{base}",
                timeout=5
            )
            data = response.json()
        except Exception:
            continue  # skip this base, app still runs

        if data.get("result") != "success":
            continue

        rates = data.get("rates", {})

        for target in ALL_CURRENCIES:
            if target == base:
                continue

            rate = rates.get(target)
            if not rate:
                continue

            key = cache_key(base, target, yesterday)

            # Only fill missing entries
            if key not in cache:
                cache[key] = rate

    save_cache(cache)


def already_precached_today():
    cache = load_cache()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return any(today in key for key in cache)


def get_cached_yesterday_rate(base, target):
    cache = load_cache()
    yesterday = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    key = cache_key(base, target, yesterday)
    return cache.get(key)




def calculate_volatility(current, past):
    change_pct = ((current - past) / past) * 100

    if abs(change_pct) < 0.5:
        level = "Stable"
        color = "green"
    elif abs(change_pct) < 1.5:
        level = "Moderate"
        color = "orange"
    else:
        level = "Volatile"
        color = "red"

    return round(change_pct, 2), level, color


app = Flask(__name__)


# ---------- API CONFIG ----------
APIS = {
"open_er": {
"name": "Open ER API (Global)",
"supports": "all"
},
"frankfurter": {
"name": "Frankfurter API (ECB)",
"supports": "limited"
}
}


# Master currency list
ALL_CURRENCIES = [
"USD", "MYR", "EUR", "GBP", "JPY", "SGD", "AUD", "CAD",
"CHF", "NZD", "CNY", "HKD", "INR", "KRW"
]


# Frankfurter-supported currencies (ECB-based)
FRANKFURTER_CURRENCIES = [
"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "SGD"
]


# ---------- CONVERTER ----------
def convert_currency(api, amount, from_currency, to_currency):
    if api == "open_er":
        url = f"https://open.er-api.com/v6/latest/{from_currency}"
        data = requests.get(url).json()

        if data.get("result") != "success":
            return None, "Invalid base currency"

        if to_currency not in data["rates"]:
            return None, "Currency not supported"

        rate = data["rates"][to_currency]
        return amount * rate, None

    if api == "frankfurter":
        url = "https://api.frankfurter.app/latest"
        params = {"from": from_currency, "to": to_currency}
        data = requests.get(url, params=params).json()

        if "rates" not in data or to_currency not in data["rates"]:
            return None, "Currency not supported by Frankfurter"

        return amount * data["rates"][to_currency], None




# ---------- ROUTE ----------
@app.route("/", methods=["GET", "POST"])
def home():
    result = error = output = None
    selected_api = request.form.get("api", "open_er")
    volatility: dict | None = None

    if request.method == "POST":

        # ✅ Only convert if Convert button was pressed
        if request.form.get("action") == "convert":
            amount = float(request.form["amount"])
            from_curr = request.form["from_currency"]
            to_curr = request.form["to_currency"]

            result, error = convert_currency(
                selected_api, amount, from_curr, to_curr
            )

            if result:
                output = f"{amount} {from_curr} = {result:.2f} {to_curr}"

            if result: # and selected_api == "open_er":
                rate_today = result / amount
                save_today_rate(from_curr, to_curr, rate_today)

                past_rate = get_cached_yesterday_rate(from_curr, to_curr)

                if past_rate:
                    change, level, color = calculate_volatility(result / amount, past_rate)
                    volatility = {
                    "level": level,
                    "change": change,
                    "color": color
                }
                else:
                    volatility = {
                        "level": "Unavailable",
                        "change": None,
                        "color": "gray"
                }

    return render_template(
        "index.html",
        apis=APIS,
        selected_api=selected_api,
        currencies=ALL_CURRENCIES,
        frankfurter_currencies=FRANKFURTER_CURRENCIES,
        result=result,
        output=output,
        error=error,
        volatility = volatility
    )




cache_initialized = False

@app.before_request
def initialize_cache_once():
    global cache_initialized
    if not cache_initialized:
        if not already_precached_today():
            precache_all_currencies()

        cache_initialized = True




if __name__ == "__main__":
    app.run(debug=True)
