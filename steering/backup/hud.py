import tkinter as tk
from PIL import Image, ImageTk
import os

class HUD:
    def __init__(self):
        print("HUD A")
        self.root = tk.Tk()
        print("HUD B")

    def update(self, *args, **kwargs):
        pass

    def close(self):
        try:
            self.root.destroy()
        except:
            pass