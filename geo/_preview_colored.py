"""
Preview colored China map with epicenter (*) and monitoring point (@).
Usage:
  python geo/_preview_colored.py
  python geo/_preview_colored.py 103.4 31.0       # epicenter lon lat
"""
import json, os, sys
import gj2ascii
from rich.console import Console
from rich.text import Text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo.geo_ascii import lonlat_to_rc

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
console = Console()

EPI_LON = float(sys.argv[1]) if len(sys.argv) > 1 else 103.4
EPI_LAT = float(sys.argv[2]) if len(sys.argv) > 2 else 31.0
MON_LON = 104.14
MON_LAT = 30.67

with open(os.path.join(BASE, 'geo', 'china.geojson'), encoding='utf-8') as f:
    data = json.load(f)

CHINA_BBOX = (73.0, 3.0, 136.0, 54.0)

features = [f for f in data['features'] if f.get('geometry') and f['geometry'].get('coordinates')]
N = len(features)

chars_pool = [str(i) for i in range(10)] + [chr(ord('a') + i) for i in range(26)]

COLORS = [
    'grey23', 'grey30', 'grey37', 'grey46', 'grey54', 'grey62',
    'grey70', 'grey78', 'grey82', 'grey89',
    'dark_red', 'dark_green', 'dark_blue',
    'dark_magenta', 'dark_cyan', 'dark_yellow',
    'bright_black',
]

pairs = []
colormap = {}
for i, feat in enumerate(features):
    ch = chars_pool[i % len(chars_pool)]
    color = COLORS[i % len(COLORS)]
    pairs.append((feat, ch))
    colormap[ch] = color

rendered = gj2ascii.render_multiple(pairs, width=80, fill=' ', bbox=CHINA_BBOX, all_touched=False)

# Overlay markers: convert ASCII string to list of lists, replace at computed coords
rows = [list(r) for r in rendered.splitlines()]

def plot_char(lon, lat, ch):
    r, c = lonlat_to_rc(lon, lat, CHINA_BBOX, 40, len(rows))
    tc = c * 2
    if 0 <= r < len(rows) and 0 <= tc < len(rows[r]):
        rows[r][tc] = ch

plot_char(EPI_LON, EPI_LAT, '*')
plot_char(MON_LON, MON_LAT, '@')

rendered_marked = '\n'.join(''.join(r) for r in rows)

# Build colored Text
t = Text()
for line in rendered_marked.splitlines():
    for ch in line:
        if ch == '*':
            t.append('*', style='bold white on red')
        elif ch == '@':
            t.append('@', style='bold white on green')
        elif ch == ' ':
            t.append(' ', style='dim')
        elif ch in colormap:
            t.append(ch, style=colormap[ch])
        else:
            t.append(ch, style='dim')
    t.append('\n')

console.print(f"\n[bold cyan]中国地图 (各省份彩色) 震中({EPI_LON},{EPI_LAT}) 监控点({MON_LON},{MON_LAT})[/bold cyan]")
console.print("[dim]*震中(白底红字)  @监控点(白底绿字)  各省份用不同颜色区分[/dim]")
console.print(t)

console.print("\n[bold cyan]图例 (可见省份)[/bold cyan]")
visible_chars = set()
for line in rendered.splitlines():
    for ch in line:
        if ch != ' ':
            visible_chars.add(ch)
for i, feat in enumerate(features):
    ch = chars_pool[i % len(chars_pool)]
    if ch not in visible_chars:
        continue
    props = feat.get('properties', {})
    name = props.get('name', props.get('NAME', f'Province_{i}'))
    color = COLORS[i % len(COLORS)]
    t = Text()
    t.append(f'{ch}: ', style=color)
    t.append(name)
    console.print(t)
