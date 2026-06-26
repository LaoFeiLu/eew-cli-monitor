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

# 启用哪些数据源（这里保留，但 all_eew 会全部推送，可根据需要过滤）
FILTER_CONFIG = {
    'jma': True,
    'cenc': True,
    'sc': True,
    'fj': True,
    'cq': True
}

# 融合 WebSocket 地址
WS_URL = 'wss://ws-api.wolfx.jp/all_eew'

# HTTP 地址（仅用于启动快照）
HTTP_URLS = {
    'jma': 'https://api.wolfx.jp/jma_eew.json',
    'cenc': 'https://api.wolfx.jp/cenc_eew.json',
    'sc': 'https://api.wolfx.jp/sc_eew.json',
    'fj': 'https://api.wolfx.jp/fj_eew.json',
    'cq': 'https://api.wolfx.jp/cq_eew.json'
}
# ============================================

processed_events = set()
high_intensity_state = {}
console = Console()
ws_running = True

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

# ---------- 启动快照（HTTP 获取最新历史） ----------
def fetch_initial_snapshots():
    for source_key, enabled in FILTER_CONFIG.items():
        if not enabled:
            continue
        url = HTTP_URLS.get(source_key)
        if not url:
            continue
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict) and ('EventID' in data or 'event_id' in data):
                    process_eew(data, source_key)
        except Exception:
            pass

# ---------- WebSocket 处理（融合 all_eew） ----------
def on_message(ws, message):
    try:
        data = json.loads(message)
        if not isinstance(data, dict):
            return
        # 根据 'type' 字段识别数据来源（Wolfx 文档中 all_eew 推送的每条数据都包含 type）
        source_key = data.get('type')
        if not source_key:
            return
        # 检查是否启用该数据源
        if not FILTER_CONFIG.get(source_key, False):
            return
        if 'EventID' in data or 'event_id' in data:
            process_eew(data, source_key)
    except json.JSONDecodeError:
        pass

def on_error(ws, error):
    console.print(f"[red]WebSocket 错误: {error}[/red]")

def on_close(ws, close_status_code, close_msg):
    console.print("[yellow]连接已关闭，5秒后重连...[/yellow]")
    if ws_running:
        time.sleep(5)
        start_websocket()

def on_open(ws):
    console.print("[green]融合 WebSocket 已连接，实时接收所有数据源...[/green]")

def start_websocket():
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 WebSocket[/red]")
        return
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_websocket()

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
        cmd = ''.join(line).strip().lower()
        return cmd
    return None

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

    # 启动快照（获取各数据源最新历史）
    fetch_initial_snapshots()

    # 启动融合 WebSocket
    ws_running = True
    ws_thread = threading.Thread(target=start_websocket, daemon=True)
    ws_thread.start()

    # 主循环处理命令
    try:
        while True:
            if WINDOWS:
                cmd = check_user_command()
                if cmd == 'test':
                    run_mock_test()
            time.sleep(0.1)
    except KeyboardInterrupt:
        ws_running = False
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    main()