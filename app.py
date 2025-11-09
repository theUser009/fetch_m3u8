import os
import re
import time
import gzip
import pickle
import traceback
import requests
from send_mst import msg_fun, file_fun
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

ANILIST_URL = "https://graphql.anilist.co"
MIRURO_WATCH_BASE = "https://www.miruro.to/watch"
PROGRESS_FILE = "progress.txt"
OUTPUT_DIR = "anime_bins"


# ---------- FETCH ANILIST DATA ----------
def fetch_anime_details(anime_id: int):
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        title {
          romaji
          english
        }
        episodes
      }
    }
    """
    try:
        r = requests.post(ANILIST_URL, json={"query": query, "variables": {"id": anime_id}}, timeout=10)
        r.raise_for_status()
        return r.json().get("data", {}).get("Media")
    except Exception as e:
        print(f"⚠️ AniList fetch error for {anime_id}: {e}")
        return None


# ---------- DRIVER ----------
def initialize_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    service = Service("chromedriver")
    return webdriver.Chrome(service=service, options=opts)


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
    anime = fetch_anime_details(anime_id)
    if not anime:
        print(f"[SKIP] AniList ID {anime_id} not found.")
        return None

    title = anime["title"].get("romaji") or anime["title"].get("english") or f"Anime {anime_id}"
    total_eps = anime.get("episodes") or 12

    print(f"\n🎬 {title} (ID: {anime_id}) - {total_eps} eps")

    episode_entries = []
    for ep in range(153800, total_eps + 1):
        url = f"{MIRURO_WATCH_BASE}/{anime_id}/episode-{ep}"
        try:
            driver.get(url)
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
    MAX_ID = int(os.getenv("MAX_ID", "50"))  # per GitHub run
    START_ID = load_progress()
    END_ID = START_ID + MAX_ID - 1

    msg_fun(f"🚀 Starting scrape: IDs {START_ID} → {END_ID}")

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

                # Send to Telegram bot
                try:
                    file_fun(file_path, caption=f"Anime ID {anime_id} ✅ ({len(episode_data)} eps)")
                except Exception as e:
                    print(f"⚠️ Telegram send failed for {anime_id}: {e}")

                # Update progress immediately
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
        # Always save progress even if crash or timeout
        save_progress(current_id)

        # Gracefully close browser
        if driver:
            try:
                driver.quit()
            except:
                pass

        msg_fun(f"🛑 Run ended. Last processed ID: {current_id}")


if __name__ == "__main__":
    main()
