"""Dry-run: show classification for every file under D:/soft_plc/A_soft without uploading."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from import_local_software import iter_targets, classify, extract_version, ROOT  # noqa

print(f'scanning {ROOT}\n')
n = 0
total_bytes = 0
for path, rel, size in iter_targets(include_huge=True):
    n += 1
    total_bytes += size
    brand, category, vh = classify(rel)
    version = vh or extract_version(path.name)
    print(f'  {rel:80s}  {size / 1024 / 1024:>7.1f} MB  brand={brand:10s} category={category:10s} ver={version}')
print(f'\n{n} files, total {total_bytes / 1024 / 1024 / 1024:.2f} GB')
