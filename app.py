import os
import re
import time
import gzip
import pickle
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
DEBUG_DIR = "debug_dumps"

# Enable testing mode (True = capture screenshots and HTML on failure)
TESTING_FLAG = False

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
    """Extract maximum episode number from the new Miruro layout."""
    try:
        # Target the new div class that holds the select dropdown
        container = driver.find_element(By.CSS_SELECTOR, "div.c1hiac3k select")
        options = container.find_elements(By.TAG_NAME, "option")

        if not options:
            return 0

        max_ep = 0
        for opt in options:
            text = opt.text.strip()
            # Matches things like "EPS 1 - 74" or "Ep 1 - 24"
            match = re.search(r"(\d+)\s*-\s*(\d+)", text)
            if match:
                upper = int(match.group(2))
                if upper > max_ep:
                    max_ep = upper

        return max_ep
    except Exception as e:
        print(f"⚠️ Failed to get total episodes: {e}")
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


# ---------- SAVE DEBUG DATA ----------
def save_debug_snapshot(driver, anime_id, error_text="Unknown Error"):
    """Saves a screenshot and HTML dump for debugging and sends them via Telegram."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        screenshot_path = os.path.join(DEBUG_DIR, f"animeid_{anime_id}.png")
        html_path = os.path.join(DEBUG_DIR, f"animeid_{anime_id}.html")

        # Save screenshot and page source
        driver.save_screenshot(screenshot_path)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        # Send to Telegram if testing mode
        caption = f"⚠️ Debug dump for Anime ID {anime_id}\nReason: {error_text}"
        file_fun(screenshot_path, caption=caption)
        file_fun(html_path, caption=f"🧩 HTML dump for Anime ID {anime_id}")

        print(f"🧩 Debug files saved and sent for Anime ID {anime_id}")
    except Exception as e:
        print(f"⚠️ Failed to save/send debug dump for ID {anime_id}: {e}")


# ---------- THREAD-SAFE EPISODE FETCH ----------
driver_lock = threading.Lock()

def fetch_episode_threadsafe(ep, anime_id, driver):
    """Thread-safe episode fetch using a shared driver."""
    with driver_lock:
        try:
            ep_url = f"{MIRURO_WATCH_BASE}/{anime_id}/episode-{ep}"
            driver.get(ep_url)
            time.sleep(1)
            vurl = extract_video_url(driver)
            if vurl:
                return f"ep_num_{ep}_url_data_{vurl}"
            else:
                print(f"  ⚠️ Ep {ep}: No URL found")
                return None
        except Exception as e:
            print(f"  ❌ Ep {ep} error: {str(e)[:80]}")
            if TESTING_FLAG:
                save_debug_snapshot(driver, anime_id, f"Episode {ep} error: {e}")
            return None


# ---------- EXTRACT ONE ANIME ----------
def extract_anime_urls(anime_id: int, driver):
    url = f"{MIRURO_WATCH_BASE}/{anime_id}"
    try:
        driver.get(url)
        # Wait until page body loads
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except Exception as e:
        print(f"⚠️ Page for ID {anime_id} did not load. Skipping.")
        if TESTING_FLAG:
            save_debug_snapshot(driver, anime_id, f"Page load failed: {e}")
        return None

    # --- Step 1: Validate by .ep-title ---
    try:
        # Wait a bit for Miruro JS to populate
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ep-title"))
        )
        title_elem = driver.find_element(By.CSS_SELECTOR, ".ep-title")
        title_text = title_elem.text.strip()
    except Exception:
        title_text = ""

    if not title_text:
        print(f"[SKIP] Invalid Miruro page (no title) for ID {anime_id}.")
        if TESTING_FLAG:
            save_debug_snapshot(driver, anime_id, "No .ep-title element or empty title")
        return None

    print(f"🎬 Anime ID {anime_id} — Title: {title_text}")

    # --- Step 2: Get total episode count ---
    total_eps = get_total_episodes(driver)
    if total_eps == 0:
        print(f"[SKIP] No episode dropdown found for ID {anime_id}.")
        if TESTING_FLAG:
            save_debug_snapshot(driver, anime_id, "No episode dropdown found")
        return None

    print(f"📺 Detected {total_eps} episodes for '{title_text}'")

    # --- Step 3: Extract each episode URL (multi-threaded with one driver) ---
    episode_entries = []
    MAX_THREADS = 10  # run up to 10 episodes in parallel (shared driver, safe)

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(fetch_episode_threadsafe, ep, anime_id, driver): ep for ep in range(1, total_eps + 1)}
        for future in as_completed(futures):
            ep = futures[future]
            try:
                result = future.result()
                if result:
                    episode_entries.append(result)
                    print(f"  ✅ Ep {ep} done")
            except Exception as e:
                print(f"  ❌ Thread error on Ep {ep}: {e}")

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

    last_saved_id = load_progress()
    START_ID = last_saved_id + 1
    END_ID = START_ID + MAX_ID - 1  # process MAX_ID entries per run

    msg_fun(f"🚀 Starting Miruro scrape: IDs {START_ID} → {END_ID}")

    driver = None
    current_id = START_ID

    try:
        driver = initialize_driver()

        for anime_id in range(START_ID, END_ID + 1):
            current_id = anime_id
            try:
                # Measure time taken per anime
                start_time = time.time()
                episode_data = extract_anime_urls(anime_id, driver)
                elapsed_time = time.time() - start_time

                if not episode_data:
                    save_progress(anime_id)
                    continue

                combined_str = ",".join(episode_data)

                # Format time — e.g., 12.3s or 1m23s
                if elapsed_time < 60:
                    elapsed_label = f"{elapsed_time:.1f}s"
                else:
                    mins, secs = divmod(int(elapsed_time), 60)
                    elapsed_label = f"{mins}m{secs}s"

                file_path = os.path.join(OUTPUT_DIR, f"anime_{anime_id}_{elapsed_label}.bin")

                # 🔄 If older bin exists for same anime_id, delete it
                for f in os.listdir(OUTPUT_DIR):
                    if f.startswith(f"anime_{anime_id}_") and f.endswith(".bin"):
                        os.remove(os.path.join(OUTPUT_DIR, f))

                # Save as compressed binary
                with gzip.open(file_path, "wb") as f:
                    pickle.dump(combined_str, f)

                print(f"💾 Saved {file_path} ({len(episode_data)} entries, took {elapsed_label})")

                try:
                    file_fun(file_path, caption=f"Anime ID {anime_id} ✅ ({len(episode_data)} eps, {elapsed_label})")
                except Exception as e:
                    print(f"⚠️ Telegram send failed for {anime_id}: {e}")

                # ✅ Save progress after each anime
                save_progress(anime_id)

            except Exception as e:
                print(f"[ERROR] {anime_id}: {e}")
                traceback.print_exc()
                if TESTING_FLAG:
                    save_debug_snapshot(driver, anime_id, f"Top-level scrape error: {e}")
                save_progress(anime_id)

            time.sleep(1)

    except Exception as e:
        print(f"💥 Fatal error: {e}")
        traceback.print_exc()
        msg_fun(f"❌ Fatal error at Anime ID {current_id}: {e}")
        if TESTING_FLAG and driver:
            save_debug_snapshot(driver, current_id, f"Fatal crash: {e}")

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
