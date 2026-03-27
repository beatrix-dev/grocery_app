import base64
import json
import os
import re
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import boto3
from boto3.dynamodb.conditions import Key


TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ.get("BUCKET_NAME")
DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "demo-user")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
table = dynamodb.Table(TABLE_NAME)


def handler(event, _context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")

    try:
        if path == "/entries" and method == "GET":
            return respond(200, {"entries": get_entries()})
        if path == "/entries" and method == "POST":
            payload = parse_body(event)
            entry = create_entry(payload)
            return respond(201, {"entry": entry})
        if path == "/entries/bulk" and method == "POST":
            payload = parse_body(event)
            entries = [create_entry(item) for item in payload.get("entries", [])]
            return respond(201, {"entries": entries, "count": len(entries)})
        if path == "/summary" and method == "GET":
            entries = get_entries()
            return respond(200, build_summary(entries))
        if path == "/receipts/text" and method == "POST":
            payload = parse_body(event)
            imported = import_receipt_text(payload)
            return respond(201, imported)
        if path == "/upload-url" and method == "POST":
            payload = parse_body(event)
            return respond(200, create_upload_url(payload))
        return respond(404, {"error": f"No route for {method} {path}"})
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    except Exception as exc:
        print(f"Unhandled error: {exc}")
        return respond(500, {"error": "Internal server error"})


def parse_body(event):
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body)


def respond(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(payload),
    }


def get_entries():
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{DEFAULT_USER_ID}")
        & Key("SK").begins_with("ENTRY#")
    )
    items = response.get("Items", [])
    entries = [format_entry(item) for item in items]
    entries.sort(key=sort_key_for_entry, reverse=True)
    return entries


def create_entry(payload):
    prepared = validate_entry_payload(payload)
    history = [
        entry
        for entry in get_entries()
        if entry["itemKey"] == prepared["itemKey"] and not entry["id"] == prepared["id"]
    ]
    analysis = analyze_special(prepared, history)

    item = {
        "PK": f"USER#{DEFAULT_USER_ID}",
        "SK": f"ENTRY#{prepared['purchasedOn']}#{prepared['id']}",
        "id": prepared["id"],
        "item_name": prepared["itemName"],
        "item_key": prepared["itemKey"],
        "store": prepared["store"],
        "price_cents": prepared["priceCents"],
        "purchased_on": prepared["purchasedOn"],
        "created_at": prepared["createdAt"],
        "notes": prepared.get("notes", ""),
        "is_special": prepared["isSpecial"],
        "quantity": prepared["quantity"],
    }

    if prepared.get("claimedOriginalPriceCents") is not None:
        item["claimed_original_price_cents"] = prepared["claimedOriginalPriceCents"]

    if analysis:
        item["special_analysis"] = to_dynamo_compatible(analysis)

    table.put_item(Item=to_dynamo_compatible(item))
    return format_entry(item)


def validate_entry_payload(payload):
    item_name = (payload.get("itemName") or "").strip()
    store = (payload.get("store") or "").strip()
    purchased_on = payload.get("purchasedOn") or date.today().isoformat()
    price = payload.get("price")
    quantity = int(payload.get("quantity") or 1)
    is_special = bool(payload.get("isSpecial"))
    claimed_original = payload.get("claimedOriginalPrice")

    if not item_name:
        raise ValueError("Item name is required")
    if not store:
        raise ValueError("Store is required")
    if price in (None, ""):
        raise ValueError("Price is required")

    try:
        date.fromisoformat(purchased_on)
    except ValueError as exc:
        raise ValueError("purchasedOn must be YYYY-MM-DD") from exc

    price_cents = to_cents(price)
    claimed_original_cents = (
        to_cents(claimed_original) if claimed_original not in (None, "") else None
    )

    return {
        "id": payload.get("id") or str(uuid.uuid4()),
        "itemName": item_name,
        "itemKey": normalize_name(item_name),
        "store": store,
        "priceCents": price_cents,
        "purchasedOn": purchased_on,
        "createdAt": payload.get("createdAt") or datetime.utcnow().isoformat(),
        "quantity": max(quantity, 1),
        "notes": (payload.get("notes") or "").strip(),
        "isSpecial": is_special,
        "claimedOriginalPriceCents": claimed_original_cents,
    }


def analyze_special(entry, history):
    if not entry["isSpecial"]:
        return None

    regular_prices = [
        historic["price"]
        for historic in history
        if not historic["isSpecial"]
    ]

    claimed_discount = None
    if entry.get("claimedOriginalPriceCents"):
        claimed_discount = percentage_drop(
            entry["claimedOriginalPriceCents"], entry["priceCents"]
        )

    if len(regular_prices) < 2:
        return {
            "verdict": "needs-more-history",
            "label": "Needs more history",
            "message": "Log a couple of normal-price entries before trusting this special.",
            "baselinePrice": None,
            "actualDiscountPercent": None,
            "claimedDiscountPercent": round(claimed_discount, 1)
            if claimed_discount is not None
            else None,
        }

    baseline_price = median_cents(regular_prices)
    actual_discount = percentage_drop(baseline_price, entry["priceCents"])

    if actual_discount <= 1:
        verdict = "fake-special"
        label = "Fake special"
        message = "This price is basically the same as your normal paid price."
    elif claimed_discount is not None and claimed_discount - actual_discount >= 10:
        verdict = "inflated-discount"
        label = "Inflated discount"
        message = "The advertised percentage looks much bigger than the saving in your history."
    else:
        verdict = "real-saving"
        label = "Real saving"
        message = "Your history shows this special is genuinely cheaper than usual."

    return {
        "verdict": verdict,
        "label": label,
        "message": message,
        "baselinePrice": cents_to_amount(baseline_price),
        "actualDiscountPercent": round(actual_discount, 1),
        "claimedDiscountPercent": round(claimed_discount, 1)
        if claimed_discount is not None
        else None,
    }


def build_summary(entries):
    today = date.today()
    this_month = today.strftime("%Y-%m")
    last_month_date = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    last_month = last_month_date.strftime("%Y-%m")

    monthly_total = sum(entry["price"] for entry in entries if entry["purchasedOn"].startswith(this_month))
    last_month_total = sum(entry["price"] for entry in entries if entry["purchasedOn"].startswith(last_month))
    unique_items = len({entry["itemKey"] for entry in entries})
    fake_specials = sum(
        1
        for entry in entries
        if entry.get("specialAnalysis", {}).get("verdict") == "fake-special"
    )

    stores = defaultdict(float)
    for entry in entries:
        if entry["purchasedOn"].startswith(this_month):
            stores[entry["store"]] += entry["price"]

    recent_entries = []
    for entry in entries[:5]:
        change = compare_with_previous(entry, entries)
        recent_entries.append({**entry, "priceChange": change})

    specials = [
        entry
        for entry in entries
        if entry["isSpecial"] and entry.get("specialAnalysis") is not None
    ]

    return {
        "monthlySpend": round(monthly_total, 2),
        "lastMonthSpend": round(last_month_total, 2),
        "monthOverMonthDelta": round(monthly_total - last_month_total, 2),
        "uniqueItemsTracked": unique_items,
        "fakeSpecialsCaught": fake_specials,
        "storeBreakdown": [
            {"store": store, "spend": round(spend, 2)}
            for store, spend in sorted(stores.items(), key=lambda item: item[1], reverse=True)
        ],
        "recentEntries": recent_entries,
        "specials": specials[:10],
        "entries": entries,
    }


def compare_with_previous(entry, entries):
    current_key = sort_key_for_entry(entry)
    same_item = [
        candidate
        for candidate in entries
        if candidate["itemKey"] == entry["itemKey"]
        and candidate["id"] != entry["id"]
        and sort_key_for_entry(candidate) < current_key
    ]
    if not same_item:
        return {"direction": "new", "difference": 0}

    same_item.sort(key=sort_key_for_entry, reverse=True)
    previous = same_item[0]
    difference = round(entry["price"] - previous["price"], 2)
    if abs(difference) < 0.01:
        direction = "flat"
    elif difference > 0:
        direction = "up"
    else:
        direction = "down"
    return {"direction": direction, "difference": difference}


def import_receipt_text(payload):
    raw_text = payload.get("receiptText") or ""
    store = (payload.get("store") or "").strip()
    purchased_on = payload.get("purchasedOn") or date.today().isoformat()

    if not raw_text.strip():
        raise ValueError("receiptText is required")
    if not store:
        raise ValueError("Store is required for receipt import")

    parsed_entries = []
    for name, price in parse_receipt_lines(raw_text):
        parsed_entries.append(
            create_entry(
                {
                    "itemName": name,
                    "price": price,
                    "store": store,
                    "purchasedOn": purchased_on,
                    "isSpecial": False,
                }
            )
        )

    return {"entries": parsed_entries, "count": len(parsed_entries)}


def create_upload_url(payload):
    if not BUCKET_NAME:
        raise ValueError("Receipt uploads are not configured")

    file_name = (payload.get("fileName") or "receipt.jpg").strip()
    content_type = (payload.get("fileType") or "image/jpeg").strip()
    object_key = f"receipts/{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4()}-{safe_file_name(file_name)}"

    signed_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=300,
    )

    return {"uploadUrl": signed_url, "objectKey": object_key}


def parse_receipt_lines(raw_text):
    matches = []
    pattern = re.compile(r"^(?P<name>.+?)\s+R?(?P<price>\d+[.,]\d{2})$")
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            matches.append(
                (
                    match.group("name").strip(),
                    float(match.group("price").replace(",", ".")),
                )
            )
    if not matches:
        raise ValueError("No receipt lines matched the format: Item name   R24.99")
    return matches


def format_entry(item):
    special_analysis = item.get("special_analysis")
    return {
        "id": item["id"],
        "itemName": item["item_name"],
        "itemKey": item["item_key"],
        "store": item["store"],
        "price": cents_to_amount(item["price_cents"]),
        "purchasedOn": item["purchased_on"],
        "createdAt": item["created_at"],
        "notes": item.get("notes", ""),
        "quantity": int(item.get("quantity", 1)),
        "isSpecial": bool(item.get("is_special")),
        "claimedOriginalPrice": cents_to_amount(item["claimed_original_price_cents"])
        if item.get("claimed_original_price_cents") is not None
        else None,
        "specialAnalysis": from_dynamo_compatible(special_analysis),
    }


def to_cents(amount):
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def cents_to_amount(cents):
    return round(int(cents) / 100, 2)


def percentage_drop(original_cents, current_cents):
    if not original_cents or original_cents <= 0:
        return 0.0
    return max(0.0, ((original_cents - current_cents) / original_cents) * 100)


def median_cents(prices):
    cents_values = [to_cents(price) if not isinstance(price, int) else price for price in prices]
    return int(statistics.median(cents_values))


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def safe_file_name(file_name):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", file_name)


def sort_key_for_entry(entry):
    return (entry["purchasedOn"], entry["createdAt"])


def to_dynamo_compatible(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: to_dynamo_compatible(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_dynamo_compatible(item) for item in value]
    return value


def from_dynamo_compatible(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: from_dynamo_compatible(val) for key, val in value.items()}
    if isinstance(value, list):
        return [from_dynamo_compatible(item) for item in value]
    return value
