import requests
import time
import sys
import os
import winsound
import random
import json
import threading
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

try:
    import msvcrt
    WINDOWS = True
except ImportError:
    WINDOWS = False

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[警告] websocket-client 未安装，请运行 pip install websocket-client")

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
# 只对这两个数据源尝试 WebSocket
WS_SOURCES = ['jma', 'cenc']
WS_URLS = {
    'jma': 'wss://ws-api.wolfx.jp/jma_eew',
    'cenc': 'wss://ws-api.wolfx.jp/cenc_eew'
}
HTTP_URLS = {
    'jma': 'https://api.wolfx.jp/jma_eew.json',
    'cenc': 'https://api.wolfx.jp/cenc_eew.json',
    'sc': 'https://api.wolfx.jp/sc_eew.json',
    'fj': 'https://api.wolfx.jp/fj_eew.json',
    'cq': 'https://api.wolfx.jp/cq_eew.json'
}
FILTER_CONFIG = {
    'jma': True,
    'cenc': True,
    'sc': True,
    'fj': True,
    'cq': True
}
# HTTP 轮询间隔（秒），用于非 WebSocket 数据源（四川、福建、重庆）
HTTP_POLL_INTERVAL = 600   # 10 分钟
# ============================================

processed_events = set()
high_intensity_state = {}
console = Console()
ws_running = True

# 状态管理：每个数据源的 WebSocket 模式（'trying', 'connected', 'fallback'）
ws_status = {key: 'trying' for key in FILTER_CONFIG}

def print_earthquake_table(title, rows):
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=14)
    table.add_column("信息", style="white", no_wrap=False, width=50)
    if not rows or len(rows) < 2:
        return
    for data_row in rows[1:]:
        table.add_row(str(data_row[0]), str(data_row[1]))
    console.print(table)

# ---------- 处理各种数据源 ----------
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
    acc_epicenter = data.get('Accuracy', {}).get('Epicenter', 'N/A')
    acc_depth = data.get('Accuracy', {}).get('Depth', 'N/A')
    acc_magnitude = data.get('Accuracy', {}).get('Magnitude', 'N/A')
    max_int_change = data.get('MaxIntChange', {}).get('String', None)
    warn_areas = data.get('WarnArea', [])
    first_area_info = "无具体区域"
    if warn_areas:
        first = warn_areas[0]
        first_area_info = f"{first.get('Chiiki')} 震度 {first.get('Shindo1', 'N/A')}"

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
        ["震央精度", acc_epicenter],
        ["深度精度", acc_depth],
        ["震级精度", acc_magnitude],
        ["震度变化", max_int_change if max_int_change else "无"],
        ["警报区域示例", first_area_info],
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

# ---------- HTTP 轮询函数 ----------
def http_fetch_once(source_key):
    url = HTTP_URLS.get(source_key)
    if not url:
        return
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, dict) and ('EventID' in data or 'event_id' in data):
                process_eew(data, source_key)
    except Exception:
        pass

def fetch_initial_snapshots():
    """启动时获取所有数据源的最新一条历史报告"""
    for source_key, enabled in FILTER_CONFIG.items():
        if not enabled:
            continue
        http_fetch_once(source_key)

def http_polling_loop(source_key):
    """HTTP 轮询循环（用于非 WebSocket 数据源），每 HTTP_POLL_INTERVAL 秒一次"""
    while ws_running and ws_status.get(source_key, 'fallback') == 'fallback':
        http_fetch_once(source_key)
        time.sleep(HTTP_POLL_INTERVAL)

# ---------- WebSocket 处理（独立连接，仅用于 WS_SOURCES） ----------
def on_message_factory(source_key):
    def on_message(ws, message):
        try:
            data = json.loads(message)
            if data and isinstance(data, dict) and ('EventID' in data or 'event_id' in data):
                process_eew(data, source_key)
        except json.JSONDecodeError:
            pass
    return on_message

def on_error_factory(source_key):
    def on_error(ws, error):
        console.print(f"[red]{source_key} WebSocket 错误: {error}[/red]")
        if '503' in str(error) and ws_status[source_key] != 'fallback':
            console.print(f"[yellow]{source_key} WebSocket 服务不可用，切换到 HTTP 轮询模式[/yellow]")
            ws_status[source_key] = 'fallback'
            threading.Thread(target=http_polling_loop, args=(source_key,), daemon=True).start()
    return on_error

def on_close_factory(source_key):
    def on_close(ws, close_status_code, close_msg):
        if ws_status[source_key] == 'fallback':
            console.print(f"[dim]{source_key} 已切换至 HTTP 轮询，不再尝试 WebSocket 重连[/dim]")
            return
        if ws_running and ws_status[source_key] in ('trying', 'connected'):
            console.print(f"[yellow]{source_key} WebSocket 连接已关闭，5秒后重连...[/yellow]")
            time.sleep(5)
            start_websocket(source_key)
    return on_close

def on_open_factory(source_key):
    def on_open(ws):
        console.print(f"[green]{source_key} WebSocket 已连接，实时接收速报...[/green]")
        ws_status[source_key] = 'connected'
    return on_open

def start_websocket(source_key):
    if not WS_AVAILABLE:
        console.print(f"[red]websocket-client 未安装，无法启动 {source_key} WebSocket[/red]")
        ws_status[source_key] = 'fallback'
        threading.Thread(target=http_polling_loop, args=(source_key,), daemon=True).start()
        return
    if ws_status[source_key] == 'fallback':
        return
    url = WS_URLS.get(source_key)
    if not url:
        return
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open_factory(source_key),
            on_message=on_message_factory(source_key),
            on_error=on_error_factory(source_key),
            on_close=on_close_factory(source_key)
        )
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]{source_key} WebSocket 启动失败: {e}[/red]")
        if ws_running and ws_status[source_key] != 'fallback':
            ws_status[source_key] = 'fallback'
            console.print(f"[yellow]{source_key} 切换到 HTTP 轮询模式[/yellow]")
            threading.Thread(target=http_polling_loop, args=(source_key,), daemon=True).start()

# ---------- 实验功能 ----------
def generate_mock_jma_event(serial=1, is_final=False, event_id="MOCK001", intensity=None):
    base_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_mag = 4.5 + (serial * 0.1)
    mock_depth = 50 - (serial * 2)
    if intensity is None:
        intensity_list = ["1", "2", "3", "4", "5弱", "5强", "6弱", "6強", "7"]
        max_intensity = intensity_list[min(serial-1, 8)]
    else:
        max_intensity = intensity
    return {
        "EventID": event_id,
        "Serial": serial,
        "OriginTime": base_time,
        "Hypocenter": f"模拟地震区域 (第{serial}报)",
        "Magunitude": round(mock_mag, 1),
        "Depth": max(10, int(mock_depth)),
        "MaxIntensity": max_intensity,
        "isFinal": is_final,
        "Latitude": 35.0 + random.random() * 5,
        "Longitude": 138.0 + random.random() * 5,
        "Accuracy": {"Epicenter": "锁", "Depth": "锁", "Magnitude": "锁"},
        "MaxIntChange": {"String": "无" if serial == 1 else "震度更新"},
        "WarnArea": [{"Chiiki": "模拟区域A", "Shindo1": max_intensity}]
    }

def run_mock_test():
    console.print("\n[bold magenta]========== 模拟测试模式 ==========[/bold magenta]")
    console.print("[yellow]第一报震度3（普通音），第二报震度6强（触发NHK），第三报震度7（不再触发NHK）[/yellow]")
    console.print("[cyan]按任意键可中断测试。[/cyan]\n")

    event_id = f"DEMO_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    console.print("[cyan]第一报（震度3）...[/cyan]")
    process_jma_eew(generate_mock_jma_event(1, False, event_id, intensity="3"))
    for _ in range(30):
        if WINDOWS and msvcrt.kbhit():
            msvcrt.getch()
            console.print("[yellow]用户中断，退出模拟模式。[/yellow]")
            return
        time.sleep(0.1)

    console.print("[cyan]第二报（震度6强）...[/cyan]")
    process_jma_eew(generate_mock_jma_event(2, False, event_id, intensity="6強"))
    for _ in range(30):
        if WINDOWS and msvcrt.kbhit():
            msvcrt.getch()
            console.print("[yellow]用户中断，退出模拟模式。[/yellow]")
            return
        time.sleep(0.1)

    console.print("[cyan]第三报（震度7）...[/cyan]")
    process_jma_eew(generate_mock_jma_event(3, True, event_id, intensity="7"))

    console.print("[green]模拟演示完成。按任意键继续...[/green]")
    if WINDOWS:
        while True:
            if msvcrt.kbhit():
                msvcrt.getch()
                break
            time.sleep(0.1)
    else:
        input()
    console.print("[yellow]退出模拟模式。[/yellow]")

def check_user_command():
    if not WINDOWS:
        return None
    if msvcrt.kbhit():
        line = []
        while True:
            ch = msvcrt.getch()
            if ch == b'\x03':
                raise KeyboardInterrupt
            if ch == b'\r':
                break
            elif ch == b'\x08':
                if line:
                    line.pop()
            else:
                if 32 <= ch[0] <= 126:
                    line.append(ch.decode('ascii'))
        raw = ''.join(line).strip()
        if not raw:
            return None
        return raw.lower()
    return None

def check_ws_status(source_key):
    """显示指定数据源的 WebSocket 连接状态"""
    if source_key not in FILTER_CONFIG or not FILTER_CONFIG[source_key]:
        console.print(f"[yellow]未启用或不存在的数据源: {source_key}[/yellow]")
        return
    if source_key in WS_SOURCES:
        status = ws_status.get(source_key, 'unknown')
        status_text = {
            'trying': '[yellow]连接中...[/yellow]',
            'connected': '[green]已连接[/green]',
            'fallback': '[red]已回退至 HTTP 轮询[/red]'
        }.get(status, f'[yellow]未知状态: {status}[/yellow]')
        console.print(f"{SOURCE_NAMES[source_key]} WebSocket 状态: {status_text}")
    else:
        console.print(f"[dim]{SOURCE_NAMES[source_key]} 使用 HTTP 轮询，无 WebSocket 连接[/dim]")

# ================== 主程序 ==================
def main():
    global ws_running

    if not WS_AVAILABLE:
        console.print("[red]错误: websocket-client 未安装，请运行 pip install websocket-client[/red]")
        sys.exit(1)

    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.5 ==========[/bold yellow]")
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    if not os.path.exists(SOUND_NHK):
        console.print("[yellow]提示: 紧急铃声文件未找到，将无法播放。[/yellow]")

    active_sources = [src for src, active in FILTER_CONFIG.items() if active]
    console.print(f"[green]已启用数据源:[/green] {', '.join([SOURCE_NAMES.get(s, s) for s in active_sources])}")
    console.print("[cyan]按 Ctrl+C 可退出程序。[/cyan]\n")

    # 启动快照
    fetch_initial_snapshots()

    # 启动 JMA 和 CENC 的 WebSocket 连接（间隔 2~3 秒，不显示提示）
    startup_order = ['jma', 'cenc']
    for source_key in startup_order:
        if not FILTER_CONFIG.get(source_key, False):
            continue
        ws_status[source_key] = 'trying'
        thread = threading.Thread(target=start_websocket, args=(source_key,), daemon=True)
        thread.start()
        delay = random.uniform(2.0, 3.0)
        time.sleep(delay)

    # 对于非 WebSocket 数据源（sc, fj, cq），直接标记为 fallback 并启动轮询（不显示提示）
    for source_key in ['sc', 'fj', 'cq']:
        if not FILTER_CONFIG.get(source_key, False):
            continue
        ws_status[source_key] = 'fallback'
        threading.Thread(target=http_polling_loop, args=(source_key,), daemon=True).start()

    # 主循环
    try:
        while True:
            if WINDOWS:
                raw_cmd = check_user_command()
                if raw_cmd:
                    parts = raw_cmd.split()
                    if parts[0] == 'test':
                        if len(parts) == 1:
                            run_mock_test()
                        elif len(parts) == 2:
                            check_ws_status(parts[1])
                        else:
                            console.print("[yellow]用法: test [数据源] 或 test 无参数执行模拟[/yellow]")
            time.sleep(0.1)
    except KeyboardInterrupt:
        ws_running = False
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    main()