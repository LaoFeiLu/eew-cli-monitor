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


# ================== 资源路径 ==================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ================== 音频配置 ==================
SOUND_ALERT = resource_path("sounds/alert.wav")
SOUND_NHK = resource_path("sounds/nhk_bell.wav")
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


# ================== 数据源配置 ==================
SOURCE_CONFIG = {
    'p2p': {
        'name': 'P2PQuake',
        'url': 'wss://api.p2pquake.net/v2/ws',
        'enabled': True,
        'type': 'jma_only'
    },
    'wolfx': {
        'name': 'Wolfx',
        'url': 'wss://ws-api.wolfx.jp/all_eew',
        'enabled': True,
        'type': 'all'
    }
}

SOURCE_DISPLAY = {
    'p2p': 'P2PQuake',
    'wolfx': 'Wolfx'
}

# HTTP 快照地址
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
# ============================================

processed_events = set()
high_intensity_state = {}
console = Console()
ws_running = True
ws_connections = {}
ws_status = {}


def print_earthquake_table(title, rows, source_label):
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    if not rows or len(rows) < 2:
        return
    rows_copy = rows.copy()
    rows_copy.append(["信号源", source_label])
    for data_row in rows_copy[1:]:
        table.add_row(str(data_row[0]), str(data_row[1]))
    console.print(table)


# ---------- 统一数据处理入口 ----------
def process_eew(data, source_key, default_type=None):
    data_type = data.get('type')
    if data_type is None and default_type is not None:
        data_type = default_type
    if not data_type:
        return
    if not FILTER_CONFIG.get(data_type, False):
        return
    if data_type == 'jma':
        process_jma_eew(data, source_key)
    elif data_type == 'cenc':
        process_cenc_eew(data, source_key)
    elif data_type == 'sc':
        process_sc_eew(data, source_key)
    elif data_type == 'fj':
        process_fj_eew(data, source_key)
    elif data_type == 'cq':
        process_cq_eew(data, source_key)


# ---------- 各数据源处理函数 ----------
def process_jma_eew(data, source_key):
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
        ["警报区域示例", first_area_info]
    ]
    print_earthquake_table("地震预警速报 (日本气象厅 JMA)", rows, SOURCE_DISPLAY.get(source_key, source_key))


def process_cenc_eew(data, source_key):
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
        ["最终报", "是" if is_final else "否"]
    ]
    print_earthquake_table("地震预警速报 (中国地震台网中心 CENC)", rows, SOURCE_DISPLAY.get(source_key, source_key))


def process_sc_eew(data, source_key):
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
        ["警报触发", "是" if is_warn else "否"]
    ]
    print_earthquake_table("地震预警速报 (四川省地震局 SC)", rows, SOURCE_DISPLAY.get(source_key, source_key))


def process_fj_eew(data, source_key):
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
        ["最大烈度(中国)", max_intensity]
    ]
    print_earthquake_table("地震预警速报 (福建省地震局 FJ)", rows, SOURCE_DISPLAY.get(source_key, source_key))


def process_cq_eew(data, source_key):
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
        ["最大烈度(中国)", max_intensity]
    ]
    print_earthquake_table("地震预警速报 (重庆市地震局 CQ)", rows, SOURCE_DISPLAY.get(source_key, source_key))


# ---------- 快照功能 ----------
def fetch_initial_snapshots():
    console.print("[dim]正在获取启动快照...[/dim]")

    # ---- Wolfx 快照 ----
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
                    process_eew(data, 'wolfx', default_type=source_key)
        except Exception:
            pass

    # ---- P2PQuake 快照 ----
    try:
        p2p_url = "https://api.p2pquake.net/v2/history?codes=551&limit=1"
        response = requests.get(p2p_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                quake = data[0]
                eq_data = quake.get("earthquake", {})
                hypocenter = eq_data.get("hypocenter", {})
                converted = {
                    "type": "jma",
                    "EventID": quake.get("id", ""),
                    "OriginTime": eq_data.get("time", ""),
                    "Hypocenter": hypocenter.get("name", "未知地区"),
                    "Magunitude": hypocenter.get("magnitude", -1),
                    "Depth": hypocenter.get("depth", "N/A"),
                    "MaxIntensity": scale_to_jma(eq_data.get("maxScale", 0)),
                    "Latitude": hypocenter.get("latitude"),
                    "Longitude": hypocenter.get("longitude"),
                    "isFinal": True,
                    "Accuracy": {},
                    "WarnArea": []
                }
                if converted["Magunitude"] != -1:
                    process_eew(converted, 'p2p')
    except Exception:
        pass

    console.print("[dim]快照获取完成。[/dim]")


def scale_to_jma(scale_code):
    scale_map = {
        -1: "不明",
        10: "1",
        20: "2",
        30: "3",
        40: "4",
        45: "5弱",
        50: "5強",
        55: "6弱",
        60: "6強",
        70: "7"
    }
    return scale_map.get(scale_code, "不明")


# ---------- WebSocket 处理 ----------
def on_message_factory(source_key):
    def on_message(ws, message):
        if not SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
            return
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                return
            if source_key == 'p2p':
                if data.get('type') == 'earthquake':
                    eq_data = data.get('earthquake', {})
                    hypocenter = eq_data.get('hypocenter', {})
                    converted = {
                        "type": "jma",
                        "EventID": data.get("id", ""),
                        "OriginTime": eq_data.get("time", ""),
                        "Hypocenter": hypocenter.get("name", "未知地区"),
                        "Magunitude": hypocenter.get("magnitude", -1),
                        "Depth": hypocenter.get("depth", "N/A"),
                        "MaxIntensity": scale_to_jma(eq_data.get("maxScale", 0)),
                        "Latitude": hypocenter.get("latitude"),
                        "Longitude": hypocenter.get("longitude"),
                        "isFinal": True,
                        "Accuracy": {},
                        "WarnArea": []
                    }
                    if converted["Magunitude"] != -1:
                        process_eew(converted, source_key)
            else:
                if 'EventID' in data or 'event_id' in data:
                    process_eew(data, source_key)
        except json.JSONDecodeError:
            pass

    return on_message


def on_error_factory(source_key):
    def on_error(ws, error):
        console.print(f"[red]{source_key} WebSocket 错误: {error}[/red]")

    return on_error


def on_close_factory(source_key):
    def on_close(ws, close_status_code, close_msg):
        console.print(f"[yellow]{source_key} 连接已关闭，5秒后重连...[/yellow]")
        if ws_running and SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
            time.sleep(5)
            start_websocket(source_key)

    return on_close


def on_open_factory(source_key):
    def on_open(ws):
        console.print(f"[green]{source_key} WebSocket 已连接 ({SOURCE_CONFIG[source_key]['name']})[/green]")
        ws_status[source_key] = 'connected'

    return on_open


def start_websocket(source_key):
    if not WS_AVAILABLE:
        console.print(f"[red]websocket-client 未安装，无法启动 {source_key} WebSocket[/red]")
        return
    if not SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
        return
    url = SOURCE_CONFIG[source_key]['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open_factory(source_key),
            on_message=on_message_factory(source_key),
            on_error=on_error_factory(source_key),
            on_close=on_close_factory(source_key)
        )
        ws_connections[source_key] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]{source_key} WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_websocket(source_key)


# ---------- 命令处理 ----------
def handle_command(cmd):
    parts = cmd.split()
    if not parts:
        return
    if parts[0] == 'test':
        run_mock_test()
        return
    elif parts[0] == 'stop':
        if len(parts) < 2:
            console.print("[yellow]用法: stop <p2p|wolfx>[/yellow]")
            return
        target = parts[1]
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return
        if not SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于停用状态[/yellow]")
            return
        SOURCE_CONFIG[target]['enabled'] = False
        console.print(f"[yellow]{target} 已停用[/yellow]")
        if target in ws_connections:
            try:
                ws_connections[target].close()
            except:
                pass
        return
    elif parts[0] == 'enable':
        if len(parts) < 2:
            console.print("[yellow]用法: enable <p2p|wolfx>[/yellow]")
            return
        target = parts[1]
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return
        if SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于启用状态[/yellow]")
            return
        SOURCE_CONFIG[target]['enabled'] = True
        console.print(f"[green]{target} 已启用，正在连接...[/green]")
        threading.Thread(target=start_websocket, args=(target,), daemon=True).start()
        return
    elif parts[0] == 'status':
        console.print("[cyan]当前数据源状态:[/cyan]")
        for key, config in SOURCE_CONFIG.items():
            status = "[green]启用[/green]" if config['enabled'] else "[red]停用[/red]"
            conn_status = "[green]已连接[/green]" if ws_status.get(key) == 'connected' else "[yellow]未连接[/yellow]"
            console.print(f"  {config['name']} ({key}): {status} | {conn_status}")
        return
    else:
        console.print(f"[yellow]未知命令: {cmd}[/yellow]")


# ---------- 模拟测试 ----------
def generate_mock_jma_event(serial=1, is_final=False, event_id="MOCK001", intensity=None):
    base_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_mag = 4.5 + (serial * 0.1)
    mock_depth = 50 - (serial * 2)
    if intensity is None:
        intensity_list = ["1", "2", "3", "4", "5弱", "5强", "6弱", "6強", "7"]
        max_intensity = intensity_list[min(serial - 1, 8)]
    else:
        max_intensity = intensity
    return {
        "type": "jma",
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
        "WarnArea": [{"Chiiki": "模拟区域A", "Shindo1": max_intensity}]
    }


def run_mock_test():
    console.print("\n[bold magenta]========== 模拟测试模式 ==========[/bold magenta]")
    console.print("[yellow]第一报震度3（普通音），第二报震度6强（触发NHK），第三报震度7（不再触发NHK）[/yellow]")
    console.print("[cyan]按任意键可中断测试。[/cyan]\n")

    event_id = f"DEMO_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    console.print("[cyan]第一报（震度3）...[/cyan]")
    process_eew(generate_mock_jma_event(1, False, event_id, intensity="3"), 'test')
    for _ in range(30):
        if WINDOWS and msvcrt.kbhit():
            msvcrt.getch()
            console.print("[yellow]用户中断，退出模拟模式。[/yellow]")
            return
        time.sleep(0.1)

    console.print("[cyan]第二报（震度6强）...[/cyan]")
    process_eew(generate_mock_jma_event(2, False, event_id, intensity="6強"), 'test')
    for _ in range(30):
        if WINDOWS and msvcrt.kbhit():
            msvcrt.getch()
            console.print("[yellow]用户中断，退出模拟模式。[/yellow]")
            return
        time.sleep(0.1)

    console.print("[cyan]第三报（震度7）...[/cyan]")
    process_eew(generate_mock_jma_event(3, True, event_id, intensity="7"), 'test')

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


# ================== 主程序 ==================
def main():
    global ws_running

    if not WS_AVAILABLE:
        console.print("[red]错误: websocket-client 未安装，请运行 pip install websocket-client[/red]")
        sys.exit(1)

    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.6 ==========[/bold yellow]")
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    if not os.path.exists(SOUND_NHK):
        console.print("[yellow]提示: 紧急铃声文件未找到，将无法播放。[/yellow]")

    # 不再显示命令列表，所有命令为实验性功能
    console.print("[cyan]数据源: P2PQuake (日本) + Wolfx (日本+中国)[/cyan]")
    console.print("[cyan]按 Ctrl+C 可退出程序。[/cyan]\n")

    # 启动快照
    fetch_initial_snapshots()

    # 启动所有启用的数据源
    for source_key, config in SOURCE_CONFIG.items():
        if config['enabled']:
            ws_status[source_key] = 'connecting'
            threading.Thread(target=start_websocket, args=(source_key,), daemon=True).start()
            time.sleep(1)

    # 主循环
    try:
        while True:
            if WINDOWS:
                cmd = check_user_command()
                if cmd:
                    handle_command(cmd)
            time.sleep(0.1)
    except KeyboardInterrupt:
        ws_running = False
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)


if __name__ == "__main__":
    main()