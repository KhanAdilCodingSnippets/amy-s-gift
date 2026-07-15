import subprocess
import threading
import time

from steering.steering import main as steering_main

# Detect whether we're running from source or from inside Race Ahmed.app
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent.parent / "Resources"
else:
    BASE_DIR = Path(__file__).resolve().parent

STEERING_DIR = BASE_DIR / "Steering"

print("=" * 50)
print("            RACE AHMED")
print("=" * 50)

print("Starting Steering Engine...")

steering_thread = threading.Thread(
    target=steering_main,
    daemon=True
)

steering_thread.start()

print("Waiting for camera...")
time.sleep(4)

print("Launching SuperTuxKart...")

game = subprocess.Popen(
    ["open", "-W", "-a", "SuperTuxKart"]
)

time.sleep(2)

subprocess.run([
    "osascript",
    "-e",
    'tell application "SuperTuxKart" to activate'
])

print("Game Running.")

game.wait()

print("Game closed.")
print("Stopping Steering Engine...")

# The steering thread is a daemon thread.
# When the launcher exits, it will exit automatically.

print("Goodbye.")