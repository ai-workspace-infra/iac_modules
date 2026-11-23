#!/usr/bin/env python3
"""Pure-stdlib S3 SigV4 (R2) + OSS HMAC-SHA1 uploader and HTTPS/CORS probe verifier."""

import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _sign_s3_v4_headers(*, method, url, payload_bytes, access_key, secret_key, region="auto", service="s3"):
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    canonical_uri = parsed.path or "/"
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()

    headers_to_sign = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    signed_headers = ";".join(sorted(headers_to_sign.keys()))
    canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted(headers_to_sign.keys()))
    canonical_request = "\n".join(
        [method, canonical_uri, parsed.query or "", canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
    )

    def _hmac(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Host": host,
        "Content-Type": "application/json",
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": auth,
    }


def _sign_oss_v1_headers(*, method, bucket, key_path, content_type, access_key, secret_key, date_str=None):
    date_header = date_str or datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    canonical_resource = f"/{bucket}/{key_path.lstrip('/')}"
    string_to_sign = f"{method}\n\n{content_type}\n{date_header}\n{canonical_resource}"
    sig = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    return {
        "Date": date_header,
        "Content-Type": content_type,
        "Authorization": f"OSS {access_key}:{sig}",
    }


def upload_r2_probe(*, endpoint, bucket, key_path, payload_bytes, access_key, secret_key, opener=urllib.request.urlopen):
    clean_key = key_path.lstrip("/")
    url = f"{endpoint.rstrip('/')}/{bucket}/{clean_key}"
    headers = _sign_s3_v4_headers(
        method="PUT",
        url=url,
        payload_bytes=payload_bytes,
        access_key=access_key,
        secret_key=secret_key,
    )
    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="PUT")
    with opener(req, timeout=20) as resp:
        return resp.status


def upload_oss_probe(*, endpoint, bucket, key_path, payload_bytes, access_key, secret_key, opener=urllib.request.urlopen):
    clean_key = key_path.lstrip("/")
    parsed = urllib.parse.urlparse(endpoint.rstrip("/"))
    url = f"{parsed.scheme}://{bucket}.{parsed.netloc}/{clean_key}"
    headers = _sign_oss_v1_headers(
        method="PUT",
        bucket=bucket,
        key_path=clean_key,
        content_type="application/json",
        access_key=access_key,
        secret_key=secret_key,
    )
    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="PUT")
    with opener(req, timeout=20) as resp:
        return resp.status


def probe_https_mirror(*, domain, key_path, origin, opener=urllib.request.urlopen):
    clean_key = key_path.lstrip("/")
    url = f"https://{domain}/{clean_key}"
    req = urllib.request.Request(url, headers={"Origin": origin, "User-Agent": "iac-dual-mirror-probe/1"}, method="GET")
    try:
        with opener(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers_lower = {k.lower(): v for k, v in resp.headers.items()}
            acao = headers_lower.get("access-control-allow-origin", "")
            return {
                "url": url,
                "status": resp.status,
                "acao": acao,
                "body_len": len(body),
                "ok": resp.status == 200 and (acao in (origin, "*")),
            }
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code, "acao": "", "body_len": 0, "ok": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r2-domain", required=True)
    parser.add_argument("--cn-domain", required=True)
    parser.add_argument("--probe-path", default="releases/_health/probe.json")
    parser.add_argument("--origin", default="https://console.svc.plus")
    parser.add_argument("--upload", action="store_true", help="Upload health probe object before HTTPS GET checks")
    args = parser.parse_args(argv)

    if args.upload:
        payload = json.dumps(
            {
                "status": "ok",
                "mirrors": [f"https://{args.r2_domain}", f"https://{args.cn_domain}"],
                "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            sort_keys=True,
        ).encode("utf-8")
        r2_status = upload_r2_probe(
            endpoint=os.environ["R2_ENDPOINT"],
            bucket=os.environ["R2_BUCKET"],
            key_path=args.probe_path,
            payload_bytes=payload,
            access_key=os.environ["R2_ACCESS_KEY_ID"],
            secret_key=os.environ["R2_SECRET_ACCESS_KEY"],
        )
        oss_status = upload_oss_probe(
            endpoint=os.environ["OSS_ENDPOINT"],
            bucket=os.environ["OSS_BUCKET"],
            key_path=args.probe_path,
            payload_bytes=payload,
            access_key=os.environ["OSS_ACCESS_KEY_ID"],
            secret_key=os.environ["OSS_ACCESS_KEY_SECRET"],
        )
        print(json.dumps({"r2_put": r2_status, "oss_put": oss_status}, sort_keys=True))

    results = [
        probe_https_mirror(domain=args.r2_domain, key_path=args.probe_path, origin=args.origin),
        probe_https_mirror(domain=args.cn_domain, key_path=args.probe_path, origin=args.origin),
    ]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
