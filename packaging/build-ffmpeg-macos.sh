#!/usr/bin/env bash
# Builds static ffmpeg and ffprobe for this Mac's architecture into build/ffmpeg/,
# with the encoders Clickwheel and pyPodLib use: AAC (AudioToolbox), ALAC, LAME
# MP3 and x264. Only macOS's own libraries are linked, so the binaries run on any
# Mac the app supports. Needs Xcode's command line tools, nasm (Intel) and pkgconf.
set -euo pipefail

FFMPEG_VERSION=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
X264_COMMIT=31e19f92f00c7003fa115047ce50978bc98c3a0d  # stable branch

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/ffmpeg"
WORK="$ROOT/build/ffmpeg-src"
PREFIX="$WORK/prefix"
JOBS="$(sysctl -n hw.ncpu)"
export MACOSX_DEPLOYMENT_TARGET=12.0

fetch() {  # url sha256 file
    curl -fsSL --retry 3 -o "$3" "$1"
    echo "$2  $3" | shasum -a 256 -c -
}

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$PREFIX" "$OUT"
cd "$WORK"

fetch "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" "$LAME_SHA256" lame.tar.gz
tar xzf lame.tar.gz
(
    cd "lame-$LAME_VERSION"
    sed -i '' '/lame_init_old/d' include/libmp3lame.sym  # exported but never defined
    ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-frontend --disable-dependency-tracking
    make -j"$JOBS" install
)

git init -q x264
git -C x264 fetch -q --depth 1 https://github.com/mirror/x264 "$X264_COMMIT"
git -C x264 checkout -q FETCH_HEAD
(
    cd x264
    ./configure --prefix="$PREFIX" --enable-static --enable-pic --disable-cli
    make -j"$JOBS" install
)

fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256" ffmpeg.tar.xz
tar xf ffmpeg.tar.xz
(
    cd "ffmpeg-$FFMPEG_VERSION"
    # --disable-autodetect keeps Homebrew's libraries on the build machine out of
    # the binaries; everything wanted is listed explicitly.
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig" ./configure \
        --prefix="$PREFIX" --enable-gpl --enable-static --disable-shared \
        --disable-autodetect --enable-libmp3lame --enable-libx264 \
        --enable-audiotoolbox --enable-videotoolbox --enable-securetransport \
        --enable-zlib --enable-bzlib --enable-iconv \
        --disable-ffplay --disable-doc --disable-debug \
        --pkg-config-flags=--static \
        --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib"
    make -j"$JOBS"
    cp ffmpeg ffprobe "$OUT/"
    cp COPYING.GPLv2 "$OUT/LICENSE-ffmpeg.txt"
)

# Anything linked from outside macOS itself would be missing on users' Macs.
if otool -L "$OUT/ffmpeg" "$OUT/ffprobe" | grep -v ':$' | grep -vE '^[[:space:]]+(/usr/lib/|/System/Library/)'; then
    echo "ffmpeg links libraries that aren't part of macOS" >&2
    exit 1
fi
for encoder in aac aac_at alac libmp3lame libx264; do
    "$OUT/ffmpeg" -hide_banner -encoders | grep -q " $encoder " || { echo "ffmpeg lacks $encoder" >&2; exit 1; }
done
rm -rf "$WORK"
"$OUT/ffmpeg" -hide_banner -version | head -1
