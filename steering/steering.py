import cv2
import mediapipe as mp
import numpy as np
import math
import time
import os
from pynput.keyboard import Key, Controller

# --- CONFIGURATION ---
CAMERA_INDEX       = 0
WHEEL_PATH         = "assets/wheel.png"
WINDOW_WIDTH       = 320  # Wider layout for natural camera aspect ratio
WINDOW_HEIGHT      = 240

DEAD_ZONE_DEG      = 8
MAX_STEER_DEG      = 40
PWM_CYCLE_SEC      = 0.05

FLIP_CAMERA        = True
MIN_DETECTION_CONF = 0.65
MIN_TRACKING_CONF  = 0.65
GRACE_FRAMES       = 12 

# Hardcoded Ergonomic Anchors (Calculated from screen-width ratios)
ABS_NEUTRAL_DIST   = 0.28  # Resting hand separation baseline
ABS_MAX_GAS_DIST   = 0.44  # Spread out for max speed
ABS_BRAKE_DIST     = 0.20  # Pulled close for heavy braking

# Sleek UI Overlay Colors
CLR_TEXT      = (255, 255, 255)
CLR_ACTIVE    = (255, 160, 0)
CLR_GAS       = (80, 240, 80)
CLR_BRAKE     = (80, 80, 255)
CLR_WARNING   = (0, 0, 255)

keyboard   = Controller()
mp_hands   = mp.solutions.hands
mp_draw    = mp.solutions.drawing_utils
mp_styles  = mp.solutions.drawing_styles

# ==========================================
# GRAPHICS TRANSFORMATION ENGINE
# ==========================================
def rotate_image(image, angle):
    if image is None: return None
    image_center = tuple(np.array(image.shape[1::-1]) / 2)
    rot_mat = cv2.getRotationMatrix2D(image_center, angle, 1.0)
    return cv2.warpAffine(image, rot_mat, image.shape[1::-1], flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0,0))

def overlay_transparent(bg_img, img_to_overlay_t, x, y):
    try:
        b, g, r, a = cv2.split(img_to_overlay_t)
        overlay_color = cv2.merge((b, g, r))
        mask = cv2.medianBlur(a, 3)
        h, w, _ = overlay_color.shape
        roi = bg_img[y:y+h, x:x+w]
        img1_bg = cv2.bitwise_and(roi.copy(), roi.copy(), mask=cv2.bitwise_not(mask))
        img2_fg = cv2.bitwise_and(overlay_color, overlay_color, mask=mask)
        bg_img[y:y+h, x:x+w] = cv2.add(img1_bg, img2_fg)
    except Exception:
        pass
    return bg_img

# ==========================================
# REFINED ABSOLUTE CONTROLLER
# ==========================================
class AbsoluteSteeringController:
    def __init__(self):
        self.keys_held = {Key.left: False, Key.right: False, Key.up: False, Key.down: False}
        self.angle_history = []
        self.HISTORY_LEN = 3

    def _press(self, key):
        if not self.keys_held[key]:
            try:
                keyboard.press(key)
                self.keys_held[key] = True
            except Exception:
                pass

    def _release(self, key):
        if self.keys_held[key]:
            try:
                keyboard.release(key)
                self.keys_held[key] = False
            except Exception:
                pass

    def release_all(self):
        for key in list(self.keys_held.keys()):
            self._release(key)
        self.angle_history.clear()

    def smooth_angle(self, raw_angle: float) -> float:
        self.angle_history.append(raw_angle)
        if len(self.angle_history) > self.HISTORY_LEN:
            self.angle_history.pop(0)
        return float(np.mean(self.angle_history))

    def update(self, left_wrist, right_wrist):
        dx = right_wrist[0] - left_wrist[0]
        dy = right_wrist[1] - left_wrist[1]

        raw_angle_deg = math.degrees(math.atan2(dy, dx))
        angle = self.smooth_angle(raw_angle_deg)
        hand_distance = math.sqrt(dx * dx + dy * dy)

        # 1. FIXED ABSOLUTE STEERING CALCULATIONS
        direction = "STRAIGHT"
        if angle < -DEAD_ZONE_DEG: direction = "LEFT"
        elif angle > DEAD_ZONE_DEG: direction = "RIGHT"

        steer_strength = 0.0
        if direction != "STRAIGHT":
            steer_strength = min(1.0, (abs(angle) - DEAD_ZONE_DEG) / (MAX_STEER_DEG - DEAD_ZONE_DEG))

        # 2. FIXED ERGONOMIC PEDAL MAPPING (NO GUESSING)
        gas_strength = 0.0
        brake_strength = 0.0

        if hand_distance >= ABS_NEUTRAL_DIST:
            # Neutral starts at 25% cruise speed. Spreading wide brings it to 100%.
            span_ratio = (hand_distance - ABS_NEUTRAL_DIST) / (ABS_MAX_GAS_DIST - ABS_NEUTRAL_DIST)
            gas_strength = min(1.0, 0.25 + (max(0.0, span_ratio) * 0.75))
        else:
            # Dropping inside the neutral pocket engages the braking engine
            if hand_distance < ABS_NEUTRAL_DIST:
                brake_ratio = (ABS_NEUTRAL_DIST - hand_distance) / (ABS_NEUTRAL_DIST - ABS_BRAKE_DIST)
                brake_strength = min(1.0, max(0.0, brake_ratio))

        # 3. DIRECT HARDWARE INPUT INJECTIONS
        current_time = time.time()
        cycle_pos = (current_time % PWM_CYCLE_SEC) / PWM_CYCLE_SEC

        if direction == "LEFT":
            self._release(Key.right)
            if cycle_pos < steer_strength or steer_strength == 1.0: self._press(Key.left)
            else: self._release(Key.left)
        elif direction == "RIGHT":
            self._release(Key.left)
            if cycle_pos < steer_strength or steer_strength == 1.0: self._press(Key.right)
            else: self._release(Key.right)
        else:
            self._release(Key.left)
            self._release(Key.right)

        if gas_strength > 0:
            self._release(Key.down)
            if cycle_pos < gas_strength or gas_strength == 1.0: self._press(Key.up)
            else: self._release(Key.up)
        elif brake_strength > 0:
            self._release(Key.up)
            if cycle_pos < brake_strength or brake_strength == 1.0: self._press(Key.down)
            else: self._release(Key.down)
        else:
            self._release(Key.up)
            self._release(Key.down)

        return angle, steer_strength, gas_strength, brake_strength

# ==========================================
# HEADS-UP DISPLAY DRAW OVERLAY
# ==========================================
def draw_hud_overlay(hud, wheel_img, angle, gas_strength, brake_strength, hands_visible, speed):
    h, w = hud.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Status Notification Flags
    if not hands_visible:
        cv2.rectangle(hud, (0, 0), (w, 35), (0, 0, 180), -1)
        cv2.putText(hud, "HANDS LOST / CORRECT POSITION", (25, 22), font, 0.45, (255, 255, 255), 2)
    else:
        # Mini Translucent Telemetry Plate
        cv2.rectangle(hud, (5, 5), (95, 45), (0, 0, 0), -1)
        cv2.putText(hud, f"{int(speed)} KM/H", (10, 24), font, 0.45, CLR_TEXT, 1)
        
        gear = "D" if gas_strength > 0.26 else ("R" if brake_strength > 0 else "N")
        if gas_strength <= 0.26 and gas_strength > 0: gear = "CRUISE"
        cv2.putText(hud, f"MODE: {gear}", (10, 40), font, 0.35, CLR_ACTIVE, 1)

    # Centered Spinning Wheel Graphic
    wheel_size = 110
    if wheel_img is not None:
        rotated = rotate_image(wheel_img, -angle)
        x_off = (w - wheel_size) // 2
        y_off = (h - wheel_size) // 2 + 10
        overlay_transparent(hud, rotated, x_off, y_off)

    # Sleek Left/Right Margin Pedal Graphs
    bar_h = 100
    bar_y = (h + bar_h) // 2
    
    # Left Margin: Brake Channel
    cv2.rectangle(hud, (10, bar_y - bar_h), (18, bar_y), (60, 60, 60), -1)
    if brake_strength > 0:
        cv2.rectangle(hud, (10, bar_y - int(bar_h * brake_strength)), (18, bar_y), CLR_BRAKE, -1)

    # Right Margin: Throttle Channel
    cv2.rectangle(hud, (w - 18, bar_y - bar_h), (w - 10, bar_y), (60, 60, 60), -1)
    if gas_strength > 0:
        cv2.rectangle(hud, (w - 18, bar_y - int(bar_h * gas_strength)), (w - 10, bar_y), CLR_GAS, -1)

# ==========================================
# RUNTIME PIPELINE LOOP
# ==========================================
def main():
    wheel_img = None
    if os.path.exists(WHEEL_PATH):
        wheel_img = cv2.imread(WHEEL_PATH, cv2.IMREAD_UNCHANGED)
        if wheel_img is not None:
            wheel_img = cv2.resize(wheel_img, (110, 110))

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    controller = AbsoluteSteeringController()
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        model_complexity=1,
        min_detection_confidence=MIN_DETECTION_CONF,
        min_tracking_confidence=MIN_TRACKING_CONF,
    )

    angle = 0.0
    steer_strength, gas_strength, brake_strength = 0.0, 0.0, 0.0
    lost_frames = 0
    fake_speed = 0.0

    win_name = "Dashboard Mirror"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, WINDOW_WIDTH, WINDOW_HEIGHT)
    cv2.setWindowProperty(win_name, cv2.WND_PROP_TOPMOST, 1)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            if FLIP_CAMERA:
                frame = cv2.flip(frame, 1)

            # Resize the raw camera frame directly to form our HUD background!
            hud_display = cv2.resize(frame, (WINDOW_WIDTH, WINDOW_HEIGHT))

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)

            both_visible = False

            if results.multi_hand_landmarks:
                # Render the tracked skeletal mesh overlay directly onto our HUD window frame
                for res_landmarks in results.multi_hand_landmarks:
                    mp_draw.draw_landmarks(
                        hud_display,
                        res_landmarks,
                        mp_hands.HAND_CONNECTIONS,
                        mp_styles.get_default_hand_landmarks_style(),
                        mp_styles.get_default_hand_connections_style()
                    )

                if len(results.multi_hand_landmarks) == 2 and results.multi_handedness:
                    hand_data = {}
                    for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                        label = handedness.classification[0].label
                        wrist = hand_landmarks.landmark[0]
                        hand_data[label] = (wrist.x, wrist.y)

                    if "Left" in hand_data and "Right" in hand_data:
                        both_visible = True
                        lost_frames = 0
                        angle, steer_strength, gas_strength, brake_strength = controller.update(hand_data["Left"], hand_data["Right"])
                    else:
                        lost_frames += 1
                else:
                    lost_frames += 1
            else:
                lost_frames += 1

            if lost_frames >= GRACE_FRAMES:
                controller.release_all()
                angle, steer_strength, gas_strength, brake_strength = 0.0, 0.0, 0.0, 0.0

            # Dynamic speed approximation
            if both_visible:
                if gas_strength > 0: fake_speed = min(140, fake_speed + (gas_strength * 1.8))
                elif brake_strength > 0: fake_speed = max(0, fake_speed - (brake_strength * 4.8))
                else: fake_speed = max(0, fake_speed - 0.5)
            else:
                fake_speed = max(0, fake_speed - 2.0)

            # Render UI graphics over the processed camera feed background
            draw_hud_overlay(hud_display, wheel_img, angle, gas_strength, brake_strength, both_visible, fake_speed)
            cv2.imshow(win_name, hud_display)

            if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q'), 27):
                break
    finally:
        controller.release_all()
        hands.close()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()