import sys
import requests
from bs4 import BeautifulSoup
import json


def construct_playlist_rss_url(id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?playlist_id={id}"

def construct_channel_rss_url(id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={id}"

def construct_user_url(id: str) -> str:
    return f"https://www.youtube.com/user/{id}"

def construct_short_url(id: str) -> str:
    return f"https://www.youtube.com/{id}"

def get_channel_id_from_url(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    for elem in soup.find_all('script', string=True):
        prefix = 'var ytInitialData = '
        suffix = ';'
        text = elem.contents[0].strip()
        if (text.startswith(prefix)):
            json_text = text.removeprefix(prefix).removesuffix(suffix)
            ytInitialData = json.loads(json_text)
            for obj in ytInitialData['responseContext']['serviceTrackingParams']:
                if obj['service'] == 'GOOGLE_HELP':
                    for param in obj['params']:
                        if (param['key'] == 'browse_id'):
                            return param['value']
    raise RuntimeError(f"Failed to extract channel ID from {url}")

def get_rss_url(id: str) -> str:
    # Try for a channel ID or a playlist ID as is
    for url in construct_channel_rss_url(id), construct_playlist_rss_url(id):
        if (requests.head(url).status_code == 200):
            return url

    # Extract a channel ID from a channel web page
    for url in construct_short_url(id), construct_user_url(id):
        try:
            if (requests.head(url).status_code == 200):
                url = construct_channel_rss_url(get_channel_id_from_url(url))
                requests.head(url).raise_for_status()
                return url
        except:
            continue

    return None


def main():
    if (len(sys.argv) < 2):
        sys.exit('Need at leat 1 argument')

    for file_path in sys.argv[1:]:
        print(f"{file_path}")
        with open(file_path) as file:
            for id in file:
                id = id.strip()
                if (len(id)):
                    rss_url = get_rss_url(id)
                    print(f"    {id}: {rss_url}")
    

if __name__ == '__main__':
    main()