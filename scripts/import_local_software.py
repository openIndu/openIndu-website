"""Scan D:/soft_plc/A_soft, classify each archive, and upload via the direct-to-OSS flow.

Process per file:
  1. login -> JWT
  2. POST /software/upload/init with metadata (brand/category/version/size)
  3. Multipart PUT each part directly to OSS (server-side time)
  4. POST /software/upload/complete with the part ETags
  5. Print a summary line

Skipped:
  - subdirectories (only files at depth 1 of each brand folder)
  - <1MB files (Omron's 25KB rar is junk)
  - .001/.002 split-volume followers (kept .exe combiner per user choice — "含分卷")
  - extensions outside {zip, rar, 7z, exe, msi}
"""
import io
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import requests

ROOT = Path(r'D:/soft_plc/A_soft')
API = 'http://localhost:8004/api/v1'
PHONE, CODE = '13800000000', '888888'
ALLOWED_EXTS = {'.zip', '.rar', '.7z', '.exe', '.msi'}
MIN_SIZE = 1 * 1024 * 1024  # 1 MiB

# (path-fragment matchers, brand, category, optional version)
# Matched on the lowercased path relative to ROOT. First match wins, so put
# specific rules above generic ones.
RULES = [
    # === Driver folder ===
    ('driver/mx component', 'mitsubishi', 'plc-driver', None),
    ('driver/3u_usb', 'mitsubishi', 'plc-driver', None),
    ('driver/ch340', 'other', 'plc-driver', None),
    ('driver/msrd3x40', 'other', 'plc-driver', None),
    ('driver/usr-tcp232', 'other', 'utility', None),

    # === SV folder (servo / utilities) ===
    ('sv/alpha5', 'fuji', 'plc-ide', None),
    ('sv/axtools', 'other', 'utility', None),
    ('sv/ckd', 'ckd', 'plc-ide', None),
    ('sv/nsk', 'nsk', 'utility', None),
    ('sv/panaterm', 'panasonic', 'plc-ide', None),

    # === HMI folder ===
    ('hmi/ebpro', 'weinview', 'hmi-ide', None),
    ('hmi/proface', 'proface', 'hmi-ide', None),
    ('hmi/proex', 'proface', 'hmi-ide', None),

    # === Top-level brand folders ===
    ('codesys/', 'codesys', 'plc-ide', None),
    ('ebpro/', 'weinview', 'hmi-ide', None),
    ('威纶触摸屏/', 'weinview', 'hmi-ide', None),
    ('huatu/', 'huatu', 'utility', None),
    ('kvs/', 'keyence', 'plc-ide', None),
    ('inovance/', 'inovance', 'plc-ide', None),

    # === Mitsubishi sub-rules (look at filename) ===
    ('mitsubishi/gt works', 'mitsubishi', 'hmi-ide', None),
    ('mitsubishi/gx works', 'mitsubishi', 'plc-ide', None),
    ('mitsubishi/gtwk', 'mitsubishi', 'hmi-ide', None),
    ('mitsubishi/sw1dnd-gxw', 'mitsubishi', 'plc-ide', None),
    ('mitsubishi/', 'mitsubishi', 'plc-ide', None),

    # === Fuji ===
    ('fuji/fuji-hmi', 'fuji', 'hmi-ide', None),
    ('fuji/富士plc', 'fuji', 'plc-ide', None),
    ('fuji/', 'fuji', 'plc-ide', None),

    # === Simens (typo of siemens) ===
    ('simens/tia.portal.v20', 'siemens', 'plc-ide', 'V20'),
    ('simens/', 'siemens', 'plc-ide', None),

    # === Omron — only the suspicious 25KB rar; will be filtered by MIN_SIZE ===
    ('omron/', 'omron', 'other', None),
]


def login() -> str:
    req = urllib.request.Request(f'{API}/auth/login', method='POST',
        headers={'Content-Type': 'application/json'},
        data=json.dumps({'phone': PHONE, 'code': CODE}).encode())
    return json.loads(urllib.request.urlopen(req).read())['data']['tokens']['access_token']


def classify(rel_path: str) -> tuple[str, str, str | None]:
    """Return (brand, category, version_hint) for a relative path. Falls back
    to ('other', 'other', None) when nothing matches."""
    p = rel_path.replace('\\', '/').lower()
    for fragment, brand, category, version in RULES:
        if fragment in p:
            return brand, category, version
    return 'other', 'other', None


def extract_version(name: str) -> str:
    """Best-effort version from filename. Default '1.0' if nothing found."""
    import re
    # Match things like V18, v1.9.1.6, Ver.1.401T, 3.5.21, V20
    for pat in [r'[vV][eE]?[rR]?\.?\s?(\d+(?:\.\d+)+[A-Za-z]?)', r'[vV](\d+(?:\.\d+)*[A-Za-z]?)', r'(\d+\.\d+\.\d+[A-Za-z]?)']:
        m = re.search(pat, name)
        if m:
            return m.group(1)
    return '1.0'


def iter_targets():
    """Yield (abs_path, rel_path, size) for every uploadable file.

    Strategy: only walk the brand folder (one level deep). Files inside any
    further subdirectory are skipped — those are almost always pieces of an
    installer disk image (Disk1/SUPPORT/.NET prerequisites/etc.) and would
    explode the catalog with 100+ junk entries.

    Special case: KVS_Sample_G_1234_combine.exe and any other top-level
    .exe in a brand folder is still considered the "package".
    """
    skipped_combos: set[str] = set()
    for brand_dir in sorted(ROOT.iterdir()):
        if not brand_dir.is_dir():
            continue
        for path in sorted(brand_dir.iterdir()):
            if not path.is_file():
                # Subdirectories are skipped — they're either unpacked installer
                # contents or duplicate copies of the archive at this level.
                continue
            rel = path.relative_to(ROOT).as_posix()
            ext = path.suffix.lower()
            if ext not in ALLOWED_EXTS:
                if ext in {'.001', '.002', '.003', '.004', '.005'}:
                    stem = path.stem
                    if stem not in skipped_combos:
                        skipped_combos.add(stem)
                        print(f'  - SKIP split-volume {rel}')
                else:
                    print(f'  - SKIP non-archive {rel}')
                continue
            size = path.stat().st_size
            if size < MIN_SIZE:
                print(f'  - SKIP <1MB ({size}B) {rel}')
                continue
            yield path, rel, size


def upload_one(token: str, path: Path, rel: str, size: int) -> None:
    brand, category, version_hint = classify(rel)
    version = version_hint or extract_version(path.name)
    init_body = {
        'filename': path.name,
        'brand': brand,
        'category': category,
        'version': version,
        'content_type': 'application/octet-stream',
        'size': size,
    }
    h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    print(f'\n>>> {rel}  ({size / 1024 / 1024:.1f} MB)  brand={brand} category={category} ver={version}')

    # init
    init = requests.post(f'{API}/software/upload/init', headers=h, json=init_body, timeout=60).json()
    if init.get('code') != 200:
        print(f'   ! init failed: {init}')
        return
    d = init['data']
    mode = d['mode']
    token_jwt = d.get('token')

    parts: list[dict] = []
    if mode == 'multipart':
        part_size = d['part_size']
        urls = d['part_urls']
        with open(path, 'rb') as f:
            for i, url in enumerate(urls, 1):
                buf = f.read(part_size)
                # Retry up to 3 times per part — OSS occasionally drops a connection on multi-GB transfers.
                for attempt in range(3):
                    try:
                        r = requests.put(url, data=buf, timeout=1800)
                        if r.status_code == 200:
                            etag = r.headers.get('ETag', '').strip('"')
                            parts.append({'part_number': i, 'etag': etag})
                            print(f'   part {i}/{len(urls)} OK ({len(buf) / 1024 / 1024:.1f} MB)')
                            break
                        print(f'   part {i} HTTP {r.status_code} attempt {attempt + 1}')
                    except Exception as e:
                        print(f'   part {i} error attempt {attempt + 1}: {e}')
                else:
                    print(f'   ! part {i} permanently failed')
                    requests.post(f'{API}/software/upload/abort', headers=h, json={'token': token_jwt})
                    return
    elif mode == 'single':
        with open(path, 'rb') as f:
            buf = f.read()
        r = requests.put(d['upload_url'], data=buf, timeout=1800)
        if r.status_code != 200:
            print(f'   ! single PUT failed: {r.status_code}')
            return
    elif mode == 'sync':
        # Local storage backend fallback — POST as multipart form.
        with open(path, 'rb') as f:
            files = {'file': (path.name, f, 'application/octet-stream')}
            data = {'brand': brand, 'category': category, 'version': version, 'description': ''}
            r = requests.post(f'{API}/software/upload', headers={'Authorization': f'Bearer {token}'}, files=files, data=data, timeout=3600)
        if r.status_code != 200:
            print(f'   ! sync upload failed: {r.status_code} {r.text[:200]}')
        else:
            print(f'   OK (sync)')
        return
    else:
        print(f'   ! unknown init mode {mode}')
        return

    # complete
    comp = requests.post(f'{API}/software/upload/complete', headers=h, json={'token': token_jwt, 'parts': parts}, timeout=300).json()
    if comp.get('code') == 200:
        sw = comp['data']
        print(f'   OK -> software id={sw["id"]}')
    else:
        print(f'   ! complete failed: {comp}')


def main():
    if not ROOT.is_dir():
        sys.exit(f'ROOT not found: {ROOT}')
    print(f'login as {PHONE}...')
    token = login()
    targets = list(iter_targets())
    print(f'\nTotal {len(targets)} files to upload.\n')
    for i, (path, rel, size) in enumerate(targets, 1):
        print(f'\n[{i}/{len(targets)}]', end=' ')
        try:
            upload_one(token, path, rel, size)
        except Exception as e:
            print(f'   !! exception: {e}')
    print('\nAll done.')


if __name__ == '__main__':
    main()
