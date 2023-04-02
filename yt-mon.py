import subprocess
import sys
import threading
from typing import List, TypedDict
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime, timedelta


Id = str
Time = datetime
Title = str
Url = str

class Entry(TypedDict):
    time: Title
    title: Title
    url: Url

class Task(TypedDict):
    id: Id
    entry: Entry
    thread: threading.Thread
    event: threading.Event

class Record(TypedDict):
    id: Id
    rss_url: Url
    last_time: Time
    tasks: List[Task]


def construct_playlist_rss_url(id: Id) -> Url:
    return f"https://www.youtube.com/feeds/videos.xml?playlist_id={id}"

def construct_channel_rss_url(id: Id) -> Url:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={id}"

def construct_user_url(id: Id) -> Url:
    return f"https://www.youtube.com/user/{id}"

def construct_short_url(id: Id) -> Url:
    return f"https://www.youtube.com/{id}"

def get_channel_id_from_url(url: Url) -> Id:
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    for elem in soup.find_all('script', string=True):
        prefix = 'var ytInitialData = '
        suffix = ';'
        text = elem.contents[0].strip()
        if text.startswith(prefix):
            json_text = text.removeprefix(prefix).removesuffix(suffix)
            ytInitialData = json.loads(json_text)
            for obj in ytInitialData['responseContext']['serviceTrackingParams']:
                if obj['service'] == 'GOOGLE_HELP':
                    for param in obj['params']:
                        if param['key'] == 'browse_id':
                            return param['value']
    raise RuntimeError(f"Failed to extract channel ID from {url}")

def get_rss_url(id: Id) -> Url:
    # Try for a channel ID or a playlist ID as is
    for url in construct_channel_rss_url(id), construct_playlist_rss_url(id):
        if requests.head(url).status_code == 200:
            return url

    # Extract a channel ID from a channel web page
    for url in construct_short_url(id), construct_user_url(id):
        try:
            if requests.head(url).status_code == 200:
                url = construct_channel_rss_url(get_channel_id_from_url(url))
                requests.head(url).raise_for_status()
                return url
        except:
            continue

    return None

def parse_time(time_str: str) -> Time:
    return datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S%z')

def format_time(t: Time) -> str:
    return t.astimezone().strftime('%d.%m.%Y %H:%M:%S')

def get_expire_time(t: Time) -> Time:
    return t - timedelta(days=2)

def sleep(seconds: float):
    time.sleep(seconds)

def parse_rss_entries(rss_url: Url) -> List[Entry]:
    retries = 20
    for retry in range(retries):
        try:
            response = requests.get(rss_url)
            break
        except requests.RequestException as e:
            print(e)
            print(f"retrying {retry + 1} of {retries}")
            sleep(1)
    else:
        raise RuntimeError(f"Failed to get {rss_url}")
    
    response.raise_for_status()
    entries: List[Entry] = []
    # Collect all entries
    for entry_node in BeautifulSoup(response.content, "xml").find_all('entry'):
        title = entry_node.find('title').get_text()
        url = entry_node.find('link').get('href')
        time = parse_time(entry_node.find('published').get_text())
        entries.append({ 'time': time, 'title': title, 'url': url })
    # Sort entries by the time ascending
    entries.sort(key=lambda entry: entry['time'])
    return entries

def download_thread_func(task: Task):
    cmd_argv = ['yt-dlp', '--live-from-start', '--wait-for-video', '10-300', task['entry']['url']]
    # Retry until success
    exit_code = 1
    while exit_code:
        # Run the process in a separate window
        process = subprocess.Popen(cmd_argv, creationflags=subprocess.DETACHED_PROCESS)
        while not task['event'].is_set():
            # Wait for process stopped
            try:
                exit_code = process.wait(1)
                break
            except subprocess.TimeoutExpired:
                pass
        else:
            # Got event signal to stop
            break

def main():
    if len(sys.argv) < 2:
        raise RuntimeError('Need at leat 1 argument')

    records: List[Record] = []

    # Collect IDs from input files
    for file_path in sys.argv[1:]:
        try:
            file = open(file_path, 'r')
        except OSError as e:
            print(e)
            continue
        except:
            print(f"{file_path} open error")
            continue

        with file:
            for id in file:
                id = id.strip()
                if not id:
                    continue

                # Check for a duplicate
                for record in records:
                    if id == record['id']:
                        continue

                rss_url = get_rss_url(id)
                print(f"{id}: {rss_url}")
                if not rss_url:
                    continue

                entries = parse_rss_entries(rss_url)
                last_time = None
                if entries:
                    last = entries[-1]
                    last_time = last['time']
                    print(f"    {format_time(last_time)} {last['title']}")
                else:
                    print('    <no data>')

                records.append({ 'id': id, 'rss_url': rss_url, 'last_time': last_time, 'tasks': [] })

    # Monitor records in the loop
    print('------------------------------------------')
    try:
        while True:
            time.sleep(60)
            for record in records:
                # Clear expired tasks
                last_time = record['last_time']
                expire_time = get_expire_time(last_time)
                record['tasks'] = list(filter(lambda task: task['entry']['time'] > expire_time or task['thread'].is_alive(), record['tasks']))

                # Get all current entries
                new_entries = parse_rss_entries(record['rss_url'])
                if not new_entries:
                    # No entries at all
                    continue

                # Update last time
                record['last_time'] = new_entries[-1]['time']
                if last_time:
                    # Get only newer entries
                    new_entries = filter(lambda entry: entry['time'] > last_time, new_entries)

                # Process all new entries
                for entry in new_entries:
                    for task in record['tasks']:
                        if entry['url'] == task['entry']['url']:
                            # Skip already processed entries
                            break
                    else:
                        id = record['id']
                        url = entry['url']
                        print(f"{format_time(entry['time'])} | {id} | {entry['title']} | {url}")

                        task: Task = { 'id': id, 'entry': entry, 'thread': None, 'event': threading.Event() }
                        thread = threading.Thread(target=download_thread_func, args=(task,))
                        task['thread'] = thread
                        thread.start()
                        record['tasks'].append(task)

    except KeyboardInterrupt as e:
        # Stop download tasks
        for record in records:
            for task in record['tasks']:
                task['event'].set()
                task['thread'].join()
        print('Terminated by Ctrl-C')


if __name__ == '__main__':
    main()
