#!/usr/bin/env python3
"""Usage: python make.py scenes.json   -> output/<name>.mp4 + frame checks"""
import asyncio, json, math, os, shutil, subprocess, sys, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
WORK = ROOT / "build"
NAME = "budhigandaki-kukur"
W, H = 1080, 1920


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(path)])
    return float(out)


def tts(text, out_wav, cfg, rate_pct):
    """edge-tts (Sagar -> Hemkala) -> gTTS -> espeak-ng (offline fallback)."""
    rate = f"{rate_pct:+d}%"
    clean = text.replace("‍", "")
    try:
        import edge_tts
        for voice in [cfg["voice"]] + cfg.get("fallback_voices", []):
            try:
                mp3 = out_wav.with_suffix(".mp3")
                asyncio.run(edge_tts.Communicate(clean, voice, rate=rate).save(str(mp3)))
                if mp3.exists() and mp3.stat().st_size > 1000:
                    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(out_wav)])
                    return "edge-tts " + voice
            except Exception as e:
                print("  edge-tts failed:", voice, type(e).__name__)
    except ImportError:
        pass
    try:
        from gtts import gTTS
        mp3 = out_wav.with_suffix(".mp3")
        gTTS(clean, lang="ne").save(str(mp3))
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", f"atempo={1+rate_pct/100}",
             "-ar", "44100", "-ac", "1", str(out_wav)])
        return "gTTS"
    except Exception as e:
        print("  gTTS failed:", type(e).__name__)
    if shutil.which("espeak-ng"):
        tmp = out_wav.with_suffix(".raw.wav")
        run(["espeak-ng", "-v", "ne", "-s", str(int(150 * (1 + rate_pct / 100))), "-p", "35", "-g", "4",
             "-w", str(tmp), clean])
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-ar", "44100", "-ac", "1", str(out_wav)])
        return "espeak-ng (ne)"
    raise RuntimeError("No TTS backend available")


def build_audio(cfg, rate_pct):
    WORK.mkdir(exist_ok=True)
    fps, tail = cfg["fps"], cfg["tail"]
    infos, backend = [], None
    for i, sc in enumerate(cfg["scenes"], 1):
        wav = WORK / f"s{i}.wav"
        backend = tts(sc["text"], wav, cfg, rate_pct)
        a = dur(wav)
        frames = math.ceil((a + tail) * fps)
        infos.append({"audio": a, "frames": frames, "wav": wav})
    return infos, backend


def main():
    cfg_path = Path(sys.argv[1] if len(sys.argv) > 1 else "scenes.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    fps = cfg["fps"]
    OUT.mkdir(exist_ok=True)
    if WORK.exists():
        shutil.rmtree(WORK)
    rate_pct = int(cfg.get("rate", "+0%").replace("%", ""))
    infos, backend = build_audio(cfg, rate_pct)
    total = sum(x["frames"] for x in infos) / fps
    print(f"TTS backend: {backend}; total {total:.1f}s at rate {rate_pct:+d}%")
    if total > cfg["max_total"] and rate_pct < 10:
        print("Too long -> rebuilding at +10% voice rate")
        shutil.rmtree(WORK)
        rate_pct = 10
        infos, backend = build_audio(cfg, rate_pct)
        total = sum(x["frames"] for x in infos) / fps
        print(f"total now {total:.1f}s")

    # per-scene padded audio -> single track
    padded = []
    for i, x in enumerate(infos, 1):
        p = WORK / f"p{i}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(x["wav"]), "-af",
             f"apad=whole_dur={x['frames']/fps:.4f}", "-ar", "44100", "-ac", "1", str(p)])
        padded.append(p)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in padded))
    audio = WORK / "audio.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", str(audio)])

    # frames
    from playwright.sync_api import sync_playwright
    frames_dir = WORK / "frames"
    frames_dir.mkdir()
    check_dir = OUT / "checks"
    check_dir.mkdir(exist_ok=True)
    n = 0
    with sync_playwright() as pw:
        exe = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux64/chrome"))), None)
        br = pw.chromium.launch(executable_path=str(exe) if exe else None, args=["--no-sandbox"])
        page = br.new_page(viewport={"width": W, "height": H})
        for si, (sc, x) in enumerate(zip(cfg["scenes"], infos), 1):
            page.goto((ROOT / "template.html").as_uri())
            page.evaluate("document.fonts.ready")
            # word reveal times, weighted by character count over the spoken duration
            words = sc["text"].split(" ")
            total_c = sum(len(w) for w in words)
            span = x["audio"] * 0.94
            t0, acc, times = 0.12, 0, []
            for w in words:
                times.append(t0 + span * acc / total_c)
                acc += len(w)
            sc2 = dict(sc, times=times)
            page.evaluate("([s,c])=>init(s,c)", [sc2, cfg])
            page.evaluate("document.fonts.ready")
            for f in range(x["frames"]):
                t = f / fps
                page.evaluate("t=>setT(t)", t)
                page.screenshot(path=str(frames_dir / f"f{n:05d}.jpg"), type="jpeg", quality=95)
                if si in (1, 3, 6) and f == x["frames"] - 1:
                    page.screenshot(path=str(check_dir / f"scene{si}.png"))
                n += 1
            print(f"scene {si}: {x['frames']} frames ({x['frames']/fps:.2f}s, audio {x['audio']:.2f}s)")
        br.close()

    mp4 = OUT / f"{NAME}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames_dir / "f%05d.jpg"),
         "-i", str(audio), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(fps), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart",
         "-shortest", str(mp4)])
    shutil.rmtree(frames_dir)

    cap = OUT / "caption.txt"
    if not cap.exists():
        cap.write_text("२० दिनपछि कुकुर उद्धार, बुढीगण्डकी बाढीपछिको खबर #नेपाल #गोरखा #बुढीगण्डकी #खबर #nepalnews\n",
                       encoding="utf-8")
    vs = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                             "stream=width,height,r_frame_rate,codec_name", "-of", "json", str(mp4)]))["streams"][0]
    print(f"\nDuration: {dur(mp4):.2f}s | {vs['width']}x{vs['height']} {vs['r_frame_rate']} {vs['codec_name']}")
    print(f"Size: {mp4.stat().st_size/1e6:.2f} MB")
    print(f"Path: {mp4}")


if __name__ == "__main__":
    main()
