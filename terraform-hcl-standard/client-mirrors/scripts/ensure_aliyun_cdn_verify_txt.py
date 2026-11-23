#!/usr/bin/env python3
"""Ensure Aliyun CDN domain ownership TXT record exists in Cloudflare DNS before Terraform apply."""

import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ALICLOUD_CDN_ENDPOINT = "https://cdn.aliyuncs.com/"
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


def _percent_encode(value):
    return urllib.parse.quote(str(value), safe="~")


def sign_aliyun_rpc_params(params, access_key_secret, method="GET"):
    """Build query string signed with Aliyun RPC v1 HMAC-SHA1."""
    ordered = sorted((str(k), str(v)) for k, v in params.items())
    canonical = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in ordered)
    string_to_sign = f"{method}&%2F&{_percent_encode(canonical)}"
    digest = hmac.new(
        f"{access_key_secret}&".encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(digest).decode("utf-8")
    return f"{canonical}&Signature={_percent_encode(signature)}"


def aliyun_cdn_call(action, extra_params, access_key_id, access_key_secret, opener=urllib.request.urlopen):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "Format": "JSON",
        "Version": "2018-05-10",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": timestamp,
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Action": action,
    }
    params.update(extra_params)
    query = sign_aliyun_rpc_params(params, access_key_secret, method="GET")
    req = urllib.request.Request(f"{ALICLOUD_CDN_ENDPOINT}?{query}", method="GET")
    try:
        with opener(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Aliyun CDN {action} failed ({exc.code}): {body}") from exc


def cloudflare_api_call(path, cf_token, method="GET", payload=None, opener=urllib.request.urlopen):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {cf_token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(f"{CLOUDFLARE_API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with opener(req, timeout=20) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare API {method} {path} failed ({exc.code}): {body}") from exc
    if not parsed.get("success", False):
        raise RuntimeError(f"Cloudflare API {method} {path} rejected: {parsed.get('errors')}")
    return parsed


def ensure_verify_txt(
    *,
    cdn_domain,
    zone_name,
    alicloud_access_key,
    alicloud_secret_key,
    cloudflare_api_token,
    dry_run=False,
    verify_owner=True,
    wait_dns_seconds=5,
    opener=urllib.request.urlopen,
):
    verify_resp = aliyun_cdn_call(
        "DescribeVerifyContent",
        {"DomainName": cdn_domain},
        alicloud_access_key,
        alicloud_secret_key,
        opener=opener,
    )
    txt_value = str(verify_resp.get("Content") or "").strip()
    if not txt_value:
        raise RuntimeError(f"DescribeVerifyContent returned empty Content for {cdn_domain}")

    record_name = f"verification.{zone_name}".rstrip(".")
    zones = cloudflare_api_call(
        f"/zones?name={urllib.parse.quote(zone_name)}",
        cloudflare_api_token,
        opener=opener,
    ).get("result") or []
    if not zones:
        raise RuntimeError(f"Cloudflare zone not found: {zone_name}")
    zone_id = zones[0]["id"]

    existing = cloudflare_api_call(
        f"/zones/{zone_id}/dns_records?type=TXT&name={urllib.parse.quote(record_name)}",
        cloudflare_api_token,
        opener=opener,
    ).get("result") or []

    matching = [r for r in existing if str(r.get("content") or "").strip('"') == txt_value]
    changed = False
    if matching:
        action = "unchanged"
    elif dry_run:
        action = "would-upsert"
    else:
        body = {
            "type": "TXT",
            "name": record_name,
            "content": f'"{txt_value}"',
            "ttl": 120,
            "proxied": False,
            "comment": "Aliyun CDN domain ownership verification",
        }
        if existing:
            rec_id = existing[0]["id"]
            cloudflare_api_call(
                f"/zones/{zone_id}/dns_records/{rec_id}",
                cloudflare_api_token,
                method="PUT",
                payload=body,
                opener=opener,
            )
            action = "updated"
        else:
            cloudflare_api_call(
                f"/zones/{zone_id}/dns_records",
                cloudflare_api_token,
                method="POST",
                payload=body,
                opener=opener,
            )
            action = "created"
        changed = True

    verified = False
    if verify_owner and not dry_run:
        if changed and wait_dns_seconds > 0:
            time.sleep(wait_dns_seconds)
        attempts = 3 if changed else 1
        last_err = None
        for idx in range(attempts):
            try:
                aliyun_cdn_call(
                    "VerifyDomainOwner",
                    {"DomainName": cdn_domain, "VerifyType": "dnsCheck"},
                    alicloud_access_key,
                    alicloud_secret_key,
                    opener=opener,
                )
                verified = True
                break
            except RuntimeError as exc:
                last_err = exc
                if idx + 1 < attempts and wait_dns_seconds > 0:
                    time.sleep(wait_dns_seconds)
        if not verified and last_err is not None:
            raise last_err

    return {
        "record_name": record_name,
        "zone_id": zone_id,
        "action": action,
        "verified": verified,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdn-domain", required=True)
    parser.add_argument("--zone-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-verify-call", action="store_true")
    parser.add_argument("--wait-dns-seconds", type=int, default=5)
    args = parser.parse_args(argv)

    ak = os.environ.get("ALICLOUD_ACCESS_KEY", "").strip()
    sk = os.environ.get("ALICLOUD_SECRET_KEY", "").strip()
    cf = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not ak or not sk or not cf:
        print(
            "Missing ALICLOUD_ACCESS_KEY, ALICLOUD_SECRET_KEY, or CLOUDFLARE_API_TOKEN",
            file=sys.stderr,
        )
        return 1

    result = ensure_verify_txt(
        cdn_domain=args.cdn_domain,
        zone_name=args.zone_name,
        alicloud_access_key=ak,
        alicloud_secret_key=sk,
        cloudflare_api_token=cf,
        dry_run=args.dry_run,
        verify_owner=not args.skip_verify_call,
        wait_dns_seconds=args.wait_dns_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
