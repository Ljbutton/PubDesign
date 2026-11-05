# Notices

`template.pub` is derived from a sample file in the Apache POI test data
(https://github.com/apache/poi), licensed under the Apache License 2.0.

The .pub format knowledge was learned from reading the open-source
libmspub project (https://git.libreoffice.org/libmspub, MPL 2.0) and from
studying sample files. No code from either project is included.

## Bundled Publisher reader

PubDesign ships `pubconv`, built from libmspub, librevenge and libodfgen (MPL 2.0) with ICU,
zlib and the GCC runtime libraries, using unmodified DLLs from MSYS2. See
`tools/pubconv/NOTICE.txt` for details and source links.
