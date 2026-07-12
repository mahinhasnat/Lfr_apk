[app]
title = LFR Track Analyzer
package.name = lfrtrackanalyzer
package.domain = org.lfrbot
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas
version = 0.1

# opencv-python-headless avoids pulling in Qt/GUI deps that don't build for Android.
# numpy/scikit-image/opencv are the heaviest part of this build — first build will
# take a while (image is compiled via python-for-android recipes).
requirements = python3,kivy==2.3.0,opencv-python-headless,numpy,scikit-image,plyer,usb4a,usbserial4a,pyjnius

orientation = portrait
fullscreen = 0

# USB host feature + permissions needed for OTG serial to the Arduino,
# plus storage/camera permissions for picking a photo.
android.permissions = USB_PERMISSION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,CAMERA
android.features = android.hardware.usb.host

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
