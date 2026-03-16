"""Remove BladeRF from ngsoftfm build files.

BladeRFSource.cpp uses a deprecated API incompatible with the libbladerf
version in Debian bookworm. We only need RTL-SDR support, so BladeRF is
removed from CMakeLists.txt and main.cpp before building.
"""
import re, sys, os

src = sys.argv[1]   # path to ngsoftfm source directory

# ── Patch CMakeLists.txt ──────────────────────────────────────────────────────
cmake = os.path.join(src, 'CMakeLists.txt')
txt = open(cmake).read()
txt = re.sub(r'add_library\(sfmbladerf\b.*?\)', '', txt, flags=re.DOTALL)
txt = re.sub(r'target_link_libraries\(sfmbladerf\b.*?\)', '', txt, flags=re.DOTALL)
txt = re.sub(r'\bsfmbladerf\b', '', txt)
open(cmake, 'w').write(txt)
print("Patched CMakeLists.txt")

# ── Patch main.cpp ────────────────────────────────────────────────────────────
main = os.path.join(src, 'main.cpp')
lines = open(main).readlines()
result = []
i = 0
while i < len(lines):
    line = lines[i]

    # Remove BladeRFSource.h include
    if re.search(r'#include\s+"BladeRFSource\.h"', line):
        i += 1
        continue

    # Remove "else if (...bladerf... == 0) { ... }" blocks
    if re.search(r'else if\b.*"bladerf".*==.*0', line):
        i += 1  # skip the else-if line itself
        # advance to the opening '{'
        while i < len(lines) and '{' not in lines[i]:
            i += 1
        # now track brace depth until block closes
        depth = 0
        while i < len(lines):
            depth += lines[i].count('{') - lines[i].count('}')
            i += 1
            if depth == 0:
                break
        continue

    result.append(line)
    i += 1

open(main, 'w').writelines(result)
print("Patched main.cpp")
