"""
ZBAA/ZHHH 机场气象报文解码 - Streamlit Web 应用
从 aviationweather.gov 获取 METAR 和 TAF 报文，解码后网页展示
"""

import streamlit as st
import requests
import json
import re
from datetime import datetime, timezone, timedelta

# ==================== ICAO 列表 ====================
ICAO_LIST = {
    "ZBAA - 北京首都": "ZBAA",
    "ZHHH - 武汉天河": "ZHHH",
    "ZSSS - 上海虹桥": "ZSSS",
    "ZGGG - 广州白云": "ZGGG",
    "ZUCK - 重庆江北": "ZUCK",
    "ZSPD - 上海浦东": "ZSPD",
    "EGLL - 伦敦希思罗": "EGLL",
    "KJFK - 纽约肯尼迪": "KJFK",
}

BEIJING_OFFSET = timedelta(hours=8)


# ==================== 数据获取与解码函数 ====================

def utc_to_beijing(utc_str):
    if not utc_str:
        return ""
    try:
        utc_dt = datetime.strptime(utc_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
        beijing_dt = utc_dt.replace(tzinfo=timezone.utc) + BEIJING_OFFSET
        return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            utc_dt = datetime.strptime(utc_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
            beijing_dt = utc_dt.replace(tzinfo=timezone.utc) + BEIJING_OFFSET
            return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return utc_str


def decode_significant_change(raw_metar):
    if not raw_metar:
        return "未知"
    if "NOSIG" in raw_metar.upper():
        return "无显著变化"
    elif "TEMPO" in raw_metar.upper() or "BECMG" in raw_metar.upper() or "PROB" in raw_metar.upper():
        return "有显著变化"
    else:
        return "无显著变化"


def parse_tx_tn_from_raw_taf(raw_taf):
    taf_upper = raw_taf.upper()
    tx_list = []
    tx_pattern = re.findall(r'TX(\d+)/(\d{2})(\d{2})Z', taf_upper)
    for temp_str, day_str, hour_str in tx_pattern:
        temp = int(temp_str)
        day_utc = int(day_str)
        hour_utc = int(hour_str)
        tx_list.append({
            "温度": f"{temp}°C",
            "类型": "最高温",
            "北京时间": f"{day_utc}日 {hour_utc + 8}:00" if hour_utc + 8 < 24
                      else f"{day_utc + 1}日 {hour_utc + 8 - 24}:00"
        })

    tn_list = []
    tn_pattern = re.findall(r'TN(\d+)/(\d{2})(\d{2})Z', taf_upper)
    for temp_str, day_str, hour_str in tn_pattern:
        temp = int(temp_str)
        day_utc = int(day_str)
        hour_utc = int(hour_str)
        tn_list.append({
            "温度": f"{temp}°C",
            "类型": "最低温",
            "北京时间": f"{day_utc}日 {hour_utc + 8}:00" if hour_utc + 8 < 24
                      else f"{day_utc + 1}日 {hour_utc + 8 - 24}:00"
        })

    return tx_list, tn_list


def parse_taf_valid_period(raw_taf):
    if not raw_taf:
        return "", "", "", ""
    match = re.search(r'(?<!\w)(\d{2})(\d{2})/(\d{2})(\d{2})(?!\w)', raw_taf)
    if match:
        from_day, from_hour, to_day, to_hour = match.groups()
        fd, fh, td, th = int(from_day), int(from_hour), int(to_day), int(to_hour)

        utc_from = f"{fd}日 {fh}:00Z"
        utc_to = f"{td}日 {th}:00Z"

        def utc_to_bj_day(day, hour):
            bj_h = hour + 8
            bj_d = day
            if bj_h >= 24:
                bj_h -= 24
                bj_d += 1
            if bj_d > 31:
                bj_d -= 31
            return bj_d, bj_h

        bj_from_d, bj_from_h = utc_to_bj_day(fd, fh)
        bj_to_d, bj_to_h = utc_to_bj_day(td, th)

        bj_from = f"{bj_from_d}日 {bj_from_h}:00"
        bj_to = f"{bj_to_d}日 {bj_to_h}:00"

        return utc_from, utc_to, bj_from, bj_to
    return "", "", "", ""


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

    decoded = {
        "机场": metar.get("icaoId", ""),
        "原始报文": raw_ob,
        "报文时间 (北京时间)": utc_to_beijing(metar.get("reportTime", "")),
        "实际气温": f"{metar.get('temp', 'N/A')}°C" if metar.get('temp') is not None else "N/A",
        "露点温度": f"{metar.get('dewp', 'N/A')}°C" if metar.get('dewp') is not None else "N/A",
        "未来2小时变化": decode_significant_change(raw_ob),
    }
    return decoded


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

    utc_from, utc_to, bj_from, bj_to = parse_taf_valid_period(raw_taf)
    tx_list, tn_list = parse_tx_tn_from_raw_taf(raw_taf)

    max_temp_info = ""
    min_temp_info = ""
    if tx_list:
        max_temp_info = f"最高 {tx_list[0]['温度']}，预计出现时间（北京）：{tx_list[0]['北京时间']}"
    if tn_list:
        tn_values = [int(re.search(r'(\d+)', t['温度']).group(1)) for t in tn_list]
        min_idx = tn_values.index(min(tn_values))
        min_temp_info = f"最低 {tn_list[min_idx]['温度']}，预计出现时间（北京）：{tn_list[min_idx]['北京时间']}"

    decoded = {
        "机场": taf.get("icaoId", ""),
        "原始报文": raw_taf,
        "预报发布时间 (北京时间)": utc_to_beijing(taf.get("issueTime", "")),
        "预报有效期": f"{bj_from} 至 {bj_to}（北京时间）" if bj_from else "",
        "预报期内最高温": max_temp_info,
        "预报期内最低温": min_temp_info,
    }
    return decoded


# ==================== Streamlit UI ====================

st.set_page_config(
    page_title="机场气象报文解码",
    page_icon="🌤️",
    layout="wide"
)

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

# 获取数据
try:
    metar_data = fetch_metar(icao)
    taf_data = fetch_taf(icao)

    col1, col2 = st.columns(2)

    # ===== METAR 卡片 =====
    with col1:
        st.subheader(f"📋 METAR 航空例行天气报告")
        st.code(metar_data["原始报文"], language="text")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("实际气温", metar_data["实际气温"])
        with m2:
            st.metric("露点温度", metar_data["露点温度"])
        with m3:
            st.metric("报文时间", metar_data["报文时间 (北京时间)"][:16])
        with m4:
            change = metar_data["未来2小时变化"]
            delta = "✅" if "无" in change else "⚠️"
            st.metric("未来2小时", change, delta=delta)

    # ===== TAF 卡片 =====
    with col2:
        st.subheader(f"📋 TAF 终端机场天气预报")
        st.code(taf_data["原始报文"], language="text")

        t1, t2 = st.columns(2)
        with t1:
            st.metric("预报发布时间", taf_data["预报发布时间 (北京时间)"][:16])
        with t2:
            st.metric("预报有效期", taf_data["预报有效期"], label_visibility="collapsed")

        st.divider()

        t3, t4 = st.columns(2)
        with t3:
            st.metric("📈 预报期内最高温", taf_data["预报期内最高温"])
        with t4:
            st.metric("📉 预报期内最低温", taf_data["预报期内最低温"])

except requests.exceptions.RequestException as e:
    st.error(f"网络请求失败: {e}")
except json.JSONDecodeError as e:
    st.error(f"数据解析失败: {e}")
except Exception as e:
    st.error(f"发生错误: {e}")

st.divider()
st.caption(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
           f"数据来自 aviationweather.gov")
