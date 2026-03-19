import os
import sys
import tkinter as tk
from tkinter import ttk
import threading
from PIL import Image, ImageTk

def main():
    root = tk.Tk()
    root.title("OpenS Loading")
    
    # Hide title bar and window decorations
    root.overrideredirect(True)
    
    # Dimensions
    width = 340
    height = 280
    
    # Center on screen
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    
    # Styling
    root.configure(bg="#ffffff")
    
    # Label for Logo
    logo_label = tk.Label(root, bg="#ffffff")
    logo_label.pack(pady=(30, 10))
    
    # Load High-Resolution Logo with PIL
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "launcher.png")
    if os.path.exists(logo_path):
        try:
            img = Image.open(logo_path)
            # Resize with lanczos for high resolution scaling
            img = img.resize((120, 120), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            logo_label.configure(image=photo)
            logo_label.image = photo  # keep a reference
            
            # Set window icon
            root.iconphoto(True, photo)
        except Exception as e:
            print(f"Error loading logo: {e}", file=sys.stderr)
            tk.Label(root, text="OpenS", font=("Arial", 24, "bold"), bg="#ffffff").pack(pady=20)
    else:
        tk.Label(root, text="OpenS", font=("Arial", 24, "bold"), bg="#ffffff").pack(pady=20)

    # App Name
    name_label = tk.Label(root, text="OpenS", font=("Arial", 20, "bold"), bg="#ffffff", fg="#1f1f1f")
    name_label.pack()

    # Status Label
    status_label = tk.Label(root, text="Loading...", font=("Arial", 11), bg="#ffffff", fg="#444444")
    status_label.pack(pady=(10, 5))
    
    # Progress Bar
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("TProgressbar", thickness=8, troughcolor="#f0f0f0", background="#005A9C", borderwidth=0)
    progress = ttk.Progressbar(root, length=240, mode='determinate', style="TProgressbar")
    progress.pack(pady=10)
    progress['value'] = 0

    def listen_stdin():
        for line in sys.stdin:
            line = line.strip()
            if line.startswith("MSG:"):
                msg = line[4:]
                root.after(0, lambda m=msg: status_label.config(text=m))
            elif line.startswith("PROGRESS:"):
                try:
                    val = int(line[9:])
                    root.after(0, lambda v=val: progress.config(value=v))
                except ValueError:
                    pass
            elif line == "QUIT":
                root.after(0, root.destroy)
                break

    # Run stdin listener in a separate thread
    threading.Thread(target=listen_stdin, daemon=True).start()
    
    # Bring to front
    root.lift()
    root.attributes('-topmost', True)
    
    root.mainloop()

if __name__ == "__main__":
    main()
