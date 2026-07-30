"""
Preview colored world map with epicenter (*) and monitoring point (@).
Usage:
  python geo/_preview_world.py
  python geo/_preview_world.py 138.65 -2.95       # epicenter lon lat (Papua)
"""
import json, os, sys
import gj2ascii
from rich.console import Console
from rich.text import Text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo.geo_ascii import lonlat_to_rc

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
console = Console()

EPI_LON = float(sys.argv[1]) if len(sys.argv) > 1 else 138.65
EPI_LAT = float(sys.argv[2]) if len(sys.argv) > 2 else -2.95
MON_LON = 104.14
MON_LAT = 30.67

with open(os.path.join(BASE, 'geo', 'world.json'), encoding='utf-8') as f:
    data = json.load(f)

WORLD_BBOX = (-180.0, -90.0, 180.0, 90.0)

features = [f for f in data['features'] if f.get('geometry') and f['geometry'].get('coordinates')]
N = len(features)

chars_pool = [str(i) for i in range(10)] + [chr(ord('a') + i) for i in range(26)]

COLORS = [
    'red', 'green', 'blue', 'yellow', 'cyan', 'magenta',
    'bright_red', 'bright_green', 'bright_blue', 'bright_yellow',
    'bright_cyan', 'bright_magenta',
    'dark_red', 'dark_green', 'dark_blue',
    'orange1', 'orange3', 'gold1',
    'purple', 'deep_pink4', 'hot_pink',
    'turquoise2', 'steel_blue1', 'spring_green1',
    'deep_sky_blue1', 'wheat1', 'tan', 'salmon1',
]

pairs = []
colormap = {}
for i, feat in enumerate(features):
    ch = chars_pool[i % len(chars_pool)]
    color = COLORS[i % len(COLORS)]
    pairs.append((feat, ch))
    colormap[ch] = color

console.print(f"[dim]Rendering {N} features at width=80...[/dim]")
rendered = gj2ascii.render_multiple(pairs, width=80, fill=' ', bbox=WORLD_BBOX, all_touched=False)

# Overlay markers
W, H = 40, len(rendered.splitlines())
rows = [list(r) for r in rendered.splitlines()]

def plot_char(lon, lat, ch):
    r, c = lonlat_to_rc(lon, lat, WORLD_BBOX, W, H)
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

console.print(f"\n[bold cyan]世界地图 (各国彩色) 震中({EPI_LON},{EPI_LAT}) 监控点({MON_LON},{MON_LAT})[/bold cyan]")
console.print("[dim]*震中(白底红字)  @监控点(白底绿字)  各国用不同颜色区分[/dim]")
console.print(t)

# Legend visible countries
visible_chars = set()
for line in rendered.splitlines():
    for ch in line:
        if ch != ' ':
            visible_chars.add(ch)

console.print(f"\n[bold cyan]图例 ({len(visible_chars)} 个可见国家/地区)[/bold cyan]")
for i, feat in enumerate(features):
    ch = chars_pool[i % len(chars_pool)]
    if ch not in visible_chars:
        continue
    props = feat.get('properties', {})
    name = props.get('name', props.get('NAME', props.get('ADMIN', f'#{i}')))
    color = COLORS[i % len(COLORS)]
    t = Text()
    t.append(f'{ch}: ', style=color)
    t.append(name)
    console.print(t)
