"""Scan D:/soft_plc/A_soft, classify each archive, and upload via the direct-to-OSS flow.

Per file:
  1. login -> JWT
  2. POST /software/upload/init with metadata (brand/category/version/size)
  3. Multipart PUT each part directly to OSS (server-side time)
  4. POST /software/upload/complete with the part ETags
  5. Mark done in scripts/import_state.json (resume support)

Skipped:
  - subdirectories (only files at depth 1 of each brand folder)
  - <1MB files
  - .001/.002 split-volume followers (kept .exe combiner per user choice)
  - extensions outside {zip, rar, 7z, exe, msi}
  - files already marked done in scripts/import_state.json
  - files > 2 GB (use --include-huge to override)

Usage:
  python scripts/import_local_software.py                  # full run, with resume
  python scripts/import_local_software.py --max 3           # only next 3 not-yet-uploaded
  python scripts/import_local_software.py --no-huge         # skip files > 2 GB
  python scripts/import_local_software.py --reset          # wipe state and start over
  python scripts/import_local_software_dryrun.py          # print classification only
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import requests

# Force unbuffered output so progress is visible when piped.
import functools
print = functools.partial(print, flush=True)

ROOT = Path(r'D:/soft_plc/A_soft')
API = 'http://localhost:8004/api/v1'
PHONE, CODE = '13800000000', '888888'
ALLOWED_EXTS = {'.zip', '.rar', '.7z', '.exe', '.msi'}
# Must match the Content-Type signed into the single-PUT presigned URL by the
# backend (presign_single_put includes ContentType in the s3v4 signature). If
# the PUT request omits this header OSS rejects it with 403 SignatureDoesNotMatch.
CONTENT_TYPE = 'application/octet-stream'
MIN_SIZE = 1 * 1024 * 1024  # 1 MiB
HUGE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB — KVS combine etc.
STATE_FILE = Path(__file__).parent / 'import_state.json'


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

    # === Omron ===
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
    for pat in [r'[vV][eE]?[rR]?\.?\s?(\d+(?:\.\d+)+[A-Za-z]?)', r'[vV](\d+(?:\.\d+)*[A-Za-z]?)', r'(\d+\.\d+\.\d+[A-Za-z]?)']:
        m = re.search(pat, name)
        if m:
            return m.group(1)
    return '1.0'


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def iter_targets(include_huge: bool):
    """Yield (abs_path, rel_path, size) for every uploadable file at depth 1
    of each brand folder. Files inside any further subdirectory are skipped
    — those are almost always pieces of an installer disk image and would
    explode the catalog with hundreds of junk entries.
    """
    skipped_combos: set[str] = set()
    for brand_dir in sorted(ROOT.iterdir()):
        if not brand_dir.is_dir():
            continue
        for path in sorted(brand_dir.iterdir()):
            if not path.is_file():
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
            if not include_huge and size > HUGE_SIZE:
                print(f'  - SKIP huge >2GB ({size/1024/1024:.0f}MB) {rel}  (use --include-huge to upload)')
                continue
            yield path, rel, size


def upload_one(token: str, path: Path, rel: str, size: int) -> bool:
    brand, category, version_hint = classify(rel)
    version = version_hint or extract_version(path.name)
    init_body = {
        'filename': path.name,
        'brand': brand,
        'category': category,
        'version': version,
        'content_type': CONTENT_TYPE,
        'size': size,
    }
    h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    print(f'\n>>> {rel}  ({size / 1024 / 1024:.1f} MB)  brand={brand} category={category} ver={version}')
    t0 = time.time()

    init = requests.post(f'{API}/software/upload/init', headers=h, json=init_body, timeout=60).json()
    if init.get('code') != 200:
        print(f'   ! init failed: {init}')
        return False
    d = init['data']
    mode = d['mode']
    token_jwt = d.get('token')

    parts: list[dict] = []
    if mode == 'multipart':
        part_size = d['part_size']
        urls = d['part_urls']
        with open(path, 'rb') as f:
            for i, url in enumerate(urls, 1):
                t_part = time.time()
                buf = f.read(part_size)
                for attempt in range(3):
                    try:
                        r = requests.put(url, data=buf, timeout=1800)
                        if r.status_code == 200:
                            etag = r.headers.get('ETag', '').strip('"')
                            parts.append({'part_number': i, 'etag': etag})
                            elapsed = time.time() - t_part
                            mbps = (len(buf) / 1024 / 1024) / elapsed if elapsed > 0 else 0
                            print(f'   part {i}/{len(urls)} OK ({len(buf)/1024/1024:.1f} MB in {elapsed:.1f}s, {mbps:.1f} MB/s)')
                            break
                        print(f'   part {i} HTTP {r.status_code} attempt {attempt + 1}')
                    except Exception as e:
                        print(f'   part {i} error attempt {attempt + 1}: {e}')
                else:
                    print(f'   ! part {i} permanently failed, aborting upload')
                    requests.post(f'{API}/software/upload/abort', headers=h, json={'token': token_jwt})
                    return False
    elif mode == 'single':
        with open(path, 'rb') as f:
            buf = f.read()
        t_part = time.time()
        # Content-Type must match what was signed into the presigned URL.
        for attempt in range(3):
            try:
                r = requests.put(d['upload_url'], data=buf, headers={'Content-Type': CONTENT_TYPE}, timeout=1800)
                if r.status_code == 200:
                    break
                print(f'   single PUT HTTP {r.status_code} attempt {attempt + 1}: {r.text[:200]}')
            except Exception as e:
                print(f'   single PUT error attempt {attempt + 1}: {e}')
        else:
            print(f'   ! single PUT permanently failed, aborting upload')
            requests.post(f'{API}/software/upload/abort', headers=h, json={'token': token_jwt})
            return False
        print(f'   single OK ({len(buf)/1024/1024:.1f} MB in {time.time()-t_part:.1f}s)')
    elif mode == 'sync':
        with open(path, 'rb') as f:
            files = {'file': (path.name, f, 'application/octet-stream')}
            data = {'brand': brand, 'category': category, 'version': version, 'description': ''}
            r = requests.post(f'{API}/software/upload', headers={'Authorization': f'Bearer {token}'}, files=files, data=data, timeout=3600)
        if r.status_code != 200:
            print(f'   ! sync upload failed: {r.status_code} {r.text[:200]}')
            return False
        print(f'   OK (sync)')
    else:
        print(f'   ! unknown init mode {mode}')
        return False

    comp = requests.post(f'{API}/software/upload/complete', headers=h, json={'token': token_jwt, 'parts': parts}, timeout=300).json()
    if comp.get('code') == 200:
        sw = comp['data']
        print(f'   OK -> software id={sw["id"]}  (total {time.time()-t0:.1f}s)')
        return True
    else:
        print(f'   ! complete failed: {comp}')
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=0, help='stop after N successful uploads (0 = no limit)')
    ap.add_argument('--no-huge', action='store_true', help='skip files > 2 GB')
    ap.add_argument('--include-huge', action='store_true', help='(default) include huge files')
    ap.add_argument('--reset', action='store_true', help='wipe state file and start over')
    args = ap.parse_args()

    if not ROOT.is_dir():
        sys.exit(f'ROOT not found: {ROOT}')

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print('state file wiped')

    include_huge = not args.no_huge

    state = load_state()
    # Only files confirmed ok are skipped; failed/incomplete entries (ok=False)
    # are retried on the next run.
    done = {r for r, v in state.items() if v.get('ok')}
    print(f'resuming with {len(done)} already-uploaded files recorded')
    targets = list(iter_targets(include_huge=include_huge))
    pending = [(p, r, s) for p, r, s in targets if r not in done]
    print(f'\ntotal candidates: {len(targets)}, already uploaded: {len(done)}, pending: {len(pending)}')
    if args.max:
        pending = pending[:args.max]
        print(f'--max {args.max}: processing only the first {len(pending)} pending')
    print(f'estimated upload size: {sum(s for _, _, s in pending) / 1024**3:.2f} GB\n')

    # JWT access tokens expire in 15 min; for the 20 GB total run a single
    # token won't last. Refresh before each file — the cost is one HTTP call
    # vs hours of debugging 401s mid-batch.
    token = login()
    token_time = time.time()

    ok = 0
    fail = 0
    for i, (path, rel, size) in enumerate(pending, 1):
        if time.time() - token_time > 600:  # 10 min: refresh with 5 min to spare
            print(f'\n[refreshing token after {int(time.time() - token_time)}s]')
            token = login()
            token_time = time.time()
        print(f'\n[{i}/{len(pending)}]')
        try:
            if upload_one(token, path, rel, size):
                state[rel] = {'size': size, 'ok': True}
                save_state(state)
                ok += 1
            else:
                state[rel] = {'size': size, 'ok': False}
                save_state(state)
                fail += 1
        except Exception as e:
            print(f'   !! exception: {e}')
            state[rel] = {'size': size, 'ok': False, 'err': str(e)[:200]}
            save_state(state)
            fail += 1
        if args.max and ok >= args.max:
            print(f'\nreached --max {args.max}, stopping')
            break

    print(f'\n=== done: {ok} uploaded, {fail} failed (of {len(pending)} this run) ===')
    print(f'overall state: {sum(1 for v in state.values() if v.get("ok"))} ok / {len(state)} total')


if __name__ == '__main__':
    main()
