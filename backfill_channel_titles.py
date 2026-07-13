"""
기존 insights 데이터의 channel_title 컬럼을 채우는 마이그레이션 스크립트.
YouTube oEmbed API를 사용하여 video_id로부터 채널 이름(author_name)을 가져옵니다.

실행 방법:
    python backfill_channel_titles.py

참고:
    - API key가 필요하지 않습니다 (oEmbed는 공개 API)
    - rate limit 방지를 위해 0.5초 간격으로 요청합니다
    - 이미 channel_title이 있는 항목은 건너뜁니다
    - 동일 video_id에 대한 중복 요청을 방지합니다
"""

import sqlite3
import requests
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "insights.db"
OEMBED_URL = "https://www.youtube.com/oembed"


def get_channel_title_from_oembed(video_id: str) -> str | None:
    """YouTube oEmbed API를 사용하여 채널 이름을 가져옵니다."""
    try:
        resp = requests.get(
            OEMBED_URL,
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json"
            },
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("author_name")
        else:
            print(f"  ⚠️ HTTP {resp.status_code} for {video_id}")
            return None
    except Exception as e:
        print(f"  ❌ Error for {video_id}: {e}")
        return None


def backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # channel_title 컬럼이 없으면 추가 (app.py 미실행 상태 대비)
    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN channel_title TEXT")
        conn.commit()
        print("✅ channel_title 컬럼 생성 완료")
    except sqlite3.OperationalError:
        pass  # 이미 존재

    # channel_title이 NULL인 항목의 고유 video_id 목록 조회
    cursor.execute("""
        SELECT DISTINCT video_id 
        FROM insights 
        WHERE channel_title IS NULL
        ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    total = len(rows)

    if total == 0:
        print("✅ 모든 인사이트에 채널 정보가 이미 있습니다!")
        conn.close()
        return

    print(f"📋 채널 정보가 없는 고유 video_id: {total}개")
    print(f"{'='*60}")

    success = 0
    fail = 0

    for i, row in enumerate(rows):
        video_id = row['video_id']
        print(f"[{i+1}/{total}] {video_id} ... ", end="", flush=True)

        channel_title = get_channel_title_from_oembed(video_id)

        if channel_title:
            # 해당 video_id를 가진 모든 insights 업데이트
            cursor.execute(
                "UPDATE insights SET channel_title = ? WHERE video_id = ? AND channel_title IS NULL",
                (channel_title, video_id)
            )
            affected = cursor.rowcount
            conn.commit()
            print(f"✅ {channel_title} ({affected}건 업데이트)")
            success += 1
        else:
            print("⏭️ 건너뜀 (정보 없음)")
            fail += 1

        # rate limit 방지
        time.sleep(0.5)

    conn.close()

    print(f"\n{'='*60}")
    print(f"📊 결과: 성공 {success}개, 실패 {fail}개")
    print(f"✅ 마이그레이션 완료!")


if __name__ == "__main__":
    backfill()
