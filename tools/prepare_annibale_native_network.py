#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Apply pinned native init integration; never modify a stock input dump."""
import hashlib
import inspect
import json
from pathlib import Path
from annibale_ramdisk import require


def fixup_annibale_native_init(ctx, file, file_path, rule, **kwargs):
    # Self-contained: this exact function is embedded in extract-files.py.
    import hashlib
    from pathlib import Path
    path = Path(file_path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != rule['input_sha256']:
        raise ValueError('native init input changed: ' + str(file_path))
    text = data.decode('utf-8')
    for old, new in rule['replacements']:
        if text.count(old) != 1:
            raise ValueError('native init replacement is not unique')
        text = text.replace(old, new)
    data = text.encode('utf-8')
    if hashlib.sha256(data).hexdigest() != rule['output_sha256']:
        raise ValueError('native init output differs')
    path.write_bytes(data)


def prepare(tree):
    tree=Path(tree)
    repo=Path(__file__).resolve().parents[1]
    profile=json.loads((repo/'Documentation/xiaomi/annibale-native-network.json').read_text())
    for name,rule in profile['device_files'].items():
        fixup_annibale_native_init(None,None,tree/name,rule)
    path=tree/'extract-files.py';script=path.read_text()
    require(hashlib.sha256(script.encode()).hexdigest()==profile['extract_input_sha256'], 'changed extraction script')
    marker='blob_fixups: blob_fixups_user_type = {\n'
    require(script.count(marker)==1,'changed fixup dictionary')
    entries=''.join('    '+repr(name)+': blob_fixup().call(fixup_annibale_native_init, '+repr(rule)+', need_tmp_dir=False),\n'
                    for name,rule in profile['vendor_files'].items())
    script=script.replace(marker,inspect.getsource(fixup_annibale_native_init)+'\n'+marker+entries)
    path.write_text(script)
    return profile
