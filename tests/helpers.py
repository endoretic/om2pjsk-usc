import io
import zipfile

from PIL import Image


def make_osz(path, keys=(4, 5, 6)):
    """Small offline fixture: timing changes, simultaneous notes, and two holds."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("audio.mp3", b"audio fixture (not for playback)")
        image = io.BytesIO()
        Image.new("RGB", (16, 9), (255, 0, 128)).save(image, format="PNG")
        archive.writestr("background.png", image.getvalue())
        for key_count in keys:
            left = int(0.5 * 512 / key_count)
            second = int(1.5 * 512 / key_count)
            archive.writestr(f"{key_count}K.osu", f"""osu file format v14
[General]
AudioFilename: audio.mp3
Mode: 3
[Metadata]
Title: Target test
Artist: Test
Creator: Test
Version: {key_count}K
[Difficulty]
CircleSize: {key_count}
[Events]
0,0,"background.png",0,0
[TimingPoints]
1000,500,4,2,0,100,1,0
2000,-50,4,2,0,100,0,0
3000,250,4,2,0,100,1,0
[HitObjects]
{left},192,999,1,0,0:0:0:0:
{second},192,999,1,0,0:0:0:0:
{left},192,1745,128,0,2500:0:0:0:0:
{second},192,1745,128,0,2500:0:0:0:0:
{left},192,3500,1,0,0:0:0:0:
""")
    return path
