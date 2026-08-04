"""
backfill_wiki.py — 기존 인사이트 데이터에서 위키 엔터티·주장을 추출하는 백필 스크립트

사용법:
    python backfill_wiki.py                    # 미처리 항목 전체
    python backfill_wiki.py --limit 30         # 30건만 (테스트용)
    python backfill_wiki.py --retry-failed     # 실패한 항목 재시도
    python backfill_wiki.py --reextract        # 구버전 항목 재추출
"""

import sqlite3
import json
import time
import sys
import io
import argparse
from pathlib import Path

# Windows 콘솔 인코딩 문제 해결
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


from wiki import extract_wiki_data, init_wiki_tables, CURRENT_EXTRACTION_VERSION

BASE_PATH = Path(__file__).parent
DB_PATH = str(BASE_PATH / "insights.db")
CONFIG_PATH = BASE_PATH / "config.json"


def get_api_key():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('GOOGLE_API_KEY', '')
    return ''


def get_targets(conn, user_id: int, mode: str, limit: int = None):
    """처리 대상 인사이트 ID 목록을 반환합니다."""
    if mode == 'pending':
        query = """
            SELECT id FROM insights
            WHERE user_id = ? AND (wiki_extracted = 0 OR wiki_extracted IS NULL)
            ORDER BY created_at DESC
        """
    elif mode == 'failed':
        query = """
            SELECT id FROM insights
            WHERE user_id = ? AND wiki_extracted = -1
            ORDER BY created_at DESC
        """
    elif mode == 'reextract':
        query = f"""
            SELECT id FROM insights
            WHERE user_id = ? AND wiki_extracted = 1
              AND wiki_extraction_version < {CURRENT_EXTRACTION_VERSION}
            ORDER BY created_at DESC
        """
    else:
        query = """
            SELECT id FROM insights
            WHERE user_id = ? AND (wiki_extracted != 1 OR wiki_extracted IS NULL)
            ORDER BY created_at DESC
        """

    params = [user_id]
    if limit:
        query += f" LIMIT {limit}"

    return [r[0] for r in conn.execute(query, params).fetchall()]


def main():
    parser = argparse.ArgumentParser(description='위키 백필 스크립트')
    parser.add_argument('--limit', type=int, default=None, help='처리할 최대 건수')
    parser.add_argument('--retry-failed', action='store_true', help='실패한 항목만 재시도')
    parser.add_argument('--reextract', action='store_true', help='구버전 추출 결과 재처리')
    parser.add_argument('--user-id', type=int, default=None, help='사용자 ID (기본: 첫 번째 사용자)')
    parser.add_argument('--delay', type=float, default=1.0, help='요청 간 대기 시간(초)')
    args = parser.parse_args()

    # DB 초기화
    init_wiki_tables(DB_PATH)

    api_key = get_api_key()
    if not api_key:
        print("❌ config.json에서 GOOGLE_API_KEY를 찾을 수 없습니다.")
        return

    conn = sqlite3.connect(DB_PATH)

    # 사용자 ID 결정
    if args.user_id:
        user_id = args.user_id
    else:
        row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        if not row:
            print("❌ users 테이블에 사용자가 없습니다.")
            conn.close()
            return
        user_id = row[0]

    print(f"📌 사용자 ID: {user_id}")
    print(f"📌 추출 버전: {CURRENT_EXTRACTION_VERSION}")

    # 모드 결정
    if args.retry_failed:
        mode = 'failed'
    elif args.reextract:
        mode = 'reextract'
    else:
        mode = 'pending'

    targets = get_targets(conn, user_id, mode, args.limit)
    conn.close()

    if not targets:
        print("✅ 처리할 항목이 없습니다.")
        return

    print(f"📋 처리 대상: {len(targets)}건 (모드: {mode})")
    print(f"⏱️  예상 시간: ~{len(targets) * args.delay / 60:.1f}분")
    print()

    # 처리
    success = 0
    failed = 0
    total_tokens_in = 0
    total_tokens_out = 0
    start_time = time.time()

    for i, insight_id in enumerate(targets):
        try:
            t0 = time.time()
            extract_wiki_data(DB_PATH, insight_id, api_key, user_id)
            elapsed = time.time() - t0

            success += 1
            status = "✅"
            print(f"  {status} [{i+1}/{len(targets)}] insight_id={insight_id} ({elapsed:.1f}s)")

        except Exception as e:
            failed += 1
            status = "❌"
            err_msg = str(e)[:80]
            print(f"  {status} [{i+1}/{len(targets)}] insight_id={insight_id} — {err_msg}")

        # 진행률
        if (i + 1) % 10 == 0:
            elapsed_total = time.time() - start_time
            rate = (i + 1) / elapsed_total
            remaining = (len(targets) - i - 1) / rate if rate > 0 else 0
            print(f"  📊 진행: {i+1}/{len(targets)} | 성공: {success} | 실패: {failed} | 남은 시간: ~{remaining/60:.1f}분")

        # Rate limiting
        if i < len(targets) - 1:
            time.sleep(args.delay)

    # 결과 요약
    elapsed_total = time.time() - start_time
    print()
    print("=" * 50)
    print(f"📊 백필 완료")
    print(f"  총 처리: {len(targets)}건")
    print(f"  성공: {success}건")
    print(f"  실패: {failed}건")
    print(f"  소요 시간: {elapsed_total/60:.1f}분")
    print(f"  평균 처리 시간: {elapsed_total/len(targets):.1f}초/건")

    if failed > 0:
        print(f"\n💡 실패한 항목은 --retry-failed 옵션으로 재시도할 수 있습니다.")


if __name__ == '__main__':
    main()
