[app]
title = LFR Track Analyzer
package.name = lfrtrackanalyzer
package.domain = org.lfrbot
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas
version = 0.1

requirements = python3,kivy==2.3.0,opencv,numpy,plyer,usb4a,usbserial4a,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = USB_PERMISSION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,CAMERA
android.features = android.hardware.usb.host

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

android.accept_sdk_license = True
android.build_tools_version = 34.0.0

[buildozer]
log_level = 2
warn_on_root = 1
