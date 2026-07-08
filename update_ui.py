import re

def main():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. 헬퍼 함수 추가 (delete_stock 아래에)
    helper_code = """
def render_group_management(user_id: int, stock_type: str, prefix: str):
    import streamlit as st
    groups = get_groups(user_id, stock_type)
    
    with st.expander("📂 그룹 관리 (추가/삭제)"):
        col1, col2 = st.columns([3, 1])
        with col1:
            new_group_name = st.text_input("새 그룹 이름", key=f"new_group_{prefix}", label_visibility="collapsed", placeholder="새 그룹 이름")
        with col2:
            if st.button("추가", key=f"add_group_{prefix}", use_container_width=True):
                if new_group_name:
                    create_group(user_id, new_group_name, stock_type)
                    st.success("그룹 생성 완료")
                    st.rerun()
                    
        if groups:
            st.markdown("---")
            for g in groups:
                col_n, col_d = st.columns([4, 1])
                col_n.markdown(f"**{g['name']}**")
                if col_d.button("삭제", key=f"del_group_{prefix}_{g['id']}", use_container_width=True):
                    delete_group(g['id'])
                    st.warning("그룹 삭제 완료")
                    st.rerun()
    return groups

def render_watched_stocks_grouped(watched_list, render_item_func, prefix):
    import streamlit as st
    if not watched_list:
        st.info("📭 관심 종목을 등록해주세요.")
        return
        
    # 그룹별 분류
    from collections import defaultdict
    grouped = defaultdict(list)
    for s in watched_list:
        gname = s['group_name'] if s['group_name'] else "미지정"
        grouped[gname].append(s)
        
    for gname, stocks in grouped.items():
        with st.expander(f"📁 {gname} ({len(stocks)}종목)", expanded=True):
            for stock in stocks:
                render_item_func(stock)
                st.markdown("---")
"""
    if "def render_group_management" not in content:
        content = content.replace("def delete_stock(stock_id: int):", helper_code + "\ndef delete_stock(stock_id: int):")

    # 2. Daily 종목 추가 쪽에 그룹 선택기 주입
    daily_search_block = """
        # 종목 추가 영역
        st.subheader("➕ 종목 추가")
        
        daily_groups = render_group_management(user_id, 'DAILY', 'daily')
        
        group_options = {"미지정 (기본)": None}
        for g in daily_groups: group_options[g['name']] = g['id']
        selected_daily_group_name = st.selectbox("추가할 그룹 선택", list(group_options.keys()), key="sel_g_daily")
        sel_g_daily_id = group_options[selected_daily_group_name]
        
        search_query = st.text_input(
"""
    content = content.replace("""
        # 종목 추가 영역
        st.subheader("➕ 종목 추가")
        
        search_query = st.text_input(""", daily_search_block)

    # get_or_create_stock 호출부 수정 (DAILY)
    content = content.replace("get_or_create_stock(query, name, user_id=user_id)", "get_or_create_stock(query, name, user_id=user_id, group_id=sel_g_daily_id)")
    content = content.replace("get_or_create_stock(r['symbol'], r['name'], user_id=user_id)", "get_or_create_stock(r['symbol'], r['name'], user_id=user_id, group_id=sel_g_daily_id)")

    # 3. Consensus 종목 추가 쪽에 그룹 선택기 주입
    consensus_search_block = """
        # 종목 추가 섹션 (컨센서스 전용)
        st.subheader("🔍 종목 추가 (컨센서스용)")
        
        cons_groups = render_group_management(user_id, 'CONSENSUS', 'cons')
        
        c_group_options = {"미지정 (기본)": None}
        for g in cons_groups: c_group_options[g['name']] = g['id']
        selected_cons_group_name = st.selectbox("추가할 그룹 선택", list(c_group_options.keys()), key="sel_g_cons")
        sel_g_cons_id = c_group_options[selected_cons_group_name]
        
        query = st.text_input("종목명 또는 종목코드 6자리 입력", placeholder="예: 삼성전자, 005930", key="consensus_search_input")
"""
    content = content.replace("""
        # 종목 추가 섹션 (컨센서스 전용)
        st.subheader("🔍 종목 추가 (컨센서스용)")
        query = st.text_input("종목명 또는 종목코드 6자리 입력", placeholder="예: 삼성전자, 005930", key="consensus_search_input")""", consensus_search_block)

    # get_or_create_stock 호출부 수정 (CONSENSUS)
    content = content.replace("get_or_create_stock(query, name, user_id=user_id, stock_type='CONSENSUS')", "get_or_create_stock(query, name, user_id=user_id, stock_type='CONSENSUS', group_id=sel_g_cons_id)")
    content = content.replace("get_or_create_stock(r['symbol'], r['name'], user_id=user_id, stock_type='CONSENSUS')", "get_or_create_stock(r['symbol'], r['name'], user_id=user_id, stock_type='CONSENSUS', group_id=sel_g_cons_id)")

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("UI 코드 1차 인젝션 성공")

if __name__ == '__main__':
    main()
