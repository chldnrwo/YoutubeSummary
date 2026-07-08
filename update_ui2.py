import re

def main():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 주식 탭(DAILY) 관심 종목 목록 렌더링 수정
    daily_render_block = """
            def render_daily_stock(stock):
                col_name, col_info, col_fetch, col_del = st.columns([3, 2, 1, 1])
                with col_name:
                    st.markdown(f"**{stock['name']}** (`{stock['symbol']}`)")
                with col_info:
                    last_date = stock['last_date'] or '-'
                    data_count = stock['data_count'] or 0
                    st.caption(f"최근: {last_date} | {data_count}건")
                with col_fetch:
                    if st.button("📥", key=f"fetch_{stock['id']}", help="수동 수집"):
                        with st.spinner(f"📥 {stock['name']} 데이터 수집 중..."):
                            name, records = fetch_stock_data(stock['symbol'], pages=25)
                            if records:
                                inserted = save_daily_prices_bulk(stock['id'], records)
                                st.toast(f"✅ {stock['name']}: {len(records)}건 수집 완료!", icon="📈")
                            else:
                                st.toast(f"⚠️ {stock['name']}: 수집된 데이터가 없습니다.", icon="⚠️")
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_stock_{stock['id']}", help="종목 삭제"):
                        delete_stock(stock['id'])
                        st.toast(f"🗑️ {stock['name']} 삭제 완료", icon="🗑️")
                        st.rerun()
            
            render_watched_stocks_grouped(watched, render_daily_stock, 'daily_list')
"""

    # 정규식이나 replace 로 교체. 기존 루프문을 덮어씀.
    # 기존 코드:
    # for stock in watched:
    #    col_name, ...
    #    ...
    #    st.rerun()
    # (st.markdown("---") 직전까지)
    
    daily_pattern = r"(for stock in watched:.*?)(?=        st\.markdown\(\"---\"\)\n        \n        # 데이터 조회 영역)"
    content = re.sub(daily_pattern, daily_render_block, content, flags=re.DOTALL)

    # 컨센서스 탭 종목 렌더링 수정
    cons_render_block = """
            def render_cons_stock(stock):
                col_name, col_info, col_fetch, col_del = st.columns([3, 2, 1, 1])
                with col_name:
                    st.markdown(f"**{stock['name']}** (`{stock['symbol']}`)")
                with col_info:
                    last_date = stock['last_date'] or '-'
                    data_count = stock['data_count'] or 0
                    st.caption(f"최근: {last_date} | {data_count}건")
                with col_fetch:
                    if st.button("📥", key=f"fetch_cons_{stock['id']}", help="수동 수집"):
                        with st.spinner(f"📥 {stock['name']} 수집 중..."):
                            result = fetch_consensus_data(stock['symbol'])
                            if result:
                                save_consensus_data(stock['id'], result)
                                st.toast(f"✅ {stock['name']} 컨센서스 수집 완료!", icon="📈")
                            else:
                                st.toast(f"⚠️ {stock['name']} 데이터를 가져올 수 없습니다.", icon="⚠️")
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_cons_{stock['id']}", help="종목 삭제"):
                        delete_stock(stock['id'])
                        st.toast(f"🗑️ {stock['name']} 삭제 완료", icon="🗑️")
                        st.rerun()
                        
            render_watched_stocks_grouped(watched_for_consensus, render_cons_stock, 'cons_list')
"""
    
    cons_pattern = r"(for stock in watched_for_consensus:.*?)(?=        st\.markdown\(\"---\"\)\n        \n        st\.subheader\(\"📊 수집된 컨센서스 데이터 조회\"\))"
    
    # 하지만 fetch_consensus_btn (전체 수집 버튼 로직) 이 for 루프 위에 있음.
    # fetch_consensus_btn 동작 후에는 기존의 일렬 루프가 있었고, 그 밑에 개별 종목 렌더링 루프가 있음.
    # 안전하게 2980 라인 주변의 "for stock in watched_for_consensus:" 개별 렌더링 루프만 찾아 교체.
    cons_individual_loop = r"(for stock in watched_for_consensus:\n                col_name, col_info, col_fetch, col_del = st\.columns.*?\n                        st\.rerun\(\))"
    content = re.sub(cons_individual_loop, cons_render_block, content, flags=re.DOTALL)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print("UI 코드 2차 인젝션 성공")

if __name__ == '__main__':
    main()
