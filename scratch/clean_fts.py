import sqlite3

def clean_fts():
    conn = sqlite3.connect('insights.db')
    cursor = conn.cursor()
    
    # Drop main FTS tables
    for table in ['insights_fts', 'claims_fts', 'entities_fts']:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
            print(f"Dropped {table}")
        except Exception as e:
            print(f"Error dropping {table}: {e}")
            
    # Try to drop shadow tables just in case (normally not allowed directly, but if corrupted it might be stuck)
    # Actually SQLite might throw an error if we try to drop shadow tables directly. 
    # Let's run VACUUM.
    try:
        conn.execute("VACUUM")
        print("VACUUM completed.")
    except Exception as e:
        print(f"VACUUM error: {e}")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    clean_fts()
