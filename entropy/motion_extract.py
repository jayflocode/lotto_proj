"""Extract reproducible motion evidence from local, constant-rate footage."""

import json
from hashlib import sha256
from pathlib import Path

import cv2
import numpy as np

from .motion import MIN_USABLE_FRACTION, WINDOWS, validate_evidence, validate_geometry, window_bounds


def read_chamber(video, manifest):
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ValueError(f"cannot open {video}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        dimensions = [int(capture.get(key)) for key in
                      (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)]
        if not np.isfinite(fps) or fps <= 0 or dimensions != manifest["frame_size_px"]:
            raise ValueError(f"frame rate or frame size mismatch for {video}")
        start = round(manifest["decode_start_s"] * fps)
        pairs = round(manifest["decode_duration_s"] * fps)
        if not capture.set(cv2.CAP_PROP_POS_FRAMES, start):
            raise ValueError(f"cannot seek in {video}")
        x0, y0, x1, y1 = manifest["crop"]
        frames = []
        for index in range(start, start + pairs + 1):
            ok, frame = capture.read()
            if not ok or int(capture.get(cv2.CAP_PROP_POS_FRAMES)) != index + 1:
                raise ValueError(f"cannot decode frame {index} of {video}")
            frames.append(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY))
        return fps, (start + np.arange(pairs) + 0.5) / fps, np.asarray(frames)
    finally:
        capture.release()


def chamber_flow(frames, scale, alternate=False):
    # Match the Ball Speed Skill foreground mask and two optical-flow settings.
    if alternate:
        frames = frames[:, 8:-5, 7:-7]
    background = np.median(frames, axis=0).astype(np.uint8)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    estimates = np.full(len(frames) - 1, np.nan)
    for index, (first, second) in enumerate(zip(frames, frames[1:])):
        foreground = (first > 95) & (cv2.absdiff(first, background) > 24)
        foreground[:4, :] = foreground[-4:, :] = False
        foreground[:, :4] = foreground[:, -4:] = False
        if np.count_nonzero(foreground) < 15:
            continue
        if alternate:
            flow = cv2.calcOpticalFlowFarneback(first, second, None, 0.5, 3, 13, 3, 5, 1.2, 0)
        else:
            flow = dis.calc(first, second, None)
        estimates[index] = np.median(np.linalg.norm(flow[foreground], axis=-1)) * scale
    return estimates


def summarize_window(time, arrival, shift, series):
    start, end = window_bounds(arrival, shift)
    mask = (time >= start) & (time < end)
    expected = int(mask.sum())
    record = {"frame_pairs": expected}
    for method, values in series.items():
        usable = values[mask & np.isfinite(values)]
        record[method] = {
            "usable_pairs": len(usable),
            "chamber_widths_per_s": round(float(np.median(usable)), 6)
            if len(usable) and len(usable) >= expected * MIN_USABLE_FRACTION else None,
        }
    return record


def extract(manifest_path, video_directory):
    manifest = json.loads(Path(manifest_path).read_text())
    validate_geometry(manifest)
    reports = []
    for clip in manifest["clips"]:
        video = Path(video_directory) / clip["file"]
        digest = sha256()
        with video.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        fps, time, frames = read_chamber(video, manifest)
        scale = fps / manifest["chamber_width_px"]
        series = {"dis": chamber_flow(frames, scale),
                  "farneback": chamber_flow(frames, scale, alternate=True)}
        measurements = {
            name: [summarize_window(time, arrival, shift, series) for arrival in clip["rack_arrival_s"]]
            for name, shift in WINDOWS.items()
        }
        reports.append({**clip, "fps": fps, "sha256": digest.hexdigest(),
                        "measurements": measurements})
    evidence = {
        **manifest, "schema_version": 1,
        "software": {"opencv": cv2.__version__, "numpy": np.__version__},
        "clips": reports,
    }
    validate_evidence(evidence)
    return evidence
