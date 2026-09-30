import os
import glob
from pathlib import Path
from movie_scene_multispeaker import assemble_test_video

CLIPS_DIR = "/srv/media/movie_scene_multispeaker/clips"
OUTPUT_FILE = "current_progress.mp4"

def merge_clips():
    search_pattern = os.path.join(CLIPS_DIR, "clip_*.mp4")
    clip_files = sorted(glob.glob(search_pattern))
    
    if not clip_files:
        print(f"No clips found in {CLIPS_DIR}")
        return

    print(f"Found {len(clip_files)} clips. Assembling progress video...")
    for f in clip_files:
        print(f"  + {os.path.basename(f)}")
        
    print("\nRendering final video using internal ffmpeg compiler...")
    paths = [Path(f) for f in clip_files]
    final_path = assemble_test_video(paths, OUTPUT_FILE)
    
    print(f"\n✅ Success! The merged video is saved inside the container at: {final_path}")
    print("To copy it to your PC, run this in PowerShell:")
    print("  $cid = (docker-compose ps -q api).Trim()")
    print(f"  docker cp \"${{cid}}:{final_path}\" .\\current_progress.mp4\n")

if __name__ == "__main__":
    merge_clips()
