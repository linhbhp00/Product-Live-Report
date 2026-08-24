from __future__ import annotations

import json
import re

import pandas as pd
import requests

from report_logic import clean_master, normalize_header


def normalize_image_source(value) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, list):
        for item in value:
            source = normalize_image_source(item)
            if source:
                return source
        return ""
    if isinstance(value, dict):
        for key in ("url", "tmp_url", "link"):
            source = normalize_image_source(value.get(key, ""))
            if source:
                return source
        return ""
    text = str(value).strip()
    if text.startswith("data:image/"):
        return text
    if text[:1] in "[{":
        try:
            return normalize_image_source(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            pass
    match = re.search(r"https?://[^\s,;\]\)}]+", text)
    return match.group(0).rstrip("'\"") if match else ""


def flatten(value):
    if isinstance(value, list):
        parts = [flatten(item) for item in value]
        return ", ".join(str(item) for item in parts if str(item).strip())
    if isinstance(value, dict):
        for key in ("name", "text", "display_name", "en_name", "link"):
            if value.get(key):
                return value[key]
        return ", ".join(str(item) for item in value.values() if item not in (None, ""))
    return "" if value is None else value


def fetch_lark_master(app_id: str, app_secret: str, app_token: str, table_id: str, view_id: str) -> pd.DataFrame:
    response = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret}, timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("tenant_access_token")
    if not token:
        raise ValueError(payload.get("msg", "Không lấy được Lark access token."))
    records, page_token = [], None
    while True:
        params = {"page_size": 500, "view_id": view_id}
        if page_token:
            params["page_token"] = page_token
        response = requests.get(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg", "Không đọc được Lark Base."))
        data = payload.get("data", {})
        for item in data.get("items", []):
            fields = dict(item.get("fields", {}))
            fields.setdefault("Record ID", item.get("record_id", ""))
            records.append(fields)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    normalized = [{
        key: normalize_image_source(value) if normalize_header(key) in {"image", "image url", "product image", "photo"} else flatten(value)
        for key, value in record.items()
    } for record in records]
    return clean_master(pd.DataFrame(normalized), normalize_image_source)


