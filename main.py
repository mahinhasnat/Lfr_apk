"""
LFR Track Analyzer — mobile app (Kivy)
========================================
Same analysis pipeline as the PC script (track_core.py), wrapped in a
touch UI: pick a photo -> analyze -> view result -> send to Arduino over
USB-OTG.

Runs on desktop too (for quick testing with `python main.py`), but the
USB-OTG send button only works on an actual Android device with a cable/
adapter into the Arduino, since that path uses Android's USB host APIs
(usb4a / usbserial4a) which don't exist on desktop.
"""

import os
import threading

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.utils import platform

import track_core as tc

LABEL_COLORS = {"STRAIGHT": (0.2, 0.8, 0.2, 1),
                "CURVE": (0.9, 0.75, 0.1, 1),
                "SHARP": (0.9, 0.2, 0.2, 1)}


class MainLayout(BoxLayout):
    pass


class LFRApp(App):
    def build(self):
        self.title = "LFR Track Analyzer"
        self.selected_path = None
        self.profile = None

        root = BoxLayout(orientation="vertical", padding=10, spacing=10)

        self.status_label = Label(text="Pick a track photo to begin.",
                                   size_hint=(1, 0.08))
        root.add_widget(self.status_label)

        self.preview = Image(size_hint=(1, 0.45))
        root.add_widget(self.preview)

        results_scroll = ScrollView(size_hint=(1, 0.25))
        self.results_box = BoxLayout(orientation="vertical", size_hint_y=None)
        self.results_box.bind(minimum_height=self.results_box.setter("height"))
        results_scroll.add_widget(self.results_box)
        root.add_widget(results_scroll)

        btn_row1 = BoxLayout(size_hint=(1, 0.1), spacing=10)
        pick_btn = Button(text="Pick Photo")
        pick_btn.bind(on_release=self.open_file_chooser)
        analyze_btn = Button(text="Analyze")
        analyze_btn.bind(on_release=self.run_analysis)
        btn_row1.add_widget(pick_btn)
        btn_row1.add_widget(analyze_btn)
        root.add_widget(btn_row1)

        btn_row2 = BoxLayout(size_hint=(1, 0.1), spacing=10)
        self.send_btn = Button(text="Send to Arduino (USB)")
        self.send_btn.bind(on_release=self.send_to_arduino)
        btn_row2.add_widget(self.send_btn)
        root.add_widget(btn_row2)

        return root

    # ── file picking ─────────────────────────────────────────────────────
    def open_file_chooser(self, *_):
        if platform == "android":
            self._open_android_photo_picker()
        else:
            self._open_desktop_file_chooser()

    def _open_desktop_file_chooser(self):
        chooser = FileChooserIconView(path=os.path.expanduser("~"),
                                       filters=["*.jpg", "*.jpeg", "*.png"])
        popup = Popup(title="Pick a track photo", content=chooser, size_hint=(0.9, 0.9))

        def choose(_, selection, __):
            if selection:
                self.selected_path = selection[0]
                self.status_label.text = f"Selected: {os.path.basename(self.selected_path)}"
                self.preview.source = self.selected_path
                self.preview.reload()
            popup.dismiss()

        chooser.bind(on_submit=choose)
        popup.open()

    def _open_android_photo_picker(self):
        # plyer's filechooser uses Android's native picker (SAF) and copies
        # the result to a private-storage path we can hand to OpenCV.
        from plyer import filechooser

        def handle_selection(selection):
            if not selection:
                return
            self.selected_path = selection[0]
            Clock.schedule_once(lambda dt: self._on_android_pick_done())

        filechooser.open_file(on_selection=handle_selection,
                               filters=["*.jpg", "*.jpeg", "*.png"])

    def _on_android_pick_done(self):
        self.status_label.text = f"Selected: {os.path.basename(self.selected_path)}"
        self.preview.source = self.selected_path
        self.preview.reload()

    # ── analysis ─────────────────────────────────────────────────────────
    def run_analysis(self, *_):
        if not self.selected_path:
            self.status_label.text = "Pick a photo first."
            return
        self.status_label.text = "Analyzing..."
        threading.Thread(target=self._analyze_worker, daemon=True).start()

    def _analyze_worker(self):
        try:
            img, path, labels, profile = tc.analyze(self.selected_path)
            out_dir = self.user_data_dir
            vis_path = os.path.join(out_dir, "photo_analyzed.jpg")
            header_path = os.path.join(out_dir, "track_profile.h")
            tc.draw_visualization(img, path, labels, vis_path)
            tc.write_header(profile, header_path)
            self.profile = profile
            Clock.schedule_once(lambda dt: self._on_analysis_done(vis_path))
        except SystemExit:
            Clock.schedule_once(lambda dt: self._set_status(
                "No line detected — check lighting/crop and try again."))
        except Exception as e:
            msg = str(e)
            Clock.schedule_once(lambda dt: self._set_status(f"Error: {msg}"))

    def _set_status(self, text):
        self.status_label.text = text

    def _on_analysis_done(self, vis_path):
        self.status_label.text = f"Done — {len(self.profile)} segments detected."
        self.preview.source = vis_path
        self.preview.reload()
        self.results_box.clear_widgets()
        for seg in self.profile:
            row = Label(text=f"{seg['label']:<9}  {seg['pct']:5.1f}%   speed={seg['speed']}",
                        color=LABEL_COLORS.get(seg["label"], (1, 1, 1, 1)),
                        size_hint_y=None, height=28)
            self.results_box.add_widget(row)

    # ── USB send (Android only) ─────────────────────────────────────────
    def send_to_arduino(self, *_):
        if not self.profile:
            self.status_label.text = "Analyze a photo first."
            return
        if platform != "android":
            self.status_label.text = "USB-OTG send only works on an Android device."
            return
        self.status_label.text = "Connecting over USB..."
        threading.Thread(target=self._send_worker, daemon=True).start()

    def _send_worker(self):
        try:
            from usb4a import usb
            from usbserial4a import serial4a

            device_list = usb.get_usb_device_list()
            if not device_list:
                Clock.schedule_once(lambda dt: self._set_status(
                    "No USB device found — check the OTG cable/adapter."))
                return

            device = device_list[0]  # first device found; refine if you have more than one
            port_name = device.getDeviceName()
            serial_port = serial4a.get_serial_port(port_name, 115200, 8, 1, "N")

            import time
            time.sleep(2)  # allow Arduino reset after port opens

            def send_line(s):
                serial_port.write((s + "\n").encode("utf-8"))
                time.sleep(0.05)
                resp = serial_port.read(64)
                return resp.decode("utf-8", errors="replace").strip() if resp else ""

            send_line(f"COUNT,{len(self.profile)}")
            for p in self.profile:
                send_line(f"{p['type']},{p['speed']},{p['pct']:.2f}")
            resp = send_line("DONE")

            serial_port.close()
            Clock.schedule_once(lambda dt: self._set_status(
                f"Sent to Arduino. Reply: '{resp}'"))
        except Exception as e:
            msg = str(e)
            Clock.schedule_once(lambda dt: self._set_status(f"USB send failed: {msg}"))


if __name__ == "__main__":
    LFRApp().run()
