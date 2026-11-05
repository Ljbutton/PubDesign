#!/usr/bin/env bash
# Builds pubconv.exe (Publisher reader) with MSYS2 UCRT64 and gathers the DLLs it needs into build/.
# Needs: mingw-w64-ucrt-x86_64-{gcc,pkgconf,libmspub,libodfgen}
set -euo pipefail
set -x
cd "$(dirname "$0")"
pkg-config --modversion libmspub-0.1 libodfgen-0.1 librevenge-0.0
FLAGS="$(pkg-config --cflags --libs libmspub-0.1 libodfgen-0.1 librevenge-0.0 librevenge-stream-0.0)"
rm -rf build
mkdir -p build
g++ -O2 -std=c++17 pubconv.cpp -o build/pubconv.exe $FLAGS -lgdiplus
# copy every MSYS2 DLL the exe needs (repeat to pick up dependencies of dependencies)
for pass in 1 2 3 4; do
    ldd build/pubconv.exe build/*.dll 2>/dev/null | awk '/\/ucrt64\// {print $3}' | sort -u | while read -r dll; do
        [ -f "build/$(basename "$dll")" ] || cp "$dll" build/
    done
done
cp test.wmf build/
cp NOTICE.txt build/
ls -la build
du -sh build
