import subprocess
import sys
import time
import requests # Pastikan ini ada di requirements.txt jika bot main Anda juga pakai requests
import threading

BOT_SCRIPT = 'bot.py'
KEEPALIVE_URL = "https://api.ipify.org" # Ganti dengan URL yang Anda inginkan
KEEPALIVE_INTERVAL = 60 * 5 # Ping setiap 5 menit (300 detik)

def keep_alive_task():
    """Fungsi untuk melakukan ping secara berkala."""
    while True:
        try:
            response = requests.get(KEEPALIVE_URL, timeout=10) # Timeout agar tidak terblokir lama
            # print(f"Keep-alive ping sent. Status: {response.status_code}") # Opsional: log ping
        except requests.exceptions.RequestException as e:
            print(f"Keep-alive ping failed: {e}")
        time.sleep(KEEPALIVE_INTERVAL)

def run_bot_process():
    """Meluncurkan dan memantau proses bot utama."""
    print(f"🚀 Starting {BOT_SCRIPT} process...")
    process = subprocess.Popen([sys.executable, BOT_SCRIPT])
    process.wait() # Tunggu sampai bot berhenti
    return process.returncode

if __name__ == "__main__":
    print("✨ Bot Supervisor initialized.")

    # Mulai thread keep-alive di latar belakang
    # 'daemon=True' artinya thread ini akan otomatis berhenti jika program utama selesai
    keep_alive_thread = threading.Thread(target=keep_alive_task, daemon=True)
    keep_alive_thread.start()
    print(f"💓 Keep-alive thread started. Pinging {KEEPALIVE_URL} every {KEEPALIVE_INTERVAL} seconds.")

    print("🔄 Entering bot restart loop...")
    while True:
        return_code = run_bot_process()
        if return_code == 0:
            print(f"✅ {BOT_SCRIPT} exited cleanly. Not restarting.")
            break
        else:
            print(f"💥 {BOT_SCRIPT} crashed with exit code {return_code}. Restarting in 10 seconds...")
            time.sleep(10)

