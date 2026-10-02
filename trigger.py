import os
import sys
import time
import socket
import subprocess

PROJECT_DIR = "/home/zen-anaxa/Projects/KianaAI"
PYTHON_BIN = os.path.join(PROJECT_DIR, "venv/bin/python")
HARRIS_SCRIPT = os.path.join(PROJECT_DIR, "harris.py")
SOCKET_PATH = "/tmp/harris.sock"

def send_trigger():
    """Mengirim sinyal panggil ke socket Harris"""
    if not os.path.exists(SOCKET_PATH):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(SOCKET_PATH)
        s.close()
        return True
    except Exception:
        return False

def main():
    # 1. Jika Harris sudah berjalan, langsung panggil!
    if send_trigger():
        print("[Trigger]: Harris sudah aktif, pemicu berhasil dikirim.")
        return

    # 2. Jika Harris belum aktif, jalankan harris.py secara independen di background
    print("[Trigger]: Harris belum berjalan. Menyalakan Harris di background...")
    subprocess.Popen(
        [PYTHON_BIN, HARRIS_SCRIPT],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    # 3. Tunggu hingga socket Harris siap (maksimal 5 detik), lalu panggil
    for _ in range(25):
        time.sleep(0.2)
        if send_trigger():
            print("[Trigger]: Harris berhasil dinyalakan dan dipanggil!")
            return

    print("[Trigger]: Gagal terhubung setelah menyalakan Harris.")

if __name__ == "__main__":
    main()
