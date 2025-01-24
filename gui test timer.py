import tkinter as tk

# THis stopwatch tkinter script is cobbled together with youtube and chat gpt. I haven't really made any interface scripts before
# so this is a practice run

# https://youtu.be/ibf5cx221hk


class TimerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Count-Up Timer")

        # Timer display
        self.time_label = tk.Label(root, text="00:00:00.00", font=("Verdana", 24)) # verdana goat
        self.time_label.pack(pady=20)

        # Start Stop buttons
        self.start_button = tk.Button(root, text="Start", command=self.start_timer, width=10)
        self.start_button.pack(side=tk.LEFT, padx=10)

        self.stop_button = tk.Button(root, text="Stop", command=self.stop_timer, width=10)
        self.stop_button.pack(side=tk.LEFT, padx=10)

        self.reset_button = tk.Button(root, text="Reset", command=self.reset_timer, width=10)
        self.reset_button.pack(side=tk.LEFT, padx=10)

        # Timer variables
        self.running = False
        self.start_time = 0
        self.elapsed_time = 0

    def update_timer(self):
        if self.running:

            self.elapsed_time += 0.01

            # Convert to h, m, s and cs
            hours = int(self.elapsed_time // 3600)
            minutes = int((self.elapsed_time % 3600) // 60)
            seconds = int(self.elapsed_time % 60)
            centiseconds = int((self.elapsed_time - int(self.elapsed_time)) * 100)

            # format
            self.time_label.config(text=f"{hours:02}:{minutes:02}:{seconds:02}.{centiseconds:02}")

            # hupdate
            self.root.after(10, self.update_timer)

    def start_timer(self):
        if not self.running:
            self.running = True
            self.update_timer()

    def stop_timer(self):
        self.running = False

    def reset_timer(self):
        self.running = False
        self.elapsed_time = 0
        self.time_label.config(text="00:00:00.00")


# Create the interface
root = tk.Tk()
app = TimerApp(root)
root.mainloop()
