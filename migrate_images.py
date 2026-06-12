"""
migrate_images.py — Task 5 一次性遷移腳本
把 app.py 內 RAW_DATA 的所有外鏈圖片（postimg / zara.net）抓下來，
上傳到 Supabase Storage 的 item-images bucket，並寫入 item_image_cache 表。
跑完之後 App 的圖片就全部走自家 CDN，不再依賴外鏈存活。

用法（本機）：
    export SUPABASE_URL=...
    export SUPABASE_KEY=...        # service key（要能寫 Storage）
    python migrate_images.py [path/to/app.py]
"""
import ast
import hashlib
import os
import sys

import requests

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_KEY")
BUCKET = os.getenv("SB_IMAGE_BUCKET", "item-images")
APP_PATH = sys.argv[1] if len(sys.argv) > 1 else "app.py"

assert SB_URL and SB_KEY, "請先設定 SUPABASE_URL / SUPABASE_KEY 環境變數"

HEADERS = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36",
    "Referer": "https://www.zara.com/",
}


def extract_raw_data(app_path: str) -> list[dict]:
    """用 AST 從 app.py 抓出 RAW_DATA（不執行 app）。"""
    tree = ast.parse(open(app_path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "RAW_DATA":
                    return ast.literal_eval(node.value)
    raise SystemExit("找不到 RAW_DATA")


def migrate_one(name: str, url: str) -> bool:
    key = name.lower().strip()
    try:
        resp = requests.get(url, timeout=15, headers=FETCH_HEADERS)
        if not resp.ok or len(resp.content) < 1000:
            print(f"  ✗ 抓圖失敗 {resp.status_code}: {name}")
            return False
        ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        ext = {"image/png": "png", "image/webp": "webp", "image/avif": "avif"}.get(ctype, "jpg")
        path = f"{hashlib.md5(key.encode()).hexdigest()}.{ext}"
        up = requests.post(
            f"{SB_URL}/storage/v1/object/{BUCKET}/{path}",
            headers={**HEADERS, "Content-Type": ctype, "x-upsert": "true"},
            data=resp.content, timeout=20)
        if not up.ok:
            print(f"  ✗ 上傳失敗 {up.status_code}: {name} — {up.text[:120]}")
            return False
        stored = f"{SB_URL}/storage/v1/object/public/{BUCKET}/{path}"
        requests.post(
            f"{SB_URL}/rest/v1/item_image_cache",
            headers={**HEADERS, "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"},
            json={"item_name": name, "source_url": url, "stored_url": stored},
            timeout=10)
        print(f"  ✓ {name} → {path}")
        return True
    except Exception as e:
        print(f"  ✗ 例外: {name} — {e}")
        return False


def main():
    items = extract_raw_data(APP_PATH)
    print(f"RAW_DATA 共 {len(items)} 筆，開始遷移到 bucket '{BUCKET}'...")
    ok = sum(migrate_one(it["name"], it["url"]) for it in items)
    print(f"\n完成：{ok}/{len(items)} 成功。失敗的會在 App 執行時由背景暖存再試。")


if __name__ == "__main__":
    main()
