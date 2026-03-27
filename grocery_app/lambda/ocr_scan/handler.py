import json
import os
import re
import uuid
from datetime import date, datetime

import boto3


textract = boto3.client("textract")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
BUCKET_NAME = os.environ["BUCKET_NAME"]
DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "demo-user")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


def handler(event, _context):
    try:
        body = json.loads(event.get("body") or "{}")
        object_key = body.get("objectKey")
        store = (body.get("store") or "Receipt upload").strip()
        purchased_on = body.get("purchasedOn") or date.today().isoformat()

        if not object_key:
            return respond(400, {"error": "objectKey is required"})

        response = textract.analyze_expense(
            Document={"S3Object": {"Bucket": BUCKET_NAME, "Name": object_key}}
        )

        extracted_items = []
        for document in response.get("ExpenseDocuments", []):
            for group in document.get("LineItemGroups", []):
                for line_item in group.get("LineItems", []):
                    name = ""
                    price = None
                    for field in line_item.get("LineItemExpenseFields", []):
                        field_type = field.get("Type", {}).get("Text", "")
                        value = field.get("ValueDetection", {}).get("Text", "")
                        if field_type == "ITEM":
                            name = value.strip()
                        elif field_type == "PRICE":
                            price = parse_price(value)

                    if not name or price is None:
                        continue

                    item_id = str(uuid.uuid4())
                    record = {
                        "PK": f"USER#{DEFAULT_USER_ID}",
                        "SK": f"ENTRY#{purchased_on}#{item_id}",
                        "id": item_id,
                        "item_name": name,
                        "item_key": normalize_name(name),
                        "store": store,
                        "price_cents": int(round(price * 100)),
                        "purchased_on": purchased_on,
                        "created_at": datetime.utcnow().isoformat(),
                        "notes": f"Imported from receipt image {object_key}",
                        "is_special": False,
                        "quantity": 1,
                    }
                    table.put_item(Item=record)
                    extracted_items.append(
                        {
                            "id": item_id,
                            "itemName": name,
                            "store": store,
                            "price": price,
                            "purchasedOn": purchased_on,
                        }
                    )

        return respond(
            200,
            {
                "message": "Receipt scan complete",
                "count": len(extracted_items),
                "entries": extracted_items,
            },
        )
    except Exception as exc:
        print(f"OCR scan failed: {exc}")
        return respond(500, {"error": "Unable to scan receipt image"})


def respond(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload),
    }


def parse_price(value):
    cleaned = re.sub(r"[^0-9.,]", "", value or "").replace(",", ".")
    return float(cleaned) if cleaned else None


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
