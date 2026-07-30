"""Download the 12 Kling Avatar 2.0 talking-head clips into clips/<id>.mp4.

URLs captured 2026-06-23 from kling.ai works/personal API (signed CDN links).
Order = firing order = script order. Each clip already has its VO baked in.
Stdlib only. Re-run safe (skips existing non-empty files).
"""
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "clips")
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (line_id, url) in narrative order
CLIPS = [
    ("q_math",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/0d44aee7-b8ab-4628-b254-cdff3965c5af-AwCKfEDk149v8B84jPMpdg-output.mp4?x-kcdn-pid=112372"),
    ("q_intro",   "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/67f710d3-f673-4d72-85c1-b4d99486cd78-y7OKCjx-lkvMXYhh_LCbwg-output.mp4?x-kcdn-pid=112372"),
    ("q_get",     "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/47929dd7-76c6-4dc6-b2a3-d19b5b7655db-bL_aRBgvVQuhvcd4qrViJg-output.mp4?x-kcdn-pid=112372"),
    ("q_keep",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/b2962553-d30e-4472-85b3-66632b8b7cb4-B1TVCY1P72jsqGpJ1LEE0w-output.mp4?x-kcdn-pid=112372"),
    ("q_grow",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/58d1e094-3585-4c74-a704-cab5585d2efb-zrfFKa6ZDGgjd8nEjx3gKg-output.mp4?x-kcdn-pid=112372"),
    ("q_proof",   "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/cc68c10d-e05b-4cc0-9b03-860f904d3c3b-ljLSG0vnLUlmdwgTSrw0pg-output.mp4?x-kcdn-pid=112372"),
    ("q_cta",     "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/2f5628c8-ef71-4408-81a8-6d6271ee8006-sSS3sUBy203Ucbe5HXwWpQ-output.mp4?x-kcdn-pid=112372"),
    ("q_signoff", "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/b93355d3-43c9-45a9-b455-d827e0ac759f-VXyq8oiX2NC8luNlpxhagQ-output.mp4?x-kcdn-pid=112372"),
    ("c_hook",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/e0e661cb-9d59-45a0-9398-c289469e3f36-BgZRDJYx7pPPmUjZ-OfDBA-output.mp4?x-kcdn-pid=112372"),
    ("c_math",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/a7d8eeb6-30f0-4a85-bf8f-05f56fc28c4d-wiwPeF3Sms4LyR12DB8bKw-output.mp4?x-kcdn-pid=112372"),
    ("c_what",    "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/e65b6bce-0eac-4679-9562-c013cc0913a7-yEbv7GrxdhxZOY_o9ZKZYA-output.mp4?x-kcdn-pid=112372"),
    ("c_cta",     "https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/59fa7664-2900-4ddb-80f9-a84814b32309-vUa9BgPhmBedRvWX6ngbFw-output.mp4?x-kcdn-pid=112372"),
]


def main() -> None:
    for line_id, url in CLIPS:
        path = os.path.join(OUT, f"{line_id}.mp4")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print(f"skip {line_id}")
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as resp, open(path, "wb") as fh:
                fh.write(resp.read())
            print(f"OK   {line_id}.mp4 ({os.path.getsize(path)//1024} KB)")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {line_id} :: {e}")


if __name__ == "__main__":
    main()
