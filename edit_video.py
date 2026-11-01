#!/usr/bin/env python3
"""Edit the uploaded talking-head clip: cut pauses, alternate punch-in zoom, title overlay, 1080x1920.
Usage: python edit_video.py <input.mp4> [output.mp4]"""
import subprocess, sys
src = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else "output/edited-smartwatch.mp4"
segs = [(0, 5.31), (5.58, 7.32), (7.58, 9.49), (9.78, 13.03), (13.45, 16.13), (16.40, 18.03)]
font = "assets/NotoSansDevanagari.ttf"
parts, labels = [], []
for i, (a, b) in enumerate(segs):
    z = 1.0 if i % 2 == 0 else 1.18
    w, h = int(1080 * z), int(1920 * z)
    parts.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS,scale={w}:{h},crop=1080:1920:(iw-1080)/2:(ih-1920)/3,setsar=1,fps=30[v{i}]")
    parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]")
    labels.append(f"[v{i}][a{i}]")
dt = lambda txt, y, col, size: (f"drawtext=fontfile={font}:text='{txt}':fontcolor={col}:fontsize={size}:x=(w-text_w)/2:y={y}:"
                                 f"borderw=4:bordercolor=0x0B1F3A:enable='gte(t,1.2)'")
parts.append("".join(labels) + f"concat=n={len(segs)}:v=1:a=1[cv][ca]")
parts.append(f"[cv]{dt('S2000 Promax',230,'0xFFC857',84)},{dt('Smart Watch + Earbuds',340,'white',58)}[v]")
parts.append("[ca]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-filter_complex", ";".join(parts),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out], check=True)
print(out)
