import sys
import os
import json
import urllib.request
import re

sys.stdout.reconfigure(encoding='utf-8')

PRODUCT_CACHE = {}

def inspect_product_url(url, pid, raw_type, title=""):
    if url in PRODUCT_CACHE:
        return PRODUCT_CACHE[url]

    norm_type = "vp"
    if "/vig/" in url or raw_type == "integratedGroup":
        norm_type = "vig"
    elif "/course/" in url or raw_type == "course":
        norm_type = "course"
    elif "/ps/" in url or raw_type == "ps":
        norm_type = "ps"
    elif "/e/" in url or raw_type == "webinar":
        norm_type = "webinar"
    elif "/bookings/" in url or raw_type == "oneOnOne":
        norm_type = "oneOnOne"
    elif "/vp/" in url or raw_type == "page":
        norm_type = "vp"

    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    is_attached = False

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', 'ignore')
            matches = re.findall(r'(\{"props":\{"pageProps":.*?\})\s*</script>', html, re.DOTALL)
            if not matches:
                matches = re.findall(r'(\{"props":\{"pageProps":.*)', html, re.DOTALL)
            if matches:
                parsed = json.loads(matches[0])
                page_props = parsed.get('props', {}).get('pageProps', {})
                data_obj = page_props.get('prefetchedData') or page_props.get('courseData', {}).get('collection') or page_props.get('channelData') or page_props.get('eventData') or page_props

                redir = data_obj.get("redirectionLink")
                resources = data_obj.get("resourcesDetails") or {}
                total_res_size = data_obj.get("totalResourcesSize") or 0
                prods_arr = data_obj.get("products") or []
                p0 = prods_arr[0] if prods_arr else {}
                modules = data_obj.get("modules") or data_obj.get("chapters") or []
                thank_you = data_obj.get("thankYouNote") or {}

                has_redir = False
                if isinstance(redir, dict):
                    if redir.get("isEnabled") is not False and redir.get("text"):
                        has_redir = True
                elif isinstance(redir, str) and redir.strip():
                    has_redir = True

                has_file = (resources.get("file", 0) > 0 and total_res_size > 0)
                has_video = (resources.get("video", 0) > 0)
                has_link = (resources.get("link", 0) > 0)
                has_prod_link = bool(p0.get("link") or p0.get("custom") or p0.get("courseIds"))
                has_modules = bool(len(modules) > 0)
                has_thankyou = bool(isinstance(thank_you, dict) and (thank_you.get("note") or thank_you.get("isEnabled")))

                if norm_type in ("vp", "ps"):
                    is_attached = has_file or has_video or has_link or has_redir or has_prod_link or has_modules or has_thankyou
                elif norm_type == "vig":
                    is_attached = has_redir or bool(data_obj.get("telegramLink"))
                elif norm_type == "course":
                    is_attached = has_modules or has_redir or has_prod_link
                elif norm_type in ("oneOnOne", "webinar"):
                    is_attached = True
    except Exception as e:
        is_attached = False

    res = {
        "productId": pid,
        "productType": norm_type,
        "productUrl": url,
        "title": title,
        "isAttached": is_attached,
        "status": "Valid" if is_attached else "Flagged",
        "reason": "Product Link Attached" if is_attached else "Payment page exists, but no product/content link is attached"
    }

    PRODUCT_CACHE[url] = res
    return res

test_items = [
    ("66b33dc602e939001355091d", "page", "https://superprofile.bio/vp/66b33dc602e939001355091d", "Psychology Of Relationship E-book"),
    ("67a77fdaaceb2400138be70b", "integratedGroup", "https://superprofile.bio/vig/67a77fdaaceb2400138be70b", "BASIC+ ADVANCE COURSE"),
    ("065f4cfd-4f8f-4185-8f68-7e88bd18780d", "course", "https://superprofile.bio/course/065f4cfd-4f8f-4185-8f68-7e88bd18780d", "Career Clarity In Intellectual Property Rights")
]

for pid, ptype, url, title in test_items:
    out = inspect_product_url(url, pid, ptype, title)
    print(json.dumps(out, indent=2))
