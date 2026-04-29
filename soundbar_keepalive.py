#!/usr/bin/env python3
"""
soundbar_keepalive.py — keep a soundbar alive via PulseAudio/PipeWire

Setup:
  1. List sinks:          python3 soundbar_keepalive.py --list
  2. Test:                python3 soundbar_keepalive.py -d "Samsung Soundbar Q90R"
  3. Add to cron:         crontab -e
                          */3 * * * * /path/to/soundbar_keepalive.py -d "Samsung Soundbar Q90R"
     With optional log:   */3 * * * * /path/to/soundbar_keepalive.py -d "Samsung Soundbar Q90R" >> ~/soundbar.log 2>&1
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
import time

FREQ     = 18000    # Hz — above typical hearing range
DURATION = 0.5     # seconds
INTERVAL = None    # seconds
VOLUME   = 0.5     # 0.0–1.0;
RATE     = 44100


# PulseAudio / PipeWire

def list_sinks() -> list[dict]:
    try:
        raw = subprocess.check_output(["pactl", "list", "sinks"], text=True, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit("pactl not found — is PulseAudio or PipeWire running?")
    except subprocess.CalledProcessError as e:
        sys.exit(f"pactl error: {e}")

    sinks, cur = [], {}
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("Sink #"):
            if cur:
                sinks.append(cur)
            cur = {"name": "", "desc": "", "state": ""}
        elif s.startswith("Name:"):
            cur["name"] = s.split(":", 1)[1].strip()
        elif s.startswith("Description:"):
            cur["desc"] = s.split(":", 1)[1].strip()
        elif s.startswith("State:"):
            cur["state"] = s.split(":", 1)[1].strip()
    if cur:
        sinks.append(cur)
    return sinks


def find_sink(hint: str) -> dict | None:
    h = hint.lower()
    return next(
        (s for s in list_sinks() if h in s["desc"].lower() or h in s["name"].lower()),
        None,
    )


# Audio

def make_wav(path: str, freq: int, duration: float, volume: float):
    n    = int(RATE * duration)
    peak = int(32767 * max(0.0, min(1.0, volume)))
    data = [int(peak * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)]
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(struct.pack(f"<{n}h", *data))


def play(wav_path: str, sink_name: str) -> bool:
    for cmd in [
        ["pw-play", "--target=" + sink_name, wav_path],  # PIPEWIRE-NATIVE ADDITION
        ["paplay", "--device", sink_name, wav_path],
        ["ffmpeg", "-y", "-loglevel", "quiet", "-i", wav_path, "-f", "pulse", sink_name],
    ]:
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            return True
        except FileNotFoundError:
            continue
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return False


# Cleanup

def cleanup(wav_path: str):
    print()
    print(f"Cleaning up {wav_path}")
    try:
        os.unlink(wav_path)
    except OSError:
        pass


# CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", metavar="DEVICE", default=os.environ.get("KEEPALIVE_DEVICE", ""),
                    help="Case-insensitive substring of sink name or description")
    ap.add_argument("--list",    "-l", action="store_true", help="Print all sinks and exit")
    ap.add_argument("--interval",type=int,   default=INTERVAL, help="Time in seconds between playback if not using cron")
    ap.add_argument("--freq",    type=int,   default=FREQ,     help=f"Tone Hz (default: {FREQ})")
    ap.add_argument("--volume",  type=float, default=VOLUME,   help=f"Volume 0.0-1.0 (default: {VOLUME})")
    ap.add_argument("--duration",type=float, default=DURATION, help=f"Seconds (default: {DURATION})")
    args = ap.parse_args()
    args.device = args.d

    if args.list:
        sinks = list_sinks()
        if not sinks:
            sys.exit("No output sinks found.")
        col = max(len(s["desc"] or s["name"]) for s in sinks) + 2
        print(f"\n{'DESCRIPTION':<{col}} {'STATE':<12} SINK NAME")
        print("-" * (col + 40))
        for s in sinks:
            print(f"{(s['desc'] or s['name']):<{col}} {s['state']:<12} {s['name']}")
        print(f"\nExample: {sys.argv[0]} --device 'Samsung Soundbar Q90R'\n")
        return

    if not args.device:
        ap.error("-d is required. Use --list to see available sinks.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    make_wav(wav_path, args.freq, args.duration, args.volume)

    pings = 1

    try:
        while True:
            sink = find_sink(args.device)
            if sink is None:
                sys.exit("No output sink found.")

            if not play(wav_path, sink["name"]):
                sys.exit("Playback failed — is paplay or ffmpeg installed?")

            if args.interval is None:
                break

            if pings != 1:
                print(f"We have pinged the speaker {pings} times", end="\r", flush=True)
            else:
                print("\033[K" + f"We have pinged the speaker {pings} time", end="\r", flush=True)
            pings += 1

            time.sleep(args.interval)
    finally:
        cleanup(wav_path)

if __name__ == "__main__":
    main()
