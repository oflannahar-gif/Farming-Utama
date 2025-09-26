# farming_and_levelup.py — Auto Farming Grand Pirates (dengan Level Up Kapal)
# Features:
#   - Auto Restore Energi
#   - Auto Adventure / Fight
#   - Auto Level Up Kapal (Level Up Kapal + ATK)
#   - Limit Detect (pause jika capek limit server)
#   - Watchdog anti-stuck (cek setiap 20 detik)
#   - Pause/Resume via command "pause" / "resume"
# Requirements:
#   pip install telethon python-dotenv

import os
import re
import asyncio
import random
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ---------------- config (.env) ----------------
load_dotenv("token.env")
API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH") or ""
PHONE = os.getenv("PHONE") or ""
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "GrandPiratesBot").lstrip('@')
OWNER_ID = int(os.getenv("OWNER_ID") or 0)

if not API_ID or not API_HASH or not PHONE:
    raise SystemExit("ERROR: Pastikan API_ID, API_HASH, PHONE ter-set di file token.env")

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger("gp_bot")

# ---------------- client ----------------
SESSION_STRING = os.getenv("TELEGRAM_SESSION")
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient("gp_combo_session", API_ID, API_HASH)

# ---------------- state ----------------
attack_block_until = 0.0
last_event_time = 0.0
energy_threshold = 22
last_action = None
paused = False
need_refresh_ship = True
# State untuk Level Up Kapal
exp_current = 0
exp_max = None
leveling = False

# ---------------- regex ----------------
# Farming
energy_re = re.compile(r"Sisa energi:\s*(\d+)%", re.IGNORECASE)
limit_msg_re = re.compile(r"batas maksimal melawan musuh|Kamu sudah mencapai batas maksimal", re.IGNORECASE)
# Level Up Kapal
exp_progress_re = re.compile(r"EXP:\s*\(([\d,]+)\/([\d,]+)\)", re.IGNORECASE)
exp_gain_re = re.compile(r"❇️\s*([\d,]+)\s*EXP Kapal", re.IGNORECASE)

# ---------------- helpers ----------------
def parse_int(s: str) -> int:
    """Mengubah string angka dengan koma menjadi integer"""
    return int(s.replace(",", "").strip())

async def human_sleep(min_s=0.5, max_s=1.0):
    """Jeda waktu dengan variasi acak untuk meniru perilaku manusia"""
    await asyncio.sleep(random.uniform(min_s, max_s))

async def robust_click(event, label_text):
    """Klik tombol inline berdasarkan text, dengan upaya ganda jika gagal"""
    try:
        btns = await event.get_buttons()
        if not btns:
            return False
        flat = [b.text for row in btns for b in row if getattr(b, "text", None)]
        candidate = next((txt for txt in flat if label_text.lower() in txt.lower()), None)
        if not candidate:
            return False
        
        # Coba klik dengan text, lalu dengan index
        for attempt in range(1, 4):
            try:
                await human_sleep(0.4, 0.9)
                await event.click(text=candidate)
                return True
            except Exception:
                try:
                    idx = flat.index(candidate)
                    await human_sleep(0.3, 0.7)
                    await event.message.click(idx)
                    return True
                except Exception:
                    if attempt < 3:
                        await asyncio.sleep(0.5 + attempt * 0.3)
                        continue
                    else:
                        return False
    except Exception:
        return False
    return False

# ---------------- level up flow ----------------
async def start_levelup():
    """Mulai proses level up kapal"""
    global leveling
    if leveling:
        return
    leveling = True
    try:
        print(">> EXP FULL → Mulai level up kapal")
        await client.send_message(BOT_USERNAME, "/levelupKapal")
        print(">> Kirim /levelupKapal")
        await asyncio.sleep(4)
        await client.send_message(BOT_USERNAME, "/levelupKapal_ATK")
        print(">> Kirim /levelupKapal_ATK")
    except Exception as e:
        print("!! Gagal start levelup:", e)
        leveling = False

# ---------------- pause/resume ----------------
@client.on(events.NewMessage(from_users=OWNER_ID))
async def owner_control(event):
    """Menangani perintah pause/resume dari OWNER_ID"""
    global paused
    msg = (event.raw_text or "").strip().lower()
    if msg == "pause":
        paused = True
        await event.reply("⏸ Bot PAUSED (Farming & Level Up)")
        print(">> Bot paused oleh owner.")
    elif msg == "resume":
        paused = False
        await event.reply("▶️ Bot RESUMED (Farming & Level Up)")
        print(">> Bot resumed oleh owner.")

# ---------------- main handler ----------------
@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def handler(event):
    """Menangani semua pesan masuk dari bot Grand Pirates"""
    global last_event_time, last_action, attack_block_until, paused, need_refresh_ship
    global exp_current, exp_max, leveling

    if paused:
        print(">> (PAUSED) Pesan bot diabaikan.")
        return
    
    # Blokir aksi jika masih dalam periode limit server
    if attack_block_until and time.time() < attack_block_until and not leveling:
        print(">> (LIMIT BLOCK) Bot menunggu limit selesai.")
        return

    try:
        last_event_time = asyncio.get_event_loop().time()
        text = event.raw_text or ""
        lowered = text.lower()
        print("\n>> Pesan bot:")
        print(text[:1000])

        # Refresh kapal sekali di awal
        if need_refresh_ship:
            await asyncio.sleep(1)
            await client.send_message(BOT_USERNAME, "/kapal")
            need_refresh_ship = False
            return

        # ==========================================================
        # LOGIKA LEVEL UP KAPAL
        # ==========================================================
        
        # Deteksi pesan konfirmasi level up
        if "apa kamu yakin ingin meningkatkan" in lowered and "kapal" in lowered:
            print(">> Deteksi pesan konfirmasi level up!")
            start = asyncio.get_event_loop().time()

            while leveling:  # hanya jalan selama proses leveling
                # Coba klik tombol confirm/yes
                if await robust_click(event, "confirm") or await robust_click(event, "yes"):
                    print(">> Klik Confirm dikirim, tunggu balasan...")
        
                await asyncio.sleep(3)

                # Cek timeout 5 menit
                if asyncio.get_event_loop().time() - start > 300:
                    print("!! Timeout 5 menit, kirim ulang /levelupKapal_ATK")
                    await client.send_message(BOT_USERNAME, "/levelupKapal_ATK")
                    start = asyncio.get_event_loop().time()  # reset timer

                # Jika bot sudah kirim pesan sukses, keluar dari loop (supaya tidak spam)
                if "berhasil meningkatkan level kapal" in lowered or "berhasil meningkatkan level" in lowered:
                    print(">> Level up kapal sukses terdeteksi (break loop)!")
                    break

        # Levelup sukses
        if "berhasil meningkatkan level" in lowered:
            print(">> LEVEL UP BERHASIL!")
            exp_current = 0
            exp_max = None
            leveling = False   # reset flag leveling
            await asyncio.sleep(4)
            await client.send_message(BOT_USERNAME, "/kapal")
            print(">> Kirim /kapal untuk refresh status")
            await asyncio.sleep(3)
            # Lanjut ke farming dengan kirim /adventure
            await client.send_message(BOT_USERNAME, "/adventure")
            return

        # EXP progress
        m_exp = exp_progress_re.search(text)
        if m_exp:
            exp_current = parse_int(m_exp.group(1))
            exp_max = parse_int(m_exp.group(2))
            print(f">> EXP Kapal: {exp_current}/{exp_max}")
            if exp_max and exp_current >= exp_max and not leveling:
                await start_levelup()
            return

        # ==========================================================
        # LOGIKA FARMING
        # ==========================================================
        
        if leveling:  # Jika sedang leveling, skip farming
            return

        # Detect server limit
        if limit_msg_re.search(text):
            now = time.time()
            next_hour = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)
            attack_block_until = now + (next_hour - datetime.now()).total_seconds()
            print(f">> DETECTED limit, farming pause hingga {datetime.fromtimestamp(attack_block_until).strftime('%H:%M:%S')}.")
            return

        # Energi restore
        m_en = energy_re.search(text)
        if m_en:
            energy = int(m_en.group(1))
            print(f">> Energi: {energy}%")
            if energy <= energy_threshold and last_action != "restore_sent":
                await asyncio.sleep(0.6)
                await client.send_message(BOT_USERNAME, "/restore_x")
                last_action = "restore_sent"
                print(">> Energi kurang, kirim /restore_x")
                return

        if last_action == "restore_sent" and "berhasil memulihkan energi" in lowered:
            await asyncio.sleep(0.8)
            await client.send_message(BOT_USERNAME, "/adventure")
            last_action = None
            print(">> Energi pulih, kirim /adventure")
            return

        # EXP gain - update exp_current, lalu cek jika full
        m_gain = exp_gain_re.search(text)
        if m_gain:
            gain = parse_int(m_gain.group(1))
            exp_current += gain
            if exp_max:
                exp_current = min(exp_current, exp_max)
                print(f">> +{gain} EXP → {exp_current}/{exp_max}")
                if exp_current >= exp_max and not leveling:
                    await start_levelup()
            else:
                print(f">> +{gain} EXP (sementara)")

        # Auto fight / telusuri
        if "dihadang" in lowered and "musuh" in lowered:
            await robust_click(event, "Lawan")
            print(">> Dihadang musuh, klik Lawan")
            return

        if "kamu menang" in lowered or "telusuri" in lowered or "gagal" in lowered:
            if await robust_click(event, "Telusuri") or await robust_click(event, "Adventure"):
                print(">> Menang/Pesan umum, klik Telusuri/Adventure")
                return
            else:
                await client.send_message(BOT_USERNAME, "/adventure")
                print(">> Fallback: kirim /adventure")
                return

        # Fallback click
        buttons = await event.get_buttons()
        if buttons:
            for kw in ("telusuri", "adventure"):
                if await robust_click(event, kw):
                    print(f">> Fallback click: klik {kw}")
                    return

    except Exception as e:
        logger.exception("Handler error: %s", e)

# ---------------- watchdog ----------------
async def watchdog():
    """Mencegah bot stuck dengan mengirim /adventure secara berkala jika tidak ada aktivitas"""
    global last_event_time, attack_block_until, paused
    while True:
        await asyncio.sleep(20)
        
        if paused or leveling:  # pause atau leveling → skip
            continue
            
        if attack_block_until and time.time() < attack_block_until:  # limit server → skip
            continue
            
        if asyncio.get_event_loop().time() - last_event_time > 15:
            try:
                await client.send_message(BOT_USERNAME, "/adventure")
                print(">> WATCHDOG: sent /adventure")
            except Exception as e:
                print("!! WATCHDOG gagal /adventure:", e)

# ---------------- startup ----------------
async def main():
    await client.start(phone=PHONE)
    logger.info("Client started")
    await asyncio.sleep(1)
    
    await client.send_message(BOT_USERNAME, "/kapal")  # init state
    client.loop.create_task(watchdog())
    print(f">> Bot siap FARMING & LEVEL UP di @{BOT_USERNAME}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        while True:
            try:
                asyncio.run(main())
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print("!! Crash, restart 5s:", e)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Exiting.")
