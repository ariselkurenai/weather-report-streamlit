"""
机场气象报文解码 - Streamlit Web 应用
从 aviationweather.gov 获取 METAR 和 TAF 报文，解码后网页展示
"""

import streamlit as st
import requests
import json
import re
from datetime import datetime, timezone, timedelta

# ==================== ICAO 配置 ====================
ICAO_LIST = {
    "ZBAA - 北京首都": "ZBAA",
    "ZHHH - 武汉天河": "ZHHH",
    "ZSSS - 上海虹桥": "ZSSS",
    "ZGGG - 广州白云": "ZGGG",
    "ZUCK - 重庆江北": "ZUCK",
    "ZSPD - 上海浦东": "ZSPD",
    "EGLC - 伦敦城市": "EGLC",
    "KJFK - 纽约肯尼迪": "KJFK",
}

# 各机场当地时间偏移量（含夏令时，以当前季节为准）
LOCAL_OFFSET = {
    "ZBAA": 8, "ZHHH": 8, "ZSSS": 8, "ZGGG": 8, "ZUCK": 8, "ZSPD": 8,
    "EGLC": 1,   # BST (British Summer Time)
    "KJFK": -4,  # EDT (Eastern Daylight Time)
}


# ==================== 工具函数 ====================

def utc_to_local(utc_str, offset_hours):
    """将 UTC 时间字符串转换为指定时区的当地时间"""
    if not utc_str:
        return ""
    offset = timedelta(hours=offset_hours)
    try:
        utc_dt = datetime.strptime(utc_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
        local_dt = utc_dt.replace(tzinfo=timezone.utc) + offset
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            utc_dt = datetime.strptime(utc_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
            local_dt = utc_dt.replace(tzinfo=timezone.utc) + offset
            return local_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return utc_str


def decode_significant_change(raw_metar):
    if not raw_metar:
        return "未知"
    if "NOSIG" in raw_metar.upper():
        return "无显著变化"
    elif any(kw in raw_metar.upper() for kw in ["TEMPO", "BECMG", "PROB"]):
        return "有显著变化"
    else:
        return "无显著变化"


def utc_day_hour_to_local(day, hour, offset):
    """将 UTC (日, 时) 转换为当地 (日, 时)，处理跨日/跨月"""
    h = hour + offset
    d = day
    if h >= 24:
        h -= 24
        d += 1
    elif h < 0:
        h += 24
        d -= 1
    # TAF 中日数范围 1-31，超出则回绕
    if d > 31:
        d -= 31
    elif d < 1:
        d += 31
    return d, h


def parse_tx_tn_from_raw_taf(raw_taf, offset):
    """解析 TX/TN，时间转换为当地时间"""
    taf_upper = raw_taf.upper()
    result = []

    for prefix, label in [("TX", "最高温"), ("TN", "最低温")]:
        for m in re.findall(rf'{prefix}(\d+)/(\d{{2}})(\d{{2}})Z', taf_upper):
            temp = int(m[0])
            d_utc, h_utc = int(m[1]), int(m[2])
            d_loc, h_loc = utc_day_hour_to_local(d_utc, h_utc, offset)
            result.append({
                "温度": f"{temp}°C",
                "类型": label,
                "当地时间": f"{d_loc}日 {h_loc}:00"
            })

    tx_list = [r for r in result if r["类型"] == "最高温"]
    tn_list = [r for r in result if r["类型"] == "最低温"]
    return tx_list, tn_list


def parse_taf_valid_period(raw_taf, offset):
    """解析有效期，时间转换为当地时间"""
    if not raw_taf:
        return "", ""
    match = re.search(r'(?<!\w)(\d{2})(\d{2})/(\d{2})(\d{2})(?!\w)', raw_taf)
    if match:
        fd, fh, td, th = int(match[1]), int(match[2]), int(match[3]), int(match[4])
        d1, h1 = utc_day_hour_to_local(fd, fh, offset)
        d2, h2 = utc_day_hour_to_local(td, th, offset)
        return f"{d1}日 {h1}:00", f"{d2}日 {h2}:00"
    return "", ""


# ==================== 数据获取 ====================

@st.cache_data(ttl=300, show_spinner="正在获取 METAR 数据...")
def fetch_metar(icao):
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    metar = data[0]
    raw_ob = metar.get("rawOb", "")
    offset = LOCAL_OFFSET.get(icao, 0)

    return {
        "机场": metar.get("icaoId", ""),
        "原始报文": raw_ob,
        "报文时间": utc_to_local(metar.get("reportTime", ""), offset),
        "实际气温": f"{metar.get('temp', 'N/A')}°C" if metar.get('temp') is not None else "N/A",
        "露点温度": f"{metar.get('dewp', 'N/A')}°C" if metar.get('dewp') is not None else "N/A",
        "未来2小时变化": decode_significant_change(raw_ob),
    }


@st.cache_data(ttl=300, show_spinner="正在获取 TAF 数据...")
def fetch_taf(icao):
    url = f"https://aviationweather.gov/api/data/taf?ids={icao}&format=json"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    taf = data[0]
    raw_taf = taf.get("rawTAF", "")
    offset = LOCAL_OFFSET.get(icao, 0)

    loc_from, loc_to = parse_taf_valid_period(raw_taf, offset)
    tx_list, tn_list = parse_tx_tn_from_raw_taf(raw_taf, offset)

    max_info = ""
    min_info = ""
    if tx_list:
        max_info = f"最高 {tx_list[0]['温度']}，预计出现时间：{tx_list[0]['当地时间']}"
    if tn_list:
        vals = [int(re.search(r'(\d+)', t['温度']).group(1)) for t in tn_list]
        idx = vals.index(min(vals))
        min_info = f"最低 {tn_list[idx]['温度']}，预计出现时间：{tn_list[idx]['当地时间']}"

    return {
        "机场": taf.get("icaoId", ""),
        "原始报文": raw_taf,
        "预报发布时间": utc_to_local(taf.get("issueTime", ""), offset),
        "预报有效期": f"{loc_from} 至 {loc_to}" if loc_from else "",
        "预报期内最高温": max_info,
        "预报期内最低温": min_info,
    }


# ==================== Streamlit UI ====================

st.set_page_config(page_title="机场气象报文解码", page_icon="🌤️", layout="wide")

# 缩小解码信息字体的 CSS
st.markdown("""
<style>
    div[data-testid="metric-container"] label p { font-size: 0.8rem !important; }
    div[data-testid="metric-container"] div[data-testid="metric-value"] { font-size: 1.2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("🌤️ 机场气象报文解码")
st.markdown("数据来源: [aviationweather.gov](https://aviationweather.gov)")

# 侧边栏
with st.sidebar:
    st.header("⚙️ 设置")
    selected = st.selectbox(
        "选择机场 (ICAO)",
        options=list(ICAO_LIST.keys()),
        index=0
    )
    icao = ICAO_LIST[selected]

    if st.button("🔄 刷新数据", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption("数据缓存 5 分钟，点击「刷新数据」立即获取最新报文")

# 获取并展示数据
try:
    metar = fetch_metar(icao)
    taf = fetch_taf(icao)

    col1, col2 = st.columns(2)

    # ===== METAR =====
    with col1:
        st.subheader("📋 METAR 航空例行天气报告")
        st.code(metar["原始报文"], language="text")

        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric("实际气温", metar["实际气温"])
        with m2: st.metric("露点温度", metar["露点温度"])
        with m3: st.metric("报文时间", metar["报文时间"][:16])
        with m4:
            c = metar["未来2小时变化"]
            st.metric("未来2小时", c, delta="✅" if "无" in c else "⚠️")

    # ===== TAF =====
    with col2:
        st.subheader("📋 TAF 终端机场天气预报")
        st.code(taf["原始报文"], language="text")

        t1, t2 = st.columns(2)
        with t1: st.metric("预报发布时间", taf["预报发布时间"][:16])
        with t2: st.metric("预报有效期", taf["预报有效期"])

        st.divider()

        t3, t4 = st.columns(2)
        with t3: st.metric("📈 预报期内最高温", taf["预报期内最高温"])
        with t4: st.metric("📉 预报期内最低温", taf["预报期内最低温"])

except requests.exceptions.RequestException as e:
    st.error(f"网络请求失败: {e}")
except json.JSONDecodeError as e:
    st.error(f"数据解析失败: {e}")
except Exception as e:
    st.error(f"发生错误: {e}")

st.divider()
st.caption(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
           f"数据来自 aviationweather.gov")
