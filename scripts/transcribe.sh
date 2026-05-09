#!/bin/bash
# Whisper.cpp wrapper — called by OpenClaw when a voice note arrives
# Usage: transcribe.sh <input_audio_file>
# Outputs: plain text transcript to stdout
set -e

INPUT="$1"
TMPWAV="/tmp/whisper_$(date +%s%N).wav"
WHISPER_DIR="$HOME/whisper.cpp"

if [ -z "$INPUT" ]; then
    echo "Usage: transcribe.sh <audio_file>" >&2
    exit 1
fi

if [ ! -f "$INPUT" ]; then
    echo "File not found: $INPUT" >&2
    exit 1
fi

ffmpeg -i "$INPUT" "$TMPWAV" -y -loglevel quiet

"$WHISPER_DIR/main" \
    -m "$WHISPER_DIR/models/ggml-medium.bin" \
    -f "$TMPWAV" \
    --print-special false \
    --no-timestamps true \
    -l auto \
    2>/dev/null | grep -v '^\[' | sed '/^$/d'

rm -f "$TMPWAV"
