import os
import re
import time
import gzip
import pickle
import traceback
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from send_mst import msg_fun, file_fun

MIRURO_WATCH_BASE = "https://www.miruro.to/watch"
PROGRESS_FILE = "progress.txt"
OUTPUT_DIR = "anime_bins"


# ---------- DRIVER ----------
def initialize_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    service = Service("chromedriver")
    return webdriver.Chrome(service=service, options=opts)


# ---------- PARSE EPISODE COUNT ----------
def get_total_episodes(driver):
    """Extract the maximum episode number from the dropdown if available."""
    try:
        select_elem = driver.find_element(By.CSS_SELECTOR, "select")
        options = select_elem.find_elements(By.TAG_NAME, "option")
        if not options:
            return 0

        max_ep = 0
        for opt in options:
            match = re.search(r"EPS\s+(\d+)\s*-\s*(\d+)", opt.text)
            if match:
                upper = int(match.group(2))
                if upper > max_ep:
                    max_ep = upper
        return max_ep
    except Exception:
        return 0


# ---------- VIDEO URL EXTRACT ----------
def extract_video_url(driver, max_presses=10):
    body = driver.find_element(By.TAG_NAME, "body")
    actions = ActionChains(driver)
    pattern = re.compile(r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)')
    for _ in range(max_presses):
        actions.move_to_element(body).click().send_keys("k").perform()
        time.sleep(0.8)
        html = driver.page_source
        match = pattern.search(html)
        if match:
            return match.group(0)
    return None


# ---------- EXTRACT ONE ANIME ----------
def extract_anime_urls(anime_id: int, driver):
    url = f"{MIRURO_WATCH_BASE}/{anime_id}"
    try:
        driver.get(url)
        # Wait for page to load properly (max 30 seconds)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except Exception:
        print(f"⚠️ Page for ID {anime_id} did not load. Skipping.")
        return None

    html = driver.page_source
    # If Miruro shows an invalid page
    if "404" in html or "not found" in html.lower():
        print(f"[SKIP] Miruro page for ID {anime_id} not found.")
        return None

    total_eps = get_total_episodes(driver)
    if total_eps == 0:
        print(f"[SKIP] No episode dropdown found for ID {anime_id}.")
        return None

    print(f"\n🎬 Miruro Anime ID {anime_id} — Detected {total_eps} episodes")

    episode_entries = []
    for ep in range(1, total_eps + 1):
        ep_url = f"{MIRURO_WATCH_BASE}/{anime_id}/episode-{ep}"
        try:
            driver.get(ep_url)
            time.sleep(1)
            vurl = extract_video_url(driver)
            if vurl:
                entry = f"ep_num_{ep}_url_data_{vurl}"
                episode_entries.append(entry)
                print(f"  ✅ {entry}")
            else:
                print(f"  ⚠️  Ep {ep}: No URL found")
        except Exception as e:
            print(f"  ❌ Ep {ep} error: {str(e)[:80]}")
    return episode_entries


# ---------- PROGRESS TRACKER ----------
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return 1


def save_progress(last_id: int):
    try:
        with open(PROGRESS_FILE, "w") as f:
            f.write(str(last_id))
        print(f"💾 Progress saved at ID {last_id}")
    except Exception as e:
        print(f"⚠️ Failed to save progress: {e}")


# ---------- MAIN ----------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    MAX_ID = int(os.getenv("MAX_ID", "30"))  # per GitHub run
    # START_ID = load_progress()
    START_ID = 153800
    # END_ID = START_ID + MAX_ID - 1
    END_ID = 153801
    msg_fun(f"🚀 Starting Miruro scrape: IDs {START_ID} → {END_ID}")

    driver = None
    current_id = START_ID

    try:
        driver = initialize_driver()

        for anime_id in range(START_ID, END_ID + 1):
            current_id = anime_id
            try:
                episode_data = extract_anime_urls(anime_id, driver)
                if not episode_data:
                    save_progress(anime_id)
                    continue

                combined_str = ",".join(episode_data)
                file_path = os.path.join(OUTPUT_DIR, f"anime_{anime_id}.bin")

                # Save as compressed binary
                with gzip.open(file_path, "wb") as f:
                    pickle.dump(combined_str, f)

                print(f"💾 Saved {file_path} ({len(episode_data)} entries)")

                try:
                    file_fun(file_path, caption=f"Anime ID {anime_id} ✅ ({len(episode_data)} eps)")
                except Exception as e:
                    print(f"⚠️ Telegram send failed for {anime_id}: {e}")

                save_progress(anime_id)
            except Exception as e:
                print(f"[ERROR] {anime_id}: {e}")
                traceback.print_exc()
                save_progress(anime_id)

            time.sleep(1)

    except Exception as e:
        print(f"💥 Fatal error: {e}")
        traceback.print_exc()
        msg_fun(f"❌ Fatal error at Anime ID {current_id}: {e}")

    finally:
        save_progress(current_id)
        if driver:
            try:
                driver.quit()
            except:
                pass
        msg_fun(f"🛑 Run ended. Last processed ID: {current_id}")


if __name__ == "__main__":
    main()
