"""Check CI YAML for encoding issues."""
import sys, base64, json, urllib.request, os

# Get the file from GitHub API
token = os.environ.get("GH_TOKEN", "")
headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
req = urllib.request.Request(
    "https://api.github.com/repos/papayasamosa/Forecasting-Tool/contents/.github/workflows/ci.yml",
    headers=headers,
)
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
content = base64.b64decode(data["content"])

print(f"Total bytes: {len(content)}")
print(f"First 20 bytes hex: {content[:20].hex()}")

# Check for non-ASCII
for i, b in enumerate(content):
    if b > 127:
        print(f"Non-ASCII at byte {i}: 0x{b:02x}")

# Check for null bytes
nulls = [i for i, b in enumerate(content) if b == 0]
if nulls:
    print(f"Null bytes at positions: {nulls[:20]}")
else:
    print("No null bytes found")

# Check for BOM
if content[:3] == b'\xef\xbb\xbf':
    print("UTF-8 BOM detected at start")
elif content[:2] == b'\xff\xfe':
    print("UTF-16 LE BOM detected at start")
elif content[:2] == b'\xfe\xff':
    print("UTF-16 BE BOM detected at start")
else:
    print("No BOM detected")

# Parse as YAML
try:
    import yaml
    parsed = yaml.safe_load(content)
    print("YAML is valid")
    print(f"Keys: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
    if isinstance(parsed, dict) and "jobs" in parsed:
        print(f"Jobs: {list(parsed['jobs'].keys())}")
        for jname, jbody in parsed["jobs"].items():
            if isinstance(jbody, dict) and "steps" in jbody:
                print(f"  Job '{jname}' has {len(jbody['steps'])} steps")
                for s in jbody["steps"]:
                    if isinstance(s, dict):
                        print(f"    - {s.get('name', 'unnamed')}")
except Exception as e:
    print(f"YAML error: {e}")
