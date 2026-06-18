import requests
import time
import sys
import os
import winsound
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

try:
    import msvcrt
    WINDOWS = True
except ImportError:
    WINDOWS = False

# ================== 资源路径（兼容 PyInstaller） ==================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ================== 音频配置 ==================
SOUND_ALERT = resource_path("sounds/alert.wav")
SOUND_NHK   = resource_path("sounds/nhk_bell.wav")
NHK_BLOCK_DURATION = 6.0
nhk_block_until = 0.0

def play_sound(file_path, is_nhk=False):
    global nhk_block_until
    if not os.path.exists(file_path):
        return
    if is_nhk:
        try:
            winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            nhk_block_until = time.time() + NHK_BLOCK_DURATION
        except Exception:
            pass
    else:
        if time.time() < nhk_block_until:
            return
        try:
            winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass

def is_high_intensity(intensity_str):
    if not intensity_str:
        return False
    s = intensity_str.strip().lower()
    if s == '7':
        return True
    if s.startswith('6'):
        high_patterns = ['弱', '-', 'lower', '强', '+', 'upper', '強']
        for pat in high_patterns:
            if pat in s:
                return True
    return False

# ================== 预警配置区 ==================
SOURCE_NAMES = {
    'jma': '日本气象厅',
    'cenc': '中国地震台网中心',
    'sc': '四川地震局',
    'fj': '福建地震局',
    'cq': '重庆地震局'
}
FILTER_CONFIG = {
    'jma': True,
    'cenc': True,
    'sc': True,
    'fj': True,
    'cq': True
}
# ============================================

processed_events = set()
high_intensity_state = {}
console = Console()

def print_earthquake_table(title, rows):
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=14)
    table.add_column("信息", style="white", no_wrap=False, width=50)
    if not rows or len(rows) < 2:
        return
    for data_row in rows[1:]:
        table.add_row(str(data_row[0]), str(data_row[1]))
    console.print(table)

def process_jma_eew(data):
    global nhk_block_until
    event_id = data.get('EventID', '')
    serial = data.get('Serial', 1)
    report_key = f"jma_{event_id}_serial_{serial}"
    if report_key in processed_events:
        return
    processed_events.add(report_key)

    max_intensity = data.get('MaxIntensity', 'N/A')
    current_high = is_high_intensity(max_intensity)
    prev_high = high_intensity_state.get(event_id, False)

    play_sound(SOUND_ALERT, is_nhk=False)
    if current_high and not prev_high:
        play_sound(SOUND_NHK, is_nhk=True)
    high_intensity_state[event_id] = current_high

    origin_time = data.get('OriginTime', 'N/A')
    hypocenter = data.get('Hypocenter', '未知地区')
    mag = data.get('Magunitude', 'N/A')
    depth = data.get('Depth', 'N/A')
    is_final = data.get('isFinal', False)
    lat = data.get('Latitude')
    lon = data.get('Longitude')
    coords = f"{lat}, {lon}" if lat and lon else '未知'
    rows = [
        ["项目", "信息"],
        ["发震时刻", origin_time],
        ["震中位置", hypocenter],
        ["坐标", coords],
        ["震级(M)", mag],
        ["深度(km)", depth],
        ["最大震度(日本)", max_intensity],
        ["速报序号", str(serial)],
        ["最终报", "是" if is_final else "否"],
        ["数据来源", SOURCE_NAMES['jma']]
    ]
    print_earthquake_table("地震预警速报 (日本气象厅 JMA)", rows)

def process_cenc_eew(data):
    event_id = data.get('EventID', data.get('event_id', ''))
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)
    origin_time = data.get('OriginTime', data.get('origin_time', 'N/A'))
    hypocenter = data.get('Hypocenter', data.get('hypocenter', '未知地区'))
    mag = data.get('Magunitude', data.get('magnitude', 'N/A'))
    depth = data.get('Depth', data.get('depth', 'N/A'))
    max_intensity = data.get('MaxIntensity', data.get('max_intensity', 'N/A'))
    lat = data.get('Latitude', data.get('latitude'))
    lon = data.get('Longitude', data.get('longitude'))
    coords = f"{lat}, {lon}" if lat and lon else '未知'
    is_final = data.get('isFinal', data.get('is_final', False))
    rows = [
        ["项目", "信息"],
        ["发震时刻", origin_time],
        ["震中位置", hypocenter],
        ["坐标", coords],
        ["震级(M)", mag],
        ["深度(km)", depth],
        ["最大烈度(中国)", max_intensity],
        ["最终报", "是" if is_final else "否"],
        ["数据来源", SOURCE_NAMES['cenc']]
    ]
    print_earthquake_table("地震预警速报 (中国地震台网中心 CENC)", rows)

def process_sc_eew(data):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)
    origin_time = data.get('OriginTime', 'N/A')
    hypocenter = data.get('Hypocenter', '未知地区')
    mag = data.get('Magunitude', 'N/A')
    depth = data.get('Depth', 'N/A')
    lat = data.get('Latitude')
    lon = data.get('Longitude')
    coords = f"{lat}, {lon}" if lat and lon else '未知'
    max_intensity = data.get('MaxIntensity', 'N/A')
    is_warn = data.get('isWarn', False)
    rows = [
        ["项目", "信息"],
        ["发震时刻", origin_time],
        ["震中位置", hypocenter],
        ["坐标", coords],
        ["震级(M)", mag],
        ["深度(km)", depth],
        ["最大烈度(中国)", max_intensity],
        ["警报触发", "是" if is_warn else "否"],
        ["数据来源", SOURCE_NAMES['sc']]
    ]
    print_earthquake_table("地震预警速报 (四川省地震局 SC)", rows)

def process_fj_eew(data):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)
    origin_time = data.get('OriginTime', 'N/A')
    hypocenter = data.get('Hypocenter', '未知地区')
    mag = data.get('Magunitude', 'N/A')
    depth = data.get('Depth', 'N/A')
    lat = data.get('Latitude')
    lon = data.get('Longitude')
    coords = f"{lat}, {lon}" if lat and lon else '未知'
    max_intensity = data.get('MaxIntensity', 'N/A')
    rows = [
        ["项目", "信息"],
        ["发震时刻", origin_time],
        ["震中位置", hypocenter],
        ["坐标", coords],
        ["震级(M)", mag],
        ["深度(km)", depth],
        ["最大烈度(中国)", max_intensity],
        ["数据来源", SOURCE_NAMES['fj']]
    ]
    print_earthquake_table("地震预警速报 (福建省地震局 FJ)", rows)

def process_cq_eew(data):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)
    origin_time = data.get('OriginTime', 'N/A')
    hypocenter = data.get('Hypocenter', '未知地区')
    mag = data.get('Magunitude', 'N/A')
    depth = data.get('Depth', 'N/A')
    lat = data.get('Latitude')
    lon = data.get('Longitude')
    coords = f"{lat}, {lon}" if lat and lon else '未知'
    max_intensity = data.get('MaxIntensity', 'N/A')
    rows = [
        ["项目", "信息"],
        ["发震时刻", origin_time],
        ["震中位置", hypocenter],
        ["坐标", coords],
        ["震级(M)", mag],
        ["深度(km)", depth],
        ["最大烈度(中国)", max_intensity],
        ["数据来源", SOURCE_NAMES['cq']]
    ]
    print_earthquake_table("地震预警速报 (重庆市地震局 CQ)", rows)

def process_eew(data, source_key):
    if source_key == 'jma':
        process_jma_eew(data)
    elif source_key == 'cenc':
        process_cenc_eew(data)
    elif source_key == 'sc':
        process_sc_eew(data)
    elif source_key == 'fj':
        process_fj_eew(data)
    elif source_key == 'cq':
        process_cq_eew(data)

def fetch_and_process():
    urls = []
    if FILTER_CONFIG.get('jma'):
        urls.append(('jma_eew', 'https://api.wolfx.jp/jma_eew.json'))
    if FILTER_CONFIG.get('cenc'):
        urls.append(('cenc_eew', 'https://api.wolfx.jp/cenc_eew.json'))
    if FILTER_CONFIG.get('sc'):
        urls.append(('sc_eew', 'https://api.wolfx.jp/sc_eew.json'))
    if FILTER_CONFIG.get('fj'):
        urls.append(('fj_eew', 'https://api.wolfx.jp/fj_eew.json'))
    if FILTER_CONFIG.get('cq'):
        urls.append(('cq_eew', 'https://api.wolfx.jp/cq_eew.json'))

    for source_key, url in urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if '_eew' in source_key:
                    process_eew(data, source_key.replace('_eew', ''))
        except Exception:
            pass

def main():
    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.2 ==========[/bold yellow]")
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    if not os.path.exists(SOUND_NHK):
        console.print("[yellow]提示: 紧急铃声文件未找到，将无法播放。[/yellow]")

    active_sources = [src for src, active in FILTER_CONFIG.items() if active]
    console.print(f"[green]已启用数据源:[/green] {', '.join([SOURCE_NAMES.get(s, s) for s in active_sources])}")
    console.print("[cyan]收到新地震时会弹出表格并播放提示音。紧急铃声播放期间普通提示音会被屏蔽。[/cyan]")
    console.print("[cyan]按 Ctrl+C 可退出程序。[/cyan]\n")

    # 修复：将首次调用也纳入 try 块
    try:
        fetch_and_process()
        while True:
            time.sleep(1)
            fetch_and_process()
    except KeyboardInterrupt:
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    main()