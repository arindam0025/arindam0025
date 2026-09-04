import urllib.request
import json

# Fetch user profile
req = urllib.request.Request("https://api.github.com/users/arindam0025", headers={"User-Agent": "Mozilla/5.0"})
user_data = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
print("Public profile:", user_data.get("login"), "Repos:", user_data.get("public_repos"), "Followers:", user_data.get("followers"))

# Fetch public repos
req_repos = urllib.request.Request("https://api.github.com/users/arindam0025/repos?per_page=100", headers={"User-Agent": "Mozilla/5.0"})
repos = json.loads(urllib.request.urlopen(req_repos).read().decode("utf-8"))
print("Public repos count fetched:", len(repos))
total_stars = sum(r.get("stargazers_count", 0) for r in repos)
print("Total stars:", total_stars)
languages = {}
for r in repos:
    lang = r.get("language")
    if lang:
        languages[lang] = languages.get(lang, 0) + 1
print("Languages by repo count:", languages)
