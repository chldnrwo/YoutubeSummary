import re

def main():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 교체할 원본 패턴: "# 데이터 요약" 부터 "st.info("📭 수집된 데이터가 없습니다...)" 까지.
    # 안전하게 정규식을 위해 전체를 하드코딩하기보다, 특정 블럭을 찾아 교체합니다.
    
    target_pattern = r"(# 데이터 요약\s+summary = get_all_consensus_summary\(user_id=user_id\).*?)(?=\s+elif selected_menu == \"📰 내 신문\":)"
    
    new_block = """# 데이터 요약
            summary = get_all_consensus_summary(user_id=user_id)
            
            # watched_for_consensus (리스트 안의 sqlite3.Row 객체)를 활용해 
            # stock_id 별로 group_name을 매핑할 수 있는 딕셔너리 생성
            group_map = {}
            for s in watched_for_consensus:
                group_map[s['id']] = s['group_name'] if s['group_name'] else "미지정 (기본)"
                
            consensus_stock_ids = list(group_map.keys())
            filtered_summary = [row for row in summary if row['stock_id'] in consensus_stock_ids]
            
            has_data = any(row['y2026'] is not None for row in filtered_summary)
            
            if has_data:
                def fmt_val(v):
                    if v is None: return "-"
                    v = float(v)
                    if abs(v) >= 10000: return f"{v/10000:,.1f}조"
                    else: return f"{v:,.0f}억"
                
                def calc_yoy(cur, prev):
                    if cur is None or prev is None or prev == 0: return "-"
                    rate = (float(cur) - float(prev)) / abs(float(prev)) * 100
                    sign = "+" if rate > 0 else ""
                    return f"{sign}{rate:.1f}%"
                
                # 정렬 옵션 확장
                sort_options = {
                    "종목명순": "name",
                    "26년 영업이익 높은순": "y2026_desc",
                    "27년 영업이익 높은순": "y2027_desc",
                    "28년 영업이익 높은순": "y2028_desc",
                    "27년 YoY 성장률 높은순": "yoy27_desc",
                    "28년 YoY 성장률 높은순": "yoy28_desc",
                }
                sort_key = st.selectbox(
                    "정렬 기준 (그룹 내 정렬)",
                    options=list(sort_options.keys()),
                    key="consensus_sort"
                )
                
                # 딕셔너리로 행(row) 변환 및 group_name 추가
                summary_list = []
                for row in filtered_summary:
                    r_dict = dict(row)
                    r_dict['group_name'] = group_map.get(row['stock_id'], "미지정 (기본)")
                    summary_list.append(r_dict)
                
                # 그룹별로 분리
                from collections import defaultdict
                grouped_data = defaultdict(list)
                for r in summary_list:
                    if r['y2026'] is not None or r['y2027'] is not None:
                        grouped_data[r['group_name']].append(r)
                
                # 정렬용 헬퍼 함수
                def _get_yoy(x, cur_yr, prev_yr):
                    if x[cur_yr] and x[prev_yr] and x[prev_yr] != 0:
                        return (x[cur_yr] - x[prev_yr]) / abs(x[prev_yr])
                    return -999999
                
                csv_header = "그룹명,종목코드,종목명,26년(E),27년(E),28년(E),YoY_26_27,YoY_27_28"
                csv_body = []
                
                # 그룹명을 알파벳/가나다 순으로 먼저 정렬해서 화면에 표시
                for g_name in sorted(grouped_data.keys()):
                    g_list = grouped_data[g_name]
                    
                    # 사용자가 선택한 기준으로 '그룹 내부' 정렬
                    sk = sort_options[sort_key]
                    if sk == "y2026_desc":
                        g_list.sort(key=lambda x: x['y2026'] or -999999, reverse=True)
                    elif sk == "y2027_desc":
                        g_list.sort(key=lambda x: x['y2027'] or -999999, reverse=True)
                    elif sk == "y2028_desc":
                        g_list.sort(key=lambda x: x['y2028'] or -999999, reverse=True)
                    elif sk == "yoy27_desc":
                        g_list.sort(key=lambda x: _get_yoy(x, 'y2027', 'y2026'), reverse=True)
                    elif sk == "yoy28_desc":
                        g_list.sort(key=lambda x: _get_yoy(x, 'y2028', 'y2027'), reverse=True)
                    else:
                        g_list.sort(key=lambda x: x['name'])
                    
                    st.markdown(f"#### 📁 {g_name} ({len(g_list)}종목)")
                    
                    table_rows = []
                    for row in g_list:
                        table_rows.append({
                            "종목": f"{row['name']} ({row['symbol']})",
                            "26년(E)": fmt_val(row['y2026']),
                            "27년(E)": fmt_val(row['y2027']),
                            "28년(E)": fmt_val(row['y2028']),
                            "YoY 26→27": calc_yoy(row['y2027'], row['y2026']),
                            "YoY 27→28": calc_yoy(row['y2028'], row['y2027']),
                            "수집일": row['updated_at'][:10] if row['updated_at'] else "-",
                        })
                        
                        # CSV 데이터 누적
                        yoy27 = calc_yoy(row['y2027'], row['y2026'])
                        yoy28 = calc_yoy(row['y2028'], row['y2027'])
                        csv_body.append(
                            f"{g_name},{row['symbol']},{row['name']},{row['y2026'] or ''},{row['y2027'] or ''},{row['y2028'] or ''},{yoy27},{yoy28}"
                        )
                    
                    st.dataframe(table_rows, use_container_width=True, hide_index=True)
                    st.markdown("<br>", unsafe_allow_html=True)
                
                consensus_csv = csv_header + "\\n" + "\\n".join(csv_body)
                st.download_button(
                    label="📄 컨센서스 전체 CSV 다운로드",
                    data=consensus_csv,
                    file_name="consensus_operating_profit_grouped.csv",
                    mime="text/csv",
                    key="consensus_csv_download"
                )
            else:
                st.info("📭 수집된 데이터가 없습니다. 위의 **📥 전체 수집 및 갱신** 버튼을 눌러주세요.")
"""
    
    new_content, count = re.subn(target_pattern, new_block, content, flags=re.DOTALL)
    
    if count == 0:
        print("정규식 매칭 실패. 코드를 덮어쓰지 않았습니다.")
    else:
        with open('app.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("UI 표 렌더링 코드 인젝션 성공")

if __name__ == '__main__':
    main()
