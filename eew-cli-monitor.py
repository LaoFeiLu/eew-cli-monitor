import requests
import time
import sys
import os
import winsound
import random
import json
import threading
import socket
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
                return val  # 即使是空串也返回，不过滤
            return val
    return default


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
        'enabled': True,
        'type': 'jma_only'
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
    },
    'fanw': {
        'name': 'FAN Weather (气象预警)',
        'url': 'wss://ws.fanstudio.tech/weatheralarm',
        'enabled': True,
        'type': 'weather',
        'need_subscribe': False,
        'fallback_urls': []
    }
}

SOURCE_DISPLAY = {
    'wolfx': 'Wolfx',
    'p2p': 'P2PQuake (EPSP)',
    'nied': 'NIED',
    'fan': 'FAN Studio',
    'fanw': 'FAN Weather'
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
    },
    'fanw': {}
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

FAN_RECONNECT_DELAY = 1800
fan_last_reconnect_time = 0
FANW_RECONNECT_DELAY = 1800
fanw_last_reconnect_time = 0

processed_events = set()
high_intensity_state = {}
console = Console()
ws_running = True
ws_connections = {}
ws_status = {}


def print_earthquake_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold yellow")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    rows.append(["信号源", source_label])
    for row in rows:
        table.add_row(str(row[0]), str(row[1]))
    console.print(table)


def print_weather_table(title, rows, source_label):
    if not rows:
        return
    table = Table(title=title, box=box.ROUNDED, border_style="bold blue")
    table.add_column("项目", style="cyan", no_wrap=True, width=12)
    table.add_column("信息", style="white", no_wrap=False, width=48)
    rows.append(["信号源", source_label])
    for row in rows:
        table.add_row(str(row[0]), str(row[1]))
    console.print(table)


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
    rows.append(["最大震度/烈度", safe_get(data, 'epiIntensity', 'maxIntensity', 'MaxIntensity')])
    rows.append(["最终报", "是" if data.get('final', False) else "否"])
    rows.append(["取消报", "是" if data.get('cancel', False) else "否"])
    rows.append(["更新报数", str(data.get('updates', 1))])
    rows.append(["信息类型", safe_get(data, 'infoTypeName', 'info_type')])

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


# ---------- Wolfx 各处理函数（不过滤字段） ----------
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
    rows.append(["震中位置", safe_get(data, 'HypoCenter', 'Hypocenter', 'hypocenter', 'placeName')])  # 关键修正
    lat = safe_get(data, 'Latitude', 'latitude')
    lon = safe_get(data, 'Longitude', 'longitude')
    rows.append(["坐标", f"{lat}, {lon}" if lat and lon else '未知'])
    rows.append(["震级(M)", safe_get(data, 'Magunitude', 'magnitude')])
    rows.append(["深度(km)", safe_get(data, 'Depth', 'depth')])
    rows.append(["最大烈度(中国)", safe_get(data, 'MaxIntensity', 'max_intensity', 'epiIntensity')])
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
    rows.append(["最大烈度(中国)", safe_get(data, 'MaxIntensity', 'max_intensity')])
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
    rows.append(["最大烈度(中国)", safe_get(data, 'MaxIntensity', 'max_intensity')])

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
    rows.append(["最大烈度(中国)", safe_get(data, 'MaxIntensity', 'max_intensity')])

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
    rows.append(["预估烈度", safe_get(data, 'epiIntensity')])

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
    rows.append(["最大震度", safe_get(data, 'maxIntensity', 'MaxIntensity')])
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
    rows.append(["最大震度", safe_get(data, 'maxIntensity', 'MaxIntensity')])

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
    rows.append(["最大烈度", safe_get(data, 'maxIntensity', 'epiIntensity')])

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


# ---------- EPSPClient 修正版本 ----------
class EPSPClient:
    def __init__(self):
        self.servers = ['www.p2pquake.net', 'p2pquake.info', 'p2pquake.xyz', 'p2pquake.ddo.jp']
        self.port = 6910
        self.running = True
        self.sock = None
        self.peer_id = None
        self.region_code = 250      # 根据抓包调整为250（也可以保留901，但抓包显示250）
        self.connected_peers = {}
        self.lock = threading.Lock()
        self.server_index = 0
        self.recv_buffer = ""
        self.listener = None
        self.listener_thread = None
        self.max_connections = 20   # 可调整

    def start(self):
        self._start_listener()
        threading.Thread(target=self._run, daemon=True).start()

    def _start_listener(self):
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(('0.0.0.0', 6911))
            self.listener.listen(5)
            self.listener_thread = threading.Thread(target=self._listener_loop, daemon=True)
            self.listener_thread.start()
            if DEBUG:
                console.print("[dim]端口 6911 监听已启动[/dim]")
        except Exception as e:
            if DEBUG:
                console.print(f"[red]无法启动端口监听 (6911): {e}[/red]")

    def _listener_loop(self):
        while self.running:
            try:
                client, addr = self.listener.accept()
                client.close()
                if DEBUG:
                    console.print(f"[dim]收到连接检查请求，已关闭[/dim]")
            except Exception:
                break

    def _run(self):
        while self.running:
            host = self.servers[self.server_index % len(self.servers)]
            if DEBUG:
                console.print(f"[dim]尝试连接 P2PQuake (EPSP) 服务器: {host}:{self.port}[/dim]")
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10)
                self.sock.connect((host, self.port))
                if DEBUG:
                    console.print(f"[dim]已连接到 {host}:{self.port}[/dim]")
                self._send("131 1 0.38:EEW_CLI:2.0")
                if DEBUG:
                    console.print("[dim]发送协议版本: 131 1 0.38:EEW_CLI:2.0[/dim]")
                self._receive_loop()  # 阻塞直到连接断开
                # 断开后，如果 self.running 为 True，继续尝试下一个服务器
                if not self.running:
                    break
                self.server_index += 1
                time.sleep(3)
            except socket.timeout:
                if DEBUG:
                    console.print(f"[red]连接 {host} 超时[/red]")
                self.server_index += 1
                time.sleep(3)
            except Exception as e:
                if DEBUG:
                    console.print(f"[red]连接 {host} 失败: {e}[/red]")
                self.server_index += 1
                time.sleep(3)
            finally:
                # 确保套接字被关闭并置空
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None
        if not self.running:
            console.print("[red]P2PQuake (EPSP) 连接失败，已放弃[/red]")

    def _send(self, msg):
        if self.sock:
            try:
                full_msg = msg + "\r\n"
                self.sock.send(full_msg.encode('shift-jis'))
                if DEBUG:
                    console.print(f"[dim]发送: {msg}[/dim]")
            except Exception as e:
                console.print(f"[red]发送失败: {e}[/red]")

    def _send_connected_peers(self, peer_ids):
        if peer_ids:
            data = ":".join(peer_ids)
            self._send(f"155 1 {data}")
            if DEBUG:
                console.print(f"[dim]发送 155 已连接节点: {data}[/dim]")

    def _receive_loop(self):
        while self.running:
            try:
                if self.sock is None:
                    break
                data = self.sock.recv(4096)
                if not data:
                    if DEBUG:
                        console.print("[yellow]服务器关闭连接[/yellow]")
                    break
                self.recv_buffer += data.decode('shift-jis', errors='ignore')
                if DEBUG:
                    console.print(f"[dim]原始数据: {data[:200]}[/dim]")
                while '\r\n' in self.recv_buffer:
                    line, self.recv_buffer = self.recv_buffer.split('\r\n', 1)
                    if line.strip():
                        if DEBUG:
                            console.print(f"[dim]收到: {line}[/dim]")
                        self._handle_line(line)
            except socket.timeout:
                continue
            except OSError as e:
                # 套接字已关闭（如主动关闭或网络错误）
                if DEBUG:
                    console.print(f"[dim]套接字错误: {e}[/dim]")
                break
            except Exception as e:
                console.print(f"[red]接收错误: {e}[/red]")
                break
        # 不再递归调用 _run，只打印信息，由 _run 循环处理重连
        if self.running:
            console.print("[yellow]P2PQuake (EPSP) 连接已关闭，将尝试重连...[/yellow]")

    def _handle_line(self, line):
        try:
            parts = line.split(' ', 2)
            if len(parts) < 3:
                if DEBUG:
                    console.print(f"[dim]忽略格式错误行: {line}[/dim]")
                return
            code = parts[0]
            hop = parts[1]
            data = parts[2] if len(parts) > 2 else ''
            if DEBUG:
                console.print(f"[dim]处理代码 {code}, 数据: {data[:50]}[/dim]")

            if code == '295':
                # 密钥已分配或无需分配，忽略即可，继续处理后续消息
                if DEBUG:
                    console.print("[dim]服务器返回 295（密钥已分配），忽略[/dim]")
                return  # 也可以不 return，但 295 没有后续数据，直接返回安全

            if code == '212':
                if DEBUG:
                    console.print(f"[dim]服务器版本: {data}[/dim]")
                self._send("113 1")
            elif code == '233':
                self.peer_id = data
                if DEBUG:
                    console.print(f"[dim]临时ID: {self.peer_id}[/dim]")
                self._send(f"115 1 {self.peer_id}")
            elif code == '235':
                if DEBUG:
                    console.print(f"[dim]收到节点列表，长度: {len(data)}[/dim]")
                self._connect_to_peers(data)  # 内部会发送 155
                current_conn = len(self.connected_peers)
                self._send(f"116 1 {self.peer_id}:6911:{self.region_code}:{current_conn}:{self.max_connections}")
                if DEBUG:
                    console.print(
                        f"[dim]发送 116: {self.peer_id}:6911:{self.region_code}:{current_conn}:{self.max_connections}[/dim]")
            elif code == '236':
                console.print(f"[green]P2PQuake (EPSP) 已连接 (总节点数: {data})[/green]")
                ws_status['p2p'] = 'connected'
                # 先获取地域ピア数和协议时间（即使没有密钥）
                self._send("127 1")
                self._send("118 1")
                # 尝试获取密钥（如果返回 295 会被上面忽略）
                self._send(f"117 1 {self.peer_id}")
            elif code == '237':
                # 收到密钥，保存（这里可以提取密钥，但暂不使用）
                if DEBUG:
                    console.print("[dim]收到密钥[/dim]")
                # 可以解析密钥，但我们只做接收显示，不需要签名
            elif code == '247':
                # 地域ピア数（可忽略）
                if DEBUG:
                    console.print("[dim]收到地域ピア数[/dim]")
            elif code == '238':
                # 协议时间（可忽略）
                if DEBUG:
                    console.print("[dim]收到协议时间[/dim]")
            elif code == '551':
                self._handle_earthquake_data(data)
            elif code == '552':
                self._handle_tsunami_data(data)
            elif code == '555':
                self._handle_sensor_data(data)
            elif code == '561':
                self._handle_peer_count_data(data)
            elif code == '299':
                console.print("[red]P2PQuake (EPSP) IP 变化，重新连接[/red]")
                self.sock.close()
                self.server_index += 1
                self._run()
                return
            elif code == '298':
                if DEBUG:
                    console.print("[dim]收到协议警告 (298)，忽略[/dim]")
            else:
                if DEBUG:
                    console.print(f"[dim]忽略代码 {code}[/dim]")
        except Exception as e:
            console.print(f"[red]处理消息错误: {e}[/red]")
    def _connect_to_peers(self, peer_data):
        peers = peer_data.split(':')
        connected_ids = []
        for peer_info in peers:
            try:
                parts = peer_info.split(',')
                if len(parts) >= 3:
                    ip = parts[0]
                    port = int(parts[1])
                    pid = parts[2]
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    sock.connect((ip, port))
                    sock.send(b"614 1 0.38:EEW_CLI:2.0\r\n")
                    response = sock.recv(1024).decode('shift-jis', errors='ignore')
                    if response.startswith('634'):
                        sock.send(b"612 1\r\n")
                        id_response = sock.recv(1024).decode('shift-jis', errors='ignore')
                        if id_response.startswith('632'):
                            their_id = id_response.split(' ', 2)[2].strip()
                            with self.lock:
                                self.connected_peers[their_id] = sock
                                connected_ids.append(their_id)
                        else:
                            sock.close()
                    else:
                        sock.close()
            except Exception as e:
                if DEBUG:
                    console.print(f"[dim]连接节点 {peer_info} 失败: {e}[/dim]")
        # 发送 155 通知服务器已连接的节点 ID
        self._send_connected_peers(connected_ids)

    def _handle_earthquake_data(self, data):
        try:
            parts = data.split(':', 3)
            if len(parts) < 4:
                return
            signature, expiry, summary, detail = parts
            summary_parts = summary.split(',')
            if len(summary_parts) < 11:
                # 补齐
                while len(summary_parts) < 12:
                    summary_parts.append('N/A')
            origin_time = summary_parts[0]
            intensity = summary_parts[1]
            tsunami = summary_parts[2]
            info_type = summary_parts[3]
            source = summary_parts[4]
            depth = summary_parts[5]
            mag = summary_parts[6]
            correction = summary_parts[7]
            lat_dir = summary_parts[8]
            lat_val = summary_parts[9] if len(summary_parts) > 9 else ''
            lon_dir = summary_parts[10] if len(summary_parts) > 10 else ''
            lon_val = summary_parts[11] if len(summary_parts) > 11 else ''

            earthquake_data = {
                "type": "jma",
                "EventID": f"P2P_{int(time.time())}",
                "OriginTime": origin_time.replace('頃', ''),
                "Hypocenter": source,
                "Magunitude": mag,
                "Depth": depth,
                "MaxIntensity": intensity,
                "isFinal": True,
                "Latitude": self._parse_latlon(lat_dir, lat_val),
                "Longitude": self._parse_latlon(lon_dir, lon_val)
            }
            process_eew(earthquake_data, 'p2p')
        except Exception as e:
            console.print(f"[red]解析地震数据失败: {e}[/red]")

    def _handle_tsunami_data(self, data):
        try:
            parts = data.split(':', 2)
            if len(parts) < 3:
                return
            signature, expiry, detail = parts
            items = detail.split(',')
            rows = [["項目", "情報"]]
            rows.append(["種別", "海嘯預警"])
            for item in items:
                if item.startswith('-'):
                    rows.append(["予報種類", item[1:]])
                elif item.startswith('+') or item.startswith('*'):
                    rows.append(["予報区", item[1:]])
                elif item == "解除":
                    rows.append(["解除", "津波注意報等が解除されました"])
            table = Table(title="海嘯預警 (P2PQuake)", box=box.ROUNDED, border_style="bold red")
            table.add_column("項目", style="cyan", no_wrap=True, width=12)
            table.add_column("情報", style="white", no_wrap=False, width=48)
            for row in rows[1:]:
                table.add_row(row[0], row[1])
            console.print(table)
            play_sound(SOUND_ALERT, is_nhk=False)
        except Exception as e:
            console.print(f"[red]解析海嘯數據失敗: {e}[/red]")

    def _handle_sensor_data(self, data):
        try:
            parts = data.split(':', 5)
            if len(parts) < 6:
                return
            sensor_info = parts[5]
            console.print(f"[dim]收到地震感知情報: {sensor_info}[/dim]")
        except Exception as e:
            console.print(f"[red]解析感知情報失敗: {e}[/red]")

    def _handle_peer_count_data(self, data):
        try:
            parts = data.split(':', 2)
            if len(parts) < 3:
                return
            signature, expiry, peer_data = parts
            items = peer_data.split(';')
            eew_found = False
            for item in items:
                if ',' in item:
                    code, count = item.split(',')
                    if code == '950':
                        console.print("[bold red]緊急地震速報（警報）が発表されました！[/bold red]")
                        play_sound(SOUND_NHK, is_nhk=True)
                        eew_found = True
                    elif code == '951':
                        console.print("[bold yellow]緊急地震速報（配信試験）[/bold yellow]")
                        eew_found = True
                    elif code == '952':
                        console.print("[bold red]緊急地震速報（警報）部分配信[/bold red]")
                        play_sound(SOUND_NHK, is_nhk=True)
                        eew_found = True
                    elif code == '953':
                        console.print("[bold yellow]緊急地震速報（テスト）部分配信[/bold yellow]")
                        eew_found = True
                    elif code == '954':
                        console.print("[bold blue]緊急地震速報（警報）取消[/bold blue]")
                        eew_found = True
                    elif code == '955':
                        console.print("[bold cyan]緊急地震速報（続報）[/bold cyan]")
                        eew_found = True
            if not eew_found and DEBUG:
                console.print(f"[dim]各地域ピア数: {peer_data[:100]}[/dim]")
        except Exception as e:
            console.print(f"[red]解析ピア数失敗: {e}[/red]")

    def _parse_latlon(self, direction, value):
        if not value or value == '-1' or value == 'N/A':
            return None
        try:
            val = float(value)
            if direction == 'N' or direction == 'E':
                return val
            elif direction == 'S' or direction == 'W':
                return -val
            else:
                return val
        except:
            return None


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

        def delayed_connect():
            time.sleep(FAN_RECONNECT_DELAY)
            if ws_running and SOURCE_CONFIG.get('fan', {}).get('enabled', True):
                start_fan_websocket()

        threading.Thread(target=delayed_connect, daemon=True).start()


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


# ---------- FAN Weather ----------
def on_fanw_message(ws, message):
    if not SOURCE_CONFIG.get('fanw', {}).get('enabled', True):
        return
    try:
        data = json.loads(message)
        if DEBUG:
            console.print(f"[dim]FAN Weather 原始数据: {data}[/dim]")
        if 'Data' in data:
            weather_data = data.get('Data', {})
            if weather_data:
                process_weather_warning(weather_data, 'fanw')
        else:
            msg_type = data.get('type')
            if msg_type == 'welcome':
                console.print("[green]FAN Weather 已连接[/green]")
                ws_status['fanw'] = 'connected'
            elif msg_type == 'heartbeat':
                if DEBUG:
                    console.print("[dim]FAN Weather 心跳[/dim]")
    except json.JSONDecodeError as e:
        console.print(f"[red]FAN Weather JSON 解析错误: {e}[/red]")
    except Exception as e:
        console.print(f"[red]FAN Weather 处理异常: {e}[/red]")


def on_fanw_error(ws, error):
    console.print(f"[red]FAN Weather WebSocket 错误: {error}[/red]")


def on_fanw_close(ws, close_status_code, close_msg):
    global fanw_last_reconnect_time
    console.print("[yellow]FAN Weather 连接已关闭[/yellow]")
    fanw_last_reconnect_time = time.time()
    if ws_running and SOURCE_CONFIG.get('fanw', {}).get('enabled', True):
        console.print(f"[dim]FAN Weather 将在 {FANW_RECONNECT_DELAY // 60} 分钟后尝试重连[/dim]")

        def delayed_connect():
            time.sleep(FANW_RECONNECT_DELAY)
            if ws_running and SOURCE_CONFIG.get('fanw', {}).get('enabled', True):
                start_fanw_websocket()

        threading.Thread(target=delayed_connect, daemon=True).start()


def on_fanw_open(ws):
    console.print("[green]FAN Weather 已连接[/green]")
    ws_status['fanw'] = 'connected'


def start_fanw_websocket():
    global fanw_last_reconnect_time
    if not WS_AVAILABLE:
        console.print("[red]websocket-client 未安装，无法启动 FAN Weather[/red]")
        return
    if not SOURCE_CONFIG.get('fanw', {}).get('enabled', True):
        return
    elapsed = time.time() - fanw_last_reconnect_time
    if elapsed < FANW_RECONNECT_DELAY and fanw_last_reconnect_time > 0:
        remaining = int(FANW_RECONNECT_DELAY - elapsed)
        console.print(f"[yellow]FAN Weather 重连冷却中，剩余 {remaining // 60} 分钟[/yellow]")
        return
    url = SOURCE_CONFIG['fanw']['url']
    try:
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url,
            on_open=on_fanw_open,
            on_message=on_fanw_message,
            on_error=on_fanw_error,
            on_close=on_fanw_close
        )
        ws_connections['fanw'] = ws
        fanw_last_reconnect_time = 0
        ws.run_forever()
    except Exception as e:
        console.print(f"[red]FAN Weather WebSocket 启动失败: {e}[/red]")
        if ws_running:
            fanw_last_reconnect_time = time.time()
            threading.Timer(FANW_RECONNECT_DELAY, start_fanw_websocket).start()


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
    global DEBUG, SOURCE_CONFIG, FILTER_DETAIL
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
        elif target == 'nied':
            threading.Thread(target=start_nied_websocket, daemon=True).start()
        elif target == 'fan':
            threading.Thread(target=start_fan_websocket, daemon=True).start()
        elif target == 'fanw':
            threading.Thread(target=start_fanw_websocket, daemon=True).start()
        else:
            threading.Thread(target=start_websocket, args=(target,), daemon=True).start()
        return True

    if parts[0] == 'help':
        console.print("[cyan]可用命令:[/cyan]")
        console.print("  test                          - 模拟地震多报演示")
        console.print("  debug [on|off]                - 开启/关闭调试模式")
        console.print("  stop <source>                 - 停用数据源 (wolfx/p2p/nied/fan/fanw/all)")
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
                'enabled': True,
                'type': 'jma_only'
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
            },
            'fanw': {
                'name': 'FAN Weather (气象预警)',
                'url': 'wss://ws.fanstudio.tech/weatheralarm',
                'enabled': True,
                'type': 'weather',
                'need_subscribe': False,
                'fallback_urls': []
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
            },
            'fanw': {}
        }
        for sub in FAN_SUBTYPES:
            if sub not in FILTER_DETAIL['fan']:
                FILTER_DETAIL['fan'][sub] = False

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
    global ws_running, epsp_client

    if not WS_AVAILABLE:
        console.print("[red]错误: websocket-client 未安装，WebSocket 数据源将不可用[/red]")

    console.print("\n[bold yellow]========== Wolfx 地震预警命令行监控程序 v1.8.2 ==========[/bold yellow]")
    if not os.path.exists(SOUND_ALERT):
        console.print("[yellow]提示: 普通提示音文件未找到，将无法播放。[/yellow]")
    if not os.path.exists(SOUND_NHK):
        console.print("[yellow]提示: 紧急铃声文件未找到，将无法播放。[/yellow]")

    console.print("[cyan]数据源: Wolfx(快照) + P2PQuake(EPSP) + NIED + FAN Studio(地震) + FAN Weather(气象)[/cyan]")
    console.print("[cyan]按 Ctrl+C 退出[/cyan]")
    console.print("[cyan]输入 help 查看命令[/cyan]\n")

    fetch_initial_snapshots()

    if SOURCE_CONFIG.get('fan', {}).get('enabled', False):
        ws_status['fan'] = 'connecting'
        threading.Thread(target=start_fan_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('nied', {}).get('enabled', False):
        ws_status['nied'] = 'connecting'
        threading.Thread(target=start_nied_websocket, daemon=True).start()
        time.sleep(1)

    if SOURCE_CONFIG.get('fanw', {}).get('enabled', False):
        ws_status['fanw'] = 'connecting'
        threading.Thread(target=start_fanw_websocket, daemon=True).start()
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
        console.print("\n[bold red]程序已退出，感谢使用！[/bold red]")
        sys.exit(0)


if __name__ == "__main__":
    main()