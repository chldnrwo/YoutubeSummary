import sqlite3
import chromadb
from pathlib import Path
from tqdm import tqdm

DB_PATH = Path("insights.db")
CHROMA_PATH = Path("chroma_db")

def sync_all_entities():
    print(f"[{DB_PATH}] SQLite DB에서 엔터티를 읽어옵니다...")
    
    if not DB_PATH.exists():
        print("에러: insights.db 파일이 없습니다.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 전체 엔터티 조회
    entities = conn.execute("SELECT id, name, description, entity_type FROM wiki_entities").fetchall()
    
    # 전체 별칭 조회 (메모리에 미리 캐싱)
    aliases_rows = conn.execute("SELECT entity_id, alias FROM wiki_entity_aliases").fetchall()
    aliases_map = {}
    for r in aliases_rows:
        eid = r['entity_id']
        if eid not in aliases_map:
            aliases_map[eid] = []
        aliases_map[eid].append(r['alias'])
        
    conn.close()

    total = len(entities)
    print(f"총 {total}개의 엔터티를 찾았습니다. ChromaDB에 동기화를 시작합니다.")

    if total == 0:
        return

    # ChromaDB 연결
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = chroma_client.get_or_create_collection(name="wiki_entities")

    # 배치 단위로 처리
    BATCH_SIZE = 100
    
    for i in tqdm(range(0, total, BATCH_SIZE), desc="ChromaDB 동기화"):
        batch = entities[i:i+BATCH_SIZE]
        
        ids = []
        documents = []
        metadatas = []
        
        for ent in batch:
            eid = ent['id']
            name = ent['name']
            desc = ent['description']
            etype = ent['entity_type']
            
            ent_aliases = aliases_map.get(eid, [])
            alias_str = ", ".join(ent_aliases) if ent_aliases else ""
            
            text_for_embedding = f"이름: {name}"
            if alias_str:
                text_for_embedding += f"\n별칭: {alias_str}"
            if desc:
                text_for_embedding += f"\n설명: {desc}"
                
            ids.append(str(eid))
            documents.append(text_for_embedding)
            metadatas.append({"name": name, "type": etype})
            
        try:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
        except Exception as e:
            print(f"\n배치 Upsert 에러 (Index {i}): {e}")

    print("\n✅ 동기화 완료!")

if __name__ == "__main__":
    sync_all_entities()
