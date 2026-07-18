import requests
import time
import sys
import os
import winsound
import random
import json
import threading
import socket
import csv
import re
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

try:
    import msvcrt
    WINDOWS = True
except ImportError:
    WINDOWS = False

DEBUG = False

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[警告] websocket-client 未安装，WebSocket 数据源将无法连接")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


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


def safe_get(dic, *keys, default='N/A'):
    for key in keys:
        val = dic.get(key)
        if val is not None:
            if isinstance(val, str):
                return val
            return val
    return default


def to_roman(num):
    """将数字（1~12）转换为罗马数字"""
    if num is None:
        return 'N/A'
    try:
        n = int(round(float(num)))
        if n < 1 or n > 12:
            return str(n)
        roman_map = {
            1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V',
            6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX',
            10: 'X', 11: 'XI', 12: 'XII'
        }
        return roman_map.get(n, str(n))
    except:
        return str(num)


def estimate_intensity(magnitude, depth_km, output_type='number'):
    try:
        if magnitude is None or magnitude == 'N/A' or magnitude == '':
            return 'N/A'
        M = float(magnitude)
        if depth_km and depth_km != 'N/A':
            if isinstance(depth_km, str):
                match = re.search(r'(\d+\.?\d*)', depth_km)
                d = float(match.group(1)) if match else 15.0
            else:
                d = float(depth_km)
        else:
            d = 15.0
        intensity = M + 1.5 - 0.05 * d
        if intensity < 1:
            intensity = 1
        elif intensity > 12:
            intensity = 12
        if output_type == 'roman':
            return f"{to_roman(intensity)}(估算)"
        else:
            return f"{round(intensity, 1)}度(估算)"
    except:
        return 'N/A'


def get_intensity_display(data, source_type=None):
    official = safe_get(data, 'epiIntensity', 'maxIntensity', 'MaxIntensity')
    if official != 'N/A' and official not in (None, '', '未知'):
        return official
    mag = safe_get(data, 'magnitude', 'Magunitude')
    depth = safe_get(data, 'depth', 'Depth')
    if source_type in ('jma', 'nied', 'p2p', 'p2pjson'):
        return estimate_intensity(mag, depth, 'number')
    else:
        return estimate_intensity(mag, depth, 'roman')


# ================== 配置文件路径（持久化） ==================
CONFIG_FILE = "eew_monitor_config.json"


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        console.print(f"[red]保存配置失败: {e}[/red]")


# ================== 数据源配置 ==================
SOURCE_CONFIG = {
    'wolfx': {
        'name': 'Wolfx',
        'url': 'wss://ws-api.wolfx.jp/all_eew',
        'enabled': False,
        'type': 'all',
        'need_subscribe': False,
        'fallback_urls': []
    },
    'p2p': {
        'name': 'P2PQuake (EPSP)',
        'enabled': False,
        'type': 'jma_only'
    },
    'p2pjson': {
        'name': 'P2PQuake (JSON API v2)',
        'url': 'wss://api.p2pquake.net/v2/ws',
        'enabled': True,
        'type': 'websocket',
        'need_subscribe': True,
        'subscribe_msg': '{"type":"subscribe","topic":"all"}'
    },
    'nied': {
        'name': 'NIED (日本防灾科学技术研究所)',
        'url': 'wss://sismotide.top/nied',
        'enabled': True,
        'type': 'jma_only',
        'need_subscribe': False,
        'fallback_urls': []
    },
    'fan': {
        'name': 'FAN Studio (地震)',
        'url': 'wss://ws.fanstudio.tech/all',
        'enabled': True,
        'type': 'all',
        'need_subscribe': False,
        'fallback_urls': ['wss://ws.fanstudio.hk/all']
    }
}

SOURCE_DISPLAY = {
    'wolfx': 'Wolfx',
    'p2p': 'P2PQuake (EPSP)',
    'p2pjson': 'P2PQuake (JSON API)',
    'nied': 'NIED',
    'fan': 'FAN Studio'
}

HTTP_URLS = {
    'jma': 'https://api.wolfx.jp/jma_eew.json',
    'cenc': 'https://api.wolfx.jp/cenc_eew.json',
    'sc': 'https://api.wolfx.jp/sc_eew.json',
    'fj': 'https://api.wolfx.jp/fj_eew.json',
    'cq': 'https://api.wolfx.jp/cq_eew.json'
}

FAN_SUBTYPES = [
    'cea', 'cwa-eew', 'jma',
    'cenc', 'cwa',
    'usgs', 'sa', 'emsc', 'bcsf', 'gfz', 'usp',
    'kma', 'kma-eew',
    'fssn', 'fssn-cmt',
    'cea-pr',
    'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan',
    'hko'
]

FILTER_DETAIL = {
    'wolfx': {
        'jma': True,
        'cenc': True,
        'sc': False,
        'fj': False,
        'cq': False
    },
    'p2p': {
        'jma': True
    },
    'p2pjson': {},
    'nied': {},
    'fan': {
        'cea': True,
        'cwa-eew': True,
        'jma': True,
        'cenc': True,
        'cwa': True,
        'cea-pr': False,
        'ningxia': False,
        'guangxi': False,
        'shanxi': False,
        'beijing': False,
        'yunnan': False,
        'hko': False,
        'usgs': False,
        'sa': False,
        'emsc': False,
        'bcsf': False,
        'gfz': False,
        'usp': False,
        'kma': False,
        'kma-eew': False,
        'fssn': False,
        'fssn-cmt': False,
    }
}
for sub in FAN_SUBTYPES:
    if sub not in FILTER_DETAIL['fan']:
        FILTER_DETAIL['fan'][sub] = False

FILTER_CONFIG = {
    'jma': True,
    'cenc': True,
    'sc': False,
    'fj': False,
    'cq': False
}

# FAN 重连冷却时间：改为 5 分钟
FAN_RECONNECT_DELAY = 300
fan_last_reconnect_time = 0

# P2P JSON 重连配置
p2pjson_reconnect_delay = 5

processed_events = set()
high_intensity_state = {}
console = Console()
ws_running = True
ws_connections = {}
ws_status = {}

# ================== 导出功能全局变量 ==================
EXPORT_ENABLED = False
EXPORT_FILE = None
EXPORT_FILE_PATH = None
# ==================================================


# ---------- 表格显示与导出 ----------
def write_table_to_csv(title, rows):
    global EXPORT_FILE, EXPORT_FILE_PATH
    if not EXPORT_ENABLED:
        return
    try:
        if EXPORT_FILE is None:
            if EXPORT_FILE_PATH:
                filename = EXPORT_FILE_PATH
            else:
                prog_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(prog_dir, f"quake_export_{timestamp}.csv")
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
            EXPORT_FILE = open(filename, 'a', newline='', encoding='utf-8-sig')
            if os.path.getsize(filename) == 0:
                writer = csv.writer(EXPORT_FILE)
                writer.writerow(["表格标题", "项目", "信息"])
        writer = csv.writer(EXPORT_FILE)
        for row in rows:
            writer.writerow([title, row[0], row[1]])
        EXPORT_FILE.flush()
    except Exception as e:
        console.print(f"[red]写入CSV失败: {e}[/red]")


def print_earthquake_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    rows_with_src = rows.copy()
    rows_with_src.append(["信号源", source_label])
    for row in rows_with_src:
        table.add_row(str(row[0]), str(row[1]))
    console.print(table)
    write_table_to_csv(title, rows_with_src)


def print_weather_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold blue")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    rows_with_src = rows.copy()
    rows_with_src.append(["信号源", source_label])
    for row in rows_with_src:
        table.add_row(str(row[0]), str(row[1]))
    console.print(table)
    write_table_to_csv(title, rows_with_src)


# ---------- 海啸预警 (FAN tsunami) ----------
def process_tsunami(data, source_label):
    try:
        rows = []
        wi = data.get('warningInfo', {})
        si = data.get('shockInfo', {})
        ti = data.get('timeInfo', {})
        rows.append(["标题", wi.get('title', 'N/A')])
        rows.append(["级别", wi.get('level', 'N/A')])
        rows.append(["发布机构", wi.get('orgUnit', 'N/A')])
        rows.append(["发震时刻", si.get('shockTime', 'N/A')])
        rows.append(["震中位置", si.get('placeName', '未知地区')])
        lat, lon = si.get('latitude'), si.get('longitude')
        rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
        rows.append(["震级", si.get('magnitude', 'N/A')])
        rows.append(["深度(km)", si.get('depth', 'N/A')])
        rows.append(["发布时间", ti.get('alarmDate', 'N/A')])
        rows.append(["更新时间", ti.get('updateDate', 'N/A')])

        forecasts = data.get('forecasts', [])
        if forecasts:
            first = forecasts[0]
            province = first.get('province', '')
            area = first.get('forecastArea', '')
            rows.append(["预报区域", f"{province} {area}".strip() or 'N/A'])
            rows.append(["预计到达", first.get('estimatedArrivalTime', 'N/A')])
            rows.append(["最大波高(cm)", first.get('maxWaveHeight', 'N/A')])
        else:
            rows.append(["预报区域", "无"])
        wl = data.get('waterLevelMonitoring', [])
        if wl:
            first_wl = wl[0]
            rows.append(["监测站", first_wl.get('stationName', 'N/A')])
            rows.append(["最大波高(cm)", first_wl.get('maxWaveHeight', 'N/A')])
        else:
            rows.append(["监测站", "无"])

        if rows:
            table = Table(title="海啸预警 (自然资源部)", box=box.ROUNDED, border_style="bold red")
            table.add_column("项目", style="cyan", no_wrap=True, width=12)
            table.add_column("信息", style="white", no_wrap=False, width=48)
            rows.append(["信号源", source_label])
            for row in rows:
                table.add_row(row[0], str(row[1]))
            console.print(table)
            write_table_to_csv("海啸预警 (自然资源部)", rows)
            play_sound(SOUND_ALERT, is_nhk=False)
    except Exception as e:
        console.print(f"[red]海啸预警解析错误: {e}[/red]")


# ---------- FAN 各子源独立处理 ----------
def process_fan_data(data, sub_type, source_label):
    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter', 'region_name')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    if sub_type in ('jma', 'nied', 'p2p', 'p2pjson'):
        rows.append(["最大震度/烈度", get_intensity_display(data, 'jma')])
    else:
        rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["最终报", "是" if data.get('final', False) else "否"])
    rows.append(["取消报", "是" if data.get('cancel', False) else "否"])
    rows.append(["更新报数", str(data.get('updates', 1))])
    info_type = safe_get(data, 'infoTypeName', 'info_type')
    if info_type == 'N/A' or info_type == '' or info_type is None:
        info_type = '地震测定报'
    rows.append(["信息类型", info_type])
    affected = data.get('locationDesc', [])
    rows.append(["影响区域", ', '.join(affected) if affected else '无'])

    title_map = {
        'jma': '地震预警速报 (日本气象厅 JMA)',
        'cenc': '地震情报 (中国地震台网中心 CENC)',
        'cwa': '地震报告 (台湾气象署 CWA)',
        'cwa-eew': '地震预警速报 (台湾气象署 CWA-EEW)',
        'cea': '地震预警速报 (中国地震预警网 CEA)',
    }
    title = title_map.get(sub_type, f"地震报告 ({sub_type})")

    province_map = {
        'cea-pr': '省级', 'ningxia': '宁夏', 'guangxi': '广西',
        'shanxi': '山西', 'beijing': '北京', 'yunnan': '云南'
    }
    if sub_type in province_map:
        title = f"地震测定报 ({province_map[sub_type]}省地震局)"

    if rows:
        print_earthquake_table(title, rows, source_label)
        play_sound(SOUND_ALERT, is_nhk=False)


# ---------- Wolfx 各处理函数 ----------
def process_jma_eew(data, source_key, source_label):
    global nhk_block_until
    event_id = safe_get(data, 'EventID', 'id', default='')
    if not event_id:
        if DEBUG:
            console.print("[dim]JMA 数据缺少 EventID/id，跳过[/dim]")
        return
    origin_time = safe_get(data, 'OriginTime', 'origin_time', 'shockTime', default='')
    if not origin_time:
        if DEBUG:
            console.print(f"[dim]JMA 数据缺少发震时刻，跳过 (EventID: {event_id})[/dim]")
        return

    serial = data.get('Serial', 1)
    report_key = f"jma_{event_id}_serial_{serial}"
    if report_key in processed_events:
        return
    processed_events.add(report_key)

    max_intensity = safe_get(data, 'MaxIntensity', 'epiIntensity', default='N/A')
    current_high = is_high_intensity(str(max_intensity))
    prev_high = high_intensity_state.get(event_id, False)

    play_sound(SOUND_ALERT, is_nhk=False)
    if current_high and not prev_high:
        play_sound(SOUND_NHK, is_nhk=True)
    high_intensity_state[event_id] = current_high

    rows = []
    rows.append(["发震时刻", origin_time])
    rows.append(["震中位置", safe_get(data, 'Hypocenter', 'placeName', 'region_name')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大震度(日本)", max_intensity])
    rows.append(["速报序号", str(serial)])
    rows.append(["最终报", "是" if data.get('isFinal', False) else "否"])

    acc = data.get('Accuracy', {})
    rows.append(["震央精度", acc.get('Epicenter', 'N/A')])
    rows.append(["深度精度", acc.get('Depth', 'N/A')])
    rows.append(["震级精度", acc.get('Magnitude', 'N/A')])

    max_int_change = data.get('MaxIntChange', {}).get('String', '无')
    rows.append(["震度变化", max_int_change])

    warn_areas = data.get('WarnArea', [])
    if warn_areas:
        first = warn_areas[0]
        rows.append(["警报区域示例", f"{first.get('Chiiki', '')} 震度 {first.get('Shindo1', 'N/A')}"])
    else:
        rows.append(["警报区域示例", "无具体区域"])

    print_earthquake_table("地震预警速报 (日本气象厅 JMA)", rows, source_label)


def process_cenc_eew(data, source_key, source_label):
    event_id = safe_get(data, 'EventID', 'event_id', 'eventId', default='')
    if not event_id:
        if DEBUG:
            console.print("[dim]CENC 数据缺少 EventID，跳过[/dim]")
        return
    if event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time', 'shockTime')])
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])
    rows.append(["最终报", "是" if data.get('isFinal', data.get('is_final', False)) else "否"])

    print_earthquake_table("地震情报 (中国地震台网中心 CENC)", rows, source_label)


def process_sc_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])
    rows.append(["警报触发", "是" if data.get('isWarn', False) else "否"])

    print_earthquake_table("地震测定报 (四川省地震局 SC)", rows, source_label)


def process_fj_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震测定报 (福建省地震局 FJ)", rows, source_label)


def process_cq_eew(data, source_key, source_label):
    event_id = data.get('EventID', '')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'Hypocenter', 'placeName')])
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大烈度(中国)", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震测定报 (重庆市地震局 CQ)", rows, source_label)


def process_cea_eew(data, source_key, source_label):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["预估烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震预警速报 (中国地震预警网 CEA)", rows, source_label)


def process_cwa_eew(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度", get_intensity_display(data, 'cenc')])
    affected = data.get('locationDesc', [])
    rows.append(["影响区域", ', '.join(affected) if affected else '无'])

    print_earthquake_table("地震预警速报 (台湾气象署 CWA-EEW)", rows, source_label)


def process_cwa_report(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度", get_intensity_display(data, 'cenc')])

    print_earthquake_table("地震报告 (台湾气象署 CWA)", rows, source_label)


def process_provincial_eew(data, source_key, source_label, province_name):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table(f"地震测定报 ({province_name}省地震局)", rows, source_label)


def process_hko_eew(data, source_key, source_label):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["区域", safe_get(data, 'region', 'citystring')])

    print_earthquake_table("地震报告 (香港天文台 HKO)", rows, source_label)


def process_usgs_eew(data, source_key, source_label):
    event_id = safe_get(data, 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])
    rows.append(["标题", safe_get(data, 'title')])

    print_earthquake_table("地震测定报 (USGS)", rows, source_label)


def process_generic_eew(data, source_key, source_label, data_type):
    event_id = safe_get(data, 'eventId', 'id', default='')
    if not event_id or event_id in processed_events:
        return
    processed_events.add(event_id)
    play_sound(SOUND_ALERT, is_nhk=False)

    rows = []
    rows.append(["发震时刻", safe_get(data, 'shockTime', 'OriginTime', 'origin_time')])
    rows.append(["震中位置", safe_get(data, 'placeName', 'Hypocenter', 'region_name')])
    lat = safe_get(data, 'latitude', 'Latitude')
    lon = safe_get(data, 'longitude', 'Longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'magnitude', 'Magunitude')])
    rows.append(["深度(km)", safe_get(data, 'depth', 'Depth')])
    rows.append(["最大震度/烈度", get_intensity_display(data, 'cenc')])

    print_earthquake_table(f"地震报告 ({data_type})", rows, source_label)


# ---------- 统一入口 ----------
def process_eew(data, source_key, default_type=None):
    data_type = data.get('type')
    if data_type is None and default_type is not None:
        data_type = default_type
    if not data_type:
        return

    if source_key in FILTER_DETAIL:
        if data_type in FILTER_DETAIL[source_key]:
            if not FILTER_DETAIL[source_key][data_type]:
                return
    if not FILTER_CONFIG.get(data_type, True):
        return

    if source_key == 'fan':
        source_label = f"{SOURCE_DISPLAY['fan']} ({data_type})"
        process_fan_data(data, data_type, source_label)
        return
    elif source_key == 'p2pjson':
        source_label = SOURCE_DISPLAY.get(source_key, source_key)
        if data_type == 'jma':
            process_jma_eew(data, source_key, source_label)
        else:
            process_generic_eew(data, source_key, source_label, data_type)
        return

    source_label = SOURCE_DISPLAY.get(source_key, source_key)

    if data_type == 'jma':
        process_jma_eew(data, source_key, source_label)
    elif data_type == 'cenc':
        process_cenc_eew(data, source_key, source_label)
    elif data_type == 'sc':
        process_sc_eew(data, source_key, source_label)
    elif data_type == 'fj':
        process_fj_eew(data, source_key, source_label)
    elif data_type == 'cq':
        process_cq_eew(data, source_key, source_label)
    elif data_type == 'cea':
        process_cea_eew(data, source_key, source_label)
    elif data_type == 'cwa-eew':
        process_cwa_eew(data, source_key, source_label)
    elif data_type == 'cwa':
        process_cwa_report(data, source_key, source_label)
    elif data_type == 'yunnan':
        process_provincial_eew(data, source_key, source_label, '云南')
    elif data_type == 'ningxia':
        process_provincial_eew(data, source_key, source_label, '宁夏')
    elif data_type == 'guangxi':
        process_provincial_eew(data, source_key, source_label, '广西')
    elif data_type == 'shanxi':
        process_provincial_eew(data, source_key, source_label, '山西')
    elif data_type == 'beijing':
        process_provincial_eew(data, source_key, source_label, '北京')
    elif data_type == 'cea-pr':
        process_provincial_eew(data, source_key, source_label, '省级')
    elif data_type == 'hko':
        process_hko_eew(data, source_key, source_label)
    elif data_type == 'usgs':
        process_usgs_eew(data, source_key, source_label)
    else:
        if data and isinstance(data, dict):
            process_generic_eew(data, source_key, source_label, data_type)
        elif DEBUG:
            console.print(f"[dim]未处理的类型: {data_type} 来自 {source_key}[/dim]")


# ---------- P2P JSON API 专用处理函数 ----------
def process_p2p_quake(data):
    """
    处理 P2P JSON API 的地震信息 (code=551)
    支持两种数据来源：
    1. WebSocket 推送：顶层包含 id, issue, earthquake, points 等
    2. 历史接口：顶层也是完整的 JMAQuake 对象
    """
    try:
        # 从顶层提取基本字段
        quake_id = data.get('id') or data.get('_id')
        if not quake_id:
            if DEBUG:
                console.print("[dim]P2P 地震信息缺少 id，跳过[/dim]")
            return

        # 去重（基于 id）
        if quake_id in processed_events:
            if DEBUG:
                console.print(f"[dim]P2P 地震信息已处理过 (id={quake_id})，跳过[/dim]")
            return
        processed_events.add(quake_id)

        # 提取 issue 和 earthquake
        issue = data.get('issue', {})
        earthquake = data.get('earthquake', {})
        issue_type = issue.get('type', '')

        # 提取震源信息
        hypocenter = earthquake.get('hypocenter', {})
        max_scale = earthquake.get('maxScale', -1)
        max_intensity = scale_to_jma(max_scale)

        # 发震时刻：优先用 earthquake.time，否则用顶层 time
        origin_time = earthquake.get('time') or data.get('time', '')

        # 构建通用字段
        rows = []
        rows.append(["发震时刻", origin_time])
        rows.append(["震中位置", hypocenter.get('name', '未知')])
        lat = hypocenter.get('latitude')
        lon = hypocenter.get('longitude')
        if lat and lon and lat != -200 and lon != -200:
            rows.append(["坐标", f"{lat}, {lon}"])
        else:
            rows.append(["坐标", "不明"])
        rows.append(["震级(M)", hypocenter.get('magnitude', -1)])
        rows.append(["深度(km)", hypocenter.get('depth', 'N/A')])

        # 处理不同类型的 551 消息
        if issue_type == 'ScalePrompt':
            # 震度速报：无震源详细信息，但有 points 区域列表
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", "震度速报 (ScalePrompt)"])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])

            # 显示受影响区域
            points = data.get('points', [])
            if points:
                area_list = []
                for p in points[:10]:  # 最多显示10条
                    pref = p.get('pref', '')
                    addr = p.get('addr', '')
                    scale = scale_to_jma(p.get('scale', -1))
                    area_list.append(f"{pref} {addr} (震度{scale})")
                if len(points) > 10:
                    area_list.append(f"... 共 {len(points)} 个区域")
                rows.append(["受影响区域", '\n'.join(area_list)])
            else:
                rows.append(["受影响区域", "无"])

            title = "P2P 震度速报 (ScalePrompt)"

        elif issue_type in ('DetailScale', 'ScaleAndDestination', 'Destination'):
            # 详细地震信息
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", issue_type])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])

            # 显示观测点震度列表
            points = data.get('points', [])
            if points:
                area_list = []
                for p in points[:10]:
                    pref = p.get('pref', '')
                    addr = p.get('addr', '')
                    scale = scale_to_jma(p.get('scale', -1))
                    area_list.append(f"{pref} {addr} (震度{scale})")
                if len(points) > 10:
                    area_list.append(f"... 共 {len(points)} 个观测点")
                rows.append(["震度观测点", '\n'.join(area_list)])
            else:
                rows.append(["震度观测点", "无"])

            # 津波信息
            domestic = earthquake.get('domesticTsunami', '')
            foreign = earthquake.get('foreignTsunami', '')
            if domestic:
                rows.append(["国内津波", domestic])
            if foreign:
                rows.append(["海外津波", foreign])

            title = "P2P 地震情報 (JMA)"

        else:
            # 其他类型（如 Foreign 等），通用处理
            rows.append(["最大震度", max_intensity])
            rows.append(["信息类型", issue_type or "不明"])
            rows.append(["発表元", issue.get('source', 'N/A')])
            rows.append(["発表時刻", issue.get('time', 'N/A')])
            title = f"P2P 地震情報 ({issue_type or 'Unknown'})"

        print_earthquake_table(title, rows, "P2P JSON API")
        play_sound(SOUND_ALERT, is_nhk=False)

    except Exception as e:
        console.print(f"[red]P2P 地震处理异常: {e}[/red]")


def process_p2p_tsunami(data):
    """处理 P2P JSON API 的海啸预报 (code=552)"""
    try:
        if data.get('cancelled', False):
            console.print("[yellow]P2P 海啸预报已取消[/yellow]")
            return
        issue = data.get('issue', {})
        areas = data.get('areas', [])
        rows = []
        rows.append(["発表元", issue.get('source', 'N/A')])
        rows.append(["発表時刻", issue.get('time', 'N/A')])
        if not areas:
            rows.append(["予報区", "なし"])
        else:
            for area in areas:
                grade = area.get('grade', 'Unknown')
                name = area.get('name', '')
                immediate = area.get('immediate', False)
                max_height = area.get('maxHeight', {})
                height_desc = max_height.get('description', 'N/A')
                rows.append(["種別", grade])
                rows.append(["予報区", name])
                rows.append(["直ちに来襲", "はい" if immediate else "いいえ"])
                rows.append(["最大波高", height_desc])
        print_earthquake_table("P2P 津波予報", rows, "P2P JSON API")
        play_sound(SOUND_ALERT, is_nhk=False)
    except Exception as e:
        console.print(f"[red]P2P 海啸解析错误: {e}[/red]")


def process_p2p_eew(data):
    """处理 P2P JSON API 的紧急地震速报 (code=556)"""
    try:
        if data.get('cancelled', False):
            console.print("[yellow]P2P 紧急地震速报已取消[/yellow]")
            return
        quake = data.get('earthquake', {})
        issue = data.get('issue', {})
        areas = data.get('areas', [])
        rows = []
        rows.append(["発表時刻", issue.get('time', 'N/A')])
        rows.append(["イベントID", issue.get('eventId', 'N/A')])
        rows.append(["連番", issue.get('serial', 'N/A')])
        rows.append(["テスト", "はい" if data.get('test', False) else "いいえ"])

        if quake:
            hypocenter = quake.get('hypocenter', {})
            rows.append(["発震時刻", quake.get('originTime', 'N/A')])
            rows.append(["到達時刻", quake.get('arrivalTime', 'N/A')])
            rows.append(["震央地名", hypocenter.get('name', 'N/A')])
            rows.append(["短縮地名", hypocenter.get('reduceName', 'N/A')])
            rows.append(["緯度", hypocenter.get('latitude', 'N/A')])
            rows.append(["経度", hypocenter.get('longitude', 'N/A')])
            rows.append(["深さ(km)", hypocenter.get('depth', 'N/A')])
            rows.append(["マグニチュード", hypocenter.get('magnitude', 'N/A')])
        else:
            rows.append(["地震情報", "なし"])

        if areas:
            for area in areas:
                pref = area.get('pref', '')
                name = area.get('name', '')
                scale_from = scale_to_jma(area.get('scaleFrom', -1))
                scale_to = scale_to_jma(area.get('scaleTo', -1))
                kind = area.get('kindCode', '')
                rows.append([f"地域: {pref} {name}", f"予測震度: {scale_from}～{scale_to} (種別:{kind})"])
        else:
            rows.append(["予測地域", "なし"])

        print_earthquake_table("P2P 緊急地震速報", rows, "P2P JSON API")
        play_sound(SOUND_NHK, is_nhk=True)
    except Exception as e:
        console.print(f"[red]P2P EEW 解析错误: {e}[/red]")


def process_p2p_userquake(data):
    """处理 P2P JSON API 的地震感知情報 (code=561)"""
    try:
        area_code = data.get('area', -1)
        rows = []
        rows.append(["地域コード", str(area_code)])
        rows.append(["受信時刻", data.get('time', 'N/A')])
        print_earthquake_table("P2P 地震感知情報", rows, "P2P JSON API")
        play_sound(SOUND_ALERT, is_nhk=False)
    except Exception as e:
        console.print(f"[red]P2P 感知情報解析错误: {e}[/red]")


# ---------- 气象预警 ----------
def process_weather_warning(data, source_key):
    try:
        rows = []
        rows.append(["预警标题", safe_get(data, 'title', 'headline')])
        rows.append(["预警类型", data.get('type', 'N/A')])
        rows.append(["生效时间", data.get('effective', 'N/A')])
        desc = data.get('description', '')
        rows.append(["预警内容", desc[:200] + ("..." if len(desc) > 200 else "")])
        lat = data.get('latitude')
        lon = data.get('longitude')
        rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])

        if rows:
            print_weather_table("气象预警 (中国气象局)", rows, SOURCE_DISPLAY.get(source_key, source_key))
            play_sound(SOUND_ALERT, is_nhk=False)
    except Exception as e:
        console.print(f"[red]气象预警解析错误: {e}[/red]")


# ---------- 快照 ----------
def fetch_initial_snapshots():
    console.print("[dim]正在获取启动快照...[/dim]")
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
                    data['type'] = source_key
                    process_eew(data, 'wolfx')
        except Exception:
            pass

    # 从 P2P JSON API 获取快照
    try:
        p2pjson_url = "https://api.p2pquake.net/v2/history?codes=551&limit=3"
        response = requests.get(p2pjson_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                for quake in data[:3]:
                    process_p2p_quake(quake)
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


# ---------- EPSPClient (已弃用，保留但不启动) ----------
class EPSPClient:
    def __init__(self):
        self.servers = ['www.p2pquake.net', 'p2pquake.info', 'p2pquake.xyz', 'p2pquake.ddo.jp']
        self.port = 6910
        self.running = True
        self.sock = None
        self.peer_id = None
        self.region_code = 901
        self.connected_peers = {}
        self.lock = threading.Lock()
        self.server_index = 0
        self.recv_buffer = ""
        self.listener = None
        self.listener_thread = None
        self.max_connections = 20

    def start(self):
        pass


# ---------- P2P JSON API v2 WebSocket ----------
def on_p2pjson_message(ws, message):
    if not SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]P2P JSON 原始数据: {data}[/dim]")

        # 标记连接成功（如果尚未标记）
        if ws_status.get('p2pjson') != 'connected':
            msg_type = data.get('type')
            if msg_type not in ('heartbeat', 'error', 'pong'):
                console.print("[green]P2P JSON API 已连接并接收数据[/green]")
                ws_status['p2pjson'] = 'connected'

        # 处理基于 type 的消息
        if 'type' in data:
            msg_type = data['type']
            if msg_type == 'welcome':
                console.print("[green]P2P JSON API 已连接[/green]")
                ws_status['p2pjson'] = 'connected'
            elif msg_type == 'heartbeat':
                if DEBUG:
                    console.print("[dim]P2P JSON 心跳[/dim]")
            elif msg_type == 'error':
                console.print(f"[red]P2P JSON 错误: {data.get('message', '未知错误')}[/red]")
            elif msg_type == 'earthquake':
                quake = data.get('earthquake', {})
                if quake:
                    # 构建完整对象传递给 process_p2p_quake
                    full_quake = {
                        'id': data.get('id'),
                        '_id': data.get('id'),
                        'earthquake': quake,
                        'issue': data.get('issue', {}),
                        'points': data.get('points', []),
                        'time': data.get('time', ''),
                        'comments': data.get('comments', {})
                    }
                    process_p2p_quake(full_quake)
            else:
                if DEBUG:
                    console.print(f"[dim]未知 P2P JSON 消息类型: {msg_type}[/dim]")
        # 处理基于 code 的消息
        elif 'code' in data:
            code = data.get('code')
            if code == 551:
                if DEBUG:
                    console.print("[dim]收到 P2P 地震信息 (code=551)[/dim]")
                # 直接传递整个 data 对象
                process_p2p_quake(data)
            elif code == 552:
                if DEBUG:
                    console.print("[dim]收到 P2P 海啸预报 (code=552)[/dim]")
                process_p2p_tsunami(data)
            elif code == 555:
                if DEBUG:
                    console.print("[dim]收到 P2P 感知信息/节点分布 (code=555)[/dim]")
            elif code == 556:
                if DEBUG:
                    console.print("[dim]收到 P2P 紧急地震速报 (code=556)[/dim]")
                process_p2p_eew(data)
            elif code == 561:
                if DEBUG:
                    console.print("[dim]收到 P2P 地震感知情報 (code=561)[/dim]")
                process_p2p_userquake(data)
            else:
                if DEBUG:
                    console.print(f"[dim]收到 P2P 未处理 code={code}[/dim]")
        else:
            if DEBUG:
                console.print("[dim]P2P JSON 未知格式消息[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]P2P JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]P2P JSON 处理异常: {e}[/red]")


def on_p2pjson_error(ws, error):
    if "429" in str(error):
        console.print("[red]P2P JSON 请求过于频繁 (429)，已启动退避重连[/red]")
    else:
        console.print(f"[red]P2P JSON WebSocket 错误: {error}[/red]")


def on_p2pjson_close(ws, close_status_code, close_msg):
    global p2pjson_reconnect_delay
    console.print("[yellow]P2P JSON 连接已关闭[/yellow]")
    if ws_running and SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        delay = p2pjson_reconnect_delay
        console.print(f"[dim]将在 {delay} 秒后尝试重连[/dim]")
        threading.Timer(delay, start_p2pjson_websocket).start()
        p2pjson_reconnect_delay = min(p2pjson_reconnect_delay * 2, 300)


def on_p2pjson_open(ws):
    global p2pjson_reconnect_delay
    p2pjson_reconnect_delay = 5
    console.print("[green]P2P JSON WebSocket 已连接，正在订阅...[/green]")
    subscribe_msg = '{"type":"subscribe","topic":"all"}'
    ws.send(subscribe_msg)
    if DEBUG:
        console.print(f"[dim]发送订阅: {subscribe_msg}[/dim]")


def start_p2pjson_websocket():
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 P2P JSON[/red]")
        return
    if not SOURCE_CONFIG.get('p2pjson', {}).get('enabled', True):
        return
    url = SOURCE_CONFIG['p2pjson']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_p2pjson_open,
            on_message=on_p2pjson_message,
            on_error=on_p2pjson_error,
            on_close=on_p2pjson_close
        )
        ws_connections['p2pjson'] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]P2P JSON WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_p2pjson_websocket()


# ---------- NIED WebSocket ----------
def on_nied_message(ws, message):
    if not SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]NIED 原始数据: {data}[/dim]")
        msg_type = data.get('type')
        if msg_type == 'welcome':
            ws_status['nied'] = 'connected'
        elif msg_type == 'heartbeat':
            if DEBUG:
                console.print("[dim]NIED 心跳[/dim]")
        elif msg_type == 'update':
            inner_data = data.get('data')
            if not inner_data or not isinstance(inner_data, dict):
                if DEBUG:
                    console.print("[dim]NIED update 无有效数据，跳过[/dim]")
                return
            magunitude = inner_data.get('magunitude')
            region_name = inner_data.get('region_name')
            if (magunitude is None or magunitude == '' or magunitude == 'N/A') and \
                    (region_name is None or region_name == '' or region_name == '未知'):
                if DEBUG:
                    console.print(f"[dim]NIED 数据缺少震级或区域: mag={magunitude}, region={region_name}[/dim]")
                return
            report_id = inner_data.get('report_id')
            report_num = inner_data.get('report_num', '1')
            if report_id:
                report_key = f"nied_{report_id}_{report_num}"
            else:
                report_key = f"nied_{int(time.time())}"
            if report_key in processed_events:
                if DEBUG:
                    console.print(f"[dim]NIED 重复事件: {report_key}[/dim]")
                return
            processed_events.add(report_key)
            mapped = {
                "type": "jma",
                "EventID": report_id or f"NIED_{int(time.time())}",
                "OriginTime": inner_data.get('origin_time') or inner_data.get('report_time', ''),
                "Hypocenter": region_name or '未知地区',
                "Magunitude": magunitude if magunitude and magunitude != 'N/A' else 'N/A',
                "Depth": inner_data.get('depth', 'N/A'),
                "MaxIntensity": inner_data.get('calcintensity', 'N/A'),
                "isFinal": inner_data.get('is_final', False),
                "Latitude": float(inner_data['latitude']) if inner_data.get('latitude') and inner_data[
                    'latitude'] != 'N/A' else None,
                "Longitude": float(inner_data['longitude']) if inner_data.get('longitude') and inner_data[
                    'longitude'] != 'N/A' else None,
                "Accuracy": {},
                "WarnArea": [],
                "Serial": int(report_num) if report_num.isdigit() else 1
            }
            process_eew(mapped, 'nied')
        elif msg_type == 'pong':
            if DEBUG:
                console.print("[dim]NIED Pong 响应[/dim]")
        else:
            if DEBUG:
                console.print(f"[dim]NIED 未知消息类型: {msg_type}[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]NIED JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]NIED 处理异常: {e}[/red]")


def on_nied_error(ws, error):
    console.print(f"[red]NIED WebSocket 错误: {error}[/red]")


def on_nied_close(ws, close_status_code, close_msg):
    console.print("[yellow]NIED 连接已关闭，5秒后重连...[/yellow]")
    if ws_running and SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        time.sleep(5)
        start_nied_websocket()


def on_nied_open(ws):
    console.print("[green]NIED WebSocket 已连接[/green]")
    ws_status['nied'] = 'connected'


def start_nied_websocket():
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 NIED[/red]")
        return
    if not SOURCE_CONFIG.get('nied', {}).get('enabled', True):
        return
    url = SOURCE_CONFIG['nied']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_nied_open,
            on_message=on_nied_message,
            on_error=on_nied_error,
            on_close=on_nied_close
        )
        ws_connections['nied'] = ws
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]NIED WebSocket 启动失败: {e}[/red]")
        if ws_running:
            time.sleep(5)
            start_nied_websocket()


# ---------- FAN Studio ----------
def on_fan_message(ws, message):
    if not SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]FAN 原始数据: {data}[/dim]")
        msg_type = data.get('type')
        if msg_type == 'initial_all' or msg_type == 'query_response':
            for sub_key, sub_data in data.items():
                if sub_key in ('type', 'md5'):
                    continue
                if isinstance(sub_data, dict) and 'Data' in sub_data:
                    if sub_key == 'weatheralarm':
                        # 处理气象预警
                        item_data = sub_data.get('Data')
                        if item_data and isinstance(item_data, dict):
                            process_weather_warning(item_data, 'fan')
                        continue
                    if sub_key == 'tsunami':
                        item_data = sub_data.get('Data')
                        if item_data and isinstance(item_data, dict):
                            process_tsunami(item_data, source_label='FAN Studio (tsunami)')
                        continue
                    if sub_key in FILTER_DETAIL.get('fan', {}):
                        if not FILTER_DETAIL['fan'][sub_key]:
                            if DEBUG:
                                console.print(f"[dim]FAN 子源 {sub_key} 已禁用，跳过[/dim]")
                            continue
                    item_data = sub_data['Data']
                    if item_data and isinstance(item_data, dict):
                        mapped_data = {
                            "type": sub_key,
                            **item_data
                        }
                        process_eew(mapped_data, 'fan')
        elif msg_type == 'update':
            source = data.get('source')
            if source:
                if source == 'weatheralarm':
                    item_data = data.get('Data')
                    if item_data and isinstance(item_data, dict):
                        process_weather_warning(item_data, 'fan')
                    return
                elif source == 'tsunami':
                    item_data = data.get('Data')
                    if item_data and isinstance(item_data, dict):
                        process_tsunami(item_data, source_label='FAN Studio (tsunami)')
                    return
                if source in FILTER_DETAIL.get('fan', {}):
                    if not FILTER_DETAIL['fan'][source]:
                        if DEBUG:
                            console.print(f"[dim]FAN 子源 {source} 已禁用，跳过更新[/dim]")
                        return
                item_data = data.get('Data')
                if item_data and isinstance(item_data, dict):
                    mapped_data = {
                        "type": source,
                        **item_data
                    }
                    process_eew(mapped_data, 'fan')
        elif msg_type == 'heartbeat':
            if DEBUG:
                console.print("[dim]FAN 心跳[/dim]")
        else:
            if DEBUG:
                console.print(f"[dim]FAN 未知消息类型: {msg_type}[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]FAN JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]FAN 处理异常: {e}[/red]")


def on_fan_error(ws, error):
    console.print(f"[red]FAN WebSocket 错误: {error}[/red]")


def on_fan_close(ws, close_status_code, close_msg):
    global fan_last_reconnect_time
    console.print("[yellow]FAN 连接已关闭[/yellow]")
    fan_last_reconnect_time = time.time()
    if ws_running and SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        console.print(f"[dim]FAN 将在 {FAN_RECONNECT_DELAY // 60} 分钟后尝试重连[/dim]")
        threading.Timer(FAN_RECONNECT_DELAY, start_fan_websocket).start()


def on_fan_open(ws):
    console.print("[green]FAN Studio (地震) 已连接[/green]")
    ws_status['fan'] = 'connected'


def start_fan_websocket():
    global fan_last_reconnect_time
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 FAN[/red]")
        return
    if not SOURCE_CONFIG.get('fan', {}).get('enabled', True):
        return
    elapsed = time.time() - fan_last_reconnect_time
    if elapsed < FAN_RECONNECT_DELAY and fan_last_reconnect_time > 0:
        remaining = int(FAN_RECONNECT_DELAY - elapsed)
        console.print(f"[yellow]FAN 重连冷却中，剩余 {remaining // 60} 分钟[/yellow]")
        return
    url = SOURCE_CONFIG['fan']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_fan_open,
            on_message=on_fan_message,
            on_error=on_fan_error,
            on_close=on_fan_close
        )
        ws_connections['fan'] = ws
        fan_last_reconnect_time = 0
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]FAN WebSocket 启动失败: {e}[/red]")
        if ws_running:
            fan_last_reconnect_time = time.time()
            threading.Timer(FAN_RECONNECT_DELAY, start_fan_websocket).start()


# ---------- Wolfx WebSocket (已禁用，保留占位) ----------
def on_message_factory(source_key):
    def on_message(ws, message):
        if not SOURCE_CONFIG.get(source_key, {}).get('enabled', True):
            return
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                return
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
    global DEBUG, SOURCE_CONFIG, FILTER_DETAIL, EXPORT_ENABLED, EXPORT_FILE, EXPORT_FILE_PATH
    parts = cmd.split()
    if not parts:
        return

    def _stop_source(target):
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return False
        if not SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于停用状态[/yellow]")
            return False
        SOURCE_CONFIG[target]['enabled'] = False
        console.print(f"[yellow]{target} 已停用[/yellow]")
        if target in ws_connections:
            try:
                ws_connections[target].close()
            except:
                pass
        if target == 'p2p' and 'epsp_client' in globals():
            epsp_client.running = False
            if epsp_client.sock:
                try:
                    epsp_client.sock.close()
                except:
                    pass
        return True

    def _enable_source(target):
        if target not in SOURCE_CONFIG:
            console.print(f"[yellow]未知数据源: {target}[/yellow]")
            return False
        if SOURCE_CONFIG[target]['enabled']:
            console.print(f"[yellow]{target} 已经处于启用状态[/yellow]")
            return False
        SOURCE_CONFIG[target]['enabled'] = True
        console.print(f"[green]{target} 已启用，正在连接...[/green]")
        if target == 'p2p':
            epsp_client.start()
        elif target == 'p2pjson':
            threading.Thread(target=start_p2pjson_websocket, daemon=True).start()
        elif target == 'nied':
            threading.Thread(target=start_nied_websocket, daemon=True).start()
        elif target == 'fan':
            threading.Thread(target=start_fan_websocket, daemon=True).start()
        else:
            threading.Thread(target=start_websocket, args=(target,), daemon=True).start()
        return True

    if parts[0] == 'help':
        console.print("[cyan]可用命令:[/cyan]")
        console.print("  test                          - 模拟地震多报演示")
        console.print("  debug [on|off]                - 开启/关闭调试模式")
        console.print("  export on/off                 - 开启/关闭表格导出到CSV")
        console.print("  export path <文件路径>        - 设置导出文件路径（相对路径）")
        console.print("  stop <source>                 - 停用数据源 (wolfx/p2p/p2pjson/nied/fan/all)")
        console.print("  stop <source>/<subtype>       - 停用子源 (如 stop fan/cenc)")
        console.print("  stop <source>/all             - 停用该数据源所有子源 (如 stop fan/all)")
        console.print("  enable <source>               - 启用数据源")
        console.print("  enable <source>/<subtype>     - 启用子源")
        console.print("  enable <source>/all           - 启用该数据源所有子源 (如 enable fan/all)")
        console.print("  restart <source>              - 重启数据源 (或 restart all)")
        console.print("  reset                         - 一键恢复所有配置到默认状态并自动重连")
        console.print("  status                        - 查看所有数据源状态")
        console.print("  help                          - 显示此帮助")
        console.print("[dim]快捷键: Ctrl+C 退出[/dim]")
        return

    elif parts[0] == 'test':
        run_mock_test()
        return

    elif parts[0] == 'debug':
        if len(parts) == 1:
            DEBUG = not DEBUG
            console.print(f"[dim]调试模式: {'开启' if DEBUG else '关闭'}[/dim]")
        elif len(parts) == 2:
            if parts[1] == 'on':
                DEBUG = True
                console.print("[dim]调试模式: 开启[/dim]")
            elif parts[1] == 'off':
                DEBUG = False
                console.print("[dim]调试模式: 关闭[/dim]")
            else:
                console.print("[yellow]用法: debug [on|off] 或 debug (切换)[/yellow]")
        return

    elif parts[0] == 'export':
        if len(parts) < 2:
            console.print("[yellow]用法: export on / export off / export path <文件路径>[/yellow]")
            return
        if parts[1] == 'on':
            EXPORT_ENABLED = True
            console.print("[green]表格导出已开启[/green]")
            if EXPORT_FILE_PATH:
                console.print(f"[dim]目标文件: {EXPORT_FILE_PATH}[/dim]")
            else:
                console.print("[dim]未指定路径，将自动生成文件名。使用 'export path <路径>' 设置。[/dim]")
        elif parts[1] == 'off':
            EXPORT_ENABLED = False
            if EXPORT_FILE:
                EXPORT_FILE.close()
                EXPORT_FILE = None
            console.print("[yellow]表格导出已关闭[/yellow]")
        elif parts[1] == 'path':
            if len(parts) < 3:
                console.print("[yellow]用法: export path <文件路径>[/yellow]")
                return
            raw_path = parts[2]
            if not os.path.isabs(raw_path):
                prog_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                EXPORT_FILE_PATH = os.path.join(prog_dir, raw_path)
            else:
                EXPORT_FILE_PATH = raw_path
            config = load_config()
            config['export_path'] = EXPORT_FILE_PATH
            save_config(config)
            if EXPORT_FILE:
                EXPORT_FILE.close()
                EXPORT_FILE = None
            console.print(f"[green]导出路径已设置为: {EXPORT_FILE_PATH} (已保存配置)[/green]")
        else:
            console.print("[yellow]参数错误，请用 on / off / path[/yellow]")
        return

    elif parts[0] == 'stop':
        if len(parts) < 2:
            console.print("[yellow]用法: stop <source> 或 stop <source>/<subtype>[/yellow]")
            return
        target = parts[1]
        if '/' in target:
            src, sub = target.split('/', 1)
            if src not in FILTER_DETAIL or src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}[/yellow]")
                return
            if sub == 'all':
                for key in FILTER_DETAIL[src]:
                    FILTER_DETAIL[src][key] = False
                console.print(f"[yellow]{src} 所有子源已停用[/yellow]")
                return
            else:
                if sub not in FILTER_DETAIL[src]:
                    console.print(f"[yellow]未知的子源: {target}[/yellow]")
                    return
                if not FILTER_DETAIL[src][sub]:
                    console.print(f"[yellow]{src}/{sub} 已经处于停用状态[/yellow]")
                    return
                FILTER_DETAIL[src][sub] = False
                console.print(f"[yellow]{src}/{sub} 已停用[/yellow]")
                return
        else:
            if target == 'all':
                for key in SOURCE_CONFIG:
                    _stop_source(key)
                return
            else:
                _stop_source(target)
                return

    elif parts[0] == 'enable':
        if len(parts) < 2:
            console.print("[yellow]用法: enable <source> 或 enable <source>/<subtype>[/yellow]")
            return
        target = parts[1]
        if '/' in target:
            src, sub = target.split('/', 1)
            if src not in FILTER_DETAIL or src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}[/yellow]")
                return
            if sub == 'all':
                for key in FILTER_DETAIL[src]:
                    FILTER_DETAIL[src][key] = True
                console.print(f"[green]{src} 所有子源已启用[/green]")
                return
            else:
                if sub not in FILTER_DETAIL[src]:
                    console.print(f"[yellow]未知的子源: {target}[/yellow]")
                    return
                if FILTER_DETAIL[src][sub]:
                    console.print(f"[yellow]{src}/{sub} 已经处于启用状态[/yellow]")
                    return
                FILTER_DETAIL[src][sub] = True
                console.print(f"[green]{src}/{sub} 已启用[/green]")
                return
        else:
            if target == 'all':
                for key in SOURCE_CONFIG:
                    _enable_source(key)
                return
            else:
                _enable_source(target)
                return

    elif parts[0] == 'restart':
        if len(parts) < 2:
            console.print("[yellow]用法: restart <source> 或 restart all[/yellow]")
            return
        target = parts[1]
        sources = list(SOURCE_CONFIG.keys()) if target == 'all' else [target]
        for src in sources:
            if src not in SOURCE_CONFIG:
                console.print(f"[yellow]未知数据源: {src}，跳过[/yellow]")
                continue
            if SOURCE_CONFIG[src]['enabled']:
                _stop_source(src)
            _enable_source(src)
        return

    elif parts[0] == 'reset':
        SOURCE_CONFIG = {
            'wolfx': {
                'name': 'Wolfx',
                'url': 'wss://ws-api.wolfx.jp/all_eew',
                'enabled': False,
                'type': 'all',
                'need_subscribe': False,
                'fallback_urls': []
            },
            'p2p': {
                'name': 'P2PQuake (EPSP)',
                'enabled': False,
                'type': 'jma_only'
            },
            'p2pjson': {
                'name': 'P2PQuake (JSON API v2)',
                'url': 'wss://api.p2pquake.net/v2/ws',
                'enabled': True,
                'type': 'websocket',
                'need_subscribe': True,
                'subscribe_msg': '{"type":"subscribe","topic":"all"}'
            },
            'nied': {
                'name': 'NIED (日本防灾科学技术研究所)',
                'url': 'wss://sismotide.top/nied',
                'enabled': True,
                'type': 'jma_only',
                'need_subscribe': False,
                'fallback_urls': []
            },
            'fan': {
                'name': 'FAN Studio (地震)',
                'url': 'wss://ws.fanstudio.tech/all',
                'enabled': True,
                'type': 'all',
                'need_subscribe': False,
                'fallback_urls': ['wss://ws.fanstudio.hk/all']
            }
        }
        FILTER_DETAIL = {
            'wolfx': {
                'jma': True,
                'cenc': True,
                'sc': False,
                'fj': False,
                'cq': False
            },
            'p2p': {
                'jma': True
            },
            'p2pjson': {},
            'nied': {},
            'fan': {
                'cea': True,
                'cwa-eew': True,
                'jma': True,
                'cenc': True,
                'cwa': True,
                'cea-pr': False,
                'ningxia': False,
                'guangxi': False,
                'shanxi': False,
                'beijing': False,
                'yunnan': False,
                'hko': False,
                'usgs': False,
                'sa': False,
                'emsc': False,
                'bcsf': False,
                'gfz': False,
                'usp': False,
                'kma': False,
                'kma-eew': False,
                'fssn': False,
                'fssn-cmt': False,
            }
        }
        for sub in FAN_SUBTYPES:
            if sub not in FILTER_DETAIL['fan']:
                FILTER_DETAIL['fan'][sub] = False
        EXPORT_FILE_PATH = None
        save_config({})
        console.print("[dim]导出路径配置已重置[/dim]")
        console.print("[green]配置已恢复默认，正在重新连接所有数据源...[/green]")
        handle_command('restart all')
        return

    elif parts[0] == 'status':
        console.print("[cyan]当前数据源状态:[/cyan]")
        for key, config in SOURCE_CONFIG.items():
            status = "[green]启用[/green]" if config['enabled'] else "[red]停用[/red]"
            conn_status = "[green]已连接[/green]" if ws_status.get(key) == 'connected' else "[yellow]未连接[/yellow]"
            console.print(f"  {config['name']} ({key}): {status} | {conn_status}")
            if key in FILTER_DETAIL and FILTER_DETAIL[key]:
                for sub, enabled in FILTER_DETAIL[key].items():
                    sub_status = "[green]启用[/green]" if enabled else "[red]停用[/red]"
                    console.print(f"    └─ {sub}: {sub_status}")
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
    global ws_running, epsp_client, EXPORT_FILE, EXPORT_FILE_PATH

    if not WS_AVAILABLE:
        console.print("[red]错误: websocket-client 未安装，WebSocket 数据源将不可用[/red]")

    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.8.2 ==========[/bold yellow]")
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    if not os.path.exists(SOUND_NHK):
        console.print("[yellow]提示: 紧急铃声文件未找到，将无法播放。[/yellow]")

    config = load_config()
    if 'export_path' in config:
        EXPORT_FILE_PATH = config['export_path']
        console.print(f"[dim]加载导出路径配置: {EXPORT_FILE_PATH}[/dim]")

    console.print("[cyan]数据源: Wolfx(快照) + P2PQuake(JSON API) + NIED + FAN Studio(地震)[/cyan]")
    console.print("[cyan]按 Ctrl+C 退出[/cyan]")
    console.print("[cyan]输入 help 查看命令[/cyan]\n")

    fetch_initial_snapshots()

    if SOURCE_CONFIG.get('p2pjson', {}).get('enabled', False):
        ws_status['p2pjson'] = 'connecting'
        threading.Thread(target=start_p2pjson_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('fan', {}).get('enabled', False):
        ws_status['fan'] = 'connecting'
        threading.Thread(target=start_fan_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('nied', {}).get('enabled', False):
        ws_status['nied'] = 'connecting'
        threading.Thread(target=start_nied_websocket, daemon=True).start()
        time.sleep(1)

    epsp_client = EPSPClient()
    if SOURCE_CONFIG['p2p']['enabled']:
        ws_status['p2p'] = 'connecting'
        epsp_client.start()

    try:
        while True:
            if WINDOWS:
                cmd = check_user_command()
                if cmd:
                    handle_command(cmd)
            time.sleep(0.1)
    except KeyboardInterrupt:
        ws_running = False
        if 'epsp_client' in globals():
            epsp_client.running = False
        if EXPORT_FILE:
            EXPORT_FILE.close()
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)


if __name__ == "__main__":
    main()