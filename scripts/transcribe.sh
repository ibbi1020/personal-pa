#!/bin/bash
# Groq Whisper API wrapper — called by OpenClaw when a voice note arrives
# Usage: transcribe.sh <input_audio_file>
# Outputs: plain text transcript to stdout
set -e

INPUT="$1"
TMPWAV="/tmp/whisper_$(date +%s%N).wav"

if [ -z "$INPUT" ]; then
    echo "Usage: transcribe.sh <audio_file>" >&2
    exit 1
fi

if [ ! -f "$INPUT" ]; then
    echo "File not found: $INPUT" >&2
    exit 1
fi

if [ -z "$GROQ_API_KEY" ]; then
    echo "GROQ_API_KEY is not set" >&2
    exit 1
fi

ffmpeg -i "$INPUT" -ar 16000 -ac 1 "$TMPWAV" -y -loglevel quiet

source "$HOME/pa/venv/bin/activate"

python3 - "$TMPWAV" <<'PYEOF'
import sys, os
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])
with open(sys.argv[1], "rb") as f:
    result = client.audio.transcriptions.create(
        model="whisper-large-v3",
        file=f,
        response_format="text",
    )
print(result, end="")
PYEOF

rm -f "$TMPWAV"
