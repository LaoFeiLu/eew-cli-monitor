import requests
import time
import sys
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

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
    event_id = data.get('EventID', '')
    serial = data.get('Serial', 1)
    report_key = f"jma_{event_id}_serial_{serial}"
    if report_key in processed_events:
        return
    processed_events.add(report_key)

    origin_time = data.get('OriginTime', 'N/A')
    hypocenter = data.get('Hypocenter', '未知地区')
    mag = data.get('Magunitude', 'N/A')
    depth = data.get('Depth', 'N/A')
    max_intensity = data.get('MaxIntensity', 'N/A')
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
    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.1 ==========[/bold yellow]")
    active_sources = [src for src, active in FILTER_CONFIG.items() if active]
    console.print(f"[green]已启用的数据源:[/green] {', '.join([SOURCE_NAMES.get(s, s) for s in active_sources])}")
    console.print("[cyan]每1秒检查一次，有新地震时弹出表格（支持日本气象厅多报更新）。[/cyan]")
    console.print("[cyan]按 Ctrl+C 退出。[/cyan]\n")

    # 将首次调用也放入 try 块，确保 Ctrl+C 能被捕获
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