import io
import zipfile

from PIL import Image


def make_osz(path, keys=(4, 5, 6), all_columns=False):
    """Small offline fixture: timing changes, simultaneous taps, and holds."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("audio.mp3", b"audio fixture (not for playback)")
        image = io.BytesIO()
        Image.new("RGB", (16, 9), (255, 0, 128)).save(image, format="PNG")
        archive.writestr("background.png", image.getvalue())
        for key_count in keys:
            columns = range(key_count) if all_columns else range(2)
            positions = [int((col + 0.5) * 512 / key_count) for col in columns]
            notes = [f"{x},192,999,1,0,0:0:0:0:" for x in positions]
            notes.extend(f"{x},192,1745,128,0,2500:0:0:0:0:" for x in positions)
            notes.append(f"{positions[0]},192,3500,1,0,0:0:0:0:")
            hit_objects = "\n".join(notes)
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
{hit_objects}
""")
    return path
