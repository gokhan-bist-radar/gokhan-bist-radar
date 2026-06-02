from pathlib import Path

v11 = Path("bist_telegram_radar_v11.py")
v12 = Path("bist_telegram_radar_v12.py")

text = v11.read_text(encoding="utf-8")

text = text.replace("Gökhan BIST Radar V11", "Gökhan BIST Radar V12")
text = text.replace(
    "V11 filtre: Para + Kırılım + R/R + Fib/Uyumsuzluk + RS XU100 + negatif uyumsuzluk elemesi",
    "V12 filtre: V11 + RS bonus + para ivmesi + büyük hisse bonusu + R/R tavanı"
)

bonus_func = r'''
def v12_bonus(r):
    bonus = 0
    notes = []

    rs20 = r.get("rs_xu100_20") or 0
    rs60 = r.get("rs_xu100_60") or 0
    money15 = r.get("money_flow_15m") or 0
    money1h = r.get("money_flow_1h") or 0
    money4h = r.get("money_flow_4h") or 0
    symbol = r.get("symbol", "").replace(".IS", "")

    big_names = {
        "ASELS", "EREGL", "THYAO", "TUPRS", "KCHOL", "SAHOL",
        "GARAN", "AKBNK", "YKBNK", "ISCTR", "TOASO", "FROTO",
        "DOAS", "CCOLA", "BIMAS", "MGROS", "ENKAI", "TTKOM",
        "TCELL", "ARCLK", "SISE", "ALARK"
    }

    if rs20 >= 15:
        bonus += 10
        notes.append("RS20 lider bonus")

    if rs60 >= 5:
        bonus += 10
        notes.append("RS60 devam bonus")

    if money15 >= 60:
        bonus += 10
        notes.append("15dk güçlü para bonus")

    if money1h >= 55:
        bonus += 10
        notes.append("1s para bonus")

    if money4h >= 50:
        bonus += 5
        notes.append("4s para destek bonus")

    if r.get("daily_support") or r.get("daily_support_ok"):
        bonus += 5
        notes.append("günlük destek bonus")

    if symbol in big_names:
        bonus += 5
        notes.append("büyük hisse bonus")

    rr = r.get("risk_reward")
    if rr is not None and rr > 10:
        r["risk_reward"] = 10
        notes.append("R/R üst sınırlandı")

    r["v12_bonus"] = bonus
    r["v12_notes"] = notes
    r["score"] = (r.get("score", 0) or 0) + bonus
    return r
'''

marker = "results = sorted(results,"
text = text.replace(marker, bonus_func + "\n\nresults = [v12_bonus(r) for r in results]\n" + marker)

text = text.replace(
    "f\"• {r['symbol']} skor {r['score']}\"",
    "f\"• {r['symbol']} skor {r['score']} | V12 bonus {r.get('v12_bonus', 0)}\""
)

v12.write_text(text, encoding="utf-8")
print("✅ bist_telegram_radar_v12.py oluşturuldu.")