#!/bin/bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
output=${1:?Pass a new output directory, for example ./out}
mkdir "$output"
output=$(cd "$output" && pwd)
driver="$output/driver"
nvidia="$output/nvidia"
low_level="$output/archives"
mkdir "$low_level" "$output/payload"

source_value() {
    /usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]][sys.argv[3]])' \
        "$repo/kit.json" "$1" "$2"
}

git clone --depth 1 --branch "$(source_value driver_source tag)" "$(source_value driver_source url)" "$driver"
git clone --depth 1 --branch "$(source_value nvidia_source tag)" "$(source_value nvidia_source url)" "$nvidia"
[[ "$(git -C "$driver" rev-parse HEAD)" = "$(source_value driver_source commit)" ]]
[[ "$(git -C "$nvidia" rev-parse HEAD)" = "$(source_value nvidia_source commit)" ]]
git -C "$driver" apply --check "$repo/patches/0001-loq-s3-edp.patch"
git -C "$driver" apply "$repo/patches/0001-loq-s3-edp.patch"

# Use literal hostnames. Short numeric hostnames otherwise match strings such as 192KHz.
/usr/bin/python3 - "$driver" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for name in ("build_rm620.sh", "build_kms620.sh"):
    recipe = root / "build" / name
    data = recipe.read_text()
    data = data.replace('grep -ciE "$(id -un)|$(hostname -s)"',
                        'grep -ciF -e "$(id -un)" -e "$(hostname)"')
    data = data.replace('grep -iE "$(id -un)|$(hostname -s)"',
                        'grep -iF -e "$(id -un)" -e "$(hostname)"')
    recipe.write_text(data)
PY

bash "$driver/build/build_rm620.sh" "$low_level" "$nvidia"
bash "$driver/build/build_kms620.sh" "$low_level"
bash "$driver/build/build_nvrm.sh" "$driver/kexts/NVRM" "$low_level/ogkm-620.70.06" "$output/rm"
OGKM="$nvidia" bash "$driver/build/fb_build.sh" "$driver/kexts" "$output/fb"
/usr/bin/python3 "$driver/tools/test_panel_wake_edid.py"
/usr/bin/python3 "$driver/tools/test_display_power_retry.py"
/usr/bin/python3 "$repo/tests/test_loq_panel.py" "$driver"

/usr/bin/ditto "$output/rm/NVRM.kext" "$output/payload/NVRM.kext"
/usr/bin/ditto "$output/fb/NVRMFB.kext" "$output/payload/NVRMFB.kext"
for name in NVRM NVRMFB; do
    target="$output/payload/$name.kext"
    cp "$repo/metadata/$name.plist" "$target/Contents/Info.plist"
    /usr/bin/codesign --force --sign - --timestamp=none "$target"
    /usr/bin/codesign --verify --strict "$target"
    xcrun dwarfdump --uuid "$target/Contents/MacOS/$name"
    shasum -a 256 "$target/Contents/MacOS/$name"
done
