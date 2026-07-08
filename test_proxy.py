import requests
import json
import re
import pandas as pd
from io import StringIO
from pathlib import Path

def fetch_consensus_data(symbol: str):
    import urllib3
    urllib3.disable_warnings()
    
    _headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }
    
    base = 'https://navercomp.wisereport.co.kr/v2/company'
    
    try:
        session = requests.Session()
        session.verify = False
        session.headers.update(_headers)
        
        # 프록시 설정 (웹쉐어)
        try:
            CONFIG_PATH = Path('config.json')
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                proxy_cfg = config.get('WEBSHARE_PROXY', {})
                if proxy_cfg.get('enabled') and proxy_cfg.get('username') and proxy_cfg.get('password'):
                    proxy_url = f"http://{proxy_cfg['username']}:{proxy_cfg['password']}@p.webshare.io:80"
                    print(f"Using proxy: {proxy_url}")
                    session.proxies.update({
                        'http': proxy_url,
                        'https': proxy_url
                    })
        except Exception as e:
            print(f"[CONSENSUS] 프록시 설정 로드 실패: {e}")
            
        page_url = f"{base}/c1010001.aspx?cmp_cd={symbol}"
        print(f"Fetching page_url: {page_url}")
        resp = session.get(page_url, timeout=15)
        text = resp.text
        
        enc_match = re.search(r"encparam\s*:\s*'([^']+)'", text)
        id_match = re.search(r"id\s*:\s*'([^']+)'\s*\?", text)
        
        encparam = enc_match.group(1) if enc_match else ''
        id_val = id_match.group(1) if id_match else ''
        
        if not encparam:
            print(f"[CONSENSUS] encparam 추출 실패: {symbol}")
            return None
        
        print(f"encparam: {encparam}, id: {id_val}")
        
        ajax_url = f"{base}/ajax/cF1001.aspx"
        params = {
            'cmp_cd': symbol,
            'fin_typ': '0',
            'freq_typ': 'Y',
            'extY': '3',
            'extQ': '0',
            'encparam': encparam,
            'id': id_val,
        }
        
        ajax_resp = session.get(ajax_url, params=params, headers={
            'Referer': page_url,
            'X-Requested-With': 'XMLHttpRequest',
        }, timeout=15)
        
        if len(ajax_resp.text.strip()) < 10:
            print(f"[CONSENSUS] AJAX 빈 응답: {symbol}")
            return None
            
        dfs = pd.read_html(StringIO(ajax_resp.text), encoding='utf-8')
        print(f"Table extracted! Num tables: {len(dfs)}")
        return "SUCCESS"
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    fetch_consensus_data('000660')
